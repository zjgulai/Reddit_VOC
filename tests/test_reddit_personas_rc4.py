from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.build_reddit_personas_snapshot import build, write_snapshot
from scripts.validate_reddit_personas_snapshot import validate


ROOT = Path(__file__).resolve().parents[1]
BASE_SNAPSHOT = (
    ROOT
    / "tmp/reddit-voc-plan-a1-20260715/base-a2"
    / "reddit_voc_site_snapshot_20260715_candidate_a2"
)
LEGACY_INSIGHTS = ROOT / "data/processed/reddit_voc_insights_20260714/insights.json"
PERSONA_CONFIG = ROOT / "config/personas/reddit-voc-evidence-personas-v2.json"
AVATAR_DIR = ROOT / "docs/superpowers/assets/reddit-voc-evidence-personas"
SOURCE_TAG_IDS = {"L0-GEN-075", "L0-GEN-103"}
HYDRATION_SOURCE_STRATUM = "tencent_existing_post_comment_hydration"


def _canonical_write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )


def _file_contract(path: Path) -> dict[str, object]:
    return {
        "bytes": path.stat().st_size,
        "sha256": sha256(path.read_bytes()).hexdigest(),
    }


def _rewrite_output_json(output_dir: Path, filename: str, value: object) -> None:
    path = output_dir / filename
    _canonical_write(path, value)
    manifest_path = output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][filename]["bytes"] = path.stat().st_size
    manifest["files"][filename]["sha256"] = sha256(path.read_bytes()).hexdigest()
    _canonical_write(manifest_path, manifest)


def _build_v2_insights_fixture(root: Path) -> Path:
    base_manifest_path = BASE_SNAPSHOT / "manifest.json"
    base_manifest = json.loads(base_manifest_path.read_text(encoding="utf-8"))
    dictionary = json.loads(
        (BASE_SNAPSHOT / "tag-dictionary.json").read_text(encoding="utf-8")
    )
    legacy = json.loads(LEGACY_INSIGHTS.read_text(encoding="utf-8"))
    signals = [
        row for row in legacy["signals"] if row["tag_id"] in SOURCE_TAG_IDS
    ]
    assert {row["tag_id"] for row in signals} == SOURCE_TAG_IDS
    dataset_version = "reddit_voc_insights_20260715_v2_fixture"
    generated_at = base_manifest["generated_at_utc"]
    insights = {
        "schema_version": "reddit_voc_insights_v2",
        "dataset_version": dataset_version,
        "base_dataset_version": base_manifest["dataset_version"],
        "generated_at_utc": generated_at,
        "headline": legacy["headline"],
        "signals": signals,
        "reference_dimensions": legacy["reference_dimensions"],
        "held_tags": legacy["held_tags"],
        "risk_command_center": {},
        "product_analysis": {},
        "report_booklets": {},
        "control_evidence": {},
    }
    audit = {
        "schema_version": "reddit_voc_tag_semantic_audit_v2",
        "audit_version": "fixture-governance-v2",
        "base_dataset_version": base_manifest["dataset_version"],
        "base_manifest_sha256": sha256(base_manifest_path.read_bytes()).hexdigest(),
        "dictionary_version": dictionary["dictionary_version"],
        "dictionary_sha256": dictionary["dictionary_sha256"],
        "summary": {
            "promoted_tags": 2,
            "held_tags": 0,
            "promoted_tag_ids": sorted(SOURCE_TAG_IDS),
            "held_tag_ids": [],
            "status": "governance_projection_no_raw_samples",
        },
        "boundaries": {
            "raw_review_samples_included": False,
            "production_unchanged": True,
            "provider_call": False,
            "database_write": False,
            "live_send": False,
        },
    }
    insights_path = root / "insights.json"
    audit_path = root / "semantic-audit.json"
    _canonical_write(insights_path, insights)
    _canonical_write(audit_path, audit)
    manifest = {
        "schema_version": "reddit_voc_insights_manifest_v1",
        "contract_extension": "reddit_voc_insights_manifest_v2",
        "dataset_version": dataset_version,
        "delivery_mode": "versioned_static_insights_overlay",
        "generated_at_utc": generated_at,
        "base_dataset_version": base_manifest["dataset_version"],
        "base_manifest_sha256": sha256(base_manifest_path.read_bytes()).hexdigest(),
        "dictionary_version": dictionary["dictionary_version"],
        "dictionary_sha256": dictionary["dictionary_sha256"],
        "status": "passed_with_scope_limits",
        "audit_summary": {
            "audited_tags": 2,
            "reviewed_assignments": None,
            "promoted_tags": 2,
            "held_tags": 0,
            "promoted_tag_ids": sorted(SOURCE_TAG_IDS),
            "held_tag_ids": [],
            "status": "passed_with_scope_limits",
        },
        "files": {
            "insights.json": _file_contract(insights_path),
            "semantic-audit.json": _file_contract(audit_path),
        },
    }
    _canonical_write(root / "manifest.json", manifest)
    return root


def _build_overlay(output_dir: Path, insights_dir: Path) -> dict[str, Any]:
    personas, persona_tags, manifest = build(
        BASE_SNAPSHOT,
        insights_dir,
        PERSONA_CONFIG,
        AVATAR_DIR,
    )
    return write_snapshot(
        output_dir,
        personas,
        persona_tags,
        manifest,
        AVATAR_DIR,
    )


