#!/usr/bin/env python3
"""Build immutable Momcozy risk insights and daily/weekly/monthly reports.

The command reads one already-enriched site snapshot, verifies its manifest,
builds the A/B analytical contracts, and atomically publishes two versioned
local directories under a fresh output root.  It does not call a Provider,
write a database, deploy, or copy source body/author fields to the output.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Any, cast

from reddit_voc.risk_report_contracts import (
    InputContractError,
    build_contract_bundle,
    required_report_windows,
)


REQUIRED_SNAPSHOT_FILES = ("posts.json", "comments.json", "tag-dictionary.json")
LEGACY_INSIGHTS_FIELDS = (
    "headline",
    "signals",
    "reference_dimensions",
    "held_tags",
)


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_bytes(value))


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_contract(path: Path) -> dict[str, object]:
    return {"bytes": path.stat().st_size, "sha256": _sha256(path)}


def _harden_private_tree(root: Path) -> None:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("analytics staging root is unsafe")
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("analytics staging tree contains a symlink")
        if path.is_dir():
            os.chmod(path, 0o700)
        elif path.is_file():
            os.chmod(path, 0o600)
        else:
            raise ValueError("analytics staging tree contains an unsafe entry")
    os.chmod(root, 0o700)


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputContractError(
            "input JSON cannot be loaded", invalid_fields=[str(path)]
        ) from exc


def _load_object(path: Path, *, field: str) -> dict[str, object]:
    value = _load_json(path)
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise InputContractError(
            "input JSON object contract failed", invalid_fields=[field]
        )
    return cast(dict[str, object], value)


def _load_object_list(path: Path, *, field: str) -> list[dict[str, object]]:
    value = _load_json(path)
    if not isinstance(value, list):
        raise InputContractError(
            "input JSON list contract failed", invalid_fields=[field]
        )
    output: list[dict[str, object]] = []
    for index, row in enumerate(value):
        if not isinstance(row, dict) or not all(isinstance(key, str) for key in row):
            raise InputContractError(
                "input JSON list contract failed",
                invalid_fields=[f"{field}[{index}]"],
            )
        output.append(cast(dict[str, object], row))
    return output


def _verify_manifest_file(
    snapshot_dir: Path,
    files: dict[str, object],
    name: str,
) -> None:
    expected_value = files.get(name)
    if not isinstance(expected_value, dict):
        raise InputContractError(
            "snapshot manifest file contract failed",
            missing_fields=[f"manifest.files.{name}"],
        )
    expected = cast(dict[str, object], expected_value)
    path = snapshot_dir / name
    if not path.is_file():
        raise InputContractError(
            "snapshot file is missing", missing_fields=[f"snapshot.{name}"]
        )
    expected_bytes = expected.get("bytes")
    expected_sha = expected.get("sha256")
    invalid: list[str] = []
    if (
        isinstance(expected_bytes, bool)
        or not isinstance(expected_bytes, int)
        or path.stat().st_size != expected_bytes
    ):
        invalid.append(f"manifest.files.{name}.bytes")
    if not isinstance(expected_sha, str) or _sha256(path) != expected_sha:
        invalid.append(f"manifest.files.{name}.sha256")
    if invalid:
        raise InputContractError(
            "snapshot manifest verification failed", invalid_fields=invalid
        )


def load_verified_snapshot(
    snapshot_dir: Path,
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    dict[str, object],
    dict[str, object],
]:
    manifest_path = snapshot_dir / "manifest.json"
    manifest = _load_object(manifest_path, field="manifest")
    files_value = manifest.get("files")
    if not isinstance(files_value, dict):
        raise InputContractError(
            "snapshot manifest file contract failed",
            invalid_fields=["manifest.files"],
        )
    files = cast(dict[str, object], files_value)
    for name in REQUIRED_SNAPSHOT_FILES:
        _verify_manifest_file(snapshot_dir, files, name)
    dataset_version = manifest.get("dataset_version")
    generated_at = manifest.get("generated_at_utc")
    if not isinstance(dataset_version, str) or not dataset_version.strip():
        raise InputContractError(
            "snapshot identity contract failed",
            invalid_fields=["manifest.dataset_version"],
        )
    if not isinstance(generated_at, str) or not generated_at.strip():
        raise InputContractError(
            "snapshot identity contract failed",
            invalid_fields=["manifest.generated_at_utc"],
        )
    source_cutoffs: dict[str, object] = {}
    for field in (
        "source_cutoff_utc",
        "source_cutoffs",
        "source_boundaries",
        "semantic_boundaries",
        "rc_freeze",
    ):
        if field in manifest:
            source_cutoffs[field] = manifest[field]
    base_identity: dict[str, object] = {
        "dataset_version": dataset_version,
        "manifest_sha256": _sha256(manifest_path),
        "generated_at_utc": generated_at,
        "source_cutoffs": source_cutoffs,
    }
    canonical_counts = manifest.get("canonical_counts")
    if isinstance(canonical_counts, dict):
        quarantined = cast(dict[str, object], canonical_counts).get(
            "quarantined_comments"
        )
        if isinstance(quarantined, int) and not isinstance(quarantined, bool):
            base_identity["quarantined_comments"] = quarantined
    return (
        _load_object_list(snapshot_dir / "posts.json", field="posts"),
        _load_object_list(snapshot_dir / "comments.json", field="comments"),
        _load_object(snapshot_dir / "tag-dictionary.json", field="tag_dictionary"),
        base_identity,
    )


def normalise_semantic_governance(
    value: dict[str, object],
    *,
    source_sha256: str | None = None,
    source_name: str | None = None,
) -> dict[str, object]:
    source_audit = {
        "source_name": source_name,
        "sha256": source_sha256,
        "schema_version": value.get("schema_version"),
        "audit_version": value.get("audit_version"),
        "base_dataset_version": value.get("base_dataset_version"),
        "base_manifest_sha256": value.get("base_manifest_sha256"),
        "quality_gate": value.get("quality_gate"),
    }
    if {
        "governance_version",
        "promoted_tag_ids",
        "held_tag_ids",
    }.issubset(value):
        normalised: dict[str, object] = {
            "governance_version": value["governance_version"],
            "promoted_tag_ids": value["promoted_tag_ids"],
            "held_tag_ids": value["held_tag_ids"],
            "source_audit": value.get("source_audit") or source_audit,
        }
        if value.get("schema_version") == "reddit_voc_semantic_governance_projection_v1":
            normalised["schema_version"] = value.get("schema_version")
            normalised["source_sha256"] = source_sha256
            for field in (
                "projection_mode",
                "target_base",
                "dictionary_version",
                "dictionary_sha256",
                "identity_gate",
                "compatibility_summary",
                "tag_compatibility",
                "legacy_insights",
                "boundaries",
            ):
                normalised[field] = value.get(field)
        return normalised
    audit_summary = value.get("audit_summary") or value.get("summary")
    if isinstance(audit_summary, dict):
        summary = cast(dict[str, object], audit_summary)
        version = value.get("dataset_version") or value.get("audit_version")
        return {
            "governance_version": version,
            "promoted_tag_ids": summary.get("promoted_tag_ids"),
            "held_tag_ids": summary.get("held_tag_ids"),
            "source_audit": source_audit,
        }
    raise InputContractError(
        "semantic governance contract failed",
        missing_fields=[
            "semantic_governance.governance_version",
            "semantic_governance.promoted_tag_ids",
            "semantic_governance.held_tag_ids",
        ],
    )


def resolve_legacy_compatibility(
    semantic_governance: dict[str, object],
    *,
    base_identity: dict[str, object],
    tag_dictionary: dict[str, object],
    explicit_legacy_insights: dict[str, object] | None,
) -> dict[str, object] | None:
    """Return only a Base-bound compatibility projection for the v2 builder."""

    if semantic_governance.get("schema_version") != (
        "reddit_voc_semantic_governance_projection_v1"
    ):
        return explicit_legacy_insights
    if explicit_legacy_insights is not None:
        raise InputContractError(
            "semantic compatibility contract failed",
            invalid_fields=["legacy_insights.external_with_projection"],
        )
    invalid: list[str] = []
    if semantic_governance.get("projection_mode") != (
        "governance_projection_no_new_review"
    ):
        invalid.append("semantic_governance.projection_mode")
    target = semantic_governance.get("target_base")
    if not isinstance(target, dict):
        invalid.append("semantic_governance.target_base")
    else:
        if target.get("dataset_version") != base_identity.get("dataset_version"):
            invalid.append("semantic_governance.target_base.dataset_version")
        if target.get("manifest_sha256") != base_identity.get("manifest_sha256"):
            invalid.append("semantic_governance.target_base.manifest_sha256")
    if semantic_governance.get("dictionary_version") != tag_dictionary.get(
        "dictionary_version"
    ):
        invalid.append("semantic_governance.dictionary_version")
    if semantic_governance.get("dictionary_sha256") != tag_dictionary.get(
        "dictionary_sha256"
    ):
        invalid.append("semantic_governance.dictionary_sha256")
    identity_gate = semantic_governance.get("identity_gate")
    if not isinstance(identity_gate, dict):
        invalid.append("semantic_governance.identity_gate")
    else:
        for field in (
            "candidate_ledger_manifest_sha256",
            "ledger_validation_receipt_sha256",
        ):
            value = identity_gate.get(field)
            if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                invalid.append(f"semantic_governance.identity_gate.{field}")
        if identity_gate.get("unaccounted_total") != 0:
            invalid.append("semantic_governance.identity_gate.unaccounted_total")
    compatibility = semantic_governance.get("compatibility_summary")
    if not isinstance(compatibility, dict):
        invalid.append("semantic_governance.compatibility_summary")
    else:
        if compatibility.get("promoted_retention_gate_passed") is not True:
            invalid.append(
                "semantic_governance.compatibility_summary.promoted_retention_gate_passed"
            )
        if compatibility.get("promoted_source_assignments") != compatibility.get(
            "promoted_compatible_assignments"
        ):
            invalid.append(
                "semantic_governance.compatibility_summary.promoted_assignments"
            )
    boundaries = semantic_governance.get("boundaries")
    if not isinstance(boundaries, dict) or any(
        boundaries.get(field) is not False
        for field in (
            "new_review_performed",
            "provider_call",
            "database_write",
            "remote_write",
            "live_send",
            "deploy",
        )
    ) or not isinstance(boundaries, dict) or boundaries.get("production_unchanged") is not True:
        invalid.append("semantic_governance.boundaries")
    legacy = semantic_governance.get("legacy_insights")
    if not isinstance(legacy, dict):
        invalid.append("semantic_governance.legacy_insights")
    else:
        missing = [field for field in LEGACY_INSIGHTS_FIELDS if field not in legacy]
        if missing:
            invalid.extend(
                f"semantic_governance.legacy_insights.{field}" for field in missing
            )
        headline = legacy.get("headline")
        if not isinstance(headline, dict) or headline.get("reviewed_assignments") is not None:
            invalid.append(
                "semantic_governance.legacy_insights.headline.reviewed_assignments"
            )
        contract = legacy.get("compatibility_contract")
        source_audit = semantic_governance.get("source_audit")
        if not isinstance(contract, dict) or not isinstance(source_audit, dict):
            invalid.append(
                "semantic_governance.legacy_insights.compatibility_contract"
            )
        else:
            if contract.get("status") != (
                "current_base_recomputed_governance_projection"
            ):
                invalid.append(
                    "semantic_governance.legacy_insights.compatibility_contract.status"
                )
            if contract.get("current_base_manifest_sha256") != base_identity.get(
                "manifest_sha256"
            ):
                invalid.append(
                    "semantic_governance.legacy_insights.compatibility_contract.current_base_manifest_sha256"
                )
            if contract.get("source_semantic_audit_sha256") != source_audit.get(
                "sha256"
            ):
                invalid.append(
                    "semantic_governance.legacy_insights.compatibility_contract.source_semantic_audit_sha256"
                )
            if contract.get("new_review_performed") is not False:
                invalid.append(
                    "semantic_governance.legacy_insights.compatibility_contract.new_review_performed"
                )
    if invalid:
        raise InputContractError(
            "semantic compatibility contract failed", invalid_fields=invalid
        )
    return cast(dict[str, object], legacy)


def materialise_coverage_ledger(
    value: dict[str, object],
    *,
    as_of_utc: datetime,
    base_identity: dict[str, object],
    tag_dictionary: dict[str, object],
) -> dict[str, object]:
    """Expand a base-bound conservative profile into exact report windows."""

    if value.get("schema_version") == "reddit_voc_period_coverage_ledger_v1":
        return value
    if value.get("schema_version") != "reddit_voc_period_coverage_profile_v1":
        raise InputContractError(
            "coverage profile input contract failed",
            invalid_fields=["coverage_ledger.schema_version"],
        )
    required = {
        "profile_version",
        "applies_to_base_dataset_version",
        "applies_to_base_manifest_sha256",
        "query_profile_version",
        "source_set_version",
        "tag_dictionary_version",
        "tag_dictionary_sha256",
        "product_catalog_version",
        "product_catalog_sha256",
        "event_time_coverage",
        "search_has_next_truncates_window",
        "hydration_policy_version",
        "comment_coverage_status",
        "schema_drift",
        "id_conflicts",
        "source_missing",
        "recent_partition",
    }
    missing = sorted(required - set(value))
    if missing:
        raise InputContractError(
            "coverage profile input contract failed",
            missing_fields=[f"coverage_ledger.{field}" for field in missing],
        )
    invalid: list[str] = []
    if value["applies_to_base_dataset_version"] != base_identity.get(
        "dataset_version"
    ):
        invalid.append("coverage_ledger.applies_to_base_dataset_version")
    if value["applies_to_base_manifest_sha256"] != base_identity.get(
        "manifest_sha256"
    ):
        invalid.append("coverage_ledger.applies_to_base_manifest_sha256")
    if value["tag_dictionary_version"] != tag_dictionary.get(
        "dictionary_version"
    ):
        invalid.append("coverage_ledger.tag_dictionary_version")
    if value["tag_dictionary_sha256"] != tag_dictionary.get(
        "dictionary_sha256"
    ):
        invalid.append("coverage_ledger.tag_dictionary_sha256")
    source_cutoffs = base_identity.get("source_cutoffs")
    semantic_boundaries = (
        cast(dict[str, object], source_cutoffs).get("semantic_boundaries")
        if isinstance(source_cutoffs, dict)
        else None
    )
    expected_product_sha = (
        cast(dict[str, object], semantic_boundaries).get(
            "product_entity_ledger_sha256"
        )
        if isinstance(semantic_boundaries, dict)
        else None
    )
    if (
        expected_product_sha is not None
        and value["product_catalog_sha256"] != expected_product_sha
    ):
        invalid.append("coverage_ledger.product_catalog_sha256")
    if value["event_time_coverage"] not in {
        "complete",
        "partial",
        "unavailable",
    }:
        invalid.append("coverage_ledger.event_time_coverage")
    if value["comment_coverage_status"] not in {
        "thread_complete",
        "observed_first_page",
        "post_only",
        "mixed",
    }:
        invalid.append("coverage_ledger.comment_coverage_status")
    for field in (
        "search_has_next_truncates_window",
        "schema_drift",
        "source_missing",
        "recent_partition",
    ):
        if not isinstance(value[field], bool):
            invalid.append(f"coverage_ledger.{field}")
    id_conflicts = value["id_conflicts"]
    if (
        isinstance(id_conflicts, bool)
        or not isinstance(id_conflicts, int)
        or id_conflicts < 0
    ):
        invalid.append("coverage_ledger.id_conflicts")
    for field in (
        "profile_version",
        "query_profile_version",
        "source_set_version",
        "tag_dictionary_version",
        "tag_dictionary_sha256",
        "product_catalog_version",
        "product_catalog_sha256",
        "hydration_policy_version",
    ):
        if not isinstance(value[field], str) or not cast(str, value[field]).strip():
            invalid.append(f"coverage_ledger.{field}")
    if invalid:
        raise InputContractError(
            "coverage profile input contract failed",
            invalid_fields=invalid,
        )
    shared_fields = {
        field: value[field]
        for field in (
            "query_profile_version",
            "source_set_version",
            "tag_dictionary_version",
            "tag_dictionary_sha256",
            "product_catalog_version",
            "product_catalog_sha256",
            "event_time_coverage",
            "search_has_next_truncates_window",
            "hydration_policy_version",
            "comment_coverage_status",
            "schema_drift",
            "id_conflicts",
            "source_missing",
            "recent_partition",
        )
    }
    return {
        "schema_version": "reddit_voc_period_coverage_ledger_v1",
        "ledger_version": value["profile_version"],
        "source_profile": value,
        "windows": [
            {
                "start_utc": window.to_record()["start_utc"],
                "end_utc": window.to_record()["end_utc"],
                "is_closed": True,
                **shared_fields,
            }
            for window in required_report_windows(as_of_utc)
        ],
    }


def _semantic_audit_projection(
    semantic_governance: dict[str, object],
    *,
    base_identity: dict[str, object],
    dictionary_version: object,
    dictionary_sha256: object,
) -> dict[str, object]:
    promoted = cast(list[object], semantic_governance["promoted_tag_ids"])
    held = cast(list[object], semantic_governance["held_tag_ids"])
    compatibility = semantic_governance.get("compatibility_summary")
    source_reviewed = (
        cast(dict[str, object], compatibility).get("source_reviewed_assignments")
        if isinstance(compatibility, dict)
        else None
    )
    compatible_reviewed = (
        cast(dict[str, object], compatibility).get("compatible_source_assignments")
        if isinstance(compatibility, dict)
        else None
    )
    return {
        "schema_version": "reddit_voc_tag_semantic_audit_v2",
        "contract_extension": "reddit_voc_semantic_compatibility_projection_v1",
        "audit_version": semantic_governance["governance_version"],
        "projection_mode": semantic_governance.get("projection_mode"),
        "base_dataset_version": base_identity["dataset_version"],
        "base_manifest_sha256": base_identity["manifest_sha256"],
        "dictionary_version": dictionary_version,
        "dictionary_sha256": dictionary_sha256,
        "source_audit": semantic_governance.get("source_audit"),
        "identity_gate": semantic_governance.get("identity_gate"),
        "compatibility_summary": compatibility,
        "tag_compatibility": semantic_governance.get("tag_compatibility"),
        "summary": {
            "audited_tags": len(promoted) + len(held),
            "reviewed_assignments": None,
            "source_reviewed_assignments": source_reviewed,
            "compatible_source_assignments": compatible_reviewed,
            "promoted_tags": len(promoted),
            "held_tags": len(held),
            "promoted_tag_ids": promoted,
            "held_tag_ids": held,
            "status": "governance_projection_no_new_review",
        },
        "boundaries": {
            "raw_review_samples_included": False,
            "new_review_performed": False,
            "production_unchanged": True,
            "provider_call": False,
            "database_write": False,
            "live_send": False,
        },
    }


def _status(bundle: dict[str, object], risk_policy: dict[str, object] | None) -> str:
    reports = cast(dict[str, object], bundle["reports"])
    current = cast(dict[str, object], reports["current"])
    comparison_statuses = {
        cast(dict[str, object], cast(dict[str, object], report)["window"])[
            "comparison_status"
        ]
        for report in current.values()
    }
    if risk_policy is None or risk_policy.get("status") != "frozen":
        return "passed_provisional_risk_threshold"
    if comparison_statuses != {"comparable"}:
        return "passed_with_comparison_coverage_limits"
    return "passed"


def write_contract_bundle(
    output_root: Path,
    *,
    bundle: dict[str, object],
    base_identity: dict[str, object],
    tag_dictionary: dict[str, object],
    semantic_governance: dict[str, object],
    risk_gate_policy: dict[str, object] | None,
    as_of_utc: datetime,
) -> dict[str, object]:
    """Write both datasets below one fresh root and atomically publish it."""

    if output_root.exists():
        raise FileExistsError(f"output root already exists: {output_root}")
    insights = cast(dict[str, object], bundle["insights"])
    reports = cast(dict[str, object], bundle["reports"])
    insights_version = cast(str, insights["dataset_version"])
    reports_version = cast(str, reports["dataset_version"])
    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(
        tempfile.mkdtemp(
            prefix=f".{output_root.name}.staging-", dir=output_root.parent
        )
    )
    try:
        insights_dir = staging_root / insights_version
        reports_dir = staging_root / reports_version
        insights_path = insights_dir / "insights.json"
        _write_json(insights_path, insights)
        semantic_audit = _semantic_audit_projection(
            semantic_governance,
            base_identity=base_identity,
            dictionary_version=tag_dictionary.get("dictionary_version"),
            dictionary_sha256=tag_dictionary.get("dictionary_sha256"),
        )
        semantic_path = insights_dir / "semantic-audit.json"
        _write_json(semantic_path, semantic_audit)
        promoted = cast(list[object], semantic_governance["promoted_tag_ids"])
        held = cast(list[object], semantic_governance["held_tag_ids"])
        compatibility = semantic_governance.get("compatibility_summary")
        build_status = _status(bundle, risk_gate_policy)
        audit_summary = {
            "audited_tags": len(promoted) + len(held),
            "reviewed_assignments": None,
            "source_reviewed_assignments": (
                cast(dict[str, object], compatibility).get(
                    "source_reviewed_assignments"
                )
                if isinstance(compatibility, dict)
                else None
            ),
            "compatible_source_assignments": (
                cast(dict[str, object], compatibility).get(
                    "compatible_source_assignments"
                )
                if isinstance(compatibility, dict)
                else None
            ),
            "promoted_tags": len(promoted),
            "held_tags": len(held),
            "promoted_tag_ids": promoted,
            "held_tag_ids": held,
            "status": build_status,
        }
        insights_manifest = {
            "schema_version": "reddit_voc_insights_manifest_v1",
            "contract_extension": "reddit_voc_insights_manifest_v2",
            "dataset_version": insights_version,
            "delivery_mode": "versioned_static_insights_overlay",
            "generated_at_utc": as_of_utc.astimezone(timezone.utc).isoformat(),
            "base_dataset_version": base_identity["dataset_version"],
            "base_manifest_sha256": base_identity["manifest_sha256"],
            "reports_dataset_version": reports_version,
            "dictionary_version": tag_dictionary.get("dictionary_version"),
            "dictionary_sha256": tag_dictionary.get("dictionary_sha256"),
            "semantic_governance_version": semantic_governance["governance_version"],
            "semantic_source_audit": semantic_governance.get("source_audit"),
            "semantic_governance_sha256": semantic_governance.get("source_sha256"),
            "identity_gate": semantic_governance.get("identity_gate"),
            "status": build_status,
            "audit_summary": audit_summary,
            "files": {
                "insights.json": _file_contract(insights_path),
                "semantic-audit.json": _file_contract(semantic_path),
            },
            "boundaries": {
                "scope": "momcozy_risk_command_center_and_report_booklets",
                "labels_outside_promoted_set_provisional": True,
                "independent_human_review": False,
                "new_review_performed": False,
                "production_unchanged": True,
                "provider_call": False,
                "database_write": False,
                "live_send": False,
                "deploy": False,
            },
        }
        insights_manifest_path = insights_dir / "manifest.json"
        _write_json(insights_manifest_path, insights_manifest)

        index = reports["index"]
        index_path = reports_dir / "report-index.json"
        _write_json(index_path, index)
        by_path = cast(dict[str, object], reports["by_path"])
        for relative_path, report in sorted(by_path.items()):
            _write_json(reports_dir / relative_path, report)
        report_files = {
            "report-index.json": _file_contract(index_path),
            **{
                relative_path: _file_contract(reports_dir / relative_path)
                for relative_path in sorted(by_path)
            },
        }
        reports_manifest = {
            "schema_version": "reddit_voc_reports_manifest_v1",
            "contract_extension": "reddit_voc_reports_manifest_v2",
            "dataset_version": reports_version,
            "delivery_mode": "versioned_static_reports",
            "generated_at_utc": as_of_utc.astimezone(timezone.utc).isoformat(),
            "base_dataset_version": base_identity["dataset_version"],
            "base_manifest_sha256": base_identity["manifest_sha256"],
            "insights_dataset_version": insights_version,
            "insights_manifest_sha256": _sha256(insights_manifest_path),
            "dictionary_version": tag_dictionary.get("dictionary_version"),
            "dictionary_sha256": tag_dictionary.get("dictionary_sha256"),
            "semantic_source_audit": semantic_governance.get("source_audit"),
            "semantic_governance_sha256": semantic_governance.get("source_sha256"),
            "identity_gate": semantic_governance.get("identity_gate"),
            "report_count": len(by_path),
            "promoted_tag_ids": promoted,
            "held_tag_ids_excluded": held,
            "status": build_status,
            "files": report_files,
            "boundaries": {
                "production_unchanged": True,
                "provider_call": False,
                "database_write": False,
                "live_send": False,
                "webhook_send": False,
                "deploy": False,
                "schedule_change": False,
                "independent_human_review": False,
                "consumer_card_is_reference_not_persona_id": True,
                "persona_tags_generated": False,
                "market_share_supported": False,
                "roi_supported": False,
                "trend_claim_supported": build_status == "passed",
            },
        }
        reports_manifest_path = reports_dir / "manifest.json"
        _write_json(reports_manifest_path, reports_manifest)
        _harden_private_tree(staging_root)
        os.replace(staging_root, output_root)
        return {
            "status": build_status,
            "insights_dataset_version": insights_version,
            "insights_manifest_sha256": _sha256(
                output_root / insights_version / "manifest.json"
            ),
            "reports_dataset_version": reports_version,
            "reports_manifest_sha256": _sha256(
                output_root / reports_version / "manifest.json"
            ),
            "report_count": len(by_path),
            "production_unchanged": True,
            "provider_call": False,
            "database_write": False,
            "live_send": False,
            "deploy": False,
        }
    except Exception:
        if staging_root.exists():
            shutil.rmtree(staging_root)
        raise


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--as-of-utc must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _field_pattern_counts(values: tuple[str, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        pattern = re.sub(r"\[(?:\d+)\]", "[*]", value)
        counts[pattern] = counts.get(pattern, 0) + 1
    return dict(sorted(counts.items()))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--semantic-governance", type=Path, required=True)
    parser.add_argument("--legacy-insights", type=Path)
    parser.add_argument("--coverage-ledger", type=Path)
    parser.add_argument("--risk-gate-policy", type=Path)
    parser.add_argument("--insights-dataset-version", required=True)
    parser.add_argument("--reports-dataset-version", required=True)
    parser.add_argument("--as-of-utc", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        as_of_utc = _parse_datetime(args.as_of_utc)
        posts, comments, tag_dictionary, base_identity = load_verified_snapshot(
            args.snapshot_dir.resolve(strict=True)
        )
        semantic_path = args.semantic_governance.resolve(strict=True)
        semantic_governance = normalise_semantic_governance(
            _load_object(semantic_path, field="semantic_governance"),
            source_sha256=_sha256(semantic_path),
            source_name=semantic_path.name,
        )
        explicit_legacy_insights = (
            _load_object(
                args.legacy_insights.resolve(strict=True),
                field="legacy_insights",
            )
            if args.legacy_insights
            else None
        )
        legacy_insights = resolve_legacy_compatibility(
            semantic_governance,
            base_identity=base_identity,
            tag_dictionary=tag_dictionary,
            explicit_legacy_insights=explicit_legacy_insights,
        )
        coverage_ledger = (
            materialise_coverage_ledger(
                _load_object(
                    args.coverage_ledger.resolve(strict=True),
                    field="coverage_ledger",
                ),
                as_of_utc=as_of_utc,
                base_identity=base_identity,
                tag_dictionary=tag_dictionary,
            )
            if args.coverage_ledger
            else None
        )
        risk_gate_policy = (
            _load_object(
                args.risk_gate_policy.resolve(strict=True),
                field="risk_gate_policy",
            )
            if args.risk_gate_policy
            else None
        )
        bundle = build_contract_bundle(
            posts=posts,
            comments=comments,
            tag_dictionary=tag_dictionary,
            semantic_governance=semantic_governance,
            base_identity=base_identity,
            insights_dataset_version=args.insights_dataset_version,
            reports_dataset_version=args.reports_dataset_version,
            as_of_utc=as_of_utc,
            coverage_ledger=coverage_ledger,
            risk_gate_policy=risk_gate_policy,
            legacy_insights=legacy_insights,
        )
        receipt = write_contract_bundle(
            args.output_root,
            bundle=bundle,
            base_identity=base_identity,
            tag_dictionary=tag_dictionary,
            semantic_governance=semantic_governance,
            risk_gate_policy=risk_gate_policy,
            as_of_utc=as_of_utc,
        )
    except InputContractError as exc:
        print(
            json.dumps(
                {
                    "status": "blocked_input_contract",
                    "missing_field_occurrences": len(exc.missing_fields),
                    "missing_field_patterns": _field_pattern_counts(
                        exc.missing_fields
                    ),
                    "invalid_field_occurrences": len(exc.invalid_fields),
                    "invalid_field_patterns": _field_pattern_counts(
                        exc.invalid_fields
                    ),
                    "production_unchanged": True,
                    "provider_call": False,
                    "database_write": False,
                    "live_send": False,
                    "deploy": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
