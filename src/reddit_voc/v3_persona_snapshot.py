from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Any, Iterable, Mapping
import xml.etree.ElementTree as ET

from reddit_voc.v3_persona_inference import (
    PersonaAtomicFact,
    PersonaCohortAssignment,
    PersonaCohortConfig,
    PersonaDictionary,
    build_cohort_assignments,
    canonical_json_bytes,
    canonical_persona_fact_jsonl_bytes,
    infer_persona_facts,
)


PERSONA_MANIFEST_SCHEMA = "reddit_voc_personas_manifest_v3"
PERSONAS_SCHEMA = "reddit_voc_personas_v3"
PERSONA_CATALOG_SCHEMA = "reddit_voc_persona_atomic_catalog_v1"
PERSONA_BRIDGE_SCHEMA = "reddit_voc_persona_cohort_bridge_v1"
PERSONA_ASSIGNMENTS_SCHEMA = "reddit_voc_persona_cohort_assignments_v1"
DELIVERY_MODE = "versioned_static_content_entity_personas_v3"
JSON_MEDIA_TYPE = "application/json"
JSONL_MEDIA_TYPE = "application/x-ndjson"
SVG_MEDIA_TYPE = "image/svg+xml"
BOUNDARIES = {
    "author_level_personas": False,
    "counts_are_content_entities_not_users": True,
    "database_write": False,
    "demographics_supported": False,
    "deploy": False,
    "live_send": False,
    "population_share_supported": False,
    "production_unchanged": True,
    "provider_call": False,
    "real_user_images": False,
    "remote_write": False,
}
ALLOWED_SVG_TAGS = frozenset(
    {"svg", "rect", "circle", "ellipse", "path", "g", "line", "polyline", "polygon"}
)


class PersonaSnapshotError(ValueError):
    """The V3 persona snapshot is not complete, replayable or privacy bounded."""


@dataclass(frozen=True)
class PersonaSnapshotDocuments:
    personas: dict[str, object]
    catalog: dict[str, object]
    bridge: dict[str, object]
    assignments: dict[str, object]
    facts: tuple[PersonaAtomicFact, ...]
    manifest: dict[str, object]


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if hasattr(value, "as_dict"):
        value = value.as_dict()
    if not isinstance(value, Mapping):
        raise PersonaSnapshotError(f"{label} must be an object")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise PersonaSnapshotError(f"{label} must be a non-empty string")
    return value


def _sha_string(value: object, label: str) -> str:
    text = _string(value, label)
    if re.fullmatch(r"[0-9a-f]{64}", text) is None:
        raise PersonaSnapshotError(f"{label} must be a lowercase SHA-256")
    return text


def _timestamp(value: object) -> str:
    text = _string(value, "persona generated timestamp")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PersonaSnapshotError("persona generated timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise PersonaSnapshotError("persona generated timestamp must be UTC")
    return parsed.astimezone(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _line_count(path: Path) -> int:
    with path.open("rb") as handle:
        return sum(1 for _ in handle)


def _tree_contract(root: Path) -> dict[str, object]:
    if root.is_symlink() or not root.is_dir():
        raise PersonaSnapshotError("persona snapshot tree is unsafe")
    entries: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise PersonaSnapshotError("persona snapshot tree contains a symlink")
        if path.is_dir():
            kind = "directory"
            digest = None
        elif path.is_file():
            kind = "file"
            digest = _sha256(path)
        else:
            raise PersonaSnapshotError("persona snapshot tree contains an unsafe entry")
        entries.append(
            {
                "kind": kind,
                "mode": path.stat().st_mode & 0o777,
                "path": relative,
                "sha256": digest,
            }
        )
    return {"entries": entries, "root_mode": root.stat().st_mode & 0o777}


def _canonical_json_file_bytes(value: object) -> bytes:
    return canonical_json_bytes(value) + b"\n"


def _safe_relative_asset(value: object) -> PurePosixPath:
    if (
        not isinstance(value, str)
        or not value
        or value.startswith(("/", "data:", "blob:"))
        or "://" in value
    ):
        raise PersonaSnapshotError("persona avatar path is not local")
    path = PurePosixPath(value)
    if path.parts[0] != "assets" or ".." in path.parts or path.suffix != ".svg":
        raise PersonaSnapshotError("persona avatar path is not local")
    return path


def _safe_source_asset(project_root: Path, value: object) -> Path:
    relative = _string(value, "persona source avatar path")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or pure.suffix != ".svg":
        raise PersonaSnapshotError("persona source avatar path is unsafe")
    root = project_root.resolve(strict=True)
    unresolved = root
    for part in pure.parts:
        unresolved /= part
        if unresolved.is_symlink():
            raise PersonaSnapshotError("persona source avatar is a symlink")
    path = unresolved.resolve(strict=True)
    if not path.is_file() or root not in path.parents:
        raise PersonaSnapshotError("persona source avatar is unsafe")
    return path


def _validate_svg(path: Path) -> tuple[int, int]:
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
    )
    if any(marker in lowered for marker in forbidden):
        raise PersonaSnapshotError(f"persona avatar contains an unsafe marker: {path.name}")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise PersonaSnapshotError(f"persona avatar is invalid XML: {path.name}") from exc
    if root.tag.rsplit("}", 1)[-1] != "svg":
        raise PersonaSnapshotError("persona avatar root is invalid")
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] not in ALLOWED_SVG_TAGS:
            raise PersonaSnapshotError("persona avatar contains an unsafe element")
        if (node.text or "").strip():
            raise PersonaSnapshotError("persona avatar contains text")
        for raw_name, raw_value in node.attrib.items():
            name = raw_name.rsplit("}", 1)[-1].casefold()
            value = str(raw_value).casefold()
            if name == "href" or name.startswith("on") or any(
                marker in value for marker in ("://", "javascript:", "data:", "url(")
            ):
                raise PersonaSnapshotError("persona avatar contains an unsafe attribute")
    try:
        width = int(root.attrib["width"])
        height = int(root.attrib["height"])
    except (KeyError, ValueError) as exc:
        raise PersonaSnapshotError("persona avatar dimensions are invalid") from exc
    if (width, height) != (512, 512) or root.attrib.get("viewBox") != "0 0 512 512":
        raise PersonaSnapshotError("persona avatar dimensions must be 512x512")
    return width, height


