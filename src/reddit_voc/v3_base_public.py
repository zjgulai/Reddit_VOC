from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any
from urllib.parse import urlparse

from .analyzer import analyze_text
from .permalink import permalink_targets_entity
from .tag_dictionary import TagDictionary
from .v3_periodized_metrics import (
    UNATTESTED_REASON,
    _calendar_date,
    validate_coverage_attestation,
)


MANIFEST_SCHEMA = "reddit_voc_site_snapshot_manifest_v3"
AGGREGATES_SCHEMA = "reddit_voc_site_aggregates_v3"
POST_SCHEMA = "reddit_voc_public_post_v3"
COMMENT_SCHEMA = "reddit_voc_public_comment_v3"
PUBLIC_DICTIONARY_SCHEMA = "reddit_voc_public_tag_dictionary_v1"
DELIVERY_MODE = "versioned_static_snapshot"
CANONICAL_SCHEMA_PAIRS = {
    "reddit_voc_canonical_snapshot_manifest_v1":
        "reddit_voc_canonical_snapshot_validation_receipt_v1",
    "reddit_voc_canonical_snapshot_manifest_v2":
        "reddit_voc_canonical_snapshot_validation_receipt_v2",
}
DATASET_VERSION_RE = re.compile(r"^reddit_voc_site_snapshot_[a-z0-9][a-z0-9_-]{2,127}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
POST_ID_RE = re.compile(r"^[a-z0-9]{5,10}$")
COMMENT_ID_RE = re.compile(r"^t1_[a-z0-9]+$")
SUBREDDIT_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d() .-]{7,}\d)(?!\w)")
USERNAME_MENTION_RE = re.compile(r"(?i)(?<![A-Za-z0-9_])/?u/[A-Za-z0-9_-]{2,30}")
AT_USERNAME_RE = re.compile(r"(?<![A-Za-z0-9_.+-])@[A-Za-z0-9_-]{2,30}")
PUBLIC_FILES = (
    "aggregates-public.json",
    "posts-public.json",
    "comments-public.json",
    "tag-dictionary-public.json",
)
CANONICAL_FILES = (
    "posts.jsonl",
    "comments.jsonl",
    "unresolved-parent-ledger.jsonl",
    "quarantine.jsonl",
)
BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}
ANALYSIS_FIELDS = (
    "analysis_version",
    "sentiment_label",
    "sentiment_score",
    "topic",
    "severity",
    "confidence",
    "pain_points",
    "provider_call",
)
TAG_MATCH_FIELDS = (
    "tag_id",
    "tag_scope",
    "tag_sentiment",
    "evidence_keywords",
    "evidence_count",
    "match_strength",
    "validation_status",
)
PRODUCT_BINDING_FIELDS = (
    "brand_id",
    "category",
    "product_family",
    "exact_spu",
    "binding_level",
    "match_type",
    "matched_alias",
    "governance_status",
    "governance_reason",
)
PUBLIC_RULE_FIELDS = (
    "tag_id",
    "name_cn",
    "name_en",
    "theme",
    "sentiment",
    "tag_scope",
)


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def sha256_path(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_contract(path: Path) -> dict[str, Any]:
    return {"bytes": path.stat().st_size, "sha256": sha256_path(path)}


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label}_object_required")
    return value


def _require_count(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{label}_non_negative_integer_required")
    return value


def _require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{label}_sha256_required")
    return value


def _parse_generated_at(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("generated_at_utc_invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("generated_at_utc_timezone_missing")
    return parsed.astimezone(timezone.utc).isoformat()


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label}_unsafe_or_missing")
    try:
        return _require_object(json.loads(path.read_text(encoding="utf-8")), label)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label}_invalid_json") from exc


def _load_jsonl(path: Path, label: str) -> list[dict[str, Any]]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label}_unsafe_or_missing")
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{label}_invalid_jsonl_line_{line_number}") from exc
            rows.append(_require_object(value, f"{label}_line_{line_number}"))
    return rows


def _verify_file_contract(root: Path, name: str, contract: Any) -> None:
    expected = _require_object(contract, f"canonical_file_{name}")
    path = root / name
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"canonical_file_missing:{name}")
    if _require_count(expected.get("rows"), f"canonical_file_{name}_rows") < 0:
        raise AssertionError("unreachable")
    if _require_count(expected.get("bytes"), f"canonical_file_{name}_bytes") != path.stat().st_size:
        raise ValueError(f"canonical_file_bytes_mismatch:{name}")
    if _require_sha(expected.get("sha256"), f"canonical_file_{name}") != sha256_path(path):
        raise ValueError(f"canonical_file_sha256_mismatch:{name}")


