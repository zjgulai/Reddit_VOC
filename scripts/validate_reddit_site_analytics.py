#!/usr/bin/env python3
"""Independently validate V2 Reddit VOC insights and report candidates.

The validator is deliberately read-only for all candidate inputs.  A successful
CLI invocation writes only the requested validation receipt.  It does not reuse
the analytics builder, call a provider, mutate a database, deploy, or switch a
release pointer.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import html
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable, Mapping, Sequence, cast
from zoneinfo import ZoneInfo


TIMEZONE_NAME = "Asia/Shanghai"
TIMEZONE = ZoneInfo(TIMEZONE_NAME)
PERIODS = ("daily", "weekly", "monthly")
COLLECTIONS = ("current", "archive")
ENTITY_TYPES = ("post", "comment")
PRODUCT_LEVELS = ("category", "product_family", "spu_exact")
BRAND_BINDINGS = {
    "brand_unbound",
    "competitor_sentence_bound",
    "momcozy_entity_reviewed",
    "momcozy_sentence_bound",
    "multi_brand_context",
}
MOMCOZY_BINDINGS = {"momcozy_sentence_bound", "momcozy_entity_reviewed"}
COMPARISON_STATUSES = {
    "comparable",
    "provisional_observed_sample",
    "unavailable",
}
FORBIDDEN_CAPABILITIES = {"market_share", "sov", "roi", "response_time"}
PROVISIONAL_REASON_CODES = {
    "comment_coverage_not_thread_complete",
    "event_time_coverage_partial",
    "search_has_next_truncates_window",
}
UNAVAILABLE_REASON_CODES = {
    *PROVISIONAL_REASON_CODES,
    "baseline_coverage_missing",
    "baseline_event_time_coverage_unavailable",
    "baseline_id_conflicts",
    "baseline_observation_absent_under_incomplete_coverage",
    "baseline_recent_partition",
    "baseline_schema_drift",
    "baseline_source_missing",
    "baseline_window_not_closed",
    "current_coverage_missing",
    "current_event_time_coverage_unavailable",
    "current_id_conflicts",
    "current_observation_absent_under_incomplete_coverage",
    "current_recent_partition",
    "current_schema_drift",
    "current_source_missing",
    "current_window_not_closed",
    "hydration_policy_version_mismatch",
    "observation_absent_under_incomplete_coverage",
    "product_catalog_version_mismatch",
    "query_profile_version_mismatch",
    "source_set_version_mismatch",
    "tag_dictionary_version_mismatch",
}
INSIGHTS_FILES = {"insights.json", "semantic-audit.json"}
SIDE_EFFECT_FIELDS = (
    "provider_call",
    "database_write",
    "live_send",
    "deploy",
)
REPORT_SIDE_EFFECT_FIELDS = (
    *SIDE_EFFECT_FIELDS,
    "webhook_send",
    "schedule_change",
)
SEMANTIC_PROJECTION_SCHEMA = "reddit_voc_semantic_governance_projection_v1"
SOURCE_SEMANTIC_AUDIT_SCHEMA = "reddit_voc_tag_semantic_audit_v1"
LEDGER_MANIFEST_SCHEMA = "reddit_voc_candidate_ledger_manifest_v2"
LEDGER_MANIFEST_STATUS = "a2_identity_closed_with_explicit_coverage_debt"
LEDGER_RECEIPT_SCHEMA = "reddit_voc_candidate_ledger_validation_receipt_v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"JSON cannot be loaded: {path}") from exc


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"object contract mismatch: {field}")
    return value


def _rows(value: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"list contract mismatch: {field}")
    output: list[dict[str, Any]] = []
    for index, row in enumerate(value):
        output.append(_object(row, f"{field}[{index}]"))
    return output


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _nonempty(value: Any, field: str) -> str:
    _check(isinstance(value, str) and bool(value.strip()), f"string contract mismatch: {field}")
    return value


def _integer(value: Any, field: str, *, minimum: int = 0) -> int:
    _check(
        isinstance(value, int) and not isinstance(value, bool) and value >= minimum,
        f"integer contract mismatch: {field}",
    )
    return value


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_datetime(value: Any, field: str) -> datetime:
    text = _nonempty(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"datetime contract mismatch: {field}") from exc
    _check(parsed.tzinfo is not None, f"naive datetime: {field}")
    return parsed


def _parse_utc(value: Any, field: str) -> datetime:
    return _parse_datetime(value, field).astimezone(timezone.utc)


def _tag_match(row: Mapping[str, Any], tag_id: str, field: str) -> dict[str, Any] | None:
    tagging = _object(row.get("tagging"), f"{field}.tagging")
    matches = _rows(tagging.get("matches"), f"{field}.tagging.matches")
    found = [match for match in matches if match.get("tag_id") == tag_id]
    _check(len(found) <= 1, f"duplicate tag match: {field}:{tag_id}")
    return found[0] if found else None


def _keyword_list(value: Any, field: str) -> list[str]:
    rows = _rows_or_strings(value, field)
    return [item.casefold().strip() for item in rows]


def _validate_projection_sources(
    *,
    semantic_governance_path: Path,
    source_semantic_audit_path: Path,
    expected_source_semantic_audit_sha256: str,
    candidate_ledger_manifest_path: Path,
    ledger_validation_receipt_path: Path,
    expected_ledger_validation_receipt_sha256: str,
    base_manifest: dict[str, Any],
    base_manifest_sha: str,
    tag_dictionary: dict[str, Any],
    posts: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    insights: dict[str, Any],
    projected_audit: dict[str, Any],
    insights_manifest: dict[str, Any],
    reports_manifest: dict[str, Any],
) -> dict[str, Any]:
    for value, field in (
        (expected_source_semantic_audit_sha256, "expected_source_semantic_audit_sha256"),
        (
            expected_ledger_validation_receipt_sha256,
            "expected_ledger_validation_receipt_sha256",
        ),
    ):
        _check(
            isinstance(value, str) and SHA256_RE.fullmatch(value) is not None,
            f"SHA contract mismatch: {field}",
        )

    projection = _object(_load(semantic_governance_path), "semantic_governance")
    projection_sha = _sha256(semantic_governance_path)
    _check(
        projection.get("schema_version") == SEMANTIC_PROJECTION_SCHEMA,
        "semantic projection schema mismatch",
    )
    _check(
        projection.get("projection_mode") == "governance_projection_no_new_review",
        "semantic projection mode mismatch",
    )
    for manifest, label in (
        (insights_manifest, "insights_manifest"),
        (reports_manifest, "reports_manifest"),
    ):
        _check(
            manifest.get("semantic_governance_sha256") == projection_sha,
            f"semantic projection hash lineage mismatch: {label}",
        )

    source_audit = _object(_load(source_semantic_audit_path), "source_semantic_audit")
    source_audit_sha = _sha256(source_semantic_audit_path)
    _check(
        source_audit_sha == expected_source_semantic_audit_sha256,
        "source semantic audit SHA mismatch",
    )
    _check(
        source_audit.get("schema_version") == SOURCE_SEMANTIC_AUDIT_SCHEMA,
        "source semantic audit schema mismatch",
    )
    source_binding = _object(projection.get("source_audit"), "projection.source_audit")
    _check(
        source_binding.get("sha256") == source_audit_sha,
        "semantic source audit binding mismatch",
    )
    for field in (
        "schema_version",
        "audit_version",
        "base_dataset_version",
        "base_manifest_sha256",
        "sample_sha256",
    ):
        _check(
            source_binding.get(field) == source_audit.get(field),
            f"semantic source audit field mismatch: {field}",
        )

    target = _object(projection.get("target_base"), "projection.target_base")
    _check(
        target.get("dataset_version") == base_manifest.get("dataset_version")
        and target.get("manifest_sha256") == base_manifest_sha,
        "semantic target Base mismatch",
    )
    _check(
        projection.get("dictionary_version") == tag_dictionary.get("dictionary_version")
        and projection.get("dictionary_sha256") == tag_dictionary.get("dictionary_sha256")
        and source_audit.get("dictionary_version") == tag_dictionary.get("dictionary_version")
        and source_audit.get("dictionary_sha256") == tag_dictionary.get("dictionary_sha256"),
        "semantic dictionary lineage mismatch",
    )

    ledger_manifest = _object(
        _load(candidate_ledger_manifest_path), "candidate_ledger_manifest"
    )
    ledger_manifest_sha = _sha256(candidate_ledger_manifest_path)
    ledger_accounting = _object(
        ledger_manifest.get("accounting"), "candidate_ledger_manifest.accounting"
    )
    ledger_inputs = _object(
        ledger_manifest.get("inputs"), "candidate_ledger_manifest.inputs"
    )
    _check(
        ledger_manifest.get("schema_version") == LEDGER_MANIFEST_SCHEMA
        and ledger_manifest.get("status") == LEDGER_MANIFEST_STATUS
        and ledger_accounting.get("unaccounted_total") == 0
        and ledger_inputs.get("candidate_base_manifest_sha256") == base_manifest_sha,
        "candidate ledger manifest binding mismatch",
    )
    _check(
        ledger_manifest.get("production_unchanged") is True,
        "candidate ledger production boundary mismatch",
    )
    _validate_false_fields(
        ledger_manifest,
        (
            "provider_call",
            "provider_attempt_made",
            "database_write",
            "remote_write",
            "deployment",
            "production_merge",
            "live_send",
        ),
        "candidate_ledger_manifest",
    )

    receipt = _object(
        _load(ledger_validation_receipt_path), "ledger_validation_receipt"
    )
    receipt_sha = _sha256(ledger_validation_receipt_path)
    receipt_counts = _object(receipt.get("counts"), "ledger_validation_receipt.counts")
    _check(
        receipt_sha == expected_ledger_validation_receipt_sha256,
        "ledger validation receipt SHA mismatch",
    )
    _check(
        receipt.get("schema_version") == LEDGER_RECEIPT_SCHEMA
        and receipt.get("status") == "passed"
        and receipt.get("candidate_ledger_manifest_sha256") == ledger_manifest_sha
        and receipt_counts.get("unaccounted_total") == 0,
        "ledger validation receipt binding mismatch",
    )
    _check(
        receipt.get("production_unchanged") is True,
        "ledger validation receipt production boundary mismatch",
    )
    _validate_false_fields(
        receipt,
        (
            "provider_call",
            "provider_attempt_made",
            "database_write",
            "remote_write",
            "deployment",
            "production_merge",
            "live_send",
        ),
        "ledger_validation_receipt",
    )
    identity_gate = _object(projection.get("identity_gate"), "projection.identity_gate")
    expected_identity = {
        "candidate_ledger_manifest_sha256": ledger_manifest_sha,
        "ledger_validation_receipt_sha256": receipt_sha,
        "input_evidence_sha256": receipt.get("input_evidence_sha256"),
        "unaccounted_total": 0,
    }
    _check(identity_gate == expected_identity, "semantic identity gate mismatch")
    for manifest, label in (
        (insights_manifest, "insights_manifest"),
        (reports_manifest, "reports_manifest"),
    ):
        _check(manifest.get("identity_gate") == expected_identity, f"identity gate mismatch: {label}")

    source_summary = _object(source_audit.get("summary"), "source_semantic_audit.summary")
    promoted = set(_rows_or_strings(source_summary.get("promoted_tag_ids"), "source promoted tags"))
    held = set(_rows_or_strings(source_summary.get("held_tag_ids"), "source held tags"))
    projection_promoted = set(_rows_or_strings(projection.get("promoted_tag_ids"), "projection promoted tags"))
    projection_held = set(_rows_or_strings(projection.get("held_tag_ids"), "projection held tags"))
    _check(promoted == projection_promoted and held == projection_held, "semantic tag partition mismatch")
    _check(not promoted & held, "semantic promoted/held overlap")

    rules = {
        _nonempty(row.get("tag_id"), f"tag_dictionary.rules[{index}].tag_id"): row
        for index, row in enumerate(_rows(tag_dictionary.get("rules"), "tag_dictionary.rules"))
    }
    source_tags = _rows(source_audit.get("tags"), "source_semantic_audit.tags")
    source_by_tag = {
        _nonempty(row.get("tag_id"), f"source_semantic_audit.tags[{index}].tag_id"): row
        for index, row in enumerate(source_tags)
    }
    _check(set(source_by_tag) == promoted | held, "source semantic tag set mismatch")

    posts_by_id = {
        _nonempty(row.get("post_id"), f"posts[{index}].post_id"): row
        for index, row in enumerate(posts)
    }
    comments_by_id = {
        _nonempty(row.get("comment_id"), f"comments[{index}].comment_id"): row
        for index, row in enumerate(comments)
    }
    compatible_ids: set[str] = set()
    incompatible_ids: set[str] = set()
    allowed_evidence_ids: set[str] = set()
    tag_compatibility: dict[str, tuple[int, int]] = {}
    populations: dict[str, dict[str, int]] = {}
    promoted_source = 0
    promoted_compatible = 0
    source_reviewed = 0

    for tag_id, tag in source_by_tag.items():
        rule = rules[tag_id]
        reference = _object(tag.get("dictionary_reference"), f"source tag reference:{tag_id}")
        for field in (
            "consumer_card",
            "aipl_node",
            "story_lines",
            "intent_type",
            "problem_type",
        ):
            _check(reference.get(field) == rule.get(field), f"semantic dictionary rule drift: {tag_id}:{field}")
        samples = _rows(tag.get("samples"), f"source tag samples:{tag_id}")
        source_reviewed += len(samples)
        compatible_count = 0
        for sample in samples:
            audit_id = _nonempty(sample.get("audit_id"), f"source sample audit_id:{tag_id}")
            entity_type = sample.get("entity_type")
            entity_id = _nonempty(sample.get("entity_id"), f"source sample entity_id:{audit_id}")
            _check(entity_type in ENTITY_TYPES, f"source sample entity type mismatch: {audit_id}")
            row = (posts_by_id if entity_type == "post" else comments_by_id).get(entity_id)
            _check(row is not None, f"source reviewed entity absent from Base: {audit_id}")
            assert row is not None
            match = _tag_match(row, tag_id, f"source reviewed entity:{audit_id}")
            compatible = match is not None and (
                entity_type == "post" or row.get("include_in_voc_metrics") is True
            )
            if compatible and match is not None:
                compatible = _keyword_list(
                    match.get("evidence_keywords"), f"current evidence keywords:{audit_id}"
                ) == _keyword_list(
                    sample.get("evidence_keywords"), f"source evidence keywords:{audit_id}"
                )
            (compatible_ids if compatible else incompatible_ids).add(audit_id)
            compatible_count += int(compatible)
            review = _object(sample.get("review"), f"source review:{audit_id}")
            if compatible and review.get("label_verdict") == "correct" and review.get("taxonomy_fit") == "fit":
                allowed_evidence_ids.add(audit_id)
        tag_compatibility[tag_id] = (len(samples), compatible_count)
        if tag_id in promoted:
            promoted_source += len(samples)
            promoted_compatible += compatible_count
            _check(compatible_count == len(samples), f"promoted semantic carry-forward failed: {tag_id}")
        post_count = sum(_tag_match(row, tag_id, f"post:{index}") is not None for index, row in enumerate(posts))
        comment_count = sum(
            row.get("include_in_voc_metrics") is True
            and _tag_match(row, tag_id, f"comment:{index}") is not None
            for index, row in enumerate(comments)
        )
        populations[tag_id] = {
            "post_entities": post_count,
            "comment_entities": comment_count,
            "total_entities": post_count + comment_count,
        }

    _check(source_reviewed == source_summary.get("reviewed_assignments"), "source reviewed count mismatch")
    compatibility = _object(projection.get("compatibility_summary"), "projection.compatibility_summary")
    _check(
        compatibility.get("source_reviewed_assignments") == source_reviewed
        and compatibility.get("compatible_source_assignments") == len(compatible_ids)
        and compatibility.get("incompatible_or_absent_source_assignments") == len(incompatible_ids)
        and compatibility.get("promoted_source_assignments") == promoted_source
        and compatibility.get("promoted_compatible_assignments") == promoted_compatible
        and compatibility.get("promoted_retention_gate_passed") is True,
        "semantic compatibility summary mismatch",
    )

    legacy = _object(projection.get("legacy_insights"), "projection.legacy_insights")
    headline = _object(legacy.get("headline"), "projection.legacy_insights.headline")
    current_headline = _object(insights.get("headline"), "insights.headline")
    unique_posts = sum(
        any(_tag_match(row, tag_id, f"post:{index}") is not None for tag_id in promoted)
        for index, row in enumerate(posts)
    )
    unique_comments = sum(
        row.get("include_in_voc_metrics") is True
        and any(_tag_match(row, tag_id, f"comment:{index}") is not None for tag_id in promoted)
        for index, row in enumerate(comments)
    )
    expected_headline = {
        "audited_tags": len(promoted | held),
        "promoted_tags": len(promoted),
        "held_tags": len(held),
        "reviewed_assignments": None,
        "source_reviewed_assignments": source_reviewed,
        "compatible_source_assignments": len(compatible_ids),
        "promoted_rule_assignments": sum(populations[tag_id]["total_entities"] for tag_id in promoted),
        "unique_posts_with_promoted_tags": unique_posts,
        "unique_comments_with_promoted_tags": unique_comments,
    }
    _check(headline == expected_headline, "semantic projected headline mismatch")
    _check(current_headline == expected_headline, "insights current-base headline mismatch")

    reference_fields = (
        "consumer_card",
        "aipl_node",
        "story_lines",
        "intent_type",
        "problem_type",
    )
    expected_dimensions: dict[str, dict[str, int]] = {}
    for field in reference_fields:
        counter: Counter[str] = Counter()
        for tag_id in promoted:
            reference = _object(source_by_tag[tag_id].get("dictionary_reference"), f"reference:{tag_id}")
            counter[_nonempty(reference.get(field), f"reference:{tag_id}:{field}")] += populations[tag_id]["total_entities"]
        expected_dimensions[field] = dict(counter.most_common())
    _check(legacy.get("reference_dimensions") == expected_dimensions, "semantic projected reference dimensions mismatch")
    _check(insights.get("reference_dimensions") == expected_dimensions, "insights reference dimensions mismatch")

    signals = _rows(insights.get("signals"), "insights.signals")
    _check({row.get("tag_id") for row in signals} == promoted, "insights signal tag set mismatch")
    for signal in signals:
        tag_id = _nonempty(signal.get("tag_id"), "insights.signal.tag_id")
        population = populations[tag_id]
        _check(
            signal.get("matched_posts") == population["post_entities"]
            and signal.get("matched_comments") == population["comment_entities"]
            and signal.get("matched_entities") == population["total_entities"],
            f"insights signal population mismatch: {tag_id}",
        )
        for evidence in _rows(signal.get("evidence_examples"), f"signal evidence:{tag_id}"):
            audit_id = _nonempty(evidence.get("audit_id"), f"signal evidence audit_id:{tag_id}")
            _check(audit_id in allowed_evidence_ids, f"unreviewed semantic evidence example: {audit_id}")

    held_rows = _rows(insights.get("held_tags"), "insights.held_tags")
    _check({row.get("tag_id") for row in held_rows} == held, "insights held tag set mismatch")
    for row in held_rows:
        tag_id = _nonempty(row.get("tag_id"), "insights.held_tag_id")
        _check(row.get("matched_entities") == populations[tag_id]["total_entities"], f"insights held population mismatch: {tag_id}")

    legacy_contract = _object(insights.get("legacy_compatibility"), "insights.legacy_compatibility")
    _check(
        legacy_contract.get("status") == "current_base_recomputed_governance_projection"
        and legacy_contract.get("current_base_manifest_sha256") == base_manifest_sha
        and legacy_contract.get("source_semantic_audit_sha256") == source_audit_sha
        and legacy_contract.get("candidate_ledger_manifest_sha256") == ledger_manifest_sha
        and legacy_contract.get("ledger_validation_receipt_sha256") == receipt_sha
        and legacy_contract.get("new_review_performed") is False,
        "legacy compatibility provenance mismatch",
    )
    audit_summary = _object(projected_audit.get("summary"), "projected_audit.summary")
    _check(
        projected_audit.get("contract_extension") == "reddit_voc_semantic_compatibility_projection_v1"
        and projected_audit.get("projection_mode") == "governance_projection_no_new_review"
        and audit_summary.get("reviewed_assignments") is None
        and audit_summary.get("source_reviewed_assignments") == source_reviewed
        and audit_summary.get("compatible_source_assignments") == len(compatible_ids),
        "semantic audit projection provenance mismatch",
    )
    return {
        "semantic_governance_sha256": projection_sha,
        "source_semantic_audit_sha256": source_audit_sha,
        "candidate_ledger_manifest_sha256": ledger_manifest_sha,
        "ledger_validation_receipt_sha256": receipt_sha,
        "source_reviewed_assignments": source_reviewed,
        "compatible_source_assignments": len(compatible_ids),
        "promoted_compatible_assignments": promoted_compatible,
    }


def _safe_manifest_path(root: Path, name: str) -> Path:
    relative = Path(name)
    _check(not relative.is_absolute() and ".." not in relative.parts, f"unsafe manifest path: {name}")
    path = root / relative
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=True))
    except ValueError as exc:
        raise ValueError(f"unsafe manifest path: {name}") from exc
    _check(path.is_file() and not path.is_symlink(), f"manifest file missing: {name}")
    return path


def _validate_manifest_files(
    root: Path,
    manifest: Mapping[str, Any],
    *,
    required: set[str],
    exact: set[str] | None = None,
) -> dict[str, Path]:
    files = _object(manifest.get("files"), "manifest.files")
    names = set(files)
    _check(required <= names, "manifest required file set mismatch")
    if exact is not None:
        _check(names == exact, "manifest file set mismatch")
    paths: dict[str, Path] = {}
    for name, raw_record in files.items():
        record = _object(raw_record, f"manifest.files.{name}")
        path = _safe_manifest_path(root, name)
        expected_bytes = _integer(record.get("bytes"), f"manifest.files.{name}.bytes")
        expected_sha = _nonempty(record.get("sha256"), f"manifest.files.{name}.sha256")
        _check(re.fullmatch(r"[0-9a-f]{64}", expected_sha) is not None, f"invalid sha256: {name}")
        _check(path.stat().st_size == expected_bytes, f"byte mismatch: {name}")
        _check(_sha256(path) == expected_sha, f"sha256 mismatch: {name}")
        paths[name] = path
    return paths


def _validate_private_analytics_tree(root: Path, label: str) -> None:
    _check(not root.is_symlink(), f"{label} root is a symlink")
    _check(root.stat().st_mode & 0o777 == 0o700, f"{label} root mode mismatch")
    for path in root.rglob("*"):
        _check(not path.is_symlink(), f"{label} tree contains a symlink")
        if path.is_dir():
            _check(
                path.stat().st_mode & 0o777 == 0o700,
                f"{label} directory mode mismatch",
            )
        elif path.is_file():
            _check(
                path.stat().st_mode & 0o777 == 0o600,
                f"{label} file mode mismatch",
            )
        else:
            raise ValueError(f"{label} tree contains an unsafe entry")


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        _check(self.start.tzinfo is not None, "window start is naive")
        _check(self.end.tzinfo is not None, "window end is naive")
        _check(self.start < self.end, "window is empty")

    @property
    def start_utc(self) -> datetime:
        return self.start.astimezone(timezone.utc)

    @property
    def end_utc(self) -> datetime:
        return self.end.astimezone(timezone.utc)


@dataclass(frozen=True)
class WindowSet:
    current: Window
    previous: Window
    year_over_year: Window
    trend: tuple[Window, ...]


@dataclass(frozen=True)
class Entity:
    entity_type: str
    entity_id: str
    post_id: str
    event_time: datetime
    subreddit: str
    permalink: str | None
    brand_binding: str
    sentiment: str
    product_bindings: tuple[dict[str, Any], ...]
    matches: tuple[dict[str, Any], ...]
    source_text: str
    row: dict[str, Any]


def _local_midnight(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=TIMEZONE)


def _add_months(value: date, months: int) -> date:
    absolute = value.year * 12 + value.month - 1 + months
    year, month_zero = divmod(absolute, 12)
    return date(year, month_zero + 1, 1)


def _shift_year(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=28)


def _daily_window(value: date) -> Window:
    start = _local_midnight(value)
    return Window(start, start + timedelta(days=1))


def _weekly_window(value: date) -> Window:
    start = _local_midnight(value)
    return Window(start, start + timedelta(days=7))


def _monthly_window(value: date) -> Window:
    return Window(_local_midnight(value), _local_midnight(_add_months(value, 1)))


def _window_set_from_current(period: str, current: Window) -> WindowSet:
    start_date = current.start.astimezone(TIMEZONE).date()
    if period == "daily":
        previous = _daily_window(start_date - timedelta(days=1))
        year_over_year = _daily_window(_shift_year(start_date, -1))
        trend = tuple(
            _daily_window(start_date - timedelta(days=offset))
            for offset in reversed(range(14))
        )
    elif period == "weekly":
        previous = _weekly_window(start_date - timedelta(days=7))
        year_over_year = _weekly_window(start_date - timedelta(days=364))
        trend = tuple(
            _weekly_window(start_date - timedelta(days=7 * offset))
            for offset in reversed(range(13))
        )
    elif period == "monthly":
        previous = _monthly_window(_add_months(start_date, -1))
        year_over_year = _monthly_window(_shift_year(start_date, -1))
        trend = tuple(
            _monthly_window(_add_months(start_date, -offset))
            for offset in reversed(range(12))
        )
    else:
        raise ValueError(f"unsupported report period: {period}")
    return WindowSet(current, previous, year_over_year, trend)


def _expected_window_sets(as_of: datetime) -> dict[tuple[str, str], WindowSet]:
    local_date = as_of.astimezone(TIMEZONE).date()
    current_week_start = local_date - timedelta(days=local_date.weekday())
    current_month_start = local_date.replace(day=1)
    current_windows = {
        "daily": _daily_window(local_date - timedelta(days=1)),
        "weekly": _weekly_window(current_week_start - timedelta(days=7)),
        "monthly": _monthly_window(_add_months(current_month_start, -1)),
    }
    result: dict[tuple[str, str], WindowSet] = {}
    for period, current in current_windows.items():
        current_set = _window_set_from_current(period, current)
        result[("current", period)] = current_set
        result[("archive", period)] = _window_set_from_current(
            period, current_set.previous
        )
    return result


def _archive_path(period: str, window: Window) -> str:
    start = window.start.astimezone(TIMEZONE).date()
    end = (window.end.astimezone(TIMEZONE) - timedelta(microseconds=1)).date()
    if period == "daily":
        return f"archive/daily-{start.isoformat()}.json"
    if period == "weekly":
        return f"archive/weekly-{start.isoformat()}_{end.isoformat()}.json"
    return f"archive/monthly-{start.strftime('%Y-%m')}.json"


def _report_path(collection: str, period: str, window: Window) -> str:
    return (
        f"current/{period}.json"
        if collection == "current"
        else _archive_path(period, window)
    )


def _validate_product_binding(binding: dict[str, Any], field: str) -> None:
    _check(binding.get("brand_id") == "momcozy", f"non-Momcozy governed binding: {field}")
    category = _object(binding.get("category"), f"{field}.category")
    for name in ("id", "name_en", "name_cn"):
        _nonempty(category.get(name), f"{field}.category.{name}")
    family = binding.get("product_family")
    if family is not None:
        family = _object(family, f"{field}.product_family")
        for name in ("id", "name_en", "name_cn"):
            _nonempty(family.get(name), f"{field}.product_family.{name}")
    level = binding.get("binding_level")
    _check(level in {"category", "product_family", "spu_exact"}, f"invalid binding level: {field}")
    exact = binding.get("exact_spu")
    if level == "spu_exact":
        exact = _object(exact, f"{field}.exact_spu")
        _nonempty(exact.get("spu_id"), f"{field}.exact_spu.spu_id")
        _nonempty(exact.get("spu_name"), f"{field}.exact_spu.spu_name")
        _check(
            binding.get("governance_status") == "exact_spu_approved",
            f"unapproved exact SPU binding: {field}",
        )
    else:
        _check(exact is None, f"non-exact binding contains exact SPU: {field}")


def _build_entities(
    posts: list[dict[str, Any]], comments: list[dict[str, Any]]
) -> tuple[list[Entity], dict[str, Entity], dict[str, Entity], dict[str, dict[str, Any]]]:
    entities: list[Entity] = []
    posts_by_id: dict[str, Entity] = {}
    comments_by_id: dict[str, Entity] = {}
    raw_posts: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(posts):
        post_id = _nonempty(row.get("post_id"), f"posts[{index}].post_id")
        _check(post_id not in posts_by_id, f"duplicate base post id: {post_id}")
        subreddit = _nonempty(row.get("subreddit"), f"posts[{index}].subreddit")
        title = row.get("title")
        content = row.get("content")
        _check(isinstance(title, str) and isinstance(content, str), f"base post text contract: {post_id}")
        products = _rows(row.get("product_bindings"), f"posts[{index}].product_bindings")
        for product_index, binding in enumerate(products):
            _validate_product_binding(binding, f"posts[{index}].product_bindings[{product_index}]")
        tagging = _object(row.get("tagging"), f"posts[{index}].tagging")
        matches = _rows(tagging.get("matches"), f"posts[{index}].tagging.matches")
        analysis = _object(row.get("analysis"), f"posts[{index}].analysis")
        sentiment = _nonempty(analysis.get("sentiment_label"), f"posts[{index}].analysis.sentiment_label")
        event = _parse_utc(row.get("event_created_at_utc"), f"posts[{index}].event_created_at_utc")
        permalink_value = row.get("permalink")
        permalink = permalink_value.strip() if isinstance(permalink_value, str) and permalink_value.strip() else None
        entity = Entity(
            "post",
            post_id,
            post_id,
            event,
            subreddit,
            permalink,
            _nonempty(row.get("brand_binding"), f"posts[{index}].brand_binding"),
            sentiment,
            tuple(products),
            tuple(matches),
            f"{title}\n{content}",
            row,
        )
        posts_by_id[post_id] = entity
        raw_posts[post_id] = row
        entities.append(entity)
    for index, row in enumerate(comments):
        comment_id = _nonempty(row.get("comment_id"), f"comments[{index}].comment_id")
        _check(comment_id not in comments_by_id, f"duplicate base comment id: {comment_id}")
        post_id = _nonempty(row.get("post_id"), f"comments[{index}].post_id")
        _check(post_id in posts_by_id, f"orphan base comment: {comment_id}")
        include = row.get("include_in_voc_metrics")
        _check(isinstance(include, bool), f"comment metric flag mismatch: {comment_id}")
        products = _rows(row.get("product_bindings"), f"comments[{index}].product_bindings")
        for product_index, binding in enumerate(products):
            _validate_product_binding(binding, f"comments[{index}].product_bindings[{product_index}]")
        if not include:
            continue
        body = row.get("body")
        _check(isinstance(body, str), f"base comment text contract: {comment_id}")
        body_text = body if isinstance(body, str) else ""
        tagging = _object(row.get("tagging"), f"comments[{index}].tagging")
        matches = _rows(tagging.get("matches"), f"comments[{index}].tagging.matches")
        analysis = _object(row.get("analysis"), f"comments[{index}].analysis")
        sentiment = _nonempty(analysis.get("sentiment_label"), f"comments[{index}].analysis.sentiment_label")
        parent = posts_by_id[post_id]
        entity = Entity(
            "comment",
            comment_id,
            post_id,
            _parse_utc(row.get("event_created_at_utc"), f"comments[{index}].event_created_at_utc"),
            parent.subreddit,
            parent.permalink,
            _nonempty(row.get("brand_binding"), f"comments[{index}].brand_binding"),
            sentiment,
            tuple(products),
            tuple(matches),
            body_text,
            row,
        )
        comments_by_id[comment_id] = entity
        entities.append(entity)
    return entities, posts_by_id, comments_by_id, raw_posts


def _in_window(entity: Entity, window: Window) -> bool:
    return window.start_utc <= entity.event_time < window.end_utc


def _window_entities(entities: Sequence[Entity], window: Window) -> list[Entity]:
    return [entity for entity in entities if _in_window(entity, window)]


def _scope_reference(binding: Mapping[str, Any], level: str) -> tuple[str, str, str] | None:
    if level == "category":
        value = _object(binding.get("category"), "product_binding.category")
        return value["id"], value["name_en"], value["name_cn"]
    if level == "product_family":
        value = binding.get("product_family")
        if value is None:
            return None
        family = _object(value, "product_binding.product_family")
        return family["id"], family["name_en"], family["name_cn"]
    if level == "spu_exact":
        if (
            binding.get("binding_level") != "spu_exact"
            or binding.get("governance_status") != "exact_spu_approved"
        ):
            return None
        value = _object(binding.get("exact_spu"), "product_binding.exact_spu")
        return value["spu_id"], value["spu_name"], value["spu_name"]
    raise ValueError(f"unsupported product level: {level}")


def _product_catalog(
    entities: Iterable[Entity], *, momcozy_entities_only: bool
) -> dict[str, dict[str, tuple[str, str, str]]]:
    catalog: dict[str, dict[str, tuple[str, str, str]]] = {
        level: {} for level in PRODUCT_LEVELS
    }
    for entity in entities:
        if momcozy_entities_only and entity.brand_binding not in MOMCOZY_BINDINGS:
            continue
        for binding in entity.product_bindings:
            for level in PRODUCT_LEVELS:
                reference = _scope_reference(binding, level)
                if reference is None:
                    continue
                existing = catalog[level].get(reference[0])
                _check(
                    existing is None or existing == reference,
                    f"conflicting governed product reference: {level}:{reference[0]}",
                )
                catalog[level][reference[0]] = reference
    return catalog


def _product_coverage(entities: Sequence[Entity]) -> dict[str, Any]:
    momcozy = [entity for entity in entities if entity.brand_binding in MOMCOZY_BINDINGS]
    bound = [entity for entity in momcozy if entity.product_bindings]
    bindings = [binding for entity in momcozy for binding in entity.product_bindings]
    return {
        "momcozy_observed_entities": len(momcozy),
        "bound_entities": len(bound),
        "unbound_entities": len(momcozy) - len(bound),
        "binding_rate": round(len(bound) / len(momcozy), 6) if momcozy else None,
        "binding_count": len(bindings),
        "family_only_bindings": sum(
            binding.get("governance_status") == "family_only" for binding in bindings
        ),
        "category_only_bindings": sum(
            binding.get("governance_status") == "category_only" for binding in bindings
        ),
        "taxonomy_blocked_bindings": sum(
            binding.get("governance_status") == "taxonomy_blocked" for binding in bindings
        ),
        "exact_spu_release_rule": "exact_spu_approved_only",
    }


def _entities_for_scope(
    entities: Sequence[Entity], level: str, scope_id: str
) -> list[Entity]:
    output: dict[tuple[str, str], Entity] = {}
    for entity in entities:
        if entity.brand_binding not in MOMCOZY_BINDINGS:
            continue
        if any(
            (reference := _scope_reference(binding, level)) is not None
            and reference[0] == scope_id
            for binding in entity.product_bindings
        ):
            output[(entity.entity_type, entity.entity_id)] = entity
    return list(output.values())


def _validate_product_metric(metric: Mapping[str, Any], entities: Sequence[Entity], field: str) -> None:
    for entity_type in ENTITY_TYPES:
        rows = [entity for entity in entities if entity.entity_type == entity_type]
        value = _object(metric.get(entity_type), f"{field}.{entity_type}")
        denominator = len(rows)
        numerator = sum(entity.sentiment == "negative" for entity in rows)
        _check(value.get("denominator") == denominator, f"product denominator mismatch: {field}.{entity_type}")
        _check(value.get("numerator") == numerator, f"product numerator mismatch: {field}.{entity_type}")
        expected_value = round(numerator / denominator, 6) if denominator else None
        _check(value.get("value") == expected_value, f"product metric mismatch: {field}.{entity_type}")
        expected_status = "observed" if denominator else "denominator_zero"
        _check(value.get("value_status") == expected_status, f"product value status mismatch: {field}.{entity_type}")
    combined = _object(metric.get("combined"), f"{field}.combined")
    _check(combined.get("supported") is False, f"combined product metric overclaim: {field}")
    _check(combined.get("value") is None, f"combined product metric must be null: {field}")


def _validate_product_analysis(
    value: Any, entities: Sequence[Entity], field: str
) -> dict[str, dict[str, tuple[str, str, str]]]:
    analysis = _object(value, field)
    _check(analysis.get("schema_version") == "reddit_voc_product_analysis_v1", f"product schema mismatch: {field}")
    _check(analysis.get("decision_subject") == "momcozy", f"product decision subject mismatch: {field}")
    _check(analysis.get("scope_order") == list(PRODUCT_LEVELS), f"product scope order mismatch: {field}")
    expected_catalog = _product_catalog(entities, momcozy_entities_only=True)
    for level in PRODUCT_LEVELS:
        rows = _rows(analysis.get(level), f"{field}.{level}")
        by_id: dict[str, dict[str, Any]] = {}
        for index, row in enumerate(rows):
            scope_id = _nonempty(row.get("scope_id"), f"{field}.{level}[{index}].scope_id")
            _check(scope_id not in by_id, f"duplicate product scope: {field}.{level}:{scope_id}")
            by_id[scope_id] = row
        _check(set(by_id) == set(expected_catalog[level]), f"product scope set mismatch: {field}.{level}")
        for scope_id, reference in expected_catalog[level].items():
            row = by_id[scope_id]
            _check(row.get("binding_level") == level, f"product binding level mismatch: {field}.{level}:{scope_id}")
            _check(row.get("scope_name_en") == reference[1], f"product English name mismatch: {field}.{level}:{scope_id}")
            _check(row.get("scope_name_cn") == reference[2], f"product Chinese name mismatch: {field}.{level}:{scope_id}")
            scoped = _entities_for_scope(entities, level, scope_id)
            _validate_product_metric(
                _object(row.get("metrics"), f"{field}.{level}.{scope_id}.metrics"),
                scoped,
                f"{field}.{level}.{scope_id}.metrics",
            )
            priorities = _object(
                row.get("risk_priority_assignments"),
                f"{field}.{level}.{scope_id}.risk_priority_assignments",
            )
            _check(set(priorities) == {"P0", "P1", "P2", "P3", "insufficient"}, f"risk priority structure mismatch: {field}.{level}:{scope_id}")
            for priority, count in priorities.items():
                _integer(count, f"{field}.{level}.{scope_id}.risk_priority_assignments.{priority}")
    coverage = _object(analysis.get("coverage"), f"{field}.coverage")
    expected_coverage = _product_coverage(entities)
    for key, expected in expected_coverage.items():
        _check(coverage.get(key) == expected, f"product coverage mismatch: {field}.{key}")
    return expected_catalog


def _normalise_capability(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def _canonical_capability(value: str) -> str:
    normalised = _normalise_capability(value)
    return "sov" if normalised == "share_of_voice" else normalised


def _validate_capabilities(value: Any, field: str) -> None:
    capabilities = _object(value, field)
    lists: dict[str, list[str]] = {}
    for name in ("supported", "conditionally_supported", "unsupported"):
        lists[name] = _rows_or_strings(
            capabilities.get(name), f"{field}.{name}"
        )
    supported = {_canonical_capability(item) for item in lists["supported"]}
    conditional = {
        _canonical_capability(item) for item in lists["conditionally_supported"]
    }
    unsupported = {
        _canonical_capability(item) for item in lists["unsupported"]
    }
    _check(not (FORBIDDEN_CAPABILITIES & (supported | conditional)), f"forbidden capability enabled: {field}")
    _check(FORBIDDEN_CAPABILITIES <= unsupported, f"forbidden capability boundary missing: {field}")


def _validate_recursive_support_flags(value: Any, field: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalised = _normalise_capability(key)
            if normalised in {
                "market_share_supported",
                "share_of_voice_supported",
                "sov_supported",
                "roi_supported",
                "response_time_supported",
            }:
                _check(child is False, f"forbidden support flag enabled: {field}.{key}")
            _validate_recursive_support_flags(child, f"{field}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_recursive_support_flags(child, f"{field}[{index}]")


def _validate_false_fields(
    value: Mapping[str, Any], fields: Iterable[str], label: str
) -> None:
    for field in fields:
        _check(value.get(field) is False, f"boundary must be false: {label}.{field}")


def _comparison_type(period: str, group: str) -> str:
    if group == "year_over_year":
        return "year_over_year"
    return {
        "daily": "day_over_day",
        "weekly": "week_over_week",
        "monthly": "month_over_month",
    }[period]


def _validate_comparison(
    value: Any,
    *,
    field: str,
    entity_type: str,
    metric_name: str,
    comparison_type: str,
) -> str:
    comparison = _object(value, field)
    _check(comparison.get("entity_type") == entity_type, f"comparison entity mismatch: {field}")
    _check(comparison.get("metric_name") == metric_name, f"comparison metric mismatch: {field}")
    _check(comparison.get("comparison_type") == comparison_type, f"comparison type mismatch: {field}")
    status_value = comparison.get("comparison_status")
    _check(status_value in COMPARISON_STATUSES, f"comparison status mismatch: {field}")
    status = str(status_value)
    reasons = _rows_or_strings(
        comparison.get("reason_codes"), f"{field}.reason_codes"
    )
    _check(reasons == sorted(reasons), f"comparison reason-code order mismatch: {field}")
    direction = comparison.get("direction_claim_supported")
    _check(isinstance(direction, bool), f"comparison direction flag mismatch: {field}")
    absolute = comparison.get("absolute_delta")
    relative = comparison.get("relative_delta")
    if status == "comparable":
        _check(not reasons, f"comparable comparison has reasons: {field}")
        _check(direction is (absolute is not None), f"comparable direction mismatch: {field}")
    elif status == "provisional_observed_sample":
        _check(bool(reasons), f"provisional comparison lacks reasons: {field}")
        _check(
            set(reasons) <= PROVISIONAL_REASON_CODES,
            f"provisional comparison has unknown reason: {field}",
        )
        _check(direction is False, f"provisional direction overclaim: {field}")
    else:
        _check(bool(reasons), f"unavailable comparison lacks reasons: {field}")
        _check(
            set(reasons) <= UNAVAILABLE_REASON_CODES,
            f"unavailable comparison has unknown reason: {field}",
        )
        _check(direction is False, f"unavailable direction overclaim: {field}")
        _check(absolute is None and relative is None, f"unavailable comparison has delta: {field}")
        _check(comparison.get("delta_reason") == "comparison_gate_unavailable", f"unavailable delta reason mismatch: {field}")
    return status


def _validate_observation(value: Any, *, field: str, expected_count: int | None = None) -> str:
    observation = _object(value, field)
    status_value = observation.get("observation_status")
    _check(status_value in COMPARISON_STATUSES, f"observation status mismatch: {field}")
    status = str(status_value)
    reasons = _rows_or_strings(
        observation.get("reason_codes"), f"{field}.reason_codes"
    )
    _check(reasons == sorted(reasons), f"observation reason-code order mismatch: {field}")
    if status == "comparable":
        _check(not reasons, f"comparable observation has reasons: {field}")
    else:
        _check(bool(reasons), f"non-comparable observation lacks reasons: {field}")
        allowed = (
            PROVISIONAL_REASON_CODES
            if status == "provisional_observed_sample"
            else UNAVAILABLE_REASON_CODES
        )
        _check(
            set(reasons) <= allowed,
            f"observation has unknown reason: {field}",
        )
    if status == "unavailable":
        _check(observation.get("value") is None, f"unavailable observation has value: {field}")
    if expected_count is not None and expected_count > 0:
        _check(status != "unavailable", f"observed product scope is unavailable: {field}")
        if observation.get("metric") == "momcozy_brand_bound_observed_entity_count":
            _check(observation.get("value") == expected_count, f"product observed count mismatch: {field}")
        else:
            _check(observation.get("denominator") == expected_count, f"product observed denominator mismatch: {field}")
    return status


def _overall_status(statuses: Iterable[str]) -> str:
    values = set(statuses)
    if "unavailable" in values:
        return "unavailable"
    if "provisional_observed_sample" in values:
        return "provisional_observed_sample"
    return "comparable"


def _validate_window_record(value: Any, expected: Window, *, field: str) -> None:
    window = _object(value, field)
    _check(_parse_utc(window.get("start_utc"), f"{field}.start_utc") == expected.start_utc, f"window start mismatch: {field}")
    _check(_parse_utc(window.get("end_utc"), f"{field}.end_utc") == expected.end_utc, f"window end mismatch: {field}")
    _check(_parse_datetime(window.get("start_local"), f"{field}.start_local") == expected.start, f"local window start mismatch: {field}")
    _check(_parse_datetime(window.get("end_local"), f"{field}.end_local") == expected.end, f"local window end mismatch: {field}")
    _check(window.get("timezone") == TIMEZONE_NAME, f"window timezone mismatch: {field}")
    _check(window.get("interval") == "half_open", f"window interval mismatch: {field}")
    _check(window.get("is_closed") is True, f"window is not closed: {field}")


def _tag_binding(entity: Entity, match: Mapping[str, Any]) -> str:
    raw_keywords = match.get("evidence_keywords", [])
    keywords = [
        keyword.casefold().strip()
        for keyword in raw_keywords
        if isinstance(keyword, str) and keyword.strip()
    ]
    sentences = re.split(
        r"(?<=[.!?])\s+|\n+", html.unescape(entity.source_text).casefold()
    )
    sentence_bound = any(
        any(alias in sentence for alias in ("momcozy", "mcozy"))
        and any(keyword in sentence for keyword in keywords)
        for sentence in sentences
        if sentence.strip()
    )
    if sentence_bound:
        return "momcozy_sentence_bound"
    if entity.brand_binding == "momcozy_sentence_bound":
        return "momcozy_entity_reviewed"
    return entity.brand_binding


def _risk_facts(
    entities: Sequence[Entity], rules: Mapping[str, dict[str, Any]]
) -> dict[str, list[tuple[Entity, str]]]:
    output: dict[str, list[tuple[Entity, str]]] = defaultdict(list)
    for entity in entities:
        seen: set[str] = set()
        for match in entity.matches:
            tag_id = match.get("tag_id")
            if not isinstance(tag_id, str) or tag_id in seen or tag_id not in rules:
                continue
            seen.add(tag_id)
            rule_sentiment = str(rules[tag_id].get("sentiment", "")).casefold()
            if entity.sentiment != "negative" and rule_sentiment not in {
                "negative",
                "负向",
                "消极",
            }:
                continue
            output[tag_id].append((entity, _tag_binding(entity, match)))
    return output


def _scope_ids(bindings: Iterable[dict[str, Any]]) -> dict[str, list[str]]:
    output: dict[str, set[str]] = {level: set() for level in PRODUCT_LEVELS}
    for binding in bindings:
        for level in PRODUCT_LEVELS:
            reference = _scope_reference(binding, level)
            if reference is not None:
                output[level].add(reference[0])
    return {level: sorted(values) for level, values in output.items()}


def _validate_risk_themes(
    value: Any,
    *,
    entities: Sequence[Entity],
    rules: Mapping[str, dict[str, Any]],
    promoted: set[str],
    window: Window,
    field: str,
) -> int:
    themes = _rows(value, field)
    window_rows = _window_entities(entities, window)
    facts = _risk_facts(window_rows, rules)
    expected = {
        tag_id: rows
        for tag_id, rows in facts.items()
        if any(binding in MOMCOZY_BINDINGS for _, binding in rows)
    }
    by_id: dict[str, dict[str, Any]] = {}
    for index, theme in enumerate(themes):
        tag_id = _nonempty(theme.get("tag_id"), f"{field}[{index}].tag_id")
        _check(theme.get("risk_theme_id") == tag_id, f"risk theme identity mismatch: {field}:{tag_id}")
        _check(tag_id not in by_id, f"duplicate risk theme: {field}:{tag_id}")
        by_id[tag_id] = theme
    _check(set(by_id) == set(expected), f"risk theme set mismatch: {field}")
    for tag_id, rows in expected.items():
        theme = by_id[tag_id]
        rule = rules[tag_id]
        for name in (
            "name_cn",
            "name_en",
            "theme",
            "risk_level",
            "problem_type",
            "intent_type",
            "business_impact",
            "dept_owner",
        ):
            _check(theme.get(name) == rule.get(name), f"risk dictionary field mismatch: {field}:{tag_id}.{name}")
        _check(
            theme.get("suggested_action") == rule.get("biz_action"),
            f"risk suggested action mismatch: {field}:{tag_id}",
        )
        _check(theme.get("dictionary_default_priority") == rule.get("default_priority"), f"risk priority source mismatch: {field}:{tag_id}")
        _check(theme.get("action_state") == "recommendation_only", f"risk action overclaim: {field}:{tag_id}")
        unique_all = {(entity.entity_type, entity.entity_id): entity for entity, _ in rows}
        momcozy_rows = [row for row in rows if row[1] in MOMCOZY_BINDINGS]
        unique_momcozy = {
            (entity.entity_type, entity.entity_id): entity
            for entity, _ in momcozy_rows
        }
        observed = _object(theme.get("observed_entities"), f"{field}.{tag_id}.observed_entities")
        for entity_type in ENTITY_TYPES:
            expected_count = sum(key[0] == entity_type for key in unique_momcozy)
            _check(observed.get(entity_type) == expected_count, f"risk observed count mismatch: {field}:{tag_id}.{entity_type}")
        total = len(unique_momcozy)
        _check(theme.get("evidence_ref_count_total") == total, f"risk evidence total mismatch: {field}:{tag_id}")
        refs = _rows(theme.get("evidence_refs"), f"{field}.{tag_id}.evidence_refs")
        truncated = theme.get("evidence_refs_truncated")
        _check(isinstance(truncated, bool), f"risk evidence truncation flag mismatch: {field}:{tag_id}")
        _check((len(refs) < total) is truncated, f"risk evidence truncation mismatch: {field}:{tag_id}")
        ordered = sorted(
            unique_momcozy.values(),
            key=lambda entity: (
                -entity.event_time.timestamp(),
                0 if entity.entity_type == "post" else 1,
                entity.entity_id,
            ),
        )
        expected_refs = ordered[: len(refs)]
        seen_refs: set[tuple[str, str]] = set()
        for index, (reference, entity) in enumerate(zip(refs, expected_refs, strict=True)):
            ref_field = f"{field}.{tag_id}.evidence_refs[{index}]"
            key = (
                _nonempty(reference.get("entity_type"), f"{ref_field}.entity_type"),
                _nonempty(reference.get("entity_id"), f"{ref_field}.entity_id"),
            )
            _check(key not in seen_refs, f"duplicate risk evidence: {ref_field}")
            seen_refs.add(key)
            _check(key == (entity.entity_type, entity.entity_id), f"risk evidence ID mismatch: {ref_field}")
            _check(reference.get("post_id") == entity.post_id, f"risk evidence parent mismatch: {ref_field}")
            _check(_parse_utc(reference.get("event_created_at_utc"), f"{ref_field}.event_created_at_utc") == entity.event_time, f"risk evidence time mismatch: {ref_field}")
            _check(reference.get("subreddit") == entity.subreddit, f"risk evidence subreddit mismatch: {ref_field}")
            _check(reference.get("permalink") == entity.permalink, f"risk evidence permalink mismatch: {ref_field}")
            _check(reference.get("brand_binding") in MOMCOZY_BINDINGS, f"risk evidence is not Momcozy-bound: {ref_field}")
        expected_scopes = _scope_ids(
            binding
            for entity in unique_momcozy.values()
            for binding in entity.product_bindings
        )
        _check(theme.get("product_scope_ids") == expected_scopes, f"risk product scope mismatch: {field}:{tag_id}")
        bindings = Counter(binding for _, binding in rows)
        reported_bindings = _object(theme.get("brand_binding_counts"), f"{field}.{tag_id}.brand_binding_counts")
        _check(
            set(reported_bindings) == BRAND_BINDINGS,
            f"risk binding structure mismatch: {field}:{tag_id}",
        )
        for binding, count in reported_bindings.items():
            _check(count == bindings[binding], f"risk binding count mismatch: {field}:{tag_id}.{binding}")
        _check(sum(reported_bindings.values()) == len(rows), f"risk binding conservation mismatch: {field}:{tag_id}")
        expected_rate = round(total / len(unique_all), 6) if unique_all else 0.0
        _check(theme.get("brand_binding_rate") == expected_rate, f"risk binding rate mismatch: {field}:{tag_id}")
        expected_sentence_rate = round(
            bindings["momcozy_sentence_bound"] / total, 6
        )
        _check(
            theme.get("sentence_bound_rate") == expected_sentence_rate,
            f"risk sentence-bound rate mismatch: {field}:{tag_id}",
        )
        expected_posts = {entity.post_id for entity in unique_momcozy.values()}
        expected_communities = {
            entity.subreddit
            for entity in unique_momcozy.values()
            if entity.subreddit.casefold() != "unknown"
        }
        _check(
            theme.get("distinct_posts") == len(expected_posts),
            f"risk distinct-post count mismatch: {field}:{tag_id}",
        )
        _check(
            theme.get("communities") == len(expected_communities),
            f"risk community count mismatch: {field}:{tag_id}",
        )
        times = sorted(entity.event_time for entity in unique_momcozy.values())
        event_window = _object(
            theme.get("event_window"), f"{field}.{tag_id}.event_window"
        )
        _check(
            _parse_utc(event_window.get("first_utc"), f"{field}.{tag_id}.event_window.first_utc")
            == times[0],
            f"risk first-event mismatch: {field}:{tag_id}",
        )
        _check(
            _parse_utc(event_window.get("last_utc"), f"{field}.{tag_id}.event_window.last_utc")
            == times[-1],
            f"risk last-event mismatch: {field}:{tag_id}",
        )
        gate = _object(theme.get("evidence_gate"), f"{field}.{tag_id}.evidence_gate")
        semantic_status = "promoted" if tag_id in promoted else "provisional"
        _check(gate.get("semantic_status") == semantic_status, f"risk semantic status mismatch: {field}:{tag_id}")
        reasons = gate.get("reason_codes")
        _check(isinstance(reasons, list) and reasons == sorted(set(reasons)), f"risk gate reason mismatch: {field}:{tag_id}")
        if gate.get("status") == "passed":
            _check(not reasons, f"passed risk gate has reasons: {field}:{tag_id}")
            _check(theme.get("effective_priority") == rule.get("default_priority"), f"passed risk priority mismatch: {field}:{tag_id}")
        else:
            _check(gate.get("status") == "insufficient" and bool(reasons), f"risk gate status mismatch: {field}:{tag_id}")
            _check(theme.get("effective_priority") == "insufficient", f"insufficient risk priority mismatch: {field}:{tag_id}")
    return len(themes)


def _validate_product_period_analysis(
    value: Any,
    *,
    all_entities: Sequence[Entity],
    window_set: WindowSet,
    period: str,
    field: str,
) -> None:
    analysis = _object(value, field)
    _check(analysis.get("schema_version") == "reddit_voc_product_period_metrics_v1", f"product period schema mismatch: {field}")
    _check(analysis.get("decision_subject") == "momcozy", f"product period subject mismatch: {field}")
    _check(analysis.get("period") == period, f"product period mismatch: {field}")
    _check(analysis.get("scope_order") == list(PRODUCT_LEVELS), f"product period scope order mismatch: {field}")
    relevant_windows = (
        window_set.current,
        window_set.previous,
        window_set.year_over_year,
        *window_set.trend,
    )
    relevant = [
        entity
        for entity in all_entities
        if any(_in_window(entity, window) for window in relevant_windows)
    ]
    expected_catalog = _product_catalog(relevant, momcozy_entities_only=True)
    current_entities = _window_entities(all_entities, window_set.current)
    for level in PRODUCT_LEVELS:
        rows = _rows(analysis.get(level), f"{field}.{level}")
        by_id: dict[str, dict[str, Any]] = {}
        for index, row in enumerate(rows):
            scope_id = _nonempty(row.get("scope_id"), f"{field}.{level}[{index}].scope_id")
            _check(scope_id not in by_id, f"duplicate product period scope: {field}.{level}:{scope_id}")
            by_id[scope_id] = row
        _check(set(by_id) == set(expected_catalog[level]), f"product period scope set mismatch: {field}.{level}")
        for scope_id, reference in expected_catalog[level].items():
            row = by_id[scope_id]
            _check(row.get("binding_level") == level, f"product period level mismatch: {field}.{level}:{scope_id}")
            _check(row.get("scope_name_en") == reference[1], f"product period name mismatch: {field}.{level}:{scope_id}")
            _check(row.get("scope_name_cn") == reference[2], f"product period name mismatch: {field}.{level}:{scope_id}")
            scoped_current = _entities_for_scope(current_entities, level, scope_id)
            current = _object(row.get("current"), f"{field}.{level}.{scope_id}.current")
            for entity_type in ENTITY_TYPES:
                type_metrics = _object(current.get(entity_type), f"{field}.{level}.{scope_id}.current.{entity_type}")
                count = sum(entity.entity_type == entity_type for entity in scoped_current)
                for metric_name in ("observed_count", "negative_evidence_share"):
                    _validate_observation(
                        type_metrics.get(metric_name),
                        field=f"{field}.{level}.{scope_id}.current.{entity_type}.{metric_name}",
                        expected_count=count,
                    )
            comparisons = _object(row.get("period_comparisons"), f"{field}.{level}.{scope_id}.period_comparisons")
            for group in ("previous_period", "year_over_year"):
                grouped = _object(comparisons.get(group), f"{field}.{level}.{scope_id}.period_comparisons.{group}")
                for entity_type in ENTITY_TYPES:
                    metrics = _object(grouped.get(entity_type), f"{field}.{level}.{scope_id}.period_comparisons.{group}.{entity_type}")
                    for metric_name in ("observed_count", "negative_evidence_share"):
                        _validate_comparison(
                            metrics.get(metric_name),
                            field=f"{field}.{level}.{scope_id}.period_comparisons.{group}.{entity_type}.{metric_name}",
                            entity_type=entity_type,
                            metric_name=metric_name,
                            comparison_type=_comparison_type(period, group),
                        )
            _validate_product_trend(
                row.get("trend"),
                window_set=window_set,
                period=period,
                field=f"{field}.{level}.{scope_id}.trend",
            )


def _validate_product_trend(
    value: Any, *, window_set: WindowSet, period: str, field: str
) -> None:
    trend = _object(value, field)
    points = _rows(trend.get("points"), f"{field}.points")
    _check(trend.get("point_count") == len(points) == len(window_set.trend), f"product trend point count mismatch: {field}")
    adjacent_statuses: list[str] = []
    for index, (point, expected_window) in enumerate(zip(points, window_set.trend, strict=True)):
        _validate_window_record(point.get("window"), expected_window, field=f"{field}.points[{index}].window")
        current_change = point.get("change_from_previous")
        if index == 0:
            _check(current_change is None, f"first product trend point has comparison: {field}")
            continue
        changes = _object(current_change, f"{field}.points[{index}].change_from_previous")
        for entity_type in ENTITY_TYPES:
            metrics = _object(changes.get(entity_type), f"{field}.points[{index}].change_from_previous.{entity_type}")
            for metric_name in ("observed_count", "negative_evidence_share"):
                adjacent_statuses.append(
                    _validate_comparison(
                        metrics.get(metric_name),
                        field=f"{field}.points[{index}].change_from_previous.{entity_type}.{metric_name}",
                        entity_type=entity_type,
                        metric_name=metric_name,
                        comparison_type="trend_period_over_period",
                    )
                )
    expected_direction = bool(adjacent_statuses) and all(
        status == "comparable" for status in adjacent_statuses
    )
    _check(trend.get("direction_claim_supported") is expected_direction, f"product trend direction mismatch: {field}")


def _validate_report_trend(
    value: Any, *, window_set: WindowSet, period: str, field: str
) -> None:
    trend = _object(value, field)
    _check(trend.get("period") == period, f"trend period mismatch: {field}")
    points = _rows(trend.get("points"), f"{field}.points")
    _check(trend.get("point_count") == len(points) == len(window_set.trend), f"trend point count mismatch: {field}")
    statuses: dict[str, list[str]] = {
        "negative_evidence_share": [],
        "observed_count": [],
    }
    for index, (point, expected_window) in enumerate(zip(points, window_set.trend, strict=True)):
        _validate_window_record(point.get("window"), expected_window, field=f"{field}.points[{index}].window")
        for metric_name in ("negative_evidence_share", "observed_count"):
            observations = _object(point.get(metric_name), f"{field}.points[{index}].{metric_name}")
            for entity_type in ENTITY_TYPES:
                _validate_observation(
                    observations.get(entity_type),
                    field=f"{field}.points[{index}].{metric_name}.{entity_type}",
                )
        if index == 0:
            _check(point.get("change_from_previous") is None, f"first trend point has comparison: {field}")
            _check(point.get("observed_count_change_from_previous") is None, f"first trend volume point has comparison: {field}")
            continue
        for metric_name, key in (
            ("negative_evidence_share", "change_from_previous"),
            ("observed_count", "observed_count_change_from_previous"),
        ):
            changes = _object(point.get(key), f"{field}.points[{index}].{key}")
            for entity_type in ENTITY_TYPES:
                statuses[metric_name].append(
                    _validate_comparison(
                        changes.get(entity_type),
                        field=f"{field}.points[{index}].{key}.{entity_type}",
                        entity_type=entity_type,
                        metric_name=metric_name,
                        comparison_type="trend_period_over_period",
                    )
                )
    expected_by_metric = {
        metric_name: bool(values) and all(status == "comparable" for status in values)
        for metric_name, values in statuses.items()
    }
    _check(trend.get("direction_claim_supported_by_metric") == expected_by_metric, f"trend metric direction mismatch: {field}")
    _check(trend.get("direction_claim_supported") is all(expected_by_metric.values()), f"trend direction mismatch: {field}")


def _normalise_brand(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _is_momcozy_name(value: str) -> bool:
    return _normalise_brand(value) in {"momcozy", "mcozy"}


def _competitor_brand_groups(
    entities: Sequence[Entity],
) -> tuple[dict[str, dict[tuple[str, str], Entity]], dict[str, str]]:
    grouped: dict[str, dict[tuple[str, str], Entity]] = defaultdict(dict)
    display_names: dict[str, str] = {}
    for entity in entities:
        if entity.brand_binding != "competitor_sentence_bound":
            continue
        raw_names = entity.row.get("mentioned_brands")
        if not isinstance(raw_names, list) or not raw_names:
            raise ValueError("competitor brand names missing")
        _check(
            all(isinstance(name, str) and bool(name.strip()) for name in raw_names),
            "competitor brand-name contract mismatch",
        )
        names = [cast(str, name).strip() for name in raw_names]
        _check(
            not any(_is_momcozy_name(name) for name in names),
            "Momcozy leaked into competitor binding",
        )
        _check(
            not entity.product_bindings,
            "governed Momcozy product leaked into competitor binding",
        )
        for brand in names:
            key = _normalise_brand(brand)
            _check(bool(key), "normalised competitor brand is empty")
            grouped[key][(entity.entity_type, entity.entity_id)] = entity
            display_names.setdefault(key, brand)
    return grouped, display_names


def _competitor_metric(
    entities: Iterable[Entity], metric_name: str
) -> dict[str, Any]:
    unique = {
        (entity.entity_type, entity.entity_id): entity for entity in entities
    }
    rows = list(unique.values())
    if metric_name == "observed_count":
        return {
            "metric": "competitor_brand_bound_observed_entity_count",
            "value": len(rows),
            "unit": "observed_entity",
            "value_status": "observed",
        }
    _check(metric_name == "negative_evidence_share", "unknown competitor metric")
    numerator = sum(entity.sentiment == "negative" for entity in rows)
    denominator = len(rows)
    return {
        "metric": (
            "negative_competitor_observed_entities_over_classified_"
            "competitor_observed_entities"
        ),
        "numerator": numerator,
        "denominator": denominator,
        "value": round(numerator / denominator, 6) if denominator else None,
        "value_status": "observed" if denominator else "denominator_zero",
    }


def _competitor_null_metric(metric_name: str) -> dict[str, Any]:
    if metric_name == "observed_count":
        return {
            "metric": "competitor_brand_bound_observed_entity_count",
            "value": None,
            "unit": "observed_entity",
            "value_status": "unavailable",
        }
    return {
        "metric": (
            "negative_competitor_observed_entities_over_classified_"
            "competitor_observed_entities"
        ),
        "numerator": None,
        "denominator": None,
        "value": None,
        "value_status": "unavailable",
    }


def _ranked_competitor_dimension(
    values: Iterable[str], *, key: str, limit: int = 5
) -> list[dict[str, Any]]:
    counts = Counter(value for value in values if value)
    return [
        {key: value, "observed_entities": count}
        for value, count in sorted(
            counts.items(), key=lambda item: (-item[1], item[0])
        )[:limit]
    ]


def _entity_topic(entity: Entity) -> str:
    analysis = _object(entity.row.get("analysis"), "competitor.analysis")
    value = analysis.get("topic")
    return value.strip() if isinstance(value, str) and value.strip() else "unclassified"


def _entity_pain_points(entity: Entity) -> set[str]:
    analysis = _object(entity.row.get("analysis"), "competitor.analysis")
    raw = analysis.get("pain_points", [])
    _check(isinstance(raw, list), "competitor pain-point contract mismatch")
    _check(
        all(isinstance(value, str) and bool(value.strip()) for value in raw),
        "competitor pain-point contract mismatch",
    )
    return {cast(str, value).strip() for value in raw}


def _entity_tag_ids(entity: Entity) -> set[str]:
    output: set[str] = set()
    for match in entity.matches:
        tag_id = _nonempty(match.get("tag_id"), "competitor.tagging.matches.tag_id")
        output.add(tag_id)
    return output


def _validate_competitor_comparison(
    value: Any,
    *,
    current_entities: Sequence[Entity],
    baseline_entities: Sequence[Entity],
    entity_type: str,
    metric_name: str,
    comparison_type: str,
    field: str,
) -> str:
    status = _validate_comparison(
        value,
        field=field,
        entity_type=entity_type,
        metric_name=metric_name,
        comparison_type=comparison_type,
    )
    comparison = _object(value, field)
    reasons = set(_rows_or_strings(comparison.get("reason_codes"), f"{field}.reason_codes"))
    current_rows = [
        entity for entity in current_entities if entity.entity_type == entity_type
    ]
    baseline_rows = [
        entity for entity in baseline_entities if entity.entity_type == entity_type
    ]
    current_expected = (
        _competitor_null_metric(metric_name)
        if "current_observation_absent_under_incomplete_coverage" in reasons
        else _competitor_metric(current_rows, metric_name)
    )
    baseline_expected: dict[str, Any] | None
    if (
        "baseline_coverage_missing" in reasons
        or "baseline_observation_absent_under_incomplete_coverage" in reasons
    ):
        baseline_expected = None
    else:
        baseline_expected = _competitor_metric(baseline_rows, metric_name)
    _check(
        comparison.get("current") == current_expected,
        f"competitor comparison current mismatch: {field}",
    )
    _check(
        comparison.get("baseline") == baseline_expected,
        f"competitor comparison baseline mismatch: {field}",
    )
    absolute_delta: float | None = None
    relative_delta: float | None = None
    delta_reason: str | None = None
    if status != "unavailable" and baseline_expected is not None:
        current_value = current_expected["value"]
        baseline_value = baseline_expected["value"]
        if current_value is None:
            delta_reason = "current_denominator_zero"
        elif baseline_value is None:
            delta_reason = "baseline_denominator_zero"
        else:
            absolute_delta = round(float(current_value) - float(baseline_value), 6)
            if float(baseline_value) == 0:
                delta_reason = "baseline_value_zero_relative_delta_undefined"
            else:
                relative_delta = round(absolute_delta / float(baseline_value), 6)
    elif status == "unavailable":
        delta_reason = "comparison_gate_unavailable"
    _check(
        comparison.get("absolute_delta") == absolute_delta,
        f"competitor comparison absolute delta mismatch: {field}",
    )
    _check(
        comparison.get("relative_delta") == relative_delta,
        f"competitor comparison relative delta mismatch: {field}",
    )
    _check(
        comparison.get("delta_reason") == delta_reason,
        f"competitor comparison delta reason mismatch: {field}",
    )
    expected_direction = status == "comparable" and absolute_delta is not None
    _check(
        comparison.get("direction_claim_supported") is expected_direction,
        f"competitor comparison direction mismatch: {field}",
    )
    return status


def _validate_competitor_context(
    value: Any,
    *,
    current_entities: Sequence[Entity],
    previous_entities: Sequence[Entity] | None,
    year_over_year_entities: Sequence[Entity] | None,
    previous_comparison_type: str | None,
    field: str,
) -> int:
    rows = _rows(value, field)
    current_groups, display_names = _competitor_brand_groups(current_entities)
    previous_groups, _ = _competitor_brand_groups(previous_entities or [])
    yoy_groups, _ = _competitor_brand_groups(year_over_year_entities or [])
    expected_ids = sorted(current_groups)
    _check(
        [row.get("brand_id") for row in rows] == expected_ids,
        f"competitor brand set/order mismatch: {field}",
    )
    include_comparisons = (
        previous_entities is not None and year_over_year_entities is not None
    )
    base_keys = {
        "brand_id",
        "brand_name",
        "comparison_role",
        "negative_evidence_share",
        "observed_count",
        "top_topics",
        "top_pain_points",
        "top_communities",
        "top_risk_tags",
        "product_scope_ids",
        "product_taxonomy",
        "interpretation_boundary",
    }
    for row, brand_id in zip(rows, expected_ids, strict=True):
        expected_keys = base_keys | ({"period_comparisons", "trend"} if include_comparisons else set())
        _check(set(row) == expected_keys, f"competitor row field mismatch: {field}.{brand_id}")
        _check(row.get("brand_name") == display_names[brand_id], f"competitor display-name mismatch: {field}.{brand_id}")
        _check(row.get("comparison_role") == "same_observed_sample_context", f"competitor role mismatch: {field}.{brand_id}")
        brand_entities = list(current_groups[brand_id].values())
        previous_brand_entities = list(previous_groups.get(brand_id, {}).values())
        yoy_brand_entities = list(yoy_groups.get(brand_id, {}).values())
        for metric_name in ("negative_evidence_share", "observed_count"):
            metrics = _object(row.get(metric_name), f"{field}.{brand_id}.{metric_name}")
            _check(set(metrics) == set(ENTITY_TYPES), f"competitor metric entity set mismatch: {field}.{brand_id}.{metric_name}")
            for entity_type in ENTITY_TYPES:
                expected_metric = _competitor_metric(
                    (
                        entity
                        for entity in brand_entities
                        if entity.entity_type == entity_type
                    ),
                    metric_name,
                )
                _check(
                    metrics.get(entity_type) == expected_metric,
                    f"competitor metric mismatch: {field}.{brand_id}.{metric_name}.{entity_type}",
                )
        _check(
            row.get("top_topics")
            == _ranked_competitor_dimension(
                (_entity_topic(entity) for entity in brand_entities), key="topic"
            ),
            f"competitor topic ranking mismatch: {field}.{brand_id}",
        )
        _check(
            row.get("top_pain_points")
            == _ranked_competitor_dimension(
                (
                    pain_point
                    for entity in brand_entities
                    for pain_point in _entity_pain_points(entity)
                ),
                key="pain_point",
            ),
            f"competitor pain-point ranking mismatch: {field}.{brand_id}",
        )
        _check(
            row.get("top_communities")
            == _ranked_competitor_dimension(
                (entity.subreddit for entity in brand_entities), key="subreddit"
            ),
            f"competitor community ranking mismatch: {field}.{brand_id}",
        )
        _check(
            row.get("top_risk_tags")
            == _ranked_competitor_dimension(
                (
                    tag_id
                    for entity in brand_entities
                    for tag_id in _entity_tag_ids(entity)
                ),
                key="tag_id",
            ),
            f"competitor risk-tag ranking mismatch: {field}.{brand_id}",
        )
        _check(
            row.get("product_scope_ids")
            == {"category": [], "product_family": [], "spu_exact": []},
            f"competitor product scope overclaim: {field}.{brand_id}",
        )
        _check(
            row.get("product_taxonomy")
            == {
                "status": "unavailable_no_competitor_taxonomy",
                "category": [],
                "product_family": [],
                "spu_exact": [],
                "reason_code": "competitor_product_catalog_not_governed",
            },
            f"competitor product taxonomy overclaim: {field}.{brand_id}",
        )
        _check(
            row.get("interpretation_boundary")
            == "comparison_is_not_market_share_sov_penetration_or_sales",
            f"competitor interpretation boundary mismatch: {field}.{brand_id}",
        )
        if not include_comparisons:
            continue
        comparison_groups = _object(
            row.get("period_comparisons"), f"{field}.{brand_id}.period_comparisons"
        )
        _check(
            set(comparison_groups) == {"previous_period", "year_over_year"},
            f"competitor comparison group mismatch: {field}.{brand_id}",
        )
        previous_comparisons: dict[str, Any] | None = None
        for group, baseline_entities, comparison_type in (
            (
                "previous_period",
                previous_brand_entities,
                previous_comparison_type or "period_over_period",
            ),
            ("year_over_year", yoy_brand_entities, "year_over_year"),
        ):
            grouped = _object(
                comparison_groups.get(group),
                f"{field}.{brand_id}.period_comparisons.{group}",
            )
            _check(
                set(grouped) == {"observed_count", "negative_evidence_share"},
                f"competitor comparison metric set mismatch: {field}.{brand_id}.{group}",
            )
            for metric_name in ("observed_count", "negative_evidence_share"):
                metrics = _object(
                    grouped.get(metric_name),
                    f"{field}.{brand_id}.period_comparisons.{group}.{metric_name}",
                )
                _check(
                    set(metrics) == set(ENTITY_TYPES),
                    f"competitor comparison entity set mismatch: {field}.{brand_id}.{group}.{metric_name}",
                )
                for entity_type in ENTITY_TYPES:
                    _validate_competitor_comparison(
                        metrics.get(entity_type),
                        current_entities=brand_entities,
                        baseline_entities=baseline_entities,
                        entity_type=entity_type,
                        metric_name=metric_name,
                        comparison_type=comparison_type,
                        field=(
                            f"{field}.{brand_id}.period_comparisons.{group}."
                            f"{metric_name}.{entity_type}"
                        ),
                    )
            if group == "previous_period":
                previous_comparisons = grouped
        trend = _object(row.get("trend"), f"{field}.{brand_id}.trend")
        _check(set(trend) == {"basis", "direction_claim_supported", "comparisons"}, f"competitor trend field mismatch: {field}.{brand_id}")
        _check(trend.get("basis") == "current_vs_previous_period", f"competitor trend basis mismatch: {field}.{brand_id}")
        _check(trend.get("comparisons") == previous_comparisons, f"competitor trend comparison mismatch: {field}.{brand_id}")
        expected_direction = all(
            comparison.get("comparison_status") == "comparable"
            and comparison.get("direction_claim_supported") is True
            for metric in cast(dict[str, dict[str, Any]], previous_comparisons).values()
            for comparison in metric.values()
        )
        _check(
            trend.get("direction_claim_supported") is expected_direction,
            f"competitor trend direction mismatch: {field}.{brand_id}",
        )
    return len(rows)


def _validate_report(
    report: dict[str, Any],
    *,
    descriptor: dict[str, Any],
    collection: str,
    period: str,
    expected_version: str,
    as_of: datetime,
    window_set: WindowSet,
    all_entities: Sequence[Entity],
    rules: Mapping[str, dict[str, Any]],
    promoted: set[str],
    quarantined_comments: int,
    field: str,
) -> tuple[int, list[str]]:
    _check(report.get("schema_version") == "reddit_voc_report_v1", f"report schema mismatch: {field}")
    _check(report.get("contract_extension") == "reddit_voc_risk_report_v2", f"report extension mismatch: {field}")
    identity = _object(report.get("identity"), f"{field}.identity")
    _check(identity.get("dataset_version") == expected_version, f"report version mismatch: {field}")
    _check(identity.get("period") == period, f"report period mismatch: {field}")
    _check(identity.get("window_mode") == "calendar_closed", f"report window mode mismatch: {field}")
    window = _object(report.get("window"), f"{field}.window")
    _validate_window_record(window, window_set.current, field=f"{field}.window")
    _check(_parse_utc(window.get("as_of_utc"), f"{field}.window.as_of_utc") == as_of, f"report as-of mismatch: {field}")
    _check(window.get("bucket_grain") == ("hour" if period == "daily" else "day"), f"report bucket grain mismatch: {field}")
    _check(window.get("coverage_status") in {"complete", "partial", "unavailable", "coverage_missing"}, f"report coverage status mismatch: {field}")

    current_entities = _window_entities(all_entities, window_set.current)
    posts = [entity for entity in current_entities if entity.entity_type == "post"]
    comments = [entity for entity in current_entities if entity.entity_type == "comment"]
    headline = _object(report.get("headline"), f"{field}.headline")
    _check(headline.get("posts") == len(posts), f"headline post count mismatch: {field}")
    _check(headline.get("voc_comments") == len(comments), f"headline comment count mismatch: {field}")
    _check(headline.get("observed_entities") == len(current_entities), f"headline entity count mismatch: {field}")
    _check(headline.get("quarantined_comments_in_base_snapshot") == quarantined_comments, f"headline quarantine mismatch: {field}")
    _check(headline.get("quarantined_comments_counted") == 0, f"quarantine leaked into report: {field}")

    comparison_statuses: list[str] = []
    for metric_name, root_name in (
        ("negative_evidence_share", "period_comparisons"),
        ("observed_count", "observed_count_comparisons"),
    ):
        comparisons = _object(report.get(root_name), f"{field}.{root_name}")
        for group in ("previous_period", "year_over_year"):
            grouped = _object(comparisons.get(group), f"{field}.{root_name}.{group}")
            for entity_type in ENTITY_TYPES:
                comparison_statuses.append(
                    _validate_comparison(
                        grouped.get(entity_type),
                        field=f"{field}.{root_name}.{group}.{entity_type}",
                        entity_type=entity_type,
                        metric_name=metric_name,
                        comparison_type=_comparison_type(period, group),
                    )
                )
    expected_overall = _overall_status(comparison_statuses)
    _check(window.get("comparison_status") == expected_overall, f"report comparison status mismatch: {field}")
    if window.get("coverage_status") != "complete":
        _check(
            all(status != "comparable" for status in comparison_statuses),
            f"incomplete coverage comparison overclaim: {field}",
        )

    momcozy_metrics = _object(
        report.get("momcozy_metrics"), f"{field}.momcozy_metrics"
    )
    for metric_name in ("observed_count", "negative_evidence_share"):
        metric = _object(
            momcozy_metrics.get(metric_name),
            f"{field}.momcozy_metrics.{metric_name}",
        )
        for entity_type in ENTITY_TYPES:
            expected_count = sum(
                entity.entity_type == entity_type
                and entity.brand_binding in MOMCOZY_BINDINGS
                for entity in current_entities
            )
            _validate_observation(
                metric.get(entity_type),
                field=f"{field}.momcozy_metrics.{metric_name}.{entity_type}",
                expected_count=expected_count,
            )
        combined = _object(
            metric.get("combined"),
            f"{field}.momcozy_metrics.{metric_name}.combined",
        )
        _check(
            combined.get("supported") is False and combined.get("value") is None,
            f"combined report metric overclaim: {field}.{metric_name}",
        )

    reported_path = descriptor.get("path")
    _check(descriptor.get("period") == period, f"index period mismatch: {field}")
    _check(descriptor.get("window_mode") == "calendar_closed", f"index window mode mismatch: {field}")
    _check(descriptor.get("report_id") == identity.get("report_id"), f"index report id mismatch: {field}")
    _check(descriptor.get("display_name") == identity.get("display_name"), f"index display mismatch: {field}")
    _check(_parse_utc(descriptor.get("start_utc"), f"{field}.descriptor.start_utc") == window_set.current.start_utc, f"index start mismatch: {field}")
    _check(_parse_utc(descriptor.get("end_utc"), f"{field}.descriptor.end_utc") == window_set.current.end_utc, f"index end mismatch: {field}")
    _check(descriptor.get("coverage_status") == window.get("coverage_status"), f"index coverage mismatch: {field}")
    _check(descriptor.get("comparison_status") == expected_overall, f"index comparison mismatch: {field}")
    _check(descriptor.get("posts") == len(posts), f"index post count mismatch: {field}")
    _check(descriptor.get("voc_comments") == len(comments), f"index comment count mismatch: {field}")
    _nonempty(reported_path, f"{field}.descriptor.path")

    product_catalog = _validate_product_analysis(
        report.get("product_analysis"), current_entities, f"{field}.product_analysis"
    )
    _validate_product_period_analysis(
        report.get("product_period_analysis"),
        all_entities=all_entities,
        window_set=window_set,
        period=period,
        field=f"{field}.product_period_analysis",
    )
    theme_count = _validate_risk_themes(
        report.get("risk_themes"),
        entities=all_entities,
        rules=rules,
        promoted=promoted,
        window=window_set.current,
        field=f"{field}.risk_themes",
    )
    _check(momcozy_metrics.get("risk_theme_count") == theme_count, f"report risk theme count mismatch: {field}")
    _validate_report_trend(
        report.get("trend"), window_set=window_set, period=period, field=f"{field}.trend"
    )
    _validate_competitor_context(
        report.get("competitor_context"),
        current_entities=current_entities,
        previous_entities=_window_entities(all_entities, window_set.previous),
        year_over_year_entities=_window_entities(
            all_entities, window_set.year_over_year
        ),
        previous_comparison_type=_comparison_type(period, "previous_period"),
        field=f"{field}.competitor_context",
    )
    _validate_capabilities(report.get("capabilities"), f"{field}.capabilities")
    interpretation = _object(report.get("interpretation_boundaries"), f"{field}.interpretation_boundaries")
    _check(interpretation.get("market_share_supported") is False, f"market-share boundary mismatch: {field}")
    _check(interpretation.get("roi_supported") is False, f"ROI boundary mismatch: {field}")
    _check(interpretation.get("combined_view_supported") is False, f"combined-view boundary mismatch: {field}")
    _check(interpretation.get("competitors_are_context_only") is True, f"competitor context boundary mismatch: {field}")
    expected_direction = all(status == "comparable" for status in comparison_statuses)
    _check(interpretation.get("trend_claim_supported") is expected_direction, f"report trend boundary mismatch: {field}")
    runtime = _object(report.get("runtime_boundaries"), f"{field}.runtime_boundaries")
    _check(runtime.get("production_unchanged") is True, f"production boundary mismatch: {field}")
    _validate_false_fields(runtime, REPORT_SIDE_EFFECT_FIELDS, f"{field}.runtime_boundaries")
    _validate_recursive_support_flags(report, field)
    return theme_count, [
        scope_id
        for level in PRODUCT_LEVELS
        for scope_id in product_catalog[level]
    ]


def validate(
    base_dir: Path,
    insights_dir: Path,
    reports_dir: Path,
    *,
    expected_insights_version: str,
    expected_reports_version: str,
    semantic_governance_path: Path | None = None,
    source_semantic_audit_path: Path | None = None,
    expected_source_semantic_audit_sha256: str | None = None,
    candidate_ledger_manifest_path: Path | None = None,
    ledger_validation_receipt_path: Path | None = None,
    expected_ledger_validation_receipt_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate one Base + Insights + Reports candidate without mutating it."""

    for directory, label in (
        (base_dir, "base"),
        (insights_dir, "insights"),
        (reports_dir, "reports"),
    ):
        _check(directory.is_dir(), f"{label} directory missing")
    _validate_private_analytics_tree(insights_dir, "insights")
    _validate_private_analytics_tree(reports_dir, "reports")

    base_manifest_path = base_dir / "manifest.json"
    insights_manifest_path = insights_dir / "manifest.json"
    reports_manifest_path = reports_dir / "manifest.json"
    base_manifest = _object(_load(base_manifest_path), "base_manifest")
    insights_manifest = _object(_load(insights_manifest_path), "insights_manifest")
    reports_manifest = _object(_load(reports_manifest_path), "reports_manifest")
    base_paths = _validate_manifest_files(
        base_dir,
        base_manifest,
        required={"posts.json", "comments.json", "tag-dictionary.json"},
    )
    insights_paths = _validate_manifest_files(
        insights_dir,
        insights_manifest,
        required=INSIGHTS_FILES,
        exact=INSIGHTS_FILES,
    )

    base_version = _nonempty(base_manifest.get("dataset_version"), "base_manifest.dataset_version")
    _check(
        base_manifest.get("schema_version")
        in {
            "reddit_voc_site_snapshot_manifest_v1",
            "reddit_voc_site_snapshot_manifest_v2",
        },
        "base manifest schema mismatch",
    )
    if base_manifest.get("schema_version") == "reddit_voc_site_snapshot_manifest_v2":
        _check(base_manifest.get("all_checks_passed") is True, "base v2 not validated")
    _check(insights_manifest.get("schema_version") == "reddit_voc_insights_manifest_v1", "insights manifest schema mismatch")
    _check(insights_manifest.get("contract_extension") == "reddit_voc_insights_manifest_v2", "insights manifest extension mismatch")
    _check(insights_manifest.get("dataset_version") == expected_insights_version, "insights expected version mismatch")
    _check(reports_manifest.get("schema_version") == "reddit_voc_reports_manifest_v1", "reports manifest schema mismatch")
    _check(reports_manifest.get("contract_extension") == "reddit_voc_reports_manifest_v2", "reports manifest extension mismatch")
    _check(reports_manifest.get("dataset_version") == expected_reports_version, "reports expected version mismatch")

    base_manifest_sha = _sha256(base_manifest_path)
    insights_manifest_sha = _sha256(insights_manifest_path)
    reports_manifest_sha = _sha256(reports_manifest_path)
    _check(insights_manifest.get("base_dataset_version") == base_version, "insights/base version lineage mismatch")
    _check(insights_manifest.get("base_manifest_sha256") == base_manifest_sha, "insights/base hash lineage mismatch")
    _check(insights_manifest.get("reports_dataset_version") == expected_reports_version, "insights/reports version lineage mismatch")
    _check(reports_manifest.get("base_dataset_version") == base_version, "reports/base version lineage mismatch")
    _check(reports_manifest.get("base_manifest_sha256") == base_manifest_sha, "reports/base hash lineage mismatch")
    _check(reports_manifest.get("insights_dataset_version") == expected_insights_version, "reports/insights version lineage mismatch")
    _check(reports_manifest.get("insights_manifest_sha256") == insights_manifest_sha, "reports/insights hash lineage mismatch")
    _check(
        reports_manifest.get("status") == insights_manifest.get("status"),
        "analytics manifest status mismatch",
    )

    posts = _rows(_load(base_paths["posts.json"]), "posts")
    comments = _rows(_load(base_paths["comments.json"]), "comments")
    tag_dictionary = _object(_load(base_paths["tag-dictionary.json"]), "tag_dictionary")
    rules_list = _rows(tag_dictionary.get("rules"), "tag_dictionary.rules")
    rules: dict[str, dict[str, Any]] = {}
    for index, rule in enumerate(rules_list):
        tag_id = _nonempty(rule.get("tag_id"), f"tag_dictionary.rules[{index}].tag_id")
        _check(tag_id not in rules, f"duplicate dictionary tag id: {tag_id}")
        rules[tag_id] = rule
    dictionary_version = _nonempty(tag_dictionary.get("dictionary_version"), "tag_dictionary.dictionary_version")
    dictionary_sha = _nonempty(tag_dictionary.get("dictionary_sha256"), "tag_dictionary.dictionary_sha256")
    for manifest, label in (
        (insights_manifest, "insights_manifest"),
        (reports_manifest, "reports_manifest"),
    ):
        _check(manifest.get("dictionary_version") == dictionary_version, f"dictionary version lineage mismatch: {label}")
        _check(manifest.get("dictionary_sha256") == dictionary_sha, f"dictionary hash lineage mismatch: {label}")

    entities, posts_by_id, comments_by_id, _ = _build_entities(posts, comments)
    canonical = _object(base_manifest.get("canonical_counts"), "base_manifest.canonical_counts")
    quarantined = _integer(canonical.get("quarantined_comments"), "base_manifest.canonical_counts.quarantined_comments")
    _check(canonical.get("posts") == len(posts_by_id), "base post count mismatch")
    _check(canonical.get("linked_comments") == len(comments), "base linked comment count mismatch")
    _check(canonical.get("stored_comments") == len(comments) + quarantined, "base stored comment conservation mismatch")

    insights = _object(_load(insights_paths["insights.json"]), "insights")
    audit = _object(_load(insights_paths["semantic-audit.json"]), "semantic_audit")
    _check(insights.get("schema_version") == "reddit_voc_insights_v2", "insights schema mismatch")
    _check(insights.get("dataset_version") == expected_insights_version, "insights payload version mismatch")
    _check(insights.get("base_dataset_version") == base_version, "insights payload base mismatch")
    _check(audit.get("schema_version") == "reddit_voc_tag_semantic_audit_v2", "semantic audit schema mismatch")
    _check(audit.get("base_dataset_version") == base_version, "semantic audit base version mismatch")
    _check(audit.get("base_manifest_sha256") == base_manifest_sha, "semantic audit base hash mismatch")
    _check(audit.get("dictionary_version") == dictionary_version, "semantic audit dictionary version mismatch")
    _check(audit.get("dictionary_sha256") == dictionary_sha, "semantic audit dictionary hash mismatch")

    semantic_projection_receipt: dict[str, Any] | None = None
    semantic_projection_sha = insights_manifest.get("semantic_governance_sha256")
    if isinstance(semantic_projection_sha, str):
        required_projection_inputs = (
            semantic_governance_path,
            source_semantic_audit_path,
            expected_source_semantic_audit_sha256,
            candidate_ledger_manifest_path,
            ledger_validation_receipt_path,
            expected_ledger_validation_receipt_sha256,
        )
        _check(
            all(value is not None for value in required_projection_inputs),
            "semantic projection validation inputs missing",
        )
        semantic_projection_receipt = _validate_projection_sources(
            semantic_governance_path=cast(Path, semantic_governance_path),
            source_semantic_audit_path=cast(Path, source_semantic_audit_path),
            expected_source_semantic_audit_sha256=cast(
                str, expected_source_semantic_audit_sha256
            ),
            candidate_ledger_manifest_path=cast(
                Path, candidate_ledger_manifest_path
            ),
            ledger_validation_receipt_path=cast(
                Path, ledger_validation_receipt_path
            ),
            expected_ledger_validation_receipt_sha256=cast(
                str, expected_ledger_validation_receipt_sha256
            ),
            base_manifest=base_manifest,
            base_manifest_sha=base_manifest_sha,
            tag_dictionary=tag_dictionary,
            posts=posts,
            comments=comments,
            insights=insights,
            projected_audit=audit,
            insights_manifest=insights_manifest,
            reports_manifest=reports_manifest,
        )

    audit_summary = _object(insights_manifest.get("audit_summary"), "insights_manifest.audit_summary")
    audit_projection = _object(audit.get("summary"), "semantic_audit.summary")
    promoted = set(_rows_or_strings(audit_summary.get("promoted_tag_ids"), "audit_summary.promoted_tag_ids"))
    held = set(_rows_or_strings(audit_summary.get("held_tag_ids"), "audit_summary.held_tag_ids"))
    _check(not (promoted & held), "promoted/held tag overlap")
    _check(promoted | held <= set(rules), "semantic tag outside dictionary")
    _check(set(_rows_or_strings(audit_projection.get("promoted_tag_ids"), "semantic_audit.promoted_tag_ids")) == promoted, "semantic promoted set mismatch")
    _check(set(_rows_or_strings(audit_projection.get("held_tag_ids"), "semantic_audit.held_tag_ids")) == held, "semantic held set mismatch")
    _check(audit_summary.get("promoted_tags") == len(promoted), "promoted tag count mismatch")
    _check(audit_summary.get("held_tags") == len(held), "held tag count mismatch")
    _check(audit_summary.get("audited_tags") == len(promoted | held), "audited tag count mismatch")
    _check(
        audit_summary.get("status") == insights_manifest.get("status"),
        "insights audit status mismatch",
    )
    input_contract = _object(insights.get("input_contract"), "insights.input_contract")
    _check(input_contract.get("post_count") == len(posts_by_id), "insights input post count mismatch")
    _check(input_contract.get("comment_count") == len(comments_by_id), "insights input comment count mismatch")
    _check(set(_rows_or_strings(input_contract.get("promoted_tag_ids"), "input_contract.promoted_tag_ids")) == promoted, "insights promoted set mismatch")
    _check(set(_rows_or_strings(input_contract.get("held_tag_ids"), "input_contract.held_tag_ids")) == held, "insights held set mismatch")

    insights_boundary = _object(insights.get("boundaries"), "insights.boundaries")
    manifest_boundary = _object(insights_manifest.get("boundaries"), "insights_manifest.boundaries")
    control = _object(insights.get("control_evidence"), "insights.control_evidence")
    audit_boundary = _object(audit.get("boundaries"), "semantic_audit.boundaries")
    for boundary, label in (
        (insights_boundary, "insights.boundaries"),
        (manifest_boundary, "insights_manifest.boundaries"),
        (control, "insights.control_evidence"),
    ):
        _check(boundary.get("production_unchanged") is True, f"production boundary mismatch: {label}")
        _validate_false_fields(boundary, SIDE_EFFECT_FIELDS, label)
    _check(
        audit_boundary.get("production_unchanged") is True,
        "production boundary mismatch: semantic_audit.boundaries",
    )
    _validate_false_fields(
        audit_boundary,
        ("provider_call", "database_write", "live_send"),
        "semantic_audit.boundaries",
    )
    _check(
        audit_boundary.get("raw_review_samples_included") is False,
        "semantic audit raw-review boundary mismatch",
    )
    _check(control.get("base_dataset_version") == base_version, "control/base version mismatch")
    _check(control.get("base_manifest_sha256") == base_manifest_sha, "control/base hash mismatch")
    _check(control.get("base_generated_at_utc") == base_manifest.get("generated_at_utc"), "control/base time mismatch")

    interpretation = _object(insights.get("interpretation_boundaries"), "insights.interpretation_boundaries")
    for name in ("market_share_supported", "roi_supported", "response_time_supported", "combined_view_supported"):
        _check(interpretation.get(name) is False, f"insights interpretation overclaim: {name}")
    _check(interpretation.get("competitors_are_context_only") is True, "insights competitor boundary mismatch")

    command = _object(insights.get("risk_command_center"), "insights.risk_command_center")
    decision = _object(command.get("decision_subject"), "insights.risk_command_center.decision_subject")
    _check(decision == {"brand_id": "momcozy", "brand_role": "primary", "competitors_role": "comparison_context_only"}, "risk decision subject mismatch")
    command_window_value = _object(command.get("window"), "insights.risk_command_center.window")
    command_window = Window(
        _parse_datetime(command_window_value.get("start_local"), "risk_command_center.window.start_local"),
        _parse_datetime(command_window_value.get("end_local"), "risk_command_center.window.end_local"),
    )
    _validate_window_record(command_window_value, command_window, field="insights.risk_command_center.window")
    _check(command_window.end - command_window.start == timedelta(days=30), "risk command window is not 30 closed days")
    _check(command_window_value.get("window_mode") == "rolling_30_closed_days", "risk command window mode mismatch")
    analytics_as_of = _parse_utc(insights.get("generated_at_utc"), "insights.generated_at_utc")
    expected_command_end = _local_midnight(analytics_as_of.astimezone(TIMEZONE).date())
    _check(command_window.end == expected_command_end, "risk command window anchor mismatch")
    insight_entities = _window_entities(entities, command_window)
    insights_competitor_count = _validate_competitor_context(
        command.get("competitor_context"),
        current_entities=insight_entities,
        previous_entities=None,
        year_over_year_entities=None,
        previous_comparison_type=None,
        field="insights.risk_command_center.competitor_context",
    )
    insight_catalog = _validate_product_analysis(
        insights.get("product_analysis"), insight_entities, "insights.product_analysis"
    )
    insights_theme_count = _validate_risk_themes(
        command.get("risk_themes"),
        entities=entities,
        rules=rules,
        promoted=promoted,
        window=command_window,
        field="insights.risk_command_center.risk_themes",
    )
    priority_distribution = _object(command.get("priority_distribution"), "risk_command_center.priority_distribution")
    _check(sum(_integer(value, f"risk_command_center.priority_distribution.{key}") for key, value in priority_distribution.items()) == insights_theme_count, "risk priority distribution mismatch")

    index_path = reports_dir / "report-index.json"
    index = _object(_load(index_path), "report_index")
    _check(index.get("schema_version") == "reddit_voc_report_index_v1", "report index schema mismatch")
    _check(index.get("contract_extension") == "reddit_voc_report_index_v2", "report index extension mismatch")
    _check(index.get("dataset_version") == expected_reports_version, "report index version mismatch")
    _check(index.get("timezone") == TIMEZONE_NAME, "report index timezone mismatch")
    as_of = _parse_utc(index.get("as_of_utc"), "report_index.as_of_utc")
    _check(as_of == analytics_as_of, "analytics/report time anchor mismatch")
    _check(_parse_utc(insights_manifest.get("generated_at_utc"), "insights_manifest.generated_at_utc") == as_of, "insights manifest time mismatch")
    _check(_parse_utc(reports_manifest.get("generated_at_utc"), "reports_manifest.generated_at_utc") == as_of, "reports manifest time mismatch")

    expected_sets = _expected_window_sets(as_of)
    expected_paths: set[str] = {"report-index.json"}
    report_descriptors: dict[tuple[str, str], dict[str, Any]] = {}
    for collection in COLLECTIONS:
        group = _object(index.get(collection), f"report_index.{collection}")
        _check(set(group) == set(PERIODS), f"report index state set mismatch: {collection}")
        for period in PERIODS:
            descriptor = _object(group.get(period), f"report_index.{collection}.{period}")
            expected_path = _report_path(collection, period, expected_sets[(collection, period)].current)
            _check(descriptor.get("path") == expected_path, f"report path mismatch: {collection}.{period}")
            expected_paths.add(expected_path)
            report_descriptors[(collection, period)] = descriptor
    report_paths = _validate_manifest_files(
        reports_dir,
        reports_manifest,
        required=expected_paths,
        exact=expected_paths,
    )
    _check(reports_manifest.get("report_count") == len(expected_paths) - 1, "report manifest count mismatch")
    _check(set(_rows_or_strings(reports_manifest.get("promoted_tag_ids"), "reports_manifest.promoted_tag_ids")) == promoted, "report promoted set mismatch")
    _check(set(_rows_or_strings(reports_manifest.get("held_tag_ids_excluded"), "reports_manifest.held_tag_ids_excluded")) == held, "report held set mismatch")
    report_boundary = _object(reports_manifest.get("boundaries"), "reports_manifest.boundaries")
    _check(report_boundary.get("production_unchanged") is True, "reports manifest production boundary mismatch")
    _validate_false_fields(report_boundary, REPORT_SIDE_EFFECT_FIELDS, "reports_manifest.boundaries")
    for field in ("independent_human_review", "persona_tags_generated", "market_share_supported", "roi_supported"):
        _check(report_boundary.get(field) is False, f"reports manifest boundary overclaim: {field}")

    embedded_booklets = _object(insights.get("report_booklets"), "insights.report_booklets")
    _check(embedded_booklets.get("dataset_version") == expected_reports_version, "embedded report version mismatch")
    _check(embedded_booklets.get("timezone") == TIMEZONE_NAME, "embedded report timezone mismatch")
    _check(embedded_booklets.get("index") == index, "embedded report index mismatch")

    report_theme_count = 0
    report_scope_rows = 0
    report_trend_claims: list[bool] = []
    for collection in COLLECTIONS:
        for period in PERIODS:
            descriptor = report_descriptors[(collection, period)]
            path = descriptor["path"]
            report = _object(_load(report_paths[path]), f"reports.{path}")
            theme_count, scopes = _validate_report(
                report,
                descriptor=descriptor,
                collection=collection,
                period=period,
                expected_version=expected_reports_version,
                as_of=as_of,
                window_set=expected_sets[(collection, period)],
                all_entities=entities,
                rules=rules,
                promoted=promoted,
                quarantined_comments=quarantined,
                field=f"reports.{path}",
            )
            report_theme_count += theme_count
            report_scope_rows += len(scopes)
            report_trend_claims.append(
                report["interpretation_boundaries"]["trend_claim_supported"]
            )
    _check(
        report_boundary.get("trend_claim_supported")
        is (bool(report_trend_claims) and all(report_trend_claims)),
        "reports manifest trend boundary mismatch",
    )
    _validate_recursive_support_flags(insights, "insights")
    _validate_recursive_support_flags(base_manifest, "base_manifest")
    _validate_recursive_support_flags(reports_manifest, "reports_manifest")

    checks = {
        "manifest_file_bytes_and_hashes": True,
        "private_analytics_tree_modes": True,
        "expected_versions_and_cross_lineage": True,
        "six_report_states_and_closed_windows": True,
        "coverage_and_comparison_reason_contracts": True,
        "risk_theme_base_evidence_and_momcozy_conservation": True,
        "governed_category_family_spu_scope_conservation": True,
        "forbidden_capability_boundaries": True,
        "competitor_observation_context_conservation": True,
        "side_effect_boundaries": True,
        "semantic_governance_current_base_projection": (
            semantic_projection_receipt is not None
            if isinstance(semantic_projection_sha, str)
            else True
        ),
    }
    return {
        "schema_version": "reddit_voc_site_analytics_validation_v1",
        "validated_at_utc": insights.get("generated_at_utc"),
        "status": "passed_release_candidate",
        "release_candidate": True,
        "base_dataset_version": base_version,
        "insights_dataset_version": expected_insights_version,
        "reports_dataset_version": expected_reports_version,
        "base_manifest_sha256": base_manifest_sha,
        "insights_manifest_sha256": insights_manifest_sha,
        "reports_manifest_sha256": reports_manifest_sha,
        "semantic_projection": semantic_projection_receipt,
        "checks": checks,
        "counts": {
            "reports": len(expected_paths) - 1,
            "insights_risk_themes": insights_theme_count,
            "report_risk_theme_occurrences": report_theme_count,
            "insights_product_scopes": sum(len(rows) for rows in insight_catalog.values()),
            "insights_competitor_brands": insights_competitor_count,
            "report_product_scope_occurrences": report_scope_rows,
        },
        "production_unchanged": True,
        "provider_call": False,
        "database_write": False,
        "live_send": False,
        "webhook_send": False,
        "deploy": False,
        "schedule_change": False,
    }