def _validate_voc_identity(row: Mapping[str, Any]) -> tuple[str, str, str]:
    if row.get("schema_version") != "reddit_voc_fielded_voc_v1":
        raise PersonaSnapshotError("persona VOC schema is invalid")
    if row.get("analysis_text_status") != "ready":
        raise PersonaSnapshotError("persona VOC is not analysis ready")
    voc_id = _string(row.get("voc_id"), "persona VOC ID")
    voc_type = _string(row.get("voc_type"), "persona VOC type")
    entity_id = _string(row.get("canonical_entity_id"), "persona canonical entity ID")
    post_id = _string(row.get("post_id"), "persona parent post ID")
    if row.get("thread_id") != post_id:
        raise PersonaSnapshotError("persona VOC thread identity is invalid")
    if voc_type == "post_voc":
        if voc_id != f"post:{post_id}" or entity_id != f"t3_{post_id}" or row.get("comment_id") is not None:
            raise PersonaSnapshotError("post persona VOC identity is invalid")
    elif voc_type == "comment_context_voc":
        comment_id = _string(row.get("comment_id"), "persona comment ID")
        if voc_id != f"comment:{comment_id}" or entity_id != f"t1_{comment_id}":
            raise PersonaSnapshotError("comment persona VOC identity is invalid")
    else:
        raise PersonaSnapshotError("persona VOC type is unsupported")
    return voc_id, voc_type, entity_id


def _fact_summary(facts: Iterable[PersonaAtomicFact]) -> dict[str, int]:
    result = {"held": 0, "promoted": 0, "total": 0}
    for fact in facts:
        if fact.decision_status not in {"promoted", "held"}:
            raise PersonaSnapshotError("persona atomic fact status is invalid")
        result[fact.decision_status] += 1
        result["total"] += 1
    return result


def _availability(count: int, config: PersonaCohortConfig) -> str:
    thresholds = config.availability_thresholds
    if count >= thresholds["stable_sample_min"]:
        return "stable_observed_sample"
    if count >= thresholds["directional_sample_min"]:
        return "directional_observed_sample"
    return "unavailable_insufficient_observed_sample"


def _avatar_contract(project_root: Path, raw_avatar: Mapping[str, object]) -> dict[str, object]:
    source = _safe_source_asset(project_root, raw_avatar.get("source_asset_path"))
    fallback = _safe_source_asset(project_root, raw_avatar.get("fallback_source_asset_path"))
    _validate_svg(source)
    _validate_svg(fallback)
    public = _safe_relative_asset(raw_avatar.get("public_asset_path")).as_posix()
    fallback_public = _safe_relative_asset(raw_avatar.get("fallback_public_asset_path")).as_posix()
    if (
        raw_avatar.get("synthetic") is not True
        or raw_avatar.get("real_user_image") is not False
        or raw_avatar.get("derived_from_reddit_media") is not False
        or raw_avatar.get("identity_claim") is not False
        or raw_avatar.get("media_type") != SVG_MEDIA_TYPE
        or raw_avatar.get("width") != 512
        or raw_avatar.get("height") != 512
        or "非真实用户" not in str(raw_avatar.get("alt_text", ""))
    ):
        raise PersonaSnapshotError("persona avatar identity boundary is invalid")
    return {
        "alt_text": raw_avatar["alt_text"],
        "asset_path": public,
        "asset_sha256": _sha256(source),
        "derived_from_reddit_media": False,
        "fallback_asset_path": fallback_public,
        "fallback_asset_sha256": _sha256(fallback),
        "height": 512,
        "identity_claim": False,
        "media_type": SVG_MEDIA_TYPE,
        "real_user_image": False,
        "synthetic": True,
        "width": 512,
    }


