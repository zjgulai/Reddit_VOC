from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from reddit_voc.risk_report_contracts import (
    build_contract_bundle,
    required_report_windows,
)
from scripts.build_reddit_site_insights import write_contract_bundle
from scripts.validate_reddit_site_analytics import validate


AS_OF = datetime(2026, 7, 15, 0, 30, tzinfo=timezone.utc)
BASE_VERSION = "reddit_voc_site_snapshot_analytics_fixture"
INSIGHTS_VERSION = "reddit_voc_insights_analytics_fixture"
REPORTS_VERSION = "reddit_voc_reports_analytics_fixture"


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )


def _file_record(path: Path) -> dict[str, Any]:
    return {
        "bytes": path.stat().st_size,
        "sha256": sha256(path.read_bytes()).hexdigest(),
    }


def _product_binding() -> dict[str, Any]:
    return {
        "brand_id": "momcozy",
        "category": {
            "id": "breast_pump",
            "name_en": "Breast Pump",
            "name_cn": "吸奶器",
        },
        "product_family": {
            "id": "m9-mobile-flow",
            "name_en": "M9 Mobile Flow",
            "name_cn": "M9 产品族",
        },
        "exact_spu": {"spu_id": "SPU000168", "spu_name": "M9 Mobile Flow"},
        "binding_level": "spu_exact",
        "match_type": "strong_name",
        "matched_alias": "M9 Mobile Flow",
        "governance_status": "exact_spu_approved",
        "governance_reason": None,
    }


def _post(post_id: str, created: str, *, sentiment: str = "negative") -> dict[str, Any]:
    return {
        "post_id": post_id,
        "reddit_id": post_id,
        "event_created_at_utc": created,
        "created_at_utc": created,
        "subreddit": "NewParents",
        "permalink": f"https://www.reddit.com/r/NewParents/comments/{post_id}/fixture/",
        "comment_coverage_status": "thread_complete",
        "brand_binding": "momcozy_sentence_bound",
        "mentioned_brands": ["Momcozy"],
        "product_bindings": [_product_binding()],
        "analysis": {
            "sentiment_label": sentiment,
            "topic": "product_experience",
            "pain_points": ["reliability"] if sentiment == "negative" else [],
        },
        "tagging": {
            "matches": [
                {
                    "tag_id": "risk-fixture",
                    "evidence_keywords": ["failure"],
                }
            ]
        },
        "title": "Momcozy M9 failure",
        "content": "Momcozy failure needs review.",
    }


def _comment(comment_id: str, post_id: str, created: str) -> dict[str, Any]:
    return {
        "comment_id": comment_id,
        "reddit_id": comment_id,
        "post_id": post_id,
        "event_created_at_utc": created,
        "created_at_utc": created,
        "include_in_voc_metrics": True,
        "brand_binding": "momcozy_sentence_bound",
        "mentioned_brands": ["Momcozy"],
        "product_bindings": [_product_binding()],
        "analysis": {
            "sentiment_label": "negative",
            "topic": "product_experience",
            "pain_points": ["reliability"],
        },
        "tagging": {
            "matches": [
                {
                    "tag_id": "risk-fixture",
                    "evidence_keywords": ["failure"],
                }
            ]
        },
        "body": "Momcozy failure happened again.",
    }


def _competitor_post(post_id: str, created: str, *, sentiment: str) -> dict[str, Any]:
    return {
        "post_id": post_id,
        "reddit_id": post_id,
        "event_created_at_utc": created,
        "created_at_utc": created,
        "subreddit": "NewParents",
        "permalink": f"https://www.reddit.com/r/NewParents/comments/{post_id}/fixture/",
        "comment_coverage_status": "thread_complete",
        "brand_binding": "competitor_sentence_bound",
        "mentioned_brands": ["Elvie"],
        "product_bindings": [],
        "analysis": {
            "sentiment_label": sentiment,
            "topic": "product_experience",
            "pain_points": ["reliability"] if sentiment == "negative" else [],
        },
        "tagging": {
            "matches": [
                {
                    "tag_id": "risk-fixture",
                    "evidence_keywords": ["failure"],
                }
            ]
        },
        "title": "Elvie Stride failure",
        "content": "Elvie failure needs review.",
    }


