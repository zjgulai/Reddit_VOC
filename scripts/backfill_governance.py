"""Materialise public governance onto content that has none.

10,877 posts collected by the weekly archive backfill carry real content but no
`brand_binding`, no `analysis` and no `tagging`. `snapshot_projection` can only emit
those fields when a `content_enrichment` row exists, so projecting today produces
records with `analysis: {}` and `tagging: {}` -- and the client rejects the whole
dataset on the first such record, because `analysis.provider_call` must be exactly
`false` and `tagging.semantic_validation_status` must be exactly `'not_run'`.

Two rules govern this script, and both are load-bearing:

  **Reuse, do not reinvent.** The values come from `v3_base_public._analysis`,
  `_tagging`, `_derived_mentions`, `_brand_binding` and `_sanitize_text` -- the one
  producer that emits the complete 30-field contract, and the rule that produced the
  3,591 governed posts these rows will join. Writing a second rule set here is how
  the cohorts would end up speaking different dialects: the incremental pipeline's
  own brand chain matches six hardcoded names by lowercase substring, so it can never
  emit `multi_brand_context` and misses 55 registered competitors. Every
  Momcozy-plus-competitor post would be counted as a governed Momcozy VOC and inflate
  the denominator -- exactly the silent jump this whole exercise is about.

  **Materialise once, pin the versions.** Deriving on every publish means the
  governance silently changes when the analyzer or the dictionary changes, and no two
  releases are comparable. The receipt records the analyzer version, the dictionary
  version and SHA-256, and a content digest, so a later run can prove it either
  reproduced the same values or was told to recompute.

Scope is `is_backfilled = 1` posts and the comments belonging to them. Rows that
already carry governance are never touched: the July corpus's governed values are the
only copy in existence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from reddit_voc import content_entity as ce  # noqa: E402
from reddit_voc.permalink import resolve_post_permalink  # noqa: E402
from reddit_voc.tag_dictionary import TagDictionary  # noqa: E402
from reddit_voc.v3_base_public import (  # noqa: E402
    _analysis,
    _brand_binding,
    _derived_mentions,
    _sanitize_text,
    _tagging,
)

ANALYZER_VERSION = "local_rules_v1"
RULE_VERSION = "backfill_governance_v1"

ENRICH_SCHEMA = """
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

# PROVENANCE COLUMN.
# `governance_json` is a passthrough into the PUBLIC payload, and the offline
# validator requires `set(row) == POST_FIELDS` exactly (30 keys, no extras). Writing
# rule_version / dictionary_sha256 / content_sha256 into it leaked 6 extra keys onto
# every backfilled record (31 instead of 30) and would have rejected the whole
# dataset. Provenance therefore lives in its own column, which the projector never
# reads, and is compared on re-run to decide whether to skip a row.
PROVENANCE_COLUMN = "provenance_json"


def ensure_enrichment_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(ENRICH_SCHEMA)
    existing = {row[1] for row in conn.execute("PRAGMA table_info(content_enrichment)")}
    if PROVENANCE_COLUMN not in existing:
        conn.execute(
            f"ALTER TABLE content_enrichment ADD COLUMN {PROVENANCE_COLUMN} "
            "TEXT NOT NULL DEFAULT '{}'"
        )

# Coverage grades this corpus can honestly claim. The archive channel reports how
# many comments it returned, but it does not page a thread to exhaustion, so
# "full" is not provable from what we hold. `source_observed` says exactly what
# happened: these rows are what the source returned, with no completeness claim.
GRADE_SOURCE_OBSERVED = "source_observed"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_dictionary_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    for candidate in (
        ROOT / "dim_tag_v6.3_final.csv",
        ROOT / "config" / "dim_tag_v6.3_final.csv",
    ):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("dim_tag_v6.3_final.csv not found; pass --dictionary")


def _library_version_matches(recorded: str | None) -> bool:
    """True when a stored governance blob was produced by the current rule set."""
    return recorded == RULE_VERSION