def load_canonical(
    canonical_root: Path,
    *,
    expected_manifest_sha256: str,
    validation_receipt: Path,
    expected_validation_receipt_sha256: str,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    root = canonical_root.resolve(strict=True)
    if not root.is_dir() or root.is_symlink():
        raise ValueError("canonical_root_unsafe")
    _require_sha(expected_manifest_sha256, "expected_manifest")
    _require_sha(expected_validation_receipt_sha256, "expected_validation_receipt")
    manifest_path = root / "manifest.json"
    if sha256_path(manifest_path) != expected_manifest_sha256:
        raise ValueError("canonical_manifest_sha256_mismatch")
    if sha256_path(validation_receipt) != expected_validation_receipt_sha256:
        raise ValueError("canonical_validation_receipt_sha256_mismatch")
    manifest = _load_json(manifest_path, "canonical_manifest")
    receipt = _load_json(validation_receipt, "canonical_validation_receipt")
    manifest_schema = manifest.get("schema_version")
    if manifest_schema not in CANONICAL_SCHEMA_PAIRS:
        raise ValueError("canonical_manifest_schema_unsupported")
    if (
        receipt.get("schema_version") != CANONICAL_SCHEMA_PAIRS[manifest_schema]
        or receipt.get("status") != "passed"
    ):
        raise ValueError("canonical_validation_receipt_not_passed")
    if receipt.get("bundle_manifest_sha256") != expected_manifest_sha256:
        raise ValueError("canonical_receipt_manifest_binding_mismatch")
    if receipt.get("canonical_counts") != manifest.get("canonical_counts"):
        raise ValueError("canonical_receipt_count_binding_mismatch")
    files = _require_object(manifest.get("files"), "canonical_files")
    for name in CANONICAL_FILES:
        _verify_file_contract(root, name, files.get(name))
    posts = _load_jsonl(root / "posts.jsonl", "canonical_posts")
    comments = _load_jsonl(root / "comments.jsonl", "canonical_comments")
    unresolved = _load_jsonl(
        root / "unresolved-parent-ledger.jsonl", "canonical_unresolved_parent"
    )
    quarantine = _load_jsonl(root / "quarantine.jsonl", "canonical_quarantine")
    counts = _require_object(manifest.get("canonical_counts"), "canonical_counts")
    expected_counts = {
        key: _require_count(counts.get(key), f"canonical_count_{key}")
        for key in (
            "posts",
            "comments_jsonl",
            "linked_comments",
            "unresolved_parent_comments",
            "quarantined_comments",
            "stored_comments",
        )
    }
    linked = [row for row in comments if row.get("comment_state") == "linked"]
    unresolved_rows = [
        row for row in comments if row.get("comment_state") == "unresolved_parent"
    ]
    if len(posts) != expected_counts["posts"]:
        raise ValueError("canonical_post_count_mismatch")
    if len(comments) != expected_counts["comments_jsonl"]:
        raise ValueError("canonical_comment_jsonl_count_mismatch")
    if len(linked) != expected_counts["linked_comments"]:
        raise ValueError("canonical_linked_comment_count_mismatch")
    if len(unresolved_rows) != expected_counts["unresolved_parent_comments"]:
        raise ValueError("canonical_unresolved_comment_count_mismatch")
    if len(unresolved) != expected_counts["unresolved_parent_comments"]:
        raise ValueError("canonical_unresolved_ledger_count_mismatch")
    if len(quarantine) != expected_counts["quarantined_comments"]:
        raise ValueError("canonical_quarantine_count_mismatch")
    if expected_counts["comments_jsonl"] != (
        expected_counts["linked_comments"]
        + expected_counts["unresolved_parent_comments"]
    ):
        raise ValueError("canonical_comment_state_conservation_failed")
    if expected_counts["stored_comments"] != (
        expected_counts["comments_jsonl"] + expected_counts["quarantined_comments"]
    ):
        raise ValueError("canonical_stored_comment_conservation_failed")
    return manifest, posts, linked, unresolved, quarantine


def _sanitize_text(value: Any) -> tuple[str, list[str]]:
    text = value if isinstance(value, str) else ""
    flags: list[str] = []
    text, count = EMAIL_RE.subn("[redacted_email]", text)
    if count:
        flags.append("email")
    text, count = PHONE_RE.subn("[redacted_phone_candidate]", text)
    if count:
        flags.append("phone_candidate")
    text, count = USERNAME_MENTION_RE.subn("u/[redacted_user]", text)
    if count:
        flags.append("username_mention")
    text, count = AT_USERNAME_RE.subn("@[redacted_user]", text)
    if count and "username_mention" not in flags:
        flags.append("username_mention")
    return text, flags


def _reddit_url(
    value: Any, label: str, *, subreddit_hint: Any = None
) -> tuple[str, str]:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label}_reddit_url_missing")
    parsed = urlparse(value)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme != "https" or host not in {
        "reddit.com",
        "www.reddit.com",
        "old.reddit.com",
        "redd.it",
        "i.redd.it",
        "v.redd.it",
    }:
        raise ValueError(f"{label}_reddit_url_invalid")
    parts = [part for part in parsed.path.split("/") if part]
    if isinstance(subreddit_hint, str) and subreddit_hint.strip():
        return value, subreddit_hint.strip()
    if len(parts) < 2 or parts[0].casefold() != "r" or not parts[1]:
        raise ValueError(f"{label}_subreddit_missing")
    return value, parts[1]


