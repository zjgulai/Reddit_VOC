#!/usr/bin/env python3
"""Build one immutable current-release pointer from verified public artifacts.

The command only reads already-built dataset directories.  It does not copy
data into the UI tree, call a Provider, deploy, or modify an existing pointer
whose bytes differ from the requested release.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any


SCHEMA_VERSION = "reddit_voc_current_release_v1"
VERSION_PREFIXES = {
    "base": "reddit_voc_site_snapshot_",
    "insights": "reddit_voc_insights_",
    "reports": "reddit_voc_reports_",
    "personas": "reddit_voc_personas_",
}
VERSION_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,127}$")


class CurrentReleaseContractError(ValueError):
    """A public or lineage artifact does not satisfy the release contract."""


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink():
        raise CurrentReleaseContractError(f"{label}_unsafe")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise CurrentReleaseContractError(f"{label}_missing") from exc
    if not resolved.is_file():
        raise CurrentReleaseContractError(f"{label}_unsafe")
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CurrentReleaseContractError(f"{label}_invalid_json") from exc
    if not isinstance(value, dict):
        raise CurrentReleaseContractError(f"{label}_not_object")
    return value


def _dataset_version(manifest: dict[str, Any], key: str) -> str:
    value = manifest.get("dataset_version")
    prefix = VERSION_PREFIXES[key]
    if (
        not isinstance(value, str)
        or not value.startswith(prefix)
        or VERSION_RE.fullmatch(value) is None
    ):
        raise CurrentReleaseContractError(f"{key}_dataset_version_invalid")
    return value


def _utc(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CurrentReleaseContractError("generated_at_utc_invalid")
    candidate = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise CurrentReleaseContractError("generated_at_utc_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise CurrentReleaseContractError("generated_at_utc_not_utc")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_public_path(relative: PurePosixPath) -> str:
    if relative.is_absolute() or ".." in relative.parts:
        raise CurrentReleaseContractError("public_manifest_path_unsafe")
    return relative.as_posix()


def _require_linkage(
    *,
    base_manifest: dict[str, Any],
    insights_manifest: dict[str, Any],
    reports_manifest: dict[str, Any],
    personas_manifest: dict[str, Any],
    base_version: str,
    base_sha: str,
    insights_version: str,
    insights_sha: str,
) -> None:
    if (
        insights_manifest.get("base_dataset_version") != base_version
        or insights_manifest.get("base_manifest_sha256") != base_sha
    ):
        raise CurrentReleaseContractError("insights_base_linkage_mismatch")
    if (
        reports_manifest.get("base_dataset_version") != base_version
        or reports_manifest.get("base_manifest_sha256") != base_sha
        or reports_manifest.get("insights_dataset_version") != insights_version
        or reports_manifest.get("insights_manifest_sha256") != insights_sha
    ):
        raise CurrentReleaseContractError("reports_lineage_mismatch")
    if (
        personas_manifest.get("base_dataset_version") != base_version
        or personas_manifest.get("base_manifest_sha256") != base_sha
        or personas_manifest.get("insights_dataset_version") != insights_version
        or personas_manifest.get("insights_manifest_sha256") != insights_sha
    ):
        raise CurrentReleaseContractError("personas_lineage_mismatch")
    if base_manifest.get("all_checks_passed") is not True:
        raise CurrentReleaseContractError("base_not_validated")


def build_current_release(
    *,
    public_root: Path,
    base_source_dir: Path,
    insights_source_dir: Path,
    reports_source_dir: Path,
    personas_source_dir: Path,
    release_id: str,
    generated_at_utc: str,
) -> dict[str, Any]:
    if (
        not release_id.startswith("reddit_voc_release_")
        or VERSION_RE.fullmatch(release_id) is None
    ):
        raise CurrentReleaseContractError("release_id_invalid")
    generated_at = _utc(generated_at_utc)
    if public_root.is_symlink():
        raise CurrentReleaseContractError("public_root_unsafe")
    try:
        root = public_root.resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise CurrentReleaseContractError("public_root_missing") from exc
    if not root.is_dir():
        raise CurrentReleaseContractError("public_root_unsafe")

    source_dirs = {
        "base": base_source_dir,
        "insights": insights_source_dir,
        "reports": reports_source_dir,
        "personas": personas_source_dir,
    }
    lineage_manifests: dict[str, dict[str, Any]] = {}
    lineage_paths: dict[str, Path] = {}
    versions: dict[str, str] = {}
    for key, directory in source_dirs.items():
        manifest_path = directory / "manifest.json"
        lineage_manifests[key] = _load_object(
            manifest_path, label=f"{key}_lineage_manifest"
        )
        lineage_paths[key] = manifest_path.resolve(strict=True)
        versions[key] = _dataset_version(lineage_manifests[key], key)

    lineage_shas = {key: _sha256(path) for key, path in lineage_paths.items()}
    _require_linkage(
        base_manifest=lineage_manifests["base"],
        insights_manifest=lineage_manifests["insights"],
        reports_manifest=lineage_manifests["reports"],
        personas_manifest=lineage_manifests["personas"],
        base_version=versions["base"],
        base_sha=lineage_shas["base"],
        insights_version=versions["insights"],
        insights_sha=lineage_shas["insights"],
    )

    public_relatives = {
        "base": PurePosixPath(
            "data", "reddit-voc", versions["base"], "manifest-public.json"
        ),
        "insights": PurePosixPath(
            "data", "reddit-voc", versions["insights"], "public", "manifest.json"
        ),
        "reports": PurePosixPath(
            "data", "reddit-voc", versions["reports"], "public", "manifest.json"
        ),
        "personas": PurePosixPath(
            "data", "reddit-voc", versions["personas"], "manifest.json"
        ),
    }
    public_manifests: dict[str, dict[str, Any]] = {}
    public_paths: dict[str, Path] = {}
    for key, relative in public_relatives.items():
        path = root.joinpath(*relative.parts)
        public_manifests[key] = _load_object(path, label=f"{key}_public_manifest")
        public_paths[key] = path.resolve(strict=True)
        if public_manifests[key].get("dataset_version") != versions[key]:
            raise CurrentReleaseContractError(f"{key}_public_version_mismatch")

    # Public manifests must retain the private lineage bindings used by the UI.
    for key in ("insights", "reports", "personas"):
        private = lineage_manifests[key]
        public = public_manifests[key]
        for field in (
            "base_dataset_version",
            "base_manifest_sha256",
            "insights_dataset_version",
            "insights_manifest_sha256",
        ):
            if field in private and public.get(field) != private.get(field):
                raise CurrentReleaseContractError(
                    f"{key}_public_lineage_projection_mismatch"
                )

    cases_manifest_relative = PurePosixPath("data", "cases", "manifest.v1.json")
    cases_index_relative = PurePosixPath("data", "cases", "case-index.v1.json")
    cases_manifest_path = root.joinpath(*cases_manifest_relative.parts)
    cases_index_path = root.joinpath(*cases_index_relative.parts)
    cases_manifest = _load_object(cases_manifest_path, label="cases_manifest")
    cases_index = _load_object(cases_index_path, label="cases_index")
    dataset_version = cases_manifest.get("datasetVersion")
    if (
        not isinstance(dataset_version, str)
        or not dataset_version.startswith("case_catalog_")
        or VERSION_RE.fullmatch(dataset_version) is None
        or cases_index.get("datasetVersion") != dataset_version
    ):
        raise CurrentReleaseContractError("cases_dataset_version_mismatch")
    seed = cases_manifest.get("seed")
    legacy = cases_manifest.get("legacyUnverified")
    approved = cases_manifest.get("approvedDelta")
    index_contract = cases_manifest.get("index")
    approved_rows = cases_index.get("approvedDelta")
    if not all(isinstance(value, dict) for value in (seed, legacy, approved, index_contract)):
        raise CurrentReleaseContractError("cases_manifest_contract_invalid")
    if seed.get("count") != 38 or legacy.get("count") != 12:
        raise CurrentReleaseContractError("cases_stock_content_changed")
    if not isinstance(approved_rows, list) or approved.get("count") != len(approved_rows):
        raise CurrentReleaseContractError("cases_approved_delta_mismatch")
    index_sha = _sha256(cases_index_path)
    if (
        index_contract.get("path") != "/data/cases/case-index.v1.json"
        or index_contract.get("sha256") != index_sha
    ):
        raise CurrentReleaseContractError("cases_index_binding_mismatch")

    return {
        "schema_version": SCHEMA_VERSION,
        "release_id": release_id,
        "generated_at_utc": generated_at,
        "datasets": {
            key: {
                "dataset_version": versions[key],
                "manifest_path": _safe_public_path(public_relatives[key]),
                "public_manifest_sha256": _sha256(public_paths[key]),
                "lineage_manifest_sha256": lineage_shas[key],
            }
            for key in ("base", "insights", "reports", "personas")
        },
        "cases": {
            "dataset_version": dataset_version,
            "manifest_path": _safe_public_path(cases_manifest_relative),
            "public_manifest_sha256": _sha256(cases_manifest_path),
            "index_path": _safe_public_path(cases_index_relative),
            "index_sha256": index_sha,
            "stock_content_preserved": True,
            "approved_delta_count": len(approved_rows),
        },
        "boundaries": {
            "case_gallery_stock_preserved": True,
            "collector_isolation_required": True,
            "login_required": False,
        },
    }


def write_immutable_pointer(path: Path, value: dict[str, Any]) -> str:
    payload = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    ).encode("utf-8")
    if path.exists():
        if not path.is_file() or path.is_symlink():
            raise CurrentReleaseContractError("pointer_destination_unsafe")
        if path.read_bytes() != payload:
            raise CurrentReleaseContractError("pointer_immutable_collision")
        return "no_change"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    descriptor = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644
    )
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
    parser.add_argument("--base-source-dir", type=Path, required=True)
    parser.add_argument("--insights-source-dir", type=Path, required=True)
    parser.add_argument("--reports-source-dir", type=Path, required=True)
    parser.add_argument("--personas-source-dir", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--generated-at-utc", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    pointer = build_current_release(
        public_root=args.public_root,
        base_source_dir=args.base_source_dir,
        insights_source_dir=args.insights_source_dir,
        reports_source_dir=args.reports_source_dir,
        personas_source_dir=args.personas_source_dir,
        release_id=args.release_id,
        generated_at_utc=args.generated_at_utc,
    )
    status = write_immutable_pointer(args.output, pointer)
    print(
        json.dumps(
            {
                "schema_version": "reddit_voc_current_release_receipt_v1",
                "status": status,
                "release_id": pointer["release_id"],
                "pointer_sha256": _sha256(args.output),
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
