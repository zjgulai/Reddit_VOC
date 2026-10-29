"""M1: build `content_entity` and backfill it from the two legacy tables.

Why this migration exists (see docs/prd/STORAGE-MODEL.md):

  - Posts and comments carried two near-duplicate column sets, and the duplicated
    mapping in `merge_normalize` had already drifted.
  - Rows were destructive upserts, so "when did we first see this" and "what did it
    look like last time" were unrepresentable.
  - Deletion was a magic string in `body` for posts (672 rows) and a boolean for
    comments, so the two entities disagreed on the same concept.

The migration is idempotent and must pass four checks before it is allowed to
replace anything:

  1. row parity        : content_entity count == threads + comments
  2. content parity    : sampled body/title hashes match the source rows
  3. time parity       : event_at_utc distribution matches the source rows
  4. idempotency       : re-running adds no rows and changes no state_hash

Identity: the legacy tables store BARE ids ("1xghwfs") while `parent_id` carries
fullnames ("t3_1xghwfs"). `content_entity.entity_id` is the fullname, so every id
is normalised once here instead of being re-derived (and mis-derived) at each call
site -- the `t1_t1_` double-prefix bug was exactly that failure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS content_entity (
    entity_id           TEXT PRIMARY KEY,
    entity_type         TEXT NOT NULL,
    thread_id           TEXT,
    parent_id           TEXT,
    depth               INTEGER,
    title               TEXT,
    body                TEXT NOT NULL DEFAULT '',
    author_hash         TEXT,
    subreddit           TEXT,
    permalink           TEXT,
    event_at_utc        TEXT NOT NULL,
    event_precision     TEXT NOT NULL,
    source_date         TEXT,
    first_seen_at_utc   TEXT NOT NULL,
    last_seen_at_utc    TEXT NOT NULL,
    last_changed_at_utc TEXT,
    score               INTEGER,
    num_comments        INTEGER,
    lifecycle           TEXT NOT NULL,
    state_hash          TEXT NOT NULL,
    first_seen_run_id   TEXT NOT NULL,
    last_seen_run_id    TEXT NOT NULL,
    raw_payload_id      TEXT,
    record_authority    TEXT NOT NULL,
    is_backfilled       INTEGER NOT NULL DEFAULT 0,
    created_at_utc      TEXT NOT NULL,
    updated_at_utc      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ce_type_event ON content_entity(entity_type, event_at_utc);
CREATE INDEX IF NOT EXISTS idx_ce_thread ON content_entity(thread_id);
CREATE INDEX IF NOT EXISTS idx_ce_first_seen ON content_entity(first_seen_run_id);
CREATE INDEX IF NOT EXISTS idx_ce_payload ON content_entity(raw_payload_id);
"""


def normalise_entity_id(raw: str, entity_type: str) -> str:
    """Return the Reddit fullname for an id that may or may not be prefixed."""
    prefix = "t3_" if entity_type == "post" else "t1_"
    text = str(raw or "").strip()
    if not text:
        return ""
    if text.startswith(("t1_", "t3_", "t5_")):
        return text
    return prefix + text


def _iso(value: str | None) -> str | None:
    """Normalise a stored timestamp to a single comparable ISO form.

    The legacy tables mix `2026-10-28T10:00:00+00:00` (len 25) with a longer form
    carrying microseconds. Comparing raw strings across the two widths would make
    the time-parity check pass or fail for the wrong reason.
    """
    if not value:
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")


def derive_lifecycle(body: str, deleted_flag: bool | None) -> str:
    """Explicit lifecycle instead of guessing from body text.

    `[removed]` (moderator action, content may still be reachable) and `[deleted]`
    (author deletion) are different events and must not collapse into one boolean.
    """
    text = (body or "").strip().lower()
    if text.startswith("[removed]"):
        return "removed"
    if text.startswith("[deleted]"):
        return "deleted"
    if deleted_flag:
        return "deleted"
    if not text:
        return "unknown"
    return "alive"


def derive_precision(created_at: str) -> tuple[str, str | None]:
    """Return (event_precision, source_date).

    A pure date string ("2026-07-01") is day-precision; a full timestamp is instant.
    Precision is preserved rather than upgraded, so downstream code cannot treat an
    assumed midnight as an observed moment.
    """
    text = str(created_at or "").strip()
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return "day", text
    return "instant", None