def _governed_post_permalink(
    value: Any, *, post_id: str, subreddit: Any
) -> tuple[str, str, str]:
    if not isinstance(subreddit, str) or SUBREDDIT_RE.fullmatch(subreddit) is None:
        raise ValueError(f"post_{post_id}_subreddit_invalid")
    # A permalink must identify THIS post. Accepting any reddit URL let 90 rows carry
    # `https://i.redd.it/<hash>.jpeg` (the post's image) and
    # `https://www.reddit.com/gallery/<id>` (its gallery) as if they were evidence
    # links, so clicking a quote opened an image instead of the source thread.
    # Check identity first; fall back to the canonical identity URL, which Reddit
    # resolves without a title slug.
    if permalink_targets_entity(value, post_id):
        try:
            permalink, normalized_subreddit = _reddit_url(
                value,
                f"post_{post_id}",
                subreddit_hint=subreddit,
            )
            return permalink, normalized_subreddit, "source_permalink"
        except ValueError as exc:
            if not str(exc).endswith("_reddit_url_invalid"):
                raise
    return (
        f"https://www.reddit.com/r/{subreddit}/comments/{post_id}",
        subreddit,
        "canonical_reddit_identity",
    )


def _analysis(text: str, source: Any) -> dict[str, Any]:
    if isinstance(source, dict) and all(field in source for field in ANALYSIS_FIELDS):
        result = {field: source[field] for field in ANALYSIS_FIELDS}
        if result["provider_call"] is not False:
            raise ValueError("source_analysis_provider_call_not_false")
        return result
    analysis = analyze_text(text)
    return {
        "analysis_version": "local_rules_v1",
        "sentiment_label": analysis.sentiment_label,
        "sentiment_score": analysis.sentiment_score,
        "topic": analysis.topic,
        "severity": analysis.severity,
        "confidence": analysis.confidence,
        "pain_points": analysis.pain_points,
        "provider_call": False,
    }


def _tagging(text: str, source: Any, dictionary: TagDictionary) -> dict[str, Any]:
    raw = (
        source
        if isinstance(source, dict)
        else dictionary.extract_for_contexts(text, contexts=[("", "", ())])
    )
    for field in (
        "dictionary_version",
        "tag_ids",
        "aspect_tag_ids",
        "brand_tag_ids",
        "matches",
        "semantic_validation_status",
    ):
        if field not in raw:
            raise ValueError(f"tagging_field_missing:{field}")
    matches = raw["matches"]
    if not isinstance(matches, list):
        raise ValueError("tagging_matches_not_list")
    return {
        "dictionary_version": raw["dictionary_version"],
        "tag_ids": list(raw["tag_ids"]),
        "aspect_tag_ids": list(raw["aspect_tag_ids"]),
        "brand_tag_ids": list(raw["brand_tag_ids"]),
        "matches": [
            {field: match[field] for field in TAG_MATCH_FIELDS}
            for match in matches
        ],
        "semantic_validation_status": raw["semantic_validation_status"],
    }


def _product_bindings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    projected: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        row = _require_object(raw, f"product_binding_{index}")
        if any(field not in row for field in PRODUCT_BINDING_FIELDS):
            raise ValueError(f"product_binding_fields_missing:{index}")
        projected.append({field: row[field] for field in PRODUCT_BINDING_FIELDS})
    return projected


def _event_time(record: dict[str, Any], label: str) -> dict[str, Any]:
    if record.get("event_time_precision") == "day":
        day = record.get("source_calendar_date")
        if not isinstance(day, str) or DAY_RE.fullmatch(day) is None:
            raise ValueError(f"{label}_source_calendar_date_invalid")
        return {
            "created_at_utc": day,
            "event_created_at_utc": None,
            "source_calendar_date": day,
            "event_time_precision": "day",
        }
    instant = record.get("event_created_at_utc") or record.get("created_at_utc")
    if not isinstance(instant, str) or "T" not in instant:
        raise ValueError(f"{label}_instant_event_time_invalid")
    try:
        parsed = datetime.fromisoformat(instant.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label}_instant_event_time_invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label}_instant_event_time_timezone_missing")
    normalized = parsed.astimezone(timezone.utc).isoformat()
    return {
        "created_at_utc": normalized,
        "event_created_at_utc": normalized,
        "source_calendar_date": None,
        "event_time_precision": "instant",
    }


def _derived_mentions(text: str) -> list[str]:
    match = analyze_text(text).keyword_match
    return sorted(set([*match.brands, *match.competitors]))


def _brand_binding(mentions: list[str]) -> str:
    has_momcozy = any(value.casefold() == "momcozy" for value in mentions)
    has_other = any(value.casefold() != "momcozy" for value in mentions)
    if has_momcozy and has_other:
        return "multi_brand_context"
    if has_momcozy:
        return "momcozy_sentence_bound"
    if has_other:
        return "competitor_sentence_bound"
    return "brand_unbound"


