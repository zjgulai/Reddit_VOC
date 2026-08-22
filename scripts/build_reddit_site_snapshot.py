#!/usr/bin/env python3
"""Build a sanitized, versioned, static Reddit VOC website snapshot."""

from __future__ import annotations

import argparse
import ctypes
from collections.abc import Iterator
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
import errno
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile
from typing import Any, Sequence, cast

from reddit_voc.adapters import BrowserJsonAdapter
from reddit_voc.analyzer import analyze_text
from reddit_voc.keywords import keyword_rules_sha256, match_keywords
from reddit_voc.product_entity_resolution import CoverageLedger, ProductEntityResolver
from reddit_voc.product_tag_context import TagContext, tag_contexts_from_product_bindings
from reddit_voc.tag_dictionary import TagDictionary


ANALYSIS_VERSION = "local_rules_v1"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
V3_METRIC_ELIGIBILITY_POLICY = (
    PROJECT_ROOT / "config/analytics/reddit-voc-metric-eligibility-v1.json"
)
V3_METRIC_ELIGIBILITY_POLICY_SHA256 = (
    "c6c0faf2aef38da468d9bb42ddc1dc8f1f8f5b70d4d735e7756c64d3320381ab"
)
V3_PERIOD = "all_observed_history"
V3_SCOPE = "canonical_observation_pool"
V3_BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}
V3_ARGUMENTS = (
    "v3_canonical_root",
    "v3_canonical_manifest_sha256",
    "v3_validation_receipt",
    "v3_validation_receipt_sha256",
)
LEGACY_INPUT_ARGUMENTS = (
    "archive_dir",
    "historical_db",
    "production_snapshot",
    "staging_snapshot",
    "v2_raw_snapshot",
    "v2_identity_freeze",
    "existing_post_hydration_snapshot",
    "tag_dictionary",
    "product_entity_ledger",
)
EXPECTED_PRODUCT_LEDGER_SHA256 = (
    "cc66f565d64c19d0624baf9821ff4e765c692c8d85b8a4d7368214ab555451ab"
)
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d() .-]{7,}\d)(?!\w)")
USERNAME_MENTION_RE = re.compile(r"(?i)(?<![A-Za-z0-9_])/?u/[A-Za-z0-9_-]{2,30}")
AT_USERNAME_RE = re.compile(r"(?<![A-Za-z0-9_.+-])@[A-Za-z0-9_-]{2,30}")
POST_ID_RE = re.compile(r"^[a-z0-9]{5,10}$")
COMMENT_ID_RE = re.compile(r"^t1_[a-z0-9]+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
AUTHOR_HASH_RE = re.compile(r"^author_sha256:[0-9a-f]{16}$")
DATASET_VERSION_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,127}$")
BRAND_BINDINGS = frozenset(
    {
        "momcozy_sentence_bound",
        "momcozy_entity_reviewed",
        "competitor_sentence_bound",
        "multi_brand_context",
        "brand_unbound",
    }
)
COMMENT_COVERAGE_STATUS_BY_GRADE = {
    "full": "thread_complete",
    "partial": "observed_first_page",
    "post_only": "post_only",
}

BRAND_FAMILY_PREFIXES = (
    ("baby brezza", "Baby Brezza"),
    ("baby buddha", "Baby Buddha"),
    ("kindred bravely", "Kindred Bravely"),
    ("legendairy milk", "Legendairy Milk"),
    ("my brest friend", "My Brest Friend"),
    ("philips avent", "Philips Avent"),
    ("tommee tippee", "Tommee Tippee"),
    ("dr. brown", "Dr. Brown's"),
    ("fetal plus", "FetalPlus"),
    ("fetalplus", "FetalPlus"),
    ("baby bjorn", "BabyBjorn"),
    ("babybjorn", "BabyBjorn"),
    ("ergo embrace", "Ergobaby"),
    ("eufy", "eufy"),
    ("medela", "Medela"),
    ("lansinoh", "Lansinoh"),
    ("motif", "Motif"),
    ("momcozy", "Momcozy"),
    ("mom cozy", "Momcozy"),
)


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _identity_hash(values: list[str] | set[str]) -> str:
    ordered = sorted(set(values))
    return sha256("".join(f"{value}\n" for value in ordered).encode("utf-8")).hexdigest()


