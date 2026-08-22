#!/usr/bin/env python3
"""Build the minimum browser-facing projection from governed static artifacts."""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Any

try:
    from build_public_tag_dictionary import build_public_dictionary
except ModuleNotFoundError:  # Imported as scripts.build_public_site_projection.
    from scripts.build_public_tag_dictionary import build_public_dictionary


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
VERSION_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{2,127}$")
PERSONAS_MANIFEST_SCHEMA = "reddit_voc_personas_manifest_v1"
PERSONAS_SCHEMA = "reddit_voc_personas_v1"
PERSONA_TAGS_SCHEMA = "reddit_voc_persona_tags_v1"
PERSONAS_DELIVERY_MODE = "versioned_static_evidence_personas"
REPORT_INDEX_SCHEMA = "reddit_voc_report_index_v1"
REPORT_INDEX_V2_EXTENSION = "reddit_voc_report_index_v2"
REPORT_SCHEMA = "reddit_voc_report_v1"
RISK_REPORT_V2_EXTENSION = "reddit_voc_risk_report_v2"
RISK_REPORT_V2_FIELDS = (
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
PERSONA_PRIVATE_FIELDS = {
    "age",
    "author",
    "author_name",
    "author_pseudonym",
    "device",
    "gender",
    "profile_url",
    "username",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def compact_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(compact_bytes(value))


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _validate_version(value: str, label: str) -> None:
    if VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} is not a safe dataset version: {value!r}")


def _tree_contract(root: Path) -> dict[str, Any]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError(f"publication root is unsafe: {root}")
    directories: list[str] = []
    files: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValueError(f"publication tree contains a symlink: {relative}")
        if path.is_dir():
            directories.append(relative)
        elif path.is_file():
            files[relative] = file_contract(path)
        else:
            raise ValueError(f"publication tree contains an unsafe entry: {relative}")
    return {"directories": directories, "files": files}


def file_contract(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {"bytes": len(payload), "sha256": sha256(payload).hexdigest()}


def allowlisted(source: dict[str, Any], fields: tuple[str, ...], label: str) -> dict[str, Any]:
    missing = [field for field in fields if field not in source]
    if missing:
        raise ValueError(f"{label} missing fields: {missing}")
    return {field: source[field] for field in fields}


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be an object")
    return value


def require_object_list(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(value):
        rows.append(require_object(row, f"{label}[{index}]"))
    return rows


def require_dataset_version(
    source: dict[str, Any], expected_version: str, label: str
) -> None:
    actual = source.get("dataset_version")
    if actual != expected_version:
        raise ValueError(
            f"{label}.dataset_version mismatch: expected {expected_version!r}, "
            f"got {actual!r}"
        )


def verify_source_file_contract(
    root: Path,
    relative_path: str,
    contract: Any,
    *,
    label: str,
) -> None:
    relative = PurePosixPath(relative_path)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.suffix != ".json"
    ):
        raise ValueError(f"{label} contains unsafe JSON path: {relative_path!r}")
    expected = require_object(contract, f"{label}.{relative_path}")
    required = allowlisted(
        expected, ("bytes", "sha256"), f"{label}.{relative_path}"
    )
    path = root.joinpath(*relative.parts)
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} source file is missing: {relative_path}")
    if required != file_contract(path):
        raise ValueError(f"{label} source file contract mismatch: {relative_path}")


def verify_source_manifest_files(
    root: Path,
    manifest: dict[str, Any],
    required_paths: tuple[str, ...],
    *,
    label: str,
) -> dict[str, Any]:
    files = require_object(manifest.get("files"), f"{label}.files")
    missing = [path for path in required_paths if path not in files]
    if missing:
        raise ValueError(f"{label}.files missing fields: {missing}")
    for relative_path in required_paths:
        verify_source_file_contract(
            root, relative_path, files[relative_path], label=f"{label}.files"
        )
    return files


def _walk_object_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            key for child in value.values() for key in _walk_object_keys(child)
        }
    if isinstance(value, list):
        return {key for child in value for key in _walk_object_keys(child)}
    return set()


