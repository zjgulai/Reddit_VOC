#!/usr/bin/env python3
"""Build deterministic, privacy-bounded Reddit VOC evidence personas."""

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
from typing import Any, Iterable
import xml.etree.ElementTree as ET


MANIFEST_SCHEMA = "reddit_voc_personas_manifest_v1"
PERSONAS_SCHEMA = "reddit_voc_personas_v1"
PERSONA_TAGS_SCHEMA = "reddit_voc_persona_tags_v1"
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


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    os.chmod(path, 0o600)


def _tree_contract(root: Path) -> dict[str, Any]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("persona output root is unsafe")
    files: dict[str, dict[str, Any]] = {}
    directories: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValueError("persona output contains a symlink")
        if path.is_dir():
            directories.append(
                {"path": relative, "mode": path.stat().st_mode & 0o777}
            )
        elif path.is_file():
            files[relative] = {
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
                "mode": path.stat().st_mode & 0o777,
            }
        else:
            raise ValueError("persona output contains an unsafe entry")
    return {
        "root_mode": root.stat().st_mode & 0o777,
        "directories": directories,
        "files": files,
    }


def _harden_private_tree(root: Path) -> None:
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("persona output contains a symlink")
        if path.is_dir():
            os.chmod(path, 0o700)
        elif path.is_file():
            os.chmod(path, 0o600)
        else:
            raise ValueError("persona output contains an unsafe entry")
    os.chmod(root, 0o700)


def _verify_manifest_files(root: Path, manifest: dict[str, Any]) -> None:
    for name, expected in manifest["files"].items():
        path = root / name
        if not path.is_file():
            raise ValueError(f"manifest file missing: {name}")
        if path.stat().st_size != expected["bytes"]:
            raise ValueError(f"manifest byte mismatch: {name}")
        if _sha256(path) != expected["sha256"]:
            raise ValueError(f"manifest sha256 mismatch: {name}")


def _safe_asset_path(value: str) -> PurePosixPath:
    if not value or "://" in value or value.startswith(("/", "data:", "blob:")):
        raise ValueError(f"avatar path is not local: {value}")
    path = PurePosixPath(value)
    if path.parts[0] != "assets" or ".." in path.parts or path.suffix != ".svg":
        raise ValueError(f"avatar path is not local: {value}")
    return path


def _svg_dimensions(path: Path) -> tuple[int, int]:
    raw = path.read_text(encoding="utf-8")
    lowered = raw.casefold()
    forbidden = (
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
        "reddit",
        "momcozy",
    )
    if any(marker in lowered for marker in forbidden):
        raise ValueError(f"unsafe SVG marker: {path.name}")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError(f"invalid SVG: {path.name}") from exc
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag not in ALLOWED_SVG_TAGS:
            raise ValueError(f"unsafe SVG element: {tag}")
        for attribute in node.attrib:
            normalized = attribute.rsplit("}", 1)[-1].casefold()
            if normalized == "href" or normalized.startswith("on"):
                raise ValueError(f"unsafe SVG attribute: {normalized}")
    if root.tag.rsplit("}", 1)[-1] != "svg":
        raise ValueError(f"invalid SVG root: {path.name}")
    try:
        width = int(root.attrib["width"])
        height = int(root.attrib["height"])
    except (KeyError, ValueError) as exc:
        raise ValueError(f"invalid SVG dimensions: {path.name}") from exc
    if root.attrib.get("viewBox") != f"0 0 {width} {height}":
        raise ValueError(f"invalid SVG viewBox: {path.name}")
    return width, height


def _source_stratum(
    source_kinds: Iterable[str], source_priority: list[str]
) -> str:
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
    return list(value)


