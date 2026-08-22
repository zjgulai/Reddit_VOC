#!/usr/bin/env python3
"""Independently validate a generated static Reddit VOC website snapshot."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Iterable, cast

try:
    from scripts import validate_reddit_v3_voc_facts as v3_independent
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import validate_reddit_v3_voc_facts as v3_independent  # type: ignore[no-redef]


MANIFEST_SCHEMA_V1 = "reddit_voc_site_snapshot_manifest_v1"
MANIFEST_SCHEMA_V2 = "reddit_voc_site_snapshot_manifest_v2"
MANIFEST_SCHEMAS = {MANIFEST_SCHEMA_V1, MANIFEST_SCHEMA_V2}
MANIFEST_SCHEMA_V3 = "reddit_voc_site_state_manifest_v3"
AGGREGATES_SCHEMA = "reddit_voc_site_aggregates_v1"
TAG_DICTIONARY_SCHEMA = "reddit_voc_tag_dictionary_v1"
VALIDATION_SCHEMA = "reddit_voc_site_snapshot_validation_v2"
V3_VALIDATION_SCHEMA = "reddit_voc_site_state_validation_v3"
V3_POLICY_SHA256 = (
    "c6c0faf2aef38da468d9bb42ddc1dc8f1f8f5b70d4d735e7756c64d3320381ab"
)
V3_PERIOD = "all_observed_history"
V3_SCOPE = "canonical_observation_pool"
V3_BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}
V3_INPUT_KEYS = {
    "canonical_dataset_id",
    "canonical_manifest_sha256",
    "canonical_validation_receipt_sha256",
    "metric_eligibility_policy_sha256",
    "metric_eligibility_policy_version",
}
V3_LIFECYCLE_KEYS = {
    "canonical_consumption_status",
    "canonical_independent_validation_status",
    "canonical_manifest_status",
    "promotable",
    "validation_consumption_status",
    "validation_status",
}
V3_STATE_VECTOR_KEYS = {
    "analysis_ready",
    "canonical",
    "exclusions",
    "metric_eligibility",
    "time_precision",
    "voc_facts",
}
V3_CHECK_KEYS = {
    "analysis_ready_subset_of_voc_facts",
    "canonical_identity_conservation",
    "canonical_manifest_and_receipt_exactly_bound",
    "complete_canonical_union_not_legacy_append",
    "floating_day_preserved_without_fabricated_utc",
    "metric_eligible_subset_of_analysis_ready",
    "privacy_sensitive_rows_not_emitted",
    "public_projection_not_prematurely_emitted",
    "side_effect_boundaries_preserved",
    "voc_and_exclusion_identity_partition",
}
V3_CANONICAL_STATE_KEYS = {
    "comments_jsonl",
    "identity_lf_sha256",
    "linked_comments",
    "posts",
    "quarantined_comments",
    "stored_comments",
    "total_identities",
    "unresolved_parent_comments",
}
V3_VOC_STATE_KEYS = {
    "comment_context_vocs",
    "identity_lf_sha256",
    "post_vocs",
    "total_vocs",
}
V3_EXCLUSION_STATE_KEYS = {
    "excluded_comment_identities",
    "excluded_identities",
    "excluded_post_identities",
    "identity_lf_sha256",
    "reason_counts",
}
V3_ELIGIBILITY_STATE_KEYS = {
    "denominator_true_rows",
    "distinct_eligible_comment_context_vocs",
    "distinct_eligible_post_vocs",
    "distinct_eligible_voc_facts",
    "eligible_identity_lf_sha256",
    "eligible_rows",
    "excluded_rows",
    "membership_rows",
    "numerator_true_rows",
    "period",
    "scope",
}
V3_TIME_STATE_KEYS = {
    "day_precision_vocs",
    "instant_or_hour_precision_vocs",
    "missing_event_time_vocs",
}
V3_TOP_LEVEL_KEYS = {
    "all_checks_passed",
    "artifact_stage",
    "boundaries",
    "checks",
    "dataset_version",
    "delivery_mode",
    "files",
    "fusion_accounting",
    "generated_at_utc",
    "inputs",
    "public_projection_complete",
    "release_candidate",
    "schema_version",
    "state_vector",
    "upstream_lifecycle",
}
EXPECTED_FILES = {
    "posts.json",
    "comments.json",
    "aggregates.json",
    "quarantine.json",
    "tag-dictionary.json",
}
EXPECTED_SOURCE_KEYS_V1 = {
    "imported_archive",
    "historical_canonical",
    "tencent_production_primary",
    "tencent_isolated_staging",
    "tencent_v2_search_hydrated",
}
HYDRATION_SOURCE = "tencent_existing_post_comment_hydration"
EXPECTED_SOURCE_KEYS_V2 = {*EXPECTED_SOURCE_KEYS_V1, HYDRATION_SOURCE}
EXPECTED_LOAD_ORDER_V1 = [
    "imported_archive",
    "historical_canonical_lineage_only",
    "tencent_production_primary",
    "tencent_isolated_staging_overlay",
    "tencent_v2_search_hydrated_disjoint_append",
]
EXPECTED_LOAD_ORDER_V2 = [
    *EXPECTED_LOAD_ORDER_V1,
    "tencent_existing_post_comment_hydration_append",
]
PRODUCT_RESOLVER_VERSION = "product-entity-resolver-v1"
PRODUCT_LEDGER_VERSION = "momcozy-product-entity-ledger-2026-07-15.v1"
PRODUCT_LEDGER_SHA256 = (
    "cc66f565d64c19d0624baf9821ff4e765c692c8d85b8a4d7368214ab555451ab"
)
COVERAGE_KEYS = {
    "input_record_count",
    "bound_record_count",
    "unbound_record_count",
    "multi_binding_record_count",
    "binding_count",
    "exact_spu_binding_count",
    "family_only_binding_count",
    "category_only_binding_count",
    "taxonomy_blocked_binding_count",
    "category_binding_counts",
    "family_binding_counts",
    "is_conserved",
}
PRODUCT_RESOLUTION_KEYS = {
    "status",
    "resolver_version",
    "ledger_version",
    "ledger_sha256",
    "coverage",
    "observed_tag_contexts",
}
BINDING_KEYS = {
    "brand_id",
    "category",
    "product_family",
    "exact_spu",
    "binding_level",
    "match_type",
    "matched_alias",
    "governance_status",
    "governance_reason",
}
FORBIDDEN_KEYS = {
    "author",
    "author_hash",
    "author_fullname",
    "body_html",
    "selftext_html",
}
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d() .-]{7,}\d)(?!\w)")
USERNAME_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_])(?:/?u/[A-Za-z0-9_-]{2,30}|@[A-Za-z0-9_-]{2,30})"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DATASET_VERSION_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,127}$")
POST_ID_RE = re.compile(r"^[a-z0-9]{5,10}$")
COMMENT_ID_RE = re.compile(r"^t1_[a-z0-9]+$")


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _identity_hash(values: Iterable[str]) -> str:
    ordered = sorted(set(values))
    return sha256("".join(f"{value}\n" for value in ordered).encode("utf-8")).hexdigest()


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _entity_texts(
    posts: list[dict[str, Any]], comments: list[dict[str, Any]]
) -> Iterable[str]:
    for post in posts:
        yield f"{post.get('title', '')}\n{post.get('content', '')}"
    for comment in comments:
        yield str(comment.get("body") or "")


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _object(value: Any, location: str) -> dict[str, Any]:
    _check(
        isinstance(value, dict) and all(isinstance(key, str) for key in value),
        f"object expected: {location}",
    )
    return cast(dict[str, Any], value)


def _rows(value: Any, location: str) -> list[dict[str, Any]]:
    _check(isinstance(value, list), f"list expected: {location}")
    result: list[dict[str, Any]] = []
    for index, row in enumerate(cast(list[Any], value)):
        result.append(_object(row, f"{location}[{index}]"))
    return result


def _integer(
    value: Any,
    location: str,
    *,
    minimum: int = 0,
) -> int:
    _check(
        isinstance(value, int) and not isinstance(value, bool) and value >= minimum,
        f"non-negative integer expected: {location}",
    )
    return cast(int, value)


def _nonempty_string(value: Any, location: str) -> str:
    _check(isinstance(value, str) and bool(value.strip()), f"string expected: {location}")
    return cast(str, value)


def _sha(value: Any, location: str) -> str:
    text = _nonempty_string(value, location)
    _check(SHA256_RE.fullmatch(text) is not None, f"sha256 expected: {location}")
    return text


def _parse_utc(value: Any, location: str) -> datetime:
    text = _nonempty_string(value, location)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"timestamp invalid: {location}") from exc
    _check(parsed.tzinfo is not None, f"timezone missing: {location}")
    return parsed.astimezone(timezone.utc)


def _validate_manifest_files(
    snapshot_dir: Path, manifest: dict[str, Any]
) -> dict[str, Path]:
    files = _object(manifest.get("files"), "manifest.files")
    _check(set(files) == EXPECTED_FILES, "manifest file set mismatch")
    paths: dict[str, Path] = {}
    for name in sorted(EXPECTED_FILES):
        expected = _object(files[name], f"manifest.files.{name}")
        _check(set(expected) == {"bytes", "sha256"}, f"file record mismatch: {name}")
        path = snapshot_dir / name
        _check(path.is_file() and not path.is_symlink(), f"snapshot file missing: {name}")
        expected_bytes = _integer(expected.get("bytes"), f"manifest.files.{name}.bytes")
        expected_sha = _sha(expected.get("sha256"), f"manifest.files.{name}.sha256")
        _check(path.stat().st_size == expected_bytes, f"byte mismatch: {name}")
        _check(_sha256(path) == expected_sha, f"sha256 mismatch: {name}")
        paths[name] = path
    return paths


def _source_set(
    row: dict[str, Any], location: str, expected_source_keys: set[str]
) -> set[str]:
    occurrences = _rows(row.get("source_occurrences"), f"{location}.source_occurrences")
    _check(bool(occurrences), f"source occurrence missing: {location}")
    sources = [
        _nonempty_string(item.get("source_kind"), f"{location}.source_kind")
        for item in occurrences
    ]
    _check(len(sources) == len(set(sources)), f"duplicate source occurrence: {location}")
    _check(
        set(sources) <= expected_source_keys,
        f"unknown source occurrence: {location}",
    )
    return set(sources)


def _validate_identity_and_sources(
    posts: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    quarantine: list[dict[str, Any]],
    *,
    expected_source_keys: set[str],
) -> tuple[set[str], Counter[str], Counter[str]]:
    post_ids: list[str] = []
    post_sources: Counter[str] = Counter()
    for index, post in enumerate(posts):
        post_id = _nonempty_string(post.get("post_id"), f"posts[{index}].post_id")
        _check(POST_ID_RE.fullmatch(post_id) is not None, "invalid post id")
        post_ids.append(post_id)
        sources = _source_set(post, f"posts[{index}]", expected_source_keys)
        declared_sources = post.get("source_kinds")
        _check(isinstance(declared_sources, list), "post source_kinds missing")
        _check(
            set(cast(list[Any], declared_sources)) == sources,
            "post source kind partition mismatch",
        )
        post_sources.update(sources)
    _check(len(post_ids) == len(set(post_ids)), "duplicate post ids")
    post_id_set = set(post_ids)

    comment_ids: list[str] = []
    comment_sources: Counter[str] = Counter()
    for index, comment in enumerate(comments):
        comment_id = _nonempty_string(
            comment.get("comment_id"), f"comments[{index}].comment_id"
        )
        _check(COMMENT_ID_RE.fullmatch(comment_id) is not None, "invalid comment id")
        comment_ids.append(comment_id)
        post_id = _nonempty_string(
            comment.get("post_id"), f"comments[{index}].post_id"
        )
        _check(post_id in post_id_set, "linked comment missing parent post")
        comment_sources.update(
            _source_set(comment, f"comments[{index}]", expected_source_keys)
        )
    _check(len(comment_ids) == len(set(comment_ids)), "duplicate linked comment ids")

    quarantine_ids: list[str] = []
    for index, row in enumerate(quarantine):
        comment_id = _nonempty_string(
            row.get("comment_id"), f"quarantine[{index}].comment_id"
        )
        _check(COMMENT_ID_RE.fullmatch(comment_id) is not None, "invalid quarantine id")
        quarantine_ids.append(comment_id)
        missing_post_id = _nonempty_string(
            row.get("missing_post_id"), f"quarantine[{index}].missing_post_id"
        )
        _check(
            missing_post_id not in post_id_set,
            "quarantined parent unexpectedly exists",
        )
        sources_raw = row.get("source_kinds")
        _check(isinstance(sources_raw, list) and bool(sources_raw), "quarantine sources missing")
        sources = [
            _nonempty_string(value, f"quarantine[{index}].source_kinds")
            for value in cast(list[Any], sources_raw)
        ]
        _check(len(sources) == len(set(sources)), "duplicate quarantine source")
        _check(set(sources) <= expected_source_keys, "unknown quarantine source")
        comment_sources.update(sources)
    _check(len(quarantine_ids) == len(set(quarantine_ids)), "duplicate quarantine ids")
    _check(
        not (set(comment_ids) & set(quarantine_ids)),
        "linked/quarantine overlap",
    )
    return post_id_set, post_sources, comment_sources


def _validate_counts(
    manifest: dict[str, Any],
    posts: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    quarantine: list[dict[str, Any]],
) -> dict[str, int]:
    raw_counts = _object(manifest.get("canonical_counts"), "canonical_counts")
    _check(
        set(raw_counts)
        == {"posts", "stored_comments", "linked_comments", "quarantined_comments"},
        "canonical count field set mismatch",
    )
    counts = {
        key: _integer(value, f"canonical_counts.{key}")
        for key, value in raw_counts.items()
    }
    _check(len(posts) == counts["posts"], "post count mismatch")
    _check(len(comments) == counts["linked_comments"], "comment count mismatch")
    _check(len(quarantine) == counts["quarantined_comments"], "quarantine mismatch")
    _check(
        counts["stored_comments"]
        == counts["linked_comments"] + counts["quarantined_comments"],
        "linked/quarantine stored comment conservation mismatch",
    )
    return counts


def _boundary_count(
    boundary: dict[str, Any], source: str, entity: str
) -> int:
    field_by_source = {
        "imported_archive": {
            "posts": "unique_posts",
            "comments": "unique_comments",
        },
        "historical_canonical": {
            "posts": "input_posts",
            "comments": "input_comments",
        },
        "tencent_production_primary": {
            "posts": "input_posts",
            "comments": "input_comments",
        },
        "tencent_isolated_staging": {
            "posts": "input_posts",
            "comments": "input_comments",
        },
        "tencent_v2_search_hydrated": {
            "posts": "admitted_posts",
            "comments": "admitted_observed_comments",
        },
        HYDRATION_SOURCE: {
            "posts": "input_posts",
            "comments": "materialized_comments",
        },
    }
    field = field_by_source[source][entity]
    return _integer(boundary.get(field), f"source_boundaries.{source}.{field}")


def _validate_v2_contract(
    v2: dict[str, Any],
    fusion: dict[str, Any],
    posts: list[dict[str, Any]],
    *,
    product_resolution_status: str,
) -> str:
    _nonempty_string(v2.get("identity_set_id"), "v2.identity_set_id")
    target_count = _integer(v2.get("target_count"), "v2.target_count", minimum=1)
    lineage_gap_count = _integer(
        v2.get("lineage_gap_count"), "v2.lineage_gap_count"
    )
    _check(lineage_gap_count <= target_count, "V2 lineage gap exceeds target")
    _sha(v2.get("lineage_gap_lf_sha256"), "v2.lineage_gap_lf_sha256")
    _sha(v2.get("identity_freeze_sha256"), "v2.identity_freeze_sha256")
    _sha(v2.get("snapshot_sha256"), "v2.snapshot_sha256")
    target_hash = v2.get("target_lf_sha256")
    if target_hash is None:
        _check(
            product_resolution_status == "pending_product_entity_resolver",
            "resolved release missing V2 target hash",
        )
        target_hash_binding = "upstream_identity_gate_legacy_manifest"
    else:
        target_hash = _sha(target_hash, "v2.target_lf_sha256")
        target_hash_binding = "manifest_exact"

    admitted_posts = _integer(v2.get("admitted_posts"), "v2.admitted_posts")
    admitted_comments = _integer(
        v2.get("admitted_observed_comments"), "v2.admitted_observed_comments"
    )
    _check(
        admitted_posts == target_count - lineage_gap_count,
        "V2 admitted post/gap conservation mismatch",
    )
    _check(v2.get("overlap_posts") == 0, "V2 post overlap is not zero")
    _check(v2.get("overlap_comments") == 0, "V2 comment overlap is not zero")
    _check(v2.get("net_new_posts") == admitted_posts, "V2 net-new post mismatch")
    _check(v2.get("net_new_comments") == admitted_comments, "V2 net-new comment mismatch")
    for key in ("provider_call", "database_write", "production_merge", "live_send"):
        _check(v2.get(key) is False, f"V2 side effect enabled: {key}")

    grades_raw = _object(v2.get("coverage_grade_counts"), "v2.coverage_grade_counts")
    _check(set(grades_raw) == {"full", "partial"}, "V2 coverage grade set mismatch")
    grades = {
        key: _integer(value, f"v2.coverage_grade_counts.{key}")
        for key, value in grades_raw.items()
    }
    _check(sum(grades.values()) == admitted_posts, "V2 coverage grade conservation mismatch")
    observed_grades: Counter[str] = Counter()
    admitted_post_ids: list[str] = []
    for post in posts:
        sources = set(cast(list[Any], post.get("source_kinds", [])))
        if "tencent_v2_search_hydrated" not in sources:
            continue
        _check(
            sources == {"tencent_v2_search_hydrated"},
            "V2 post is not disjoint from prior sources",
        )
        grade = _nonempty_string(post.get("structural_coverage_grade"), "V2 post grade")
        _check(grade in {"full", "partial"}, "V2 post coverage grade invalid")
        observed_grades[grade] += 1
        admitted_post_ids.append(
            _nonempty_string(post.get("post_id"), "V2 post identity")
        )
    _check(
        {key: observed_grades[key] for key in ("full", "partial")} == grades,
        "V2 post coverage grade mismatch",
    )

    lineage_gap_ids_raw = v2.get("lineage_gap_post_ids")
    if lineage_gap_ids_raw is not None:
        _check(
            isinstance(lineage_gap_ids_raw, list),
            "V2 lineage gap identity list invalid",
        )
        lineage_gap_ids = [
            _nonempty_string(value, "v2.lineage_gap_post_ids")
            for value in cast(list[Any], lineage_gap_ids_raw)
        ]
        _check(
            all(POST_ID_RE.fullmatch(value) is not None for value in lineage_gap_ids),
            "V2 lineage gap post id invalid",
        )
        _check(
            len(lineage_gap_ids) == len(set(lineage_gap_ids)),
            "V2 lineage gap post ids duplicate",
        )
        _check(
            len(lineage_gap_ids) == lineage_gap_count,
            "V2 lineage gap identity count mismatch",
        )
        _check(
            _identity_hash(lineage_gap_ids) == v2.get("lineage_gap_lf_sha256"),
            "V2 lineage gap identity hash mismatch",
        )
        _check(
            not (set(admitted_post_ids) & set(lineage_gap_ids)),
            "V2 admitted/lineage gap overlap",
        )
        target_ids = [*admitted_post_ids, *lineage_gap_ids]
        _check(len(target_ids) == target_count, "V2 target identity count mismatch")
        _check(target_hash is not None, "V2 target identity hash missing")
        _check(
            _identity_hash(target_ids) == target_hash,
            "V2 target identity hash mismatch",
        )

    debt_raw = _object(v2.get("comment_coverage_debt"), "v2.comment_coverage_debt")
    _check(
        set(debt_raw) == {"cursor_outstanding", "page_pagination_outstanding", "partial_threads"},
        "V2 coverage debt field set mismatch",
    )
    debt = {
        key: _integer(value, f"v2.comment_coverage_debt.{key}")
        for key, value in debt_raw.items()
    }
    has_debt = bool(
        lineage_gap_count
        or debt["cursor_outstanding"]
        or debt["page_pagination_outstanding"]
        or debt["partial_threads"]
    )
    expected_admission_status = (
        "passed_with_partial_comment_coverage" if has_debt else "passed_complete"
    )
    _check(
        v2.get("admission_status") == expected_admission_status,
        "V2 admission status mismatch",
    )
    if lineage_gap_count or grades["partial"]:
        _check(
            any(value > 0 for value in debt.values()),
            "V2 comment coverage debt was zero-filled",
        )
    _check(
        debt["cursor_outstanding"] == v2.get("cursor_outstanding")
        and debt["page_pagination_outstanding"]
        == v2.get("page_pagination_outstanding")
        and debt["partial_threads"] == grades["partial"],
        "V2 comment coverage debt mismatch",
    )
    _check(
        fusion.get("v2_comment_coverage_debt") == debt,
        "fusion/V2 coverage debt mismatch",
    )
    _check(
        fusion.get("coverage_debt_is_not_zero_filled") is True,
        "coverage debt zero-fill boundary missing",
    )
    return target_hash_binding


def _validate_hydration_occurrence_disjoint(
    posts: list[dict[str, Any]], comments: list[dict[str, Any]]
) -> None:
    v2_post_ids = {
        _nonempty_string(post.get("post_id"), "V2 post identity")
        for post in posts
        if "tencent_v2_search_hydrated"
        in set(cast(list[Any], post.get("source_kinds", [])))
    }
    for post in posts:
        sources = set(cast(list[Any], post.get("source_kinds", [])))
        _check(HYDRATION_SOURCE not in sources, "hydration post occurrence found")
    for comment in comments:
        sources = {
            occurrence.get("source_kind")
            for occurrence in cast(
                list[dict[str, Any]], comment.get("source_occurrences", [])
            )
        }
        if HYDRATION_SOURCE not in sources:
            continue
        _check(
            sources == {HYDRATION_SOURCE},
            "hydration comment is not disjoint from prior sources",
        )
        _check(
            comment.get("post_id") not in v2_post_ids,
            "hydration comment parent is a V2 discovery post",
        )


def _validate_existing_hydration_contract(
    hydration: dict[str, Any],
    posts: list[dict[str, Any]],
    comments: list[dict[str, Any]],
) -> dict[str, Any]:
    _nonempty_string(hydration.get("dataset_id"), "hydration.dataset_id")
    _sha(hydration.get("snapshot_sha256"), "hydration.snapshot_sha256")
    _check(
        hydration.get("fusion_role") == "existing_post_comment_delta_after_v2",
        "hydration fusion role mismatch",
    )
    _check(
        hydration.get("precedence_policy") == "preceding_canonical_wins",
        "hydration precedence policy mismatch",
    )
    _check(
        hydration.get("dedup_key")
        == {"posts": "post_id", "comments": "comment_id"},
        "hydration dedup key mismatch",
    )
    for key in ("provider_call", "database_write", "production_merge", "live_send"):
        _check(hydration.get(key) is False, f"hydration side effect enabled: {key}")

    post_ids = {
        _nonempty_string(post.get("post_id"), "hydration canonical post id")
        for post in posts
    }
    v2_post_ids = {
        _nonempty_string(post.get("post_id"), "hydration V2 post id")
        for post in posts
        if "tencent_v2_search_hydrated"
        in set(cast(list[Any], post.get("source_kinds", [])))
    }
    baseline_post_count = _integer(
        hydration.get("baseline_post_count"), "hydration.baseline_post_count"
    )
    baseline_post_hash = _sha(
        hydration.get("baseline_post_ids_lf_sha256"),
        "hydration.baseline_post_ids_lf_sha256",
    )
    _check(
        baseline_post_count <= len(post_ids),
        "hydration baseline post count exceeds canonical",
    )
    if baseline_post_count == len(post_ids):
        _check(
            baseline_post_hash == _identity_hash(post_ids),
            "hydration baseline post identity mismatch",
        )
    _integer(
        hydration.get("baseline_comment_count"),
        "hydration.baseline_comment_count",
    )
    _sha(
        hydration.get("baseline_comment_ids_lf_sha256"),
        "hydration.baseline_comment_ids_lf_sha256",
    )

    input_posts = _integer(hydration.get("input_posts"), "hydration.input_posts")
    overlap_posts = _integer(
        hydration.get("overlap_posts"), "hydration.overlap_posts"
    )
    net_new_posts = _integer(
        hydration.get("net_new_posts"), "hydration.net_new_posts"
    )
    _check(
        input_posts == overlap_posts + net_new_posts == 0,
        "hydration post accounting mismatch",
    )
    input_comments = _integer(
        hydration.get("input_comments"), "hydration.input_comments"
    )
    materialized_comments = _integer(
        hydration.get("materialized_comments"),
        "hydration.materialized_comments",
    )
    release_candidate_comments = _integer(
        hydration.get("release_candidate_comments"),
        "hydration.release_candidate_comments",
    )
    preceding_overlap = _integer(
        hydration.get("preceding_overlap_comments"),
        "hydration.preceding_overlap_comments",
    )
    overlap_comments = _integer(
        hydration.get("overlap_comments"), "hydration.overlap_comments"
    )
    net_new_comments = _integer(
        hydration.get("net_new_comments"), "hydration.net_new_comments"
    )
    body_conflicts = _integer(
        hydration.get("preceding_body_conflicts"),
        "hydration.preceding_body_conflicts",
    )
    _check(
        input_comments == release_candidate_comments
        == materialized_comments + preceding_overlap,
        "hydration input/materialization conservation mismatch",
    )
    _check(
        overlap_comments == preceding_overlap
        and net_new_comments == materialized_comments,
        "hydration overlap/net-new conservation mismatch",
    )
    _check(
        body_conflicts <= preceding_overlap,
        "hydration body conflicts exceed preceding overlap",
    )
    actual_hydration_comments = [
        comment
        for comment in comments
        if HYDRATION_SOURCE
        in {
            occurrence.get("source_kind")
            for occurrence in cast(
                list[dict[str, Any]], comment.get("source_occurrences", [])
            )
        }
    ]
    _check(
        len(actual_hydration_comments) == materialized_comments,
        "hydration canonical comment materialization mismatch",
    )

    grades_raw = _object(
        hydration.get("coverage_grade_counts"),
        "hydration.coverage_grade_counts",
    )
    _check(
        set(grades_raw) == {"full", "partial", "not_observed"},
        "hydration coverage grade set mismatch",
    )
    grades = {
        key: _integer(value, f"hydration.coverage_grade_counts.{key}")
        for key, value in grades_raw.items()
    }
    _check(
        sum(grades.values()) <= baseline_post_count,
        "hydration coverage exceeds baseline posts",
    )

    debt_raw = _object(
        hydration.get("comment_coverage_debt"),
        "hydration.comment_coverage_debt",
    )
    expected_debt_keys = {
        "first_page_missing",
        "cursor_outstanding",
        "page_pagination_outstanding",
        "failed_reports",
        "partial_threads",
        "not_observed_threads",
        "failure_reason_counts",
    }
    _check(set(debt_raw) == expected_debt_keys, "hydration coverage debt set mismatch")
    failure_reason_counts_raw = _object(
        debt_raw.get("failure_reason_counts"),
        "hydration.comment_coverage_debt.failure_reason_counts",
    )
    allowed_failure_reasons = {
        "legacy_reply_source_chain_incomplete",
        "legacy_reply_source_predecessor_missing",
        "report_response_validation_failed",
    }
    _check(
        set(failure_reason_counts_raw) <= allowed_failure_reasons,
        "hydration failure reason invalid",
    )
    failure_reason_counts = {
        key: _integer(value, f"hydration.failure_reason_counts.{key}")
        for key, value in failure_reason_counts_raw.items()
    }
    debt: dict[str, Any] = {
        key: _integer(debt_raw.get(key), f"hydration.comment_coverage_debt.{key}")
        for key in expected_debt_keys - {"failure_reason_counts"}
    }
    debt["failure_reason_counts"] = failure_reason_counts

    work = _object(
        hydration.get("coverage_work_items"), "hydration.coverage_work_items"
    )
    expected_work_keys = {
        "first_page_missing_post_ids",
        "cursor_outstanding",
        "page_pagination_outstanding_post_ids",
        "failed_reports",
        "partial_post_ids",
        "not_observed_post_ids",
    }
    _check(set(work) == expected_work_keys, "hydration coverage work set mismatch")

    def post_id_set(name: str) -> set[str]:
        raw = work.get(name)
        _check(isinstance(raw, list), f"hydration coverage work list invalid: {name}")
        values = [
            _nonempty_string(value, f"hydration.coverage_work_items.{name}")
            for value in cast(list[Any], raw)
        ]
        _check(
            len(values) == len(set(values)),
            "hydration coverage work item duplicate",
        )
        _check(
            all(
                POST_ID_RE.fullmatch(value) is not None
                and value in post_ids
                and value not in v2_post_ids
                for value in values
            ),
            "hydration coverage work post invalid",
        )
        return set(values)

    first_missing = post_id_set("first_page_missing_post_ids")
    page_outstanding = post_id_set("page_pagination_outstanding_post_ids")
    partial_post_ids = post_id_set("partial_post_ids")
    not_observed_post_ids = post_id_set("not_observed_post_ids")

    cursor_rows = _rows(
        work.get("cursor_outstanding"),
        "hydration.coverage_work_items.cursor_outstanding",
    )
    cursor_keys: set[str] = set()
    cursor_post_ids: set[str] = set()
    for index, row in enumerate(cursor_rows):
        _check(
            set(row) == {"post_id", "cursor_sha256"},
            "hydration cursor work field mismatch",
        )
        post_id = _nonempty_string(row.get("post_id"), f"hydration.cursor[{index}]")
        _check(
            POST_ID_RE.fullmatch(post_id) is not None
            and post_id in post_ids
            and post_id not in v2_post_ids,
            "hydration cursor work post invalid",
        )
        cursor_hash = _sha(
            row.get("cursor_sha256"), f"hydration.cursor[{index}].cursor_sha256"
        )
        cursor_keys.add(f"{post_id}\t{cursor_hash}")
        cursor_post_ids.add(post_id)
    _check(
        len(cursor_keys) == len(cursor_rows),
        "hydration coverage work item duplicate",
    )

    failed_rows = _rows(
        work.get("failed_reports"),
        "hydration.coverage_work_items.failed_reports",
    )
    failed_keys: set[str] = set()
    observed_failure_reasons: Counter[str] = Counter()
    for index, row in enumerate(failed_rows):
        _check(
            frozenset(row)
            in {
                frozenset({"post_id", "reason", "report_kind", "report_sha256"}),
                frozenset(
                    {
                        "post_id",
                        "reason",
                        "report_kind",
                        "report_sha256",
                        "cursor_sha256",
                    }
                ),
            },
            "hydration failed report field mismatch",
        )
        post_id = _nonempty_string(
            row.get("post_id"), f"hydration.failed_reports[{index}].post_id"
        )
        _check(
            POST_ID_RE.fullmatch(post_id) is not None
            and post_id in post_ids
            and post_id not in v2_post_ids,
            "hydration failed report post invalid",
        )
        reason = _nonempty_string(
            row.get("reason"), f"hydration.failed_reports[{index}].reason"
        )
        _check(reason in allowed_failure_reasons, "hydration failure reason invalid")
        _nonempty_string(
            row.get("report_kind"),
            f"hydration.failed_reports[{index}].report_kind",
        )
        _sha(
            row.get("report_sha256"),
            f"hydration.failed_reports[{index}].report_sha256",
        )
        if "cursor_sha256" in row:
            _sha(
                row.get("cursor_sha256"),
                f"hydration.failed_reports[{index}].cursor_sha256",
            )
        observed_failure_reasons[reason] += 1
        failed_keys.add(
            sha256(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        )
    _check(
        len(failed_keys) == len(failed_rows),
        "hydration coverage work item duplicate",
    )
    _check(
        dict(sorted(observed_failure_reasons.items())) == failure_reason_counts,
        "hydration failure reason count mismatch",
    )
    _check(
        first_missing == not_observed_post_ids,
        "hydration first-page/not-observed set mismatch",
    )
    _check(
        not (partial_post_ids & not_observed_post_ids)
        and page_outstanding <= partial_post_ids
        and cursor_post_ids <= partial_post_ids,
        "hydration coverage work partition mismatch",
    )
    _check(
        debt["first_page_missing"] == len(first_missing)
        and debt["cursor_outstanding"] == len(cursor_keys)
        and debt["page_pagination_outstanding"] == len(page_outstanding)
        and debt["failed_reports"] == len(failed_keys)
        and debt["partial_threads"] == len(partial_post_ids) == grades["partial"]
        and debt["not_observed_threads"]
        == len(not_observed_post_ids)
        == grades["not_observed"],
        "hydration coverage debt/work mismatch",
    )
    _check(
        sum(failure_reason_counts.values()) == debt["failed_reports"],
        "hydration failed report conservation mismatch",
    )
    has_debt = any(
        debt[key] > 0
        for key in (
            "first_page_missing",
            "cursor_outstanding",
            "page_pagination_outstanding",
            "failed_reports",
            "partial_threads",
            "not_observed_threads",
        )
    )
    expected_status = (
        "passed_with_explicit_comment_coverage_debt"
        if has_debt
        else "passed_complete"
    )
    _check(
        hydration.get("admission_status") == expected_status,
        "hydration admission status mismatch",
    )
    return {
        "debt": debt,
        "first_missing": first_missing,
        "cursor_keys": cursor_keys,
        "page_outstanding": page_outstanding,
        "failed_keys": failed_keys,
        "partial_post_ids": partial_post_ids,
        "not_observed_post_ids": not_observed_post_ids,
        "v2_post_ids": v2_post_ids,
    }


def _validate_comment_coverage_debt_union(
    v2: dict[str, Any],
    hydration_state: dict[str, Any],
    fusion: dict[str, Any],
    posts: list[dict[str, Any]],
) -> None:
    union = _object(
        fusion.get("comment_coverage_debt_union"),
        "fusion.comment_coverage_debt_union",
    )
    expected_fields = {
        "first_page_missing",
        "first_page_missing_lf_sha256",
        "cursor_outstanding",
        "cursor_outstanding_lf_sha256",
        "page_pagination_outstanding",
        "page_pagination_outstanding_lf_sha256",
        "failed_reports",
        "failed_reports_lf_sha256",
        "partial_threads",
        "partial_thread_ids_lf_sha256",
        "not_observed_threads",
        "not_observed_thread_ids_lf_sha256",
        "source_counts",
        "key_union_not_numeric_sum",
    }
    _check(set(union) == expected_fields, "coverage debt union field set mismatch")
    _check(
        union.get("key_union_not_numeric_sum") is True,
        "coverage debt union key semantics missing",
    )
    source_counts = _object(
        union.get("source_counts"), "coverage debt union source_counts"
    )
    _check(
        set(source_counts) == {"v2", "existing_post_hydration"},
        "coverage debt union source set mismatch",
    )
    v2_source = _object(source_counts.get("v2"), "coverage debt union V2 source")
    _check(
        set(v2_source)
        == {
            "first_page_missing",
            "cursor_outstanding",
            "page_pagination_outstanding",
            "failed_reports",
        },
        "coverage debt union V2 source field mismatch",
    )
    v2_source_counts = {
        key: _integer(value, f"coverage debt union V2 source.{key}")
        for key, value in v2_source.items()
    }
    lineage_gap_ids_raw = v2.get("lineage_gap_post_ids")
    _check(
        isinstance(lineage_gap_ids_raw, list),
        "manifest v2 requires V2 lineage gap identities",
    )
    lineage_gap_ids = {
        _nonempty_string(value, "v2.lineage_gap_post_ids")
        for value in cast(list[Any], lineage_gap_ids_raw)
    }
    _check(
        len(lineage_gap_ids) == len(cast(list[Any], lineage_gap_ids_raw)),
        "V2 lineage gap post ids duplicate",
    )
    v2_debt = _object(v2.get("comment_coverage_debt"), "v2.comment_coverage_debt")
    _check(
        v2_source_counts
        == {
            "first_page_missing": len(lineage_gap_ids),
            "cursor_outstanding": _integer(
                v2_debt.get("cursor_outstanding"),
                "v2.comment_coverage_debt.cursor_outstanding",
            ),
            "page_pagination_outstanding": _integer(
                v2_debt.get("page_pagination_outstanding"),
                "v2.comment_coverage_debt.page_pagination_outstanding",
            ),
            "failed_reports": 0,
        },
        "coverage debt union V2 source mismatch",
    )
    _check(
        source_counts.get("existing_post_hydration") == hydration_state["debt"],
        "coverage debt union hydration source mismatch",
    )
    _check(
        fusion.get("existing_post_hydration_coverage_debt")
        == hydration_state["debt"],
        "fusion/hydration coverage debt mismatch",
    )

    v2_partial_post_ids = {
        _nonempty_string(post.get("post_id"), "V2 partial post id")
        for post in posts
        if "tencent_v2_search_hydrated"
        in set(cast(list[Any], post.get("source_kinds", [])))
        and post.get("structural_coverage_grade") == "partial"
    }
    _check(
        not (v2_partial_post_ids & hydration_state["partial_post_ids"]),
        "coverage debt union source partitions overlap",
    )
    first_missing = lineage_gap_ids | hydration_state["first_missing"]
    partial_post_ids = v2_partial_post_ids | hydration_state["partial_post_ids"]
    not_observed_post_ids = set(first_missing)
    failed_keys = set(hydration_state["failed_keys"])
    expected_counts = {
        "first_page_missing": len(first_missing),
        "cursor_outstanding": v2_source_counts["cursor_outstanding"]
        + len(hydration_state["cursor_keys"]),
        "page_pagination_outstanding": v2_source_counts[
            "page_pagination_outstanding"
        ]
        + len(hydration_state["page_outstanding"]),
        "failed_reports": len(failed_keys),
        "partial_threads": len(partial_post_ids),
        "not_observed_threads": len(not_observed_post_ids),
    }
    messages = {
        "first_page_missing": "coverage debt union first-page mismatch",
        "cursor_outstanding": "coverage debt union cursor mismatch",
        "page_pagination_outstanding": "coverage debt union page mismatch",
        "failed_reports": "coverage debt union failed-report mismatch",
        "partial_threads": "coverage debt union partial-thread mismatch",
        "not_observed_threads": "coverage debt union not-observed mismatch",
    }
    for key, expected in expected_counts.items():
        _check(_integer(union.get(key), f"coverage debt union.{key}") == expected, messages[key])

    exact_hashes = {
        "first_page_missing_lf_sha256": _identity_hash(first_missing),
        "failed_reports_lf_sha256": _identity_hash(failed_keys),
        "partial_thread_ids_lf_sha256": _identity_hash(partial_post_ids),
        "not_observed_thread_ids_lf_sha256": _identity_hash(
            not_observed_post_ids
        ),
    }
    hash_messages = {
        "first_page_missing_lf_sha256": "coverage debt union first-page mismatch",
        "failed_reports_lf_sha256": "coverage debt union failed-report mismatch",
        "partial_thread_ids_lf_sha256": "coverage debt union partial-thread mismatch",
        "not_observed_thread_ids_lf_sha256": "coverage debt union not-observed mismatch",
    }
    for key, expected in exact_hashes.items():
        _check(_sha(union.get(key), f"coverage debt union.{key}") == expected, hash_messages[key])

    cursor_hash = _sha(
        union.get("cursor_outstanding_lf_sha256"),
        "coverage debt union.cursor_outstanding_lf_sha256",
    )
    page_hash = _sha(
        union.get("page_pagination_outstanding_lf_sha256"),
        "coverage debt union.page_pagination_outstanding_lf_sha256",
    )
    if v2_source_counts["cursor_outstanding"] == 0:
        _check(
            cursor_hash == _identity_hash(hydration_state["cursor_keys"]),
            "coverage debt union cursor mismatch",
        )
    if v2_source_counts["page_pagination_outstanding"] == 0:
        _check(
            page_hash == _identity_hash(hydration_state["page_outstanding"]),
            "coverage debt union page mismatch",
        )


def _validate_fusion(
    manifest: dict[str, Any],
    counts: dict[str, int],
    posts: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    post_sources: Counter[str],
    comment_sources: Counter[str],
    *,
    manifest_schema: str,
    product_resolution_status: str,
) -> str:
    boundaries = _object(manifest.get("source_boundaries"), "source_boundaries")
    expected_source_keys = (
        EXPECTED_SOURCE_KEYS_V2
        if manifest_schema == MANIFEST_SCHEMA_V2
        else EXPECTED_SOURCE_KEYS_V1
    )
    expected_load_order = (
        EXPECTED_LOAD_ORDER_V2
        if manifest_schema == MANIFEST_SCHEMA_V2
        else EXPECTED_LOAD_ORDER_V1
    )
    _check(set(boundaries) == expected_source_keys, "source boundary set mismatch")
    typed_boundaries = {
        source: _object(value, f"source_boundaries.{source}")
        for source, value in boundaries.items()
    }
    if manifest_schema == MANIFEST_SCHEMA_V2:
        _validate_hydration_occurrence_disjoint(posts, comments)
    for source, boundary in typed_boundaries.items():
        _check(
            post_sources[source] == _boundary_count(boundary, source, "posts"),
            f"source post occurrence mismatch: {source}",
        )
        _check(
            comment_sources[source] == _boundary_count(boundary, source, "comments"),
            f"source comment occurrence mismatch: {source}",
        )

    for source in (
        "historical_canonical",
        "tencent_production_primary",
        "tencent_isolated_staging",
    ):
        boundary = typed_boundaries[source]
        for entity in ("posts", "comments"):
            _check(
                _integer(boundary.get(f"input_{entity}"), f"{source}.input_{entity}")
                == _integer(boundary.get(f"overlap_{entity}"), f"{source}.overlap_{entity}")
                + _integer(boundary.get(f"net_new_{entity}"), f"{source}.net_new_{entity}"),
                f"source overlap/net-new conservation mismatch: {source}.{entity}",
            )
    archive = typed_boundaries["imported_archive"]
    _check(
        archive.get("unique_posts") == archive.get("net_new_posts")
        and archive.get("unique_comments") == archive.get("net_new_comments"),
        "archive source net-new mismatch",
    )

    fusion = _object(manifest.get("fusion_accounting"), "fusion_accounting")
    _check(fusion.get("load_order") == expected_load_order, "fusion load order mismatch")
    _check(fusion.get("post_identity_key") == "post_id", "post identity key mismatch")
    _check(fusion.get("comment_identity_key") == "comment_id", "comment identity key mismatch")
    net_new_posts = sum(
        _integer(boundary.get("net_new_posts"), f"{source}.net_new_posts")
        for source, boundary in typed_boundaries.items()
    )
    net_new_comments = sum(
        _integer(boundary.get("net_new_comments"), f"{source}.net_new_comments")
        for source, boundary in typed_boundaries.items()
    )
    _check(net_new_posts == counts["posts"], "source net-new post conservation mismatch")
    _check(
        net_new_comments == counts["stored_comments"],
        "source net-new comment conservation mismatch",
    )
    expected = _object(
        fusion.get("expected_from_source_net_new"),
        "fusion.expected_from_source_net_new",
    )
    _check(
        expected == {"posts": net_new_posts, "stored_comments": net_new_comments},
        "fusion expected source accounting mismatch",
    )
    actual = _object(fusion.get("actual_canonical"), "fusion.actual_canonical")
    _check(actual == counts, "fusion actual canonical mismatch")

    target_hash_binding = _validate_v2_contract(
        typed_boundaries["tencent_v2_search_hydrated"],
        fusion,
        posts,
        product_resolution_status=product_resolution_status,
    )
    if manifest_schema == MANIFEST_SCHEMA_V2:
        hydration_state = _validate_existing_hydration_contract(
            typed_boundaries[HYDRATION_SOURCE], posts, comments
        )
        _validate_comment_coverage_debt_union(
            typed_boundaries["tencent_v2_search_hydrated"],
            hydration_state,
            fusion,
            posts,
        )
    return target_hash_binding


def _validate_analysis_and_tags(
    manifest: dict[str, Any],
    posts: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    tag_dictionary: dict[str, Any],
) -> None:
    all_entities = [*posts, *comments]
    analysis_manifest = _object(manifest.get("analysis"), "analysis")
    analysis_version = _nonempty_string(analysis_manifest.get("version"), "analysis.version")
    analysis_code_sha = _sha(analysis_manifest.get("code_sha256"), "analysis.code_sha256")
    _sha(analysis_manifest.get("keyword_rules_sha256"), "analysis.keyword_rules_sha256")
    _check(analysis_manifest.get("provider_call") is False, "analysis provider call found")
    _check(
        analysis_manifest.get("recomputed_for_all_public_entities") is True,
        "analysis recomputation boundary missing",
    )
    for index, row in enumerate(all_entities):
        analysis = _object(row.get("analysis"), f"entities[{index}].analysis")
        _check(analysis.get("provider_call") is False, "provider call found")
        _check(
            analysis.get("analysis_version") == analysis_version,
            "analysis version mismatch",
        )
        _check(
            analysis.get("analysis_code_sha256") == analysis_code_sha,
            "analysis code hash mismatch",
        )

    _check(
        tag_dictionary.get("schema_version") == TAG_DICTIONARY_SCHEMA,
        "tag dictionary schema mismatch",
    )
    dictionary_version = _nonempty_string(
        tag_dictionary.get("dictionary_version"), "tag_dictionary.dictionary_version"
    )
    dictionary_sha = _sha(
        tag_dictionary.get("dictionary_sha256"), "tag_dictionary.dictionary_sha256"
    )
    profile = _object(tag_dictionary.get("profile"), "tag_dictionary.profile")
    rules = _rows(tag_dictionary.get("rules"), "tag_dictionary.rules")
    tag_ids = [
        _nonempty_string(rule.get("tag_id"), f"tag_dictionary.rules[{index}].tag_id")
        for index, rule in enumerate(rules)
    ]
    _check(len(tag_ids) == len(set(tag_ids)), "duplicate governed tag id")
    tagging_manifest = _object(manifest.get("tagging"), "tagging")
    _check(
        tagging_manifest.get("dictionary_version")
        == profile.get("dictionary_version")
        == dictionary_version,
        "tag dictionary version mismatch",
    )
    _check(
        tagging_manifest.get("dictionary_sha256") == dictionary_sha,
        "tag dictionary hash mismatch",
    )
    _check(
        tagging_manifest.get("dictionary_row_count") == profile.get("row_count"),
        "tag dictionary row count mismatch",
    )
    _check(tagging_manifest.get("labels_provisional") is True, "tag status not provisional")
    _check(
        tagging_manifest.get("semantic_validation_run") is False,
        "unexpected semantic validation claim",
    )
    _check(tagging_manifest.get("provider_call") is False, "tagging provider call found")
    governed_tag_ids = set(tag_ids)
    for index, row in enumerate(all_entities):
        tagging = _object(row.get("tagging"), f"entities[{index}].tagging")
        _check(
            tagging.get("dictionary_version") == dictionary_version,
            "entity tag dictionary version mismatch",
        )
        _check(
            tagging.get("semantic_validation_status") == "not_run",
            "tag validation mismatch",
        )
        row_tag_ids = set(cast(list[Any], tagging.get("tag_ids", [])))
        aspect_tag_ids = set(cast(list[Any], tagging.get("aspect_tag_ids", [])))
        brand_tag_ids = set(cast(list[Any], tagging.get("brand_tag_ids", [])))
        _check(row_tag_ids <= governed_tag_ids, "ungoverned tag id")
        _check(
            row_tag_ids == aspect_tag_ids | brand_tag_ids,
            "tag partition mismatch",
        )
        _check(not (aspect_tag_ids & brand_tag_ids), "aspect/brand tag overlap")
        matches = _rows(tagging.get("matches"), f"entities[{index}].tagging.matches")
        _check(
            {match.get("tag_id") for match in matches} == row_tag_ids,
            "tag match/id mismatch",
        )
        _check(
            all(
                match.get("validation_status")
                == "lexical_rule_match_unvalidated"
                for match in matches
            ),
            "unexpected semantic tag claim",
        )


def _reference(value: Any, location: str) -> dict[str, Any]:
    result = _object(value, location)
    _check(set(result) == {"id", "name_en", "name_cn"}, f"reference field mismatch: {location}")
    for key in ("id", "name_en", "name_cn"):
        _nonempty_string(result.get(key), f"{location}.{key}")
    return result


def _validate_binding(value: Any, location: str) -> dict[str, Any]:
    binding = _object(value, location)
    _check(set(binding) == BINDING_KEYS, f"product binding field mismatch: {location}")
    _check(binding.get("brand_id") == "momcozy", "non-Momcozy product binding found")
    category = _reference(binding.get("category"), f"{location}.category")
    product_family_raw = binding.get("product_family")
    product_family = (
        None
        if product_family_raw is None
        else _reference(product_family_raw, f"{location}.product_family")
    )
    exact_spu_raw = binding.get("exact_spu")
    exact_spu: dict[str, Any] | None
    if exact_spu_raw is None:
        exact_spu = None
    else:
        exact_spu = _object(exact_spu_raw, f"{location}.exact_spu")
        _check(set(exact_spu) == {"spu_id", "spu_name"}, "exact SPU field mismatch")
        _nonempty_string(exact_spu.get("spu_id"), f"{location}.exact_spu.spu_id")
        _nonempty_string(exact_spu.get("spu_name"), f"{location}.exact_spu.spu_name")
    binding_level = binding.get("binding_level")
    governance_status = binding.get("governance_status")
    match_type = binding.get("match_type")
    _check(
        match_type in {"strong_name", "contextual_alias", "category_context"},
        "product binding match type invalid",
    )
    _nonempty_string(binding.get("matched_alias"), f"{location}.matched_alias")
    _check(
        binding.get("governance_reason") is None
        or isinstance(binding.get("governance_reason"), str),
        "product governance reason invalid",
    )
    if binding_level == "category":
        _check(product_family is None and exact_spu is None, "category binding shape invalid")
        _check(governance_status == "category_only", "category governance mismatch")
        _check(match_type == "category_context", "category match type mismatch")
    elif binding_level == "product_family":
        _check(product_family is not None and exact_spu is None, "family binding shape invalid")
        _check(
            governance_status in {"family_only", "taxonomy_blocked"},
            "family governance mismatch",
        )
        _check(match_type != "category_context", "family match type mismatch")
    elif binding_level == "spu_exact":
        _check(product_family is not None and exact_spu is not None, "exact SPU binding shape invalid")
        _check(governance_status == "exact_spu_approved", "exact SPU governance mismatch")
        _check(match_type != "category_context", "exact SPU match type mismatch")
    else:
        raise ValueError("product binding level invalid")
    return {
        "category_id": category["id"],
        "family_id": product_family["id"] if product_family else None,
        "spu_id": exact_spu["spu_id"] if exact_spu else None,
        "binding_level": binding_level,
        "governance_status": governance_status,
    }


def _recompute_product_coverage(
    rows: list[dict[str, Any]], location: str
) -> dict[str, Any]:
    resolved_bindings: list[dict[str, Any]] = []
    bound_records = 0
    multi_records = 0
    for index, row in enumerate(rows):
        raw_bindings = row.get("product_bindings")
        _check(isinstance(raw_bindings, list), f"product_bindings missing: {location}[{index}]")
        bindings = [
            _validate_binding(value, f"{location}[{index}].product_bindings[{binding_index}]")
            for binding_index, value in enumerate(cast(list[Any], raw_bindings))
        ]
        identities = [
            (binding["category_id"], binding["family_id"], binding["spu_id"])
            for binding in bindings
        ]
        _check(len(identities) == len(set(identities)), "duplicate product binding")
        bound_records += bool(bindings)
        multi_records += len(bindings) > 1
        resolved_bindings.extend(bindings)
    category_counts = Counter(
        cast(str, binding["category_id"]) for binding in resolved_bindings
    )
    family_counts = Counter(
        cast(str, binding["family_id"])
        for binding in resolved_bindings
        if binding["family_id"] is not None
    )
    coverage = {
        "input_record_count": len(rows),
        "bound_record_count": bound_records,
        "unbound_record_count": len(rows) - bound_records,
        "multi_binding_record_count": multi_records,
        "binding_count": len(resolved_bindings),
        "exact_spu_binding_count": sum(
            binding["binding_level"] == "spu_exact" for binding in resolved_bindings
        ),
        "family_only_binding_count": sum(
            binding["binding_level"] == "product_family"
            for binding in resolved_bindings
        ),
        "category_only_binding_count": sum(
            binding["binding_level"] == "category" for binding in resolved_bindings
        ),
        "taxonomy_blocked_binding_count": sum(
            binding["governance_status"] == "taxonomy_blocked"
            for binding in resolved_bindings
        ),
        "category_binding_counts": dict(sorted(category_counts.items())),
        "family_binding_counts": dict(sorted(family_counts.items())),
        "is_conserved": True,
    }
    coverage["is_conserved"] = all(
        (
            coverage["input_record_count"]
            == coverage["bound_record_count"] + coverage["unbound_record_count"],
            coverage["binding_count"]
            == coverage["exact_spu_binding_count"]
            + coverage["family_only_binding_count"]
            + coverage["category_only_binding_count"],
            coverage["binding_count"] == sum(category_counts.values()),
            coverage["binding_count"]
            == sum(family_counts.values()) + coverage["category_only_binding_count"],
            coverage["multi_binding_record_count"] <= coverage["bound_record_count"],
            coverage["taxonomy_blocked_binding_count"]
            <= coverage["family_only_binding_count"],
        )
    )
    return coverage


def _validate_product_resolution(
    manifest: dict[str, Any],
    posts: list[dict[str, Any]],
    comments: list[dict[str, Any]],
) -> str:
    tagging = _object(manifest.get("tagging"), "tagging")
    semantic = _object(manifest.get("semantic_boundaries"), "semantic_boundaries")
    resolution_raw = tagging.get("product_entity_resolution")
    if resolution_raw is None:
        context = _object(tagging.get("entity_context"), "tagging.entity_context")
        status = _nonempty_string(
            context.get("resolution_status"),
            "tagging.entity_context.resolution_status",
        )
        _check(
            status == "pending_product_entity_resolver"
            and semantic.get("product_category_resolution_status") == status,
            "product resolution semantic status mismatch",
        )
        _check(
            "product_entity_resolution" not in tagging,
            "pending product resolution contains resolver metadata",
        )
        _check(
            all("product_bindings" not in row for row in [*posts, *comments]),
            "pending product resolution contains entity bindings",
        )
        _check(
            semantic.get("global_product_category_imputed") is False,
            "pending product category was globally imputed",
        )
        return "pending"
    _check("entity_context" not in tagging, "resolved product status contains legacy context")
    _check(
        semantic.get("product_category_resolution_status")
        == "governed_product_entity_resolver_v1",
        "product resolution semantic status mismatch",
    )
    _check(
        semantic.get("product_entity_ledger_sha256") == PRODUCT_LEDGER_SHA256,
        "semantic product ledger hash mismatch",
    )
    for key in (
        "product_category_analysis_supported",
        "product_family_analysis_supported",
        "exact_spu_analysis_supported_only_for_approved_bindings",
    ):
        _check(semantic.get(key) is True, f"resolved product semantic gate missing: {key}")
    resolution = _object(resolution_raw, "tagging.product_entity_resolution")
    _check(set(resolution) == PRODUCT_RESOLUTION_KEYS, "product resolver field set mismatch")
    _check(resolution.get("status") == "resolved", "product resolver status mismatch")
    _check(
        resolution.get("resolver_version") == PRODUCT_RESOLVER_VERSION,
        "product resolver version mismatch",
    )
    _check(
        resolution.get("ledger_version") == PRODUCT_LEDGER_VERSION,
        "product resolver ledger version mismatch",
    )
    _check(
        resolution.get("ledger_sha256") == PRODUCT_LEDGER_SHA256,
        "product resolver ledger hash mismatch",
    )
    coverage = _object(resolution.get("coverage"), "product resolver coverage")
    _check(set(coverage) == {"posts", "comments", "combined"}, "product coverage layer mismatch")
    expected_coverage = {
        "posts": _recompute_product_coverage(posts, "posts"),
        "comments": _recompute_product_coverage(comments, "comments"),
        "combined": _recompute_product_coverage([*posts, *comments], "combined"),
    }
    for layer, recomputed in expected_coverage.items():
        supplied = _object(coverage.get(layer), f"product coverage.{layer}")
        _check(set(supplied) == COVERAGE_KEYS, f"product coverage field mismatch: {layer}")
        _check(supplied == recomputed, f"product coverage mismatch: {layer}")
    observed_contexts_raw = resolution.get("observed_tag_contexts")
    _check(
        isinstance(observed_contexts_raw, list) and bool(observed_contexts_raw),
        "observed tag contexts missing",
    )
    observed_contexts = [
        _object(value, f"observed_tag_contexts[{index}]")
        for index, value in enumerate(cast(list[Any], observed_contexts_raw))
    ]
    entity_contexts: list[dict[str, Any]] = []
    for index, row in enumerate([*posts, *comments]):
        context = _object(
            row["tagging"].get("context"), f"entities[{index}].tagging.context"
        )
        _check(
            set(context)
            == {"resolution_mode", "contexts", "detected_spu_ids", "spu_binding_mode"},
            "resolved entity tag context field mismatch",
        )
        _check(
            context.get("resolution_mode") == "governed_product_bindings"
            and context.get("spu_binding_mode") == "governed_explicit",
            "resolved entity tag context mode mismatch",
        )
        contexts = _rows(context.get("contexts"), f"entities[{index}].tagging.contexts")
        _check(bool(contexts), "resolved entity tag contexts missing")
        context_spu_ids: set[str] = set()
        for context_index, tag_context in enumerate(contexts):
            _check(
                set(tag_context) == {"product_line", "voc_category", "spu_ids"},
                "resolved tag context field mismatch",
            )
            product_line = tag_context.get("product_line")
            voc_category = tag_context.get("voc_category")
            spu_ids_raw = tag_context.get("spu_ids")
            _check(
                isinstance(product_line, str)
                and isinstance(voc_category, str)
                and isinstance(spu_ids_raw, list),
                "resolved tag context value mismatch",
            )
            _check(
                bool(cast(str, product_line)) == bool(cast(str, voc_category)),
                "resolved tag context scope mismatch",
            )
            spu_ids = [
                _nonempty_string(
                    value,
                    f"entities[{index}].tagging.contexts[{context_index}].spu_ids",
                )
                for value in cast(list[Any], spu_ids_raw)
            ]
            _check(
                len(spu_ids) == len(set(spu_ids)) and spu_ids == sorted(spu_ids),
                "resolved tag context SPU set mismatch",
            )
            context_spu_ids.update(spu_ids)
            if product_line or voc_category:
                entity_contexts.append(tag_context)
        detected_raw = context.get("detected_spu_ids")
        _check(isinstance(detected_raw, list), "resolved detected SPU set missing")
        detected = [
            _nonempty_string(value, "resolved detected SPU id")
            for value in cast(list[Any], detected_raw)
        ]
        _check(
            detected == sorted(context_spu_ids),
            "resolved detected SPU/context mismatch",
        )
    supplied_canonical = {
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for value in observed_contexts
    }
    entity_canonical = {
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for value in entity_contexts
    }
    _check(
        len(supplied_canonical) == len(observed_contexts),
        "duplicate observed tag context",
    )
    _check(supplied_canonical == entity_canonical, "observed tag context mismatch")
    _check(
        semantic.get("global_product_category_imputed") is False,
        "global product category imputation is not allowed",
    )
    return "resolved"


def _validate_privacy_and_boundaries(
    manifest: dict[str, Any],
    posts: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    aggregates: dict[str, Any],
    quarantine: list[dict[str, Any]],
    tag_dictionary: dict[str, Any],
) -> None:
    privacy = _object(manifest.get("privacy"), "privacy")
    expected_privacy = {
        "raw_author_fields_present": False,
        "author_display": "stable_pseudonym",
        "html_fields_present": False,
        "contact_patterns_redacted": True,
        "known_archive_bots_excluded_from_voc_metrics": True,
        "raw_archive_public": False,
        "production_private_snapshot_mode": "0600",
    }
    _check(privacy == expected_privacy, "privacy boundary mismatch")
    _check(manifest.get("production_unchanged") is True, "production boundary mismatch")
    _check(manifest.get("provider_call") is False, "manifest provider call found")
    _check(manifest.get("live_send") is False, "manifest live send found")
    public_values: list[Any] = [posts, comments, aggregates, quarantine, tag_dictionary]
    public_keys = {key for value in public_values for key in _walk_keys(value)}
    _check(not (public_keys & FORBIDDEN_KEYS), "forbidden private key present")
    _check(
        all(
            row.get("author_pseudonym") is None
            or (
                isinstance(row.get("author_pseudonym"), str)
                and re.fullmatch(r"anon_[a-f0-9]{10}", cast(str, row["author_pseudonym"]))
                is not None
            )
            for row in [*posts, *comments]
        ),
        "invalid author pseudonym",
    )
    for text in _entity_texts(posts, comments):
        _check(EMAIL_RE.search(text) is None, "email pattern present")
        _check(PHONE_RE.search(text) is None, "phone pattern present")
        _check(USERNAME_RE.search(text) is None, "username mention present")


def _validate_aggregates(
    aggregates: dict[str, Any],
    posts: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    quarantine: list[dict[str, Any]],
) -> dict[str, int]:
    _check(aggregates.get("schema_version") == AGGREGATES_SCHEMA, "aggregate schema mismatch")
    headline = _object(aggregates.get("headline"), "aggregates.headline")
    included_comments = [row for row in comments if row.get("include_in_voc_metrics") is True]
    expected_counts = {
        "unique_posts": len(posts),
        "linked_comments": len(comments),
        "quarantined_comments": len(quarantine),
        "comments_in_voc_metrics": len(included_comments),
        "analysis_covered_posts": len(posts),
        "analysis_covered_comments": len(comments),
        "posts_with_rule_tags": sum(bool(row["tagging"]["tag_ids"]) for row in posts),
        "comments_with_rule_tags_in_voc_metrics": sum(
            bool(row["tagging"]["tag_ids"]) for row in included_comments
        ),
        "posts_with_aspect_tags": sum(
            bool(row["tagging"]["aspect_tag_ids"]) for row in posts
        ),
        "comments_with_aspect_tags": sum(
            bool(row["tagging"]["aspect_tag_ids"]) for row in included_comments
        ),
    }
    for key, expected in expected_counts.items():
        _check(headline.get(key) == expected, f"aggregate headline mismatch: {key}")
    tagging = _object(aggregates.get("tagging"), "aggregates.tagging")
    _check(
        tagging.get("posts_with_rule_tags") == expected_counts["posts_with_rule_tags"],
        "aggregate post tag coverage mismatch",
    )
    _check(
        tagging.get("comments_with_rule_tags")
        == expected_counts["comments_with_rule_tags_in_voc_metrics"],
        "aggregate comment tag coverage mismatch",
    )
    _check(
        tagging.get("posts_with_aspect_tags")
        == expected_counts["posts_with_aspect_tags"],
        "aggregate post aspect coverage mismatch",
    )
    _check(
        tagging.get("comments_with_aspect_tags")
        == expected_counts["comments_with_aspect_tags"],
        "aggregate comment aspect coverage mismatch",
    )
    return expected_counts


def _v3_identity_lf_sha256(values: Iterable[str]) -> str:
    ordered = sorted(values)
    _check(len(ordered) == len(set(ordered)), "V3 identity set contains duplicates")
    return sha256(
        "".join(f"{value}\n" for value in ordered).encode("utf-8")
    ).hexdigest()


def _v3_distinct_identity_lf_sha256(values: Iterable[str]) -> str:
    return sha256(
        "".join(f"{value}\n" for value in sorted(set(values))).encode("utf-8")
    ).hexdigest()


def _read_v3_site_manifest(snapshot_dir: Path) -> bytes:
    try:
        directory_fd = os.open(snapshot_dir, v3_independent.DIRECTORY_FLAGS)
    except OSError as exc:
        raise ValueError("V3 snapshot directory is unavailable") from exc
    try:
        metadata = os.fstat(directory_fd)
        _check(
            stat.S_ISDIR(metadata.st_mode)
            and stat.S_IMODE(metadata.st_mode) == 0o700,
            "V3 snapshot directory must have mode 0700",
        )
        try:
            inventory = set(os.listdir(directory_fd))
        except OSError as exc:
            raise ValueError("V3 snapshot inventory is unavailable") from exc
        _check(inventory == {"manifest.json"}, "V3 snapshot inventory is invalid")
        return v3_independent._read_at(
            directory_fd,
            "manifest.json",
            label="V3 site-state manifest",
            require_private=True,
        )
    finally:
        os.close(directory_fd)


def _load_validated_v3_canonical(
    *,
    canonical_root: Path,
    expected_manifest_sha256: str,
    validation_receipt: Path,
    expected_validation_receipt_sha256: str,
    project_root: Path,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, bytes],
    dict[str, Any],
    bytes,
    bytes,
]:
    canonical_parts = v3_independent._private_parts(
        canonical_root, project_root, "V3 canonical bundle"
    )
    receipt_parts = v3_independent._private_parts(
        validation_receipt, project_root, "V3 canonical validation receipt"
    )
    _check(
        receipt_parts[: len(canonical_parts)] != canonical_parts,
        "V3 canonical validation receipt must be outside the canonical bundle",
    )

    manifest_sha = v3_independent._sha_value(
        expected_manifest_sha256, "V3 canonical manifest SHA-256"
    )
    receipt_sha = v3_independent._sha_value(
        expected_validation_receipt_sha256,
        "V3 canonical validation receipt SHA-256",
    )
    raw_payloads = v3_independent._read_private_bundle(
        canonical_root,
        expected_inventory=v3_independent.CANONICAL_FILES,
        project_root=project_root,
        label="V3 canonical bundle",
    )
    manifest_payload = raw_payloads["manifest.json"]
    _check(
        v3_independent._sha(manifest_payload) == manifest_sha,
        "V3 canonical manifest hash mismatch",
    )
    manifest = v3_independent._object(
        manifest_payload, "V3 canonical manifest"
    )
    expected_manifest_fields = {
        "boundaries",
        "canonical_counts",
        "consumption_status",
        "dataset_id",
        "files",
        "governed_base_parent_lineage_debt",
        "independent_validation_status",
        "inputs",
        "promotable",
        "schema_version",
        "source_row_accounting",
        "state_contract",
        "status",
        "validation_receipt_sha256",
    }
    _check(set(manifest) == expected_manifest_fields, "V3 canonical manifest fields are invalid")
    _check(
        manifest.get("schema_version")
        == "reddit_voc_canonical_snapshot_manifest_v1"
        and manifest.get("status") == "candidate_built"
        and manifest.get("independent_validation_status") == "pending"
        and manifest.get("consumption_status")
        == "blocked_pending_independent_validation"
        and manifest.get("promotable") is False
        and manifest.get("validation_receipt_sha256") is None
        and manifest.get("boundaries") == V3_BOUNDARIES,
        "V3 canonical manifest lifecycle is invalid",
    )
    dataset_id = manifest.get("dataset_id")
    _check(
        isinstance(dataset_id, str) and dataset_id.endswith("_canonical_v1"),
        "V3 canonical dataset ID is invalid",
    )
    canonical_payloads = v3_independent._bound_documents(
        raw_payloads,
        manifest,
        v3_independent.CANONICAL_FILES - {"manifest.json"},
        "V3 canonical",
    )

    receipt_payload = v3_independent._read_private_receipt(
        validation_receipt,
        project_root=project_root,
        label="V3 canonical validation receipt",
    )
    _check(
        v3_independent._sha(receipt_payload) == receipt_sha,
        "V3 canonical validation receipt hash mismatch",
    )
    receipt = v3_independent._object(
        receipt_payload, "V3 canonical validation receipt"
    )
    expected_receipt_fields = {
        "boundaries",
        "bundle_manifest_sha256",
        "canonical_counts",
        "consumption_status",
        "inputs",
        "promotable",
        "schema_version",
        "source_row_accounting",
        "status",
        "unaccounted_canonical_identities",
        "unaccounted_foreign_keys",
    }
    source_accounting = manifest.get("source_row_accounting")
    expected_receipt_accounting = None
    if isinstance(source_accounting, dict):
        expected_receipt_accounting = {
            "source_rows": source_accounting.get("source_rows"),
            "terminal_outcomes": source_accounting.get("terminal_outcomes"),
        }
    _check(
        set(receipt) == expected_receipt_fields
        and receipt.get("schema_version")
        == "reddit_voc_canonical_snapshot_validation_receipt_v1"
        and receipt.get("status") == "passed"
        and receipt.get("bundle_manifest_sha256")
        == v3_independent._sha(manifest_payload)
        and receipt.get("consumption_status") == "blocked_pending_voc_facts"
        and receipt.get("promotable") is False
        and receipt.get("boundaries") == V3_BOUNDARIES
        and type(receipt.get("unaccounted_canonical_identities")) is int
        and receipt.get("unaccounted_canonical_identities") == 0
        and type(receipt.get("unaccounted_foreign_keys")) is int
        and receipt.get("unaccounted_foreign_keys") == 0
        and receipt.get("canonical_counts") == manifest.get("canonical_counts")
        and receipt.get("inputs") == manifest.get("inputs")
        and receipt.get("source_row_accounting") == expected_receipt_accounting,
        "V3 canonical validation receipt is not consumable",
    )

    policy_path = (
        project_root
        / "config"
        / "analytics"
        / "reddit-voc-metric-eligibility-v1.json"
    )
    policy_payload = v3_independent._read_project_file(
        policy_path,
        project_root=project_root,
        label="V3 metric eligibility policy",
    )
    _check(
        v3_independent._sha(policy_payload) == V3_POLICY_SHA256,
        "V3 metric eligibility policy hash mismatch",
    )
    policy = v3_independent._object(
        policy_payload, "V3 metric eligibility policy"
    )
    v3_independent._validate_policy(policy)
    return (
        manifest,
        receipt,
        canonical_payloads,
        policy,
        manifest_payload,
        receipt_payload,
    )


def _summarize_v3_metric_eligibility(
    vocs: list[dict[str, Any]], policy: dict[str, Any]
) -> tuple[dict[str, Any], set[str]]:
    policy_with_context = dict(policy)
    policy_with_context["_period"] = V3_PERIOD
    policy_with_context["_scope"] = V3_SCOPE
    membership_rows = 0
    eligible_rows = 0
    excluded_rows = 0
    denominator_true_rows = 0
    numerator_true_rows = 0
    eligible_by_type: dict[str, set[str]] = {
        "post_voc": set(),
        "comment_context_voc": set(),
    }
    for row in v3_independent._iter_expected_eligibility(
        vocs, policy_with_context
    ):
        membership_rows += 1
        status = row.get("status")
        _check(status in {"eligible", "excluded"}, "V3 eligibility status is invalid")
        if status == "eligible":
            eligible_rows += 1
            voc_type = cast(str, row.get("voc_type"))
            _check(voc_type in eligible_by_type, "V3 eligibility VOC type is invalid")
            eligible_by_type[voc_type].add(
                _nonempty_string(
                    row.get("metric_member_id"), "V3 eligibility member ID"
                )
            )
        else:
            excluded_rows += 1
        denominator_true_rows += row.get("denominator_member") is True
        numerator_true_rows += row.get("numerator_member") is True
    eligible_ids = eligible_by_type["post_voc"] | eligible_by_type["comment_context_voc"]
    _check(
        not (
            eligible_by_type["post_voc"]
            & eligible_by_type["comment_context_voc"]
        ),
        "V3 eligible identity appears in multiple VOC grains",
    )
    return (
        {
            "denominator_true_rows": denominator_true_rows,
            "distinct_eligible_comment_context_vocs": len(
                eligible_by_type["comment_context_voc"]
            ),
            "distinct_eligible_post_vocs": len(eligible_by_type["post_voc"]),
            "distinct_eligible_voc_facts": len(eligible_ids),
            "eligible_identity_lf_sha256": _v3_distinct_identity_lf_sha256(
                eligible_ids
            ),
            "eligible_rows": eligible_rows,
            "excluded_rows": excluded_rows,
            "membership_rows": membership_rows,
            "numerator_true_rows": numerator_true_rows,
            "period": V3_PERIOD,
            "scope": V3_SCOPE,
        },
        eligible_ids,
    )


def _recompute_v3_state_vector(
    canonical_payloads: dict[str, bytes],
    canonical_manifest: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    canonical_posts = v3_independent._jsonl(
        canonical_payloads["posts.jsonl"], "V3 canonical posts"
    )
    canonical_comments = v3_independent._jsonl(
        canonical_payloads["comments.jsonl"], "V3 canonical comments"
    )
    canonical_quarantine = v3_independent._jsonl(
        canonical_payloads["quarantine.jsonl"], "V3 canonical quarantine"
    )
    unresolved_ledger = v3_independent._jsonl(
        canonical_payloads["unresolved-parent-ledger.jsonl"],
        "V3 canonical unresolved parent ledger",
    )
    vocs, exclusions, computed_counts = v3_independent._expected_materialization(
        canonical_posts,
        canonical_comments,
        canonical_quarantine,
        unresolved_ledger,
    )
    _check(
        canonical_manifest.get("canonical_counts") == computed_counts,
        "V3 canonical counts do not reproduce canonical documents",
    )

    canonical_ids = [
        _nonempty_string(row.get("canonical_reddit_id"), "V3 canonical identity")
        for row in [*canonical_posts, *canonical_comments, *canonical_quarantine]
    ]
    voc_ids = [
        _nonempty_string(row.get("canonical_entity_id"), "V3 VOC identity")
        for row in vocs
    ]
    exclusion_ids = [
        _nonempty_string(
            row.get("canonical_entity_id"), "V3 exclusion identity"
        )
        for row in exclusions
    ]
    _check(
        not (set(voc_ids) & set(exclusion_ids))
        and set(canonical_ids) == set(voc_ids) | set(exclusion_ids),
        "V3 VOC/exclusion identity partition is invalid",
    )
    analysis_ready = [
        row for row in vocs if row.get("analysis_text_status") == "ready"
    ]
    analysis_ready_ids = {
        cast(str, row["canonical_entity_id"]) for row in analysis_ready
    }
    _check(
        analysis_ready_ids <= set(voc_ids),
        "V3 analysis-ready identities are outside VOC facts",
    )

    eligibility, eligible_ids = _summarize_v3_metric_eligibility(vocs, policy)
    _check(
        eligible_ids <= analysis_ready_ids,
        "V3 metric-eligible identities are outside analysis-ready facts",
    )

    reason_counts: Counter[str] = Counter()
    for row in exclusions:
        reasons = row.get("reason_codes")
        _check(
            isinstance(reasons, list)
            and bool(reasons)
            and all(isinstance(reason, str) and reason for reason in reasons),
            "V3 exclusion reason codes are invalid",
        )
        reason_counts.update(cast(list[str], reasons))

    day_precision = 0
    instant_or_hour_precision = 0
    missing_event_time = 0
    for row in vocs:
        precision = row.get("event_time_precision")
        if precision == "day":
            day_precision += 1
            _check(
                isinstance(row.get("source_calendar_date"), str)
                and row.get("event_created_at_utc") is None
                and row.get("source_timezone_status") == "unknown",
                "V3 floating day received a fabricated instant",
            )
        elif precision in {"instant", "hour"}:
            instant_or_hour_precision += 1
            _check(
                isinstance(row.get("event_created_at_utc"), str)
                and row.get("source_calendar_date") is None,
                "V3 instant/hour time contract is invalid",
            )
        elif precision is None:
            missing_event_time += 1
            _check(
                row.get("event_created_at_utc") is None
                and row.get("source_calendar_date") is None,
                "V3 missing-time contract is invalid",
            )
        else:
            raise ValueError("V3 event time precision is invalid")

    canonical_state = {
        **computed_counts,
        "identity_lf_sha256": _v3_identity_lf_sha256(canonical_ids),
        "total_identities": len(canonical_ids),
    }
    voc_state = {
        "comment_context_vocs": sum(
            row.get("voc_type") == "comment_context_voc" for row in vocs
        ),
        "identity_lf_sha256": _v3_identity_lf_sha256(voc_ids),
        "post_vocs": sum(row.get("voc_type") == "post_voc" for row in vocs),
        "total_vocs": len(vocs),
    }
    analysis_ids = [
        cast(str, row["canonical_entity_id"]) for row in analysis_ready
    ]
    analysis_state = {
        "comment_context_vocs": sum(
            row.get("voc_type") == "comment_context_voc"
            for row in analysis_ready
        ),
        "identity_lf_sha256": _v3_identity_lf_sha256(analysis_ids),
        "post_vocs": sum(
            row.get("voc_type") == "post_voc" for row in analysis_ready
        ),
        "total_vocs": len(analysis_ready),
    }
    exclusion_state = {
        "excluded_comment_identities": sum(
            row.get("entity_type") == "comment" for row in exclusions
        ),
        "excluded_identities": len(exclusions),
        "excluded_post_identities": sum(
            row.get("entity_type") == "post" for row in exclusions
        ),
        "identity_lf_sha256": _v3_identity_lf_sha256(exclusion_ids),
        "reason_counts": dict(sorted(reason_counts.items())),
    }
    time_state = {
        "day_precision_vocs": day_precision,
        "instant_or_hour_precision_vocs": instant_or_hour_precision,
        "missing_event_time_vocs": missing_event_time,
    }
    _check(set(canonical_state) == V3_CANONICAL_STATE_KEYS, "V3 canonical state fields are invalid")
    _check(set(voc_state) == V3_VOC_STATE_KEYS, "V3 VOC state fields are invalid")
    _check(set(analysis_state) == V3_VOC_STATE_KEYS, "V3 analysis-ready state fields are invalid")
    _check(set(exclusion_state) == V3_EXCLUSION_STATE_KEYS, "V3 exclusion state fields are invalid")
    _check(set(eligibility) == V3_ELIGIBILITY_STATE_KEYS, "V3 eligibility state fields are invalid")
    _check(set(time_state) == V3_TIME_STATE_KEYS, "V3 time state fields are invalid")
    return {
        "analysis_ready": analysis_state,
        "canonical": canonical_state,
        "exclusions": exclusion_state,
        "metric_eligibility": eligibility,
        "time_precision": time_state,
        "voc_facts": voc_state,
    }


def _validate_v3_site_state(
    snapshot_dir: Path,
    *,
    expected_dataset_version: str,
    canonical_root: Path,
    canonical_manifest_sha256: str,
    validation_receipt: Path,
    validation_receipt_sha256: str,
) -> dict[str, Any]:
    project_root = Path(__file__).resolve().parents[1]
    manifest_payload = _read_v3_site_manifest(snapshot_dir)
    manifest = v3_independent._object(manifest_payload, "V3 site-state manifest")
    _check(set(manifest) == V3_TOP_LEVEL_KEYS, "V3 site-state manifest fields are invalid")
    _check(manifest.get("schema_version") == MANIFEST_SCHEMA_V3, "V3 manifest schema mismatch")
    dataset_version = _nonempty_string(
        manifest.get("dataset_version"), "V3 dataset_version"
    )
    _check(
        DATASET_VERSION_RE.fullmatch(dataset_version) is not None,
        "V3 dataset version invalid",
    )
    _check(dataset_version == expected_dataset_version, "V3 dataset version mismatch")
    _parse_utc(manifest.get("generated_at_utc"), "V3 generated_at_utc")
    _check(
        manifest.get("delivery_mode") == "isolated_v3_state_snapshot"
        and manifest.get("artifact_stage") == "v3_state_vector_only"
        and manifest.get("public_projection_complete") is False
        and manifest.get("release_candidate") is False
        and manifest.get("files") == {},
        "V3 site-state publication lifecycle is invalid",
    )
    _check(manifest.get("boundaries") == V3_BOUNDARIES, "V3 side-effect boundaries mismatch")
    fusion_accounting = _object(
        manifest.get("fusion_accounting"), "V3 fusion_accounting"
    )
    _check(
        fusion_accounting
        == {"fusion_mode": "complete_canonical_union", "legacy_append": False},
        "V3 fusion accounting is invalid",
    )

    (
        canonical_manifest,
        canonical_receipt,
        canonical_payloads,
        policy,
        canonical_manifest_payload,
        canonical_receipt_payload,
    ) = _load_validated_v3_canonical(
        canonical_root=canonical_root,
        expected_manifest_sha256=canonical_manifest_sha256,
        validation_receipt=validation_receipt,
        expected_validation_receipt_sha256=validation_receipt_sha256,
        project_root=project_root,
    )
    policy_version = _nonempty_string(
        policy.get("policy_version"), "V3 metric eligibility policy version"
    )
    inputs = _object(manifest.get("inputs"), "V3 inputs")
    _check(set(inputs) == V3_INPUT_KEYS, "V3 input fields are invalid")
    _check(
        inputs
        == {
            "canonical_dataset_id": canonical_manifest.get("dataset_id"),
            "canonical_manifest_sha256": v3_independent._sha(
                canonical_manifest_payload
            ),
            "canonical_validation_receipt_sha256": v3_independent._sha(
                canonical_receipt_payload
            ),
            "metric_eligibility_policy_sha256": V3_POLICY_SHA256,
            "metric_eligibility_policy_version": policy_version,
        },
        "V3 site-state input bindings mismatch",
    )

    lifecycle = _object(
        manifest.get("upstream_lifecycle"), "V3 upstream_lifecycle"
    )
    _check(set(lifecycle) == V3_LIFECYCLE_KEYS, "V3 upstream lifecycle fields are invalid")
    _check(
        lifecycle
        == {
            "canonical_consumption_status": canonical_manifest.get(
                "consumption_status"
            ),
            "canonical_independent_validation_status": canonical_manifest.get(
                "independent_validation_status"
            ),
            "canonical_manifest_status": canonical_manifest.get("status"),
            "promotable": False,
            "validation_consumption_status": canonical_receipt.get(
                "consumption_status"
            ),
            "validation_status": canonical_receipt.get("status"),
        },
        "V3 upstream lifecycle binding mismatch",
    )

    state_vector = _recompute_v3_state_vector(
        canonical_payloads, canonical_manifest, policy
    )
    supplied_state = _object(manifest.get("state_vector"), "V3 state_vector")
    _check(set(supplied_state) == V3_STATE_VECTOR_KEYS, "V3 state vector fields are invalid")
    _check(supplied_state == state_vector, "V3 state vector does not reproduce canonical input")

    checks = _object(manifest.get("checks"), "V3 checks")
    _check(
        set(checks) == V3_CHECK_KEYS
        and all(value is True for value in checks.values()),
        "V3 builder checks are invalid",
    )
    _check(manifest.get("all_checks_passed") is True, "V3 builder checks did not pass")
    _check(
        not ({key for key in _walk_keys(manifest)} & FORBIDDEN_KEYS),
        "V3 manifest contains a forbidden private key",
    )

    return {
        "artifact_stage": "v3_state_vector_only",
        "boundaries": dict(V3_BOUNDARIES),
        "checks": {key: True for key in sorted(V3_CHECK_KEYS)},
        "dataset_version": dataset_version,
        "database_write": False,
        "deploy": False,
        "live_send": False,
        "manifest_sha256": v3_independent._sha(manifest_payload),
        "production_unchanged": True,
        "provider_call": False,
        "public_projection_complete": False,
        "release_candidate": False,
        "remote_write": False,
        "schema_version": V3_VALIDATION_SCHEMA,
        "state_vector": state_vector,
        "status": "passed_state_vector_only",
        "validated_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def validate(
    snapshot_dir: Path,
    *,
    expected_dataset_version: str,
    v3_canonical_root: Path | None = None,
    v3_canonical_manifest_sha256: str | None = None,
    v3_validation_receipt: Path | None = None,
    v3_validation_receipt_sha256: str | None = None,
) -> dict[str, Any]:
    _check(snapshot_dir.is_dir(), "snapshot directory missing")
    _check(
        DATASET_VERSION_RE.fullmatch(expected_dataset_version) is not None,
        "expected dataset version invalid",
    )
    v3_arguments = (
        v3_canonical_root,
        v3_canonical_manifest_sha256,
        v3_validation_receipt,
        v3_validation_receipt_sha256,
    )
    _check(
        not any(value is not None for value in v3_arguments)
        or all(value is not None for value in v3_arguments),
        "V3 canonical arguments must be supplied all-or-none",
    )
    if all(value is not None for value in v3_arguments):
        return _validate_v3_site_state(
            snapshot_dir,
            expected_dataset_version=expected_dataset_version,
            canonical_root=cast(Path, v3_canonical_root),
            canonical_manifest_sha256=cast(str, v3_canonical_manifest_sha256),
            validation_receipt=cast(Path, v3_validation_receipt),
            validation_receipt_sha256=cast(
                str, v3_validation_receipt_sha256
            ),
        )
    manifest = _object(_load(snapshot_dir / "manifest.json"), "manifest")
    manifest_schema = manifest.get("schema_version")
    if manifest_schema == MANIFEST_SCHEMA_V3:
        raise ValueError(
            "V3 manifest requires explicit canonical root, hashes, and validation receipt"
        )
    _check(
        not any(value is not None for value in v3_arguments),
        "legacy manifest must not carry V3 canonical arguments",
    )
    _check(manifest_schema in MANIFEST_SCHEMAS, "manifest schema mismatch")
    manifest_schema = cast(str, manifest_schema)
    expected_source_keys = (
        EXPECTED_SOURCE_KEYS_V2
        if manifest_schema == MANIFEST_SCHEMA_V2
        else EXPECTED_SOURCE_KEYS_V1
    )
    dataset_version = _nonempty_string(manifest.get("dataset_version"), "dataset_version")
    _check(DATASET_VERSION_RE.fullmatch(dataset_version) is not None, "dataset version invalid")
    _check(dataset_version == expected_dataset_version, "dataset version mismatch")
    _check(
        manifest.get("delivery_mode") == "versioned_static_snapshot",
        "snapshot delivery mode mismatch",
    )
    _parse_utc(manifest.get("generated_at_utc"), "generated_at_utc")
    paths = _validate_manifest_files(snapshot_dir, manifest)

    posts = _rows(_load(paths["posts.json"]), "posts")
    comments = _rows(_load(paths["comments.json"]), "comments")
    aggregates = _object(_load(paths["aggregates.json"]), "aggregates")
    quarantine = _rows(_load(paths["quarantine.json"]), "quarantine")
    tag_dictionary = _object(_load(paths["tag-dictionary.json"]), "tag_dictionary")

    counts = _validate_counts(manifest, posts, comments, quarantine)
    _, post_sources, comment_sources = _validate_identity_and_sources(
        posts,
        comments,
        quarantine,
        expected_source_keys=expected_source_keys,
    )
    _validate_analysis_and_tags(manifest, posts, comments, tag_dictionary)
    product_resolution = _validate_product_resolution(manifest, posts, comments)
    product_status = (
        "pending_product_entity_resolver"
        if product_resolution == "pending"
        else "resolved"
    )
    v2_hash_binding = _validate_fusion(
        manifest,
        counts,
        posts,
        comments,
        post_sources,
        comment_sources,
        manifest_schema=manifest_schema,
        product_resolution_status=product_status,
    )
    aggregate_counts = _validate_aggregates(
        aggregates, posts, comments, quarantine
    )
    _validate_privacy_and_boundaries(
        manifest, posts, comments, aggregates, quarantine, tag_dictionary
    )
    builder_checks = _object(manifest.get("checks"), "manifest.checks")
    _check(bool(builder_checks), "builder checks missing")
    _check(all(value is True for value in builder_checks.values()), "builder check failed")
    _check(manifest.get("all_checks_passed") is True, "builder all-checks status failed")

    release_candidate = (
        product_resolution == "resolved" and v2_hash_binding == "manifest_exact"
    )
    status = (
        "passed_release_candidate"
        if release_candidate
        else "validated_with_pending_product_resolution"
    )
    checks = {
        "schema_and_expected_version_binding": True,
        "manifest_file_set_bytes_and_hashes": True,
        "canonical_count_identity_and_parent_conservation": True,
        "source_occurrence_and_net_new_fusion_conservation": True,
        "v2_identity_gap_and_nonzero_coverage_debt": True,
        "analysis_and_governed_provisional_tag_contract": True,
        "product_resolution_state_contract": True,
        "privacy_and_side_effect_boundaries": True,
        "aggregate_denominator_reconciliation": True,
        "builder_check_cross_check": True,
    }
    result = {
        "schema_version": VALIDATION_SCHEMA,
        "validated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_version": dataset_version,
        "status": status,
        "release_candidate": release_candidate,
        "product_entity_resolution": product_resolution,
        "v2_target_hash_binding": v2_hash_binding,
        "checks": checks,
        "counts": {
            **counts,
            "comments_in_voc_metrics": aggregate_counts["comments_in_voc_metrics"],
            "entities_with_rule_tags": aggregate_counts["posts_with_rule_tags"]
            + aggregate_counts["comments_with_rule_tags_in_voc_metrics"],
            "entities_with_aspect_tags": aggregate_counts["posts_with_aspect_tags"]
            + aggregate_counts["comments_with_aspect_tags"],
        },
        "production_unchanged": True,
        "provider_call": False,
        "database_write": False,
        "live_send": False,
        "deploy": False,
    }
    if manifest_schema == MANIFEST_SCHEMA_V2:
        result["manifest_sha256"] = _sha256(snapshot_dir / "manifest.json")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--expected-dataset-version", required=True)
    parser.add_argument("--v3-canonical-root", type=Path)
    parser.add_argument("--v3-canonical-manifest-sha256")
    parser.add_argument("--v3-validation-receipt", type=Path)
    parser.add_argument("--v3-validation-receipt-sha256")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    has_v3_argument = any(
        value is not None
        for value in (
            args.v3_canonical_root,
            args.v3_canonical_manifest_sha256,
            args.v3_validation_receipt,
            args.v3_validation_receipt_sha256,
        )
    )
    result = validate(
        (
            args.snapshot_dir
            if has_v3_argument
            else args.snapshot_dir.resolve(strict=True)
        ),
        expected_dataset_version=args.expected_dataset_version,
        v3_canonical_root=args.v3_canonical_root,
        v3_canonical_manifest_sha256=args.v3_canonical_manifest_sha256,
        v3_validation_receipt=args.v3_validation_receipt,
        v3_validation_receipt_sha256=args.v3_validation_receipt_sha256,
    )
    if args.receipt:
        if has_v3_argument:
            v3_independent._write_receipt(
                args.receipt,
                result,
                Path(__file__).resolve().parents[1],
            )
        else:
            args.receipt.parent.mkdir(parents=True, exist_ok=True)
            args.receipt.write_text(
                json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
