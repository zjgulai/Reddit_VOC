#!/usr/bin/env python3
"""Export an allowlisted Reddit SQLite snapshot over read-only SSH.

The remote database is opened with SQLite URI ``mode=ro&immutable=1`` after
its SHA-256 and absence of journal sidecars are verified.  All remote output
is streamed over stdout; this script never creates a remote file.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import subprocess
from typing import Any


POST_COLUMNS = (
    "post_id, run_id, raw_capture_id, subreddit, title, selftext, source_url, "
    "created_at_utc, score, num_comments_reported, parsed_comment_count, "
    "more_node_count, coverage_grade, matched_keywords, author_hash, media_urls"
)
COMMENT_COLUMNS = (
    "comment_id, post_id, run_id, raw_capture_id, parent_id, body, "
    "created_at_utc, score, depth, is_submitter, matched_keywords, "
    "author_hash, deleted_or_removed"
)
ANALYSIS_COLUMNS = (
    "analysis_id, run_id, source_type, source_id, analysis_version, "
    "sentiment_label, sentiment_score, topic, severity, confidence, "
    "pain_points, provider_call"
)
MAX_SNAPSHOT_BYTES = 50_000_000


def _sha256_object(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _remote_query(database_path: str, *, immutable: bool) -> str:
    uri_suffix = "&immutable=1" if immutable else ""
    return f'''
import datetime
import json
import os
import sqlite3

path = {database_path!r}
sidecars = {{suffix: os.path.exists(path + suffix) for suffix in ("-wal", "-shm", "-journal")}}
if {immutable!r} and any(sidecars.values()):
    raise RuntimeError("sqlite sidecar present; immutable read refused")

connection = sqlite3.connect(
    f"file:{{path}}?mode=ro{uri_suffix}",
    uri=True,
    timeout=30,
)
connection.row_factory = sqlite3.Row
connection.execute("PRAGMA query_only=ON")
connection.execute("PRAGMA busy_timeout=30000")
connection.execute("BEGIN")
tables = {{
    row[0]
    for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
}}
count_tables = (
    "runs",
    "raw_captures",
    "reddit_threads",
    "reddit_comments",
    "analysis_results",
    "backfill_candidates",
    "backfill_provider_attempts",
)

payload = {{
    "captured_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "query_only": connection.execute("PRAGMA query_only").fetchone()[0],
    "integrity_check": connection.execute("PRAGMA integrity_check").fetchone()[0],
    "quick_check": connection.execute("PRAGMA quick_check").fetchone()[0],
    "foreign_key_violations": len(connection.execute("PRAGMA foreign_key_check").fetchall()),
    "sidecars": sidecars,
    "counts": {{
        table: (
            connection.execute(f'SELECT COUNT(*) FROM "{{table}}"').fetchone()[0]
            if table in tables
            else 0
        )
        for table in count_tables
    }},
    "run_history": [dict(row) for row in connection.execute(
        "SELECT status, provider_call, live_send, COUNT(*) AS count "
        "FROM runs GROUP BY status, provider_call, live_send "
        "ORDER BY status, provider_call, live_send"
    )],
    "candidate_status": (
        [dict(row) for row in connection.execute(
            "SELECT status, status_reason, COUNT(*) AS count "
            "FROM backfill_candidates GROUP BY status, status_reason "
            "ORDER BY status, status_reason"
        )]
        if "backfill_candidates" in tables
        else []
    ),
    "provider_attempt_history": (
        [dict(row) for row in connection.execute(
            "SELECT status, COUNT(*) AS count FROM backfill_provider_attempts "
            "GROUP BY status ORDER BY status"
        )]
        if "backfill_provider_attempts" in tables
        else []
    ),
    "posts": [dict(row) for row in connection.execute(
        "SELECT {POST_COLUMNS} FROM reddit_threads ORDER BY post_id"
    )],
    "comments": [dict(row) for row in connection.execute(
        "SELECT {COMMENT_COLUMNS} FROM reddit_comments ORDER BY comment_id"
    )],
    "analyses": [dict(row) for row in connection.execute(
        "SELECT {ANALYSIS_COLUMNS} FROM analysis_results "
        "ORDER BY source_type, source_id, analysis_id"
    )],
}}
connection.rollback()
connection.close()
print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
'''


def _run_ssh(
    *,
    identity_file: Path,
    remote: str,
    command: str,
    stdin: str | None = None,
    timeout: int = 120,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [
            "ssh",
            "-i",
            str(identity_file),
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ConnectTimeout=15",
            remote,
            command,
        ],
        input=None if stdin is None else stdin.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        timeout=timeout,
    )


def _validate_remote_path(value: str) -> str:
    path = PurePosixPath(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("remote database path must be absolute and normalized")
    if path.suffix not in {".sqlite", ".sqlite3", ".db"}:
        raise ValueError("remote database must have a SQLite filename suffix")
    return str(path)


def _identity_snapshot(
    *, payload: dict[str, Any], source: dict[str, Any], checks: dict[str, bool]
) -> dict[str, Any]:
    posts = [
        {"post_id": row["post_id"], "created_at_utc": row["created_at_utc"]}
        for row in payload["posts"]
    ]
    comments = [
        {
            "comment_id": row["comment_id"],
            "post_id": row["post_id"],
            "created_at_utc": row["created_at_utc"],
        }
        for row in payload["comments"]
    ]
    return {
        "schema_version": "reddit_voc_remote_identity_snapshot_v1",
        "captured_at_utc": payload["captured_at_utc"],
        "source": source,
        "counts": {
            "posts": len(posts),
            "comments": len(comments),
            "analyses": len(payload["analyses"]),
            "orphan_comments": sum(
                row["post_id"] not in {post["post_id"] for post in posts}
                for row in comments
            ),
        },
        "time_bounds": {
            "post_min_utc": min(row["created_at_utc"] for row in posts),
            "post_max_utc": max(row["created_at_utc"] for row in posts),
            "comment_min_utc": min(row["created_at_utc"] for row in comments),
            "comment_max_utc": max(row["created_at_utc"] for row in comments),
        },
        "identity_sha256": {
            "post_ids": _sha256_object(sorted(row["post_id"] for row in posts)),
            "comment_ids": _sha256_object(
                sorted(row["comment_id"] for row in comments)
            ),
            "comment_linkage": _sha256_object(
                sorted((row["comment_id"], row["post_id"]) for row in comments)
            ),
        },
        "checks": checks,
        "posts": posts,
        "comments": comments,
        "boundaries": {
            "content_exported": False,
            "usernames_exported": False,
            "remote_write": False,
            "provider_call": False,
            "provider_attempt_made": False,
            "production_unchanged": True,
            "live_send": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--remote", default="ubuntu@101.34.52.232")
    parser.add_argument("--ssh-key", type=Path, required=True)
    parser.add_argument("--remote-database", required=True)
    parser.add_argument("--expected-database-sha256", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--identity-output", type=Path, required=True)
    parser.add_argument("--content-output", type=Path, required=True)
    parser.add_argument(
        "--active-database",
        action="store_true",
        help="Use a normal read-only transaction instead of immutable mode.",
    )
    parser.add_argument(
        "--allow-orphan-comments",
        action="store_true",
        help="Permit comments whose parent post is outside this database snapshot.",
    )
    args = parser.parse_args()

    identity_file = args.ssh_key.resolve(strict=True)
    remote_database = _validate_remote_path(args.remote_database)
    hash_result = _run_ssh(
        identity_file=identity_file,
        remote=args.remote,
        command=f"sudo -n sha256sum -- {shlex.quote(remote_database)}",
    )
    remote_sha256 = hash_result.stdout.decode("utf-8").split(maxsplit=1)[0]
    if remote_sha256 != args.expected_database_sha256:
        raise RuntimeError(
            "remote database SHA-256 mismatch: "
            f"{remote_sha256} != {args.expected_database_sha256}"
        )

    result = _run_ssh(
        identity_file=identity_file,
        remote=args.remote,
        command="sudo -n python3 -",
        stdin=_remote_query(remote_database, immutable=not args.active_database),
    )
    if len(result.stdout) > MAX_SNAPSHOT_BYTES:
        raise ValueError("remote snapshot exceeds the 50 MB safety bound")
    payload = json.loads(result.stdout.decode("utf-8"))

    post_ids = [str(row["post_id"]) for row in payload["posts"]]
    comment_ids = [str(row["comment_id"]) for row in payload["comments"]]
    post_id_set = set(post_ids)
    analysis_ids = [str(row["analysis_id"]) for row in payload["analyses"]]
    analysis_sources = {
        (str(row["source_type"]), str(row["source_id"]))
        for row in payload["analyses"]
    }
    expected_comment_ids = {
        str(row["comment_id"])
        for row in payload["comments"]
        if not args.allow_orphan_comments or str(row["post_id"]) in post_id_set
    }
    expected_analysis_sources = {
        *(('post', post_id) for post_id in post_ids),
        *(('comment', comment_id) for comment_id in expected_comment_ids),
    }
    checks = {
        "database_sha256_matches": remote_sha256
        == args.expected_database_sha256,
        "query_only_enabled": payload["query_only"] == 1,
        "integrity_check_ok": payload["integrity_check"] == "ok",
        "quick_check_ok": payload["quick_check"] == "ok",
        "foreign_key_check_ok": payload["foreign_key_violations"] == 0,
        "sqlite_read_mode_safe": args.active_database
        or not any(payload["sidecars"].values()),
        "post_count_matches": len(post_ids)
        == payload["counts"]["reddit_threads"],
        "comment_count_matches": len(comment_ids)
        == payload["counts"]["reddit_comments"],
        "analysis_count_matches": len(analysis_ids)
        == payload["counts"]["analysis_results"],
        "post_ids_unique": len(post_ids) == len(post_id_set),
        "comment_ids_unique": len(comment_ids) == len(set(comment_ids)),
        "analysis_ids_unique": len(analysis_ids) == len(set(analysis_ids)),
        "comment_linkage_policy_passed": args.allow_orphan_comments
        or all(
            str(row["post_id"]) in post_id_set for row in payload["comments"]
        ),
        "analysis_sources_exact": analysis_sources == expected_analysis_sources,
        "analysis_provider_calls_false": all(
            row.get("provider_call") in (0, False) for row in payload["analyses"]
        ),
    }
    if not all(checks.values()):
        raise RuntimeError(
            "remote snapshot checks failed: "
            + ", ".join(name for name, passed in checks.items() if not passed)
        )

    source = {
        "environment": args.environment,
        "dataset_id": args.dataset_id,
        "remote": args.remote,
        "database_path": remote_database,
        "database_sha256": remote_sha256,
        "database_mode": (
            "sqlite_uri_mode_ro_query_only_transaction"
            if args.active_database
            else "sqlite_uri_mode_ro_immutable_query_only_transaction"
        ),
        "field_allowlist": True,
        "remote_write": False,
    }
    identity = _identity_snapshot(payload=payload, source=source, checks=checks)
    content = {
        "schema_version": "reddit_voc_remote_content_snapshot_v1",
        "captured_at_utc": payload["captured_at_utc"],
        "local_capture_verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "integrity_check": payload["integrity_check"],
        "quick_check": payload["quick_check"],
        "query_only": payload["query_only"],
        "foreign_key_violations": payload["foreign_key_violations"],
        "sidecars": payload["sidecars"],
        "counts": payload["counts"],
        "run_history": payload["run_history"],
        "candidate_status": payload["candidate_status"],
        "provider_attempt_history": payload["provider_attempt_history"],
        "posts": payload["posts"],
        "comments": payload["comments"],
        "analyses": payload["analyses"],
        "identity_snapshot_match": True,
        "identity_sha256": identity["identity_sha256"],
        "checks": checks,
        "boundaries": {
            "production_unchanged": True,
            "remote_write": False,
            "database_write": False,
            "provider_call": False,
            "provider_attempt_made": False,
            "live_send": False,
            "webhook_send": False,
            "deploy": False,
            "schedule_change": False,
        },
    }

    for path, value in (
        (args.identity_output, identity),
        (args.content_output, content),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.chmod(path, 0o600)

    print(
        json.dumps(
            {
                "status": "captured",
                "identity_output": str(args.identity_output),
                "content_output": str(args.content_output),
                "database_sha256": remote_sha256,
                "posts": len(post_ids),
                "comments": len(comment_ids),
                "analyses": len(analysis_ids),
                "production_unchanged": True,
                "remote_write": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
