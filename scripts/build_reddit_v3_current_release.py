#!/usr/bin/env python3
"""Build a frontend current-release pointer from one validated Reddit VOC V3 snapshot.

This command is local-only.  It reads an already staged public tree and four
independent validation receipts; it neither copies data nor changes production.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping


CURRENT_RELEASE_SCHEMA = "reddit_voc_current_release_v1"
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,127}$")
VERSION_PREFIXES = {
    "base": "reddit_voc_site_snapshot_",
    "insights": "reddit_voc_insights_",
    "reports": "reddit_voc_reports_",
    "personas": "reddit_voc_personas_",
}
MANIFEST_SCHEMAS = {
    "base": "reddit_voc_site_snapshot_manifest_v3",
    "insights": "reddit_voc_insights_public_manifest_v3",
    "reports": "reddit_voc_reports_public_manifest_v3",
    "personas": "reddit_voc_personas_manifest_v3",
}
RECEIPT_SCHEMAS = {
    "base": "reddit_voc_base_public_validation_receipt_v1",
    "insights": "reddit_voc_insights_public_validation_receipt_v3",
    "reports": "reddit_voc_reports_public_validation_receipt_v3",
    "personas": "reddit_voc_personas_validation_v3",
}
STATIC_FALSE_BOUNDARIES = (
    "provider_call",
    "database_write",
    "remote_write",
    "live_send",
    "deploy",
)
BASE_PUBLIC_FILES = {
    "aggregates-public.json",
    "posts-public.json",
    "comments-public.json",
    "tag-dictionary-public.json",
}
INSIGHTS_PUBLIC_FILES = {"insights.json", "validation-receipt.json"}
REPORTS_PUBLIC_FILES = {
    "business-history-index.json",
    "report-index.json",
    "validation-receipt.json",
    "current/daily.json",
    "current/weekly.json",
    "current/monthly.json",
    "archive/daily.json",
    "archive/weekly.json",
    "archive/monthly.json",
}
PERSONAS_PUBLIC_FILES = {
    "personas.json",
    "persona-tags.json",
    "persona-atomic-catalog.json",
    "persona-atomic-facts.jsonl",
    "persona-cohort-bridge.json",
    "assets/persona-competitor-comparer.svg",
    "assets/persona-explicit-advocate.svg",
    "assets/persona-fallback-neutral.svg",
    "assets/persona-fit-output-optimizer.svg",
    "assets/persona-operations-troubleshooter.svg",
    "assets/persona-product-evaluator.svg",
    "assets/persona-purchase-decision.svg",
    "assets/persona-service-support-seeker.svg",
    "assets/persona-work-scenario.svg",
}
EXPECTED_PUBLIC_FILES = {
    "base": BASE_PUBLIC_FILES,
    "insights": INSIGHTS_PUBLIC_FILES,
    "reports": REPORTS_PUBLIC_FILES,
    "personas": PERSONAS_PUBLIC_FILES,
}


class V3CurrentReleaseContractError(ValueError):
    """A staged V3 artifact does not satisfy the immutable release contract."""


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink():
        raise V3CurrentReleaseContractError(f"{label}_unsafe")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise V3CurrentReleaseContractError(f"{label}_missing") from exc
    if not resolved.is_file():
        raise V3CurrentReleaseContractError(f"{label}_unsafe")
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise V3CurrentReleaseContractError(f"{label}_invalid_json") from exc
    if not isinstance(value, dict):
        raise V3CurrentReleaseContractError(f"{label}_not_object")
    return value


def _require_sha(value: object, *, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise V3CurrentReleaseContractError(f"{label}_invalid")
    return value


def _require_version(value: object, *, key: str) -> str:
    prefix = VERSION_PREFIXES[key]
    if (
        not isinstance(value, str)
        or not value.startswith(prefix)
        or SAFE_ID_RE.fullmatch(value) is None
    ):
        raise V3CurrentReleaseContractError(f"{key}_dataset_version_invalid")
    return value


def _utc(value: str) -> str:
    candidate = value.strip().replace("Z", "+00:00") if isinstance(value, str) else ""
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise V3CurrentReleaseContractError("generated_at_utc_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise V3CurrentReleaseContractError("generated_at_utc_not_utc")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_relative(value: str, *, label: str) -> PurePosixPath:
    relative = PurePosixPath(value)
    if not value or relative.is_absolute() or ".." in relative.parts:
        raise V3CurrentReleaseContractError(f"{label}_unsafe")
    return relative


def _manifest_relative(key: str, version: str) -> PurePosixPath:
    base = PurePosixPath("data", "reddit-voc", version)
    if key == "base":
        return base / "manifest-public.json"
    if key in {"insights", "reports"}:
        return base / "public" / "manifest.json"
    return base / "manifest.json"


def _validate_safe_boundaries(
    artifact: Mapping[str, Any],
    *,
    key: str,
    nested: bool = True,
) -> None:
    boundaries = artifact.get("boundaries") if nested else artifact
    if not isinstance(boundaries, dict):
        raise V3CurrentReleaseContractError(f"{key}_boundaries_missing")
    if boundaries.get("production_unchanged") is not True:
        raise V3CurrentReleaseContractError(f"{key}_production_boundary_invalid")
    for field in STATIC_FALSE_BOUNDARIES:
        if boundaries.get(field) is not False:
            raise V3CurrentReleaseContractError(f"{key}_{field}_boundary_invalid")


def _validate_declared_files(manifest: Mapping[str, Any], *, directory: Path, key: str) -> None:
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise V3CurrentReleaseContractError(f"{key}_files_missing")
    expected_files = set(EXPECTED_PUBLIC_FILES[key])
    if key == "reports":
        comparison_contract_proven = manifest.get(
            "comparison_contract_proven"
        )
        if type(comparison_contract_proven) is not bool:
            raise V3CurrentReleaseContractError(
                "reports_comparison_contract_state_invalid"
            )
        history_report_count = manifest.get("history_report_count")
        if history_report_count not in (
            {38} if comparison_contract_proven else {0, 38}
        ):
            raise V3CurrentReleaseContractError(
                "reports_history_access_state_invalid"
            )
        expected_history_counts = (
            {"daily": 14, "weekly": 12, "monthly": 12}
            if history_report_count
            else {"daily": 0, "weekly": 0, "monthly": 0}
        )
        expected_history_total = sum(expected_history_counts.values())
        history_index = _load_object(
            directory / "business-history-index.json",
            label="reports_business_history_index",
        )
        if (
            history_index.get("schema_version")
            != "reddit_voc_business_history_index_v1"
            or history_index.get("limits")
            != {"daily": 14, "weekly": 12, "monthly": 12}
            or history_index.get("history_entry_count")
            != expected_history_total
            or history_index.get("total_business_entry_count")
            != expected_history_total + 3
            or history_index.get("dataset_version") != manifest.get("dataset_version")
        ):
            raise V3CurrentReleaseContractError(
                "reports_business_history_index_invalid"
            )
        history_paths: set[str] = set()
        reports = history_index.get("reports")
        if not isinstance(reports, dict) or set(reports) != {
            "daily",
            "weekly",
            "monthly",
        }:
            raise V3CurrentReleaseContractError(
                "reports_business_history_index_invalid"
            )
        for grain, expected_count in expected_history_counts.items():
            entries = reports[grain]
            if not isinstance(entries, list) or len(entries) != expected_count:
                raise V3CurrentReleaseContractError(
                    "reports_business_history_index_invalid"
                )
            for entry in entries:
                path = entry.get("artifact_path") if isinstance(entry, dict) else None
                if (
                    not isinstance(path, str)
                    or re.fullmatch(rf"history/{grain}/[0-9_-]+\.json", path)
                    is None
                    or path in history_paths
                    or not isinstance(files.get(path), dict)
                    or files[path].get("sha256") != entry.get("artifact_sha256")
                ):
                    raise V3CurrentReleaseContractError(
                        "reports_business_history_index_invalid"
                    )
                history_paths.add(path)
        expected_files.update(history_paths)
    if set(files) != expected_files:
        raise V3CurrentReleaseContractError(f"{key}_files_contract_mismatch")
    for relative_text, integrity in files.items():
        if not isinstance(relative_text, str) or not isinstance(integrity, dict):
            raise V3CurrentReleaseContractError(f"{key}_file_contract_invalid")
        relative = _safe_relative(relative_text, label=f"{key}_file_path")
        path = directory.joinpath(*relative.parts)
        if path.is_symlink():
            raise V3CurrentReleaseContractError(f"{key}_file_unsafe")
        try:
            resolved = path.resolve(strict=True)
        except (OSError, ValueError) as exc:
            raise V3CurrentReleaseContractError(f"{key}_file_missing") from exc
        try:
            resolved.relative_to(directory.resolve(strict=True))
        except ValueError as exc:
            raise V3CurrentReleaseContractError(f"{key}_file_unsafe") from exc
        if not resolved.is_file():
            raise V3CurrentReleaseContractError(f"{key}_file_unsafe")
        declared_bytes = integrity.get("bytes")
        if not isinstance(declared_bytes, int) or declared_bytes != resolved.stat().st_size:
            raise V3CurrentReleaseContractError(f"{key}_file_bytes_mismatch")
        if _require_sha(integrity.get("sha256"), label=f"{key}_file_sha256") != _sha256(resolved):
            raise V3CurrentReleaseContractError(f"{key}_file_sha256_mismatch")


def _validate_dataset_inventory(
    manifest: Mapping[str, Any],
    *,
    directory: Path,
    key: str,
    validation_receipt: Path,
) -> None:
    if directory.is_symlink() or not directory.is_dir():
        raise V3CurrentReleaseContractError(f"{key}_directory_inventory_unsafe")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise V3CurrentReleaseContractError(f"{key}_files_missing")
    manifest_name = "manifest-public.json" if key == "base" else "manifest.json"
    expected_files = set(files) | {manifest_name}
    sidecar = directory / "public-validation-receipt.json"
    if key == "insights" or (key == "reports" and sidecar.exists()):
        try:
            receipt_bytes = validation_receipt.resolve(strict=True).read_bytes()
        except OSError as exc:
            raise V3CurrentReleaseContractError(
                f"{key}_validation_receipt_missing"
            ) from exc
        if (
            not sidecar.exists()
            or sidecar.is_symlink()
            or not sidecar.is_file()
            or sidecar.read_bytes() != receipt_bytes
        ):
            raise V3CurrentReleaseContractError(
                f"{key}_validation_sidecar_mismatch"
            )
        expected_files.add("public-validation-receipt.json")
    expected_directories = {
        parent.as_posix()
        for name in expected_files
        for parent in PurePosixPath(name).parents
        if parent != PurePosixPath(".")
    }
    if key == "reports":
        expected_directories.add("history")
    actual_files: set[str] = set()
    actual_directories: set[str] = set()
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise V3CurrentReleaseContractError(
                f"{key}_directory_inventory_unsafe"
            )
        relative = path.relative_to(directory).as_posix()
        if path.is_file():
            actual_files.add(relative)
        elif path.is_dir():
            actual_directories.add(relative)
        else:
            raise V3CurrentReleaseContractError(
                f"{key}_directory_inventory_unsafe"
            )
    if actual_files != expected_files or actual_directories - expected_directories:
        raise V3CurrentReleaseContractError(
            f"{key}_directory_inventory_mismatch"
        )


def _validate_receipt(
    receipt_path: Path,
    *,
    key: str,
    manifest: Mapping[str, Any],
    manifest_sha256: str,
) -> str:
    receipt = _load_object(receipt_path, label=f"{key}_validation_receipt")
    if receipt.get("schema_version") != RECEIPT_SCHEMAS[key]:
        raise V3CurrentReleaseContractError(f"{key}_validation_receipt_schema_invalid")
    expected_status = "passed" if key == "personas" else "passed_candidate_only"
    if receipt.get("status") != expected_status:
        raise V3CurrentReleaseContractError(f"{key}_validation_receipt_not_passed")
    if receipt.get("promotable") is not True:
        raise V3CurrentReleaseContractError(f"{key}_validation_receipt_not_promotable")
    bound = (
        receipt.get("manifest_sha256")
        if key == "personas"
        else receipt.get("bundle_manifest_sha256")
    )
    if bound != manifest_sha256:
        raise V3CurrentReleaseContractError(f"{key}_validation_receipt_manifest_mismatch")
    if key != "personas" and receipt.get("privacy_safe_projection") is not True:
        raise V3CurrentReleaseContractError(f"{key}_validation_receipt_not_privacy_safe")
    _validate_safe_boundaries(
        receipt,
        key=f"{key}_validation_receipt",
        nested=key != "personas",
    )

    if key == "base":
        inputs = manifest.get("inputs")
        if not isinstance(inputs, dict):
            raise V3CurrentReleaseContractError("base_manifest_inputs_invalid")
        if (
            receipt.get("public_manifest_sha256") != manifest_sha256
            or receipt.get("dataset_version") != manifest.get("dataset_version")
            or receipt.get("source_snapshot_id") != manifest.get("source_snapshot_id")
            or receipt.get("canonical_manifest_sha256")
            != manifest.get("lineage_manifest_sha256")
            or receipt.get("canonical_manifest_sha256")
            != inputs.get("canonical_manifest_sha256")
            or receipt.get("canonical_validation_receipt_sha256")
            != inputs.get("canonical_validation_receipt_sha256")
            or receipt.get("comparison_contract_proven")
            is not manifest.get("comparison_contract_proven")
            or receipt.get("comparison_contract_basis")
            != manifest.get("comparison_contract_basis")
            or receipt.get("completeness_percent")
            != manifest.get("completeness_percent")
            or receipt.get("coverage_attestation")
            != manifest.get("coverage_attestation")
            or receipt.get("data_owner_coverage_attestation_sha256")
            != manifest.get("data_owner_coverage_attestation_sha256")
            or receipt.get("all_checks_passed") is not True
        ):
            raise V3CurrentReleaseContractError("base_validation_receipt_lineage_invalid")
        checks = receipt.get("checks")
        if not isinstance(checks, dict) or not checks or not all(value is True for value in checks.values()):
            raise V3CurrentReleaseContractError("base_validation_receipt_checks_invalid")
    elif key in {"insights", "reports"}:
        if (
            receipt.get("lineage_manifest_sha256")
            != manifest.get("lineage_manifest_sha256")
            or receipt.get("validation_receipt_sha256")
            != manifest.get("validation_receipt_sha256")
            or receipt.get("deterministic_full_byte_replay") is not True
            or receipt.get("comparison_contract_proven")
            is not manifest.get("comparison_contract_proven")
            or receipt.get("comparison_contract_basis")
            != manifest.get("comparison_contract_basis")
            or receipt.get("completeness_percent")
            != manifest.get("completeness_percent")
            or receipt.get("data_owner_coverage_attestation_sha256")
            != manifest.get("data_owner_coverage_attestation_sha256")
            or (
                key == "reports"
                and (
                    receipt.get("report_count")
                    != manifest.get("report_count")
                    or receipt.get("history_report_count")
                    != manifest.get("history_report_count")
                    or receipt.get("business_entry_count")
                    != manifest.get("business_entry_count")
                )
            )
        ):
            raise V3CurrentReleaseContractError(f"{key}_validation_receipt_lineage_invalid")
    else:
        checks = receipt.get("checks")
        upstream = manifest.get("upstream")
        if (
            receipt.get("snapshot_id") != manifest.get("snapshot_id")
            or receipt.get("consumption_status")
            != "eligible_for_downstream_consumption"
            or not isinstance(checks, dict)
            or checks.get("deterministic_full_byte_replay") is not True
            or not isinstance(upstream, dict)
            or upstream.get("consumption_status")
            != "eligible_for_downstream_consumption"
            or upstream.get("promotable") is not True
        ):
            raise V3CurrentReleaseContractError("personas_validation_receipt_lineage_invalid")
    return _sha256(receipt_path.resolve(strict=True))


def _validate_dataset(
    *,
    public_root: Path,
    key: str,
    version: str,
    validation_receipt: Path,
) -> tuple[dict[str, Any], str, str, str]:
    relative = _manifest_relative(key, version)
    manifest_path = public_root.joinpath(*relative.parts)
    current = public_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise V3CurrentReleaseContractError(f"{key}_public_manifest_unsafe")
    try:
        manifest_path.resolve(strict=True).relative_to(public_root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise V3CurrentReleaseContractError(f"{key}_public_manifest_unsafe") from exc
    manifest = _load_object(manifest_path, label=f"{key}_public_manifest")
    actual_version = manifest.get("snapshot_id") if key == "personas" else manifest.get("dataset_version")
    if actual_version != version:
        raise V3CurrentReleaseContractError(f"{key}_public_version_mismatch")
    if manifest.get("schema_version") != MANIFEST_SCHEMAS[key]:
        raise V3CurrentReleaseContractError(f"{key}_public_schema_mismatch")
    if manifest.get("promotable") is not True:
        raise V3CurrentReleaseContractError(f"{key}_not_promotable")
    if key == "personas":
        if (
            manifest.get("status") != "candidate_built"
            or manifest.get("consumption_status") != "eligible_for_downstream_consumption"
        ):
            raise V3CurrentReleaseContractError("personas_consumption_status_invalid")
        boundaries = manifest.get("boundaries")
        if (
            not isinstance(boundaries, dict)
            or boundaries.get("counts_are_content_entities_not_users") is not True
            or boundaries.get("author_level_personas") is not False
            or boundaries.get("real_user_images") is not False
        ):
            raise V3CurrentReleaseContractError("personas_public_safety_boundary_invalid")
        source_snapshot_id = manifest.get("governed_signal_source_snapshot_id")
        lineage_sha = _sha256(manifest_path.resolve(strict=True))
    else:
        if manifest.get("status") != "validated_candidate":
            raise V3CurrentReleaseContractError(f"{key}_status_invalid")
        if manifest.get("privacy_safe_projection") is not True:
            raise V3CurrentReleaseContractError(f"{key}_not_privacy_safe")
        expected_consumption = (
            "eligible_for_current_release_candidate_binding"
            if key == "base"
            else "eligible_for_frontend_candidate_consumption"
        )
        if manifest.get("consumption_status") != expected_consumption:
            raise V3CurrentReleaseContractError(f"{key}_consumption_status_invalid")
        source_snapshot_id = manifest.get("source_snapshot_id")
        lineage_sha = _require_sha(
            manifest.get("lineage_manifest_sha256"),
            label=f"{key}_lineage_manifest_sha256",
        )
    if not isinstance(source_snapshot_id, str) or not source_snapshot_id:
        raise V3CurrentReleaseContractError(f"{key}_source_snapshot_missing")
    comparison_contract_proven: bool | None = None
    if key in {"base", "insights", "reports"}:
        comparison_contract_proven = manifest.get("comparison_contract_proven")
        if type(comparison_contract_proven) is not bool:
            raise V3CurrentReleaseContractError(
                f"{key}_comparison_contract_state_invalid"
            )
        expected_basis = (
            "owner_attested_dataset_scope_window"
            if comparison_contract_proven
            else "not_owner_attested"
        )
        expected_completeness = 100 if comparison_contract_proven else None
        if (
            manifest.get("comparison_contract_basis") != expected_basis
            or manifest.get("completeness_percent") != expected_completeness
        ):
            raise V3CurrentReleaseContractError(
                f"{key}_comparison_contract_invalid"
            )
        attestation = manifest.get("coverage_attestation")
        attestation_sha = manifest.get(
            "data_owner_coverage_attestation_sha256"
        )
        if comparison_contract_proven:
            if (
                not isinstance(attestation, dict)
                or attestation.get("attestation_basis")
                != "data_owner_declaration"
                or attestation.get("completeness_percent") != 100
                or attestation.get("evidence_class")
                != "owner_attested_not_crawler_proof"
                or attestation.get("source_snapshot_id")
                != source_snapshot_id
            ):
                raise V3CurrentReleaseContractError(
                    f"{key}_coverage_attestation_invalid"
                )
            _require_sha(
                attestation_sha,
                label=f"{key}_data_owner_coverage_attestation",
            )
        elif (
            attestation is not None
            or attestation_sha is not None
            or manifest.get("comparison_unavailable_reason_codes")
            != [
                "historical_collection_coverage_not_owner_attested_complete"
            ]
        ):
            raise V3CurrentReleaseContractError(
                f"{key}_unattested_coverage_binding_invalid"
            )
    if key == "base" and manifest.get("completeness_basis") != (
        "data_owner_declaration"
        if comparison_contract_proven
        else "not_owner_attested"
    ):
        raise V3CurrentReleaseContractError("base_completeness_basis_invalid")
    if key == "base":
        inputs = manifest.get("inputs")
        if (
            not isinstance(inputs, dict)
            or _require_sha(
                inputs.get("canonical_manifest_sha256"),
                label="base_input_canonical_manifest_sha256",
            )
            != lineage_sha
        ):
            raise V3CurrentReleaseContractError("base_manifest_inputs_invalid")
        _require_sha(
            inputs.get("canonical_validation_receipt_sha256"),
            label="base_input_canonical_validation_receipt_sha256",
        )
    if key in {"insights", "reports"}:
        if (
            manifest.get("fixture_only") is not False
            or manifest.get("independent_validation_status") != "passed"
        ):
            raise V3CurrentReleaseContractError(
                f"{key}_independent_validation_invalid"
            )
        files = manifest.get("files")
        receipt_integrity = files.get("validation-receipt.json") if isinstance(files, dict) else None
        if (
            not isinstance(receipt_integrity, dict)
            or receipt_integrity.get("sha256")
            != manifest.get("validation_receipt_sha256")
        ):
            raise V3CurrentReleaseContractError(f"{key}_embedded_receipt_binding_invalid")
    _validate_safe_boundaries(manifest, key=key)
    _validate_declared_files(manifest, directory=manifest_path.parent, key=key)
    _validate_dataset_inventory(
        manifest,
        directory=manifest_path.parent,
        key=key,
        validation_receipt=validation_receipt,
    )
    manifest_sha = _sha256(manifest_path.resolve(strict=True))
    _validate_receipt(
        validation_receipt,
        key=key,
        manifest=manifest,
        manifest_sha256=manifest_sha,
    )
    return manifest, manifest_sha, lineage_sha, source_snapshot_id


def _validate_cases(public_root: Path) -> dict[str, Any]:
    manifest_relative = PurePosixPath("data", "cases", "manifest.v1.json")
    index_relative = PurePosixPath("data", "cases", "case-index.v1.json")
    manifest_path = public_root.joinpath(*manifest_relative.parts)
    index_path = public_root.joinpath(*index_relative.parts)
    manifest = _load_object(manifest_path, label="cases_manifest")
    index = _load_object(index_path, label="cases_index")
    dataset_version = manifest.get("datasetVersion")
    if (
        not isinstance(dataset_version, str)
        or not dataset_version.startswith("case_catalog_")
        or SAFE_ID_RE.fullmatch(dataset_version) is None
        or index.get("datasetVersion") != dataset_version
    ):
        raise V3CurrentReleaseContractError("cases_dataset_version_mismatch")
    seed = manifest.get("seed")
    legacy = manifest.get("legacyUnverified")
    approved = manifest.get("approvedDelta")
    index_binding = manifest.get("index")
    approved_rows = index.get("approvedDelta")
    if (
        not isinstance(seed, dict)
        or not isinstance(legacy, dict)
        or not isinstance(approved, dict)
        or not isinstance(index_binding, dict)
    ):
        raise V3CurrentReleaseContractError("cases_manifest_contract_invalid")
    if seed.get("count") != 38 or legacy.get("count") != 12:
        raise V3CurrentReleaseContractError("cases_stock_content_changed")
    if not isinstance(approved_rows, list) or approved.get("count") != len(approved_rows):
        raise V3CurrentReleaseContractError("cases_approved_delta_mismatch")
    index_sha = _sha256(index_path.resolve(strict=True))
    if index_binding.get("path") != "/data/cases/case-index.v1.json" or index_binding.get("sha256") != index_sha:
        raise V3CurrentReleaseContractError("cases_index_binding_mismatch")
    return {
        "dataset_version": dataset_version,
        "manifest_path": manifest_relative.as_posix(),
        "public_manifest_sha256": _sha256(manifest_path.resolve(strict=True)),
        "index_path": index_relative.as_posix(),
        "index_sha256": index_sha,
        "stock_content_preserved": True,
        "approved_delta_count": len(approved_rows),
    }


def build_v3_current_release(
    *,
    public_root: Path,
    base_validation_receipt: Path,
    insights_validation_receipt: Path,
    reports_validation_receipt: Path,
    personas_validation_receipt: Path,
    release_id: str,
    generated_at_utc: str,
    versions: Mapping[str, str],
) -> dict[str, Any]:
    if not release_id.startswith("reddit_voc_release_") or SAFE_ID_RE.fullmatch(release_id) is None:
        raise V3CurrentReleaseContractError("release_id_invalid")
    generated_at = _utc(generated_at_utc)
    if public_root.is_symlink():
        raise V3CurrentReleaseContractError("public_root_unsafe")
    try:
        root = public_root.resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise V3CurrentReleaseContractError("public_root_missing") from exc
    if not root.is_dir():
        raise V3CurrentReleaseContractError("public_root_unsafe")
    if set(versions) != set(VERSION_PREFIXES):
        raise V3CurrentReleaseContractError("dataset_version_keys_invalid")

    receipts = {
        "base": base_validation_receipt,
        "insights": insights_validation_receipt,
        "reports": reports_validation_receipt,
        "personas": personas_validation_receipt,
    }
    validated: dict[str, tuple[dict[str, Any], str, str, str]] = {}
    for key in ("base", "insights", "reports", "personas"):
        version = _require_version(versions[key], key=key)
        validated[key] = _validate_dataset(
            public_root=root,
            key=key,
            version=version,
            validation_receipt=receipts[key],
        )
    source_ids = {item[3] for item in validated.values()}
    if len(source_ids) != 1:
        raise V3CurrentReleaseContractError("source_snapshot_mismatch")
    comparison_manifests = {
        key: validated[key][0] for key in ("base", "insights", "reports")
    }
    comparison_states = {
        (
            manifest.get("comparison_contract_proven"),
            manifest.get("comparison_contract_basis"),
            manifest.get("completeness_percent"),
            tuple(manifest.get("comparison_unavailable_reason_codes", [])),
        )
        for manifest in comparison_manifests.values()
    }
    attestation_shas = {
        manifest.get("data_owner_coverage_attestation_sha256")
        for manifest in comparison_manifests.values()
    }
    if len(comparison_states) != 1 or len(attestation_shas) != 1:
        raise V3CurrentReleaseContractError(
            "coordinated_coverage_contract_mismatch"
        )

    datasets = {
        key: {
            "dataset_version": versions[key],
            "manifest_path": _manifest_relative(key, versions[key]).as_posix(),
            "public_manifest_sha256": validated[key][1],
            "lineage_manifest_sha256": validated[key][2],
        }
        for key in ("base", "insights", "reports", "personas")
    }
    return {
        "schema_version": CURRENT_RELEASE_SCHEMA,
        "release_id": release_id,
        "generated_at_utc": generated_at,
        "datasets": datasets,
        "cases": _validate_cases(root),
        "boundaries": {
            "case_gallery_stock_preserved": True,
            "collector_isolation_required": True,
            "login_required": False,
        },
    }


def write_immutable_pointer(path: Path, value: Mapping[str, Any]) -> str:
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise V3CurrentReleaseContractError("pointer_destination_unsafe")
        if path.read_bytes() != payload:
            raise V3CurrentReleaseContractError("pointer_immutable_collision")
        return "no_change"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return "created"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-root", type=Path, required=True)
    parser.add_argument("--base-version", required=True)
    parser.add_argument("--insights-version", required=True)
    parser.add_argument("--reports-version", required=True)
    parser.add_argument("--personas-version", required=True)
    parser.add_argument("--base-validation-receipt", type=Path, required=True)
    parser.add_argument("--insights-validation-receipt", type=Path, required=True)
    parser.add_argument("--reports-validation-receipt", type=Path, required=True)
    parser.add_argument("--personas-validation-receipt", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--generated-at-utc", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        pointer = build_v3_current_release(
            public_root=args.public_root,
            base_validation_receipt=args.base_validation_receipt,
            insights_validation_receipt=args.insights_validation_receipt,
            reports_validation_receipt=args.reports_validation_receipt,
            personas_validation_receipt=args.personas_validation_receipt,
            release_id=args.release_id,
            generated_at_utc=args.generated_at_utc,
            versions={
                "base": args.base_version,
                "insights": args.insights_version,
                "reports": args.reports_version,
                "personas": args.personas_version,
            },
        )
        result = write_immutable_pointer(args.output, pointer)
    except V3CurrentReleaseContractError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 1
    print(
        json.dumps(
            {
                "status": "passed",
                "result": result,
                "output": str(args.output),
                "pointer_sha256": _sha256(args.output),
                "production_unchanged": True,
                "deploy": False,
                "remote_write": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