def build_post_governance(
    *,
    post_id: str,
    body: str,
    title: str,
    subreddit: str | None,
    current_permalink: str | None,
    dictionary: TagDictionary,
) -> dict[str, Any]:
    """The single rule for a post with no prior governance.

    Field order mirrors `v3_base_public._project_post` so a reader can diff the two
    side by side. `content` is sanitised before analysis and tagging -- analysing raw
    text would let a redacted email token leak into a match.
    """
    content, content_flags = _sanitize_text(body)
    clean_title, title_flags = _sanitize_text(title)
    mentions = _derived_mentions(content)
    permalink, permalink_basis = resolve_post_permalink(
        post_id=post_id, subreddit=subreddit, permalink=current_permalink
    )
    return {
        "content": content,
        "title": clean_title,
        "title_basis": "source_title" if clean_title.strip() else "content_unavailable",
        "pii_redaction_flags": sorted(set(content_flags) | set(title_flags)),
        "permalink": permalink,
        "permalink_basis": permalink_basis,
        "mentioned_brands": mentions,
        "brand_binding": _brand_binding(mentions),
        "analysis": _analysis(content, None),
        "tagging": _tagging(content, None, dictionary),
        "structural_coverage_grade": GRADE_SOURCE_OBSERVED,
        "count_completeness_status": "source_rows_only",
        "comment_coverage_status": "source_rows_only",
    }


def build_comment_governance(*, body: str, dictionary: TagDictionary) -> dict[str, Any]:
    content, flags = _sanitize_text(body)
    mentions = _derived_mentions(content)
    return {
        "body": content,
        "pii_redaction_flags": sorted(set(flags)),
        "mentioned_brands": mentions,
        "brand_binding": _brand_binding(mentions),
        "analysis": _analysis(content, None),
        "tagging": _tagging(content, None, dictionary),
    }