def _dictionary() -> dict[str, Any]:
    return {
        "schema_version": "reddit_voc_tag_dictionary_v1",
        "dictionary_version": "analytics-fixture-dictionary-v1",
        "dictionary_sha256": "d" * 64,
        "rules": [
            {
                "tag_id": "risk-fixture",
                "name_cn": "关键故障",
                "name_en": "Critical failure",
                "theme": "产品风险",
                "sentiment": "negative",
                "default_priority": "P1",
                "risk_level": "高风险",
                "problem_type": "产品性能",
                "intent_type": "投诉",
                "story_lines": "核心体验问题",
                "business_impact": "品牌信任",
                "dept_owner": "产品中心",
                "biz_action": "核验故障证据",
            },
            {
                "tag_id": "held-fixture",
                "name_cn": "待复核",
                "name_en": "Held fixture",
                "theme": "服务风险",
                "sentiment": "negative",
                "default_priority": "P2",
                "risk_level": "中风险",
                "problem_type": "售后服务",
                "intent_type": "投诉",
                "story_lines": "服务恢复",
                "business_impact": "品牌信任",
                "dept_owner": "客户服务部",
                "biz_action": "复核证据",
            },
        ],
    }


def _coverage_ledger() -> dict[str, Any]:
    return {
        "schema_version": "reddit_voc_period_coverage_ledger_v1",
        "ledger_version": "analytics-fixture-coverage-v1",
        "windows": [
            {
                "start_utc": window.start_utc.isoformat(),
                "end_utc": window.end_utc.isoformat(),
                "is_closed": True,
                "query_profile_version": "fixture-query-v1",
                "source_set_version": "fixture-source-v1",
                "tag_dictionary_version": "analytics-fixture-dictionary-v1",
                "product_catalog_version": "fixture-products-v1",
                "event_time_coverage": "partial",
                "search_has_next_truncates_window": True,
                "hydration_policy_version": "fixture-hydration-v1",
                "comment_coverage_status": "observed_first_page",
                "schema_drift": False,
                "id_conflicts": 0,
                "source_missing": False,
                "recent_partition": False,
            }
            for window in required_report_windows(AS_OF)
        ],
    }


def _build_fixture(
    root: Path, *, base_schema: str = "reddit_voc_site_snapshot_manifest_v1"
) -> tuple[Path, Path, Path]:
    base_dir = root / "base"
    base_dir.mkdir(parents=True)
    posts = [
        _post("current", "2026-07-14T00:00:00+00:00"),
        _post("previous", "2026-07-13T00:00:00+00:00", sentiment="neutral"),
        _post("monthly", "2026-06-15T00:00:00+00:00"),
        _competitor_post(
            "competitor-current",
            "2026-07-14T01:00:00+00:00",
            sentiment="negative",
        ),
        _competitor_post(
            "competitor-previous",
            "2026-07-13T01:00:00+00:00",
            sentiment="neutral",
        ),
    ]
    comments = [_comment("t1_current", "current", "2026-07-14T00:05:00+00:00")]
    dictionary = _dictionary()
    documents = {
        "posts.json": posts,
        "comments.json": comments,
        "quarantine.json": [],
        "tag-dictionary.json": dictionary,
    }
    for name, value in documents.items():
        _write_json(base_dir / name, value)
    base_manifest = {
        "schema_version": base_schema,
        "dataset_version": BASE_VERSION,
        "generated_at_utc": AS_OF.isoformat(),
        "delivery_mode": "versioned_static_snapshot",
        "canonical_counts": {
            "posts": len(posts),
            "linked_comments": len(comments),
            "stored_comments": len(comments),
            "quarantined_comments": 0,
        },
        "semantic_boundaries": {
            "market_share_supported": False,
            "roi_supported": False,
            "response_time_supported": False,
        },
        "files": {
            name: _file_record(base_dir / name) for name in documents
        },
        "production_unchanged": True,
        "provider_call": False,
        "live_send": False,
    }
    if base_schema == "reddit_voc_site_snapshot_manifest_v2":
        base_manifest["all_checks_passed"] = True
    _write_json(base_dir / "manifest.json", base_manifest)
    base_identity = {
        "dataset_version": BASE_VERSION,
        "manifest_sha256": sha256((base_dir / "manifest.json").read_bytes()).hexdigest(),
        "generated_at_utc": AS_OF.isoformat(),
        "quarantined_comments": 0,
        "source_cutoffs": {},
    }
    semantic = {
        "governance_version": "analytics-fixture-semantic-v1",
        "promoted_tag_ids": ["risk-fixture"],
        "held_tag_ids": ["held-fixture"],
    }
    risk_policy = {
        "schema_version": "reddit_voc_risk_theme_gate_policy_v1",
        "policy_version": "analytics-fixture-risk-policy-v1",
        "status": "frozen",
        "minimum_observed_entities": 1,
        "minimum_distinct_posts": 1,
        "minimum_communities": 1,
        "minimum_brand_binding_rate": 0.5,
    }
    bundle = build_contract_bundle(
        posts=posts,
        comments=comments,
        tag_dictionary=dictionary,
        semantic_governance=semantic,
        base_identity=base_identity,
        insights_dataset_version=INSIGHTS_VERSION,
        reports_dataset_version=REPORTS_VERSION,
        as_of_utc=AS_OF,
        coverage_ledger=_coverage_ledger(),
        risk_gate_policy=risk_policy,
    )
    analytics_root = root / "analytics"
    write_contract_bundle(
        analytics_root,
        bundle=bundle,
        base_identity=base_identity,
        tag_dictionary=dictionary,
        semantic_governance=semantic,
        risk_gate_policy=risk_policy,
        as_of_utc=AS_OF,
    )
    return (
        base_dir,
        analytics_root / INSIGHTS_VERSION,
        analytics_root / REPORTS_VERSION,
    )


