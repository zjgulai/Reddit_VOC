from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from reddit_voc.report_contracts import canonical_json_bytes
from reddit_voc.v2_center import BOUNDARIES, V2CenterError, V2CenterStore


SPEC_SCHEMA = "reddit_voc_v2_business_activation_spec_v1"
MANIFEST_SCHEMA = "reddit_voc_v2_business_activation_manifest_v1"
EXPECTED_ARTIFACTS = {
    "baseline_bridge": "reddit_voc_v3_baseline_bridge_receipt_v1",
    "base_manifest": "reddit_voc_site_snapshot_manifest_v3",
    "base_receipt": "reddit_voc_base_public_validation_receipt_v1",
    "brand_health_public_manifest": "reddit_voc_brand_health_public_manifest_v1",
    "canonical_manifest": "reddit_voc_canonical_snapshot_manifest_v1",
    "canonical_receipt": "reddit_voc_canonical_snapshot_validation_receipt_v1",
    "frontend_source_manifest": "reddit_voc_frontend_source_manifest_v2",
    "frontend_source_stage_receipt": "reddit_voc_frontend_source_stage_receipt_v1",
    "governed_manifest": "reddit_voc_governed_signal_snapshot_v1",
    "governed_receipt": "reddit_voc_governed_signal_validation_receipt_v1",
    "insights_manifest": "reddit_voc_insights_manifest_v3",
    "insights_public_manifest": "reddit_voc_insights_public_manifest_v3",
    "insights_public_receipt": "reddit_voc_insights_public_validation_receipt_v3",
    "insights_receipt": "reddit_voc_insights_validation_receipt_v3",
    "metrics_input_manifest": "reddit_voc_metrics_input_manifest_v1",
    "metrics_manifest": "reddit_voc_metrics_candidate_manifest_v1",
    "metrics_receipt": "reddit_voc_metrics_validation_receipt_v1",
    "personas_manifest": "reddit_voc_personas_manifest_v3",
    "personas_receipt": "reddit_voc_personas_validation_v3",
    "reports_manifest": "reddit_voc_reports_manifest_v3",
    "reports_public_manifest": "reddit_voc_reports_public_manifest_v3",
    "reports_public_receipt": "reddit_voc_reports_public_validation_receipt_v3",
    "reports_receipt": "reddit_voc_reports_validation_receipt_v3",
    "voc_facts_manifest": "reddit_voc_voc_facts_manifest_v2",
    "voc_facts_receipt": "reddit_voc_voc_facts_validation_receipt_v2",
    "zero_diff_receipt": "reddit_voc_v3_baseline_center_validation_receipt_v1",
}
FALSE_BOUNDARIES = {"deploy", "live_send", "provider_call", "remote_write"}


class V2BusinessActivationError(ValueError):
    pass


