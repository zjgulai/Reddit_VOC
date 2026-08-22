#!/usr/bin/env python3
"""Build an immutable Reddit VOC data-only release pointer.

The builder upgrades one already validated V1 core pointer with the three
data-dependent auxiliary projections and explicit 07:00-to-07:00 freshness
evidence.  It is local-only: it never deploys, writes a database, calls a
provider, or changes an existing pointer whose bytes differ.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping


SCHEMA_VERSION = "reddit_voc_current_release_v2"
FRESHNESS_SCHEMA = "reddit_voc_data_freshness_v1"
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,127}$")
AUXILIARY_PREFIXES = {
    "brand_health": "reddit_voc_brand_health_",
    "quarter_insights": "reddit_voc_quarter_insights_",
    "casebook": "reddit_voc_casebook_",
}
AUXILIARY_MANIFEST_SCHEMAS = {
    "brand_health": "reddit_voc_brand_health_public_manifest_v1",
    "quarter_insights": "reddit_voc_quarter_insights_public_manifest_v1",
    "casebook": "reddit_voc_governance_casebook_public_manifest_v1",
}
CORE_DATASET_KEYS = {"base", "insights", "reports", "personas"}
STATIC_FALSE_BOUNDARIES = {
    "provider_call": False,
    "database_write": False,
    "remote_write": False,
    "live_send": False,
    "deploy": False,
}


class DataReleaseContractError(ValueError):
    """One input does not satisfy the data-only release contract."""


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink():
        raise DataReleaseContractError(f"{label}_unsafe")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise DataReleaseContractError(f"{label}_missing") from exc
    if not resolved.is_file():
        raise DataReleaseContractError(f"{label}_unsafe")
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DataReleaseContractError(f"{label}_invalid_json") from exc
    if not isinstance(value, dict):
        raise DataReleaseContractError(f"{label}_not_object")
    return value


def _safe_id(value: object, *, label: str, prefix: str | None = None) -> str:
    if not isinstance(value, str) or SAFE_ID_RE.fullmatch(value) is None:
        raise DataReleaseContractError(f"{label}_invalid")
    if prefix is not None and not value.startswith(prefix):
        raise DataReleaseContractError(f"{label}_invalid")
    return value


def _sha(value: object, *, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise DataReleaseContractError(f"{label}_invalid")
    return value


def _utc(value: object, *, label: str) -> datetime:
    if not isinstance(value, str):
        raise DataReleaseContractError(f"{label}_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DataReleaseContractError(f"{label}_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise DataReleaseContractError(f"{label}_not_utc")
    return parsed.astimezone(timezone.utc)


def _utc_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _nonnegative(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DataReleaseContractError(f"{label}_invalid")
    return value


def _inside(path: Path, root: Path, *, label: str) -> Path:
    if path.is_symlink():
        raise DataReleaseContractError(f"{label}_unsafe")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise DataReleaseContractError(f"{label}_unsafe") from exc
    if not resolved.is_file():
        raise DataReleaseContractError(f"{label}_unsafe")
    return resolved


def _validate_core_pointer(
    value: Mapping[str, Any],
    *,
    public_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if value.get("schema_version") != "reddit_voc_current_release_v1":
        raise DataReleaseContractError("core_pointer_schema_invalid")
    if set(value) != {
        "schema_version",
        "release_id",
        "generated_at_utc",
        "datasets",
        "cases",
        "boundaries",
    }:
        raise DataReleaseContractError("core_pointer_fields_invalid")
    datasets = value.get("datasets")
    if not isinstance(datasets, dict) or set(datasets) != CORE_DATASET_KEYS:
        raise DataReleaseContractError("core_pointer_datasets_invalid")
    for key, binding in datasets.items():
        if not isinstance(binding, dict) or set(binding) != {
            "dataset_version",
            "manifest_path",
            "public_manifest_sha256",
            "lineage_manifest_sha256",
        }:
            raise DataReleaseContractError(f"core_{key}_binding_invalid")
        manifest_relative = binding.get("manifest_path")
        if (
            not isinstance(manifest_relative, str)
            or manifest_relative.startswith("/")
            or ".." in Path(manifest_relative).parts
        ):
            raise DataReleaseContractError(f"core_{key}_manifest_path_invalid")
        manifest_path = _inside(
            public_root / manifest_relative,
            public_root,
            label=f"core_{key}_manifest",
        )
        if _sha(binding.get("public_manifest_sha256"), label=f"core_{key}_manifest_sha256") != _sha256(manifest_path):
            raise DataReleaseContractError(f"core_{key}_manifest_sha256_mismatch")
        _sha(binding.get("lineage_manifest_sha256"), label=f"core_{key}_lineage_sha256")
    cases = value.get("cases")
    boundaries = value.get("boundaries")
    if not isinstance(cases, dict) or not isinstance(boundaries, dict):
        raise DataReleaseContractError("core_pointer_governance_invalid")
    if boundaries != {
        "case_gallery_stock_preserved": True,
        "collector_isolation_required": True,
        "login_required": False,
    }:
        raise DataReleaseContractError("core_pointer_boundaries_invalid")
    base_binding = datasets["base"]
    base_manifest = _load_object(
        public_root / base_binding["manifest_path"],
        label="core_base_manifest",
    )
    return dict(value), base_manifest


def _validate_freshness(
    value: Mapping[str, Any],
    *,
    center_snapshot_id: str,
) -> dict[str, Any]:
    expected = {
        "schema_version",
        "status",
        "timezone",
        "data_as_of_utc",
        "window_start_utc",
        "window_end_utc",
        "collector_run_id",
        "source_batch_id",
        "center_snapshot_id",
        "net_new",
        "coverage",
        "boundaries",
    }
    if set(value) != expected or value.get("schema_version") != FRESHNESS_SCHEMA:
        raise DataReleaseContractError("freshness_contract_invalid")
    if value.get("timezone") != "Asia/Shanghai":
        raise DataReleaseContractError("freshness_timezone_invalid")
    status = value.get("status")
    if status not in {"full", "partial", "empty_success"}:
        raise DataReleaseContractError("freshness_status_invalid")
    start = _utc(value.get("window_start_utc"), label="window_start_utc")
    end = _utc(value.get("window_end_utc"), label="window_end_utc")
    data_as_of = _utc(value.get("data_as_of_utc"), label="data_as_of_utc")
    if end - start != timedelta(hours=24) or end != data_as_of:
        raise DataReleaseContractError("freshness_window_invalid")
    if start.hour != 23 or end.hour != 23 or start.minute != 0 or end.minute != 0:
        raise DataReleaseContractError("freshness_window_not_0700_asia_shanghai")
    collector_run_id = _safe_id(value.get("collector_run_id"), label="collector_run_id")
    source_batch_id = _safe_id(value.get("source_batch_id"), label="source_batch_id")
    observed_center = _safe_id(value.get("center_snapshot_id"), label="center_snapshot_id")
    if observed_center != center_snapshot_id:
        raise DataReleaseContractError("freshness_center_snapshot_mismatch")
    net_new = value.get("net_new")
    coverage = value.get("coverage")
    if not isinstance(net_new, dict) or set(net_new) != {
        "posts",
        "comments",
        "updated_historical_posts",
        "repaired_parent_links",
    }:
        raise DataReleaseContractError("freshness_net_new_invalid")
    if not isinstance(coverage, dict) or set(coverage) != {
        "full_posts",
        "partial_posts",
        "unresolved_continuations",
    }:
        raise DataReleaseContractError("freshness_coverage_invalid")
    clean_net_new = {
        key: _nonnegative(net_new[key], label=f"net_new_{key}")
        for key in sorted(net_new)
    }
    clean_coverage = {
        key: _nonnegative(coverage[key], label=f"coverage_{key}")
        for key in sorted(coverage)
    }
    if clean_coverage["partial_posts"] > 0 and status != "partial":
        raise DataReleaseContractError("freshness_partial_status_mismatch")
    if status == "empty_success" and any(clean_net_new.values()):
        raise DataReleaseContractError("freshness_empty_success_has_delta")
    boundaries = value.get("boundaries")
    if not isinstance(boundaries, dict) or boundaries != {
        **STATIC_FALSE_BOUNDARIES,
        "production_unchanged": True,
    }:
        raise DataReleaseContractError("freshness_boundaries_invalid")
    return {
        "status": status,
        "timezone": "Asia/Shanghai",
        "data_as_of_utc": _utc_z(data_as_of),
        "window_start_utc": _utc_z(start),
        "window_end_utc": _utc_z(end),
        "collector_run_id": collector_run_id,
        "source_batch_id": source_batch_id,
        "center_snapshot_id": observed_center,
        "net_new": clean_net_new,
        "coverage": clean_coverage,
    }


def _validate_auxiliary(
    *,
    public_root: Path,
    key: str,
    version: str,
    expected_manifest_sha256: str,
    center_snapshot_id: str,
) -> tuple[dict[str, str], dict[str, Any]]:
    prefix = AUXILIARY_PREFIXES[key]
    version = _safe_id(version, label=f"{key}_version", prefix=prefix)
    expected_sha = _sha(expected_manifest_sha256, label=f"{key}_manifest_sha256")
    relative = Path("data/reddit-voc") / version / "manifest.json"
    manifest_path = _inside(public_root / relative, public_root, label=f"{key}_manifest")
    if _sha256(manifest_path) != expected_sha:
        raise DataReleaseContractError(f"{key}_manifest_sha256_mismatch")
    manifest = _load_object(manifest_path, label=f"{key}_manifest")
    if manifest.get("schema_version") != AUXILIARY_MANIFEST_SCHEMAS[key]:
        raise DataReleaseContractError(f"{key}_manifest_schema_invalid")
    manifest_identity = manifest.get("dataset_version") or manifest.get("projection_id")
    if manifest_identity != version:
        raise DataReleaseContractError(f"{key}_manifest_identity_mismatch")
    if manifest.get("status") != "ready":
        raise DataReleaseContractError(f"{key}_not_ready")
    if key == "brand_health" and manifest.get("source_snapshot_id") != center_snapshot_id:
        raise DataReleaseContractError("brand_health_center_snapshot_mismatch")
    if key == "quarter_insights":
        source = manifest.get("source")
        if not isinstance(source, dict) or source.get("source_snapshot_id") != center_snapshot_id:
            raise DataReleaseContractError("quarter_insights_center_snapshot_mismatch")
    return (
        {
            "dataset_version": version,
            "manifest_path": relative.as_posix(),
            "public_manifest_sha256": expected_sha,
            "lineage_manifest_sha256": expected_sha,
        },
        manifest,
    )


def build_data_release(
    *,
    public_root: Path,
    core_pointer_path: Path,
    auxiliary_versions: Mapping[str, str],
    auxiliary_manifest_sha256s: Mapping[str, str],
    freshness_path: Path,
    release_id: str,
    generated_at_utc: str,
) -> dict[str, Any]:
    release_id = _safe_id(release_id, label="release_id", prefix="reddit_voc_release_")
    generated_at = _utc(generated_at_utc, label="generated_at_utc")
    if public_root.is_symlink():
        raise DataReleaseContractError("public_root_unsafe")
    try:
        root = public_root.resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise DataReleaseContractError("public_root_missing") from exc
    if not root.is_dir():
        raise DataReleaseContractError("public_root_unsafe")
    if set(auxiliary_versions) != set(AUXILIARY_PREFIXES):
        raise DataReleaseContractError("auxiliary_version_keys_invalid")
    if set(auxiliary_manifest_sha256s) != set(AUXILIARY_PREFIXES):
        raise DataReleaseContractError("auxiliary_manifest_sha256_keys_invalid")

    core, base_manifest = _validate_core_pointer(
        _load_object(core_pointer_path, label="core_pointer"),
        public_root=root,
    )
    center_snapshot_id = _safe_id(
        base_manifest.get("source_snapshot_id"),
        label="base_source_snapshot_id",
    )
    freshness = _validate_freshness(
        _load_object(freshness_path, label="freshness"),
        center_snapshot_id=center_snapshot_id,
    )
    if generated_at < _utc(freshness["data_as_of_utc"], label="freshness_data_as_of_utc"):
        raise DataReleaseContractError("generated_at_precedes_data_as_of")

    auxiliary_bindings: dict[str, dict[str, str]] = {}
    for key in AUXILIARY_PREFIXES:
        binding, _ = _validate_auxiliary(
            public_root=root,
            key=key,
            version=auxiliary_versions[key],
            expected_manifest_sha256=auxiliary_manifest_sha256s[key],
            center_snapshot_id=center_snapshot_id,
        )
        auxiliary_bindings[key] = binding

    return {
        "schema_version": SCHEMA_VERSION,
        "release_id": release_id,
        "generated_at_utc": _utc_z(generated_at),
        "datasets": {**core["datasets"], **auxiliary_bindings},
        "freshness": freshness,
        "cases": core["cases"],
        "boundaries": core["boundaries"],
    }


def write_immutable_pointer(path: Path, value: Mapping[str, Any]) -> str:
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            raise DataReleaseContractError("pointer_destination_unsafe")
        if path.read_bytes() != payload:
            raise DataReleaseContractError("pointer_immutable_collision")
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
    parser.add_argument("--core-pointer", type=Path, required=True)
    parser.add_argument("--brand-health-version", required=True)
    parser.add_argument("--brand-health-manifest-sha256", required=True)
    parser.add_argument("--quarter-insights-version", required=True)
    parser.add_argument("--quarter-insights-manifest-sha256", required=True)
    parser.add_argument("--casebook-version", required=True)
    parser.add_argument("--casebook-manifest-sha256", required=True)
    parser.add_argument("--freshness", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--generated-at-utc", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        pointer = build_data_release(
            public_root=args.public_root,
            core_pointer_path=args.core_pointer,
            auxiliary_versions={
                "brand_health": args.brand_health_version,
                "quarter_insights": args.quarter_insights_version,
                "casebook": args.casebook_version,
            },
            auxiliary_manifest_sha256s={
                "brand_health": args.brand_health_manifest_sha256,
                "quarter_insights": args.quarter_insights_manifest_sha256,
                "casebook": args.casebook_manifest_sha256,
            },
            freshness_path=args.freshness,
            release_id=args.release_id,
            generated_at_utc=args.generated_at_utc,
        )
        result = write_immutable_pointer(args.output, pointer)
    except (DataReleaseContractError, OSError, ValueError) as exc:
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
