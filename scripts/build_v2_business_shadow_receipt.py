#!/usr/bin/env python3
"""Build one immutable read-only V2 business shadow comparison receipt."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping


SCHEMA = "reddit_voc_v2_business_shadow_receipt_v1"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class ShadowReceiptError(ValueError):
    pass


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_sha(value: str, label: str) -> str:
    if SHA_RE.fullmatch(value or "") is None:
        raise ShadowReceiptError(f"{label}_sha256_invalid")
    return value


def load_exact(path: Path, expected_sha256: str, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ShadowReceiptError(f"{label}_missing_or_unsafe")
    if file_sha256(path) != require_sha(expected_sha256, label):
        raise ShadowReceiptError(f"{label}_sha256_mismatch")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ShadowReceiptError(f"{label}_json_invalid") from exc
    if not isinstance(value, dict):
        raise ShadowReceiptError(f"{label}_object_invalid")
    return value


def object_field(value: Mapping[str, Any], key: str, label: str) -> dict[str, Any]:
    child = value.get(key)
    if not isinstance(child, dict):
        raise ShadowReceiptError(f"{label}_invalid")
    return child


def build_receipt(args: argparse.Namespace) -> dict[str, Any]:
    if re.fullmatch(r"cycle-[1-9][0-9]*", args.cycle_id or "") is None:
        raise ShadowReceiptError("cycle_id_invalid")
    if not isinstance(args.observed_at_utc, str) or not args.observed_at_utc.endswith("Z"):
        raise ShadowReceiptError("observed_at_utc_invalid")

    marker = load_exact(Path(args.production_release_marker), args.expected_production_release_marker_sha256, "production_release_marker")
    pointer = load_exact(Path(args.production_current_release), args.expected_production_current_release_sha256, "production_current_release")
    production_build = load_exact(Path(args.production_build_receipt), args.expected_production_build_receipt_sha256, "production_build_receipt")
    candidate_build = load_exact(Path(args.candidate_build_receipt), args.expected_candidate_build_receipt_sha256, "candidate_build_receipt")
    candidate_e2e = load_exact(Path(args.candidate_e2e_receipt), args.expected_candidate_e2e_receipt_sha256, "candidate_e2e_receipt")
    activation = load_exact(Path(args.activation_manifest), args.expected_activation_manifest_sha256, "activation_manifest")
    activation_public = load_exact(
        Path(args.candidate_activation_public_manifest),
        args.expected_candidate_activation_public_manifest_sha256,
        "candidate_activation_public_manifest",
    )

    production_release_sha = marker.get("release_sha256")
    if (
        marker.get("release_sha256") != production_build.get("release_sha256")
        or production_build.get("schema_version") != "reddit_voc_insights_build_receipt_v1"
        or production_build.get("status") != "passed_local_build"
    ):
        raise ShadowReceiptError("production_release_lineage_invalid")
    if pointer.get("schema_version") != "reddit_voc_current_release_v1":
        raise ShadowReceiptError("production_current_release_contract_invalid")

    candidate_lineage = object_field(object_field(candidate_build, "frontend_source", "candidate_frontend_source"), "v3_lineage", "candidate_v3_lineage")
    candidate_e2e_release = object_field(candidate_e2e, "release", "candidate_e2e_release")
    if (
        candidate_build.get("schema_version") != "reddit_voc_insights_build_receipt_v1"
        or candidate_build.get("status") != "passed_local_build"
        or candidate_e2e.get("schema_version") != "reddit_voc_same_dist_browser_e2e_receipt_v2"
        or candidate_e2e.get("status") != "passed_local_same_dist_browser_acceptance"
        or candidate_e2e_release.get("release_sha256") != candidate_build.get("release_sha256")
        or candidate_e2e_release.get("release_manifest_sha256") != object_field(candidate_build, "release_manifest", "candidate_release_manifest").get("sha256")
    ):
        raise ShadowReceiptError("candidate_release_e2e_lineage_invalid")

    pointer_sha = file_sha256(Path(args.production_current_release))
    if candidate_lineage.get("current_release_pointer_sha256") != pointer_sha:
        raise ShadowReceiptError("candidate_production_pointer_mismatch")
    pointer_datasets = object_field(pointer, "datasets", "production_datasets")
    candidate_datasets = object_field(candidate_lineage, "datasets", "candidate_datasets")
    if set(pointer_datasets) != {"base", "insights", "reports", "personas"} or set(candidate_datasets) != set(pointer_datasets):
        raise ShadowReceiptError("dataset_set_invalid")
    for name, binding in pointer_datasets.items():
        candidate_binding = object_field(candidate_datasets, name, f"candidate_{name}")
        if not isinstance(binding, dict) or any(
            candidate_binding.get(field) != binding.get(field)
            for field in ("dataset_version", "public_manifest_sha256", "lineage_manifest_sha256")
        ):
            raise ShadowReceiptError(f"dataset_{name}_mismatch")

    production_dist = object_field(production_build, "dist_inventory", "production_dist")
    candidate_dist = object_field(candidate_build, "dist_inventory", "candidate_dist")
    dist_identical = candidate_dist == production_dist
    counts = object_field(activation, "business_counts", "activation_business_counts")
    if (
        activation.get("schema_version") != "reddit_voc_v2_business_activation_manifest_v1"
        or activation.get("status") != "business_artifacts_activated_local"
        or counts.get("posts") != 3494
        or counts.get("stored_comments") != 27158
        or counts.get("linked_comments") != 20205
        or counts.get("unresolved_parent_comments") != 6943
    ):
        raise ShadowReceiptError("activation_contract_invalid")

    auxiliary = candidate_lineage.get("auxiliary_public_manifests")
    public_manifest_sha = file_sha256(Path(args.candidate_activation_public_manifest))
    activation_in_source = (
        activation_public.get("schema_version") == "reddit_voc_v2_business_activation_public_manifest_v1"
        and activation_public.get("source_activation_manifest_sha256")
        == file_sha256(Path(args.activation_manifest))
        and isinstance(auxiliary, list)
        and any(
            isinstance(row, dict)
            and row.get("sha256") == public_manifest_sha
            and str(row.get("relative_path", "")).endswith("/manifest.json")
            for row in auxiliary
        )
    )
    if not activation_in_source:
        raise ShadowReceiptError("activation_not_in_candidate_source")

    receipt = {
        "schema_version": SCHEMA,
        "status": "passed_local_read_only_shadow",
        "cycle_id": args.cycle_id,
        "observed_at_utc": args.observed_at_utc,
        "production": {
            "release_sha256": production_release_sha,
            "release_id": pointer.get("release_id"),
            "current_release_sha256": pointer_sha,
            "dataset_versions": {name: pointer_datasets[name]["dataset_version"] for name in sorted(pointer_datasets)},
            "dist_inventory": production_dist,
        },
        "candidate": {
            "release_sha256": candidate_build.get("release_sha256"),
            "release_manifest_sha256": object_field(candidate_build, "release_manifest", "candidate_release_manifest").get("sha256"),
            "frontend_candidate_input_sha256": object_field(candidate_build, "frontend_source", "candidate_frontend_source").get("frontend_candidate_input_sha256"),
            "current_release_sha256": candidate_lineage.get("current_release_pointer_sha256"),
            "activation_id": activation.get("activation_id"),
            "center_state_sha256": activation.get("center_state_sha256"),
            "dist_inventory": candidate_dist,
            "e2e_receipt_sha256": file_sha256(Path(args.candidate_e2e_receipt)),
        },
        "difference_classification": {
            "data_version": "same_four_dataset_release",
            "late_arrival": "not_observed_same_dataset_version",
            "relationship_debt": {
                "unresolved_parent_comments": counts["unresolved_parent_comments"],
                "quarantined_comments": counts.get("quarantined_comments"),
                "classification": "known_structure_debt_retained",
            },
            "ui": "byte_identical_dist" if dist_identical else "candidate_dist_changed",
            "governance_metadata": "business_activation_lineage_added",
        },
        "checks": {
            "production_release_and_pointer_captured_read_only": True,
            "candidate_four_dataset_lineage_matches_production": True,
            "candidate_activation_present_in_frontend_source": True,
            "candidate_same_dist_e2e_passed": True,
            "difference_categories_complete": True,
        },
        "boundaries": {
            "database_write": False,
            "deploy": False,
            "live_send": False,
            "production_unchanged": True,
            "provider_call": False,
            "remote_read": True,
            "remote_write": False,
            "schedule_change": False,
        },
    }
    return receipt


def write_immutable(path: Path, value: Mapping[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_bytes(value) + b"\n"
    if path.exists():
        if path.is_file() and not path.is_symlink() and path.read_bytes() == payload:
            return "no_change"
        raise ShadowReceiptError("output_immutable_collision")
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".shadow-", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(payload)
        stream.flush()
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return "created"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--cycle-id", required=True)
    result.add_argument("--observed-at-utc", required=True)
    for name in (
        "production-release-marker", "production-current-release", "production-build-receipt",
        "candidate-build-receipt", "candidate-e2e-receipt", "activation-manifest",
        "candidate-activation-public-manifest",
    ):
        result.add_argument(f"--{name}", required=True)
        result.add_argument(f"--expected-{name}-sha256", required=True)
    result.add_argument("--output", required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        receipt = build_receipt(args)
        status = write_immutable(Path(args.output), receipt)
    except ShadowReceiptError as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps({"status": status, "receipt_sha256": file_sha256(Path(args.output)), "production_unchanged": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
