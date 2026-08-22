#!/usr/bin/env python3
"""Profile Task 37 comment debt without exporting remote content or users."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
RUN_ID = "backfill_momcozy_20250101_20260711"
REMOTE_DB = (
    "/opt/reddit-voc-staging/"
    "task37-2560998311fc176c366c70086ba3a58f6b76ee073dba855ea9a0eb1c5f9a94b1/"
    f"{RUN_ID}/reddit_voc_backfill.sqlite3"
)
EXPECTED_REMOTE_DB_SHA256 = (
    "8356981018466164fe1f84953bd1e1e19010114817dd9689a31b996d9cc51497"
)
LOCAL_POSTS = ROOT / "data/processed/reddit_voc_site_snapshot_20260714/posts.json"
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
OVERLAP_AUDIT = OUT / "cross-source-overlap-audit.json"
PROVIDER_CODE = ROOT / "src/reddit_voc/backfill_provider.py"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def file_sha(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


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
        timeout=120,
    )
    return completed.stdout


def remote_query_source() -> str:
    return f'''\
import json
import sqlite3

path = {REMOTE_DB!r}
run_id = {RUN_ID!r}
connection = sqlite3.connect(f"file:{{path}}?mode=ro&immutable=1", uri=True)
connection.execute("PRAGMA query_only=ON")

candidate_columns = [row[1] for row in connection.execute("PRAGMA table_info(backfill_candidates)")]
thread_columns = [row[1] for row in connection.execute("PRAGMA table_info(reddit_threads)")]
comment_columns = [row[1] for row in connection.execute("PRAGMA table_info(reddit_comments)")]
checkpoint_columns = [row[1] for row in connection.execute("PRAGMA table_info(backfill_checkpoints)")]

rows = []
query = """
SELECT candidate.post_id,
       candidate.status_reason,
       candidate.first_lane_type,
       candidate.first_lane_key,
       candidate.post_created_at_utc,
       thread.num_comments_reported,
       thread.parsed_comment_count,
       thread.more_node_count,
       thread.coverage_grade,
       checkpoint.status,
       checkpoint.stop_reason,
       checkpoint.page_number,
       checkpoint.provider_request_count
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
for values in connection.execute(query, (run_id,)):
    post_id = values[0]
    comment_ids = [
        row[0]
        for row in connection.execute(
            "SELECT comment_id FROM reddit_comments WHERE post_id = ? ORDER BY comment_id",
            (post_id,),
        )
    ]
    rows.append({{
        "post_id": post_id,
        "status_reason": values[1],
        "first_lane_type": values[2],
        "first_lane_key": values[3],
        "post_created_at_utc": values[4],
        "num_comments_reported": values[5] or 0,
        "parsed_comment_count": values[6],
        "more_node_count": values[7],
        "coverage_grade": values[8],
        "checkpoint_status": values[9],
        "checkpoint_stop_reason": values[10],
        "checkpoint_page_number": values[11],
        "checkpoint_cumulative_provider_request_count": values[12],
        "comment_ids": comment_ids,
    }})

