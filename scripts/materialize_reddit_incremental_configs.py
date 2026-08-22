#!/usr/bin/env python3
"""Bind reusable analytics/persona definitions to one immutable Base snapshot."""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any


VERSION_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,127}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
BASE_MANIFEST_V1 = "reddit_voc_site_snapshot_manifest_v1"
BASE_MANIFEST_V2 = "reddit_voc_site_snapshot_manifest_v2"
V1_DEBT_COUNT_FIELDS = (
    "cursor_outstanding",
    "page_pagination_outstanding",
    "partial_threads",
)
V2_UNION_COUNT_FIELDS = (
    "first_page_missing",
    "cursor_outstanding",
    "page_pagination_outstanding",
    "failed_reports",
    "partial_threads",
    "not_observed_threads",
)
V2_UNION_HASH_FIELDS = (
    "first_page_missing_lf_sha256",
    "cursor_outstanding_lf_sha256",
    "page_pagination_outstanding_lf_sha256",
    "failed_reports_lf_sha256",
    "partial_thread_ids_lf_sha256",
    "not_observed_thread_ids_lf_sha256",
)
V2_SOURCE_COUNT_FIELDS = (
    "first_page_missing",
    "cursor_outstanding",
    "page_pagination_outstanding",
    "failed_reports",
)
HYDRATION_SOURCE_COUNT_FIELDS = (
    "first_page_missing",
    "cursor_outstanding",
    "page_pagination_outstanding",
    "failed_reports",
    "partial_threads",
    "not_observed_threads",
)
LEDGER_MANIFEST_SCHEMA = "reddit_voc_candidate_ledger_manifest_v2"
LEDGER_MANIFEST_STATUS = "a2_identity_closed_with_explicit_coverage_debt"
LEDGER_RECEIPT_SCHEMA = "reddit_voc_candidate_ledger_validation_receipt_v1"


class IncrementalConfigError(ValueError):
    """A template or Base binding cannot produce candidate configuration."""