def _rehash_payload(directory: Path, relative_path: str) -> None:
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][relative_path] = _file_record(directory / relative_path)
    _write_json(manifest_path, manifest)


def _refresh_insights_lineage(insights_dir: Path, reports_dir: Path) -> None:
    _rehash_payload(insights_dir, "insights.json")
    reports_manifest_path = reports_dir / "manifest.json"
    reports_manifest = json.loads(reports_manifest_path.read_text(encoding="utf-8"))
    reports_manifest["insights_manifest_sha256"] = sha256(
        (insights_dir / "manifest.json").read_bytes()
    ).hexdigest()
    _write_json(reports_manifest_path, reports_manifest)


def _validate(paths: tuple[Path, Path, Path]) -> dict[str, Any]:
    return validate(
        *paths,
        expected_insights_version=INSIGHTS_VERSION,
        expected_reports_version=REPORTS_VERSION,
    )


def test_valid_candidate_passes_without_mutating_inputs(tmp_path: Path) -> None:
    paths = _build_fixture(tmp_path)
    before = {
        path: sha256(path.read_bytes()).hexdigest()
        for directory in paths
        for path in directory.rglob("*.json")
    }

    receipt = _validate(paths)

    after = {path: sha256(path.read_bytes()).hexdigest() for path in before}
    assert before == after
    assert receipt["status"] == "passed_release_candidate"
    assert receipt["release_candidate"] is True
    assert receipt["counts"]["reports"] == 6
    assert all(receipt["checks"].values())
    assert receipt["provider_call"] is False
    assert receipt["database_write"] is False
    assert receipt["deploy"] is False


def test_validated_base_manifest_v2_is_supported(tmp_path: Path) -> None:
    paths = _build_fixture(
        tmp_path, base_schema="reddit_voc_site_snapshot_manifest_v2"
    )
    receipt = _validate(paths)
    assert receipt["status"] == "passed_release_candidate"


def test_rejects_file_hash_tampering_before_semantic_checks(tmp_path: Path) -> None:
    paths = _build_fixture(tmp_path)
    _, insights_dir, _ = paths
    insights_path = insights_dir / "insights.json"
    insights_path.write_text(
        insights_path.read_text(encoding="utf-8") + " ", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="byte mismatch: insights.json"):
        _validate(paths)


def test_rejects_public_mode_private_analytics_file(tmp_path: Path) -> None:
    paths = _build_fixture(tmp_path)
    _, insights_dir, _ = paths
    (insights_dir / "insights.json").chmod(0o644)

    with pytest.raises(ValueError, match="insights file mode mismatch"):
        _validate(paths)


