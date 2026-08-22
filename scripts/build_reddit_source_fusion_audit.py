#!/usr/bin/env python3
"""Build a privacy-safe, reproducible audit for the Reddit corpus sources."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable

from reddit_voc.adapters import BrowserJsonAdapter


SCHEMA_VERSION = "reddit_voc_source_fusion_audit_v1"
BRAND_ALIASES = {
    "Momcozy": ("momcozy", "mom cozy"),
    "Spectra": ("spectra",),
    "Elvie": ("elvie",),
    "Medela": ("medela",),
    "Willow": ("willow",),
    "Lansinoh": ("lansinoh",),
}
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d() .-]{7,}\d)(?!\w)")
URL_RE = re.compile(r"https?://", re.I)


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _bare_comment_id(value: str) -> str:
    return value[3:] if value.startswith("t1_") else value


def _date(value: datetime) -> str:
    return value.astimezone(timezone.utc).date().isoformat()


def _iso(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _contains_phrase(text: str, phrase: str) -> bool:
    pattern = r"(?<![A-Za-z0-9])" + re.escape(phrase) + r"(?![A-Za-z0-9])"
    return re.search(pattern, text, re.I) is not None


def _mentioned_brands(text: str) -> list[str]:
    return sorted(
        brand
        for brand, aliases in BRAND_ALIASES.items()
        if any(_contains_phrase(text, alias) for alias in aliases)
    )


def _raw_comments(nodes: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    comments: list[dict[str, Any]] = []
    more_nodes = 0
    for node in nodes:
        if not isinstance(node, dict):
            continue
        kind = node.get("kind")
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        if kind == "more":
            more_nodes += 1
            continue
        if kind != "t1":
            continue
        comments.append(data)
        replies = data.get("replies")
        if isinstance(replies, dict):
            children = replies.get("data", {}).get("children", [])
            nested, nested_more = _raw_comments(children)
            comments.extend(nested)
            more_nodes += nested_more
    return comments, more_nodes


def _legacy_etl_comments_from_post_listing(payload: list[Any]) -> int:
    """Reproduce the source ETL's effective comment scope without eval()."""
    if not payload or not isinstance(payload[0], dict):
        return 0
    comments, _ = _raw_comments(payload[0].get("data", {}).get("children", []))
    return len(comments)


def _inventory(raw_dir: Path) -> tuple[list[dict[str, Any]], str]:
    rows: list[dict[str, Any]] = []
    for path in sorted(p for p in raw_dir.rglob("*") if p.is_file()):
        relative = path.relative_to(raw_dir).as_posix()
        if path.name == ".DS_Store":
            continue
        rows.append(
            {
                "relative_path": relative,
                "collection_bucket": relative.split("/", 1)[0]
                if "/" in relative
                else None,
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
                "media_type": "application/json"
                if path.suffix.lower() == ".json"
                else "text/markdown",
            }
        )
    payload = b"\n".join(_canonical_json(row) for row in rows) + b"\n"
    return rows, sha256(payload).hexdigest()


