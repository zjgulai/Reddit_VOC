#!/usr/bin/env python3
"""Build the private Plan-A candidate-data reconciliation thin layer.

This command consumes already-built and independently validated A2/A3
artifacts.  It does not rebuild Base, analytics, personas, or the public
projection.  Its only write is an immutable local closure directory whose
name is the canonical candidate-input SHA-256.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
from typing import Any, Mapping


SCHEMA_VERSION = "reddit_voc_candidate_data_reconciliation_v1"
MANIFEST_SCHEMA_VERSION = "reddit_voc_candidate_data_manifest_v1"
SOURCE_FREEZE_SCHEMA = "reddit_voc_candidate_source_freeze_v1"
LEDGER_MANIFEST_SCHEMA = "reddit_voc_candidate_ledger_manifest_v2"
LEDGER_RECEIPT_SCHEMA = "reddit_voc_candidate_ledger_validation_receipt_v1"
CONFIG_MANIFEST_SCHEMA = "reddit_voc_incremental_candidate_config_manifest_v1"
ANALYTICS_RECEIPT_SCHEMA = "reddit_voc_site_analytics_validation_v1"
PERSONAS_RECEIPT_SCHEMA = "reddit_voc_personas_validation_v1"
CODE_FREEZE_SCHEMA = "reddit_voc_data_build_code_freeze_v1"
PRODUCTION_ACCEPTANCE_SCHEMA = "reddit_voc_production_acceptance_receipt_v1"
BASE_MANIFEST_SCHEMAS = {
    "reddit_voc_site_snapshot_manifest_v1",
    "reddit_voc_site_snapshot_manifest_v2",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
LEDGER_NAMES = (
    "source-occurrence-ledger.jsonl",
    "post-identity-delta-ledger.jsonl",
    "comment-identity-delta-ledger.jsonl",
    "coverage-work-ledger.jsonl",
)
COPIED_INPUT_NAMES = ("source-freeze-manifest.json", *LEDGER_NAMES)
REQUIRED_PUBLICATION_NAMES = (
    *COPIED_INPUT_NAMES,
    "candidate-data-reconciliation-ledger.jsonl",
    "candidate-data-manifest.json",
)

# Plan A data-build code only.  The React/package-lock freeze belongs to Plan C
# and must never be smuggled into this earlier cutoff.
CODE_ALLOWLIST = (
    "scripts/build_public_site_projection.py",
    "scripts/build_reddit_candidate_data_closure.py",
    "scripts/build_reddit_candidate_ledgers.py",
    "scripts/build_reddit_personas_snapshot.py",
    "scripts/build_reddit_semantic_compatibility.py",
    "scripts/build_reddit_site_insights.py",
    "scripts/build_reddit_site_snapshot.py",
    "scripts/materialize_reddit_incremental_configs.py",
    "scripts/validate_reddit_candidate_data_closure.py",
    "scripts/validate_reddit_candidate_ledgers.py",
    "scripts/validate_reddit_personas_snapshot.py",
    "scripts/validate_public_site_projection.py",
    "scripts/validate_reddit_site_analytics.py",
    "scripts/validate_reddit_site_snapshot.py",
    "src/reddit_voc/risk_report_contracts.py",
)

BOUNDARIES = {
    "provider_call": False,
    "provider_attempt_made": False,
    "database_write": False,
    "remote_write": False,
    "production_merge": False,
    "deployment": False,
    "deploy": False,
    "live_send": False,
    "webhook_send": False,
    "schedule_change": False,
    "collector_change": False,
    "production_unchanged": True,
}
SIDE_EFFECT_KEYS = {
    "provider_call",
    "provider_attempt_made",
    "database_write",
    "remote_write",
    "production_merge",
    "deployment",
    "deploy",
    "live_send",
    "webhook_send",
    "schedule_change",
    "collector_change",
}


class CandidateDataClosureError(ValueError):
    """A closure input or immutable publication invariant failed."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reject_traversal(path: Path, *, label: str) -> None:
    if ".." in path.parts:
        raise CandidateDataClosureError(f"{label}_path_traversal")


