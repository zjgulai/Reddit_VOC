from __future__ import annotations

import json
import re
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Collection, Literal, Mapping, Sequence, TypeVar

from .report_contracts import (
    AttemptBudget,
    AttemptEvidence,
    AttemptReservationSink,
    JsonCompletionClient,
    MonotonicDeadline,
    Phase,
    TokenUsage,
    canonical_json_bytes,
    load_translation_terms_document,
    read_regular_utf8,
    sha256_hex,
)


_ID_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_URL = re.compile(r"https?://[^\s<>()]+")
_MARKDOWN_LINK_ONLY = re.compile(
    r"^\s*\[(?P<label>[^\]\r\n]+)\]\("
    r"(?P<url>https?://(?P<host>[^/\s<>()]+)[^\s<>()]*)\)\s*$",
    re.IGNORECASE,
)
_OPAQUE_MEDIA_ONLY = re.compile(
    r"^\s*!\[(?i:gif|img|image|video)\]\([A-Za-z0-9._|-]+\)(?:\s|[^\w\s])*$"
)
_REDDIT_REFERENCE = re.compile(r"\b[ru]/[A-Za-z0-9_-]+\b")
_NUMBER = re.compile(r"(?<![A-Za-z0-9_])\d+(?:[.,]\d+)?(?:%?)(?![A-Za-z0-9_])")
_KNOWN_SOURCE_EQUAL_BRANDS = (
    "Baby Buddha",
    "Boppy",
    "eBay",
    "Eufy",
    "Evelyn and Bobbie",
    "Infant Optics",
    "Kindred Bravely",
    "Lacevo",
    "Molke",
    "Spectra",
    "Sugar Candy",
    "Bravissimo",
    "Ubbi",
    "Yoto",
)
_KNOWN_SOURCE_EQUAL_NOISE = frozenset(
    {
        "&amp;’ ha m my",
        "Illuminati Hotties - Let Me Do One More\n\n"
        "Julien Baker - Little Oblivions\n\n"
        "Snail Mail - Valentine\n\n"
        "Black Country, New Road - For the First Time",
        "Mom Freida",
        "Omega Sayori Undertale ",
        "Sayori :3",
        "Wudl ",
        "Ɛ: sayori :3",
    }
)
_KNOWN_PROPER_NAME_ONLY = re.compile(
    r"^\s*(?i:Boon|Boppy|Bravissimo|Bugaboo Donkey 6|Cybex Gazelle|Eufy|Evelyn and Bobbie|Lacevo|Magyarinda mini|Minbie|Mockingbird|Molke|Momcozy BreezyClear Pro|Moody Beauty|Moonycozy|Owlet|Pumpables genie advanced|Signature Pro|Sugar Candy|The Zomee|Tripp Trap|Tyco|Uninom Opera|Xbox|Yoto)\s*[!?.,*]*\s*$"
)
_OPAQUE_IDENTIFIER_ONLY = re.compile(
    r"^\s*(?:"
    r"(?=[A-Za-z0-9._-]*[A-Z][A-Za-z0-9._-]*[A-Z0-9])"
    r"[A-Za-z0-9._-]+"
    r"|[A-Za-z]+\d[A-Za-z0-9._-]*"
    r"|[A-Z][A-Za-z._-]+\s+[A-Za-z]?\d[A-Za-z0-9._-]*"
    r")\s*[!?.,]*\s*$"
)
_OPAQUE_MODEL_NAME_ONLY = re.compile(
    r"^\s*(?i:The\s+)?[A-Za-z]+\d[A-Za-z0-9._-]*"
    r"(?:\s+(?i:Pro|Plus|Lite))?\s*[!?.,]*\s*$"
)
_BOT_COMMAND_ONLY = re.compile(r"^\s*![A-Za-z][A-Za-z0-9_-]*\s*$")
_OPAQUE_REDDIT_REFERENCE_ONLY = re.compile(
    r"^\s*/?[ru]/(?:[A-Za-z0-9_-]+|\[redacted_user\])\s*$", re.IGNORECASE
)
_MODEL = "deepseek-v4-flash"
_ZERO_USAGE = TokenUsage(0, 0, 0, 0, 0)


@dataclass(frozen=True)
class SourceSignalRules:
    negation: tuple[str, ...]
    comparison: tuple[str, ...]
    sentiment: tuple[str, ...]


@dataclass(frozen=True)
class TranslationTerms:
    schema_version: str
    preserve_exact: tuple[str, ...]
    case_sensitive_terms: tuple[str, ...]
    case_insensitive_terms: tuple[str, ...]
    model_patterns: tuple[str, ...]
    unit_patterns: tuple[str, ...]
    allow_source_equal_patterns: tuple[str, ...]
    source_signal_rules: SourceSignalRules


@dataclass(frozen=True)
class TranslationRuntimeAssets:
    terms: TranslationTerms
    translation_prompt: str
    validator_prompt: str
    translation_prompt_bytes: bytes
    validator_prompt_bytes: bytes
    terms_sha256: str
    source_signal_rules_sha256: str
    prompt_version: str
    validator_prompt_version: str


@dataclass(frozen=True)
class TranslationItem:
    stable_id: str
    item_type: Literal["title", "body", "comment"]
    post_id: str
    comment_id: str | None
    source_text: str
    input_sha256: str


@dataclass(frozen=True)
class PostTranslationBundle:
    post_id: str
    items: tuple[TranslationItem, ...]


@dataclass(frozen=True)
class SourceSignals:
    negation: tuple[str, ...]
    comparison: tuple[str, ...]
    sentiment: tuple[str, ...]


@dataclass(frozen=True)
class SemanticVerdict:
    meaning_preserved: bool
    negation_preserved: bool
    comparison_preserved: bool
    sentiment_preserved: bool
    hallucination_free: bool
    critical_error_codes: tuple[str, ...]


@dataclass(frozen=True)
class ValidatedTranslationItem:
    stable_id: str
    item_type: Literal["title", "body", "comment"]
    post_id: str
    comment_id: str | None
    input_sha256: str
    zh: str
    source_signals: SourceSignals
    entity_status: str


@dataclass(frozen=True)
class CompletionEvidence:
    phase: Phase
    response_id: str
    actual_model: str
    system_fingerprint: str | None
    finish_reason: str
    usage: TokenUsage
    attempts: tuple[AttemptEvidence, ...]


@dataclass(frozen=True)
class PhaseEvidence:
    phase: Phase
    request_count: int
    retry_count: int
    attempt_made: bool
    duration_ms: int
    usage: TokenUsage
    completions: tuple[CompletionEvidence, ...]
    attempts: tuple[AttemptEvidence, ...] = ()


@dataclass(frozen=True)
class ValidatedItemEvidence:
    stable_id: str
    item_type: str
    post_id: str
    comment_id: str | None
    input_sha256: str
    zh: str | None
    source_signals: SourceSignals
    semantic_verdict: SemanticVerdict | None
    entity_status: str
    status: str
    error_type: str | None
    error_codes: tuple[str, ...]


@dataclass(frozen=True)
class VerifiedCacheManifest:
    run_id: str
    artifact_version_id: str
    bundle_sha256: str
    is_current: bool
    manifest: Mapping[str, object]


@dataclass(frozen=True)
class TranslationPipelineResult:
    translations: Mapping[str, str]
    verdicts: Mapping[str, SemanticVerdict]
    items: tuple[ValidatedItemEvidence, ...]
    translation_input_fingerprint: str
    translation_cache_key: str
    translation_output_sha256: str
    validator_cache_key: str
    validator_output_sha256: str
    translation_reused: bool
    semantic_validation_reused: bool
    attempts: tuple[AttemptEvidence, ...]
    translation_phase: PhaseEvidence
    semantic_validation_phase: PhaseEvidence
    total_usage: TokenUsage
    duration_ms: int


class TranslationPipelineBlocked(RuntimeError):
    def __init__(
        self,
        *,
        reason_codes: Sequence[str],
        attempts: Sequence[AttemptEvidence],
        translation_phase: PhaseEvidence,
        semantic_validation_phase: PhaseEvidence,
        item_evidence: Sequence[ValidatedItemEvidence],
    ) -> None:
        self.reason_codes = tuple(sorted(set(reason_codes)))
        self.attempts = tuple(attempts)
        self.translation_phase = translation_phase
        self.semantic_validation_phase = semantic_validation_phase
        self.item_evidence = tuple(item_evidence)
        super().__init__(",".join(self.reason_codes))


