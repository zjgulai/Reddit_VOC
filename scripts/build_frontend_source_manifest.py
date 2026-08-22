#!/usr/bin/env python3
"""Freeze an explicit local React source inventory for Reddit VOC.

The legacy contract reads immutable Plan-A evidence.  The V3 contract instead
binds the current-release pointer and the independently validated Base,
Insights, Reports and Personas public datasets.  The two lineage modes are
mutually exclusive: V3 data must never be represented as old Plan-A evidence.
The command writes one canonical source manifest under a private,
content-addressed local candidate root.  It never builds or deploys a site.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit


SCHEMA_VERSION = "reddit_voc_frontend_source_manifest_v1"
V3_SCHEMA_VERSION = "reddit_voc_frontend_source_manifest_v2"
PLAN_A_MANIFEST_SCHEMA = "reddit_voc_candidate_data_manifest_v1"
PLAN_A_RECONCILIATION_SCHEMA = "reddit_voc_candidate_data_reconciliation_v1"
PLAN_A_RECEIPT_SCHEMA = "reddit_voc_candidate_data_validation_receipt_v1"
PUBLIC_RECEIPT_SCHEMA = "reddit_voc_public_projection_validation_v1"
CURRENT_RELEASE_SCHEMAS = frozenset(
    {"reddit_voc_current_release_v1", "reddit_voc_current_release_v2"}
)
DATASET_NAMES = frozenset({"base", "insights", "reports", "personas"})
V2_AUXILIARY_DATASET_NAMES = frozenset(
    {"brand_health", "quarter_insights", "casebook"}
)
V2_DATASET_NAMES = DATASET_NAMES | V2_AUXILIARY_DATASET_NAMES
V3_LINEAGE_CONTRACT = "reddit_voc_v3_four_dataset_frontend_lineage_v1"
V3_LINEAGE_CONTRACT_V2 = "reddit_voc_v3_seven_dataset_frontend_lineage_v2"
V3_MANIFEST_SCHEMAS = {
    "base": "reddit_voc_site_snapshot_manifest_v3",
    "insights": "reddit_voc_insights_public_manifest_v3",
    "reports": "reddit_voc_reports_public_manifest_v3",
    "personas": "reddit_voc_personas_manifest_v3",
}
V3_RECEIPT_SCHEMAS = {
    "base": "reddit_voc_base_public_validation_receipt_v1",
    "insights": "reddit_voc_insights_public_validation_receipt_v3",
    "reports": "reddit_voc_reports_public_validation_receipt_v3",
    "personas": "reddit_voc_personas_validation_v3",
}
PERIODIC_PUBLIC_MANIFEST_SCHEMA = "reddit-voc-periodic-report-public-manifest-v1"
PERIODIC_GRAINS = ("daily", "weekly", "monthly")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
VERSION_RE = re.compile(r"^v?[0-9]+(?:\.[0-9]+){1,3}(?:[-+][0-9A-Za-z.-]+)?$")
MAX_SOURCE_FILES = 50_000
MAX_SOURCE_BYTES = 500_000_000
FORBIDDEN_SOURCE_NAMES = frozenset({".DS_Store", ".env"})
FORBIDDEN_SOURCE_SUFFIXES = frozenset({".pem", ".key"})

BOUNDARIES = {
    "artifact_build": False,
    "database_write": False,
    "deploy": False,
    "deployment": False,
    "live_send": False,
    "provider_call": False,
    "remote_write": False,
    "production_unchanged": True,
    "promotable_dist_included": False,
}
FALSE_SIDE_EFFECT_KEYS = frozenset(
    {
        "artifact_build",
        "database_write",
        "deploy",
        "deployment",
        "live_send",
        "provider_attempt_made",
        "provider_call",
        "remote_write",
        "schedule_change",
        "webhook_send",
    }
)


class FrontendSourceManifestError(ValueError):
    """An input or immutable publication contract failed."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _valid_sha(value: object, *, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise FrontendSourceManifestError(f"{label}_sha256_invalid")
    return value


def _require_not_future_utc(
    value: object,
    *,
    label: str,
    now_utc: datetime | None = None,
) -> datetime:
    if not isinstance(value, str) or not value:
        raise FrontendSourceManifestError(f"{label}_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FrontendSourceManifestError(f"{label}_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(None):
        raise FrontendSourceManifestError(f"{label}_timezone_invalid")
    observed_now = now_utc or datetime.now(timezone.utc)
    if observed_now.tzinfo is None:
        raise FrontendSourceManifestError("validation_now_timezone_invalid")
    if parsed.astimezone(timezone.utc) > observed_now.astimezone(timezone.utc):
        raise FrontendSourceManifestError(f"{label}_future")
    return parsed.astimezone(timezone.utc)


def _validate_generated_timestamps(
    value: Mapping[str, Any],
    *,
    label: str,
) -> None:
    for field in ("generated_at_utc", "generated_at"):
        if field in value:
            _require_not_future_utc(value.get(field), label=f"{label}_{field}")


def _safe_relative(value: object, *, label: str, source: bool = False) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or "\x00" in value
    ):
        raise FrontendSourceManifestError(f"{label}_path_invalid")
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or pure.as_posix() != value
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise FrontendSourceManifestError(f"{label}_path_invalid")
    if source:
        for part in pure.parts:
            if (
                part in FORBIDDEN_SOURCE_NAMES
                or part.startswith(".env.")
                or PurePosixPath(part).suffix.lower() in FORBIDDEN_SOURCE_SUFFIXES
            ):
                raise FrontendSourceManifestError("source_member_forbidden")
    return pure.as_posix()


