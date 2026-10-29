"""Bring `content_entity` up to date with the legacy tables.

`content_entity` is the fact table the publish path reads. It was populated once by
M1 from `reddit_threads` / `reddit_comments`, and that snapshot was taken *before*
the last two archive weeks finished collecting:

    run                            threads   in content_entity
    backfill_20260928_20261004        1431        0
    backfill_20260921_20260927        1411        0
    (the eight earlier weeks)         9434     9434

So 2,842 posts and 10,564 comments exist in the legacy tables and are invisible to
any projection built on `content_entity`. The dual-write added to
`VocStore.upsert_thread/upsert_comment` only covers runs that happen after it landed;
it cannot backfill history. This script closes that gap.

It is a sync, not a migration: it reads the legacy tables, upserts through
`content_entity.upsert_post/upsert_comment` (so lifecycle, precision, permalink
identity and `state_hash` all come from one rule), and reports what it moved.

`is_backfilled` keeps first-acquisition semantics because `run_id` is passed through
from the legacy row: a post whose `run_id` starts with `backfill_` is marked 1, and
the upsert never lets a later run move that flag. Re-running is a no-op.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Two layouts must both work — hardcoding either breaks the other:
#   repo  : <repo>/src/reddit_voc/...
#   deploy: /opt/echo-agent-bot/reddit_voc/...   (no src/ directory)
for candidate in (ROOT / "src", ROOT):
    if (candidate / "reddit_voc").is_dir():
        sys.path.insert(0, str(candidate))
        break

from reddit_voc import content_entity as ce  # noqa: E402


def _existing_ids(conn: sqlite3.Connection, entity_type: str) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            "SELECT entity_id FROM content_entity WHERE entity_type=?", (entity_type,)
        )
    }


def sync(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = False,
    run_filter: str | None = None,
) -> dict:
    conn.row_factory = sqlite3.Row
    conn.executescript(ce.SCHEMA)

    known_posts = _existing_ids(conn, "post")
    known_comments = _existing_ids(conn, "comment")

    stats = {
        "posts_in_legacy": 0, "posts_missing": 0, "posts_written": 0,
        "comments_in_legacy": 0, "comments_missing": 0, "comments_written": 0,
        "by_run": {},
    }

    thread_sql = "SELECT * FROM reddit_threads"
    params: tuple = ()
    if run_filter:
        thread_sql += " WHERE run_id = ?"
        params = (run_filter,)

    for row in conn.execute(thread_sql, params):
        stats["posts_in_legacy"] += 1
        entity_id = ce.normalise_entity_id(row["post_id"], "post")
        if not entity_id:
            continue
        run_id = row["run_id"]
        bucket = stats["by_run"].setdefault(run_id, {"posts": 0, "comments": 0})
        if entity_id in known_posts:
            continue
        stats["posts_missing"] += 1
        bucket["posts"] += 1
        stats["posts_written"] += 1
        if not dry_run:
            ce.upsert_post(
                conn,
                post_id=row["post_id"],
                run_id=run_id,
                subreddit=row["subreddit"],
                title=row["title"],
                body=row["selftext"],
                created_at_utc=row["created_at_utc"],
                score=row["score"],
                num_comments=row["num_comments_reported"],
                source_url=row["source_url"],
                author_hash=row["author_hash"],
                raw_payload_id=row["raw_capture_id"],
            )
        known_posts.add(entity_id)

    comment_sql = "SELECT * FROM reddit_comments"
    params = ()
    if run_filter:
        comment_sql += " WHERE run_id = ?"
        params = (run_filter,)

    for row in conn.execute(comment_sql, params):
        stats["comments_in_legacy"] += 1
        entity_id = ce.normalise_entity_id(row["comment_id"], "comment")
        if not entity_id:
            continue
        run_id = row["run_id"]
        bucket = stats["by_run"].setdefault(run_id, {"posts": 0, "comments": 0})
        if entity_id in known_comments:
            continue
        stats["comments_missing"] += 1
        bucket["comments"] += 1
        stats["comments_written"] += 1
        if not dry_run:
            ce.upsert_comment(
                conn,
                comment_id=row["comment_id"],
                post_id=row["post_id"],
                run_id=run_id,
                body=row["body"],
                created_at_utc=row["created_at_utc"],
                score=row["score"],
                depth=row["depth"],
                parent_id=row["parent_id"],
                author_hash=row["author_hash"],
                raw_payload_id=row["raw_capture_id"],
                deleted_or_removed=bool(row["deleted_or_removed"]),
            )
        known_comments.add(entity_id)

    stats["posts_in_content_entity"] = conn.execute(
        "SELECT COUNT(*) FROM content_entity WHERE entity_type='post'"
    ).fetchone()[0]
    stats["comments_in_content_entity"] = conn.execute(
        "SELECT COUNT(*) FROM content_entity WHERE entity_type='comment'"
    ).fetchone()[0]
    stats["by_run"] = {
        k: v for k, v in stats["by_run"].items() if v["posts"] or v["comments"]
    }
    return stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", type=Path,
                        default=Path("/opt/echo-agent-bot/data/reddit_voc_daily.sqlite3"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--run-id", default=None,
                        help="limit to one legacy run_id")
    parser.add_argument("--receipt", type=Path, default=None)
    args = parser.parse_args()

    conn = sqlite3.connect(args.store, isolation_level=None)
    stats = sync(conn, dry_run=args.dry_run, run_filter=args.run_id)
    conn.commit()

    payload = {
        "status": "dry_run" if args.dry_run else "ok",
        "store": str(args.store),
        **stats,
    }
    printed = json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True)
    print(printed)
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(printed + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