@dataclass(frozen=True)
class V2BusinessActivationResult:
    activation_id: str
    manifest_path: Path
    manifest_sha256: str
    write_status: str


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _safe_path(project_root: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise V2BusinessActivationError(f"{label} path is invalid")
    relative = PurePosixPath(value)
    if relative.is_absolute() or relative.as_posix() != value or ".." in relative.parts:
        raise V2BusinessActivationError(f"{label} path is invalid")
    path = project_root.joinpath(*relative.parts)
    if path.is_symlink() or not path.is_file():
        raise V2BusinessActivationError(f"{label} path is unavailable")
    try:
        path.resolve(strict=True).relative_to(project_root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise V2BusinessActivationError(f"{label} path is unsafe") from exc
    return path


def _canonical(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        payload = path.read_bytes()
        value = json.loads(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V2BusinessActivationError(f"{label} is invalid") from exc
    if not isinstance(value, dict) or payload != canonical_json_bytes(value) + b"\n":
        raise V2BusinessActivationError(f"{label} is not canonical")
    return value, payload


def _json_object(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        payload = path.read_bytes()
        value = json.loads(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V2BusinessActivationError(f"{label} is invalid") from exc
    if not isinstance(value, dict):
        raise V2BusinessActivationError(f"{label} is not an object")
    return value, payload


def _assert_boundaries(value: Mapping[str, Any], label: str) -> None:
    boundaries = value.get("boundaries")
    if boundaries is None:
        return
    if not isinstance(boundaries, dict) or boundaries.get("production_unchanged") is not True:
        raise V2BusinessActivationError(f"{label} boundary is invalid")
    if any(boundaries.get(key) is not False for key in FALSE_BOUNDARIES):
        raise V2BusinessActivationError(f"{label} boundary is invalid")


def _binding(value: Mapping[str, Any], key: str, expected: str) -> None:
    if value.get(key) != expected:
        raise V2BusinessActivationError(f"lineage mismatch:{key}")


def _frontend_inventory(frontend: Mapping[str, Any]) -> dict[str, str]:
    try:
        rows = frontend["source"]["inventory"]["files"]
    except (KeyError, TypeError) as exc:
        raise V2BusinessActivationError("frontend source inventory is invalid") from exc
    if not isinstance(rows, list):
        raise V2BusinessActivationError("frontend source inventory is invalid")
    result: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise V2BusinessActivationError("frontend source inventory is invalid")
        result[row["path"]] = str(row.get("sha256") or "")
    return result


def build_business_activation_value(
    *, project_root: Path | str, spec_path: Path | str
) -> dict[str, object]:
    root = Path(project_root).resolve(strict=True)
    spec, spec_payload = _canonical(Path(spec_path), "business activation spec")
    if set(spec) != {
        "artifacts",
        "center_database",
        "expected_center_state_sha256",
        "schema_version",
    } or spec.get("schema_version") != SPEC_SCHEMA:
        raise V2BusinessActivationError("business activation spec contract is invalid")
    expected_center_state = spec.get("expected_center_state_sha256")
    if not isinstance(expected_center_state, str) or len(expected_center_state) != 64:
        raise V2BusinessActivationError("expected center state SHA is invalid")
    artifacts_contract = spec.get("artifacts")
    if not isinstance(artifacts_contract, dict) or set(artifacts_contract) != set(EXPECTED_ARTIFACTS):
        raise V2BusinessActivationError("business activation artifact set is invalid")
    artifacts: dict[str, dict[str, Any]] = {}
    bindings: dict[str, dict[str, str]] = {}
    for label, schema in sorted(EXPECTED_ARTIFACTS.items()):
        contract = artifacts_contract[label]
        if not isinstance(contract, dict) or set(contract) != {"path", "sha256"}:
            raise V2BusinessActivationError(f"artifact contract is invalid:{label}")
        path = _safe_path(root, contract["path"], label)
        value, payload = _json_object(path, label)
        actual_sha = _sha(payload)
        if contract["sha256"] != actual_sha or value.get("schema_version") != schema:
            raise V2BusinessActivationError(f"artifact binding mismatch:{label}")
        _assert_boundaries(value, label)
        artifacts[label] = value
        bindings[label] = {
            "path": str(contract["path"]),
            "schema_version": schema,
            "sha256": actual_sha,
        }

    bridge = artifacts["baseline_bridge"]
    canonical_manifest = artifacts["canonical_manifest"]
    canonical_receipt = artifacts["canonical_receipt"]
    zero_diff = artifacts["zero_diff_receipt"]
    if bridge.get("status") != "passed" or canonical_receipt.get("status") != "passed":
        raise V2BusinessActivationError("canonical baseline is not passed")
    _binding(bridge, "source_canonical_manifest_sha256", bindings["canonical_manifest"]["sha256"])
    _binding(bridge, "source_canonical_validation_receipt_sha256", bindings["canonical_receipt"]["sha256"])
    _binding(zero_diff, "bridge_receipt_sha256", bindings["baseline_bridge"]["sha256"])
    _binding(zero_diff, "canonical_manifest_sha256", bindings["canonical_manifest"]["sha256"])
    _binding(zero_diff, "canonical_validation_receipt_sha256", bindings["canonical_receipt"]["sha256"])
    _binding(zero_diff, "center_state_sha256", expected_center_state)
    if zero_diff.get("status") != "passed" or not all(zero_diff.get("checks", {}).values()):
        raise V2BusinessActivationError("center zero-diff receipt is not passed")

    center_path = _safe_path(root, spec["center_database"], "center database")
    center = V2CenterStore(center_path, read_only=True)
    if center.state_sha256() != expected_center_state:
        raise V2BusinessActivationError("center state SHA mismatch")
    counts = canonical_manifest.get("canonical_counts")
    if not isinstance(counts, dict):
        raise V2BusinessActivationError("canonical counts are invalid")
    observed_counts = {
        "posts": center.count("canonical_posts"),
        "stored_comments": center.count("canonical_comments"),
        "linked_comments": center.count("comment_parent_edges")
        - center.count("relationship_debt")
        - center.count("comment_quarantine"),
        "unresolved_parent_comments": center.count("relationship_debt"),
        "quarantined_comments": center.count("comment_quarantine"),
    }
    if any(observed_counts[key] != counts[key] for key in observed_counts):
        raise V2BusinessActivationError("center canonical count mismatch")

    base = artifacts["base_manifest"]
    base_receipt = artifacts["base_receipt"]
    _binding(base["inputs"], "canonical_manifest_sha256", bindings["canonical_manifest"]["sha256"])
    _binding(base["inputs"], "canonical_validation_receipt_sha256", bindings["canonical_receipt"]["sha256"])
    _binding(base_receipt, "public_manifest_sha256", bindings["base_manifest"]["sha256"])
    if base_receipt.get("status") != "passed_candidate_only" or base_receipt.get("promotable") is not True:
        raise V2BusinessActivationError("base public projection is not passed")

    facts = artifacts["voc_facts_manifest"]
    facts_receipt = artifacts["voc_facts_receipt"]
    _binding(facts["inputs"], "canonical_manifest_sha256", bindings["canonical_manifest"]["sha256"])
    _binding(facts["inputs"], "canonical_validation_receipt_sha256", bindings["canonical_receipt"]["sha256"])
    _binding(facts_receipt, "bundle_manifest_sha256", bindings["voc_facts_manifest"]["sha256"])
    if facts_receipt.get("status") != "passed":
        raise V2BusinessActivationError("VOC facts are not passed")

    governed = artifacts["governed_manifest"]
    governed_receipt = artifacts["governed_receipt"]
    _binding(governed["inputs"], "facts_manifest_sha256", bindings["voc_facts_manifest"]["sha256"])
    _binding(governed["inputs"], "facts_receipt_sha256", bindings["voc_facts_receipt"]["sha256"])
    _binding(governed_receipt, "snapshot_manifest_sha256", bindings["governed_manifest"]["sha256"])
    if governed_receipt.get("status") != "passed" or governed_receipt.get("promotable") is not True:
        raise V2BusinessActivationError("governed signals are not passed")

    metrics_input = artifacts["metrics_input_manifest"]
    for key, label in {
        "canonical_manifest_sha256": "canonical_manifest",
        "canonical_receipt_sha256": "canonical_receipt",
        "facts_manifest_sha256": "voc_facts_manifest",
        "facts_receipt_sha256": "voc_facts_receipt",
        "governed_manifest_sha256": "governed_manifest",
        "governed_receipt_sha256": "governed_receipt",
    }.items():
        _binding(metrics_input["inputs"], key, bindings[label]["sha256"])
    metrics = artifacts["metrics_manifest"]
    metrics_receipt = artifacts["metrics_receipt"]
    _binding(metrics_receipt, "bundle_manifest_sha256", bindings["metrics_manifest"]["sha256"])
    _binding(metrics_receipt, "source_facts_validation_receipt_sha256", bindings["governed_receipt"]["sha256"])
    if metrics_receipt.get("status") != "passed_candidate_only" or metrics_receipt.get("promotable") is not True:
        raise V2BusinessActivationError("metrics are not passed")

    personas = artifacts["personas_manifest"]
    personas_receipt = artifacts["personas_receipt"]
    _binding(personas, "source_facts_manifest_sha256", bindings["voc_facts_manifest"]["sha256"])
    _binding(personas, "governed_signal_manifest_sha256", bindings["governed_manifest"]["sha256"])
    _binding(personas, "governed_signal_validation_receipt_sha256", bindings["governed_receipt"]["sha256"])
    _binding(personas_receipt, "manifest_sha256", bindings["personas_manifest"]["sha256"])
    if personas_receipt.get("status") != "passed" or personas_receipt.get("promotable") is not True:
        raise V2BusinessActivationError("personas are not passed")

    reports = artifacts["reports_manifest"]
    reports_receipt = artifacts["reports_receipt"]
    reports_public = artifacts["reports_public_manifest"]
    reports_public_receipt = artifacts["reports_public_receipt"]
    insights = artifacts["insights_manifest"]
    insights_receipt = artifacts["insights_receipt"]
    insights_public = artifacts["insights_public_manifest"]
    insights_public_receipt = artifacts["insights_public_receipt"]
    for value in (reports, reports_receipt, insights, insights_receipt):
        _binding(value, "metrics_candidate_manifest_sha256", bindings["metrics_manifest"]["sha256"])
        _binding(value, "metrics_input_manifest_sha256", bindings["metrics_input_manifest"]["sha256"])
        _binding(value, "metrics_validation_receipt_sha256", bindings["metrics_receipt"]["sha256"])
    _binding(reports_receipt, "bundle_manifest_sha256", bindings["reports_manifest"]["sha256"])
    _binding(reports_public, "lineage_manifest_sha256", bindings["reports_manifest"]["sha256"])
    _binding(reports_public, "validation_receipt_sha256", bindings["reports_receipt"]["sha256"])
    _binding(reports_public_receipt, "bundle_manifest_sha256", bindings["reports_public_manifest"]["sha256"])
    _binding(insights, "report_manifest_sha256", bindings["reports_manifest"]["sha256"])
    _binding(insights, "report_validation_receipt_sha256", bindings["reports_receipt"]["sha256"])
    _binding(insights_receipt, "bundle_manifest_sha256", bindings["insights_manifest"]["sha256"])
    _binding(insights_public, "lineage_manifest_sha256", bindings["insights_manifest"]["sha256"])
    _binding(insights_public, "validation_receipt_sha256", bindings["insights_receipt"]["sha256"])
    _binding(insights_public_receipt, "bundle_manifest_sha256", bindings["insights_public_manifest"]["sha256"])
    if any(
        value.get("promotable") is not True
        for value in (reports_receipt, reports_public_receipt, insights_receipt, insights_public_receipt)
    ):
        raise V2BusinessActivationError("reports or insights are not promotable inputs")

    brand_health = artifacts["brand_health_public_manifest"]
    _binding(brand_health, "source_metrics_manifest_sha256", bindings["metrics_manifest"]["sha256"])
    _binding(brand_health, "source_metrics_validation_receipt_sha256", bindings["metrics_receipt"]["sha256"])
    if brand_health.get("status") != "ready":
        raise V2BusinessActivationError("brand health public projection is not ready")

    frontend = artifacts["frontend_source_manifest"]
    frontend_receipt = artifacts["frontend_source_stage_receipt"]
    _binding(frontend_receipt, "frontend_source_manifest_sha256", bindings["frontend_source_manifest"]["sha256"])
    if frontend_receipt.get("status") != "source_stage_materialized_local":
        raise V2BusinessActivationError("frontend source stage is not materialized")
    inventory = _frontend_inventory(frontend)
    required_inventory = {
        f"public/data/reddit-voc/{base['dataset_version']}/manifest-public.json": bindings["base_manifest"]["sha256"],
        f"public/data/reddit-voc/{brand_health['projection_id']}/manifest.json": bindings["brand_health_public_manifest"]["sha256"],
        f"public/data/reddit-voc/{insights_public['dataset_version']}/public/manifest.json": bindings["insights_public_manifest"]["sha256"],
        f"public/data/reddit-voc/{personas['snapshot_id']}/manifest.json": bindings["personas_manifest"]["sha256"],
        f"public/data/reddit-voc/{reports_public['dataset_version']}/public/manifest.json": bindings["reports_public_manifest"]["sha256"],
    }
    if any(inventory.get(path) != digest for path, digest in required_inventory.items()):
        raise V2BusinessActivationError("frontend source business inventory mismatch")

    seed = {
        "artifact_sha256s": {key: row["sha256"] for key, row in bindings.items()},
        "center_state_sha256": expected_center_state,
        "spec_sha256": _sha(spec_payload),
    }
    activation_id = "reddit-voc-v2-business-activation-" + _sha(canonical_json_bytes(seed))[:20]
    return {
        "activation_id": activation_id,
        "artifacts": bindings,
        "boundaries": dict(BOUNDARIES),
        "business_counts": {
            "analysis_ready_vocs": facts["counts"]["total_vocs"],
            "atomic_persona_catalog": personas["counts"]["atomic_persona_catalog"],
            "governed_fact_rows": governed["counts"]["fact_rows"],
            "indicator_count": metrics["indicator_count"],
            "persona_cohorts": personas["counts"]["persona_cohorts"],
            "report_count": reports["report_count"],
            "storyline_count": insights["storyline_count"],
            **observed_counts,
        },
        "center_state_sha256": expected_center_state,
        "checks": {
            "brand_health_lineage": True,
            "canonical_center_zero_diff": True,
            "frontend_business_inventory": True,
            "metrics_lineage": True,
            "personas_lineage": True,
            "reports_insights_lineage": True,
            "voc_governed_lineage": True,
        },
        "frontend_candidate_input_sha256": frontend["frontend_candidate_input_sha256"],
        "next_blockers": [
            "activation_manifest_not_yet_in_frontend_source",
            "full_page_e2e_pending",
            "two_shadow_cycles_pending",
        ],
        "promotable": False,
        "schema_version": MANIFEST_SCHEMA,
        "spec_sha256": _sha(spec_payload),
        "status": "business_artifacts_activated_local",
    }


def build_business_activation(
    *, project_root: Path | str, spec_path: Path | str, output_path: Path | str
) -> V2BusinessActivationResult:
    value = build_business_activation_value(project_root=project_root, spec_path=spec_path)
    payload = canonical_json_bytes(value) + b"\n"
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise V2BusinessActivationError("business activation immutable collision")
        write_status = "no_change"
    else:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        write_status = "created"
    return V2BusinessActivationResult(
        activation_id=str(value["activation_id"]),
        manifest_path=path,
        manifest_sha256=_sha(payload),
        write_status=write_status,
    )