def build_v3_persona_documents(
    vocs: Iterable[object],
    *,
    automation_voc_ids: Iterable[str],
    dictionary: PersonaDictionary,
    config: PersonaCohortConfig,
    snapshot_id: str,
    generated_at_utc: str,
    source_facts_manifest_sha256: str,
    source_facts_validation_receipt_sha256: str,
    automation_manifest_sha256: str,
    automation_classifications_sha256: str,
    automation_classification_rows: int,
    reference_manifest_sha256: str,
    project_root: Path,
    upstream_consumption_status: str,
    upstream_promotable: bool,
    governed_signals_by_voc_id: Mapping[str, Mapping[str, object]] | None = None,
    governed_signal_facts_by_voc_id: Mapping[
        str, Mapping[str, object]
    ] | None = None,
    governed_signal_manifest_sha256: str | None = None,
    governed_signal_validation_receipt_sha256: str | None = None,
    governed_signal_snapshot_id: str | None = None,
    governed_signal_source_snapshot_id: str | None = None,
    governed_signal_loaded_promoted_fact_count: int = 0,
    governed_signal_dropped_comment_fact_count: int = 0,
    governed_signal_dropped_comment_voc_count: int = 0,
) -> PersonaSnapshotDocuments:
    if not isinstance(dictionary, PersonaDictionary) or not isinstance(config, PersonaCohortConfig):
        raise PersonaSnapshotError("persona dictionary or cohort config is invalid")
    snapshot_id = _string(snapshot_id, "persona snapshot ID")
    generated_at_utc = _timestamp(generated_at_utc)
    source_facts_manifest_sha256 = _sha_string(
        source_facts_manifest_sha256, "source facts manifest SHA"
    )
    source_facts_validation_receipt_sha256 = _sha_string(
        source_facts_validation_receipt_sha256,
        "source facts validation receipt SHA",
    )
    automation_manifest_sha256 = _sha_string(
        automation_manifest_sha256, "automation manifest SHA"
    )
    automation_classifications_sha256 = _sha_string(
        automation_classifications_sha256,
        "automation classifications SHA",
    )
    automation = set(automation_voc_ids)
    if any(not isinstance(value, str) or not value for value in automation):
        raise PersonaSnapshotError("automation persona exclusion IDs are invalid")
    if (
        isinstance(automation_classification_rows, bool)
        or not isinstance(automation_classification_rows, int)
        or automation_classification_rows < len(automation)
    ):
        raise PersonaSnapshotError("automation classification row count is invalid")
    reference_manifest_sha256 = _sha_string(
        reference_manifest_sha256, "persona reference manifest SHA"
    )
    if upstream_consumption_status not in {
        "eligible_for_downstream_consumption",
        "blocked_pending_atomic_facts",
    } or type(upstream_promotable) is not bool:
        raise PersonaSnapshotError("persona upstream consumption state is invalid")
    if (
        upstream_consumption_status == "eligible_for_downstream_consumption"
    ) is not upstream_promotable:
        raise PersonaSnapshotError("persona upstream promotable state is inconsistent")
    signals_by_voc = (
        {}
        if governed_signals_by_voc_id is None
        else dict(governed_signals_by_voc_id)
    )
    signal_facts_by_voc = (
        {}
        if governed_signal_facts_by_voc_id is None
        else dict(governed_signal_facts_by_voc_id)
    )
    governed_values = (
        governed_signal_manifest_sha256,
        governed_signal_validation_receipt_sha256,
        governed_signal_snapshot_id,
        governed_signal_source_snapshot_id,
    )
    governed_bound = any(value is not None for value in governed_values)
    if governed_bound:
        if any(value is None for value in governed_values):
            raise PersonaSnapshotError("governed signal lineage is incomplete")
        governed_signal_manifest_sha256 = _sha_string(
            governed_signal_manifest_sha256, "governed signal manifest SHA"
        )
        governed_signal_validation_receipt_sha256 = _sha_string(
            governed_signal_validation_receipt_sha256,
            "governed signal validation receipt SHA",
        )
        governed_signal_snapshot_id = _string(
            governed_signal_snapshot_id, "governed signal snapshot ID"
        )
        governed_signal_source_snapshot_id = _string(
            governed_signal_source_snapshot_id,
            "governed signal source snapshot ID",
        )
        if (
            upstream_consumption_status != "eligible_for_downstream_consumption"
            or upstream_promotable is not True
        ):
            raise PersonaSnapshotError(
                "governed persona signals are not downstream eligible"
            )
    elif signals_by_voc or signal_facts_by_voc:
        raise PersonaSnapshotError("governed persona signals lack lineage")
    if set(signals_by_voc) != set(signal_facts_by_voc):
        raise PersonaSnapshotError("governed persona signal registries are inconsistent")
    for label, value in (
        (
            "governed signal loaded promoted fact count",
            governed_signal_loaded_promoted_fact_count,
        ),
        (
            "governed signal dropped comment fact count",
            governed_signal_dropped_comment_fact_count,
        ),
        (
            "governed signal dropped comment VOC count",
            governed_signal_dropped_comment_voc_count,
        ),
    ):
        if type(value) is not int or value < 0:
            raise PersonaSnapshotError(f"{label} is invalid")
    injected_governed_fact_count = sum(
        len(registry)
        for registry in signal_facts_by_voc.values()
        if isinstance(registry, Mapping)
    )
    if any(not isinstance(registry, Mapping) for registry in signal_facts_by_voc.values()):
        raise PersonaSnapshotError("governed persona fact registry is invalid")
    if governed_bound and (
        governed_signal_loaded_promoted_fact_count
        != injected_governed_fact_count
        + governed_signal_dropped_comment_fact_count
    ):
        raise PersonaSnapshotError("governed persona signal accounting is invalid")
    all_facts: list[PersonaAtomicFact] = []
    all_assignments: list[PersonaCohortAssignment] = []
    observed_voc_ids: set[str] = set()
    excluded_automation: set[str] = set()
    for raw in vocs:
        row = _mapping(raw, "persona VOC")
        voc_id, _voc_type, _entity_id = _validate_voc_identity(row)
        if voc_id in observed_voc_ids:
            raise PersonaSnapshotError("duplicate persona VOC ID")
        observed_voc_ids.add(voc_id)
        if voc_id in automation:
            excluded_automation.add(voc_id)
            continue
        facts = infer_persona_facts(row, dictionary=dictionary, snapshot_id=snapshot_id)
        all_facts.extend(facts)
        raw_signals = signals_by_voc.get(voc_id)
        signals = {"snapshot_id": snapshot_id}
        governed_registry = None
        if raw_signals is not None:
            if not isinstance(raw_signals, Mapping):
                raise PersonaSnapshotError("governed persona signal set is invalid")
            signals.update(dict(raw_signals))
            governed_registry = signal_facts_by_voc[voc_id]
        all_assignments.extend(
            build_cohort_assignments(
                row,
                facts=facts,
                config=config,
                signals=signals,
                explicit_automation=False,
                governed_signal_facts_by_id=governed_registry,
                governed_source_snapshot_id=(
                    governed_signal_source_snapshot_id
                    if raw_signals is not None
                    else None
                ),
            )
        )
    orphan_automation = automation - observed_voc_ids
    if orphan_automation:
        raise PersonaSnapshotError("automation persona exclusions contain non-VOC identities")
    orphan_signal_vocs = set(signals_by_voc) - observed_voc_ids
    if orphan_signal_vocs:
        raise PersonaSnapshotError(
            "governed persona signals contain non-VOC identities"
        )
    if set(signals_by_voc) & automation:
        raise PersonaSnapshotError("automation VOC has governed persona signals")

    if len({fact.fact_id for fact in all_facts}) != len(all_facts):
        raise PersonaSnapshotError("duplicate persona atomic fact ID")
    if len({row.assignment_id for row in all_assignments}) != len(all_assignments):
        raise PersonaSnapshotError("duplicate persona cohort assignment ID")
    all_facts.sort(key=lambda row: (row.voc_id, row.persona_id, row.decision_status, row.fact_id))
    all_assignments.sort(key=lambda row: (row.cohort_id, row.voc_id, row.assignment_id))

    catalog_rows = [
        {
            "definition": row.definition,
            "dimension": row.dimension,
            "hit_rate_tier": row.hit_rate_tier,
            "keyword_count": len(row.keywords),
            "lifecycle_stage": row.lifecycle_stage,
            "persona_id": row.persona_id,
            "persona_name": row.persona_name,
            "semantic_pattern": row.semantic_pattern,
            "sub_dimension": row.sub_dimension,
        }
        for row in dictionary.definitions
    ]
    catalog = {
        "schema_version": PERSONA_CATALOG_SCHEMA,
        "snapshot_id": snapshot_id,
        "atomic_persona_count": len(catalog_rows),
        "dictionary_sha256": dictionary.sha256,
        "atomic_personas": catalog_rows,
        "boundaries": {
            "dictionary_closed_set": True,
            "facts_are_content_evidence_not_people": True,
        },
    }

    cohort_by_id = {row.cohort_id: row for row in config.cohorts}
    avatar_by_cohort = {
        cohort_id: _avatar_contract(project_root, cohort.avatar)
        for cohort_id, cohort in cohort_by_id.items()
    }
    bridge_rows = [
        {
            "avatar": avatar_by_cohort[row.cohort_id],
            "bridge_edge_count": len(row.persona_tag_ids),
            "cohort_id": row.cohort_id,
            "definition": row.definition,
            "name_cn": row.name_cn,
            "persona_tag_ids": list(row.persona_tag_ids),
            "trigger_paths": [dict(path) for path in row.trigger_paths],
        }
        for row in config.cohorts
    ]
    bridge = {
        "schema_version": PERSONA_BRIDGE_SCHEMA,
        "snapshot_id": snapshot_id,
        "config_version": config.config_version,
        "config_sha256": config.config_sha256,
        "cohort_count": len(bridge_rows),
        "bridge_edge_count": sum(row["bridge_edge_count"] for row in bridge_rows),
        "unbridged_persona_tag_ids": list(config.unbridged_persona_tag_ids),
        "cohorts": bridge_rows,
    }

    assignments_by_cohort: dict[str, list[PersonaCohortAssignment]] = defaultdict(list)
    for assignment in all_assignments:
        assignments_by_cohort[assignment.cohort_id].append(assignment)
    persona_rows: list[dict[str, object]] = []
    for cohort in config.cohorts:
        rows = assignments_by_cohort[cohort.cohort_id]
        unique_entities = {row.entity_id for row in rows}
        persona_rows.append(
            {
                "assignment_count": len(rows),
                "avatar": avatar_by_cohort[cohort.cohort_id],
                "cohort_id": cohort.cohort_id,
                "comment_count": sum(row.source_entity_type == "comment" for row in rows),
                "coverage_scope": "observed_content_entities_only",
                "definition": cohort.definition,
                "name_cn": cohort.name_cn,
                "persona_atomic_tag_count": len(cohort.persona_tag_ids),
                "population_share_supported": False,
                "post_count": sum(row.source_entity_type == "post" for row in rows),
                "status": _availability(len(unique_entities), config),
                "thread_count": len({row.thread_id for row in rows}),
                "unique_entity_count": len(unique_entities),
            }
        )
    personas = {
        "schema_version": PERSONAS_SCHEMA,
        "snapshot_id": snapshot_id,
        "generated_at_utc": generated_at_utc,
        "persona_cohort_count": len(persona_rows),
        "personas": persona_rows,
        "interpretation_boundaries": {
            "counts_are_assignments_and_content_entities_not_users": True,
            "parent_persona_inheritance": False,
            "population_share_supported": False,
            "unavailable_means_insufficient_observed_evidence": True,
        },
    }
    assignment_rows = [row.as_dict() for row in all_assignments]
    assignments = {
        "schema_version": PERSONA_ASSIGNMENTS_SCHEMA,
        "snapshot_id": snapshot_id,
        "grain": "cohort_id_x_voc_id",
        "assignment_count": len(assignment_rows),
        "unique_entity_count": len({row.entity_id for row in all_assignments}),
        "post_count": sum(row.source_entity_type == "post" for row in all_assignments),
        "comment_count": sum(row.source_entity_type == "comment" for row in all_assignments),
        "assignments": assignment_rows,
        "boundaries": {
            "author_level_personas": False,
            "counts_are_content_entities_not_users": True,
            "explicit_automation_excluded": True,
        },
    }
    facts_summary = _fact_summary(all_facts)
    manifest = {
        "schema_version": PERSONA_MANIFEST_SCHEMA,
        "snapshot_id": snapshot_id,
        "delivery_mode": DELIVERY_MODE,
        "generated_at_utc": generated_at_utc,
        "source_facts_manifest_sha256": source_facts_manifest_sha256,
        "source_facts_validation_receipt_sha256": (
            source_facts_validation_receipt_sha256
        ),
        "automation_manifest_sha256": automation_manifest_sha256,
        "automation_classifications_sha256": automation_classifications_sha256,
        "reference_manifest_sha256": reference_manifest_sha256,
        "persona_dictionary_sha256": dictionary.sha256,
        "cohort_config_sha256": config.config_sha256,
        "status": (
            "candidate_built"
            if upstream_promotable
            else "candidate_built_blocked_pending_atomic_facts"
        ),
        "consumption_status": (
            "eligible_for_downstream_consumption"
            if upstream_promotable
            else "blocked_pending_governed_atomic_signals"
        ),
        "promotable": upstream_promotable,
        "upstream": {
            "consumption_status": upstream_consumption_status,
            "promotable": upstream_promotable,
        },
        "counts": {
            "analysis_ready_vocs": len(observed_voc_ids),
            "automation_classification_rows": automation_classification_rows,
            "atomic_persona_catalog": len(catalog_rows),
            "automation_excluded_vocs": len(excluded_automation),
            "cohort_assignments": len(all_assignments),
            "persona_atomic_facts": facts_summary["total"],
            "persona_atomic_facts_held": facts_summary["held"],
            "persona_atomic_facts_promoted": facts_summary["promoted"],
            "persona_cohorts": len(persona_rows),
            "unique_assigned_content_entities": len(
                {row.entity_id for row in all_assignments}
            ),
        },
        "files": {},
        "boundaries": dict(BOUNDARIES),
    }
    if governed_bound:
        manifest.update(
            {
                "governed_signal_manifest_sha256": (
                    governed_signal_manifest_sha256
                ),
                "governed_signal_snapshot_id": governed_signal_snapshot_id,
                "governed_signal_source_snapshot_id": (
                    governed_signal_source_snapshot_id
                ),
                "governed_signal_validation_receipt_sha256": (
                    governed_signal_validation_receipt_sha256
                ),
            }
        )
        manifest["counts"].update(
            {
                "governed_signal_comment_facts_dropped": (
                    governed_signal_dropped_comment_fact_count
                ),
                "governed_signal_comment_vocs_dropped_no_direct_evidence": (
                    governed_signal_dropped_comment_voc_count
                ),
                "governed_signal_facts_injected": injected_governed_fact_count,
                "governed_signal_promoted_facts_loaded": (
                    governed_signal_loaded_promoted_fact_count
                ),
                "governed_signal_vocs_injected": len(signals_by_voc),
            }
        )
    return PersonaSnapshotDocuments(
        personas=personas,
        catalog=catalog,
        bridge=bridge,
        assignments=assignments,
        facts=tuple(all_facts),
        manifest=manifest,
    )