@dataclass(frozen=True)
class _PhaseCallResult:
    index: int
    completion: object
    parsed: Mapping[str, object]


class _PhaseWorkerFailure(RuntimeError):
    def __init__(self, cause: BaseException, *, completion: object | None = None) -> None:
        self.cause = cause
        self.completion = completion
        super().__init__(_reason_code(cause))


@dataclass(frozen=True)
class _DeterministicItemFailure:
    stable_id: str
    input_sha256: str
    reason_code: str
    item_error_codes: tuple[str, ...]


class _DeterministicTranslationFailure(ValueError):
    def __init__(self, failures: Sequence[_DeterministicItemFailure]) -> None:
        if not failures:
            raise ValueError("deterministic_failure_evidence_required")
        self.failures = tuple(failures)
        self.reason_codes = tuple(sorted({failure.reason_code for failure in failures}))
        self.reason_code = (
            self.reason_codes[0]
            if len(self.reason_codes) == 1
            else "deterministic_translation_failed"
        )
        super().__init__(",".join(self.reason_codes))


@dataclass(frozen=True)
class _ProtectedReplacement:
    marker: str
    source_value: str
    error_codes: tuple[str, ...]


@dataclass(frozen=True)
class _ProtectedText:
    provider_text: str
    namespace: str
    replacements: tuple[_ProtectedReplacement, ...]


_T = TypeVar("_T")


def normalize_source_text(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError("source_text_must_be_string")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def build_post_translation_bundle(
    post: Mapping[str, object],
    comments: Sequence[Mapping[str, object]],
) -> PostTranslationBundle:
    post_id = _required_id(post.get("post_id"), field_name="post_id")
    items: list[TranslationItem] = [
        _translation_item(
            stable_id=f"post:{post_id}:title",
            item_type="title",
            post_id=post_id,
            comment_id=None,
            source=post.get("title"),
        ),
        _translation_item(
            stable_id=f"post:{post_id}:body",
            item_type="body",
            post_id=post_id,
            comment_id=None,
            source=post.get("selftext"),
        ),
    ]
    seen = {item.stable_id for item in items}
    for comment in comments:
        comment_id = _required_id(comment.get("comment_id"), field_name="comment_id")
        comment_post_id = comment.get("post_id")
        if comment_post_id is not None and str(comment_post_id) != post_id:
            raise ValueError("comment_post_id_mismatch")
        stable_id = f"comment:{comment_id}:body"
        if stable_id in seen:
            raise ValueError("duplicate_stable_id")
        seen.add(stable_id)
        items.append(
            _translation_item(
                stable_id=stable_id,
                item_type="comment",
                post_id=post_id,
                comment_id=comment_id,
                source=comment.get("body"),
            )
        )
    return PostTranslationBundle(post_id=post_id, items=tuple(items))


def translation_input_fingerprint(
    bundles: Sequence[PostTranslationBundle],
) -> str:
    all_items = [item for bundle in bundles for item in bundle.items]
    stable_ids = [item.stable_id for item in all_items]
    if len(stable_ids) != len(set(stable_ids)):
        raise ValueError("duplicate_stable_id")
    preimage = [
        {
            "stable_id": item.stable_id,
            "item_type": item.item_type,
            "post_id": item.post_id,
            "comment_id": item.comment_id,
            "source_text": item.source_text,
        }
        for item in sorted(all_items, key=lambda value: value.stable_id)
    ]
    return sha256_hex(canonical_json_bytes(preimage))


def load_translation_runtime_assets(config_root: Path) -> TranslationRuntimeAssets:
    terms_document = load_translation_terms_document(config_root=config_root)
    translation_prompt = read_regular_utf8(
        trusted_root=config_root,
        path=config_root / "prompts" / "deepseek-translation-v1.txt",
    )
    validator_prompt = read_regular_utf8(
        trusted_root=config_root,
        path=config_root / "prompts" / "deepseek-semantic-validator-v1.txt",
    )
    if "json" not in translation_prompt or "json" not in validator_prompt:
        raise ValueError("prompt_json_instruction_missing")
    terms = _typed_terms(terms_document)
    terms_bytes = canonical_json_bytes(terms_document)
    signal_document = terms_document["source_signal_rules"]
    signal_bytes = canonical_json_bytes(signal_document)
    translation_prompt_bytes = translation_prompt.encode("utf-8")
    validator_prompt_bytes = validator_prompt.encode("utf-8")
    terms_sha256 = sha256_hex(terms_bytes)
    signal_sha256 = sha256_hex(signal_bytes)
    translation_prompt_sha256 = sha256_hex(translation_prompt_bytes)
    validator_prompt_sha256 = sha256_hex(validator_prompt_bytes)
    return TranslationRuntimeAssets(
        terms=terms,
        translation_prompt=translation_prompt,
        validator_prompt=validator_prompt,
        translation_prompt_bytes=translation_prompt_bytes,
        validator_prompt_bytes=validator_prompt_bytes,
        terms_sha256=terms_sha256,
        source_signal_rules_sha256=signal_sha256,
        prompt_version=build_prompt_version(
            translation_prompt_sha256=translation_prompt_sha256,
            translation_terms_sha256=terms_sha256,
        ),
        validator_prompt_version=build_validator_prompt_version(
            source_signal_rules_sha256=signal_sha256,
            translation_terms_sha256=terms_sha256,
            validator_prompt_sha256=validator_prompt_sha256,
        ),
    )


def build_prompt_version(
    *, translation_prompt_sha256: str, translation_terms_sha256: str
) -> str:
    return sha256_hex(
        canonical_json_bytes(
            {
                "translation_prompt_sha256": translation_prompt_sha256,
                "translation_terms_sha256": translation_terms_sha256,
            }
        )
    )


def build_validator_prompt_version(
    *,
    source_signal_rules_sha256: str,
    translation_terms_sha256: str,
    validator_prompt_sha256: str,
) -> str:
    return sha256_hex(
        canonical_json_bytes(
            {
                "source_signal_rules_sha256": source_signal_rules_sha256,
                "translation_terms_sha256": translation_terms_sha256,
                "validator_prompt_sha256": validator_prompt_sha256,
            }
        )
    )


def parse_translation_content(
    content: str,
    *,
    expected_ids: Collection[str],
    allow_extra_fields: bool = False,
) -> dict[str, str]:
    value = _strict_json(content)
    if not isinstance(value, Mapping) or (
        "translations" not in value
        or (not allow_extra_fields and set(value) != {"translations"})
    ):
        raise ValueError("translation_schema_invalid")
    rows = value.get("translations")
    if not isinstance(rows, list):
        raise ValueError("translation_schema_invalid")
    expected = set(expected_ids)
    result: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, Mapping) or (
            not {"id", "zh"}.issubset(row)
            or (not allow_extra_fields and set(row) != {"id", "zh"})
        ):
            raise ValueError("translation_schema_invalid")
        stable_id = row.get("id")
        zh = row.get("zh")
        if not isinstance(stable_id, str) or not isinstance(zh, str):
            raise ValueError("translation_schema_invalid")
        if stable_id not in expected:
            raise ValueError("translation_unknown_id")
        if stable_id in result:
            raise ValueError("translation_duplicate_id")
        result[stable_id] = zh
    if set(result) != expected:
        raise ValueError("translation_missing_id")
    return result


