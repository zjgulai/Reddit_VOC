#!/usr/bin/env python3
"""Build the release-pinned aggregate query index for @Echo SPU 问数.

Reads the *served* release (pointer → base manifest → posts/comments), pins the
release token (pointer sha + manifest sha) into the index, and produces one
SQLite file that the reply engine's query service reads online. The index is
keyed to exactly one generation: when the 07:05 pipeline advances the pointer,
a new index must be built — a query service must never serve an index whose
token no longer matches the served pointer.

Design (plan §3 D1 T6', decision C5 of the adversarial review):
- aggregate-first: the index holds binding rows, sentiment, dates and links —
  never post/comment bodies. Lexical evidence lookup goes through FTS5 over
  titles and (separately) comment bodies, returning evidence ids only; the
  reply service resolves evidence by permalink from the release datasets.
- zero-binding SPU queries must be answerable offline: family/category
  rollups live here, so "exact → family → category → unavailable" never
  requires scanning 200MB of comments.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

PUBLIC_ROOT = "https://radar.luteos.com/data/reddit-voc"
POINTER_PATH = "current-release.json"

SCHEMA = """
CREATE TABLE meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE posts (
  post_id TEXT PRIMARY KEY,
  title TEXT NOT NULL DEFAULT '',
  subreddit TEXT NOT NULL DEFAULT '',
  created_at_utc TEXT NOT NULL,
  source_calendar_date TEXT NOT NULL,
  sentiment_label TEXT,
  severity TEXT,
  topic TEXT,
  brand_binding TEXT,
  mentioned_brands TEXT NOT NULL DEFAULT '[]',
  pain_points TEXT NOT NULL DEFAULT '[]',
  linked_comment_count INTEGER NOT NULL DEFAULT 0,
  permalink TEXT NOT NULL DEFAULT ''
);
CREATE TABLE post_bindings (
  post_id TEXT NOT NULL,
  binding_level TEXT NOT NULL,
  governance_status TEXT NOT NULL,
  product_family_id TEXT,
  exact_spu_id TEXT,
  category_id TEXT,
  match_type TEXT,
  governance_reason TEXT
);
CREATE INDEX idx_bindings_family ON post_bindings(product_family_id);
CREATE INDEX idx_bindings_spu ON post_bindings(exact_spu_id);
CREATE INDEX idx_bindings_cat ON post_bindings(category_id);
CREATE INDEX idx_bindings_level ON post_bindings(binding_level);
CREATE TABLE comments (
  comment_id TEXT PRIMARY KEY,
  post_id TEXT NOT NULL,
  created_at_utc TEXT NOT NULL,
  source_calendar_date TEXT NOT NULL,
  sentiment_label TEXT,
  severity TEXT,
  topic TEXT,
  pain_points TEXT NOT NULL DEFAULT '[]',
  include_in_voc_metrics INTEGER,
  brand_binding TEXT,
  permalink TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_comments_post ON comments(post_id);
CREATE INDEX idx_comments_date ON comments(source_calendar_date);
CREATE VIRTUAL TABLE posts_fts USING fts5(post_id UNINDEXED, title, subreddit);
CREATE VIRTUAL TABLE comments_fts USING fts5(comment_id UNINDEXED, post_id UNINDEXED, body);
"""


def _fetch_json(url: str, timeout: float = 120.0):
    request = urllib.request.Request(
        url, headers={"Cache-Control": "no-cache", "Pragma": "no-cache"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _sha256_url(url: str, timeout: float = 120.0) -> str:
    request = urllib.request.Request(
        url, headers={"Cache-Control": "no-cache", "Pragma": "no-cache"}
    )
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for chunk in iter(lambda: response.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(output: Path, timeout: float = 120.0) -> dict:
    started = time.time()
    pointer = _fetch_json(f"{PUBLIC_ROOT}/{POINTER_PATH}", timeout)
    pointer_bytes = json.dumps(pointer, sort_keys=True, separators=(",", ":")).encode()
    pointer_token = hashlib.sha256(pointer_bytes).hexdigest()
    release_id = pointer["release_id"]
    freshness = pointer.get("freshness") or {}
    base = (pointer.get("datasets") or {}).get("base") or {}
    base_version = base["dataset_version"]
    manifest_sha = base["public_manifest_sha256"]

    # The index is only valid for the generation the manifest hash names; the
    # manifest itself must confirm it is the same bytes the site serves.
    served_manifest_sha = _sha256_url(f"{PUBLIC_ROOT}/{base_version}/manifest-public.json", timeout)
    if served_manifest_sha != manifest_sha:
        raise SystemExit(
            f"manifest drift: pointer binds {manifest_sha[:12]}… but the site serves {served_manifest_sha[:12]}…"
        )

    release_token = f"{pointer_token[:16]}:{manifest_sha[:16]}"

    posts = _fetch_json(f"{PUBLIC_ROOT}/{base_version}/posts-public.json", timeout)
    comments = _fetch_json(f"{PUBLIC_ROOT}/{base_version}/comments-public.json", timeout)

    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".building")
    if tmp.exists():
        tmp.unlink()
    conn = sqlite3.connect(tmp)
    conn.executescript(SCHEMA)

    conn.executemany(
        "INSERT INTO meta(key, value) VALUES (?, ?)",
        [
            ("schema_version", "echo_agent_query_index_v1"),
            ("release_id", release_id),
            ("release_token", release_token),
            ("pointer_sha256_16", pointer_token[:16]),
            ("manifest_sha256", manifest_sha),
            ("base_dataset_version", base_version),
            ("data_as_of_utc", freshness.get("data_as_of_utc") or ""),
            ("collector_run_id", freshness.get("collector_run_id") or ""),
            ("built_from", "served_release"),
        ],
    )

    post_rows = []
    binding_rows = []
    fts_rows = []
    for p in posts:
        analysis = p.get("analysis") or {}
        post_rows.append(
            (
                p["post_id"],
                p.get("title") or "",
                p.get("subreddit") or "",
                p.get("created_at_utc") or "",
                p.get("source_calendar_date") or "",
                analysis.get("sentiment_label"),
                analysis.get("severity"),
                analysis.get("topic"),
                p.get("brand_binding"),
                json.dumps(p.get("mentioned_brands") or [], ensure_ascii=False),
                json.dumps((analysis.get("pain_points") or []), ensure_ascii=False),
                int(p.get("linked_comment_count") or 0),
                p.get("permalink") or "",
            )
        )
        for b in p.get("product_bindings") or []:
            family = b.get("product_family") or {}
            category = b.get("category") or {}
            exact_spu = b.get("exact_spu") or {}
            spu_id = (
                exact_spu.get("spu_id") or exact_spu.get("id")
                if isinstance(exact_spu, dict)
                else b.get("exact_spu")
            )
            binding_rows.append(
                (
                    p["post_id"],
                    b.get("binding_level") or "",
                    b.get("governance_status") or "",
                    family.get("id") if isinstance(family, dict) else None,
                    spu_id,
                    category.get("id") if isinstance(category, dict) else None,
                    b.get("match_type"),
                    b.get("governance_reason"),
                )
            )
        fts_rows.append((p["post_id"], p.get("title") or "", p.get("subreddit") or ""))
    conn.executemany("INSERT INTO posts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", post_rows)
    conn.executemany(
        "INSERT INTO post_bindings VALUES (?,?,?,?,?,?,?,?)", binding_rows
    )
    conn.executemany("INSERT INTO posts_fts(post_id, title, subreddit) VALUES (?,?,?)", fts_rows)

    comment_rows = []
    c_fts_rows = []
    for c in comments:
        analysis = c.get("analysis") or {}
        comment_rows.append(
            (
                c["comment_id"],
                c.get("post_id") or "",
                c.get("created_at_utc") or "",
                c.get("source_calendar_date") or "",
                analysis.get("sentiment_label"),
                analysis.get("severity"),
                analysis.get("topic"),
                json.dumps((analysis.get("pain_points") or []), ensure_ascii=False),
                c.get("include_in_voc_metrics"),
                c.get("brand_binding"),
                c.get("permalink") or "",
            )
        )
        c_fts_rows.append(
            (c["comment_id"], c.get("post_id") or "", c.get("body") or "")
        )
    conn.executemany("INSERT INTO comments VALUES (?,?,?,?,?,?,?,?,?,?,?)", comment_rows)
    conn.executemany(
        "INSERT INTO comments_fts(comment_id, post_id, body) VALUES (?,?,?)", c_fts_rows
    )

    conn.commit()
    # Quick self-checks before the atomic swap.
    counts = {
        "posts": conn.execute("SELECT count(*) FROM posts").fetchone()[0],
        "comments": conn.execute("SELECT count(*) FROM comments").fetchone()[0],
        "bindings": conn.execute("SELECT count(*) FROM post_bindings").fetchone()[0],
        "spu_exact_posts": conn.execute(
            "SELECT count(DISTINCT post_id) FROM post_bindings WHERE binding_level='spu_exact'"
        ).fetchone()[0],
    }
    expected = _fetch_json(
        f"{PUBLIC_ROOT}/{base_version}/manifest-public.json", timeout
    )["canonical_counts"]
    if counts["posts"] != expected["posts"] or counts["comments"] != expected["comments_jsonl"]:
        conn.close()
        tmp.unlink()
        raise SystemExit(
            f"index counts disagree with manifest: {counts} vs {expected}"
        )
    conn.close()
    tmp.replace(output)

    return {
        "output": str(output),
        "release_id": release_id,
        "release_token": release_token,
        "data_as_of_utc": freshness.get("data_as_of_utc"),
        "counts": counts,
        "elapsed_s": round(time.time() - started, 1),
        "size_bytes": output.stat().st_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/query-index/query-index.sqlite3"),
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    receipt = build(args.output, args.timeout)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
