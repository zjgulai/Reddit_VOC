from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

from reddit_voc.daily_source_batch import (
    _json_object,
    _member,
    _private_directory,
    _profile_version,
    _sha256,
    _write_jsonl,
)
from reddit_voc.report_contracts import canonical_json_bytes
from reddit_voc.source_batch import PRIORITY_REASON_CODES, REQUIRED_MEMBER_ROLES, load_source_batch
from reddit_voc.tikhub import (
    FETCH_POST_COMMENTS,
    _parse_tikhub_comment_payload,
    extract_tikhub_more_cursors,
)
from reddit_voc.v2_center import V2CenterStore


class CommentRefreshError(ValueError):
    pass


@dataclass(frozen=True)
class CommentRefreshResult:
    batch_root: Path
    manifest_path: Path
    manifest_sha256: str
    observed_comments: int
    new_comment_ids: tuple[str, ...]
    write_status: str


def _utc_z(value: datetime, *, label: str) -> str:
    if value.tzinfo is None:
        raise CommentRefreshError(f"{label} is not timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_parent(value: object, post_id: str) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith(("t1_", "t3_")):
        return text
    return "t3_" + text if text == post_id.removeprefix("t3_") else "t1_" + text


def _write_raw(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _build_staging(
    staging: Path,
    *,
    center: V2CenterStore,
    client: Any,
    run_id: str,
    window_start_utc: datetime,
    window_end_utc: datetime,
    query_profile_path: Path,
    coverage_profile_path: Path,
    max_active_threads: int,
) -> tuple[str, tuple[str, ...], int, tuple[str, ...]]:
    if window_end_utc - window_start_utc != timedelta(days=1):
        raise CommentRefreshError("comment refresh window must be exactly 24 hours")
    query_profile, query_sha = _json_object(query_profile_path, label="query profile")
    coverage_profile, coverage_sha = _json_object(coverage_profile_path, label="coverage profile")
    query_version = _profile_version(query_profile, "reddit_voc_query_profile_v1", label="query profile")
    coverage_version = _profile_version(
        coverage_profile, "reddit_voc_coverage_profile_v1", label="coverage profile"
    )
    policy = coverage_profile.get("active_thread_policy")
    if not isinstance(policy, dict) or tuple(policy.get("priority_reason_codes", ())) != PRIORITY_REASON_CODES:
        raise CommentRefreshError("coverage profile active thread policy is invalid")
    active_posts = center.active_thread_payloads(window_end_utc, limit=max_active_threads)
    existing_comment_ids = center.canonical_comment_ids()
    new_comment_ids: set[str] = set()
    raw_index: list[dict[str, object]] = []
    posts: list[dict[str, Any]] = []
    comments_by_id: dict[str, dict[str, Any]] = {}
    post_occurrences: list[dict[str, object]] = []
    comment_occurrences: list[dict[str, object]] = []
    checkpoints: list[dict[str, object]] = []
    issues: list[dict[str, object]] = []
    raw_root = staging / "raw"
    raw_root.mkdir(mode=0o700)

    for post in active_posts:
        post_id = str(post["post_id"])
        try:
            payload = client.get_json(
                FETCH_POST_COMMENTS,
                {
                    "after": "",
                    "need_format": "false",
                    "post_id": post_id,
                    "sort_type": "CONFIDENCE",
                },
            )
        except Exception as exc:
            issues.append(
                {
                    "error_class": type(exc).__name__,
                    "fatal": False,
                    "issue_id": "comment_refresh_" + hashlib.sha256(post_id.encode()).hexdigest()[:16],
                    "issue_kind": "provider_error",
                    "lane_key": post_id,
                    "lane_type": "active_thread",
                }
            )
            continue
        raw_payload = canonical_json_bytes(payload) + b"\n"
        raw_digest = hashlib.sha256(raw_payload).hexdigest()
        raw_id = "raw-refresh-" + hashlib.sha256(
            canonical_json_bytes([run_id, post_id, raw_digest])
        ).hexdigest()[:20]
        raw_path = raw_root / f"{raw_id}.json"
        _write_raw(raw_path, raw_payload)
        raw_index.append(
            {
                "bytes": len(raw_payload),
                "raw_object_id": raw_id,
                "relative_path": f"raw/{raw_path.name}",
                "sha256": raw_digest,
                "terminal_disposition": "entity_observed",
            }
        )
        post_row = dict(post)
        post_row.pop("priority_reason_codes", None)
        posts.append(post_row)
        post_occurrences.append(
            {
                "lane_type": "active_thread",
                "occurrence_id": hashlib.sha256(
                    canonical_json_bytes([run_id, "post", post_id, raw_id])
                ).hexdigest(),
                "post_id": post_id,
                "raw_object_id": raw_id,
            }
        )
        parsed, more_count = _parse_tikhub_comment_payload(
            payload,
            post_id=post_id.removeprefix("t3_"),
            run_id=run_id,
            raw_capture_id=raw_id,
            submitter_name="",
        )
        cursors = extract_tikhub_more_cursors(payload)
        checkpoints.append(
            {
                "lane_key": post_id,
                "lane_type": "active_thread",
                "reply_cursors": list(cursors),
                "status": "partial" if cursors or more_count else "complete",
                "unresolved_continuations": max(more_count, len(cursors)),
            }
        )
        for comment in parsed:
            row = comment.as_record()
            comment_id = str(row["comment_id"])
            row["post_id"] = post_id
            row["parent_id"] = _normalize_parent(row.get("parent_id"), post_id)
            row["deleted_or_removed"] = bool(row["deleted_or_removed"])
            if row.get("is_submitter") is not None:
                row["is_submitter"] = bool(row["is_submitter"])
            existing = comments_by_id.get(comment_id)
            if existing is not None and existing != row:
                raise CommentRefreshError("comment refresh duplicate identity conflict")
            comments_by_id[comment_id] = row
            comment_occurrences.append(
                {
                    "comment_id": comment_id,
                    "occurrence_id": hashlib.sha256(
                        canonical_json_bytes([run_id, "comment", comment_id, raw_id])
                    ).hexdigest(),
                    "raw_object_id": raw_id,
                }
            )
            created = datetime.fromisoformat(str(row["created_at_utc"]).replace("Z", "+00:00"))
            if comment_id not in existing_comment_ids and window_start_utc <= created < window_end_utc:
                new_comment_ids.add(comment_id)

    unresolved = sum(int(row["unresolved_continuations"]) for row in checkpoints)
    status = "empty" if not active_posts else "success"
    if issues or unresolved:
        status = "partial" if raw_index else "failed"
    documents = {
        "checkpoints": sorted(checkpoints, key=lambda row: str(row["lane_key"])),
        "comment_occurrences": sorted(comment_occurrences, key=lambda row: str(row["occurrence_id"])),
        "comments": sorted(comments_by_id.values(), key=lambda row: str(row["comment_id"])),
        "issues": sorted(issues, key=lambda row: str(row["issue_id"])),
        "post_occurrences": sorted(post_occurrences, key=lambda row: str(row["occurrence_id"])),
        "posts": sorted(posts, key=lambda row: str(row["post_id"])),
        "raw_index": sorted(raw_index, key=lambda row: str(row["raw_object_id"])),
    }
    paths: dict[str, Path] = {}
    for role in REQUIRED_MEMBER_ROLES:
        path = staging / (role.replace("_", "-") + ".jsonl")
        _write_jsonl(path, documents[role])
        paths[role] = path
    manifest = {
        "active_thread_policy": policy,
        "batch_id": run_id,
        "boundaries": {
            "database_write": False,
            "deploy": False,
            "live_send": False,
            "production_unchanged": True,
            "provider_call": True,
            "remote_write": False,
        },
        "counts": {
            "comment_occurrences": len(comment_occurrences),
            "comments": len(comments_by_id),
            "issues": len(issues),
            "post_occurrences": len(post_occurrences),
            "posts": len(posts),
            "raw_objects": len(raw_index),
            "unresolved_continuations": unresolved,
        },
        "members": [_member(paths[role], role, staging) for role in REQUIRED_MEMBER_ROLES],
        "producer_type": "comment_refresh",
        "profiles": {
            "coverage_profile_sha256": coverage_sha,
            "coverage_profile_version": coverage_version,
            "query_profile_sha256": query_sha,
            "query_profile_version": query_version,
        },
        "schema_version": "reddit_voc_source_batch_v2",
        "status": status,
        "window": {
            "metric_end_utc": _utc_z(window_end_utc, label="window_end_utc"),
            "metric_start_utc": _utc_z(window_start_utc, label="window_start_utc"),
            "new_post_discovery_end_utc": _utc_z(window_end_utc, label="window_end_utc"),
            "new_post_discovery_start_utc": _utc_z(window_start_utc, label="window_start_utc"),
            "timezone": "Asia/Shanghai",
        },
    }
    manifest_path = staging / "source-batch-manifest.json"
    manifest_path.write_bytes(canonical_json_bytes(manifest) + b"\n")
    manifest_path.chmod(0o600)
    load_source_batch(manifest_path, staging, require_consumable=status != "failed")
    return (
        _sha256(manifest_path),
        tuple(sorted(new_comment_ids)),
        len(comments_by_id),
        tuple(sorted(str(post["post_id"]) for post in posts)),
    )


def build_comment_refresh_source_batch(
    center: V2CenterStore,
    *,
    client: Any,
    run_id: str,
    window_start_utc: datetime,
    window_end_utc: datetime,
    query_profile_path: Path | str,
    coverage_profile_path: Path | str,
    output_root: Path | str,
    max_active_threads: int = 100,
) -> CommentRefreshResult:
    if isinstance(max_active_threads, bool) or max_active_threads < 1:
        raise CommentRefreshError("max_active_threads is invalid")
    root = Path(output_root)
    _private_directory(root, label="comment refresh output root")
    target = root / run_id
    _, query_sha = _json_object(Path(query_profile_path), label="query profile")
    _, coverage_sha = _json_object(Path(coverage_profile_path), label="coverage profile")
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_dir():
            raise CommentRefreshError("comment refresh immutable collision")
        existing = load_source_batch(target / "source-batch-manifest.json", target)
        if (
            existing.profiles.query_profile_sha256 != query_sha
            or existing.profiles.coverage_profile_sha256 != coverage_sha
        ):
            raise CommentRefreshError("comment refresh immutable collision")
        if (
            existing.window.metric_start_utc != window_start_utc.astimezone(timezone.utc)
            or existing.window.metric_end_utc != window_end_utc.astimezone(timezone.utc)
        ):
            raise CommentRefreshError("comment refresh immutable collision")
        comments_path = target / existing.member("comments").relative_path
        comment_rows = [json.loads(line) for line in comments_path.read_bytes().splitlines()]
        known = center.canonical_comment_ids()
        new_comment_ids = tuple(
            sorted(
                str(row["comment_id"])
                for row in comment_rows
                if str(row["comment_id"]) not in known
                and window_start_utc
                <= datetime.fromisoformat(str(row["created_at_utc"]).replace("Z", "+00:00"))
                < window_end_utc
            )
        )
        return CommentRefreshResult(
            batch_root=target,
            manifest_path=target / "source-batch-manifest.json",
            manifest_sha256=existing.manifest_sha256,
            observed_comments=len(comment_rows),
            new_comment_ids=new_comment_ids,
            write_status="no_change",
        )
    staging = Path(tempfile.mkdtemp(prefix=f".{run_id}.staging-", dir=root))
    staging.chmod(0o700)
    try:
        digest, new_comment_ids, observed_comments, refreshed_post_ids = _build_staging(
            staging,
            center=center,
            client=client,
            run_id=run_id,
            window_start_utc=window_start_utc,
            window_end_utc=window_end_utc,
            query_profile_path=Path(query_profile_path),
            coverage_profile_path=Path(coverage_profile_path),
            max_active_threads=max_active_threads,
        )
        os.rename(staging, target)
        center.mark_threads_refreshed(refreshed_post_ids, window_end_utc)
        return CommentRefreshResult(
            batch_root=target,
            manifest_path=target / "source-batch-manifest.json",
            manifest_sha256=digest,
            observed_comments=observed_comments,
            new_comment_ids=new_comment_ids,
            write_status="created",
        )
    finally:
        if staging.exists():
            shutil.rmtree(staging)
