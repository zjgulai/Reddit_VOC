#!/usr/bin/env python3
"""Build a resumable DeepSeek translation sidecar for a V3 public snapshot.

The command is intentionally local-only.  It may call DeepSeek only when both
``--authorize-provider-call`` and a non-empty ``DEEPSEEK_API_KEY`` are present.
It never writes a database, remote host, live pointer, or message channel.

Successful translations are appended to a source-bound checkpoint after every
provider response.  Re-running the command reuses those rows and continues from
the exact remaining item.  A completed run copies the immutable source public
snapshot into a new dataset version and adds two hash-bound sidecars:
``post-translations-public.json`` and ``comment-translations-public.json``.
"""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import threading
import time
from typing import Any, Callable, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from reddit_voc.deepseek_client import (  # noqa: E402
    DEEPSEEK_MODEL,
    DeepSeekClient,
)
from reddit_voc.report_contracts import (  # noqa: E402
    AttemptBudget,
    MonotonicDeadline,
    TokenUsage,
    canonical_json_bytes,
    sha256_hex,
)
from reddit_voc.translation_pipeline import (  # noqa: E402
    PostTranslationBundle,
    TranslationItem,
    _protect_translation_text,
    _restore_protected_translations,
    _source_equal_allowed,
    load_translation_runtime_assets,
    parse_translation_content,
    translation_output_sha256,
    validate_deterministic_translation,
)


TRANSLATION_SCHEMA = "reddit_voc_public_translations_v1"
CHECKPOINT_SCHEMA = "reddit_voc_translation_checkpoint_row_v1"
RUN_RECEIPT_SCHEMA = "reddit_voc_translation_provider_run_receipt_v1"
MANIFEST_EXTENSION_SCHEMA = "reddit_voc_translation_extension_v1"
SAFE_ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_-")
SIDE_CAR_NAMES = (
    "post-translations-public.json",
    "comment-translations-public.json",
)


class TranslationCandidateError(ValueError):
    """The translation candidate cannot advance safely."""