def _sha(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink():
        raise IncrementalConfigError(f"{label}_unsafe")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise IncrementalConfigError(f"{label}_missing") from exc
    if not resolved.is_file():
        raise IncrementalConfigError(f"{label}_not_file")
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IncrementalConfigError(f"{label}_invalid_json") from exc
    if not isinstance(value, dict):
        raise IncrementalConfigError(f"{label}_not_object")
    return value


def _write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(path, 0o600)


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _has_nonnegative_int_fields(value: object, fields: tuple[str, ...]) -> bool:
    if not isinstance(value, dict):
        return False
    return all(
        not isinstance(value.get(field), bool)
        and isinstance(value.get(field), int)
        and value[field] >= 0
        for field in fields
    )


def _coverage_debt(base: dict[str, Any]) -> dict[str, Any]:
    schema = base.get("schema_version")
    if schema not in {BASE_MANIFEST_V1, BASE_MANIFEST_V2}:
        raise IncrementalConfigError("base_manifest_schema_invalid")
    fusion = base.get("fusion_accounting")
    if not isinstance(fusion, dict):
        raise IncrementalConfigError("base_fusion_accounting_missing")
    if fusion.get("coverage_debt_is_not_zero_filled") is not True:
        raise IncrementalConfigError("base_coverage_debt_invalid")

    if schema == BASE_MANIFEST_V1:
        debt = fusion.get("v2_comment_coverage_debt")
        if not isinstance(debt, dict):
            raise IncrementalConfigError("base_coverage_debt_missing")
        if not _has_nonnegative_int_fields(debt, V1_DEBT_COUNT_FIELDS):
            raise IncrementalConfigError("base_coverage_debt_invalid")
        return debt

    debt = fusion.get("comment_coverage_debt_union")
    if not isinstance(debt, dict):
        raise IncrementalConfigError("base_coverage_debt_missing")
    source_counts = debt.get("source_counts")
    if not isinstance(source_counts, dict):
        raise IncrementalConfigError("base_coverage_debt_invalid")
    v2_counts = source_counts.get("v2")
    hydration_counts = source_counts.get("existing_post_hydration")
    failure_reason_counts = (
        hydration_counts.get("failure_reason_counts")
        if isinstance(hydration_counts, dict)
        else None
    )
    if (
        not _has_nonnegative_int_fields(debt, V2_UNION_COUNT_FIELDS)
        or any(
            not isinstance(debt.get(field), str)
            or SHA256_RE.fullmatch(debt[field]) is None
            for field in V2_UNION_HASH_FIELDS
        )
        or not _has_nonnegative_int_fields(v2_counts, V2_SOURCE_COUNT_FIELDS)
        or not _has_nonnegative_int_fields(
            hydration_counts, HYDRATION_SOURCE_COUNT_FIELDS
        )
        or not isinstance(failure_reason_counts, dict)
        or any(
            not isinstance(reason, str)
            or not reason
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
            for reason, count in failure_reason_counts.items()
        )
        or debt.get("key_union_not_numeric_sum") is not True
    ):
        raise IncrementalConfigError("base_coverage_debt_invalid")
    return debt


def _tree_contract(root: Path) -> dict[str, Any]:
    if not root.is_dir() or root.is_symlink():
        raise IncrementalConfigError("output_root_unsafe")
    directories: list[dict[str, int | str]] = []
    files: dict[str, dict[str, int | str]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise IncrementalConfigError("output_root_contains_symlink")
        if path.is_dir():
            directories.append(
                {"path": relative, "mode": path.stat().st_mode & 0o777}
            )
            continue
        if not path.is_file():
            raise IncrementalConfigError("output_root_contains_unsafe_entry")
        files[relative] = {
            "bytes": path.stat().st_size,
            "sha256": _sha(path),
            "mode": path.stat().st_mode & 0o777,
        }
    return {
        "root_mode": root.stat().st_mode & 0o777,
        "directories": directories,
        "files": files,
    }


def materialize_configs(
    *,
    base_dir: Path,
    coverage_template_path: Path,
    risk_template_path: Path,
    persona_template_path: Path,
    personas_dataset_version: str,
    candidate_ledger_manifest_path: Path,
    ledger_validation_receipt_path: Path,
    expected_ledger_validation_receipt_sha256: str,
) -> dict[str, Any]:
    if (
        not personas_dataset_version.startswith("reddit_voc_personas_")
        or VERSION_RE.fullmatch(personas_dataset_version) is None
    ):
        raise IncrementalConfigError("personas_dataset_version_invalid")
    base_manifest_path = base_dir / "manifest.json"
    base = _load(base_manifest_path, label="base_manifest")
    if base.get("all_checks_passed") is not True:
        raise IncrementalConfigError("base_not_validated")
    base_version = base.get("dataset_version")
    if not isinstance(base_version, str) or VERSION_RE.fullmatch(base_version) is None:
        raise IncrementalConfigError("base_dataset_version_invalid")
    base_sha = _sha(base_manifest_path)
    # Validate the Base's own deterministic coverage contract before checking
    # downstream lineage so callers receive the original root-cause error.
    debt = _coverage_debt(base)
    if SHA256_RE.fullmatch(expected_ledger_validation_receipt_sha256) is None:
        raise IncrementalConfigError("ledger_validation_receipt_expected_sha_invalid")
    ledger_manifest = _load(
        candidate_ledger_manifest_path, label="candidate_ledger_manifest"
    )
    ledger_manifest_sha = _sha(candidate_ledger_manifest_path)
    ledger_accounting = ledger_manifest.get("accounting")
    ledger_inputs = ledger_manifest.get("inputs")
    if (
        ledger_manifest.get("schema_version") != LEDGER_MANIFEST_SCHEMA
        or ledger_manifest.get("status") != LEDGER_MANIFEST_STATUS
        or not isinstance(ledger_accounting, dict)
        or ledger_accounting.get("unaccounted_total") != 0
        or not isinstance(ledger_inputs, dict)
        or ledger_inputs.get("candidate_base_manifest_sha256") != base_sha
        or ledger_manifest.get("production_unchanged") is not True
        or any(
            ledger_manifest.get(field) is not False
            for field in (
                "provider_call",
                "provider_attempt_made",
                "database_write",
                "remote_write",
                "deployment",
                "production_merge",
                "live_send",
            )
        )
    ):
        raise IncrementalConfigError("candidate_ledger_manifest_invalid")
    receipt = _load(
        ledger_validation_receipt_path, label="ledger_validation_receipt"
    )
    receipt_sha = _sha(ledger_validation_receipt_path)
    receipt_counts = receipt.get("counts")
    if receipt_sha != expected_ledger_validation_receipt_sha256:
        raise IncrementalConfigError("ledger_validation_receipt_sha_mismatch")
    if (
        receipt.get("schema_version") != LEDGER_RECEIPT_SCHEMA
        or receipt.get("status") != "passed"
        or receipt.get("candidate_ledger_manifest_sha256") != ledger_manifest_sha
        or not isinstance(receipt_counts, dict)
        or receipt_counts.get("unaccounted_total") != 0
        or receipt.get("production_unchanged") is not True
        or any(
            receipt.get(field) is not False
            for field in (
                "provider_call",
                "provider_attempt_made",
                "database_write",
                "remote_write",
                "deployment",
                "production_merge",
                "live_send",
            )
        )
    ):
        raise IncrementalConfigError("ledger_validation_receipt_invalid")
    fingerprint = base_sha[:12]
    tagging = base.get("tagging")
    semantic = base.get("semantic_boundaries")
    sources = base.get("source_boundaries")
    if not isinstance(tagging, dict) or not isinstance(semantic, dict) or not isinstance(sources, dict):
        raise IncrementalConfigError("base_contract_missing")
    v2 = sources.get("tencent_v2_search_hydrated")
    if not isinstance(v2, dict):
        raise IncrementalConfigError("base_v2_boundary_missing")
    cursor_debt = debt.get("cursor_outstanding")
    page_debt = debt.get("page_pagination_outstanding")
    assert isinstance(cursor_debt, int) and not isinstance(cursor_debt, bool)
    assert isinstance(page_debt, int) and not isinstance(page_debt, bool)
    debt_count_fields = (
        V2_UNION_COUNT_FIELDS
        if base.get("schema_version") == BASE_MANIFEST_V2
        else V1_DEBT_COUNT_FIELDS
    )
    has_comment_coverage_debt = any(
        debt[field] > 0 for field in debt_count_fields
    )

    coverage = deepcopy(_load(coverage_template_path, label="coverage_template"))
    if coverage.get("schema_version") != "reddit_voc_period_coverage_profile_v1":
        raise IncrementalConfigError("coverage_template_schema_invalid")
    coverage.update(
        {
            "profile_version": f"reddit-voc-observed-coverage-{fingerprint}",
            "applies_to_base_dataset_version": base_version,
            "applies_to_base_manifest_sha256": base_sha,
            "source_set_version": base_version,
            "tag_dictionary_version": tagging.get("dictionary_version"),
            "tag_dictionary_sha256": tagging.get("dictionary_sha256"),
            "product_catalog_sha256": semantic.get(
                "product_entity_ledger_sha256"
            ),
            "search_has_next_truncates_window": bool(cursor_debt or page_debt),
            "comment_coverage_status": (
                "mixed" if has_comment_coverage_debt else "thread_complete"
            ),
            "id_conflicts": 0,
            "source_missing": False,
            "recent_partition": False,
            "claim_scope": "frozen_observed_fused_snapshot_not_full_reddit_population",
        }
    )
    coverage["reason_codes"] = sorted(
        set(
            [
                str(value)
                for value in coverage.get("reason_codes", [])
                if isinstance(value, str) and value
            ]
            + ["incremental_candidate_coverage_debt_explicit"]
        )
    )

    risk = deepcopy(_load(risk_template_path, label="risk_template"))
    if risk.get("schema_version") != "reddit_voc_risk_theme_gate_policy_v1":
        raise IncrementalConfigError("risk_template_schema_invalid")
    if risk.get("status") != "draft":
        raise IncrementalConfigError("risk_template_must_remain_draft")
    risk.update(
        {
            "policy_version": f"reddit-voc-risk-theme-gate-candidate-{fingerprint}",
            "applies_to_base_dataset_version": base_version,
            "applies_to_base_manifest_sha256": base_sha,
            "candidate_basis": {
                "status": "recomputed_in_candidate_analytics",
                "base_dataset_version": base_version,
                "base_manifest_sha256": base_sha,
            },
        }
    )

    persona = deepcopy(_load(persona_template_path, label="persona_template"))
    if persona.get("schema_version") != "reddit_voc_persona_config_v1":
        raise IncrementalConfigError("persona_template_schema_invalid")
    persona.update(
        {
            "config_version": f"reddit_voc_evidence_personas_{fingerprint}",
            "dataset_version": personas_dataset_version,
        }
    )
    return {
        "coverage": coverage,
        "risk": risk,
        "personas": persona,
        "identity_gate": {
            "candidate_base_manifest_sha256": base_sha,
            "candidate_ledger_manifest_sha256": ledger_manifest_sha,
            "ledger_validation_receipt_sha256": receipt_sha,
            "input_evidence_sha256": receipt.get("input_evidence_sha256"),
            "unaccounted_total": 0,
        },
    }


def write_configs(output_root: Path, values: dict[str, Any]) -> dict[str, Any]:
    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{output_root.name}.staging-", dir=output_root.parent
        )
    )
    os.chmod(staging, 0o700)
    try:
        paths = {
            "coverage": staging / "coverage-profile.json",
            "risk": staging / "risk-gate-policy.json",
            "personas": staging / "personas-config.json",
        }
        for key, path in paths.items():
            _write(path, values[key])
        manifest = {
            "schema_version": "reddit_voc_incremental_candidate_config_manifest_v1",
            "files": {
                path.name: {"bytes": path.stat().st_size, "sha256": _sha(path)}
                for path in paths.values()
            },
            "identity_gate": values["identity_gate"],
            "boundaries": {
                "risk_policy_frozen": False,
                "provider_call": False,
                "database_write": False,
                "deploy": False,
                "live_send": False,
            },
        }
        _write(staging / "manifest.json", manifest)
        staging_contract = _tree_contract(staging)
        if _path_exists(output_root):
            if _tree_contract(output_root) != staging_contract:
                raise IncrementalConfigError("output_root_collision")
            status = "no_change"
        else:
            # Recheck immediately before the same-filesystem atomic rename so
            # a concurrent candidate cannot be overwritten silently.
            if _path_exists(output_root):
                raise IncrementalConfigError("output_root_collision")
            os.rename(staging, output_root)
            status = "created"
    except BaseException:
        if staging.exists() and not staging.is_symlink():
            shutil.rmtree(staging, ignore_errors=True)
        raise
    if staging.exists() and not staging.is_symlink():
        shutil.rmtree(staging)
    return {"status": status, **manifest}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", type=Path, required=True)
    parser.add_argument("--coverage-template", type=Path, required=True)
    parser.add_argument("--risk-template", type=Path, required=True)
    parser.add_argument("--persona-template", type=Path, required=True)
    parser.add_argument("--personas-dataset-version", required=True)
    parser.add_argument("--candidate-ledger-manifest", type=Path, required=True)
    parser.add_argument("--ledger-validation-receipt", type=Path, required=True)
    parser.add_argument(
        "--expected-ledger-validation-receipt-sha256", required=True
    )
    parser.add_argument("--output-root", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    values = materialize_configs(
        base_dir=args.base_dir.resolve(strict=True),
        coverage_template_path=args.coverage_template,
        risk_template_path=args.risk_template,
        persona_template_path=args.persona_template,
        personas_dataset_version=args.personas_dataset_version,
        candidate_ledger_manifest_path=args.candidate_ledger_manifest,
        ledger_validation_receipt_path=args.ledger_validation_receipt,
        expected_ledger_validation_receipt_sha256=(
            args.expected_ledger_validation_receipt_sha256
        ),
    )
    manifest = write_configs(args.output_root, values)
    print(
        json.dumps(
            {
                "schema_version": "reddit_voc_incremental_candidate_config_receipt_v1",
                "status": manifest["status"],
                "output_root": str(args.output_root),
                "files": manifest["files"],
                "risk_policy_frozen": False,
                "provider_call": False,
                "database_write": False,
                "deploy": False,
                "live_send": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