def _display_title(text: str, source_summary: Any) -> tuple[str, str]:
    if isinstance(source_summary, str) and source_summary.strip():
        value = " ".join(source_summary.split())
        return value[:180], "source_summary"
    value = " ".join(text.split())
    if not value:
        return "正文不可用", "content_unavailable"
    return value[:177] + ("…" if len(value) > 177 else ""), "content_excerpt"


def _project_post(
    row: dict[str, Any],
    *,
    linked_count: int,
    dictionary: TagDictionary,
) -> dict[str, Any]:
    post_id = row.get("post_id")
    if not isinstance(post_id, str) or POST_ID_RE.fullmatch(post_id) is None:
        raise ValueError("canonical_post_id_invalid")
    record = _require_object(row.get("record"), f"post_{post_id}_record")
    governed = "content" in record
    raw_text = record.get("content") if governed else record.get("source_text")
    content, redactions = _sanitize_text(raw_text)
    if governed:
        title, title_redactions = _sanitize_text(record.get("title"))
        title_basis = "source_title"
        permalink, subreddit, permalink_basis = _governed_post_permalink(
            record.get("permalink"),
            post_id=post_id,
            subreddit=record.get("subreddit"),
        )
    else:
        title, title_basis = _display_title(content, record.get("source_summary"))
        title, title_redactions = _sanitize_text(title)
        permalink, subreddit = _reddit_url(record.get("source_url"), f"post_{post_id}")
        permalink_basis = "source_url"
    redactions.extend(flag for flag in title_redactions if flag not in redactions)
    event_time = _event_time(record, f"post_{post_id}")
    analysis = _analysis(content, record.get("analysis"))
    tagging = _tagging(content, record.get("tagging"), dictionary)
    governed_mentions = record.get("mentioned_brands")
    mentions = (
        list(governed_mentions)
        if governed and isinstance(governed_mentions, list)
        else _derived_mentions(content)
    )
    annotations = record.get("source_annotations")
    score = (
        record.get("score")
        if governed
        else annotations.get("engagement_count")
        if isinstance(annotations, dict)
        else None
    )
    return {
        "schema_version": POST_SCHEMA,
        "post_id": post_id,
        "reddit_id": f"t3_{post_id}",
        "title": title,
        "title_basis": title_basis,
        "content": content,
        "subreddit": subreddit,
        "permalink": permalink,
        "permalink_basis": permalink_basis,
        **event_time,
        "score": score if isinstance(score, (int, float)) and not isinstance(score, bool) else None,
        "upvote_ratio": record.get("upvote_ratio") if governed else None,
        "num_comments_reported": record.get("num_comments_reported") if governed else None,
        "linked_comment_count": linked_count,
        "structural_coverage_grade": (
            record.get("structural_coverage_grade") or "source_observed"
        ),
        "count_completeness_status": (
            record.get("count_completeness_status") or "source_rows_only"
        ),
        "comment_coverage_status": (
            record.get("comment_coverage_status") or "source_rows_only"
        ),
        "author_pseudonym": None,
        "author_pseudonym_status": "suppressed_for_public_projection",
        "mentioned_brands": sorted(set(str(value) for value in mentions if value)),
        "brand_binding": (
            record.get("brand_binding")
            if governed and isinstance(record.get("brand_binding"), str)
            else _brand_binding(mentions)
        ),
        "product_bindings": _product_bindings(record.get("product_bindings")),
        "analysis": analysis,
        "tagging": tagging,
        "evidence_id": f"post:{post_id}",
        "pii_redaction_flags": sorted(set(redactions)),
        "record_authority": row.get("record_authority"),
    }