def validate_deterministic_translation(
    bundle: PostTranslationBundle,
    zh_by_id: Mapping[str, str],
    terms: TranslationTerms,
) -> tuple[ValidatedTranslationItem, ...]:
    expected = {item.stable_id for item in bundle.items}
    if set(zh_by_id) != expected:
        raise ValueError("translation_id_set_mismatch")
    result: list[ValidatedTranslationItem] = []
    failures: list[_DeterministicItemFailure] = []
    for item in bundle.items:
        candidate = zh_by_id[item.stable_id]
        if not isinstance(candidate, str):
            failures.append(
                _deterministic_item_failure(item, "translation_schema_invalid")
            )
            continue
        source = item.source_text
        if not source:
            if candidate != "":
                failures.append(
                    _deterministic_item_failure(
                        item, "empty_source_translation_mismatch"
                    )
                )
                continue
            result.append(
                ValidatedTranslationItem(
                    stable_id=item.stable_id,
                    item_type=item.item_type,
                    post_id=item.post_id,
                    comment_id=item.comment_id,
                    input_sha256=item.input_sha256,
                    zh=candidate,
                    source_signals=_detect_source_signals(source, terms.source_signal_rules),
                    entity_status="not_applicable",
                )
            )
            continue
        if not candidate.strip():
            failures.append(_deterministic_item_failure(item, "empty_translation"))
            continue
        source_equal_allowed = source == candidate and _source_equal_allowed(
            source, terms
        )
        if source == candidate and not source_equal_allowed:
            failures.append(
                _deterministic_item_failure(item, "source_equal_translation")
            )
            continue
        if (
            not source_equal_allowed
            and _requires_chinese(source)
            and _CJK.search(candidate) is None
        ):
            failures.append(
                _deterministic_item_failure(item, "non_chinese_translation")
            )
            continue
        protected = _protected_values(source, terms)
        missing_codes: set[str] = set()
        for value, case_sensitive, error_code in protected:
            present = value in candidate if case_sensitive else value.casefold() in candidate.casefold()
            if not present:
                missing_codes.add(error_code)
        if missing_codes:
            failures.append(
                _deterministic_item_failure(
                    item,
                    "protected_entity_changed",
                    item_error_codes=tuple(sorted(missing_codes)),
                )
            )
            continue
        result.append(
            ValidatedTranslationItem(
                stable_id=item.stable_id,
                item_type=item.item_type,
                post_id=item.post_id,
                comment_id=item.comment_id,
                input_sha256=item.input_sha256,
                zh=candidate,
                source_signals=_detect_source_signals(source, terms.source_signal_rules),
                entity_status="accepted" if protected else "not_applicable",
            )
        )
    if failures:
        raise _DeterministicTranslationFailure(failures)
    return tuple(result)


def _validate_deterministic_bundles(
    bundles: Sequence[PostTranslationBundle],
    translations: Mapping[str, str],
    terms: TranslationTerms,
) -> tuple[ValidatedTranslationItem, ...]:
    validated: list[ValidatedTranslationItem] = []
    failures: list[_DeterministicItemFailure] = []
    for bundle in bundles:
        try:
            validated.extend(
                validate_deterministic_translation(
                    bundle,
                    {
                        item.stable_id: translations[item.stable_id]
                        for item in bundle.items
                    },
                    terms,
                )
            )
        except _DeterministicTranslationFailure as exc:
            failures.extend(exc.failures)
    if failures:
        raise _DeterministicTranslationFailure(failures)
    return tuple(validated)


def parse_semantic_content(
    content: str, *, expected_ids: Collection[str]
) -> dict[str, SemanticVerdict]:
    value = _strict_json(content)
    if not isinstance(value, Mapping) or set(value) != {"verdicts"}:
        raise ValueError("semantic_schema_invalid")
    rows = value.get("verdicts")
    if not isinstance(rows, list):
        raise ValueError("semantic_schema_invalid")
    expected = set(expected_ids)
    required = {
        "id",
        "meaning_preserved",
        "negation_preserved",
        "comparison_preserved",
        "sentiment_preserved",
        "hallucination_free",
        "critical_error_codes",
    }
    result: dict[str, SemanticVerdict] = {}
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != required:
            raise ValueError("semantic_schema_invalid")
        stable_id = row.get("id")
        if not isinstance(stable_id, str) or stable_id not in expected:
            raise ValueError("semantic_unknown_id")
        if stable_id in result:
            raise ValueError("semantic_duplicate_id")
        boolean_keys = [
            "meaning_preserved",
            "negation_preserved",
            "comparison_preserved",
            "sentiment_preserved",
            "hallucination_free",
        ]
        if any(not isinstance(row.get(key), bool) for key in boolean_keys):
            raise ValueError("semantic_schema_invalid")
        error_codes = row.get("critical_error_codes")
        if (
            not isinstance(error_codes, list)
            or any(not isinstance(code, str) or not code for code in error_codes)
            or error_codes != sorted(set(error_codes))
        ):
            raise ValueError("semantic_schema_invalid")
        result[stable_id] = SemanticVerdict(
            meaning_preserved=row["meaning_preserved"],
            negation_preserved=row["negation_preserved"],
            comparison_preserved=row["comparison_preserved"],
            sentiment_preserved=row["sentiment_preserved"],
            hallucination_free=row["hallucination_free"],
            critical_error_codes=tuple(error_codes),
        )
    if set(result) != expected:
        raise ValueError("semantic_missing_id")
    return result


def require_semantic_acceptance(
    verdicts: Mapping[str, SemanticVerdict],
    *,
    expected_ids: Collection[str],
) -> None:
    expected = set(expected_ids)
    if set(verdicts) != expected:
        raise ValueError("semantic_gate_failed")
    for verdict in verdicts.values():
        if (
            not verdict.meaning_preserved
            or not verdict.negation_preserved
            or not verdict.comparison_preserved
            or not verdict.sentiment_preserved
            or not verdict.hallucination_free
            or verdict.critical_error_codes
        ):
            raise ValueError("semantic_gate_failed")


def translation_cache_key(
    *, translation_input_fingerprint: str, model: str, prompt_version: str
) -> str:
    return sha256_hex(
        canonical_json_bytes(
            {
                "translation_input_fingerprint": translation_input_fingerprint,
                "model": model,
                "prompt_version": prompt_version,
            }
        )
    )


def translation_output_sha256(translations: Mapping[str, str]) -> str:
    rows = [
        {"id": stable_id, "zh": translations[stable_id]}
        for stable_id in sorted(translations)
    ]
    return sha256_hex(canonical_json_bytes(rows))


def validator_cache_key(
    *,
    translation_input_fingerprint: str,
    translation_output_sha256: str,
    model: str,
    validator_prompt_version: str,
) -> str:
    return sha256_hex(
        canonical_json_bytes(
            {
                "translation_input_fingerprint": translation_input_fingerprint,
                "translation_output_sha256": translation_output_sha256,
                "model": model,
                "validator_prompt_version": validator_prompt_version,
            }
        )
    )


def validator_output_sha256(
    *,
    bundles: Sequence[PostTranslationBundle],
    translations: Mapping[str, str],
    source_signals: Mapping[str, SourceSignals],
    verdicts: Mapping[str, SemanticVerdict],
) -> str:
    item_by_id = {
        item.stable_id: item
        for bundle in bundles
        for item in bundle.items
    }
    expected = set(item_by_id)
    if set(translations) != expected or set(source_signals) != expected or set(verdicts) != expected:
        raise ValueError("validator_digest_id_set_mismatch")
    rows = []
    for stable_id in sorted(expected):
        signals = source_signals[stable_id]
        verdict = verdicts[stable_id]
        rows.append(
            {
                "id": stable_id,
                "input_sha256": item_by_id[stable_id].input_sha256,
                "zh_sha256": sha256_hex(translations[stable_id].encode("utf-8")),
                "source_signals": _signals_document(signals),
                "semantic_verdict": _verdict_document(verdict),
                "critical_error_codes": list(verdict.critical_error_codes),
            }
        )
    return sha256_hex(canonical_json_bytes(rows))