def _tag_repair_binding(
    tag_repair_dir: Path | None,
    policy_path: Path | None,
    *,
    base_manifest: dict[str, Any],
    base_manifest_sha256: str,
    dictionary: dict[str, Any],
) -> dict[str, Any]:
    if tag_repair_dir is None:
        if policy_path is not None:
            raise ValueError("tag repair policy provided without tag repair snapshot")
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
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError("tag repair manifest missing")
    manifest = _load(manifest_path)
    if manifest.get("schema_version") != TAG_REPAIR_MANIFEST_SCHEMA:
        raise ValueError("tag repair manifest schema mismatch")
    if manifest.get("delivery_mode") != TAG_REPAIR_DELIVERY_MODE:
        raise ValueError("tag repair delivery mode mismatch")
    if manifest.get("status") not in TAG_REPAIR_ALLOWED_STATUSES:
        raise ValueError("tag repair status is not consumable")
    if manifest.get("base_dataset_version") != base_manifest["dataset_version"]:
        raise ValueError("tag repair base dataset mismatch")
    if manifest.get("base_manifest_sha256") != base_manifest_sha256:
        raise ValueError("tag repair base manifest hash mismatch")
    if (
        manifest.get("dictionary_version") != dictionary["dictionary_version"]
        or manifest.get("dictionary_sha256") != dictionary["dictionary_sha256"]
    ):
        raise ValueError("tag repair dictionary binding mismatch")
    if manifest.get("boundaries") != TAG_REPAIR_BOUNDARIES:
        raise ValueError("tag repair boundary mismatch")

    policy_path = policy_path.resolve(strict=True)
    if policy_path.is_symlink():
        raise ValueError("tag repair policy path is unsafe")
    policy = _load(policy_path)
    if policy.get("schema_version") != TAG_REPAIR_POLICY_SCHEMA:
        raise ValueError("tag repair policy schema mismatch")
    if _sha256(policy_path) != manifest.get("predicate_policy_sha256"):
        raise ValueError("tag repair policy hash mismatch")
    if (
        policy.get("policy_version") != manifest.get("predicate_policy_version")
        or policy.get("base_dataset_version") != manifest["base_dataset_version"]
        or policy.get("base_manifest_sha256") != manifest["base_manifest_sha256"]
        or policy.get("dictionary_version") != manifest["dictionary_version"]
        or policy.get("dictionary_sha256") != manifest["dictionary_sha256"]
        or policy.get("boundaries") != TAG_REPAIR_BOUNDARIES
    ):
        raise ValueError("tag repair policy binding mismatch")

    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != set(TAG_REPAIR_FILE_SCHEMAS):
        raise ValueError("tag repair manifest file set mismatch")
    loaded_files: dict[str, dict[str, Any]] = {}
    for name, expected_schema in TAG_REPAIR_FILE_SCHEMAS.items():
        metadata = files[name]
        if set(metadata) != {"bytes", "sha256"}:
            raise ValueError(f"tag repair file metadata mismatch: {name}")
        path = tag_repair_dir / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"tag repair file missing or unsafe: {name}")
        if path.stat().st_size != metadata["bytes"] or _sha256(path) != metadata["sha256"]:
            raise ValueError(f"tag repair file hash mismatch: {name}")
        document = _load(path)
        if document.get("schema_version") != expected_schema:
            raise ValueError(f"tag repair file schema mismatch: {name}")
        if document.get("dataset_version") != manifest.get("dataset_version"):
            raise ValueError(f"tag repair file dataset mismatch: {name}")
        if document.get("base_manifest_sha256") != base_manifest_sha256:
            raise ValueError(f"tag repair file base binding mismatch: {name}")
        if (
            document.get("predicate_policy_version")
            != manifest.get("predicate_policy_version")
            or document.get("predicate_policy_sha256")
            != manifest.get("predicate_policy_sha256")
        ):
            raise ValueError(f"tag repair file policy binding mismatch: {name}")
        if document.get("boundaries") != TAG_REPAIR_BOUNDARIES:
            raise ValueError(f"tag repair file boundary mismatch: {name}")
        loaded_files[name] = document

    semantic_audit = loaded_files["semantic-audit.json"]
    if semantic_audit.get("review_status") != "complete":
        raise ValueError("tag repair semantic review is incomplete")
    if semantic_audit.get("summary") != manifest.get("audit_summary"):
        raise ValueError("tag repair audit summary mismatch")
    if semantic_audit["summary"].get("status") != manifest.get("status"):
        raise ValueError("tag repair status mismatch")
    return {
        "applied": True,
        "schema_version": manifest["schema_version"],
        "dataset_version": manifest["dataset_version"],
        "manifest_sha256": _sha256(manifest_path),
        "status": manifest["status"],
    }