def test_rejects_rehashed_unknown_risk_evidence_id(tmp_path: Path) -> None:
    paths = _build_fixture(tmp_path)
    _, insights_dir, reports_dir = paths
    insights_path = insights_dir / "insights.json"
    insights = json.loads(insights_path.read_text(encoding="utf-8"))
    insights["risk_command_center"]["risk_themes"][0]["evidence_refs"][0][
        "entity_id"
    ] = "missing-evidence"
    _write_json(insights_path, insights)
    _refresh_insights_lineage(insights_dir, reports_dir)

    with pytest.raises(ValueError, match="risk evidence ID mismatch"):
        _validate(paths)


def test_rejects_rehashed_product_scope_drift(tmp_path: Path) -> None:
    paths = _build_fixture(tmp_path)
    _, insights_dir, reports_dir = paths
    insights_path = insights_dir / "insights.json"
    insights = json.loads(insights_path.read_text(encoding="utf-8"))
    insights["product_analysis"]["category"][0]["scope_id"] = "invented-category"
    _write_json(insights_path, insights)
    _refresh_insights_lineage(insights_dir, reports_dir)

    with pytest.raises(ValueError, match="product scope set mismatch"):
        _validate(paths)


def test_rejects_rehashed_comparison_without_reason_codes(tmp_path: Path) -> None:
    paths = _build_fixture(tmp_path)
    _, _, reports_dir = paths
    relative_path = "current/daily.json"
    report_path = reports_dir / relative_path
    report = json.loads(report_path.read_text(encoding="utf-8"))
    comparison = report["period_comparisons"]["previous_period"]["post"]
    assert comparison["comparison_status"] == "provisional_observed_sample"
    comparison["reason_codes"] = []
    _write_json(report_path, report)
    _rehash_payload(reports_dir, relative_path)

    with pytest.raises(ValueError, match="provisional comparison lacks reasons"):
        _validate(paths)


def test_rejects_rehashed_competitor_observed_count_tampering(tmp_path: Path) -> None:
    paths = _build_fixture(tmp_path)
    _, _, reports_dir = paths
    relative_path = "current/daily.json"
    report_path = reports_dir / relative_path
    report = json.loads(report_path.read_text(encoding="utf-8"))
    competitor = report["competitor_context"][0]
    assert competitor["brand_id"] == "elvie"
    competitor["observed_count"]["post"]["value"] += 1
    _write_json(report_path, report)
    _rehash_payload(reports_dir, relative_path)

    with pytest.raises(ValueError, match="competitor metric mismatch"):
        _validate(paths)


def test_rejects_rehashed_sov_capability_enablement(tmp_path: Path) -> None:
    paths = _build_fixture(tmp_path)
    _, _, reports_dir = paths
    relative_path = "current/daily.json"
    report_path = reports_dir / relative_path
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["capabilities"]["unsupported"].remove("sov")
    report["capabilities"]["supported"].append("sov")
    _write_json(report_path, report)
    _rehash_payload(reports_dir, relative_path)

    with pytest.raises(ValueError, match="forbidden capability enabled"):
        _validate(paths)


def test_cli_writes_only_requested_receipt(tmp_path: Path) -> None:
    paths = _build_fixture(tmp_path)
    base_dir, insights_dir, reports_dir = paths
    receipt_path = tmp_path / "receipts" / "analytics.json"
    before = {
        path: sha256(path.read_bytes()).hexdigest()
        for directory in paths
        for path in directory.rglob("*.json")
    }

    command = [
            sys.executable,
            str(
                Path(__file__).resolve().parents[1]
                / "scripts"
                / "validate_reddit_site_analytics.py"
            ),
            "--base-dir",
            str(base_dir),
            "--insights-dir",
            str(insights_dir),
            "--reports-dir",
            str(reports_dir),
            "--expected-insights-version",
            INSIGHTS_VERSION,
            "--expected-reports-version",
            REPORTS_VERSION,
            "--receipt",
            str(receipt_path),
        ]
    subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )

    assert receipt_path.is_file()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "passed_release_candidate"
    before_receipt = receipt_path.read_bytes()
    second = subprocess.run(
        command, check=True, capture_output=True, text=True
    )
    assert json.loads(second.stdout)["receipt_write_status"] == "no_change"
    assert receipt_path.read_bytes() == before_receipt
    assert before == {
        path: sha256(path.read_bytes()).hexdigest() for path in before
    }
