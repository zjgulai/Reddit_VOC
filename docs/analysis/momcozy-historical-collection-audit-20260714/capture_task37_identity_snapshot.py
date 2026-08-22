#!/usr/bin/env python3
"""Capture only Task 37 Reddit identity fields from the retained remote staging DB."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from typing import Any


OUT = Path(__file__).resolve().parent
REMOTE_DB = (
    "/opt/reddit-voc-staging/"
    "task37-2560998311fc176c366c70086ba3a58f6b76ee073dba855ea9a0eb1c5f9a94b1/"
    "backfill_momcozy_20250101_20260711/reddit_voc_backfill.sqlite3"
)
EXPECTED_DB_SHA256 = (
    "8356981018466164fe1f84953bd1e1e19010114817dd9689a31b996d9cc51497"
)
EXPECTED_POST_COUNT = 301
EXPECTED_COMMENT_COUNT = 3225


REMOTE_QUERY = f"""
import json
import sqlite3

path = {REMOTE_DB!r}
connection = sqlite3.connect(f"file:{{path}}?mode=ro&immutable=1", uri=True)
connection.execute("PRAGMA query_only=ON")
posts = [
    {{"post_id": post_id, "created_at_utc": created_at_utc}}
    for post_id, created_at_utc in connection.execute(
        "SELECT post_id, created_at_utc FROM reddit_threads ORDER BY post_id"
    )
]
comments = [
    {{
        "comment_id": comment_id,
        "post_id": post_id,
        "created_at_utc": created_at_utc,
    }}
    for comment_id, post_id, created_at_utc in connection.execute(
        "SELECT comment_id, post_id, created_at_utc "
        "FROM reddit_comments ORDER BY comment_id"
    )
]
print(json.dumps({{"posts": posts, "comments": comments}}, separators=(",", ":")))
"""


def canonical_sha(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def run_ssh(
    *, remote: str, ssh_key: Path, command: str, stdin: str | None = None
) -> str:
    completed = subprocess.run(
        [
            "ssh",
            "-i",
            str(ssh_key),
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ConnectTimeout=10",
            remote,
            command,
        ],
        input=stdin,
        capture_output=True,
        check=True,
        text=True,
        timeout=90,
    )
    return completed.stdout


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--remote", default="ubuntu@101.34.52.232")
    parser.add_argument("--ssh-key", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=OUT / "task37-identity-snapshot.json",
    )
    args = parser.parse_args()

    if not args.ssh_key.is_file():
        raise FileNotFoundError(args.ssh_key)

    hash_output = run_ssh(
        remote=args.remote,
        ssh_key=args.ssh_key,
        command=f"sudo -n sha256sum -- {REMOTE_DB}",
    )
    remote_db_sha256 = hash_output.split(maxsplit=1)[0]
    if remote_db_sha256 != EXPECTED_DB_SHA256:
        raise RuntimeError(
            f"Task 37 DB hash mismatch: {remote_db_sha256} != {EXPECTED_DB_SHA256}"
        )

    raw = run_ssh(
        remote=args.remote,
        ssh_key=args.ssh_key,
        command="sudo -n python3 -",
        stdin=REMOTE_QUERY,
    )
    identity = json.loads(raw)
    posts = identity["posts"]
    comments = identity["comments"]
    post_ids = [row["post_id"] for row in posts]
    comment_ids = [row["comment_id"] for row in comments]
    post_id_set = set(post_ids)

    checks = {
        "remote_database_sha256_matches_task37_report": (
            remote_db_sha256 == EXPECTED_DB_SHA256
        ),
        "post_count_301": len(posts) == EXPECTED_POST_COUNT,
        "comment_count_3225": len(comments) == EXPECTED_COMMENT_COUNT,
        "post_ids_unique": len(post_ids) == len(set(post_ids)),
        "comment_ids_unique": len(comment_ids) == len(set(comment_ids)),
        "identity_fields_only": all(set(row) == {"post_id", "created_at_utc"} for row in posts)
        and all(
            set(row) == {"comment_id", "post_id", "created_at_utc"}
            for row in comments
        ),
        "all_comments_link_to_exported_posts": all(
            row["post_id"] in post_id_set for row in comments
        ),
    }
    if not all(checks.values()):
        raise RuntimeError([name for name, passed in checks.items() if not passed])

    snapshot = {
        "schema_version": "task37_reddit_identity_snapshot_v1",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": {
            "environment": "tencent_isolated_staging",
            "task": 37,
            "remote": args.remote,
            "database_path": REMOTE_DB,
            "database_sha256": remote_db_sha256,
            "database_mode": "sqlite_uri_mode_ro_immutable_query_only",
            "fields": {
                "posts": ["post_id", "created_at_utc"],
                "comments": ["comment_id", "post_id", "created_at_utc"],
            },
        },
        "counts": {
            "posts": len(posts),
            "comments": len(comments),
            "orphan_comments": sum(
                row["post_id"] not in post_id_set for row in comments
            ),
        },
        "time_bounds": {
            "post_min_utc": min(row["created_at_utc"] for row in posts),
            "post_max_utc": max(row["created_at_utc"] for row in posts),
            "comment_min_utc": min(row["created_at_utc"] for row in comments),
            "comment_max_utc": max(row["created_at_utc"] for row in comments),
        },
        "identity_sha256": {
            "post_ids": canonical_sha(sorted(post_ids)),
            "comment_ids": canonical_sha(sorted(comment_ids)),
            "comment_linkage": canonical_sha(
                sorted(
                    (row["comment_id"], row["post_id"])
                    for row in comments
                )
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
    write_json(args.output, snapshot)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "posts": len(posts),
                "comments": len(comments),
                "post_ids_sha256": snapshot["identity_sha256"]["post_ids"],
                "comment_ids_sha256": snapshot["identity_sha256"]["comment_ids"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
