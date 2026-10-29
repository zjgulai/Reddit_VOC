"""The unified content entity table: one schema, one writer, one identity rule.

Before this module the same table existed three times -- `migrate_content_entity.py`
(SCHEMA + INSERT_SQL), `snapshot_projection.py` (its own INSERT plus a different
conflict clause), and nowhere in `storage.py` at all. That last gap was the real
problem: no collector wrote here, so the table could only ever hold what M1
backfilled plus what was imported from the published JSON. Making the database the
source of truth (M2) is impossible while the daily collectors bypass it.

Putting the schema and the write path in one place means:

  - a collector persisting a thread/comment updates the fact table by construction,
    not by remembering to call a second API;
  - `first_seen_run_id` is never overwritten, so "when did we first see this" stays
    answerable (the legacy upsert destroys it on every run);
  - `last_changed_at_utc` only moves when `state_hash` moves, which is what makes
    "did the score change?" a single comparison instead of a full diff.

Identity: `entity_id` is always the Reddit fullname (`t3_`/`t1_`). The legacy tables
store bare ids while `parent_id` carries fullnames, and that mismatch produced the
`t1_t1_` double-prefix bug. Normalising once, here, is the fix.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from .permalink import resolve_post_permalink

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

UMBRELLA_PREFIXES = ("t1_", "t3_", "t5_")


def normalise_entity_id(raw: Any, entity_type: str) -> str:
    """Return the Reddit fullname for an id that may or may not be prefixed."""
    prefix = "t3_" if entity_type == "post" else "t1_"
    text = str(raw or "").strip()
    if not text:
        return ""
    if text.startswith(UMBRELLA_PREFIXES):
        return text
    return prefix + text


def bare_id(entity_id: Any) -> str:
    """Strip one known prefix, if present. Used when emitting the public payload."""
    text = str(entity_id or "")
    for prefix in UMBRELLA_PREFIXES:
        if text.startswith(prefix):
            return text[len(prefix):]
    return text


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


def derive_precision(created_at: Any) -> tuple[str, str | None]:
    """Return (event_precision, source_date).

    A pure date ("2026-07-01") is day-precision; anything else is instant. Precision
    is preserved rather than upgraded so downstream code cannot treat an assumed
    midnight as an observed moment.
    """
    text = str(created_at or "").strip()
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return "day", text
    return "instant", None


def compute_state_hash(fields: dict) -> str:
    """Hash the mutable state so "did anything change" is one comparison.

    Excludes timestamps that move on every fetch (`last_seen_at_utc`), otherwise every
    run would look like a change.
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


def is_backfill_run(run_id: Any) -> int:
    return 1 if str(run_id or "").startswith("backfill_") else 0


UPSERT_SQL = """
INSERT INTO content_entity (
    entity_id, entity_type, thread_id, parent_id, depth, title, body, author_hash,
    subreddit, permalink, event_at_utc, event_precision, source_date,
    first_seen_at_utc, last_seen_at_utc, last_changed_at_utc, score, num_comments,
    lifecycle, state_hash, first_seen_run_id, last_seen_run_id, raw_payload_id,
    record_authority, is_backfilled, created_at_utc, updated_at_utc
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(entity_id) DO UPDATE SET
    entity_type=excluded.entity_type,
    thread_id=COALESCE(excluded.thread_id, content_entity.thread_id),
    parent_id=COALESCE(excluded.parent_id, content_entity.parent_id),
    depth=COALESCE(excluded.depth, content_entity.depth),
    title=COALESCE(excluded.title, content_entity.title),
    body=excluded.body,
    author_hash=COALESCE(excluded.author_hash, content_entity.author_hash),
    subreddit=COALESCE(NULLIF(excluded.subreddit,''), content_entity.subreddit),
    permalink=COALESCE(NULLIF(excluded.permalink,''), content_entity.permalink),
    event_at_utc=excluded.event_at_utc,
    event_precision=excluded.event_precision,
    source_date=COALESCE(excluded.source_date, content_entity.source_date),
    -- first_seen_* are deliberately absent: they record the FIRST observation and
    -- must survive every later run. Overwriting them is what lost provenance in the
    -- legacy tables.
    last_seen_at_utc=excluded.last_seen_at_utc,
    score=excluded.score,
    num_comments=COALESCE(excluded.num_comments, content_entity.num_comments),
    lifecycle=excluded.lifecycle,
    state_hash=excluded.state_hash,
    last_seen_run_id=excluded.last_seen_run_id,
    raw_payload_id=COALESCE(excluded.raw_payload_id, content_entity.raw_payload_id),
    -- `is_backfilled` is FIRST-ACQUISITION, never updated. It answers "was this entity
    -- originally obtained by a backfill run", not "has a backfill ever touched it".
    -- Two ways to get this wrong, both of which make the marker useless:
    --   MAX(excluded, existing)       -> a realtime post later swept by a backfill
    --                                    flips to 1 forever, inflating the backfilled
    --                                    cohort with data that was never backfilled.
    --   excluded (blind overwrite)    -> a backfilled post later seen in realtime
    --                                    flips to 0, so the cohort shrinks and the
    --                                    time-series discontinuity reappears unlabelled.
    -- Leaving the column out of the conflict clause gives exactly first-acquisition
    -- semantics for free: the INSERT value stands and no later run can move it.
    updated_at_utc=excluded.updated_at_utc,
    last_changed_at_utc=CASE
        WHEN content_entity.state_hash <> excluded.state_hash
        THEN excluded.updated_at_utc
        ELSE content_entity.last_changed_at_utc
    END
"""