def _digest(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def materialise(
    conn: sqlite3.Connection,
    *,
    dictionary: TagDictionary,
    dictionary_sha256: str,
    recompute: bool = False,
    dry_run: bool = False,
) -> dict:
    """Write governance for every backfilled entity that lacks it.

    Idempotent by construction: a row whose stored `rule_version` matches and whose
    content digest is unchanged is skipped, so re-running cannot shift values.
    """
    conn.row_factory = sqlite3.Row
    ensure_enrichment_schema(conn)
    now = _now()

    existing = {
        r["entity_id"]: dict(r)
        for r in conn.execute(
            f"SELECT entity_id, governance_json, analysis_json, tagging_json,"
            f" brand_binding, source, {PROVENANCE_COLUMN} FROM content_enrichment"
        )
    }

    stats = {
        "posts_seen": 0, "posts_written": 0, "posts_skipped_has_governance": 0,
        "posts_skipped_unchanged": 0,
        "comments_seen": 0, "comments_written": 0,
        "comments_skipped_has_governance": 0, "comments_skipped_unchanged": 0,
        "posts_hidden": 0, "comments_hidden": 0,
    }
    repair: list[dict] = []

    upsert = f"""
    INSERT INTO content_enrichment (
        entity_id, brand_binding, mentioned_brands, governance_json,
        analysis_json, tagging_json, source, imported_at_utc, {PROVENANCE_COLUMN}
    ) VALUES (?,?,?,?,?,?,?,?,?)
    ON CONFLICT(entity_id) DO UPDATE SET
        brand_binding=excluded.brand_binding,
        mentioned_brands=excluded.mentioned_brands,
        governance_json=excluded.governance_json,
        analysis_json=excluded.analysis_json,
        tagging_json=excluded.tagging_json,
        source=excluded.source,
        imported_at_utc=excluded.imported_at_utc,
        {PROVENANCE_COLUMN}=excluded.{PROVENANCE_COLUMN}
    """

    def _provenance(content_digest: str) -> str:
        """Metadata that must NEVER reach the public payload."""
        return json.dumps({
            "rule_version": RULE_VERSION,
            "analyzer_version": ANALYZER_VERSION,
            "dictionary_version": dictionary.version,
            "dictionary_sha256": dictionary_sha256,
            "content_sha256": content_digest,
            "materialised_at_utc": now,
        }, ensure_ascii=False, sort_keys=True)

    def _prior_provenance(prior: dict | None) -> dict:
        if not prior:
            return {}
        try:
            return json.loads(prior.get(PROVENANCE_COLUMN) or "{}")
        except (ValueError, TypeError):
            return {}

    # Only entities the backfill acquired. `is_backfilled` is first-acquisition
    # semantics, so this set never grows just because a backfill swept a row.
    backfilled_posts = [
        r for r in conn.execute(
            "SELECT entity_id, title, body, subreddit, permalink, event_at_utc,"
            " event_precision, source_date FROM content_entity"
            " WHERE entity_type='post' AND is_backfilled=1"
        )
    ]
    for row in backfilled_posts:
        stats["posts_seen"] += 1
        entity_id = row["entity_id"]
        prior = existing.get(entity_id)
        prior_prov = _prior_provenance(prior)
        if prior and not recompute and _library_version_matches(prior_prov.get("rule_version")):
            stats["posts_skipped_has_governance"] += 1
            continue

        post_id = ce.bare_id(entity_id)
        subreddit = row["subreddit"]

        gov = build_post_governance(
            post_id=post_id, body=row["body"] or "", title=row["title"] or "",
            subreddit=subreddit, current_permalink=row["permalink"],
            dictionary=dictionary,
        )
        # Publishability gate: without a usable subreddit no canonical permalink can
        # be built, and the client rejects a post whose permalink is not a Reddit URL.
        if not gov["permalink"]:
            stats["posts_hidden"] += 1
            repair.append({
                "entity_id": entity_id, "reason": "no_publishable_permalink",
                "subreddit": subreddit,
            })
            continue
        digest = _digest({
            "title": gov["title"], "content": gov["content"],
            "brand_binding": gov["brand_binding"],
        })
        if prior and prior_prov.get("content_sha256") == digest and not recompute:
            stats["posts_skipped_unchanged"] += 1
            continue

        stats["posts_written"] += 1
        if not dry_run:
            conn.execute(upsert, (
                entity_id, gov["brand_binding"],
                json.dumps(gov["mentioned_brands"], ensure_ascii=False),
                json.dumps(gov, ensure_ascii=False),
                json.dumps(gov["analysis"], ensure_ascii=False),
                json.dumps(gov["tagging"], ensure_ascii=False),
                RULE_VERSION, now, _provenance(digest),
            ))

    backfilled_threads = {r[0] for r in conn.execute(
        "SELECT entity_id FROM content_entity WHERE entity_type='post' AND is_backfilled=1"
    )}
    for row in conn.execute(
        "SELECT entity_id, thread_id, body FROM content_entity WHERE entity_type='comment'"
    ):
        if row["thread_id"] not in backfilled_threads:
            continue
        stats["comments_seen"] += 1
        entity_id = row["entity_id"]
        prior = existing.get(entity_id)
        prior_prov = _prior_provenance(prior)
        if prior and not recompute and _library_version_matches(prior_prov.get("rule_version")):
            stats["comments_skipped_has_governance"] += 1
            continue

        gov = build_comment_governance(body=row["body"] or "", dictionary=dictionary)
        digest = _digest({"body": gov["body"], "brand_binding": gov["brand_binding"]})
        if prior and prior_prov.get("content_sha256") == digest and not recompute:
            stats["comments_skipped_unchanged"] += 1
            continue

        stats["comments_written"] += 1
        if not dry_run:
            conn.execute(upsert, (
                entity_id, gov["brand_binding"],
                json.dumps(gov["mentioned_brands"], ensure_ascii=False),
                json.dumps(gov, ensure_ascii=False),
                json.dumps(gov["analysis"], ensure_ascii=False),
                json.dumps(gov["tagging"], ensure_ascii=False),
                RULE_VERSION, now, _provenance(digest),
            ))

    stats["repair_ledger"] = repair[:50]
    stats["repair_ledger_size"] = len(repair)
    stats["dictionary_version"] = dictionary.version
    stats["dictionary_sha256"] = dictionary_sha256
    stats["rule_version"] = RULE_VERSION
    return stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", type=Path,
                        default=Path("/opt/echo-agent-bot/data/reddit_voc_daily.sqlite3"))
    parser.add_argument("--dictionary", type=str, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--recompute", action="store_true",
                        help="recompute even when stored rule version matches")
    parser.add_argument("--receipt", type=Path, default=None)
    args = parser.parse_args()

    dictionary_path = _resolve_dictionary_path(args.dictionary)
    dictionary_sha256 = hashlib.sha256(dictionary_path.read_bytes()).hexdigest()
    dictionary = TagDictionary.from_csv(dictionary_path)

    conn = sqlite3.connect(args.store, isolation_level=None)
    conn.executescript(ENRICH_SCHEMA)
    stats = materialise(
        conn, dictionary=dictionary, dictionary_sha256=dictionary_sha256,
        recompute=args.recompute, dry_run=args.dry_run,
    )
    conn.commit()

    payload = {
        "status": "dry_run" if args.dry_run else "ok",
        "store": str(args.store),
        "dictionary_path": str(dictionary_path),
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
