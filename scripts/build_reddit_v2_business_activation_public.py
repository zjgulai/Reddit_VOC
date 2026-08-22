#!/usr/bin/env python3
"""Build a privacy-safe public projection of a passed business activation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from reddit_voc.report_contracts import canonical_json_bytes  # noqa: E402


class PublicActivationError(ValueError):
    pass


BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical(path: Path, label: str) -> tuple[dict[str, object], bytes]:
    payload = path.read_bytes()
    value = json.loads(payload)
    if not isinstance(value, dict) or payload != canonical_json_bytes(value) + b"\n":
        raise PublicActivationError(f"{label} is not canonical")
    return value, payload


def build(activation_path: Path, receipt_path: Path, output_root: Path) -> tuple[str, str]:
    activation, activation_payload = _canonical(activation_path, "activation manifest")
    receipt, _ = _canonical(receipt_path, "activation validation receipt")
    activation_sha = _sha(activation_payload)
    if (
        activation.get("schema_version") != "reddit_voc_v2_business_activation_manifest_v1"
        or activation.get("status") != "business_artifacts_activated_local"
        or receipt.get("schema_version")
        != "reddit_voc_v2_business_activation_validation_receipt_v1"
        or receipt.get("status") != "passed"
        or receipt.get("activation_manifest_sha256") != activation_sha
    ):
        raise PublicActivationError("activation validation binding is invalid")
    dataset_version = str(activation["activation_id"]).replace("reddit-voc-", "reddit_voc_")
    public_value = {
        "activation_id": activation["activation_id"],
        "artifact_bindings": {
            key: {
                "schema_version": row["schema_version"],
                "sha256": row["sha256"],
            }
            for key, row in sorted(activation["artifacts"].items())
        },
        "boundaries": dict(BOUNDARIES),
        "business_counts": activation["business_counts"],
        "center_state_sha256": activation["center_state_sha256"],
        "checks": activation["checks"],
        "dataset_version": dataset_version,
        "schema_version": "reddit_voc_v2_business_activation_public_v1",
        "status": "validated_local_business_data",
    }
    public_payload = canonical_json_bytes(public_value) + b"\n"
    manifest = {
        "boundaries": dict(BOUNDARIES),
        "dataset_version": dataset_version,
        "files": {
            "activation.json": {
                "bytes": len(public_payload),
                "sha256": _sha(public_payload),
            }
        },
        "schema_version": "reddit_voc_v2_business_activation_public_manifest_v1",
        "source_activation_manifest_sha256": activation_sha,
        "source_activation_validation_receipt_sha256": _sha(receipt_path.read_bytes()),
        "status": "ready",
    }
    manifest_payload = canonical_json_bytes(manifest) + b"\n"
    target = output_root / dataset_version
    if target.exists() or target.is_symlink():
        if (
            target.is_symlink()
            or not target.is_dir()
            or (target / "activation.json").read_bytes() != public_payload
            or (target / "manifest.json").read_bytes() != manifest_payload
        ):
            raise PublicActivationError("public activation immutable collision")
        return dataset_version, "no_change"
    output_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging = Path(tempfile.mkdtemp(prefix=".business-activation-", dir=output_root))
    try:
        for name, payload in (("activation.json", public_payload), ("manifest.json", manifest_payload)):
            descriptor = os.open(staging / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        os.rename(staging, target)
    finally:
        if staging.exists():
            staging.rmdir()
    return dataset_version, "created"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--activation", type=Path, required=True)
    parser.add_argument("--validation-receipt", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        dataset_version, status = build(args.activation, args.validation_receipt, args.output_root)
        manifest = args.output_root / dataset_version / "manifest.json"
    except (OSError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"error": str(exc), "status": "blocked"}, sort_keys=True))
        return 1
    print(json.dumps({"dataset_version": dataset_version, "manifest_sha256": _sha(manifest.read_bytes()), "status": "passed", "write_status": status}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