def _profile_archive(raw_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    adapter = BrowserJsonAdapter()
    posts: dict[str, dict[str, Any]] = {}
    comments: dict[str, dict[str, Any]] = {}
    folder_stats: dict[str, Counter[str]] = defaultdict(Counter)
    subreddit_posts: Counter[str] = Counter()
    subreddit_comments: Counter[str] = Counter()
    coverage: Counter[str] = Counter()
    years: Counter[str] = Counter()
    parse_errors: list[dict[str, str]] = []
    file_count_completeness: Counter[str] = Counter()
    full_with_negative_gap = 0
    post_authors: set[str] = set()
    comment_authors: set[str] = set()
    privacy = Counter()
    post_dates: list[str] = []
    comment_dates: list[str] = []
    duplicate_post_ids: list[str] = []
    duplicate_comment_ids: list[str] = []
    file_hashes: Counter[str] = Counter()
    legacy_comment_total = 0
    multi_brand_discussions = 0
    folder_brand_post_mentions = 0
    folder_brand_discussion_mentions = 0
    branded_folder_posts = 0
    other_brand_counts: Counter[str] = Counter()

    for path in sorted(raw_dir.rglob("*.json")):
        relative = path.relative_to(raw_dir).as_posix()
        folder = relative.split("/", 1)[0]
        file_hashes[_sha256(path)] += 1
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            parsed = adapter.parse_thread_payload(
                payload,
                run_id="audit",
                raw_capture_id="audit",
                source_url=f"import://{relative}",
            )
        except Exception as exc:  # pragma: no cover - surfaced in output
            parse_errors.append(
                {"relative_path": relative, "error_class": type(exc).__name__}
            )
            continue

        legacy_comment_total += _legacy_etl_comments_from_post_listing(payload)
        post_data = payload[0]["data"]["children"][0]["data"]
        raw_comment_nodes = payload[1].get("data", {}).get("children", [])
        raw_comments, raw_more = _raw_comments(raw_comment_nodes)
        thread = parsed.thread
        post_id = thread.post_id
        if post_id in posts:
            duplicate_post_ids.append(post_id)
        reported = thread.num_comments_reported or 0
        parsed_count = len(parsed.comments)
        gap = reported - parsed_count
        if gap == 0:
            file_count_completeness["equal"] += 1
        elif gap > 0:
            file_count_completeness["parsed_lower"] += 1
        else:
            file_count_completeness["parsed_higher"] += 1
        if thread.coverage_grade == "full" and gap > 0:
            full_with_negative_gap += 1

        discussion_text = "\n".join(
            [thread.title, thread.selftext, *(comment.body for comment in parsed.comments)]
        )
        post_brands = _mentioned_brands(f"{thread.title}\n{thread.selftext}")
        discussion_brands = _mentioned_brands(discussion_text)
        if len(discussion_brands) >= 2:
            multi_brand_discussions += 1
        if folder in BRAND_ALIASES:
            branded_folder_posts += 1
            folder_brand_post_mentions += int(folder in post_brands)
            folder_brand_discussion_mentions += int(folder in discussion_brands)
        if folder == "other":
            other_brand_counts.update(discussion_brands)

        posts[post_id] = {
            "post_id": post_id,
            "collection_bucket": folder,
            "subreddit": thread.subreddit,
            "title": thread.title,
            "selftext": thread.selftext,
            "source_url": thread.source_url,
            "created_at_utc": thread.created_at_utc.isoformat(),
            "score": thread.score,
            "num_comments_reported": thread.num_comments_reported,
            "parsed_comment_count": parsed_count,
            "more_node_count": raw_more,
            "coverage_grade": thread.coverage_grade,
            "mentioned_brands": discussion_brands,
            "upvote_ratio_present": post_data.get("upvote_ratio") is not None,
        }
        folder_stats[folder]["posts"] += 1
        folder_stats[folder]["comments"] += parsed_count
        folder_stats[folder]["more_nodes"] += raw_more
        subreddit_posts[thread.subreddit] += 1
        coverage[thread.coverage_grade] += 1
        post_day = _date(thread.created_at_utc)
        post_dates.append(post_day)
        years[post_day[:4]] += 1

        author = str(post_data.get("author") or "")
        if author:
            post_authors.add(author)
        privacy["post_author_rows"] += int(bool(author))
        privacy["post_deleted_author_rows"] += int(author == "[deleted]")
        privacy["post_author_fullname_rows"] += int(
            bool(post_data.get("author_fullname"))
        )
        privacy["post_html_rows"] += int(bool(post_data.get("selftext_html")))
        privacy["post_flair_rows"] += int(bool(post_data.get("author_flair_text")))
        privacy["post_url_text_rows"] += int(bool(URL_RE.search(thread.selftext)))
        privacy["adapter_media_url_candidate_post_rows"] += int(bool(thread.media_urls))
        privacy["nsfw_post_rows"] += int(bool(post_data.get("over_18")))

        if len(raw_comments) != parsed_count:
            raise ValueError(f"raw/parser comment mismatch: {relative}")
        for raw_comment, comment in zip(raw_comments, parsed.comments, strict=True):
            comment_id = _bare_comment_id(comment.comment_id)
            if comment_id in comments:
                duplicate_comment_ids.append(comment_id)
            comments[comment_id] = {
                "comment_id": comment_id,
                "post_id": comment.post_id,
                "parent_id": comment.parent_id,
                "body": comment.body,
                "created_at_utc": comment.created_at_utc.isoformat(),
                "score": comment.score,
                "depth": comment.depth,
                "is_submitter": comment.is_submitter,
                "deleted_or_removed": comment.deleted_or_removed,
                "collection_bucket": folder,
            }
            subreddit_comments[thread.subreddit] += 1
            comment_dates.append(_date(comment.created_at_utc))
            raw_author = str(raw_comment.get("author") or "")
            if raw_author:
                comment_authors.add(raw_author)
            lower_author = raw_author.lower()
            is_bot = raw_author == "AutoModerator" or lower_author.endswith("bot")
            privacy["comment_author_rows"] += int(bool(raw_author))
            privacy["comment_deleted_author_rows"] += int(raw_author == "[deleted]")
            privacy["comment_author_fullname_rows"] += int(
                bool(raw_comment.get("author_fullname"))
            )
            privacy["automoderator_rows"] += int(raw_author == "AutoModerator")
            privacy["bot_rows"] += int(is_bot)
            privacy["email_match_rows"] += int(bool(EMAIL_RE.search(comment.body)))
            privacy["phone_candidate_rows"] += int(bool(PHONE_RE.search(comment.body)))
            privacy["comment_url_text_rows"] += int(bool(URL_RE.search(comment.body)))
            privacy["comment_html_rows"] += int(bool(raw_comment.get("body_html")))
            privacy["comment_flair_rows"] += int(
                bool(raw_comment.get("author_flair_text"))
            )

    reported_total = sum(
        int(post["num_comments_reported"] or 0) for post in posts.values()
    )
    parsed_total = len(comments)
    profile = {
        "schema_version": "reddit_voc_import_source_profile_v1",
        "json_files": len(list(raw_dir.rglob("*.json"))),
        "parse_successes": len(posts),
        "parse_errors": parse_errors,
        "posts": len(posts),
        "unique_posts": len(posts),
        "comments": parsed_total,
        "unique_comments": len(comments),
        "duplicate_post_ids": len(duplicate_post_ids),
        "duplicate_comment_ids": len(duplicate_comment_ids),
        "duplicate_file_sha_groups": sum(1 for count in file_hashes.values() if count > 1),
        "folder_distribution": {
            folder: dict(sorted(counts.items()))
            for folder, counts in sorted(folder_stats.items())
        },
        "subreddit_posts": dict(subreddit_posts.most_common()),
        "subreddit_comments": dict(subreddit_comments.most_common()),
        "coverage_grade": dict(sorted(coverage.items())),
        "reported_comment_count": reported_total,
        "parsed_comment_count": parsed_total,
        "comment_count_gap": reported_total - parsed_total,
        "aggregate_capture_ratio": round(parsed_total / reported_total, 6),
        "file_count_completeness": dict(sorted(file_count_completeness.items())),
        "full_grade_with_reported_gap_files": full_with_negative_gap,
        "more_node_count": sum(post["more_node_count"] for post in posts.values()),
        "max_comment_depth": max(
            (int(comment["depth"] or 0) for comment in comments.values()), default=0
        ),
        "post_date_range": [min(post_dates), max(post_dates)],
        "comment_date_range": [min(comment_dates), max(comment_dates)],
        "post_year_distribution": dict(sorted(years.items())),
        "upvote_ratio_present_posts": sum(
            int(post["upvote_ratio_present"]) for post in posts.values()
        ),
        "brand_semantics": {
            "branded_folder_posts": branded_folder_posts,
            "folder_brand_mentioned_in_post": folder_brand_post_mentions,
            "folder_brand_mentioned_in_discussion": folder_brand_discussion_mentions,
            "multi_brand_discussions": multi_brand_discussions,
            "other_bucket_brand_mentions": dict(other_brand_counts.most_common()),
        },
        "privacy_risk_counts": {
            **dict(sorted(privacy.items())),
            "unique_post_authors": len(post_authors),
            "unique_comment_authors": len(comment_authors),
        },
        "legacy_source_etl_effective_comment_count": legacy_comment_total,
    }
    return profile, {"posts": posts, "comments": comments}


def _load_historical(db_path: Path) -> dict[str, Any]:
    uri = f"file:{db_path.resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        posts = {
            str(row["post_id"]): dict(row)
            for row in conn.execute("SELECT * FROM reddit_threads")
        }
        comments = {
            _bare_comment_id(str(row["comment_id"])): dict(row)
            for row in conn.execute("SELECT * FROM reddit_comments")
        }
        analysis_counts = {
            str(row[0]): int(row[1])
            for row in conn.execute(
                "SELECT source_type, COUNT(*) FROM analysis_results GROUP BY source_type"
            )
        }
    return {
        "integrity_check": integrity,
        "posts": posts,
        "comments": comments,
        "analysis_counts": analysis_counts,
    }


