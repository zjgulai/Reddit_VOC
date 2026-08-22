#!/usr/bin/env python3
"""Validate one immutable Reddit VOC incremental candidate, without building it.

This gate is intentionally read-only except for an optional immutable receipt.
It does not copy public data, update the UI source tree, deploy, call a provider,
write a database, change a schedule, or describe partial hydration as complete.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any, Iterable


SCHEMA_VERSION = "reddit_voc_incremental_candidate_validation_v1"
SUCCESS_STATUS = "candidate_validated_with_explicit_debt"
FAIL_STATUS = "fail-closed"
FREEZE_SCHEMA = "reddit_voc_incremental_input_freeze_v1"
ANALYTICS_RECEIPT_SCHEMA = "reddit_voc_site_analytics_validation_v1"
BASE_MANIFEST_V1 = "reddit_voc_site_snapshot_manifest_v1"
BASE_MANIFEST_V2 = "reddit_voc_site_snapshot_manifest_v2"
BASE_V2_SOURCE_KEYS = frozenset(
    {
        "imported_archive",
        "historical_canonical",
        "tencent_production_primary",
        "tencent_isolated_staging",
        "tencent_v2_search_hydrated",
        "tencent_existing_post_comment_hydration",
    }
)
BASE_V2_LOAD_ORDER = [
    "imported_archive",
    "historical_canonical_lineage_only",
    "tencent_production_primary",
    "tencent_isolated_staging_overlay",
    "tencent_v2_search_hydrated_disjoint_append",
    "tencent_existing_post_comment_hydration_append",
]
BASE_V2_UNION_COUNT_FIELDS = (
    "first_page_missing",
    "cursor_outstanding",
    "page_pagination_outstanding",
    "failed_reports",
    "partial_threads",
    "not_observed_threads",
)
BASE_V2_UNION_SHA_FIELDS = (
    "first_page_missing_lf_sha256",
    "cursor_outstanding_lf_sha256",
    "page_pagination_outstanding_lf_sha256",
    "failed_reports_lf_sha256",
    "partial_thread_ids_lf_sha256",
    "not_observed_thread_ids_lf_sha256",
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
VERSION_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,127}$")
RC_FREEZE_RE = re.compile(
    r"^reddit_voc_incremental_freeze_"
    r"(?P<body>[a-z0-9][a-z0-9_-]{1,94}[a-z0-9])_"
    r"rc(?P<generation>[1-9][0-9]*)$"
)
DATASET_PREFIXES = {
    "base": "reddit_voc_site_snapshot_",
    "insights": "reddit_voc_insights_",
    "reports": "reddit_voc_reports_",
    "personas": "reddit_voc_personas_",
}
DATASET_LAYERS = ("base", "insights", "reports", "personas")
RELEASE_METADATA_KEYS = frozenset(
    {
        "schema_version",
        "release_sha256",
        "generated_at_utc",
        "delivery_mode",
        "public_access",
        "authentication_enabled",
        "latest_collection_integrated",
        "latest_collection_fully_hydrated",
        "nginx_base_image",
        "target_platform",
        "build_contract_version",
        "deployment_inputs",
        "build_inputs",
        "toolchain",
        "dataset_versions",
        "dataset_manifests",
        "current_release",
        "file_count",
        "files",
        "boundaries",
    }
)
DEPLOYMENT_INPUT_PATHS = (
    "deploy/insights/Dockerfile",
    "deploy/insights/nginx.conf",
    "deploy/insights/compose.yaml",
    "deploy/insights/build-release.mjs",
)
BUILD_INPUT_PATHS = (
    "package-lock.json",
    "scripts/build_public_tag_dictionary.py",
    "scripts/build_public_site_projection.py",
    "scripts/build_insights_release.sh",
    "scripts/audit_insights_dist.py",
    "ref/UI/momcozy-reddit-workbench/.dockerignore",
)
RELEASE_METADATA_BOUNDARIES = {
    "provider_call": False,
    "database_write": False,
    "live_send": False,
    "webhook_send": False,
    "schedule_change": False,
    "collector_restart": False,
    "collector_isolation_required": True,
    "case_gallery_stock_preserved": True,
    "login_required": False,
}
CASE_STOCK = {
    "seed": {
        "source": "bundled_seed",
        "version": "case_seed_bundled_v1",
        "count": 38,
        "contentSha256": (
            "372fa672767ed2585300cd1d47141b6189d3d6784b98c4bc8a69074db5ba48a7"
        ),
    },
    "legacyUnverified": {
        "source": "bundled_legacy_snapshot",
        "version": "legacy_unverified_bundled_v1",
        "count": 12,
        "contentSha256": (
            "9d09b10949eb3790b34507d13dcbddcaf5fcd6e9f81e96dddd7e12ef86691de2"
        ),
    },
}
OUTPUT_BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_merge": False,
    "provider_attempt_made": False,
    "provider_call": False,
    "remote_write": False,
    "schedule_change": False,
    "webhook_send": False,
}


class IncrementalCandidateValidationError(ValueError):
    """The candidate does not satisfy the immutable cross-layer contract."""


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")


def _compact_sha(value: object) -> str:
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require(condition: bool, error: str) -> None:
    if not condition:
        raise IncrementalCandidateValidationError(error)


def _safe_file(path: Path, *, label: str) -> Path:
    if path.is_symlink():
        raise IncrementalCandidateValidationError(f"{label}_unsafe")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise IncrementalCandidateValidationError(f"{label}_missing") from exc
    if not resolved.is_file():
        raise IncrementalCandidateValidationError(f"{label}_unsafe")
    return resolved


def _safe_directory(path: Path, *, label: str) -> Path:
    if path.is_symlink():
        raise IncrementalCandidateValidationError(f"{label}_unsafe")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise IncrementalCandidateValidationError(f"{label}_missing") from exc
    if not resolved.is_dir():
        raise IncrementalCandidateValidationError(f"{label}_unsafe")
    return resolved


def _load_object(path: Path, *, label: str) -> tuple[dict[str, Any], Path]:
    resolved = _safe_file(path, label=label)
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IncrementalCandidateValidationError(f"{label}_invalid_json") from exc
    if not isinstance(value, dict):
        raise IncrementalCandidateValidationError(f"{label}_not_object")
    return value, resolved


def _utc(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IncrementalCandidateValidationError(f"{label}_invalid")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise IncrementalCandidateValidationError(f"{label}_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise IncrementalCandidateValidationError(f"{label}_not_utc")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _object(value: object, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IncrementalCandidateValidationError(f"{label}_invalid")
    return value


def _list(value: object, *, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise IncrementalCandidateValidationError(f"{label}_invalid")
    return value


def _string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise IncrementalCandidateValidationError(f"{label}_invalid")
    return value


def _rc_generation(value: object) -> tuple[str, int]:
    freeze_id = _string(value, label="input_freeze_id")
    match = RC_FREEZE_RE.fullmatch(freeze_id)
    if match is None:
        raise IncrementalCandidateValidationError(
            "input_freeze_rc_generation_invalid"
        )
    generation = int(match.group("generation"))
    if generation < 2:
        raise IncrementalCandidateValidationError(
            "input_freeze_rc_generation_invalid"
        )
    return freeze_id, generation


def _integer(value: object, *, label: str, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise IncrementalCandidateValidationError(f"{label}_invalid")
    if value < (1 if positive else 0):
        raise IncrementalCandidateValidationError(f"{label}_invalid")
    return value


def _sha(value: object, *, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise IncrementalCandidateValidationError(f"{label}_invalid")
    return value


def _dataset_version(value: object, *, layer: str) -> str:
    prefix = DATASET_PREFIXES[layer]
    if (
        not isinstance(value, str)
        or not value.startswith(prefix)
        or VERSION_RE.fullmatch(value) is None
    ):
        raise IncrementalCandidateValidationError(
            f"{layer}_dataset_version_invalid"
        )
    return value


def _require_false_fields(
    value: dict[str, Any], fields: Iterable[str], *, label: str
) -> None:
    for field in fields:
        if value.get(field) is not False:
            raise IncrementalCandidateValidationError(
                f"{label}_{field}_boundary_invalid"
            )


def _require_all_true(value: object, *, label: str) -> dict[str, bool]:
    if not isinstance(value, dict) or not value:
        raise IncrementalCandidateValidationError(f"{label}_invalid")
    if any(not isinstance(item, bool) or item is not True for item in value.values()):
        raise IncrementalCandidateValidationError(f"{label}_not_all_true")
    return value


def _validate_file_manifest(
    directory: Path,
    manifest: dict[str, Any],
    *,
    manifest_name: str,
    label: str,
) -> None:
    for candidate in directory.rglob("*"):
        if candidate.is_symlink():
            raise IncrementalCandidateValidationError(f"{label}_symlink_forbidden")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise IncrementalCandidateValidationError(f"{label}_files_invalid")
    expected: set[str] = set()
    for name, descriptor in files.items():
        if not isinstance(name, str) or not name:
            raise IncrementalCandidateValidationError(f"{label}_file_path_invalid")
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise IncrementalCandidateValidationError(f"{label}_file_path_unsafe")
        if not isinstance(descriptor, dict):
            raise IncrementalCandidateValidationError(
                f"{label}_file_descriptor_invalid"
            )
        path = directory.joinpath(*relative.parts)
        resolved = _safe_file(path, label=f"{label}_file")
        try:
            resolved.relative_to(directory)
        except ValueError as exc:
            raise IncrementalCandidateValidationError(
                f"{label}_file_outside_directory"
            ) from exc
        expected.add(relative.as_posix())
        size = _integer(descriptor.get("bytes"), label=f"{label}_file_bytes")
        digest = _sha(descriptor.get("sha256"), label=f"{label}_file_sha256")
        if resolved.stat().st_size != size or _sha256(resolved) != digest:
            raise IncrementalCandidateValidationError(f"{label}_file_hash_mismatch")

    actual = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file() and path.name != manifest_name
    }
    if actual != expected:
        raise IncrementalCandidateValidationError(f"{label}_file_set_mismatch")


def _validate_freeze(
    *, project_root: Path, freeze_path: Path, expected_sha256: str
) -> tuple[dict[str, Any], str, int]:
    freeze, resolved = _load_object(freeze_path, label="input_freeze")
    expected = _sha(expected_sha256, label="expected_input_freeze_sha256")
    actual = _sha256(resolved)
    _require(actual == expected, "input_freeze_sha256_mismatch")
    _require(freeze.get("schema_version") == FREEZE_SCHEMA, "input_freeze_schema_invalid")
    _, rc_generation = _rc_generation(freeze.get("freeze_id"))
    _require(freeze.get("status") == "frozen_build_input", "input_freeze_status_invalid")
    _require(
        freeze.get("evidence_grade") == "L2-local-immutable-input",
        "input_freeze_evidence_grade_invalid",
    )
    _utc(freeze.get("generated_at_utc"), label="input_freeze_generated_at")
    _utc(freeze.get("source_cutoff_utc"), label="input_freeze_source_cutoff")
    boundaries = _object(freeze.get("boundaries"), label="input_freeze_boundaries")
    _require_false_fields(boundaries, OUTPUT_BOUNDARIES.keys() - {"webhook_send"}, label="input_freeze")

    identity = _object(freeze.get("identity"), label="input_freeze_identity")
    coverage = _object(freeze.get("coverage"), label="input_freeze_coverage")
    _require(identity.get("set_id") == "discovery_only", "input_freeze_identity_set_invalid")
    _require(identity.get("monotonic_without_tombstone") is True, "input_freeze_identity_not_monotonic")
    previous = _integer(identity.get("previous_count"), label="input_freeze_previous_count")
    candidate = _integer(identity.get("candidate_count"), label="input_freeze_candidate_count", positive=True)
    added = _integer(identity.get("added_count"), label="input_freeze_added_count", positive=True)
    _require(candidate - previous == added, "input_freeze_identity_delta_mismatch")
    for field in ("previous_lf_sha256", "candidate_lf_sha256", "added_lf_sha256"):
        _sha(identity.get(field), label=f"input_freeze_{field}")
    admitted = _integer(coverage.get("admitted_post_count"), label="input_freeze_admitted_posts", positive=True)
    lineage = _integer(coverage.get("lineage_gap_count"), label="input_freeze_lineage_debt", positive=True)
    cursor = _integer(coverage.get("cursor_outstanding"), label="input_freeze_cursor_debt", positive=True)
    page = _integer(coverage.get("page_pagination_outstanding"), label="input_freeze_page_debt", positive=True)
    _require(admitted + lineage == candidate, "input_freeze_coverage_conservation_mismatch")
    _sha(coverage.get("raw_snapshot_sha256"), label="input_freeze_raw_snapshot_sha256")
    _sha(coverage.get("lineage_gap_lf_sha256"), label="input_freeze_lineage_gap_sha256")
    _integer(coverage.get("observed_comment_count"), label="input_freeze_comment_count")
    _require(cursor > 0 and page > 0 and lineage > 0, "coverage_debt_must_remain_explicit")

    artifacts = _object(freeze.get("artifacts"), label="input_freeze_artifacts")
    _require(bool(artifacts), "input_freeze_artifacts_invalid")
    for name, descriptor in artifacts.items():
        _require(isinstance(name, str), "input_freeze_artifact_invalid")
        artifact_descriptor = _object(
            descriptor, label="input_freeze_artifact_descriptor"
        )
        relative_value = _string(
            artifact_descriptor.get("repo_relative_path"),
            label="input_freeze_artifact_path",
        )
        relative = PurePosixPath(relative_value)
        _require(not relative.is_absolute() and ".." not in relative.parts, "input_freeze_artifact_path_unsafe")
        artifact_path = project_root.joinpath(*relative.parts)
        artifact = _safe_file(artifact_path, label="input_freeze_artifact")
        try:
            artifact.relative_to(project_root)
        except ValueError as exc:
            raise IncrementalCandidateValidationError(
                "input_freeze_artifact_outside_project"
            ) from exc
        _require(
            artifact.stat().st_size == _integer(artifact_descriptor.get("bytes"), label="input_freeze_artifact_bytes")
            and _sha256(artifact) == _sha(artifact_descriptor.get("sha256"), label="input_freeze_artifact_sha256"),
            "input_freeze_artifact_drift",
        )
    return freeze, actual, rc_generation


def _validate_base(
    *, base_dir: Path, receipt_path: Path, freeze: dict[str, Any]
) -> tuple[
    dict[str, Any],
    str,
    str,
    dict[str, int],
    dict[str, Any],
]:
    directory = _safe_directory(base_dir, label="base_dir")
    manifest, manifest_path = _load_object(directory / "manifest.json", label="base_manifest")
    receipt, _ = _load_object(receipt_path, label="base_validation_receipt")
    version = _dataset_version(manifest.get("dataset_version"), layer="base")
    manifest_sha = _sha256(manifest_path)
    manifest_schema = manifest.get("schema_version")
    _require(
        manifest_schema in {BASE_MANIFEST_V1, BASE_MANIFEST_V2},
        "base_schema_invalid",
    )
    _require(manifest.get("all_checks_passed") is True, "base_checks_not_passed")
    _require_all_true(manifest.get("checks"), label="base_manifest_checks")
    _require(manifest.get("production_unchanged") is True, "base_production_boundary_invalid")
    _require_false_fields(manifest, ("provider_call", "live_send"), label="base")
    analysis = _object(manifest.get("analysis"), label="base_analysis")
    _require_false_fields(analysis, ("provider_call",), label="base_analysis")
    _validate_file_manifest(directory, manifest, manifest_name="manifest.json", label="base")

    identity = freeze["identity"]
    coverage = freeze["coverage"]
    source = _object(manifest.get("source_boundaries"), label="base_source_boundaries")
    v2 = _object(
        source.get("tencent_v2_search_hydrated"), label="base_v2_source"
    )
    debt = _object(v2.get("comment_coverage_debt"), label="base_v2_debt")
    expected_debt = {
        "cursor_outstanding": coverage["cursor_outstanding"],
        "page_pagination_outstanding": coverage["page_pagination_outstanding"],
        "partial_threads": debt.get("partial_threads"),
    }
    _integer(expected_debt["partial_threads"], label="base_partial_threads", positive=True)
    _require(
        v2.get("admission_status") == "passed_with_partial_comment_coverage"
        and v2.get("target_count") == identity["candidate_count"]
        and v2.get("target_lf_sha256") == identity["candidate_lf_sha256"]
        and v2.get("admitted_posts") == coverage["admitted_post_count"]
        and v2.get("admitted_observed_comments") == coverage["observed_comment_count"]
        and v2.get("lineage_gap_count") == coverage["lineage_gap_count"]
        and v2.get("lineage_gap_lf_sha256") == coverage["lineage_gap_lf_sha256"]
        and v2.get("snapshot_sha256") == coverage["raw_snapshot_sha256"]
        and debt.get("cursor_outstanding") == coverage["cursor_outstanding"]
        and debt.get("page_pagination_outstanding") == coverage["page_pagination_outstanding"],
        "base_v2_freeze_binding_mismatch",
    )
    _require_false_fields(v2, ("provider_call", "database_write", "live_send", "production_merge"), label="base_v2")
    fusion = _object(
        manifest.get("fusion_accounting"), label="base_fusion_accounting"
    )
    _require(fusion.get("coverage_debt_is_not_zero_filled") is True, "base_debt_zero_fill_boundary_invalid")
    _require(fusion.get("v2_comment_coverage_debt") == debt, "base_debt_fusion_mismatch")
    selected_debt: dict[str, Any] = {
        "lineage_gap_count": coverage["lineage_gap_count"],
        "cursor_outstanding": coverage["cursor_outstanding"],
        "page_pagination_outstanding": coverage[
            "page_pagination_outstanding"
        ],
        "partial_threads": expected_debt["partial_threads"],
    }
    if manifest_schema == BASE_MANIFEST_V2:
        _require(
            set(source) == BASE_V2_SOURCE_KEYS,
            "base_v2_source_set_invalid",
        )
        _require(
            fusion.get("load_order") == BASE_V2_LOAD_ORDER,
            "base_v2_load_order_invalid",
        )
        hydration = _object(
            source.get("tencent_existing_post_comment_hydration"),
            label="base_v2_hydration_source",
        )
        _require(
            hydration.get("admission_status")
            == "passed_with_explicit_comment_coverage_debt"
            and hydration.get("fusion_role")
            == "existing_post_comment_delta_after_v2"
            and hydration.get("dedup_key")
            == {"posts": "post_id", "comments": "comment_id"}
            and hydration.get("precedence_policy")
            == "preceding_canonical_wins",
            "base_v2_hydration_contract_invalid",
        )
        _require_false_fields(
            hydration,
            ("provider_call", "database_write", "production_merge", "live_send"),
            label="base_v2_hydration",
        )
        _sha(
            hydration.get("snapshot_sha256"),
            label="base_v2_hydration_snapshot_sha256",
        )
        hydration_counts = {
            field: _integer(
                hydration.get(field), label=f"base_v2_hydration_{field}"
            )
            for field in (
                "input_posts",
                "input_comments",
                "overlap_posts",
                "overlap_comments",
                "net_new_posts",
                "net_new_comments",
                "materialized_comments",
                "release_candidate_comments",
                "preceding_overlap_comments",
                "preceding_body_conflicts",
            )
        }
        _require(
            hydration_counts["input_posts"] == 0
            and hydration_counts["overlap_posts"] == 0
            and hydration_counts["net_new_posts"] == 0
            and hydration_counts["input_comments"]
            == hydration_counts["overlap_comments"]
            + hydration_counts["net_new_comments"]
            and hydration_counts["materialized_comments"]
            == hydration_counts["net_new_comments"]
            and hydration_counts["release_candidate_comments"]
            == hydration_counts["net_new_comments"]
            and hydration_counts["preceding_overlap_comments"]
            <= hydration_counts["input_comments"]
            and hydration_counts["preceding_body_conflicts"] == 0,
            "base_v2_hydration_accounting_invalid",
        )
        hydration_debt = _object(
            hydration.get("comment_coverage_debt"),
            label="base_v2_hydration_debt",
        )
        _require(
            set(hydration_debt)
            == {
                "first_page_missing",
                "cursor_outstanding",
                "page_pagination_outstanding",
                "failed_reports",
                "partial_threads",
                "not_observed_threads",
                "failure_reason_counts",
            },
            "base_v2_hydration_debt_invalid",
        )
        hydration_debt_counts = {
            field: _integer(
                hydration_debt.get(field),
                label=f"base_v2_hydration_debt_{field}",
            )
            for field in BASE_V2_UNION_COUNT_FIELDS
        }
        failure_reason_counts = _object(
            hydration_debt.get("failure_reason_counts"),
            label="base_v2_hydration_failure_reason_counts",
        )
        failure_total = 0
        for reason, count in failure_reason_counts.items():
            _string(reason, label="base_v2_hydration_failure_reason")
            failure_total += _integer(
                count,
                label="base_v2_hydration_failure_reason_count",
                positive=True,
            )
        _require(
            failure_total == hydration_debt_counts["failed_reports"],
            "base_v2_hydration_failure_reason_mismatch",
        )
        _require(
            fusion.get("existing_post_hydration_coverage_debt")
            == hydration_debt,
            "base_v2_hydration_debt_fusion_mismatch",
        )

        union = _object(
            fusion.get("comment_coverage_debt_union"),
            label="base_v2_coverage_union",
        )
        _require(
            set(union)
            == set(BASE_V2_UNION_COUNT_FIELDS)
            | set(BASE_V2_UNION_SHA_FIELDS)
            | {"source_counts", "key_union_not_numeric_sum"},
            "base_v2_coverage_union_invalid",
        )
        union_counts = {
            field: _integer(
                union.get(field), label=f"base_v2_coverage_union_{field}"
            )
            for field in BASE_V2_UNION_COUNT_FIELDS
        }
        for field in BASE_V2_UNION_SHA_FIELDS:
            _sha(union.get(field), label=f"base_v2_coverage_union_{field}")
        _require(
            union.get("key_union_not_numeric_sum") is True,
            "base_v2_coverage_union_invalid",
        )
        union_source_counts = _object(
            union.get("source_counts"),
            label="base_v2_coverage_union_source_counts",
        )
        _require(
            set(union_source_counts) == {"v2", "existing_post_hydration"},
            "base_v2_coverage_union_source_counts_invalid",
        )
        union_v2 = _object(
            union_source_counts.get("v2"),
            label="base_v2_coverage_union_v2_counts",
        )
        _require(
            set(union_v2)
            == {
                "first_page_missing",
                "cursor_outstanding",
                "page_pagination_outstanding",
                "failed_reports",
            },
            "base_v2_coverage_union_v2_counts_invalid",
        )
        union_v2_counts = {
            field: _integer(
                union_v2.get(field),
                label=f"base_v2_coverage_union_v2_{field}",
            )
            for field in union_v2
        }
        _require(
            union_v2_counts["cursor_outstanding"]
            == debt["cursor_outstanding"]
            and union_v2_counts["page_pagination_outstanding"]
            == debt["page_pagination_outstanding"]
            and union_source_counts.get("existing_post_hydration")
            == hydration_debt,
            "base_v2_coverage_union_source_binding_mismatch",
        )
        source_ranges = {
            "first_page_missing": (
                union_v2_counts["first_page_missing"],
                hydration_debt_counts["first_page_missing"],
            ),
            "cursor_outstanding": (
                union_v2_counts["cursor_outstanding"],
                hydration_debt_counts["cursor_outstanding"],
            ),
            "page_pagination_outstanding": (
                union_v2_counts["page_pagination_outstanding"],
                hydration_debt_counts["page_pagination_outstanding"],
            ),
            "failed_reports": (
                union_v2_counts["failed_reports"],
                hydration_debt_counts["failed_reports"],
            ),
            "partial_threads": (
                _integer(
                    debt.get("partial_threads"), label="base_v2_partial_threads"
                ),
                hydration_debt_counts["partial_threads"],
            ),
            "not_observed_threads": (
                union_v2_counts["first_page_missing"],
                hydration_debt_counts["not_observed_threads"],
            ),
        }
        for field, components in source_ranges.items():
            _require(
                max(components) <= union_counts[field] <= sum(components),
                "base_v2_coverage_union_conservation_mismatch",
            )
        _require(
            union_counts["not_observed_threads"]
            == union_counts["first_page_missing"]
            and union["not_observed_thread_ids_lf_sha256"]
            == union["first_page_missing_lf_sha256"],
            "base_v2_coverage_union_not_observed_mismatch",
        )
        selected_debt = {
            "lineage_gap_count": coverage["lineage_gap_count"],
            **union,
        }
    counts = _object(manifest.get("canonical_counts"), label="base_counts")

    _require(receipt.get("schema_version") == "reddit_voc_site_snapshot_validation_v2", "base_receipt_schema_invalid")
    _require(receipt.get("status") == "passed_release_candidate", "base_receipt_status_invalid")
    _require(receipt.get("release_candidate") is True, "base_receipt_candidate_invalid")
    _require(receipt.get("dataset_version") == version, "base_receipt_version_mismatch")
    if manifest_schema == BASE_MANIFEST_V2:
        _require(
            _sha(
                receipt.get("manifest_sha256"),
                label="base_v2_receipt_manifest_sha256",
            )
            == manifest_sha,
            "base_v2_receipt_manifest_sha256_mismatch",
        )
    _require_all_true(receipt.get("checks"), label="base_receipt_checks")
    _require(receipt.get("production_unchanged") is True, "base_receipt_production_boundary_invalid")
    _require_false_fields(receipt, ("provider_call", "database_write", "live_send", "deploy"), label="base_receipt")
    receipt_counts = _object(receipt.get("counts"), label="base_receipt_counts")
    for field in ("posts", "stored_comments", "linked_comments", "quarantined_comments"):
        _require(receipt_counts.get(field) == counts.get(field), "base_receipt_count_mismatch")
    return manifest, version, manifest_sha, {
        "posts": _integer(counts.get("posts"), label="base_posts", positive=True),
        "stored_comments": _integer(counts.get("stored_comments"), label="base_stored_comments"),
        "linked_comments": _integer(counts.get("linked_comments"), label="base_linked_comments"),
        "quarantined_comments": _integer(counts.get("quarantined_comments"), label="base_quarantined_comments"),
        "partial_threads": selected_debt["partial_threads"],
    }, selected_debt


def _validate_analytics(
    *,
    insights_dir: Path,
    reports_dir: Path,
    receipt_path: Path,
    base_version: str,
    base_sha: str,
) -> tuple[dict[str, Any], str, str, dict[str, Any], str, str]:
    insights_root = _safe_directory(insights_dir, label="insights_dir")
    reports_root = _safe_directory(reports_dir, label="reports_dir")
    insights, insights_path = _load_object(insights_root / "manifest.json", label="insights_manifest")
    reports, reports_path = _load_object(reports_root / "manifest.json", label="reports_manifest")
    receipt, _ = _load_object(receipt_path, label="analytics_validation_receipt")
    insights_version = _dataset_version(insights.get("dataset_version"), layer="insights")
    reports_version = _dataset_version(reports.get("dataset_version"), layer="reports")
    insights_sha = _sha256(insights_path)
    reports_sha = _sha256(reports_path)
    _require(insights.get("schema_version") == "reddit_voc_insights_manifest_v1", "insights_schema_invalid")
    _require(reports.get("schema_version") == "reddit_voc_reports_manifest_v1", "reports_schema_invalid")
    _require(insights.get("status") == "passed_provisional_risk_threshold", "insights_status_invalid")
    _require(reports.get("status") == "passed_provisional_risk_threshold", "reports_status_invalid")
    _require(
        insights.get("base_dataset_version") == base_version
        and insights.get("base_manifest_sha256") == base_sha,
        "insights_base_lineage_mismatch",
    )
    _require(
        reports.get("base_dataset_version") == base_version
        and reports.get("base_manifest_sha256") == base_sha
        and reports.get("insights_dataset_version") == insights_version
        and reports.get("insights_manifest_sha256") == insights_sha,
        "reports_lineage_mismatch",
    )
    _require(reports.get("report_count") == 6, "reports_six_state_contract_invalid")
    _validate_file_manifest(insights_root, insights, manifest_name="manifest.json", label="insights")
    _validate_file_manifest(reports_root, reports, manifest_name="manifest.json", label="reports")
    for label, manifest in (("insights", insights), ("reports", reports)):
        boundaries = _object(
            manifest.get("boundaries"), label=f"{label}_boundaries"
        )
        fields = ["provider_call", "database_write", "live_send", "deploy", "independent_human_review"]
        if label == "reports":
            fields.extend(("webhook_send", "schedule_change"))
        _require_false_fields(boundaries, fields, label=label)
        _require(boundaries.get("production_unchanged") is True, f"{label}_production_boundary_invalid")

    _require(receipt.get("schema_version") == ANALYTICS_RECEIPT_SCHEMA, "analytics_receipt_schema_invalid")
    _require(receipt.get("status") == "passed_release_candidate", "analytics_receipt_status_invalid")
    _require(receipt.get("release_candidate") is True, "analytics_receipt_candidate_invalid")
    _require_all_true(receipt.get("checks"), label="analytics_receipt_checks")
    _require(
        receipt.get("base_dataset_version") == base_version
        and receipt.get("insights_dataset_version") == insights_version
        and receipt.get("reports_dataset_version") == reports_version
        and receipt.get("base_manifest_sha256") == base_sha
        and receipt.get("insights_manifest_sha256") == insights_sha
        and receipt.get("reports_manifest_sha256") == reports_sha,
        "analytics_receipt_lineage_mismatch",
    )
    _require(receipt.get("production_unchanged") is True, "analytics_receipt_production_boundary_invalid")
    _require_false_fields(
        receipt,
        ("provider_call", "database_write", "live_send", "webhook_send", "deploy", "schedule_change"),
        label="analytics_receipt",
    )
    return insights, insights_version, insights_sha, reports, reports_version, reports_sha


def _validate_personas(
    *,
    personas_dir: Path,
    receipt_path: Path,
    base_version: str,
    base_sha: str,
    insights_version: str,
    insights_sha: str,
) -> tuple[dict[str, Any], str, str]:
    directory = _safe_directory(personas_dir, label="personas_dir")
    manifest, manifest_path = _load_object(directory / "manifest.json", label="personas_manifest")
    receipt, _ = _load_object(receipt_path, label="personas_validation_receipt")
    version = _dataset_version(manifest.get("dataset_version"), layer="personas")
    manifest_sha = _sha256(manifest_path)
    _require(manifest.get("schema_version") == "reddit_voc_personas_manifest_v1", "personas_schema_invalid")
    _require(
        manifest.get("base_dataset_version") == base_version
        and manifest.get("base_manifest_sha256") == base_sha
        and manifest.get("insights_dataset_version") == insights_version
        and manifest.get("insights_manifest_sha256") == insights_sha,
        "personas_lineage_mismatch",
    )
    _integer(manifest.get("persona_count"), label="personas_count", positive=True)
    _integer(manifest.get("assignment_count"), label="personas_assignment_count", positive=True)
    _validate_file_manifest(directory, manifest, manifest_name="manifest.json", label="personas")
    boundaries = _object(manifest.get("boundaries"), label="personas_boundaries")
    _require_false_fields(
        boundaries,
        ("provider_call", "database_write", "live_send", "webhook_send", "deploy", "schedule_change", "independent_human_review"),
        label="personas",
    )
    _require(boundaries.get("production_unchanged") is True, "personas_production_boundary_invalid")
    _require(boundaries.get("synthetic_avatars") is True and boundaries.get("real_user_image") is False, "personas_avatar_boundary_invalid")

    _require(receipt.get("schema_version") == "reddit_voc_personas_validation_v1", "personas_receipt_schema_invalid")
    _require(receipt.get("status") == "passed", "personas_receipt_status_invalid")
    _require(receipt.get("dataset_version") == version, "personas_receipt_version_mismatch")
    _require(receipt.get("base_manifest_sha256") == base_sha, "personas_receipt_base_mismatch")
    _require(receipt.get("insights_manifest_sha256") == insights_sha, "personas_receipt_insights_mismatch")
    _require_all_true(receipt.get("checks"), label="personas_receipt_checks")
    _require(receipt.get("production_unchanged") is True, "personas_receipt_production_boundary_invalid")
    _require_false_fields(
        receipt,
        ("provider_call", "database_write", "live_send", "webhook_send", "deploy", "independent_human_review"),
        label="personas_receipt",
    )
    return manifest, version, manifest_sha


def _public_manifest_path(root: Path, value: object, *, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise IncrementalCandidateValidationError(f"{label}_path_invalid")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise IncrementalCandidateValidationError(f"{label}_path_unsafe")
    path = _safe_file(root.joinpath(*relative.parts), label=label)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise IncrementalCandidateValidationError(f"{label}_outside_public_root") from exc
    return path


def _validate_public_bundle(
    *,
    public_root: Path,
    lineage: dict[str, tuple[dict[str, Any], str, str]],
) -> tuple[str, str, dict[str, int]]:
    root = _safe_directory(public_root, label="public_root")
    pointer_path = root / "data/reddit-voc/current-release.json"
    pointer, pointer_resolved = _load_object(pointer_path, label="current_release")
    _require(pointer.get("schema_version") == "reddit_voc_current_release_v1", "current_release_schema_invalid")
    release_id = _string(pointer.get("release_id"), label="current_release_id")
    _require(
        isinstance(release_id, str)
        and release_id.startswith("reddit_voc_release_")
        and VERSION_RE.fullmatch(release_id) is not None,
        "current_release_id_invalid",
    )
    _utc(pointer.get("generated_at_utc"), label="current_release_generated_at")
    pointer_boundaries = _object(
        pointer.get("boundaries"), label="current_release_boundaries"
    )
    _require(
        isinstance(pointer_boundaries, dict)
        and pointer_boundaries.get("case_gallery_stock_preserved") is True
        and pointer_boundaries.get("collector_isolation_required") is True
        and pointer_boundaries.get("login_required") is False,
        "current_release_boundaries_invalid",
    )
    datasets = _object(pointer.get("datasets"), label="current_release_datasets")
    _require(set(datasets) == set(lineage), "current_release_datasets_invalid")
    for layer, (private_manifest, version, private_sha) in lineage.items():
        binding = _object(
            datasets.get(layer), label=f"current_release_{layer}_binding"
        )
        expected_manifest_path = {
            "base": f"data/reddit-voc/{version}/manifest-public.json",
            "insights": f"data/reddit-voc/{version}/public/manifest.json",
            "reports": f"data/reddit-voc/{version}/public/manifest.json",
            "personas": f"data/reddit-voc/{version}/manifest.json",
        }[layer]
        _require(
            binding.get("manifest_path") == expected_manifest_path,
            f"public_{layer}_manifest_path_mismatch",
        )
        public_path = _public_manifest_path(root, binding.get("manifest_path"), label=f"public_{layer}_manifest")
        public_manifest, _ = _load_object(public_path, label=f"public_{layer}_manifest")
        _require(
            binding.get("dataset_version") == version
            and binding.get("lineage_manifest_sha256") == private_sha
            and binding.get("public_manifest_sha256") == _sha256(public_path)
            and public_manifest.get("dataset_version") == version,
            f"public_{layer}_pointer_binding_mismatch",
        )
        for field in (
            "base_dataset_version",
            "base_manifest_sha256",
            "insights_dataset_version",
            "insights_manifest_sha256",
        ):
            if field in private_manifest:
                _require(
                    public_manifest.get(field) == private_manifest.get(field),
                    f"public_{layer}_lineage_projection_mismatch",
                )
        manifest_name = public_path.name
        _validate_file_manifest(
            public_path.parent,
            public_manifest,
            manifest_name=manifest_name,
            label=f"public_{layer}",
        )
        if layer == "base":
            _require(public_manifest.get("production_unchanged") is True, "public_base_production_boundary_invalid")
            _require_false_fields(public_manifest, ("provider_call", "live_send"), label="public_base")
        else:
            boundaries = _object(
                public_manifest.get("boundaries"),
                label=f"public_{layer}_boundaries",
            )
            fields = ["provider_call", "database_write", "live_send", "deploy", "independent_human_review"]
            if layer in {"reports", "personas"}:
                fields.extend(("webhook_send", "schedule_change"))
            _require_false_fields(boundaries, fields, label=f"public_{layer}")
            _require(boundaries.get("production_unchanged") is True, f"public_{layer}_production_boundary_invalid")

    cases = _object(pointer.get("cases"), label="current_release_cases")
    _require(
        cases.get("manifest_path") == "data/cases/manifest.v1.json"
        and cases.get("index_path") == "data/cases/case-index.v1.json",
        "cases_public_path_mismatch",
    )
    cases_manifest_path = _public_manifest_path(root, cases.get("manifest_path"), label="cases_manifest")
    cases_index_path = _public_manifest_path(root, cases.get("index_path"), label="cases_index")
    cases_manifest, _ = _load_object(cases_manifest_path, label="cases_manifest")
    cases_index, _ = _load_object(cases_index_path, label="cases_index")
    _require(
        cases.get("public_manifest_sha256") == _sha256(cases_manifest_path)
        and cases.get("index_sha256") == _sha256(cases_index_path)
        and cases.get("stock_content_preserved") is True,
        "cases_pointer_hash_mismatch",
    )
    for field, expected in CASE_STOCK.items():
        _require(cases_manifest.get(field) == expected, f"cases_{field}_stock_changed")
    approved = _object(cases_manifest.get("approvedDelta"), label="cases_delta")
    approved_rows = _list(cases_index.get("approvedDelta"), label="cases_delta_rows")
    index_binding = _object(cases_manifest.get("index"), label="cases_index_binding")
    _require(
        cases_manifest.get("datasetVersion") == cases_index.get("datasetVersion") == cases.get("dataset_version")
        and approved.get("count") == len(approved_rows) == cases.get("approved_delta_count")
        and approved.get("contentSha256") == _compact_sha(approved_rows)
        and index_binding.get("path") == "/data/cases/case-index.v1.json"
        and index_binding.get("sha256") == _sha256(cases_index_path),
        "cases_delta_or_index_binding_mismatch",
    )
    return release_id, _sha256(pointer_resolved), {
        "seed": CASE_STOCK["seed"]["count"],
        "legacy_unverified": CASE_STOCK["legacyUnverified"]["count"],
        "approved_delta": len(approved_rows),
    }


def _exact_keys(value: dict[str, Any], expected: Iterable[str], *, label: str) -> None:
    if set(value) != set(expected):
        raise IncrementalCandidateValidationError(f"{label}_field_contract_mismatch")


def _tree_inventory(root: Path, *, label: str) -> dict[str, dict[str, int | str]]:
    directory = _safe_directory(root, label=label)
    inventory: dict[str, dict[str, int | str]] = {}
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise IncrementalCandidateValidationError(f"{label}_symlink_forbidden")
        if path.is_dir():
            continue
        if not path.is_file():
            raise IncrementalCandidateValidationError(f"{label}_special_file_forbidden")
        relative = path.relative_to(directory).as_posix()
        inventory[relative] = {
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
    return dict(sorted(inventory.items()))


def _metadata_descriptors(
    value: object, *, label: str
) -> list[dict[str, int | str]]:
    rows = _list(value, label=label)
    normalized: list[dict[str, int | str]] = []
    seen: set[str] = set()
    for item in rows:
        descriptor = _object(item, label=f"{label}_descriptor")
        _exact_keys(
            descriptor, ("path", "bytes", "sha256"), label=f"{label}_descriptor"
        )
        path_value = _string(descriptor.get("path"), label=f"{label}_path")
        relative = PurePosixPath(path_value)
        _require(
            not relative.is_absolute()
            and ".." not in relative.parts
            and path_value == relative.as_posix()
            and path_value not in seen,
            f"{label}_path_unsafe_or_duplicate",
        )
        seen.add(path_value)
        normalized.append(
            {
                "path": path_value,
                "bytes": _integer(
                    descriptor.get("bytes"), label=f"{label}_bytes"
                ),
                "sha256": _sha(
                    descriptor.get("sha256"), label=f"{label}_sha256"
                ),
            }
        )
    return normalized


def _metadata_source_path(project_root: Path, relative: str) -> Path:
    ui_root = project_root / "ref/UI/momcozy-reddit-workbench"
    if relative == "package-lock.json":
        return ui_root / relative
    if relative.startswith("deploy/insights/"):
        return ui_root.joinpath(*PurePosixPath(relative).parts)
    return project_root.joinpath(*PurePosixPath(relative).parts)


def _validate_metadata_source_descriptors(
    *,
    project_root: Path,
    descriptors: list[dict[str, int | str]],
    expected_paths: tuple[str, ...],
    label: str,
) -> None:
    actual_paths = tuple(str(row["path"]) for row in descriptors)
    _require(actual_paths == expected_paths, f"{label}_path_contract_mismatch")
    for row in descriptors:
        source = _safe_file(
            _metadata_source_path(project_root, str(row["path"])),
            label=f"{label}_source",
        )
        _require(
            source.stat().st_size == row["bytes"]
            and _sha256(source) == row["sha256"],
            f"{label}_source_drift",
        )


def _release_content_sha256(
    *,
    metadata: dict[str, Any],
    files: list[dict[str, int | str]],
    deployment_inputs: list[dict[str, int | str]],
    build_inputs: list[dict[str, int | str]],
    dataset_versions: dict[str, str],
    dataset_manifests: dict[str, dict[str, str]],
    current_release: dict[str, str],
) -> str:
    toolchain = _object(metadata.get("toolchain"), label="release_metadata_toolchain")
    _exact_keys(toolchain, ("node", "npm"), label="release_metadata_toolchain")
    node = _string(toolchain.get("node"), label="release_metadata_node")
    npm = _string(toolchain.get("npm"), label="release_metadata_npm")
    descriptor = {
        "build_contract_version": metadata["build_contract_version"],
        "target_platform": metadata["target_platform"],
        "nginx_base_image": metadata["nginx_base_image"],
        "files": files,
        "deployment_inputs": deployment_inputs,
        "build_inputs": build_inputs,
        "toolchain": {"node": node, "npm": npm},
        "dataset_versions": {
            layer: dataset_versions[layer] for layer in DATASET_LAYERS
        },
        "dataset_manifests": {
            layer: {
                "manifest_path": dataset_manifests[layer]["manifest_path"],
                "public_manifest_sha256": dataset_manifests[layer][
                    "public_manifest_sha256"
                ],
                "lineage_manifest_sha256": dataset_manifests[layer][
                    "lineage_manifest_sha256"
                ],
            }
            for layer in DATASET_LAYERS
        },
        "current_release": {
            "path": current_release["path"],
            "release_id": current_release["release_id"],
            "sha256": current_release["sha256"],
        },
        "collection_status": {
            "latest_collection_integrated": True,
            "latest_collection_fully_hydrated": False,
        },
    }
    return sha256(
        json.dumps(
            descriptor,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _validate_frontend_release(
    *,
    project_root: Path,
    frontend_dist: Path,
    release_metadata_manifest_path: Path,
    public_root: Path,
    release_id: str,
    pointer_sha256: str,
    lineage: dict[str, tuple[dict[str, Any], str, str]],
) -> dict[str, int | str | bool]:
    dist_root = _safe_directory(frontend_dist, label="frontend_dist")
    public = _safe_directory(public_root, label="public_root_for_frontend")
    dist_data = _tree_inventory(dist_root / "data", label="frontend_dist_data")
    public_data = _tree_inventory(public / "data", label="public_root_data")
    _require(dist_data == public_data, "frontend_data_public_mismatch")

    dist_inventory = _tree_inventory(dist_root, label="frontend_dist")
    metadata, metadata_path = _load_object(
        release_metadata_manifest_path, label="release_metadata_manifest"
    )
    _exact_keys(metadata, RELEASE_METADATA_KEYS, label="release_metadata")
    _require(
        metadata.get("schema_version") == "reddit_voc_insights_site_release_v2"
        and metadata.get("delivery_mode") == "immutable_static_container"
        and metadata.get("public_access") is True
        and metadata.get("authentication_enabled") is False
        and metadata.get("target_platform") == "linux/amd64"
        and metadata.get("build_contract_version")
        == "reddit_voc_insights_container_v4",
        "release_metadata_identity_or_access_contract_invalid",
    )
    _utc(metadata.get("generated_at_utc"), label="release_metadata_generated_at")
    image = _string(
        metadata.get("nginx_base_image"), label="release_metadata_nginx_base_image"
    )
    _require(
        re.fullmatch(r"[^\s@]+@sha256:[0-9a-f]{64}", image) is not None,
        "release_metadata_base_image_not_digest_pinned",
    )
    _require(
        metadata.get("latest_collection_integrated") is True
        and metadata.get("latest_collection_fully_hydrated") is False,
        "release_metadata_collection_status_invalid",
    )
    boundaries = _object(
        metadata.get("boundaries"), label="release_metadata_boundaries"
    )
    _require(
        boundaries == RELEASE_METADATA_BOUNDARIES,
        "release_metadata_boundaries_invalid",
    )

    file_rows = _metadata_descriptors(metadata.get("files"), label="release_files")
    file_map = {
        str(row["path"]): {
            "bytes": row["bytes"],
            "sha256": row["sha256"],
        }
        for row in file_rows
    }
    _require(
        metadata.get("file_count") == len(file_rows)
        and file_map == dist_inventory,
        "release_metadata_dist_inventory_mismatch",
    )
    deployment_inputs = _metadata_descriptors(
        metadata.get("deployment_inputs"), label="release_deployment_inputs"
    )
    build_inputs = _metadata_descriptors(
        metadata.get("build_inputs"), label="release_build_inputs"
    )
    _validate_metadata_source_descriptors(
        project_root=project_root,
        descriptors=deployment_inputs,
        expected_paths=DEPLOYMENT_INPUT_PATHS,
        label="release_deployment_inputs",
    )
    _validate_metadata_source_descriptors(
        project_root=project_root,
        descriptors=build_inputs,
        expected_paths=BUILD_INPUT_PATHS,
        label="release_build_inputs",
    )

    pointer, pointer_path = _load_object(
        public / "data/reddit-voc/current-release.json",
        label="frontend_release_pointer",
    )
    _require(
        _sha256(pointer_path) == pointer_sha256
        and pointer.get("release_id") == release_id,
        "frontend_release_pointer_drift",
    )
    pointer_datasets = _object(
        pointer.get("datasets"), label="frontend_release_pointer_datasets"
    )
    metadata_versions_raw = _object(
        metadata.get("dataset_versions"), label="release_metadata_dataset_versions"
    )
    _exact_keys(
        metadata_versions_raw, DATASET_LAYERS, label="release_metadata_dataset_versions"
    )
    metadata_versions: dict[str, str] = {}
    expected_versions: dict[str, str] = {}
    for layer in DATASET_LAYERS:
        binding = _object(
            pointer_datasets.get(layer), label=f"release_pointer_{layer}_binding"
        )
        expected_versions[layer] = lineage[layer][1]
        metadata_versions[layer] = _string(
            metadata_versions_raw.get(layer),
            label=f"release_metadata_{layer}_version",
        )
        _require(
            metadata_versions[layer]
            == expected_versions[layer]
            == binding.get("dataset_version"),
            f"release_metadata_{layer}_version_mismatch",
        )

    manifests_raw = _object(
        metadata.get("dataset_manifests"),
        label="release_metadata_dataset_manifests",
    )
    _exact_keys(
        manifests_raw, DATASET_LAYERS, label="release_metadata_dataset_manifests"
    )
    metadata_manifests: dict[str, dict[str, str]] = {}
    for layer in DATASET_LAYERS:
        row = _object(
            manifests_raw.get(layer),
            label=f"release_metadata_{layer}_manifest",
        )
        _exact_keys(
            row,
            ("manifest_path", "public_manifest_sha256", "lineage_manifest_sha256"),
            label=f"release_metadata_{layer}_manifest",
        )
        binding = _object(
            pointer_datasets.get(layer), label=f"release_pointer_{layer}_binding"
        )
        normalized = {
            "manifest_path": _string(
                row.get("manifest_path"),
                label=f"release_metadata_{layer}_manifest_path",
            ),
            "public_manifest_sha256": _sha(
                row.get("public_manifest_sha256"),
                label=f"release_metadata_{layer}_public_manifest_sha256",
            ),
            "lineage_manifest_sha256": _sha(
                row.get("lineage_manifest_sha256"),
                label=f"release_metadata_{layer}_lineage_manifest_sha256",
            ),
        }
        _require(
            normalized
            == {
                "manifest_path": binding.get("manifest_path"),
                "public_manifest_sha256": binding.get("public_manifest_sha256"),
                "lineage_manifest_sha256": binding.get("lineage_manifest_sha256"),
            },
            f"release_metadata_{layer}_manifest_binding_mismatch",
        )
        metadata_manifests[layer] = normalized

    current = _object(
        metadata.get("current_release"), label="release_metadata_current_release"
    )
    _exact_keys(
        current,
        ("path", "release_id", "sha256"),
        label="release_metadata_current_release",
    )
    normalized_current = {
        "path": _string(current.get("path"), label="release_metadata_current_path"),
        "release_id": _string(
            current.get("release_id"), label="release_metadata_current_id"
        ),
        "sha256": _sha(
            current.get("sha256"), label="release_metadata_current_sha256"
        ),
    }
    _require(
        normalized_current
        == {
            "path": "data/reddit-voc/current-release.json",
            "release_id": release_id,
            "sha256": pointer_sha256,
        },
        "release_metadata_current_release_mismatch",
    )
    expected_release_sha = _release_content_sha256(
        metadata=metadata,
        files=file_rows,
        deployment_inputs=deployment_inputs,
        build_inputs=build_inputs,
        dataset_versions=metadata_versions,
        dataset_manifests=metadata_manifests,
        current_release=normalized_current,
    )
    release_sha = _sha(
        metadata.get("release_sha256"), label="release_metadata_release_sha256"
    )
    _require(release_sha == expected_release_sha, "release_metadata_release_sha256_mismatch")
    return {
        "release_metadata_manifest_sha256": _sha256(metadata_path),
        "release_sha256": release_sha,
        "dist_file_count": len(dist_inventory),
        "data_file_count": len(dist_data),
        "latest_collection_integrated": True,
        "latest_collection_fully_hydrated": False,
        "container_build_completed_claim_supported": False,
        "deploy_completed_claim_supported": False,
        "browser_e2e_evaluated": False,
    }


def validate_candidate(
    *,
    project_root: Path,
    input_freeze_path: Path,
    expected_input_freeze_sha256: str,
    base_dir: Path,
    base_validation_receipt_path: Path,
    insights_dir: Path,
    reports_dir: Path,
    analytics_validation_receipt_path: Path,
    personas_dir: Path,
    personas_validation_receipt_path: Path,
    public_root: Path,
    frontend_dist: Path,
    release_metadata_manifest_path: Path,
    validated_at_utc: str,
) -> dict[str, Any]:
    root = _safe_directory(project_root, label="project_root")
    validated_at = _utc(validated_at_utc, label="validated_at_utc")
    freeze, freeze_sha, rc_generation = _validate_freeze(
        project_root=root,
        freeze_path=input_freeze_path,
        expected_sha256=expected_input_freeze_sha256,
    )
    base, base_version, base_sha, base_counts, base_coverage_debt = _validate_base(
        base_dir=base_dir,
        receipt_path=base_validation_receipt_path,
        freeze=freeze,
    )
    insights, insights_version, insights_sha, reports, reports_version, reports_sha = _validate_analytics(
        insights_dir=insights_dir,
        reports_dir=reports_dir,
        receipt_path=analytics_validation_receipt_path,
        base_version=base_version,
        base_sha=base_sha,
    )
    personas, personas_version, personas_sha = _validate_personas(
        personas_dir=personas_dir,
        receipt_path=personas_validation_receipt_path,
        base_version=base_version,
        base_sha=base_sha,
        insights_version=insights_version,
        insights_sha=insights_sha,
    )
    release_id, pointer_sha, case_counts = _validate_public_bundle(
        public_root=public_root,
        lineage={
            "base": (base, base_version, base_sha),
            "insights": (insights, insights_version, insights_sha),
            "reports": (reports, reports_version, reports_sha),
            "personas": (personas, personas_version, personas_sha),
        },
    )
    frontend = _validate_frontend_release(
        project_root=root,
        frontend_dist=frontend_dist,
        release_metadata_manifest_path=release_metadata_manifest_path,
        public_root=public_root,
        release_id=release_id,
        pointer_sha256=pointer_sha,
        lineage={
            "base": (base, base_version, base_sha),
            "insights": (insights, insights_version, insights_sha),
            "reports": (reports, reports_version, reports_sha),
            "personas": (personas, personas_version, personas_sha),
        },
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": SUCCESS_STATUS,
        "evidence_grade": "L2-fixture-or-dry-run",
        "validated_at_utc": validated_at,
        "release_candidate": True,
        "hydration_status": "partial_with_explicit_debt",
        "completion_claim_supported": False,
        "input_freeze": {
            "freeze_id": freeze["freeze_id"],
            "rc_generation": rc_generation,
            "sha256": freeze_sha,
            "source_cutoff_utc": freeze["source_cutoff_utc"],
        },
        "release": {
            "release_id": release_id,
            "current_release_sha256": pointer_sha,
        },
        "datasets": {
            "base": {"dataset_version": base_version, "manifest_sha256": base_sha},
            "insights": {"dataset_version": insights_version, "manifest_sha256": insights_sha},
            "reports": {"dataset_version": reports_version, "manifest_sha256": reports_sha},
            "personas": {"dataset_version": personas_version, "manifest_sha256": personas_sha},
        },
        "counts": base_counts,
        "coverage_debt": base_coverage_debt,
        "cases": case_counts,
        "frontend": frontend,
        "checks": {
            "immutable_rc_generation_input_freeze_and_artifacts": True,
            "base_manifest_and_independent_receipt": True,
            "analytics_manifests_and_independent_receipt": True,
            "personas_manifest_and_independent_receipt": True,
            "public_pointer_and_four_manifest_bindings": True,
            "frontend_dist_data_exactly_matches_public_bundle": True,
            "release_metadata_binds_dist_pointer_and_partial_collection": True,
            "case_gallery_stock_38_plus_12_preserved": True,
            "partial_hydration_debt_explicit_and_nonzero": True,
            "side_effect_boundaries_false": True,
        },
        "boundaries": dict(OUTPUT_BOUNDARIES),
    }


def write_immutable_receipt(path: Path, value: dict[str, Any]) -> str:
    payload = _canonical_bytes(value)
    if path.is_symlink():
        raise IncrementalCandidateValidationError("receipt_path_unsafe")
    if path.exists():
        resolved = _safe_file(path, label="receipt")
        if resolved.read_bytes() == payload:
            if resolved.stat().st_mode & 0o777 != 0o600:
                raise IncrementalCandidateValidationError(
                    "receipt_existing_mode_invalid"
                )
            return "no_change"
        raise IncrementalCandidateValidationError("receipt_immutable_collision")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise IncrementalCandidateValidationError("receipt_parent_unsafe")
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = None
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise IncrementalCandidateValidationError("receipt_atomic_write_failed") from exc
    return "created"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--input-freeze", type=Path, required=True)
    parser.add_argument("--expected-input-freeze-sha256", required=True)
    parser.add_argument("--base-dir", type=Path, required=True)
    parser.add_argument("--base-validation-receipt", type=Path, required=True)
    parser.add_argument("--insights-dir", type=Path, required=True)
    parser.add_argument("--reports-dir", type=Path, required=True)
    parser.add_argument("--analytics-validation-receipt", type=Path, required=True)
    parser.add_argument("--personas-dir", type=Path, required=True)
    parser.add_argument("--personas-validation-receipt", type=Path, required=True)
    parser.add_argument("--public-root", type=Path, required=True)
    parser.add_argument("--frontend-dist", type=Path, required=True)
    parser.add_argument("--release-metadata-manifest", type=Path, required=True)
    parser.add_argument("--validated-at-utc", required=True)
    parser.add_argument("--receipt", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        value = validate_candidate(
            project_root=args.project_root,
            input_freeze_path=args.input_freeze,
            expected_input_freeze_sha256=args.expected_input_freeze_sha256,
            base_dir=args.base_dir,
            base_validation_receipt_path=args.base_validation_receipt,
            insights_dir=args.insights_dir,
            reports_dir=args.reports_dir,
            analytics_validation_receipt_path=args.analytics_validation_receipt,
            personas_dir=args.personas_dir,
            personas_validation_receipt_path=args.personas_validation_receipt,
            public_root=args.public_root,
            frontend_dist=args.frontend_dist,
            release_metadata_manifest_path=args.release_metadata_manifest,
            validated_at_utc=args.validated_at_utc,
        )
        result = "not_requested"
        if args.receipt is not None:
            result = write_immutable_receipt(args.receipt, value)
        print(
            json.dumps(
                {
                    "status": SUCCESS_STATUS,
                    "receipt": result,
                    "release_id": value["release"]["release_id"],
                    "hydration_status": value["hydration_status"],
                },
                sort_keys=True,
            )
        )
        return 0
    except IncrementalCandidateValidationError as exc:
        print(
            json.dumps(
                {"status": FAIL_STATUS, "error": str(exc)}, sort_keys=True
            ),
            file=sys.stderr,
        )
        return 1
    except Exception:
        print(
            json.dumps(
                {"status": FAIL_STATUS, "error": "unexpected_validation_failure"},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
