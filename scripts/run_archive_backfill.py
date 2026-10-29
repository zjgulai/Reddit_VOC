#!/usr/bin/env python3
"""Backfill the archive gap, one weekly shard at a time.

Usage:
    python3 scripts/run_archive_backfill.py --from 2026-07-23 --to 2026-10-04
    python3 scripts/run_archive_backfill.py --plan-only           # show shards + gaps
    python3 scripts/run_archive_backfill.py --shard 0             # run only the first shard
    python3 scripts/run_archive_backfill.py --resume              # skip days already covered

Design notes:

  - One shard = one actor run = one retryable unit. Weekly granularity keeps a
    failure cheap and the whole 74-day hole to ~11 runs.
  - A shard whose run comes back truncated is recorded as `partial` and its days
    stay gaps, so re-running `--resume` picks them up again. Partial data is never
    promoted to "covered".
  - Coverage is written per (lane, business day) so the ledger, not this script,
    is the source of truth for what is still missing.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from reddit_voc.archive_collector import (  # noqa: E402
    ArchiveRedditClient,
    backfill_week_shards,
    build_plan,
    collect_archive,
    shanghai_t1,
)
from reddit_voc.storage import VocStore  # noqa: E402

# Discovery channel. Measured on 2026-10-28 over 2026-07-23..07-27:
#   subreddits  -> 800 posts   (reliable)
#   searchQueries -> 0 posts   (unreliable; kept only as a secondary sweep)
#   commentSearchQueries -> 300 items, all posts, 0 comments (advertised as comment
#     full-text search but does not deliver)
# So subreddit listings carry discovery, and comments come from two-phase postIds
# expansion, which measured 9.0 comments/post vs ~4.7 for the realtime actor.
SUBREDDITS = [
    "ExclusivelyPumping",
    "breastfeeding",
    "workingmoms",
    "beyondthebump",
    "NewParents",
    "Momcozy",
    "BabyBumps",
]
SEARCH_QUERIES = ["Momcozy", "wearable breast pump"]
# Kept empty: the provider's comment search does not return comments (see above).
COMMENT_QUERIES: list[str] = []

# The known hole: publication froze on 2026-07-23 and collection resumed 2026-10-05.
DEFAULT_FROM = "2026-07-23"
DEFAULT_TO = "2026-10-04"


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill Reddit archive gap by weekly shard")
    parser.add_argument("--from", dest="date_from", default=DEFAULT_FROM)
    parser.add_argument("--to", dest="date_to", default=DEFAULT_TO)
    parser.add_argument("--store", type=Path, default=Path("/opt/echo-agent-bot/data/reddit_voc_daily.sqlite3"))
    parser.add_argument("--raw-root", type=Path, default=Path("/opt/echo-agent-bot/data/raw"))
    parser.add_argument("--output-dir", type=Path, default=Path("/opt/echo-agent-bot/outputs"))
    parser.add_argument("--max-items", type=int, default=1200)
    parser.add_argument("--max-items-per-target", type=int, default=250)
    parser.add_argument("--max-wait", type=int, default=900)
    parser.add_argument("--max-expand-posts", type=int, default=60,
                        help="how many discovered posts to expand comments for")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--shard", type=int, default=None, help="run only this shard index")
    parser.add_argument("--resume", action="store_true", help="skip days already covered")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    date_from = date.fromisoformat(args.date_from)
    date_to = date.fromisoformat(args.date_to)
    if date_to < date_from:
        print(f"invalid range: {date_from} > {date_to}", file=sys.stderr)
        return 2

    shards = backfill_week_shards(date_from, date_to)
    plan = build_plan(
        date_from=date_from,
        date_to=date_to,
        search_queries=SEARCH_QUERIES,
        comment_queries=COMMENT_QUERIES,
        subreddits=SUBREDDITS,
        max_items=args.max_items,
        max_items_per_target=args.max_items_per_target,
    )

    print(json.dumps({
        "plan_id": plan["plan_id"],
        "range": [date_from.isoformat(), date_to.isoformat()],
        "shards": len(shards),
        "subreddits": len(SUBREDDITS),
        "search_queries": len(SEARCH_QUERIES),
        "comment_queries": len(COMMENT_QUERIES),
    }, ensure_ascii=False, indent=1))

    store = VocStore(args.store)
    store.migrate()

    selected = shards if args.shard is None else [shards[args.shard]]
    if args.plan_only:
        for i, (s, e) in enumerate(shards):
            print(f"  shard {i:2d}: {s} .. {e}  ({(e - s).days + 1}d)")
        gaps = store.coverage_gaps(date_from.isoformat(), date_to.isoformat())
        print(f"known gaps in ledger: {len(gaps)}")
        return 0

    client = None if args.dry_run else ArchiveRedditClient()
    receipts: list[dict] = []
    failed_shards: list[int] = []

    for index, (shard_start, shard_end) in enumerate(selected):
        real_index = index if args.shard is None else args.shard
        if args.resume:
            pending = store.coverage_gaps(shard_start.isoformat(), shard_end.isoformat())
            if not pending:
                receipts.append({
                    "shard": real_index, "range": [shard_start.isoformat(), shard_end.isoformat()],
                    "status": "skipped_already_covered",
                })
                continue
        run_id = f"backfill_{shard_start:%Y%m%d}_{shard_end:%Y%m%d}"

        if args.dry_run:
            receipts.append({
                "shard": real_index, "run_id": run_id,
                "range": [shard_start.isoformat(), shard_end.isoformat()],
                "status": "dry_run",
            })
            continue

        logging.info("shard %s/%s: %s .. %s", real_index, len(shards), shard_start, shard_end)
        summary, coverage = collect_archive(
            store,
            run_id=run_id,
            client=client,
            date_from=shard_start,
            date_to=shard_end,
            search_queries=SEARCH_QUERIES,
            comment_queries=COMMENT_QUERIES,
            subreddits=SUBREDDITS,
            expand_comments=True,
            max_expand_posts=args.max_expand_posts,
            max_items=args.max_items,
            max_items_per_target=args.max_items_per_target,
            max_wait_seconds=args.max_wait,
            raw_artifact_root=args.raw_root,
        )
        store.record_coverage(run_id, coverage, plan["plan_id"])

        covered_days = sum(1 for row in coverage if row["reached_floor"])
        missing_days = sum(1 for row in coverage if row["completeness"] == "missing")
        receipts.append({
            "shard": real_index,
            "run_id": run_id,
            "range": [shard_start.isoformat(), shard_end.isoformat()],
            "status": summary.status,
            "posts": summary.ingested_threads,
            "comments": summary.ingested_comments,
            "covered_days": covered_days,
            "missing_days": missing_days,
            "issues": summary.issues,
        })
        if summary.status == "failed":
            failed_shards.append(real_index)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt_path = args.output_dir / f"archive-backfill-{stamp}.json"
    total_posts = sum(r.get("posts", 0) for r in receipts)
    total_comments = sum(r.get("comments", 0) for r in receipts)
    doc = {
        "schema_version": "echo_agent_archive_backfill_receipt_v1",
        "plan_id": plan["plan_id"],
        "range": [date_from.isoformat(), date_to.isoformat()],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "shards_total": len(shards),
        "shards_run": len(selected),
        "totals": {"posts": total_posts, "comments": total_comments},
        "failed_shards": failed_shards,
        "receipts": receipts,
    }
    receipt_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: doc[k] for k in ("shards_run", "totals", "failed_shards")},
                     ensure_ascii=False, indent=1))
    print(f"receipt: {receipt_path}")
    return 0 if not failed_shards else 1


if __name__ == "__main__":
    raise SystemExit(main())