def _compare_historical(
    archive: dict[str, Any], historical: dict[str, Any]
) -> dict[str, Any]:
    post_fields = (
        "subreddit",
        "title",
        "selftext",
        "source_url",
        "score",
        "num_comments_reported",
    )
    comment_fields = (
        "post_id",
        "parent_id",
        "body",
        "score",
        "depth",
        "is_submitter",
        "deleted_or_removed",
    )
    post_mismatches = Counter()
    comment_mismatches = Counter()
    for post_id, db_row in historical["posts"].items():
        source = archive["posts"].get(post_id)
        if source is None:
            continue
        for field in post_fields:
            if source[field] != db_row[field]:
                post_mismatches[field] += 1
        if _iso(source["created_at_utc"]) != _iso(str(db_row["created_at_utc"])):
            post_mismatches["created_at_utc"] += 1
    for comment_id, db_row in historical["comments"].items():
        source = archive["comments"].get(comment_id)
        if source is None:
            continue
        for field in comment_fields:
            left = source[field]
            right = db_row[field]
            if field in {"is_submitter", "deleted_or_removed"}:
                right = bool(right) if right is not None else None
            if left != right:
                comment_mismatches[field] += 1
        if _iso(source["created_at_utc"]) != _iso(str(db_row["created_at_utc"])):
            comment_mismatches["created_at_utc"] += 1
    return {
        "post_field_mismatches": dict(sorted(post_mismatches.items())),
        "comment_field_mismatches": dict(sorted(comment_mismatches.items())),
    }