def _rows_or_strings(value: Any, field: str) -> list[str]:
    _check(isinstance(value, list), f"string-list contract mismatch: {field}")
    _check(
        all(isinstance(item, str) and item for item in value),
        f"string-list contract mismatch: {field}",
    )
    _check(len(value) == len(set(value)), f"duplicate string-list value: {field}")
    return value


def _write_receipt(path: Path, result: dict[str, Any]) -> str:
    payload = (
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    if path.exists() or path.is_symlink():
        _check(
            not path.is_symlink() and path.is_file() and path.read_bytes() == payload,
            "validation receipt collision",
        )
        status = "no_change"
    else:
        handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            os.write(handle, payload)
            os.close(handle)
            handle = -1
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            if handle >= 0:
                os.close(handle)
            if temporary.exists():
                temporary.unlink()
        status = "created"
    os.chmod(path, 0o600)
    return status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-dir", type=Path, required=True)
    parser.add_argument("--insights-dir", type=Path, required=True)
    parser.add_argument("--reports-dir", type=Path, required=True)
    parser.add_argument("--expected-insights-version", required=True)
    parser.add_argument("--expected-reports-version", required=True)
    parser.add_argument("--semantic-governance", type=Path)
    parser.add_argument("--source-semantic-audit", type=Path)
    parser.add_argument("--expected-source-semantic-audit-sha256")
    parser.add_argument("--candidate-ledger-manifest", type=Path)
    parser.add_argument("--ledger-validation-receipt", type=Path)
    parser.add_argument("--expected-ledger-validation-receipt-sha256")
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    result = validate(
        args.base_dir.resolve(strict=True),
        args.insights_dir.resolve(strict=True),
        args.reports_dir.resolve(strict=True),
        expected_insights_version=args.expected_insights_version,
        expected_reports_version=args.expected_reports_version,
        semantic_governance_path=args.semantic_governance,
        source_semantic_audit_path=args.source_semantic_audit,
        expected_source_semantic_audit_sha256=(
            args.expected_source_semantic_audit_sha256
        ),
        candidate_ledger_manifest_path=args.candidate_ledger_manifest,
        ledger_validation_receipt_path=args.ledger_validation_receipt,
        expected_ledger_validation_receipt_sha256=(
            args.expected_ledger_validation_receipt_sha256
        ),
    )
    writer_status = _write_receipt(args.receipt, result)
    print(
        json.dumps(
            {**result, "receipt_write_status": writer_status},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
