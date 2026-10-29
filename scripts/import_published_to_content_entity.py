#!/usr/bin/env python3
"""Import the center-only published corpus into `content_entity` (ADR-004 C2).

Closes the last containment violation: 3,609 posts / 20,609 comments exist only
in the published JSON (the July center corpus merged on 10-28) — no DB row, so
"rebuild the release from the fact store" would silently drop them. Runs on the
production host against the live public tree, idempotently.

Rules:
- Reads current-release.json -> base dataset posts/comments (the ONLY full copy).
- Upserts through reddit_voc.content_entity (lifecycle, state_hash, precision
  rules all come from the one writer). `run_id` is a synthetic import marker so
  `is_backfilled` first-acquisition semantics mark these rows as backfill.
- Day-precision records (bare-date created_at_utc) keep their precision; the CE
  writer stores them verbatim — no midnight imputation anywhere.
- Skips ids already present (re-run is a no-op); reports the delta either way.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT / "src", ROOT):
    if (candidate / "reddit_voc").is_dir():
        sys.path.insert(0, str(candidate))
        break

from reddit_voc import content_entity as ce  # noqa: E402

IMPORT_RUN_ID = "import_center_corpus_20261028"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", type=Path,
                        default=Path("/opt/echo-agent-bot/data/reddit_voc_daily.sqlite3"))
    parser.add_argument("--public-root", type=Path, default=Path("/opt/voc-report/html"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    release = json.loads(
        (args.public_root / "data/reddit-voc/current-release.json").read_text(encoding="utf-8")
    )
    dataset = args.public_root / release["datasets"]["base"]["manifest_path"]
    posts = json.loads((dataset.parent / "posts-public.json").read_text(encoding="utf-8"))
    comments = json.loads((dataset.parent / "comments-public.json").read_text(encoding="utf-8"))

    conn = sqlite3.connect(args.store, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript(ce.SCHEMA)

    known_posts = {
        r[0] for r in conn.execute("SELECT entity_id FROM content_entity WHERE entity_type='post'")
    }
    known_comments = {
        r[0] for r in conn.execute("SELECT entity_id FROM content_entity WHERE entity_type='comment'")
    }
    legacy_posts = {r[0] for r in conn.execute("SELECT post_id FROM reddit_threads")}
    legacy_comments = {r[0] for r in conn.execute("SELECT comment_id FROM reddit_comments")}

    stats = {
        "posts_in_published": len(posts),
        "comments_in_published": len(comments),
        "posts_imported": 0,
        "comments_imported": 0,
        "posts_skipped_present": 0,
        "comments_skipped_present": 0,
    }

    for p in posts:
        post_id = str(p["post_id"])
        entity_id = ce.normalise_entity_id(post_id, "post")
        if entity_id in known_posts:
            stats["posts_skipped_present"] += 1
            continue
        stats["posts_imported"] += 1
        if not args.dry_run:
            ce.upsert_post(
                conn,
                post_id=post_id,
                run_id=IMPORT_RUN_ID,
                subreddit=p.get("subreddit"),
                title=p.get("title"),
                body=p.get("content"),
                created_at_utc=p.get("created_at_utc"),
                score=p.get("score"),
                num_comments=p.get("num_comments_reported"),
                source_url=p.get("permalink"),
            )
        known_posts.add(entity_id)

    for c in comments:
        comment_id = str(c["comment_id"]).removeprefix("t1_")
        entity_id = ce.normalise_entity_id(comment_id, "comment")
        if entity_id in known_comments:
            stats["comments_skipped_present"] += 1
            continue
        stats["comments_imported"] += 1
        if not args.dry_run:
            ce.upsert_comment(
                conn,
                comment_id=comment_id,
                post_id=str(c.get("post_id") or ""),
                run_id=IMPORT_RUN_ID,
                body=c.get("body"),
                created_at_utc=c.get("created_at_utc"),
                score=c.get("score"),
                depth=c.get("depth"),
                parent_id=c.get("parent_id"),
                deleted_or_removed=bool(c.get("deleted_or_removed")),
            )
        known_comments.add(entity_id)

    stats["ce_posts_after"] = conn.execute(
        "SELECT COUNT(*) FROM content_entity WHERE entity_type='post'"
    ).fetchone()[0]
    stats["ce_comments_after"] = conn.execute(
        "SELECT COUNT(*) FROM content_entity WHERE entity_type='comment'"
    ).fetchone()[0]

    # Containment verification against BOTH sources. (Parenthesise the union —
    # `|` binds looser than `-`, and an unparenthesised mix silently computes
    # the wrong set, which is exactly what the first dry-run reported.)
    final_posts = {
        r[0] for r in conn.execute("SELECT entity_id FROM content_entity WHERE entity_type='post'")
    }
    final_comments = {
        r[0] for r in conn.execute("SELECT entity_id FROM content_entity WHERE entity_type='comment'")
    }
    bare_posts = {x[3:] if x.startswith("t3_") else x for x in final_posts}
    bare_comments = {x[3:] if x.startswith("t1_") else x for x in final_comments}
    stats["containment_posts_missing_from_ce"] = len(
        ({str(p["post_id"]) for p in posts} | legacy_posts) - bare_posts
    )
    stats["containment_comments_missing_from_ce"] = len(
        ({str(c["comment_id"]).removeprefix("t1_") for c in comments} | legacy_comments)
        - bare_comments
    )

    if not args.dry_run:
        conn.commit()
    print(json.dumps(stats, ensure_ascii=False, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