def _regular_file(path: Path, *, label: str, mode: int | None = None) -> os.stat_result:
    _reject_traversal(path, label=label)
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise CandidateDataClosureError(f"{label}_missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise CandidateDataClosureError(f"{label}_unsafe")
    if mode is not None and stat.S_IMODE(metadata.st_mode) != mode:
        raise CandidateDataClosureError(f"{label}_mode_invalid")
    return metadata


def _directory(path: Path, *, label: str, mode: int | None = None) -> os.stat_result:
    _reject_traversal(path, label=label)
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise CandidateDataClosureError(f"{label}_missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise CandidateDataClosureError(f"{label}_unsafe")
    if mode is not None and stat.S_IMODE(metadata.st_mode) != mode:
        raise CandidateDataClosureError(f"{label}_mode_invalid")
    return metadata


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    _regular_file(path, label=label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateDataClosureError(f"{label}_invalid") from exc
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise CandidateDataClosureError(f"{label}_invalid")
    return value


def _expected_file(path: Path, expected: str, *, label: str) -> str:
    if not isinstance(expected, str) or SHA256_RE.fullmatch(expected) is None:
        raise CandidateDataClosureError(f"{label}_expected_sha256_invalid")
    _regular_file(path, label=label)
    actual = _file_sha256(path)
    if actual != expected:
        raise CandidateDataClosureError(f"{label}_sha256_mismatch")
    return actual


def _safe_relative(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise CandidateDataClosureError(f"{label}_path_invalid")
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != value:
        raise CandidateDataClosureError(f"{label}_path_invalid")
    return value


def _validate_file_contracts(root: Path, manifest: Mapping[str, Any], *, label: str) -> None:
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise CandidateDataClosureError(f"{label}_files_invalid")
    for name, contract in files.items():
        relative = _safe_relative(name, label=f"{label}_file")
        if not isinstance(contract, dict):
            raise CandidateDataClosureError(f"{label}_file_contract_invalid")
        path = root / relative
        metadata = _regular_file(path, label=f"{label}_file")
        if (
            contract.get("bytes") != metadata.st_size
            or contract.get("sha256") != _file_sha256(path)
        ):
            raise CandidateDataClosureError(f"{label}_file_binding_invalid")


def _assert_side_effect_boundaries(value: object, *, label: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in SIDE_EFFECT_KEYS and child is not False:
                raise CandidateDataClosureError(f"{label}_side_effect_boundary_invalid")
            _assert_side_effect_boundaries(child, label=label)
    elif isinstance(value, list):
        for child in value:
            _assert_side_effect_boundaries(child, label=label)


def _validate_base(root: Path, expected_sha256: str, *, label: str) -> dict[str, Any]:
    _directory(root, label=label)
    manifest_path = root / "manifest.json"
    _expected_file(manifest_path, expected_sha256, label=f"{label}_manifest")
    manifest = _load_json(manifest_path, label=f"{label}_manifest")
    if manifest.get("schema_version") not in BASE_MANIFEST_SCHEMAS:
        raise CandidateDataClosureError(f"{label}_schema_invalid")
    if manifest.get("all_checks_passed") is not True:
        raise CandidateDataClosureError(f"{label}_checks_invalid")
    _validate_file_contracts(root, manifest, label=label)
    if manifest.get("provider_call") is not False or manifest.get("live_send") is not False:
        raise CandidateDataClosureError(f"{label}_side_effect_boundary_invalid")
    if manifest.get("production_unchanged") is not True:
        raise CandidateDataClosureError(f"{label}_production_boundary_invalid")
    return manifest


def _code_file_path(root: Path, relative: str) -> Path:
    _directory(root, label="code_root")
    pure = PurePosixPath(relative)
    current = root
    for part in pure.parts[:-1]:
        current = current / part
        _directory(current, label="code_parent")
    target = root / relative
    _regular_file(target, label="code_file")
    return target


def _validate_code_freeze(
    path: Path, expected_sha256: str, code_root: Path
) -> dict[str, Any]:
    _expected_file(path, expected_sha256, label="code_freeze_manifest")
    manifest = _load_json(path, label="code_freeze_manifest")
    if manifest.get("schema_version") != CODE_FREEZE_SCHEMA:
        raise CandidateDataClosureError("code_freeze_schema_invalid")
    cutoff = manifest.get("code_cutoff_utc")
    if not isinstance(cutoff, str) or not cutoff.endswith("Z"):
        raise CandidateDataClosureError("code_cutoff_utc_invalid")
    if manifest.get("allowlist_version") != "plan_a_data_build_v1":
        raise CandidateDataClosureError("code_allowlist_version_invalid")
    files = manifest.get("files")
    if not isinstance(files, dict) or tuple(sorted(files)) != tuple(sorted(CODE_ALLOWLIST)):
        raise CandidateDataClosureError("code_allowlist_invalid")
    for relative, contract in files.items():
        _safe_relative(relative, label="code_allowlist")
        if (
            not isinstance(contract, dict)
            or not isinstance(contract.get("bytes"), int)
            or isinstance(contract.get("bytes"), bool)
            or contract["bytes"] < 0
            or not isinstance(contract.get("sha256"), str)
            or SHA256_RE.fullmatch(contract["sha256"]) is None
        ):
            raise CandidateDataClosureError("code_file_contract_invalid")
        code_path = _code_file_path(code_root, relative)
        metadata = _regular_file(code_path, label="code_file")
        if (
            contract.get("bytes") != metadata.st_size
            or contract.get("sha256") != _file_sha256(code_path)
        ):
            raise CandidateDataClosureError("code_file_binding_invalid")
    if manifest.get("boundaries") != BOUNDARIES:
        raise CandidateDataClosureError("code_freeze_boundaries_invalid")
    _assert_side_effect_boundaries(manifest.get("boundaries"), label="code_freeze")
    return manifest


def _validate_ledger_bundle(
    root: Path,
    expected_manifest_sha256: str,
    receipt_path: Path,
    expected_receipt_sha256: str,
    *,
    source_sha256: str,
    baseline_sha256: str,
    candidate_base_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _directory(root, label="ledger_root")
    manifest_path = root / "candidate-ledger-manifest.json"
    _expected_file(manifest_path, expected_manifest_sha256, label="ledger_manifest")
    manifest = _load_json(manifest_path, label="ledger_manifest")
    if (
        manifest.get("schema_version") != LEDGER_MANIFEST_SCHEMA
        or manifest.get("status") != "a2_identity_closed_with_explicit_coverage_debt"
    ):
        raise CandidateDataClosureError("ledger_manifest_status_invalid")
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict) or inputs.get("source_freeze_manifest_sha256") != source_sha256:
        raise CandidateDataClosureError("ledger_source_lineage_invalid")
    if inputs.get("production_baseline_manifest_sha256") != baseline_sha256:
        raise CandidateDataClosureError("ledger_baseline_lineage_invalid")
    if inputs.get("candidate_base_manifest_sha256") != candidate_base_sha256:
        raise CandidateDataClosureError("ledger_candidate_base_lineage_invalid")
    ledgers = manifest.get("ledgers")
    if not isinstance(ledgers, dict) or tuple(sorted(ledgers)) != tuple(sorted(LEDGER_NAMES)):
        raise CandidateDataClosureError("ledger_inventory_invalid")
    for name in LEDGER_NAMES:
        contract = ledgers.get(name)
        path = root / name
        metadata = _regular_file(path, label="ledger_file")
        if (
            not isinstance(contract, dict)
            or contract.get("bytes") != metadata.st_size
            or contract.get("sha256") != _file_sha256(path)
            or not isinstance(contract.get("rows"), int)
        ):
            raise CandidateDataClosureError("ledger_file_binding_invalid")
    accounting = manifest.get("accounting")
    if not isinstance(accounting, dict) or accounting.get("unaccounted_total") != 0:
        raise CandidateDataClosureError("ledger_unaccounted_invalid")
    _assert_side_effect_boundaries(manifest, label="ledger_manifest")
    if manifest.get("production_unchanged") is not True:
        raise CandidateDataClosureError("ledger_production_boundary_invalid")

    _expected_file(receipt_path, expected_receipt_sha256, label="ledger_receipt")
    receipt = _load_json(receipt_path, label="ledger_receipt")
    if receipt.get("schema_version") != LEDGER_RECEIPT_SCHEMA or receipt.get("status") != "passed":
        raise CandidateDataClosureError("ledger_receipt_status_invalid")
    if receipt.get("candidate_ledger_manifest_sha256") != expected_manifest_sha256:
        raise CandidateDataClosureError("ledger_receipt_lineage_invalid")
    counts = receipt.get("counts")
    if not isinstance(counts, dict) or counts.get("unaccounted_total") != 0:
        raise CandidateDataClosureError("ledger_receipt_accounting_invalid")
    _assert_side_effect_boundaries(receipt, label="ledger_receipt")
    if receipt.get("production_unchanged") is not True:
        raise CandidateDataClosureError("ledger_receipt_production_boundary_invalid")
    return manifest, receipt


def _validate_config(
    path: Path,
    expected_sha256: str,
    *,
    base_sha256: str,
    ledger_sha256: str,
    ledger_receipt_sha256: str,
) -> dict[str, Any]:
    _expected_file(path, expected_sha256, label="config_manifest")
    manifest = _load_json(path, label="config_manifest")
    if manifest.get("schema_version") != CONFIG_MANIFEST_SCHEMA:
        raise CandidateDataClosureError("config_manifest_schema_invalid")
    gate = manifest.get("identity_gate")
    if not isinstance(gate, dict) or gate != {
        "candidate_base_manifest_sha256": base_sha256,
        "candidate_ledger_manifest_sha256": ledger_sha256,
        "input_evidence_sha256": gate.get("input_evidence_sha256"),
        "ledger_validation_receipt_sha256": ledger_receipt_sha256,
        "unaccounted_total": 0,
    }:
        raise CandidateDataClosureError("config_identity_gate_invalid")
    _validate_file_contracts(path.parent, manifest, label="config")
    _assert_side_effect_boundaries(manifest, label="config")
    return manifest


def _validate_analytics(
    insights_root: Path,
    expected_insights_sha256: str,
    reports_root: Path,
    expected_reports_sha256: str,
    receipt_path: Path,
    expected_receipt_sha256: str,
    *,
    base_sha256: str,
    ledger_sha256: str,
    ledger_receipt_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    _directory(insights_root, label="insights_root")
    _directory(reports_root, label="reports_root")
    insights_path = insights_root / "manifest.json"
    reports_path = reports_root / "manifest.json"
    _expected_file(insights_path, expected_insights_sha256, label="insights_manifest")
    _expected_file(reports_path, expected_reports_sha256, label="reports_manifest")
    insights = _load_json(insights_path, label="insights_manifest")
    reports = _load_json(reports_path, label="reports_manifest")
    if insights.get("schema_version") != "reddit_voc_insights_manifest_v1":
        raise CandidateDataClosureError("insights_schema_invalid")
    if reports.get("schema_version") != "reddit_voc_reports_manifest_v1":
        raise CandidateDataClosureError("reports_schema_invalid")
    if insights.get("base_manifest_sha256") != base_sha256:
        raise CandidateDataClosureError("insights_base_lineage_invalid")
    if reports.get("base_manifest_sha256") != base_sha256:
        raise CandidateDataClosureError("reports_base_lineage_invalid")
    if reports.get("insights_manifest_sha256") != expected_insights_sha256:
        raise CandidateDataClosureError("reports_insights_lineage_invalid")
    for value, label in ((insights, "insights"), (reports, "reports")):
        gate = value.get("identity_gate")
        if (
            not isinstance(gate, dict)
            or gate.get("candidate_ledger_manifest_sha256") != ledger_sha256
            or gate.get("ledger_validation_receipt_sha256") != ledger_receipt_sha256
            or gate.get("unaccounted_total") != 0
        ):
            raise CandidateDataClosureError(f"{label}_identity_gate_invalid")
        _validate_file_contracts(
            insights_root if label == "insights" else reports_root,
            value,
            label=label,
        )
        _assert_side_effect_boundaries(value, label=label)
        boundaries = value.get("boundaries")
        if not isinstance(boundaries, dict) or boundaries.get("production_unchanged") is not True:
            raise CandidateDataClosureError(f"{label}_production_boundary_invalid")

    _expected_file(receipt_path, expected_receipt_sha256, label="analytics_receipt")
    receipt = _load_json(receipt_path, label="analytics_receipt")
    if (
        receipt.get("schema_version") != ANALYTICS_RECEIPT_SCHEMA
        or receipt.get("status") != "passed_release_candidate"
        or receipt.get("base_manifest_sha256") != base_sha256
        or receipt.get("insights_manifest_sha256") != expected_insights_sha256
        or receipt.get("reports_manifest_sha256") != expected_reports_sha256
    ):
        raise CandidateDataClosureError("analytics_receipt_lineage_invalid")
    _assert_side_effect_boundaries(receipt, label="analytics_receipt")
    if receipt.get("production_unchanged") is not True:
        raise CandidateDataClosureError("analytics_receipt_production_boundary_invalid")
    return insights, reports, receipt


def _validate_personas(
    root: Path,
    expected_manifest_sha256: str,
    receipt_path: Path,
    expected_receipt_sha256: str,
    *,
    base_sha256: str,
    insights_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _directory(root, label="personas_root")
    manifest_path = root / "manifest.json"
    _expected_file(manifest_path, expected_manifest_sha256, label="personas_manifest")
    manifest = _load_json(manifest_path, label="personas_manifest")
    if (
        manifest.get("schema_version") != "reddit_voc_personas_manifest_v1"
        or manifest.get("base_manifest_sha256") != base_sha256
        or manifest.get("insights_manifest_sha256") != insights_sha256
    ):
        raise CandidateDataClosureError("personas_manifest_lineage_invalid")
    _validate_file_contracts(root, manifest, label="personas")
    _assert_side_effect_boundaries(manifest, label="personas")
    boundaries = manifest.get("boundaries")
    if not isinstance(boundaries, dict) or boundaries.get("production_unchanged") is not True:
        raise CandidateDataClosureError("personas_production_boundary_invalid")

    _expected_file(receipt_path, expected_receipt_sha256, label="personas_receipt")
    receipt = _load_json(receipt_path, label="personas_receipt")
    if (
        receipt.get("schema_version") != PERSONAS_RECEIPT_SCHEMA
        or receipt.get("status") != "passed"
        or receipt.get("manifest_sha256") != expected_manifest_sha256
        or receipt.get("base_manifest_sha256") != base_sha256
        or receipt.get("insights_manifest_sha256") != insights_sha256
    ):
        raise CandidateDataClosureError("personas_receipt_lineage_invalid")
    _assert_side_effect_boundaries(receipt, label="personas_receipt")
    if receipt.get("production_unchanged") is not True:
        raise CandidateDataClosureError("personas_receipt_production_boundary_invalid")
    return manifest, receipt


def _public_inventory(root: Path) -> tuple[list[dict[str, Any]], int, str]:
    _directory(root, label="public_root")
    inventory: list[dict[str, Any]] = []
    total_bytes = 0
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        metadata = os.lstat(path)
        if stat.S_ISLNK(metadata.st_mode):
            raise CandidateDataClosureError("public_tree_symlink")
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise CandidateDataClosureError("public_tree_unsafe")
        digest = _file_sha256(path)
        inventory.append({"path": relative, "bytes": metadata.st_size, "sha256": digest})
        total_bytes += metadata.st_size
    if not inventory:
        raise CandidateDataClosureError("public_tree_empty")
    payload = "".join(
        f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in inventory
    ).encode("utf-8")
    return inventory, total_bytes, _sha256_bytes(payload)


def _validate_public_projection(
    root: Path,
    expected_inventory_sha256: str,
    *,
    base: Mapping[str, Any],
    base_sha256: str,
    insights: Mapping[str, Any],
    insights_sha256: str,
    reports: Mapping[str, Any],
    personas: Mapping[str, Any],
) -> dict[str, Any]:
    inventory, total_bytes, inventory_sha256 = _public_inventory(root)
    if inventory_sha256 != expected_inventory_sha256:
        raise CandidateDataClosureError("public_inventory_sha256_mismatch")
    base_version = base.get("dataset_version")
    insights_version = insights.get("dataset_version")
    reports_version = reports.get("dataset_version")
    personas_version = personas.get("dataset_version")
    versions = (base_version, insights_version, reports_version, personas_version)
    if not all(isinstance(value, str) and value for value in versions):
        raise CandidateDataClosureError("public_dataset_version_invalid")
    manifest_paths = {
        "base": root / "data" / "reddit-voc" / str(base_version) / "manifest-public.json",
        "insights": root / "data" / "reddit-voc" / str(insights_version) / "public" / "manifest.json",
        "reports": root / "data" / "reddit-voc" / str(reports_version) / "public" / "manifest.json",
        "personas": root / "data" / "reddit-voc" / str(personas_version) / "manifest.json",
    }
    manifests = {label: _load_json(path, label=f"public_{label}_manifest") for label, path in manifest_paths.items()}
    if manifests["base"].get("dataset_version") != base_version:
        raise CandidateDataClosureError("public_base_version_invalid")
    for label in ("insights", "reports", "personas"):
        if manifests[label].get("base_manifest_sha256") != base_sha256:
            raise CandidateDataClosureError(f"public_{label}_base_lineage_invalid")
    if manifests["reports"].get("insights_manifest_sha256") != insights_sha256:
        raise CandidateDataClosureError("public_reports_insights_lineage_invalid")
    if manifests["personas"].get("insights_manifest_sha256") != insights_sha256:
        raise CandidateDataClosureError("public_personas_insights_lineage_invalid")
    if manifests["insights"].get("dataset_version") != insights_version:
        raise CandidateDataClosureError("public_insights_version_invalid")
    if manifests["reports"].get("dataset_version") != reports_version:
        raise CandidateDataClosureError("public_reports_version_invalid")
    if manifests["personas"].get("dataset_version") != personas_version:
        raise CandidateDataClosureError("public_personas_version_invalid")
    manifest_sha256: dict[str, str] = {}
    for label, path in manifest_paths.items():
        manifest_sha256[label] = _file_sha256(path)
        _validate_file_contracts(path.parent, manifests[label], label=f"public_{label}")
        _assert_side_effect_boundaries(manifests[label], label=f"public_{label}")
        boundaries = manifests[label].get("boundaries")
        if boundaries is not None and (
            not isinstance(boundaries, dict)
            or boundaries.get("production_unchanged") is not True
        ):
            raise CandidateDataClosureError(f"public_{label}_production_boundary_invalid")
    return {
        "file_count": len(inventory),
        "total_bytes": total_bytes,
        "inventory_sha256": inventory_sha256,
        "manifest_sha256": manifest_sha256,
    }


def _validate_public_receipt(
    path: Path,
    expected_sha256: str,
    *,
    inventory_sha256: str,
    base_sha256: str,
    insights_sha256: str,
    reports_sha256: str,
    personas_sha256: str,
    public: Mapping[str, Any],
    base_version: object,
    insights_version: object,
    reports_version: object,
    personas_version: object,
    cases: Mapping[str, Any],
) -> dict[str, Any]:
    _expected_file(path, expected_sha256, label="public_validation_receipt")
    receipt = _load_json(path, label="public_validation_receipt")
    if (
        receipt.get("schema_version") != "reddit_voc_public_projection_validation_v1"
        or receipt.get("status") != "passed_release_candidate"
    ):
        raise CandidateDataClosureError("public_validation_receipt_status_invalid")
    if receipt.get("public_inventory") != {
        "file_count": public["file_count"],
        "total_bytes": public["total_bytes"],
        "inventory_sha256": inventory_sha256,
    }:
        raise CandidateDataClosureError("public_validation_receipt_inventory_invalid")
    expected_lineage = {
        "base": {
            "dataset_version": base_version,
            "private_manifest_sha256": base_sha256,
            "public_manifest_sha256": public["manifest_sha256"]["base"],
        },
        "insights": {
            "dataset_version": insights_version,
            "private_manifest_sha256": insights_sha256,
            "public_manifest_sha256": public["manifest_sha256"]["insights"],
        },
        "reports": {
            "dataset_version": reports_version,
            "private_manifest_sha256": reports_sha256,
            "public_manifest_sha256": public["manifest_sha256"]["reports"],
        },
        "personas": {
            "dataset_version": personas_version,
            "private_manifest_sha256": personas_sha256,
            "public_manifest_sha256": public["manifest_sha256"]["personas"],
        },
    }
    if receipt.get("lineage") != expected_lineage:
        raise CandidateDataClosureError("public_validation_receipt_lineage_invalid")
    if receipt.get("cases") != cases:
        raise CandidateDataClosureError("public_validation_receipt_cases_invalid")
    _assert_side_effect_boundaries(receipt, label="public_validation_receipt")
    if receipt.get("production_unchanged") is not True:
        raise CandidateDataClosureError("public_validation_receipt_production_boundary_invalid")
    return receipt


def _validate_cases(
    manifest_path: Path,
    expected_manifest_sha256: str,
    index_path: Path,
    expected_index_sha256: str,
) -> dict[str, Any]:
    _expected_file(manifest_path, expected_manifest_sha256, label="cases_manifest")
    _expected_file(index_path, expected_index_sha256, label="cases_index")
    manifest = _load_json(manifest_path, label="cases_manifest")
    index = _load_json(index_path, label="cases_index")
    if manifest.get("schemaVersion") != 1 or index.get("schemaVersion") != 1:
        raise CandidateDataClosureError("cases_schema_invalid")
    if manifest.get("datasetVersion") != index.get("datasetVersion"):
        raise CandidateDataClosureError("cases_version_invalid")
    seed = manifest.get("seed")
    legacy = manifest.get("legacyUnverified")
    delta = manifest.get("approvedDelta")
    if not isinstance(seed, dict) or seed.get("count") != 38:
        raise CandidateDataClosureError("cases_selected_count_invalid")
    if not isinstance(legacy, dict) or legacy.get("count") != 12:
        raise CandidateDataClosureError("cases_unverified_count_invalid")
    approved = index.get("approvedDelta")
    if not isinstance(approved, list) or not isinstance(delta, dict) or delta.get("count") != len(approved):
        raise CandidateDataClosureError("cases_approved_delta_count_invalid")
    if len(approved) != 0:
        raise CandidateDataClosureError("cases_approved_delta_not_empty")
    if delta.get("contentSha256") != _sha256_bytes(_canonical_bytes(approved)):
        raise CandidateDataClosureError("cases_approved_delta_hash_invalid")
    index_contract = manifest.get("index")
    if not isinstance(index_contract, dict) or index_contract.get("sha256") != expected_index_sha256:
        raise CandidateDataClosureError("cases_index_lineage_invalid")
    provenance = manifest.get("provenance")
    if not isinstance(provenance, dict) or provenance.get("networkSearch") is not False:
        raise CandidateDataClosureError("cases_network_boundary_invalid")
    return {
        "dataset_version": manifest.get("datasetVersion"),
        "selected_count": 38,
        "unverified_count": 12,
        "approved_delta_count": 0,
        "manifest_sha256": expected_manifest_sha256,
        "index_sha256": expected_index_sha256,
        "seed_content_sha256": seed.get("contentSha256"),
        "legacy_unverified_content_sha256": legacy.get("contentSha256"),
        "approved_delta_content_sha256": delta.get("contentSha256"),
    }


def _validate_production_acceptance(
    path: Path,
    expected_sha256: str,
    *,
    baseline: Mapping[str, Any],
) -> dict[str, Any]:
    _expected_file(path, expected_sha256, label="production_acceptance_receipt")
    receipt = _load_json(path, label="production_acceptance_receipt")
    if (
        receipt.get("schema_version") != PRODUCTION_ACCEPTANCE_SCHEMA
        or receipt.get("status") != "production_accepted_with_explicit_coverage_debt"
    ):
        raise CandidateDataClosureError("production_acceptance_status_invalid")
    release = receipt.get("release")
    datasets = receipt.get("datasets")
    if (
        not isinstance(release, dict)
        or not isinstance(release.get("current_production_release_sha256"), str)
        or SHA256_RE.fullmatch(release["current_production_release_sha256"]) is None
        or not isinstance(datasets, dict)
        or datasets.get("base") != baseline.get("dataset_version")
    ):
        raise CandidateDataClosureError("production_acceptance_lineage_invalid")
    counts = baseline.get("canonical_counts")
    if not isinstance(counts, dict):
        raise CandidateDataClosureError("production_baseline_counts_invalid")
    for receipt_key, base_key in (
        ("published_posts", "posts"),
        ("linked_comments", "linked_comments"),
        ("stored_comments", "stored_comments"),
        ("quarantined_comments", "quarantined_comments"),
    ):
        if datasets.get(receipt_key) != counts.get(base_key):
            raise CandidateDataClosureError("production_acceptance_counts_invalid")
    return receipt


def _candidate_input_sha256(
    *,
    source_freeze_sha256: str,
    production_baseline_sha256: str,
    config_sha256: str,
    code_freeze_sha256: str,
) -> tuple[dict[str, str], str]:
    payload = {
        "code_freeze_manifest_sha256": code_freeze_sha256,
        "config_manifest_sha256": config_sha256,
        "production_baseline_manifest_sha256": production_baseline_sha256,
        "source_freeze_manifest_sha256": source_freeze_sha256,
    }
    return payload, _sha256_bytes(_canonical_bytes(payload))


def _coverage_transition(accounting: Mapping[str, Any]) -> dict[str, Any]:
    coverage = accounting.get("coverage")
    if not isinstance(coverage, dict):
        raise CandidateDataClosureError("coverage_accounting_invalid")
    total = coverage.get("total")
    statuses = coverage.get("status_counts")
    if not isinstance(total, int) or not isinstance(statuses, dict):
        raise CandidateDataClosureError("coverage_accounting_invalid")
    open_count = sum(
        value
        for key, value in statuses.items()
        if key in {"retryable_failed", "open_carried"} and isinstance(value, int)
    )
    return {
        "before": {"frozen_work_items": total},
        "after": {
            "open_work_items": open_count,
            "terminal_work_items": total - open_count,
            "status_counts": deepcopy(statuses),
        },
    }


def _build_documents(args: argparse.Namespace) -> tuple[str, dict[str, Any], dict[str, Any]]:
    source_path = Path(args.source_freeze_manifest)
    source_sha = _expected_file(
        source_path,
        args.expected_source_freeze_manifest_sha256,
        label="source_freeze_manifest",
    )
    source = _load_json(source_path, label="source_freeze_manifest")
    if source.get("schema_version") != SOURCE_FREEZE_SCHEMA:
        raise CandidateDataClosureError("source_freeze_schema_invalid")
    source_cutoff = source.get("source_cutoff_utc")
    if not isinstance(source_cutoff, str) or not source_cutoff.endswith("Z"):
        raise CandidateDataClosureError("source_cutoff_utc_invalid")
    _assert_side_effect_boundaries(source.get("boundaries"), label="source_freeze")

    baseline_sha = args.expected_production_baseline_manifest_sha256
    baseline = _validate_base(Path(args.production_baseline_root), baseline_sha, label="production_baseline")
    base_sha = args.expected_candidate_base_manifest_sha256
    base = _validate_base(Path(args.candidate_base_root), base_sha, label="candidate_base")
    production_receipt = _validate_production_acceptance(
        Path(args.production_acceptance_receipt),
        args.expected_production_acceptance_receipt_sha256,
        baseline=baseline,
    )
    ledger, _ledger_receipt = _validate_ledger_bundle(
        Path(args.candidate_ledger_root),
        args.expected_candidate_ledger_manifest_sha256,
        Path(args.ledger_validation_receipt),
        args.expected_ledger_validation_receipt_sha256,
        source_sha256=source_sha,
        baseline_sha256=baseline_sha,
        candidate_base_sha256=base_sha,
    )
    _validate_config(
        Path(args.config_manifest),
        args.expected_config_manifest_sha256,
        base_sha256=base_sha,
        ledger_sha256=args.expected_candidate_ledger_manifest_sha256,
        ledger_receipt_sha256=args.expected_ledger_validation_receipt_sha256,
    )
    code = _validate_code_freeze(
        Path(args.code_freeze_manifest),
        args.expected_code_freeze_manifest_sha256,
        Path(args.code_root),
    )
    insights, reports, _analytics_receipt = _validate_analytics(
        Path(args.insights_root),
        args.expected_insights_manifest_sha256,
        Path(args.reports_root),
        args.expected_reports_manifest_sha256,
        Path(args.analytics_validation_receipt),
        args.expected_analytics_validation_receipt_sha256,
        base_sha256=base_sha,
        ledger_sha256=args.expected_candidate_ledger_manifest_sha256,
        ledger_receipt_sha256=args.expected_ledger_validation_receipt_sha256,
    )
    personas, _personas_receipt = _validate_personas(
        Path(args.personas_root),
        args.expected_personas_manifest_sha256,
        Path(args.personas_validation_receipt),
        args.expected_personas_validation_receipt_sha256,
        base_sha256=base_sha,
        insights_sha256=args.expected_insights_manifest_sha256,
    )
    public = _validate_public_projection(
        Path(args.public_root),
        args.expected_public_inventory_sha256,
        base=base,
        base_sha256=base_sha,
        insights=insights,
        insights_sha256=args.expected_insights_manifest_sha256,
        reports=reports,
        personas=personas,
    )
    cases = _validate_cases(
        Path(args.cases_manifest),
        args.expected_cases_manifest_sha256,
        Path(args.cases_index),
        args.expected_cases_index_sha256,
    )
    _validate_public_receipt(
        Path(args.public_validation_receipt),
        args.expected_public_validation_receipt_sha256,
        inventory_sha256=public["inventory_sha256"],
        base_sha256=base_sha,
        insights_sha256=args.expected_insights_manifest_sha256,
        reports_sha256=args.expected_reports_manifest_sha256,
        personas_sha256=args.expected_personas_manifest_sha256,
        public=public,
        base_version=base.get("dataset_version"),
        insights_version=insights.get("dataset_version"),
        reports_version=reports.get("dataset_version"),
        personas_version=personas.get("dataset_version"),
        cases=cases,
    )
    input_payload, candidate_input_sha = _candidate_input_sha256(
        source_freeze_sha256=source_sha,
        production_baseline_sha256=baseline_sha,
        config_sha256=args.expected_config_manifest_sha256,
        code_freeze_sha256=args.expected_code_freeze_manifest_sha256,
    )

    accounting = ledger.get("accounting")
    identity_sets = ledger.get("identity_sets")
    ledger_files = ledger.get("ledgers")
    if not isinstance(accounting, dict) or not isinstance(identity_sets, dict) or not isinstance(ledger_files, dict):
        raise CandidateDataClosureError("ledger_reconciliation_fields_invalid")
    comment_statuses = accounting.get("comments", {}).get("status_counts", {})
    if not isinstance(comment_statuses, dict):
        raise CandidateDataClosureError("comment_accounting_invalid")
    release = production_receipt["release"]
    reconciliation = {
        "schema_version": SCHEMA_VERSION,
        "candidate_input_sha256": candidate_input_sha,
        "source_cutoff_utc": source_cutoff,
        "code_cutoff_utc": code["code_cutoff_utc"],
        "production_baseline": {
            "dataset_version": baseline.get("dataset_version"),
            "manifest_sha256": baseline_sha,
            "release_sha256": release["current_production_release_sha256"],
            "acceptance_receipt_sha256": args.expected_production_acceptance_receipt_sha256,
        },
        "input_freeze_sha256": source_sha,
        "identity_sets": deepcopy(identity_sets),
        "detail_ledgers": deepcopy(ledger_files),
        "accounting": deepcopy(accounting),
        "coverage_transition": _coverage_transition(accounting),
        "quarantine_transitions": {
            "new_quarantined": comment_statuses.get("new_quarantined", 0),
            "relinked": comment_statuses.get("existing_quarantine_relinked", 0),
            "retained": comment_statuses.get("existing_quarantine_retained", 0),
        },
        "outputs": {
            "base_manifest_sha256": base_sha,
            "insights_manifest_sha256": args.expected_insights_manifest_sha256,
            "reports_manifest_sha256": args.expected_reports_manifest_sha256,
            "personas_manifest_sha256": args.expected_personas_manifest_sha256,
            "public_inventory_sha256": public["inventory_sha256"],
            "public_manifest_sha256": public["manifest_sha256"],
            "cases_manifest_sha256": cases["manifest_sha256"],
            "cases_index_sha256": cases["index_sha256"],
        },
        "validation_receipts": {
            "candidate_ledgers": args.expected_ledger_validation_receipt_sha256,
            "analytics": args.expected_analytics_validation_receipt_sha256,
            "personas": args.expected_personas_validation_receipt_sha256,
            "public": args.expected_public_validation_receipt_sha256,
        },
        "validation_code": {
            "public_projection_validator_sha256": code["files"]
            ["scripts/validate_public_site_projection.py"]["sha256"],
        },
        "cases": cases,
        "evidence_grade": "L2_local_candidate_with_L3_readonly_baseline",
        "boundaries": deepcopy(BOUNDARIES),
    }
    reconciliation_payload = _canonical_bytes(reconciliation) + b"\n"
    reconciliation_sha = _sha256_bytes(reconciliation_payload)
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "candidate_data_built_local",
        "candidate_input_sha256": candidate_input_sha,
        "candidate_input": input_payload,
        "source_cutoff_utc": source_cutoff,
        "code_cutoff_utc": code["code_cutoff_utc"],
        "reconciliation": {
            "path": "candidate-data-reconciliation-ledger.jsonl",
            "rows": 1,
            "bytes": len(reconciliation_payload),
            "sha256": reconciliation_sha,
        },
        "files": {
            "source-freeze-manifest.json": {
                "bytes": source_path.stat().st_size,
                "sha256": source_sha,
            },
            **deepcopy(ledger_files),
            "candidate-data-reconciliation-ledger.jsonl": {
                "bytes": len(reconciliation_payload),
                "rows": 1,
                "sha256": reconciliation_sha,
            },
        },
        "lineage": {
            "production_acceptance_receipt_sha256": args.expected_production_acceptance_receipt_sha256,
            "candidate_base_manifest_sha256": base_sha,
            "candidate_ledger_manifest_sha256": args.expected_candidate_ledger_manifest_sha256,
            "ledger_validation_receipt_sha256": args.expected_ledger_validation_receipt_sha256,
            "analytics_validation_receipt_sha256": args.expected_analytics_validation_receipt_sha256,
            "personas_validation_receipt_sha256": args.expected_personas_validation_receipt_sha256,
            "public_validation_receipt_sha256": args.expected_public_validation_receipt_sha256,
            "public_projection_validator_code_sha256": code["files"]
            ["scripts/validate_public_site_projection.py"]["sha256"],
            "insights_manifest_sha256": args.expected_insights_manifest_sha256,
            "reports_manifest_sha256": args.expected_reports_manifest_sha256,
            "personas_manifest_sha256": args.expected_personas_manifest_sha256,
            "public_inventory_sha256": public["inventory_sha256"],
            "cases_manifest_sha256": cases["manifest_sha256"],
            "cases_index_sha256": cases["index_sha256"],
        },
        "counts": {
            "detail_ledgers": 4,
            "public_files": public["file_count"],
            "public_bytes": public["total_bytes"],
            "cases_selected": cases["selected_count"],
            "cases_unverified": cases["unverified_count"],
            "cases_approved_delta": cases["approved_delta_count"],
            "unaccounted_total": 0,
        },
        "evidence_grade": "L2_local_candidate_with_L3_readonly_baseline",
        "boundaries": deepcopy(BOUNDARIES),
    }
    return candidate_input_sha, reconciliation, manifest


def _ensure_output_root(path: Path) -> None:
    _reject_traversal(path, label="output_root")
    if path.exists() or path.is_symlink():
        _directory(path, label="output_root", mode=0o700)
        return
    _directory(path.parent, label="output_root_parent")
    try:
        path.mkdir(mode=0o700)
    except OSError as exc:
        raise CandidateDataClosureError("output_root_create_failed") from exc
    _directory(path, label="output_root", mode=0o700)


def _existing_publication_status(
    target: Path,
    expected_payloads: Mapping[str, bytes],
) -> str:
    _directory(target, label="candidate_root", mode=0o700)
    allowed = {*REQUIRED_PUBLICATION_NAMES, "candidate-data-validation-receipt.json"}
    members = {path.name for path in target.iterdir()}
    if not set(REQUIRED_PUBLICATION_NAMES) <= members or not members <= allowed:
        raise CandidateDataClosureError("candidate_root_inventory_invalid")
    for name, payload in expected_payloads.items():
        path = target / name
        _regular_file(path, label="published_file", mode=0o600)
        if path.read_bytes() != payload:
            raise CandidateDataClosureError("candidate_publication_immutable_collision")
    receipt_path = target / "candidate-data-validation-receipt.json"
    if receipt_path.exists() or receipt_path.is_symlink():
        _regular_file(receipt_path, label="published_receipt", mode=0o600)
    return "no_change"


def _publication_payloads(
    args: argparse.Namespace,
    reconciliation: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> dict[str, bytes]:
    contracts = manifest.get("files")
    if not isinstance(contracts, dict):
        raise CandidateDataClosureError("candidate_manifest_files_invalid")
    source_path = Path(args.source_freeze_manifest)
    source_payload = source_path.read_bytes()
    source_contract = contracts.get("source-freeze-manifest.json")
    if not isinstance(source_contract, dict) or source_contract != {
        "bytes": len(source_payload),
        "sha256": _sha256_bytes(source_payload),
    }:
        raise CandidateDataClosureError("source_freeze_copy_binding_invalid")
    payloads = {"source-freeze-manifest.json": source_payload}
    ledger_root = Path(args.candidate_ledger_root)
    for name in LEDGER_NAMES:
        path = ledger_root / name
        _regular_file(path, label="ledger_copy_source")
        payload = path.read_bytes()
        contract = contracts.get(name)
        if (
            not isinstance(contract, dict)
            or contract.get("bytes") != len(payload)
            or contract.get("sha256") != _sha256_bytes(payload)
        ):
            raise CandidateDataClosureError("ledger_copy_binding_invalid")
        payloads[name] = payload
    payloads["candidate-data-reconciliation-ledger.jsonl"] = (
        _canonical_bytes(reconciliation) + b"\n"
    )
    payloads["candidate-data-manifest.json"] = _canonical_bytes(manifest) + b"\n"
    return payloads


def build_candidate_data_closure(args: argparse.Namespace) -> dict[str, Any]:
    candidate_input_sha, reconciliation, manifest = _build_documents(args)
    expected_payloads = _publication_payloads(args, reconciliation, manifest)
    reconciliation_payload = expected_payloads[
        "candidate-data-reconciliation-ledger.jsonl"
    ]
    manifest_payload = expected_payloads["candidate-data-manifest.json"]
    output_root = Path(args.output_root)
    _ensure_output_root(output_root)
    target = output_root / candidate_input_sha
    if target.exists() or target.is_symlink():
        status = _existing_publication_status(target, expected_payloads)
    else:
        staging = Path(tempfile.mkdtemp(prefix=".candidate-data-staging-", dir=output_root))
        try:
            os.chmod(staging, 0o700)
            for name, payload in expected_payloads.items():
                path = staging / name
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                _regular_file(path, label="staged_output", mode=0o600)
            try:
                staging.rename(target)
                status = "created"
            except OSError:
                if target.exists() or target.is_symlink():
                    status = _existing_publication_status(target, expected_payloads)
                else:
                    raise
        except CandidateDataClosureError:
            raise
        except OSError as exc:
            raise CandidateDataClosureError("candidate_publication_failed") from exc
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    return {
        "status": status,
        "candidate_input_sha256": candidate_input_sha,
        "candidate_root": str(target),
        "candidate_data_manifest_sha256": _sha256_bytes(manifest_payload),
        "reconciliation_sha256": _sha256_bytes(reconciliation_payload),
        "production_unchanged": True,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    path_sha_pairs = (
        ("source-freeze-manifest", "source-freeze-manifest"),
        ("production-acceptance-receipt", "production-acceptance-receipt"),
        ("ledger-validation-receipt", "ledger-validation-receipt"),
        ("config-manifest", "config-manifest"),
        ("code-freeze-manifest", "code-freeze-manifest"),
        ("analytics-validation-receipt", "analytics-validation-receipt"),
        ("personas-validation-receipt", "personas-validation-receipt"),
        ("public-validation-receipt", "public-validation-receipt"),
        ("cases-manifest", "cases-manifest"),
        ("cases-index", "cases-index"),
    )
    for option, expected in path_sha_pairs:
        parser.add_argument(f"--{option}", required=True)
        parser.add_argument(f"--expected-{expected}-sha256", required=True)
    root_sha_pairs = (
        ("production-baseline-root", "production-baseline-manifest"),
        ("candidate-base-root", "candidate-base-manifest"),
        ("candidate-ledger-root", "candidate-ledger-manifest"),
        ("insights-root", "insights-manifest"),
        ("reports-root", "reports-manifest"),
        ("personas-root", "personas-manifest"),
        ("public-root", "public-inventory"),
    )
    for option, expected in root_sha_pairs:
        parser.add_argument(f"--{option}", required=True)
        parser.add_argument(f"--expected-{expected}-sha256", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--code-root", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = build_candidate_data_closure(args)
    except CandidateDataClosureError as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