class TranslationService:
    def __init__(
        self,
        *,
        client: JsonCompletionClient | None,
        assets: TranslationRuntimeAssets,
        attempt_reservation_sink: AttemptReservationSink | None = None,
    ) -> None:
        self._client = client
        self._assets = assets
        self._attempt_reservation_sink = attempt_reservation_sink

    def run(
        self,
        bundles: Sequence[PostTranslationBundle],
        *,
        cached_manifests: Sequence[VerifiedCacheManifest],
        deadline_seconds: float = 300.0,
        max_attempts: int = 100,
    ) -> TranslationPipelineResult:
        if isinstance(deadline_seconds, bool) or not 0 < deadline_seconds <= 300:
            raise ValueError("translation_deadline_out_of_range")
        if isinstance(max_attempts, bool) or not 1 <= max_attempts <= 100:
            raise ValueError("translation_attempt_budget_out_of_range")
        for manifest in cached_manifests:
            if not isinstance(manifest, VerifiedCacheManifest):
                raise ValueError("cache_manifest_type_invalid")
        started_at = time.monotonic()
        input_fingerprint = translation_input_fingerprint(bundles)
        translation_key = translation_cache_key(
            translation_input_fingerprint=input_fingerprint,
            model=_MODEL,
            prompt_version=self._assets.prompt_version,
        )
        if not bundles:
            empty_digest = sha256_hex(canonical_json_bytes([]))
            validation_key = validator_cache_key(
                translation_input_fingerprint=input_fingerprint,
                translation_output_sha256=empty_digest,
                model=_MODEL,
                validator_prompt_version=self._assets.validator_prompt_version,
            )
            zero_translation = _empty_phase("translation")
            zero_semantic = _empty_phase("semantic_validation")
            return TranslationPipelineResult(
                translations={},
                verdicts={},
                items=(),
                translation_input_fingerprint=input_fingerprint,
                translation_cache_key=translation_key,
                translation_output_sha256=empty_digest,
                validator_cache_key=validation_key,
                validator_output_sha256=empty_digest,
                translation_reused=False,
                semantic_validation_reused=False,
                attempts=(),
                translation_phase=zero_translation,
                semantic_validation_phase=zero_semantic,
                total_usage=_ZERO_USAGE,
                duration_ms=0,
            )

        deadline = MonotonicDeadline(started_at + deadline_seconds)
        budget = AttemptBudget(
            max_attempts=max_attempts,
            reservation_sink=self._attempt_reservation_sink,
        )
        pending_items = _pending_item_evidence(bundles)
        zero_translation = _empty_phase("translation")
        zero_semantic = _empty_phase("semantic_validation")

        cached_translation = _load_cached_translation(
            cached_manifests=cached_manifests,
            bundles=bundles,
            expected_input_fingerprint=input_fingerprint,
            expected_cache_key=translation_key,
            terms=self._assets.terms,
        )
        translation_reused = cached_translation is not None
        if cached_translation is not None:
            translations, deterministic_items = cached_translation
            translation_phase = zero_translation
        else:
            if self._client is None:
                raise TranslationPipelineBlocked(
                    reason_codes=("translation_client_required",),
                    attempts=(),
                    translation_phase=zero_translation,
                    semantic_validation_phase=zero_semantic,
                    item_evidence=pending_items,
                )
            protected_text_by_id = {
                item.stable_id: _protect_translation_text(item, self._assets.terms)
                for bundle in bundles
                for item in bundle.items
            }
            translation_results, translation_errors = self._run_translation_calls(
                bundles=bundles,
                protected_text_by_id=protected_text_by_id,
                deadline=deadline,
                budget=budget,
            )
            translation_phase = _phase_evidence(
                "translation", translation_results, translation_errors
            )
            if translation_errors:
                raise TranslationPipelineBlocked(
                    reason_codes=tuple(_failure_reason(error) for error in translation_errors),
                    attempts=_phase_attempts(translation_phase),
                    translation_phase=translation_phase,
                    semantic_validation_phase=zero_semantic,
                    item_evidence=pending_items,
                )
            provider_translations = {}
            for result in sorted(translation_results, key=lambda value: value.index):
                provider_translations.update(result.parsed)
            try:
                translations = _restore_protected_translations(
                    bundles=bundles,
                    provider_translations=provider_translations,
                    protected_text_by_id=protected_text_by_id,
                )
                deterministic_items = _validate_deterministic_bundles(
                    bundles,
                    translations,
                    self._assets.terms,
                )
            except _DeterministicTranslationFailure as exc:
                repairable = tuple(
                    failure
                    for failure in exc.failures
                    if failure.reason_code == "source_equal_translation"
                )
                if len(repairable) != len(exc.failures) or not 1 <= len(repairable) <= 8:
                    raise TranslationPipelineBlocked(
                        reason_codes=exc.reason_codes,
                        attempts=_phase_attempts(translation_phase),
                        translation_phase=translation_phase,
                        semantic_validation_phase=zero_semantic,
                        item_evidence=_pending_item_evidence(
                            bundles,
                            failures=exc.failures,
                        ),
                    ) from exc
                repair_ids = {failure.stable_id for failure in repairable}
                repair_bundles = tuple(
                    PostTranslationBundle(
                        post_id=bundle.post_id,
                        items=tuple(
                            item for item in bundle.items if item.stable_id in repair_ids
                        ),
                    )
                    for bundle in bundles
                    if any(item.stable_id in repair_ids for item in bundle.items)
                )
                repair_results, repair_errors = self._run_translation_calls(
                    bundles=repair_bundles,
                    protected_text_by_id=protected_text_by_id,
                    deadline=deadline,
                    budget=budget,
                    repair_reason_codes_by_id={
                        failure.stable_id: (failure.reason_code,)
                        for failure in repairable
                    },
                )
                translation_phase = _phase_evidence(
                    "translation",
                    (*translation_results, *repair_results),
                    repair_errors,
                )
                if repair_errors:
                    raise TranslationPipelineBlocked(
                        reason_codes=tuple(
                            _failure_reason(error) for error in repair_errors
                        ),
                        attempts=_phase_attempts(translation_phase),
                        translation_phase=translation_phase,
                        semantic_validation_phase=zero_semantic,
                        item_evidence=_pending_item_evidence(
                            bundles,
                            failures=repairable,
                        ),
                    )
                for result in sorted(repair_results, key=lambda value: value.index):
                    provider_translations.update(result.parsed)
                try:
                    translations = _restore_protected_translations(
                        bundles=bundles,
                        provider_translations=provider_translations,
                        protected_text_by_id=protected_text_by_id,
                    )
                    deterministic_items = _validate_deterministic_bundles(
                        bundles,
                        translations,
                        self._assets.terms,
                    )
                except ValueError as repair_exc:
                    repair_failures = (
                        repair_exc.failures
                        if isinstance(repair_exc, _DeterministicTranslationFailure)
                        else ()
                    )
                    repair_reason_codes = (
                        repair_exc.reason_codes
                        if isinstance(repair_exc, _DeterministicTranslationFailure)
                        else (_reason_code(repair_exc),)
                    )
                    raise TranslationPipelineBlocked(
                        reason_codes=repair_reason_codes,
                        attempts=_phase_attempts(translation_phase),
                        translation_phase=translation_phase,
                        semantic_validation_phase=zero_semantic,
                        item_evidence=_pending_item_evidence(
                            bundles,
                            failures=repair_failures,
                        ),
                    ) from repair_exc
            except ValueError as exc:
                reason_codes = (
                    exc.reason_codes
                    if isinstance(exc, _DeterministicTranslationFailure)
                    else (_reason_code(exc),)
                )
                failures = (
                    exc.failures
                    if isinstance(exc, _DeterministicTranslationFailure)
                    else ()
                )
                raise TranslationPipelineBlocked(
                    reason_codes=reason_codes,
                    attempts=_phase_attempts(translation_phase),
                    translation_phase=translation_phase,
                    semantic_validation_phase=zero_semantic,
                    item_evidence=_pending_item_evidence(
                        bundles,
                        failures=failures,
                    ),
                ) from exc

        output_digest = translation_output_sha256(translations)
        validation_key = validator_cache_key(
            translation_input_fingerprint=input_fingerprint,
            translation_output_sha256=output_digest,
            model=_MODEL,
            validator_prompt_version=self._assets.validator_prompt_version,
        )
        signals_by_id = {
            item.stable_id: item.source_signals for item in deterministic_items
        }

        cached_verdicts = _load_cached_verdicts(
            cached_manifests=cached_manifests,
            bundles=bundles,
            translations=translations,
            source_signals=signals_by_id,
            expected_input_fingerprint=input_fingerprint,
            expected_translation_cache_key=translation_key,
            expected_translation_output_sha256=output_digest,
            expected_validator_cache_key=validation_key,
        )
        semantic_reused = cached_verdicts is not None
        if cached_verdicts is not None:
            verdicts = cached_verdicts
            semantic_phase = zero_semantic
        else:
            if self._client is None:
                accepted_without_verdict = _accepted_item_evidence(
                    deterministic_items, verdicts={}
                )
                raise TranslationPipelineBlocked(
                    reason_codes=("semantic_validation_client_required",),
                    attempts=_phase_attempts(translation_phase),
                    translation_phase=translation_phase,
                    semantic_validation_phase=zero_semantic,
                    item_evidence=accepted_without_verdict,
                )
            semantic_results, semantic_errors = self._run_semantic_calls(
                bundles=bundles,
                translations=translations,
                source_signals=signals_by_id,
                deadline=deadline,
                budget=budget,
            )
            semantic_phase = _phase_evidence(
                "semantic_validation", semantic_results, semantic_errors
            )
            if semantic_errors:
                raise TranslationPipelineBlocked(
                    reason_codes=tuple(_failure_reason(error) for error in semantic_errors),
                    attempts=(*_phase_attempts(translation_phase), *_phase_attempts(semantic_phase)),
                    translation_phase=translation_phase,
                    semantic_validation_phase=semantic_phase,
                    item_evidence=_accepted_item_evidence(
                        deterministic_items, verdicts={}
                    ),
                )
            verdicts = {}
            for result in sorted(semantic_results, key=lambda value: value.index):
                verdicts.update(result.parsed)
            try:
                require_semantic_acceptance(verdicts, expected_ids=translations)
            except ValueError as exc:
                raise TranslationPipelineBlocked(
                    reason_codes=("semantic_gate_failed",),
                    attempts=(*_phase_attempts(translation_phase), *_phase_attempts(semantic_phase)),
                    translation_phase=translation_phase,
                    semantic_validation_phase=semantic_phase,
                    item_evidence=_accepted_item_evidence(
                        deterministic_items, verdicts=verdicts
                    ),
                ) from exc

        validation_digest = validator_output_sha256(
            bundles=bundles,
            translations=translations,
            source_signals=signals_by_id,
            verdicts=verdicts,
        )
        item_evidence = _accepted_item_evidence(
            deterministic_items, verdicts=verdicts
        )
        all_attempts = (
            *_phase_attempts(translation_phase),
            *_phase_attempts(semantic_phase),
        )
        total_usage = _add_usage(
            translation_phase.usage, semantic_phase.usage
        )
        return TranslationPipelineResult(
            translations=dict(translations),
            verdicts=dict(verdicts),
            items=item_evidence,
            translation_input_fingerprint=input_fingerprint,
            translation_cache_key=translation_key,
            translation_output_sha256=output_digest,
            validator_cache_key=validation_key,
            validator_output_sha256=validation_digest,
            translation_reused=translation_reused,
            semantic_validation_reused=semantic_reused,
            attempts=all_attempts,
            translation_phase=translation_phase,
            semantic_validation_phase=semantic_phase,
            total_usage=total_usage,
            duration_ms=max(0, int((time.monotonic() - started_at) * 1000)),
        )

    def _run_translation_calls(
        self,
        *,
        bundles: Sequence[PostTranslationBundle],
        protected_text_by_id: Mapping[str, _ProtectedText],
        deadline: MonotonicDeadline,
        budget: AttemptBudget,
        repair_reason_codes_by_id: Mapping[str, tuple[str, ...]] | None = None,
    ) -> tuple[list[_PhaseCallResult], list[_PhaseWorkerFailure]]:
        assert self._client is not None

        expected_ids = {
            item.stable_id for bundle in bundles for item in bundle.items
        }
        if repair_reason_codes_by_id is not None:
            if set(repair_reason_codes_by_id) != expected_ids or any(
                not reason_codes
                for reason_codes in repair_reason_codes_by_id.values()
            ):
                raise ValueError("translation_repair_scope_invalid")

        def worker(index: int, bundle: PostTranslationBundle) -> _PhaseCallResult:
            payload = {
                "items": [
                    {
                        "id": item.stable_id,
                        "item_type": item.item_type,
                        "post_id": item.post_id,
                        "comment_id": item.comment_id,
                        "input_sha256": item.input_sha256,
                        "source_text": protected_text_by_id[item.stable_id].provider_text,
                    }
                    for item in bundle.items
                ]
            }
            if repair_reason_codes_by_id is not None:
                payload["repair_context"] = {
                    "reason_codes_by_id": {
                        item.stable_id: list(
                            repair_reason_codes_by_id[item.stable_id]
                        )
                        for item in bundle.items
                    },
                    "requirements": [
                        "return_a_materially_translated_chinese_value",
                        "do_not_return_the_source_text_unchanged",
                        "preserve_all_protected_placeholders_exactly",
                    ],
                }
            try:
                completion = self._client.complete_json(
                    phase="translation",
                    system_prompt=self._assets.translation_prompt,
                    user_payload=payload,
                    deadline=deadline,
                    attempt_budget=budget,
                )
            except Exception as exc:
                raise _PhaseWorkerFailure(exc) from exc
            try:
                parsed = parse_translation_content(
                    completion.content,
                    expected_ids={item.stable_id for item in bundle.items},
                )
            except Exception as exc:
                raise _PhaseWorkerFailure(exc, completion=completion) from exc
            return _PhaseCallResult(index=index, completion=completion, parsed=parsed)

        return _run_bounded(bundles, worker)

    def _run_semantic_calls(
        self,
        *,
        bundles: Sequence[PostTranslationBundle],
        translations: Mapping[str, str],
        source_signals: Mapping[str, SourceSignals],
        deadline: MonotonicDeadline,
        budget: AttemptBudget,
    ) -> tuple[list[_PhaseCallResult], list[_PhaseWorkerFailure]]:
        assert self._client is not None

        def worker(index: int, bundle: PostTranslationBundle) -> _PhaseCallResult:
            payload = {
                "items": [
                    {
                        "id": item.stable_id,
                        "item_type": item.item_type,
                        "post_id": item.post_id,
                        "comment_id": item.comment_id,
                        "input_sha256": item.input_sha256,
                        "source_text": item.source_text,
                        "candidate_zh": translations[item.stable_id],
                        "source_signals": _signals_document(
                            source_signals[item.stable_id]
                        ),
                    }
                    for item in bundle.items
                ]
            }
            try:
                completion = self._client.complete_json(
                    phase="semantic_validation",
                    system_prompt=self._assets.validator_prompt,
                    user_payload=payload,
                    deadline=deadline,
                    attempt_budget=budget,
                )
            except Exception as exc:
                raise _PhaseWorkerFailure(exc) from exc
            try:
                parsed = parse_semantic_content(
                    completion.content,
                    expected_ids={item.stable_id for item in bundle.items},
                )
            except Exception as exc:
                raise _PhaseWorkerFailure(exc, completion=completion) from exc
            return _PhaseCallResult(index=index, completion=completion, parsed=parsed)

        return _run_bounded(bundles, worker)


