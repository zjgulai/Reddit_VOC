from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import Any, Mapping

from reddit_voc.daily_source_batch import (
    _json_object,
    _member,
    _private_directory,
    _profile_version,
    _sha256,
    _write_jsonl,
)
from reddit_voc.report_contracts import canonical_json_bytes
from reddit_voc.source_batch import REQUIRED_MEMBER_ROLES, load_source_batch


class ServerSnapshotSourceBatchError(ValueError):
    pass


@dataclass(frozen=True)
class ServerSnapshotSourceBatchResult:
    batch_root: Path
    manifest_path: Path
    manifest_sha256: str
    source_database_sha256: str
    write_status: str


def _utc(value: object, *, label: str) -> datetime:
    if not isinstance(value, str):
        raise ServerSnapshotSourceBatchError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ServerSnapshotSourceBatchError(f"{label} is invalid") from exc
    if parsed.tzinfo is None:
        raise ServerSnapshotSourceBatchError(f"{label} is not timezone-aware")
    return parsed.astimezone(timezone.utc)


def _utc_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _post_fullname(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise ServerSnapshotSourceBatchError("post_id is missing")
    return text if text.startswith("t3_") else "t3_" + text


def _comment_fullname(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise ServerSnapshotSourceBatchError("comment_id is missing")
    return text if text.startswith("t1_") else "t1_" + text


def _parent_fullname(value: object, post_id: str, depth: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        if type(depth) is int and depth == 0:
            return post_id
        return None
    if text.startswith(("t1_", "t3_")):
        return text
    if text == post_id.removeprefix("t3_"):
        return "t3_" + text
    return "t1_" + text


def _read_rows(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    try:
        return [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]
    except sqlite3.DatabaseError as exc:
        raise ServerSnapshotSourceBatchError(f"source database table unavailable:{table}") from exc


def _source_database(path: Path) -> tuple[sqlite3.Connection, str]:
    if not path.exists() or path.is_symlink() or not path.is_file():
        raise ServerSnapshotSourceBatchError("source database is unsafe")
    before = _sha256(path)
    try:
        connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        quick_check = connection.execute("PRAGMA quick_check").fetchone()
    except sqlite3.DatabaseError as exc:
        raise ServerSnapshotSourceBatchError("source database is invalid") from exc
    if quick_check is None or quick_check[0] != "ok":
        connection.close()
        raise ServerSnapshotSourceBatchError("source database quick_check failed")
    if _sha256(path) != before:
        connection.close()
        raise ServerSnapshotSourceBatchError("source database changed during read-only probe")
    return connection, before


def _occurrence_id(batch_id: str, entity_type: str, entity_id: str, raw_id: str) -> str:
    return hashlib.sha256(
        canonical_json_bytes([batch_id, entity_type, entity_id, raw_id])
    ).hexdigest()


def _build_staging(
    staging: Path,
    *,
    source_database_path: Path,
    batch_id: str,
    window_start_utc: datetime,
    window_end_utc: datetime,
    query_profile_path: Path,
    coverage_profile_path: Path,
) -> tuple[str, str]:
    if window_start_utc >= window_end_utc:
        raise ServerSnapshotSourceBatchError("source snapshot window is invalid")
    query_profile, query_sha = _json_object(query_profile_path, label="query profile")
    coverage_profile, coverage_sha = _json_object(coverage_profile_path, label="coverage profile")
    query_version = _profile_version(
        query_profile, "reddit_voc_query_profile_v1", label="query profile"
    )
    coverage_version = _profile_version(
        coverage_profile, "reddit_voc_coverage_profile_v1", label="coverage profile"
    )
    connection, source_sha = _source_database(source_database_path)
    try:
        source_posts = _read_rows(connection, "reddit_threads")
        source_comments = _read_rows(connection, "reddit_comments")
        source_runs = _read_rows(connection, "runs")
    finally:
        connection.close()
    if _sha256(source_database_path) != source_sha:
        raise ServerSnapshotSourceBatchError("source database changed during snapshot read")
    if not source_runs:
        raise ServerSnapshotSourceBatchError("source database has no collection runs")
    for run in source_runs:
        run_start = _utc(run.get("window_start_utc"), label="source run window_start_utc")
        run_end = _utc(run.get("window_end_utc"), label="source run window_end_utc")
        if run_start >= run_end or run_start < window_start_utc or run_end > window_end_utc:
            raise ServerSnapshotSourceBatchError("source run falls outside snapshot window")

    post_rows: list[dict[str, Any]] = []
    post_ids: set[str] = set()
    for source in source_posts:
        row = dict(source)
        post_id = _post_fullname(row.get("post_id"))
        if post_id in post_ids:
            raise ServerSnapshotSourceBatchError(f"duplicate post identity:{post_id}")
        post_ids.add(post_id)
        row["post_id"] = post_id
        row["source_run_id"] = row.pop("run_id", None)
        row["source_raw_capture_id"] = row.pop("raw_capture_id", None)
        post_rows.append(row)

    comment_rows: list[dict[str, Any]] = []
    comment_ids: set[str] = set()
    missing_post_ids: set[str] = set()
    for source in source_comments:
        row = dict(source)
        comment_id = _comment_fullname(row.get("comment_id"))
        post_id = _post_fullname(row.get("post_id"))
        if comment_id in comment_ids:
            raise ServerSnapshotSourceBatchError(f"duplicate comment identity:{comment_id}")
        comment_ids.add(comment_id)
        row["comment_id"] = comment_id
        row["post_id"] = post_id
        row["parent_id"] = _parent_fullname(row.get("parent_id"), post_id, row.get("depth"))
        row["relationship_status"] = "linked" if post_id in post_ids else "unresolved_parent"
        row["source_run_id"] = row.pop("run_id", None)
        row["source_raw_capture_id"] = row.pop("raw_capture_id", None)
        row["deleted_or_removed"] = bool(row.get("deleted_or_removed"))
        if row.get("is_submitter") is not None:
            row["is_submitter"] = bool(row["is_submitter"])
        if post_id not in post_ids:
            missing_post_ids.add(post_id)
        comment_rows.append(row)

    raw_root = staging / "raw"
    raw_root.mkdir(mode=0o700)
    raw_id = "raw_server_snapshot_" + source_sha[:20]
    raw_name = f"reddit-voc-daily-{source_sha[:16]}.sqlite3"
    raw_path = raw_root / raw_name
    shutil.copyfile(source_database_path, raw_path)
    raw_path.chmod(0o600)
    if _sha256(raw_path) != source_sha:
        raise ServerSnapshotSourceBatchError("source database copy hash mismatch")

    raw_index = [
        {
            "bytes": raw_path.stat().st_size,
            "raw_object_id": raw_id,
            "relative_path": f"raw/{raw_name}",
            "sha256": source_sha,
            "terminal_disposition": "entity_observed" if post_rows or comment_rows else "empty_page",
        }
    ]
    post_occurrences = [
        {
            "occurrence_id": _occurrence_id(batch_id, "post", row["post_id"], raw_id),
            "post_id": row["post_id"],
            "raw_object_id": raw_id,
            "source_run_id": row.get("source_run_id"),
        }
        for row in post_rows
    ]
    comment_occurrences = [
        {
            "comment_id": row["comment_id"],
            "occurrence_id": _occurrence_id(batch_id, "comment", row["comment_id"], raw_id),
            "raw_object_id": raw_id,
            "source_run_id": row.get("source_run_id"),
        }
        for row in comment_rows
    ]
    checkpoints = [
        {
            "lane_key": str(row.get("run_id") or "unknown"),
            "lane_type": "server_normalized_snapshot",
            "status": str(row.get("status") or "unknown"),
            "window_end_utc": row.get("window_end_utc"),
            "window_start_utc": row.get("window_start_utc"),
        }
        for row in source_runs
    ]
    issues = [
        {
            "fatal": False,
            "issue_id": "source_run_" + hashlib.sha256(
                str(row.get("run_id") or "unknown").encode("utf-8")
            ).hexdigest()[:16],
            "issue_kind": "source_run_not_success",
            "run_id": row.get("run_id"),
            "source_status": row.get("status"),
        }
        for row in source_runs
        if row.get("status") not in {"empty", "success"}
    ]
    issues.extend(
        {
            "fatal": False,
            "issue_id": "missing_post_" + post_id.removeprefix("t3_"),
            "issue_kind": "comment_parent_post_absent_from_snapshot",
            "post_id": post_id,
        }
        for post_id in sorted(missing_post_ids)
    )
    unresolved_continuations = sum(int(row.get("more_node_count") or 0) for row in post_rows)
    documents: Mapping[str, list[dict[str, Any]]] = {
        "checkpoints": sorted(checkpoints, key=lambda row: str(row["lane_key"])),
        "comment_occurrences": sorted(
            comment_occurrences, key=lambda row: str(row["occurrence_id"])
        ),
        "comments": sorted(comment_rows, key=lambda row: str(row["comment_id"])),
        "issues": sorted(issues, key=lambda row: str(row["issue_id"])),
        "post_occurrences": sorted(
            post_occurrences, key=lambda row: str(row["occurrence_id"])
        ),
        "posts": sorted(post_rows, key=lambda row: str(row["post_id"])),
        "raw_index": raw_index,
    }
    paths: dict[str, Path] = {}
    for role in REQUIRED_MEMBER_ROLES:
        path = staging / (role.replace("_", "-") + ".jsonl")
        _write_jsonl(path, documents[role])
        paths[role] = path

    status = "success"
    if issues or unresolved_continuations:
        status = "partial" if post_rows or comment_rows else "failed"
    elif not post_rows and not comment_rows:
        status = "empty"
    manifest = {
        "active_thread_policy": None,
        "batch_id": batch_id,
        "boundaries": {
            "database_write": False,
            "deploy": False,
            "live_send": False,
            "production_unchanged": True,
            "provider_call": any(bool(row.get("provider_call")) for row in source_runs),
            "remote_write": False,
        },
        "counts": {
            "comment_occurrences": len(comment_occurrences),
            "comments": len(comment_rows),
            "issues": len(issues),
            "post_occurrences": len(post_occurrences),
            "posts": len(post_rows),
            "raw_objects": len(raw_index),
            "unresolved_continuations": unresolved_continuations,
        },
        "members": [_member(paths[role], role, staging) for role in REQUIRED_MEMBER_ROLES],
        "producer_type": "historical_backfill",
        "profiles": {
            "coverage_profile_sha256": coverage_sha,
            "coverage_profile_version": coverage_version,
            "query_profile_sha256": query_sha,
            "query_profile_version": query_version,
        },
        "schema_version": "reddit_voc_source_batch_v2",
        "status": status,
        "window": {
            "metric_end_utc": _utc_z(window_end_utc),
            "metric_start_utc": _utc_z(window_start_utc),
            "new_post_discovery_end_utc": _utc_z(window_end_utc),
            "new_post_discovery_start_utc": _utc_z(window_start_utc),
            "timezone": "Asia/Shanghai",
        },
    }
    manifest_path = staging / "source-batch-manifest.json"
    manifest_path.write_bytes(canonical_json_bytes(manifest) + b"\n")
    manifest_path.chmod(0o600)
    digest = _sha256(manifest_path)
    load_source_batch(manifest_path, staging, require_consumable=status != "failed")
    return digest, source_sha


def build_server_snapshot_source_batch(
    *,
    source_database_path: Path | str,
    output_root: Path | str,
    batch_id: str,
    window_start_utc: datetime,
    window_end_utc: datetime,
    query_profile_path: Path | str,
    coverage_profile_path: Path | str,
) -> ServerSnapshotSourceBatchResult:
    root = Path(output_root)
    _private_directory(root, label="server snapshot source batch output root")
    target = root / batch_id
    staging = Path(tempfile.mkdtemp(prefix=f".{batch_id}.staging-", dir=root))
    staging.chmod(0o700)
    try:
        digest, source_sha = _build_staging(
            staging,
            source_database_path=Path(source_database_path),
            batch_id=batch_id,
            window_start_utc=window_start_utc,
            window_end_utc=window_end_utc,
            query_profile_path=Path(query_profile_path),
            coverage_profile_path=Path(coverage_profile_path),
        )
        if target.exists() or target.is_symlink():
            if target.is_symlink() or not target.is_dir():
                raise ServerSnapshotSourceBatchError("server snapshot source batch immutable collision")
            existing = load_source_batch(target / "source-batch-manifest.json", target)
            if existing.manifest_sha256 != digest:
                raise ServerSnapshotSourceBatchError("server snapshot source batch immutable collision")
            return ServerSnapshotSourceBatchResult(
                batch_root=target,
                manifest_path=target / "source-batch-manifest.json",
                manifest_sha256=digest,
                source_database_sha256=source_sha,
                write_status="no_change",
            )
        os.rename(staging, target)
        return ServerSnapshotSourceBatchResult(
            batch_root=target,
            manifest_path=target / "source-batch-manifest.json",
            manifest_sha256=digest,
            source_database_sha256=source_sha,
            write_status="created",
        )
    finally:
        if staging.exists():
            shutil.rmtree(staging)
