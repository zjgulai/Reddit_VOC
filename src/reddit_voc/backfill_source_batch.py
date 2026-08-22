from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile
from typing import Any

from reddit_voc.backfill_archive import PrivateRawArchive
from reddit_voc.backfill_models import RawArtifactMetadata
from reddit_voc.report_contracts import canonical_json_bytes
from reddit_voc.source_batch import REQUIRED_MEMBER_ROLES, load_source_batch


class BackfillSourceBatchError(ValueError):
    pass


@dataclass(frozen=True)
class BackfillSourceBatchResult:
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
            raise BackfillSourceBatchError(f"{label} is unsafe")
        path.chmod(0o700)
        return
    path.mkdir(parents=True, mode=0o700)
    path.chmod(0o700)


def _connect_read_only(database_path: Path) -> sqlite3.Connection:
    if not database_path.exists() or database_path.is_symlink() or not database_path.is_file():
        raise BackfillSourceBatchError("backfill database is unavailable")
    connection = sqlite3.connect(database_path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _rows(connection: sqlite3.Connection, table: str, run_id: str, order_by: str) -> list[dict[str, Any]]:
    allowed = {
        "backfill_checkpoints",
        "backfill_discovery_occurrences",
        "backfill_issues",
        "backfill_raw_artifacts",
        "reddit_comments",
        "reddit_threads",
    }
    if table not in allowed:
        raise BackfillSourceBatchError("unsupported backfill table")
    return [
        dict(row)
        for row in connection.execute(
            f"SELECT * FROM {table} WHERE run_id = ? ORDER BY {order_by}",
            (run_id,),
        ).fetchall()
    ]


def _post_fullname(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise BackfillSourceBatchError("post_id is missing")
    return text if text.startswith("t3_") else "t3_" + text


def _comment_fullname(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise BackfillSourceBatchError("comment_id is missing")
    return text if text.startswith("t1_") else "t1_" + text


def _parent_fullname(value: object, post_id: str) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith(("t1_", "t3_")):
        return text
    return "t3_" + text if text == post_id.removeprefix("t3_") else "t1_" + text


def _utc_z(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise BackfillSourceBatchError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BackfillSourceBatchError(f"{label} is invalid") from exc
    if parsed.tzinfo is None:
        raise BackfillSourceBatchError(f"{label} is not timezone-aware")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("xb") as handle:
        for row in rows:
            handle.write(canonical_json_bytes(row) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(0o600)


def _write_raw(path: Path, payload: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(0o600)


def _member(path: Path, role: str, root: Path) -> dict[str, object]:
    return {
        "bytes": path.stat().st_size,
        "relative_path": path.relative_to(root).as_posix(),
        "role": role,
        "rows": len(path.read_bytes().splitlines()),
        "sha256": _sha256(path),
    }


def _mapped_status(status: object) -> tuple[str, bool]:
    value = str(status)
    if value == "success":
        return "success", False
    if value in {"seed_complete", "partial"}:
        return "partial", value == "seed_complete"
    if value in {"blocked", "failed"}:
        return "failed", False
    raise BackfillSourceBatchError("backfill run is not exportable")


def _build_in_staging(
    staging: Path,
    *,
    database_path: Path,
    archive_root: Path,
    run_id: str,
) -> tuple[Path, str]:
    archive = PrivateRawArchive(archive_root, read_only=True)
    with _connect_read_only(database_path) as connection:
        manifest_rows = connection.execute(
            "SELECT * FROM backfill_manifests WHERE run_id = ?", (run_id,)
        ).fetchall()
        if len(manifest_rows) != 1:
            raise BackfillSourceBatchError("backfill manifest not found")
        source_manifest = dict(manifest_rows[0])
        status, seed_only = _mapped_status(source_manifest["status"])
        artifacts = _rows(connection, "backfill_raw_artifacts", run_id, "artifact_id")
        posts = _rows(connection, "reddit_threads", run_id, "post_id")
        comments = _rows(connection, "reddit_comments", run_id, "comment_id")
        discovery = _rows(
            connection,
            "backfill_discovery_occurrences",
            run_id,
            "lane_type, lane_key, page_number, ordinal",
        )
        checkpoints = _rows(
            connection, "backfill_checkpoints", run_id, "lane_type, lane_key"
        )
        issues = _rows(connection, "backfill_issues", run_id, "issue_id")

    raw_root = staging / "raw"
    raw_root.mkdir(mode=0o700)
    raw_capture_to_object: dict[str, str] = {}
    artifact_to_object: dict[str, str] = {}
    raw_index: list[dict[str, Any]] = []
    for source in artifacts:
        artifact = RawArtifactMetadata(**source)
        raw_id = artifact.raw_capture_id
        if raw_id in raw_capture_to_object:
            raise BackfillSourceBatchError("duplicate backfill raw capture identity")
        payload = archive.read_verified(artifact)
        if hashlib.sha256(payload).hexdigest() != artifact.payload_sha256:
            raise BackfillSourceBatchError("backfill raw artifact hash mismatch")
        target = raw_root / f"{raw_id}.json"
        _write_raw(target, payload)
        raw_capture_to_object[raw_id] = raw_id
        artifact_to_object[artifact.artifact_id] = raw_id
        raw_index.append(
            {
                "bytes": len(payload),
                "raw_object_id": raw_id,
                "relative_path": f"raw/{target.name}",
                "sha256": artifact.payload_sha256,
            }
        )

    post_rows: list[dict[str, Any]] = []
    post_ids: set[str] = set()
    post_occurrences: list[dict[str, Any]] = []
    occurrence_keys: set[tuple[str, str]] = set()
    for source in posts:
        row = dict(source)
        post_id = _post_fullname(row["post_id"])
        raw_id = str(row["raw_capture_id"])
        if raw_id not in raw_capture_to_object:
            raise BackfillSourceBatchError("backfill post raw artifact is unavailable")
        row["post_id"] = post_id
        row["source_run_id"] = row.pop("run_id")
        row["media_urls"] = json.loads(row.get("media_urls") or "[]")
        post_rows.append(row)
        post_ids.add(post_id)
        occurrence_keys.add((post_id, raw_id))
        post_occurrences.append(
            {
                "lane_type": "parsed_entity",
                "occurrence_id": hashlib.sha256(
                    canonical_json_bytes([run_id, "post", post_id, raw_id])
                ).hexdigest(),
                "post_id": post_id,
                "raw_object_id": raw_id,
                "source_run_id": run_id,
            }
        )

    for source in discovery:
        if not source.get("post_id"):
            continue
        post_id = _post_fullname(source["post_id"])
        raw_id = artifact_to_object.get(str(source["raw_artifact_id"]))
        if post_id not in post_ids or raw_id is None or (post_id, raw_id) in occurrence_keys:
            continue
        occurrence_keys.add((post_id, raw_id))
        post_occurrences.append(
            {
                "disposition": source["disposition"],
                "lane_key": source["lane_key"],
                "lane_type": source["lane_type"],
                "occurrence_id": hashlib.sha256(
                    canonical_json_bytes(
                        [
                            run_id,
                            "discovery",
                            post_id,
                            raw_id,
                            source["page_number"],
                            source["ordinal"],
                        ]
                    )
                ).hexdigest(),
                "page_number": source["page_number"],
                "post_id": post_id,
                "raw_object_id": raw_id,
                "source_run_id": run_id,
            }
        )

    comment_rows: list[dict[str, Any]] = []
    comment_occurrences: list[dict[str, Any]] = []
    for source in comments:
        row = dict(source)
        comment_id = _comment_fullname(row["comment_id"])
        post_id = _post_fullname(row["post_id"])
        raw_id = str(row["raw_capture_id"])
        if post_id not in post_ids:
            raise BackfillSourceBatchError("backfill comment parent post is unavailable")
        if raw_id not in raw_capture_to_object:
            raise BackfillSourceBatchError("backfill comment raw artifact is unavailable")
        row["comment_id"] = comment_id
        row["post_id"] = post_id
        row["parent_id"] = _parent_fullname(row.get("parent_id"), post_id)
        row["source_run_id"] = row.pop("run_id")
        row["deleted_or_removed"] = bool(row["deleted_or_removed"])
        if row.get("is_submitter") is not None:
            row["is_submitter"] = bool(row["is_submitter"])
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

    checkpoint_rows = []
    for source in checkpoints:
        row = dict(source)
        row["source_run_id"] = row.pop("run_id")
        checkpoint_rows.append(row)
    issue_rows = []
    for source in issues:
        row = dict(source)
        row["source_run_id"] = row.pop("run_id")
        row["fatal"] = bool(row["fatal"])
        issue_rows.append(row)
    if seed_only:
        issue_rows.append(
            {
                "detail": "Historical seed import is complete; online discovery and hydration are not claimed complete.",
                "error_class": None,
                "fatal": False,
                "issue_id": "historical_seed_only_coverage",
                "issue_kind": "coverage_debt",
                "lane_key": None,
                "lane_type": "seed",
                "source_run_id": run_id,
            }
        )

    documents = {
        "checkpoints": checkpoint_rows,
        "comment_occurrences": sorted(comment_occurrences, key=lambda row: row["occurrence_id"]),
        "comments": sorted(comment_rows, key=lambda row: row["comment_id"]),
        "issues": sorted(issue_rows, key=lambda row: row["issue_id"]),
        "post_occurrences": sorted(post_occurrences, key=lambda row: row["occurrence_id"]),
        "posts": sorted(post_rows, key=lambda row: row["post_id"]),
        "raw_index": sorted(raw_index, key=lambda row: row["raw_object_id"]),
    }
    paths: dict[str, Path] = {}
    for role in REQUIRED_MEMBER_ROLES:
        path = staging / (role.replace("_", "-") + ".jsonl")
        _write_jsonl(path, documents[role])
        paths[role] = path

    unresolved = sum(int(row.get("more_node_count") or 0) for row in post_rows)
    manifest = {
        "active_thread_policy": None,
        "batch_id": run_id,
        "boundaries": {
            "database_write": False,
            "deploy": False,
            "live_send": False,
            "production_unchanged": True,
            "provider_call": bool(source_manifest["provider_call"]),
            "remote_write": False,
        },
        "counts": {
            "comment_occurrences": len(comment_occurrences),
            "comments": len(comment_rows),
            "issues": len(issue_rows),
            "post_occurrences": len(post_occurrences),
            "posts": len(post_rows),
            "raw_objects": len(raw_index),
            "unresolved_continuations": unresolved,
        },
        "members": [_member(paths[role], role, staging) for role in REQUIRED_MEMBER_ROLES],
        "producer_type": "historical_backfill",
        "profiles": {
            "coverage_profile_sha256": str(source_manifest["required_lanes_sha256"]),
            "coverage_profile_version": "backfill-coverage-" + str(source_manifest["required_lanes_sha256"])[:12],
            "query_profile_sha256": str(source_manifest["keyword_config_sha256"]),
            "query_profile_version": "backfill-query-" + str(source_manifest["keyword_config_sha256"])[:12],
        },
        "schema_version": "reddit_voc_source_batch_v2",
        "status": status,
        "window": {
            "metric_end_utc": _utc_z(source_manifest["effective_end_utc"], label="effective_end_utc"),
            "metric_start_utc": _utc_z(source_manifest["window_start_utc"], label="window_start_utc"),
            "new_post_discovery_end_utc": _utc_z(source_manifest["effective_end_utc"], label="effective_end_utc"),
            "new_post_discovery_start_utc": _utc_z(source_manifest["window_start_utc"], label="window_start_utc"),
            "timezone": "Asia/Shanghai",
        },
    }
    manifest_path = staging / "source-batch-manifest.json"
    manifest_path.write_bytes(canonical_json_bytes(manifest) + b"\n")
    manifest_path.chmod(0o600)
    digest = _sha256(manifest_path)
    load_source_batch(manifest_path, staging, require_consumable=status != "failed")
    return manifest_path, digest


def build_backfill_source_batch(
    *,
    database_path: Path | str,
    archive_root: Path | str,
    run_id: str,
    output_root: Path | str,
) -> BackfillSourceBatchResult:
    root = Path(output_root)
    _private_directory(root, label="backfill source batch output root")
    target = root / run_id
    staging = Path(tempfile.mkdtemp(prefix=f".{run_id}.staging-", dir=root))
    staging.chmod(0o700)
    try:
        _, digest = _build_in_staging(
            staging,
            database_path=Path(database_path),
            archive_root=Path(archive_root),
            run_id=run_id,
        )
        if target.exists() or target.is_symlink():
            if target.is_symlink() or not target.is_dir():
                raise BackfillSourceBatchError("backfill source batch immutable collision")
            existing = load_source_batch(target / "source-batch-manifest.json", target)
            if existing.manifest_sha256 != digest:
                raise BackfillSourceBatchError("backfill source batch immutable collision")
            return BackfillSourceBatchResult(
                batch_root=target,
                manifest_path=target / "source-batch-manifest.json",
                manifest_sha256=digest,
                write_status="no_change",
            )
        os.rename(staging, target)
        return BackfillSourceBatchResult(
            batch_root=target,
            manifest_path=target / "source-batch-manifest.json",
            manifest_sha256=digest,
            write_status="created",
        )
    finally:
        if staging.exists():
            shutil.rmtree(staging)
