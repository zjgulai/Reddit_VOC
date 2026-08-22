#!/usr/bin/env python3
"""Capture production Reddit identities over read-only SSH without content fields."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shlex
import subprocess


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PREVIOUS = (
    ROOT
    / "data/imports/tencent_production_20260714/production-identity-snapshot.json"
)
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "production-identity-refresh.json"


REMOTE_CODE = r'''
import datetime
import json
import sqlite3

uri = "file:/app/data/reddit_voc_daily.sqlite3?mode=ro"
conn = sqlite3.connect(uri, uri=True, timeout=30)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA query_only=ON")
conn.execute("PRAGMA busy_timeout=30000")
conn.execute("BEGIN")
payload = {
    "captured_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "query_only": conn.execute("PRAGMA query_only").fetchone()[0],
    "quick_check": conn.execute("PRAGMA quick_check").fetchone()[0],
    "run_count": conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0],
    "raw_capture_count": conn.execute("SELECT COUNT(*) FROM raw_captures").fetchone()[0],
    "posts": [dict(row) for row in conn.execute(
        "SELECT post_id, created_at_utc FROM reddit_threads ORDER BY post_id"
    )],
    "comments": [dict(row) for row in conn.execute(
        "SELECT comment_id, post_id, created_at_utc FROM reddit_comments ORDER BY comment_id"
    )],
    "analysis_counts": {
        str(row["source_type"]): int(row["count"])
        for row in conn.execute(
            "SELECT source_type, COUNT(*) AS count FROM analysis_results GROUP BY source_type ORDER BY source_type"
        )
    },
    "run_post_counts": [dict(row) for row in conn.execute(
        "SELECT run_id, COUNT(*) AS posts FROM reddit_threads GROUP BY run_id ORDER BY run_id"
    )],
}
conn.rollback()
conn.close()
print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
'''


def file_sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def identity_sha(values: list[str]) -> str:
    return sha256("\n".join(sorted(values)).encode("utf-8")).hexdigest()


def run_ssh(
    *, identity_file: Path, host: str, user: str, command: str
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [
            "ssh",
            "-i",
            str(identity_file),
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ConnectTimeout=15",
            f"{user}@{host}",
            command,
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=90,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="101.34.52.232")
    parser.add_argument("--user", default="ubuntu")
    parser.add_argument("--container", default="reddit_voc_site_app")
    parser.add_argument("--ssh-key", type=Path, required=True)
    parser.add_argument("--previous", type=Path, default=DEFAULT_PREVIOUS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    identity_file = args.ssh_key.resolve(strict=True)
    previous_path = args.previous.resolve(strict=True)
    previous = json.loads(previous_path.read_text(encoding="utf-8"))
    inspect_command = (
        f"docker inspect -f {shlex.quote('{{.Id}}|{{.Image}}|{{.State.StartedAt}}|{{.State.Running}}|{{.RestartCount}}')} "
        f"{shlex.quote(args.container)}"
    )
    before = run_ssh(
        identity_file=identity_file,
        host=args.host,
        user=args.user,
        command=inspect_command,
    ).stdout.decode("utf-8").strip()
    remote_command = " ".join(
        [
            "docker exec",
            shlex.quote(args.container),
            "python3 -c",
            shlex.quote(REMOTE_CODE),
        ]
    )
    result = run_ssh(
        identity_file=identity_file,
        host=args.host,
        user=args.user,
        command=remote_command,
    )
    after = run_ssh(
        identity_file=identity_file,
        host=args.host,
        user=args.user,
        command=inspect_command,
    ).stdout.decode("utf-8").strip()
    remote = json.loads(result.stdout.decode("utf-8"))

    posts = remote["posts"]
    comments = remote["comments"]
    post_ids = {str(row["post_id"]) for row in posts}
    comment_ids = {str(row["comment_id"]) for row in comments}
    previous_post_ids = {str(row["post_id"]) for row in previous["posts"]}
    previous_comment_ids = {str(row["comment_id"]) for row in previous["comments"]}
    orphan_comment_ids = sorted(
        str(row["comment_id"])
        for row in comments
        if str(row["post_id"]) not in post_ids
    )
    payload = {
        "schema_version": "reddit_voc_production_identity_refresh_v1",
        "captured_at_utc": remote["captured_at_utc"],
        "source": {
            "environment": "tencent_production",
            "database": "primary_daily_sqlite",
            "container": args.container,
            "remote": f"{args.user}@{args.host}",
            "read_only": True,
            "identity_fields_only": True,
            "previous_snapshot": str(previous_path.relative_to(ROOT)),
            "previous_snapshot_sha256": file_sha(previous_path),
        },
        "counts": {
            "runs": int(remote["run_count"]),
            "raw_captures": int(remote["raw_capture_count"]),
            "posts": len(posts),
            "comments": len(comments),
            "analyses": sum(int(value) for value in remote["analysis_counts"].values()),
            "orphan_comments": len(orphan_comment_ids),
        },
        "analysis_counts": remote["analysis_counts"],
        "time_bounds": {
            "post_min_utc": min(row["created_at_utc"] for row in posts),
            "post_max_utc": max(row["created_at_utc"] for row in posts),
            "comment_min_utc": min(row["created_at_utc"] for row in comments),
            "comment_max_utc": max(row["created_at_utc"] for row in comments),
        },
        "identity_sha256": {
            "post_ids": identity_sha(list(post_ids)),
            "comment_ids": identity_sha(list(comment_ids)),
        },
        "comparison_to_previous": {
            "new_post_ids": sorted(post_ids - previous_post_ids),
            "new_comment_ids": sorted(comment_ids - previous_comment_ids),
            "removed_post_ids": sorted(previous_post_ids - post_ids),
            "removed_comment_ids": sorted(previous_comment_ids - comment_ids),
            "post_count_delta": len(posts) - len(previous["posts"]),
            "comment_count_delta": len(comments) - len(previous["comments"]),
            "database_identity_unchanged": (
                post_ids == previous_post_ids and comment_ids == previous_comment_ids
            ),
        },
        "orphan_comment_ids": orphan_comment_ids,
        "run_post_counts": remote["run_post_counts"],
        "posts": posts,
        "comments": comments,
        "boundaries": {
            "provider_call": False,
            "provider_attempt_made": False,
            "production_unchanged": True,
            "remote_write": False,
            "live_send": False,
            "local_product_tests_run": False,
        },
        "checks": {
            "query_only_enabled": remote["query_only"] == 1,
            "quick_check_ok": remote["quick_check"] == "ok",
            "post_ids_unique": len(post_ids) == len(posts),
            "comment_ids_unique": len(comment_ids) == len(comments),
            "previous_posts_preserved": previous_post_ids <= post_ids,
            "previous_comments_preserved": previous_comment_ids <= comment_ids,
            "container_state_stable": before == after,
            "identity_fields_only": set(posts[0]) == {"post_id", "created_at_utc"}
            and set(comments[0])
            == {"comment_id", "post_id", "created_at_utc"},
        },
    }
    if not all(payload["checks"].values()):
        raise RuntimeError(f"production identity refresh checks failed: {payload['checks']}")

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "posts": len(posts),
                "comments": len(comments),
                "new_posts": len(payload["comparison_to_previous"]["new_post_ids"]),
                "new_comments": len(
                    payload["comparison_to_previous"]["new_comment_ids"]
                ),
                "post_max_utc": payload["time_bounds"]["post_max_utc"],
                "comment_max_utc": payload["time_bounds"]["comment_max_utc"],
                "production_unchanged": True,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
