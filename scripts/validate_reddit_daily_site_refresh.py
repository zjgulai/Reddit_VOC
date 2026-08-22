#!/usr/bin/env python3
"""Validate one local Reddit VOC daily site data release and write a readiness receipt.

This gate is deliberately side-effect free apart from its immutable receipt.
It does not collect, merge, deploy, switch a production pointer, edit cron, or
send DingTalk messages.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "reddit_voc_daily_site_refresh_validation_v1"
EXPECTED_DATASETS = {
    "base",
    "brand_health",
    "casebook",
    "insights",
    "personas",
    "quarter_insights",
    "reports",
}


class DailySiteRefreshValidationError(ValueError):
    """The candidate daily site refresh is not safe to publish."""


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise DailySiteRefreshValidationError(f"{label}_unsafe_or_missing")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DailySiteRefreshValidationError(f"{label}_invalid_json") from exc
    if not isinstance(value, dict):
        raise DailySiteRefreshValidationError(f"{label}_not_object")
    return value


def _utc(value: object, *, label: str) -> datetime:
    if not isinstance(value, str):
        raise DailySiteRefreshValidationError(f"{label}_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DailySiteRefreshValidationError(f"{label}_invalid") from exc
    if parsed.tzinfo is None:
        raise DailySiteRefreshValidationError(f"{label}_not_utc")
    return parsed.astimezone(timezone.utc)


def _inside(root: Path, relative: object, *, label: str) -> Path:
    if not isinstance(relative, str) or not relative or relative.startswith("/"):
        raise DailySiteRefreshValidationError(f"{label}_path_invalid")
    path = root / relative
    if path.is_symlink():
        raise DailySiteRefreshValidationError(f"{label}_unsafe")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise DailySiteRefreshValidationError(f"{label}_unsafe") from exc
    if not resolved.is_file():
        raise DailySiteRefreshValidationError(f"{label}_unsafe")
    return resolved


def _center_id(manifest: Mapping[str, Any], key: str) -> str | None:
    if key in {"base", "insights", "reports", "brand_health"}:
        value = manifest.get("source_snapshot_id")
    elif key == "quarter_insights":
        source = manifest.get("source")
        value = source.get("source_snapshot_id") if isinstance(source, dict) else None
    elif key == "personas":
        value = manifest.get("governed_signal_source_snapshot_id")
    else:
        return None
    return value if isinstance(value, str) else None


def validate_daily_site_refresh(
    *,
    public_root: Path,
    pointer_path: Path,
    e2e_summary_path: Path,
    screenshot_root: Path,
) -> dict[str, Any]:
    root = public_root.resolve(strict=True)
    if public_root.is_symlink() or not root.is_dir():
        raise DailySiteRefreshValidationError("public_root_unsafe")
    pointer = _load(pointer_path, label="current_release")
    if pointer.get("schema_version") != "reddit_voc_current_release_v2":
        raise DailySiteRefreshValidationError("current_release_schema_invalid")
    datasets = pointer.get("datasets")
    if not isinstance(datasets, dict) or set(datasets) != EXPECTED_DATASETS:
        raise DailySiteRefreshValidationError("dataset_inventory_invalid")

    freshness = pointer.get("freshness")
    if not isinstance(freshness, dict):
        raise DailySiteRefreshValidationError("freshness_missing")
    if freshness.get("timezone") != "Asia/Shanghai":
        raise DailySiteRefreshValidationError("freshness_timezone_invalid")
    status = freshness.get("status")
    if status not in {"full", "partial", "empty_success", "no_change"}:
        raise DailySiteRefreshValidationError("freshness_status_invalid")
    start = _utc(freshness.get("window_start_utc"), label="window_start_utc")
    end = _utc(freshness.get("window_end_utc"), label="window_end_utc")
    as_of = _utc(freshness.get("data_as_of_utc"), label="data_as_of_utc")
    if end - start != timedelta(hours=24) or end != as_of:
        raise DailySiteRefreshValidationError("freshness_window_invalid")
    if (start.hour, start.minute, end.hour, end.minute) != (23, 0, 23, 0):
        raise DailySiteRefreshValidationError("freshness_not_0700_asia_shanghai")
    coverage = freshness.get("coverage")
    if not isinstance(coverage, dict):
        raise DailySiteRefreshValidationError("coverage_missing")
    if status == "partial" and int(coverage.get("partial_posts", 0)) <= 0:
        raise DailySiteRefreshValidationError("partial_without_partial_posts")

    center_snapshot_id = freshness.get("center_snapshot_id")
    if not isinstance(center_snapshot_id, str) or not center_snapshot_id:
        raise DailySiteRefreshValidationError("center_snapshot_id_invalid")
    dataset_rows: list[dict[str, Any]] = []
    for key in sorted(datasets):
        binding = datasets[key]
        if not isinstance(binding, dict):
            raise DailySiteRefreshValidationError(f"{key}_binding_invalid")
        manifest = _inside(root, binding.get("manifest_path"), label=f"{key}_manifest")
        observed_sha = _sha256(manifest)
        if observed_sha != binding.get("public_manifest_sha256"):
            raise DailySiteRefreshValidationError(f"{key}_manifest_sha256_mismatch")
        manifest_value = _load(manifest, label=f"{key}_manifest")
        observed_center = _center_id(manifest_value, key)
        if key != "casebook" and observed_center != center_snapshot_id:
            raise DailySiteRefreshValidationError(f"{key}_center_snapshot_mismatch")
        dataset_rows.append(
            {
                "key": key,
                "dataset_version": binding.get("dataset_version"),
                "manifest_path": binding.get("manifest_path"),
                "manifest_sha256": observed_sha,
                "center_snapshot_id": observed_center,
            }
        )

    pointer_sha = _sha256(pointer_path)
    e2e = _load(e2e_summary_path, label="e2e_summary")
    if (
        e2e.get("schema_version") != "reddit_voc_daily_release_e2e_summary_v1"
        or e2e.get("status") != "passed"
        or e2e.get("release_id") != pointer.get("release_id")
        or e2e.get("release_pointer_sha256") != pointer_sha
        or e2e.get("route_count") != 18
        or e2e.get("browser_error_count") != 0
        or e2e.get("failed_request_count") != 0
        or e2e.get("external_request_count") != 0
    ):
        raise DailySiteRefreshValidationError("e2e_summary_invalid")

    screenshot_rows = []
    for grain in ("daily", "weekly", "monthly"):
        path = screenshot_root / f"{grain}.png"
        if path.is_symlink() or not path.is_file():
            raise DailySiteRefreshValidationError(f"{grain}_screenshot_missing")
        payload = path.read_bytes()
        if len(payload) < 10_000 or not payload.startswith(b"\x89PNG\r\n\x1a\n"):
            raise DailySiteRefreshValidationError(f"{grain}_screenshot_invalid")
        screenshot_rows.append(
            {
                "grain": grain,
                "path": path.as_posix(),
                "bytes": len(payload),
                "sha256": sha256(payload).hexdigest(),
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "passed_candidate_only",
        "promotable": True,
        "release_id": pointer["release_id"],
        "release_pointer_sha256": pointer_sha,
        "center_snapshot_id": center_snapshot_id,
        "freshness": freshness,
        "datasets": dataset_rows,
        "e2e_summary_sha256": _sha256(e2e_summary_path),
        "screenshots": screenshot_rows,
        "boundaries": {
            "collector_modified": False,
            "cron_modified": False,
            "deploy": False,
            "live_send": False,
            "production_unchanged": True,
            "remote_write": False,
        },
    }


def write_immutable(path: Path, value: Mapping[str, Any]) -> str:
    payload = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise DailySiteRefreshValidationError("receipt_immutable_collision")
        return "no_change"
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return "created"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-root", type=Path, required=True)
    parser.add_argument("--pointer", type=Path, required=True)
    parser.add_argument("--e2e-summary", type=Path, required=True)
    parser.add_argument("--screenshot-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        value = validate_daily_site_refresh(
            public_root=args.public_root,
            pointer_path=args.pointer,
            e2e_summary_path=args.e2e_summary,
            screenshot_root=args.screenshot_root,
        )
        outcome = write_immutable(args.output, value)
    except (DailySiteRefreshValidationError, OSError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}))
        return 1
    print(
        json.dumps(
            {
                "status": value["status"],
                "release_id": value["release_id"],
                "receipt": args.output.as_posix(),
                "receipt_sha256": _sha256(args.output),
                "write": outcome,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
