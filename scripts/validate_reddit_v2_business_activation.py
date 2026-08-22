#!/usr/bin/env python3
"""Independently validate one V2 center business-activation manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from reddit_voc.report_contracts import canonical_json_bytes  # noqa: E402
from reddit_voc.v2_center import BOUNDARIES, V2CenterStore  # noqa: E402


class ValidationError(ValueError):
    pass


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical(path: Path, label: str) -> tuple[dict[str, object], bytes]:
    payload = path.read_bytes()
    value = json.loads(payload)
    if not isinstance(value, dict) or payload != canonical_json_bytes(value) + b"\n":
        raise ValidationError(f"{label} is not canonical")
    return value, payload


def _safe(project_root: Path, relative_text: object) -> Path:
    if not isinstance(relative_text, str):
        raise ValidationError("artifact path is invalid")
    relative = PurePosixPath(relative_text)
    if relative.is_absolute() or relative.as_posix() != relative_text or ".." in relative.parts:
        raise ValidationError("artifact path is invalid")
    path = project_root.joinpath(*relative.parts)
    if path.is_symlink() or not path.is_file():
        raise ValidationError("artifact path is unsafe")
    path.resolve(strict=True).relative_to(project_root.resolve(strict=True))
    return path


def _write(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise ValidationError("validation receipt immutable collision")
        return "no_change"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return "created"


def validate(project_root: Path, spec_path: Path, manifest_path: Path) -> dict[str, object]:
    spec, spec_payload = _canonical(spec_path, "activation spec")
    manifest, manifest_payload = _canonical(manifest_path, "activation manifest")
    if manifest.get("schema_version") != "reddit_voc_v2_business_activation_manifest_v1":
        raise ValidationError("activation manifest schema is invalid")
    if manifest.get("status") != "business_artifacts_activated_local" or manifest.get("promotable") is not False:
        raise ValidationError("activation status is invalid")
    if manifest.get("boundaries") != BOUNDARIES:
        raise ValidationError("activation boundaries are invalid")
    if manifest.get("spec_sha256") != _sha(spec_payload):
        raise ValidationError("activation spec binding mismatch")
    if not isinstance(manifest.get("checks"), dict) or not all(manifest["checks"].values()):
        raise ValidationError("activation checks are not passed")
    contracts = spec.get("artifacts")
    observed = manifest.get("artifacts")
    if not isinstance(contracts, dict) or not isinstance(observed, dict) or set(contracts) != set(observed):
        raise ValidationError("activation artifact set mismatch")
    values: dict[str, dict[str, object]] = {}
    for label, contract in contracts.items():
        if not isinstance(contract, dict) or not isinstance(observed[label], dict):
            raise ValidationError("activation artifact contract is invalid")
        path = _safe(project_root, contract.get("path"))
        payload = path.read_bytes()
        value = json.loads(payload)
        digest = _sha(payload)
        if (
            not isinstance(value, dict)
            or digest != contract.get("sha256")
            or observed[label].get("sha256") != digest
            or observed[label].get("path") != contract.get("path")
            or observed[label].get("schema_version") != value.get("schema_version")
        ):
            raise ValidationError(f"activation artifact mismatch:{label}")
        values[label] = value
    center = V2CenterStore(_safe(project_root, spec.get("center_database")), read_only=True)
    if center.state_sha256() != manifest.get("center_state_sha256"):
        raise ValidationError("activation center state mismatch")
    counts = manifest.get("business_counts")
    if not isinstance(counts, dict) or (
        counts.get("posts") != center.count("canonical_posts")
        or counts.get("stored_comments") != center.count("canonical_comments")
        or counts.get("unresolved_parent_comments") != center.count("relationship_debt")
        or counts.get("quarantined_comments") != center.count("comment_quarantine")
    ):
        raise ValidationError("activation center counts mismatch")

    facts_sha = observed["voc_facts_manifest"]["sha256"]
    governed_sha = observed["governed_manifest"]["sha256"]
    metrics_sha = observed["metrics_manifest"]["sha256"]
    reports_sha = observed["reports_manifest"]["sha256"]
    if values["voc_facts_receipt"].get("bundle_manifest_sha256") != facts_sha:
        raise ValidationError("independent VOC lineage mismatch")
    if values["governed_receipt"].get("snapshot_manifest_sha256") != governed_sha:
        raise ValidationError("independent governed lineage mismatch")
    if values["metrics_receipt"].get("bundle_manifest_sha256") != metrics_sha:
        raise ValidationError("independent metrics lineage mismatch")
    if values["reports_receipt"].get("bundle_manifest_sha256") != reports_sha:
        raise ValidationError("independent reports lineage mismatch")
    if values["insights_manifest"].get("report_manifest_sha256") != reports_sha:
        raise ValidationError("independent insights lineage mismatch")
    if values["frontend_source_stage_receipt"].get("frontend_source_manifest_sha256") != observed["frontend_source_manifest"]["sha256"]:
        raise ValidationError("independent frontend lineage mismatch")
    return {
        "activation_id": manifest["activation_id"],
        "activation_manifest_sha256": _sha(manifest_payload),
        "boundaries": dict(BOUNDARIES),
        "center_state_sha256": manifest["center_state_sha256"],
        "checks": {
            "artifact_hashes_and_schemas": True,
            "center_counts": True,
            "center_state": True,
            "critical_lineage_recomputed": True,
            "spec_binding": True,
        },
        "schema_version": "reddit_voc_v2_business_activation_validation_receipt_v1",
        "status": "passed",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        value = validate(args.project_root.resolve(strict=True), args.spec, args.manifest)
        payload = canonical_json_bytes(value) + b"\n"
        write_status = _write(args.output, payload)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        sys.stderr.write(json.dumps({"error": str(exc), "status": "failed"}, sort_keys=True) + "\n")
        return 1
    sys.stdout.write(json.dumps({"receipt_sha256": _sha(payload), "status": "passed", "write_status": write_status}, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
