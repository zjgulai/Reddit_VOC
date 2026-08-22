from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import Any, Mapping

from reddit_voc.report_contracts import canonical_json_bytes
from reddit_voc.source_batch import PRIORITY_REASON_CODES, REQUIRED_MEMBER_ROLES, load_source_batch
from reddit_voc.storage import VocStore


class DailySourceBatchError(ValueError):
    pass


@dataclass(frozen=True)
class DailySourceBatchResult:
    batch_root: Path
    manifest_path: Path
    manifest_sha256: str
    write_status: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _private_directory(path: Path, *, label: str) -> None:
    if path.exists() or path.is_symlink():
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise DailySourceBatchError(f"{label} is unsafe")
        path.chmod(0o700)
        return
    path.mkdir(parents=True, mode=0o700)
    path.chmod(0o700)


def _json_object(path: Path, *, label: str) -> tuple[dict[str, Any], str]:
    try:
        payload = path.read_bytes()
        value = json.loads(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DailySourceBatchError(f"{label} is invalid") from exc
    if not isinstance(value, dict) or payload != canonical_json_bytes(value) + b"\n":
        raise DailySourceBatchError(f"{label} must be canonical JSON")
    return value, hashlib.sha256(payload).hexdigest()


def _profile_version(value: Mapping[str, Any], schema: str, *, label: str) -> str:
    if value.get("schema_version") != schema:
        raise DailySourceBatchError(f"{label} schema_version unsupported")
    version = value.get("version")
    if not isinstance(version, str) or not version:
        raise DailySourceBatchError(f"{label} version is invalid")
    return version


def _utc(value: object, *, label: str) -> datetime:
    if not isinstance(value, str):
        raise DailySourceBatchError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DailySourceBatchError(f"{label} is invalid") from exc
    if parsed.tzinfo is None:
        raise DailySourceBatchError(f"{label} is not timezone-aware")
    return parsed.astimezone(timezone.utc)


def _utc_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _post_fullname(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise DailySourceBatchError("post_id is missing")
    return text if text.startswith("t3_") else "t3_" + text


def _comment_fullname(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise DailySourceBatchError("comment_id is missing")
    return text if text.startswith("t1_") else "t1_" + text


def _parent_fullname(value: object, post_id: str) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith(("t1_", "t3_")):
        return text
    return "t3_" + text if text == post_id.removeprefix("t3_") else "t1_" + text


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("wb") as handle:
        for row in rows:
            handle.write(canonical_json_bytes(row) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(0o600)


def _copy_raw(source: Path, target: Path, *, expected_sha256: str) -> None:
    if not source.exists() or source.is_symlink() or not source.is_file():
        raise DailySourceBatchError("daily raw artifact unavailable")
    if _sha256(source) != expected_sha256:
        raise DailySourceBatchError("daily raw artifact hash mismatch")
    target.write_bytes(source.read_bytes())
    target.chmod(0o600)


def _member(path: Path, role: str, root: Path) -> dict[str, object]:
    rows = len(path.read_bytes().splitlines())
    return {
        "bytes": path.stat().st_size,
        "relative_path": path.relative_to(root).as_posix(),
        "role": role,
        "rows": rows,
        "sha256": _sha256(path),
    }


def _build_in_staging(
    staging: Path,
    *,
    store: VocStore,
    run_id: str,
    raw_artifact_root: Path,
    query_profile_path: Path,
    coverage_profile_path: Path,
    collector_summary: Mapping[str, object],
) -> tuple[Path, str]:
    run = store.get_run(run_id)
    if run is None:
        raise DailySourceBatchError("daily run not found")
    status = str(run.get("status"))
    if status not in {"success", "partial", "empty", "failed"}:
        raise DailySourceBatchError("daily run status is not terminal")
    query_profile, query_sha = _json_object(query_profile_path, label="query profile")
    coverage_profile, coverage_sha = _json_object(coverage_profile_path, label="coverage profile")
    query_version = _profile_version(
        query_profile, "reddit_voc_query_profile_v1", label="query profile"
    )
    coverage_version = _profile_version(
        coverage_profile, "reddit_voc_coverage_profile_v1", label="coverage profile"
    )
    overlap = coverage_profile.get("new_post_overlap_hours")
    policy = coverage_profile.get("active_thread_policy")
    if isinstance(overlap, bool) or not isinstance(overlap, int) or overlap < 0:
        raise DailySourceBatchError("coverage profile overlap is invalid")
    if not isinstance(policy, dict) or tuple(policy.get("priority_reason_codes", ())) != PRIORITY_REASON_CODES:
        raise DailySourceBatchError("coverage profile active thread policy is invalid")

    raw_rows = store.fetch_raw_captures_for_run(run_id)
    posts = store.fetch_threads_for_run(run_id)
    comments = store.fetch_comments_for_run(run_id)
    raw_ids = {str(row["raw_capture_id"]) for row in raw_rows}
    raw_root = staging / "raw"
    raw_root.mkdir(mode=0o700)
    raw_index: list[dict[str, Any]] = []
    for row in raw_rows:
        raw_id = str(row["raw_capture_id"])
        payload_hash = str(row["raw_payload_hash"])
        if not payload_hash.startswith("sha256:"):
            raise DailySourceBatchError("daily raw payload hash is invalid")
        digest = payload_hash.split(":", 1)[1]
        extension = {"json": "json", "html": "html", "text": "txt"}.get(str(row["payload_format"]))
        if extension is None:
            raise DailySourceBatchError("daily raw payload format unsupported")
        source = raw_artifact_root / run_id / f"{raw_id}.{extension}"
        target = raw_root / f"{raw_id}.{extension}"
        _copy_raw(source, target, expected_sha256=digest)
        raw_index.append(
            {
                "bytes": target.stat().st_size,
                "raw_object_id": raw_id,
                "relative_path": f"raw/{target.name}",
                "sha256": digest,
            }
        )

    post_rows: list[dict[str, Any]] = []
    post_occurrences: list[dict[str, Any]] = []
    checkpoints: list[dict[str, Any]] = []
    for source in posts:
        row = dict(source)
        post_id = _post_fullname(row["post_id"])
        raw_id = str(row["raw_capture_id"])
        if raw_id not in raw_ids:
            raise DailySourceBatchError("daily post raw capture is unavailable")
        row["post_id"] = post_id
        row["source_run_id"] = row.pop("run_id")
        post_rows.append(row)
        post_occurrences.append(
            {
                "occurrence_id": hashlib.sha256(
                    canonical_json_bytes([run_id, "post", post_id, raw_id])
                ).hexdigest(),
                "post_id": post_id,
                "raw_object_id": raw_id,
                "source_run_id": run_id,
            }
        )
        more_count = int(row.get("more_node_count") or 0)
        checkpoints.append(
            {
                "lane_key": post_id,
                "lane_type": "comments",
                "status": "complete" if row.get("coverage_grade") == "full" else "partial",
                "unresolved_continuations": more_count,
            }
        )

    comment_rows: list[dict[str, Any]] = []
    comment_occurrences: list[dict[str, Any]] = []
    for source in comments:
        row = dict(source)
        comment_id = _comment_fullname(row["comment_id"])
        post_id = _post_fullname(row["post_id"])
        raw_id = str(row["raw_capture_id"])
        if raw_id not in raw_ids:
            raise DailySourceBatchError("daily comment raw capture is unavailable")
        row["comment_id"] = comment_id
        row["post_id"] = post_id
        row["parent_id"] = _parent_fullname(row.get("parent_id"), post_id)
        row["source_run_id"] = row.pop("run_id")
        row.pop("post_source_url", None)
        comment_rows.append(row)
        comment_occurrences.append(
            {
                "comment_id": comment_id,
                "occurrence_id": hashlib.sha256(
                    canonical_json_bytes([run_id, "comment", comment_id, raw_id])
                ).hexdigest(),
                "raw_object_id": raw_id,
                "source_run_id": run_id,
            }
        )

    referenced_raw_ids = {
        str(row["raw_object_id"]) for row in (*post_occurrences, *comment_occurrences)
    }
    for row in raw_index:
        row["terminal_disposition"] = (
            "entity_observed" if row["raw_object_id"] in referenced_raw_ids else "no_entity"
        )

    issues_value = collector_summary.get("issues", [])
    if not isinstance(issues_value, list) or any(not isinstance(item, dict) for item in issues_value):
        raise DailySourceBatchError("collector summary issues are invalid")
    documents = {
        "checkpoints": sorted(checkpoints, key=lambda row: str(row["lane_key"])),
        "comment_occurrences": sorted(comment_occurrences, key=lambda row: str(row["occurrence_id"])),
        "comments": sorted(comment_rows, key=lambda row: str(row["comment_id"])),
        "issues": [dict(item) for item in issues_value],
        "post_occurrences": sorted(post_occurrences, key=lambda row: str(row["occurrence_id"])),
        "posts": sorted(post_rows, key=lambda row: str(row["post_id"])),
        "raw_index": sorted(raw_index, key=lambda row: str(row["raw_object_id"])),
    }
    paths: dict[str, Path] = {}
    for role in REQUIRED_MEMBER_ROLES:
        path = staging / (role.replace("_", "-") + ".jsonl")
        _write_jsonl(path, documents[role])
        paths[role] = path

    metric_start = _utc(run["window_start_utc"], label="window_start_utc")
    metric_end = _utc(run["window_end_utc"], label="window_end_utc")
    counts = {
        "comment_occurrences": len(comment_occurrences),
        "comments": len(comment_rows),
        "issues": len(documents["issues"]),
        "post_occurrences": len(post_occurrences),
        "posts": len(post_rows),
        "raw_objects": len(raw_index),
        "unresolved_continuations": sum(
            int(row["unresolved_continuations"]) for row in checkpoints
        ),
    }
    manifest = {
        "active_thread_policy": policy,
        "batch_id": run_id,
        "boundaries": {
            "database_write": False,
            "deploy": False,
            "live_send": False,
            "production_unchanged": True,
            "provider_call": bool(run.get("provider_call")),
            "remote_write": False,
        },
        "counts": counts,
        "members": [_member(paths[role], role, staging) for role in REQUIRED_MEMBER_ROLES],
        "producer_type": "daily_incremental",
        "profiles": {
            "coverage_profile_sha256": coverage_sha,
            "coverage_profile_version": coverage_version,
            "query_profile_sha256": query_sha,
            "query_profile_version": query_version,
        },
        "schema_version": "reddit_voc_source_batch_v2",
        "status": status,
        "window": {
            "metric_end_utc": _utc_z(metric_end),
            "metric_start_utc": _utc_z(metric_start),
            "new_post_discovery_end_utc": _utc_z(metric_end),
            "new_post_discovery_start_utc": _utc_z(metric_start - timedelta(hours=overlap)),
            "timezone": "Asia/Shanghai",
        },
    }
    manifest_path = staging / "source-batch-manifest.json"
    manifest_path.write_bytes(canonical_json_bytes(manifest) + b"\n")
    manifest_path.chmod(0o600)
    digest = _sha256(manifest_path)
    load_source_batch(manifest_path, staging, require_consumable=status != "failed")
    return manifest_path, digest


def build_daily_source_batch(
    store: VocStore,
    *,
    run_id: str,
    raw_artifact_root: Path | str,
    output_root: Path | str,
    query_profile_path: Path | str,
    coverage_profile_path: Path | str,
    collector_summary: Mapping[str, object],
) -> DailySourceBatchResult:
    root = Path(output_root)
    _private_directory(root, label="daily source batch output root")
    target = root / run_id
    staging = Path(tempfile.mkdtemp(prefix=f".{run_id}.staging-", dir=root))
    staging.chmod(0o700)
    try:
        _, digest = _build_in_staging(
            staging,
            store=store,
            run_id=run_id,
            raw_artifact_root=Path(raw_artifact_root),
            query_profile_path=Path(query_profile_path),
            coverage_profile_path=Path(coverage_profile_path),
            collector_summary=collector_summary,
        )
        if target.exists() or target.is_symlink():
            if target.is_symlink() or not target.is_dir():
                raise DailySourceBatchError("daily source batch immutable collision")
            existing = load_source_batch(target / "source-batch-manifest.json", target)
            if existing.manifest_sha256 != digest:
                raise DailySourceBatchError("daily source batch immutable collision")
            return DailySourceBatchResult(
                batch_root=target,
                manifest_path=target / "source-batch-manifest.json",
                manifest_sha256=digest,
                write_status="no_change",
            )
        os.rename(staging, target)
        return DailySourceBatchResult(
            batch_root=target,
            manifest_path=target / "source-batch-manifest.json",
            manifest_sha256=digest,
            write_status="created",
        )
    finally:
        if staging.exists():
            shutil.rmtree(staging)