def _run_bounded(
    values: Sequence[_T],
    worker: Callable[[int, _T], _PhaseCallResult],
) -> tuple[list[_PhaseCallResult], list[_PhaseWorkerFailure]]:
    results: list[_PhaseCallResult] = []
    errors: list[_PhaseWorkerFailure] = []
    next_index = 0
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="reddit-voc-translation") as executor:
        active: dict[Future[_PhaseCallResult], int] = {}

        def submit_one(index: int) -> None:
            active[executor.submit(worker, index, values[index])] = index

        while next_index < len(values) and len(active) < 2:
            submit_one(next_index)
            next_index += 1

        fatal = False
        while active:
            done, _pending = wait(tuple(active), return_when=FIRST_COMPLETED)
            for future in sorted(done, key=lambda item: active[item]):
                active.pop(future)
                try:
                    results.append(future.result())
                except _PhaseWorkerFailure as exc:
                    errors.append(exc)
                    fatal = True
                except Exception as exc:
                    errors.append(_PhaseWorkerFailure(exc))
                    fatal = True
            if fatal:
                remaining = list(active)
                for future in remaining:
                    future.cancel()
                for future in sorted(remaining, key=lambda item: active[item]):
                    active.pop(future)
                    if future.cancelled():
                        continue
                    try:
                        results.append(future.result())
                    except _PhaseWorkerFailure as exc:
                        errors.append(exc)
                    except Exception as exc:
                        errors.append(_PhaseWorkerFailure(exc))
                break
            while next_index < len(values) and len(active) < 2:
                submit_one(next_index)
                next_index += 1
    return results, errors