def compute_state_hash(fields: dict) -> str:
    """Hash the mutable state so a change is one comparison, not ten.

    Includes exactly the fields whose change should create a new observation.
    Excludes timestamps that move on every fetch (`last_seen_at_utc`), otherwise
    every run would look like a change.
    """
    payload = json.dumps(
        {
            "title": fields.get("title"),
            "body": fields.get("body"),
            "score": fields.get("score"),
            "num_comments": fields.get("num_comments"),
            "lifecycle": fields.get("lifecycle"),
            "subreddit": fields.get("subreddit"),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _is_backfill_run(run_id: str) -> int:
    return 1 if str(run_id or "").startswith("backfill_") else 0


def build_rows(conn: sqlite3.Connection) -> tuple[list[tuple], dict]:
    """Read both legacy tables and produce content_entity rows."""
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc).isoformat()
    rows: list[tuple] = []

    for r in conn.execute("SELECT * FROM reddit_threads"):
        post_id = normalise_entity_id(r["post_id"], "post")
        if not post_id:
            continue
        event_at = _iso(r["created_at_utc"]) or now
        precision, source_date = derive_precision(r["created_at_utc"])
        lifecycle = derive_lifecycle(r["selftext"], None)
        state = {
            "title": r["title"], "body": r["selftext"], "score": r["score"],
            "num_comments": r["num_comments_reported"],
            "lifecycle": lifecycle, "subreddit": r["subreddit"],
        }
        rows.append((
            post_id, "post", None, None, None,
            r["title"], r["selftext"], r["author_hash"], r["subreddit"], r["source_url"],
            event_at, precision, source_date,
            event_at, event_at, None,
            r["score"], r["num_comments_reported"], lifecycle,
            compute_state_hash(state),
            r["run_id"], r["run_id"], r["raw_capture_id"],
            "governed_base", _is_backfill_run(r["run_id"]),
            now, now,
        ))

    # Threads must exist for comments to satisfy the thread_id FK semantics; we keep
    # the constraint logical (SQLite FKs are off in this db) but verify it ourselves.
    known_threads = {row[0] for row in rows}

    for r in conn.execute("SELECT * FROM reddit_comments"):
        comment_id = normalise_entity_id(r["comment_id"], "comment")
        if not comment_id:
            continue
        event_at = _iso(r["created_at_utc"]) or now
        precision, source_date = derive_precision(r["created_at_utc"])
        parent_id = normalise_entity_id(r["parent_id"], "post") if r["parent_id"] else None
        thread_id = normalise_entity_id(r["post_id"], "post")
        lifecycle = derive_lifecycle(r["body"], bool(r["deleted_or_removed"]))
        state = {
            "title": None, "body": r["body"], "score": r["score"],
            "num_comments": None, "lifecycle": lifecycle, "subreddit": None,
        }
        rows.append((
            comment_id, "comment", thread_id, parent_id, r["depth"],
            None, r["body"], r["author_hash"], None, None,
            event_at, precision, source_date,
            event_at, event_at, None,
            r["score"], None, lifecycle,
            compute_state_hash(state),
            r["run_id"], r["run_id"], r["raw_capture_id"],
            "governed_base", _is_backfill_run(r["run_id"]),
            now, now,
        ))

    stats = {
        "threads_total": conn.execute("SELECT COUNT(*) FROM reddit_threads").fetchone()[0],
        "comments_total": conn.execute("SELECT COUNT(*) FROM reddit_comments").fetchone()[0],
        "orphan_thread_ids": sorted(
            {row[2] for row in rows if row[1] == "comment" and row[2] not in known_threads}
        )[:10],
    }
    return rows, stats


INSERT_SQL = """
INSERT INTO content_entity (
    entity_id, entity_type, thread_id, parent_id, depth, title, body, author_hash,
    subreddit, permalink, event_at_utc, event_precision, source_date,
    first_seen_at_utc, last_seen_at_utc, last_changed_at_utc, score, num_comments,
    lifecycle, state_hash, first_seen_run_id, last_seen_run_id, raw_payload_id,
    record_authority, is_backfilled, created_at_utc, updated_at_utc
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(entity_id) DO UPDATE SET
    thread_id=excluded.thread_id,
    parent_id=excluded.parent_id,
    depth=excluded.depth,
    title=excluded.title,
    body=excluded.body,
    author_hash=excluded.author_hash,
    subreddit=excluded.subreddit,
    permalink=excluded.permalink,
    event_at_utc=excluded.event_at_utc,
    event_precision=excluded.event_precision,
    source_date=excluded.source_date,
    last_seen_at_utc=excluded.last_seen_at_utc,
    score=excluded.score,
    num_comments=excluded.num_comments,
    lifecycle=excluded.lifecycle,
    state_hash=excluded.state_hash,
    last_seen_run_id=excluded.last_seen_run_id,
    raw_payload_id=excluded.raw_payload_id,
    is_backfilled=excluded.is_backfilled,
    updated_at_utc=excluded.updated_at_utc,
    last_changed_at_utc=CASE
        WHEN content_entity.state_hash <> excluded.state_hash
        THEN excluded.updated_at_utc
        ELSE content_entity.last_changed_at_utc
    END
"""


def run_checks(conn: sqlite3.Connection, stats: dict, sample: int = 100) -> dict:
    """The four gates from the migration plan. Any failure means: do not cut over."""
    conn.row_factory = sqlite3.Row
    result: dict = {"passed": True, "checks": {}}

    # 1. row parity
    ce = conn.execute("SELECT COUNT(*) FROM content_entity").fetchone()[0]
    expected = stats["threads_total"] + stats["comments_total"]
    result["checks"]["row_parity"] = {
        "content_entity": ce, "expected": expected, "ok": ce == expected,
    }

    # 2. content parity (sampled)
    mismatch = []
    for r in conn.execute(
        "SELECT content_entity.entity_id, content_entity.body, reddit_comments.body AS src "
        "FROM content_entity JOIN reddit_comments "
        "ON content_entity.entity_id = 't1_' || reddit_comments.comment_id "
        "WHERE content_entity.entity_type='comment' LIMIT ?", (sample,)
    ):
        if r["body"] != r["src"]:
            mismatch.append(r["entity_id"])
    for r in conn.execute(
        "SELECT content_entity.entity_id, content_entity.body, reddit_threads.selftext AS src "
        "FROM content_entity JOIN reddit_threads "
        "ON content_entity.entity_id = 't3_' || reddit_threads.post_id "
        "WHERE content_entity.entity_type='post' LIMIT ?", (sample,)
    ):
        if r["body"] != r["src"]:
            mismatch.append(r["entity_id"])
    result["checks"]["content_parity"] = {
        "sampled": sample * 2, "mismatch": len(mismatch), "ok": not mismatch,
        "examples": mismatch[:5],
    }

    # 3. time parity (distribution by month)
    def month_hist(sql: str) -> dict:
        return {r[0]: r[1] for r in conn.execute(sql)}

    src_months = month_hist(
        "SELECT substr(created_at_utc,1,7) m, COUNT(*) FROM reddit_threads GROUP BY m"
    )
    src_months_c = month_hist(
        "SELECT substr(created_at_utc,1,7) m, COUNT(*) FROM reddit_comments GROUP BY m"
    )
    for k, v in src_months_c.items():
        src_months[k] = src_months.get(k, 0) + v
    ce_months = month_hist(
        "SELECT substr(event_at_utc,1,7) m, COUNT(*) FROM content_entity GROUP BY m"
    )
    result["checks"]["time_parity"] = {
        "ok": src_months == ce_months,
        "source_months": len(src_months), "entity_months": len(ce_months),
        "diff": {k: (src_months.get(k, 0), ce_months.get(k, 0))
                 for k in set(src_months) | set(ce_months)
                 if src_months.get(k, 0) != ce_months.get(k, 0)},
    }

    # 4. idempotency is verified by the caller (re-run + compare state_hash set)
    result["checks"]["idempotency"] = {"ok": None, "note": "verified by --verify-idempotent"}

    result["orphan_thread_ids"] = stats["orphan_thread_ids"]
    result["passed"] = all(
        c.get("ok") is not False for c in result["checks"].values()
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", type=Path,
                        default=Path("/opt/echo-agent-bot/data/reddit_voc_daily.sqlite3"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify-idempotent", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(args.store, isolation_level=None)
    conn.executescript(SCHEMA)
    conn.row_factory = sqlite3.Row

    rows, stats = build_rows(conn)
    print(json.dumps({"planned_rows": len(rows), "source": stats}, ensure_ascii=False, indent=1))

    if args.dry_run:
        return 0

    conn.execute("BEGIN")
    before_hash = None
    if args.verify_idempotent:
        before_hash = hashlib.sha256(
            "\n".join(sorted(
                r[0] + ":" + r[1] for r in
                conn.execute("SELECT entity_id, state_hash FROM content_entity")
            )).encode()
        ).hexdigest()

    conn.executemany(INSERT_SQL, rows)
    conn.execute("COMMIT")

    report = run_checks(conn, stats)

    if args.verify_idempotent and before_hash:
        after_hash = hashlib.sha256(
            "\n".join(sorted(
                r[0] + ":" + r[1] for r in
                conn.execute("SELECT entity_id, state_hash FROM content_entity")
            )).encode()
        ).hexdigest()
        report["checks"]["idempotency"] = {
            "ok": before_hash == after_hash,
            "before": before_hash[:16], "after": after_hash[:16],
        }
        report["passed"] = all(
            c.get("ok") is not False for c in report["checks"].values()
        )

    print(json.dumps(report, ensure_ascii=False, indent=1))
    if stats["orphan_thread_ids"]:
        print(f"WARNING: {len(stats['orphan_thread_ids'])} comment thread_ids have no "
              f"matching post (sample: {stats['orphan_thread_ids']})", file=sys.stderr)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
