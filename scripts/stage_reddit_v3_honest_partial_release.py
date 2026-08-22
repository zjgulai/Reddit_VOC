#!/usr/bin/env python3
"""Stage one isolated seven-dataset V3 release candidate.

The destination must not exist.  This command copies only reviewed public
artifacts, builds V1 then V2 pointers in the isolated tree, and records the
08:00 Beijing freshness contract.  It never touches the live workbench pointer.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_reddit_data_release import (  # noqa: E402
    build_data_release,
    write_immutable_pointer as write_v2_pointer,
)
from scripts.build_reddit_v3_current_release import (  # noqa: E402
    build_v3_current_release,
    write_immutable_pointer as write_v1_pointer,
)


def _sha(path: Path) -> str:
    digest = sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _identity(root: Path, kind: str) -> str:
    manifest_name = "manifest-public.json" if kind == "base" else "manifest.json"
    manifest = _load(root / manifest_name)
    field = "snapshot_id" if kind == "personas" else "dataset_version"
    value = manifest.get(field) or manifest.get("projection_id")
    if not isinstance(value, str) or not value:
        raise ValueError(f"{kind} dataset identity missing")
    return value


def _copy_tree(source: Path, destination: Path) -> None:
    source = Path(source)
    if source.is_symlink() or not source.is_dir():
        raise ValueError(f"unsafe source directory: {source}")
    if destination.exists() or destination.is_symlink():
        raise ValueError(f"stage destination collision: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, symlinks=False)


def _write_json(path: Path, value: object) -> None:
    if path.exists() or path.is_symlink():
        raise ValueError(f"stage file collision: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def stage(args: argparse.Namespace) -> dict[str, Any]:
    stage_root = Path(args.stage_root)
    if stage_root.exists() or stage_root.is_symlink():
        raise ValueError("stage root must not exist")
    public_root = stage_root / "public"
    public_root.mkdir(parents=True)

    roots = {
        "base": Path(args.base_root),
        "insights": Path(args.insights_root),
        "reports": Path(args.reports_root),
        "personas": Path(args.personas_root),
        "brand_health": Path(args.brand_health_root),
        "quarter_insights": Path(args.quarter_insights_root),
        "casebook": Path(args.casebook_root),
    }
    versions = {
        key: _identity(roots[key], key)
        for key in ("base", "insights", "reports", "personas")
    }
    auxiliary_versions = {
        key: _identity(roots[key], key)
        for key in ("brand_health", "quarter_insights")
    }
    auxiliary_versions["casebook"] = str(
        _load(roots["casebook"] / "manifest.json")["projection_id"]
    )
    for key, version in {**versions, **auxiliary_versions}.items():
        source = roots[key]
        destination = public_root / "data/reddit-voc" / version
        if key in {"insights", "reports"}:
            destination = destination / "public"
        _copy_tree(source, destination)

    insights_destination = (
        public_root / "data/reddit-voc" / versions["insights"] / "public"
    )
    shutil.copy2(
        args.insights_public_validation_receipt,
        insights_destination / "public-validation-receipt.json",
    )
    reports_destination = (
        public_root / "data/reddit-voc" / versions["reports"] / "public"
    )
    shutil.copy2(
        args.reports_public_validation_receipt,
        reports_destination / "public-validation-receipt.json",
    )

    cases_source = Path(args.cases_root)
    for name in ("manifest.v1.json", "case-index.v1.json"):
        target = public_root / "data/cases" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cases_source / name, target)
    static_source = Path(args.static_root)
    for name in ("favicon.svg", "icons.svg", "robots.txt"):
        shutil.copy2(static_source / name, public_root / name)

    core_pointer = build_v3_current_release(
        public_root=public_root,
        base_validation_receipt=args.base_validation_receipt,
        insights_validation_receipt=args.insights_public_validation_receipt,
        reports_validation_receipt=args.reports_public_validation_receipt,
        personas_validation_receipt=args.personas_validation_receipt,
        release_id=f"{args.release_id}_core",
        generated_at_utc=args.generated_at_utc,
        versions=versions,
    )
    core_pointer_path = stage_root / "core-pointer-v1.json"
    write_v1_pointer(core_pointer_path, core_pointer)

    freshness = {
        "boundaries": {
            "database_write": False,
            "deploy": False,
            "live_send": False,
            "production_unchanged": True,
            "provider_call": False,
            "remote_write": False,
        },
        "center_snapshot_id": "reddit_voc_center_20260809_v3_canonical_v2",
        "collector_run_id": "daily_collect_20260809_0700",
        "coverage": {
            "full_posts": 11,
            "partial_posts": 5,
            "unresolved_continuations": 5,
        },
        "data_as_of_utc": "2026-08-08T23:00:00Z",
        "net_new": {
            "comments": 74,
            "posts": 16,
            "repaired_parent_links": 0,
            "updated_historical_posts": 0,
        },
        "schema_version": "reddit_voc_data_freshness_v1",
        "source_batch_id": "server_snapshot_20260809",
        "status": "partial",
        "timezone": "Asia/Shanghai",
        "window_end_utc": "2026-08-08T23:00:00Z",
        "window_start_utc": "2026-08-07T23:00:00Z",
    }
    freshness_path = stage_root / "freshness.json"
    _write_json(freshness_path, freshness)
    auxiliary_manifest_sha256s = {
        key: _sha(roots[key] / "manifest.json") for key in auxiliary_versions
    }
    pointer = build_data_release(
        public_root=public_root,
        core_pointer_path=core_pointer_path,
        auxiliary_versions=auxiliary_versions,
        auxiliary_manifest_sha256s=auxiliary_manifest_sha256s,
        freshness_path=freshness_path,
        release_id=args.release_id,
        generated_at_utc=args.generated_at_utc,
    )
    pointer_path = public_root / "data/reddit-voc/current-release.json"
    write_v2_pointer(pointer_path, pointer)
    return {
        "boundaries": {
            "deploy": False,
            "production_unchanged": True,
            "remote_write": False,
        },
        "datasets": {**versions, **auxiliary_versions},
        "pointer": pointer_path.as_posix(),
        "pointer_sha256": _sha(pointer_path),
        "release_id": pointer["release_id"],
        "schema_version": "reddit_voc_isolated_release_stage_receipt_v1",
        "status": "staged_candidate_only",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    for name in (
        "base-root",
        "insights-root",
        "reports-root",
        "personas-root",
        "brand-health-root",
        "quarter-insights-root",
        "casebook-root",
        "cases-root",
        "static-root",
        "base-validation-receipt",
        "insights-public-validation-receipt",
        "reports-public-validation-receipt",
        "personas-validation-receipt",
        "stage-root",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument(
        "--release-id",
        default="reddit_voc_release_20260809_honest_partial_v2",
    )
    parser.add_argument(
        "--generated-at-utc",
        default="2026-08-09T08:00:00Z",
    )
    args = parser.parse_args()
    result = stage(args)
    _write_json(Path(args.stage_root) / "stage-receipt.json", result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