def _phase_evidence(
    phase: Phase,
    results: Sequence[_PhaseCallResult],
    errors: Sequence[_PhaseWorkerFailure],
) -> PhaseEvidence:
    completions: list[CompletionEvidence] = []
    attempts: list[AttemptEvidence] = []
    usage_groups: list[TokenUsage] = []
    retry_count = 0
    for result in results:
        completion = result.completion
        completion_attempts = tuple(getattr(completion, "attempts", ()))
        attempts.extend(completion_attempts)
        retry_count += max(
            0,
            len(
                [
                    attempt
                    for attempt in completion_attempts
                    if attempt.outcome != "deadline_before_open"
                ]
            )
            - 1,
        )
        usage = getattr(completion, "usage", _ZERO_USAGE)
        if not isinstance(usage, TokenUsage):
            usage = _ZERO_USAGE
        usage_groups.append(usage)
        completions.append(_completion_evidence(phase, completion, usage, completion_attempts))
    for failure in errors:
        if failure.completion is not None:
            completion = failure.completion
            completion_attempts = tuple(getattr(completion, "attempts", ()))
            attempts.extend(completion_attempts)
            retry_count += max(
                0,
                len(
                    [
                        attempt
                        for attempt in completion_attempts
                        if attempt.outcome != "deadline_before_open"
                    ]
                )
                - 1,
            )
            usage = getattr(completion, "usage", _ZERO_USAGE)
            if not isinstance(usage, TokenUsage):
                usage = _ZERO_USAGE
            usage_groups.append(usage)
            completions.append(_completion_evidence(phase, completion, usage, completion_attempts))
            continue
        cause = failure.cause
        cause_attempts = tuple(getattr(cause, "attempts", ()))
        attempts.extend(cause_attempts)
        retry_count += max(
            0,
            len(
                [
                    attempt
                    for attempt in cause_attempts
                    if attempt.outcome != "deadline_before_open"
                ]
            )
            - 1,
        )
        usage = getattr(cause, "usage", _ZERO_USAGE)
        if not isinstance(usage, TokenUsage):
            usage = _ZERO_USAGE
        usage_groups.append(usage)
    ordered_attempts = tuple(sorted(attempts, key=lambda value: value.sequence))
    provider_attempts = tuple(
        attempt
        for attempt in ordered_attempts
        if attempt.outcome != "deadline_before_open"
    )
    return PhaseEvidence(
        phase=phase,
        request_count=len(provider_attempts),
        retry_count=retry_count,
        attempt_made=bool(provider_attempts),
        duration_ms=sum(attempt.duration_ms for attempt in ordered_attempts),
        usage=_sum_usage_values(usage_groups),
        completions=tuple(
            sorted(
                completions,
                key=lambda value: value.attempts[0].sequence if value.attempts else 0,
            )
        ),
        attempts=ordered_attempts,
    )


def _completion_evidence(
    phase: Phase,
    completion: object,
    usage: TokenUsage,
    attempts: tuple[AttemptEvidence, ...],
) -> CompletionEvidence:
    return CompletionEvidence(
        phase=phase,
        response_id=str(getattr(completion, "request_id", "")),
        actual_model=str(getattr(completion, "model", "")),
        system_fingerprint=getattr(completion, "system_fingerprint", None),
        finish_reason=str(getattr(completion, "finish_reason", "")),
        usage=usage,
        attempts=attempts,
    )


def _empty_phase(phase: Phase) -> PhaseEvidence:
    return PhaseEvidence(
        phase=phase,
        request_count=0,
        retry_count=0,
        attempt_made=False,
        duration_ms=0,
        usage=_ZERO_USAGE,
        completions=(),
        attempts=(),
    )


def _phase_attempts(evidence: PhaseEvidence) -> tuple[AttemptEvidence, ...]:
    return evidence.attempts


def _failure_reason(failure: _PhaseWorkerFailure) -> str:
    return _reason_code(failure.cause)


def _reason_code(error: BaseException) -> str:
    candidate = getattr(error, "reason_code", None)
    if isinstance(candidate, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,127}", candidate):
        return candidate
    message = str(error)
    if re.fullmatch(r"[a-z][a-z0-9_]{0,127}", message):
        return message
    return "translation_pipeline_error"


def _pending_item_evidence(
    bundles: Sequence[PostTranslationBundle],
    *,
    failures: Sequence[_DeterministicItemFailure] = (),
) -> tuple[ValidatedItemEvidence, ...]:
    failure_by_id = {failure.stable_id: failure for failure in failures}
    return tuple(
        ValidatedItemEvidence(
            stable_id=item.stable_id,
            item_type=item.item_type,
            post_id=item.post_id,
            comment_id=item.comment_id,
            input_sha256=item.input_sha256,
            zh=None,
            source_signals=SourceSignals((), (), ()),
            semantic_verdict=None,
            entity_status="pending",
            status="blocked" if item.stable_id in failure_by_id else "pending",
            error_type=(
                failure_by_id[item.stable_id].item_error_codes[0]
                if item.stable_id in failure_by_id
                else None
            ),
            error_codes=(
                failure_by_id[item.stable_id].item_error_codes
                if item.stable_id in failure_by_id
                else ()
            ),
        )
        for bundle in bundles
        for item in bundle.items
    )


def _accepted_item_evidence(
    items: Sequence[ValidatedTranslationItem],
    *,
    verdicts: Mapping[str, SemanticVerdict],
) -> tuple[ValidatedItemEvidence, ...]:
    return tuple(
        ValidatedItemEvidence(
            stable_id=item.stable_id,
            item_type=item.item_type,
            post_id=item.post_id,
            comment_id=item.comment_id,
            input_sha256=item.input_sha256,
            zh=item.zh,
            source_signals=item.source_signals,
            semantic_verdict=verdicts.get(item.stable_id),
            entity_status=item.entity_status,
            status="accepted" if item.stable_id in verdicts else "translated",
            error_type=None,
            error_codes=(),
        )
        for item in items
    )


def _load_cached_translation(
    *,
    cached_manifests: Sequence[VerifiedCacheManifest],
    bundles: Sequence[PostTranslationBundle],
    expected_input_fingerprint: str,
    expected_cache_key: str,
    terms: TranslationTerms,
) -> tuple[dict[str, str], tuple[ValidatedTranslationItem, ...]] | None:
    expected_items = {
        item.stable_id: item for bundle in bundles for item in bundle.items
    }
    for candidate in cached_manifests:
        manifest = candidate.manifest
        try:
            if (
                manifest.get("requested_model") != _MODEL
                or manifest.get("translation_input_fingerprint") != expected_input_fingerprint
                or manifest.get("translation_cache_key") != expected_cache_key
            ):
                continue
            rows = manifest.get("items")
            if not isinstance(rows, list):
                continue
            translations: dict[str, str] = {}
            for row in rows:
                if not isinstance(row, Mapping):
                    raise ValueError("cache_item_invalid")
                stable_id = row.get("stable_id")
                zh = row.get("zh")
                input_sha256 = row.get("input_sha256")
                if (
                    not isinstance(stable_id, str)
                    or stable_id not in expected_items
                    or stable_id in translations
                    or not isinstance(zh, str)
                    or input_sha256 != expected_items[stable_id].input_sha256
                ):
                    raise ValueError("cache_item_invalid")
                translations[stable_id] = zh
            if set(translations) != set(expected_items):
                continue
            output_digest = translation_output_sha256(translations)
            if manifest.get("translation_output_sha256") != output_digest:
                continue
            validated = _validate_deterministic_bundles(
                bundles,
                translations,
                terms,
            )
            return translations, validated
        except (KeyError, TypeError, ValueError):
            continue
    return None


def _load_cached_verdicts(
    *,
    cached_manifests: Sequence[VerifiedCacheManifest],
    bundles: Sequence[PostTranslationBundle],
    translations: Mapping[str, str],
    source_signals: Mapping[str, SourceSignals],
    expected_input_fingerprint: str,
    expected_translation_cache_key: str,
    expected_translation_output_sha256: str,
    expected_validator_cache_key: str,
) -> dict[str, SemanticVerdict] | None:
    expected_ids = set(translations)
    for candidate in cached_manifests:
        manifest = candidate.manifest
        try:
            if (
                manifest.get("requested_model") != _MODEL
                or manifest.get("translation_input_fingerprint") != expected_input_fingerprint
                or manifest.get("translation_cache_key") != expected_translation_cache_key
                or manifest.get("translation_output_sha256") != expected_translation_output_sha256
                or manifest.get("validator_cache_key") != expected_validator_cache_key
            ):
                continue
            rows = manifest.get("items")
            if not isinstance(rows, list):
                continue
            verdicts: dict[str, SemanticVerdict] = {}
            for row in rows:
                if not isinstance(row, Mapping):
                    raise ValueError("cache_item_invalid")
                stable_id = row.get("stable_id")
                if (
                    not isinstance(stable_id, str)
                    or stable_id not in expected_ids
                    or stable_id in verdicts
                    or row.get("zh") != translations[stable_id]
                ):
                    raise ValueError("cache_item_invalid")
                cached_signals = _signals_from_document(row.get("source_signals"))
                if cached_signals != source_signals[stable_id]:
                    raise ValueError("cache_signal_mismatch")
                verdicts[stable_id] = _verdict_from_cache_row(row)
            if set(verdicts) != expected_ids:
                continue
            require_semantic_acceptance(verdicts, expected_ids=expected_ids)
            digest = validator_output_sha256(
                bundles=bundles,
                translations=translations,
                source_signals=source_signals,
                verdicts=verdicts,
            )
            if manifest.get("validator_output_sha256") != digest:
                continue
            return verdicts
        except (KeyError, TypeError, ValueError):
            continue
    return None