def test_v2_recomputes_current_assignments_instead_of_reusing_legacy_counts(
    tmp_path: Path,
) -> None:
    insights_dir = _build_v2_insights_fixture(tmp_path / "insights")
    output_dir = tmp_path / "personas"
    manifest = _build_overlay(output_dir, insights_dir)
    receipt = validate(
        output_dir,
        BASE_SNAPSHOT,
        insights_dir,
        PERSONA_CONFIG,
        AVATAR_DIR,
    )
    personas = json.loads((output_dir / "personas.json").read_text(encoding="utf-8"))
    assignments = json.loads(
        (output_dir / "persona-tags.json").read_text(encoding="utf-8")
    )["assignments"]

    assert manifest["dataset_version"] == "reddit_voc_personas_20260715_v2"
    assert (
        manifest["base_dataset_version"]
        == "reddit_voc_site_snapshot_20260715_candidate_a2"
    )
    assert manifest["assignment_count"] == 323
    assert receipt["status"] == "passed"
    assert all(receipt["checks"].values())
    assert {
        row["persona_id"]: row["metrics"] for row in personas["personas"]
    } == {
        "PER-SCENE-WORK-001": {
            "matched_entities": 132,
            "matched_posts": 18,
            "matched_comments": 114,
            "distinct_pseudonyms": 119,
            "threads": 87,
        },
        "PER-BEHAVIOR-ADVOCATE-001": {
            "matched_entities": 191,
            "matched_posts": 4,
            "matched_comments": 187,
            "distinct_pseudonyms": 183,
            "threads": 111,
        },
    }
    assert len(assignments) == 323
    assert {row["tag_id"] for row in assignments} == SOURCE_TAG_IDS
    assert all(row["source_stratum"] != "unknown" for row in assignments)
    assert Counter(row["source_stratum"] for row in assignments) == {
        "tencent_production_primary": 11,
        "tencent_isolated_staging": 67,
        "tencent_v2_search_hydrated": 114,
        HYDRATION_SOURCE_STRATUM: 68,
        "imported_archive": 63,
    }
    assert all(
        row["avatar"]["synthetic"] is True
        and row["avatar"]["real_user_image"] is False
        and row["avatar"]["derived_from_reddit_media"] is False
        for row in personas["personas"]
    )


def test_v2_overlay_is_byte_stable_and_avatar_bound(tmp_path: Path) -> None:
    insights_dir = _build_v2_insights_fixture(tmp_path / "insights")
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_manifest = _build_overlay(first, insights_dir)
    second_manifest = _build_overlay(second, insights_dir)

    assert first_manifest == second_manifest
    assert (first / "manifest.json").read_bytes() == (second / "manifest.json").read_bytes()
    for relative_path in first_manifest["files"]:
        assert (first / relative_path).read_bytes() == (second / relative_path).read_bytes()
    assert {
        name
        for name, metadata in first_manifest["files"].items()
        if metadata["media_type"] == "image/svg+xml"
    } == {
        "assets/persona-work-scenario.svg",
        "assets/persona-explicit-advocate.svg",
    }


def test_v2_rejects_insights_without_a_configured_promoted_signal(
    tmp_path: Path,
) -> None:
    insights_dir = _build_v2_insights_fixture(tmp_path / "insights")
    insights_path = insights_dir / "insights.json"
    insights = json.loads(insights_path.read_text(encoding="utf-8"))
    insights["signals"] = [
        row for row in insights["signals"] if row["tag_id"] != "L0-GEN-103"
    ]
    _canonical_write(insights_path, insights)
    manifest_path = insights_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["insights.json"] = _file_contract(insights_path)
    _canonical_write(manifest_path, manifest)

    with pytest.raises(
        ValueError,
        match="persona source tag is missing from insights: L0-GEN-103",
    ):
        build(BASE_SNAPSHOT, insights_dir, PERSONA_CONFIG, AVATAR_DIR)


def test_v2_requires_hydration_source_stratum_in_priority(tmp_path: Path) -> None:
    insights_dir = _build_v2_insights_fixture(tmp_path / "insights")
    config = json.loads(PERSONA_CONFIG.read_text(encoding="utf-8"))
    config["source_priority"].remove(HYDRATION_SOURCE_STRATUM)
    config_path = tmp_path / "personas-config-without-hydration.json"
    _canonical_write(config_path, config)

    with pytest.raises(
        ValueError,
        match="persona evidence source stratum is not governed",
    ):
        build(BASE_SNAPSHOT, insights_dir, config_path, AVATAR_DIR)


def test_validator_rejects_rehashed_unknown_source_stratum(tmp_path: Path) -> None:
    insights_dir = _build_v2_insights_fixture(tmp_path / "insights")
    output_dir = tmp_path / "personas"
    _build_overlay(output_dir, insights_dir)
    tags = json.loads((output_dir / "persona-tags.json").read_text(encoding="utf-8"))
    tags["assignments"][0]["source_stratum"] = "unknown"
    _rewrite_output_json(output_dir, "persona-tags.json", tags)

    with pytest.raises(
        ValueError,
        match="persona assignment source stratum is not governed",
    ):
        validate(
            output_dir,
            BASE_SNAPSHOT,
            insights_dir,
            PERSONA_CONFIG,
            AVATAR_DIR,
        )