def _project_comment(
    row: dict[str, Any],
    *,
    dictionary: TagDictionary,
    post: dict[str, Any],
) -> dict[str, Any]:
    record = _require_object(row.get("record"), "linked_comment_record")
    comment_id = record.get("comment_id")
    post_id = row.get("post_id")
    if not isinstance(comment_id, str) or COMMENT_ID_RE.fullmatch(comment_id) is None:
        raise ValueError("canonical_comment_id_invalid")
    if not isinstance(post_id, str) or POST_ID_RE.fullmatch(post_id) is None:
        raise ValueError(f"comment_{comment_id}_post_id_invalid")
    governed = "body" in record
    body, redactions = _sanitize_text(
        record.get("body") if governed else record.get("source_text")
    )
    if governed:
        permalink = post["permalink"]
        subreddit = post["subreddit"]
        permalink_basis = "parent_post_permalink"
    else:
        permalink, subreddit = _reddit_url(
            record.get("source_url"), f"comment_{comment_id}"
        )
        permalink_basis = "source_url"
    event_time = _event_time(record, f"comment_{comment_id}")
    analysis = _analysis(body, record.get("analysis"))
    tagging = _tagging(body, record.get("tagging"), dictionary)
    governed_mentions = record.get("mentioned_brands")
    mentions = (
        list(governed_mentions)
        if governed and isinstance(governed_mentions, list)
        else _derived_mentions(body)
    )
    annotations = record.get("source_annotations")
    score = (
        record.get("score")
        if governed
        else annotations.get("engagement_count")
        if isinstance(annotations, dict)
        else None
    )
    return {
        "schema_version": COMMENT_SCHEMA,
        "comment_id": comment_id,
        "reddit_id": comment_id,
        "post_id": post_id,
        "parent_id": record.get("parent_id") if governed else None,
        "parent_link_status": (
            record.get("parent_link_status") if governed else "linked_to_post_only"
        ),
        "body": body,
        "subreddit": subreddit,
        "permalink": permalink,
        "permalink_basis": permalink_basis,
        **event_time,
        "score": score if isinstance(score, (int, float)) and not isinstance(score, bool) else None,
        "depth": record.get("depth") if governed else None,
        "deleted_or_removed": (
            bool(record.get("deleted_or_removed"))
            if governed
            else body.strip().casefold() in {"[deleted]", "[removed]"}
        ),
        "is_bot": record.get("is_bot") if governed else None,
        "include_in_voc_metrics": (
            record.get("include_in_voc_metrics") if governed else None
        ),
        "metric_eligibility_status": (
            "source_explicit"
            if governed and isinstance(record.get("include_in_voc_metrics"), bool)
            else "determined_in_governed_metrics_not_base_projection"
        ),
        "author_pseudonym": None,
        "author_pseudonym_status": "suppressed_for_public_projection",
        "mentioned_brands": sorted(set(str(value) for value in mentions if value)),
        "brand_binding": (
            record.get("brand_binding")
            if governed and isinstance(record.get("brand_binding"), str)
            else _brand_binding(mentions)
        ),
        "product_bindings": _product_bindings(record.get("product_bindings")),
        "analysis": analysis,
        "tagging": tagging,
        "evidence_id": f"comment:{comment_id}",
        "pii_redaction_flags": sorted(set(redactions)),
        "record_authority": row.get("record_authority"),
    }


def _public_dictionary(dictionary: TagDictionary, dictionary_sha256: str) -> dict[str, Any]:
    return {
        "schema_version": PUBLIC_DICTIONARY_SCHEMA,
        "dictionary_version": dictionary.version,
        "dictionary_sha256": dictionary_sha256,
        "projection": {
            "audience": "public_ui",
            "source_schema_version": "dim_tag_v6.3_csv",
            "rule_fields": list(PUBLIC_RULE_FIELDS),
            "internal_strategy_fields_excluded": True,
        },
        "rules": [
            {field: rule.to_record()[field] for field in PUBLIC_RULE_FIELDS}
            for rule in dictionary.rules
        ],
    }


def _tag_summary(
    posts: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    dictionary: TagDictionary,
) -> dict[str, Any]:
    post_tags = Counter(
        tag_id for row in posts for tag_id in row["tagging"]["aspect_tag_ids"]
    )
    comment_tags = Counter(
        tag_id for row in comments for tag_id in row["tagging"]["aspect_tag_ids"]
    )
    all_ids = set(post_tags) | set(comment_tags)
    top_tags = []
    for tag_id in sorted(
        all_ids, key=lambda value: (-(post_tags[value] + comment_tags[value]), value)
    ):
        rule = dictionary.by_id[tag_id]
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
    return {
        "dictionary_version": dictionary.version,
        "posts_with_rule_tags": sum(bool(row["tagging"]["tag_ids"]) for row in posts),
        "comments_with_rule_tags": sum(
            bool(row["tagging"]["tag_ids"]) for row in comments
        ),
        "posts_with_aspect_tags": sum(
            bool(row["tagging"]["aspect_tag_ids"]) for row in posts
        ),
        "comments_with_aspect_tags": sum(
            bool(row["tagging"]["aspect_tag_ids"]) for row in comments
        ),
        "top_tags": top_tags,
    }