def _fusion_audit(
    archive: dict[str, Any], historical: dict[str, Any], production: dict[str, Any]
) -> dict[str, Any]:
    a_posts = set(archive["posts"])
    a_comments = set(archive["comments"])
    b_posts = set(historical["posts"])
    b_comments = set(historical["comments"])
    c_posts = {str(row["post_id"]) for row in production["posts"]}
    c_comments = {
        _bare_comment_id(str(row["comment_id"])) for row in production["comments"]
    }
    union_posts = a_posts | b_posts | c_posts
    union_comments = a_comments | b_comments | c_comments
    production_orphans = [
        row
        for row in production["comments"]
        if str(row["post_id"]) not in union_posts
    ]
    linked_comments = len(union_comments) - len(production_orphans)

    archive_only_posts = a_posts - b_posts - c_posts
    archive_only_comments = a_comments - b_comments - c_comments
    increment_by_folder: dict[str, Counter[str]] = defaultdict(Counter)
    for post_id in archive_only_posts:
        increment_by_folder[archive["posts"][post_id]["collection_bucket"]]["posts"] += 1
    for comment_id in archive_only_comments:
        increment_by_folder[archive["comments"][comment_id]["collection_bucket"]][
            "comments"
        ] += 1

    comparison = _compare_historical(archive, historical)
    checks = {
        "archive_parse_count": len(a_posts) == 136,
        "archive_comment_count": len(a_comments) == 4153,
        "historical_posts_subset_archive": b_posts < a_posts,
        "historical_comments_subset_archive": b_comments < a_comments,
        "production_posts_disjoint_archive": not (c_posts & a_posts),
        "production_comments_disjoint_archive": not (c_comments & a_comments),
        "historical_field_equivalence": not comparison["post_field_mismatches"]
        and not comparison["comment_field_mismatches"],
        "union_post_count": len(union_posts) == 221,
        "union_comment_count": len(union_comments) == 4567,
        "production_orphan_count": len(production_orphans) == 18,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "sources": {
            "archive_import": {"posts": len(a_posts), "comments": len(a_comments)},
            "historical_canonical": {
                "posts": len(b_posts),
                "comments": len(b_comments),
                "integrity_check": historical["integrity_check"],
                "analysis_counts": historical["analysis_counts"],
            },
            "tencent_production_primary": {
                "posts": len(c_posts),
                "comments": len(c_comments),
                "integrity_check": production["integrity_check"],
                "analysis_counts": production["analysis_counts"],
                "captured_at_utc": production["captured_at_utc"],
            },
        },
        "overlap": {
            "archive_historical_posts": len(a_posts & b_posts),
            "archive_historical_comments": len(a_comments & b_comments),
            "archive_production_posts": len(a_posts & c_posts),
            "archive_production_comments": len(a_comments & c_comments),
            "historical_production_posts": len(b_posts & c_posts),
            "historical_production_comments": len(b_comments & c_comments),
        },
        "archive_net_increment": {
            "posts": len(archive_only_posts),
            "comments": len(archive_only_comments),
            "by_collection_bucket": {
                folder: dict(sorted(counts.items()))
                for folder, counts in sorted(increment_by_folder.items())
            },
        },
        "canonical_union": {
            "posts": len(union_posts),
            "stored_comments": len(union_comments),
            "linked_comments": linked_comments,
            "quarantined_comments": len(production_orphans),
            "quarantined_missing_post_ids": len(
                {str(row["post_id"]) for row in production_orphans}
            ),
        },
        "analysis_coverage_before_enrichment": {
            "analyzed_posts": len(b_posts) + len(c_posts),
            "pending_posts": len(archive_only_posts),
            "analyzed_linked_comments": len(b_comments)
            + int(production["analysis_counts"].get("comment", 0)),
            "pending_linked_comments": len(archive_only_comments),
            "quarantined_unanalyzed_comments": len(production_orphans),
        },
        "historical_equivalence": comparison,
        "checks": checks,
        "all_checks_passed": all(checks.values()),
        "boundaries": {
            "production_unchanged": True,
            "provider_call": False,
            "live_send": False,
        },
    }


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--historical-db", type=Path, required=True)
    parser.add_argument("--production-snapshot", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    raw_dir = args.raw_dir.resolve(strict=True)
    historical_db = args.historical_db.resolve(strict=True)
    production_path = args.production_snapshot.resolve(strict=True)
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    inventory, inventory_sha = _inventory(raw_dir)
    source_profile, archive = _profile_archive(raw_dir)
    historical = _load_historical(historical_db)
    production = json.loads(production_path.read_text(encoding="utf-8"))
    fusion = _fusion_audit(archive, historical, production)

    inventory_path = output_dir / "file-inventory.jsonl"
    inventory_path.write_bytes(
        b"\n".join(_canonical_json(row) for row in inventory) + b"\n"
    )
    _write_json(output_dir / "source-profile.json", source_profile)
    _write_json(output_dir / "fusion-audit.json", fusion)

    parser_path = Path(__file__).resolve().parents[1] / "src/reddit_voc/adapters.py"
    manifest = {
        "schema_version": "reddit_voc_import_manifest_v1",
        "dataset_id": "ai_nlp_voc_reddit_20260714",
        "source_dataset": "ai_nlp_voc/system_data/voc_data/reddit",
        "imported_at_utc": datetime.now(timezone.utc).isoformat(),
        "copy_mode": "immutable_snapshot",
        "excluded_files": [".DS_Store"],
        "file_count": len(inventory),
        "json_files": sum(row["media_type"] == "application/json" for row in inventory),
        "documentation_files": sum(
            row["media_type"] == "text/markdown" for row in inventory
        ),
        "total_bytes": sum(row["size_bytes"] for row in inventory),
        "inventory_sha256": inventory_sha,
        "parser_name": "reddit_voc.adapters.BrowserJsonAdapter",
        "parser_code_sha256": _sha256(parser_path),
        "post_count": source_profile["posts"],
        "comment_count": source_profile["comments"],
        "parse_errors": len(source_profile["parse_errors"]),
        "coverage_grade": source_profile["coverage_grade"],
        "source_unchanged": True,
        "provider_call": False,
        "live_send": False,
    }
    _write_json(output_dir / "import-manifest.json", manifest)

    print(
        json.dumps(
            {
                "status": "passed" if fusion["all_checks_passed"] else "failed",
                "manifest": str(output_dir / "import-manifest.json"),
                "source_profile": str(output_dir / "source-profile.json"),
                "fusion_audit": str(output_dir / "fusion-audit.json"),
                "posts": fusion["canonical_union"]["posts"],
                "stored_comments": fusion["canonical_union"]["stored_comments"],
                "linked_comments": fusion["canonical_union"]["linked_comments"],
                "quarantined_comments": fusion["canonical_union"][
                    "quarantined_comments"
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if fusion["all_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