def _generated_at_utc(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("generated_at_utc_invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("generated_at_utc_timezone_missing")
    return parsed.astimezone(timezone.utc).isoformat()


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _harden_private_tree(root: Path) -> None:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("snapshot staging root is unsafe")
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("snapshot staging tree contains a symlink")
        if path.is_dir():
            path.chmod(0o700)
        elif path.is_file():
            path.chmod(0o600)
        else:
            raise ValueError("snapshot staging tree contains an unsafe entry")
    root.chmod(0o700)


def _rename_directory_noreplace(
    parent: Path, source_name: str, target_name: str
) -> None:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    parent_fd = os.open(parent, flags)
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        if sys.platform == "darwin" and hasattr(libc, "renameatx_np"):
            function = libc.renameatx_np
            function.argtypes = [
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            ]
            function.restype = ctypes.c_int
            result = function(
                parent_fd,
                os.fsencode(source_name),
                parent_fd,
                os.fsencode(target_name),
                0x00000004,
            )
        elif sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
            function = libc.renameat2
            function.argtypes = [
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            ]
            function.restype = ctypes.c_int
            result = function(
                parent_fd,
                os.fsencode(source_name),
                parent_fd,
                os.fsencode(target_name),
                1,
            )
        else:
            raise ValueError("atomic_no_replace_snapshot_publish_unavailable")
        if result != 0:
            number = ctypes.get_errno()
            if number in {errno.EEXIST, errno.ENOTEMPTY}:
                raise FileExistsError(
                    f"output_dir_created_during_publish: {parent / target_name}"
                )
            raise OSError(number, os.strerror(number))
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


@contextmanager
def _fresh_output_directory(output_dir: Path) -> Iterator[Path]:
    """Build beside the target, then publish with one same-filesystem rename."""

    if _path_exists(output_dir):
        raise FileExistsError(f"output_dir_already_exists: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(
        tempfile.mkdtemp(
            prefix=f".{output_dir.name}.staging-",
            dir=output_dir.parent,
        )
    )
    staging_dir.chmod(0o700)
    try:
        yield staging_dir
        _harden_private_tree(staging_dir)
        if _path_exists(output_dir):
            raise FileExistsError(f"output_dir_created_during_build: {output_dir}")
        _rename_directory_noreplace(
            output_dir.parent, staging_dir.name, output_dir.name
        )
    except BaseException:
        if _path_exists(staging_dir):
            shutil.rmtree(staging_dir)
        raise


def _json_list(value: Any, *, allow_legacy_csv: bool = False) -> list[Any]:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        if allow_legacy_csv and isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        raise
    return parsed if isinstance(parsed, list) else []


def _bare_comment_id(value: str) -> str:
    return value[3:] if value.startswith("t1_") else value


def _full_comment_id(value: str) -> str:
    return value if value.startswith("t1_") else f"t1_{value}"


def _pseudonym(author_hash: str | None) -> str | None:
    if not author_hash:
        return None
    suffix = author_hash.split(":", 1)[-1]
    return f"anon_{suffix[:10]}"


def _sanitize_text(value: str) -> tuple[str, list[str]]:
    text = value or ""
    flags: list[str] = []
    updated, count = EMAIL_RE.subn("[redacted_email]", text)
    if count:
        flags.append("email")
    updated, count = PHONE_RE.subn("[redacted_phone_candidate]", updated)
    if count:
        flags.append("phone_candidate")
    updated, count = USERNAME_MENTION_RE.subn("u/[redacted_user]", updated)
    if count:
        flags.append("username_mention")
    updated, count = AT_USERNAME_RE.subn("@[redacted_user]", updated)
    if count and "username_mention" not in flags:
        flags.append("username_mention")
    return updated, flags


def _brand_family(term: str) -> str:
    lowered = term.casefold()
    for prefix, family in BRAND_FAMILY_PREFIXES:
        if lowered.startswith(prefix):
            return family
    return term


def _mentioned_brands(text: str) -> list[str]:
    match = match_keywords(text)
    return sorted({_brand_family(term) for term in [*match.brands, *match.competitors]})


def _is_momcozy_brand(value: str) -> bool:
    return re.sub(r"[^a-z0-9]", "", value.casefold()) == "momcozy"


def _entity_brand_binding(
    mentioned_brands: list[str], product_bindings: list[dict[str, Any]]
) -> str:
    has_product_binding = any(
        binding.get("brand_id") == "momcozy" for binding in product_bindings
    )
    has_explicit_momcozy = any(_is_momcozy_brand(brand) for brand in mentioned_brands)
    has_competitor = any(
        not _is_momcozy_brand(brand) for brand in mentioned_brands
    )
    if (has_product_binding or has_explicit_momcozy) and has_competitor:
        return "multi_brand_context"
    if has_product_binding or has_explicit_momcozy:
        return "momcozy_entity_reviewed"
    if has_competitor:
        return "competitor_sentence_bound"
    return "brand_unbound"


def _combine_product_coverage(
    post_coverage: dict[str, Any], comment_coverage: dict[str, Any]
) -> dict[str, Any]:
    category_counts = Counter(post_coverage["category_binding_counts"])
    category_counts.update(comment_coverage["category_binding_counts"])
    family_counts = Counter(post_coverage["family_binding_counts"])
    family_counts.update(comment_coverage["family_binding_counts"])
    ledger = CoverageLedger(
        input_record_count=(
            int(post_coverage["input_record_count"])
            + int(comment_coverage["input_record_count"])
        ),
        bound_record_count=(
            int(post_coverage["bound_record_count"])
            + int(comment_coverage["bound_record_count"])
        ),
        unbound_record_count=(
            int(post_coverage["unbound_record_count"])
            + int(comment_coverage["unbound_record_count"])
        ),
        multi_binding_record_count=(
            int(post_coverage["multi_binding_record_count"])
            + int(comment_coverage["multi_binding_record_count"])
        ),
        binding_count=(
            int(post_coverage["binding_count"])
            + int(comment_coverage["binding_count"])
        ),
        exact_spu_binding_count=(
            int(post_coverage["exact_spu_binding_count"])
            + int(comment_coverage["exact_spu_binding_count"])
        ),
        family_only_binding_count=(
            int(post_coverage["family_only_binding_count"])
            + int(comment_coverage["family_only_binding_count"])
        ),
        category_only_binding_count=(
            int(post_coverage["category_only_binding_count"])
            + int(comment_coverage["category_only_binding_count"])
        ),
        taxonomy_blocked_binding_count=(
            int(post_coverage["taxonomy_blocked_binding_count"])
            + int(comment_coverage["taxonomy_blocked_binding_count"])
        ),
        category_binding_counts=tuple(sorted(category_counts.items())),
        family_binding_counts=tuple(sorted(family_counts.items())),
    )
    return ledger.to_record()


def _tag_dictionary_context_profile(
    tag_dictionary: TagDictionary, contexts: tuple[TagContext, ...]
) -> dict[str, Any]:
    rules = tag_dictionary.select_rules_for_contexts(contexts)
    phrase_tag_ids: dict[str, set[str]] = defaultdict(set)
    phrase_sentiments: dict[str, set[str]] = defaultdict(set)
    for rule in rules:
        for phrase in rule.keywords:
            phrase_tag_ids[phrase].add(rule.tag_id)
            phrase_sentiments[phrase].add(rule.sentiment)
    shared = {
        phrase for phrase, tag_ids in phrase_tag_ids.items() if len(tag_ids) > 1
    }
    return {
        "dictionary_version": tag_dictionary.version,
        "row_count": len(tag_dictionary.rules),
        "tag_ids_unique": len(tag_dictionary.by_id) == len(tag_dictionary.rules),
        "resolution_mode": "governed_product_bindings",
        "observed_contexts": [
            {
                "product_line": product_line,
                "voc_category": voc_category,
                "spu_ids": list(spu_ids),
            }
            for product_line, voc_category, spu_ids in contexts
        ],
        "eligible_rule_count": len(rules),
        "scope_counts": dict(
            sorted(Counter(rule.tag_scope for rule in rules).items())
        ),
        "unique_keyword_count": len(phrase_tag_ids),
        "shared_keyword_count": len(shared),
        "cross_sentiment_keyword_count": sum(
            phrase in shared and len(sentiments) > 1
            for phrase, sentiments in phrase_sentiments.items()
        ),
        "approved_spu_ids": sorted(
            {spu_id for _, _, spu_ids in contexts for spu_id in spu_ids}
        ),
        "legacy_model_alias_detection_used": False,
    }


def _analysis(text: str, *, code_sha256: str) -> dict[str, Any]:
    result = analyze_text(text)
    return {
        "analysis_version": ANALYSIS_VERSION,
        "analysis_code_sha256": code_sha256,
        "sentiment_label": result.sentiment_label,
        "sentiment_score": result.sentiment_score,
        "topic": result.topic,
        "severity": result.severity,
        "confidence": result.confidence,
        "pain_points": result.pain_points,
        "provider_call": False,
    }


def _occurrence(
    *,
    source_kind: str,
    dataset_id: str,
    collection_bucket: str | None,
    run_id: str | None = None,
    coverage_grade: str | None = None,
) -> dict[str, Any]:
    return {
        "source_kind": source_kind,
        "dataset_id": dataset_id,
        "collection_bucket": collection_bucket,
        "run_id": run_id,
        "coverage_grade": coverage_grade,
    }


def _load_archive(
    raw_dir: Path,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    set[str],
    dict[str, Any],
]:
    adapter = BrowserJsonAdapter()
    posts: dict[str, dict[str, Any]] = {}
    comments: dict[str, dict[str, Any]] = {}
    raw_authors: set[str] = set()
    post_occurrences: Counter[str] = Counter()
    comment_occurrences: Counter[str] = Counter()
    source_file_count = 0
    source_bytes = 0
    source_file_lineage: list[str] = []

    for path in sorted(raw_dir.rglob("*.json")):
        source_file_count += 1
        relative = path.relative_to(raw_dir).as_posix()
        size = path.stat().st_size
        source_bytes += size
        source_file_lineage.append(f"{relative}|{size}|{_sha256(path)}\n")
        bucket = relative.split("/", 1)[0]
        payload = json.loads(path.read_text(encoding="utf-8"))
        parsed = adapter.parse_thread_payload(
            payload,
            run_id="archive_import",
            raw_capture_id="archive_import",
            source_url=f"import://{relative}",
        )
        post_data = payload[0]["data"]["children"][0]["data"]
        raw_author = str(post_data.get("author") or "")
        if raw_author and raw_author not in {"[deleted]", "AutoModerator"}:
            raw_authors.add(raw_author)
        title, title_flags = _sanitize_text(parsed.thread.title)
        content, content_flags = _sanitize_text(parsed.thread.selftext)
        post_id = parsed.thread.post_id
        post_occurrences[post_id] += 1
        posts[post_id] = {
            "post_id": post_id,
            "reddit_id": f"t3_{post_id}",
            "title": title,
            "content": content,
            "subreddit": parsed.thread.subreddit,
            "permalink": parsed.thread.source_url,
            "created_at_utc": parsed.thread.created_at_utc.isoformat(),
            "score": parsed.thread.score,
            "upvote_ratio": post_data.get("upvote_ratio"),
            "num_comments_reported": parsed.thread.num_comments_reported,
            "parsed_comment_count": parsed.thread.parsed_comment_count,
            "more_node_count": parsed.thread.more_node_count,
            "structural_coverage_grade": parsed.thread.coverage_grade,
            "matched_keywords": parsed.thread.matched_keywords,
            "media_urls": parsed.thread.media_urls,
            "author_pseudonym": _pseudonym(parsed.thread.author_hash),
            "pii_redaction_flags": sorted(set(title_flags + content_flags)),
            "source_occurrences": [
                _occurrence(
                    source_kind="imported_archive",
                    dataset_id="ai_nlp_voc_reddit_20260714",
                    collection_bucket=bucket,
                    coverage_grade=parsed.thread.coverage_grade,
                )
            ],
        }

        comment_nodes = payload[1].get("data", {}).get("children", [])
        raw_comment_rows: list[dict[str, Any]] = []

        def collect(nodes: list[dict[str, Any]]) -> None:
            for node in nodes:
                if node.get("kind") != "t1":
                    continue
                raw_data = node.get("data")
                data = cast(dict[str, Any], raw_data) if isinstance(raw_data, dict) else {}
                raw_comment_rows.append(data)
                replies = data.get("replies")
                if isinstance(replies, dict):
                    collect(replies.get("data", {}).get("children", []))

        collect(comment_nodes)
        if len(raw_comment_rows) != len(parsed.comments):
            raise ValueError(f"raw/parser comment mismatch: {relative}")
        for raw_comment, comment in zip(raw_comment_rows, parsed.comments, strict=True):
            raw_comment_author = str(raw_comment.get("author") or "")
            if raw_comment_author and raw_comment_author not in {
                "[deleted]",
                "AutoModerator",
            }:
                raw_authors.add(raw_comment_author)
            body, flags = _sanitize_text(comment.body)
            is_bot = raw_comment_author == "AutoModerator" or raw_comment_author.casefold().endswith(
                "bot"
            )
            comment_id = _full_comment_id(comment.comment_id)
            comment_occurrences[comment_id] += 1
            comments[comment_id] = {
                "comment_id": comment_id,
                "reddit_id": comment_id,
                "post_id": comment.post_id,
                "parent_id": comment.parent_id,
                "body": body,
                "created_at_utc": comment.created_at_utc.isoformat(),
                "score": comment.score,
                "depth": comment.depth,
                "is_submitter": comment.is_submitter,
                "deleted_or_removed": comment.deleted_or_removed,
                "is_bot": is_bot,
                "bot_detection_status": "known_from_archive_author",
                "author_pseudonym": _pseudonym(comment.author_hash),
                "pii_redaction_flags": flags,
                "source_occurrences": [
                    _occurrence(
                        source_kind="imported_archive",
                        dataset_id="ai_nlp_voc_reddit_20260714",
                        collection_bucket=bucket,
                        coverage_grade=parsed.thread.coverage_grade,
                    )
                ],
            }
    archive_meta = {
        "dataset_id": "ai_nlp_voc_reddit_20260714",
        "source_files": source_file_count,
        "source_bytes": source_bytes,
        "source_file_lf_sha256": sha256(
            "".join(source_file_lineage).encode("utf-8")
        ).hexdigest(),
        "post_occurrences": sum(post_occurrences.values()),
        "comment_occurrences": sum(comment_occurrences.values()),
        "unique_posts": len(posts),
        "unique_comments": len(comments),
        "duplicate_post_occurrences": sum(
            count - 1 for count in post_occurrences.values() if count > 1
        ),
        "duplicate_comment_occurrences": sum(
            count - 1 for count in comment_occurrences.values() if count > 1
        ),
        "dedup_key": {"posts": "post_id", "comments": "comment_id"},
        "net_new_posts": len(posts),
        "net_new_comments": len(comments),
    }
    return posts, comments, raw_authors, archive_meta


def _append_historical_occurrences(
    db_path: Path,
    posts: dict[str, dict[str, Any]],
    comments: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    uri = f"file:{db_path.resolve()}?mode=ro"
    post_occurrences = 0
    comment_occurrences = 0
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        versions = [
            str(row[0])
            for row in conn.execute(
                "SELECT DISTINCT analysis_version FROM analysis_results ORDER BY 1"
            )
        ]
        for row in conn.execute(
            "SELECT post_id, run_id, coverage_grade FROM reddit_threads ORDER BY post_id"
        ):
            post_occurrences += 1
            post_id = str(row["post_id"])
            if post_id not in posts:
                raise ValueError(f"historical post missing from archive: {post_id}")
            posts[post_id]["source_occurrences"].append(
                _occurrence(
                    source_kind="historical_canonical",
                    dataset_id="backfill_momcozy_20250101_20260711",
                    collection_bucket="Momcozy",
                    run_id=str(row["run_id"]),
                    coverage_grade=str(row["coverage_grade"]),
                )
            )
        for row in conn.execute(
            "SELECT comment_id, run_id, post_id FROM reddit_comments ORDER BY comment_id"
        ):
            comment_occurrences += 1
            comment_id = _full_comment_id(str(row["comment_id"]))
            if comment_id not in comments:
                raise ValueError(f"historical comment missing from archive: {comment_id}")
            if comments[comment_id]["post_id"] != str(row["post_id"]):
                raise ValueError(f"historical comment post mismatch: {comment_id}")
            comments[comment_id]["source_occurrences"].append(
                _occurrence(
                    source_kind="historical_canonical",
                    dataset_id="backfill_momcozy_20250101_20260711",
                    collection_bucket="Momcozy",
                    run_id=str(row["run_id"]),
                )
            )
    return {
        "dataset_id": "backfill_momcozy_20250101_20260711",
        "database_sha256": _sha256(db_path),
        "integrity_check": integrity,
        "analysis_versions": versions,
        "input_posts": post_occurrences,
        "input_comments": comment_occurrences,
        "overlap_posts": post_occurrences,
        "overlap_comments": comment_occurrences,
        "net_new_posts": 0,
        "net_new_comments": 0,
        "fusion_role": "lineage_occurrence_only_strict_archive_subset",
    }


def _append_production(
    snapshot_path: Path,
    posts: dict[str, dict[str, Any]],
    comments: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot_checks = snapshot.get("checks")
    if (
        snapshot.get("schema_version") != "reddit_voc_remote_content_snapshot_v1"
        or snapshot.get("integrity_check") != "ok"
        or snapshot.get("quick_check") != "ok"
        or snapshot.get("query_only") != 1
        or not snapshot.get("identity_snapshot_match")
        or not isinstance(snapshot_checks, dict)
        or not all(snapshot_checks.values())
        or snapshot.get("source", {}).get("environment") != "tencent_production"
    ):
        raise ValueError("production content snapshot failed its read-only identity gate")
    dataset_id = str(
        snapshot.get("source", {}).get("dataset_id")
        or "tencent_production_20260714"
    )
    for row in snapshot["posts"]:
        post_id = str(row["post_id"])
        if post_id in posts:
            raise ValueError(f"unexpected archive/production post overlap: {post_id}")
        title, title_flags = _sanitize_text(str(row.get("title") or ""))
        content, content_flags = _sanitize_text(str(row.get("selftext") or ""))
        posts[post_id] = {
            "post_id": post_id,
            "reddit_id": f"t3_{post_id}",
            "title": title,
            "content": content,
            "subreddit": str(row.get("subreddit") or ""),
            "permalink": str(row.get("source_url") or ""),
            "created_at_utc": str(row["created_at_utc"]),
            "score": row.get("score"),
            "upvote_ratio": None,
            "num_comments_reported": row.get("num_comments_reported"),
            "parsed_comment_count": int(row.get("parsed_comment_count") or 0),
            "more_node_count": int(row.get("more_node_count") or 0),
            "structural_coverage_grade": str(row.get("coverage_grade") or "unknown"),
            "matched_keywords": _json_list(
                row.get("matched_keywords"), allow_legacy_csv=True
            ),
            "media_urls": _json_list(row.get("media_urls")),
            "author_pseudonym": _pseudonym(row.get("author_hash")),
            "pii_redaction_flags": sorted(set(title_flags + content_flags)),
            "source_occurrences": [
                _occurrence(
                    source_kind="tencent_production_primary",
                    dataset_id=dataset_id,
                    collection_bucket="daily_production",
                    run_id=str(row["run_id"]),
                    coverage_grade=str(row.get("coverage_grade") or "unknown"),
                )
            ],
        }
    for row in snapshot["comments"]:
        comment_id = _full_comment_id(str(row["comment_id"]))
        if comment_id in comments:
            raise ValueError(f"unexpected archive/production comment overlap: {comment_id}")
        body, flags = _sanitize_text(str(row.get("body") or ""))
        comments[comment_id] = {
            "comment_id": comment_id,
            "reddit_id": comment_id,
            "post_id": str(row["post_id"]),
            "parent_id": row.get("parent_id"),
            "body": body,
            "created_at_utc": str(row["created_at_utc"]),
            "score": row.get("score"),
            "depth": row.get("depth"),
            "is_submitter": None
            if row.get("is_submitter") is None
            else bool(row.get("is_submitter")),
            "deleted_or_removed": bool(row.get("deleted_or_removed")),
            "is_bot": None,
            "bot_detection_status": "unavailable_in_normalized_production",
            "author_pseudonym": _pseudonym(row.get("author_hash")),
            "pii_redaction_flags": flags,
            "source_occurrences": [
                _occurrence(
                    source_kind="tencent_production_primary",
                    dataset_id=dataset_id,
                    collection_bucket="daily_production",
                    run_id=str(row["run_id"]),
                )
            ],
        }
    versions = sorted({str(row["analysis_version"]) for row in snapshot["analyses"]})
    return {
        "integrity_check": snapshot["integrity_check"],
        "captured_at_utc": snapshot["captured_at_utc"],
        "analysis_versions": versions,
        "dataset_id": dataset_id,
        "database_sha256": snapshot["source"]["database_sha256"],
        "snapshot_sha256": _sha256(snapshot_path),
        "input_posts": len(snapshot["posts"]),
        "input_comments": len(snapshot["comments"]),
        "overlap_posts": 0,
        "overlap_comments": 0,
        "net_new_posts": len(snapshot["posts"]),
        "net_new_comments": len(snapshot["comments"]),
        "fusion_role": "canonical_primary_disjoint_from_archive",
    }


def _append_isolated_staging(
    snapshot_path: Path,
    posts: dict[str, dict[str, Any]],
    comments: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot_checks = snapshot.get("checks")
    if (
        snapshot.get("schema_version") != "reddit_voc_remote_content_snapshot_v1"
        or snapshot.get("integrity_check") != "ok"
        or snapshot.get("quick_check") != "ok"
        or snapshot.get("query_only") != 1
        or not snapshot.get("identity_snapshot_match")
        or not isinstance(snapshot_checks, dict)
        or not all(snapshot_checks.values())
        or snapshot.get("source", {}).get("environment")
        != "tencent_isolated_staging"
    ):
        raise ValueError("isolated staging snapshot failed its read-only identity gate")

    dataset_id = str(snapshot["source"]["dataset_id"])
    post_ids_before = set(posts)
    comment_ids_before = set(comments)
    post_title_conflicts = 0
    post_content_conflicts = 0
    post_content_upgrades = 0
    comment_body_conflicts = 0
    comment_link_conflicts = 0

    for row in snapshot["posts"]:
        post_id = str(row["post_id"])
        occurrence = _occurrence(
            source_kind="tencent_isolated_staging",
            dataset_id=dataset_id,
            collection_bucket="momcozy_historical_staging",
            run_id=str(row["run_id"]),
            coverage_grade=str(row.get("coverage_grade") or "unknown"),
        )
        title, title_flags = _sanitize_text(str(row.get("title") or ""))
        content, content_flags = _sanitize_text(str(row.get("selftext") or ""))
        if post_id in posts:
            post = posts[post_id]
            if title != post["title"]:
                post_title_conflicts += 1
            if content != post["content"]:
                post_content_conflicts += 1
                if len(content) > len(str(post["content"])):
                    post["content"] = content
                    post_content_upgrades += 1
            post["pii_redaction_flags"] = sorted(
                set(post["pii_redaction_flags"] + title_flags + content_flags)
            )
            post["source_occurrences"].append(occurrence)
            continue
        posts[post_id] = {
            "post_id": post_id,
            "reddit_id": f"t3_{post_id}",
            "title": title,
            "content": content,
            "subreddit": str(row.get("subreddit") or ""),
            "permalink": str(row.get("source_url") or ""),
            "created_at_utc": str(row["created_at_utc"]),
            "score": row.get("score"),
            "upvote_ratio": None,
            "num_comments_reported": row.get("num_comments_reported"),
            "parsed_comment_count": int(row.get("parsed_comment_count") or 0),
            "more_node_count": int(row.get("more_node_count") or 0),
            "structural_coverage_grade": str(
                row.get("coverage_grade") or "unknown"
            ),
            "matched_keywords": _json_list(
                row.get("matched_keywords"), allow_legacy_csv=True
            ),
            "media_urls": _json_list(row.get("media_urls")),
            "author_pseudonym": _pseudonym(row.get("author_hash")),
            "pii_redaction_flags": sorted(set(title_flags + content_flags)),
            "source_occurrences": [occurrence],
        }

    for row in snapshot["comments"]:
        comment_id = _full_comment_id(str(row["comment_id"]))
        post_id = str(row["post_id"])
        occurrence = _occurrence(
            source_kind="tencent_isolated_staging",
            dataset_id=dataset_id,
            collection_bucket="momcozy_historical_staging",
            run_id=str(row["run_id"]),
        )
        body, flags = _sanitize_text(str(row.get("body") or ""))
        if comment_id in comments:
            comment = comments[comment_id]
            if body != comment["body"]:
                comment_body_conflicts += 1
            if post_id != comment["post_id"]:
                comment_link_conflicts += 1
            comment["pii_redaction_flags"] = sorted(
                set(comment["pii_redaction_flags"] + flags)
            )
            comment["source_occurrences"].append(occurrence)
            continue
        comments[comment_id] = {
            "comment_id": comment_id,
            "reddit_id": comment_id,
            "post_id": post_id,
            "parent_id": row.get("parent_id"),
            "body": body,
            "created_at_utc": str(row["created_at_utc"]),
            "score": row.get("score"),
            "depth": row.get("depth"),
            "is_submitter": None
            if row.get("is_submitter") is None
            else bool(row.get("is_submitter")),
            "deleted_or_removed": bool(row.get("deleted_or_removed")),
            "is_bot": None,
            "bot_detection_status": "unavailable_in_normalized_staging",
            "author_pseudonym": _pseudonym(row.get("author_hash")),
            "pii_redaction_flags": flags,
            "source_occurrences": [occurrence],
        }

    versions = sorted({str(row["analysis_version"]) for row in snapshot["analyses"]})
    return {
        "integrity_check": snapshot["integrity_check"],
        "captured_at_utc": snapshot["captured_at_utc"],
        "database_sha256": snapshot["source"]["database_sha256"],
        "snapshot_sha256": _sha256(snapshot_path),
        "dataset_id": dataset_id,
        "analysis_versions": versions,
        "input_posts": len(snapshot["posts"]),
        "input_comments": len(snapshot["comments"]),
        "overlap_posts": len(
            post_ids_before & {str(row["post_id"]) for row in snapshot["posts"]}
        ),
        "overlap_comments": len(
            comment_ids_before
            & {
                _full_comment_id(str(row["comment_id"]))
                for row in snapshot["comments"]
            }
        ),
        "net_new_posts": len(posts) - len(post_ids_before),
        "net_new_comments": len(comments) - len(comment_ids_before),
        "post_title_conflicts": post_title_conflicts,
        "post_content_conflicts": post_content_conflicts,
        "post_content_upgrades": post_content_upgrades,
        "comment_body_conflicts": comment_body_conflicts,
        "comment_link_conflicts": comment_link_conflicts,
        "fusion_role": "deterministic_overlay_after_production",
        "dedup_key": {"posts": "post_id", "comments": "comment_id"},
        "precedence_policy": {
            "title": "existing_canonical_wins",
            "content": "longer_sanitized_content_wins",
            "comment_body": "existing_canonical_wins",
            "source_occurrences": "append_all_observed_lineage",
        },
    }


def _append_v2_raw_snapshot(
    snapshot_path: Path,
    identity_freeze_path: Path,
    posts: dict[str, dict[str, Any]],
    comments: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Admit hydrated V2 discovery rows without overstating comment coverage."""

    identity = json.loads(identity_freeze_path.read_text(encoding="utf-8"))
    if identity.get("schema_version") != "reddit_voc_v2_identity_freeze_v1":
        raise ValueError("v2_identity_freeze_schema_invalid")
    identity_boundaries = identity.get("boundaries")
    if not isinstance(identity_boundaries, dict) or any(
        identity_boundaries.get(field) is not False
        for field in (
            "provider_call",
            "remote_write",
            "database_write",
            "production_merge",
            "live_send",
            "deployment",
        )
    ):
        raise ValueError("v2_identity_freeze_boundary_invalid")

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if snapshot.get("schema_version") != "reddit_voc_v2_raw_snapshot_v1":
        raise ValueError("v2_raw_snapshot_schema_invalid")
    if snapshot.get("status") not in {"blocked", "complete"}:
        raise ValueError("v2_raw_snapshot_status_invalid")
    for field in (
        "provider_call",
        "provider_attempt_made",
        "database_write",
        "production_merge",
        "live_send",
        "git_push",
        "dingtalk",
    ):
        if snapshot.get(field) is not False:
            raise ValueError(f"v2_raw_snapshot_{field}_boundary_invalid")
    privacy = snapshot.get("privacy")
    if (
        not isinstance(privacy, dict)
        or privacy.get("raw_payload_embedded") is not False
        or privacy.get("raw_username_embedded") is not False
    ):
        raise ValueError("v2_raw_snapshot_privacy_invalid")

    target = snapshot.get("target")
    if not isinstance(target, dict):
        raise ValueError("v2_raw_snapshot_target_invalid")
    identity_set_id = target.get("set_id")
    if not isinstance(identity_set_id, str) or not identity_set_id.strip():
        raise ValueError("v2_raw_snapshot_target_set_id_invalid")

    identity_sets = identity.get("identity_sets")
    matches = [
        row
        for row in identity_sets if isinstance(row, dict) and row.get("set_id") == identity_set_id
    ] if isinstance(identity_sets, list) else []
    if len(matches) != 1:
        raise ValueError("v2_identity_set_not_unique")
    identity_set = matches[0]
    target_ids_raw = identity_set.get("post_ids")
    if not isinstance(target_ids_raw, list) or not target_ids_raw or any(
        not isinstance(value, str) or POST_ID_RE.fullmatch(value) is None
        for value in target_ids_raw
    ):
        raise ValueError("v2_identity_post_ids_invalid")
    target_ids = set(target_ids_raw)
    if len(target_ids) != len(target_ids_raw):
        raise ValueError("v2_identity_post_ids_duplicate")
    target_hash = _identity_hash(target_ids)
    identity_target_count = identity_set.get("count")
    if (
        not isinstance(identity_target_count, int)
        or isinstance(identity_target_count, bool)
        or identity_target_count != len(target_ids)
        or identity_set.get("lf_sha256") != target_hash
    ):
        raise ValueError("v2_identity_set_count_or_sha256_mismatch")
    identity_sha = _sha256(identity_freeze_path)
    if target.get("identity_inventory_sha256") != identity_sha:
        raise ValueError("v2_identity_snapshot_sha256_mismatch")
    raw_target_count = target.get("count")
    if (
        target.get("set_id") != identity_set_id
        or not isinstance(raw_target_count, int)
        or isinstance(raw_target_count, bool)
        or raw_target_count != len(target_ids)
        or target.get("post_ids_sha256") != target_hash
    ):
        raise ValueError("v2_raw_snapshot_target_mismatch")

    accounting = snapshot.get("accounting")
    blockers = accounting.get("blockers") if isinstance(accounting, dict) else None
    if not isinstance(accounting, dict) or not isinstance(blockers, dict):
        raise ValueError("v2_raw_snapshot_accounting_invalid")
    for field in (
        "search_post_conflicts",
        "outside_target_window",
        "cursor_cycles",
        "orphan_reply_reports",
        "report_conflicts",
        "comment_conflicts",
        "failed_reports",
    ):
        if blockers.get(field) != 0:
            raise ValueError(f"v2_raw_snapshot_{field}_not_admissible")
    if accounting.get("target_search_row_rejection_count") != 0:
        raise ValueError("v2_raw_snapshot_target_search_row_rejection")

    lineage_missing_raw = accounting.get("lineage_missing_post_ids")
    first_page_missing_raw = accounting.get("first_page_missing_post_ids")
    if not isinstance(lineage_missing_raw, list) or not isinstance(first_page_missing_raw, list):
        raise ValueError("v2_raw_snapshot_missing_sets_invalid")
    if any(
        not isinstance(value, str) or POST_ID_RE.fullmatch(value) is None
        for value in [*lineage_missing_raw, *first_page_missing_raw]
    ):
        raise ValueError("v2_raw_snapshot_missing_post_ids_invalid")
    lineage_missing = set(lineage_missing_raw)
    first_page_missing = set(first_page_missing_raw)
    if (
        len(lineage_missing) != len(lineage_missing_raw)
        or len(first_page_missing) != len(first_page_missing_raw)
        or not lineage_missing <= target_ids
        or not first_page_missing <= target_ids
    ):
        raise ValueError("v2_raw_snapshot_missing_post_sets_invalid")
    lineage_missing_count = blockers.get("lineage_missing")
    if (
        not isinstance(lineage_missing_count, int)
        or isinstance(lineage_missing_count, bool)
        or lineage_missing_count != len(lineage_missing)
    ):
        raise ValueError("v2_lineage_gap_contract_mismatch")
    if first_page_missing != lineage_missing:
        raise ValueError("v2_first_page_gap_exceeds_lineage_gap")
    first_page_missing_count = blockers.get("first_page_missing")
    if (
        not isinstance(first_page_missing_count, int)
        or isinstance(first_page_missing_count, bool)
        or first_page_missing_count != len(first_page_missing)
    ):
        raise ValueError("v2_first_page_gap_count_mismatch")
    for field in ("cursor_outstanding", "page_pagination_outstanding"):
        value = blockers.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"v2_raw_snapshot_{field}_invalid")

    raw_posts = snapshot.get("posts")
    raw_comments = snapshot.get("comments")
    analyses = snapshot.get("analyses")
    if not isinstance(raw_posts, list) or not isinstance(raw_comments, list) or not isinstance(analyses, list):
        raise ValueError("v2_raw_snapshot_entity_arrays_invalid")
    raw_post_ids = [row.get("post_id") for row in raw_posts if isinstance(row, dict)]
    if len(raw_post_ids) != len(raw_posts) or any(
        not isinstance(value, str) or POST_ID_RE.fullmatch(value) is None
        for value in raw_post_ids
    ):
        raise ValueError("v2_raw_snapshot_post_ids_invalid")
    raw_post_id_set = set(raw_post_ids)
    if len(raw_post_id_set) != len(raw_post_ids):
        raise ValueError("v2_raw_snapshot_post_ids_duplicate")
    if raw_post_id_set != target_ids - lineage_missing:
        raise ValueError("v2_raw_snapshot_post_identity_relation_invalid")
    if raw_post_id_set & set(posts):
        raise ValueError("v2_raw_snapshot_post_overlap")

    raw_comment_ids: list[str] = []
    for row in raw_comments:
        if not isinstance(row, dict):
            raise ValueError("v2_raw_snapshot_comment_row_invalid")
        comment_id = row.get("comment_id")
        post_id = row.get("post_id")
        if (
            not isinstance(comment_id, str)
            or COMMENT_ID_RE.fullmatch(comment_id) is None
            or post_id not in raw_post_id_set
        ):
            raise ValueError("v2_raw_snapshot_comment_identity_invalid")
        raw_comment_ids.append(comment_id)
    if len(set(raw_comment_ids)) != len(raw_comment_ids):
        raise ValueError("v2_raw_snapshot_comment_ids_duplicate")
    if set(raw_comment_ids) & set(comments):
        raise ValueError("v2_raw_snapshot_comment_overlap")
    if (
        accounting.get("canonical_post_count") != len(raw_posts)
        or accounting.get("canonical_comment_count") != len(raw_comments)
        or accounting.get("canonical_analysis_count") != len(analyses)
        or len(analyses) != len(raw_posts) + len(raw_comments)
    ):
        raise ValueError("v2_raw_snapshot_canonical_count_mismatch")

    snapshot_sha = _sha256(snapshot_path)
    dataset_id = f"reddit_v2_raw_{snapshot_sha[:16]}"
    coverage_counts: Counter[str] = Counter()
    for row in raw_posts:
        post_id = str(row["post_id"])
        coverage_grade = row.get("coverage_grade")
        if coverage_grade not in {"full", "partial"}:
            raise ValueError("v2_raw_snapshot_post_coverage_not_admissible")
        coverage_counts[str(coverage_grade)] += 1
        title, title_flags = _sanitize_text(str(row.get("title") or ""))
        content, content_flags = _sanitize_text(str(row.get("selftext") or ""))
        posts[post_id] = {
            "post_id": post_id,
            "reddit_id": f"t3_{post_id}",
            "title": title,
            "content": content,
            "subreddit": str(row.get("subreddit") or ""),
            "permalink": str(row.get("source_url") or ""),
            "created_at_utc": str(row["created_at_utc"]),
            "score": row.get("score"),
            "upvote_ratio": None,
            "num_comments_reported": row.get("num_comments_reported"),
            "parsed_comment_count": int(row.get("parsed_comment_count") or 0),
            "more_node_count": None,
            "structural_coverage_grade": str(coverage_grade),
            "comment_coverage_status": (
                "thread_complete" if coverage_grade == "full" else "observed_first_page"
            ),
            "matched_keywords": [],
            "media_urls": [],
            "author_pseudonym": _pseudonym(row.get("author_hash")),
            "pii_redaction_flags": sorted(set(title_flags + content_flags)),
            "source_occurrences": [
                _occurrence(
                    source_kind="tencent_v2_search_hydrated",
                    dataset_id=dataset_id,
                    collection_bucket="v2_discovery",
                    coverage_grade=str(coverage_grade),
                )
            ],
        }

    for row in raw_comments:
        comment_id = str(row["comment_id"])
        body, flags = _sanitize_text(str(row.get("body") or ""))
        comments[comment_id] = {
            "comment_id": comment_id,
            "reddit_id": comment_id,
            "post_id": str(row["post_id"]),
            "parent_id": row.get("parent_id"),
            "body": body,
            "created_at_utc": str(row["created_at_utc"]),
            "score": row.get("score"),
            "depth": row.get("depth"),
            "is_submitter": None if row.get("is_submitter") is None else bool(row.get("is_submitter")),
            "deleted_or_removed": bool(row.get("deleted_or_removed")),
            "is_bot": None,
            "bot_detection_status": "unavailable_in_v2_report_snapshot",
            "author_pseudonym": _pseudonym(row.get("author_hash")),
            "pii_redaction_flags": flags,
            "source_occurrences": [
                _occurrence(
                    source_kind="tencent_v2_search_hydrated",
                    dataset_id=dataset_id,
                    collection_bucket="v2_discovery",
                )
            ],
        }

    coverage_grade_counts = {
        "full": coverage_counts["full"],
        "partial": coverage_counts["partial"],
    }
    has_comment_coverage_debt = bool(
        lineage_missing
        or blockers["cursor_outstanding"]
        or blockers["page_pagination_outstanding"]
        or coverage_counts["partial"]
    )
    return {
        "admission_status": (
            "passed_with_partial_comment_coverage"
            if has_comment_coverage_debt
            else "passed_complete"
        ),
        "dataset_id": dataset_id,
        "snapshot_sha256": snapshot_sha,
        "identity_freeze_sha256": identity_sha,
        "identity_set_id": identity_set_id,
        "target_count": len(target_ids),
        "target_lf_sha256": target_hash,
        "admitted_posts": len(raw_posts),
        "admitted_observed_comments": len(raw_comments),
        "overlap_posts": 0,
        "overlap_comments": 0,
        "net_new_posts": len(raw_posts),
        "net_new_comments": len(raw_comments),
        "lineage_gap_count": len(lineage_missing),
        "lineage_gap_lf_sha256": _identity_hash(lineage_missing),
        "lineage_gap_post_ids": sorted(lineage_missing),
        "coverage_grade_counts": coverage_grade_counts,
        "cursor_outstanding": blockers.get("cursor_outstanding"),
        "page_pagination_outstanding": blockers.get("page_pagination_outstanding"),
        "comment_coverage_debt": {
            "cursor_outstanding": blockers["cursor_outstanding"],
            "page_pagination_outstanding": blockers[
                "page_pagination_outstanding"
            ],
            "partial_threads": coverage_counts["partial"],
        },
        "fusion_role": "disjoint_hydrated_discovery_append",
        "dedup_key": {"posts": "post_id", "comments": "comment_id"},
        "provider_call": False,
        "database_write": False,
        "production_merge": False,
        "live_send": False,
    }


def _append_existing_post_hydration(
    snapshot_path: Path,
    posts: dict[str, dict[str, Any]],
    comments: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Append only new comments for production-baseline posts."""

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if snapshot.get("schema_version") != "reddit_voc_existing_post_hydration_v1":
        raise ValueError("existing_hydration_schema_invalid")
    if snapshot.get("status") not in {
        "complete",
        "blocked_with_explicit_coverage_debt",
    }:
        raise ValueError("existing_hydration_status_invalid")
    for field in (
        "provider_call",
        "provider_attempt_made",
        "database_write",
        "remote_write",
        "production_merge",
        "deployment",
        "git_push",
        "live_send",
        "dingtalk",
    ):
        if snapshot.get(field) is not False:
            raise ValueError(f"existing_hydration_{field}_boundary_invalid")
    if snapshot.get("production_unchanged") is not True:
        raise ValueError("existing_hydration_production_boundary_invalid")
    privacy = snapshot.get("privacy")
    if (
        not isinstance(privacy, dict)
        or privacy.get("raw_payload_embedded") is not False
        or privacy.get("raw_username_embedded") is not False
        or privacy.get("private_artifact") is not True
    ):
        raise ValueError("existing_hydration_privacy_invalid")

    target = snapshot.get("target")
    baseline = snapshot.get("baseline_identity")
    if not isinstance(target, dict) or not isinstance(baseline, dict):
        raise ValueError("existing_hydration_baseline_invalid")
    base_post_ids_raw = baseline.get("base_post_ids")
    base_comment_ids_raw = baseline.get("base_comment_ids")
    if not isinstance(base_post_ids_raw, list) or not isinstance(
        base_comment_ids_raw, list
    ):
        raise ValueError("existing_hydration_baseline_ids_invalid")
    if any(
        not isinstance(value, str) or POST_ID_RE.fullmatch(value) is None
        for value in base_post_ids_raw
    ) or any(
        not isinstance(value, str) or COMMENT_ID_RE.fullmatch(value) is None
        for value in base_comment_ids_raw
    ):
        raise ValueError("existing_hydration_baseline_identity_invalid")
    base_post_ids = set(base_post_ids_raw)
    base_comment_ids = set(base_comment_ids_raw)
    if (
        len(base_post_ids) != len(base_post_ids_raw)
        or len(base_comment_ids) != len(base_comment_ids_raw)
        or target.get("base_post_count") != len(base_post_ids)
        or target.get("base_post_ids_lf_sha256") != _identity_hash(base_post_ids)
        or target.get("base_comment_count") != len(base_comment_ids)
        or target.get("base_comment_ids_lf_sha256")
        != _identity_hash(base_comment_ids)
    ):
        raise ValueError("existing_hydration_baseline_self_accounting_invalid")
    if not base_post_ids <= set(posts):
        raise ValueError("existing_hydration_baseline_post_missing")
    if not base_comment_ids <= set(comments):
        raise ValueError("existing_hydration_baseline_comment_missing")

    post_coverage = snapshot.get("post_coverage")
    if not isinstance(post_coverage, list):
        raise ValueError("existing_hydration_post_coverage_invalid")
    existing_post_ids: list[str] = []
    coverage_counts: Counter[str] = Counter()
    for row in post_coverage:
        if not isinstance(row, dict):
            raise ValueError("existing_hydration_post_coverage_row_invalid")
        post_id = row.get("post_id")
        grade = row.get("coverage_grade")
        if (
            not isinstance(post_id, str)
            or post_id not in base_post_ids
            or grade not in {"full", "partial", "not_observed"}
        ):
            raise ValueError("existing_hydration_post_coverage_value_invalid")
        existing_post_ids.append(post_id)
        coverage_counts[str(grade)] += 1
    existing_post_set = set(existing_post_ids)
    if (
        len(existing_post_set) != len(existing_post_ids)
        or target.get("existing_post_count") != len(existing_post_set)
        or target.get("existing_post_ids_lf_sha256")
        != _identity_hash(existing_post_set)
    ):
        raise ValueError("existing_hydration_existing_post_set_invalid")

    accounting = snapshot.get("accounting")
    blockers = accounting.get("blockers") if isinstance(accounting, dict) else None
    if not isinstance(accounting, dict) or not isinstance(blockers, dict):
        raise ValueError("existing_hydration_accounting_invalid")
    if (
        accounting.get("unaccounted_report_count") != 0
        or accounting.get("observed_identity_conserved") is not True
        or accounting.get("baseline_identity_conserved") is not True
    ):
        raise ValueError("existing_hydration_accounting_not_conserved")
    report_outcome_counts = accounting.get("report_outcome_counts")
    expected_report_outcomes = {
        "accepted_first_page",
        "accepted_reply",
        "accepted_duplicate",
        "rejected_invalid",
        "excluded_non_target",
    }
    if (
        not isinstance(report_outcome_counts, dict)
        or set(report_outcome_counts) != expected_report_outcomes
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in report_outcome_counts.values()
        )
        or accounting.get("accounted_report_count")
        != sum(report_outcome_counts.values())
        or accounting.get("comment_report_file_count")
        != accounting.get("accounted_report_count")
    ):
        raise ValueError("existing_hydration_report_outcome_invalid")
    for field in (
        "orphan_reply_reports",
        "cursor_cycles",
        "report_conflicts",
        "comment_conflicts",
    ):
        if blockers.get(field) != 0:
            raise ValueError(f"existing_hydration_{field}_not_admissible")
    failure_reason_counts = accounting.get("failure_reason_counts")
    allowed_failure_reasons = {
        "legacy_reply_source_chain_incomplete",
        "legacy_reply_source_predecessor_missing",
        "report_response_validation_failed",
    }
    if (
        not isinstance(failure_reason_counts, dict)
        or not set(failure_reason_counts) <= allowed_failure_reasons
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in failure_reason_counts.values()
        )
        or sum(failure_reason_counts.values()) != blockers.get("failed_reports")
    ):
        raise ValueError("existing_hydration_failure_reason_invalid")
    expected_coverage_counts = accounting.get("coverage_grade_counts")
    if expected_coverage_counts != {
        "full": coverage_counts["full"],
        "partial": coverage_counts["partial"],
        "not_observed": coverage_counts["not_observed"],
    }:
        raise ValueError("existing_hydration_coverage_count_mismatch")

    work_items = snapshot.get("coverage_work_items")
    if not isinstance(work_items, dict):
        raise ValueError("existing_hydration_coverage_work_invalid")
    first_page_missing = work_items.get("first_page_missing_post_ids")
    cursor_outstanding = work_items.get("cursor_outstanding")
    page_outstanding = work_items.get(
        "page_pagination_outstanding_post_ids"
    )
    failed_reports = work_items.get("failed_reports")
    partial_post_ids = work_items.get("partial_post_ids")
    not_observed_post_ids = work_items.get("not_observed_post_ids")
    if not all(
        isinstance(value, list)
        for value in (
            first_page_missing,
            cursor_outstanding,
            page_outstanding,
            failed_reports,
            partial_post_ids,
            not_observed_post_ids,
        )
    ):
        raise ValueError("existing_hydration_coverage_work_shape_invalid")
    if (
        len(first_page_missing) != blockers.get("first_page_missing")
        or len(cursor_outstanding) != blockers.get("cursor_outstanding")
        or len(page_outstanding) != blockers.get("page_pagination_outstanding")
        or len(failed_reports) != blockers.get("failed_reports")
        or len(partial_post_ids) != coverage_counts["partial"]
        or len(not_observed_post_ids) != coverage_counts["not_observed"]
    ):
        raise ValueError("existing_hydration_coverage_work_count_mismatch")
    post_id_work_lists = (
        first_page_missing,
        page_outstanding,
        partial_post_ids,
        not_observed_post_ids,
    )
    if any(
        not isinstance(value, str)
        or POST_ID_RE.fullmatch(value) is None
        or value not in existing_post_set
        for values in post_id_work_lists
        for value in values
    ):
        raise ValueError("existing_hydration_coverage_post_invalid")
    if any(len(values) != len(set(values)) for values in post_id_work_lists):
        raise ValueError("existing_hydration_coverage_post_duplicate")
    expected_partial_post_ids = {
        str(row["post_id"])
        for row in post_coverage
        if row["coverage_grade"] == "partial"
    }
    expected_not_observed_post_ids = {
        str(row["post_id"])
        for row in post_coverage
        if row["coverage_grade"] == "not_observed"
    }
    expected_page_outstanding = {
        str(row["post_id"])
        for row in post_coverage
        if row.get("page_has_next") is True
    }
    if (
        set(partial_post_ids) != expected_partial_post_ids
        or set(not_observed_post_ids) != expected_not_observed_post_ids
        or set(first_page_missing) != expected_not_observed_post_ids
        or set(page_outstanding) != expected_page_outstanding
    ):
        raise ValueError("existing_hydration_coverage_post_set_mismatch")
    if (
        accounting.get("first_page_missing_post_ids_lf_sha256")
        != _identity_hash(set(first_page_missing))
        or accounting.get("page_pagination_outstanding_post_ids_lf_sha256")
        != _identity_hash(set(page_outstanding))
    ):
        raise ValueError("existing_hydration_coverage_post_hash_mismatch")
    cursor_counts: Counter[str] = Counter()
    cursor_keys: list[str] = []
    for row in cursor_outstanding:
        if (
            not isinstance(row, dict)
            or row.get("post_id") not in existing_post_set
            or not isinstance(row.get("cursor_sha256"), str)
            or SHA256_RE.fullmatch(str(row["cursor_sha256"])) is None
        ):
            raise ValueError("existing_hydration_cursor_work_invalid")
        post_id = str(row["post_id"])
        cursor_counts[post_id] += 1
        cursor_keys.append(f"{post_id}\t{row['cursor_sha256']}")
    if (
        len(cursor_keys) != len(set(cursor_keys))
        or any(
            cursor_counts[str(row["post_id"])]
            != row.get("cursor_outstanding_count")
            for row in post_coverage
        )
        or accounting.get("cursor_outstanding_keys_lf_sha256")
        != _identity_hash(set(cursor_keys))
    ):
        raise ValueError("existing_hydration_cursor_work_mismatch")
    failed_reason_counts: Counter[str] = Counter()
    failed_post_counts: Counter[str] = Counter()
    failed_report_keys: list[str] = []
    for row in failed_reports:
        if not isinstance(row, dict):
            raise ValueError("existing_hydration_failed_report_invalid")
        reason = row.get("reason")
        post_id = row.get("post_id")
        if reason not in allowed_failure_reasons or post_id not in existing_post_set:
            raise ValueError("existing_hydration_failed_report_invalid")
        failed_reason_counts[str(reason)] += 1
        failed_post_counts[str(post_id)] += 1
        failed_report_keys.append(
            sha256(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        )
    if (
        dict(sorted(failed_reason_counts.items())) != failure_reason_counts
        or len(failed_report_keys) != len(set(failed_report_keys))
        or any(
            failed_post_counts[str(row["post_id"])]
            != row.get("failed_report_count")
            for row in post_coverage
        )
        or accounting.get("failed_report_keys_lf_sha256")
        != _identity_hash(set(failed_report_keys))
    ):
        raise ValueError("existing_hydration_failed_report_mismatch")

    raw_comments = snapshot.get("comments")
    if not isinstance(raw_comments, list):
        raise ValueError("existing_hydration_comments_invalid")
    raw_comment_ids: list[str] = []
    normalized: list[tuple[str, dict[str, Any]]] = []
    for row in raw_comments:
        if not isinstance(row, dict):
            raise ValueError("existing_hydration_comment_row_invalid")
        comment_id = row.get("comment_id")
        post_id = row.get("post_id")
        author_hash = row.get("author_hash")
        source_hashes = row.get("source_payload_sha256s")
        if (
            not isinstance(comment_id, str)
            or COMMENT_ID_RE.fullmatch(comment_id) is None
            or comment_id in base_comment_ids
            or post_id not in existing_post_set
            or post_id not in posts
            or not isinstance(row.get("body"), str)
            or not isinstance(row.get("created_at_utc"), str)
            or not str(row["created_at_utc"]).strip()
            or (
                author_hash is not None
                and (
                    not isinstance(author_hash, str)
                    or AUTHOR_HASH_RE.fullmatch(author_hash) is None
                )
            )
            or not isinstance(source_hashes, list)
            or not source_hashes
            or any(
                not isinstance(value, str)
                or SHA256_RE.fullmatch(value) is None
                for value in source_hashes
            )
        ):
            raise ValueError("existing_hydration_comment_parent_invalid")
        raw_comment_ids.append(comment_id)
        body, flags = _sanitize_text(str(row["body"]))
        normalized.append(
            (
                comment_id,
                {
                    "comment_id": comment_id,
                    "reddit_id": comment_id,
                    "post_id": str(post_id),
                    "parent_id": row.get("parent_id"),
                    "body": body,
                    "created_at_utc": str(row["created_at_utc"]),
                    "score": row.get("score"),
                    "depth": row.get("depth"),
                    "is_submitter": (
                        None
                        if row.get("is_submitter") is None
                        else bool(row.get("is_submitter"))
                    ),
                    "deleted_or_removed": bool(row.get("deleted_or_removed")),
                    "is_bot": None,
                    "bot_detection_status": (
                        "unavailable_in_existing_post_hydration"
                    ),
                    "author_pseudonym": _pseudonym(author_hash),
                    "pii_redaction_flags": flags,
                    "source_occurrences": [],
                },
            )
        )
    raw_comment_set = set(raw_comment_ids)
    if (
        len(raw_comment_set) != len(raw_comment_ids)
        or accounting.get("gross_new_comment_count") != len(raw_comment_set)
        or accounting.get("gross_new_comment_ids_lf_sha256")
        != _identity_hash(raw_comment_set)
    ):
        raise ValueError("existing_hydration_comment_identity_mismatch")

    snapshot_sha = _sha256(snapshot_path)
    dataset_id = f"reddit_existing_hydration_{snapshot_sha[:16]}"
    preceding_overlap = 0
    body_conflicts = 0
    inserted = 0
    for comment_id, candidate in normalized:
        existing = comments.get(comment_id)
        if existing is not None:
            if existing.get("post_id") != candidate["post_id"]:
                raise ValueError("existing_hydration_comment_link_conflict")
            preceding_overlap += 1
            body_conflicts += existing.get("body") != candidate["body"]
            continue
        candidate["source_occurrences"] = [
            _occurrence(
                source_kind="tencent_existing_post_comment_hydration",
                dataset_id=dataset_id,
                collection_bucket="existing_post_hydration",
            )
        ]
        comments[comment_id] = candidate
        inserted += 1
    if inserted + preceding_overlap != len(raw_comment_set):
        raise ValueError("existing_hydration_insert_accounting_mismatch")

    return {
        "admission_status": (
            "passed_complete"
            if snapshot["status"] == "complete"
            else "passed_with_explicit_comment_coverage_debt"
        ),
        "dataset_id": dataset_id,
        "snapshot_sha256": snapshot_sha,
        "baseline_post_count": len(base_post_ids),
        "baseline_post_ids_lf_sha256": _identity_hash(base_post_ids),
        "baseline_comment_count": len(base_comment_ids),
        "baseline_comment_ids_lf_sha256": _identity_hash(base_comment_ids),
        "input_posts": 0,
        "input_comments": len(raw_comment_set),
        "materialized_comments": inserted,
        "release_candidate_comments": len(raw_comment_set),
        "preceding_overlap_comments": preceding_overlap,
        "preceding_body_conflicts": body_conflicts,
        "overlap_posts": 0,
        "overlap_comments": preceding_overlap,
        "net_new_posts": 0,
        "net_new_comments": inserted,
        "coverage_grade_counts": {
            "full": coverage_counts["full"],
            "partial": coverage_counts["partial"],
            "not_observed": coverage_counts["not_observed"],
        },
        "comment_coverage_debt": {
            "first_page_missing": len(first_page_missing),
            "cursor_outstanding": len(cursor_outstanding),
            "page_pagination_outstanding": len(page_outstanding),
            "failed_reports": len(failed_reports),
            "partial_threads": coverage_counts["partial"],
            "not_observed_threads": coverage_counts["not_observed"],
            "failure_reason_counts": failure_reason_counts,
        },
        "coverage_work_items": work_items,
        "fusion_role": "existing_post_comment_delta_after_v2",
        "dedup_key": {"posts": "post_id", "comments": "comment_id"},
        "precedence_policy": "preceding_canonical_wins",
        "provider_call": False,
        "database_write": False,
        "production_merge": False,
        "live_send": False,
    }


def _comment_coverage_debt_union(
    v2_snapshot_path: Path,
    hydration_meta: dict[str, Any],
) -> dict[str, Any]:
    v2 = json.loads(v2_snapshot_path.read_text(encoding="utf-8"))
    accounting = v2.get("accounting")
    raw_posts = v2.get("posts")
    if not isinstance(accounting, dict) or not isinstance(raw_posts, list):
        raise ValueError("coverage_union_v2_shape_invalid")
    v2_first = accounting.get("first_page_missing_post_ids")
    v2_cursor = accounting.get("cursor_outstanding")
    v2_page = accounting.get("page_pagination_outstanding_post_ids")
    v2_failed = accounting.get("failed_reports")
    if not all(
        isinstance(value, list)
        for value in (v2_first, v2_cursor, v2_page, v2_failed)
    ):
        raise ValueError("coverage_union_v2_work_items_invalid")
    hydration_work = hydration_meta.get("coverage_work_items")
    if not isinstance(hydration_work, dict):
        raise ValueError("coverage_union_hydration_work_items_invalid")

    first_page_missing = set(str(value) for value in v2_first)
    first_page_missing.update(
        str(value)
        for value in hydration_work["first_page_missing_post_ids"]
    )
    cursor_keys = {
        f"{row['post_id']}\t{row['cursor_sha256']}"
        for row in v2_cursor
        if isinstance(row, dict)
    }
    cursor_keys.update(
        f"{row['post_id']}\t{row['cursor_sha256']}"
        for row in hydration_work["cursor_outstanding"]
        if isinstance(row, dict)
    )
    page_outstanding = set(str(value) for value in v2_page)
    page_outstanding.update(
        str(value)
        for value in hydration_work[
            "page_pagination_outstanding_post_ids"
        ]
    )
    failure_keys = {
        sha256(
            json.dumps(
                row,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        for row in [*v2_failed, *hydration_work["failed_reports"]]
    }
    partial_posts = {
        str(row["post_id"])
        for row in raw_posts
        if isinstance(row, dict) and row.get("coverage_grade") == "partial"
    }
    partial_posts.update(
        str(value) for value in hydration_work["partial_post_ids"]
    )
    not_observed_posts = set(first_page_missing)

    return {
        "first_page_missing": len(first_page_missing),
        "first_page_missing_lf_sha256": _identity_hash(first_page_missing),
        "cursor_outstanding": len(cursor_keys),
        "cursor_outstanding_lf_sha256": _identity_hash(cursor_keys),
        "page_pagination_outstanding": len(page_outstanding),
        "page_pagination_outstanding_lf_sha256": _identity_hash(
            page_outstanding
        ),
        "failed_reports": len(failure_keys),
        "failed_reports_lf_sha256": _identity_hash(failure_keys),
        "partial_threads": len(partial_posts),
        "partial_thread_ids_lf_sha256": _identity_hash(partial_posts),
        "not_observed_threads": len(not_observed_posts),
        "not_observed_thread_ids_lf_sha256": _identity_hash(
            not_observed_posts
        ),
        "source_counts": {
            "v2": {
                "first_page_missing": len(v2_first),
                "cursor_outstanding": len(v2_cursor),
                "page_pagination_outstanding": len(v2_page),
                "failed_reports": len(v2_failed),
            },
            "existing_post_hydration": hydration_meta[
                "comment_coverage_debt"
            ],
        },
        "key_union_not_numeric_sum": True,
    }


def _enrich(
    posts: dict[str, dict[str, Any]],
    comments: dict[str, dict[str, Any]],
    *,
    analysis_code_sha256: str,
    tag_dictionary: TagDictionary,
    product_resolver: ProductEntityResolver,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
    tuple[TagContext, ...],
]:
    comments_by_post: dict[str, list[dict[str, Any]]] = defaultdict(list)
    quarantine: list[dict[str, Any]] = []
    for comment in comments.values():
        if comment["post_id"] not in posts:
            quarantine.append(
                {
                    "comment_id": comment["comment_id"],
                    "missing_post_id": comment["post_id"],
                    "reason": "post_attach_orphan",
                    "source_kinds": sorted(
                        {
                            occurrence["source_kind"]
                            for occurrence in comment["source_occurrences"]
                        }
                    ),
                }
            )
            continue
        comments_by_post[comment["post_id"]].append(comment)

    linked_comment_ids = {
        comment["comment_id"]
        for rows in comments_by_post.values()
        for comment in rows
    }
    post_items = list(posts.items())
    post_texts = [f"{post['title']}\n{post['content']}" for _, post in post_items]
    post_resolution_batch = product_resolver.resolve_many(post_texts)
    observed_tag_contexts: set[TagContext] = set()
    for (post_id, post), entity_text, resolution in zip(
        post_items,
        post_texts,
        post_resolution_batch.results,
        strict=True,
    ):
        subreddit = str(post.get("subreddit") or "").strip()
        if subreddit:
            post["subreddit"] = subreddit
            post["subreddit_normalization_status"] = "source_value"
        else:
            post["subreddit"] = "unknown"
            post["subreddit_normalization_status"] = "source_empty_to_unknown"
        linked = sorted(
            comments_by_post.get(post_id, []),
            key=lambda row: (str(row["created_at_utc"]), str(row["comment_id"])),
        )
        discussion_text = "\n".join(
            [post["title"], post["content"], *(comment["body"] for comment in linked)]
        )
        post["linked_comment_count"] = len(linked)
        coverage_grade = str(post["structural_coverage_grade"])
        try:
            post["comment_coverage_status"] = (
                COMMENT_COVERAGE_STATUS_BY_GRADE[coverage_grade]
            )
        except KeyError as exc:
            raise ValueError(
                f"unsupported structural coverage grade: {coverage_grade}"
            ) from exc
        post["event_created_at_utc"] = post["created_at_utc"]
        reported = post["num_comments_reported"]
        post["comment_count_gap"] = None if reported is None else int(reported) - len(linked)
        if reported is None:
            post["count_completeness_status"] = "unknown"
        elif int(reported) == len(linked):
            post["count_completeness_status"] = "equal"
        elif int(reported) > len(linked):
            post["count_completeness_status"] = "parsed_lower"
        else:
            post["count_completeness_status"] = "parsed_higher"
        post["collection_buckets"] = sorted(
            {
                occurrence["collection_bucket"]
                for occurrence in post["source_occurrences"]
                if occurrence["collection_bucket"]
            }
        )
        post["source_kinds"] = sorted(
            {occurrence["source_kind"] for occurrence in post["source_occurrences"]}
        )
        product_bindings = [
            binding.to_record() for binding in resolution.product_bindings
        ]
        tag_contexts = tag_contexts_from_product_bindings(product_bindings)
        observed_tag_contexts.update(tag_contexts)
        mentioned_brands = _mentioned_brands(entity_text)
        post["mentioned_brands"] = mentioned_brands
        post["discussion_mentioned_brands"] = _mentioned_brands(discussion_text)
        post["product_bindings"] = product_bindings
        post["brand_binding"] = _entity_brand_binding(
            mentioned_brands, product_bindings
        )
        post["brand_binding_scope"] = "entity_level_governed_context"
        post["analysis"] = _analysis(entity_text, code_sha256=analysis_code_sha256)
        post["tagging"] = tag_dictionary.extract_for_contexts(
            entity_text,
            contexts=tag_contexts,
        )
        post["evidence_id"] = f"post:{post_id}"

    linked_comments: list[dict[str, Any]] = []
    comment_items = [
        (comment_id, comments[comment_id]) for comment_id in sorted(linked_comment_ids)
    ]
    comment_resolution_batch = product_resolver.resolve_many(
        comment["body"] for _, comment in comment_items
    )
    for (comment_id, comment), resolution in zip(
        comment_items,
        comment_resolution_batch.results,
        strict=True,
    ):
        parent_id = str(comment.get("parent_id") or "")
        if parent_id.startswith("t1_"):
            comment["parent_link_status"] = (
                "linked" if parent_id in linked_comment_ids else "parent_comment_missing"
            )
        elif parent_id.startswith("t3_"):
            comment["parent_link_status"] = (
                "linked" if parent_id[3:] == comment["post_id"] else "parent_post_mismatch"
            )
        else:
            comment["parent_link_status"] = "unknown"
        comment["include_in_voc_metrics"] = not comment["deleted_or_removed"] and (
            comment["is_bot"] is not True
        )
        comment["event_created_at_utc"] = comment["created_at_utc"]
        product_bindings = [
            binding.to_record() for binding in resolution.product_bindings
        ]
        tag_contexts = tag_contexts_from_product_bindings(product_bindings)
        observed_tag_contexts.update(tag_contexts)
        mentioned_brands = _mentioned_brands(comment["body"])
        comment["mentioned_brands"] = mentioned_brands
        comment["product_bindings"] = product_bindings
        comment["brand_binding"] = _entity_brand_binding(
            mentioned_brands, product_bindings
        )
        comment["brand_binding_scope"] = "entity_level_governed_context"
        comment["analysis"] = _analysis(
            comment["body"], code_sha256=analysis_code_sha256
        )
        comment["tagging"] = tag_dictionary.extract_for_contexts(
            comment["body"],
            contexts=tag_contexts,
        )
        comment["evidence_id"] = f"comment:{comment_id}"
        linked_comments.append(comment)
    post_coverage = post_resolution_batch.coverage.to_record()
    comment_coverage = comment_resolution_batch.coverage.to_record()
    product_resolution = {
        **product_resolver.metadata.to_record(),
        "status": "resolved",
        "coverage": {
            "posts": post_coverage,
            "comments": comment_coverage,
            "combined": _combine_product_coverage(
                post_coverage, comment_coverage
            ),
        },
    }
    return (
        sorted(posts.values(), key=lambda row: (row["created_at_utc"], row["post_id"])),
        linked_comments,
        sorted(quarantine, key=lambda row: row["comment_id"]),
        product_resolution,
        tuple(sorted(observed_tag_contexts)),
    )


def _aggregates(
    posts: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    quarantine: list[dict[str, Any]],
    *,
    tag_dictionary: TagDictionary,
) -> dict[str, Any]:
    post_sentiment = Counter(post["analysis"]["sentiment_label"] for post in posts)
    post_topics = Counter(post["analysis"]["topic"] for post in posts)
    included_comments = [row for row in comments if row["include_in_voc_metrics"]]
    comment_sentiment = Counter(
        comment["analysis"]["sentiment_label"] for comment in included_comments
    )
    pain_points = Counter(
        point
        for post in posts
        for point in post["analysis"]["pain_points"]
    )
    pain_points.update(
        point
        for comment in included_comments
        for point in comment["analysis"]["pain_points"]
    )
    subreddit_posts = Counter(post["subreddit"] for post in posts)
    subreddit_comments = Counter(comment["post_id"] for comment in comments)
    subreddit_comment_counts = Counter()
    post_subreddit = {post["post_id"]: post["subreddit"] for post in posts}
    for post_id, count in subreddit_comments.items():
        subreddit_comment_counts[post_subreddit[post_id]] += count
    month_posts = Counter(post["created_at_utc"][:7] for post in posts)
    bucket_posts = Counter(
        bucket for post in posts for bucket in post["collection_buckets"]
    )
    brand_mentions = Counter(
        brand for post in posts for brand in post["mentioned_brands"]
    )
    total_brand_mentions = sum(brand_mentions.values())
    pii = Counter(
        flag
        for post in posts
        for flag in post["pii_redaction_flags"]
    )
    pii.update(
        flag
        for comment in comments
        for flag in comment["pii_redaction_flags"]
    )
    coverage = Counter(post["structural_coverage_grade"] for post in posts)
    completeness = Counter(post["count_completeness_status"] for post in posts)
    parent_status = Counter(comment["parent_link_status"] for comment in comments)
    post_tags = Counter(
        tag_id for post in posts for tag_id in post["tagging"]["aspect_tag_ids"]
    )
    comment_tags = Counter(
        tag_id
        for comment in included_comments
        for tag_id in comment["tagging"]["aspect_tag_ids"]
    )
    post_brand_tags = Counter(
        tag_id for post in posts for tag_id in post["tagging"]["brand_tag_ids"]
    )
    comment_brand_tags = Counter(
        tag_id
        for comment in included_comments
        for tag_id in comment["tagging"]["brand_tag_ids"]
    )
    tag_dimensions: dict[str, Counter[str]] = {
        field: Counter()
        for field in [
            "theme",
            "sentiment",
            "default_priority",
            "risk_level",
            "problem_type",
            "intent_type",
            "dept_owner",
        ]
    }
    for tag_id, count in (post_tags + comment_tags).items():
        rule = tag_dictionary.by_id[tag_id]
        metadata = dict(rule.fields)
        for field, counter in tag_dimensions.items():
            counter[metadata[field]] += count
    all_tag_ids = set(post_tags) | set(comment_tags)
    top_tags = []
    for tag_id in sorted(
        all_tag_ids,
        key=lambda item: (-(post_tags[item] + comment_tags[item]), item),
    ):
        rule = tag_dictionary.by_id[tag_id]
        top_tags.append(
            {
                "tag_id": tag_id,
                "name_cn": rule.name_cn,
                "name_en": rule.name_en,
                "theme": rule.theme,
                "tag_sentiment": rule.sentiment,
                "post_entities": post_tags[tag_id],
                "comment_entities": comment_tags[tag_id],
                "total_entities": post_tags[tag_id] + comment_tags[tag_id],
            }
        )
    post_dates = [str(row["created_at_utc"]) for row in posts]
    comment_dates = [str(row["created_at_utc"]) for row in comments]
    return {
        "schema_version": "reddit_voc_site_aggregates_v1",
        "headline": {
            "unique_posts": len(posts),
            "linked_comments": len(comments),
            "quarantined_comments": len(quarantine),
            "comments_in_voc_metrics": len(included_comments),
            "analysis_covered_posts": sum(bool(post.get("analysis")) for post in posts),
            "analysis_covered_comments": sum(
                bool(comment.get("analysis")) for comment in comments
            ),
            "posts_with_rule_tags": sum(
                bool(post["tagging"]["tag_ids"]) for post in posts
            ),
            "comments_with_rule_tags_in_voc_metrics": sum(
                bool(comment["tagging"]["tag_ids"])
                for comment in included_comments
            ),
            "posts_with_aspect_tags": sum(
                bool(post["tagging"]["aspect_tag_ids"]) for post in posts
            ),
            "comments_with_aspect_tags": sum(
                bool(comment["tagging"]["aspect_tag_ids"])
                for comment in included_comments
            ),
        },
        "date_range": {
            "posts": [min(post_dates), max(post_dates)] if post_dates else [],
            "comments": [min(comment_dates), max(comment_dates)] if comment_dates else [],
        },
        "post_sentiment": dict(sorted(post_sentiment.items())),
        "comment_sentiment": dict(sorted(comment_sentiment.items())),
        "post_topics": dict(post_topics.most_common()),
        "pain_points": dict(pain_points.most_common()),
        "subreddit_posts": dict(subreddit_posts.most_common()),
        "subreddit_comments": dict(subreddit_comment_counts.most_common()),
        "monthly_posts": dict(sorted(month_posts.items())),
        "collection_bucket_posts": dict(bucket_posts.most_common()),
        "brand_sample_mentions": [
            {
                "brand": brand,
                "posts": count,
                "sample_mention_share": round(count / total_brand_mentions, 6)
                if total_brand_mentions
                else 0.0,
            }
            for brand, count in brand_mentions.most_common()
        ],
        "coverage_grade": dict(sorted(coverage.items())),
        "count_completeness_status": dict(sorted(completeness.items())),
        "parent_link_status": dict(sorted(parent_status.items())),
        "pii_redaction_counts": dict(sorted(pii.items())),
        "tagging": {
            "dictionary_version": tag_dictionary.version,
            "posts_with_rule_tags": sum(
                bool(post["tagging"]["tag_ids"]) for post in posts
            ),
            "comments_with_rule_tags": sum(
                bool(comment["tagging"]["tag_ids"])
                for comment in included_comments
            ),
            "posts_with_aspect_tags": sum(
                bool(post["tagging"]["aspect_tag_ids"]) for post in posts
            ),
            "comments_with_aspect_tags": sum(
                bool(comment["tagging"]["aspect_tag_ids"])
                for comment in included_comments
            ),
            "post_rule_aspect_assignments": sum(post_tags.values()),
            "comment_rule_aspect_assignments": sum(comment_tags.values()),
            "post_ambiguous_keyword_matches": sum(
                len(post["tagging"]["ambiguous_keyword_matches"]) for post in posts
            ),
            "comment_ambiguous_keyword_matches": sum(
                len(comment["tagging"]["ambiguous_keyword_matches"])
                for comment in comments
            ),
            "post_negated_keyword_matches": sum(
                len(post["tagging"]["negated_keyword_matches"]) for post in posts
            ),
            "comment_negated_keyword_matches": sum(
                len(comment["tagging"]["negated_keyword_matches"])
                for comment in comments
            ),
            "post_low_specificity_keyword_matches": sum(
                len(post["tagging"]["low_specificity_keyword_matches"])
                for post in posts
            ),
            "comment_low_specificity_keyword_matches": sum(
                len(comment["tagging"]["low_specificity_keyword_matches"])
                for comment in comments
            ),
            "entities_with_detected_spu": sum(
                bool(post["tagging"]["context"]["detected_spu_ids"])
                for post in posts
            )
            + sum(
                bool(comment["tagging"]["context"]["detected_spu_ids"])
                for comment in comments
            ),
            "top_tags": top_tags,
            "dictionary_brand_mentions": [
                {
                    "tag_id": tag_id,
                    "name_cn": tag_dictionary.by_id[tag_id].name_cn,
                    "name_en": tag_dictionary.by_id[tag_id].name_en,
                    "post_entities": post_brand_tags[tag_id],
                    "comment_entities": comment_brand_tags[tag_id],
                    "total_entities": post_brand_tags[tag_id]
                    + comment_brand_tags[tag_id],
                }
                for tag_id in sorted(
                    set(post_brand_tags) | set(comment_brand_tags),
                    key=lambda item: (
                        -(post_brand_tags[item] + comment_brand_tags[item]),
                        item,
                    ),
                )
            ],
            "dimensions": {
                field: dict(counter.most_common())
                for field, counter in tag_dimensions.items()
            },
        },
        "metric_notes": {
            "brand_sample_mentions": "Directed sample mention occurrences; not market share.",
            "comments_in_voc_metrics": "Excludes known archive bots and deleted/removed comments; production bot identity is unavailable.",
            "structural_coverage_grade": "Full means no visible MoreComments node, not guaranteed absolute completeness.",
            "tagging": "Only unambiguous multi-token dictionary phrases or verified brand aliases become provisional lexical rule matches; shared, negated, and low-specificity phrases remain auditable candidates.",
            "tag_sentiment": "Dictionary tag sentiment is an aspect attribute and does not override entity-level sentiment analysis.",
            "brand_tag_sentiment": "Brand mention tags are separated from aspect tags and excluded from tag sentiment dimensions.",
        },
    }


def _write_compact(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _write_canonical_compact(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--generated-at-utc")
    parser.add_argument("--archive-dir", type=Path)
    parser.add_argument("--historical-db", type=Path)
    parser.add_argument("--production-snapshot", type=Path)
    parser.add_argument("--staging-snapshot", type=Path)
    parser.add_argument("--v2-raw-snapshot", type=Path)
    parser.add_argument("--v2-identity-freeze", type=Path)
    parser.add_argument("--existing-post-hydration-snapshot", type=Path)
    parser.add_argument("--tag-dictionary", type=Path)
    parser.add_argument("--product-entity-ledger", type=Path)
    parser.add_argument("--v3-canonical-root", type=Path)
    parser.add_argument("--v3-canonical-manifest-sha256")
    parser.add_argument("--v3-validation-receipt", type=Path)
    parser.add_argument("--v3-validation-receipt-sha256")
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def _snapshot_mode(args: argparse.Namespace) -> str:
    v3_present = [getattr(args, name, None) is not None for name in V3_ARGUMENTS]
    if any(v3_present) and not all(v3_present):
        raise ValueError("v3_arguments_must_be_all_or_none")
    if all(v3_present):
        supplied_legacy = [
            name for name in LEGACY_INPUT_ARGUMENTS if getattr(args, name, None) is not None
        ]
        if supplied_legacy:
            raise ValueError(
                "v3_mode_rejects_legacy_inputs:" + ",".join(supplied_legacy)
            )
        return "v3"
    missing_legacy = [
        name
        for name in LEGACY_INPUT_ARGUMENTS
        if name != "existing_post_hydration_snapshot"
        and getattr(args, name, None) is None
    ]
    if missing_legacy:
        raise ValueError(
            "legacy_mode_missing_required_inputs:" + ",".join(missing_legacy)
        )
    return "legacy"


def _count(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{label}_invalid")
    return value


def build_v3_site_state_snapshot(
    *,
    dataset_version: str,
    generated_at_utc: str,
    canonical_root: Path,
    canonical_manifest_sha256: str,
    validation_receipt: Path,
    validation_receipt_sha256: str,
    project_root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    """Preflight and materialize a manifest-only V3 state vector in memory."""

    from scripts.build_reddit_v3_voc_facts import (
        _decode,
        _load_canonical,
        _read_project_file,
    )
    from reddit_voc.v3_metric_eligibility import (
        canonical_json_bytes as eligibility_json_bytes,
        parse_metric_eligibility_policy,
        summarize_metric_eligibility,
    )
    from reddit_voc.v3_voc_facts import materialize_voc_materialization

    normalized_dataset_version = str(dataset_version).strip()
    if DATASET_VERSION_RE.fullmatch(normalized_dataset_version) is None:
        raise ValueError("dataset_version_invalid")
    normalized_generated_at_utc = _generated_at_utc(generated_at_utc)
    root = Path(project_root).resolve(strict=True)
    policy_path = root / V3_METRIC_ELIGIBILITY_POLICY.relative_to(PROJECT_ROOT)
    policy_payload = _read_project_file(
        policy_path,
        project_root=root,
        label="V3 metric eligibility policy",
    )
    if _sha256_bytes(policy_payload) != V3_METRIC_ELIGIBILITY_POLICY_SHA256:
        raise ValueError("v3_metric_eligibility_policy_sha256_mismatch")
    policy_value = _decode(policy_payload, "V3 metric eligibility policy")
    if (
        not isinstance(policy_value, dict)
        or policy_payload != eligibility_json_bytes(policy_value) + b"\n"
    ):
        raise ValueError("v3_metric_eligibility_policy_not_canonical")
    policy = parse_metric_eligibility_policy(policy_value)
    (
        canonical_manifest,
        posts,
        comments,
        quarantine,
        canonical_manifest_payload,
        validation_receipt_payload,
    ) = _load_canonical(
        canonical_root,
        expected_manifest_sha256=canonical_manifest_sha256,
        receipt_path=validation_receipt,
        expected_receipt_sha256=validation_receipt_sha256,
        project_root=root,
    )
    validation_receipt_value = json.loads(validation_receipt_payload.decode("utf-8"))
    materialization = materialize_voc_materialization(
        posts,
        comments,
        quarantine=quarantine,
    )
    vocs = materialization.vocs
    exclusions = materialization.exclusions
    voc_ids = {row.canonical_entity_id for row in vocs}
    exclusion_ids = {row.canonical_entity_id for row in exclusions}
    canonical_ids = voc_ids | exclusion_ids
    analysis_ready_vocs = tuple(
        row
        for row in vocs
        if row.analysis_text_status == "ready"
        and (
            row.voc_type == "post_voc"
            or row.context_status == "ready"
        )
    )
    analysis_ready_ids = {row.canonical_entity_id for row in analysis_ready_vocs}
    raw_metric_summary = summarize_metric_eligibility(
        analysis_ready_vocs,
        policy,
        period=V3_PERIOD,
        scope=V3_SCOPE,
    )
    expected_metric_summary_fields = {
        "membership_rows",
        "eligible_rows",
        "excluded_rows",
        "denominator_true_rows",
        "numerator_true_rows",
        "distinct_eligible_post_vocs",
        "distinct_eligible_comment_context_vocs",
        "distinct_eligible_voc_facts",
        "eligible_identity_lf_sha256",
        "period",
        "scope",
    }
    if (
        not isinstance(raw_metric_summary, dict)
        or set(raw_metric_summary) != expected_metric_summary_fields
    ):
        raise ValueError("v3_metric_eligibility_summary_contract_invalid")
    metric_summary = dict(raw_metric_summary)

    raw_canonical_counts = canonical_manifest.get("canonical_counts")
    if not isinstance(raw_canonical_counts, dict):
        raise ValueError("v3_canonical_counts_invalid")
    canonical_counts: dict[str, int] = {
        key: _count(raw_canonical_counts.get(key), f"v3_canonical_{key}")
        for key in (
            "posts",
            "comments_jsonl",
            "linked_comments",
            "unresolved_parent_comments",
            "quarantined_comments",
            "stored_comments",
        )
    }
    canonical_counts["total_identities"] = (
        canonical_counts["posts"] + canonical_counts["stored_comments"]
    )
    canonical_state: dict[str, object] = {
        **canonical_counts,
        "identity_lf_sha256": _identity_hash(canonical_ids),
    }

    post_vocs = tuple(row for row in vocs if row.voc_type == "post_voc")
    comment_vocs = tuple(
        row for row in vocs if row.voc_type == "comment_context_voc"
    )
    ready_post_vocs = tuple(
        row for row in analysis_ready_vocs if row.voc_type == "post_voc"
    )
    ready_comment_vocs = tuple(
        row
        for row in analysis_ready_vocs
        if row.voc_type == "comment_context_voc"
    )
    reason_counts: Counter[str] = Counter(
        reason for row in exclusions for reason in row.reason_codes
    )
    excluded_posts = sum(row.entity_type == "post" for row in exclusions)
    excluded_comments = sum(row.entity_type == "comment" for row in exclusions)
    day_vocs = tuple(row for row in vocs if row.event_time_precision == "day")
    instant_or_hour_vocs = tuple(
        row for row in vocs if row.event_time_precision in {"instant", "hour"}
    )
    missing_event_time_vocs = tuple(
        row for row in vocs if row.event_time_precision is None
    )

    fusion_accounting = {
        "fusion_mode": "complete_canonical_union",
        "legacy_append": False,
    }
    files: dict[str, object] = {}
    checks = {
        "canonical_manifest_and_receipt_exactly_bound": (
            _sha256_bytes(canonical_manifest_payload)
            == canonical_manifest_sha256
            and _sha256_bytes(validation_receipt_payload)
            == validation_receipt_sha256
        ),
        "canonical_identity_conservation": (
            len(canonical_ids) == canonical_counts["total_identities"]
            and canonical_counts["comments_jsonl"]
            == canonical_counts["linked_comments"]
            + canonical_counts["unresolved_parent_comments"]
            and canonical_counts["stored_comments"]
            == canonical_counts["comments_jsonl"]
            + canonical_counts["quarantined_comments"]
        ),
        "voc_and_exclusion_identity_partition": (
            not (voc_ids & exclusion_ids)
            and len(voc_ids) + len(exclusion_ids)
            == canonical_counts["total_identities"]
        ),
        "analysis_ready_subset_of_voc_facts": analysis_ready_ids <= voc_ids,
        "metric_eligible_subset_of_analysis_ready": (
            _count(
                metric_summary.get("distinct_eligible_voc_facts"),
                "v3_distinct_eligible_voc_facts",
            )
            <= len(analysis_ready_ids)
        ),
        "complete_canonical_union_not_legacy_append": (
            fusion_accounting
            == {"fusion_mode": "complete_canonical_union", "legacy_append": False}
        ),
        "floating_day_preserved_without_fabricated_utc": all(
            row.event_created_at_utc is None
            and row.source_calendar_date is not None
            for row in day_vocs
        ),
        "public_projection_not_prematurely_emitted": files == {},
        "privacy_sensitive_rows_not_emitted": files == {},
        "side_effect_boundaries_preserved": V3_BOUNDARIES
        == {
            "database_write": False,
            "deploy": False,
            "live_send": False,
            "production_unchanged": True,
            "provider_call": False,
            "remote_write": False,
        },
    }
    if not all(checks.values()):
        raise ValueError(f"v3_site_state_checks_failed:{checks}")

    validation_receipt_document = cast(
        dict[str, Any], validation_receipt_value
    )
    manifest = {
        "schema_version": "reddit_voc_site_state_manifest_v3",
        "dataset_version": normalized_dataset_version,
        "generated_at_utc": normalized_generated_at_utc,
        "delivery_mode": "isolated_v3_state_snapshot",
        "artifact_stage": "v3_state_vector_only",
        "public_projection_complete": False,
        "release_candidate": False,
        "inputs": {
            "canonical_dataset_id": canonical_manifest["dataset_id"],
            "canonical_manifest_sha256": canonical_manifest_sha256,
            "canonical_validation_receipt_sha256": validation_receipt_sha256,
            "metric_eligibility_policy_sha256": (
                V3_METRIC_ELIGIBILITY_POLICY_SHA256
            ),
            "metric_eligibility_policy_version": policy.policy_version,
        },
        "upstream_lifecycle": {
            "canonical_manifest_status": canonical_manifest["status"],
            "canonical_independent_validation_status": canonical_manifest[
                "independent_validation_status"
            ],
            "canonical_consumption_status": canonical_manifest[
                "consumption_status"
            ],
            "validation_status": validation_receipt_document["status"],
            "validation_consumption_status": validation_receipt_document[
                "consumption_status"
            ],
            "promotable": False,
        },
        "fusion_accounting": fusion_accounting,
        "state_vector": {
            "canonical": canonical_state,
            "voc_facts": {
                "post_vocs": len(post_vocs),
                "comment_context_vocs": len(comment_vocs),
                "total_vocs": len(vocs),
                "identity_lf_sha256": _identity_hash(voc_ids),
            },
            "analysis_ready": {
                "post_vocs": len(ready_post_vocs),
                "comment_context_vocs": len(ready_comment_vocs),
                "total_vocs": len(analysis_ready_vocs),
                "identity_lf_sha256": _identity_hash(analysis_ready_ids),
            },
            "metric_eligibility": metric_summary,
            "exclusions": {
                "excluded_identities": len(exclusions),
                "excluded_post_identities": excluded_posts,
                "excluded_comment_identities": excluded_comments,
                "reason_counts": dict(sorted(reason_counts.items())),
                "identity_lf_sha256": _identity_hash(exclusion_ids),
            },
            "time_precision": {
                "day_precision_vocs": len(day_vocs),
                "instant_or_hour_precision_vocs": len(instant_or_hour_vocs),
                "missing_event_time_vocs": len(missing_event_time_vocs),
            },
        },
        "files": files,
        "checks": checks,
        "all_checks_passed": True,
        "boundaries": dict(V3_BOUNDARIES),
    }
    return manifest


def _sha256_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _build_snapshot(
    args: argparse.Namespace,
    *,
    output_dir: Path,
    generated_at_utc: str,
) -> dict[str, Any]:
    dataset_version = str(args.dataset_version).strip()
    if DATASET_VERSION_RE.fullmatch(dataset_version) is None:
        raise ValueError("dataset_version_invalid")

    archive_dir = args.archive_dir.resolve(strict=True)
    historical_db = args.historical_db.resolve(strict=True)
    production_snapshot = args.production_snapshot.resolve(strict=True)
    staging_snapshot = args.staging_snapshot.resolve(strict=True)
    v2_raw_snapshot = args.v2_raw_snapshot.resolve(strict=True)
    v2_identity_freeze = args.v2_identity_freeze.resolve(strict=True)
    existing_post_hydration_snapshot = (
        None
        if args.existing_post_hydration_snapshot is None
        else args.existing_post_hydration_snapshot.resolve(strict=True)
    )
    tag_dictionary_path = args.tag_dictionary.resolve(strict=True)
    product_entity_ledger_path = args.product_entity_ledger.resolve(strict=True)

    analyzer_path = Path(__file__).resolve().parents[1] / "src/reddit_voc/analyzer.py"
    analysis_code_sha = _sha256(analyzer_path)
    tag_dictionary_sha = _sha256(tag_dictionary_path)
    tag_dictionary = TagDictionary.from_csv(tag_dictionary_path)
    product_entity_ledger_sha = _sha256(product_entity_ledger_path)
    if product_entity_ledger_sha != EXPECTED_PRODUCT_LEDGER_SHA256:
        raise ValueError("product_entity_ledger_sha256_mismatch")
    product_resolver = ProductEntityResolver.from_ledger(
        product_entity_ledger_path
    )
    if product_resolver.metadata.ledger_sha256 != product_entity_ledger_sha:
        raise ValueError("product_entity_resolver_ledger_sha256_mismatch")
    posts, comments, raw_authors, archive_meta = _load_archive(archive_dir)
    historical_meta = _append_historical_occurrences(historical_db, posts, comments)
    production_meta = _append_production(production_snapshot, posts, comments)
    staging_meta = _append_isolated_staging(staging_snapshot, posts, comments)
    v2_meta = _append_v2_raw_snapshot(
        v2_raw_snapshot,
        v2_identity_freeze,
        posts,
        comments,
    )
    hydration_meta = (
        None
        if existing_post_hydration_snapshot is None
        else _append_existing_post_hydration(
            existing_post_hydration_snapshot,
            posts,
            comments,
        )
    )

    additive_sources = [archive_meta, production_meta, staging_meta, v2_meta]
    if hydration_meta is not None:
        additive_sources.append(hydration_meta)
    derived_stored_posts = sum(int(row["net_new_posts"]) for row in additive_sources)
    derived_stored_comments = sum(
        int(row["net_new_comments"]) for row in additive_sources
    )
    (
        public_posts,
        public_comments,
        quarantine,
        product_resolution,
        observed_tag_contexts,
    ) = _enrich(
        posts,
        comments,
        analysis_code_sha256=analysis_code_sha,
        tag_dictionary=tag_dictionary,
        product_resolver=product_resolver,
    )
    tag_dictionary_profile = _tag_dictionary_context_profile(
        tag_dictionary, observed_tag_contexts
    )
    product_resolution["observed_tag_contexts"] = tag_dictionary_profile[
        "observed_contexts"
    ]
    aggregates = _aggregates(
        public_posts,
        public_comments,
        quarantine,
        tag_dictionary=tag_dictionary,
    )

    checks = {
        "post_count_derived_from_source_identity_sets": (
            len(posts) == len(public_posts) == derived_stored_posts
        ),
        "stored_comment_count_derived_from_source_identity_sets": (
            len(comments) == derived_stored_comments
        ),
        "linked_plus_quarantine_equals_stored_comments": (
            len(public_comments) + len(quarantine) == len(comments)
        ),
        "post_ids_unique": len({row["post_id"] for row in public_posts})
        == len(public_posts),
        "comment_ids_unique": len({row["comment_id"] for row in public_comments})
        == len(public_comments),
        "all_comments_have_posts": all(
            row["post_id"] in {post["post_id"] for post in public_posts}
            for row in public_comments
        ),
        "all_posts_analyzed": all(row.get("analysis") for row in public_posts),
        "all_linked_comments_analyzed": all(
            row.get("analysis") for row in public_comments
        ),
        "all_posts_tag_processed": all(row.get("tagging") for row in public_posts),
        "all_linked_comments_tag_processed": all(
            row.get("tagging") for row in public_comments
        ),
        "all_entities_have_product_bindings_field": all(
            isinstance(row.get("product_bindings"), list)
            for row in [*public_posts, *public_comments]
        ),
        "all_entities_have_explicit_reddit_event_time": all(
            row.get("event_created_at_utc") == row.get("created_at_utc")
            for row in [*public_posts, *public_comments]
        ),
        "all_posts_have_governed_comment_coverage_status": all(
            row.get("comment_coverage_status")
            == COMMENT_COVERAGE_STATUS_BY_GRADE.get(
                str(row.get("structural_coverage_grade"))
            )
            for row in public_posts
        ),
        "all_posts_have_nonempty_controlled_subreddit": all(
            isinstance(row.get("subreddit"), str)
            and bool(str(row["subreddit"]).strip())
            and row.get("subreddit_normalization_status")
            in {"source_value", "source_empty_to_unknown"}
            for row in public_posts
        ),
        "all_entities_use_governed_spu_binding": all(
            row["tagging"]["context"]["spu_binding_mode"]
            == "governed_explicit"
            for row in [*public_posts, *public_comments]
        ),
        "all_brand_bindings_governed": all(
            row.get("brand_binding") in BRAND_BINDINGS
            for row in [*public_posts, *public_comments]
        ),
        "product_resolution_ledger_exact": (
            product_resolution["ledger_sha256"]
            == EXPECTED_PRODUCT_LEDGER_SHA256
            == product_entity_ledger_sha
        ),
        "product_resolution_coverage_conserved": all(
            product_resolution["coverage"][scope]["is_conserved"]
            for scope in ("posts", "comments", "combined")
        ),
        "all_rule_tag_ids_governed": all(
            tag_id in tag_dictionary.by_id
            for row in [*public_posts, *public_comments]
            for tag_id in row["tagging"]["tag_ids"]
        ),
        "provider_calls_false": all(
            not row["analysis"]["provider_call"] for row in public_posts
        )
        and all(not row["analysis"]["provider_call"] for row in public_comments),
        "historical_integrity": historical_meta["integrity_check"] == "ok",
        "production_integrity": production_meta["integrity_check"] == "ok",
        "staging_integrity": staging_meta["integrity_check"] == "ok",
        "historical_is_lineage_only_subset": (
            historical_meta["net_new_posts"] == 0
            and historical_meta["net_new_comments"] == 0
            and historical_meta["overlap_posts"] == historical_meta["input_posts"]
            and historical_meta["overlap_comments"]
            == historical_meta["input_comments"]
        ),
        "staging_comment_links_do_not_conflict": (
            staging_meta["comment_link_conflicts"] == 0
        ),
        "v2_identity_contract_passed": (
            bool(v2_meta["identity_set_id"])
            and v2_meta["target_count"]
            == v2_meta["admitted_posts"] + v2_meta["lineage_gap_count"]
            and SHA256_RE.fullmatch(v2_meta["target_lf_sha256"]) is not None
            and SHA256_RE.fullmatch(v2_meta["lineage_gap_lf_sha256"])
            is not None
        ),
        "v2_comment_coverage_debt_explicit": (
            isinstance(v2_meta["cursor_outstanding"], int)
            and isinstance(v2_meta["page_pagination_outstanding"], int)
            and v2_meta["comment_coverage_debt"]["partial_threads"]
            == v2_meta["coverage_grade_counts"].get("partial", 0)
        ),
        "analysis_version_compatible": historical_meta["analysis_versions"]
        == [ANALYSIS_VERSION]
        and production_meta["analysis_versions"] == [ANALYSIS_VERSION],
        "staging_analysis_version_compatible": staging_meta["analysis_versions"]
        == [ANALYSIS_VERSION],
    }
    if hydration_meta is not None:
        checks.update(
            {
                "existing_post_hydration_baseline_preserved": (
                    hydration_meta["baseline_post_count"]
                    <= len(posts)
                    and hydration_meta["baseline_comment_count"]
                    <= len(comments)
                ),
                "existing_post_hydration_comment_accounting": (
                    hydration_meta["release_candidate_comments"]
                    == hydration_meta["preceding_overlap_comments"]
                    + hydration_meta["net_new_comments"]
                    and hydration_meta["input_comments"]
                    == hydration_meta["release_candidate_comments"]
                ),
                "existing_post_hydration_no_post_insertion": (
                    hydration_meta["input_posts"] == 0
                    and hydration_meta["net_new_posts"] == 0
                ),
            }
        )
    if not all(checks.values()):
        raise ValueError(f"site snapshot checks failed: {checks}")

    posts_path = output_dir / "posts.json"
    comments_path = output_dir / "comments.json"
    aggregates_path = output_dir / "aggregates.json"
    quarantine_path = output_dir / "quarantine.json"
    tag_dictionary_output_path = output_dir / "tag-dictionary.json"
    _write_compact(posts_path, public_posts)
    _write_compact(comments_path, public_comments)
    _write_compact(aggregates_path, aggregates)
    _write_compact(quarantine_path, quarantine)
    _write_compact(
        tag_dictionary_output_path,
        {
            "schema_version": "reddit_voc_tag_dictionary_v1",
            "dictionary_version": tag_dictionary.version,
            "dictionary_sha256": tag_dictionary_sha,
            "profile": tag_dictionary_profile,
            "rules": tag_dictionary.executable_dictionary_records_for_contexts(
                observed_tag_contexts
            ),
        },
    )

    forbidden_private_keys = re.compile(
        r'"(?:author|author_hash|author_fullname|body_html|selftext_html)"\s*:'
    )
    public_payloads = [
        posts_path,
        comments_path,
        aggregates_path,
        quarantine_path,
        tag_dictionary_output_path,
    ]
    no_forbidden_private_keys = all(
        not forbidden_private_keys.search(path.read_text(encoding="utf-8"))
        for path in public_payloads
    )
    no_explicit_username_mentions = all(
        not USERNAME_MENTION_RE.search(path.read_text(encoding="utf-8"))
        and not AT_USERNAME_RE.search(path.read_text(encoding="utf-8"))
        for path in [posts_path, comments_path]
    )
    checks["no_forbidden_private_keys"] = no_forbidden_private_keys
    checks["no_explicit_username_mentions"] = no_explicit_username_mentions
    if not no_forbidden_private_keys or not no_explicit_username_mentions:
        raise ValueError("public snapshot contains a forbidden privacy signal")

    files = {
        path.name: {"bytes": path.stat().st_size, "sha256": _sha256(path)}
        for path in public_payloads
    }
    source_boundaries = {
        "imported_archive": archive_meta,
        "historical_canonical": historical_meta,
        "tencent_production_primary": production_meta,
        "tencent_isolated_staging": staging_meta,
        "tencent_v2_search_hydrated": v2_meta,
    }
    load_order = [
        "imported_archive",
        "historical_canonical_lineage_only",
        "tencent_production_primary",
        "tencent_isolated_staging_overlay",
        "tencent_v2_search_hydrated_disjoint_append",
    ]
    fusion_accounting: dict[str, Any] = {
        "load_order": load_order,
        "post_identity_key": "post_id",
        "comment_identity_key": "comment_id",
        "expected_from_source_net_new": {
            "posts": derived_stored_posts,
            "stored_comments": derived_stored_comments,
        },
        "actual_canonical": {
            "posts": len(public_posts),
            "stored_comments": len(comments),
            "linked_comments": len(public_comments),
            "quarantined_comments": len(quarantine),
        },
        "v2_comment_coverage_debt": v2_meta["comment_coverage_debt"],
        "coverage_debt_is_not_zero_filled": True,
    }
    manifest_schema = "reddit_voc_site_snapshot_manifest_v1"
    if hydration_meta is not None:
        assert existing_post_hydration_snapshot is not None
        manifest_schema = "reddit_voc_site_snapshot_manifest_v2"
        source_boundaries["tencent_existing_post_comment_hydration"] = (
            hydration_meta
        )
        load_order.append("tencent_existing_post_comment_hydration_append")
        fusion_accounting["existing_post_hydration_coverage_debt"] = (
            hydration_meta["comment_coverage_debt"]
        )
        fusion_accounting["comment_coverage_debt_union"] = (
            _comment_coverage_debt_union(v2_raw_snapshot, hydration_meta)
        )
    manifest = {
        "schema_version": manifest_schema,
        "dataset_version": dataset_version,
        "generated_at_utc": generated_at_utc,
        "delivery_mode": "versioned_static_snapshot",
        "source_boundaries": source_boundaries,
        "fusion_accounting": fusion_accounting,
        "canonical_counts": {
            "posts": len(public_posts),
            "stored_comments": len(comments),
            "linked_comments": len(public_comments),
            "quarantined_comments": len(quarantine),
        },
        "analysis": {
            "version": ANALYSIS_VERSION,
            "code_sha256": analysis_code_sha,
            "keyword_rules_sha256": keyword_rules_sha256(),
            "provider_call": False,
            "recomputed_for_all_public_entities": True,
        },
        "tagging": {
            "dictionary_version": tag_dictionary.version,
            "dictionary_sha256": tag_dictionary_sha,
            "dictionary_row_count": tag_dictionary_profile["row_count"],
            "base_eligible_rule_count": len(
                tag_dictionary.select_rules(
                    product_line="", voc_category="", spu_ids=()
                )
            ),
            "executable_rule_count": tag_dictionary_profile[
                "eligible_rule_count"
            ],
            "cross_sentiment_shared_keywords": tag_dictionary_profile[
                "cross_sentiment_keyword_count"
            ],
            "product_entity_resolution": product_resolution,
            "spu_rule_gate": "governed_product_entity_ledger",
            "matching_policy": "unambiguous multi-token exact phrase or verified brand alias, with negation gate",
            "consumer_phrases_used": False,
            "entity_sentiment_overridden": False,
            "semantic_validation_run": False,
            "labels_provisional": True,
            "provider_call": False,
        },
        "privacy": {
            "raw_author_fields_present": False,
            "author_display": "stable_pseudonym",
            "html_fields_present": False,
            "contact_patterns_redacted": True,
            "known_archive_bots_excluded_from_voc_metrics": True,
            "raw_archive_public": False,
            "production_private_snapshot_mode": "0600",
        },
        "semantic_boundaries": {
            "collection_bucket_is_brand_ownership": False,
            "brand_metric_label": "sample mention share",
            "market_share_supported": False,
            "roi_supported": False,
            "response_time_supported": False,
            "global_product_category_imputed": False,
            "product_category_resolution_status": "governed_product_entity_resolver_v1",
            "product_category_analysis_supported": True,
            "product_family_analysis_supported": True,
            "exact_spu_analysis_supported_only_for_approved_bindings": True,
            "product_entity_ledger_sha256": product_entity_ledger_sha,
            "created_at_utc_is_reddit_event_time": True,
            "canonical_event_time_field": "event_created_at_utc",
            "comment_coverage_status_mapping": {
                "full": "thread_complete",
                "partial": "observed_first_page",
                "post_only": "post_only",
            },
            "thread_complete_means_no_observed_more_node_not_absolute_reddit_completeness": True,
            "empty_subreddit_normalization": {
                "replacement": "unknown",
                "normalized_post_count": sum(
                    row.get("subreddit_normalization_status")
                    == "source_empty_to_unknown"
                    for row in public_posts
                ),
                "unknown_excluded_from_community_breadth_gate": True,
            },
        },
        "files": files,
        "checks": checks,
        "all_checks_passed": all(checks.values()),
        "raw_author_count_used_only_for_privacy_bot_audit": len(raw_authors),
        "production_unchanged": True,
        "provider_call": False,
        "live_send": False,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "status": "passed",
        "dataset_version": dataset_version,
        "posts": len(public_posts),
        "linked_comments": len(public_comments),
        "quarantined_comments": len(quarantine),
        "analysis_covered": len(public_posts) + len(public_comments),
        "tagged_posts": aggregates["tagging"]["posts_with_rule_tags"],
        "tagged_comments": aggregates["tagging"]["comments_with_rule_tags"],
        "all_checks_passed": manifest["all_checks_passed"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    mode = _snapshot_mode(args)
    output_dir = args.output_dir.expanduser().absolute()
    generated_at_utc = _generated_at_utc(args.generated_at_utc)
    if mode == "v3":
        assert args.v3_canonical_root is not None
        assert args.v3_canonical_manifest_sha256 is not None
        assert args.v3_validation_receipt is not None
        assert args.v3_validation_receipt_sha256 is not None
        manifest = build_v3_site_state_snapshot(
            dataset_version=args.dataset_version,
            generated_at_utc=generated_at_utc,
            canonical_root=args.v3_canonical_root,
            canonical_manifest_sha256=args.v3_canonical_manifest_sha256,
            validation_receipt=args.v3_validation_receipt,
            validation_receipt_sha256=args.v3_validation_receipt_sha256,
        )
        result = {
            "status": "passed_v3_state_snapshot",
            "dataset_version": manifest["dataset_version"],
            "artifact_stage": manifest["artifact_stage"],
            "public_projection_complete": False,
            "release_candidate": False,
            "all_checks_passed": True,
        }
        with _fresh_output_directory(output_dir) as staging_dir:
            _write_canonical_compact(staging_dir / "manifest.json", manifest)
        result["output_dir"] = str(output_dir)
        print(json.dumps(result, sort_keys=True))
        return 0
    with _fresh_output_directory(output_dir) as staging_dir:
        result = _build_snapshot(
            args,
            output_dir=staging_dir,
            generated_at_utc=generated_at_utc,
        )
    result["output_dir"] = str(output_dir)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