def _aggregates(
    posts: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    *,
    counts: dict[str, int],
    dictionary: TagDictionary,
) -> dict[str, Any]:
    post_sentiment = Counter(row["analysis"]["sentiment_label"] for row in posts)
    comment_sentiment = Counter(
        row["analysis"]["sentiment_label"] for row in comments
    )
    post_topics = Counter(row["analysis"]["topic"] for row in posts)
    pain_points = Counter(
        point for row in [*posts, *comments] for point in row["analysis"]["pain_points"]
    )
    subreddit_posts = Counter(row["subreddit"] for row in posts)
    subreddit_comments = Counter(row["subreddit"] for row in comments)
    monthly_posts = Counter(row["created_at_utc"][:7] for row in posts)
    brand_mentions = Counter(
        brand for row in posts for brand in row["mentioned_brands"]
    )
    total_brand_mentions = sum(brand_mentions.values())
    coverage = Counter(row["structural_coverage_grade"] for row in posts)
    completeness = Counter(row["count_completeness_status"] for row in posts)
    parent_status = Counter(row["parent_link_status"] for row in comments)
    precision_posts = Counter(row["event_time_precision"] for row in posts)
    precision_comments = Counter(row["event_time_precision"] for row in comments)
    eligibility = Counter(row["metric_eligibility_status"] for row in comments)
    tagging = _tag_summary(posts, comments, dictionary)
    return {
        "schema_version": AGGREGATES_SCHEMA,
        "headline": {
            "unique_posts": len(posts),
            "stored_comments": counts["stored_comments"],
            "linked_comments": len(comments),
            "unresolved_parent_comments": counts["unresolved_parent_comments"],
            "quarantined_comments": counts["quarantined_comments"],
            "comments_in_voc_metrics": sum(
                row["include_in_voc_metrics"] is True for row in comments
            ),
            "comments_metric_eligibility_pending_base_projection": sum(
                row["include_in_voc_metrics"] is None for row in comments
            ),
            "analysis_covered_posts": len(posts),
            "analysis_covered_comments": len(comments),
            "posts_with_rule_tags": tagging["posts_with_rule_tags"],
            "comments_with_rule_tags_in_voc_metrics": sum(
                row["include_in_voc_metrics"] is True
                and bool(row["tagging"]["tag_ids"])
                for row in comments
            ),
            "posts_with_aspect_tags": tagging["posts_with_aspect_tags"],
            "comments_with_aspect_tags": tagging["comments_with_aspect_tags"],
        },
        "date_range": {
            "posts": [
                min(row["created_at_utc"] for row in posts),
                max(row["created_at_utc"] for row in posts),
            ],
            "comments": [
                min(row["created_at_utc"] for row in comments),
                max(row["created_at_utc"] for row in comments),
            ],
        },
        "time_precision": {
            "posts": dict(sorted(precision_posts.items())),
            "comments": dict(sorted(precision_comments.items())),
            "day_precision_midnight_imputed": False,
        },
        "post_sentiment": dict(sorted(post_sentiment.items())),
        "comment_sentiment": dict(sorted(comment_sentiment.items())),
        "post_topics": dict(post_topics.most_common()),
        "pain_points": dict(pain_points.most_common()),
        "subreddit_posts": dict(subreddit_posts.most_common()),
        "subreddit_comments": dict(subreddit_comments.most_common()),
        "monthly_posts": dict(sorted(monthly_posts.items())),
        "brand_sample_mentions": [
            {
                "brand": brand,
                "posts": value,
                "sample_mention_share": (
                    round(value / total_brand_mentions, 6)
                    if total_brand_mentions
                    else 0.0
                ),
            }
            for brand, value in brand_mentions.most_common()
        ],
        "coverage_grade": dict(sorted(coverage.items())),
        "count_completeness_status": dict(sorted(completeness.items())),
        "parent_link_status": dict(sorted(parent_status.items())),
        "metric_eligibility_status": dict(sorted(eligibility.items())),
        "tagging": tagging,
        "metric_notes": {
            "brand_sample_mentions": "定向样本品牌提及份额，不代表市场份额。",
            "unresolved_parent_comments": "待关联评论保留在守恒账本中，不进入帖子评论明细、搜索或帖子+评论 VOC 上下文。",
            "comments_in_voc_metrics": "仅计 canonical Base 已显式给出资格的评论；完整指标口径由受治理 metrics 数据集提供。",
            "time_precision": "日精度来源仅显示 YYYY-MM-DD，不补造 00:00 或时区。",
            "tagging": "Base 公开投影使用确定性本地规则补齐检索标签，标签仍为待语义复核状态。",
        },
    }


def _write(path: Path, value: Any) -> None:
    path.write_bytes(canonical_json_bytes(value))


def _publish_staging(staging: Path, output_dir: Path) -> None:
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError(f"output_dir_already_exists:{output_dir}")
    for path in sorted(staging.rglob("*")):
        if path.is_symlink():
            raise ValueError("staging_symlink_forbidden")
        path.chmod(0o755 if path.is_dir() else 0o644)
    staging.chmod(0o755)
    try:
        os.rename(staging, output_dir)
    except FileExistsError:
        raise


