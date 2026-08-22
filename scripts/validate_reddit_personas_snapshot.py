#!/usr/bin/env python3
"""Independently validate the Reddit VOC evidence-persona snapshot."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Any, Iterable
import xml.etree.ElementTree as ET


MANIFEST_SCHEMA = "reddit_voc_personas_manifest_v1"
PERSONAS_SCHEMA = "reddit_voc_personas_v1"
PERSONA_TAGS_SCHEMA = "reddit_voc_persona_tags_v1"
CONFIG_SCHEMA = "reddit_voc_persona_config_v1"
DELIVERY_MODE = "versioned_static_evidence_personas"
SVG_MEDIA_TYPE = "image/svg+xml"
DATASET_VERSION_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{2,127}$")
TAG_REPAIR_MANIFEST_SCHEMA = "reddit_voc_tag_repair_manifest_v1"
TAG_REPAIR_POLICY_SCHEMA = "reddit_voc_semantic_predicate_policy_v1"
TAG_REPAIR_DELIVERY_MODE = "versioned_static_tag_repair_audit"
TAG_REPAIR_ALLOWED_STATUSES = {
    "completed_no_new_promotions",
    "completed_with_promotions",
}
TAG_REPAIR_FILE_SCHEMAS = {
    "assignments.json": "reddit_voc_tag_repair_assignments_v1",
    "regression-audit.json": "reddit_voc_tag_repair_regression_audit_v1",
    "review-sample.json": "reddit_voc_tag_repair_review_sample_v1",
    "challenge-cases.json": "reddit_voc_tag_repair_challenge_cases_v1",
    "semantic-audit.json": "reddit_voc_tag_repair_semantic_audit_v1",
}
TAG_REPAIR_BOUNDARIES = {
    "source_scope": "reddit_static_snapshot_only",
    "dictionary_mutated": False,
    "production_unchanged": True,
    "provider_call": False,
    "database_write": False,
    "live_send": False,
    "independent_human_review": False,
}
ALLOWED_SVG_TAGS = {
    "svg",
    "rect",
    "circle",
    "ellipse",
    "path",
    "g",
    "line",
    "polyline",
    "polygon",
}
PERSONA_SOURCE_STRATA = frozenset(
    {
        "tencent_production_primary",
        "tencent_isolated_staging",
        "tencent_v2_search_hydrated",
        "tencent_existing_post_comment_hydration",
        "historical_canonical",
        "imported_archive",
    }
)
FORBIDDEN_PUBLIC_KEYS = {
    "author",
    "author_pseudonym",
    "username",
    "user_id",
    "profile_url",
    "age",
    "avg_age",
    "gender",
    "location",
    "device",
    "device_type",
    "income",
    "occupation",
    "pregnancy_stage",
    "postpartum_stage",
    "demographics",
    "percentage",
    "population_share",
}
PERSONA_KEYS = {
    "persona_id",
    "persona_kind",
    "name_cn",
    "status",
    "definition",
    "source_tag_ids",
    "evidence_logic",
    "metrics",
    "dictionary_reference",
    "avatar",
    "coverage_status",
    "population_share_supported",
}
ASSIGNMENT_KEYS = {
    "persona_id",
    "evidence_id",
    "entity_type",
    "entity_id",
    "post_id",
    "tag_id",
    "evidence_keywords",
    "source_stratum",
    "assignment_status",
    "semantic_gate_scope",
    "human_validated_assignment",
}
AVATAR_KEYS = {
    "asset_path",
    "asset_sha256",
    "media_type",
    "width",
    "height",
    "synthetic",
    "real_user_image",
    "derived_from_reddit_media",
    "identity_claim",
    "alt_text",
}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _check_exact_keys(value: dict[str, Any], expected: set[str], message: str) -> None:
    _check(set(value) == expected, message)


def _verify_manifest_files(root: Path, manifest: dict[str, Any], label: str) -> None:
    for name, expected in manifest["files"].items():
        path = root / name
        _check(path.is_file() and not path.is_symlink(), f"{label} file missing: {name}")
        _check(path.stat().st_size == expected["bytes"], f"{label} byte mismatch: {name}")
        _check(_sha256(path) == expected["sha256"], f"{label} sha256 mismatch: {name}")


def _validate_private_tree(root: Path) -> None:
    _check(root.stat().st_mode & 0o777 == 0o700, "persona root mode mismatch")
    for path in root.rglob("*"):
        _check(not path.is_symlink(), "persona tree contains a symlink")
        if path.is_dir():
            _check(
                path.stat().st_mode & 0o777 == 0o700,
                "persona directory mode mismatch",
            )
        elif path.is_file():
            _check(
                path.stat().st_mode & 0o777 == 0o600,
                "persona file mode mismatch",
            )
        else:
            raise ValueError("persona tree contains an unsafe entry")


def _safe_asset_path(value: Any) -> PurePosixPath:
    if (
        not isinstance(value, str)
        or not value
        or "://" in value
        or value.startswith(("/", "data:", "blob:"))
    ):
        raise ValueError(f"avatar path is not local: {value}")
    path = PurePosixPath(value)
    if path.parts[0] != "assets" or ".." in path.parts or path.suffix != ".svg":
        raise ValueError(f"avatar path is not local: {value}")
    return path


def _svg_dimensions(path: Path) -> tuple[int, int]:
    raw = path.read_text(encoding="utf-8")
    lowered = raw.casefold()
    forbidden = (
        "<!doctype",
        "<!entity",
        "<?xml-stylesheet",
        "<script",
        "<foreignobject",
        "<image",
        "<text",
        "javascript:",
        "data:",
        "https://",
        "xlink:href",
        " href=",
        " onload=",
        " onclick=",
        "url(",
        "reddit",
        "momcozy",
        "baby",
        "logo",
    )
    _check(not any(marker in lowered for marker in forbidden), f"unsafe SVG marker: {path.name}")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError(f"invalid SVG: {path.name}") from exc
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        _check(tag in ALLOWED_SVG_TAGS, f"unsafe SVG element: {tag}")
        _check(not (node.text or "").strip(), f"unsafe SVG text content: {path.name}")
        for attribute, raw_value in node.attrib.items():
            normalized = attribute.rsplit("}", 1)[-1].casefold()
            value = str(raw_value).casefold()
            _check(
                normalized != "href" and not normalized.startswith("on"),
                f"unsafe SVG attribute: {normalized}",
            )
            _check(
                "://" not in value
                and "javascript:" not in value
                and "data:" not in value
                and "url(" not in value,
                f"unsafe SVG attribute value: {normalized}",
            )
    _check(root.tag.rsplit("}", 1)[-1] == "svg", f"invalid SVG root: {path.name}")
    try:
        width = int(root.attrib["width"])
        height = int(root.attrib["height"])
    except (KeyError, ValueError) as exc:
        raise ValueError(f"invalid SVG dimensions: {path.name}") from exc
    _check(root.attrib.get("viewBox") == f"0 0 {width} {height}", f"invalid SVG viewBox: {path.name}")
    return width, height


def _find_forbidden_key(value: Any, path: str = "$") -> tuple[str, str] | None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in FORBIDDEN_PUBLIC_KEYS:
                return path, key
            found = _find_forbidden_key(nested, f"{path}.{key}")
            if found:
                return found
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found = _find_forbidden_key(nested, f"{path}[{index}]")
            if found:
                return found
    return None


def _source_stratum(source_kinds: Iterable[str], source_priority: list[str]) -> str:
    values = set(source_kinds)
    for source in source_priority:
        if source in values:
            return source
    raise ValueError("persona evidence source stratum is not governed")


def _source_priority(config: dict[str, Any]) -> list[str]:
    value = config.get("source_priority")
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(row, str) or not row for row in value)
        or len(value) != len(set(value))
        or not set(value) <= PERSONA_SOURCE_STRATA
    ):
        raise ValueError("persona source priority is not governed")
    return [str(row) for row in value]


def _entity_rows(
    posts: list[dict[str, Any]], comments: list[dict[str, Any]]
) -> list[tuple[str, dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any]]] = [("post", row) for row in posts]
    rows.extend(
        ("comment", row) for row in comments if row["include_in_voc_metrics"]
    )
    return rows


def _expected_assignment(
    persona_id: str,
    source_tag_id: str,
    entity_type: str,
    entity: dict[str, Any],
    source_priority: list[str],
) -> dict[str, Any]:
    matches = [
        row
        for row in entity["tagging"]["matches"]
        if row["tag_id"] == source_tag_id
    ]
    _check(
        len(matches) == 1,
        f"source evidence has unexpected tag matches: {persona_id}/{entity['evidence_id']}",
    )
    source_kinds = (
        entity["source_kinds"]
        if entity_type == "post"
        else [row["source_kind"] for row in entity["source_occurrences"]]
    )
    entity_id = (
        str(entity["post_id"])
        if entity_type == "post"
        else str(entity["comment_id"])
    )
    return {
        "persona_id": persona_id,
        "evidence_id": entity["evidence_id"],
        "entity_type": entity_type,
        "entity_id": entity_id,
        "post_id": entity["post_id"],
        "tag_id": source_tag_id,
        "evidence_keywords": sorted(set(matches[0]["evidence_keywords"])),
        "source_stratum": _source_stratum(source_kinds, source_priority),
        "assignment_status": "rule_match_under_promoted_tag",
        "semantic_gate_scope": "tag_level_stratified_sample",
        "human_validated_assignment": False,
    }


def _dataset_version(config: dict[str, Any]) -> str:
    value = config.get("dataset_version")
    if not isinstance(value, str) or DATASET_VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("persona config dataset version mismatch")
    return value


def _is_v2_insights(insights: dict[str, Any]) -> bool:
    # Schema is the fail-closed switch; manifest extensions are advisory.
    return insights.get("schema_version") == "reddit_voc_insights_v2"


def _dictionary_reference(
    dictionary: dict[str, Any], tag_id: str
) -> dict[str, Any]:
    rules = dictionary.get("rules")
    if not isinstance(rules, list):
        raise ValueError("tag dictionary rules missing")
    references = {
        (
            row.get("consumer_card"),
            row.get("aipl_node"),
            row.get("story_lines"),
            row.get("intent_type"),
            row.get("problem_type"),
        )
        for row in rules
        if isinstance(row, dict) and row.get("tag_id") == tag_id
    }
    _check(
        len(references) == 1,
        f"persona dictionary reference is ambiguous: {tag_id}",
    )
    values = next(iter(references))
    _check(
        all(isinstance(value, str) and value.strip() for value in values),
        f"persona dictionary reference is incomplete: {tag_id}",
    )
    consumer_card, aipl_node, story_lines, intent_type, problem_type = values
    return {
        "consumer_card": consumer_card,
        "aipl_node": aipl_node,
        "story_lines": [story_lines],
        "intent_type": [intent_type],
        "problem_type": [problem_type],
    }


def _manifest_boundaries() -> dict[str, bool]:
    return {
        "production_unchanged": True,
        "provider_call": False,
        "database_write": False,
        "live_send": False,
        "webhook_send": False,
        "deploy": False,
        "schedule_change": False,
        "independent_human_review": False,
        "counts_are_content_entities_not_users": True,
        "author_level_personas": False,
        "public_author_identifiers": False,
        "consumer_card_is_reference_not_persona_id": True,
        "persona_tags_generated": True,
        "population_share_supported": False,
        "synthetic_avatars": True,
        "real_user_image": False,
        "derived_from_reddit_media": False,
        "identity_claim": False,
    }


def _interpretation_boundaries() -> dict[str, bool]:
    return {
        "counts_are_content_entities_not_users": True,
        "distinct_pseudonyms_are_not_people": True,
        "author_level_personas": False,
        "consumer_card_is_reference_not_persona_id": True,
        "population_share_supported": False,
        "demographics_supported": False,
        "activity_pattern_supported": False,
        "brand_preference_supported": False,
        "synthetic_avatars": True,
        "real_user_image": False,
        "derived_from_reddit_media": False,
        "identity_claim": False,
    }


def _assignment_boundaries() -> dict[str, bool]:
    return {
        "assignments_are_content_entities_not_users": True,
        "human_validated_assignment": False,
        "tag_gate_is_stratified_sample_not_full_population_review": True,
        "public_author_identifiers": False,
        "author_level_personas": False,
    }


def _tag_repair_binding(
    tag_repair_dir: Path | None,
    policy_path: Path | None,
    *,
    base_manifest: dict[str, Any],
    base_manifest_sha256: str,
    dictionary: dict[str, Any],
) -> dict[str, Any]:
    if tag_repair_dir is None:
        _check(policy_path is None, "tag repair policy provided without tag repair snapshot")
        return {
            "applied": False,
            "schema_version": None,
            "dataset_version": None,
            "manifest_sha256": None,
            "status": "not_provided",
        }
    if policy_path is None:
        raise ValueError("tag repair policy path is required")
    manifest_path = tag_repair_dir / "manifest.json"
    _check(manifest_path.is_file() and not manifest_path.is_symlink(), "tag repair manifest missing")
    manifest = _load(manifest_path)
    _check(manifest.get("schema_version") == TAG_REPAIR_MANIFEST_SCHEMA, "tag repair manifest schema mismatch")
    _check(manifest.get("delivery_mode") == TAG_REPAIR_DELIVERY_MODE, "tag repair delivery mode mismatch")
    _check(manifest.get("status") in TAG_REPAIR_ALLOWED_STATUSES, "tag repair status is not consumable")
    _check(manifest.get("base_dataset_version") == base_manifest["dataset_version"], "tag repair base dataset mismatch")
    _check(manifest.get("base_manifest_sha256") == base_manifest_sha256, "tag repair base manifest hash mismatch")
    _check(
        manifest.get("dictionary_version") == dictionary["dictionary_version"]
        and manifest.get("dictionary_sha256") == dictionary["dictionary_sha256"],
        "tag repair dictionary binding mismatch",
    )
    _check(manifest.get("boundaries") == TAG_REPAIR_BOUNDARIES, "tag repair boundary mismatch")

    resolved_policy_path = policy_path.resolve(strict=True)
    _check(not resolved_policy_path.is_symlink(), "tag repair policy path is unsafe")
    policy = _load(resolved_policy_path)
    _check(policy.get("schema_version") == TAG_REPAIR_POLICY_SCHEMA, "tag repair policy schema mismatch")
    _check(_sha256(resolved_policy_path) == manifest.get("predicate_policy_sha256"), "tag repair policy hash mismatch")
    _check(
        policy.get("policy_version") == manifest.get("predicate_policy_version")
        and policy.get("base_dataset_version") == manifest["base_dataset_version"]
        and policy.get("base_manifest_sha256") == manifest["base_manifest_sha256"]
        and policy.get("dictionary_version") == manifest["dictionary_version"]
        and policy.get("dictionary_sha256") == manifest["dictionary_sha256"]
        and policy.get("boundaries") == TAG_REPAIR_BOUNDARIES,
        "tag repair policy binding mismatch",
    )

    files = manifest.get("files")
    _check(
        isinstance(files, dict) and set(files) == set(TAG_REPAIR_FILE_SCHEMAS),
        "tag repair manifest file set mismatch",
    )
    loaded_files: dict[str, dict[str, Any]] = {}
    for name, expected_schema in TAG_REPAIR_FILE_SCHEMAS.items():
        metadata = files[name]
        _check(set(metadata) == {"bytes", "sha256"}, f"tag repair file metadata mismatch: {name}")
        path = tag_repair_dir / name
        _check(path.is_file() and not path.is_symlink(), f"tag repair file missing or unsafe: {name}")
        _check(
            path.stat().st_size == metadata["bytes"]
            and _sha256(path) == metadata["sha256"],
            f"tag repair file hash mismatch: {name}",
        )
        document = _load(path)
        _check(document.get("schema_version") == expected_schema, f"tag repair file schema mismatch: {name}")
        _check(document.get("dataset_version") == manifest.get("dataset_version"), f"tag repair file dataset mismatch: {name}")
        _check(document.get("base_manifest_sha256") == base_manifest_sha256, f"tag repair file base binding mismatch: {name}")
        _check(
            document.get("predicate_policy_version")
            == manifest.get("predicate_policy_version")
            and document.get("predicate_policy_sha256")
            == manifest.get("predicate_policy_sha256"),
            f"tag repair file policy binding mismatch: {name}",
        )
        _check(document.get("boundaries") == TAG_REPAIR_BOUNDARIES, f"tag repair file boundary mismatch: {name}")
        loaded_files[name] = document

    semantic_audit = loaded_files["semantic-audit.json"]
    _check(semantic_audit.get("review_status") == "complete", "tag repair semantic review is incomplete")
    _check(semantic_audit.get("summary") == manifest.get("audit_summary"), "tag repair audit summary mismatch")
    _check(semantic_audit["summary"].get("status") == manifest.get("status"), "tag repair status mismatch")
    return {
        "applied": True,
        "schema_version": manifest["schema_version"],
        "dataset_version": manifest["dataset_version"],
        "manifest_sha256": _sha256(manifest_path),
        "status": manifest["status"],
    }


def _expected_documents(
    config: dict[str, Any],
    insights: dict[str, Any],
    dictionary: dict[str, Any],
    posts: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    avatar_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    promoted_signals = {row["tag_id"]: row for row in insights["signals"]}
    source_priority = _source_priority(config)
    minimum_distinct = int(config["minimum_distinct_pseudonyms"])
    entities = _entity_rows(posts, comments)
    personas: list[dict[str, Any]] = []
    assignments: list[dict[str, Any]] = []

    for definition in sorted(config["personas"], key=lambda row: row["persona_id"]):
        source_tag_ids = list(definition["source_tag_ids"])
        _check(len(source_tag_ids) == 1, "persona v1 requires exactly one source tag")
        source_tag_id = source_tag_ids[0]
        _check(
            source_tag_id in promoted_signals,
            f"persona source tag is not promoted: {source_tag_id}",
        )
        selected = [
            (entity_type, entity)
            for entity_type, entity in entities
            if source_tag_id in entity["tagging"]["aspect_tag_ids"]
        ]
        assignments.extend(
            _expected_assignment(
                definition["persona_id"],
                source_tag_id,
                entity_type,
                entity,
                source_priority,
            )
            for entity_type, entity in selected
        )
        metrics = {
            "matched_entities": len(selected),
            "matched_posts": sum(entity_type == "post" for entity_type, _ in selected),
            "matched_comments": sum(
                entity_type == "comment" for entity_type, _ in selected
            ),
            "distinct_pseudonyms": len(
                {
                    entity.get("author_pseudonym")
                    for _, entity in selected
                    if entity.get("author_pseudonym")
                }
            ),
            "threads": len({entity["post_id"] for _, entity in selected}),
        }
        signal = promoted_signals[source_tag_id]
        if not _is_v2_insights(insights):
            _check(
                metrics["matched_posts"] == signal["matched_posts"],
                "insights post count mismatch",
            )
            _check(
                metrics["matched_comments"] == signal["matched_comments"],
                "insights comment count mismatch",
            )
        avatar_config = dict(definition["avatar"])
        asset_path = _safe_asset_path(avatar_config.pop("asset_path")).as_posix()
        source_filename = avatar_config.pop("source_filename")
        _check(
            PurePosixPath(asset_path).name == source_filename,
            f"avatar source mapping mismatch: {asset_path}",
        )
        source_path = avatar_dir / source_filename
        _check(
            source_path.is_file() and not source_path.is_symlink(),
            f"avatar source missing or unsafe: {source_filename}",
        )
        width, height = _svg_dimensions(source_path)
        _check((width, height) == (512, 512), f"avatar dimensions mismatch: {source_filename}")
        _check(
            (avatar_config["width"], avatar_config["height"]) == (width, height),
            f"avatar config dimensions mismatch: {source_filename}",
        )
        _check(avatar_config["media_type"] == SVG_MEDIA_TYPE, "avatar media type mismatch")
        _check(
            avatar_config["synthetic"] is True
            and avatar_config["real_user_image"] is False
            and avatar_config["derived_from_reddit_media"] is False
            and avatar_config["identity_claim"] is False,
            "avatar identity boundary mismatch",
        )
        reference = _dictionary_reference(dictionary, source_tag_id)
        personas.append(
            {
                "persona_id": definition["persona_id"],
                "persona_kind": definition["persona_kind"],
                "name_cn": definition["name_cn"],
                "status": (
                    "promoted"
                    if metrics["distinct_pseudonyms"] >= minimum_distinct
                    else "insufficient_sample"
                ),
                "definition": definition["definition"],
                "source_tag_ids": source_tag_ids,
                "evidence_logic": definition["evidence_logic"],
                "metrics": metrics,
                "dictionary_reference": reference,
                "avatar": {
                    "asset_path": asset_path,
                    "asset_sha256": _sha256(source_path),
                    **avatar_config,
                },
                "coverage_status": "observed_corpus_only",
                "population_share_supported": False,
            }
        )
    assignments.sort(
        key=lambda row: (
            row["persona_id"],
            0 if row["entity_type"] == "post" else 1,
            row["entity_id"],
        )
    )
    return personas, assignments


def validate(
    personas_dir: Path,
    snapshot_dir: Path,
    insights_dir: Path,
    config_path: Path,
    avatar_dir: Path,
    tag_repair_dir: Path | None = None,
    tag_repair_policy_path: Path | None = None,
) -> dict[str, Any]:
    _check(not personas_dir.is_symlink(), "persona root is a symlink")
    personas_dir = personas_dir.resolve(strict=True)
    snapshot_dir = snapshot_dir.resolve(strict=True)
    insights_dir = insights_dir.resolve(strict=True)
    config_path = config_path.resolve(strict=True)
    avatar_dir = avatar_dir.resolve(strict=True)
    tag_repair_dir = tag_repair_dir.resolve(strict=True) if tag_repair_dir else None
    tag_repair_policy_path = (
        tag_repair_policy_path.resolve(strict=True)
        if tag_repair_policy_path
        else None
    )

    manifest_path = personas_dir / "manifest.json"
    base_manifest_path = snapshot_dir / "manifest.json"
    insights_manifest_path = insights_dir / "manifest.json"
    manifest = _load(manifest_path)
    personas_document = _load(personas_dir / "personas.json")
    persona_tags_document = _load(personas_dir / "persona-tags.json")
    base_manifest = _load(base_manifest_path)
    insights_manifest = _load(insights_manifest_path)
    insights = _load(insights_dir / "insights.json")
    audit = _load(insights_dir / "semantic-audit.json")
    config = _load(config_path)
    posts = _load(snapshot_dir / "posts.json")
    comments = _load(snapshot_dir / "comments.json")
    dictionary = _load(snapshot_dir / "tag-dictionary.json")
    _validate_private_tree(personas_dir)

    _check_exact_keys(
        manifest,
        {
            "schema_version",
            "dataset_version",
            "delivery_mode",
            "generated_at_utc",
            "base_dataset_version",
            "base_manifest_sha256",
            "insights_dataset_version",
            "insights_manifest_sha256",
            "dictionary_version",
            "dictionary_sha256",
            "config_version",
            "config_sha256",
            "tag_repair",
            "persona_count",
            "assignment_count",
            "source_tag_ids",
            "files",
            "boundaries",
        },
        "persona manifest keys mismatch",
    )
    _check(manifest["schema_version"] == MANIFEST_SCHEMA, "manifest schema mismatch")
    _check(personas_document["schema_version"] == PERSONAS_SCHEMA, "personas schema mismatch")
    _check(persona_tags_document["schema_version"] == PERSONA_TAGS_SCHEMA, "persona tags schema mismatch")
    _check(config["schema_version"] == CONFIG_SCHEMA, "persona config schema mismatch")
    dataset_version = _dataset_version(config)
    _check(
        manifest["dataset_version"]
        == personas_document["dataset_version"]
        == persona_tags_document["dataset_version"]
        == config["dataset_version"]
        == dataset_version,
        "persona dataset version mismatch",
    )
    _check(manifest["delivery_mode"] == DELIVERY_MODE, "persona delivery mode mismatch")
    _check(persona_tags_document["grain"] == "persona_id_x_evidence_id", "persona grain mismatch")

    _verify_manifest_files(snapshot_dir, base_manifest, "base manifest")
    _verify_manifest_files(insights_dir, insights_manifest, "insights manifest")
    _check(base_manifest.get("all_checks_passed") is True, "base snapshot validation is not green")
    _check(base_manifest.get("provider_call") is False, "base snapshot provider boundary mismatch")
    _check(
        manifest["base_dataset_version"] == base_manifest["dataset_version"],
        "base dataset binding mismatch",
    )
    _check(
        manifest["base_manifest_sha256"] == _sha256(base_manifest_path),
        "base manifest hash binding mismatch",
    )
    _check(
        manifest["insights_dataset_version"] == insights_manifest["dataset_version"],
        "insights dataset binding mismatch",
    )
    _check(
        manifest["insights_manifest_sha256"] == _sha256(insights_manifest_path),
        "insights manifest hash binding mismatch",
    )
    _check(
        insights_manifest["base_dataset_version"] == base_manifest["dataset_version"]
        and insights_manifest["base_manifest_sha256"] == _sha256(base_manifest_path),
        "insights/base binding mismatch",
    )
    _check(
        manifest["dictionary_version"] == dictionary["dictionary_version"]
        and manifest["dictionary_sha256"] == dictionary["dictionary_sha256"]
        and insights_manifest["dictionary_version"] == dictionary["dictionary_version"]
        and insights_manifest["dictionary_sha256"] == dictionary["dictionary_sha256"],
        "dictionary binding mismatch",
    )
    _check(
        manifest["config_version"] == config["config_version"]
        and manifest["config_sha256"] == _sha256(config_path),
        "persona config binding mismatch",
    )
    _check(
        manifest["generated_at_utc"]
        == personas_document["generated_at_utc"]
        == insights["generated_at_utc"],
        "generated timestamp binding mismatch",
    )
    _check(
        manifest["tag_repair"]
        == _tag_repair_binding(
            tag_repair_dir,
            tag_repair_policy_path,
            base_manifest=base_manifest,
            base_manifest_sha256=_sha256(base_manifest_path),
            dictionary=dictionary,
        ),
        "optional tag repair binding mismatch",
    )

    configured_assets = {
        _safe_asset_path(row["avatar"]["asset_path"]).as_posix()
        for row in config["personas"]
    }
    expected_files = {"personas.json", "persona-tags.json", *configured_assets}
    _check(set(manifest["files"]) == expected_files, "persona file set mismatch")
    for name in sorted(expected_files):
        path = personas_dir / name
        expected = manifest["files"][name]
        _check(path.is_file() and not path.is_symlink(), f"persona file missing or unsafe: {name}")
        _check(path.stat().st_size == expected["bytes"], f"file byte mismatch: {name}")
        _check(_sha256(path) == expected["sha256"], f"file sha256 mismatch: {name}")
        if name.endswith(".json"):
            _check(expected == {
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
                "media_type": "application/json",
            }, f"JSON file metadata mismatch: {name}")

    for document in (personas_document, persona_tags_document):
        forbidden = _find_forbidden_key(document)
        _check(forbidden is None, f"forbidden public key: {forbidden}")

    promoted_ids = set(audit["summary"]["promoted_tag_ids"])
    if _is_v2_insights(insights):
        audit_summary = insights_manifest.get("audit_summary")
        _check(
            isinstance(audit_summary, dict)
            and set(audit_summary.get("promoted_tag_ids", [])) == promoted_ids,
            "insights v2 governance projection mismatch",
        )
    signal_ids = {row["tag_id"] for row in insights["signals"]}
    if not _is_v2_insights(insights):
        _check(promoted_ids == signal_ids, "insights promoted tag set mismatch")
    configured_persona_ids = {row["persona_id"] for row in config["personas"]}
    _check(len(configured_persona_ids) == len(config["personas"]) == 2, "persona config count mismatch")
    configured_tags = {
        tag_id for row in config["personas"] for tag_id in row["source_tag_ids"]
    }
    for tag_id in configured_tags:
        _check(tag_id in promoted_ids, f"persona source tag is not promoted: {tag_id}")
        _check(tag_id in signal_ids, f"persona source tag is missing from insights: {tag_id}")
    _check(manifest["source_tag_ids"] == sorted(configured_tags), "manifest source tag mismatch")

    _check_exact_keys(
        personas_document,
        {
            "schema_version",
            "dataset_version",
            "generated_at_utc",
            "persona_count",
            "personas",
            "interpretation_boundaries",
        },
        "personas document keys mismatch",
    )
    _check_exact_keys(
        persona_tags_document,
        {
            "schema_version",
            "dataset_version",
            "grain",
            "assignment_count",
            "assignments",
            "boundaries",
        },
        "persona tags document keys mismatch",
    )
    for row in personas_document["personas"]:
        _check_exact_keys(row, PERSONA_KEYS, "persona row keys mismatch")
        _check_exact_keys(row["avatar"], AVATAR_KEYS, "persona avatar keys mismatch")
        _safe_asset_path(row["avatar"]["asset_path"])
        _check(
            row["avatar"]["synthetic"] is True
            and row["avatar"]["real_user_image"] is False
            and row["avatar"]["derived_from_reddit_media"] is False
            and row["avatar"]["identity_claim"] is False,
            "avatar identity boundary mismatch",
        )
    for row in persona_tags_document["assignments"]:
        _check_exact_keys(row, ASSIGNMENT_KEYS, "persona assignment keys mismatch")
        _check(row["tag_id"] in promoted_ids, "assignment source tag is not promoted")
        _check(row["persona_id"] in configured_persona_ids, "assignment persona id mismatch")
        _check(
            row["source_stratum"] in PERSONA_SOURCE_STRATA,
            "persona assignment source stratum is not governed",
        )

    expected_personas, expected_assignments = _expected_documents(
        config,
        insights,
        dictionary,
        posts,
        comments,
        avatar_dir,
    )
    actual_by_id = {row["persona_id"]: row for row in personas_document["personas"]}
    expected_by_id = {row["persona_id"]: row for row in expected_personas}
    _check(
        len(actual_by_id) == len(personas_document["personas"]),
        "duplicate persona id",
    )
    _check(set(actual_by_id) == set(expected_by_id), "persona id set mismatch")
    for persona_id, expected in expected_by_id.items():
        actual = actual_by_id[persona_id]
        _check(actual["metrics"] == expected["metrics"], f"persona metrics mismatch: {persona_id}")
        _check(
            actual["metrics"]["distinct_pseudonyms"]
            >= int(config["minimum_distinct_pseudonyms"]),
            f"persona privacy threshold not met: {persona_id}",
        )
        _check(actual["avatar"] == expected["avatar"], f"persona avatar mismatch: {persona_id}")
        _check(actual == expected, f"persona definition mismatch: {persona_id}")
        asset_path = actual["avatar"]["asset_path"]
        output_avatar = personas_dir / asset_path
        source_avatar = avatar_dir / PurePosixPath(asset_path).name
        _check(output_avatar.read_bytes() == source_avatar.read_bytes(), f"avatar source byte mismatch: {asset_path}")
        width, height = _svg_dimensions(output_avatar)
        _check((width, height) == (512, 512), f"avatar dimensions mismatch: {asset_path}")
        _check(
            manifest["files"][asset_path]
            == {
                "bytes": output_avatar.stat().st_size,
                "sha256": _sha256(output_avatar),
                "media_type": SVG_MEDIA_TYPE,
                "width": 512,
                "height": 512,
            },
            f"avatar manifest metadata mismatch: {asset_path}",
        )

    _check(persona_tags_document["assignments"] == expected_assignments, "persona assignments mismatch")
    _check(
        len({(row["persona_id"], row["evidence_id"]) for row in expected_assignments})
        == len(expected_assignments),
        "duplicate persona assignment",
    )
    _check(
        manifest["persona_count"]
        == personas_document["persona_count"]
        == len(expected_personas),
        "persona count mismatch",
    )
    _check(
        manifest["assignment_count"]
        == persona_tags_document["assignment_count"]
        == len(expected_assignments),
        "assignment count mismatch",
    )
    _check(manifest["boundaries"] == _manifest_boundaries(), "manifest boundary mismatch")
    _check(
        personas_document["interpretation_boundaries"] == _interpretation_boundaries(),
        "persona interpretation boundary mismatch",
    )
    _check(
        persona_tags_document["boundaries"] == _assignment_boundaries(),
        "persona assignment boundary mismatch",
    )

    checks = {
        "schema_and_version_binding": True,
        "base_insights_dictionary_config_binding": True,
        "optional_tag_repair_binding": True,
        "file_hashes_and_svg_assets": True,
        "private_tree_modes": True,
        "promoted_tag_and_assignment_integrity": True,
        "persona_metric_reconciliation": True,
        "privacy_and_inference_boundaries": True,
        "side_effect_boundaries": True,
    }
    return {
        "schema_version": "reddit_voc_personas_validation_v1",
        "validated_at_utc": manifest["generated_at_utc"],
        "dataset_version": manifest["dataset_version"],
        "status": "passed",
        "manifest_sha256": _sha256(manifest_path),
        "base_manifest_sha256": _sha256(base_manifest_path),
        "insights_manifest_sha256": _sha256(insights_manifest_path),
        "config_sha256": _sha256(config_path),
        "tag_repair_manifest_sha256": manifest["tag_repair"]["manifest_sha256"],
        "checks": checks,
        "counts": {
            "personas": len(expected_personas),
            "assignments": len(expected_assignments),
            "promoted_source_tags": len(configured_tags),
        },
        "production_unchanged": True,
        "provider_call": False,
        "database_write": False,
        "live_send": False,
        "webhook_send": False,
        "deploy": False,
        "independent_human_review": False,
    }


def _write_receipt(path: Path, result: dict[str, Any]) -> str:
    payload = (
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise ValueError("persona validation receipt collision")
        status = "no_change"
    else:
        handle, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent
        )
        temporary = Path(temporary_name)
        try:
            os.write(handle, payload)
            os.close(handle)
            handle = -1
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            if handle >= 0:
                os.close(handle)
            if temporary.exists():
                temporary.unlink()
        status = "created"
    os.chmod(path, 0o600)
    return status


def validate_v3(*args: Any, **kwargs: Any) -> dict[str, object]:
    """Independently replay V3 while preserving the frozen V1 validator."""
    from reddit_voc.v3_persona_snapshot import validate_v3_persona_snapshot

    return validate_v3_persona_snapshot(*args, **kwargs)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--personas-dir", type=Path, required=True)
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--insights-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--avatar-dir", type=Path, required=True)
    parser.add_argument("--tag-repair-dir", type=Path)
    parser.add_argument("--tag-repair-policy", type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    result = validate(
        args.personas_dir,
        args.snapshot_dir,
        args.insights_dir,
        args.config,
        args.avatar_dir,
        args.tag_repair_dir,
        args.tag_repair_policy,
    )
    if args.receipt:
        result["receipt_write_status"] = _write_receipt(args.receipt, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