def _asset_sources(
    project_root: Path, config: PersonaCohortConfig
) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for cohort in config.cohorts:
        for public_key, source_key in (
            ("public_asset_path", "source_asset_path"),
            ("fallback_public_asset_path", "fallback_source_asset_path"),
        ):
            public = _safe_relative_asset(cohort.avatar.get(public_key)).as_posix()
            source = _safe_source_asset(project_root, cohort.avatar.get(source_key))
            _validate_svg(source)
            existing = result.get(public)
            if existing is not None and existing.read_bytes() != source.read_bytes():
                raise PersonaSnapshotError("persona avatar public path collision")
            result[public] = source
    return result


def write_v3_persona_snapshot(
    output_dir: Path,
    documents: PersonaSnapshotDocuments,
    *,
    project_root: Path,
    config: PersonaCohortConfig,
) -> dict[str, object]:
    if not isinstance(documents, PersonaSnapshotDocuments):
        raise PersonaSnapshotError("persona snapshot documents are invalid")
    raw_output = Path(output_dir)
    if raw_output.is_symlink():
        raise PersonaSnapshotError("persona snapshot output is unsafe")
    output = raw_output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent))
    try:
        os.chmod(staging, 0o700)
        payloads = {
            "persona-atomic-catalog.json": _canonical_json_file_bytes(documents.catalog),
            "persona-atomic-facts.jsonl": canonical_persona_fact_jsonl_bytes(documents.facts),
            "persona-cohort-bridge.json": _canonical_json_file_bytes(documents.bridge),
            "persona-tags.json": _canonical_json_file_bytes(documents.assignments),
            "personas.json": _canonical_json_file_bytes(documents.personas),
        }
        files: dict[str, dict[str, object]] = {}
        for name, payload in payloads.items():
            path = staging / name
            path.write_bytes(payload)
            os.chmod(path, 0o600)
            files[name] = {
                "bytes": len(payload),
                "media_type": JSONL_MEDIA_TYPE if name.endswith(".jsonl") else JSON_MEDIA_TYPE,
                "rows": payload.count(b"\n") if name.endswith(".jsonl") else 1,
                "sha256": sha256(payload).hexdigest(),
            }
        for public, source in sorted(_asset_sources(project_root, config).items()):
            destination = staging / public
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(destination.parent, 0o700)
            shutil.copyfile(source, destination)
            os.chmod(destination, 0o600)
            files[public] = {
                "bytes": destination.stat().st_size,
                "height": 512,
                "media_type": SVG_MEDIA_TYPE,
                "sha256": _sha256(destination),
                "width": 512,
            }
        manifest = dict(documents.manifest)
        manifest["files"] = files
        manifest_path = staging / "manifest.json"
        manifest_path.write_bytes(_canonical_json_file_bytes(manifest))
        os.chmod(manifest_path, 0o600)
        if output.exists():
            if _tree_contract(staging) != _tree_contract(output):
                raise FileExistsError(f"persona snapshot output collision: {output}")
        else:
            os.rename(staging, output)
        return manifest
    finally:
        if staging.exists() and not staging.is_symlink():
            shutil.rmtree(staging)


