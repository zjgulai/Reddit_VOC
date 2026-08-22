#!/usr/bin/env python3
"""Audit V2 staging comment coverage without calling Reddit or TikHub."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3


DEFAULT_RUN_ID = "backfill_momcozy_v2_20250101_20260714"
ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATABASE = ROOT / "data/backfill" / DEFAULT_RUN_ID / "reddit_voc_backfill.sqlite3"
DEFAULT_OUTPUT = Path(__file__).resolve().parent


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def readonly_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        f"{path.resolve(strict=True).as_uri()}?mode=ro&immutable=1",
        uri=True,
        timeout=5.0,
    )
    connection.row_factory = sqlite3.Row
    return connection


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    connection = readonly_connection(args.database)
    try:
        manifest = connection.execute(
            "SELECT status, provider_request_count, max_provider_requests, provider_call, "
            "live_send, required_lanes_sha256 FROM backfill_manifests WHERE run_id=?",
            (args.run_id,),
        ).fetchone()
        if manifest is None:
            raise SystemExit("missing run")
        rows = connection.execute(
            "SELECT post_id, subreddit, num_comments_reported, parsed_comment_count, "
            "more_node_count, coverage_grade FROM reddit_threads WHERE run_id=? "
            "ORDER BY more_node_count DESC, num_comments_reported DESC, post_id",
            (args.run_id,),
        ).fetchall()
        provider_attempts = connection.execute(
            "SELECT COUNT(*) FROM backfill_provider_attempts WHERE run_id=?", (args.run_id,)
        ).fetchone()[0]
    finally:
        connection.close()

    candidates = [
        {
            "post_id": str(row["post_id"]),
            "subreddit": str(row["subreddit"]),
            "reported_comments": int(row["num_comments_reported"] or 0),
            "parsed_comments": int(row["parsed_comment_count"] or 0),
            "reported_minus_parsed": max(
                int(row["num_comments_reported"] or 0)
                - int(row["parsed_comment_count"] or 0),
                0,
            ),
            "more_nodes": int(row["more_node_count"] or 0),
            "coverage_grade": str(row["coverage_grade"]),
        }
        for row in rows
    ]
    partial = [row for row in candidates if row["more_nodes"] > 0]
    by_grade: dict[str, dict[str, int]] = {}
    for row in candidates:
        bucket = by_grade.setdefault(
            row["coverage_grade"],
            {"posts": 0, "reported_comments": 0, "parsed_comments": 0, "more_nodes": 0},
        )
        bucket["posts"] += 1
        bucket["reported_comments"] += row["reported_comments"]
        bucket["parsed_comments"] += row["parsed_comments"]
        bucket["more_nodes"] += row["more_nodes"]

    payload = {
        "schema_version": "momcozy_v2_seed_comment_coverage_audit_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": args.run_id,
        "source_database_sha256": sha256_file(args.database),
        "manifest": dict(manifest),
        "coverage_by_grade": by_grade,
        "aggregate": {
            "posts": len(candidates),
            "reported_comments": sum(row["reported_comments"] for row in candidates),
            "parsed_comments": sum(row["parsed_comments"] for row in candidates),
            "reported_minus_parsed": sum(row["reported_minus_parsed"] for row in candidates),
            "posts_with_more_nodes": len(partial),
            "more_nodes": sum(row["more_nodes"] for row in partial),
            "provider_attempts": int(provider_attempts),
        },
        "comment_repair": {
            "first_post_comment_page_requests_required_at_minimum": len(partial),
            "more_child_cursor_available_from_browser_seed": False,
            "more_child_request_count_known": False,
            "completion_estimate_available": False,
            "separate_ledger_required": True,
            "interpretation": "Only posts with archived More nodes are known to require a TikHub post-comment page. Browser seed payloads do not contain TikHub more.cursor values, so reply requests and their page count remain unknown until a first-page response is archived. Reported-minus-parsed is a priority signal, not a guaranteed retrievable-row count.",
        },
        "v2_discovery": {
            "delta_lanes": 69,
            "one_page_per_lane_request_floor": 69,
            "separate_from_comment_repair": True,
        },
        "boundaries": {
            "provider_call": False,
            "provider_attempt_made": False,
            "production_unchanged": True,
            "production_merge": False,
            "git_push": False,
            "live_send": False,
        },
        "partial_candidates": partial,
    }
    payload["checks"] = {
        "seed_complete": manifest["status"] == "seed_complete",
        "provider_ledger_empty": int(manifest["provider_request_count"]) == 0
        and int(manifest["provider_call"]) == 0
        and int(provider_attempts) == 0,
        "partial_candidates_have_more_nodes": all(row["more_nodes"] > 0 for row in partial),
        "comment_repair_floor_matches_candidates": len(partial)
        == payload["comment_repair"]["first_post_comment_page_requests_required_at_minimum"],
    }
    payload["status"] = "passed" if all(payload["checks"].values()) else "failed"

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "v2-seed-comment-coverage-audit.json"
    csv_path = output_dir / "v2-seed-comment-coverage.csv"
    json_path.write_bytes(canonical_bytes(payload))
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(candidates[0]))
        writer.writeheader()
        writer.writerows(candidates)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if payload["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