def _persona_relative_path(value: str) -> PurePosixPath:
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"personas manifest contains an unsafe path: {value!r}")
    if value in {"personas.json", "persona-tags.json"}:
        return relative
    if (
        len(relative.parts) == 2
        and relative.parts[0] == "assets"
        and relative.suffix == ".svg"
    ):
        return relative
    raise ValueError(f"personas manifest contains a non-public path: {value!r}")


def _verify_personas_source(
    source_dir: Path, *, personas_version: str
) -> tuple[dict[str, Any], list[PurePosixPath]]:
    manifest = require_object(
        load_json(source_dir / "manifest.json"), "personas manifest"
    )
    require_dataset_version(manifest, personas_version, "personas manifest")
    if manifest.get("schema_version") != PERSONAS_MANIFEST_SCHEMA:
        raise ValueError("personas manifest schema mismatch")
    if manifest.get("delivery_mode") != PERSONAS_DELIVERY_MODE:
        raise ValueError("personas manifest delivery mode mismatch")
    boundaries = require_object(
        manifest.get("boundaries"), "personas manifest.boundaries"
    )
    for field in (
        "author_level_personas",
        "derived_from_reddit_media",
        "identity_claim",
        "public_author_identifiers",
        "real_user_image",
    ):
        if boundaries.get(field) is not False:
            raise ValueError(f"personas privacy boundary is not fail-closed: {field}")

    files = require_object(manifest.get("files"), "personas manifest.files")
    if not {"personas.json", "persona-tags.json"}.issubset(files):
        raise ValueError("personas manifest is missing required public JSON files")
    relative_paths = sorted(_persona_relative_path(name) for name in files)
    for relative in relative_paths:
        expected = require_object(
            files[relative.as_posix()],
            f"personas manifest.files.{relative.as_posix()}",
        )
        required = allowlisted(
            expected,
            ("bytes", "sha256"),
            f"personas manifest.files.{relative.as_posix()}",
        )
        path = source_dir.joinpath(*relative.parts)
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"personas source file is missing or unsafe: {relative}")
        if file_contract(path) != required:
            raise ValueError(f"personas source file contract mismatch: {relative}")

    personas = require_object(load_json(source_dir / "personas.json"), "personas")
    persona_tags = require_object(
        load_json(source_dir / "persona-tags.json"), "persona tags"
    )
    if personas.get("schema_version") != PERSONAS_SCHEMA:
        raise ValueError("personas schema mismatch")
    if persona_tags.get("schema_version") != PERSONA_TAGS_SCHEMA:
        raise ValueError("persona tags schema mismatch")
    require_dataset_version(personas, personas_version, "personas")
    require_dataset_version(persona_tags, personas_version, "persona tags")
    private_fields = (
        _walk_object_keys(personas) | _walk_object_keys(persona_tags)
    ) & PERSONA_PRIVATE_FIELDS
    if private_fields:
        raise ValueError(
            f"personas public artifacts contain private fields: {sorted(private_fields)}"
        )
    tag_boundaries = require_object(
        persona_tags.get("boundaries"), "persona tags.boundaries"
    )
    if tag_boundaries.get("public_author_identifiers") is not False:
        raise ValueError("persona tags expose public author identifiers")
    return manifest, relative_paths