def _load_json(path: Path) -> object:
    try:
        payload = path.read_bytes()
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PersonaSnapshotError(f"persona snapshot JSON is invalid: {path.name}") from exc
    if payload != _canonical_json_file_bytes(value):
        raise PersonaSnapshotError(f"persona snapshot JSON is not canonical: {path.name}")
    return value


def validate_v3_persona_snapshot(
    personas_dir: Path,
    *,
    vocs: Iterable[object],
    automation_voc_ids: Iterable[str],
    dictionary: PersonaDictionary,
    config: PersonaCohortConfig,
    project_root: Path,
    expected_source_facts_manifest_sha256: str,
    expected_source_facts_validation_receipt_sha256: str,
    expected_automation_manifest_sha256: str,
    expected_automation_classifications_sha256: str,
    expected_automation_classification_rows: int,
    expected_reference_manifest_sha256: str,
    expected_upstream_consumption_status: str,
    expected_upstream_promotable: bool,
    governed_signals_by_voc_id: Mapping[str, Mapping[str, object]] | None = None,
    governed_signal_facts_by_voc_id: Mapping[
        str, Mapping[str, object]
    ] | None = None,
    expected_governed_signal_manifest_sha256: str | None = None,
    expected_governed_signal_validation_receipt_sha256: str | None = None,
    expected_governed_signal_snapshot_id: str | None = None,
    expected_governed_signal_source_snapshot_id: str | None = None,
    expected_governed_signal_loaded_promoted_fact_count: int = 0,
    expected_governed_signal_dropped_comment_fact_count: int = 0,
    expected_governed_signal_dropped_comment_voc_count: int = 0,
) -> dict[str, object]:
    raw_root = Path(personas_dir)
    if raw_root.is_symlink():
        raise PersonaSnapshotError("persona snapshot root is unsafe")
    root = raw_root.resolve(strict=True)
    if not root.is_dir() or root.stat().st_mode & 0o777 != 0o700:
        raise PersonaSnapshotError("persona snapshot root is unsafe")
    for path in root.rglob("*"):
        if path.is_symlink():
            raise PersonaSnapshotError("persona snapshot contains a symlink")
        expected_mode = 0o700 if path.is_dir() else 0o600
        if path.stat().st_mode & 0o777 != expected_mode:
            raise PersonaSnapshotError("persona snapshot mode is invalid")
    manifest = _mapping(_load_json(root / "manifest.json"), "persona manifest")
    if manifest.get("schema_version") != PERSONA_MANIFEST_SCHEMA:
        raise PersonaSnapshotError("persona manifest schema is invalid")
    if manifest.get("delivery_mode") != DELIVERY_MODE or manifest.get("boundaries") != BOUNDARIES:
        raise PersonaSnapshotError("persona manifest boundary is invalid")
    expected_lineage = {
        "automation_manifest_sha256": _sha_string(
            expected_automation_manifest_sha256, "expected automation manifest SHA"
        ),
        "automation_classifications_sha256": _sha_string(
            expected_automation_classifications_sha256,
            "expected automation classifications SHA",
        ),
        "reference_manifest_sha256": _sha_string(
            expected_reference_manifest_sha256, "expected reference manifest SHA"
        ),
        "source_facts_manifest_sha256": _sha_string(
            expected_source_facts_manifest_sha256,
            "expected source facts manifest SHA",
        ),
        "source_facts_validation_receipt_sha256": _sha_string(
            expected_source_facts_validation_receipt_sha256,
            "expected source facts validation receipt SHA",
        ),
    }
    for key, expected in expected_lineage.items():
        if manifest.get(key) != expected:
            raise PersonaSnapshotError(f"persona manifest lineage mismatch: {key}")
    governed_lineage_values = (
        expected_governed_signal_manifest_sha256,
        expected_governed_signal_validation_receipt_sha256,
        expected_governed_signal_snapshot_id,
        expected_governed_signal_source_snapshot_id,
    )
    governed_lineage_keys = {
        "governed_signal_manifest_sha256",
        "governed_signal_snapshot_id",
        "governed_signal_source_snapshot_id",
        "governed_signal_validation_receipt_sha256",
    }
    governed_bound = any(value is not None for value in governed_lineage_values)
    if governed_bound:
        if any(value is None for value in governed_lineage_values):
            raise PersonaSnapshotError("expected governed signal lineage is incomplete")
        expected_governed_lineage = {
            "governed_signal_manifest_sha256": _sha_string(
                expected_governed_signal_manifest_sha256,
                "expected governed signal manifest SHA",
            ),
            "governed_signal_snapshot_id": _string(
                expected_governed_signal_snapshot_id,
                "expected governed signal snapshot ID",
            ),
            "governed_signal_source_snapshot_id": _string(
                expected_governed_signal_source_snapshot_id,
                "expected governed signal source snapshot ID",
            ),
            "governed_signal_validation_receipt_sha256": _sha_string(
                expected_governed_signal_validation_receipt_sha256,
                "expected governed signal validation receipt SHA",
            ),
        }
        for key, expected in expected_governed_lineage.items():
            if manifest.get(key) != expected:
                raise PersonaSnapshotError(
                    f"persona manifest governed lineage mismatch: {key}"
                )
    elif governed_lineage_keys & set(manifest):
        raise PersonaSnapshotError("persona manifest has unexpected governed lineage")
    expected_upstream = {
        "consumption_status": expected_upstream_consumption_status,
        "promotable": expected_upstream_promotable,
    }
    if manifest.get("upstream") != expected_upstream:
        raise PersonaSnapshotError("persona manifest upstream state mismatch")
    files = _mapping(manifest.get("files"), "persona manifest files")
    expected_names = {
        "persona-atomic-catalog.json",
        "persona-atomic-facts.jsonl",
        "persona-cohort-bridge.json",
        "persona-tags.json",
        "personas.json",
        *_asset_sources(project_root, config).keys(),
    }
    if set(files) != expected_names:
        raise PersonaSnapshotError("persona manifest file set is invalid")
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    if actual_files != expected_names | {"manifest.json"}:
        raise PersonaSnapshotError("persona snapshot contains undeclared files")
    actual_directories = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_dir() and not path.is_symlink()
    }
    if actual_directories != {"assets"}:
        raise PersonaSnapshotError("persona snapshot contains undeclared directories")
    for name, raw_contract in files.items():
        contract = _mapping(raw_contract, f"persona file contract {name}")
        path = root / str(name)
        if not path.is_file() or path.is_symlink():
            raise PersonaSnapshotError("persona manifest file is missing")
        if path.stat().st_size != contract.get("bytes") or _sha256(path) != contract.get("sha256"):
            raise PersonaSnapshotError("persona manifest file contract is invalid")
        if str(name).endswith(".svg"):
            _validate_svg(path)
            expected_contract = {
                "bytes": path.stat().st_size,
                "height": 512,
                "media_type": SVG_MEDIA_TYPE,
                "sha256": _sha256(path),
                "width": 512,
            }
        else:
            expected_contract = {
                "bytes": path.stat().st_size,
                "media_type": (
                    JSONL_MEDIA_TYPE if str(name).endswith(".jsonl") else JSON_MEDIA_TYPE
                ),
                "rows": (
                    _line_count(path) if str(name).endswith(".jsonl") else 1
                ),
                "sha256": _sha256(path),
            }
        if dict(contract) != expected_contract:
            raise PersonaSnapshotError("persona manifest file metadata is invalid")

    rebuilt = build_v3_persona_documents(
        vocs,
        automation_voc_ids=automation_voc_ids,
        dictionary=dictionary,
        config=config,
        snapshot_id=_string(manifest.get("snapshot_id"), "persona snapshot ID"),
        generated_at_utc=_timestamp(manifest.get("generated_at_utc")),
        source_facts_manifest_sha256=_sha_string(
            manifest.get("source_facts_manifest_sha256"), "source facts manifest SHA"
        ),
        source_facts_validation_receipt_sha256=_sha_string(
            manifest.get("source_facts_validation_receipt_sha256"),
            "source facts validation receipt SHA",
        ),
        automation_manifest_sha256=_sha_string(
            manifest.get("automation_manifest_sha256"), "automation manifest SHA"
        ),
        automation_classifications_sha256=_sha_string(
            manifest.get("automation_classifications_sha256"),
            "automation classifications SHA",
        ),
        automation_classification_rows=expected_automation_classification_rows,
        reference_manifest_sha256=_sha_string(
            manifest.get("reference_manifest_sha256"), "reference manifest SHA"
        ),
        project_root=project_root,
        upstream_consumption_status=expected_upstream_consumption_status,
        upstream_promotable=expected_upstream_promotable,
        governed_signals_by_voc_id=governed_signals_by_voc_id,
        governed_signal_facts_by_voc_id=governed_signal_facts_by_voc_id,
        governed_signal_manifest_sha256=(
            expected_governed_signal_manifest_sha256
        ),
        governed_signal_validation_receipt_sha256=(
            expected_governed_signal_validation_receipt_sha256
        ),
        governed_signal_snapshot_id=expected_governed_signal_snapshot_id,
        governed_signal_source_snapshot_id=(
            expected_governed_signal_source_snapshot_id
        ),
        governed_signal_loaded_promoted_fact_count=(
            expected_governed_signal_loaded_promoted_fact_count
        ),
        governed_signal_dropped_comment_fact_count=(
            expected_governed_signal_dropped_comment_fact_count
        ),
        governed_signal_dropped_comment_voc_count=(
            expected_governed_signal_dropped_comment_voc_count
        ),
    )
    expected_payloads = {
        "persona-atomic-catalog.json": _canonical_json_file_bytes(rebuilt.catalog),
        "persona-atomic-facts.jsonl": canonical_persona_fact_jsonl_bytes(rebuilt.facts),
        "persona-cohort-bridge.json": _canonical_json_file_bytes(rebuilt.bridge),
        "persona-tags.json": _canonical_json_file_bytes(rebuilt.assignments),
        "personas.json": _canonical_json_file_bytes(rebuilt.personas),
    }
    for name, expected in expected_payloads.items():
        if (root / name).read_bytes() != expected:
            raise PersonaSnapshotError(f"persona snapshot replay mismatch: {name}")
    for public, source in _asset_sources(project_root, config).items():
        if (root / public).read_bytes() != source.read_bytes():
            raise PersonaSnapshotError("persona avatar source byte mismatch")
    expected_manifest = dict(rebuilt.manifest)
    expected_manifest["files"] = {
        name: dict(files[name]) for name in sorted(files)
    }
    if dict(manifest) != expected_manifest:
        raise PersonaSnapshotError("persona manifest replay mismatch")
    validation_status = "passed" if manifest["promotable"] is True else "passed_candidate_only"
    return {
        "schema_version": "reddit_voc_personas_validation_v3",
        "status": validation_status,
        "snapshot_id": manifest["snapshot_id"],
        "manifest_sha256": _sha256(root / "manifest.json"),
        "consumption_status": manifest["consumption_status"],
        "promotable": manifest["promotable"],
        "counts": dict(manifest["counts"]),
        "checks": {
            "atomic_82_and_cohort_8_contract": True,
            "automation_exclusion_replayed": True,
            "avatar_bytes_and_safety": True,
            "content_entity_counts_not_users": True,
            "deterministic_full_byte_replay": True,
            "governed_signals_replayed": governed_bound,
            "manifest_lineage_and_files": True,
        },
        **BOUNDARIES,
    }