candidate_statuses = {{
    f"{{status}}/{{reason or '<null>'}}": count
    for status, reason, count in connection.execute(
        "SELECT status, status_reason, COUNT(*) FROM backfill_candidates "
        "WHERE run_id = ? GROUP BY status, status_reason",
        (run_id,),
    )
}}
manifest = connection.execute(
    "SELECT provider_request_count, max_provider_requests, provider_call "
    "FROM backfill_manifests WHERE run_id = ?",
    (run_id,),
).fetchone()
print(json.dumps({{
    "profile": {{
        "quick_check": connection.execute("PRAGMA quick_check").fetchone()[0],
        "query_only": connection.execute("PRAGMA query_only").fetchone()[0] == 1,
        "candidate_columns_required": all(
            column in candidate_columns
            for column in ["post_id", "first_lane_type", "first_lane_key", "status", "status_reason"]
        ),
        "thread_columns_required": all(
            column in thread_columns
            for column in ["post_id", "num_comments_reported", "parsed_comment_count", "more_node_count", "coverage_grade"]
        ),
        "comment_columns_required": all(
            column in comment_columns for column in ["comment_id", "post_id"]
        ),
        "checkpoint_columns_required": all(
            column in checkpoint_columns
            for column in ["lane_type", "lane_key", "status", "stop_reason", "page_number", "provider_request_count"]
        ),
        "candidate_statuses": candidate_statuses,
        "provider_request_count": manifest[0],
        "max_provider_requests": manifest[1],
        "provider_call_intent": bool(manifest[2]),
    }},
    "rows": rows,
}}, ensure_ascii=False, separators=(",", ":")))
'''


def remote_debt(*, remote: str, ssh_key: Path) -> tuple[dict[str, Any], str, str]:
    hash_output = run_ssh(
        remote=remote,
        ssh_key=ssh_key,
        command=f"sudo -n sha256sum -- {REMOTE_DB}",
    )
    remote_db_sha256 = hash_output.split(maxsplit=1)[0]
    if remote_db_sha256 != EXPECTED_REMOTE_DB_SHA256:
        raise RuntimeError(
            f"Task 37 DB hash mismatch: {remote_db_sha256} != {EXPECTED_REMOTE_DB_SHA256}"
        )
    query = remote_query_source()
    output = run_ssh(
        remote=remote,
        ssh_key=ssh_key,
        command="sudo -n python3 -",
        stdin=query,
    )
    return (
        json.loads(output),
        remote_db_sha256,
        sha256(query.encode("utf-8")).hexdigest(),
    )


def gap_tier(gap: int) -> str:
    if gap >= 100:
        return "P0"
    if gap >= 25:
        return "P1"
    if gap >= 10:
        return "P2"
    if gap >= 5:
        return "P3"
    return "P4"


def gap_bucket(gap: int) -> str:
    if gap == 0:
        return "0"
    if gap <= 4:
        return "1-4"
    if gap <= 9:
        return "5-9"
    if gap <= 24:
        return "10-24"
    if gap <= 99:
        return "25-99"
    return "100+"


def build_rows(remote_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    local_posts = {row["post_id"] for row in load_json(LOCAL_POSTS)}
    local_comments_by_post: dict[str, set[str]] = defaultdict(set)
    for row in load_json(LOCAL_COMMENTS):
        local_comments_by_post[row["post_id"]].add(row["comment_id"])

    rows: list[dict[str, Any]] = []
    for remote_row in remote_rows:
        remote_comment_ids = set(remote_row["comment_ids"])
        local_comment_ids = local_comments_by_post.get(remote_row["post_id"], set())
        union_comment_ids = remote_comment_ids | local_comment_ids
        local_only_ids = local_comment_ids - remote_comment_ids
        gap_before = max(
            int(remote_row["num_comments_reported"]) - len(remote_comment_ids), 0
        )
        gap_after = max(
            int(remote_row["num_comments_reported"]) - len(union_comment_ids), 0
        )
        if local_only_ids and gap_after == 0:
            offline_class = "offline_union_meets_reported_count"
        elif local_only_ids:
            offline_class = "offline_union_reduces_gap"
        else:
            offline_class = "no_offline_increment"
        rows.append(
            {
                "post_id": remote_row["post_id"],
                "status_reason": remote_row["status_reason"],
                "first_lane_type": remote_row["first_lane_type"],
                "first_lane_key": remote_row["first_lane_key"],
                "post_created_at_utc": remote_row["post_created_at_utc"],
                "reported_comment_count": int(
                    remote_row["num_comments_reported"]
                ),
                "task37_parsed_comment_count": int(
                    remote_row["parsed_comment_count"]
                ),
                "task37_distinct_comment_ids": len(remote_comment_ids),
                "task37_more_node_count": int(remote_row["more_node_count"]),
                "task37_coverage_grade": remote_row["coverage_grade"],
                "checkpoint_status": remote_row["checkpoint_status"],
                "checkpoint_stop_reason": remote_row["checkpoint_stop_reason"],
                "checkpoint_page_number": int(
                    remote_row["checkpoint_page_number"]
                ),
                "checkpoint_cumulative_provider_request_count": int(
                    remote_row["checkpoint_cumulative_provider_request_count"]
                ),
                "local_post_present": remote_row["post_id"] in local_posts,
                "local_linked_comment_count": len(local_comment_ids),
                "exact_comment_overlap": len(
                    local_comment_ids & remote_comment_ids
                ),
                "local_only_comment_increment": len(local_only_ids),
                "deduplicated_union_comment_count": len(union_comment_ids),
                "reported_gap_before_offline_union": gap_before,
                "reported_gap_after_offline_union": gap_after,
                "offline_gap_reduction": gap_before - gap_after,
                "offline_reconciliation_class": offline_class,
                "priority_tier": gap_tier(gap_after),
                "provider_reopen_status": (
                    "still_required_after_offline_reconciliation"
                    if gap_after > 0 or int(remote_row["more_node_count"]) > 0
                    else "recompute_before_provider"
                ),
                "identities": {
                    "task37_comment_ids": sorted(remote_comment_ids),
                    "local_only_comment_ids": sorted(local_only_ids),
                },
            }
        )
    rows.sort(
        key=lambda row: (
            -row["reported_gap_after_offline_union"],
            -row["task37_more_node_count"],
            row["post_id"],
        )
    )
    for rank, row in enumerate(rows, start=1):
        row["priority_rank"] = rank
    return rows


def build_aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total_gap = sum(row["reported_gap_after_offline_union"] for row in rows)
    buckets: dict[str, Any] = {}
    for name in ("0", "1-4", "5-9", "10-24", "25-99", "100+"):
        selected = [
            row
            for row in rows
            if gap_bucket(row["reported_gap_after_offline_union"]) == name
        ]
        buckets[name] = {
            "candidates": len(selected),
            "remaining_reported_gap": sum(
                row["reported_gap_after_offline_union"] for row in selected
            ),
        }
    concentration: dict[str, Any] = {}
    for top_n in (1, 5, 10, 20, 50, 96):
        gap = sum(
            row["reported_gap_after_offline_union"] for row in rows[:top_n]
        )
        concentration[f"top_{top_n}"] = {
            "remaining_reported_gap": gap,
            "share": round(gap / total_gap, 6) if total_gap else 0.0,
        }
    return {
        "candidates": len(rows),
        "status_reasons": dict(Counter(row["status_reason"] for row in rows)),
        "task37_comment_rows": sum(
            row["task37_distinct_comment_ids"] for row in rows
        ),
        "local_comment_rows_on_candidates": sum(
            row["local_linked_comment_count"] for row in rows
        ),
        "local_only_comment_increment": sum(
            row["local_only_comment_increment"] for row in rows
        ),
        "deduplicated_union_comment_rows": sum(
            row["deduplicated_union_comment_count"] for row in rows
        ),
        "reported_comment_count": sum(
            row["reported_comment_count"] for row in rows
        ),
        "reported_gap_before_offline_union": sum(
            row["reported_gap_before_offline_union"] for row in rows
        ),
        "reported_gap_after_offline_union": total_gap,
        "offline_gap_reduction": sum(row["offline_gap_reduction"] for row in rows),
        "task37_more_nodes": sum(row["task37_more_node_count"] for row in rows),
        "offline_reconciliation_classes": dict(
            Counter(row["offline_reconciliation_class"] for row in rows)
        ),
        "checkpoint_page_distribution": dict(
            sorted(Counter(row["checkpoint_page_number"] for row in rows).items())
        ),
        "parsed_comment_distribution": dict(
            sorted(
                Counter(row["task37_parsed_comment_count"] for row in rows).items()
            )
        ),
        "more_node_distribution": dict(
            sorted(Counter(row["task37_more_node_count"] for row in rows).items())
        ),
        "first_lane_type_distribution": dict(
            Counter(row["first_lane_type"] for row in rows)
        ),
        "first_lane_key_distribution": dict(
            Counter(row["first_lane_key"] for row in rows).most_common()
        ),
        "post_month_distribution": dict(
            sorted(Counter(row["post_created_at_utc"][:7] for row in rows).items())
        ),
        "remaining_gap_buckets": buckets,
        "remaining_gap_concentration": concentration,
    }


def build_orphan_matrix() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    production = load_json(PRODUCTION_IDENTITY)
    production_content = load_json(PRODUCTION_CONTENT)
    task37 = load_json(TASK37_IDENTITY)
    local_post_ids = {row["post_id"] for row in load_json(LOCAL_POSTS)}
    local_comment_ids = {row["comment_id"] for row in load_json(LOCAL_COMMENTS)}
    production_post_ids = {row["post_id"] for row in production["posts"]}
    task37_post_ids = {row["post_id"] for row in task37["posts"]}
    task37_comment_ids = {row["comment_id"] for row in task37["comments"]}
    content_comment_ids = {row["comment_id"] for row in production_content["comments"]}
    orphan_comments = [
        row for row in production["comments"] if row["post_id"] not in production_post_ids
    ]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in orphan_comments:
        grouped[row["post_id"]].append(row)

    rows: list[dict[str, Any]] = []
    for parent_post_id, comments in sorted(grouped.items()):
        comment_ids = {row["comment_id"] for row in comments}
        parent_in_task37 = parent_post_id in task37_post_ids
        exact_task37_ids = comment_ids & task37_comment_ids
        production_only_ids = comment_ids - task37_comment_ids
        rows.append(
            {
                "missing_parent_post_id": parent_post_id,
                "orphan_comments": len(comment_ids),
                "parent_in_local_canonical": parent_post_id in local_post_ids,
                "parent_in_task37": parent_in_task37,
                "exact_comment_ids_in_task37": len(exact_task37_ids),
                "production_only_comments_with_task37_parent": (
                    len(production_only_ids) if parent_in_task37 else 0
                ),
                "structurally_recoverable_comments": (
                    len(comment_ids) if parent_in_task37 else 0
                ),
                "still_unlinked_comments": 0 if parent_in_task37 else len(comment_ids),
                "private_content_rows_available": len(
                    comment_ids & content_comment_ids
                ),
                "comment_min_utc": min(
                    row["created_at_utc"] for row in comments
                ),
                "comment_max_utc": max(
                    row["created_at_utc"] for row in comments
                ),
                "identities": {
                    "comment_ids": sorted(comment_ids),
                    "exact_task37_comment_ids": sorted(exact_task37_ids),
                    "production_only_comment_ids": sorted(production_only_ids),
                },
            }
        )
    aggregate = {
        "production_orphan_comments": len(orphan_comments),
        "missing_parent_posts": len(rows),
        "missing_parent_posts_present_in_task37": sum(
            row["parent_in_task37"] for row in rows
        ),
        "exact_comment_ids_in_task37": sum(
            row["exact_comment_ids_in_task37"] for row in rows
        ),
        "production_only_comments_with_task37_parent": sum(
            row["production_only_comments_with_task37_parent"] for row in rows
        ),
        "structurally_recoverable_comments": sum(
            row["structurally_recoverable_comments"] for row in rows
        ),
        "still_unlinked_comments": sum(
            row["still_unlinked_comments"] for row in rows
        ),
        "private_content_rows_available": sum(
            row["private_content_rows_available"] for row in rows
        ),
        "private_content_identity_snapshot_match": production_content[
            "identity_snapshot_match"
        ],
        "private_content_query_only": production_content["query_only"] == 1,
        "private_content_integrity_ok": production_content["integrity_check"]
        == "ok",
    }
    return rows, aggregate


def write_debt_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [key for key in rows[0] if key != "identities"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(
            {key: value for key, value in row.items() if key != "identities"}
            for row in rows
        )


def write_orphan_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [key for key in rows[0] if key != "identities"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(
            {key: value for key, value in row.items() if key != "identities"}
            for row in rows
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--remote", default="ubuntu@101.34.52.232")
    parser.add_argument("--ssh-key", type=Path, required=True)
    parser.add_argument(
        "--json-output", type=Path, default=OUT / "comment-coverage-debt-audit.json"
    )
    parser.add_argument(
        "--csv-output", type=Path, default=OUT / "comment-coverage-debt.csv"
    )
    parser.add_argument(
        "--orphan-csv-output",
        type=Path,
        default=OUT / "production-orphan-recovery-matrix.csv",
    )
    args = parser.parse_args()
    if not args.ssh_key.is_file():
        raise FileNotFoundError(args.ssh_key)

    remote, remote_db_sha256, remote_query_sha256 = remote_debt(
        remote=args.remote, ssh_key=args.ssh_key
    )
    rows = build_rows(remote["rows"])
    aggregate = build_aggregate(rows)
    orphan_rows, orphan_aggregate = build_orphan_matrix()
    overlap = load_json(OVERLAP_AUDIT)
    provider_code = PROVIDER_CODE.read_text(encoding="utf-8")
    one_get_per_candidate_page = all(
        token in provider_code
        for token in (
            '"post_id": f"t3_{thread.post_id}"',
            "self.executor.get_json(FETCH_POST_COMMENTS, params)",
            'checkpoint.stop_reason\n            in {"unresolved_more", "post_only_coverage"}',
        )
    )
    provider_budget = {
        "task37_provider_request_count": remote["profile"]["provider_request_count"],
        "task37_max_provider_requests": remote["profile"]["max_provider_requests"],
        "task37_remaining_requests": remote["profile"]["max_provider_requests"]
        - remote["profile"]["provider_request_count"],
        "minimum_first_comment_page_request_floor": len(rows),
        "minimum_request_shortfall": len(rows)
        - (
            remote["profile"]["max_provider_requests"]
            - remote["profile"]["provider_request_count"]
        ),
        "one_request_can_reopen_all_candidates": False,
        "full_closure_request_budget_estimated": False,
        "floor_interpretation": (
            "The current endpoint issues one FETCH_POST_COMMENTS GET per candidate "
            "page. Ninety-six first-page requests are therefore a lower bound, not "
            "a closure estimate; unresolved More nodes may require a different "
            "contract or endpoint."
        ),
    }

    checks = {
        "remote_database_sha256_matches": remote_db_sha256
        == EXPECTED_REMOTE_DB_SHA256,
        "remote_quick_check_ok": remote["profile"]["quick_check"] == "ok",
        "remote_query_only": remote["profile"]["query_only"],
        "remote_required_columns_present": all(
            remote["profile"][name]
            for name in (
                "candidate_columns_required",
                "thread_columns_required",
                "comment_columns_required",
                "checkpoint_columns_required",
            )
        ),
        "debt_candidates_96": aggregate["candidates"] == 96,
        "unresolved_more_95": aggregate["status_reasons"]["unresolved_more"]
        == 95,
        "post_only_1": aggregate["status_reasons"]["post_only_coverage"] == 1,
        "task37_candidate_comments_752": aggregate["task37_comment_rows"] == 752,
        "remote_comment_ids_match_thread_counts": all(
            row["task37_parsed_comment_count"]
            == row["task37_distinct_comment_ids"]
            for row in rows
        ),
        "all_checkpoints_are_terminal_partial": all(
            row["checkpoint_status"] == "partial"
            and row["checkpoint_stop_reason"] == row["status_reason"]
            for row in rows
        ),
        "all_checkpoints_are_page_one": all(
            row["checkpoint_page_number"] == 1 for row in rows
        ),
        "local_increment_candidates_7": aggregate[
            "offline_reconciliation_classes"
        ]["offline_union_reduces_gap"]
        == 7,
        "no_local_increment_candidates_89": aggregate[
            "offline_reconciliation_classes"
        ]["no_offline_increment"]
        == 89,
        "no_candidate_meets_reported_count_offline": aggregate[
            "offline_reconciliation_classes"
        ].get("offline_union_meets_reported_count", 0)
        == 0,
        "local_only_increment_21": aggregate["local_only_comment_increment"]
        == 21,
        "remaining_reported_gap_2082": aggregate[
            "reported_gap_after_offline_union"
        ]
        == 2082,
        "more_nodes_148": aggregate["task37_more_nodes"] == 148,
        "all_96_still_require_reopen_decision": all(
            row["provider_reopen_status"]
            == "still_required_after_offline_reconciliation"
            for row in rows
        ),
        "current_code_one_get_per_candidate_page": one_get_per_candidate_page,
        "remaining_provider_budget_1": provider_budget["task37_remaining_requests"]
        == 1,
        "minimum_first_page_floor_96": provider_budget[
            "minimum_first_comment_page_request_floor"
        ]
        == 96,
        "one_request_budget_insufficient": provider_budget[
            "one_request_can_reopen_all_candidates"
        ]
        is False,
        "production_orphans_18": orphan_aggregate[
            "production_orphan_comments"
        ]
        == 18,
        "orphan_parent_groups_4": orphan_aggregate["missing_parent_posts"] == 4,
        "exact_task37_orphan_comments_6": orphan_aggregate[
            "exact_comment_ids_in_task37"
        ]
        == 6,
        "parent_only_recoverable_orphans_2": orphan_aggregate[
            "production_only_comments_with_task37_parent"
        ]
        == 2,
        "structurally_recoverable_orphans_8": orphan_aggregate[
            "structurally_recoverable_comments"
        ]
        == 8,
        "remaining_unlinked_orphans_10": orphan_aggregate[
            "still_unlinked_comments"
        ]
        == 10,
        "private_content_rows_available_18": orphan_aggregate[
            "private_content_rows_available"
        ]
        == 18,
        "overlap_audit_matches_recovery_8_10": overlap[
            "production_orphan_recovery_from_task37"
        ]["structurally_recoverable_after_task37_parent_insert"]
        == 8
        and overlap["production_orphan_recovery_from_task37"][
            "remaining_unlinked_production_comment_ids"
        ]
        == 10,
        "remote_output_identity_and_counts_only": all(
            set(row)
            == {
                "post_id",
                "status_reason",
                "first_lane_type",
                "first_lane_key",
                "post_created_at_utc",
                "num_comments_reported",
                "parsed_comment_count",
                "more_node_count",
                "coverage_grade",
                "checkpoint_status",
                "checkpoint_stop_reason",
                "checkpoint_page_number",
                "checkpoint_cumulative_provider_request_count",
                "comment_ids",
            }
            for row in remote["rows"]
        ),
    }
    if not all(checks.values()):
        raise RuntimeError([name for name, passed in checks.items() if not passed])

    result = {
        "schema_version": "momcozy_comment_coverage_debt_audit_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "method": {
            "grain": "one Task 37 candidate with unresolved_more or post_only_coverage",
            "reported_gap": "max(num_comments_reported - distinct linked comment IDs, 0)",
            "offline_union": "exact comment_id union of Task 37 and the local canonical snapshot for the same post_id",
            "priority": "remaining reported gap descending, then More-node count descending",
            "important_caveat": (
                "Reddit reported comment counts can include deleted, removed, or "
                "later-arriving comments. The gap is a prioritization measure, not "
                "a guaranteed retrievable-row count."
            ),
        },
        "sources": {
            "task37_remote_staging": {
                "remote": args.remote,
                "database_path": REMOTE_DB,
                "database_sha256": remote_db_sha256,
                "database_mode": "sqlite_uri_mode_ro_immutable_query_only",
                "remote_query_sha256": remote_query_sha256,
                "content_exported": False,
                "usernames_exported": False,
            },
            "local_posts": {
                "path": str(LOCAL_POSTS.relative_to(ROOT)),
                "sha256": file_sha(LOCAL_POSTS),
            },
            "local_comments": {
                "path": str(LOCAL_COMMENTS.relative_to(ROOT)),
                "sha256": file_sha(LOCAL_COMMENTS),
            },
            "production_identity": {
                "path": str(PRODUCTION_IDENTITY.relative_to(ROOT)),
                "sha256": file_sha(PRODUCTION_IDENTITY),
            },
            "production_private_content": {
                "path": str(PRODUCTION_CONTENT.relative_to(ROOT)),
                "sha256": file_sha(PRODUCTION_CONTENT),
                "content_fields_exported_to_audit": False,
            },
            "task37_identity": {
                "path": str(TASK37_IDENTITY.relative_to(ROOT)),
                "sha256": file_sha(TASK37_IDENTITY),
            },
            "cross_source_overlap_audit": {
                "path": str(OVERLAP_AUDIT.relative_to(ROOT)),
                "sha256": file_sha(OVERLAP_AUDIT),
            },
            "current_hydrator_code": {
                "path": str(PROVIDER_CODE.relative_to(ROOT)),
                "sha256": file_sha(PROVIDER_CODE),
            },
        },
        "remote_profile": remote["profile"],
        "aggregate": aggregate,
        "provider_budget_floor": provider_budget,
        "priority_queue": [
            {
                "priority_rank": row["priority_rank"],
                "priority_tier": row["priority_tier"],
                "post_id": row["post_id"],
                "status_reason": row["status_reason"],
                "remaining_reported_gap": row[
                    "reported_gap_after_offline_union"
                ],
                "more_nodes": row["task37_more_node_count"],
                "local_only_increment": row["local_only_comment_increment"],
                "provider_reopen_status": row["provider_reopen_status"],
            }
            for row in rows
        ],
        "rows": rows,
        "production_orphan_recovery": {
            "aggregate": orphan_aggregate,
            "parent_groups": orphan_rows,
            "interpretation": (
                "Insert of the one Task 37 parent post makes eight production "
                "orphan comments structurally linkable. Six are exact Task 37 "
                "comment IDs; two are production-only rows already present in the "
                "private local snapshot. Ten comments across three parent IDs still "
                "lack parent evidence."
            ),
        },
        "checks": checks,
        "boundaries": {
            "analysis_only": True,
            "search_profile_changed": False,
            "runtime_code_changed": False,
            "provider_call": False,
            "provider_attempt_made": False,
            "remote_write": False,
            "remote_content_exported": False,
            "remote_usernames_exported": False,
            "database_write": "local-analysis-output-only",
            "local_product_tests_run": False,
            "production_merge_authorized": False,
            "production_unchanged": True,
            "git_push": False,
            "live_send": False,
        },
    }
    write_json(args.json_output, result)
    write_debt_csv(args.csv_output, rows)
    write_orphan_csv(args.orphan_csv_output, orphan_rows)
    print(
        json.dumps(
            {
                "json_output": str(args.json_output),
                "csv_output": str(args.csv_output),
                "orphan_csv_output": str(args.orphan_csv_output),
                "aggregate": aggregate,
                "orphan_aggregate": orphan_aggregate,
                "checks_passed": sum(checks.values()),
                "checks_total": len(checks),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