def _copy_personas_projection(
    source_dir: Path,
    destination_dir: Path,
    *,
    personas_version: str,
) -> None:
    manifest, relative_paths = _verify_personas_source(
        source_dir, personas_version=personas_version
    )
    for relative in relative_paths:
        source = source_dir.joinpath(*relative.parts)
        destination = destination_dir.joinpath(*relative.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    write_json(destination_dir / "manifest.json", manifest)


def _project_nullable_object(
    value: Any,
    fields: tuple[str, ...],
    label: str,
) -> dict[str, Any] | None:
    if value is None:
        return None
    return allowlisted(require_object(value, label), fields, label)


def project_product_bindings(value: Any, label: str) -> list[dict[str, Any]]:
    rows = require_object_list(value, label)
    projected: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        row_label = f"{label}[{index}]"
        binding = allowlisted(row, PRODUCT_BINDING_FIELDS, row_label)
        binding["category"] = allowlisted(
            require_object(binding["category"], f"{row_label}.category"),
            PRODUCT_CATEGORY_FIELDS,
            f"{row_label}.category",
        )
        binding["product_family"] = _project_nullable_object(
            binding["product_family"],
            PRODUCT_FAMILY_FIELDS,
            f"{row_label}.product_family",
        )
        binding["exact_spu"] = _project_nullable_object(
            binding["exact_spu"],
            PRODUCT_SPU_FIELDS,
            f"{row_label}.exact_spu",
        )
        if binding["binding_level"] == "spu_exact" and binding["exact_spu"] is None:
            raise ValueError(f"{row_label}.exact_spu is required for spu_exact")
        projected.append(binding)
    return projected


def project_tagging(source: dict[str, Any]) -> dict[str, Any]:
    projected = allowlisted(source, TAGGING_FIELDS, "tagging")
    matches = require_object_list(source.get("matches"), "tagging.matches")
    projected["matches"] = [
        allowlisted(match, TAG_MATCH_FIELDS, f"tagging.matches[{index}]")
        for index, match in enumerate(matches)
    ]
    return projected


def project_posts(
    rows: list[dict[str, Any]], *, governed_fields: bool = False
) -> list[dict[str, Any]]:
    result = []
    fields = GOVERNED_POST_FIELDS if governed_fields else POST_FIELDS
    for index, row in enumerate(rows):
        label = f"post[{index}]"
        projected = allowlisted(row, fields, label)
        if governed_fields:
            projected["product_bindings"] = project_product_bindings(
                projected["product_bindings"], f"{label}.product_bindings"
            )
        else:
            projected["author_pseudonym"] = None
        projected["analysis"] = allowlisted(
            require_object(row.get("analysis"), f"{label}.analysis"),
            ANALYSIS_FIELDS,
            f"{label}.analysis",
        )
        projected["tagging"] = project_tagging(
            require_object(row.get("tagging"), f"{label}.tagging")
        )
        result.append(projected)
    return result


def project_comments(
    rows: list[dict[str, Any]], *, governed_fields: bool = False
) -> list[dict[str, Any]]:
    result = []
    fields = GOVERNED_COMMENT_FIELDS if governed_fields else COMMENT_FIELDS
    for index, row in enumerate(rows):
        label = f"comment[{index}]"
        projected = allowlisted(row, fields, label)
        if governed_fields:
            projected["product_bindings"] = project_product_bindings(
                projected["product_bindings"], f"{label}.product_bindings"
            )
        else:
            projected["author_pseudonym"] = None
        projected["analysis"] = allowlisted(
            require_object(row.get("analysis"), f"{label}.analysis"),
            ANALYSIS_FIELDS,
            f"{label}.analysis",
        )
        projected["tagging"] = project_tagging(
            require_object(row.get("tagging"), f"{label}.tagging")
        )
        result.append(projected)
    return result


def project_aggregates(source: dict[str, Any]) -> dict[str, Any]:
    projected = allowlisted(source, AGGREGATE_FIELDS, "aggregates")
    projected["tagging"] = allowlisted(
        require_object(source.get("tagging"), "aggregates.tagging"),
        AGGREGATE_TAGGING_FIELDS,
        "aggregates tagging",
    )
    return projected


def _project_evidence_refs(value: Any, label: str) -> list[dict[str, Any]]:
    rows = require_object_list(value, label)
    return [
        allowlisted(row, EVIDENCE_REF_FIELDS, f"{label}[{index}]")
        for index, row in enumerate(rows)
    ]


def project_analysis_artifact(value: Any, label: str = "analysis artifact") -> Any:
    if isinstance(value, dict):
        projected: dict[str, Any] = {}
        for key, child in value.items():
            if key in ANALYSIS_PRIVATE_FIELDS:
                continue
            if key == "evidence_refs":
                projected[key] = _project_evidence_refs(
                    child, f"{label}.evidence_refs"
                )
            else:
                projected[key] = project_analysis_artifact(
                    child, f"{label}.{key}"
                )
        return projected
    if isinstance(value, list):
        return [
            project_analysis_artifact(child, f"{label}[{index}]")
            for index, child in enumerate(value)
        ]
    return value


def remove_strategy_fields(value: Any) -> Any:
    """Backward-compatible alias for the stricter public analysis projection."""

    return project_analysis_artifact(value)


def project_semantic_audit(source: dict[str, Any]) -> dict[str, Any]:
    schema_version = source.get("schema_version")
    common_fields = (
        "schema_version",
        "audit_version",
        "base_dataset_version",
        "base_manifest_sha256",
        "dictionary_version",
        "dictionary_sha256",
    )
    if schema_version == "reddit_voc_tag_semantic_audit_v1":
        projected = allowlisted(
            source,
            common_fields
            + (
                "sample_sha256",
                "reviewer",
                "quality_gate",
                "summary",
                "boundaries",
            ),
            "semantic audit v1",
        )
        projected["tags"] = []
        tags = require_object_list(source.get("tags"), "semantic audit v1.tags")
        for tag_index, tag in enumerate(tags):
            tag_label = f"semantic audit v1.tags[{tag_index}]"
            public_tag = allowlisted(
                tag,
                ("tag_id", "promotion_status", "review_metrics", "gate_checks"),
                tag_label,
            )
            samples = require_object_list(tag.get("samples"), f"{tag_label}.samples")
            public_tag["samples"] = []
            for sample_index, sample in enumerate(samples):
                sample_label = f"{tag_label}.samples[{sample_index}]"
                sample_core = allowlisted(sample, ("audit_id", "review"), sample_label)
                sample_core["review"] = allowlisted(
                    require_object(sample_core["review"], f"{sample_label}.review"),
                    ("label_verdict", "taxonomy_fit", "reason_code"),
                    f"{sample_label}.review",
                )
                public_tag["samples"].append(sample_core)
            projected["tags"].append(public_tag)
        return project_analysis_artifact(projected, "semantic audit v1")
    if schema_version == "reddit_voc_tag_semantic_audit_v2":
        projected = allowlisted(
            source,
            common_fields + ("summary", "boundaries"),
            "semantic audit v2",
        )
        summary = require_object(projected["summary"], "semantic audit v2.summary")
        allowlisted(
            summary,
            (
                "promoted_tags",
                "held_tags",
                "promoted_tag_ids",
                "held_tag_ids",
                "status",
            ),
            "semantic audit v2.summary",
        )
        return project_analysis_artifact(projected, "semantic audit v2")
    raise ValueError(f"unsupported semantic audit schema: {schema_version!r}")


def _is_governed_base(
    manifest: dict[str, Any],
    posts: list[dict[str, Any]],
    comments: list[dict[str, Any]],
) -> bool:
    semantic = manifest.get("semantic_boundaries")
    tagging = manifest.get("tagging")
    dataset_version = manifest.get("dataset_version")
    return bool(
        (isinstance(dataset_version, str) and dataset_version.endswith("_v2"))
        or (
            isinstance(semantic, dict)
            and semantic.get("product_category_analysis_supported") is True
        )
        or (
            isinstance(tagging, dict)
            and isinstance(tagging.get("product_entity_resolution"), dict)
        )
        or any("product_bindings" in row for row in [*posts, *comments])
    )


def _project_base_manifest(
    source: dict[str, Any], *, governed_fields: bool
) -> dict[str, Any]:
    if governed_fields:
        projected = allowlisted(
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
            "base manifest v2",
        )
    else:
        projected = deepcopy(source)
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
        "governed_product_fields_included": governed_fields,
    }
    return projected


