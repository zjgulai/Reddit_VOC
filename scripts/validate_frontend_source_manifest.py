#!/usr/bin/env python3
"""Independently validate a Plan-B frontend source freeze and local gates.

The validator never imports the source-manifest builder.  It reopens every
source byte and Plan-A upstream receipt, rebuilds the selected public/source
tree in an isolated directory, executes the local frontend gates there, and
writes one deterministic non-promotable L2 receipt.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import urlsplit


MANIFEST_SCHEMA = "reddit_voc_frontend_source_manifest_v1"
V3_MANIFEST_SCHEMA = "reddit_voc_frontend_source_manifest_v2"
RECEIPT_SCHEMA = "reddit_voc_candidate_ui_source_validation_receipt_v1"
V3_RECEIPT_SCHEMA = "reddit_voc_candidate_ui_source_validation_receipt_v2"
PLAN_A_MANIFEST_SCHEMA = "reddit_voc_candidate_data_manifest_v1"
PLAN_A_RECEIPT_SCHEMA = "reddit_voc_candidate_data_validation_receipt_v1"
PUBLIC_RECEIPT_SCHEMA = "reddit_voc_public_projection_validation_v1"
CURRENT_RELEASE_SCHEMA = "reddit_voc_current_release_v1"
CURRENT_RELEASE_SCHEMAS = {
    CURRENT_RELEASE_SCHEMA,
    "reddit_voc_current_release_v2",
}
MANIFEST_STATUS = "frontend_source_frozen_local"
RECEIPT_STATUS = "passed_local_source_validation"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

ROOT_SOURCE_FILES = {
    ".gitignore",
    ".oxlintrc.json",
    "index.html",
    "package-lock.json",
    "package.json",
    "postcss.config.js",
    "tailwind.config.js",
    "tsconfig.app.json",
    "tsconfig.json",
    "tsconfig.node.json",
    "vite.config.ts",
    "vitest.config.ts",
    "vitest.setup.ts",
}
STATIC_PUBLIC_FILES = {
    "public/favicon.svg",
    "public/icons.svg",
    "public/robots.txt",
}
# The overview no longer renders the former mission hero.  Keep the source
# asset in the workbench for history, but do not require or stage it into a V3
# candidate release.
V3_STATIC_PUBLIC_FILES = STATIC_PUBLIC_FILES
EXPECTED_ROUTES = (
    "/",
    "/dashboard",
    "/dashboard/reports",
    "/dashboard/analytics",
    "/dashboard/insights",
    "/dashboard/search",
    "/dashboard/ugc-showcase",
    "/dashboard/messages",
    "/dashboard/settings",
    "/features",
    "/how-it-works",
    "/faq",
    "/cases",
)
DATASET_KEYS = ("base", "insights", "reports", "personas")
V2_AUXILIARY_DATASET_KEYS = ("brand_health", "casebook", "quarter_insights")
V2_DATASET_KEYS = (*DATASET_KEYS, *V2_AUXILIARY_DATASET_KEYS)
V3_LINEAGE_CONTRACT = "reddit_voc_v3_four_dataset_frontend_lineage_v1"
V3_LINEAGE_CONTRACT_V2 = "reddit_voc_v3_seven_dataset_frontend_lineage_v2"
V3_DATASET_MANIFEST_SCHEMAS = {
    "base": "reddit_voc_site_snapshot_manifest_v3",
    "insights": "reddit_voc_insights_public_manifest_v3",
    "reports": "reddit_voc_reports_public_manifest_v3",
    "personas": "reddit_voc_personas_manifest_v3",
}
V3_DATASET_RECEIPT_SCHEMAS = {
    "base": "reddit_voc_base_public_validation_receipt_v1",
    "insights": "reddit_voc_insights_public_validation_receipt_v3",
    "reports": "reddit_voc_reports_public_validation_receipt_v3",
    "personas": "reddit_voc_personas_validation_v3",
}
PERIODIC_PUBLIC_MANIFEST_SCHEMA = "reddit-voc-periodic-report-public-manifest-v1"
PERIODIC_GRAINS = ("daily", "weekly", "monthly")
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
FALSE_SIDE_EFFECT_KEYS = {
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


class FrontendSourceValidationError(ValueError):
    """One independent source or validation invariant failed."""


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise FrontendSourceValidationError(f"{label}_sha256_invalid")
    return value


def _require_not_future_utc(
    value: Any,
    *,
    label: str,
    now_utc: datetime | None = None,
) -> datetime:
    if not isinstance(value, str) or not value:
        raise FrontendSourceValidationError(f"{label}_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FrontendSourceValidationError(f"{label}_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(None):
        raise FrontendSourceValidationError(f"{label}_timezone_invalid")
    observed_now = now_utc or datetime.now(timezone.utc)
    if observed_now.tzinfo is None:
        raise FrontendSourceValidationError("validation_now_timezone_invalid")
    if parsed.astimezone(timezone.utc) > observed_now.astimezone(timezone.utc):
        raise FrontendSourceValidationError(f"{label}_future")
    return parsed.astimezone(timezone.utc)


def _validate_generated_timestamps(
    value: Mapping[str, Any],
    *,
    label: str,
) -> None:
    for field in ("generated_at_utc", "generated_at"):
        if field in value:
            _require_not_future_utc(value.get(field), label=f"{label}_{field}")


def _object(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise FrontendSourceValidationError(f"{label}_object_invalid")
    return value


def _assert_no_side_effects(value: Any, *, label: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FALSE_SIDE_EFFECT_KEYS and child is not False:
                raise FrontendSourceValidationError(f"{label}_side_effect_boundary_invalid")
            if key == "production_unchanged" and child is not True:
                raise FrontendSourceValidationError(f"{label}_production_boundary_invalid")
            _assert_no_side_effects(child, label=label)
    elif isinstance(value, list):
        for child in value:
            _assert_no_side_effects(child, label=label)


def _require_boundaries(value: Mapping[str, Any], *, label: str) -> None:
    if value.get("production_unchanged") is not True:
        raise FrontendSourceValidationError(f"{label}_production_boundary_invalid")
    for key in ("provider_call", "database_write", "remote_write", "deploy", "live_send"):
        if value.get(key) is not False:
            raise FrontendSourceValidationError(f"{label}_side_effect_boundary_invalid")
    _assert_no_side_effects(value, label=label)


def _safe_relative(value: Any, *, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise FrontendSourceValidationError(f"{label}_path_invalid")
    relative = PurePosixPath(value)
    if relative.is_absolute() or "." in relative.parts or ".." in relative.parts:
        raise FrontendSourceValidationError(f"{label}_path_traversal")
    return relative


def _lstat_regular(path: Path, *, label: str, mode: int | None = None) -> os.stat_result:
    if ".." in path.parts:
        raise FrontendSourceValidationError(f"{label}_path_traversal")
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise FrontendSourceValidationError(f"{label}_missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise FrontendSourceValidationError(f"{label}_unsafe")
    if mode is not None and stat.S_IMODE(metadata.st_mode) != mode:
        raise FrontendSourceValidationError(f"{label}_mode_invalid")
    return metadata


def _lstat_directory(path: Path, *, label: str, mode: int | None = None) -> os.stat_result:
    if ".." in path.parts:
        raise FrontendSourceValidationError(f"{label}_path_traversal")
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise FrontendSourceValidationError(f"{label}_missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise FrontendSourceValidationError(f"{label}_unsafe")
    if mode is not None and stat.S_IMODE(metadata.st_mode) != mode:
        raise FrontendSourceValidationError(f"{label}_mode_invalid")
    return metadata


def _safe_source_path(root: Path, relative: PurePosixPath, *, label: str) -> Path:
    _lstat_directory(root, label="source_root")
    current = root
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            metadata = os.lstat(current)
        except OSError as exc:
            raise FrontendSourceValidationError(f"{label}_missing") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise FrontendSourceValidationError(f"{label}_symlink")
        if index < len(relative.parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise FrontendSourceValidationError(f"{label}_ancestor_unsafe")
    return current


def _load_json(
    path: Path, *, label: str, canonical: bool = False, mode: int | None = None
) -> dict[str, Any]:
    _lstat_regular(path, label=label, mode=mode)
    try:
        payload = path.read_bytes()
        value = json.loads(payload)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FrontendSourceValidationError(f"{label}_json_invalid") from exc
    result = _object(value, label=label)
    if canonical and payload != _canonical_bytes(result) + b"\n":
        raise FrontendSourceValidationError(f"{label}_noncanonical")
    return result


def _expected_file(
    path: Path, expected_sha256: Any, *, label: str, mode: int | None = None
) -> str:
    expected = _require_sha(expected_sha256, label=label)
    _lstat_regular(path, label=label, mode=mode)
    actual = _file_sha256(path)
    if actual != expected:
        raise FrontendSourceValidationError(f"{label}_sha256_mismatch")
    return actual


def _file_row(root: Path, relative_text: str) -> dict[str, Any]:
    relative = _safe_relative(relative_text, label="source_inventory")
    path = _safe_source_path(root, relative, label=f"source_{relative_text}")
    metadata = _lstat_regular(path, label=f"source_{relative_text}")
    return {
        "path": relative.as_posix(),
        "bytes": metadata.st_size,
        "sha256": _file_sha256(path),
    }


def _walk_regular_files(root: Path, relative: PurePosixPath) -> set[str]:
    start = _safe_source_path(root, relative, label=f"allowlist_{relative.as_posix()}")
    metadata = os.lstat(start)
    if stat.S_ISREG(metadata.st_mode):
        return {relative.as_posix()}
    if not stat.S_ISDIR(metadata.st_mode):
        raise FrontendSourceValidationError("source_allowlist_special_file")
    paths: set[str] = set()
    for parent, directory_names, file_names in os.walk(start, followlinks=False):
        parent_path = Path(parent)
        for name in directory_names:
            child = parent_path / name
            child_meta = os.lstat(child)
            if stat.S_ISLNK(child_meta.st_mode) or not stat.S_ISDIR(child_meta.st_mode):
                raise FrontendSourceValidationError("source_allowlist_directory_unsafe")
        for name in file_names:
            child = parent_path / name
            child_meta = os.lstat(child)
            if stat.S_ISLNK(child_meta.st_mode) or not stat.S_ISREG(child_meta.st_mode):
                raise FrontendSourceValidationError("source_allowlist_file_unsafe")
            paths.add(child.relative_to(root).as_posix())
    return paths


def _expand_allowlist(root: Path, raw: Any) -> tuple[list[str], set[str]]:
    if not isinstance(raw, list) or not raw or not all(isinstance(item, str) for item in raw):
        raise FrontendSourceValidationError("source_allowlist_invalid")
    allowlist = [_safe_relative(item, label="source_allowlist").as_posix() for item in raw]
    if allowlist != sorted(set(allowlist)):
        raise FrontendSourceValidationError("source_allowlist_not_sorted_unique")
    selected: set[str] = set()
    for item in allowlist:
        expanded = _walk_regular_files(root, PurePosixPath(item))
        if selected & expanded:
            raise FrontendSourceValidationError("source_allowlist_ancestor_overlap")
        selected.update(expanded)
    return allowlist, selected


def _manifest_child_paths(
    public_root: Path, manifest_relative: str, expected_sha256: Any, *, label: str
) -> set[str]:
    relative = _safe_relative(manifest_relative, label=f"{label}_manifest")
    if not relative.as_posix().startswith("data/reddit-voc/"):
        raise FrontendSourceValidationError(f"{label}_manifest_scope_invalid")
    manifest_path = _safe_source_path(public_root, relative, label=f"{label}_manifest")
    _expected_file(manifest_path, expected_sha256, label=f"{label}_manifest")
    manifest = _load_json(manifest_path, label=f"{label}_manifest")
    files = _object(manifest.get("files"), label=f"{label}_manifest_files")
    selected = {relative.as_posix()}
    for child_text, raw_contract in files.items():
        child_relative = _safe_relative(child_text, label=f"{label}_file")
        contract = _object(raw_contract, label=f"{label}_file_contract")
        expected_child_sha = _require_sha(contract.get("sha256"), label=f"{label}_file")
        expected_bytes = contract.get("bytes")
        if not isinstance(expected_bytes, int) or isinstance(expected_bytes, bool) or expected_bytes < 0:
            raise FrontendSourceValidationError(f"{label}_file_bytes_invalid")
        full_relative = PurePosixPath(relative.parent, child_relative)
        child_path = _safe_source_path(public_root, full_relative, label=f"{label}_file")
        metadata = _lstat_regular(child_path, label=f"{label}_file")
        if metadata.st_size != expected_bytes or _file_sha256(child_path) != expected_child_sha:
            raise FrontendSourceValidationError(f"{label}_file_contract_mismatch")
        selected.add(full_relative.as_posix())
    return selected


def _validate_plan_a(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    root = Path(args.plan_a_candidate_root)
    _lstat_directory(root, label="plan_a_candidate_root", mode=0o700)
    expected_input = _require_sha(
        args.expected_plan_a_candidate_input_sha256,
        label="plan_a_candidate_input",
    )
    if root.name != expected_input:
        raise FrontendSourceValidationError("plan_a_candidate_root_identity_invalid")
    manifest_path = root / "candidate-data-manifest.json"
    reconciliation_path = root / "candidate-data-reconciliation-ledger.jsonl"
    receipt_path = root / "candidate-data-validation-receipt.json"
    manifest_sha = _expected_file(
        manifest_path,
        args.expected_plan_a_candidate_data_manifest_sha256,
        label="plan_a_manifest",
        mode=0o600,
    )
    reconciliation_sha = _expected_file(
        reconciliation_path,
        args.expected_plan_a_reconciliation_sha256,
        label="plan_a_reconciliation",
        mode=0o600,
    )
    receipt_sha = _expected_file(
        receipt_path,
        args.expected_plan_a_independent_validation_receipt_sha256,
        label="plan_a_receipt",
        mode=0o600,
    )
    manifest = _load_json(manifest_path, label="plan_a_manifest", canonical=True)
    receipt = _load_json(receipt_path, label="plan_a_receipt", canonical=True)
    reconciliation = _load_json(
        reconciliation_path, label="plan_a_reconciliation", canonical=True
    )
    if (
        manifest.get("schema_version") != PLAN_A_MANIFEST_SCHEMA
        or manifest.get("status") != "candidate_data_built_local"
        or manifest.get("candidate_input_sha256") != expected_input
    ):
        raise FrontendSourceValidationError("plan_a_manifest_contract_invalid")
    if (
        receipt.get("schema_version") != PLAN_A_RECEIPT_SCHEMA
        or receipt.get("status") != "passed"
        or receipt.get("candidate_input_sha256") != expected_input
        or receipt.get("candidate_data_manifest_sha256") != manifest_sha
        or receipt.get("reconciliation_sha256") != reconciliation_sha
    ):
        raise FrontendSourceValidationError("plan_a_receipt_contract_invalid")
    if (
        reconciliation.get("schema_version")
        != "reddit_voc_candidate_data_reconciliation_v1"
        or reconciliation.get("candidate_input_sha256") != expected_input
    ):
        raise FrontendSourceValidationError("plan_a_reconciliation_contract_invalid")
    _require_boundaries(
        _object(manifest.get("boundaries"), label="plan_a_manifest_boundaries"),
        label="plan_a_manifest",
    )
    _require_boundaries(
        _object(reconciliation.get("boundaries"), label="plan_a_reconciliation_boundaries"),
        label="plan_a_reconciliation",
    )
    _require_boundaries(
        _object(receipt.get("boundaries"), label="plan_a_receipt_boundaries"),
        label="plan_a_receipt",
    )

    public_path = Path(args.public_validation_receipt)
    public_sha = _expected_file(
        public_path,
        args.expected_public_validation_receipt_sha256,
        label="public_validation_receipt",
    )
    public = _load_json(public_path, label="public_validation_receipt")
    public_inventory = _object(public.get("public_inventory"), label="public_inventory")
    public_file_count = public_inventory.get("file_count")
    public_total_bytes = public_inventory.get("total_bytes")
    public_inventory_sha = public_inventory.get("inventory_sha256")
    if (
        public.get("schema_version") != PUBLIC_RECEIPT_SCHEMA
        or public.get("status") != "passed_release_candidate"
        or not isinstance(public_file_count, int)
        or isinstance(public_file_count, bool)
        or public_file_count <= 0
        or not isinstance(public_total_bytes, int)
        or isinstance(public_total_bytes, bool)
        or public_total_bytes <= 0
        or not isinstance(public_inventory_sha, str)
        or SHA256_RE.fullmatch(public_inventory_sha) is None
    ):
        raise FrontendSourceValidationError("public_validation_receipt_contract_invalid")
    _require_boundaries(public, label="public_validation_receipt")
    lineage = _object(manifest.get("lineage"), label="plan_a_lineage")
    counts = _object(manifest.get("counts"), label="plan_a_counts")
    if (
        lineage.get("public_validation_receipt_sha256") != public_sha
        or lineage.get("public_inventory_sha256") != public_inventory["inventory_sha256"]
        or counts.get("public_files") != public_inventory["file_count"]
        or counts.get("public_bytes") != public_inventory["total_bytes"]
    ):
        raise FrontendSourceValidationError("plan_a_public_lineage_invalid")
    return manifest, public


def _validate_current_release(
    source_root: Path,
    relative_text: str,
    expected_sha256: str,
    public_receipt: Mapping[str, Any],
) -> tuple[dict[str, Any], set[str]]:
    relative = _safe_relative(relative_text, label="current_release")
    if relative.as_posix() != "public/data/reddit-voc/current-release.json":
        raise FrontendSourceValidationError("current_release_path_invalid")
    pointer_path = _safe_source_path(source_root, relative, label="current_release")
    _expected_file(pointer_path, expected_sha256, label="current_release")
    pointer = _load_json(pointer_path, label="current_release")
    if pointer.get("schema_version") != "reddit_voc_current_release_v1":
        raise FrontendSourceValidationError("current_release_schema_invalid")
    release_id = pointer.get("release_id")
    if not isinstance(release_id, str) or not release_id:
        raise FrontendSourceValidationError("current_release_id_invalid")
    datasets = _object(pointer.get("datasets"), label="current_release_datasets")
    if set(datasets) != set(DATASET_KEYS):
        raise FrontendSourceValidationError("current_release_dataset_set_invalid")
    public_lineage = _object(public_receipt.get("lineage"), label="public_lineage")
    selected = {relative.as_posix()}
    public_root = source_root / "public"
    projection_rows: list[dict[str, Any]] = []
    for key in DATASET_KEYS:
        binding = _object(datasets[key], label=f"current_release_{key}")
        lineage = _object(public_lineage.get(key), label=f"public_lineage_{key}")
        dataset_version = binding.get("dataset_version")
        if (
            not isinstance(dataset_version, str)
            or dataset_version != lineage.get("dataset_version")
            or binding.get("public_manifest_sha256") != lineage.get("public_manifest_sha256")
            or binding.get("lineage_manifest_sha256") != lineage.get("private_manifest_sha256")
        ):
            raise FrontendSourceValidationError(f"current_release_{key}_lineage_invalid")
        manifest_relative = binding.get("manifest_path")
        if not isinstance(manifest_relative, str):
            raise FrontendSourceValidationError(f"current_release_{key}_manifest_path_invalid")
        child_paths = _manifest_child_paths(
            public_root,
            manifest_relative,
            binding.get("public_manifest_sha256"),
            label=key,
        )
        for path in child_paths:
            selected.add(f"public/{path}")
            row = _file_row(source_root, f"public/{path}")
            projection_rows.append({"path": path, "bytes": row["bytes"], "sha256": row["sha256"]})
    projection_rows.sort(key=lambda row: row["path"])
    public_inventory = _object(public_receipt.get("public_inventory"), label="public_inventory")
    if len(projection_rows) != public_inventory.get("file_count"):
        raise FrontendSourceValidationError("public_projection_file_count_invalid")
    inventory_text = "".join(
        f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in projection_rows
    )
    if (
        sum(int(row["bytes"]) for row in projection_rows) != public_inventory.get("total_bytes")
        or _sha256_bytes(inventory_text.encode("utf-8"))
        != public_inventory.get("inventory_sha256")
    ):
        raise FrontendSourceValidationError("public_projection_inventory_invalid")

    cases = _object(pointer.get("cases"), label="current_release_cases")
    receipt_cases = _object(public_receipt.get("cases"), label="public_receipt_cases")
    expected_case_paths = {
        "manifest_path": "data/cases/manifest.v1.json",
        "index_path": "data/cases/case-index.v1.json",
    }
    for field, expected_path in expected_case_paths.items():
        if cases.get(field) != expected_path:
            raise FrontendSourceValidationError("current_release_cases_path_invalid")
        selected.add(f"public/{expected_path}")
    if (
        cases.get("public_manifest_sha256") != receipt_cases.get("manifest_sha256")
        or cases.get("index_sha256") != receipt_cases.get("index_sha256")
        or cases.get("stock_content_preserved") is not True
        or cases.get("approved_delta_count") != 0
        or receipt_cases.get("selected_count") != 38
        or receipt_cases.get("unverified_count") != 12
        or receipt_cases.get("approved_delta_count") != 0
    ):
        raise FrontendSourceValidationError("current_release_cases_contract_invalid")
    _expected_file(
        source_root / "public" / expected_case_paths["manifest_path"],
        cases.get("public_manifest_sha256"),
        label="cases_manifest",
    )
    _expected_file(
        source_root / "public" / expected_case_paths["index_path"],
        cases.get("index_sha256"),
        label="cases_index",
    )
    selected.update(STATIC_PUBLIC_FILES)
    return pointer, selected


def _v3_receipt_arguments(args: argparse.Namespace) -> dict[str, tuple[Path, str]]:
    result: dict[str, tuple[Path, str]] = {}
    for name in DATASET_KEYS:
        raw_path = getattr(args, f"{name}_validation_receipt", None)
        raw_sha = getattr(args, f"expected_{name}_validation_receipt_sha256", None)
        if not isinstance(raw_path, str) or not raw_path:
            raise FrontendSourceValidationError(
                f"v3_{name}_validation_receipt_missing"
            )
        result[name] = (
            Path(raw_path),
            _require_sha(raw_sha, label=f"v3_{name}_validation_receipt"),
        )
    return result


def _v3_auxiliary_arguments(args: argparse.Namespace) -> list[dict[str, str]]:
    values = getattr(args, "v3_auxiliary_public_manifest", None) or []
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in values:
        if not isinstance(raw, str) or "=" not in raw:
            raise FrontendSourceValidationError(
                "v3_auxiliary_manifest_argument_invalid"
            )
        path_text, sha_text = raw.rsplit("=", 1)
        relative = _safe_relative(path_text, label="v3_auxiliary_manifest")
        normalized = relative.as_posix()
        if not normalized.startswith("public/data/reddit-voc/") or normalized in seen:
            raise FrontendSourceValidationError(
                "v3_auxiliary_manifest_argument_invalid"
            )
        seen.add(normalized)
        records.append(
            {
                "relative_path": normalized,
                "sha256": _require_sha(sha_text, label="v3_auxiliary_manifest"),
            }
        )
    return sorted(records, key=lambda row: row["relative_path"])


def _validate_periodic_report_publication(
    args: argparse.Namespace,
    *,
    source_root: Path,
    release_id: str,
) -> tuple[dict[str, Any] | None, set[str]]:
    raw_relative = getattr(args, "periodic_publication_manifest", None)
    raw_sha = getattr(
        args, "expected_periodic_publication_manifest_sha256", None
    )
    if not raw_relative and not raw_sha:
        return None, set()
    if not isinstance(raw_relative, str) or not raw_relative or not raw_sha:
        raise FrontendSourceValidationError(
            "periodic_publication_manifest_argument_incomplete"
        )
    relative = _safe_relative(raw_relative, label="periodic_publication_manifest")
    parts = relative.parts
    if (
        len(parts) != 4
        or parts[0] != "public"
        or parts[1] != "periodic-report-assets"
        or parts[3] != "manifest.json"
    ):
        raise FrontendSourceValidationError(
            "periodic_publication_manifest_path_invalid"
        )
    bundle_id = parts[2]
    expected_sha = _require_sha(raw_sha, label="periodic_publication_manifest")
    manifest_path = _safe_source_path(
        source_root, relative, label="periodic_publication_manifest"
    )
    observed_sha = _expected_file(
        manifest_path, expected_sha, label="periodic_publication_manifest"
    )
    manifest = _load_json(manifest_path, label="periodic_publication_manifest")
    if manifest_path.read_bytes() != _canonical_bytes(manifest):
        raise FrontendSourceValidationError(
            "periodic_publication_manifest_noncanonical"
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
        raise FrontendSourceValidationError(
            "periodic_publication_manifest_contract_invalid"
        )
    selected = {relative.as_posix()}
    asset_records: list[dict[str, Any]] = []
    seen_grains: set[str] = set()
    for asset in assets:
        if not isinstance(asset, dict):
            raise FrontendSourceValidationError("periodic_publication_asset_invalid")
        grain = asset.get("grain")
        if grain not in PERIODIC_GRAINS or grain in seen_grains:
            raise FrontendSourceValidationError("periodic_publication_asset_invalid")
        seen_grains.add(grain)
        asset_relative = PurePosixPath(
            "public",
            "periodic-report-assets",
            bundle_id,
            "public",
            str(grain),
            "poster.png",
        )
        if asset.get("relative_path") != asset_relative.as_posix().removeprefix(
            "public/"
        ):
            raise FrontendSourceValidationError("periodic_publication_asset_invalid")
        asset_sha = _require_sha(
            asset.get("sha256"), label="periodic_publication_asset"
        )
        asset_bytes = asset.get("bytes")
        parsed = urlsplit(str(asset.get("public_url", "")))
        expected_url_path = "/" + asset_relative.as_posix().removeprefix("public/")
        asset_path = _safe_source_path(
            source_root, asset_relative, label="periodic_publication_asset"
        )
        observed_asset_sha = _expected_file(
            asset_path, asset_sha, label="periodic_publication_asset"
        )
        if (
            not isinstance(asset_bytes, int)
            or isinstance(asset_bytes, bool)
            or asset_bytes <= 0
            or asset_path.stat().st_size != asset_bytes
            or observed_asset_sha != asset_sha
            or parsed.scheme != "https"
            or parsed.path != expected_url_path
        ):
            raise FrontendSourceValidationError("periodic_publication_asset_invalid")
        selected.add(asset_relative.as_posix())
        asset_records.append(
            {
                "grain": grain,
                "relative_path": asset_relative.as_posix(),
                "bytes": asset_bytes,
                "sha256": asset_sha,
            }
        )
    if seen_grains != set(PERIODIC_GRAINS):
        raise FrontendSourceValidationError(
            "periodic_publication_asset_set_invalid"
        )
    asset_records.sort(key=lambda record: PERIODIC_GRAINS.index(record["grain"]))
    binding = {
        "contract": "reddit_voc_periodic_report_frontend_publication_v1",
        "manifest_relative_path": relative.as_posix(),
        "manifest_sha256": observed_sha,
        "bundle_id": bundle_id,
        "data_release_id": release_id,
        "source_bundle_manifest_sha256": _require_sha(
            manifest.get("source_bundle_manifest_sha256"),
            label="periodic_source_bundle_manifest",
        ),
        "assets": asset_records,
    }
    return binding, selected


def _v3_manifest_version(manifest: Mapping[str, Any], name: str) -> object:
    return manifest.get("snapshot_id") if name == "personas" else manifest.get("dataset_version")


def _v3_source_snapshot(manifest: Mapping[str, Any], name: str) -> object:
    return (
        manifest.get("governed_signal_source_snapshot_id")
        if name == "personas"
        else manifest.get("source_snapshot_id")
    )


def _validate_v3_dataset_receipt(
    *,
    name: str,
    receipt_path: Path,
    expected_receipt_sha256: str,
    manifest: Mapping[str, Any],
    manifest_sha256: str,
) -> tuple[dict[str, Any], str]:
    digest = _expected_file(
        receipt_path,
        expected_receipt_sha256,
        label=f"v3_{name}_validation_receipt",
    )
    receipt = _load_json(receipt_path, label=f"v3_{name}_validation_receipt")
    expected_status = "passed" if name == "personas" else "passed_candidate_only"
    bound_manifest = (
        receipt.get("manifest_sha256")
        if name == "personas"
        else receipt.get("bundle_manifest_sha256")
    )
    if (
        receipt.get("schema_version") != V3_DATASET_RECEIPT_SCHEMAS[name]
        or receipt.get("status") != expected_status
        or receipt.get("promotable") is not True
        or bound_manifest != manifest_sha256
    ):
        raise FrontendSourceValidationError(
            f"v3_{name}_validation_receipt_contract_invalid"
        )
    if name == "personas":
        _require_boundaries(receipt, label=f"v3_{name}_validation_receipt")
        checks = _object(receipt.get("checks"), label="v3_personas_receipt_checks")
        if (
            receipt.get("snapshot_id") != manifest.get("snapshot_id")
            or receipt.get("consumption_status")
            != "eligible_for_downstream_consumption"
            or checks.get("deterministic_full_byte_replay") is not True
        ):
            raise FrontendSourceValidationError(
                "v3_personas_validation_receipt_lineage_invalid"
            )
    else:
        boundaries = _object(
            receipt.get("boundaries"), label=f"v3_{name}_receipt_boundaries"
        )
        _require_boundaries(boundaries, label=f"v3_{name}_validation_receipt")
        if receipt.get("privacy_safe_projection") is not True:
            raise FrontendSourceValidationError(
                f"v3_{name}_validation_receipt_privacy_invalid"
            )
        if "comparison_contract_proven" in manifest and (
            receipt.get("comparison_contract_proven")
            is not manifest.get("comparison_contract_proven")
            or receipt.get("comparison_contract_basis")
            != manifest.get("comparison_contract_basis")
            or receipt.get("completeness_percent")
            != manifest.get("completeness_percent")
            or receipt.get("data_owner_coverage_attestation_sha256")
            != manifest.get("data_owner_coverage_attestation_sha256")
        ):
            raise FrontendSourceValidationError(
                f"v3_{name}_validation_receipt_comparison_contract_invalid"
            )
        if name == "base":
            inputs = _object(manifest.get("inputs"), label="v3_base_manifest_inputs")
            checks = _object(receipt.get("checks"), label="v3_base_receipt_checks")
            if (
                receipt.get("public_manifest_sha256") != manifest_sha256
                or receipt.get("dataset_version") != manifest.get("dataset_version")
                or receipt.get("source_snapshot_id") != manifest.get("source_snapshot_id")
                or receipt.get("canonical_manifest_sha256")
                != manifest.get("lineage_manifest_sha256")
                or receipt.get("canonical_manifest_sha256")
                != inputs.get("canonical_manifest_sha256")
                or receipt.get("canonical_validation_receipt_sha256")
                != inputs.get("canonical_validation_receipt_sha256")
                or receipt.get("all_checks_passed") is not True
                or not checks
                or any(value is not True for value in checks.values())
            ):
                raise FrontendSourceValidationError(
                    "v3_base_validation_receipt_lineage_invalid"
                )
        elif (
            receipt.get("lineage_manifest_sha256")
            != manifest.get("lineage_manifest_sha256")
            or receipt.get("validation_receipt_sha256")
            != manifest.get("validation_receipt_sha256")
            or receipt.get("deterministic_full_byte_replay") is not True
        ):
            raise FrontendSourceValidationError(
                f"v3_{name}_validation_receipt_lineage_invalid"
            )
    return receipt, digest


def _validate_v3_current_release(
    source_root: Path,
    relative_text: str,
    expected_sha256: str,
    args: argparse.Namespace,
) -> tuple[dict[str, Any], set[str], dict[str, Any]]:
    relative = _safe_relative(relative_text, label="v3_current_release")
    if relative.as_posix() != "public/data/reddit-voc/current-release.json":
        raise FrontendSourceValidationError("v3_current_release_path_invalid")
    pointer_path = _safe_source_path(source_root, relative, label="v3_current_release")
    _expected_file(pointer_path, expected_sha256, label="v3_current_release")
    pointer = _load_json(pointer_path, label="v3_current_release")
    pointer_schema = pointer.get("schema_version")
    if pointer_schema not in CURRENT_RELEASE_SCHEMAS:
        raise FrontendSourceValidationError("v3_current_release_schema_invalid")
    _require_not_future_utc(
        pointer.get("generated_at_utc"),
        label="v3_current_release_generated_at_utc",
    )
    datasets = _object(pointer.get("datasets"), label="v3_current_release_datasets")
    expected_dataset_keys = (
        set(V2_DATASET_KEYS)
        if pointer_schema == "reddit_voc_current_release_v2"
        else set(DATASET_KEYS)
    )
    if set(datasets) != expected_dataset_keys:
        raise FrontendSourceValidationError("v3_current_release_dataset_set_invalid")
    pointer_boundaries = _object(
        pointer.get("boundaries"), label="v3_current_release_boundaries"
    )
    if pointer_boundaries != {
        "case_gallery_stock_preserved": True,
        "collector_isolation_required": True,
        "login_required": False,
    }:
        raise FrontendSourceValidationError("v3_current_release_boundaries_invalid")

    public_root = source_root / "public"
    selected = {relative.as_posix()}
    receipt_arguments = _v3_receipt_arguments(args)
    dataset_records: dict[str, dict[str, str]] = {}
    source_snapshot_ids: set[str] = set()
    comparison_states: dict[str, tuple[object, object, object, object]] = {}
    for name in DATASET_KEYS:
        binding = _object(datasets.get(name), label=f"v3_current_release_{name}")
        if set(binding) != {
            "dataset_version",
            "manifest_path",
            "public_manifest_sha256",
            "lineage_manifest_sha256",
        }:
            raise FrontendSourceValidationError(f"v3_{name}_binding_fields_invalid")
        version = binding.get("dataset_version")
        manifest_relative_text = binding.get("manifest_path")
        if not isinstance(version, str) or not isinstance(manifest_relative_text, str):
            raise FrontendSourceValidationError(f"v3_{name}_binding_invalid")
        expected_manifest_relative = (
            f"data/reddit-voc/{version}/manifest-public.json"
            if name == "base"
            else f"data/reddit-voc/{version}/public/manifest.json"
            if name in {"insights", "reports"}
            else f"data/reddit-voc/{version}/manifest.json"
        )
        if manifest_relative_text != expected_manifest_relative:
            raise FrontendSourceValidationError(f"v3_{name}_manifest_path_invalid")
        manifest_path = _safe_source_path(
            public_root,
            _safe_relative(manifest_relative_text, label=f"v3_{name}_manifest"),
            label=f"v3_{name}_manifest",
        )
        manifest_sha = _expected_file(
            manifest_path,
            binding.get("public_manifest_sha256"),
            label=f"v3_{name}_manifest",
        )
        manifest = _load_json(manifest_path, label=f"v3_{name}_manifest")
        if (
            manifest.get("schema_version") != V3_DATASET_MANIFEST_SCHEMAS[name]
            or _v3_manifest_version(manifest, name) != version
            or manifest.get("promotable") is not True
        ):
            raise FrontendSourceValidationError(f"v3_{name}_manifest_contract_invalid")
        _validate_generated_timestamps(manifest, label=f"v3_{name}_manifest")
        boundaries = _object(
            manifest.get("boundaries"), label=f"v3_{name}_manifest_boundaries"
        )
        _require_boundaries(boundaries, label=f"v3_{name}_manifest")
        source_snapshot = _v3_source_snapshot(manifest, name)
        if not isinstance(source_snapshot, str) or not source_snapshot:
            raise FrontendSourceValidationError(f"v3_{name}_source_snapshot_invalid")
        source_snapshot_ids.add(source_snapshot)
        if name == "personas":
            if (
                manifest.get("status") != "candidate_built"
                or manifest.get("consumption_status")
                != "eligible_for_downstream_consumption"
                or binding.get("lineage_manifest_sha256") != manifest_sha
                or boundaries.get("counts_are_content_entities_not_users") is not True
                or boundaries.get("author_level_personas") is not False
                or boundaries.get("real_user_images") is not False
            ):
                raise FrontendSourceValidationError(
                    "v3_personas_manifest_lineage_invalid"
                )
        else:
            comparison_contract_proven = manifest.get(
                "comparison_contract_proven"
            )
            has_explicit_comparison_contract = type(
                comparison_contract_proven
            ) is bool
            if has_explicit_comparison_contract:
                expected_completeness = (
                    100 if comparison_contract_proven else None
                )
                expected_basis = (
                    "owner_attested_dataset_scope_window"
                    if comparison_contract_proven
                    else "not_owner_attested"
                )
                attestation = manifest.get("coverage_attestation")
                attestation_sha = manifest.get(
                    "data_owner_coverage_attestation_sha256"
                )
                if (
                    manifest.get("completeness_percent")
                    != expected_completeness
                    or manifest.get("comparison_contract_basis")
                    != expected_basis
                    or (
                        comparison_contract_proven
                        and (
                            not isinstance(attestation, dict)
                            or attestation.get("source_snapshot_id")
                            != source_snapshot
                            or attestation.get("completeness_percent") != 100
                            or not isinstance(attestation_sha, str)
                        )
                    )
                    or (
                        not comparison_contract_proven
                        and (
                            attestation is not None
                            or attestation_sha is not None
                            or manifest.get(
                                "comparison_unavailable_reason_codes"
                            )
                            != [
                                "historical_collection_coverage_not_owner_attested_complete"
                            ]
                        )
                    )
                ):
                    raise FrontendSourceValidationError(
                        f"v3_{name}_comparison_contract_invalid"
                    )
                comparison_states[name] = (
                    comparison_contract_proven,
                    expected_basis,
                    expected_completeness,
                    attestation_sha,
                )
            if (
                manifest.get("status") != "validated_candidate"
                or manifest.get("privacy_safe_projection") is not True
                or binding.get("lineage_manifest_sha256")
                != manifest.get("lineage_manifest_sha256")
            ):
                raise FrontendSourceValidationError(
                    f"v3_{name}_manifest_lineage_invalid"
                )
            if name == "base":
                expected_base_basis = (
                    "data_owner_declaration"
                    if not has_explicit_comparison_contract
                    or comparison_contract_proven
                    else "not_owner_attested"
                )
                if (
                    manifest.get("completeness_basis")
                    != expected_base_basis
                    or (
                        not has_explicit_comparison_contract
                        and manifest.get("completeness_percent") != 100
                    )
                ):
                    raise FrontendSourceValidationError(
                        "v3_base_completeness_basis_invalid"
                    )
            if name in {"insights", "reports"} and (
                manifest.get("fixture_only") is not False
                or manifest.get("independent_validation_status") != "passed"
                or not has_explicit_comparison_contract
            ):
                raise FrontendSourceValidationError(
                    f"v3_{name}_comparison_contract_invalid"
                )
        selected.update(
            f"public/{path}"
            for path in _manifest_child_paths(
                public_root,
                manifest_relative_text,
                manifest_sha,
                label=f"v3_{name}",
            )
        )
        _, receipt_sha = _validate_v3_dataset_receipt(
            name=name,
            receipt_path=receipt_arguments[name][0],
            expected_receipt_sha256=receipt_arguments[name][1],
            manifest=manifest,
            manifest_sha256=manifest_sha,
        )
        if name in {"insights", "reports"}:
            sidecar_relative = PurePosixPath(manifest_relative_text).parent / "public-validation-receipt.json"
            sidecar_path = _safe_source_path(
                public_root, sidecar_relative, label=f"v3_{name}_public_receipt_sidecar"
            )
            _expected_file(
                sidecar_path,
                receipt_sha,
                label=f"v3_{name}_public_receipt_sidecar",
            )
            selected.add(f"public/{sidecar_relative.as_posix()}")
        dataset_records[name] = {
            "dataset_version": version,
            "lineage_manifest_sha256": str(binding["lineage_manifest_sha256"]),
            "public_manifest_relative_path": f"public/{manifest_relative_text}",
            "public_manifest_sha256": manifest_sha,
            "validation_receipt_schema": V3_DATASET_RECEIPT_SCHEMAS[name],
            "validation_receipt_sha256": receipt_sha,
        }
    if len(source_snapshot_ids) != 1:
        raise FrontendSourceValidationError("v3_source_snapshot_mismatch")
    if comparison_states.get("insights") != comparison_states.get("reports"):
        raise FrontendSourceValidationError("v3_comparison_contract_mismatch")
    if "base" in comparison_states:
        if comparison_states["base"] != comparison_states["insights"]:
            raise FrontendSourceValidationError(
                "v3_base_comparison_contract_mismatch"
            )
    elif comparison_states.get("insights", ())[:3] != (
        True,
        "owner_attested_dataset_scope_window",
        100,
    ):
        raise FrontendSourceValidationError(
            "v3_legacy_base_cannot_bind_unattested_release"
        )

    cases = _object(pointer.get("cases"), label="v3_current_release_cases")
    if (
        cases.get("manifest_path") != "data/cases/manifest.v1.json"
        or cases.get("index_path") != "data/cases/case-index.v1.json"
        or cases.get("stock_content_preserved") is not True
    ):
        raise FrontendSourceValidationError("v3_current_release_cases_contract_invalid")
    cases_manifest_path = public_root / "data/cases/manifest.v1.json"
    cases_index_path = public_root / "data/cases/case-index.v1.json"
    _expected_file(
        cases_manifest_path,
        cases.get("public_manifest_sha256"),
        label="v3_cases_manifest",
    )
    _expected_file(
        cases_index_path, cases.get("index_sha256"), label="v3_cases_index"
    )
    cases_manifest = _load_json(cases_manifest_path, label="v3_cases_manifest")
    cases_index = _load_json(cases_index_path, label="v3_cases_index")
    seed = _object(cases_manifest.get("seed"), label="v3_cases_seed")
    legacy = _object(
        cases_manifest.get("legacyUnverified"), label="v3_cases_legacy"
    )
    approved = _object(
        cases_manifest.get("approvedDelta"), label="v3_cases_approved"
    )
    approved_rows = cases_index.get("approvedDelta")
    if (
        seed.get("count") != 38
        or legacy.get("count") != 12
        or not isinstance(approved_rows, list)
        or approved.get("count") != len(approved_rows)
        or cases.get("approved_delta_count") != len(approved_rows)
        or cases_index.get("datasetVersion") != cases.get("dataset_version")
    ):
        raise FrontendSourceValidationError("v3_cases_stock_contract_invalid")
    selected.update(
        {
            "public/data/cases/manifest.v1.json",
            "public/data/cases/case-index.v1.json",
            *V3_STATIC_PUBLIC_FILES,
        }
    )

    auxiliary = _v3_auxiliary_arguments(args)
    for record in auxiliary:
        relative_source = _safe_relative(
            record["relative_path"], label="v3_auxiliary_manifest"
        )
        manifest_path = _safe_source_path(
            source_root, relative_source, label="v3_auxiliary_manifest"
        )
        _expected_file(
            manifest_path, record["sha256"], label="v3_auxiliary_manifest"
        )
        manifest = _load_json(manifest_path, label="v3_auxiliary_manifest")
        _validate_generated_timestamps(manifest, label="v3_auxiliary_manifest")
        boundaries = manifest.get("boundaries")
        if isinstance(boundaries, dict):
            _require_boundaries(boundaries, label="v3_auxiliary_manifest")
        public_relative = relative_source.as_posix().removeprefix("public/")
        selected.update(
            f"public/{path}"
            for path in _manifest_child_paths(
                public_root,
                public_relative,
                record["sha256"],
                label="v3_auxiliary",
            )
        )
    if pointer_schema == "reddit_voc_current_release_v2":
        freshness = _object(
            pointer.get("freshness"), label="v3_current_release_freshness"
        )
        if (
            freshness.get("status") not in {"complete", "partial"}
            or freshness.get("timezone") != "Asia/Shanghai"
            or not isinstance(freshness.get("center_snapshot_id"), str)
            or not freshness.get("center_snapshot_id")
        ):
            raise FrontendSourceValidationError(
                "v3_current_release_freshness_invalid"
            )
        auxiliary_by_path = {
            record["relative_path"]: record["sha256"] for record in auxiliary
        }
        for name in V2_AUXILIARY_DATASET_KEYS:
            binding = _object(
                datasets.get(name), label=f"v3_current_release_{name}"
            )
            expected_source_path = f"public/{binding.get('manifest_path')}"
            if (
                auxiliary_by_path.get(expected_source_path)
                != binding.get("public_manifest_sha256")
                or binding.get("lineage_manifest_sha256")
                != binding.get("public_manifest_sha256")
            ):
                raise FrontendSourceValidationError(
                    f"v3_{name}_auxiliary_binding_mismatch"
                )

    lineage = {
        "contract": (
            V3_LINEAGE_CONTRACT_V2
            if pointer_schema == "reddit_voc_current_release_v2"
            else V3_LINEAGE_CONTRACT
        ),
        "source_snapshot_id": next(iter(source_snapshot_ids)),
        "current_release_pointer_sha256": expected_sha256,
        "datasets": dataset_records,
        "auxiliary_public_manifests": auxiliary,
    }
    return pointer, selected, lineage


def _validate_source_manifest(
    args: argparse.Namespace,
    plan_a: Mapping[str, Any],
    public_receipt: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    source_root = Path(args.source_root)
    _lstat_directory(source_root, label="source_root")
    manifest_path = Path(args.manifest)
    manifest_sha = _expected_file(
        manifest_path,
        args.expected_frontend_source_manifest_sha256,
        label="frontend_source_manifest",
        mode=0o600,
    )
    manifest = _load_json(
        manifest_path,
        label="frontend_source_manifest",
        canonical=True,
        mode=0o600,
    )
    if manifest.get("schema_version") != MANIFEST_SCHEMA or manifest.get("status") != MANIFEST_STATUS:
        raise FrontendSourceValidationError("frontend_source_manifest_contract_invalid")
    identity = _require_sha(
        manifest.get("frontend_candidate_input_sha256"), label="frontend_candidate_input"
    )
    if manifest_path.name != "frontend-source-manifest.json" or manifest_path.parent.name != "source":
        raise FrontendSourceValidationError("frontend_source_manifest_path_invalid")
    if manifest_path.parent.parent.name != "frontend" or manifest_path.parents[2].name != identity:
        raise FrontendSourceValidationError("frontend_candidate_root_identity_invalid")

    upstream = _object(manifest.get("upstream"), label="frontend_upstream")
    expected_upstream = {
        "plan_a_candidate_input_sha256": args.expected_plan_a_candidate_input_sha256,
        "plan_a_candidate_data_manifest_sha256": args.expected_plan_a_candidate_data_manifest_sha256,
        "plan_a_reconciliation_sha256": args.expected_plan_a_reconciliation_sha256,
        "plan_a_independent_validation_receipt_sha256": args.expected_plan_a_independent_validation_receipt_sha256,
        "public_validation_receipt_sha256": args.expected_public_validation_receipt_sha256,
    }
    if upstream != expected_upstream:
        raise FrontendSourceValidationError("frontend_upstream_binding_invalid")
    if plan_a.get("candidate_input_sha256") != upstream["plan_a_candidate_input_sha256"]:
        raise FrontendSourceValidationError("frontend_plan_a_identity_invalid")

    current = _object(manifest.get("current_release"), label="frontend_current_release")
    if (
        current.get("relative_path") != args.current_release_relative_path
        or current.get("pointer_sha256") != args.expected_current_release_sha256
    ):
        raise FrontendSourceValidationError("frontend_current_release_binding_invalid")
    pointer, expected_public_paths = _validate_current_release(
        source_root,
        args.current_release_relative_path,
        args.expected_current_release_sha256,
        public_receipt,
    )
    if (
        current.get("schema_version") != pointer.get("schema_version")
        or current.get("release_id") != pointer.get("release_id")
    ):
        raise FrontendSourceValidationError("frontend_current_release_identity_invalid")

    toolchain = _object(manifest.get("toolchain"), label="frontend_toolchain")
    expected_toolchain = {
        "package_lock_relative_path": args.package_lock_relative_path,
        "package_lock_sha256": args.expected_package_lock_sha256,
        "lockfile_version": None,
        "node_version": args.expected_node_version,
        "npm_version": args.expected_npm_version,
    }
    package_lock_relative = _safe_relative(
        args.package_lock_relative_path, label="package_lock"
    )
    package_lock_path = _safe_source_path(source_root, package_lock_relative, label="package_lock")
    _expected_file(package_lock_path, args.expected_package_lock_sha256, label="package_lock")
    package_lock = _load_json(package_lock_path, label="package_lock")
    expected_toolchain["lockfile_version"] = package_lock.get("lockfileVersion")
    if toolchain != expected_toolchain:
        raise FrontendSourceValidationError("frontend_toolchain_binding_invalid")

    source = _object(manifest.get("source"), label="frontend_source")
    if source.get("root_label") != args.source_root_label:
        raise FrontendSourceValidationError("frontend_source_root_label_invalid")
    allowlist, selected = _expand_allowlist(source_root, source.get("allowlist"))
    expected_nonpublic = set(ROOT_SOURCE_FILES)
    expected_nonpublic.update(_walk_regular_files(source_root, PurePosixPath("src")))
    expected_paths = expected_nonpublic | expected_public_paths
    if selected != expected_paths:
        raise FrontendSourceValidationError("source_allowlist_inventory_scope_invalid")
    inventory = _object(source.get("inventory"), label="source_inventory")
    raw_files = inventory.get("files")
    if not isinstance(raw_files, list):
        raise FrontendSourceValidationError("source_inventory_files_invalid")
    files: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_files):
        row = _object(raw, label=f"source_inventory_{index}")
        if set(row) != {"path", "bytes", "sha256"}:
            raise FrontendSourceValidationError("source_inventory_row_fields_invalid")
        files.append(row)
    if [row.get("path") for row in files] != sorted(expected_paths):
        raise FrontendSourceValidationError("source_inventory_paths_invalid")
    recomputed = [_file_row(source_root, path) for path in sorted(expected_paths)]
    if files != recomputed:
        raise FrontendSourceValidationError("source_inventory_file_contract_invalid")
    inventory_sha = _sha256_bytes(_canonical_bytes(files))
    total_bytes = sum(row["bytes"] for row in files)
    if inventory != {
        "file_count": len(files),
        "total_bytes": total_bytes,
        "inventory_sha256": inventory_sha,
        "files": files,
    }:
        raise FrontendSourceValidationError("source_inventory_summary_invalid")

    candidate_input = _object(manifest.get("candidate_input"), label="frontend_candidate_input")
    expected_candidate_input = {
        "current_release_pointer_sha256": args.expected_current_release_sha256,
        "node_version": args.expected_node_version,
        "npm_version": args.expected_npm_version,
        "package_lock_sha256": args.expected_package_lock_sha256,
        **expected_upstream,
        "source_allowlist_sha256": _sha256_bytes(_canonical_bytes(allowlist)),
        "source_inventory_sha256": inventory_sha,
        "source_root_label": args.source_root_label,
    }
    if candidate_input != expected_candidate_input:
        raise FrontendSourceValidationError("frontend_candidate_input_contract_invalid")
    if _sha256_bytes(_canonical_bytes(candidate_input)) != identity:
        raise FrontendSourceValidationError("frontend_candidate_input_identity_invalid")
    if manifest.get("evidence_grade") != "L2_local_source_contract":
        raise FrontendSourceValidationError("frontend_evidence_grade_invalid")
    if manifest.get("boundaries") != BOUNDARIES:
        raise FrontendSourceValidationError("frontend_boundary_invalid")
    return manifest, files, {
        "manifest_sha256": manifest_sha,
        "identity": identity,
        "pointer": pointer,
        "toolchain": toolchain,
        "inventory_sha256": inventory_sha,
        "total_bytes": total_bytes,
    }


def _validate_v3_source_manifest(
    args: argparse.Namespace,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    source_root = Path(args.source_root)
    _lstat_directory(source_root, label="source_root")
    manifest_path = Path(args.manifest)
    manifest_sha = _expected_file(
        manifest_path,
        args.expected_frontend_source_manifest_sha256,
        label="frontend_source_manifest",
        mode=0o600,
    )
    manifest = _load_json(
        manifest_path,
        label="frontend_source_manifest",
        canonical=True,
        mode=0o600,
    )
    if (
        manifest.get("schema_version") != V3_MANIFEST_SCHEMA
        or manifest.get("status") != MANIFEST_STATUS
    ):
        raise FrontendSourceValidationError(
            "v3_frontend_source_manifest_contract_invalid"
        )
    identity = _require_sha(
        manifest.get("frontend_candidate_input_sha256"),
        label="frontend_candidate_input",
    )
    if (
        manifest_path.name != "frontend-source-manifest.json"
        or manifest_path.parent.name != "source"
        or manifest_path.parent.parent.name != "frontend"
        or manifest_path.parents[2].name != identity
    ):
        raise FrontendSourceValidationError("frontend_candidate_root_identity_invalid")

    current = _object(manifest.get("current_release"), label="frontend_current_release")
    if (
        current.get("relative_path") != args.current_release_relative_path
        or current.get("pointer_sha256") != args.expected_current_release_sha256
    ):
        raise FrontendSourceValidationError("frontend_current_release_binding_invalid")
    pointer, expected_public_paths, v3_lineage = _validate_v3_current_release(
        source_root,
        args.current_release_relative_path,
        args.expected_current_release_sha256,
        args,
    )
    if (
        current.get("schema_version") != pointer.get("schema_version")
        or current.get("release_id") != pointer.get("release_id")
    ):
        raise FrontendSourceValidationError("frontend_current_release_identity_invalid")
    expected_upstream = {"v3_lineage": v3_lineage}
    periodic_publication, periodic_paths = _validate_periodic_report_publication(
        args,
        source_root=source_root,
        release_id=str(pointer.get("release_id")),
    )
    if periodic_publication is not None:
        expected_upstream["periodic_report_publication"] = periodic_publication
        expected_public_paths.update(periodic_paths)
    if manifest.get("upstream") != expected_upstream:
        raise FrontendSourceValidationError("v3_frontend_upstream_binding_invalid")

    toolchain = _object(manifest.get("toolchain"), label="frontend_toolchain")
    package_lock_relative = _safe_relative(
        args.package_lock_relative_path, label="package_lock"
    )
    package_lock_path = _safe_source_path(
        source_root, package_lock_relative, label="package_lock"
    )
    _expected_file(
        package_lock_path,
        args.expected_package_lock_sha256,
        label="package_lock",
    )
    package_lock = _load_json(package_lock_path, label="package_lock")
    expected_toolchain = {
        "package_lock_relative_path": args.package_lock_relative_path,
        "package_lock_sha256": args.expected_package_lock_sha256,
        "lockfile_version": package_lock.get("lockfileVersion"),
        "node_version": args.expected_node_version,
        "npm_version": args.expected_npm_version,
    }
    if toolchain != expected_toolchain:
        raise FrontendSourceValidationError("frontend_toolchain_binding_invalid")

    source = _object(manifest.get("source"), label="frontend_source")
    if source.get("root_label") != args.source_root_label:
        raise FrontendSourceValidationError("frontend_source_root_label_invalid")
    allowlist, selected = _expand_allowlist(source_root, source.get("allowlist"))
    expected_nonpublic = set(ROOT_SOURCE_FILES)
    expected_nonpublic.update(_walk_regular_files(source_root, PurePosixPath("src")))
    expected_paths = expected_nonpublic | expected_public_paths
    if selected != expected_paths:
        raise FrontendSourceValidationError("source_allowlist_inventory_scope_invalid")
    inventory = _object(source.get("inventory"), label="source_inventory")
    raw_files = inventory.get("files")
    if not isinstance(raw_files, list):
        raise FrontendSourceValidationError("source_inventory_files_invalid")
    files: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_files):
        row = _object(raw, label=f"source_inventory_{index}")
        if set(row) != {"path", "bytes", "sha256"}:
            raise FrontendSourceValidationError("source_inventory_row_fields_invalid")
        files.append(row)
    if [row.get("path") for row in files] != sorted(expected_paths):
        raise FrontendSourceValidationError("source_inventory_paths_invalid")
    recomputed = [_file_row(source_root, path) for path in sorted(expected_paths)]
    if files != recomputed:
        raise FrontendSourceValidationError("source_inventory_file_contract_invalid")
    inventory_sha = _sha256_bytes(_canonical_bytes(files))
    total_bytes = sum(row["bytes"] for row in files)
    if inventory != {
        "file_count": len(files),
        "total_bytes": total_bytes,
        "inventory_sha256": inventory_sha,
        "files": files,
    }:
        raise FrontendSourceValidationError("source_inventory_summary_invalid")

    candidate_input = _object(
        manifest.get("candidate_input"), label="frontend_candidate_input"
    )
    expected_candidate_input = {
        "current_release_pointer_sha256": args.expected_current_release_sha256,
        "node_version": args.expected_node_version,
        "npm_version": args.expected_npm_version,
        "package_lock_sha256": args.expected_package_lock_sha256,
        "upstream_lineage_sha256": _sha256_bytes(
            _canonical_bytes(expected_upstream)
        ),
        "source_allowlist_sha256": _sha256_bytes(_canonical_bytes(allowlist)),
        "source_inventory_sha256": inventory_sha,
        "source_root_label": args.source_root_label,
    }
    if candidate_input != expected_candidate_input:
        raise FrontendSourceValidationError(
            "v3_frontend_candidate_input_contract_invalid"
        )
    if _sha256_bytes(_canonical_bytes(candidate_input)) != identity:
        raise FrontendSourceValidationError("frontend_candidate_input_identity_invalid")
    if manifest.get("evidence_grade") != "L2_local_v3_source_contract":
        raise FrontendSourceValidationError("frontend_evidence_grade_invalid")
    if manifest.get("boundaries") != BOUNDARIES:
        raise FrontendSourceValidationError("frontend_boundary_invalid")
    return manifest, files, {
        "manifest_sha256": manifest_sha,
        "identity": identity,
        "pointer": pointer,
        "toolchain": toolchain,
        "inventory_sha256": inventory_sha,
        "total_bytes": total_bytes,
        "v3_lineage": v3_lineage,
        "periodic_report_publication": periodic_publication,
    }


def _inventory(root: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for parent, directories, file_names in os.walk(root, followlinks=False):
        parent_path = Path(parent)
        for name in directories:
            metadata = os.lstat(parent_path / name)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise FrontendSourceValidationError("temporary_build_directory_unsafe")
        for name in file_names:
            path = parent_path / name
            metadata = os.lstat(path)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise FrontendSourceValidationError("temporary_build_file_unsafe")
            relative = path.relative_to(root).as_posix()
            rows.append({"path": relative, "bytes": metadata.st_size, "sha256": _file_sha256(path)})
    rows.sort(key=lambda row: row["path"])
    return {
        "file_count": len(rows),
        "total_bytes": sum(row["bytes"] for row in rows),
        "inventory_sha256": _sha256_bytes(_canonical_bytes(rows)),
    }


def _run_command(
    runner: Runner,
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    label: str,
) -> subprocess.CompletedProcess[str]:
    try:
        result = runner(
            list(argv), cwd=cwd, env=dict(env), capture_output=True, text=True, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise FrontendSourceValidationError(f"{label}_execution_failed") from exc
    if result.returncode != 0:
        diagnostic = "\n".join(
            part.strip()
            for part in (result.stdout, result.stderr)
            if isinstance(part, str) and part.strip()
        )
        if diagnostic:
            print(
                f"{label}_diagnostic:\n{diagnostic[-12000:]}",
                file=sys.stderr,
            )
        raise FrontendSourceValidationError(f"{label}_failed")
    return result


def _command_evidence(
    source_root: Path,
    files: Sequence[Mapping[str, Any]],
    args: argparse.Namespace,
    *,
    runner: Runner,
) -> dict[str, Any]:
    if not args.run_commands:
        raise FrontendSourceValidationError("frontend_command_execution_required")
    temporary_parent = Path(args.temporary_build_root)
    if temporary_parent.exists() or temporary_parent.is_symlink():
        _lstat_directory(temporary_parent, label="temporary_build_root")
    else:
        temporary_parent.mkdir(parents=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix=".planb-ui-validate-", dir=temporary_parent) as temporary_name:
        temporary = Path(temporary_name)
        os.chmod(temporary, 0o700)
        staged_source = temporary / "source"
        build_root = temporary / "non-promotable-preview"
        isolated_home = temporary / "home"
        isolated_tmp = temporary / "tmp"
        npm_cache = temporary / "npm-cache"
        staged_source.mkdir(mode=0o700)
        isolated_home.mkdir(mode=0o700)
        isolated_tmp.mkdir(mode=0o700)
        npm_cache.mkdir(mode=0o700)
        for row in files:
            relative = _safe_relative(row["path"], label="staged_source")
            source_path = _safe_source_path(source_root, relative, label="staged_source")
            destination = staged_source.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, destination)
        reviewed_node_modules = getattr(args, "reviewed_node_modules", None)
        node_modules = (
            Path(reviewed_node_modules)
            if isinstance(reviewed_node_modules, str) and reviewed_node_modules
            else source_root / "node_modules"
        )
        _lstat_directory(node_modules, label="node_modules")
        # The CLI accepts a repository-relative source root.  A relative link
        # target would be interpreted from the ephemeral staged directory and
        # therefore point at a non-existent nested path.
        node_modules_target = node_modules.resolve(strict=True)
        _lstat_directory(node_modules_target, label="node_modules_target")
        os.symlink(
            node_modules_target,
            staged_source / "node_modules",
            target_is_directory=True,
        )

        path_value = os.environ.get("PATH")
        if not path_value:
            raise FrontendSourceValidationError("frontend_command_path_missing")
        environment = {
                "PATH": path_value,
                "HOME": str(isolated_home),
                "TMPDIR": str(isolated_tmp),
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "CI": "1",
                "NO_COLOR": "1",
                "TERM": "dumb",
                "npm_config_offline": "true",
                "npm_config_audit": "false",
                "npm_config_fund": "false",
                "npm_config_update_notifier": "false",
                "npm_config_cache": str(npm_cache),
                "VITE_USE_MOCK": "false",
                "VITE_API_BASE_URL": "/api/v1",
                "REDDIT_VOC_BUILD_PUBLIC_DIR": str(staged_source / "public"),
                "REDDIT_VOC_BUILD_OUT_DIR": str(build_root),
        }
        node = _run_command(runner, ("node", "--version"), cwd=staged_source, env=environment, label="node_version")
        npm = _run_command(runner, ("npm", "--version"), cwd=staged_source, env=environment, label="npm_version")
        if node.stdout.strip() != args.expected_node_version or npm.stdout.strip() != args.expected_npm_version:
            raise FrontendSourceValidationError("frontend_runtime_toolchain_mismatch")
        unit = _run_command(runner, ("npm", "test", "--", "--run"), cwd=staged_source, env=environment, label="unit_tests")
        lint = _run_command(runner, ("npm", "run", "lint"), cwd=staged_source, env=environment, label="lint")
        _run_command(runner, ("npx", "tsc", "-b", "--pretty", "false"), cwd=staged_source, env=environment, label="typecheck")
        _run_command(
            runner,
            ("npm", "run", "build", "--", "--outDir", str(build_root)),
            cwd=staged_source,
            env=environment,
            label="temporary_build",
        )
        if not build_root.exists():
            raise FrontendSourceValidationError("temporary_build_output_missing")
        build_inventory = _inventory(build_root)
        if build_inventory["file_count"] == 0:
            raise FrontendSourceValidationError("temporary_build_output_empty")

        unit_text = ANSI_RE.sub("", f"{unit.stdout}\n{unit.stderr}")
        files_match = re.search(r"Test Files\s+(\d+)\s+passed", unit_text)
        tests_match = re.search(r"Tests\s+(\d+)\s+passed", unit_text)
        if files_match is None or tests_match is None:
            raise FrontendSourceValidationError("unit_test_summary_unparseable")
        lint_text = ANSI_RE.sub("", f"{lint.stdout}\n{lint.stderr}")
        warning_match = re.search(r"Found\s+(\d+)\s+warnings?", lint_text, re.IGNORECASE)
        warning_count = (
            int(warning_match.group(1))
            if warning_match
            else lint_text.count(": warning ")
        )
        public_rows = [row for row in files if str(row["path"]).startswith("public/")]
        expected_public_stage_rows = [
            {**row, "path": str(row["path"])[len("public/") :]}
            for row in public_rows
        ]
        expected_public_stage_rows.sort(key=lambda row: row["path"])
        public_stage_inventory = _inventory(staged_source / "public")
        if public_stage_inventory != {
            "file_count": len(expected_public_stage_rows),
            "total_bytes": sum(row["bytes"] for row in expected_public_stage_rows),
            "inventory_sha256": _sha256_bytes(_canonical_bytes(expected_public_stage_rows)),
        }:
            raise FrontendSourceValidationError("public_stage_inventory_mismatch")
        return {
            "environment": {
                "source_stage_from_manifest_only": True,
                "unlisted_public_excluded": True,
                "dotenv_local_excluded": True,
                "vite_use_mock": False,
                "vite_api_base_url": "/api/v1",
            },
            "toolchain": {"node_version": node.stdout.strip(), "npm_version": npm.stdout.strip()},
            "unit_tests": {
                "argv": ["npm", "test", "--", "--run"],
                "exit_code": 0,
                "passed_files": int(files_match.group(1)),
                "passed_tests": int(tests_match.group(1)),
            },
            "lint": {"argv": ["npm", "run", "lint"], "exit_code": 0, "warning_count": warning_count},
            "typecheck": {"argv": ["npx", "tsc", "-b", "--pretty", "false"], "exit_code": 0},
            "temporary_build": {
                "argv_contract": ["npm", "run", "build", "--", "--outDir", "<ephemeral-non-promotable-preview>"],
                "exit_code": 0,
                "public_stage_file_count": len(public_rows),
                "public_stage_inventory_sha256": public_stage_inventory["inventory_sha256"],
                **build_inventory,
                "promotable": False,
            },
        }


def _validate_routes(source_root: Path) -> None:
    app_path = _safe_source_path(source_root, PurePosixPath("src/App.tsx"), label="app_route_contract")
    _lstat_regular(app_path, label="app_route_contract")
    source = app_path.read_text(encoding="utf-8")
    try:
        route_block = source.split("export const PRODUCTION_ROUTE_DEFINITIONS = [", 1)[1].split(
            "] satisfies readonly ProductionRouteDefinition[];", 1
        )[0]
    except IndexError as exc:
        raise FrontendSourceValidationError("production_route_source_contract_missing") from exc
    routes = tuple(re.findall(r"\bpath:\s*'([^']+)'", route_block))
    if routes != EXPECTED_ROUTES or "login" in route_block.lower():
        raise FrontendSourceValidationError("production_route_source_contract_invalid")


def _write_immutable_receipt(path: Path, receipt: Mapping[str, Any]) -> str:
    parent = path.parent
    _lstat_directory(parent, label="receipt_parent", mode=0o700)
    payload = _canonical_bytes(receipt) + b"\n"
    if path.exists() or path.is_symlink():
        _lstat_regular(path, label="receipt", mode=0o600)
        if path.read_bytes() == payload:
            return "no_change"
        raise FrontendSourceValidationError("receipt_immutable_collision")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".ui-source-receipt-", dir=parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        stream = os.fdopen(descriptor, "wb")
        descriptor = -1
        with stream as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            _lstat_regular(path, label="receipt", mode=0o600)
            if path.read_bytes() != payload:
                raise FrontendSourceValidationError("receipt_immutable_collision")
            return "no_change"
        _lstat_regular(path, label="receipt", mode=0o600)
        if path.read_bytes() != payload:
            raise FrontendSourceValidationError("receipt_write_verification_failed")
        return "created"
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def validate_frontend_source_manifest(
    args: argparse.Namespace, *, runner: Runner = subprocess.run
) -> dict[str, Any]:
    manifest_preview = _load_json(
        Path(args.manifest),
        label="frontend_source_manifest",
        canonical=True,
        mode=0o600,
    )
    v3_mode = manifest_preview.get("schema_version") == V3_MANIFEST_SCHEMA
    if v3_mode:
        manifest, files, summary = _validate_v3_source_manifest(args)
    elif manifest_preview.get("schema_version") == MANIFEST_SCHEMA:
        plan_a, public_receipt = _validate_plan_a(args)
        manifest, files, summary = _validate_source_manifest(
            args, plan_a, public_receipt
        )
    else:
        raise FrontendSourceValidationError(
            "frontend_source_manifest_schema_invalid"
        )
    source_root = Path(args.source_root)
    _validate_routes(source_root)
    command_evidence = _command_evidence(source_root, files, args, runner=runner)
    receipt_path = Path(args.receipt)
    manifest_path = Path(args.manifest)
    if receipt_path != manifest_path.parent / "candidate-ui-source-validation-receipt.json":
        raise FrontendSourceValidationError("receipt_path_invalid")
    receipt: dict[str, Any] = {
        "schema_version": V3_RECEIPT_SCHEMA if v3_mode else RECEIPT_SCHEMA,
        "status": RECEIPT_STATUS,
        "frontend_candidate_input_sha256": summary["identity"],
        "frontend_source_manifest_sha256": summary["manifest_sha256"],
        "validator_code_sha256": _file_sha256(Path(__file__)),
        "upstream": deepcopy(manifest["upstream"]),
        "source_inventory": {
            "file_count": len(files),
            "total_bytes": summary["total_bytes"],
            "inventory_sha256": summary["inventory_sha256"],
        },
        "current_release": deepcopy(manifest["current_release"]),
        "toolchain": deepcopy(summary["toolchain"]),
        "checks": {
            "manifest_canonical_and_identity_exact": True,
            "source_allowlist_inventory_exact": True,
            "source_symlink_special_and_traversal_rejected": True,
            (
                "current_release_seven_datasets_exact"
                if v3_mode
                and manifest["current_release"]["schema_version"]
                == "reddit_voc_current_release_v2"
                else "current_release_four_datasets_and_cases_exact"
            ): True,
            "production_routes_13_no_login": True,
            "isolated_manifest_only_source_stage": True,
            "unit_lint_typecheck_temporary_build_passed": True,
            "immutable_private_receipt": True,
        },
        "command_evidence": command_evidence,
        "evidence_grade": (
            "L2_local_independent_v3_source_validation"
            if v3_mode
            else "L2_local_independent_source_validation"
        ),
        "boundaries": deepcopy(BOUNDARIES),
    }
    if v3_mode:
        seven_dataset_contract = (
            manifest["current_release"]["schema_version"]
            == "reddit_voc_current_release_v2"
        )
        receipt["checks"].update(
            {
                (
                    "v3_seven_dataset_manifest_receipt_lineage_exact"
                    if seven_dataset_contract
                    else "v3_four_dataset_manifest_receipt_lineage_exact"
                ): True,
                "v3_source_snapshot_consistent": True,
                "v3_no_legacy_plan_a_lineage": True,
            }
        )
        receipt["v3_lineage"] = deepcopy(summary["v3_lineage"])
        if summary["periodic_report_publication"] is not None:
            receipt["periodic_report_publication"] = deepcopy(
                summary["periodic_report_publication"]
            )
            receipt["checks"]["periodic_publication_manifest_and_assets_exact"] = True
    else:
        receipt["checks"].update(
            {
                "plan_a_five_sha_lineage_exact": True,
                "public_projection_inventory_exact": True,
            }
        )
        receipt["public_projection_inventory"] = deepcopy(
            public_receipt["public_inventory"]
        )
    publication_status = _write_immutable_receipt(receipt_path, receipt)
    return {
        "status": publication_status,
        "frontend_candidate_input_sha256": summary["identity"],
        "receipt_path": str(receipt_path),
        "receipt_sha256": _file_sha256(receipt_path),
        "evidence_grade": receipt["evidence_grade"],
        "production_unchanged": True,
        "promotable": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--expected-frontend-source-manifest-sha256", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--source-root-label", required=True)
    parser.add_argument("--plan-a-candidate-root")
    parser.add_argument("--expected-plan-a-candidate-input-sha256")
    parser.add_argument("--expected-plan-a-candidate-data-manifest-sha256")
    parser.add_argument("--expected-plan-a-reconciliation-sha256")
    parser.add_argument("--expected-plan-a-independent-validation-receipt-sha256")
    parser.add_argument("--public-validation-receipt")
    parser.add_argument("--expected-public-validation-receipt-sha256")
    for name in DATASET_KEYS:
        parser.add_argument(f"--{name}-validation-receipt")
        parser.add_argument(f"--expected-{name}-validation-receipt-sha256")
    parser.add_argument("--v3-auxiliary-public-manifest", action="append")
    parser.add_argument("--periodic-publication-manifest")
    parser.add_argument(
        "--expected-periodic-publication-manifest-sha256"
    )
    parser.add_argument("--current-release-relative-path", required=True)
    parser.add_argument("--expected-current-release-sha256", required=True)
    parser.add_argument("--package-lock-relative-path", required=True)
    parser.add_argument("--expected-package-lock-sha256", required=True)
    parser.add_argument("--expected-node-version", required=True)
    parser.add_argument("--expected-npm-version", required=True)
    parser.add_argument("--temporary-build-root", required=True)
    parser.add_argument("--reviewed-node-modules")
    parser.add_argument("--run-commands", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = validate_frontend_source_manifest(args)
    except FrontendSourceValidationError as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