class ProviderBatchValidationError(TranslationCandidateError):
    def __init__(
        self,
        reason_code: str,
        *,
        completion: object,
        batch_stable_ids: tuple[str, ...],
        failed_stable_ids: tuple[str, ...],
        failed_error_codes: Mapping[str, Sequence[str]] | None = None,
        accepted_translations: Mapping[str, str] | None = None,
    ) -> None:
        self.reason_code = reason_code
        self.completion = completion
        self.batch_stable_ids = batch_stable_ids
        self.failed_stable_ids = failed_stable_ids
        self.failed_error_codes = {
            stable_id: tuple(str(code) for code in codes)
            for stable_id, codes in (failed_error_codes or {}).items()
        }
        self.accepted_translations = dict(accepted_translations or {})
        super().__init__(reason_code)


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, *, expected_type: type) -> Any:
    if path.is_symlink() or not path.is_file():
        raise TranslationCandidateError(f"unsafe_or_missing_json:{path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TranslationCandidateError(f"invalid_json:{path.name}") from exc
    if not isinstance(value, expected_type):
        raise TranslationCandidateError(f"invalid_json_shape:{path.name}")
    return value


def _write_json(path: Path, value: object) -> None:
    if path.exists() or path.is_symlink():
        raise TranslationCandidateError(f"output_collision:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"
    path.write_text(payload, encoding="utf-8")


def _append_jsonl(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(value) + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    descriptor = os.open(path, flags, 0o600)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _assert_private_regular_file(path: Path, *, label: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise TranslationCandidateError(f"{label}_unreadable") from exc
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise TranslationCandidateError(f"{label}_unsafe")
    if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
        raise TranslationCandidateError(f"{label}_permissions_unsafe")


def _load_api_key(api_key_file: Path | None) -> str:
    environment_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if api_key_file is None:
        return environment_key
    if environment_key:
        raise TranslationCandidateError("deepseek_credential_source_ambiguous")
    _assert_private_regular_file(api_key_file, label="deepseek_credential_file")
    try:
        size = api_key_file.stat().st_size
        if not 1 <= size <= 4096:
            raise TranslationCandidateError("deepseek_credential_file_size_invalid")
        credential = api_key_file.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise TranslationCandidateError("deepseek_credential_file_unreadable") from exc
    if not credential or "\n" in credential or "\r" in credential:
        raise TranslationCandidateError("deepseek_credential_file_invalid")
    return credential


def _safe_identifier(value: str, *, label: str, prefix: str = "") -> str:
    if (
        not isinstance(value, str)
        or not 3 <= len(value) <= 128
        or (prefix and not value.startswith(prefix))
        or any(character not in SAFE_ID_CHARS for character in value)
    ):
        raise TranslationCandidateError(f"invalid_{label}")
    return value


def _normalized_source(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TranslationCandidateError("source_text_not_string")
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _translation_item(
    *,
    stable_id: str,
    item_type: str,
    post_id: str,
    comment_id: str | None,
    source: object,
) -> TranslationItem:
    source_text = _normalized_source(source)
    return TranslationItem(
        stable_id=stable_id,
        item_type=item_type,  # type: ignore[arg-type]
        post_id=post_id,
        comment_id=comment_id,
        source_text=source_text,
        input_sha256=sha256_hex(source_text.encode("utf-8")),
    )


def build_translation_items(
    posts: Sequence[Mapping[str, object]],
    comments: Sequence[Mapping[str, object]],
    *,
    include_comments: bool,
) -> tuple[TranslationItem, ...]:
    items: list[TranslationItem] = []
    post_ids: set[str] = set()
    for post in posts:
        post_id = post.get("post_id")
        if not isinstance(post_id, str) or not post_id or post_id in post_ids:
            raise TranslationCandidateError("post_identity_invalid")
        post_ids.add(post_id)
        items.extend(
            (
                _translation_item(
                    stable_id=f"post:{post_id}:title",
                    item_type="title",
                    post_id=post_id,
                    comment_id=None,
                    source=post.get("title"),
                ),
                _translation_item(
                    stable_id=f"post:{post_id}:content",
                    item_type="body",
                    post_id=post_id,
                    comment_id=None,
                    source=post.get("content"),
                ),
            )
        )
    if include_comments:
        comment_ids: set[str] = set()
        for comment in comments:
            comment_id = comment.get("comment_id")
            post_id = comment.get("post_id")
            if (
                not isinstance(comment_id, str)
                or not comment_id
                or comment_id in comment_ids
                or not isinstance(post_id, str)
                or post_id not in post_ids
            ):
                raise TranslationCandidateError("comment_identity_invalid")
            comment_ids.add(comment_id)
            items.append(
                _translation_item(
                    stable_id=f"comment:{comment_id}:body",
                    item_type="comment",
                    post_id=post_id,
                    comment_id=comment_id,
                    source=comment.get("body"),
                )
            )
    stable_ids = [item.stable_id for item in items]
    if len(stable_ids) != len(set(stable_ids)):
        raise TranslationCandidateError("duplicate_translation_identity")
    return tuple(items)


def _load_checkpoint(
    path: Path,
    *,
    source_manifest_sha256: str,
    item_by_id: Mapping[str, TranslationItem],
    translation_prompt_sha256: str,
    translation_terms_sha256: str,
) -> dict[str, str]:
    if not path.exists():
        return {}
    if path.is_symlink() or not path.is_file():
        raise TranslationCandidateError("checkpoint_unsafe")
    _assert_private_regular_file(path, label="checkpoint")
    translations: dict[str, str] = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TranslationCandidateError(f"checkpoint_invalid_json:{line_number}") from exc
        if not isinstance(row, dict) or row.get("schema_version") != CHECKPOINT_SCHEMA:
            raise TranslationCandidateError(f"checkpoint_schema_invalid:{line_number}")
        stable_id = row.get("stable_id")
        if not isinstance(stable_id, str) or stable_id not in item_by_id:
            raise TranslationCandidateError(f"checkpoint_identity_invalid:{line_number}")
        if stable_id in translations:
            raise TranslationCandidateError(f"checkpoint_duplicate_identity:{line_number}")
        item = item_by_id[stable_id]
        zh = row.get("zh")
        legacy_empty_row = (
            not item.source_text
            and zh == ""
            and row.get("provider_attempt_sequence") is None
            and "translation_prompt_sha256" not in row
            and "translation_terms_sha256" not in row
            and "provider_response_id" not in row
            and "provider_output_sha256" not in row
        )
        prompt_binding_valid = legacy_empty_row or (
            row.get("translation_prompt_sha256") == translation_prompt_sha256
            and row.get("translation_terms_sha256") == translation_terms_sha256
        )
        attempt_sequence = row.get("provider_attempt_sequence")
        attempt_binding_valid = (
            (
                not item.source_text
                and zh == ""
                and attempt_sequence is None
                and row.get("provider_response_id") is None
                and row.get("provider_output_sha256") is None
            )
            or (
                bool(item.source_text)
                and isinstance(attempt_sequence, int)
                and not isinstance(attempt_sequence, bool)
                and attempt_sequence >= 1
                and isinstance(row.get("provider_response_id"), str)
                and bool(row["provider_response_id"])
                and isinstance(row.get("provider_output_sha256"), str)
                and len(row["provider_output_sha256"]) == 64
            )
        )
        if (
            row.get("source_manifest_sha256") != source_manifest_sha256
            or row.get("input_sha256") != item.input_sha256
            or row.get("post_id") != item.post_id
            or row.get("comment_id") != item.comment_id
            or row.get("item_type") != item.item_type
            or row.get("provider") != "deepseek"
            or row.get("model") != DEEPSEEK_MODEL
            or not isinstance(zh, str)
            or not prompt_binding_valid
            or not attempt_binding_valid
        ):
            raise TranslationCandidateError(f"checkpoint_binding_invalid:{line_number}")
        translations[stable_id] = str(zh)
    return translations


def _validate_translation_map(
    *,
    items: Sequence[TranslationItem],
    translations: Mapping[str, str],
    terms,
) -> None:
    translated_items = [item for item in items if item.stable_id in translations]
    for offset in range(0, len(translated_items), 256):
        chunk = tuple(translated_items[offset : offset + 256])
        if not chunk:
            continue
        bundle = PostTranslationBundle(post_id=f"checkpoint-{offset}", items=chunk)
        try:
            validate_deterministic_translation(
                bundle,
                {item.stable_id: translations[item.stable_id] for item in chunk},
                terms,
            )
        except Exception as exc:
            reason_code = getattr(exc, "reason_code", type(exc).__name__)
            raise TranslationCandidateError(
                f"checkpoint_deterministic_validation_failed:{reason_code}"
            ) from exc


def _batches(
    items: Sequence[TranslationItem],
    *,
    max_items: int,
    max_source_chars: int,
) -> Iterable[tuple[TranslationItem, ...]]:
    batch: list[TranslationItem] = []
    character_count = 0
    for item in items:
        item_characters = len(item.source_text)
        if item_characters > max_source_chars:
            if batch:
                yield tuple(batch)
                batch = []
                character_count = 0
            yield (item,)
            continue
        if batch and (
            len(batch) >= max_items
            or character_count + item_characters > max_source_chars
        ):
            yield tuple(batch)
            batch = []
            character_count = 0
        batch.append(item)
        character_count += item_characters
    if batch:
        yield tuple(batch)


def _usage_document(usage: TokenUsage) -> dict[str, int]:
    return {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "prompt_cache_hit_tokens": usage.prompt_cache_hit_tokens,
        "prompt_cache_miss_tokens": usage.prompt_cache_miss_tokens,
        "total_tokens": usage.total_tokens,
    }


def _add_usage(left: dict[str, int], right: TokenUsage) -> None:
    for key, value in _usage_document(right).items():
        left[key] += value


def _is_reddit_unavailable_placeholder(item: TranslationItem) -> bool:
    return item.source_text.strip().casefold() in {"[removed]", "[deleted]"}


def _reddit_unavailable_placeholder_translation_source(item: TranslationItem) -> str:
    status = item.source_text.strip()[1:-1].casefold()
    return f"This Reddit content was {status}."


def _source_equal_retry_override(item: TranslationItem) -> str | None:
    if _is_reddit_unavailable_placeholder(item):
        return _reddit_unavailable_placeholder_translation_source(item)
    expanded = re.sub(
        r"\bwtf\b",
        "what the fuck",
        item.source_text,
        flags=re.IGNORECASE,
    )
    expanded = re.sub(
        r"\bvs\.?\b",
        "compared with",
        expanded,
        flags=re.IGNORECASE,
    )
    expanded = re.sub(
        r"\bdeluxe\b",
        "premium version",
        expanded,
        flags=re.IGNORECASE,
    )
    if expanded.strip().casefold() == "pjs":
        expanded = "pajamas"
    if expanded.strip().casefold() == "bogos binted?":
        expanded = "Have the photos been printed?"
    if expanded.strip().casefold() == "the titsoon?":
        expanded = "The Black person?"
    if re.fullmatch(r"\s*Prime day\s*", expanded, flags=re.IGNORECASE):
        expanded = "Amazon Prime Day shopping event"
    if expanded.strip().casefold() == "theetta case aanallo..":
        expanded = (
            "Translate this Malayalam transliteration into Simplified Chinese: "
            f"{item.source_text}"
        )
    if expanded.strip().casefold() == "la jax, esta divina":
        expanded = (
            "Translate this Spanish text into Simplified Chinese: "
            f"{item.source_text}"
        )
    italian_meaning = {
        "come si può sostituire il plumbus?": "How can the Plumbus be replaced?",
        "puppe strizzate al largo dei bastioni di orione": (
            "Squeezed breasts off the shoulder of Orion."
        ),
    }.get(expanded.strip().casefold())
    if italian_meaning is not None:
        expanded = (
            "Translate this Italian sentence into Simplified Chinese using its "
            f"English meaning: {italian_meaning}"
        )
    if expanded == item.source_text and any(
        ord(character) > 127 and character.isalpha()
        for character in item.source_text
    ):
        expanded = (
            "Translate this non-English text into Simplified Chinese: "
            f"{item.source_text}"
        )
    return expanded if expanded != item.source_text else None


def _provider_batch(
    *,
    client: DeepSeekClient,
    assets,
    items: tuple[TranslationItem, ...],
    budget: AttemptBudget,
    timeout_seconds: float,
    protect_source: bool = True,
    source_overrides: Mapping[str, str] | None = None,
) -> tuple[dict[str, str], object]:
    bundle = PostTranslationBundle(post_id=f"batch-{items[0].post_id}", items=items)
    protected = (
        {
            item.stable_id: _protect_translation_text(item, assets.terms)
            for item in items
        }
        if protect_source
        else {}
    )
    payload = {
        "items": [
            {
                "id": item.stable_id,
                "item_type": item.item_type,
                "post_id": item.post_id,
                "comment_id": item.comment_id,
                "input_sha256": item.input_sha256,
                "source_text": (
                    source_overrides[item.stable_id]
                    if source_overrides is not None
                    and item.stable_id in source_overrides
                    else _reddit_unavailable_placeholder_translation_source(item)
                    if _is_reddit_unavailable_placeholder(item)
                    else protected[item.stable_id].provider_text
                    if protect_source
                    else item.source_text
                ),
            }
            for item in items
        ]
    }
    completion = client.complete_json(
        phase="translation",
        system_prompt=assets.translation_prompt,
        user_payload=payload,
        deadline=MonotonicDeadline(time.monotonic() + timeout_seconds),
        attempt_budget=budget,
    )
    restored: dict[str, str] = {}
    try:
        parsed = parse_translation_content(
            completion.content,
            expected_ids={item.stable_id for item in items},
            allow_extra_fields=True,
        )
        for item in items:
            if (
                _source_equal_allowed(item.source_text, assets.terms)
                and re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", parsed[item.stable_id])
                is None
            ):
                parsed[item.stable_id] = (
                    protected[item.stable_id].provider_text
                    if protect_source
                    else item.source_text
                )
        restored = (
            _restore_protected_translations(
                bundles=(bundle,),
                provider_translations=parsed,
                protected_text_by_id=protected,
            )
            if protect_source
            else parsed
        )
        validate_deterministic_translation(bundle, restored, assets.terms)
    except Exception as exc:
        reason_code = getattr(exc, "reason_code", None) or str(exc) or type(exc).__name__
        failures = tuple(getattr(exc, "failures", ()))
        failed_ids = {
            str(failure.stable_id)
            for failure in failures
            if isinstance(getattr(failure, "stable_id", None), str)
        }
        raise ProviderBatchValidationError(
            str(reason_code),
            completion=completion,
            batch_stable_ids=tuple(item.stable_id for item in items),
            failed_stable_ids=tuple(
                str(failure.stable_id)
                for failure in failures
                if isinstance(getattr(failure, "stable_id", None), str)
            ),
            failed_error_codes={
                str(failure.stable_id): tuple(
                    str(code) for code in failure.item_error_codes
                )
                for failure in failures
                if isinstance(getattr(failure, "stable_id", None), str)
            },
            accepted_translations={
                stable_id: zh
                for stable_id, zh in restored.items()
                if failures and stable_id not in failed_ids
            },
        ) from exc
    return restored, completion


def _provider_chunked_single_item(
    *,
    client: DeepSeekClient,
    assets,
    item: TranslationItem,
    budget: AttemptBudget,
    timeout_seconds: float,
    protect_source: bool = True,
) -> tuple[dict[str, str], object]:
    source_parts = re.split(r"(\n+)", item.source_text)
    text_parts = tuple(
        (part_index, source_parts[part_index])
        for part_index in range(0, len(source_parts), 2)
        if source_parts[part_index]
    )
    if len(text_parts) < 2:
        raise TranslationCandidateError("single_item_not_paragraph_chunkable")
    chunk_items = tuple(
        _translation_item(
            stable_id=f"{item.stable_id}#chunk-{index:03d}",
            item_type=item.item_type,
            post_id=item.post_id,
            comment_id=item.comment_id,
            source=paragraph,
        )
        for index, (_part_index, paragraph) in enumerate(text_parts)
    )
    try:
        chunk_translations, completion = _provider_batch(
            client=client,
            assets=assets,
            items=chunk_items,
            budget=budget,
            timeout_seconds=timeout_seconds,
            protect_source=protect_source,
        )
    except ProviderBatchValidationError as exc:
        raise ProviderBatchValidationError(
            exc.reason_code,
            completion=exc.completion,
            batch_stable_ids=(item.stable_id,),
            failed_stable_ids=(item.stable_id,),
            failed_error_codes=exc.failed_error_codes,
        ) from exc
    combined_parts = list(source_parts)
    for (part_index, _paragraph), chunk_item in zip(text_parts, chunk_items):
        combined_parts[part_index] = chunk_translations[chunk_item.stable_id]
    combined = "".join(combined_parts)
    bundle = PostTranslationBundle(post_id=item.post_id, items=(item,))
    try:
        validate_deterministic_translation(
            bundle,
            {item.stable_id: combined},
            assets.terms,
        )
    except Exception as exc:
        reason_code = getattr(exc, "reason_code", type(exc).__name__)
        failures = tuple(getattr(exc, "failures", ()))
        raise ProviderBatchValidationError(
            str(reason_code),
            completion=completion,
            batch_stable_ids=(item.stable_id,),
            failed_stable_ids=(item.stable_id,),
            failed_error_codes={
                str(failure.stable_id): tuple(
                    str(code) for code in failure.item_error_codes
                )
                for failure in failures
                if isinstance(getattr(failure, "stable_id", None), str)
            },
        ) from exc
    return {item.stable_id: combined}, completion


def _provider_protected_chunks_after_raw_failure(
    *,
    raw_failure: Exception,
    client: DeepSeekClient,
    assets,
    item: TranslationItem,
    budget: AttemptBudget,
    timeout_seconds: float,
) -> tuple[dict[str, str], object]:
    if getattr(raw_failure, "reason_code", None) != "protected_entity_changed":
        raise raw_failure
    return _provider_chunked_single_item(
        client=client,
        assets=assets,
        item=item,
        budget=budget,
        timeout_seconds=timeout_seconds,
    )


def _request_with_split(
    *,
    client: DeepSeekClient,
    assets,
    items: tuple[TranslationItem, ...],
    budget: AttemptBudget,
    timeout_seconds: float,
    on_error: Callable[[Exception], None],
    on_success: Callable[[dict[str, str], object], None],
    on_partial_success: Callable[[dict[str, str], object], None] | None = None,
) -> None:
    try:
        batch_translations, completion = _provider_batch(
            client=client,
            assets=assets,
            items=items,
            budget=budget,
            timeout_seconds=timeout_seconds,
        )
        on_success(batch_translations, completion)
        return
    except ProviderBatchValidationError as exc:
        on_error(exc)
        if exc.accepted_translations:
            if on_partial_success is not None:
                on_partial_success(exc.accepted_translations, exc.completion)
            items = tuple(
                item
                for item in items
                if item.stable_id not in exc.accepted_translations
            )
            if not items:
                return
        if len(items) <= 1:
            if exc.reason_code == "invalid_json_content":
                try:
                    batch_translations, completion = _provider_batch(
                        client=client,
                        assets=assets,
                        items=items,
                        budget=budget,
                        timeout_seconds=timeout_seconds,
                    )
                    on_success(batch_translations, completion)
                    return
                except Exception as retry_exc:
                    on_error(retry_exc)
                    if (
                        getattr(retry_exc, "reason_code", None)
                        == "invalid_json_content"
                        and "\n" in items[0].source_text
                    ):
                        try:
                            batch_translations, completion = (
                                _provider_chunked_single_item(
                                    client=client,
                                    assets=assets,
                                    item=items[0],
                                    budget=budget,
                                    timeout_seconds=timeout_seconds,
                                )
                            )
                            on_success(batch_translations, completion)
                            return
                        except Exception as chunked_exc:
                            on_error(chunked_exc)
                            if (
                                getattr(chunked_exc, "reason_code", None)
                                == "protected_placeholder_changed"
                            ):
                                try:
                                    batch_translations, completion = (
                                        _provider_chunked_single_item(
                                            client=client,
                                            assets=assets,
                                            item=items[0],
                                            budget=budget,
                                            timeout_seconds=timeout_seconds,
                                            protect_source=False,
                                        )
                                    )
                                    on_success(batch_translations, completion)
                                    return
                                except Exception as raw_chunked_exc:
                                    on_error(raw_chunked_exc)
                                    try:
                                        batch_translations, completion = (
                                            _provider_protected_chunks_after_raw_failure(
                                                raw_failure=raw_chunked_exc,
                                                client=client,
                                                assets=assets,
                                                item=items[0],
                                                budget=budget,
                                                timeout_seconds=timeout_seconds,
                                            )
                                        )
                                        on_success(batch_translations, completion)
                                        return
                                    except Exception as final_chunked_exc:
                                        on_error(final_chunked_exc)
                                        raise
                            raise
                    raise
            retry_raw_source = exc.reason_code == "protected_placeholder_changed"
            source_equal_override = (
                _source_equal_retry_override(items[0])
                if exc.reason_code
                in {"source_equal_translation", "non_chinese_translation"}
                else None
            )
            if retry_raw_source or source_equal_override is not None:
                try:
                    source_overrides = (
                        {items[0].stable_id: source_equal_override}
                        if source_equal_override is not None
                        else None
                    )
                    batch_translations, completion = _provider_batch(
                        client=client,
                        assets=assets,
                        items=items,
                        budget=budget,
                        timeout_seconds=timeout_seconds,
                        protect_source=False,
                        source_overrides=source_overrides,
                    )
                    on_success(batch_translations, completion)
                    return
                except Exception as fallback_exc:
                    on_error(fallback_exc)
                    if (
                        retry_raw_source
                        and getattr(fallback_exc, "reason_code", None)
                        == "protected_entity_changed"
                    ):
                        try:
                            batch_translations, completion = _provider_batch(
                                client=client,
                                assets=assets,
                                items=items,
                                budget=budget,
                                timeout_seconds=timeout_seconds,
                            )
                            on_success(batch_translations, completion)
                            return
                        except Exception as protected_retry_exc:
                            on_error(protected_retry_exc)
                            if (
                                getattr(protected_retry_exc, "reason_code", None)
                                in {
                                    "protected_placeholder_changed",
                                    "protected_entity_changed",
                                }
                                and "\n" in items[0].source_text
                            ):
                                try:
                                    batch_translations, completion = (
                                        _provider_chunked_single_item(
                                            client=client,
                                            assets=assets,
                                            item=items[0],
                                            budget=budget,
                                            timeout_seconds=timeout_seconds,
                                        )
                                    )
                                    on_success(batch_translations, completion)
                                    return
                                except Exception as chunked_exc:
                                    on_error(chunked_exc)
                                    if (
                                        getattr(chunked_exc, "reason_code", None)
                                        == "protected_placeholder_changed"
                                    ):
                                        try:
                                            batch_translations, completion = (
                                                _provider_chunked_single_item(
                                                    client=client,
                                                    assets=assets,
                                                    item=items[0],
                                                    budget=budget,
                                                    timeout_seconds=timeout_seconds,
                                                    protect_source=False,
                                                )
                                            )
                                            on_success(batch_translations, completion)
                                            return
                                        except Exception as raw_chunked_exc:
                                            on_error(raw_chunked_exc)
                                            try:
                                                batch_translations, completion = (
                                                    _provider_protected_chunks_after_raw_failure(
                                                        raw_failure=raw_chunked_exc,
                                                        client=client,
                                                        assets=assets,
                                                        item=items[0],
                                                        budget=budget,
                                                        timeout_seconds=timeout_seconds,
                                                    )
                                                )
                                                on_success(batch_translations, completion)
                                                return
                                            except Exception as final_chunked_exc:
                                                on_error(final_chunked_exc)
                                                raise
                                    raise
                            raise
                    raise
            raise
        midpoint = len(items) // 2
        _request_with_split(
            client=client,
            assets=assets,
            items=items[:midpoint],
            budget=budget,
            timeout_seconds=timeout_seconds,
            on_error=on_error,
            on_success=on_success,
            on_partial_success=on_partial_success,
        )
        _request_with_split(
            client=client,
            assets=assets,
            items=items[midpoint:],
            budget=budget,
            timeout_seconds=timeout_seconds,
            on_error=on_error,
            on_success=on_success,
            on_partial_success=on_partial_success,
        )
        return
    except Exception as exc:
        on_error(exc)
        if getattr(exc, "reason_code", None) == "invalid_json_content":
            if len(items) > 1:
                midpoint = len(items) // 2
                _request_with_split(
                    client=client,
                    assets=assets,
                    items=items[:midpoint],
                    budget=budget,
                    timeout_seconds=timeout_seconds,
                    on_error=on_error,
                    on_success=on_success,
                    on_partial_success=on_partial_success,
                )
                _request_with_split(
                    client=client,
                    assets=assets,
                    items=items[midpoint:],
                    budget=budget,
                    timeout_seconds=timeout_seconds,
                    on_error=on_error,
                    on_success=on_success,
                    on_partial_success=on_partial_success,
                )
                return
            try:
                batch_translations, completion = _provider_batch(
                    client=client,
                    assets=assets,
                    items=items,
                    budget=budget,
                    timeout_seconds=timeout_seconds,
                )
                on_success(batch_translations, completion)
                return
            except Exception as retry_exc:
                on_error(retry_exc)
                if (
                    getattr(retry_exc, "reason_code", None)
                    == "invalid_json_content"
                    and "\n" in items[0].source_text
                ):
                    try:
                        batch_translations, completion = (
                            _provider_chunked_single_item(
                                client=client,
                                assets=assets,
                                item=items[0],
                                budget=budget,
                                timeout_seconds=timeout_seconds,
                            )
                        )
                        on_success(batch_translations, completion)
                        return
                    except Exception as chunked_exc:
                        on_error(chunked_exc)
                        if (
                            getattr(chunked_exc, "reason_code", None)
                            == "protected_placeholder_changed"
                        ):
                            try:
                                batch_translations, completion = (
                                    _provider_chunked_single_item(
                                        client=client,
                                        assets=assets,
                                        item=items[0],
                                        budget=budget,
                                        timeout_seconds=timeout_seconds,
                                        protect_source=False,
                                    )
                                )
                                on_success(batch_translations, completion)
                                return
                            except Exception as raw_chunked_exc:
                                on_error(raw_chunked_exc)
                                try:
                                    batch_translations, completion = (
                                        _provider_protected_chunks_after_raw_failure(
                                            raw_failure=raw_chunked_exc,
                                            client=client,
                                            assets=assets,
                                            item=items[0],
                                            budget=budget,
                                            timeout_seconds=timeout_seconds,
                                        )
                                    )
                                    on_success(batch_translations, completion)
                                    return
                                except Exception as final_chunked_exc:
                                    on_error(final_chunked_exc)
                                    raise
                        raise
                raise
        raise


def _attempts_from_error(error: Exception) -> tuple[object, ...]:
    completion = getattr(error, "completion", None)
    if completion is not None:
        return tuple(getattr(completion, "attempts", ()))
    return tuple(getattr(error, "attempts", ()))


def _attempt_log_summary(path: Path) -> tuple[int, dict[str, int]]:
    usage = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 0,
        "total_tokens": 0,
    }
    if not path.exists():
        return 0, usage
    attempts = 0
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TranslationCandidateError(
                f"attempt_log_invalid_json:{line_number}"
            ) from exc
        if not isinstance(row, dict):
            raise TranslationCandidateError(f"attempt_log_invalid:{line_number}")
        sequence = row.get("sequence")
        if sequence == 0 and row.get("outcome") == "checkpoint_reuse_no_provider_attempt":
            continue
        attempts += 1
        attempt_usage = row.get("usage")
        if attempt_usage is None:
            continue
        if not isinstance(attempt_usage, dict):
            raise TranslationCandidateError(f"attempt_log_usage_invalid:{line_number}")
        for key in usage:
            value = attempt_usage.get(key)
            if not isinstance(value, int) or value < 0:
                raise TranslationCandidateError(f"attempt_log_usage_invalid:{line_number}")
            usage[key] += value
    return attempts, usage


def _attempt_log_proves_http_402(
    path: Path,
    *,
    authorization_id: str,
    source_manifest_sha256: str,
) -> bool:
    if not path.exists():
        return False
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TranslationCandidateError(
                f"attempt_log_invalid_json:{line_number}"
            ) from exc
        if not isinstance(row, dict):
            raise TranslationCandidateError(f"attempt_log_invalid:{line_number}")
        if (
            row.get("provider_authorization_id") == authorization_id
            and row.get("source_manifest_sha256") == source_manifest_sha256
            and row.get("http_status") == 402
            and row.get("outcome") == "http_status_402"
            and row.get("retryable") is False
        ):
            return True
    return False


def _translation_sidecars(
    *,
    items: Sequence[TranslationItem],
    translations: Mapping[str, str],
    dataset_version: str,
    source_dataset_version: str,
    generated_at_utc: str,
) -> tuple[dict[str, object], dict[str, object]]:
    item_by_id = {item.stable_id: item for item in items}
    posts: dict[str, dict[str, object]] = {}
    comments: list[dict[str, object]] = []
    for stable_id in sorted(translations):
        item = item_by_id[stable_id]
        common = {
            "input_sha256": item.input_sha256,
            "provider": "deepseek",
            "quality_status": "deterministic_passed_unreviewed",
            "zh": translations[stable_id],
        }
        if item.item_type == "comment":
            comments.append(
                {
                    "comment_id": item.comment_id,
                    "post_id": item.post_id,
                    **common,
                }
            )
            continue
        row = posts.setdefault(item.post_id, {"post_id": item.post_id})
        field = "title" if item.item_type == "title" else "content"
        row[f"{field}_zh"] = common["zh"]
        row[f"{field}_input_sha256"] = item.input_sha256
        row[f"{field}_quality_status"] = common["quality_status"]
    envelope = {
        "schema_version": TRANSLATION_SCHEMA,
        "dataset_version": dataset_version,
        "source_dataset_version": source_dataset_version,
        "generated_at_utc": generated_at_utc,
        "provider": "deepseek",
        "model": DEEPSEEK_MODEL,
        "quality_gate": "deterministic_contract_v1",
        "semantic_validation": "not_run",
        "independent_human_review": False,
    }
    return (
        {**envelope, "entity_type": "post", "items": list(posts.values())},
        {**envelope, "entity_type": "comment", "items": comments},
    )


def _build_completed_candidate(
    *,
    source_root: Path,
    output_root: Path,
    source_manifest: dict[str, Any],
    source_manifest_sha256: str,
    dataset_version: str,
    generated_at_utc: str,
    authorization_id: str,
    checkpoint_path: Path,
    attempt_log_path: Path,
    items: Sequence[TranslationItem],
    translations: Mapping[str, str],
    usage: Mapping[str, int],
    provider_attempts: int,
    translation_terms_sha256: str,
    comments_total: int,
    partial_comments_reason: str | None,
) -> None:
    if output_root.exists() or output_root.is_symlink():
        raise TranslationCandidateError("output_root_must_not_exist")
    shutil.copytree(source_root, output_root, symlinks=False)
    manifest_path = output_root / "manifest-public.json"
    manifest_path.unlink()
    post_sidecar, comment_sidecar = _translation_sidecars(
        items=items,
        translations=translations,
        dataset_version=dataset_version,
        source_dataset_version=str(source_manifest["dataset_version"]),
        generated_at_utc=generated_at_utc,
    )
    _write_json(output_root / SIDE_CAR_NAMES[0], post_sidecar)
    _write_json(output_root / SIDE_CAR_NAMES[1], comment_sidecar)
    files = dict(source_manifest["files"])
    for name in SIDE_CAR_NAMES:
        path = output_root / name
        files[name] = {"bytes": path.stat().st_size, "sha256": _sha256(path)}
    post_count = len(post_sidecar["items"])
    comment_count = len(comment_sidecar["items"])
    comments_status = "complete" if comment_count == comments_total else "partial"
    if comments_status == "complete":
        partial_comments_reason = None
    manifest = {
        **source_manifest,
        "dataset_version": dataset_version,
        "generated_at_utc": generated_at_utc,
        "status": "validated_local_translation_candidate",
        "artifact_stage": "local_translation_candidate",
        "consumption_status": "eligible_for_frontend_candidate_consumption",
        "promotable": False,
        "provider_call": True,
        "files": files,
        "boundaries": {
            **source_manifest["boundaries"],
            "provider_call": True,
            "database_write": False,
            "remote_write": False,
            "deploy": False,
            "live_send": False,
            "production_unchanged": True,
        },
        "translations": {
            "schema_version": MANIFEST_EXTENSION_SCHEMA,
            "provider": "deepseek",
            "model": DEEPSEEK_MODEL,
            "provider_call": True,
            "provider_authorization_id": authorization_id,
            "source_dataset_version": source_manifest["dataset_version"],
            "source_public_manifest_sha256": source_manifest_sha256,
            "translation_prompt_sha256": _sha256(ROOT / "config/prompts/deepseek-translation-v1.txt"),
            "translation_terms_sha256": translation_terms_sha256,
            "checkpoint_sha256": _sha256(checkpoint_path),
            "provider_attempt_log_sha256": _sha256(attempt_log_path),
            "quality_gate": "deterministic_contract_v1",
            "semantic_validation": "not_run",
            "independent_human_review": False,
            "coverage": {
                "posts": post_count,
                "post_titles": post_count,
                "post_contents": post_count,
                "comments": comment_count,
                "comments_total": comments_total,
                "comments_status": comments_status,
                "comments_unavailable_reason": partial_comments_reason,
                "post_translation_status": "complete",
                "translated_items": len(translations),
            },
            "provider_attempts": provider_attempts,
            "usage": dict(usage),
        },
    }
    _write_json(manifest_path, manifest)


def run(args: argparse.Namespace, *, client: DeepSeekClient | None = None) -> dict[str, object]:
    source_root = Path(args.source_root)
    work_root = Path(args.work_root)
    output_root = Path(args.output_root)
    if source_root.is_symlink() or not source_root.is_dir():
        raise TranslationCandidateError("source_root_unsafe")
    resolved_source = source_root.resolve()
    resolved_work = work_root.resolve(strict=False)
    resolved_output = output_root.resolve(strict=False)
    if resolved_source == resolved_work or resolved_source in resolved_work.parents:
        raise TranslationCandidateError("work_root_must_be_outside_source_root")
    if resolved_source == resolved_output or resolved_source in resolved_output.parents:
        raise TranslationCandidateError("output_root_must_be_outside_source_root")
    if output_root.exists() or output_root.is_symlink():
        raise TranslationCandidateError("output_root_must_not_exist")
    manifest_path = source_root / "manifest-public.json"
    source_manifest = _load_json(manifest_path, expected_type=dict)
    source_manifest_sha256 = _sha256(manifest_path)
    if source_manifest.get("schema_version") != "reddit_voc_site_snapshot_manifest_v3":
        raise TranslationCandidateError("source_manifest_schema_invalid")
    source_dataset_version = _safe_identifier(
        str(source_manifest.get("dataset_version", "")),
        label="source_dataset_version",
        prefix="reddit_voc_site_snapshot_",
    )
    dataset_version = _safe_identifier(
        args.dataset_version,
        label="dataset_version",
        prefix="reddit_voc_site_snapshot_",
    )
    if dataset_version == source_dataset_version:
        raise TranslationCandidateError("dataset_version_must_advance")
    authorization_id = _safe_identifier(
        args.provider_authorization_id,
        label="provider_authorization_id",
    )
    generated_at_utc = (
        datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        if args.generated_at_utc == "now"
        else args.generated_at_utc
    )
    try:
        parsed_generated = datetime.fromisoformat(generated_at_utc.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TranslationCandidateError("generated_at_utc_invalid") from exc
    if parsed_generated.utcoffset() != timezone.utc.utcoffset(parsed_generated):
        raise TranslationCandidateError("generated_at_utc_not_utc")

    posts = _load_json(source_root / "posts-public.json", expected_type=list)
    comments = _load_json(source_root / "comments-public.json", expected_type=list)
    counts = source_manifest.get("canonical_counts")
    if (
        not isinstance(counts, dict)
        or counts.get("posts") != len(posts)
        or counts.get("linked_comments") != len(comments)
    ):
        raise TranslationCandidateError("source_count_contract_invalid")
    items = build_translation_items(
        posts,
        comments,
        include_comments=args.include_comments,
    )
    item_by_id = {item.stable_id: item for item in items}
    assets = load_translation_runtime_assets(ROOT / "config")
    translation_prompt_sha256 = sha256_hex(assets.translation_prompt_bytes)
    checkpoint_path = work_root / "translations-checkpoint.jsonl"
    attempt_log_path = work_root / "provider-attempts.jsonl"
    run_receipts_root = work_root / "run-receipts"
    translations = _load_checkpoint(
        checkpoint_path,
        source_manifest_sha256=source_manifest_sha256,
        item_by_id=item_by_id,
        translation_prompt_sha256=translation_prompt_sha256,
        translation_terms_sha256=assets.terms_sha256,
    )
    _validate_translation_map(
        items=items,
        translations=translations,
        terms=assets.terms,
    )
    for item in items:
        if not item.source_text and item.stable_id not in translations:
            row = {
                "schema_version": CHECKPOINT_SCHEMA,
                "source_manifest_sha256": source_manifest_sha256,
                "stable_id": item.stable_id,
                "item_type": item.item_type,
                "post_id": item.post_id,
                "comment_id": item.comment_id,
                "input_sha256": item.input_sha256,
                "zh": "",
                "provider": "deepseek",
                "model": DEEPSEEK_MODEL,
                "provider_attempt_sequence": None,
                "provider_response_id": None,
                "provider_output_sha256": None,
                "translation_prompt_sha256": translation_prompt_sha256,
                "translation_terms_sha256": assets.terms_sha256,
            }
            _append_jsonl(checkpoint_path, row)
            translations[item.stable_id] = ""
    pending = [item for item in items if item.stable_id not in translations]
    usage = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 0,
        "total_tokens": 0,
    }
    run_started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    provider_attempts = 0
    status = "complete" if not pending else "blocked_provider_credential_missing"
    failure_reason: str | None = None
    budget = AttemptBudget(max_attempts=args.max_provider_requests)
    ledger_lock = threading.Lock()

    def record_failed_attempts(error: Exception) -> None:
        nonlocal provider_attempts
        with ledger_lock:
            completion = getattr(error, "completion", None)
            if completion is not None:
                _add_usage(usage, completion.usage)
            else:
                error_usage = getattr(error, "usage", None)
                if isinstance(error_usage, TokenUsage):
                    _add_usage(usage, error_usage)
            for attempt in _attempts_from_error(error):
                diagnostic = {}
                if isinstance(error, ProviderBatchValidationError):
                    diagnostic = {
                        "quality_failure_reason": error.reason_code,
                        "failed_stable_ids": list(error.failed_stable_ids),
                        "failed_error_codes": {
                            stable_id: list(codes)
                            for stable_id, codes in error.failed_error_codes.items()
                        },
                        "batch_stable_ids_sha256": sha256_hex(
                            canonical_json_bytes(list(error.batch_stable_ids))
                        ),
                        "batch_item_count": len(error.batch_stable_ids),
                    }
                    if error.accepted_translations:
                        diagnostic.update(
                            {
                                "accepted_translation_item_count": len(
                                    error.accepted_translations
                                ),
                                "accepted_translation_output_sha256": translation_output_sha256(
                                    error.accepted_translations
                                ),
                            }
                        )
                _append_jsonl(
                    attempt_log_path,
                    {
                        "schema_version": "reddit_voc_translation_provider_attempt_v1",
                        "provider_authorization_id": authorization_id,
                        "source_manifest_sha256": source_manifest_sha256,
                        "translation_prompt_sha256": translation_prompt_sha256,
                        "translation_terms_sha256": assets.terms_sha256,
                        **asdict(attempt),
                        **diagnostic,
                    },
                )
                provider_attempts += 1

    def persist_batch_translations(
        batch_translations: Mapping[str, str], completion: object
    ) -> None:
        attempts = tuple(getattr(completion, "attempts"))
        sequence = attempts[-1].sequence
        provider_output_sha256 = translation_output_sha256(batch_translations)
        for stable_id, zh in batch_translations.items():
            item = item_by_id[stable_id]
            _append_jsonl(
                checkpoint_path,
                {
                    "schema_version": CHECKPOINT_SCHEMA,
                    "source_manifest_sha256": source_manifest_sha256,
                    "stable_id": stable_id,
                    "item_type": item.item_type,
                    "post_id": item.post_id,
                    "comment_id": item.comment_id,
                    "input_sha256": item.input_sha256,
                    "zh": zh,
                    "provider": "deepseek",
                    "model": DEEPSEEK_MODEL,
                    "provider_attempt_sequence": sequence,
                    "provider_response_id": getattr(completion, "request_id"),
                    "provider_output_sha256": provider_output_sha256,
                    "translation_prompt_sha256": translation_prompt_sha256,
                    "translation_terms_sha256": assets.terms_sha256,
                },
            )
            translations[stable_id] = zh

    def record_partial_batch(
        batch_translations: dict[str, str], completion: object
    ) -> None:
        with ledger_lock:
            persist_batch_translations(batch_translations, completion)

    def record_successful_batch(
        batch_translations: dict[str, str], completion: object
    ) -> None:
        nonlocal provider_attempts
        with ledger_lock:
            attempts = tuple(getattr(completion, "attempts"))
            sequence = attempts[-1].sequence
            provider_output_sha256 = translation_output_sha256(batch_translations)
            for attempt in attempts:
                attempt_document = {
                    "schema_version": "reddit_voc_translation_provider_attempt_v1",
                    "provider_authorization_id": authorization_id,
                    "source_manifest_sha256": source_manifest_sha256,
                    "translation_prompt_sha256": translation_prompt_sha256,
                    "translation_terms_sha256": assets.terms_sha256,
                    **asdict(attempt),
                }
                if attempt.outcome == "success":
                    attempt_document.update(
                        {
                            "translation_output_sha256": provider_output_sha256,
                            "translation_item_count": len(batch_translations),
                        }
                    )
                _append_jsonl(attempt_log_path, attempt_document)
            provider_attempts += len(attempts)
            _add_usage(usage, getattr(completion, "usage"))
            persist_batch_translations(batch_translations, completion)

    if pending:
        if not args.authorize_provider_call:
            status = "blocked_provider_call_not_authorized"
        else:
            workers = int(getattr(args, "workers", 1))
            client_factory: Callable[[], DeepSeekClient] | None = None
            if client is not None and workers != 1:
                raise TranslationCandidateError(
                    "injected_client_requires_single_worker"
                )
            if client is None:
                api_key = _load_api_key(getattr(args, "api_key_file", None))
                if not api_key:
                    status = "blocked_provider_credential_missing"
                else:
                    client_factory = lambda: DeepSeekClient(api_key=api_key)
                    if workers == 1:
                        client = client_factory()
            if client is not None or client_factory is not None:
                status = "partial_attempt_budget_exhausted"
                thread_local = threading.local()

                def run_batch(batch: tuple[TranslationItem, ...]) -> None:
                    worker_client = client
                    if worker_client is None:
                        worker_client = getattr(thread_local, "client", None)
                        if worker_client is None:
                            assert client_factory is not None
                            worker_client = client_factory()
                            thread_local.client = worker_client
                    _request_with_split(
                        client=worker_client,
                        assets=assets,
                        items=batch,
                        budget=budget,
                        timeout_seconds=args.request_timeout_seconds,
                        on_error=record_failed_attempts,
                        on_success=record_successful_batch,
                        on_partial_success=record_partial_batch,
                    )

                try:
                    batches = iter(
                        _batches(
                            pending,
                            max_items=args.batch_size,
                            max_source_chars=args.max_source_chars,
                        )
                    )
                    with ThreadPoolExecutor(max_workers=workers) as executor:
                        active: set[Future[None]] = set()
                        for _ in range(workers):
                            batch = next(batches, None)
                            if batch is None:
                                break
                            active.add(executor.submit(run_batch, batch))
                        first_error: Exception | None = None
                        while active:
                            completed, active = wait(
                                active, return_when=FIRST_COMPLETED
                            )
                            for future in completed:
                                try:
                                    future.result()
                                except Exception as exc:
                                    first_error = first_error or exc
                            if first_error is not None:
                                continue
                            for _ in completed:
                                if budget.used >= args.max_provider_requests:
                                    break
                                batch = next(batches, None)
                                if batch is None:
                                    break
                                active.add(executor.submit(run_batch, batch))
                        if first_error is not None:
                            raise first_error
                    if len(translations) == len(items):
                        status = "complete"
                except Exception as exc:
                    status = "partial_provider_or_quality_failure"
                    failure_reason = getattr(exc, "reason_code", type(exc).__name__)

    post_item_ids = {
        item.stable_id for item in items if item.item_type in {"title", "body"}
    }
    complete_post_coverage = post_item_ids.issubset(translations)
    allow_partial_comments = bool(getattr(args, "allow_partial_comments", False))
    partial_comments_reason = getattr(args, "partial_comments_reason", None)
    if (
        status != "complete"
        and allow_partial_comments
        and bool(args.include_comments)
        and complete_post_coverage
        and len(translations) < len(items)
        and partial_comments_reason == "provider_http_402_balance_blocked"
        and _attempt_log_proves_http_402(
            attempt_log_path,
            authorization_id=authorization_id,
            source_manifest_sha256=source_manifest_sha256,
        )
    ):
        status = "complete_post_coverage_partial_comments"
        failure_reason = partial_comments_reason

    candidate_ready = status in {
        "complete",
        "complete_post_coverage_partial_comments",
    }
    if candidate_ready and not output_root.exists():
        if not attempt_log_path.exists():
            _append_jsonl(
                attempt_log_path,
                {
                    "schema_version": "reddit_voc_translation_provider_attempt_v1",
                    "provider_authorization_id": authorization_id,
                    "source_manifest_sha256": source_manifest_sha256,
                    "translation_prompt_sha256": translation_prompt_sha256,
                    "translation_terms_sha256": assets.terms_sha256,
                    "sequence": 0,
                    "phase": "translation",
                    "http_status": None,
                    "outcome": "checkpoint_reuse_no_provider_attempt",
                    "retryable": False,
                    "duration_ms": 0,
                    "response_id": None,
                    "actual_model": DEEPSEEK_MODEL,
                    "system_fingerprint": None,
                    "finish_reason": None,
                    "usage": None,
                },
            )
        cumulative_provider_attempts, cumulative_usage = _attempt_log_summary(
            attempt_log_path
        )
        _build_completed_candidate(
            source_root=source_root,
            output_root=output_root,
            source_manifest=source_manifest,
            source_manifest_sha256=source_manifest_sha256,
            dataset_version=dataset_version,
            generated_at_utc=generated_at_utc,
            authorization_id=authorization_id,
            checkpoint_path=checkpoint_path,
            attempt_log_path=attempt_log_path,
            items=items,
            translations=translations,
            usage=cumulative_usage,
            provider_attempts=cumulative_provider_attempts,
            translation_terms_sha256=assets.terms_sha256,
            comments_total=len(comments) if args.include_comments else 0,
            partial_comments_reason=(
                partial_comments_reason
                if status == "complete_post_coverage_partial_comments"
                else None
            ),
        )

    receipt = {
        "schema_version": RUN_RECEIPT_SCHEMA,
        "status": status,
        "failure_reason": failure_reason,
        "provider_authorization_id": authorization_id,
        "provider_call_authorized": bool(args.authorize_provider_call),
        "provider_call": provider_attempts > 0,
        "provider_attempts": provider_attempts,
        "source_dataset_version": source_dataset_version,
        "source_manifest_sha256": source_manifest_sha256,
        "candidate_dataset_version": dataset_version,
        "include_comments": bool(args.include_comments),
        "item_count": len(items),
        "translated_item_count": len(translations),
        "remaining_item_count": len(items) - len(translations),
        "complete_post_coverage": complete_post_coverage,
        "comments_translated": sum(
            1 for item in items if item.item_type == "comment" and item.stable_id in translations
        ),
        "comments_total": len(comments) if args.include_comments else 0,
        "comments_unavailable_reason": (
            partial_comments_reason
            if status == "complete_post_coverage_partial_comments"
            else None
        ),
        "checkpoint_path": checkpoint_path.as_posix(),
        "checkpoint_sha256": _sha256(checkpoint_path) if checkpoint_path.exists() else None,
        "attempt_log_path": attempt_log_path.as_posix(),
        "attempt_log_sha256": _sha256(attempt_log_path) if attempt_log_path.exists() else None,
        "candidate_root": output_root.as_posix() if output_root.exists() else None,
        "usage": usage,
        "started_at_utc": run_started,
        "finished_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "boundaries": {
            "database_write": False,
            "deploy": False,
            "live_send": False,
            "production_unchanged": True,
            "remote_write": False,
        },
    }
    receipt_name = f"run-{run_started.replace(':', '').replace('-', '')}.json"
    _write_json(run_receipts_root / receipt_name, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--provider-authorization-id", required=True)
    parser.add_argument("--generated-at-utc", default="now")
    parser.add_argument("--include-comments", action="store_true")
    parser.add_argument(
        "--allow-partial-comments",
        action="store_true",
        help="Build a non-promotable candidate when posts are complete but comments are partial.",
    )
    parser.add_argument(
        "--partial-comments-reason",
        choices=("provider_http_402_balance_blocked",),
        help="Required auditable reason when --allow-partial-comments is used.",
    )
    parser.add_argument("--authorize-provider-call", action="store_true")
    parser.add_argument(
        "--api-key-file",
        type=Path,
        help="Optional owner-only (0600) local credential file; never recorded in receipts.",
    )
    parser.add_argument("--batch-size", type=int, default=24)
    parser.add_argument("--max-source-chars", type=int, default=24000)
    parser.add_argument("--max-provider-requests", type=int, default=100)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--request-timeout-seconds", type=float, default=60.0)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 64:
        raise SystemExit("batch-size must be between 1 and 64")
    if not 1000 <= args.max_source_chars <= 64000:
        raise SystemExit("max-source-chars must be between 1000 and 64000")
    if not 1 <= args.max_provider_requests <= 100:
        raise SystemExit("max-provider-requests must be between 1 and 100")
    if not 1 <= args.workers <= 4:
        raise SystemExit("workers must be between 1 and 4")
    if not 5 <= args.request_timeout_seconds <= 120:
        raise SystemExit("request-timeout-seconds must be between 5 and 120")
    if args.allow_partial_comments and not args.include_comments:
        raise SystemExit("--allow-partial-comments requires --include-comments")
    if args.allow_partial_comments and args.partial_comments_reason is None:
        raise SystemExit("--allow-partial-comments requires --partial-comments-reason")
    if args.partial_comments_reason and not args.allow_partial_comments:
        raise SystemExit("--partial-comments-reason requires --allow-partial-comments")
    result = run(args)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] in {
        "complete",
        "complete_post_coverage_partial_comments",
    } else 2


if __name__ == "__main__":
    raise SystemExit(main())