def _validate_insights_payload(
    source: dict[str, Any], *, insights_version: str
) -> None:
    require_dataset_version(source, insights_version, "insights")
    schema = source.get("schema_version")
    if schema == "reddit_voc_insights_v1":
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
    elif schema == "reddit_voc_insights_v2":
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
    else:
        raise ValueError(f"unsupported insights schema: {schema!r}")
    allowlisted(source, ("schema_version", "dataset_version", *required), "insights")


def _validate_report_index(
    source: dict[str, Any], *, reports_version: str
) -> bool:
    require_dataset_version(source, reports_version, "report index")
    if source.get("schema_version") != REPORT_INDEX_SCHEMA:
        raise ValueError("report index has unsupported schema")
    contract_extension = source.get("contract_extension")
    if contract_extension not in {None, REPORT_INDEX_V2_EXTENSION}:
        raise ValueError("report index has unsupported contract extension")
    allowlisted(
        source,
        ("schema_version", "dataset_version", "as_of_utc", "timezone", "current", "archive"),
        "report index",
    )
    for collection in ("current", "archive"):
        group = require_object(source[collection], f"report index.{collection}")
        missing = [period for period in ("daily", "weekly", "monthly") if period not in group]
        if missing:
            raise ValueError(f"report index.{collection} missing fields: {missing}")
    return contract_extension == REPORT_INDEX_V2_EXTENSION