def _iso_or_now(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return datetime.now(timezone.utc).isoformat()
    return text


def upsert_post(
    conn: sqlite3.Connection,
    *,
    post_id: str,
    run_id: str,
    subreddit: str | None,
    title: str | None,
    body: str | None,
    created_at_utc: Any,
    score: int | None,
    num_comments: int | None,
    source_url: str | None = None,
    permalink: str | None = None,
    author_hash: str | None = None,
    raw_payload_id: str | None = None,
    record_authority: str = "governed_base",
) -> None:
    """Persist one post. Permalink is resolved against this post's own id."""
    entity_id = normalise_entity_id(post_id, "post")
    if not entity_id:
        return
    now = datetime.now(timezone.utc).isoformat()
    event_at = _iso_or_now(created_at_utc)
    precision, source_date = derive_precision(created_at_utc)
    lifecycle = derive_lifecycle(body or "", None)
    resolved_permalink, _basis = resolve_post_permalink(
        post_id=bare_id(entity_id),
        subreddit=subreddit,
        permalink=permalink,
        source_url=source_url,
    )
    conn.execute(UPSERT_SQL, (
        entity_id, "post", None, None, None,
        title, body or "", author_hash,
        subreddit, resolved_permalink,
        event_at, precision, source_date,
        now, now, None,
        score, num_comments, lifecycle,
        compute_state_hash({
            "title": title, "body": body or "", "score": score,
            "num_comments": num_comments, "lifecycle": lifecycle, "subreddit": subreddit,
        }),
        run_id, run_id, raw_payload_id,
        record_authority, is_backfill_run(run_id), now, now,
    ))


def upsert_comment(
    conn: sqlite3.Connection,
    *,
    comment_id: str,
    post_id: str,
    run_id: str,
    body: str | None,
    created_at_utc: Any,
    score: int | None = None,
    depth: int | None = None,
    parent_id: str | None = None,
    subreddit: str | None = None,
    author_hash: str | None = None,
    raw_payload_id: str | None = None,
    deleted_or_removed: bool | None = None,
    record_authority: str = "governed_base",
) -> None:
    """Persist one comment.

    `permalink` stays NULL on purpose: a comment's link is its parent post's URL, and
    storing a copy would let the two drift (1,928 published comments inherited a
    broken parent URL exactly that way). The projector resolves it at read time.
    """
    entity_id = normalise_entity_id(comment_id, "comment")
    if not entity_id:
        return
    thread_id = normalise_entity_id(post_id, "post")
    now = datetime.now(timezone.utc).isoformat()
    event_at = _iso_or_now(created_at_utc)
    precision, source_date = derive_precision(created_at_utc)
    lifecycle = derive_lifecycle(body or "", deleted_or_removed)
    conn.execute(UPSERT_SQL, (
        entity_id, "comment", thread_id,
        normalise_entity_id(parent_id, "comment") if parent_id else None,
        depth,
        None, body or "", author_hash,
        subreddit, None,
        event_at, precision, source_date,
        now, now, None,
        score, None, lifecycle,
        compute_state_hash({
            "title": None, "body": body or "", "score": score,
            "num_comments": None, "lifecycle": lifecycle, "subreddit": subreddit,
        }),
        run_id, run_id, raw_payload_id,
        record_authority, is_backfill_run(run_id), now, now,
    ))


def has_table(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='content_entity'"
    ).fetchone()
    return row is not None
