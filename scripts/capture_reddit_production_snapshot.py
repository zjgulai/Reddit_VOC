#!/usr/bin/env python3
"""Capture a consistent, allowlisted Reddit production snapshot over read-only SSH."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import subprocess
from typing import Any


REMOTE_CODE = r'''
import datetime
import json
import sqlite3

uri = "file:/app/data/reddit_voc_daily.sqlite3?mode=ro"
conn = sqlite3.connect(uri, uri=True)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA query_only=ON")

post_columns = (
    "post_id, run_id, raw_capture_id, subreddit, title, selftext, source_url, "
    "created_at_utc, score, num_comments_reported, parsed_comment_count, "
    "more_node_count, coverage_grade, matched_keywords, author_hash, media_urls"
)
comment_columns = (
    "comment_id, post_id, run_id, raw_capture_id, parent_id, body, "
    "created_at_utc, score, depth, is_submitter, matched_keywords, "
    "author_hash, deleted_or_removed"
)
analysis_columns = (
    "analysis_id, run_id, source_type, source_id, analysis_version, "
    "sentiment_label, sentiment_score, topic, severity, confidence, "
    "pain_points, provider_call"
)
payload = {
    "schema_version": "reddit_voc_production_content_snapshot_v1",
    "captured_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "source": {
        "environment": "tencent_production",
        "database": "primary_daily_sqlite",
        "container": "reddit_voc_site_app",
        "read_only": True,
        "field_allowlist": True,
    },
    "integrity_check": conn.execute("PRAGMA integrity_check").fetchone()[0],
    "query_only": conn.execute("PRAGMA query_only").fetchone()[0],
    "posts": [dict(row) for row in conn.execute(f"SELECT {post_columns} FROM reddit_threads ORDER BY post_id")],
    "comments": [dict(row) for row in conn.execute(f"SELECT {comment_columns} FROM reddit_comments ORDER BY comment_id")],
    "analyses": [dict(row) for row in conn.execute(f"SELECT {analysis_columns} FROM analysis_results ORDER BY source_type, source_id")],
}
print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
'''


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--identity-file", type=Path, required=True)
    parser.add_argument("--container", default="reddit_voc_site_app")
    parser.add_argument("--identity-snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    identity_file = args.identity_file.resolve(strict=True)
    identity = _load(args.identity_snapshot.resolve(strict=True))
    remote_command = " ".join(
        [
            "docker exec",
            shlex.quote(args.container),
            "python3 -c",
            shlex.quote(REMOTE_CODE),
        ]
    )
    result = subprocess.run(
        [
            "ssh",
            "-i",
            str(identity_file),
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            f"{args.user}@{args.host}",
            remote_command,
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
    )
    if len(result.stdout) > 25_000_000:
        raise ValueError("production snapshot exceeds the 25 MB safety bound")
    payload = json.loads(result.stdout.decode("utf-8"))
    if payload.get("integrity_check") != "ok" or payload.get("query_only") != 1:
        raise ValueError("production snapshot did not prove read-only integrity")

    expected_posts = {str(row["post_id"]) for row in identity["posts"]}
    expected_comments = {str(row["comment_id"]) for row in identity["comments"]}
    actual_posts = {str(row["post_id"]) for row in payload["posts"]}
    actual_comments = {str(row["comment_id"]) for row in payload["comments"]}
    if actual_posts != expected_posts or actual_comments != expected_comments:
        raise ValueError("production content snapshot does not match identity snapshot")
    if len(payload["analyses"]) != sum(identity["analysis_counts"].values()):
        raise ValueError("production analysis count does not match identity snapshot")
    if any(row.get("provider_call") not in (0, False) for row in payload["analyses"]):
        raise ValueError("unexpected provider-backed analysis in production snapshot")

    payload["local_capture_verified_at_utc"] = datetime.now(timezone.utc).isoformat()
    payload["identity_snapshot_match"] = True
    payload["boundaries"] = {
        "production_unchanged": True,
        "provider_call": False,
        "live_send": False,
    }
    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(output, 0o600)
    print(
        json.dumps(
            {
                "status": "captured",
                "output": str(output),
                "posts": len(payload["posts"]),
                "comments": len(payload["comments"]),
                "analyses": len(payload["analyses"]),
                "identity_snapshot_match": True,
                "production_unchanged": True,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