def _validate_risk_report_v2_business_fields(
    source: dict[str, Any], *, label: str
) -> None:
    observed_comparisons = require_object(
        source["observed_count_comparisons"],
        f"{label}.observed_count_comparisons",
    )
    for comparison_group in ("previous_period", "year_over_year"):
        group = require_object(
            observed_comparisons.get(comparison_group),
            f"{label}.observed_count_comparisons.{comparison_group}",
        )
        allowlisted(
            group,
            ("post", "comment"),
            f"{label}.observed_count_comparisons.{comparison_group}",
        )

    product_period_analysis = require_object(
        source["product_period_analysis"], f"{label}.product_period_analysis"
    )
    allowlisted(
        product_period_analysis,
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
        require_object_list(
            product_period_analysis[scope],
            f"{label}.product_period_analysis.{scope}",
        )


def _validate_report_payload(
    source: dict[str, Any],
    *,
    reports_version: str,
    label: str,
    require_risk_v2: bool = False,
) -> None:
    if source.get("schema_version") != REPORT_SCHEMA:
        raise ValueError(f"{label} has unsupported report schema")
    contract_extension = source.get("contract_extension")
    if contract_extension not in {None, RISK_REPORT_V2_EXTENSION}:
        raise ValueError(f"{label} has unsupported contract extension")
    if require_risk_v2 and contract_extension != RISK_REPORT_V2_EXTENSION:
        raise ValueError(f"{label} is missing the required risk report v2 contract")
    required = (
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
    if contract_extension == RISK_REPORT_V2_EXTENSION:
        required += RISK_REPORT_V2_FIELDS
    allowlisted(source, required, label)
    identity = require_object(source["identity"], f"{label}.identity")
    require_dataset_version(identity, reports_version, f"{label}.identity")
    if contract_extension == RISK_REPORT_V2_EXTENSION:
        _validate_risk_report_v2_business_fields(source, label=label)


def _render_projection(
    data_root: Path,
    publication_root: Path,
    *,
    base_version: str,
    insights_version: str,
    reports_version: str,
    personas_version: str,
) -> dict[str, Any]:
    base_dir = data_root / base_version
    insights_dir = data_root / insights_version
    reports_dir = data_root / reports_version
    personas_dir = data_root / personas_version
    public_base_dir = publication_root / base_version

    base_manifest = require_object(load_json(base_dir / "manifest.json"), "base manifest")
    require_dataset_version(base_manifest, base_version, "base manifest")
    verify_source_manifest_files(
        base_dir,
        base_manifest,
        (
            "aggregates.json",
            "posts.json",
            "comments.json",
            "quarantine.json",
            "tag-dictionary.json",
        ),
        label="base manifest",
    )
    posts = require_object_list(load_json(base_dir / "posts.json"), "posts")
    comments = require_object_list(load_json(base_dir / "comments.json"), "comments")
    counts = require_object(base_manifest.get("canonical_counts"), "base manifest.canonical_counts")
    if counts.get("posts") != len(posts):
        raise ValueError("base manifest post count does not match posts.json")
    if counts.get("linked_comments") != len(comments):
        raise ValueError("base manifest linked comment count does not match comments.json")
    governed_fields = _is_governed_base(base_manifest, posts, comments)

    write_json(
        public_base_dir / "aggregates-public.json",
        project_aggregates(
            require_object(load_json(base_dir / "aggregates.json"), "aggregates")
        ),
    )
    write_json(
        public_base_dir / "posts-public.json",
        project_posts(posts, governed_fields=governed_fields),
    )
    write_json(
        public_base_dir / "comments-public.json",
        project_comments(comments, governed_fields=governed_fields),
    )
    write_json(
        public_base_dir / "tag-dictionary-public.json",
        build_public_dictionary(
            require_object(
                load_json(base_dir / "tag-dictionary.json"), "tag dictionary"
            )
        ),
    )
    public_base_manifest = _project_base_manifest(
        base_manifest, governed_fields=governed_fields
    )
    public_base_manifest["files"] = {
        name: file_contract(public_base_dir / name)
        for name in (
            "aggregates-public.json",
            "posts-public.json",
            "comments-public.json",
            "tag-dictionary-public.json",
        )
    }
    write_json(public_base_dir / "manifest-public.json", public_base_manifest)

    public_insights_dir = publication_root / insights_version / "public"
    source_insights_manifest = require_object(
        load_json(insights_dir / "manifest.json"), "insights manifest"
    )
    require_dataset_version(
        source_insights_manifest, insights_version, "insights manifest"
    )
    verify_source_manifest_files(
        insights_dir,
        source_insights_manifest,
        ("insights.json", "semantic-audit.json"),
        label="insights manifest",
    )
    source_insights = require_object(
        load_json(insights_dir / "insights.json"), "insights"
    )
    _validate_insights_payload(source_insights, insights_version=insights_version)
    public_insights = project_analysis_artifact(source_insights, "insights")
    public_audit = project_semantic_audit(
        require_object(
            load_json(insights_dir / "semantic-audit.json"), "semantic audit"
        )
    )
    write_json(public_insights_dir / "insights.json", public_insights)
    write_json(public_insights_dir / "semantic-audit.json", public_audit)
    insights_manifest = project_analysis_artifact(
        deepcopy(source_insights_manifest), "insights manifest"
    )
    insights_manifest["projection"] = {
        "audience": "public_ui",
        "internal_strategy_fields_excluded": True,
        "source_text_and_author_fields_excluded": True,
        "evidence_refs_are_id_only": True,
        "semantic_audit_context_excluded": True,
    }
    insights_manifest["files"] = {
        name: file_contract(public_insights_dir / name)
        for name in ("insights.json", "semantic-audit.json")
    }
    write_json(public_insights_dir / "manifest.json", insights_manifest)

    public_reports_dir = publication_root / reports_version / "public"
    source_report_manifest = require_object(
        load_json(reports_dir / "manifest.json"), "reports manifest"
    )
    require_dataset_version(source_report_manifest, reports_version, "reports manifest")
    report_files = require_object(
        source_report_manifest.get("files"), "reports manifest.files"
    )
    if "report-index.json" not in report_files:
        raise ValueError("reports manifest.files missing report-index.json")
    report_paths = sorted(name for name in report_files if name != "report-index.json")
    verify_source_manifest_files(
        reports_dir,
        source_report_manifest,
        ("report-index.json", *report_paths),
        label="reports manifest",
    )
    source_report_index = require_object(
        load_json(reports_dir / "report-index.json"), "report index"
    )
    report_index_requires_risk_v2 = _validate_report_index(
        source_report_index, reports_version=reports_version
    )
    write_json(
        public_reports_dir / "report-index.json",
        project_analysis_artifact(source_report_index, "report index"),
    )
    for relative_path in report_paths:
        source_report = require_object(
            load_json(reports_dir / relative_path), f"report {relative_path}"
        )
        _validate_report_payload(
            source_report,
            reports_version=reports_version,
            label=f"report {relative_path}",
            require_risk_v2=report_index_requires_risk_v2,
        )
        write_json(
            public_reports_dir / relative_path,
            project_analysis_artifact(source_report, f"report {relative_path}"),
        )
    report_manifest = project_analysis_artifact(
        deepcopy(source_report_manifest), "reports manifest"
    )
    report_manifest["projection"] = {
        "audience": "public_ui",
        "internal_strategy_fields_excluded": True,
        "source_text_and_author_fields_excluded": True,
        "evidence_refs_are_id_only": True,
    }
    report_manifest["files"] = {
        relative_path: file_contract(public_reports_dir / relative_path)
        for relative_path in ["report-index.json", *report_paths]
    }
    write_json(public_reports_dir / "manifest.json", report_manifest)

    public_personas_dir = publication_root / personas_version
    _copy_personas_projection(
        personas_dir,
        public_personas_dir,
        personas_version=personas_version,
    )

    return {
        "public_base_manifest": file_contract(public_base_dir / "manifest-public.json"),
        "public_aggregates": file_contract(public_base_dir / "aggregates-public.json"),
        "base_posts": file_contract(public_base_dir / "posts-public.json"),
        "base_comments": file_contract(public_base_dir / "comments-public.json"),
        "public_dictionary": file_contract(public_base_dir / "tag-dictionary-public.json"),
        "public_insights_manifest": file_contract(public_insights_dir / "manifest.json"),
        "public_reports_manifest": file_contract(public_reports_dir / "manifest.json"),
        "public_personas_manifest": file_contract(public_personas_dir / "manifest.json"),
    }


def build_projection(
    data_root: Path,
    *,
    output_root: Path,
    base_version: str,
    insights_version: str,
    reports_version: str,
    personas_version: str,
) -> dict[str, Any]:
    """Build one immutable public candidate and publish it with one rename."""

    versions = {
        "base_version": base_version,
        "insights_version": insights_version,
        "reports_version": reports_version,
        "personas_version": personas_version,
    }
    for label, value in versions.items():
        _validate_version(value, label)
    if len(set(versions.values())) != len(versions):
        raise ValueError("public dataset versions must be distinct")

    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(
        tempfile.mkdtemp(
            prefix=f".{output_root.name}.staging-", dir=output_root.parent
        )
    )
    try:
        result = _render_projection(
            data_root,
            staging_root / "data" / "reddit-voc",
            base_version=base_version,
            insights_version=insights_version,
            reports_version=reports_version,
            personas_version=personas_version,
        )
        staging_contract = _tree_contract(staging_root)
        if _path_exists(output_root):
            if output_root.is_symlink() or not output_root.is_dir():
                raise FileExistsError(f"output_root_collision: {output_root}")
            if _tree_contract(output_root) != staging_contract:
                raise FileExistsError(f"output_root_collision: {output_root}")
            status = "no_change"
        else:
            # Recheck immediately before the same-filesystem atomic rename.
            if _path_exists(output_root):
                raise FileExistsError(f"output_root_collision: {output_root}")
            os.rename(staging_root, output_root)
            status = "created"
        return {
            "status": status,
            "reused": status == "no_change",
            **result,
        }
    finally:
        if _path_exists(staging_root):
            if staging_root.is_symlink() or not staging_root.is_dir():
                raise RuntimeError(f"unsafe staging root: {staging_root}")
            shutil.rmtree(staging_root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--base-version", required=True)
    parser.add_argument("--insights-version", required=True)
    parser.add_argument("--reports-version", required=True)
    parser.add_argument("--personas-version", required=True)
    args = parser.parse_args()
    result = build_projection(
        args.data_root,
        output_root=args.output_root,
        base_version=args.base_version,
        insights_version=args.insights_version,
        reports_version=args.reports_version,
        personas_version=args.personas_version,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
