"""M2: make the database the single source of truth for the published snapshot.

Two things block the read path from moving into SQLite:

  1. `content_entity` holds content facts only. The public contract needs 24 more
     fields per record (analysis, tagging, brand_binding, coverage grades,
     eligibility flags, ...). Without a home for them the projector would have to
     re-derive them every run, which is exactly the drift that produced the
     `eufy`-tagged comments.
  2. The published snapshot contains 3,609 posts and 20,609 comments that are NOT
     in `content_entity` (overlap was only 141 posts). Those rows carry July
     governance that exists nowhere else, so they must be imported before the JSON
     can stop being read.

This module does both:

  `import_snapshot_governance()`  read the published JSON once, import any
                                  entity the DB is missing, and store the
                                  governance blob per entity
  `project_posts()/project_comments()`
                                  build the exact public payloads from the DB, so
                                  `merge_snapshot` never reads the old JSON again

Governance is stored as one JSON document per entity rather than normalised
columns. That is deliberate for M2: the goal here is to remove the JSON *read
path*, not to change the tag model. Normalising `tagging.matches` into
row-level `tag_assignment` records is M2.5 (see docs/prd/STORAGE-MODEL.md §4.3),
and doing it now would change bytes the client validates.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from reddit_voc.permalink import (  # noqa: E402
    resolve_comment_permalink,
    resolve_post_permalink,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS content_enrichment (
    entity_id       TEXT PRIMARY KEY,
    brand_binding   TEXT,
    mentioned_brands TEXT NOT NULL DEFAULT '[]',
    governance_json TEXT NOT NULL DEFAULT '{}',
    analysis_json   TEXT NOT NULL DEFAULT '{}',
    tagging_json    TEXT NOT NULL DEFAULT '{}',
    source          TEXT NOT NULL DEFAULT 'snapshot_import',
    imported_at_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ce_enrich_binding ON content_enrichment(brand_binding);
"""

# Fields that belong to content_entity, and fields that belong in the governance blob.
_CONTENT_KEYS_POST = {
    "title": "title", "content": "body", "subreddit": "subreddit",
    "permalink": "permalink", "score": "score",
}
_CONTENT_KEYS_COMMENT = {
    "body": "body", "subreddit": "subreddit", "permalink": "permalink",
    "score": "score", "depth": "depth",
}