def build_public_base_projection(
    *,
    dataset_version: str,
    source_snapshot_id: str,
    generated_at_utc: str,
    canonical_root: Path,
    canonical_manifest_sha256: str,
    canonical_validation_receipt: Path,
    canonical_validation_receipt_sha256: str,
    tag_dictionary_path: Path,
    output_dir: Path,
    coverage_attestation: Mapping[str, object] | None = None,
    coverage_attestation_sha256: str | None = None,
) -> dict[str, Any]:
    if DATASET_VERSION_RE.fullmatch(dataset_version) is None:
        raise ValueError("dataset_version_invalid")
    if not source_snapshot_id.strip():
        raise ValueError("source_snapshot_id_missing")
    generated_at = _parse_generated_at(generated_at_utc)
    dictionary_path = tag_dictionary_path.resolve(strict=True)
    if not dictionary_path.is_file() or dictionary_path.is_symlink():
        raise ValueError("tag_dictionary_unsafe")
    dictionary_sha256 = sha256_path(dictionary_path)
    dictionary = TagDictionary.from_csv(dictionary_path)
    manifest, canonical_posts, canonical_comments, unresolved, quarantine = load_canonical(
        canonical_root,
        expected_manifest_sha256=canonical_manifest_sha256,
        validation_receipt=canonical_validation_receipt,
        expected_validation_receipt_sha256=canonical_validation_receipt_sha256,
    )
    manifest_schema = manifest.get("schema_version")
    expected_canonical_dataset_id = (
        f"{source_snapshot_id}_canonical_v1"
        if manifest_schema == "reddit_voc_canonical_snapshot_manifest_v1"
        else source_snapshot_id
    )
    if manifest.get("dataset_id") != expected_canonical_dataset_id:
        raise ValueError("source_snapshot_id_canonical_dataset_mismatch")
    counts = {
        key: _require_count(manifest["canonical_counts"].get(key), f"canonical_{key}")
        for key in (
            "posts",
            "comments_jsonl",
            "linked_comments",
            "unresolved_parent_comments",
            "quarantined_comments",
            "stored_comments",
        )
    }
    linked_count_by_post = Counter(str(row.get("post_id")) for row in canonical_comments)
    posts = [
        _project_post(
            row,
            linked_count=linked_count_by_post[str(row.get("post_id"))],
            dictionary=dictionary,
        )
        for row in canonical_posts
    ]
    projected_post_by_id = {row["post_id"]: row for row in posts}
    comments = [
        _project_comment(
            row,
            dictionary=dictionary,
            post=projected_post_by_id[str(row.get("post_id"))],
        )
        for row in canonical_comments
    ]
    posts.sort(key=lambda row: (row["created_at_utc"], row["post_id"]))
    comments.sort(key=lambda row: (row["created_at_utc"], row["comment_id"]))
    if (coverage_attestation is None) != (coverage_attestation_sha256 is None):
        raise ValueError("coverage_attestation_and_sha_must_be_paired")
    validated_attestation: dict[str, object] | None = None
    if coverage_attestation is not None:
        assert coverage_attestation_sha256 is not None
        observed_dates = [_calendar_date(row) for row in [*posts, *comments]]
        validated_attestation = validate_coverage_attestation(
            coverage_attestation,
            expected_sha256=coverage_attestation_sha256,
            dataset_id=source_snapshot_id,
            source_snapshot_id=source_snapshot_id,
            scope="canonical_observation_pool",
            min_observed_date=min(observed_dates),
            max_observed_date=max(observed_dates),
        )
    comparison_contract_proven = validated_attestation is not None
    comparison_contract_basis = (
        "owner_attested_dataset_scope_window"
        if comparison_contract_proven
        else "not_owner_attested"
    )
    completeness_percent = 100 if comparison_contract_proven else None
    completeness_basis = (
        "data_owner_declaration"
        if comparison_contract_proven
        else "not_owner_attested"
    )
    post_ids = [row["post_id"] for row in posts]
    comment_ids = [row["comment_id"] for row in comments]
    if len(set(post_ids)) != len(post_ids):
        raise ValueError("public_post_id_duplicate")
    if len(set(comment_ids)) != len(comment_ids):
        raise ValueError("public_comment_id_duplicate")
    if not all(row["post_id"] in set(post_ids) for row in comments):
        raise ValueError("public_comment_post_fk_missing")
    aggregate = _aggregates(posts, comments, counts=counts, dictionary=dictionary)
    public_dictionary = _public_dictionary(dictionary, dictionary_sha256)
    output = output_dir.expanduser().absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"output_dir_already_exists:{output}")
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent))
    try:
        _write(staging / "posts-public.json", posts)
        _write(staging / "comments-public.json", comments)
        _write(staging / "aggregates-public.json", aggregate)
        _write(staging / "tag-dictionary-public.json", public_dictionary)
        files = {name: file_contract(staging / name) for name in PUBLIC_FILES}
        time_precision = aggregate["time_precision"]
        pseudonym_counts = Counter(
            row["author_pseudonym_status"] for row in [*posts, *comments]
        )
        checks = {
            "canonical_manifest_and_receipt_bound": True,
            "canonical_identity_conserved": (
                len(posts) == counts["posts"]
                and len(comments) == counts["linked_comments"]
                and counts["comments_jsonl"]
                == counts["linked_comments"] + counts["unresolved_parent_comments"]
                and counts["stored_comments"]
                == counts["comments_jsonl"] + counts["quarantined_comments"]
            ),
            "all_posts_projected": len(posts) == counts["posts"],
            "only_linked_comments_projected": len(comments) == counts["linked_comments"],
            "unresolved_parent_comments_ledger_only": len(unresolved)
            == counts["unresolved_parent_comments"],
            "quarantine_ledger_only": len(quarantine) == counts["quarantined_comments"],
            "post_ids_unique": len(post_ids) == len(set(post_ids)),
            "comment_ids_unique": len(comment_ids) == len(set(comment_ids)),
            "comment_post_foreign_keys_resolve": all(
                row["post_id"] in set(post_ids) for row in comments
            ),
            "day_precision_midnight_not_imputed": (
                time_precision["day_precision_midnight_imputed"] is False
                and all(
                    row["event_created_at_utc"] is None
                    and DAY_RE.fullmatch(row["created_at_utc"]) is not None
                    for row in [*posts, *comments]
                    if row["event_time_precision"] == "day"
                )
            ),
            "raw_author_fields_excluded": True,
            "public_author_linkage_suppressed": all(
                row["author_pseudonym"] is None
                and row["author_pseudonym_status"]
                == "suppressed_for_public_projection"
                for row in [*posts, *comments]
            ),
            "side_effect_boundaries_preserved": BOUNDARIES
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
            raise ValueError(f"base_public_projection_checks_failed:{checks}")
        public_manifest = {
            "schema_version": MANIFEST_SCHEMA,
            "dataset_version": dataset_version,
            "source_snapshot_id": source_snapshot_id,
            "status": "validated_candidate",
            "consumption_status": "eligible_for_current_release_candidate_binding",
            "promotable": True,
            "privacy_safe_projection": True,
            "comparison_contract_basis": comparison_contract_basis,
            "comparison_contract_proven": comparison_contract_proven,
            "comparison_unavailable_reason_codes": (
                [] if comparison_contract_proven else [UNATTESTED_REASON]
            ),
            "completeness_percent": completeness_percent,
            "completeness_basis": completeness_basis,
            "coverage_attestation": validated_attestation,
            "data_owner_coverage_attestation_sha256": (
                coverage_attestation_sha256
            ),
            "lineage_manifest_sha256": canonical_manifest_sha256,
            "generated_at_utc": generated_at,
            "delivery_mode": DELIVERY_MODE,
            "artifact_stage": "privacy_safe_base_public_candidate",
            "inputs": {
                "canonical_dataset_id": manifest["dataset_id"],
                "canonical_manifest_sha256": canonical_manifest_sha256,
                "canonical_validation_receipt_sha256": canonical_validation_receipt_sha256,
                "tag_dictionary_sha256": dictionary_sha256,
            },
            "canonical_counts": counts,
            "projection_counts": {
                "public_posts": len(posts),
                "public_linked_comments": len(comments),
                "ledger_only_unresolved_parent_comments": len(unresolved),
                "ledger_only_quarantined_comments": len(quarantine),
            },
            "time_precision": time_precision,
            "analysis": {
                "version": "local_rules_v1",
                "provider_call": False,
                "recomputed_for_missing_canonical_analysis": True,
                "source_analysis_preserved_when_present": True,
            },
            "tagging": {
                "dictionary_version": dictionary.version,
                "dictionary_sha256": dictionary_sha256,
                "labels_provisional": True,
                "semantic_validation_run": False,
                "entity_sentiment_overridden": False,
                "matching_policy": "canonical governed tags when present; otherwise deterministic L0 lexical projection",
                "provider_call": False,
            },
            "privacy": {
                "author_display": "suppressed",
                "raw_author_fields_present": False,
                "author_linkage_excluded": True,
                "stable_pseudonym_exposed": False,
                "contact_patterns_redacted": True,
                "html_fields_present": False,
                "raw_archive_public": False,
                "pseudonym_status_counts": dict(sorted(pseudonym_counts.items())),
            },
            "semantic_boundaries": {
                "collection_bucket_is_brand_ownership": False,
                "brand_metric_label": "sample mention share",
                "market_share_supported": False,
                "roi_supported": False,
                "response_time_supported": False,
                "unresolved_parent_business_label": "待关联评论",
                "unresolved_parent_comments_in_public_detail": False,
                "quarantined_comments_in_public_detail": False,
                "day_precision_midnight_imputed": False,
                "day_precision_display_contract": "YYYY-MM-DD",
                "day_precision_created_at_utc_compatibility_value_is_calendar_date_not_instant": True,
                "metric_eligibility_owned_by_governed_metrics_dataset": True,
            },
            "files": files,
            "checks": checks,
            "all_checks_passed": True,
            "boundaries": dict(BOUNDARIES),
            **BOUNDARIES,
        }
        _write(staging / "manifest-public.json", public_manifest)
        _publish_staging(staging, output)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return {
        "status": "validated_candidate",
        "dataset_version": dataset_version,
        "public_posts": len(posts),
        "public_linked_comments": len(comments),
        "unresolved_parent_comments": len(unresolved),
        "quarantined_comments": len(quarantine),
        "output_dir": str(output),
        "public_manifest_sha256": sha256_path(output / "manifest-public.json"),
        "promotable": True,
        "comparison_contract_proven": comparison_contract_proven,
        "completeness_percent": completeness_percent,
        "production_unchanged": True,
    }
