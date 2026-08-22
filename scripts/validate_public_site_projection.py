#!/usr/bin/env python3
"""Independently validate one immutable public Reddit VOC projection.

The validator deliberately does not import or call the public projection
builder.  It reconstructs the expected browser-facing bytes from the four
private datasets, rejects privacy and filesystem-policy violations, and writes
only one deterministic local receipt when invoked through the CLI.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Any, Iterable, Mapping
from xml.etree import ElementTree


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
VERSION_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,127}$")
EMAIL_RE = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE
)
# Avoid treating numeric Reddit IDs as telephone numbers: unseparated values
# are accepted as a phone candidate only when they are exactly ten digits or
# explicitly carry an international plus prefix.
PHONE_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"\+\d{10,15}|\d{10}|"
    r"(?:\+?\d{1,3}[ .-]?)?(?:\(\d{2,4}\)|\d{2,4})"
    r"[ .-]\d{3,4}[ .-]\d{3,4}"
    r")(?![A-Za-z0-9])"
)

BASE_FILES = (
    "aggregates.json",
    "posts.json",
    "comments.json",
    "quarantine.json",
    "tag-dictionary.json",
)
PUBLIC_BASE_FILES = (
    "aggregates-public.json",
    "posts-public.json",
    "comments-public.json",
    "tag-dictionary-public.json",
)
INSIGHTS_FILES = ("insights.json", "semantic-audit.json")
PERIODS = ("daily", "weekly", "monthly")
COLLECTIONS = ("current", "archive")
EXPECTED_PUBLIC_FILE_COUNT = 21

STRATEGY_FIELDS = {
    "biz_action",
    "business_impact",
    "default_priority",
    "dept_owner",
    "dictionary_default_priority",
    "suggested_action",
    "strategy_package",
}
ANALYSIS_SOURCE_TEXT_FIELDS = {
    "body",
    "content",
    "context_excerpt",
    "excerpt",
    "quote",
    "raw_body",
    "raw_content",
    "raw_text",
    "selftext",
    "source_text",
    "text",
    "title",
}
ANALYSIS_AUTHOR_FIELDS = {
    "author",
    "author_name",
    "author_pseudonym",
    "username",
}
SOURCE_RUN_FIELDS = {
    "collection_buckets",
    "dataset_id",
    "run_id",
    "source_boundaries",
    "source_cutoffs",
    "source_kinds",
    "source_occurrences",
    "source_stratum",
}
ANALYSIS_PRIVATE_FIELDS = (
    STRATEGY_FIELDS
    | ANALYSIS_SOURCE_TEXT_FIELDS
    | ANALYSIS_AUTHOR_FIELDS
    | SOURCE_RUN_FIELDS
)
PERSONA_PRIVATE_FIELDS = {
    "age",
    "author",
    "author_hash",
    "author_name",
    "author_pseudonym",
    "device",
    "email",
    "gender",
    "phone",
    "profile_url",
    "real_name",
    "reddit_username",
    "user_id",
    "username",
}
EVIDENCE_REF_FIELDS = ("entity_type", "entity_id", "post_id")

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
TAGGING_FIELDS = (
    "dictionary_version",
    "tag_ids",
    "aspect_tag_ids",
    "brand_tag_ids",
    "semantic_validation_status",
)
POST_FIELDS = (
    "post_id",
    "reddit_id",
    "title",
    "content",
    "subreddit",
    "permalink",
    "created_at_utc",
    "score",
    "upvote_ratio",
    "num_comments_reported",
    "linked_comment_count",
    "structural_coverage_grade",
    "count_completeness_status",
    "collection_buckets",
    "source_kinds",
    "mentioned_brands",
    "evidence_id",
)
GOVERNED_POST_FIELDS = tuple(
    field for field in POST_FIELDS if field not in {"collection_buckets", "source_kinds"}
) + (
    "event_created_at_utc",
    "comment_coverage_status",
    "brand_binding",
    "product_bindings",
)
COMMENT_FIELDS = (
    "comment_id",
    "reddit_id",
    "post_id",
    "parent_id",
    "body",
    "created_at_utc",
    "score",
    "depth",
    "deleted_or_removed",
    "is_bot",
    "include_in_voc_metrics",
    "evidence_id",
)
GOVERNED_COMMENT_FIELDS = COMMENT_FIELDS + (
    "event_created_at_utc",
    "brand_binding",
    "mentioned_brands",
    "product_bindings",
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
PRODUCT_CATEGORY_FIELDS = ("id", "name_en", "name_cn")
PRODUCT_FAMILY_FIELDS = ("id", "name_en", "name_cn")
PRODUCT_SPU_FIELDS = ("spu_id", "spu_name")
AGGREGATE_FIELDS = (
    "schema_version",
    "headline",
    "date_range",
    "post_sentiment",
    "comment_sentiment",
    "post_topics",
    "pain_points",
    "subreddit_posts",
    "subreddit_comments",
    "monthly_posts",
    "brand_sample_mentions",
    "coverage_grade",
    "count_completeness_status",
    "parent_link_status",
    "metric_notes",
)
AGGREGATE_TAGGING_FIELDS = (
    "dictionary_version",
    "posts_with_rule_tags",
    "comments_with_rule_tags",
    "posts_with_aspect_tags",
    "comments_with_aspect_tags",
    "top_tags",
)
PUBLIC_RULE_FIELDS = (
    "tag_id",
    "name_cn",
    "name_en",
    "theme",
    "sentiment",
    "tag_scope",
)
RISK_REPORT_FIELDS = (
    "contract_extension",
    "momcozy_metrics",
    "risk_themes",
    "product_analysis",
    "product_period_analysis",
    "competitor_context",
    "period_comparisons",
    "observed_count_comparisons",
    "trend",
)
REPORT_CORE_FIELDS = (
    "schema_version",
    "identity",
    "window",
    "headline",
    "observed_timeline",
    "communities",
    "topics",
    "pain_points",
    "brand_mentions",
    "promoted_signals",
    "attention_items",
    "evidence_posts",
    "capabilities",
    "interpretation_boundaries",
    "runtime_boundaries",
)
UNSAFE_SVG_ELEMENTS = {
    "a",
    "animate",
    "animatemotion",
    "animatetransform",
    "audio",
    "embed",
    "foreignobject",
    "iframe",
    "image",
    "object",
    "script",
    "set",
    "style",
    "use",
    "video",
}


@dataclass(frozen=True)
class ExpectedHashes:
    base_manifest_sha256: str
    insights_manifest_sha256: str
    reports_manifest_sha256: str
    personas_manifest_sha256: str
    public_base_manifest_sha256: str
    public_insights_manifest_sha256: str
    public_reports_manifest_sha256: str
    public_personas_manifest_sha256: str
    public_inventory_sha256: str
    cases_manifest_sha256: str
    cases_index_sha256: str
    cases_seed_content_sha256: str
    cases_legacy_content_sha256: str
    cases_approved_delta_content_sha256: str


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _object(value: Any, label: str) -> dict[str, Any]:
    _check(
        isinstance(value, dict) and all(isinstance(key, str) for key in value),
        f"object contract mismatch: {label}",
    )
    return value


def _rows(value: Any, label: str) -> list[dict[str, Any]]:
    _check(isinstance(value, list), f"list contract mismatch: {label}")
    return [_object(row, f"{label}[{index}]") for index, row in enumerate(value)]


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"string contract mismatch: {label}")
    return value


def _select(source: Mapping[str, Any], fields: Iterable[str], label: str) -> dict[str, Any]:
    field_list = tuple(fields)
    missing = [field for field in field_list if field not in source]
    _check(not missing, f"{label} missing fields: {missing}")
    return {field: source[field] for field in field_list}


def _load(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"JSON cannot be loaded: {label}") from exc


def _canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _hash_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _file_contract(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {"bytes": len(payload), "sha256": _hash_bytes(payload)}


def _bytes_contract(payload: bytes) -> dict[str, Any]:
    return {"bytes": len(payload), "sha256": _hash_bytes(payload)}


def _validate_expected_hashes(expected: ExpectedHashes) -> None:
    for field, value in expected.__dict__.items():
        _check(
            isinstance(value, str) and SHA256_RE.fullmatch(value) is not None,
            f"expected SHA-256 contract mismatch: {field}",
        )


def _safe_relative(value: str, *, label: str, suffix: str | None = None) -> PurePosixPath:
    relative = PurePosixPath(value)
    _check(
        bool(value)
        and not relative.is_absolute()
        and ".." not in relative.parts
        and "." not in relative.parts,
        f"unsafe relative path: {label}",
    )
    if suffix is not None:
        _check(relative.suffix == suffix, f"unsafe path suffix: {label}")
    return relative


def _safe_file(path: Path, *, label: str) -> Path:
    _check(path.exists(), f"file missing: {label}")
    _check(not path.is_symlink() and path.is_file(), f"unsafe file: {label}")
    return path


def _safe_directory(path: Path, *, label: str) -> Path:
    _check(path.exists(), f"directory missing: {label}")
    _check(not path.is_symlink() and path.is_dir(), f"unsafe directory: {label}")
    return path


def _load_manifest(directory: Path, expected_sha256: str, *, label: str) -> dict[str, Any]:
    _safe_directory(directory, label=label)
    path = _safe_file(directory / "manifest.json", label=f"{label}.manifest")
    _check(_hash_bytes(path.read_bytes()) == expected_sha256, f"{label} manifest SHA mismatch")
    return _object(_load(path, f"{label}.manifest"), f"{label}.manifest")


def _manifest_files(
    directory: Path,
    manifest: Mapping[str, Any],
    *,
    label: str,
    expected_paths: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    raw_files = _object(manifest.get("files"), f"{label}.files")
    if expected_paths is not None:
        _check(set(raw_files) == expected_paths, f"{label} file set mismatch")
    contracts: dict[str, dict[str, Any]] = {}
    for relative_text, raw_contract in sorted(raw_files.items()):
        relative = _safe_relative(relative_text, label=f"{label}.files.{relative_text}")
        contract = _select(
            _object(raw_contract, f"{label}.files.{relative_text}"),
            ("bytes", "sha256"),
            f"{label}.files.{relative_text}",
        )
        _check(
            isinstance(contract["bytes"], int)
            and not isinstance(contract["bytes"], bool)
            and contract["bytes"] >= 0,
            f"invalid byte count: {label}.files.{relative_text}",
        )
        _check(
            isinstance(contract["sha256"], str)
            and SHA256_RE.fullmatch(contract["sha256"]) is not None,
            f"invalid SHA-256: {label}.files.{relative_text}",
        )
        path = _safe_file(
            directory.joinpath(*relative.parts), label=f"{label}.files.{relative_text}"
        )
        _check(_file_contract(path) == contract, f"source file contract mismatch: {label}:{relative_text}")
        contracts[relative_text] = contract
    return contracts


def _project_nullable(value: Any, fields: tuple[str, ...], label: str) -> dict[str, Any] | None:
    if value is None:
        return None
    return _select(_object(value, label), fields, label)


def _project_product_bindings(value: Any, label: str) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for index, row in enumerate(_rows(value, label)):
        row_label = f"{label}[{index}]"
        binding = _select(row, PRODUCT_BINDING_FIELDS, row_label)
        binding["category"] = _select(
            _object(binding["category"], f"{row_label}.category"),
            PRODUCT_CATEGORY_FIELDS,
            f"{row_label}.category",
        )
        binding["product_family"] = _project_nullable(
            binding["product_family"], PRODUCT_FAMILY_FIELDS, f"{row_label}.product_family"
        )
        binding["exact_spu"] = _project_nullable(
            binding["exact_spu"], PRODUCT_SPU_FIELDS, f"{row_label}.exact_spu"
        )
        _check(
            binding["binding_level"] != "spu_exact" or binding["exact_spu"] is not None,
            f"spu_exact binding has no exact_spu: {row_label}",
        )
        projected.append(binding)
    return projected


def _project_tagging(value: Any, label: str) -> dict[str, Any]:
    source = _object(value, label)
    projected = _select(source, TAGGING_FIELDS, label)
    projected["matches"] = [
        _select(match, TAG_MATCH_FIELDS, f"{label}.matches[{index}]")
        for index, match in enumerate(_rows(source.get("matches"), f"{label}.matches"))
    ]
    return projected


def _project_posts(rows: list[dict[str, Any]], *, governed: bool) -> list[dict[str, Any]]:
    projected_rows: list[dict[str, Any]] = []
    fields = GOVERNED_POST_FIELDS if governed else POST_FIELDS
    for index, row in enumerate(rows):
        label = f"posts[{index}]"
        projected = _select(row, fields, label)
        if governed:
            projected["product_bindings"] = _project_product_bindings(
                projected["product_bindings"], f"{label}.product_bindings"
            )
        else:
            projected["author_pseudonym"] = None
        projected["analysis"] = _select(
            _object(row.get("analysis"), f"{label}.analysis"), ANALYSIS_FIELDS, f"{label}.analysis"
        )
        projected["tagging"] = _project_tagging(row.get("tagging"), f"{label}.tagging")
        projected_rows.append(projected)
    return projected_rows


def _project_comments(rows: list[dict[str, Any]], *, governed: bool) -> list[dict[str, Any]]:
    projected_rows: list[dict[str, Any]] = []
    fields = GOVERNED_COMMENT_FIELDS if governed else COMMENT_FIELDS
    for index, row in enumerate(rows):
        label = f"comments[{index}]"
        projected = _select(row, fields, label)
        if governed:
            projected["product_bindings"] = _project_product_bindings(
                projected["product_bindings"], f"{label}.product_bindings"
            )
        else:
            projected["author_pseudonym"] = None
        projected["analysis"] = _select(
            _object(row.get("analysis"), f"{label}.analysis"), ANALYSIS_FIELDS, f"{label}.analysis"
        )
        projected["tagging"] = _project_tagging(row.get("tagging"), f"{label}.tagging")
        projected_rows.append(projected)
    return projected_rows


def _project_aggregates(value: Any) -> dict[str, Any]:
    source = _object(value, "base.aggregates")
    projected = _select(source, AGGREGATE_FIELDS, "base.aggregates")
    projected["tagging"] = _select(
        _object(source.get("tagging"), "base.aggregates.tagging"),
        AGGREGATE_TAGGING_FIELDS,
        "base.aggregates.tagging",
    )
    return projected


def _project_dictionary(value: Any) -> dict[str, Any]:
    source = _object(value, "base.tag_dictionary")
    rules = _rows(source.get("rules"), "base.tag_dictionary.rules")
    _check(bool(rules), "tag dictionary has no rules")
    public_rules: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, rule in enumerate(rules):
        public_rule = _select(rule, PUBLIC_RULE_FIELDS, f"base.tag_dictionary.rules[{index}]")
        _check(
            all(isinstance(item, str) and item for item in public_rule.values()),
            f"tag dictionary public field mismatch: {index}",
        )
        tag_id = public_rule["tag_id"]
        _check(tag_id not in seen, f"duplicate public tag ID: {tag_id}")
        seen.add(tag_id)
        public_rules.append(public_rule)
    return {
        "schema_version": "reddit_voc_public_tag_dictionary_v1",
        "dictionary_version": source["dictionary_version"],
        "dictionary_sha256": source["dictionary_sha256"],
        "projection": {
            "audience": "public_ui",
            "source_schema_version": source["schema_version"],
            "rule_fields": list(PUBLIC_RULE_FIELDS),
            "internal_strategy_fields_excluded": True,
        },
        "rules": public_rules,
    }


def _project_evidence_refs(value: Any, label: str) -> list[dict[str, Any]]:
    return [
        _select(row, EVIDENCE_REF_FIELDS, f"{label}[{index}]")
        for index, row in enumerate(_rows(value, label))
    ]


def _project_analysis(value: Any, label: str) -> Any:
    if isinstance(value, dict):
        projected: dict[str, Any] = {}
        for key, child in value.items():
            if key in ANALYSIS_PRIVATE_FIELDS:
                continue
            if key == "evidence_refs":
                projected[key] = _project_evidence_refs(child, f"{label}.evidence_refs")
            else:
                projected[key] = _project_analysis(child, f"{label}.{key}")
        return projected
    if isinstance(value, list):
        return [_project_analysis(child, f"{label}[{index}]") for index, child in enumerate(value)]
    return value


def _project_semantic_audit(value: Any) -> dict[str, Any]:
    source = _object(value, "insights.semantic_audit")
    schema = source.get("schema_version")
    common = (
        "schema_version",
        "audit_version",
        "base_dataset_version",
        "base_manifest_sha256",
        "dictionary_version",
        "dictionary_sha256",
    )
    if schema == "reddit_voc_tag_semantic_audit_v2":
        projected = _select(source, common + ("summary", "boundaries"), "insights.semantic_audit")
        _select(
            _object(projected["summary"], "insights.semantic_audit.summary"),
            ("promoted_tags", "held_tags", "promoted_tag_ids", "held_tag_ids", "status"),
            "insights.semantic_audit.summary",
        )
        return _object(_project_analysis(projected, "insights.semantic_audit"), "projected semantic audit")
    if schema == "reddit_voc_tag_semantic_audit_v1":
        projected = _select(
            source,
            common + ("sample_sha256", "reviewer", "quality_gate", "summary", "boundaries"),
            "insights.semantic_audit",
        )
        public_tags: list[dict[str, Any]] = []
        for tag_index, tag in enumerate(_rows(source.get("tags"), "insights.semantic_audit.tags")):
            tag_label = f"insights.semantic_audit.tags[{tag_index}]"
            public_tag = _select(
                tag, ("tag_id", "promotion_status", "review_metrics", "gate_checks"), tag_label
            )
            public_tag["samples"] = []
            for sample_index, sample in enumerate(_rows(tag.get("samples"), f"{tag_label}.samples")):
                sample_label = f"{tag_label}.samples[{sample_index}]"
                public_sample = _select(sample, ("audit_id", "review"), sample_label)
                public_sample["review"] = _select(
                    _object(public_sample["review"], f"{sample_label}.review"),
                    ("label_verdict", "taxonomy_fit", "reason_code"),
                    f"{sample_label}.review",
                )
                public_tag["samples"].append(public_sample)
            public_tags.append(public_tag)
        projected["tags"] = public_tags
        return _object(_project_analysis(projected, "insights.semantic_audit"), "projected semantic audit")
    raise ValueError(f"unsupported semantic audit schema: {schema!r}")


def _governed_base(
    manifest: Mapping[str, Any], posts: list[dict[str, Any]], comments: list[dict[str, Any]]
) -> bool:
    semantic = manifest.get("semantic_boundaries")
    tagging = manifest.get("tagging")
    version = manifest.get("dataset_version")
    return bool(
        (isinstance(version, str) and version.endswith("_v2"))
        or (isinstance(semantic, dict) and semantic.get("product_category_analysis_supported") is True)
        or (isinstance(tagging, dict) and isinstance(tagging.get("product_entity_resolution"), dict))
        or any("product_bindings" in row for row in [*posts, *comments])
    )


def _base_public_manifest(source: Mapping[str, Any], *, governed: bool) -> dict[str, Any]:
    if governed:
        projected = _select(
            source,
            (
                "schema_version",
                "dataset_version",
                "generated_at_utc",
                "delivery_mode",
                "all_checks_passed",
                "production_unchanged",
                "provider_call",
                "live_send",
                "canonical_counts",
                "semantic_boundaries",
                "tagging",
            ),
            "base.manifest",
        )
    else:
        projected = deepcopy(dict(source))
        projected.pop("raw_author_count_used_only_for_privacy_bot_audit", None)
    projected["privacy"] = {
        "author_display": "suppressed",
        "contact_patterns_redacted": True,
        "html_fields_present": False,
        "known_archive_bots_excluded_from_voc_metrics": True,
        "raw_archive_public": False,
        "raw_author_fields_present": False,
    }
    projected["projection"] = {
        "audience": "public_ui",
        "author_linkage_excluded": True,
        "collection_run_metadata_excluded": True,
        "quarantine_records_excluded": True,
        "governed_product_fields_included": governed,
    }
    return projected


def _expected_base(
    directory: Path, expected_sha256: str
) -> tuple[str, dict[str, bytes], dict[tuple[str, str], tuple[str, str]]]:
    manifest = _load_manifest(directory, expected_sha256, label="base")
    _manifest_files(directory, manifest, label="base.manifest", expected_paths=set(BASE_FILES))
    version = _string(manifest.get("dataset_version"), "base.manifest.dataset_version")
    _check(VERSION_RE.fullmatch(version) is not None, "base version invalid")
    posts = _rows(_load(directory / "posts.json", "base.posts"), "base.posts")
    comments = _rows(_load(directory / "comments.json", "base.comments"), "base.comments")
    quarantine = _rows(_load(directory / "quarantine.json", "base.quarantine"), "base.quarantine")
    counts = _object(manifest.get("canonical_counts"), "base.manifest.canonical_counts")
    _check(counts.get("posts") == len(posts), "base post count mismatch")
    _check(counts.get("linked_comments") == len(comments), "base linked-comment count mismatch")
    _check(counts.get("quarantined_comments") == len(quarantine), "base quarantine count mismatch")
    _check(
        counts.get("stored_comments") == len(comments) + len(quarantine),
        "base stored-comment conservation mismatch",
    )
    governed = _governed_base(manifest, posts, comments)
    public_values: dict[str, Any] = {
        "aggregates-public.json": _project_aggregates(
            _load(directory / "aggregates.json", "base.aggregates")
        ),
        "posts-public.json": _project_posts(posts, governed=governed),
        "comments-public.json": _project_comments(comments, governed=governed),
        "tag-dictionary-public.json": _project_dictionary(
            _load(directory / "tag-dictionary.json", "base.tag_dictionary")
        ),
    }
    public_bytes = {name: _canonical_bytes(value) for name, value in public_values.items()}
    public_manifest = _base_public_manifest(manifest, governed=governed)
    public_manifest["files"] = {
        name: _bytes_contract(public_bytes[name]) for name in PUBLIC_BASE_FILES
    }
    public_bytes["manifest-public.json"] = _canonical_bytes(public_manifest)

    identities: dict[tuple[str, str], tuple[str, str]] = {}
    for index, row in enumerate(public_values["posts-public.json"]):
        post_id = _string(row.get("post_id"), f"public post identity: {index}")
        evidence_id = _string(row.get("evidence_id"), f"public post evidence: {index}")
        key = ("post", post_id)
        _check(key not in identities, f"duplicate public post identity: {post_id}")
        identities[key] = (post_id, evidence_id)
    for index, row in enumerate(public_values["comments-public.json"]):
        comment_id = _string(row.get("comment_id"), f"public comment identity: {index}")
        post_id = _string(row.get("post_id"), f"public comment parent: {index}")
        evidence_id = _string(row.get("evidence_id"), f"public comment evidence: {index}")
        key = ("comment", comment_id)
        _check(key not in identities, f"duplicate public comment identity: {comment_id}")
        identities[key] = (post_id, evidence_id)
    return version, public_bytes, identities


def _expected_insights(
    directory: Path,
    expected_sha256: str,
    *,
    base_version: str,
    base_manifest_sha256: str,
) -> tuple[str, dict[str, bytes], dict[str, Any]]:
    manifest = _load_manifest(directory, expected_sha256, label="insights")
    _manifest_files(directory, manifest, label="insights.manifest", expected_paths=set(INSIGHTS_FILES))
    version = _string(manifest.get("dataset_version"), "insights.manifest.dataset_version")
    _check(VERSION_RE.fullmatch(version) is not None, "insights version invalid")
    _check(manifest.get("base_dataset_version") == base_version, "insights base version lineage mismatch")
    _check(manifest.get("base_manifest_sha256") == base_manifest_sha256, "insights base SHA lineage mismatch")
    insights = _object(_load(directory / "insights.json", "insights.payload"), "insights.payload")
    _check(insights.get("dataset_version") == version, "insights payload version mismatch")
    schema = insights.get("schema_version")
    if schema == "reddit_voc_insights_v2":
        required = (
            "base_dataset_version",
            "generated_at_utc",
            "headline",
            "signals",
            "reference_dimensions",
            "held_tags",
            "interpretation_boundaries",
            "boundaries",
            "legacy_compatibility",
            "input_contract",
            "risk_command_center",
            "product_analysis",
            "report_booklets",
            "control_evidence",
        )
    elif schema == "reddit_voc_insights_v1":
        required = (
            "base_dataset_version",
            "generated_at_utc",
            "headline",
            "signals",
            "reference_dimensions",
            "held_tags",
            "interpretation_boundaries",
            "boundaries",
        )
    else:
        raise ValueError(f"unsupported insights schema: {schema!r}")
    _select(insights, ("schema_version", "dataset_version", *required), "insights.payload")
    public_values = {
        "insights.json": _project_analysis(insights, "insights.payload"),
        "semantic-audit.json": _project_semantic_audit(
            _load(directory / "semantic-audit.json", "insights.semantic_audit")
        ),
    }
    public_bytes = {name: _canonical_bytes(value) for name, value in public_values.items()}
    public_manifest = _object(_project_analysis(deepcopy(manifest), "insights.manifest"), "public insights manifest")
    public_manifest["projection"] = {
        "audience": "public_ui",
        "internal_strategy_fields_excluded": True,
        "source_text_and_author_fields_excluded": True,
        "evidence_refs_are_id_only": True,
        "semantic_audit_context_excluded": True,
    }
    public_manifest["files"] = {
        name: _bytes_contract(public_bytes[name]) for name in INSIGHTS_FILES
    }
    public_bytes["manifest.json"] = _canonical_bytes(public_manifest)
    return version, public_bytes, manifest


def _report_paths(index: Mapping[str, Any]) -> set[str]:
    paths: set[str] = set()
    for collection in COLLECTIONS:
        group = _object(index.get(collection), f"reports.index.{collection}")
        _check(set(group) == set(PERIODS), f"reports index period set mismatch: {collection}")
        for period in PERIODS:
            descriptor = _object(group[period], f"reports.index.{collection}.{period}")
            path = _string(descriptor.get("path"), f"reports.index.{collection}.{period}.path")
            relative = _safe_relative(path, label=f"reports.index.{collection}.{period}.path", suffix=".json")
            _check(relative.parts[0] == collection, f"report collection path mismatch: {path}")
            _check(path not in paths, f"duplicate report path: {path}")
            paths.add(path)
    return paths


def _validate_report_payload(value: Any, *, version: str, label: str, require_v2: bool) -> dict[str, Any]:
    report = _object(value, label)
    _check(report.get("schema_version") == "reddit_voc_report_v1", f"report schema mismatch: {label}")
    extension = report.get("contract_extension")
    _check(extension in {None, "reddit_voc_risk_report_v2"}, f"report extension mismatch: {label}")
    if require_v2:
        _check(extension == "reddit_voc_risk_report_v2", f"risk report downgrade: {label}")
    required = REPORT_CORE_FIELDS + (RISK_REPORT_FIELDS if extension == "reddit_voc_risk_report_v2" else ())
    _select(report, required, label)
    identity = _object(report.get("identity"), f"{label}.identity")
    _check(identity.get("dataset_version") == version, f"report version mismatch: {label}")
    if extension == "reddit_voc_risk_report_v2":
        comparisons = _object(report.get("observed_count_comparisons"), f"{label}.observed_count_comparisons")
        for group_name in ("previous_period", "year_over_year"):
            group = _object(comparisons.get(group_name), f"{label}.observed_count_comparisons.{group_name}")
            _select(group, ("post", "comment"), f"{label}.observed_count_comparisons.{group_name}")
        product_period = _object(report.get("product_period_analysis"), f"{label}.product_period_analysis")
        _select(
            product_period,
            (
                "schema_version",
                "period",
                "decision_subject",
                "scope_order",
                "metric_definitions",
                "category",
                "product_family",
                "spu_exact",
                "interpretation_boundary",
            ),
            f"{label}.product_period_analysis",
        )
        for scope in ("category", "product_family", "spu_exact"):
            _rows(product_period[scope], f"{label}.product_period_analysis.{scope}")
    return report


def _expected_reports(
    directory: Path,
    expected_sha256: str,
    *,
    base_version: str,
    base_manifest_sha256: str,
    insights_version: str,
    insights_manifest_sha256: str,
) -> tuple[str, dict[str, bytes], dict[str, Any]]:
    manifest = _load_manifest(directory, expected_sha256, label="reports")
    version = _string(manifest.get("dataset_version"), "reports.manifest.dataset_version")
    _check(VERSION_RE.fullmatch(version) is not None, "reports version invalid")
    _check(manifest.get("base_dataset_version") == base_version, "reports base version lineage mismatch")
    _check(manifest.get("base_manifest_sha256") == base_manifest_sha256, "reports base SHA lineage mismatch")
    _check(manifest.get("insights_dataset_version") == insights_version, "reports insights version lineage mismatch")
    _check(manifest.get("insights_manifest_sha256") == insights_manifest_sha256, "reports insights SHA lineage mismatch")
    index = _object(_load(directory / "report-index.json", "reports.index"), "reports.index")
    _check(index.get("schema_version") == "reddit_voc_report_index_v1", "report index schema mismatch")
    _check(index.get("dataset_version") == version, "report index version mismatch")
    extension = index.get("contract_extension")
    _check(extension in {None, "reddit_voc_report_index_v2"}, "report index extension mismatch")
    report_paths = _report_paths(index)
    expected_private_paths = {"report-index.json", *report_paths}
    _manifest_files(
        directory, manifest, label="reports.manifest", expected_paths=expected_private_paths
    )
    public_values: dict[str, Any] = {
        "report-index.json": _project_analysis(index, "reports.index")
    }
    for path in sorted(report_paths):
        report = _validate_report_payload(
            _load(directory / path, f"reports.{path}"),
            version=version,
            label=f"reports.{path}",
            require_v2=extension == "reddit_voc_report_index_v2",
        )
        public_values[path] = _project_analysis(report, f"reports.{path}")
    public_bytes = {name: _canonical_bytes(value) for name, value in public_values.items()}
    public_manifest = _object(_project_analysis(deepcopy(manifest), "reports.manifest"), "public reports manifest")
    public_manifest["projection"] = {
        "audience": "public_ui",
        "internal_strategy_fields_excluded": True,
        "source_text_and_author_fields_excluded": True,
        "evidence_refs_are_id_only": True,
    }
    ordered_paths = ["report-index.json", *sorted(report_paths)]
    public_manifest["files"] = {
        name: _bytes_contract(public_bytes[name]) for name in ordered_paths
    }
    public_bytes["manifest.json"] = _canonical_bytes(public_manifest)
    return version, public_bytes, manifest


def _persona_paths(manifest: Mapping[str, Any]) -> set[str]:
    files = _object(manifest.get("files"), "personas.manifest.files")
    paths: set[str] = set()
    for path in files:
        relative = _safe_relative(path, label=f"personas.manifest.files.{path}")
        allowed = path in {"personas.json", "persona-tags.json"} or (
            len(relative.parts) == 2
            and relative.parts[0] == "assets"
            and relative.suffix == ".svg"
        )
        _check(allowed, f"personas manifest contains non-public path: {path}")
        paths.add(path)
    _check({"personas.json", "persona-tags.json"}.issubset(paths), "persona public JSON missing")
    _check(len([path for path in paths if path.startswith("assets/")]) == 2, "persona SVG count mismatch")
    return paths


def _expected_personas(
    directory: Path,
    expected_sha256: str,
    *,
    base_version: str,
    base_manifest_sha256: str,
    insights_version: str,
    insights_manifest_sha256: str,
) -> tuple[str, dict[str, bytes], dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest = _load_manifest(directory, expected_sha256, label="personas")
    version = _string(manifest.get("dataset_version"), "personas.manifest.dataset_version")
    _check(VERSION_RE.fullmatch(version) is not None, "personas version invalid")
    _check(manifest.get("schema_version") == "reddit_voc_personas_manifest_v1", "personas manifest schema mismatch")
    _check(manifest.get("delivery_mode") == "versioned_static_evidence_personas", "personas delivery mismatch")
    _check(manifest.get("base_dataset_version") == base_version, "personas base version lineage mismatch")
    _check(manifest.get("base_manifest_sha256") == base_manifest_sha256, "personas base SHA lineage mismatch")
    _check(manifest.get("insights_dataset_version") == insights_version, "personas insights version lineage mismatch")
    _check(manifest.get("insights_manifest_sha256") == insights_manifest_sha256, "personas insights SHA lineage mismatch")
    boundaries = _object(manifest.get("boundaries"), "personas.manifest.boundaries")
    for field in (
        "author_level_personas",
        "derived_from_reddit_media",
        "identity_claim",
        "public_author_identifiers",
        "real_user_image",
    ):
        _check(boundaries.get(field) is False, f"persona privacy boundary mismatch: {field}")
    paths = _persona_paths(manifest)
    _manifest_files(directory, manifest, label="personas.manifest", expected_paths=paths)
    personas = _object(_load(directory / "personas.json", "personas.payload"), "personas.payload")
    persona_tags = _object(
        _load(directory / "persona-tags.json", "personas.tags"), "personas.tags"
    )
    _check(personas.get("schema_version") == "reddit_voc_personas_v1", "personas schema mismatch")
    _check(persona_tags.get("schema_version") == "reddit_voc_persona_tags_v1", "persona tags schema mismatch")
    _check(personas.get("dataset_version") == version, "personas payload version mismatch")
    _check(persona_tags.get("dataset_version") == version, "persona tags version mismatch")
    payloads: dict[str, bytes] = {
        "personas.json": _canonical_bytes(personas),
        "persona-tags.json": _canonical_bytes(persona_tags),
    }
    for path in sorted(paths - {"personas.json", "persona-tags.json"}):
        payloads[path] = (directory / path).read_bytes()
    payloads["manifest.json"] = _canonical_bytes(manifest)
    return version, payloads, manifest, personas, persona_tags


def _walk_values(value: Any, location: str = "$") -> Iterable[tuple[str, Any]]:
    yield location, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk_values(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_values(child, f"{location}[{index}]")


def _forbid_keys(value: Any, forbidden: set[str], *, label: str) -> None:
    for location, child in _walk_values(value, label):
        if isinstance(child, dict):
            overlap = set(child) & forbidden
            _check(not overlap, f"private keys present at {location}: {sorted(overlap)}")


def _validate_pii(value: Any, *, label: str) -> None:
    for location, child in _walk_values(value, label):
        if not isinstance(child, str):
            continue
        _check(EMAIL_RE.search(child) is None, f"email-like PII present: {location}")
        _check(PHONE_RE.search(child) is None, f"phone-like PII present: {location}")


def _validate_evidence_refs(
    value: Any,
    identities: Mapping[tuple[str, str], tuple[str, str]],
    *,
    label: str,
) -> int:
    count = 0
    for location, child in _walk_values(value, label):
        if not isinstance(child, dict) or "evidence_refs" not in child:
            continue
        refs = _rows(child["evidence_refs"], f"{location}.evidence_refs")
        for index, ref in enumerate(refs):
            ref_label = f"{location}.evidence_refs[{index}]"
            _check(set(ref) == set(EVIDENCE_REF_FIELDS), f"evidence ref field set mismatch: {ref_label}")
            entity_type = _string(ref.get("entity_type"), f"{ref_label}.entity_type")
            entity_id = _string(ref.get("entity_id"), f"{ref_label}.entity_id")
            post_id = ref.get("post_id")
            expected = identities.get((entity_type, entity_id))
            if expected is None:
                raise ValueError(f"evidence ref is not in Base: {ref_label}")
            _check(post_id == expected[0], f"evidence ref parent mismatch: {ref_label}")
            count += 1
    return count


def _validate_svg(payload: bytes, *, label: str) -> None:
    _check(len(payload) <= 1024 * 1024, f"SVG too large: {label}")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"SVG is not UTF-8: {label}") from exc
    lowered = text.casefold()
    _check("<!doctype" not in lowered and "<!entity" not in lowered, f"unsafe SVG declaration: {label}")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise ValueError(f"SVG cannot be parsed: {label}") from exc
    root_name = root.tag.rsplit("}", 1)[-1].casefold()
    _check(root_name == "svg", f"SVG root mismatch: {label}")
    for element in root.iter():
        element_name = element.tag.rsplit("}", 1)[-1].casefold()
        _check(element_name not in UNSAFE_SVG_ELEMENTS, f"unsafe SVG element: {label}:{element_name}")
        for raw_name, raw_value in element.attrib.items():
            attribute = raw_name.rsplit("}", 1)[-1].casefold()
            value = raw_value.strip().casefold()
            _check(not attribute.startswith("on"), f"unsafe SVG event attribute: {label}")
            _check(attribute not in {"href", "src"}, f"unsafe SVG reference attribute: {label}")
            _check(
                "javascript:" not in value
                and "data:" not in value
                and "url(" not in value
                and "expression(" not in value,
                f"unsafe SVG attribute value: {label}",
            )


def _validate_personas_privacy(
    personas: Mapping[str, Any],
    persona_tags: Mapping[str, Any],
    persona_payloads: Mapping[str, bytes],
    identities: Mapping[tuple[str, str], tuple[str, str]],
) -> int:
    _forbid_keys(personas, PERSONA_PRIVATE_FIELDS, label="personas.payload")
    _forbid_keys(persona_tags, PERSONA_PRIVATE_FIELDS, label="personas.tags")
    rows = _rows(personas.get("personas"), "personas.payload.personas")
    _check(personas.get("persona_count") == len(rows), "persona count mismatch")
    asset_paths = {path for path in persona_payloads if path.startswith("assets/")}
    for index, row in enumerate(rows):
        avatar = _object(row.get("avatar"), f"personas.payload.personas[{index}].avatar")
        _check(avatar.get("synthetic") is True, f"persona avatar is not synthetic: {index}")
        _check(avatar.get("real_user_image") is False, f"persona avatar claims a real user: {index}")
        _check(avatar.get("asset_path") in asset_paths, f"persona avatar asset is unbound: {index}")
    tag_boundaries = _object(persona_tags.get("boundaries"), "personas.tags.boundaries")
    _check(tag_boundaries.get("public_author_identifiers") is False, "persona tags expose authors")
    assignments = _rows(persona_tags.get("assignments"), "personas.tags.assignments")
    _check(persona_tags.get("assignment_count") == len(assignments), "persona assignment count mismatch")
    for index, assignment in enumerate(assignments):
        entity_type = _string(assignment.get("entity_type"), f"persona assignment entity_type: {index}")
        entity_id = _string(assignment.get("entity_id"), f"persona assignment entity_id: {index}")
        post_id = assignment.get("post_id")
        evidence_id = assignment.get("evidence_id")
        expected = identities.get((entity_type, entity_id))
        if expected is None:
            raise ValueError(f"persona assignment is not in Base: {index}")
        _check(post_id == expected[0], f"persona assignment parent mismatch: {index}")
        _check(evidence_id == expected[1], f"persona assignment evidence mismatch: {index}")
    for path in sorted(asset_paths):
        _validate_svg(persona_payloads[path], label=f"personas.{path}")
    return len(assignments)


def _tree_inventory(root: Path) -> tuple[dict[str, dict[str, Any]], set[str]]:
    _safe_directory(root, label="public_root")
    files: dict[str, dict[str, Any]] = {}
    directories: set[str] = set()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        _check(not path.is_symlink(), f"public tree contains symlink: {relative}")
        if path.is_dir():
            directories.add(relative)
        else:
            _check(path.is_file(), f"public tree contains unsafe entry: {relative}")
            _safe_relative(relative, label=f"public_tree.{relative}")
            files[relative] = _file_contract(path)
    return files, directories


def _expected_directories(paths: Iterable[str]) -> set[str]:
    directories: set[str] = set()
    for value in paths:
        relative = PurePosixPath(value)
        parent = relative.parent
        while parent != PurePosixPath("."):
            directories.add(parent.as_posix())
            parent = parent.parent
    return directories


def _verify_public_tree(root: Path, expected_payloads: Mapping[str, bytes]) -> dict[str, Any]:
    _check(len(expected_payloads) == EXPECTED_PUBLIC_FILE_COUNT, "expected public file count is not 21")
    actual, directories = _tree_inventory(root)
    _check(set(actual) == set(expected_payloads), "public projection path set mismatch")
    _check(directories == _expected_directories(expected_payloads), "public projection directory set mismatch")
    total_bytes = 0
    for path, expected_payload in sorted(expected_payloads.items()):
        actual_payload = (root / path).read_bytes()
        _check(actual_payload == expected_payload, f"public projection byte mismatch: {path}")
        _check(actual[path] == _bytes_contract(expected_payload), f"public projection contract mismatch: {path}")
        total_bytes += len(actual_payload)
    inventory_payload = "".join(
        f"{path}\t{actual[path]['bytes']}\t{actual[path]['sha256']}\n"
        for path in sorted(actual)
    ).encode("utf-8")
    inventory_sha256 = _hash_bytes(inventory_payload)
    return {
        "file_count": len(actual),
        "total_bytes": total_bytes,
        "inventory_sha256": inventory_sha256,
    }


def _validate_public_manifest_hashes(
    public_root: Path,
    *,
    base_version: str,
    insights_version: str,
    reports_version: str,
    personas_version: str,
    expected: ExpectedHashes,
) -> None:
    data_root = public_root / "data" / "reddit-voc"
    paths = {
        "base": (
            data_root / base_version / "manifest-public.json",
            expected.public_base_manifest_sha256,
        ),
        "insights": (
            data_root / insights_version / "public" / "manifest.json",
            expected.public_insights_manifest_sha256,
        ),
        "reports": (
            data_root / reports_version / "public" / "manifest.json",
            expected.public_reports_manifest_sha256,
        ),
        "personas": (
            data_root / personas_version / "manifest.json",
            expected.public_personas_manifest_sha256,
        ),
    }
    for label, (path, expected_sha) in paths.items():
        _check(_hash_bytes(_safe_file(path, label=f"public_{label}_manifest").read_bytes()) == expected_sha, f"public {label} manifest SHA mismatch")


def _validate_cases(
    manifest_path: Path,
    index_path: Path,
    *,
    expected: ExpectedHashes,
) -> dict[str, Any]:
    _check(manifest_path.name == "manifest.v1.json", "cases manifest filename mismatch")
    _check(index_path.name == "case-index.v1.json", "cases index filename mismatch")
    manifest_bytes = _safe_file(manifest_path, label="cases.manifest").read_bytes()
    index_bytes = _safe_file(index_path, label="cases.index").read_bytes()
    _check(_hash_bytes(manifest_bytes) == expected.cases_manifest_sha256, "cases manifest SHA mismatch")
    _check(_hash_bytes(index_bytes) == expected.cases_index_sha256, "cases index SHA mismatch")
    manifest = _object(_load(manifest_path, "cases.manifest"), "cases.manifest")
    index = _object(_load(index_path, "cases.index"), "cases.index")
    _check(manifest.get("schemaVersion") == 1 and index.get("schemaVersion") == 1, "cases schema mismatch")
    version = _string(manifest.get("datasetVersion"), "cases.manifest.datasetVersion")
    _check(
        version.startswith("case_catalog_")
        and VERSION_RE.fullmatch(version) is not None
        and index.get("datasetVersion") == version,
        "cases dataset version mismatch",
    )
    seed = _object(manifest.get("seed"), "cases.manifest.seed")
    legacy = _object(manifest.get("legacyUnverified"), "cases.manifest.legacyUnverified")
    approved = _object(manifest.get("approvedDelta"), "cases.manifest.approvedDelta")
    approved_rows = index.get("approvedDelta")
    if not isinstance(approved_rows, list):
        raise ValueError("cases approved delta is not a list")
    _check(seed.get("source") == "bundled_seed" and seed.get("count") == 38, "cases selected stock changed")
    _check(
        legacy.get("source") == "bundled_legacy_snapshot" and legacy.get("count") == 12,
        "cases unverified stock changed",
    )
    _check(
        approved.get("source") == "versioned_static_index"
        and approved.get("count") == len(approved_rows) == 0,
        "cases approved delta is not empty",
    )
    _check(seed.get("contentSha256") == expected.cases_seed_content_sha256, "cases seed content SHA mismatch")
    _check(
        legacy.get("contentSha256") == expected.cases_legacy_content_sha256,
        "cases legacy content SHA mismatch",
    )
    approved_payload = json.dumps(
        approved_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    _check(
        _hash_bytes(approved_payload) == expected.cases_approved_delta_content_sha256
        == approved.get("contentSha256"),
        "cases approved delta content SHA mismatch",
    )
    index_contract = _object(manifest.get("index"), "cases.manifest.index")
    _check(index_contract.get("path") == "/data/cases/case-index.v1.json", "cases index path mismatch")
    _check(index_contract.get("sha256") == expected.cases_index_sha256, "cases index lineage mismatch")
    provenance = _object(manifest.get("provenance"), "cases.manifest.provenance")
    _check(provenance.get("networkSearch") is False, "cases network boundary mismatch")
    _validate_pii(manifest, label="cases.manifest")
    _validate_pii(index, label="cases.index")
    return {
        "dataset_version": version,
        "selected_count": 38,
        "unverified_count": 12,
        "approved_delta_count": 0,
        "manifest_sha256": expected.cases_manifest_sha256,
        "index_sha256": expected.cases_index_sha256,
        "seed_content_sha256": expected.cases_seed_content_sha256,
        "legacy_unverified_content_sha256": expected.cases_legacy_content_sha256,
        "approved_delta_content_sha256": expected.cases_approved_delta_content_sha256,
    }


def validate_public_projection(
    *,
    base_dir: Path,
    insights_dir: Path,
    reports_dir: Path,
    personas_dir: Path,
    public_root: Path,
    cases_manifest: Path,
    cases_index: Path,
    expected: ExpectedHashes,
) -> dict[str, Any]:
    """Validate public bytes, privacy, lineage, cases, and side-effect boundaries."""

    _validate_expected_hashes(expected)
    base_version, base_payloads, identities = _expected_base(
        base_dir, expected.base_manifest_sha256
    )
    insights_version, insights_payloads, insights_manifest = _expected_insights(
        insights_dir,
        expected.insights_manifest_sha256,
        base_version=base_version,
        base_manifest_sha256=expected.base_manifest_sha256,
    )
    reports_version, reports_payloads, reports_manifest = _expected_reports(
        reports_dir,
        expected.reports_manifest_sha256,
        base_version=base_version,
        base_manifest_sha256=expected.base_manifest_sha256,
        insights_version=insights_version,
        insights_manifest_sha256=expected.insights_manifest_sha256,
    )
    (
        personas_version,
        persona_payloads,
        personas_manifest,
        personas,
        persona_tags,
    ) = _expected_personas(
        personas_dir,
        expected.personas_manifest_sha256,
        base_version=base_version,
        base_manifest_sha256=expected.base_manifest_sha256,
        insights_version=insights_version,
        insights_manifest_sha256=expected.insights_manifest_sha256,
    )
    _check(
        len({base_version, insights_version, reports_version, personas_version}) == 4,
        "public dataset versions are not distinct",
    )

    expected_payloads: dict[str, bytes] = {}
    prefix = "data/reddit-voc"
    for name, payload in base_payloads.items():
        expected_payloads[f"{prefix}/{base_version}/{name}"] = payload
    for name, payload in insights_payloads.items():
        expected_payloads[f"{prefix}/{insights_version}/public/{name}"] = payload
    for name, payload in reports_payloads.items():
        expected_payloads[f"{prefix}/{reports_version}/public/{name}"] = payload
    for name, payload in persona_payloads.items():
        expected_payloads[f"{prefix}/{personas_version}/{name}"] = payload

    inventory = _verify_public_tree(public_root, expected_payloads)
    _check(
        inventory["inventory_sha256"] == expected.public_inventory_sha256,
        "public inventory SHA mismatch",
    )
    _validate_public_manifest_hashes(
        public_root,
        base_version=base_version,
        insights_version=insights_version,
        reports_version=reports_version,
        personas_version=personas_version,
        expected=expected,
    )

    analysis_documents: list[tuple[str, Any]] = []
    for dataset_label, payloads in (
        ("public.insights", insights_payloads),
        ("public.reports", reports_payloads),
    ):
        for name, payload in sorted(payloads.items()):
            if name.endswith(".json"):
                analysis_documents.append((f"{dataset_label}.{name}", json.loads(payload)))
    evidence_refs = 0
    for label, value in analysis_documents:
        _forbid_keys(value, ANALYSIS_PRIVATE_FIELDS, label=label)
        _validate_pii(value, label=label)
        evidence_refs += _validate_evidence_refs(value, identities, label=label)
    for name, payload in base_payloads.items():
        if name.endswith(".json"):
            _validate_pii(json.loads(payload), label=f"public.base.{name}")
    persona_assignments = _validate_personas_privacy(
        personas, persona_tags, persona_payloads, identities
    )
    _validate_pii(personas, label="public.personas")
    _validate_pii(persona_tags, label="public.persona_tags")
    cases = _validate_cases(cases_manifest, cases_index, expected=expected)

    generated_at = _string(
        insights_manifest.get("generated_at_utc"), "insights.manifest.generated_at_utc"
    )
    checks = {
        "expected_private_and_public_manifest_sha256": True,
        "private_manifest_file_contracts": True,
        "public_exact_21_path_byte_sha_inventory": True,
        "public_no_extra_symlink_or_path_traversal": True,
        "four_public_manifests_match_private_lineage": True,
        "base_public_field_and_count_conservation": True,
        "analysis_and_persona_private_fields_absent": True,
        "evidence_references_resolve_to_base": True,
        "synthetic_svg_assets_safe": True,
        "email_and_phone_patterns_absent": True,
        "case_gallery_38_12_0_and_content_hashes": True,
        "side_effect_boundaries": True,
    }
    return {
        "schema_version": "reddit_voc_public_projection_validation_v1",
        "validated_at_utc": generated_at,
        "status": "passed_release_candidate",
        "public_inventory": inventory,
        "lineage": {
            "base": {
                "dataset_version": base_version,
                "private_manifest_sha256": expected.base_manifest_sha256,
                "public_manifest_sha256": expected.public_base_manifest_sha256,
            },
            "insights": {
                "dataset_version": insights_version,
                "private_manifest_sha256": expected.insights_manifest_sha256,
                "public_manifest_sha256": expected.public_insights_manifest_sha256,
            },
            "reports": {
                "dataset_version": reports_version,
                "private_manifest_sha256": expected.reports_manifest_sha256,
                "public_manifest_sha256": expected.public_reports_manifest_sha256,
            },
            "personas": {
                "dataset_version": personas_version,
                "private_manifest_sha256": expected.personas_manifest_sha256,
                "public_manifest_sha256": expected.public_personas_manifest_sha256,
            },
        },
        "cases": cases,
        "counts": {
            "evidence_refs": evidence_refs,
            "persona_assignments": persona_assignments,
        },
        "checks": checks,
        "production_unchanged": True,
        "provider_call": False,
        "provider_attempt_made": False,
        "database_write": False,
        "remote_write": False,
        "deploy": False,
        "live_send": False,
        "webhook_send": False,
        "schedule_change": False,
    }


def write_immutable_receipt(path: Path, value: Mapping[str, Any]) -> str:
    payload = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    if path.exists() or path.is_symlink():
        _check(not path.is_symlink() and path.is_file(), "validation receipt path unsafe")
        _check(path.read_bytes() == payload, "validation receipt immutable collision")
        _check(path.stat().st_mode & 0o777 == 0o600, "validation receipt mode mismatch")
        _check(
            not path.parent.is_symlink() and path.parent.stat().st_mode & 0o777 == 0o700,
            "validation receipt parent mode mismatch",
        )
        return "no_change"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _check(not path.parent.is_symlink() and path.parent.is_dir(), "validation receipt parent unsafe")
    os.chmod(path.parent, 0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    os.chmod(path, 0o600)
    return "created"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", type=Path, required=True)
    parser.add_argument("--insights-dir", type=Path, required=True)
    parser.add_argument("--reports-dir", type=Path, required=True)
    parser.add_argument("--personas-dir", type=Path, required=True)
    parser.add_argument("--public-root", type=Path, required=True)
    parser.add_argument("--cases-manifest", type=Path, required=True)
    parser.add_argument("--cases-index", type=Path, required=True)
    for name in ExpectedHashes.__dataclass_fields__:
        parser.add_argument(f"--expected-{name.replace('_', '-')}", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    expected = ExpectedHashes(
        **{
            name: getattr(args, f"expected_{name}")
            for name in ExpectedHashes.__dataclass_fields__
        }
    )
    result = validate_public_projection(
        base_dir=args.base_dir,
        insights_dir=args.insights_dir,
        reports_dir=args.reports_dir,
        personas_dir=args.personas_dir,
        public_root=args.public_root,
        cases_manifest=args.cases_manifest,
        cases_index=args.cases_index,
        expected=expected,
    )
    write_status = write_immutable_receipt(args.receipt, result)
    print(json.dumps({**result, "receipt_write_status": write_status}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
