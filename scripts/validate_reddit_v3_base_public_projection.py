#!/usr/bin/env python3
"""Independently validate one privacy-safe V3 Base public candidate.

This module deliberately does not import the projection builder.  It checks the
canonical identity sets, public bytes, privacy contract, time precision and all
browser-facing aggregates before emitting a candidate-only receipt.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterable, Mapping
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Sequence
from urllib.parse import urlparse

from reddit_voc.v3_periodized_metrics import (
    UNATTESTED_REASON,
    _calendar_date,
    validate_coverage_attestation,
)


MANIFEST_SCHEMA = "reddit_voc_site_snapshot_manifest_v3"
AGGREGATES_SCHEMA = "reddit_voc_site_aggregates_v3"
POST_SCHEMA = "reddit_voc_public_post_v3"
COMMENT_SCHEMA = "reddit_voc_public_comment_v3"
RECEIPT_SCHEMA = "reddit_voc_base_public_validation_receipt_v1"
PUBLIC_DICTIONARY_SCHEMA = "reddit_voc_public_tag_dictionary_v1"
PUBLIC_FILES = {
    "aggregates-public.json",
    "posts-public.json",
    "comments-public.json",
    "tag-dictionary-public.json",
}
BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d() .-]{7,}\d)(?!\w)")
USERNAME_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_])(?:/?u/[A-Za-z0-9_-]{2,30}|@[A-Za-z0-9_-]{2,30})"
)
FORBIDDEN_KEYS = {
    "author",
    "author_hash",
    "author_fullname",
    "author_name",
    "username",
    "reddit_username",
    "source_occurrences",
    "source_record_id",
    "source_row_ordinal",
    "source_annotations",
    "body_html",
    "selftext_html",
}
POST_FIELDS = {
    "schema_version",
    "post_id",
    "reddit_id",
    "title",
    "title_basis",
    "content",
    "subreddit",
    "permalink",
    "permalink_basis",
    "created_at_utc",
    "event_created_at_utc",
    "source_calendar_date",
    "event_time_precision",
    "score",
    "upvote_ratio",
    "num_comments_reported",
    "linked_comment_count",
    "structural_coverage_grade",
    "count_completeness_status",
    "comment_coverage_status",
    "author_pseudonym",
    "author_pseudonym_status",
    "mentioned_brands",
    "brand_binding",
    "product_bindings",
    "analysis",
    "tagging",
    "evidence_id",
    "pii_redaction_flags",
    "record_authority",
}
COMMENT_FIELDS = {
    "schema_version",
    "comment_id",
    "reddit_id",
    "post_id",
    "parent_id",
    "parent_link_status",
    "body",
    "subreddit",
    "permalink",
    "permalink_basis",
    "created_at_utc",
    "event_created_at_utc",
    "source_calendar_date",
    "event_time_precision",
    "score",
    "depth",
    "deleted_or_removed",
    "is_bot",
    "include_in_voc_metrics",
    "metric_eligibility_status",
    "author_pseudonym",
    "author_pseudonym_status",
    "mentioned_brands",
    "brand_binding",
    "product_bindings",
    "analysis",
    "tagging",
    "evidence_id",
    "pii_redaction_flags",
    "record_authority",
}


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _object(value: Any, label: str) -> dict[str, Any]:
    _check(
        isinstance(value, dict) and all(isinstance(key, str) for key in value),
        f"object_contract_mismatch:{label}",
    )
    return value


def _rows(value: Any, label: str) -> list[dict[str, Any]]:
    _check(isinstance(value, list), f"array_contract_mismatch:{label}")
    return [_object(row, f"{label}[{index}]") for index, row in enumerate(value)]


def _count(value: Any, label: str) -> int:
    _check(type(value) is int and value >= 0, f"count_contract_mismatch:{label}")
    return value


def _sha(value: Any, label: str) -> str:
    _check(
        isinstance(value, str) and SHA256_RE.fullmatch(value) is not None,
        f"sha256_contract_mismatch:{label}",
    )
    return value


def _sha_path(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _load(path: Path, label: str) -> Any:
    _check(path.is_file() and not path.is_symlink(), f"unsafe_or_missing_file:{label}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid_json:{label}") from exc


def _load_jsonl(path: Path, label: str) -> list[dict[str, Any]]:
    _check(path.is_file() and not path.is_symlink(), f"unsafe_or_missing_file:{label}")
    result: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            try:
                result.append(_object(json.loads(line), f"{label}:{line_number}"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid_jsonl:{label}:{line_number}") from exc
    return result


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _assert_reddit_url(value: Any, label: str) -> None:
    _check(isinstance(value, str), f"reddit_url_not_string:{label}")
    parsed = urlparse(value)
    _check(
        parsed.scheme == "https"
        and (parsed.hostname or "").casefold()
        in {
            "reddit.com",
            "www.reddit.com",
            "old.reddit.com",
            "redd.it",
            "i.redd.it",
            "v.redd.it",
        },
        f"reddit_url_invalid:{label}",
    )


def _verify_time(public: dict[str, Any], canonical: dict[str, Any], label: str) -> None:
    if canonical.get("event_time_precision") == "day":
        day = canonical.get("source_calendar_date")
        _check(isinstance(day, str) and DAY_RE.fullmatch(day) is not None, f"canonical_day_invalid:{label}")
        _check(public.get("event_time_precision") == "day", f"day_precision_lost:{label}")
        _check(public.get("source_calendar_date") == day, f"day_value_drift:{label}")
        _check(public.get("created_at_utc") == day, f"day_compatibility_value_drift:{label}")
        _check(public.get("event_created_at_utc") is None, f"day_midnight_imputed:{label}")
    else:
        instant = canonical.get("event_created_at_utc") or canonical.get("created_at_utc")
        _check(isinstance(instant, str) and "T" in instant, f"canonical_instant_invalid:{label}")
        _check(public.get("event_time_precision") == "instant", f"instant_precision_lost:{label}")
        _check(public.get("source_calendar_date") is None, f"instant_day_field_present:{label}")
        _check(isinstance(public.get("event_created_at_utc"), str), f"instant_missing:{label}")


def _validate_entity_common(row: dict[str, Any], label: str) -> None:
    _check(row.get("author_pseudonym") is None, f"public_pseudonym_not_suppressed:{label}")
    _check(
        row.get("author_pseudonym_status") == "suppressed_for_public_projection",
        f"pseudonym_status_invalid:{label}",
    )
    _assert_reddit_url(row.get("permalink"), label)
    analysis = _object(row.get("analysis"), f"{label}.analysis")
    _check(analysis.get("provider_call") is False, f"analysis_provider_call_true:{label}")
    tagging = _object(row.get("tagging"), f"{label}.tagging")
    _check(tagging.get("semantic_validation_status") == "not_run", f"tag_status_invalid:{label}")
    _check(isinstance(row.get("pii_redaction_flags"), list), f"redaction_flags_invalid:{label}")


def _recompute_tagging(
    posts: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    rules: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    post_tags = Counter(tag for row in posts for tag in row["tagging"]["aspect_tag_ids"])
    comment_tags = Counter(tag for row in comments for tag in row["tagging"]["aspect_tag_ids"])
    all_ids = set(post_tags) | set(comment_tags)
    top_tags = []
    for tag_id in sorted(all_ids, key=lambda value: (-(post_tags[value] + comment_tags[value]), value)):
        _check(tag_id in rules, f"aggregate_tag_not_in_dictionary:{tag_id}")
        rule = rules[tag_id]
        top_tags.append(
            {
                "tag_id": tag_id,
                "name_cn": rule["name_cn"],
                "name_en": rule["name_en"],
                "theme": rule["theme"],
                "tag_sentiment": rule["sentiment"],
                "post_entities": post_tags[tag_id],
                "comment_entities": comment_tags[tag_id],
                "total_entities": post_tags[tag_id] + comment_tags[tag_id],
            }
        )
    return {
        "dictionary_version": next(iter(posts))["tagging"]["dictionary_version"],
        "posts_with_rule_tags": sum(bool(row["tagging"]["tag_ids"]) for row in posts),
        "comments_with_rule_tags": sum(bool(row["tagging"]["tag_ids"]) for row in comments),
        "posts_with_aspect_tags": sum(bool(row["tagging"]["aspect_tag_ids"]) for row in posts),
        "comments_with_aspect_tags": sum(bool(row["tagging"]["aspect_tag_ids"]) for row in comments),
        "top_tags": top_tags,
    }


def _recompute_aggregates(
    posts: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    counts: dict[str, int],
    rules: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    post_sentiment = Counter(row["analysis"]["sentiment_label"] for row in posts)
    comment_sentiment = Counter(row["analysis"]["sentiment_label"] for row in comments)
    post_topics = Counter(row["analysis"]["topic"] for row in posts)
    pain_points = Counter(point for row in [*posts, *comments] for point in row["analysis"]["pain_points"])
    subreddit_posts = Counter(row["subreddit"] for row in posts)
    subreddit_comments = Counter(row["subreddit"] for row in comments)
    monthly_posts = Counter(row["created_at_utc"][:7] for row in posts)
    brand_mentions = Counter(brand for row in posts for brand in row["mentioned_brands"])
    total_brand_mentions = sum(brand_mentions.values())
    coverage = Counter(row["structural_coverage_grade"] for row in posts)
    completeness = Counter(row["count_completeness_status"] for row in posts)
    parent_status = Counter(row["parent_link_status"] for row in comments)
    precision_posts = Counter(row["event_time_precision"] for row in posts)
    precision_comments = Counter(row["event_time_precision"] for row in comments)
    eligibility = Counter(row["metric_eligibility_status"] for row in comments)
    tagging = _recompute_tagging(posts, comments, rules)
    return {
        "schema_version": AGGREGATES_SCHEMA,
        "headline": {
            "unique_posts": len(posts),
            "stored_comments": counts["stored_comments"],
            "linked_comments": len(comments),
            "unresolved_parent_comments": counts["unresolved_parent_comments"],
            "quarantined_comments": counts["quarantined_comments"],
            "comments_in_voc_metrics": sum(row["include_in_voc_metrics"] is True for row in comments),
            "comments_metric_eligibility_pending_base_projection": sum(row["include_in_voc_metrics"] is None for row in comments),
            "analysis_covered_posts": len(posts),
            "analysis_covered_comments": len(comments),
            "posts_with_rule_tags": tagging["posts_with_rule_tags"],
            "comments_with_rule_tags_in_voc_metrics": sum(
                row["include_in_voc_metrics"] is True and bool(row["tagging"]["tag_ids"])
                for row in comments
            ),
            "posts_with_aspect_tags": tagging["posts_with_aspect_tags"],
            "comments_with_aspect_tags": tagging["comments_with_aspect_tags"],
        },
        "date_range": {
            "posts": [min(row["created_at_utc"] for row in posts), max(row["created_at_utc"] for row in posts)],
            "comments": [min(row["created_at_utc"] for row in comments), max(row["created_at_utc"] for row in comments)],
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
                "sample_mention_share": round(value / total_brand_mentions, 6) if total_brand_mentions else 0.0,
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


def validate_public_base_projection(
    *,
    public_root: Path,
    expected_public_manifest_sha256: str,
    expected_dataset_version: str,
    expected_source_snapshot_id: str,
    canonical_root: Path,
    expected_canonical_manifest_sha256: str,
    canonical_validation_receipt: Path,
    expected_canonical_validation_receipt_sha256: str,
    coverage_attestation: Mapping[str, object] | None = None,
    expected_coverage_attestation_sha256: str | None = None,
) -> dict[str, Any]:
    root = public_root.resolve(strict=True)
    _check(root.is_dir() and not root.is_symlink(), "public_root_unsafe")
    manifest_path = root / "manifest-public.json"
    _check(_sha_path(manifest_path) == _sha(expected_public_manifest_sha256, "public_manifest"), "public_manifest_sha256_mismatch")
    manifest = _object(_load(manifest_path, "public_manifest"), "public_manifest")
    _check(manifest.get("schema_version") == MANIFEST_SCHEMA, "public_manifest_schema_unsupported")
    _check(manifest.get("dataset_version") == expected_dataset_version, "public_dataset_version_mismatch")
    _check(manifest.get("source_snapshot_id") == expected_source_snapshot_id, "public_source_snapshot_id_mismatch")
    _check(manifest.get("status") == "validated_candidate", "public_status_invalid")
    _check(
        manifest.get("consumption_status")
        == "eligible_for_current_release_candidate_binding",
        "public_consumption_status_invalid",
    )
    _check(manifest.get("promotable") is True, "public_promotable_false")
    _check(manifest.get("privacy_safe_projection") is True, "privacy_safe_projection_false")
    if (coverage_attestation is None) != (
        expected_coverage_attestation_sha256 is None
    ):
        raise ValueError("coverage_attestation_and_sha_must_be_paired")
    comparison_contract_proven = coverage_attestation is not None
    expected_comparison_basis = (
        "owner_attested_dataset_scope_window"
        if comparison_contract_proven
        else "not_owner_attested"
    )
    expected_completeness = 100 if comparison_contract_proven else None
    expected_completeness_basis = (
        "data_owner_declaration"
        if comparison_contract_proven
        else "not_owner_attested"
    )
    expected_unavailable_reasons = (
        [] if comparison_contract_proven else [UNATTESTED_REASON]
    )
    _check(
        manifest.get("comparison_contract_proven")
        is comparison_contract_proven,
        "public_comparison_contract_state_invalid",
    )
    _check(
        manifest.get("comparison_contract_basis") == expected_comparison_basis,
        "public_comparison_contract_basis_invalid",
    )
    _check(
        manifest.get("comparison_unavailable_reason_codes")
        == expected_unavailable_reasons,
        "public_comparison_unavailable_reasons_invalid",
    )
    _check(
        manifest.get("completeness_percent") == expected_completeness,
        "public_completeness_invalid",
    )
    _check(
        manifest.get("completeness_basis") == expected_completeness_basis,
        "public_completeness_basis_invalid",
    )
    _check(
        manifest.get("data_owner_coverage_attestation_sha256")
        == expected_coverage_attestation_sha256,
        "public_coverage_attestation_sha_mismatch",
    )
    _check(manifest.get("lineage_manifest_sha256") == expected_canonical_manifest_sha256, "lineage_manifest_binding_mismatch")
    manifest_inputs = _object(manifest.get("inputs"), "public_manifest.inputs")
    _check(
        manifest_inputs.get("canonical_validation_receipt_sha256")
        == expected_canonical_validation_receipt_sha256,
        "lineage_receipt_binding_mismatch",
    )
    _check(manifest.get("all_checks_passed") is True, "public_checks_not_passed")
    for key, value in BOUNDARIES.items():
        _check(manifest.get(key) is value, f"public_boundary_mismatch:{key}")
    _check(manifest.get("boundaries") == BOUNDARIES, "public_boundaries_object_mismatch")

    files = _object(manifest.get("files"), "public_manifest.files")
    _check(set(files) == PUBLIC_FILES, "public_file_set_mismatch")
    for name in sorted(PUBLIC_FILES):
        path = root / name
        _check(path.is_file() and not path.is_symlink(), f"public_file_unsafe_or_missing:{name}")
        contract = _object(files[name], f"public_file_contract:{name}")
        _check(set(contract) == {"bytes", "sha256"}, f"public_file_contract_keys:{name}")
        _check(_count(contract.get("bytes"), f"public_file_bytes:{name}") == path.stat().st_size, f"public_file_bytes_mismatch:{name}")
        _check(_sha(contract.get("sha256"), f"public_file_sha:{name}") == _sha_path(path), f"public_file_sha_mismatch:{name}")

    posts = _rows(_load(root / "posts-public.json", "public_posts"), "public_posts")
    comments = _rows(_load(root / "comments-public.json", "public_comments"), "public_comments")
    aggregates = _object(_load(root / "aggregates-public.json", "public_aggregates"), "public_aggregates")
    dictionary = _object(_load(root / "tag-dictionary-public.json", "public_dictionary"), "public_dictionary")
    validated_attestation: dict[str, object] | None = None
    if coverage_attestation is not None:
        assert expected_coverage_attestation_sha256 is not None
        observed_dates = [_calendar_date(row) for row in [*posts, *comments]]
        validated_attestation = validate_coverage_attestation(
            coverage_attestation,
            expected_sha256=expected_coverage_attestation_sha256,
            dataset_id=expected_source_snapshot_id,
            source_snapshot_id=expected_source_snapshot_id,
            scope="canonical_observation_pool",
            min_observed_date=min(observed_dates),
            max_observed_date=max(observed_dates),
        )
    _check(
        manifest.get("coverage_attestation") == validated_attestation,
        "public_coverage_attestation_binding_mismatch",
    )
    _check(dictionary.get("schema_version") == PUBLIC_DICTIONARY_SCHEMA, "public_dictionary_schema_invalid")
    rule_rows = _rows(dictionary.get("rules"), "public_dictionary.rules")
    rules = {str(row.get("tag_id")): row for row in rule_rows}
    _check(len(rules) == len(rule_rows), "public_dictionary_duplicate_tag_id")
    _check(all(set(row) == {"tag_id", "name_cn", "name_en", "theme", "sentiment", "tag_scope"} for row in rule_rows), "public_dictionary_private_fields_present")

    canonical = canonical_root.resolve(strict=True)
    canonical_manifest_path = canonical / "manifest.json"
    _check(_sha_path(canonical_manifest_path) == _sha(expected_canonical_manifest_sha256, "canonical_manifest"), "canonical_manifest_sha256_mismatch")
    _check(_sha_path(canonical_validation_receipt) == _sha(expected_canonical_validation_receipt_sha256, "canonical_receipt"), "canonical_receipt_sha256_mismatch")
    canonical_manifest = _object(_load(canonical_manifest_path, "canonical_manifest"), "canonical_manifest")
    canonical_receipt = _object(_load(canonical_validation_receipt, "canonical_receipt"), "canonical_receipt")
    _check(canonical_receipt.get("status") == "passed", "canonical_receipt_not_passed")
    _check(canonical_receipt.get("bundle_manifest_sha256") == expected_canonical_manifest_sha256, "canonical_receipt_manifest_binding_mismatch")
    _check(canonical_receipt.get("canonical_counts") == canonical_manifest.get("canonical_counts"), "canonical_receipt_count_binding_mismatch")
    canonical_posts = _load_jsonl(canonical / "posts.jsonl", "canonical_posts")
    canonical_comments = _load_jsonl(canonical / "comments.jsonl", "canonical_comments")
    canonical_unresolved = _load_jsonl(canonical / "unresolved-parent-ledger.jsonl", "canonical_unresolved")
    canonical_quarantine = _load_jsonl(canonical / "quarantine.jsonl", "canonical_quarantine")
    linked_canonical_comments = [row for row in canonical_comments if row.get("comment_state") == "linked"]
    counts_raw = _object(canonical_manifest.get("canonical_counts"), "canonical_counts")
    counts = {key: _count(counts_raw.get(key), f"canonical_count:{key}") for key in (
        "posts", "comments_jsonl", "linked_comments", "unresolved_parent_comments", "quarantined_comments", "stored_comments"
    )}
    _check(len(posts) == counts["posts"] == len(canonical_posts), "public_post_count_mismatch")
    _check(len(comments) == counts["linked_comments"] == len(linked_canonical_comments), "public_linked_comment_count_mismatch")
    _check(len(canonical_unresolved) == counts["unresolved_parent_comments"], "unresolved_ledger_count_mismatch")
    _check(len(canonical_quarantine) == counts["quarantined_comments"], "quarantine_count_mismatch")
    _check(counts["comments_jsonl"] == counts["linked_comments"] + counts["unresolved_parent_comments"], "comment_state_conservation_failed")
    _check(counts["stored_comments"] == counts["comments_jsonl"] + counts["quarantined_comments"], "stored_comment_conservation_failed")
    _check(manifest.get("canonical_counts") == counts, "public_manifest_canonical_counts_drift")

    public_post_by_id: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(posts):
        label = f"post[{index}]"
        _check(set(row) == POST_FIELDS, f"post_field_set_mismatch:{index}")
        _check(row.get("schema_version") == POST_SCHEMA, f"post_schema_mismatch:{index}")
        post_id = row.get("post_id")
        _check(isinstance(post_id, str) and post_id not in public_post_by_id, f"post_id_duplicate_or_invalid:{index}")
        _validate_entity_common(row, label)
        for field in ("title", "content"):
            text = row.get(field)
            _check(isinstance(text, str), f"post_text_invalid:{label}:{field}")
            _check(EMAIL_RE.search(text) is None and PHONE_RE.search(text) is None and USERNAME_RE.search(text) is None, f"post_text_privacy_failure:{label}:{field}")
        public_post_by_id[post_id] = row

    public_comment_by_id: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(comments):
        label = f"comment[{index}]"
        _check(set(row) == COMMENT_FIELDS, f"comment_field_set_mismatch:{index}")
        _check(row.get("schema_version") == COMMENT_SCHEMA, f"comment_schema_mismatch:{index}")
        comment_id = row.get("comment_id")
        _check(isinstance(comment_id, str) and comment_id not in public_comment_by_id, f"comment_id_duplicate_or_invalid:{index}")
        _check(row.get("post_id") in public_post_by_id, f"comment_post_fk_missing:{comment_id}")
        _validate_entity_common(row, label)
        text = row.get("body")
        _check(isinstance(text, str), f"comment_body_invalid:{label}")
        _check(EMAIL_RE.search(text) is None and PHONE_RE.search(text) is None and USERNAME_RE.search(text) is None, f"comment_text_privacy_failure:{label}")
        public_comment_by_id[comment_id] = row

    canonical_post_by_id = {str(row.get("post_id")): row for row in canonical_posts}
    canonical_comment_by_id = {
        str(_object(row.get("record"), "canonical_comment_record").get("comment_id")): row
        for row in linked_canonical_comments
    }
    _check(set(public_post_by_id) == set(canonical_post_by_id), "public_post_identity_set_drift")
    _check(set(public_comment_by_id) == set(canonical_comment_by_id), "public_comment_identity_set_drift")
    for post_id, public in public_post_by_id.items():
        record = _object(canonical_post_by_id[post_id].get("record"), f"canonical_post:{post_id}")
        _verify_time(public, record, f"post:{post_id}")
        _check(public.get("author_pseudonym") is None, f"post_pseudonym_not_suppressed:{post_id}")
    for comment_id, public in public_comment_by_id.items():
        record = _object(canonical_comment_by_id[comment_id].get("record"), f"canonical_comment:{comment_id}")
        _verify_time(public, record, f"comment:{comment_id}")
        _check(public.get("author_pseudonym") is None, f"comment_pseudonym_not_suppressed:{comment_id}")

    for value in (manifest, aggregates, posts, comments, dictionary):
        leaked = FORBIDDEN_KEYS & set(_walk_keys(value))
        _check(not leaked, f"private_field_leak:{sorted(leaked)}")
    for row in [*posts, *comments]:
        for tag_id in row["tagging"]["tag_ids"]:
            _check(tag_id in rules, f"entity_tag_not_in_dictionary:{tag_id}")

    expected_aggregates = _recompute_aggregates(posts, comments, counts, rules)
    _check(aggregates == expected_aggregates, "public_aggregates_recompute_mismatch")
    _check(manifest.get("time_precision") == aggregates.get("time_precision"), "manifest_time_precision_drift")
    checks = {
        "canonical_manifest_and_receipt_bound": True,
        "canonical_identity_conserved": True,
        "public_post_identity_set_exact": True,
        "public_linked_comment_identity_set_exact": True,
        "unresolved_and_quarantine_ledger_only": True,
        "public_file_hashes_exact": True,
        "public_aggregates_independently_recomputed": True,
        "day_precision_midnight_not_imputed": True,
        "public_author_linkage_suppressed": True,
        "raw_author_and_source_run_fields_absent": True,
        "contact_and_username_patterns_absent": True,
        "side_effect_boundaries_preserved": True,
    }
    return {
        "schema_version": RECEIPT_SCHEMA,
        "dataset_version": expected_dataset_version,
        "source_snapshot_id": expected_source_snapshot_id,
        "status": "passed_candidate_only",
        "consumption_status": "eligible_for_current_release_candidate_binding",
        "promotable": True,
        "privacy_safe_projection": True,
        "comparison_contract_basis": expected_comparison_basis,
        "comparison_contract_proven": comparison_contract_proven,
        "comparison_unavailable_reason_codes": expected_unavailable_reasons,
        "completeness_percent": expected_completeness,
        "completeness_basis": expected_completeness_basis,
        "coverage_attestation": validated_attestation,
        "data_owner_coverage_attestation_sha256": (
            expected_coverage_attestation_sha256
        ),
        "bundle_manifest_sha256": expected_public_manifest_sha256,
        "public_manifest_sha256": expected_public_manifest_sha256,
        "canonical_manifest_sha256": expected_canonical_manifest_sha256,
        "canonical_validation_receipt_sha256": expected_canonical_validation_receipt_sha256,
        "canonical_counts": counts,
        "projection_counts": {
            "public_posts": len(posts),
            "public_linked_comments": len(comments),
            "ledger_only_unresolved_parent_comments": len(canonical_unresolved),
            "ledger_only_quarantined_comments": len(canonical_quarantine),
        },
        "checks": checks,
        "all_checks_passed": True,
        "boundaries": dict(BOUNDARIES),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-root", type=Path, required=True)
    parser.add_argument("--expected-public-manifest-sha256", required=True)
    parser.add_argument("--expected-dataset-version", required=True)
    parser.add_argument("--expected-source-snapshot-id", required=True)
    parser.add_argument("--canonical-root", type=Path, required=True)
    parser.add_argument("--expected-canonical-manifest-sha256", required=True)
    parser.add_argument("--canonical-validation-receipt", type=Path, required=True)
    parser.add_argument("--expected-canonical-validation-receipt-sha256", required=True)
    parser.add_argument("--coverage-attestation", type=Path)
    parser.add_argument("--expected-coverage-attestation-sha256")
    parser.add_argument("--receipt-output", type=Path, required=True)
    return parser


def _write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    output = path.expanduser().absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"receipt_output_already_exists:{output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(_canonical_bytes(receipt))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(name, 0o644)
        os.rename(name, output)
    except BaseException:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass
        raise


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if (args.coverage_attestation is None) != (
        args.expected_coverage_attestation_sha256 is None
    ):
        raise ValueError("coverage_attestation_and_sha_must_be_paired")
    coverage_attestation = None
    if args.coverage_attestation is not None:
        coverage_attestation = _object(
            _load(args.coverage_attestation, "coverage_attestation"),
            "coverage_attestation",
        )
    receipt = validate_public_base_projection(
        public_root=args.public_root,
        expected_public_manifest_sha256=args.expected_public_manifest_sha256,
        expected_dataset_version=args.expected_dataset_version,
        expected_source_snapshot_id=args.expected_source_snapshot_id,
        canonical_root=args.canonical_root,
        expected_canonical_manifest_sha256=args.expected_canonical_manifest_sha256,
        canonical_validation_receipt=args.canonical_validation_receipt,
        expected_canonical_validation_receipt_sha256=(
            args.expected_canonical_validation_receipt_sha256
        ),
        coverage_attestation=coverage_attestation,
        expected_coverage_attestation_sha256=(
            args.expected_coverage_attestation_sha256
        ),
    )
    _write_receipt(args.receipt_output, receipt)
    result = {
        "status": receipt["status"],
        "dataset_version": receipt["dataset_version"],
        "promotable": receipt["promotable"],
        "receipt_output": str(args.receipt_output.expanduser().absolute()),
        "receipt_sha256": _sha_path(args.receipt_output.expanduser().absolute()),
        "public_manifest_sha256": receipt["public_manifest_sha256"],
        "production_unchanged": True,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
