#!/usr/bin/env python3
"""Independently validate the Reddit VOC static insights overlay."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any


V3_INSIGHTS_SCHEMA = "reddit_voc_insights_v3"
V3_INSIGHTS_MANIFEST_SCHEMA = "reddit_voc_insights_manifest_v3"
V3_BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}


class V3InsightsValidationError(ValueError):
    """A V3 insights fixture failed independent validation."""


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate(overlay_dir: Path, base_snapshot_dir: Path) -> dict[str, Any]:
    manifest = _load(overlay_dir / "manifest.json")
    audit = _load(overlay_dir / "semantic-audit.json")
    insights = _load(overlay_dir / "insights.json")
    base_manifest_path = base_snapshot_dir / "manifest.json"
    base_manifest = _load(base_manifest_path)
    base_aggregates = _load(base_snapshot_dir / "aggregates.json")

    _check(
        manifest["schema_version"] == "reddit_voc_insights_manifest_v1",
        "manifest schema mismatch",
    )
    _check(audit["schema_version"] == "reddit_voc_tag_semantic_audit_v1", "audit schema mismatch")
    _check(insights["schema_version"] == "reddit_voc_insights_v1", "insights schema mismatch")
    _check(manifest["dataset_version"] == insights["dataset_version"], "overlay version mismatch")
    _check(
        manifest["base_dataset_version"]
        == audit["base_dataset_version"]
        == insights["base_dataset_version"]
        == base_manifest["dataset_version"],
        "base dataset version mismatch",
    )
    _check(
        manifest["base_manifest_sha256"]
        == audit["base_manifest_sha256"]
        == _sha256(base_manifest_path),
        "base manifest hash mismatch",
    )

    expected_files = {"semantic-audit.json", "insights.json"}
    _check(set(manifest["files"]) == expected_files, "overlay file set mismatch")
    for name in expected_files:
        path = overlay_dir / name
        expected = manifest["files"][name]
        _check(path.stat().st_size == expected["bytes"], f"byte mismatch: {name}")
        _check(_sha256(path) == expected["sha256"], f"sha256 mismatch: {name}")

    tags = audit["tags"]
    _check(len(tags) == audit["summary"]["audited_tags"] == 10, "audited tag count mismatch")
    _check(
        sum(len(tag["samples"]) for tag in tags)
        == audit["summary"]["reviewed_assignments"]
        == 100,
        "reviewed assignment count mismatch",
    )
    _check(
        all(
            sample["review"]["label_verdict"] in {"correct", "incorrect", "ambiguous"}
            and sample["review"]["taxonomy_fit"] in {"fit", "mismatch", "ambiguous"}
            and sample["review"]["reason_code"] != "pending"
            for tag in tags
            for sample in tag["samples"]
        ),
        "pending or invalid review decision",
    )

    promoted = {tag["tag_id"] for tag in tags if tag["promotion_status"] == "promoted"}
    held = {tag["tag_id"] for tag in tags if tag["promotion_status"] == "held"}
    _check(promoted == set(audit["summary"]["promoted_tag_ids"]), "audit promoted set mismatch")
    _check(held == set(audit["summary"]["held_tag_ids"]), "audit held set mismatch")
    _check(promoted == {signal["tag_id"] for signal in insights["signals"]}, "insight promoted set mismatch")
    _check(held == {tag["tag_id"] for tag in insights["held_tags"]}, "insight held set mismatch")
    _check(promoted | held == {tag["tag_id"] for tag in tags}, "audit disposition gap")
    _check(not (promoted & held), "promoted/held overlap")
    _check(
        all(all(tag["gate_checks"].values()) for tag in tags if tag["tag_id"] in promoted),
        "promoted tag failed gate",
    )
    _check(
        all(not all(tag["gate_checks"].values()) for tag in tags if tag["tag_id"] in held),
        "held tag unexpectedly passed gate",
    )

    base_top_tags = {
        row["tag_id"]: row for row in base_aggregates["tagging"]["top_tags"]
    }
    for signal in insights["signals"]:
        base = base_top_tags[signal["tag_id"]]
        _check(signal["matched_posts"] == base["post_entities"], "post signal count mismatch")
        _check(signal["matched_comments"] == base["comment_entities"], "comment signal count mismatch")
        _check(signal["matched_entities"] == base["total_entities"], "signal total mismatch")
        _check(signal["evidence_examples"], "promoted signal lacks evidence")
        _check(
            signal["dictionary_reference"]["consumer_card"]
            and signal["dictionary_reference"]["aipl_node"],
            "dictionary reference incomplete",
        )

    boundaries = manifest["boundaries"]
    _check(boundaries["production_unchanged"] is True, "production boundary mismatch")
    _check(boundaries["provider_call"] is False, "provider boundary mismatch")
    _check(boundaries["database_write"] is False, "database boundary mismatch")
    _check(boundaries["live_send"] is False, "live-send boundary mismatch")
    _check(boundaries["independent_human_review"] is False, "human review overclaim")
    interpretation = insights["interpretation_boundaries"]
    _check(interpretation["consumer_card_is_reference_not_persona_id"] is True, "persona boundary missing")
    _check(interpretation["persona_tags_generated"] is False, "persona generation overclaim")
    _check(interpretation["market_share_supported"] is False, "market-share overclaim")
    _check(interpretation["roi_supported"] is False, "ROI overclaim")

    checks = {
        "schema_and_version_binding": True,
        "base_snapshot_hash_binding": True,
        "overlay_file_hashes": True,
        "review_completeness": True,
        "promotion_gate_integrity": True,
        "base_population_reconciliation": True,
        "dictionary_reference_and_persona_boundary": True,
        "side_effect_boundaries": True,
    }
    return {
        "schema_version": "reddit_voc_insights_validation_v1",
        "validated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_version": manifest["dataset_version"],
        "status": "passed",
        "checks": checks,
        "counts": {
            "audited_tags": len(tags),
            "reviewed_assignments": 100,
            "promoted_tags": len(promoted),
            "held_tags": len(held),
        },
        "production_unchanged": True,
        "provider_call": False,
        "database_write": False,
        "live_send": False,
        "independent_human_review": False,
    }


def _v3_canonical_bytes(value: Any) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise V3InsightsValidationError(
            "V3 insights document is not canonical-JSON serializable"
        ) from exc


def _v3_load_canonical(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = path.read_bytes()
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V3InsightsValidationError(f"{label} is unreadable") from exc
    if not isinstance(value, dict) or payload != _v3_canonical_bytes(value):
        raise V3InsightsValidationError(f"{label} is not canonical JSON")
    return value


def validate_v3_insights_snapshot(
    overlay_dir: Path,
    reports_dir: Path,
    metrics_root: Path,
    metrics_validation_receipt_path: Path,
    period_series: dict[str, Any],
    evidence_registry: dict[str, Any],
    *,
    expected_metrics_manifest_sha256: str,
    expected_metrics_receipt_sha256: str,
) -> dict[str, Any]:
    """Validate report lineage, six-part evidence binding, and exact replay."""

    from scripts.build_reddit_insights_snapshot import (
        V3InsightsBuildError,
        build_v3_insights_snapshot,
    )
    from scripts.build_reddit_reports_snapshot import (
        V3_REPORT_PATHS,
        load_v3_metrics_binding,
    )
    from scripts.validate_reddit_reports_snapshot import (
        V3ReportsValidationError,
        validate_v3_reports_snapshot,
    )

    try:
        validate_v3_reports_snapshot(
            reports_dir,
            metrics_root,
            metrics_validation_receipt_path,
            period_series,
            expected_metrics_manifest_sha256=expected_metrics_manifest_sha256,
            expected_metrics_receipt_sha256=expected_metrics_receipt_sha256,
        )
        binding = load_v3_metrics_binding(
            metrics_root,
            metrics_validation_receipt_path,
            expected_manifest_sha256=expected_metrics_manifest_sha256,
            expected_receipt_sha256=expected_metrics_receipt_sha256,
        )
    except (ValueError, V3ReportsValidationError) as exc:
        raise V3InsightsValidationError(str(exc)) from exc
    report_manifest = _v3_load_canonical(
        Path(reports_dir) / "manifest.json", "V3 reports manifest"
    )
    report_index = _v3_load_canonical(
        Path(reports_dir) / "report-index.json", "V3 report index"
    )
    reports = {
        name: _v3_load_canonical(Path(reports_dir) / name, name)
        for name in V3_REPORT_PATHS
    }

    overlay_dir = Path(overlay_dir)
    if overlay_dir.is_symlink() or not overlay_dir.is_dir():
        raise V3InsightsValidationError("V3 insights root is invalid")
    if {path.name for path in overlay_dir.iterdir()} != {
        "insights.json",
        "manifest.json",
    } or any(path.is_symlink() or not path.is_file() for path in overlay_dir.iterdir()):
        raise V3InsightsValidationError("V3 insights root file set is invalid")
    manifest = _v3_load_canonical(overlay_dir / "manifest.json", "V3 insights manifest")
    insights = _v3_load_canonical(overlay_dir / "insights.json", "V3 insights")
    if (
        manifest.get("schema_version") != V3_INSIGHTS_MANIFEST_SCHEMA
        or manifest.get("artifact_stage") != "fixture_insights"
        or manifest.get("status") != "fixture_only_waiting_for_periodized_metrics"
        or manifest.get("fixture_only") is not True
        or manifest.get("promotable") is not False
        or manifest.get("boundaries") != V3_BOUNDARIES
        or manifest.get("metrics_manifest_sha256")
        != expected_metrics_manifest_sha256
        or manifest.get("metrics_validation_receipt_sha256")
        != expected_metrics_receipt_sha256
    ):
        raise V3InsightsValidationError("V3 insights manifest contract is invalid")
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != {"insights.json"}:
        raise V3InsightsValidationError("V3 insights manifest file set is invalid")
    record = files["insights.json"]
    insights_path = overlay_dir / "insights.json"
    if (
        not isinstance(record, dict)
        or set(record) != {"bytes", "sha256"}
        or record.get("bytes") != insights_path.stat().st_size
        or record.get("sha256") != _sha256(insights_path)
    ):
        raise V3InsightsValidationError("V3 insights file integrity mismatch")
    if (
        insights.get("schema_version") != V3_INSIGHTS_SCHEMA
        or insights.get("fixture_only") is not True
        or insights.get("boundaries") != V3_BOUNDARIES
        or insights.get("storyline_count") != len(insights.get("storylines", []))
    ):
        raise V3InsightsValidationError("V3 insights document contract is invalid")
    required_sections = {
        "signal",
        "root_cause",
        "counter_intuitive",
        "impact",
        "action",
        "monitoring",
    }
    for storyline in insights["storylines"]:
        if set(storyline.get("sections", {})) != required_sections:
            raise V3InsightsValidationError("V3 storyline section set is invalid")
        signal = storyline["sections"]["signal"]
        if signal.get("status") == "unavailable" and (
            signal.get("direction") is not None
            or storyline.get("direction_claim_supported") is not False
        ):
            raise V3InsightsValidationError(
                "unavailable V3 storyline emitted a direction"
            )
        root_cause = storyline["sections"]["root_cause"]
        if bool(root_cause.get("evidence_ids")) != root_cause.get("supported"):
            raise V3InsightsValidationError("V3 root-cause evidence flag mismatch")

    try:
        expected_insights, expected_manifest = build_v3_insights_snapshot(
            binding,
            reports,
            report_index,
            report_manifest,
            evidence_registry,
        )
    except V3InsightsBuildError as exc:
        raise V3InsightsValidationError(str(exc)) from exc
    if insights != expected_insights:
        raise V3InsightsValidationError(
            "V3 insights deterministic replay mismatch"
        )
    if manifest != expected_manifest:
        raise V3InsightsValidationError(
            "V3 insights manifest deterministic replay mismatch"
        )
    return {
        "boundaries": dict(V3_BOUNDARIES),
        "deterministic_full_byte_replay": True,
        "fixture_only": True,
        "metrics_manifest_sha256": expected_metrics_manifest_sha256,
        "metrics_validation_receipt_sha256": expected_metrics_receipt_sha256,
        "promotable": False,
        "schema_version": "reddit_voc_insights_validation_receipt_v3",
        "status": "passed_fixture_only",
        "storyline_count": insights["storyline_count"],
    }


def validate_v3_formal_insights_snapshot(
    overlay_dir: Path,
    reports_dir: Path,
    reports_validation_receipt_path: Path,
    metrics_input_manifest_path: Path,
    metrics_root: Path,
    metrics_validation_receipt_path: Path,
    *,
    expected_metrics_input_manifest_sha256: str,
    expected_metrics_candidate_manifest_sha256: str,
    expected_metrics_receipt_sha256: str,
    expected_coverage_attestation_sha256: str | None,
    expected_reports_manifest_sha256: str,
    expected_reports_receipt_sha256: str,
) -> dict[str, Any]:
    """Replay formal reports and storylines before making insights promotable."""

    from scripts.build_reddit_insights_snapshot import (
        V3InsightsBuildError,
        build_v3_formal_insights_snapshot,
    )
    from scripts.build_reddit_reports_snapshot import (
        V3_REPORT_PATHS,
        load_v3_formal_metrics_binding,
    )
    from scripts.validate_reddit_reports_snapshot import (
        validate_v3_formal_reports_snapshot,
    )

    reports_receipt_path = Path(reports_validation_receipt_path)
    if (
        reports_receipt_path.is_symlink()
        or not reports_receipt_path.is_file()
        or _sha256(reports_receipt_path) != expected_reports_receipt_sha256
    ):
        raise V3InsightsValidationError("formal reports receipt SHA mismatch")
    reports_receipt = _v3_load_canonical(
        reports_receipt_path, "formal reports validation receipt"
    )
    replayed_reports_receipt = validate_v3_formal_reports_snapshot(
        reports_dir,
        metrics_input_manifest_path,
        metrics_root,
        metrics_validation_receipt_path,
        expected_metrics_input_manifest_sha256=expected_metrics_input_manifest_sha256,
        expected_metrics_candidate_manifest_sha256=expected_metrics_candidate_manifest_sha256,
        expected_metrics_receipt_sha256=expected_metrics_receipt_sha256,
        expected_coverage_attestation_sha256=expected_coverage_attestation_sha256,
    )
    if reports_receipt != replayed_reports_receipt:
        raise V3InsightsValidationError("formal reports receipt replay mismatch")
    reports_dir = Path(reports_dir)
    report_manifest_path = reports_dir / "manifest.json"
    if _sha256(report_manifest_path) != expected_reports_manifest_sha256:
        raise V3InsightsValidationError("formal reports manifest SHA mismatch")
    report_manifest = _v3_load_canonical(
        report_manifest_path, "formal reports manifest"
    )
    report_index = _v3_load_canonical(
        reports_dir / "report-index.json", "formal report index"
    )
    reports = {
        name: _v3_load_canonical(reports_dir / name, name)
        for name in V3_REPORT_PATHS
    }
    try:
        binding = load_v3_formal_metrics_binding(
            metrics_input_manifest_path,
            metrics_root,
            metrics_validation_receipt_path,
            expected_input_manifest_sha256=expected_metrics_input_manifest_sha256,
            expected_candidate_manifest_sha256=expected_metrics_candidate_manifest_sha256,
            expected_receipt_sha256=expected_metrics_receipt_sha256,
            expected_coverage_attestation_sha256=expected_coverage_attestation_sha256,
        )
    except ValueError as exc:
        raise V3InsightsValidationError(str(exc)) from exc

    comparison_contract_proven = expected_coverage_attestation_sha256 is not None
    expected_comparison_basis = (
        "owner_attested_dataset_scope_window"
        if comparison_contract_proven
        else "not_owner_attested"
    )
    expected_completeness = 100 if comparison_contract_proven else None

    overlay_dir = Path(overlay_dir)
    if overlay_dir.is_symlink() or not overlay_dir.is_dir():
        raise V3InsightsValidationError("formal insights root is invalid")
    if {path.name for path in overlay_dir.iterdir()} != {
        "insights.json",
        "manifest.json",
    } or any(path.is_symlink() or not path.is_file() for path in overlay_dir.iterdir()):
        raise V3InsightsValidationError("formal insights root file set is invalid")
    manifest = _v3_load_canonical(
        overlay_dir / "manifest.json", "formal insights manifest"
    )
    insights = _v3_load_canonical(
        overlay_dir / "insights.json", "formal insights"
    )
    if (
        manifest.get("schema_version") != V3_INSIGHTS_MANIFEST_SCHEMA
        or manifest.get("artifact_stage") != "insights_candidate"
        or manifest.get("status") != "candidate_built"
        or manifest.get("consumption_status")
        != "blocked_pending_independent_validation"
        or manifest.get("independent_validation_status") != "pending"
        or manifest.get("promotable") is not False
        or manifest.get("fixture_only") is not False
        or manifest.get("boundaries") != V3_BOUNDARIES
        or manifest.get("comparison_contract_proven")
        is not comparison_contract_proven
        or manifest.get("comparison_contract_basis")
        != expected_comparison_basis
        or manifest.get("completeness_percent") != expected_completeness
        or manifest.get("data_owner_coverage_attestation_sha256")
        != expected_coverage_attestation_sha256
        or manifest.get("metrics_input_manifest_sha256")
        != expected_metrics_input_manifest_sha256
        or manifest.get("metrics_candidate_manifest_sha256")
        != expected_metrics_candidate_manifest_sha256
        or manifest.get("metrics_validation_receipt_sha256")
        != expected_metrics_receipt_sha256
        or manifest.get("report_manifest_sha256")
        != expected_reports_manifest_sha256
        or manifest.get("report_validation_receipt_sha256")
        != expected_reports_receipt_sha256
        or manifest.get("coverage_attestation") != binding["coverage_attestation"]
    ):
        raise V3InsightsValidationError("formal insights manifest contract is invalid")
    files = manifest.get("files")
    insights_path = overlay_dir / "insights.json"
    if not isinstance(files, dict) or set(files) != {"insights.json"}:
        raise V3InsightsValidationError("formal insights file set is invalid")
    record = files["insights.json"]
    if (
        not isinstance(record, dict)
        or set(record) != {"bytes", "sha256"}
        or record.get("bytes") != insights_path.stat().st_size
        or record.get("sha256") != _sha256(insights_path)
    ):
        raise V3InsightsValidationError("formal insights file integrity mismatch")
    if (
        insights.get("schema_version") != V3_INSIGHTS_SCHEMA
        or insights.get("fixture_only") is not False
        or insights.get("comparison_contract_proven")
        is not comparison_contract_proven
        or insights.get("comparison_contract_basis")
        != expected_comparison_basis
        or insights.get("completeness_percent") != expected_completeness
        or insights.get("coverage_attestation") != binding["coverage_attestation"]
        or insights.get("storyline_count") != len(insights.get("storylines", []))
        or insights.get("analysis_frame", {}).get("primary_brand") != "Momcozy"
        or insights.get("analysis_frame", {}).get("comparison_brand_role")
        != "competitor_union"
    ):
        raise V3InsightsValidationError("formal insights document contract is invalid")
    required_sections = {
        "signal",
        "root_cause",
        "counter_intuitive",
        "impact",
        "action",
        "monitoring",
    }
    for storyline in insights["storylines"]:
        if set(storyline.get("sections", {})) != required_sections:
            raise V3InsightsValidationError("formal storyline section set is invalid")
        signal = storyline["sections"]["signal"]
        if signal.get("status") == "unavailable" and (
            signal.get("direction") is not None
            or storyline.get("direction_claim_supported") is not False
        ):
            raise V3InsightsValidationError("unavailable formal storyline emitted direction")
        counter = storyline["sections"]["counter_intuitive"]
        if counter.get("supported") is False and not counter.get("reason_codes"):
            raise V3InsightsValidationError("formal storyline unavailable reason is missing")
    for brand_health in insights.get("brand_health", {}).values():
        for row in brand_health.get("rows", []):
            if row.get("status") == "unavailable" and (
                row.get("value") is not None or row.get("display") != "—"
            ):
                raise V3InsightsValidationError("formal brand health fabricated a value")
    try:
        expected_insights, expected_manifest = build_v3_formal_insights_snapshot(
            binding,
            reports,
            report_index,
            report_manifest,
            reports_receipt,
            report_validation_receipt_sha256=expected_reports_receipt_sha256,
        )
    except V3InsightsBuildError as exc:
        raise V3InsightsValidationError(str(exc)) from exc
    if insights != expected_insights:
        raise V3InsightsValidationError("formal insights deterministic replay mismatch")
    if manifest != expected_manifest:
        raise V3InsightsValidationError("formal insights manifest deterministic replay mismatch")
    return {
        "boundaries": dict(V3_BOUNDARIES),
        "bundle_manifest_sha256": _sha256(overlay_dir / "manifest.json"),
        "comparison_contract_basis": expected_comparison_basis,
        "comparison_contract_proven": comparison_contract_proven,
        "completeness_percent": expected_completeness,
        "data_owner_coverage_attestation_sha256": expected_coverage_attestation_sha256,
        "deterministic_full_byte_replay": True,
        "metrics_candidate_manifest_sha256": expected_metrics_candidate_manifest_sha256,
        "metrics_input_manifest_sha256": expected_metrics_input_manifest_sha256,
        "metrics_validation_receipt_sha256": expected_metrics_receipt_sha256,
        "promotable": True,
        "report_manifest_sha256": expected_reports_manifest_sha256,
        "report_validation_receipt_sha256": expected_reports_receipt_sha256,
        "schema_version": "reddit_voc_insights_validation_receipt_v3",
        "status": "passed_candidate_only",
        "storyline_count": insights["storyline_count"],
        "storyline_summary": insights["storyline_summary"],
    }


def write_v3_insights_validation_receipt(
    path: Path, receipt: dict[str, Any]
) -> None:
    payload = _v3_canonical_bytes(receipt)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise V3InsightsValidationError("formal insights validation receipt collision")
        return
    path.write_bytes(payload)


def validate_v3_public_insights_wrapper(
    public_dir: Path,
    candidate_dir: Path,
    validation_receipt_path: Path,
    *,
    expected_candidate_manifest_sha256: str,
    expected_validation_receipt_sha256: str,
) -> dict[str, Any]:
    """Validate aggregate-only storylines and their embedded validation receipt."""

    from scripts.build_reddit_insights_snapshot import (
        V3_PUBLIC_INSIGHTS_MANIFEST_SCHEMA,
        V3_PUBLIC_INSIGHTS_SCHEMA,
        V3InsightsBuildError,
        _v3_assert_public_insights_safe,
        build_v3_public_insights_wrapper,
    )

    try:
        expected_insights, expected_receipt, expected_manifest = (
            build_v3_public_insights_wrapper(
                candidate_dir,
                validation_receipt_path,
                expected_candidate_manifest_sha256=expected_candidate_manifest_sha256,
                expected_validation_receipt_sha256=expected_validation_receipt_sha256,
            )
        )
    except V3InsightsBuildError as exc:
        raise V3InsightsValidationError(str(exc)) from exc
    public_dir = Path(public_dir)
    if public_dir.is_symlink() or not public_dir.is_dir():
        raise V3InsightsValidationError("public insights root is invalid")
    if {path.name for path in public_dir.iterdir()} != {
        "insights.json",
        "manifest.json",
        "validation-receipt.json",
    } or any(path.is_symlink() or not path.is_file() for path in public_dir.iterdir()):
        raise V3InsightsValidationError("public insights root file set is invalid")
    manifest = _v3_load_canonical(
        public_dir / "manifest.json", "public insights manifest"
    )
    insights = _v3_load_canonical(
        public_dir / "insights.json", "public insights"
    )
    embedded_receipt = _v3_load_canonical(
        public_dir / "validation-receipt.json",
        "embedded insights validation receipt",
    )
    if (
        manifest.get("schema_version") != V3_PUBLIC_INSIGHTS_MANIFEST_SCHEMA
        or manifest.get("artifact_stage") != "insights_public_candidate"
        or manifest.get("status") != "validated_candidate"
        or manifest.get("consumption_status")
        != "eligible_for_frontend_candidate_consumption"
        or manifest.get("independent_validation_status") != "passed"
        or manifest.get("promotable") is not True
        or manifest.get("privacy_safe_projection") is not True
        or manifest.get("lineage_manifest_sha256")
        != expected_candidate_manifest_sha256
        or manifest.get("validation_receipt_sha256")
        != expected_validation_receipt_sha256
    ):
        raise V3InsightsValidationError("public insights lifecycle is invalid")
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != {
        "insights.json",
        "validation-receipt.json",
    }:
        raise V3InsightsValidationError("public insights manifest file set is invalid")
    for name, record in files.items():
        path = public_dir / name
        if (
            not isinstance(record, dict)
            or set(record) != {"bytes", "sha256"}
            or record.get("bytes") != path.stat().st_size
            or record.get("sha256") != _sha256(path)
        ):
            raise V3InsightsValidationError(f"public insights file integrity mismatch: {name}")
    if (
        insights.get("schema_version") != V3_PUBLIC_INSIGHTS_SCHEMA
        or insights.get("privacy_safe_projection") is not True
        or insights.get("storyline_count") != 78
        or insights.get("storyline_count") != len(insights.get("storylines", []))
        or embedded_receipt != expected_receipt
    ):
        raise V3InsightsValidationError("public insights document contract is invalid")
    try:
        _v3_assert_public_insights_safe(insights)
    except V3InsightsBuildError as exc:
        raise V3InsightsValidationError(str(exc)) from exc
    required_sections = {
        "signal",
        "root_cause",
        "counter_intuitive",
        "impact",
        "action",
        "monitoring",
    }
    for storyline in insights["storylines"]:
        if (
            storyline.get("schema_version") != "reddit_voc_storyline_public_v3"
            or set(storyline.get("sections", {})) != required_sections
        ):
            raise V3InsightsValidationError("public storyline section set is invalid")
        root_cause = storyline["sections"]["root_cause"]
        if (
            type(root_cause.get("evidence_count")) is not int
            or root_cause["evidence_count"] < 0
            or "evidence_ids" in root_cause
        ):
            raise V3InsightsValidationError("public storyline leaked evidence IDs")
        signal = storyline["sections"]["signal"]
        if signal.get("status") == "unavailable" and (
            signal.get("direction") is not None
            or storyline.get("direction_claim_supported") is not False
        ):
            raise V3InsightsValidationError("public unavailable storyline emitted direction")
        counter = storyline["sections"]["counter_intuitive"]
        if counter.get("supported") is False and not counter.get("reason_codes"):
            raise V3InsightsValidationError("public storyline omitted unavailable reasons")
    if insights != expected_insights:
        raise V3InsightsValidationError("public insights deterministic replay mismatch")
    if manifest != expected_manifest:
        raise V3InsightsValidationError("public insights manifest replay mismatch")
    return {
        "boundaries": dict(V3_BOUNDARIES),
        "bundle_manifest_sha256": _sha256(public_dir / "manifest.json"),
        "comparison_contract_basis": manifest["comparison_contract_basis"],
        "comparison_contract_proven": manifest["comparison_contract_proven"],
        "completeness_percent": manifest["completeness_percent"],
        "data_owner_coverage_attestation_sha256": manifest[
            "data_owner_coverage_attestation_sha256"
        ],
        "deterministic_full_byte_replay": True,
        "lineage_manifest_sha256": expected_candidate_manifest_sha256,
        "privacy_safe_projection": True,
        "promotable": True,
        "schema_version": "reddit_voc_insights_public_validation_receipt_v3",
        "status": "passed_candidate_only",
        "storyline_count": insights["storyline_count"],
        "validation_receipt_sha256": expected_validation_receipt_sha256,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overlay-dir", type=Path, required=True)
    parser.add_argument("--base-snapshot-dir", type=Path, required=True)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    result = validate(
        args.overlay_dir.resolve(strict=True),
        args.base_snapshot_dir.resolve(strict=True),
    )
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