def _signals_from_document(value: object) -> SourceSignals:
    if not isinstance(value, Mapping) or set(value) != {"negation", "comparison", "sentiment"}:
        raise ValueError("cache_signal_invalid")
    converted: dict[str, tuple[str, ...]] = {}
    for key in ["negation", "comparison", "sentiment"]:
        items = value.get(key)
        if (
            not isinstance(items, list)
            or any(not isinstance(item, str) for item in items)
            or items != sorted(set(items), key=lambda item: (item.casefold(), item))
        ):
            raise ValueError("cache_signal_invalid")
        converted[key] = tuple(items)
    return SourceSignals(**converted)


def _verdict_from_cache_row(row: Mapping[str, object]) -> SemanticVerdict:
    value = row.get("semantic_verdict")
    keys = {
        "meaning_preserved",
        "negation_preserved",
        "comparison_preserved",
        "sentiment_preserved",
        "hallucination_free",
    }
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ValueError("cache_verdict_invalid")
    if any(not isinstance(value.get(key), bool) for key in keys):
        raise ValueError("cache_verdict_invalid")
    errors = row.get("critical_error_codes")
    if not isinstance(errors, list) or any(not isinstance(item, str) for item in errors):
        raise ValueError("cache_verdict_invalid")
    return SemanticVerdict(
        meaning_preserved=value["meaning_preserved"],
        negation_preserved=value["negation_preserved"],
        comparison_preserved=value["comparison_preserved"],
        sentiment_preserved=value["sentiment_preserved"],
        hallucination_free=value["hallucination_free"],
        critical_error_codes=tuple(errors),
    )


def _signals_document(value: SourceSignals) -> dict[str, list[str]]:
    return {
        "negation": list(value.negation),
        "comparison": list(value.comparison),
        "sentiment": list(value.sentiment),
    }


def _verdict_document(value: SemanticVerdict) -> dict[str, bool]:
    return {
        "meaning_preserved": value.meaning_preserved,
        "negation_preserved": value.negation_preserved,
        "comparison_preserved": value.comparison_preserved,
        "sentiment_preserved": value.sentiment_preserved,
        "hallucination_free": value.hallucination_free,
    }


def _add_usage(left: TokenUsage, right: TokenUsage) -> TokenUsage:
    return TokenUsage(
        prompt_tokens=left.prompt_tokens + right.prompt_tokens,
        completion_tokens=left.completion_tokens + right.completion_tokens,
        prompt_cache_hit_tokens=left.prompt_cache_hit_tokens + right.prompt_cache_hit_tokens,
        prompt_cache_miss_tokens=left.prompt_cache_miss_tokens + right.prompt_cache_miss_tokens,
        total_tokens=left.total_tokens + right.total_tokens,
    )


def _sum_usage_values(values: Sequence[TokenUsage]) -> TokenUsage:
    total = _ZERO_USAGE
    for value in values:
        total = _add_usage(total, value)
    return total


