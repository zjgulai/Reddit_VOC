"""Online query service for @Echo SPU 问数, backed by the release-pinned index.

Reads outputs/query-index/query-index.sqlite3 (built by
scripts/build_query_index.py from the *served* release) and answers
entity-scoped aggregate questions with the degradation chain the PMO
acceptance language requires:

    exact SPU → product family → category → unavailable

Every answer carries its provenance: the release token, data_as_of, the
coverage denominator, and the binding level actually used. The service never
scans posts/comments bodies (the index holds aggregates and evidence ids
only) and never fabricates a number the index does not contain.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_INDEX = Path("outputs/query-index/query-index.sqlite3")

# Lexical aliases accepted for family/spu entity resolution. The index's
# family ids are the governed ones (m5-smart, m9-mobile-flow, …); users say
# "M5", "M9", "V2 Pro". Exact-SPU mentions map to the ledger's SPU ids.
FAMILY_ALIASES: dict[str, str] = {
    "m5": "m5-smart",
    "m5 smart": "m5-smart",
    "m5smart": "m5-smart",
    "m9": "m9-mobile-flow",
    "m6": "m6-mobile-style",
    "s12": "s12-pro-quick",
    "s12 pro": "s12-pro-quick",
    "v1": "v1-pro",
    "v1 pro": "v1-pro",
    "v2": "v2-pro",
    "v2 pro": "v2-pro",
    "s9": "s9-pro",
    "s9 pro": "s9-pro",
    "air1": "air-1",
    "air 1": "air-1",
}

SPU_ALIASES: dict[str, str] = {
    "SPU000168": "SPU000168",
    "SPU000167": "SPU000167",
    "SPU000209": "SPU000209",
    "SPU000932": "SPU000932",
    "SPU000714": "SPU000714",
}


class QueryIndexError(RuntimeError):
    pass


@dataclass
class QueryAnswer:
    entity: str
    level: str  # spu_exact | product_family | unavailable
    family_id: str | None
    spu_id: str | None
    data_as_of_utc: str
    release_token: str
    posts: int
    vocs: int
    negative: int
    top_pain_points: list[tuple[str, int]]
    evidence: list[dict[str, str]]
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity,
            "level": self.level,
            "family_id": self.family_id,
            "spu_id": self.spu_id,
            "data_as_of_utc": self.data_as_of_utc,
            "release_token": self.release_token,
            "coverage": {"posts": self.posts, "vocs": self.vocs, "negative": self.negative},
            "top_pain_points": self.top_pain_points,
            "evidence": self.evidence,
            "note": self.note,
        }


def _meta(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    if not row:
        raise QueryIndexError(f"meta key missing: {key}")
    return row[0]


def _resolve_entity(query: str) -> tuple[str | None, str | None]:
    """Return (spu_id, family_id) the query names, or (None, None)."""
    q = query.lower()
    # An explicit ledger-format SPU id is recognized even when unknown: the
    # correct degradation is "named entity, zero bindings", not "no entity".
    explicit = re.search(r"(?i)\bspu\d{6}\b", query)
    if explicit:
        # Ledger-format SPU, known or not — degradation handles both.
        return explicit.group(0).upper(), None
    for token, spu in SPU_ALIASES.items():
        if token.lower() in q:
            return spu, None
    # Longest alias first so "m5 smart" wins over "m5".
    for alias in sorted(FAMILY_ALIASES, key=len, reverse=True):
        if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", q):
            return None, FAMILY_ALIASES[alias]
    return None, None


def query_entity(query: str, index_path: Path = DEFAULT_INDEX) -> QueryAnswer:
    """Answer an entity-scoped VOC question with explicit degradation."""
    conn = sqlite3.connect(f"file:{index_path}?mode=ro", uri=True)
    try:
        data_as_of = _meta(conn, "data_as_of_utc")
        release_token = _meta(conn, "release_token")

        spu_id, family_id = _resolve_entity(query)
        if spu_id:
            rows = conn.execute(
                """SELECT count(DISTINCT post_id) FROM post_bindings
                   WHERE binding_level='spu_exact' AND exact_spu_id=?""",
                (spu_id,),
            ).fetchone()[0]
            if rows:
                return _rollup(conn, query, "spu_exact", None, spu_id, data_as_of, release_token)
            family = conn.execute(
                "SELECT product_family_id FROM post_bindings WHERE exact_spu_id=? LIMIT 1",
                (spu_id,),
            ).fetchone()
            if family:
                return _rollup(conn, query, "product_family", family[0], spu_id, data_as_of, release_token,
                               note="该 SPU 无精确绑定，以下为所属产品家族的证据")
            return _unavailable(conn, query, spu_id, data_as_of, release_token)

        if family_id:
            rows = conn.execute(
                "SELECT count(DISTINCT post_id) FROM post_bindings WHERE product_family_id=?",
                (family_id,),
            ).fetchone()[0]
            if not rows:
                return _unavailable(conn, query, None, data_as_of, release_token)
            # Escalate: a family whose bindings are fully covered by one exact
            # SPU answers at spu_exact level (that SPU *is* the family here).
            exact_posts = conn.execute(
                """SELECT count(DISTINCT post_id) FROM post_bindings
                   WHERE product_family_id=? AND binding_level='spu_exact'""",
                (family_id,),
            ).fetchone()[0]
            level = "spu_exact" if exact_posts == rows else "product_family"
            spu = (
                conn.execute(
                    "SELECT DISTINCT exact_spu_id FROM post_bindings WHERE product_family_id=? AND exact_spu_id IS NOT NULL",
                    (family_id,),
                ).fetchone()[0]
                if level == "spu_exact"
                else None
            )
            return _rollup(conn, query, level, family_id, spu, data_as_of, release_token)

        return _unavailable(conn, query, None, data_as_of, release_token,
                            note="问题中未识别到产品实体；仅支持已知 SPU/产品家族查询")
    finally:
        conn.close()


def _rollup(
    conn: sqlite3.Connection,
    entity: str,
    level: str,
    family_id: str | None,
    spu_id: str | None,
    data_as_of: str,
    release_token: str,
    note: str = "",
) -> QueryAnswer:
    if spu_id and level == "spu_exact":
        where, params = "pb.binding_level='spu_exact' AND pb.exact_spu_id=?", (spu_id,)
    else:
        where, params = "pb.product_family_id=?", (family_id,)
    stats = conn.execute(
        f"""SELECT count(DISTINCT pb.post_id),
                   count(c.comment_id),
                   sum(CASE WHEN c.sentiment_label='negative' THEN 1 ELSE 0 END)
            FROM post_bindings pb
            LEFT JOIN comments c ON c.post_id = pb.post_id
            WHERE {where}""",
        params,
    ).fetchone()
    posts, vocs, negative = stats[0], stats[1] or 0, stats[2] or 0

    pain_rows = conn.execute(
        f"""SELECT c.pain_points, count(*) FROM comments c
            JOIN post_bindings pb ON pb.post_id = c.post_id
            WHERE {where} AND c.sentiment_label='negative'
            GROUP BY c.pain_points""",
        params,
    ).fetchall()
    counter: dict[str, int] = {}
    for payload, _count in pain_rows:
        for tag in json.loads(payload or "[]"):
            counter[tag] = counter.get(tag, 0) + 1
    top_pain = sorted(counter.items(), key=lambda kv: -kv[1])[:5]

    evidence_rows = conn.execute(
        f"""SELECT c.comment_id, c.post_id, c.created_at_utc, c.permalink
            FROM comments c JOIN post_bindings pb ON pb.post_id = c.post_id
            WHERE {where} AND c.sentiment_label='negative'
            ORDER BY c.created_at_utc DESC LIMIT 3""",
        params,
    ).fetchall()
    evidence = [
        {"comment_id": r[0], "post_id": r[1], "created_at_utc": r[2], "permalink": r[3]}
        for r in evidence_rows
    ]

    return QueryAnswer(
        entity=entity, level=level, family_id=family_id, spu_id=spu_id,
        data_as_of_utc=data_as_of, release_token=release_token,
        posts=posts, vocs=vocs, negative=negative,
        top_pain_points=top_pain, evidence=evidence, note=note,
    )


def _unavailable(
    conn: sqlite3.Connection,
    entity: str,
    spu_id: str | None,
    data_as_of: str,
    release_token: str,
    note: str = "语料中无该实体的 product_binding 记录",
) -> QueryAnswer:
    known_families = [
        r[0] for r in conn.execute(
            "SELECT DISTINCT product_family_id FROM post_bindings WHERE product_family_id IS NOT NULL ORDER BY 1"
        )
    ]
    return QueryAnswer(
        entity=entity, level="unavailable", family_id=None, spu_id=spu_id,
        data_as_of_utc=data_as_of, release_token=release_token,
        posts=0, vocs=0, negative=0, top_pain_points=[], evidence=[],
        note=f"{note}。已知可查询实体：{', '.join(known_families[:12])}（产品家族）",
    )