def _entity_rows(
    posts: list[dict[str, Any]], comments: list[dict[str, Any]]
) -> list[tuple[str, dict[str, Any]]]:
    return [
        *(("post", row) for row in posts),
        *(("comment", row) for row in comments if row["include_in_voc_metrics"]),
    ]


def _dataset_version(config: dict[str, Any]) -> str:
    value = config.get("dataset_version")
    if not isinstance(value, str) or not DATASET_VERSION_PATTERN.fullmatch(value):
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
    if len(references) != 1:
        raise ValueError(f"persona dictionary reference is ambiguous: {tag_id}")
    values = next(iter(references))
    if not all(isinstance(value, str) and value.strip() for value in values):
        raise ValueError(f"persona dictionary reference is incomplete: {tag_id}")
    consumer_card, aipl_node, story_lines, intent_type, problem_type = values
    return {
        "consumer_card": consumer_card,
        "aipl_node": aipl_node,
        "story_lines": [story_lines],
        "intent_type": [intent_type],
        "problem_type": [problem_type],
    }


def _assignment(
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
    if len(matches) != 1:
        raise ValueError(
            f"persona evidence has unexpected tag matches: {persona_id}/{entity['evidence_id']}"
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


def build(
    snapshot_dir: Path,
    insights_dir: Path,
    config_path: Path,
    avatar_dir: Path,
    tag_repair_dir: Path | None = None,
    tag_repair_policy_path: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
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

    base_manifest_path = snapshot_dir / "manifest.json"
    insights_manifest_path = insights_dir / "manifest.json"
    base_manifest = _load(base_manifest_path)
    insights_manifest = _load(insights_manifest_path)
    insights = _load(insights_dir / "insights.json")
    audit = _load(insights_dir / "semantic-audit.json")
    config = _load(config_path)
    posts = _load(snapshot_dir / "posts.json")
    comments = _load(snapshot_dir / "comments.json")
    dictionary = _load(snapshot_dir / "tag-dictionary.json")

    _verify_manifest_files(snapshot_dir, base_manifest)
    _verify_manifest_files(insights_dir, insights_manifest)
    if not base_manifest.get("all_checks_passed"):
        raise ValueError("base snapshot validation is not green")
    if base_manifest.get("provider_call") is not False:
        raise ValueError("base snapshot provider boundary mismatch")
    if insights_manifest["base_dataset_version"] != base_manifest["dataset_version"]:
        raise ValueError("insights/base dataset mismatch")
    if insights_manifest["base_manifest_sha256"] != _sha256(base_manifest_path):
        raise ValueError("insights/base manifest hash mismatch")
    if config.get("schema_version") != "reddit_voc_persona_config_v1":
        raise ValueError("persona config schema mismatch")
    dataset_version = _dataset_version(config)

    promoted_ids = set(audit["summary"]["promoted_tag_ids"])
    if _is_v2_insights(insights):
        audit_summary = insights_manifest.get("audit_summary")
        if (
            not isinstance(audit_summary, dict)
            or set(audit_summary.get("promoted_tag_ids", [])) != promoted_ids
        ):
            raise ValueError("insights v2 governance projection mismatch")
    signal_ids = {row["tag_id"] for row in insights["signals"]}
    if not _is_v2_insights(insights) and promoted_ids != signal_ids:
        raise ValueError("insights promoted tag set mismatch")
    signal_by_tag = {row["tag_id"]: row for row in insights["signals"]}
    persona_ids = [row["persona_id"] for row in config["personas"]]
    if len(persona_ids) != len(set(persona_ids)):
        raise ValueError("duplicate persona id")
    if len(persona_ids) != 2:
        raise ValueError("persona config must define exactly two personas")

    source_priority = _source_priority(config)
    minimum_distinct = int(config["minimum_distinct_pseudonyms"])
    entities = _entity_rows(posts, comments)
    personas_output: list[dict[str, Any]] = []
    assignments: list[dict[str, Any]] = []

    for definition in sorted(config["personas"], key=lambda row: row["persona_id"]):
        source_tag_ids = list(definition["source_tag_ids"])
        if len(source_tag_ids) != 1:
            raise ValueError("persona v1 requires exactly one source tag")
        source_tag_id = source_tag_ids[0]
        if source_tag_id not in promoted_ids:
            raise ValueError(f"persona source tag is not promoted: {source_tag_id}")
        if source_tag_id not in signal_by_tag:
            raise ValueError(f"persona source tag is missing from insights: {source_tag_id}")
        signal = signal_by_tag[source_tag_id]
        selected = [
            (entity_type, entity)
            for entity_type, entity in entities
            if source_tag_id in entity["tagging"]["aspect_tag_ids"]
        ]
        rows = [
            _assignment(
                definition["persona_id"],
                source_tag_id,
                entity_type,
                entity,
                source_priority,
            )
            for entity_type, entity in selected
        ]
        assignments.extend(rows)
        pseudonyms = {
            entity.get("author_pseudonym")
            for _, entity in selected
            if entity.get("author_pseudonym")
        }
        metrics = {
            "matched_entities": len(selected),
            "matched_posts": sum(entity_type == "post" for entity_type, _ in selected),
            "matched_comments": sum(
                entity_type == "comment" for entity_type, _ in selected
            ),
            "distinct_pseudonyms": len(pseudonyms),
            "threads": len({entity["post_id"] for _, entity in selected}),
        }
        if not _is_v2_insights(insights):
            if metrics["matched_posts"] != signal["matched_posts"]:
                raise ValueError(
                    f"persona post count does not match insights: {source_tag_id}"
                )
            if metrics["matched_comments"] != signal["matched_comments"]:
                raise ValueError(
                    f"persona comment count does not match insights: {source_tag_id}"
                )

        avatar_config = deepcopy(definition["avatar"])
        asset_path = _safe_asset_path(avatar_config.pop("asset_path")).as_posix()
        source_filename = avatar_config.pop("source_filename")
        if PurePosixPath(asset_path).name != source_filename:
            raise ValueError(f"avatar source mapping mismatch: {asset_path}")
        source_path = avatar_dir / source_filename
        if not source_path.is_file() or source_path.is_symlink():
            raise ValueError(f"avatar source missing or unsafe: {source_filename}")
        width, height = _svg_dimensions(source_path)
        if (width, height) != (avatar_config["width"], avatar_config["height"]):
            raise ValueError(f"avatar dimensions mismatch: {source_filename}")
        if avatar_config["media_type"] != SVG_MEDIA_TYPE:
            raise ValueError(f"avatar media type mismatch: {source_filename}")
        for key in (
            "synthetic",
            "real_user_image",
            "derived_from_reddit_media",
            "identity_claim",
        ):
            expected = key == "synthetic"
            if avatar_config[key] is not expected:
                raise ValueError(f"avatar identity boundary mismatch: {key}")
        avatar = {
            "asset_path": asset_path,
            "asset_sha256": _sha256(source_path),
            **avatar_config,
        }
        reference = _dictionary_reference(dictionary, source_tag_id)
        personas_output.append(
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
                "avatar": avatar,
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
    generated_at_utc = insights["generated_at_utc"]
    personas_document = {
        "schema_version": PERSONAS_SCHEMA,
        "dataset_version": dataset_version,
        "generated_at_utc": generated_at_utc,
        "persona_count": len(personas_output),
        "personas": personas_output,
        "interpretation_boundaries": _interpretation_boundaries(),
    }
    persona_tags_document = {
        "schema_version": PERSONA_TAGS_SCHEMA,
        "dataset_version": dataset_version,
        "grain": "persona_id_x_evidence_id",
        "assignment_count": len(assignments),
        "assignments": assignments,
        "boundaries": _assignment_boundaries(),
    }
    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "dataset_version": dataset_version,
        "delivery_mode": DELIVERY_MODE,
        "generated_at_utc": generated_at_utc,
        "base_dataset_version": base_manifest["dataset_version"],
        "base_manifest_sha256": _sha256(base_manifest_path),
        "insights_dataset_version": insights_manifest["dataset_version"],
        "insights_manifest_sha256": _sha256(insights_manifest_path),
        "dictionary_version": dictionary["dictionary_version"],
        "dictionary_sha256": dictionary["dictionary_sha256"],
        "config_version": config["config_version"],
        "config_sha256": _sha256(config_path),
        "tag_repair": _tag_repair_binding(
            tag_repair_dir,
            tag_repair_policy_path,
            base_manifest=base_manifest,
            base_manifest_sha256=_sha256(base_manifest_path),
            dictionary=dictionary,
        ),
        "persona_count": len(personas_output),
        "assignment_count": len(assignments),
        "source_tag_ids": sorted(
            {tag_id for row in config["personas"] for tag_id in row["source_tag_ids"]}
        ),
        "files": {},
        "boundaries": _manifest_boundaries(),
    }
    return personas_document, persona_tags_document, manifest


def write_snapshot(
    output_dir: Path,
    personas: dict[str, Any],
    persona_tags: dict[str, Any],
    manifest: dict[str, Any],
    avatar_dir: Path,
) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    avatar_dir = avatar_dir.resolve(strict=True)
    if output_dir.is_symlink():
        raise ValueError("persona output root is unsafe")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{output_dir.name}.staging-", dir=output_dir.parent
        )
    )
    try:
        os.chmod(staging, 0o700)
        _write(staging / "personas.json", personas)
        _write(staging / "persona-tags.json", persona_tags)

        avatar_by_path = {
            row["avatar"]["asset_path"]: row["avatar"]
            for row in personas["personas"]
        }
        for asset_path, avatar in sorted(avatar_by_path.items()):
            source_filename = PurePosixPath(asset_path).name
            source = avatar_dir / source_filename
            if not source.is_file() or source.is_symlink():
                raise ValueError(
                    f"avatar source missing or unsafe: {source_filename}"
                )
            destination = staging / _safe_asset_path(asset_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            if _sha256(destination) != avatar["asset_sha256"]:
                raise ValueError(f"copied avatar hash mismatch: {asset_path}")

        files: dict[str, dict[str, Any]] = {}
        for name in ("personas.json", "persona-tags.json"):
            path = staging / name
            files[name] = {
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
                "media_type": "application/json",
            }
        for asset_path, avatar in sorted(avatar_by_path.items()):
            path = staging / asset_path
            files[asset_path] = {
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
                "media_type": avatar["media_type"],
                "width": avatar["width"],
                "height": avatar["height"],
            }
        complete_manifest = deepcopy(manifest)
        complete_manifest["files"] = files
        _write(staging / "manifest.json", complete_manifest)
        _harden_private_tree(staging)
        if output_dir.exists():
            if _tree_contract(output_dir) != _tree_contract(staging):
                raise FileExistsError(
                    f"persona output root collision: {output_dir}"
                )
        else:
            os.rename(staging, output_dir)
    finally:
        if staging.exists() and not staging.is_symlink():
            shutil.rmtree(staging)
    return complete_manifest


def build_v3(*args: Any, **kwargs: Any) -> Any:
    """Build V3 82-atom/8-cohort documents without changing the V1 contract."""
    from reddit_voc.v3_persona_snapshot import build_v3_persona_documents

    return build_v3_persona_documents(*args, **kwargs)


def write_v3_snapshot(*args: Any, **kwargs: Any) -> Any:
    """Atomically materialize a V3 snapshot; the legacy writer remains intact."""
    from reddit_voc.v3_persona_snapshot import write_v3_persona_snapshot

    return write_v3_persona_snapshot(*args, **kwargs)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--insights-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--avatar-dir", type=Path, required=True)
    parser.add_argument("--tag-repair-dir", type=Path)
    parser.add_argument("--tag-repair-policy", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    personas, persona_tags, manifest = build(
        args.snapshot_dir,
        args.insights_dir,
        args.config,
        args.avatar_dir,
        args.tag_repair_dir,
        args.tag_repair_policy,
    )
    complete_manifest = write_snapshot(
        args.output_dir,
        personas,
        persona_tags,
        manifest,
        args.avatar_dir,
    )
    print(
        json.dumps(
            {
                "status": "built",
                "dataset_version": complete_manifest["dataset_version"],
                "persona_count": complete_manifest["persona_count"],
                "assignment_count": complete_manifest["assignment_count"],
                **complete_manifest["boundaries"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