def _required_id(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _ID_COMPONENT.fullmatch(value) is None:
        raise ValueError(f"invalid_{field_name}")
    return value


def _translation_item(
    *,
    stable_id: str,
    item_type: Literal["title", "body", "comment"],
    post_id: str,
    comment_id: str | None,
    source: object,
) -> TranslationItem:
    if source is None:
        source_text = ""
    elif isinstance(source, str):
        source_text = normalize_source_text(source)
    else:
        raise TypeError("source_text_must_be_string")
    return TranslationItem(
        stable_id=stable_id,
        item_type=item_type,
        post_id=post_id,
        comment_id=comment_id,
        source_text=source_text,
        input_sha256=sha256_hex(source_text.encode("utf-8")),
    )


def _typed_terms(document: Mapping[str, object]) -> TranslationTerms:
    rules = document["source_signal_rules"]
    return TranslationTerms(
        schema_version=str(document["schema_version"]),
        preserve_exact=tuple(document["preserve_exact"]),
        case_sensitive_terms=tuple(document["case_sensitive_terms"]),
        case_insensitive_terms=tuple(document["case_insensitive_terms"]),
        model_patterns=tuple(document["model_patterns"]),
        unit_patterns=tuple(document["unit_patterns"]),
        allow_source_equal_patterns=tuple(document["allow_source_equal_patterns"]),
        source_signal_rules=SourceSignalRules(
            negation=tuple(rules["negation"]),
            comparison=tuple(rules["comparison"]),
            sentiment=tuple(rules["sentiment"]),
        ),
    )


def _strict_json(content: str) -> object:
    if not isinstance(content, str):
        raise ValueError("json_content_not_string")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    try:
        return json.loads(content, object_pairs_hook=reject_duplicates)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid_json_content") from exc


def _source_equal_allowed(source: str, terms: TranslationTerms) -> bool:
    return source in _KNOWN_SOURCE_EQUAL_NOISE or _CJK.search(source) is not None or _KNOWN_PROPER_NAME_ONLY.fullmatch(
        source
    ) is not None or _OPAQUE_IDENTIFIER_ONLY.fullmatch(
        source
    ) is not None or _OPAQUE_MODEL_NAME_ONLY.fullmatch(
        source
    ) is not None or _BOT_COMMAND_ONLY.fullmatch(
        source
    ) is not None or _OPAQUE_REDDIT_REFERENCE_ONLY.fullmatch(source) is not None or any(
        re.fullmatch(pattern, source) is not None
        for pattern in terms.allow_source_equal_patterns
    ) or _brand_only_source(source, terms) or _brand_model_only_source(
        source, terms
    ) or _OPAQUE_MEDIA_ONLY.fullmatch(
        source
    ) is not None or _opaque_markdown_link_source(
        source
    ) or _opaque_proper_name_list_source(source, terms) or _opaque_named_url_source(
        source, terms
    ) or _opaque_url_identifier_source(source) or _opaque_url_list_source(source)


def _brand_model_only_source(source: str, terms: TranslationTerms) -> bool:
    normalized = source.strip().rstrip("!?.,")
    normalized = re.sub(r"(?i)^the\s+", "", normalized)
    for brand in (*terms.preserve_exact, *_KNOWN_SOURCE_EQUAL_BRANDS):
        prefix = f"{brand} "
        if not normalized.casefold().startswith(prefix.casefold()):
            continue
        remainder = normalized[len(prefix) :]
        if re.fullmatch(r"\d+%", remainder) is not None:
            return True
        if re.fullmatch(
            r"[A-Za-z][A-Za-z0-9.-]*\d[A-Za-z0-9.-]*"
            r"(?:\s+(?i:Pro|Plus|Lite)(?:-[A-Za-z0-9]+)?)?"
            r"(?:\s+\+\d+)?",
            remainder,
        ) is not None:
            return True
    return False


def _brand_only_source(source: str, terms: TranslationTerms) -> bool:
    normalized = source.strip()
    for brand in (*terms.preserve_exact, *_KNOWN_SOURCE_EQUAL_BRANDS):
        if not normalized.casefold().startswith(brand.casefold()):
            continue
        suffix = normalized[len(brand) :]
        if not suffix or re.search(r"[A-Za-z0-9\u3400-\u4dbf\u4e00-\u9fff]", suffix) is None:
            return True
    return False


def _opaque_markdown_link_source(source: str) -> bool:
    match = _MARKDOWN_LINK_ONLY.fullmatch(source)
    if match is None:
        return False
    label = match.group("label").strip().casefold().rstrip("/")
    url = match.group("url").strip().casefold().rstrip("/")
    host = match.group("host").strip().casefold().removeprefix("www.")
    return label == url or label.removeprefix("www.") == host


def _opaque_named_url_source(source: str, terms: TranslationTerms) -> bool:
    if _URL.search(source) is None:
        return False
    parts = tuple(
        part.strip()
        for part in _URL.sub("\n", source).splitlines()
        if part.strip()
    )
    return bool(parts) and all(
        _KNOWN_PROPER_NAME_ONLY.fullmatch(part)
        or _brand_model_only_source(part, terms)
        for part in parts
    )


def _opaque_proper_name_list_source(source: str, terms: TranslationTerms) -> bool:
    parts = tuple(
        part.strip()
        for part in re.split(r"[\r\n]+|,\s*", source)
        if part.strip()
    )
    return len(parts) >= 2 and all(
        _KNOWN_PROPER_NAME_ONLY.fullmatch(part)
        or _brand_model_only_source(part, terms)
        or _brand_only_source(part, terms)
        for part in parts
    )


def _opaque_url_identifier_source(source: str) -> bool:
    parts = source.strip().split()
    return (
        len(parts) == 2
        and _URL.fullmatch(parts[0]) is not None
        and _OPAQUE_IDENTIFIER_ONLY.fullmatch(parts[1]) is not None
    )


def _opaque_url_list_source(source: str) -> bool:
    if _URL.search(source) is None:
        return False
    residual = _URL.sub("", source)
    return not residual.strip(" \t\r\n,;|·…")


def _requires_chinese(source: str) -> bool:
    return bool(re.search(r"[A-Za-z]", source)) and _CJK.search(source) is None


def _protected_values(
    source: str, terms: TranslationTerms
) -> tuple[tuple[str, bool, str], ...]:
    values: list[tuple[str, bool, str]] = []
    for term in terms.preserve_exact:
        if term in {"r/", "u/"}:
            continue
        if term and term in source:
            values.append((term, True, "protected_named_entity_changed"))
    for term in terms.case_sensitive_terms:
        if term and term in source:
            values.append((term, True, "protected_model_changed"))
    for term in terms.case_insensitive_terms:
        if term and term.casefold() in source.casefold():
            match = re.search(re.escape(term), source, flags=re.IGNORECASE)
            if match:
                values.append(
                    (match.group(0), False, "protected_named_entity_changed")
                )
    for pattern in terms.model_patterns:
        values.extend(
            (match.group(0), False, "protected_model_changed")
            for match in re.finditer(pattern, source, flags=re.IGNORECASE)
        )
    for pattern in terms.unit_patterns:
        values.extend(
            (match.group(0), True, "protected_currency_changed")
            for match in re.finditer(pattern, source, flags=re.IGNORECASE)
        )
    values.extend(
        (match.group(0), True, "protected_url_changed")
        for match in _URL.finditer(source)
    )
    values.extend(
        (match.group(0), True, "protected_reddit_reference_changed")
        for match in _REDDIT_REFERENCE.finditer(source)
    )
    values.extend(
        (match.group(0), True, "protected_number_changed")
        for match in _NUMBER.finditer(source)
    )
    deduplicated: list[tuple[str, bool, str]] = []
    seen: set[tuple[str, bool]] = set()
    for item in values:
        identity = (item[0], item[1])
        if identity not in seen:
            seen.add(identity)
            deduplicated.append(item)
    return tuple(deduplicated)


def _protect_translation_text(
    item: TranslationItem,
    terms: TranslationTerms,
) -> _ProtectedText:
    source = item.source_text
    candidate_spans: list[tuple[int, int, str]] = []
    for value, case_sensitive, error_code in _protected_values(source, terms):
        flags = 0 if case_sensitive else re.IGNORECASE
        candidate_spans.extend(
            (match.start(), match.end(), error_code)
            for match in re.finditer(re.escape(value), source, flags=flags)
        )
    if not candidate_spans:
        return _ProtectedText(provider_text=source, namespace="", replacements=())

    merged_spans: list[tuple[int, int, set[str]]] = []
    for start, end, error_code in sorted(
        candidate_spans,
        key=lambda span: (span[0], span[1], span[2]),
    ):
        if merged_spans and start < merged_spans[-1][1]:
            prior_start, prior_end, prior_codes = merged_spans[-1]
            prior_codes.add(error_code)
            merged_spans[-1] = (prior_start, max(prior_end, end), prior_codes)
        else:
            merged_spans.append((start, end, {error_code}))

    salt = 0
    while True:
        namespace = sha256_hex(
            canonical_json_bytes(
                {
                    "input_sha256": item.input_sha256,
                    "placeholder_salt": salt,
                }
            )
        )[:16]
        if f"[[RVOC_P_{namespace}_" not in source:
            break
        salt += 1

    segments: list[str] = []
    replacements: list[_ProtectedReplacement] = []
    cursor = 0
    for ordinal, (start, end, error_codes) in enumerate(merged_spans, 1):
        marker = f"[[RVOC_P_{namespace}_{ordinal:06d}]]"
        segments.extend((source[cursor:start], marker))
        replacements.append(
            _ProtectedReplacement(
                marker=marker,
                source_value=source[start:end],
                error_codes=tuple(sorted(error_codes)),
            )
        )
        cursor = end
    segments.append(source[cursor:])
    return _ProtectedText(
        provider_text="".join(segments),
        namespace=namespace,
        replacements=tuple(replacements),
    )


def _restore_protected_translations(
    *,
    bundles: Sequence[PostTranslationBundle],
    provider_translations: Mapping[str, str],
    protected_text_by_id: Mapping[str, _ProtectedText],
) -> dict[str, str]:
    expected_items = {
        item.stable_id: item for bundle in bundles for item in bundle.items
    }
    if set(provider_translations) != set(expected_items):
        raise ValueError("translation_id_set_mismatch")
    if set(protected_text_by_id) != set(expected_items):
        raise ValueError("protected_placeholder_plan_mismatch")

    restored: dict[str, str] = {}
    failures: list[_DeterministicItemFailure] = []
    for stable_id, item in expected_items.items():
        candidate = provider_translations[stable_id]
        protected = protected_text_by_id[stable_id]
        expected_markers = {
            replacement.marker for replacement in protected.replacements
        }
        if protected.replacements:
            actual_markers = re.findall(
                rf"\[\[RVOC_P_{re.escape(protected.namespace)}_[0-9]{{6}}\]\]",
                candidate,
            )
            if (
                set(actual_markers) != expected_markers
                or len(actual_markers) != len(expected_markers)
                or any(candidate.count(marker) != 1 for marker in expected_markers)
            ):
                changed_categories = sorted(
                    {
                        error_code
                        for replacement in protected.replacements
                        if candidate.count(replacement.marker) != 1
                        for error_code in replacement.error_codes
                    }
                )
                failures.append(
                    _deterministic_item_failure(
                        item,
                        "protected_placeholder_changed",
                        item_error_codes=(
                            "protected_placeholder_changed",
                            *changed_categories,
                        ),
                    )
                )
                continue
        restored_candidate = candidate
        for replacement in protected.replacements:
            restored_candidate = restored_candidate.replace(
                replacement.marker,
                replacement.source_value,
                1,
            )
        restored[stable_id] = restored_candidate

    if failures:
        raise _DeterministicTranslationFailure(failures)
    return restored


def _deterministic_item_failure(
    item: TranslationItem,
    reason_code: str,
    *,
    item_error_codes: tuple[str, ...] | None = None,
) -> _DeterministicItemFailure:
    return _DeterministicItemFailure(
        stable_id=item.stable_id,
        input_sha256=item.input_sha256,
        reason_code=reason_code,
        item_error_codes=item_error_codes or (reason_code,),
    )


def _detect_source_signals(source: str, rules: SourceSignalRules) -> SourceSignals:
    return SourceSignals(
        negation=_signal_matches(source, rules.negation),
        comparison=_signal_matches(source, rules.comparison),
        sentiment=_signal_matches(source, rules.sentiment),
    )


def _signal_matches(source: str, patterns: Sequence[str]) -> tuple[str, ...]:
    matches: list[str] = []
    for pattern in patterns:
        matches.extend(match.group(0) for match in re.finditer(pattern, source, flags=re.IGNORECASE))
    return tuple(sorted(set(matches), key=lambda value: (value.casefold(), value)))