# Everything else on a public record is governance: preserved verbatim so the
# projector can reproduce the contract byte-for-byte.
_GOVERNANCE_KEYS = (
    "author_pseudonym", "author_pseudonym_status", "comment_coverage_status",
    "count_completeness_status", "evidence_id", "event_time_precision",
    "linked_comment_count", "num_comments_reported", "permalink_basis",
    "pii_redaction_flags", "product_bindings", "schema_version",
    "source_calendar_date", "structural_coverage_grade", "title_basis",
    "upvote_ratio", "include_in_voc_metrics", "is_bot",
    "metric_eligibility_status", "parent_link_status", "deleted_or_removed",
    # `source_url` appears on the 159 pipeline-merged posts (they carry 34 keys
    # instead of the July import's 30). It must survive so the published payload
    # keeps whatever shape each record already had -- the snapshot is NOT
    # homogeneous, and the projector must not "fix" that by dropping a field the
    # client may read.
    "source_url",
    # `matched_keywords` has no column in content_entity and `run_id` was never
    # modelled there (provenance lives in first_seen/last_seen_run_id). Both appear
    # on pipeline-merged published records, so keep them in the governance passthrough
    # instead of dropping them silently.
    "matched_keywords", "run_id", "record_authority", "depth",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def _iso(value: Any) -> str:
    """Normalise to UTC ISO-8601 *without* inventing microseconds.

    The published snapshot writes `2013-04-28T07:23:57+00:00`; emitting
    `...57.000000+00:00` instead changes the bytes, and the client compares file
    SHA-256 against the manifest, so the whole dataset would be rejected.
    """
    text = str(value or "").strip()
    if not text:
        return _now()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    # Preserve whatever precision the source had: dropping microseconds shifts the
    # event time and changes the bytes the client hashes.
    if parsed.microsecond:
        return parsed.isoformat(timespec="microseconds")
    return parsed.replace(microsecond=0).isoformat(timespec="seconds")


def _state_hash(row: dict) -> str:
    payload = json.dumps(
        {
            "title": row.get("title"), "body": row.get("body"),
            "score": row.get("score"), "num_comments": row.get("num_comments"),
            "lifecycle": row.get("lifecycle"), "subreddit": row.get("subreddit"),
        },
        sort_keys=True, ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def import_snapshot_governance(
    conn: sqlite3.Connection,
    *,
    posts: list[dict],
    comments: list[dict],
    run_id: str = "snapshot_import",
) -> dict:
    """Import any entity the DB is missing, and store governance for every record.

    Idempotent: `INSERT ... ON CONFLICT DO NOTHING` for entities (the DB's own row
    wins if it already exists) and `DO UPDATE` for governance (the snapshot is the
    richer source for July-era records).
    """
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    now = _now()

    entity_sql = """
    INSERT INTO content_entity (
        entity_id, entity_type, thread_id, parent_id, depth, title, body, author_hash,
        subreddit, permalink, event_at_utc, event_precision, source_date,
        first_seen_at_utc, last_seen_at_utc, last_changed_at_utc, score, num_comments,
        lifecycle, state_hash, first_seen_run_id, last_seen_run_id, raw_payload_id,
        record_authority, is_backfilled, created_at_utc, updated_at_utc
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT(entity_id) DO UPDATE SET
        -- The snapshot is richer than the legacy tables for fields the legacy
        -- schema never had (comments carry no subreddit/permalink column). Fill
        -- only blanks so a fresher DB value is never overwritten by an older export.
        -- NULLIF first: the legacy tables store '' for "unknown", and COALESCE
        -- only skips NULL, so a blank value would win over a real one forever.
        subreddit=COALESCE(NULLIF(content_entity.subreddit,''), excluded.subreddit),
        permalink=COALESCE(NULLIF(content_entity.permalink,''), excluded.permalink),
        -- parent_id/score/depth are NULL or stale on rows the legacy tables already
        -- held (comments had no parent linkage column before), so prefer the
        -- snapshot value when the DB has nothing.
        parent_id=COALESCE(NULLIF(content_entity.parent_id,''), excluded.parent_id),
        depth=COALESCE(content_entity.depth, excluded.depth),
        event_precision=excluded.event_precision,
        source_date=COALESCE(content_entity.source_date, excluded.source_date)
    """
    enrich_sql = """
    INSERT INTO content_enrichment (
        entity_id, brand_binding, mentioned_brands, governance_json,
        analysis_json, tagging_json, source, imported_at_utc
    ) VALUES (?,?,?,?,?,?,?,?)
    ON CONFLICT(entity_id) DO UPDATE SET
        brand_binding=excluded.brand_binding,
        mentioned_brands=excluded.mentioned_brands,
        governance_json=excluded.governance_json,
        analysis_json=excluded.analysis_json,
        tagging_json=excluded.tagging_json,
        imported_at_utc=excluded.imported_at_utc
    """

    imported_entities = 0
    enriched = 0

    for record in posts:
        post_id = str(record.get("post_id") or "")
        if not post_id:
            continue
        entity_id = f"t3_{post_id}"
        event_at = _iso(record.get("event_created_at_utc") or record.get("created_at_utc"))
        precision = record.get("event_time_precision") or "instant"
        lifecycle = "alive"
        content = record.get("content") or ""
        if content.strip().lower().startswith("[removed]"):
            lifecycle = "removed"
        elif content.strip().lower().startswith("[deleted]"):
            lifecycle = "deleted"
        # The published snapshot itself carries 249 corrupt permalinks (an image URL,
        # a gallery URL, or a different post's id). Importing those verbatim would
        # bake the corruption into the source of truth, and every later projection
        # would faithfully reproduce it. Resolve identity on the way in instead.
        permalink, _permalink_basis = resolve_post_permalink(
            post_id=post_id,
            subreddit=record.get("subreddit"),
            permalink=record.get("permalink"),
            source_url=record.get("source_url"),
            recorded_basis=record.get("permalink_basis"),
        )
        row = {
            "title": record.get("title"), "body": content,
            "score": record.get("score"), "num_comments": record.get("num_comments_reported"),
            "lifecycle": lifecycle, "subreddit": record.get("subreddit"),
        }
        cur = conn.execute(entity_sql, (
            entity_id, "post", None, None, None,
            record.get("title"), content, None,
            record.get("subreddit"), permalink,
            event_at, precision, record.get("source_calendar_date"),
            event_at, event_at, None,
            record.get("score"), record.get("num_comments_reported"), lifecycle,
            _state_hash(row), run_id, run_id, None,
            record.get("record_authority") or "governed_base", 0, now, now,
        ))
        imported_entities += cur.rowcount

        governance = {k: record.get(k) for k in _GOVERNANCE_KEYS if k in record}
        # Keep the governance blob consistent with the repaired column, otherwise the
        # projector's passthrough would re-emit the broken value it just fixed.
        governance["permalink_basis"] = _permalink_basis
        conn.execute(enrich_sql, (
            entity_id,
            record.get("brand_binding"),
            json.dumps(record.get("mentioned_brands") or [], ensure_ascii=False),
            json.dumps(governance, ensure_ascii=False),
            json.dumps(record.get("analysis") or {}, ensure_ascii=False),
            json.dumps(record.get("tagging") or {}, ensure_ascii=False),
            "snapshot_import", now,
        ))
        enriched += 1

    for record in comments:
        comment_id = str(record.get("comment_id") or "")
        if not comment_id:
            continue
        entity_id = comment_id if comment_id.startswith("t1_") else f"t1_{comment_id}"
        parent_raw = str(record.get("post_id") or "")
        thread_id = parent_raw if parent_raw.startswith("t3_") else f"t3_{parent_raw}"
        event_at = _iso(record.get("event_created_at_utc") or record.get("created_at_utc"))
        precision = record.get("event_time_precision") or "instant"
        body = record.get("body") or ""
        lifecycle = "alive"
        if record.get("deleted_or_removed"):
            lifecycle = "deleted"
        elif body.strip().lower().startswith("[removed]"):
            lifecycle = "removed"
        elif body.strip().lower().startswith("[deleted]"):
            lifecycle = "deleted"
        row = {
            "title": None, "body": body, "score": record.get("score"),
            "num_comments": None, "lifecycle": lifecycle, "subreddit": record.get("subreddit"),
        }
        parent_id = record.get("parent_id")
        # Comments inherit the parent post's permalink. The parent may be imported
        # after this row (dict order is by published position, not by dependency), so
        # read it from the table rather than from this batch.
        parent_permalink = None
        if thread_id:
            parent_row = conn.execute(
                "SELECT permalink FROM content_entity WHERE entity_id=?", (thread_id,)
            ).fetchone()
            parent_permalink = parent_row[0] if parent_row else None
        permalink, _permalink_basis = resolve_comment_permalink(
            parent_permalink or record.get("permalink"),
            comment_id=entity_id.removeprefix("t1_"),
            post_id=thread_id.removeprefix("t3_"),
            current=record.get("permalink"),
        )
        cur = conn.execute(entity_sql, (
            entity_id, "comment", thread_id, parent_id, record.get("depth"),
            None, body, None,
            record.get("subreddit"), permalink,
            event_at, precision, record.get("source_calendar_date"),
            event_at, event_at, None,
            record.get("score"), None, lifecycle,
            _state_hash(row), run_id, run_id, None,
            record.get("record_authority") or "governed_base", 0, now, now,
        ))
        imported_entities += cur.rowcount

        governance = {k: record.get(k) for k in _GOVERNANCE_KEYS if k in record}
        governance["permalink_basis"] = _permalink_basis
        conn.execute(enrich_sql, (
            entity_id,
            record.get("brand_binding"),
            json.dumps(record.get("mentioned_brands") or [], ensure_ascii=False),
            json.dumps(governance, ensure_ascii=False),
            json.dumps(record.get("analysis") or {}, ensure_ascii=False),
            json.dumps(record.get("tagging") or {}, ensure_ascii=False),
            "snapshot_import", now,
        ))
        enriched += 1

    return {"entities_imported": imported_entities, "enriched": enriched}


def load_governance(conn: sqlite3.Connection) -> dict[str, dict]:
    """Load every enrichment row keyed by entity_id."""
    ensure_schema(conn)
    conn.row_factory = sqlite3.Row
    out: dict[str, dict] = {}
    for r in conn.execute("SELECT * FROM content_enrichment"):
        out[r["entity_id"]] = {
            "brand_binding": r["brand_binding"],
            "mentioned_brands": json.loads(r["mentioned_brands"] or "[]"),
            "governance": json.loads(r["governance_json"] or "{}"),
            "analysis": json.loads(r["analysis_json"] or "{}"),
            "tagging": json.loads(r["tagging_json"] or "{}"),
        }
    return out


def _public_time(event_at: str, precision: str, source_date: str | None) -> str:
    """Render a timestamp exactly as the published contract expects it.

    Day-precision content must stay a bare `YYYY-MM-DD`. Emitting midnight instead
    would fabricate an instant the source never had -- and the client's
    `assertV3EventTime` explicitly rejects day-precision rows that carry a time.
    """
    if precision == "day":
        if source_date:
            return source_date
        return str(event_at or "")[:10]
    return event_at


def _bare_subreddit(value: str | None) -> str | None:
    """Strip a leading "r/" so the client can render it itself.

    The apify collector persists Reddit's `communityName`, which already carries the
    prefix, while the published contract (and merge_normalize's own rule) stores the
    bare name. Emitting "r/r/BabyBumps" is the same class of bug as the old
    "r/r/" display issue.
    """
    if not value:
        return value
    text = str(value).strip()
    return text[2:] if text.startswith("r/") else text


def _strip_prefix(entity_id: str, prefix: str) -> str:
    return entity_id[len(prefix):] if entity_id.startswith(prefix) else entity_id


def _int_score(value: Any) -> Any:
    """Emit `score` as an integer.

    The published snapshot stores 2,172 posts and 3,624 comments' scores as `0.0`
    rather than `0` -- not a data fact, just `float(...)` residue from
    `merge_normalize`. Every value is integral, so this normalisation changes bytes
    but never meaning. It is counted separately in the parity report so it cannot be
    mistaken for a content change.
    """
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


# The exact public post field set, per
# `validate_reddit_v3_base_public_projection.POST_FIELDS`. The offline validator
# compares `set(row) == POST_FIELDS`, so BOTH a missing and an extra key reject the
# dataset. The browser client tolerates extras, which is why 159 pipeline-merged
# records have been publishing 34 keys (`include_in_voc_metrics`, `is_bot`,
# `run_id`, `source_url`) without anyone noticing.
POST_FIELDS = (
    "schema_version", "post_id", "reddit_id", "title", "title_basis", "content",
    "subreddit", "permalink", "permalink_basis", "created_at_utc",
    "event_created_at_utc", "source_calendar_date", "event_time_precision", "score",
    "upvote_ratio", "num_comments_reported", "linked_comment_count",
    "structural_coverage_grade", "count_completeness_status",
    "comment_coverage_status", "author_pseudonym", "author_pseudonym_status",
    "mentioned_brands", "brand_binding", "product_bindings", "analysis", "tagging",
    "evidence_id", "pii_redaction_flags", "record_authority",
)
COMMENT_FIELDS = (
    "schema_version", "comment_id", "reddit_id", "post_id", "parent_id",
    "parent_link_status", "body", "subreddit", "permalink", "permalink_basis",
    "created_at_utc", "event_created_at_utc", "source_calendar_date",
    "event_time_precision", "score", "depth", "deleted_or_removed", "is_bot",
    "include_in_voc_metrics", "metric_eligibility_status", "author_pseudonym",
    "author_pseudonym_status", "mentioned_brands", "brand_binding",
    "product_bindings", "analysis", "tagging", "evidence_id", "pii_redaction_flags",
    "record_authority",
)


def _contract_record(record: dict, fields: tuple[str, ...]) -> dict:
    """Drop any key outside the frozen contract, then sort.

    Governance blobs are a passthrough from two different eras (July workbook import
    and pipeline merge), so they disagree on which extra keys exist. Emitting the
    union would publish a record shape no schema describes. Projecting onto the
    contract makes every release exactly-shaped regardless of what the blob holds.
    """
    return {key: record[key] for key in sorted(record) if key in fields}


def _sorted_record(record: dict) -> dict:
    """Emit keys in the order the published snapshot already uses.

    Every published record has alphabetically sorted keys (the files were written
    with `sort_keys=True`). Returning dict insertion order would change the bytes of
    all 3,750 posts and 21,295 comments on the very first DB-generated release, which
    makes it impossible to audit the diff -- and the diff is supposed to be *only*
    the permalink repair. Sorting keeps the switch byte-stable everywhere except the
    fields it actually corrects.
    """
    return {key: record[key] for key in sorted(record)}


def project_posts(
    conn: sqlite3.Connection,
    governance: dict[str, dict] | None = None,
) -> list[dict]:
    """Build the public posts payload from the database."""
    ensure_schema(conn)
    conn.row_factory = sqlite3.Row
    gov = governance if governance is not None else load_governance(conn)

    posts: list[dict] = []
    for r in conn.execute(
        "SELECT * FROM content_entity WHERE entity_type='post' ORDER BY event_at_utc, entity_id"
    ):
        entity_id = r["entity_id"]
        g = gov.get(entity_id, {})
        extra = g.get("governance") or {}
        record = {
            "schema_version": extra.get("schema_version") or "reddit_voc_public_post_v3",
            "post_id": _strip_prefix(entity_id, "t3_"),
            "reddit_id": entity_id,
            "subreddit": _bare_subreddit(r["subreddit"]),
            "title": r["title"],
            "content": r["body"],
            "score": _int_score(r["score"]),
            "created_at_utc": _public_time(r["event_at_utc"], r["event_precision"], r["source_date"]),
            "event_created_at_utc": (
                _public_time(r["event_at_utc"], r["event_precision"], r["source_date"])
                if r["event_precision"] == "instant" else None
            ),
            "event_time_precision": r["event_precision"],
            "source_calendar_date": r["source_date"] or extra.get("source_calendar_date"),
            "permalink": r["permalink"],
            "permalink_basis": extra.get("permalink_basis") or "source_url",
            "num_comments_reported": r["num_comments"] if r["num_comments"] is not None else extra.get("num_comments_reported"),
            "mentioned_brands": g.get("mentioned_brands") or [],
            "brand_binding": g.get("brand_binding"),
            "analysis": g.get("analysis") or {},
            "tagging": g.get("tagging") or {},
            "record_authority": extra.get("record_authority") or r["record_authority"],
            "evidence_id": extra.get("evidence_id") or f"post:{_strip_prefix(entity_id, 't3_')}",
            # The five fields below are REQUIRED by the contract but are not content
            # facts, so a record whose governance blob omits them used to lose them
            # entirely (25 keys instead of 30) and reject the whole dataset. The
            # offline validator compares `set(row) == POST_FIELDS` exactly, so a
            # missing key is as fatal as a wrong value. Governance still wins when a
            # July-era record carries a real value.
            "author_pseudonym": extra.get("author_pseudonym"),
            "author_pseudonym_status": extra.get("author_pseudonym_status")
            or "suppressed_for_public_projection",
            "product_bindings": extra.get("product_bindings") or [],
            "upvote_ratio": extra.get("upvote_ratio"),
            "title_basis": extra.get("title_basis")
            or ("source_title" if (r["title"] or "").strip() else "content_unavailable"),
        }
        # Preserve any governance field we do not model explicitly.
        for key, value in extra.items():
            record.setdefault(key, value)
        # ALWAYS recompute from the facts, never from the governance blob.
        # The contract requires `linked_comment_count` to equal the number of
        # comments in comments-public.json that reference this post, and the
        # validator asserts both that identity and its sum against the array length.
        # Preferring a stored value kept 28 posts publishing a stale count from the
        # July import (sum 58,226 vs 58,296 real comments), which breaks the
        # conservation on every page that reconciles posts against comments.
        record["linked_comment_count"] = conn.execute(
            "SELECT COUNT(*) FROM content_entity WHERE entity_type='comment' AND thread_id=?",
            (entity_id,),
        ).fetchone()[0]
        posts.append(_contract_record(record, POST_FIELDS))
    return posts


def project_comments(
    conn: sqlite3.Connection,
    governance: dict[str, dict] | None = None,
) -> list[dict]:
    """Build the public comments payload from the database."""
    ensure_schema(conn)
    conn.row_factory = sqlite3.Row
    gov = governance if governance is not None else load_governance(conn)

    comments: list[dict] = []
    for r in conn.execute(
        "SELECT * FROM content_entity WHERE entity_type='comment' ORDER BY event_at_utc, entity_id"
    ):
        entity_id = r["entity_id"]
        g = gov.get(entity_id, {})
        extra = g.get("governance") or {}
        record = {
            "comment_id": entity_id,
            "reddit_id": entity_id,
            "post_id": _strip_prefix(r["thread_id"] or "", "t3_"),
            "parent_id": r["parent_id"],
            "body": r["body"],
            "score": _int_score(r["score"]),
            # The published snapshot stores depth=1 for rows whose true depth is
            # unknown, so governance wins when the DB column is NULL.
            "depth": r["depth"] if r["depth"] is not None else extra.get("depth"),
            # The published comment contract carries subreddit even though the
            # legacy reddit_comments table never had the column; the value lives in
            # governance for July-era rows and in content_entity for new ones.
            "subreddit": _bare_subreddit(r["subreddit"] or extra.get("subreddit")),
            "created_at_utc": _public_time(r["event_at_utc"], r["event_precision"], r["source_date"]),
            "event_created_at_utc": (
                _public_time(r["event_at_utc"], r["event_precision"], r["source_date"])
                if r["event_precision"] == "instant" else None
            ),
            "event_time_precision": r["event_precision"],
            "source_calendar_date": r["source_date"] or extra.get("source_calendar_date"),
            "permalink": r["permalink"],
            "permalink_basis": extra.get("permalink_basis") or "source_url",
            "deleted_or_removed": r["lifecycle"] in ("deleted", "removed"),
            "mentioned_brands": g.get("mentioned_brands") or [],
            "brand_binding": g.get("brand_binding"),
            "analysis": g.get("analysis") or {},
            "tagging": g.get("tagging") or {},
            "record_authority": extra.get("record_authority") or r["record_authority"],
            "evidence_id": extra.get("evidence_id") or f"comment:{entity_id}",
            # Required contract fields with no content-fact source. Same failure mode
            # as on posts: omitting them yields 22 keys instead of 30 and rejects the
            # dataset. `include_in_voc_metrics` stays NULL with the paired
            # eligibility status, which is the documented way to say "the governed
            # metrics layer decides this, not the base projection".
            "schema_version": extra.get("schema_version") or "reddit_voc_public_comment_v3",
            "parent_link_status": extra.get("parent_link_status") or "linked",
            "is_bot": extra.get("is_bot") if isinstance(extra.get("is_bot"), bool) else False,
            "metric_eligibility_status": extra.get("metric_eligibility_status")
            or "determined_in_governed_metrics_not_base_projection",
            "include_in_voc_metrics": extra.get("include_in_voc_metrics")
            if isinstance(extra.get("include_in_voc_metrics"), bool) else None,
            "author_pseudonym": extra.get("author_pseudonym"),
            "author_pseudonym_status": extra.get("author_pseudonym_status")
            or "suppressed_for_public_projection",
            "product_bindings": extra.get("product_bindings") or [],
        }
        for key, value in extra.items():
            record.setdefault(key, value)
        comments.append(_contract_record(record, COMMENT_FIELDS))
    return comments
