#!/usr/bin/env python3
"""Independently validate a local V3 DeepSeek translation candidate.

This validator performs no provider, database, remote, deploy, or live-send
operation.  It binds the immutable source snapshot, translated sidecars,
checkpoint, prompt/terms assets, and provider-attempt ledger into one local
receipt.  A passing receipt is still not a production promotion receipt.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from reddit_voc.deepseek_client import DEEPSEEK_MODEL  # noqa: E402
from reddit_voc.report_contracts import sha256_hex  # noqa: E402
from reddit_voc.translation_pipeline import (  # noqa: E402
    load_translation_runtime_assets,
    translation_output_sha256,
)
from scripts.build_reddit_v3_translation_candidate import (  # noqa: E402
    CHECKPOINT_SCHEMA,
    MANIFEST_EXTENSION_SCHEMA,
    SIDE_CAR_NAMES,
    TRANSLATION_SCHEMA,
    TranslationCandidateError,
    _assert_private_regular_file,
    _checkpoint_reused_ids,
    _load_checkpoint,
    _load_json,
    _load_reuse_candidate,
    _safe_identifier,
    _sha256,
    _validate_translation_map,
    _write_json,
    build_translation_items,
)


VALIDATION_RECEIPT_SCHEMA = "reddit_voc_translation_candidate_validation_receipt_v1"
ATTEMPT_SCHEMA = "reddit_voc_translation_provider_attempt_v1"
USAGE_FIELDS = (
    "prompt_tokens",
    "completion_tokens",
    "prompt_cache_hit_tokens",
    "prompt_cache_miss_tokens",
    "total_tokens",
)


def _require(condition: object, reason: str) -> None:
    if not condition:
        raise TranslationCandidateError(reason)


def _mapping(value: object, reason: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise TranslationCandidateError(reason)
    return value


def _validate_declared_file(root: Path, name: str, declaration: object) -> None:
    record = _mapping(declaration, f"file_declaration_invalid:{name}")
    path = root / name
    _require(not path.is_symlink() and path.is_file(), f"file_missing_or_unsafe:{name}")
    _require(
        set(record) == {"bytes", "sha256"}
        and isinstance(record.get("bytes"), int)
        and not isinstance(record.get("bytes"), bool)
        and record["bytes"] > 0
        and isinstance(record.get("sha256"), str)
        and len(record["sha256"]) == 64,
        f"file_declaration_invalid:{name}",
    )
    _require(path.stat().st_size == record["bytes"], f"file_bytes_mismatch:{name}")
    _require(_sha256(path) == record["sha256"], f"file_sha256_mismatch:{name}")


def _validate_envelope(
    sidecar: Mapping[str, Any],
    *,
    entity_type: str,
    candidate_manifest: Mapping[str, Any],
    translation_manifest: Mapping[str, Any],
) -> Sequence[Mapping[str, Any]]:
    expected_keys = {
        "schema_version",
        "dataset_version",
        "source_dataset_version",
        "generated_at_utc",
        "provider",
        "model",
        "quality_gate",
        "semantic_validation",
        "independent_human_review",
        "entity_type",
        "items",
    }
    _require(set(sidecar) == expected_keys, f"{entity_type}_sidecar_keys_invalid")
    _require(
        sidecar.get("schema_version") == TRANSLATION_SCHEMA
        and sidecar.get("dataset_version") == candidate_manifest.get("dataset_version")
        and sidecar.get("source_dataset_version")
        == translation_manifest.get("source_dataset_version")
        and sidecar.get("generated_at_utc") == candidate_manifest.get("generated_at_utc")
        and sidecar.get("provider") == "deepseek"
        and sidecar.get("model") == DEEPSEEK_MODEL
        and sidecar.get("quality_gate") == "deterministic_contract_v1"
        and sidecar.get("semantic_validation") == "not_run"
        and sidecar.get("independent_human_review") is False
        and sidecar.get("entity_type") == entity_type
        and isinstance(sidecar.get("items"), list),
        f"{entity_type}_sidecar_envelope_invalid",
    )
    items = sidecar["items"]
    _require(all(isinstance(row, dict) for row in items), f"{entity_type}_sidecar_row_invalid")
    return items


def _validate_post_sidecar(
    rows: Sequence[Mapping[str, Any]],
    *,
    posts: Sequence[Mapping[str, Any]],
    translations: Mapping[str, str],
) -> None:
    expected_keys = {
        "post_id",
        "title_zh",
        "content_zh",
        "title_input_sha256",
        "content_input_sha256",
        "title_quality_status",
        "content_quality_status",
    }
    by_id: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        post_id = row.get("post_id")
        _require(
            set(row) == expected_keys
            and isinstance(post_id, str)
            and post_id not in by_id,
            "post_translation_row_invalid",
        )
        by_id[post_id] = row
    _require(len(by_id) == len(posts), "post_translation_coverage_invalid")
    for post in posts:
        post_id = post["post_id"]
        row = by_id.get(post_id)
        _require(row is not None, f"post_translation_missing:{post_id}")
        title = str(post.get("title") or "").replace("\r\n", "\n").replace("\r", "\n")
        content = str(post.get("content") or "").replace("\r\n", "\n").replace("\r", "\n")
        _require(
            row.get("title_zh") == translations[f"post:{post_id}:title"]
            and row.get("content_zh") == translations[f"post:{post_id}:content"]
            and row.get("title_input_sha256") == sha256_hex(title.encode("utf-8"))
            and row.get("content_input_sha256") == sha256_hex(content.encode("utf-8"))
            and row.get("title_quality_status") == "deterministic_passed_unreviewed"
            and row.get("content_quality_status") == "deterministic_passed_unreviewed",
            f"post_translation_binding_invalid:{post_id}",
        )


def _validate_comment_sidecar(
    rows: Sequence[Mapping[str, Any]],
    *,
    comments: Sequence[Mapping[str, Any]],
    translations: Mapping[str, str],
) -> None:
    expected_keys = {
        "comment_id",
        "post_id",
        "zh",
        "input_sha256",
        "provider",
        "quality_status",
    }
    by_id: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        comment_id = row.get("comment_id")
        _require(
            set(row) == expected_keys
            and isinstance(comment_id, str)
            and comment_id not in by_id,
            "comment_translation_row_invalid",
        )
        by_id[comment_id] = row
    comments_by_id = {comment["comment_id"]: comment for comment in comments}
    _require(set(by_id).issubset(comments_by_id), "comment_translation_identity_invalid")
    for comment_id, row in by_id.items():
        comment = comments_by_id[comment_id]
        body = str(comment.get("body") or "").replace("\r\n", "\n").replace("\r", "\n")
        _require(
            row.get("post_id") == comment.get("post_id")
            and row.get("zh") == translations[f"comment:{comment_id}:body"]
            and row.get("input_sha256") == sha256_hex(body.encode("utf-8"))
            and row.get("provider") == "deepseek"
            and row.get("quality_status") == "deterministic_passed_unreviewed",
            f"comment_translation_binding_invalid:{comment_id}",
        )


def _validate_attempt_log(
    path: Path,
    *,
    authorization_id: str,
    source_manifest_sha256: str,
    translation_prompt_sha256: str,
    translation_terms_sha256: str,
) -> tuple[int, dict[str, int], dict[str, str], set[int], tuple[str, ...]]:
    _assert_private_regular_file(path, label="attempt_log")
    attempts = 0
    successful_outputs: dict[str, str] = {}
    observed_http_statuses: set[int] = set()
    execution_authorization_ids: list[str] = []
    seen_execution_authorization_ids: set[str] = set()
    usage = {field: 0 for field in USAGE_FIELDS}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TranslationCandidateError(f"attempt_log_invalid_json:{line_number}") from exc
        _require(isinstance(row, dict), f"attempt_log_row_invalid:{line_number}")
        _require(
            row.get("schema_version") == ATTEMPT_SCHEMA
            and row.get("provider_authorization_id") == authorization_id
            and row.get("source_manifest_sha256") == source_manifest_sha256
            and row.get("translation_prompt_sha256") == translation_prompt_sha256
            and row.get("translation_terms_sha256") == translation_terms_sha256,
            f"attempt_log_binding_invalid:{line_number}",
        )
        raw_execution_authorization_id = row.get(
            "provider_execution_authorization_id",
            authorization_id,
        )
        _require(
            isinstance(raw_execution_authorization_id, str),
            f"attempt_log_execution_authorization_invalid:{line_number}",
        )
        execution_authorization_id = _safe_identifier(
            raw_execution_authorization_id,
            label="provider_execution_authorization_id",
        )
        if execution_authorization_id not in seen_execution_authorization_ids:
            seen_execution_authorization_ids.add(execution_authorization_id)
            execution_authorization_ids.append(execution_authorization_id)
        sequence = row.get("sequence")
        if sequence == 0 and row.get("outcome") == "checkpoint_reuse_no_provider_attempt":
            _require(row.get("usage") is None, f"attempt_log_marker_invalid:{line_number}")
            continue
        _require(
            isinstance(sequence, int)
            and not isinstance(sequence, bool)
            and sequence >= 1
            and row.get("phase") == "translation",
            f"attempt_log_attempt_invalid:{line_number}",
        )
        attempts += 1
        http_status = row.get("http_status")
        if isinstance(http_status, int) and not isinstance(http_status, bool):
            observed_http_statuses.add(http_status)
        output_sha256 = row.get("translation_output_sha256")
        if output_sha256 is not None:
            response_id = row.get("response_id")
            item_count = row.get("translation_item_count")
            _require(
                row.get("outcome") == "success"
                and isinstance(response_id, str)
                and bool(response_id)
                and isinstance(output_sha256, str)
                and len(output_sha256) == 64
                and isinstance(item_count, int)
                and not isinstance(item_count, bool)
                and item_count >= 1
                and (
                    response_id not in successful_outputs
                    or successful_outputs[response_id] == output_sha256
                ),
                f"attempt_log_translation_output_invalid:{line_number}",
            )
            successful_outputs[response_id] = output_sha256
        accepted_output_sha256 = row.get("accepted_translation_output_sha256")
        if accepted_output_sha256 is not None:
            response_id = row.get("response_id")
            accepted_item_count = row.get("accepted_translation_item_count")
            batch_item_count = row.get("batch_item_count")
            _require(
                row.get("outcome") == "success"
                and isinstance(row.get("quality_failure_reason"), str)
                and bool(row["quality_failure_reason"])
                and isinstance(response_id, str)
                and bool(response_id)
                and isinstance(accepted_output_sha256, str)
                and len(accepted_output_sha256) == 64
                and isinstance(accepted_item_count, int)
                and not isinstance(accepted_item_count, bool)
                and accepted_item_count >= 1
                and isinstance(batch_item_count, int)
                and not isinstance(batch_item_count, bool)
                and accepted_item_count < batch_item_count
                and output_sha256 is None
                and (
                    response_id not in successful_outputs
                    or successful_outputs[response_id] == accepted_output_sha256
                ),
                f"attempt_log_accepted_output_invalid:{line_number}",
            )
            successful_outputs[response_id] = accepted_output_sha256
        row_usage = row.get("usage")
        if row_usage is None:
            continue
        _require(isinstance(row_usage, dict), f"attempt_log_usage_invalid:{line_number}")
        for field in USAGE_FIELDS:
            value = row_usage.get(field)
            _require(
                isinstance(value, int) and not isinstance(value, bool) and value >= 0,
                f"attempt_log_usage_invalid:{line_number}",
            )
            usage[field] += value
    _require(
        attempts == 0 or bool(successful_outputs),
        "attempt_log_has_no_successful_provider_call",
    )
    return (
        attempts,
        usage,
        successful_outputs,
        observed_http_statuses,
        tuple(execution_authorization_ids),
    )


def validate_candidate(
    *,
    source_root: Path,
    candidate_root: Path,
    checkpoint_path: Path,
    attempt_log_path: Path,
    expected_authorization_id: str,
    reuse_candidate_root: Path | None = None,
) -> dict[str, object]:
    _require(source_root.is_dir() and not source_root.is_symlink(), "source_root_unsafe")
    _require(candidate_root.is_dir() and not candidate_root.is_symlink(), "candidate_root_unsafe")
    authorization_id = _safe_identifier(
        expected_authorization_id,
        label="provider_authorization_id",
    )
    source_manifest_path = source_root / "manifest-public.json"
    candidate_manifest_path = candidate_root / "manifest-public.json"
    source_manifest = _load_json(source_manifest_path, expected_type=dict)
    candidate_manifest = _load_json(candidate_manifest_path, expected_type=dict)
    source_manifest_sha256 = _sha256(source_manifest_path)
    candidate_manifest_sha256 = _sha256(candidate_manifest_path)
    source_files = _mapping(source_manifest.get("files"), "source_files_invalid")
    candidate_files = _mapping(candidate_manifest.get("files"), "candidate_files_invalid")
    _require(
        set(candidate_files) == set(source_files) | set(SIDE_CAR_NAMES),
        "candidate_file_set_invalid",
    )
    for name, declaration in source_files.items():
        _validate_declared_file(source_root, name, declaration)
        _validate_declared_file(candidate_root, name, candidate_files.get(name))
        _require(candidate_files[name] == declaration, f"source_file_binding_changed:{name}")
    for name in SIDE_CAR_NAMES:
        _validate_declared_file(candidate_root, name, candidate_files.get(name))

    translation_manifest = _mapping(
        candidate_manifest.get("translations"),
        "translation_manifest_missing",
    )
    assets = load_translation_runtime_assets(ROOT / "config")
    translation_prompt_sha256 = sha256_hex(assets.translation_prompt_bytes)
    translation_terms_sha256 = assets.terms_sha256
    boundaries = _mapping(candidate_manifest.get("boundaries"), "candidate_boundaries_invalid")
    declared_provider_call = candidate_manifest.get("provider_call")
    _require(
        source_manifest.get("schema_version") == "reddit_voc_site_snapshot_manifest_v3"
        and source_manifest.get("provider_call") is False
        and candidate_manifest.get("schema_version") == source_manifest.get("schema_version")
        and candidate_manifest.get("dataset_version") != source_manifest.get("dataset_version")
        and candidate_manifest.get("status") == "validated_local_translation_candidate"
        and candidate_manifest.get("artifact_stage") == "local_translation_candidate"
        and candidate_manifest.get("consumption_status")
        == "eligible_for_frontend_candidate_consumption"
        and candidate_manifest.get("promotable") is False
        and isinstance(declared_provider_call, bool)
        and candidate_manifest.get("production_unchanged") is True
        and candidate_manifest.get("database_write") is False
        and candidate_manifest.get("remote_write") is False
        and candidate_manifest.get("deploy") is False
        and candidate_manifest.get("live_send") is False
        and boundaries.get("provider_call") is declared_provider_call
        and boundaries.get("database_write") is False
        and boundaries.get("remote_write") is False
        and boundaries.get("deploy") is False
        and boundaries.get("live_send") is False
        and boundaries.get("production_unchanged") is True,
        "candidate_status_or_boundary_invalid",
    )
    _require(
        translation_manifest.get("schema_version") == MANIFEST_EXTENSION_SCHEMA
        and translation_manifest.get("provider") == "deepseek"
        and translation_manifest.get("model") == DEEPSEEK_MODEL
        and translation_manifest.get("provider_call") is declared_provider_call
        and translation_manifest.get("provider_authorization_id") == authorization_id
        and translation_manifest.get("source_dataset_version")
        == source_manifest.get("dataset_version")
        and translation_manifest.get("source_public_manifest_sha256")
        == source_manifest_sha256
        and translation_manifest.get("translation_prompt_sha256")
        == translation_prompt_sha256
        and translation_manifest.get("translation_terms_sha256")
        == translation_terms_sha256
        and translation_manifest.get("checkpoint_sha256") == _sha256(checkpoint_path)
        and translation_manifest.get("provider_attempt_log_sha256")
        == _sha256(attempt_log_path)
        and translation_manifest.get("quality_gate") == "deterministic_contract_v1"
        and translation_manifest.get("semantic_validation") == "not_run"
        and translation_manifest.get("independent_human_review") is False,
        "translation_manifest_binding_invalid",
    )

    posts = _load_json(source_root / "posts-public.json", expected_type=list)
    comments = _load_json(source_root / "comments-public.json", expected_type=list)
    items = build_translation_items(posts, comments, include_comments=True)
    item_by_id = {item.stable_id: item for item in items}
    reuse_translations: dict[str, str] = {}
    reuse_provenance: dict[str, object] | None = None
    if reuse_candidate_root is not None:
        reuse_translations, reuse_provenance = _load_reuse_candidate(
            reuse_candidate_root,
            items=items,
            translation_prompt_sha256=translation_prompt_sha256,
            translation_terms_sha256=translation_terms_sha256,
            terms=assets.terms,
        )
    translations = _load_checkpoint(
        checkpoint_path,
        source_manifest_sha256=source_manifest_sha256,
        item_by_id=item_by_id,
        translation_prompt_sha256=translation_prompt_sha256,
        translation_terms_sha256=translation_terms_sha256,
        reuse_translations=reuse_translations,
        reuse_provenance=reuse_provenance,
    )
    post_item_ids = {
        item.stable_id for item in items if item.item_type in {"title", "body"}
    }
    translated_comment_ids = {
        item.stable_id
        for item in items
        if item.item_type == "comment" and item.stable_id in translations
    }
    _require(
        set(translations).issubset(item_by_id)
        and post_item_ids.issubset(translations),
        "checkpoint_translation_coverage_invalid",
    )
    _validate_translation_map(items=items, translations=translations, terms=assets.terms)

    (
        attempt_count,
        usage,
        successful_outputs,
        observed_http_statuses,
        execution_authorization_ids,
    ) = _validate_attempt_log(
        attempt_log_path,
        authorization_id=authorization_id,
        source_manifest_sha256=source_manifest_sha256,
        translation_prompt_sha256=translation_prompt_sha256,
        translation_terms_sha256=translation_terms_sha256,
    )
    declared_execution_authorization_ids = translation_manifest.get(
        "provider_execution_authorization_ids"
    )
    if declared_execution_authorization_ids is None:
        _require(
            execution_authorization_ids == (authorization_id,),
            "translation_execution_authorization_chain_invalid",
        )
    else:
        _require(
            declared_execution_authorization_ids
            == list(execution_authorization_ids),
            "translation_execution_authorization_chain_invalid",
        )
    reused_ids = _checkpoint_reused_ids(checkpoint_path)
    declared_reuse = translation_manifest.get("reuse")
    if reuse_provenance is None:
        _require(not reused_ids and declared_reuse is None, "translation_reuse_binding_invalid")
    else:
        _require(
            reused_ids.issubset(reuse_translations)
            and declared_reuse
            == {**reuse_provenance, "reused_items": len(reused_ids)},
            "translation_reuse_binding_invalid",
        )
    _require(
        declared_provider_call is (attempt_count > 0),
        "translation_provider_call_boundary_invalid",
    )
    response_batches: dict[str, dict[str, str]] = {}
    response_declared_hashes: dict[str, set[str]] = {}
    for line_number, raw in enumerate(checkpoint_path.read_text(encoding="utf-8").splitlines(), 1):
        row = json.loads(raw)
        sequence = row.get("provider_attempt_sequence")
        if sequence is not None:
            response_id = row.get("provider_response_id")
            output_sha256 = row.get("provider_output_sha256")
            stable_id = row.get("stable_id")
            _require(
                isinstance(response_id, str)
                and response_id in successful_outputs
                and isinstance(output_sha256, str)
                and output_sha256 == successful_outputs[response_id]
                and isinstance(stable_id, str),
                f"checkpoint_attempt_unbound:{line_number}",
            )
            response_batches.setdefault(response_id, {})[stable_id] = row["zh"]
            response_declared_hashes.setdefault(response_id, set()).add(output_sha256)
    for response_id, batch_translations in response_batches.items():
        _require(
            len(response_declared_hashes[response_id]) == 1
            and translation_output_sha256(batch_translations)
            == successful_outputs[response_id],
            f"checkpoint_provider_output_mismatch:{response_id}",
        )

    coverage = _mapping(translation_manifest.get("coverage"), "translation_coverage_invalid")
    manifest_usage = _mapping(translation_manifest.get("usage"), "translation_usage_invalid")
    comments_status = coverage.get("comments_status")
    comments_unavailable_reason = coverage.get("comments_unavailable_reason")
    complete_comment_coverage = len(translated_comment_ids) == len(comments)
    _require(
        coverage.get("posts") == len(posts)
        and coverage.get("post_titles") == len(posts)
        and coverage.get("post_contents") == len(posts)
        and coverage.get("post_translation_status") == "complete"
        and coverage.get("comments") == len(translated_comment_ids)
        and coverage.get("comments_total") == len(comments)
        and coverage.get("translated_items") == len(translations)
        and (
            complete_comment_coverage
            and comments_status == "complete"
            and comments_unavailable_reason is None
            or not complete_comment_coverage
            and comments_status == "partial"
            and comments_unavailable_reason == "provider_http_402_balance_blocked"
            and 402 in observed_http_statuses
        )
        and translation_manifest.get("provider_attempts") == attempt_count
        and dict(manifest_usage) == usage
        and usage["total_tokens"]
        == usage["prompt_tokens"] + usage["completion_tokens"],
        "translation_coverage_or_usage_invalid",
    )

    post_sidecar = _load_json(candidate_root / SIDE_CAR_NAMES[0], expected_type=dict)
    comment_sidecar = _load_json(candidate_root / SIDE_CAR_NAMES[1], expected_type=dict)
    post_rows = _validate_envelope(
        post_sidecar,
        entity_type="post",
        candidate_manifest=candidate_manifest,
        translation_manifest=translation_manifest,
    )
    comment_rows = _validate_envelope(
        comment_sidecar,
        entity_type="comment",
        candidate_manifest=candidate_manifest,
        translation_manifest=translation_manifest,
    )
    _validate_post_sidecar(post_rows, posts=posts, translations=translations)
    _require(
        len(comment_rows) == len(translated_comment_ids),
        "comment_translation_coverage_invalid",
    )
    _validate_comment_sidecar(comment_rows, comments=comments, translations=translations)

    return {
        "schema_version": VALIDATION_RECEIPT_SCHEMA,
        "status": "passed_local_candidate_only",
        "validated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_dataset_version": source_manifest["dataset_version"],
        "source_public_manifest_sha256": source_manifest_sha256,
        "candidate_dataset_version": candidate_manifest["dataset_version"],
        "candidate_public_manifest_sha256": candidate_manifest_sha256,
        "provider_authorization_id": authorization_id,
        "provider_execution_authorization_ids": list(
            execution_authorization_ids
        ),
        "provider_attempts": attempt_count,
        "reused_items": len(reused_ids),
        "translated_items": len(translations),
        "posts": len(posts),
        "comments_translated": len(translated_comment_ids),
        "comments_total": len(comments),
        "checks": {
            "source_files_byte_identical": True,
            "sidecar_integrity_passed": True,
            "source_hash_binding_passed": True,
            "checkpoint_binding_passed": True,
            "prompt_and_terms_binding_passed": True,
            "provider_attempt_ledger_passed": True,
            "deterministic_translation_gate_passed": True,
            "complete_post_coverage": True,
            "complete_comment_coverage": complete_comment_coverage,
            "partial_comments_reason_evidence_bound": (
                complete_comment_coverage or 402 in observed_http_statuses
            ),
        },
        "quality_boundaries": {
            "semantic_validation": "not_run",
            "independent_human_review": False,
            "promotable": False,
        },
        "side_effect_boundaries": {
            "provider_call": False,
            "database_write": False,
            "remote_write": False,
            "deploy": False,
            "live_send": False,
            "production_unchanged": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--attempt-log", type=Path, required=True)
    parser.add_argument("--provider-authorization-id", required=True)
    parser.add_argument("--reuse-candidate-root", type=Path)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    receipt = validate_candidate(
        source_root=args.source_root,
        candidate_root=args.candidate_root,
        checkpoint_path=args.checkpoint,
        attempt_log_path=args.attempt_log,
        expected_authorization_id=args.provider_authorization_id,
        reuse_candidate_root=args.reuse_candidate_root,
    )
    _write_json(args.receipt, receipt)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
