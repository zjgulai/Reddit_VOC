#!/usr/bin/env python3
"""Independently validate the identity-only comment debt audit."""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
AUDIT = OUT / "comment-coverage-debt-audit.json"
LOCAL_COMMENTS = ROOT / "data/processed/reddit_voc_site_snapshot_20260714/comments.json"
PRODUCTION_IDENTITY = (
    ROOT
    / "data/imports/tencent_production_20260714/production-identity-snapshot.json"
)
PRODUCTION_CONTENT = (
    ROOT
    / "data/imports/tencent_production_20260714/private/production-content-snapshot.json"
)
TASK37_IDENTITY = OUT / "task37-identity-snapshot.json"
REMOTE_DB = (
    "/opt/reddit-voc-staging/"
    "task37-2560998311fc176c366c70086ba3a58f6b76ee073dba855ea9a0eb1c5f9a94b1/"
    "backfill_momcozy_20250101_20260711/reddit_voc_backfill.sqlite3"
)
EXPECTED_REMOTE_DB_SHA256 = (
    "8356981018466164fe1f84953bd1e1e19010114817dd9689a31b996d9cc51497"
)
RUN_ID = "backfill_momcozy_20250101_20260711"
SENSITIVE_KEYS = {
    "author",
    "author_hash",
    "body",
    "content",
    "media_urls",
    "matched_keywords",
    "raw_capture_id",
    "selftext",
    "source_url",
    "title",
    "username",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def file_sha(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
            remote,
            command,
        ],
        input=stdin,
        capture_output=True,
        check=True,
        text=True,
        timeout=120,
    )
    return completed.stdout


def remote_query() -> str:
    return f'''\
import json
import sqlite3

connection = sqlite3.connect("file:{REMOTE_DB}?mode=ro&immutable=1", uri=True)
connection.execute("PRAGMA query_only=ON")
rows = []
query = """
SELECT candidate.post_id,
       candidate.status_reason,
       thread.num_comments_reported,
       thread.parsed_comment_count,
       thread.more_node_count,
       checkpoint.status,
       checkpoint.stop_reason,
       checkpoint.page_number
FROM backfill_candidates AS candidate
JOIN reddit_threads AS thread ON thread.post_id = candidate.post_id
JOIN backfill_checkpoints AS checkpoint
  ON checkpoint.run_id = candidate.run_id
 AND checkpoint.lane_type = 'comments'
 AND checkpoint.lane_key = candidate.post_id
WHERE candidate.run_id = ?
  AND candidate.status_reason IN ('unresolved_more', 'post_only_coverage')
ORDER BY candidate.post_id
"""
for values in connection.execute(query, ({RUN_ID!r},)):
    comment_ids = [
        row[0]
        for row in connection.execute(
            "SELECT comment_id FROM reddit_comments WHERE post_id = ? ORDER BY comment_id",
            (values[0],),
        )
    ]
    rows.append({{
        "post_id": values[0],
        "status_reason": values[1],
        "reported": values[2] or 0,
        "parsed": values[3],
        "more": values[4],
        "checkpoint_status": values[5],
        "checkpoint_stop_reason": values[6],
        "checkpoint_page_number": values[7],
        "comment_ids": comment_ids,
    }})
print(json.dumps({{
    "quick_check": connection.execute("PRAGMA quick_check").fetchone()[0],
    "query_only": connection.execute("PRAGMA query_only").fetchone()[0] == 1,
    "rows": rows,
}}, separators=(",", ":")))
'''