def _reject_filesystem_traversal(path: Path, *, label: str) -> None:
    if ".." in path.parts:
        raise FrontendSourceManifestError(f"{label}_path_invalid")


def _safe_directory(path: Path, *, label: str, mode: int | None = None) -> os.stat_result:
    _reject_filesystem_traversal(path, label=label)
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise FrontendSourceManifestError(f"{label}_missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise FrontendSourceManifestError(f"{label}_unsafe")
    if mode is not None and stat.S_IMODE(metadata.st_mode) != mode:
        raise FrontendSourceManifestError(f"{label}_mode_invalid")
    return metadata


def _read_regular(path: Path, *, label: str) -> tuple[bytes, os.stat_result]:
    _reject_filesystem_traversal(path, label=label)
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise FrontendSourceManifestError(f"{label}_missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise FrontendSourceManifestError(f"{label}_unsafe")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise FrontendSourceManifestError(f"{label}_unsafe") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise FrontendSourceManifestError(f"{label}_unsafe")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    before_identity = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
        before.st_mtime_ns,
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_size,
        after.st_mtime_ns,
    )
    if len(payload) != before.st_size or before_identity != after_identity:
        raise FrontendSourceManifestError(f"{label}_drift")
    return payload, before


def _load_json(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    payload, _ = _read_regular(path, label=label)
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FrontendSourceManifestError(f"{label}_invalid") from exc
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise FrontendSourceManifestError(f"{label}_invalid")
    return value, payload


def _expected_json(
    path: Path, expected_sha256: object, *, label: str
) -> tuple[dict[str, Any], bytes, str]:
    expected = _valid_sha(expected_sha256, label=label)
    value, payload = _load_json(path, label=label)
    actual = _sha256_bytes(payload)
    if actual != expected:
        raise FrontendSourceManifestError(f"{label}_sha256_mismatch")
    return value, payload, actual


def _assert_no_side_effects(value: object, *, label: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FALSE_SIDE_EFFECT_KEYS and child is not False:
                raise FrontendSourceManifestError(f"{label}_side_effect_boundary_invalid")
            if key == "production_unchanged" and child is not True:
                raise FrontendSourceManifestError(f"{label}_production_boundary_invalid")
            _assert_no_side_effects(child, label=label)
    elif isinstance(value, list):
        for child in value:
            _assert_no_side_effects(child, label=label)


def _normalize_allowlist(values: Sequence[str]) -> list[str]:
    if not values:
        raise FrontendSourceManifestError("source_allowlist_empty")
    normalized = [_safe_relative(value, label="source_include", source=True) for value in values]
    if len(normalized) != len(set(normalized)):
        raise FrontendSourceManifestError("source_allowlist_duplicate")
    ordered = sorted(normalized)
    parts = [PurePosixPath(value).parts for value in ordered]
    for left_index, left in enumerate(parts):
        for right in parts[left_index + 1 :]:
            if len(left) < len(right) and right[: len(left)] == left:
                raise FrontendSourceManifestError("source_allowlist_overlap")
    return ordered


def _source_target(root: Path, relative: str) -> tuple[Path, os.stat_result]:
    current = root
    parts = PurePosixPath(relative).parts
    metadata: os.stat_result | None = None
    for index, part in enumerate(parts):
        current = current / part
        try:
            metadata = os.lstat(current)
        except OSError as exc:
            raise FrontendSourceManifestError("source_member_missing") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise FrontendSourceManifestError("source_member_unsafe")
        if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise FrontendSourceManifestError("source_member_unsafe")
    if metadata is None:
        raise FrontendSourceManifestError("source_member_missing")
    return current, metadata


def _source_file_row(root: Path, relative: str) -> dict[str, Any]:
    _safe_relative(relative, label="source_member", source=True)
    path, metadata = _source_target(root, relative)
    if not stat.S_ISREG(metadata.st_mode):
        raise FrontendSourceManifestError("source_member_unsafe")
    payload, _ = _read_regular(path, label="source_member")
    return {"path": relative, "bytes": len(payload), "sha256": _sha256_bytes(payload)}


def _walk_source_directory(root: Path, relative: str) -> list[dict[str, Any]]:
    path, metadata = _source_target(root, relative)
    if not stat.S_ISDIR(metadata.st_mode):
        raise FrontendSourceManifestError("source_member_unsafe")
    rows: list[dict[str, Any]] = []
    try:
        entries = sorted(os.scandir(path), key=lambda item: item.name)
    except OSError as exc:
        raise FrontendSourceManifestError("source_directory_unreadable") from exc
    for entry in entries:
        child_relative = f"{relative}/{entry.name}"
        _safe_relative(child_relative, label="source_member", source=True)
        try:
            child_metadata = entry.stat(follow_symlinks=False)
        except OSError as exc:
            raise FrontendSourceManifestError("source_member_missing") from exc
        if entry.is_symlink():
            raise FrontendSourceManifestError("source_member_unsafe")
        if stat.S_ISDIR(child_metadata.st_mode):
            rows.extend(_walk_source_directory(root, child_relative))
        elif stat.S_ISREG(child_metadata.st_mode):
            rows.append(_source_file_row(root, child_relative))
        else:
            raise FrontendSourceManifestError("source_member_unsafe")
    return rows


def _inventory_once(root: Path, allowlist: Sequence[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for relative in allowlist:
        _, metadata = _source_target(root, relative)
        if stat.S_ISDIR(metadata.st_mode):
            rows.extend(_walk_source_directory(root, relative))
        elif stat.S_ISREG(metadata.st_mode):
            rows.append(_source_file_row(root, relative))
        else:
            raise FrontendSourceManifestError("source_member_unsafe")
    rows.sort(key=lambda row: row["path"])
    if not rows:
        raise FrontendSourceManifestError("source_inventory_empty")
    paths = [row["path"] for row in rows]
    if len(paths) != len(set(paths)):
        raise FrontendSourceManifestError("source_inventory_duplicate")
    total_bytes = sum(row["bytes"] for row in rows)
    if len(rows) > MAX_SOURCE_FILES or total_bytes > MAX_SOURCE_BYTES:
        raise FrontendSourceManifestError("source_inventory_bound_exceeded")
    return rows


def _build_source_inventory(
    root: Path, allowlist: Sequence[str]
) -> tuple[list[dict[str, Any]], str]:
    _safe_directory(root, label="source_root")
    first = _inventory_once(root, allowlist)
    second = _inventory_once(root, allowlist)
    if first != second:
        raise FrontendSourceManifestError("source_inventory_drift")
    return second, _sha256_bytes(_canonical_bytes(second))


def _validate_plan_a(args: argparse.Namespace) -> dict[str, str]:
    candidate_input = _valid_sha(
        args.expected_plan_a_candidate_input_sha256,
        label="plan_a_candidate_input",
    )
    root = Path(args.plan_a_candidate_root)
    _safe_directory(root, label="plan_a_candidate_root")
    if root.name != candidate_input:
        raise FrontendSourceManifestError("plan_a_candidate_root_identity_mismatch")
    manifest, _, manifest_sha = _expected_json(
        root / "candidate-data-manifest.json",
        args.expected_plan_a_candidate_data_manifest_sha256,
        label="plan_a_candidate_data_manifest",
    )
    reconciliation, reconciliation_payload, reconciliation_sha = _expected_json(
        root / "candidate-data-reconciliation-ledger.jsonl",
        args.expected_plan_a_reconciliation_sha256,
        label="plan_a_reconciliation",
    )
    if len(reconciliation_payload.splitlines()) != 1:
        raise FrontendSourceManifestError("plan_a_reconciliation_rows_invalid")
    receipt, _, receipt_sha = _expected_json(
        root / "candidate-data-validation-receipt.json",
        args.expected_plan_a_independent_validation_receipt_sha256,
        label="plan_a_independent_validation_receipt",
    )
    if (
        manifest.get("schema_version") != PLAN_A_MANIFEST_SCHEMA
        or manifest.get("status") != "candidate_data_built_local"
        or manifest.get("candidate_input_sha256") != candidate_input
    ):
        raise FrontendSourceManifestError("plan_a_candidate_data_manifest_contract_invalid")
    reconciliation_contract = manifest.get("reconciliation")
    if (
        not isinstance(reconciliation_contract, dict)
        or reconciliation_contract.get("path")
        != "candidate-data-reconciliation-ledger.jsonl"
        or reconciliation_contract.get("sha256") != reconciliation_sha
        or reconciliation.get("schema_version") != PLAN_A_RECONCILIATION_SCHEMA
        or reconciliation.get("candidate_input_sha256") != candidate_input
    ):
        raise FrontendSourceManifestError("plan_a_reconciliation_contract_invalid")
    if (
        receipt.get("schema_version") != PLAN_A_RECEIPT_SCHEMA
        or receipt.get("status") != "passed"
        or receipt.get("candidate_input_sha256") != candidate_input
        or receipt.get("candidate_data_manifest_sha256") != manifest_sha
        or receipt.get("reconciliation_sha256") != reconciliation_sha
    ):
        raise FrontendSourceManifestError("plan_a_independent_receipt_contract_invalid")
    _assert_no_side_effects(manifest, label="plan_a_manifest")
    _assert_no_side_effects(reconciliation, label="plan_a_reconciliation")
    _assert_no_side_effects(receipt, label="plan_a_receipt")
    return {
        "plan_a_candidate_input_sha256": candidate_input,
        "plan_a_candidate_data_manifest_sha256": manifest_sha,
        "plan_a_reconciliation_sha256": reconciliation_sha,
        "plan_a_independent_validation_receipt_sha256": receipt_sha,
    }


def _validate_public_receipt(args: argparse.Namespace) -> str:
    receipt, _, digest = _expected_json(
        Path(args.public_validation_receipt),
        args.expected_public_validation_receipt_sha256,
        label="public_validation_receipt",
    )
    if (
        receipt.get("schema_version") != PUBLIC_RECEIPT_SCHEMA
        or receipt.get("status") != "passed_release_candidate"
        or receipt.get("production_unchanged") is not True
    ):
        raise FrontendSourceManifestError("public_validation_receipt_contract_invalid")
    _assert_no_side_effects(receipt, label="public_validation_receipt")
    return digest


def _v3_mode(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "v3_lineage", False))


def _v3_receipt_arguments(args: argparse.Namespace) -> dict[str, tuple[Path, str]]:
    result: dict[str, tuple[Path, str]] = {}
    for name in sorted(DATASET_NAMES):
        raw_path = getattr(args, f"{name}_validation_receipt", None)
        raw_sha = getattr(args, f"expected_{name}_validation_receipt_sha256", None)
        if not isinstance(raw_path, str) or not raw_path:
            raise FrontendSourceManifestError(f"v3_{name}_validation_receipt_missing")
        result[name] = (
            Path(raw_path),
            _valid_sha(raw_sha, label=f"v3_{name}_validation_receipt"),
        )
    return result


def _v3_auxiliary_arguments(args: argparse.Namespace) -> list[dict[str, str]]:
    values = getattr(args, "v3_auxiliary_public_manifest", None) or []
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in values:
        if not isinstance(raw, str) or "=" not in raw:
            raise FrontendSourceManifestError("v3_auxiliary_manifest_argument_invalid")
        relative_raw, expected_raw = raw.rsplit("=", 1)
        relative = _safe_relative(
            relative_raw, label="v3_auxiliary_manifest", source=True
        )
        if not relative.startswith("public/data/reddit-voc/") or relative in seen:
            raise FrontendSourceManifestError("v3_auxiliary_manifest_argument_invalid")
        seen.add(relative)
        records.append(
            {
                "relative_path": relative,
                "sha256": _valid_sha(expected_raw, label="v3_auxiliary_manifest"),
            }
        )
    return sorted(records, key=lambda row: row["relative_path"])


def _validate_periodic_report_publication(
    args: argparse.Namespace,
    *,
    source_root: Path,
    release_id: str,
    inventory_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    raw_relative = getattr(args, "periodic_publication_manifest", None)
    raw_sha = getattr(
        args, "expected_periodic_publication_manifest_sha256", None
    )
    if not raw_relative and not raw_sha:
        return None
    if not isinstance(raw_relative, str) or not raw_relative or not raw_sha:
        raise FrontendSourceManifestError(
            "periodic_publication_manifest_argument_incomplete"
        )
    relative = _safe_relative(
        raw_relative, label="periodic_publication_manifest", source=True
    )
    expected_sha = _valid_sha(raw_sha, label="periodic_publication_manifest")
    parts = PurePosixPath(relative).parts
    if (
        len(parts) != 4
        or parts[0] != "public"
        or parts[1] != "periodic-report-assets"
        or parts[3] != "manifest.json"
    ):
        raise FrontendSourceManifestError(
            "periodic_publication_manifest_path_invalid"
        )
    bundle_id = parts[2]
    inventory = _inventory_map(inventory_rows)
    row = inventory.get(relative)
    if row is None or row.get("sha256") != expected_sha:
        raise FrontendSourceManifestError(
            "periodic_publication_manifest_inventory_mismatch"
        )
    manifest, _, observed_sha = _expected_json(
        source_root / relative,
        expected_sha,
        label="periodic_publication_manifest",
    )
    assets = manifest.get("assets")
    boundaries = manifest.get("boundaries")
    if (
        manifest.get("schema_version") != PERIODIC_PUBLIC_MANIFEST_SCHEMA
        or manifest.get("status") != "publication_candidate_not_deployed"
        or manifest.get("bundle_id") != bundle_id
        or manifest.get("data_release_id") != release_id
        or not isinstance(assets, list)
        or len(assets) != len(PERIODIC_GRAINS)
        or not isinstance(boundaries, dict)
        or boundaries.get("public_png_only") is not True
        or boundaries.get("private_outbox_excluded") is not True
        or boundaries.get("destination_fingerprint_excluded") is not True
        or boundaries.get("credential_material_excluded") is not True
        or boundaries.get("production_unchanged") is not True
        or any(
            boundaries.get(key) is not False
            for key in ("deploy", "remote_write", "live_send", "webhook_send")
        )
    ):
        raise FrontendSourceManifestError(
            "periodic_publication_manifest_contract_invalid"
        )
    asset_records: list[dict[str, Any]] = []
    seen_grains: set[str] = set()
    for asset in assets:
        if not isinstance(asset, dict):
            raise FrontendSourceManifestError("periodic_publication_asset_invalid")
        grain = asset.get("grain")
        if grain not in PERIODIC_GRAINS or grain in seen_grains:
            raise FrontendSourceManifestError("periodic_publication_asset_invalid")
        seen_grains.add(grain)
        asset_relative = (
            f"public/periodic-report-assets/{bundle_id}/public/{grain}/poster.png"
        )
        if asset.get("relative_path") != asset_relative.removeprefix("public/"):
            raise FrontendSourceManifestError("periodic_publication_asset_invalid")
        asset_sha = _valid_sha(
            asset.get("sha256"), label="periodic_publication_asset"
        )
        asset_bytes = asset.get("bytes")
        parsed = urlsplit(str(asset.get("public_url", "")))
        expected_url_path = "/" + asset_relative.removeprefix("public/")
        asset_row = inventory.get(asset_relative)
        if (
            not isinstance(asset_bytes, int)
            or isinstance(asset_bytes, bool)
            or asset_bytes <= 0
            or parsed.scheme != "https"
            or parsed.path != expected_url_path
            or asset_row is None
            or asset_row.get("sha256") != asset_sha
            or asset_row.get("bytes") != asset_bytes
        ):
            raise FrontendSourceManifestError("periodic_publication_asset_invalid")
        asset_records.append(
            {
                "grain": grain,
                "relative_path": asset_relative,
                "bytes": asset_bytes,
                "sha256": asset_sha,
            }
        )
    if seen_grains != set(PERIODIC_GRAINS):
        raise FrontendSourceManifestError("periodic_publication_asset_set_invalid")
    asset_records.sort(key=lambda record: PERIODIC_GRAINS.index(record["grain"]))
    return {
        "contract": "reddit_voc_periodic_report_frontend_publication_v1",
        "manifest_relative_path": relative,
        "manifest_sha256": observed_sha,
        "bundle_id": bundle_id,
        "data_release_id": release_id,
        "source_bundle_manifest_sha256": _valid_sha(
            manifest.get("source_bundle_manifest_sha256"),
            label="periodic_source_bundle_manifest",
        ),
        "assets": asset_records,
    }


def _validate_v3_lineage(
    args: argparse.Namespace,
    *,
    source_root: Path,
    current_release_relative: str,
    current_release_sha256: str,
    inventory_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Rebuild the V3 pointer contract and bind all four independent receipts."""

    try:
        from scripts.build_reddit_v3_current_release import (
            V3CurrentReleaseContractError,
            build_v3_current_release,
        )
    except ModuleNotFoundError:  # Direct ``python scripts/...`` execution.
        from build_reddit_v3_current_release import (  # type: ignore[no-redef]
            V3CurrentReleaseContractError,
            build_v3_current_release,
        )

    pointer, _, observed_pointer_sha = _expected_json(
        source_root / current_release_relative,
        current_release_sha256,
        label="v3_current_release_pointer",
    )
    if observed_pointer_sha != current_release_sha256:
        raise FrontendSourceManifestError("v3_current_release_pointer_sha256_mismatch")
    pointer_schema = pointer.get("schema_version")
    expected_dataset_names = (
        V2_DATASET_NAMES
        if pointer_schema == "reddit_voc_current_release_v2"
        else DATASET_NAMES
    )
    datasets = pointer.get("datasets")
    if (
        pointer_schema not in CURRENT_RELEASE_SCHEMAS
        or not isinstance(datasets, dict)
        or set(datasets) != expected_dataset_names
    ):
        raise FrontendSourceManifestError("v3_current_release_datasets_invalid")
    _require_not_future_utc(
        pointer.get("generated_at_utc"),
        label="v3_current_release_generated_at_utc",
    )
    versions: dict[str, str] = {}
    for name in sorted(DATASET_NAMES):
        binding = datasets.get(name)
        version = binding.get("dataset_version") if isinstance(binding, dict) else None
        if not isinstance(version, str) or not version:
            raise FrontendSourceManifestError(f"v3_{name}_dataset_version_invalid")
        versions[name] = version

    receipt_arguments = _v3_receipt_arguments(args)
    receipt_payloads: dict[str, tuple[dict[str, Any], str]] = {}
    for name, (path, expected_sha) in receipt_arguments.items():
        receipt, _, digest = _expected_json(
            path, expected_sha, label=f"v3_{name}_validation_receipt"
        )
        if receipt.get("schema_version") != V3_RECEIPT_SCHEMAS[name]:
            raise FrontendSourceManifestError(
                f"v3_{name}_validation_receipt_schema_invalid"
            )
        _assert_no_side_effects(receipt, label=f"v3_{name}_validation_receipt")
        receipt_payloads[name] = (receipt, digest)

    if pointer_schema == "reddit_voc_current_release_v1":
        try:
            replayed = build_v3_current_release(
                public_root=source_root / "public",
                base_validation_receipt=receipt_arguments["base"][0],
                insights_validation_receipt=receipt_arguments["insights"][0],
                reports_validation_receipt=receipt_arguments["reports"][0],
                personas_validation_receipt=receipt_arguments["personas"][0],
                release_id=str(pointer.get("release_id")),
                generated_at_utc=str(pointer.get("generated_at_utc")),
                versions=versions,
            )
        except V3CurrentReleaseContractError as exc:
            raise FrontendSourceManifestError(
                f"v3_current_release_replay_failed:{exc}"
            ) from exc
        if replayed != pointer:
            raise FrontendSourceManifestError("v3_current_release_replay_mismatch")
    else:
        freshness = pointer.get("freshness")
        if (
            not isinstance(freshness, dict)
            or freshness.get("status") not in {"complete", "partial"}
            or freshness.get("timezone") != "Asia/Shanghai"
            or not isinstance(freshness.get("center_snapshot_id"), str)
            or not freshness.get("center_snapshot_id")
        ):
            raise FrontendSourceManifestError(
                "v3_current_release_freshness_invalid"
            )

    inventory = _inventory_map(inventory_rows)
    dataset_records: dict[str, dict[str, str]] = {}
    source_snapshot_ids: set[str] = set()
    for name in sorted(DATASET_NAMES):
        binding = datasets[name]
        manifest_relative = _pointer_source_path(
            current_release_relative, binding["manifest_path"]
        )
        row = inventory.get(manifest_relative)
        if row is None or row.get("sha256") != binding["public_manifest_sha256"]:
            raise FrontendSourceManifestError(f"v3_{name}_manifest_inventory_mismatch")
        manifest, _, manifest_sha = _expected_json(
            source_root / manifest_relative,
            binding["public_manifest_sha256"],
            label=f"v3_{name}_public_manifest",
        )
        if manifest.get("schema_version") != V3_MANIFEST_SCHEMAS[name]:
            raise FrontendSourceManifestError(f"v3_{name}_manifest_schema_invalid")
        _validate_generated_timestamps(manifest, label=f"v3_{name}_manifest")
        source_snapshot = (
            manifest.get("governed_signal_source_snapshot_id")
            if name == "personas"
            else manifest.get("source_snapshot_id")
        )
        if not isinstance(source_snapshot, str) or not source_snapshot:
            raise FrontendSourceManifestError(f"v3_{name}_source_snapshot_invalid")
        source_snapshot_ids.add(source_snapshot)
        dataset_records[name] = {
            "dataset_version": versions[name],
            "lineage_manifest_sha256": str(binding["lineage_manifest_sha256"]),
            "public_manifest_relative_path": manifest_relative,
            "public_manifest_sha256": manifest_sha,
            "validation_receipt_schema": V3_RECEIPT_SCHEMAS[name],
            "validation_receipt_sha256": receipt_payloads[name][1],
        }
    if len(source_snapshot_ids) != 1:
        raise FrontendSourceManifestError("v3_source_snapshot_mismatch")

    auxiliary = _v3_auxiliary_arguments(args)
    for record in auxiliary:
        row = inventory.get(record["relative_path"])
        if row is None or row.get("sha256") != record["sha256"]:
            raise FrontendSourceManifestError("v3_auxiliary_manifest_inventory_mismatch")
        manifest, _, _ = _expected_json(
            source_root / record["relative_path"],
            record["sha256"],
            label="v3_auxiliary_manifest",
        )
        _validate_generated_timestamps(manifest, label="v3_auxiliary_manifest")
        _assert_no_side_effects(manifest, label="v3_auxiliary_manifest")
    if pointer_schema == "reddit_voc_current_release_v2":
        auxiliary_by_path = {
            record["relative_path"]: record["sha256"] for record in auxiliary
        }
        for name in sorted(V2_AUXILIARY_DATASET_NAMES):
            binding = datasets.get(name)
            if not isinstance(binding, dict):
                raise FrontendSourceManifestError(
                    f"v3_{name}_dataset_binding_invalid"
                )
            manifest_relative = _pointer_source_path(
                current_release_relative, binding.get("manifest_path")
            )
            if (
                auxiliary_by_path.get(manifest_relative)
                != binding.get("public_manifest_sha256")
                or binding.get("lineage_manifest_sha256")
                != binding.get("public_manifest_sha256")
            ):
                raise FrontendSourceManifestError(
                    f"v3_{name}_auxiliary_binding_mismatch"
                )

    return {
        "contract": (
            V3_LINEAGE_CONTRACT_V2
            if pointer_schema == "reddit_voc_current_release_v2"
            else V3_LINEAGE_CONTRACT
        ),
        "source_snapshot_id": next(iter(source_snapshot_ids)),
        "current_release_pointer_sha256": current_release_sha256,
        "datasets": dataset_records,
        "auxiliary_public_manifests": auxiliary,
    }


def _inventory_map(rows: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(row["path"]): row for row in rows}


def _pointer_source_path(pointer_relative: str, web_relative: object) -> str:
    web = _safe_relative(web_relative, label="current_release_target", source=True)
    pointer_parts = PurePosixPath(pointer_relative).parts
    try:
        data_index = pointer_parts.index("data")
    except ValueError as exc:
        raise FrontendSourceManifestError("current_release_relative_path_invalid") from exc
    prefix = PurePosixPath(*pointer_parts[:data_index])
    return (prefix / web).as_posix()


def _require_pointer_target(
    inventory: Mapping[str, Mapping[str, Any]],
    pointer_relative: str,
    web_relative: object,
    expected_sha256: object,
) -> None:
    source_relative = _pointer_source_path(pointer_relative, web_relative)
    row = inventory.get(source_relative)
    if row is None:
        raise FrontendSourceManifestError("current_release_target_missing")
    expected = _valid_sha(expected_sha256, label="current_release_target")
    if row.get("sha256") != expected:
        raise FrontendSourceManifestError("current_release_target_sha256_mismatch")


def _validate_current_release(
    source_root: Path,
    relative: str,
    expected_sha256: object,
    inventory_rows: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    normalized = _safe_relative(relative, label="current_release", source=True)
    pointer, _, digest = _expected_json(
        source_root / normalized,
        expected_sha256,
        label="current_release_pointer",
    )
    inventory = _inventory_map(inventory_rows)
    pointer_row = inventory.get(normalized)
    if pointer_row is None or pointer_row.get("sha256") != digest:
        raise FrontendSourceManifestError("current_release_pointer_not_in_inventory")
    release_id = pointer.get("release_id")
    if (
        pointer.get("schema_version") not in CURRENT_RELEASE_SCHEMAS
        or not isinstance(release_id, str)
        or not release_id
    ):
        raise FrontendSourceManifestError("current_release_pointer_contract_invalid")
    datasets = pointer.get("datasets")
    expected_dataset_names = (
        V2_DATASET_NAMES
        if pointer.get("schema_version") == "reddit_voc_current_release_v2"
        else DATASET_NAMES
    )
    if not isinstance(datasets, dict) or set(datasets) != expected_dataset_names:
        raise FrontendSourceManifestError("current_release_datasets_invalid")
    for name in sorted(expected_dataset_names):
        contract = datasets.get(name)
        if not isinstance(contract, dict):
            raise FrontendSourceManifestError("current_release_dataset_contract_invalid")
        _require_pointer_target(
            inventory,
            normalized,
            contract.get("manifest_path"),
            contract.get("public_manifest_sha256"),
        )
    cases = pointer.get("cases")
    if not isinstance(cases, dict):
        raise FrontendSourceManifestError("current_release_cases_invalid")
    _require_pointer_target(
        inventory,
        normalized,
        cases.get("manifest_path"),
        cases.get("public_manifest_sha256"),
    )
    _require_pointer_target(
        inventory,
        normalized,
        cases.get("index_path"),
        cases.get("index_sha256"),
    )
    boundaries = pointer.get("boundaries")
    if not isinstance(boundaries, dict) or boundaries.get("login_required") is not False:
        raise FrontendSourceManifestError("current_release_boundaries_invalid")
    return {
        "relative_path": normalized,
        "pointer_sha256": digest,
        "schema_version": str(pointer["schema_version"]),
        "release_id": release_id,
    }


def _validate_toolchain(
    args: argparse.Namespace,
    source_root: Path,
    inventory_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    relative = _safe_relative(
        args.package_lock_relative_path, label="package_lock", source=True
    )
    lock, _, digest = _expected_json(
        source_root / relative,
        args.expected_package_lock_sha256,
        label="package_lock",
    )
    row = _inventory_map(inventory_rows).get(relative)
    if row is None or row.get("sha256") != digest:
        raise FrontendSourceManifestError("package_lock_not_in_inventory")
    lockfile_version = lock.get("lockfileVersion")
    if (
        isinstance(lockfile_version, bool)
        or not isinstance(lockfile_version, int)
        or lockfile_version < 1
    ):
        raise FrontendSourceManifestError("package_lock_version_invalid")
    for label, value in (("node_version", args.node_version), ("npm_version", args.npm_version)):
        if not isinstance(value, str) or VERSION_RE.fullmatch(value) is None:
            raise FrontendSourceManifestError(f"{label}_invalid")
    return {
        "package_lock_relative_path": relative,
        "package_lock_sha256": digest,
        "lockfile_version": lockfile_version,
        "node_version": args.node_version,
        "npm_version": args.npm_version,
    }


def _build_manifest(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    source_root = Path(args.source_root)
    root_label = _safe_relative(args.source_root_label, label="source_root_label")
    allowlist = _normalize_allowlist(args.include)
    inventory_rows, inventory_sha = _build_source_inventory(source_root, allowlist)
    current_release = _validate_current_release(
        source_root,
        args.current_release_relative_path,
        args.expected_current_release_pointer_sha256,
        inventory_rows,
    )
    if _v3_mode(args):
        upstream: dict[str, Any] = {
            "v3_lineage": _validate_v3_lineage(
                args,
                source_root=source_root,
                current_release_relative=current_release["relative_path"],
                current_release_sha256=current_release["pointer_sha256"],
                inventory_rows=inventory_rows,
            )
        }
        periodic_publication = _validate_periodic_report_publication(
            args,
            source_root=source_root,
            release_id=current_release["release_id"],
            inventory_rows=inventory_rows,
        )
        if periodic_publication is not None:
            upstream["periodic_report_publication"] = periodic_publication
        schema_version = V3_SCHEMA_VERSION
        evidence_grade = "L2_local_v3_source_contract"
    else:
        upstream = _validate_plan_a(args)
        upstream["public_validation_receipt_sha256"] = _validate_public_receipt(args)
        schema_version = SCHEMA_VERSION
        evidence_grade = "L2_local_source_contract"
    toolchain = _validate_toolchain(args, source_root, inventory_rows)
    allowlist_sha = _sha256_bytes(_canonical_bytes(allowlist))
    candidate_input = {
        "current_release_pointer_sha256": current_release["pointer_sha256"],
        "node_version": toolchain["node_version"],
        "npm_version": toolchain["npm_version"],
        "package_lock_sha256": toolchain["package_lock_sha256"],
        "upstream_lineage_sha256": _sha256_bytes(_canonical_bytes(upstream)),
        "source_allowlist_sha256": allowlist_sha,
        "source_inventory_sha256": inventory_sha,
        "source_root_label": root_label,
    }
    if not _v3_mode(args):
        # Preserve the byte-for-byte V1 identity contract for existing releases.
        candidate_input.pop("upstream_lineage_sha256")
        candidate_input.update(upstream)
    candidate_identity = _sha256_bytes(_canonical_bytes(candidate_input))
    manifest = {
        "schema_version": schema_version,
        "status": "frontend_source_frozen_local",
        "frontend_candidate_input_sha256": candidate_identity,
        "candidate_input": candidate_input,
        "source": {
            "root_label": root_label,
            "allowlist": allowlist,
            "inventory": {
                "file_count": len(inventory_rows),
                "total_bytes": sum(row["bytes"] for row in inventory_rows),
                "inventory_sha256": inventory_sha,
                "files": inventory_rows,
            },
        },
        "upstream": upstream,
        "current_release": current_release,
        "toolchain": toolchain,
        "evidence_grade": evidence_grade,
        "boundaries": dict(BOUNDARIES),
    }
    return candidate_identity, manifest


def _ensure_output_root(path: Path) -> None:
    _reject_filesystem_traversal(path, label="output_root")
    if path.exists() or path.is_symlink():
        _safe_directory(path, label="output_root", mode=0o700)
        return
    _safe_directory(path.parent, label="output_root_parent")
    try:
        path.mkdir(mode=0o700)
    except OSError as exc:
        raise FrontendSourceManifestError("output_root_create_failed") from exc
    _safe_directory(path, label="output_root", mode=0o700)


def _existing_status(target: Path, payload: bytes) -> str:
    _safe_directory(target, label="frontend_candidate_root", mode=0o700)
    frontend = target / "frontend"
    source = frontend / "source"
    _safe_directory(frontend, label="frontend_directory", mode=0o700)
    _safe_directory(source, label="frontend_source_directory", mode=0o700)
    members = {path.name for path in source.iterdir()}
    allowed = {
        "frontend-source-manifest.json",
        "candidate-ui-source-validation-receipt.json",
    }
    if "frontend-source-manifest.json" not in members or not members <= allowed:
        raise FrontendSourceManifestError("frontend_source_publication_inventory_invalid")
    manifest_path = source / "frontend-source-manifest.json"
    existing, metadata = _read_regular(manifest_path, label="frontend_source_manifest")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise FrontendSourceManifestError("frontend_source_manifest_mode_invalid")
    if existing != payload:
        raise FrontendSourceManifestError("frontend_source_manifest_immutable_collision")
    receipt = source / "candidate-ui-source-validation-receipt.json"
    if receipt.exists() or receipt.is_symlink():
        _, receipt_metadata = _read_regular(receipt, label="frontend_source_receipt")
        if stat.S_IMODE(receipt_metadata.st_mode) != 0o600:
            raise FrontendSourceManifestError("frontend_source_receipt_mode_invalid")
    return "no_change"


def _materialize(output_root: Path, identity: str, payload: bytes) -> str:
    _ensure_output_root(output_root)
    target = output_root / identity
    if target.exists() or target.is_symlink():
        return _existing_status(target, payload)
    staging = Path(tempfile.mkdtemp(prefix=".frontend-source-staging-", dir=output_root))
    try:
        os.chmod(staging, 0o700)
        frontend = staging / "frontend"
        source = frontend / "source"
        frontend.mkdir(mode=0o700)
        source.mkdir(mode=0o700)
        manifest_path = source / "frontend-source-manifest.json"
        descriptor = os.open(
            manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            staging.rename(target)
            return "created"
        except OSError:
            if target.exists() or target.is_symlink():
                return _existing_status(target, payload)
            raise
    except FrontendSourceManifestError:
        raise
    except OSError as exc:
        raise FrontendSourceManifestError("frontend_source_publication_failed") from exc
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def build_frontend_source_manifest(args: argparse.Namespace) -> dict[str, Any]:
    identity, manifest = _build_manifest(args)
    payload = _canonical_bytes(manifest) + b"\n"
    status = _materialize(Path(args.output_root), identity, payload)
    return {
        "status": status,
        "frontend_candidate_input_sha256": identity,
        "frontend_source_manifest_sha256": _sha256_bytes(payload),
        "candidate_relative_root": f"{identity}/frontend/source",
        "production_unchanged": True,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--source-root-label", required=True)
    parser.add_argument("--include", action="append", required=True)
    parser.add_argument("--v3-lineage", action="store_true")
    parser.add_argument("--plan-a-candidate-root")
    parser.add_argument("--expected-plan-a-candidate-input-sha256")
    parser.add_argument("--expected-plan-a-candidate-data-manifest-sha256")
    parser.add_argument("--expected-plan-a-reconciliation-sha256")
    parser.add_argument(
        "--expected-plan-a-independent-validation-receipt-sha256"
    )
    parser.add_argument("--public-validation-receipt")
    parser.add_argument("--expected-public-validation-receipt-sha256")
    for name in sorted(DATASET_NAMES):
        parser.add_argument(f"--{name}-validation-receipt")
        parser.add_argument(f"--expected-{name}-validation-receipt-sha256")
    parser.add_argument("--v3-auxiliary-public-manifest", action="append")
    parser.add_argument("--periodic-publication-manifest")
    parser.add_argument(
        "--expected-periodic-publication-manifest-sha256"
    )
    parser.add_argument("--current-release-relative-path", required=True)
    parser.add_argument("--expected-current-release-pointer-sha256", required=True)
    parser.add_argument("--package-lock-relative-path", required=True)
    parser.add_argument("--expected-package-lock-sha256", required=True)
    parser.add_argument("--node-version", required=True)
    parser.add_argument("--npm-version", required=True)
    parser.add_argument("--output-root", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = build_frontend_source_manifest(args)
    except FrontendSourceManifestError as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True))
        return 1
    except OSError:
        print(json.dumps({"status": "failed", "reason": "filesystem_operation_failed"}, sort_keys=True))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