def forbidden_key_paths(value: Any, prefix: str = "$") -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{prefix}.{key}"
            if key.casefold() in SENSITIVE_KEYS:
                paths.append(child_path)
            paths.extend(forbidden_key_paths(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(forbidden_key_paths(child, f"{prefix}[{index}]"))
    return paths


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--remote", default="ubuntu@101.34.52.232")
    parser.add_argument("--ssh-key", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=OUT / "comment-coverage-debt-validation.json",
    )
    args = parser.parse_args()
    if not args.ssh_key.is_file():
        raise FileNotFoundError(args.ssh_key)

    audit = load_json(AUDIT)
    remote_sha = run_ssh(
        remote=args.remote,
        ssh_key=args.ssh_key,
        command=f"sudo -n sha256sum -- {REMOTE_DB}",
    ).split(maxsplit=1)[0]
    remote = json.loads(
        run_ssh(
            remote=args.remote,
            ssh_key=args.ssh_key,
            command="sudo -n python3 -",
            stdin=remote_query(),
        )
    )

    local_comments_by_post: dict[str, set[str]] = defaultdict(set)
    for row in load_json(LOCAL_COMMENTS):
        local_comments_by_post[row["post_id"]].add(row["comment_id"])

    recomputed_rows: dict[str, dict[str, Any]] = {}
    for row in remote["rows"]:
        remote_ids = set(row["comment_ids"])
        local_ids = local_comments_by_post.get(row["post_id"], set())
        union_ids = remote_ids | local_ids
        recomputed_rows[row["post_id"]] = {
            "status_reason": row["status_reason"],
            "remote_comments": len(remote_ids),
            "local_only_increment": len(local_ids - remote_ids),
            "union_comments": len(union_ids),
            "gap_before": max(int(row["reported"]) - len(remote_ids), 0),
            "gap_after": max(int(row["reported"]) - len(union_ids), 0),
            "more_nodes": int(row["more"]),
            "checkpoint_status": row["checkpoint_status"],
            "checkpoint_stop_reason": row["checkpoint_stop_reason"],
            "checkpoint_page_number": int(row["checkpoint_page_number"]),
        }
    audit_rows = {row["post_id"]: row for row in audit["rows"]}

    production = load_json(PRODUCTION_IDENTITY)
    production_content = load_json(PRODUCTION_CONTENT)
    task37 = load_json(TASK37_IDENTITY)
    production_posts = {row["post_id"] for row in production["posts"]}
    task37_posts = {row["post_id"] for row in task37["posts"]}
    task37_comments = {row["comment_id"] for row in task37["comments"]}
    content_comments = {row["comment_id"] for row in production_content["comments"]}
    production_orphans = [
        row for row in production["comments"] if row["post_id"] not in production_posts
    ]
    exact_task37 = {
        row["comment_id"]
        for row in production_orphans
        if row["comment_id"] in task37_comments
    }
    structural = {
        row["comment_id"]
        for row in production_orphans
        if row["post_id"] in task37_posts
    }
    parent_only = structural - exact_task37
    unlinked = {row["comment_id"] for row in production_orphans} - structural

    rows_equal = set(recomputed_rows) == set(audit_rows) and all(
        audit_rows[post_id]["status_reason"] == row["status_reason"]
        and audit_rows[post_id]["task37_distinct_comment_ids"]
        == row["remote_comments"]
        and audit_rows[post_id]["local_only_comment_increment"]
        == row["local_only_increment"]
        and audit_rows[post_id]["deduplicated_union_comment_count"]
        == row["union_comments"]
        and audit_rows[post_id]["reported_gap_before_offline_union"]
        == row["gap_before"]
        and audit_rows[post_id]["reported_gap_after_offline_union"]
        == row["gap_after"]
        and audit_rows[post_id]["task37_more_node_count"] == row["more_nodes"]
        and audit_rows[post_id]["checkpoint_status"]
        == row["checkpoint_status"]
        and audit_rows[post_id]["checkpoint_stop_reason"]
        == row["checkpoint_stop_reason"]
        and audit_rows[post_id]["checkpoint_page_number"]
        == row["checkpoint_page_number"]
        for post_id, row in recomputed_rows.items()
    )
    gap_after = sum(row["gap_after"] for row in recomputed_rows.values())
    local_increment = sum(
        row["local_only_increment"] for row in recomputed_rows.values()
    )
    more_nodes = sum(row["more_nodes"] for row in recomputed_rows.values())
    increment_candidates = sum(
        row["local_only_increment"] > 0 for row in recomputed_rows.values()
    )

    checks = {
        "audit_source_hash_matches": audit["sources"]["task37_remote_staging"][
            "database_sha256"
        ]
        == remote_sha,
        "remote_database_hash_pinned": remote_sha == EXPECTED_REMOTE_DB_SHA256,
        "remote_quick_check_ok": remote["quick_check"] == "ok",
        "remote_query_only": remote["query_only"],
        "audit_checks_passed": all(audit["checks"].values()),
        "rows_96": len(recomputed_rows) == 96 == len(audit_rows),
        "independent_rows_match_audit": rows_equal,
        "status_split_95_1": sum(
            row["status_reason"] == "unresolved_more"
            for row in recomputed_rows.values()
        )
        == 95
        and sum(
            row["status_reason"] == "post_only_coverage"
            for row in recomputed_rows.values()
        )
        == 1,
        "all_checkpoints_partial_page_one": all(
            row["checkpoint_status"] == "partial"
            and row["checkpoint_stop_reason"] == row["status_reason"]
            and row["checkpoint_page_number"] == 1
            for row in recomputed_rows.values()
        ),
        "local_increment_candidates_7": increment_candidates == 7,
        "local_increment_rows_21": local_increment == 21,
        "remaining_gap_2082": gap_after == 2082,
        "more_nodes_148": more_nodes == 148,
        "all_candidates_still_have_gap": all(
            row["gap_after"] > 0 for row in recomputed_rows.values()
        ),
        "priority_ranks_complete": sorted(
            row["priority_rank"] for row in audit["rows"]
        )
        == list(range(1, 97)),
        "top_priority_gap_566": audit["priority_queue"][0][
            "remaining_reported_gap"
        ]
        == 566,
        "minimum_request_floor_96": audit["provider_budget_floor"][
            "minimum_first_comment_page_request_floor"
        ]
        == 96,
        "one_request_insufficient": audit["provider_budget_floor"][
            "one_request_can_reopen_all_candidates"
        ]
        is False,
        "production_orphans_18": len(production_orphans) == 18,
        "exact_task37_orphans_6": len(exact_task37) == 6,
        "parent_only_recovery_2": len(parent_only) == 2,
        "structural_recovery_8": len(structural) == 8,
        "remaining_unlinked_10": len(unlinked) == 10,
        "private_content_has_all_orphans": all(
            row["comment_id"] in content_comments for row in production_orphans
        ),
        "audit_contains_no_content_or_user_keys": not forbidden_key_paths(audit),
        "remote_content_not_exported": audit["boundaries"][
            "remote_content_exported"
        ]
        is False,
        "remote_usernames_not_exported": audit["boundaries"][
            "remote_usernames_exported"
        ]
        is False,
        "provider_not_called": audit["boundaries"]["provider_call"] is False
        and audit["boundaries"]["provider_attempt_made"] is False,
        "production_unchanged": audit["boundaries"]["production_unchanged"]
        is True,
        "local_product_tests_not_run": audit["boundaries"][
            "local_product_tests_run"
        ]
        is False,
    }
    status = "passed" if all(checks.values()) else "failed"
    result = {
        "schema_version": "momcozy_comment_coverage_debt_validation_v1",
        "validated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "source": {
            "audit_path": str(AUDIT.relative_to(ROOT)),
            "audit_sha256": file_sha(AUDIT),
            "remote_database_sha256": remote_sha,
            "remote_database_mode": "sqlite_uri_mode_ro_immutable_query_only",
        },
        "recomputed": {
            "candidates": len(recomputed_rows),
            "local_increment_candidates": increment_candidates,
            "local_increment_rows": local_increment,
            "remaining_reported_gap": gap_after,
            "more_nodes": more_nodes,
            "structurally_recoverable_production_orphans": len(structural),
            "remaining_unlinked_production_orphans": len(unlinked),
        },
        "checks": checks,
        "boundaries": {
            "remote_write": False,
            "remote_content_exported": False,
            "remote_usernames_exported": False,
            "provider_call": False,
            "provider_attempt_made": False,
            "database_write": "local-analysis-output-only",
            "local_product_tests_run": False,
            "production_unchanged": True,
            "live_send": False,
        },
    }
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "status": status,
                "checks_passed": sum(checks.values()),
                "checks_total": len(checks),
            },
            sort_keys=True,
        )
    )
    if status != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
