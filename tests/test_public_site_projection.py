from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Iterator

from scripts.build_public_site_projection import build_projection, project_posts


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "ref/UI/momcozy-reddit-workbench/public/data/reddit-voc"
BASE = DATA / "reddit_voc_site_snapshot_20260714_v1"
INSIGHTS = DATA / "reddit_voc_insights_20260714_v1/public"
REPORTS = DATA / "reddit_voc_reports_20260714_v1/public"
FORBIDDEN_KEYS = {
    "biz_action",
    "business_impact",
    "dataset_id",
    "default_priority",
    "dept_owner",
    "dictionary_default_priority",
    "run_id",
    "source_occurrences",
    "suggested_action",
    "strategy_package",
}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def walk(value: Any, location: str = "$") -> Iterator[tuple[str, str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_location = f"{location}.{key}"
            yield child_location, key, child
            yield from walk(child, child_location)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, f"{location}[{index}]")


def assert_file_contract(root: Path, relative_path: str, contract: dict[str, Any]) -> None:
    payload = (root / relative_path).read_bytes()
    assert contract == {"bytes": len(payload), "sha256": sha256(payload).hexdigest()}


def test_public_base_projection_is_minimized_and_self_consistent() -> None:
    source_manifest = load(BASE / "manifest.json")
    manifest = load(BASE / "manifest-public.json")
    aggregates = load(BASE / "aggregates-public.json")
    posts = load(BASE / "posts-public.json")
    comments = load(BASE / "comments-public.json")

    assert manifest["privacy"]["author_display"] == "suppressed"
    assert set(manifest["files"]) == {
        "aggregates-public.json",
        "posts-public.json",
        "comments-public.json",
        "tag-dictionary-public.json",
    }
    for relative_path, contract in manifest["files"].items():
        assert_file_contract(BASE, relative_path, contract)
    assert len(posts) == manifest["canonical_counts"]["posts"]
    assert len(comments) == manifest["canonical_counts"]["linked_comments"]
    assert manifest["canonical_counts"] == source_manifest["canonical_counts"]
    assert all(row["author_pseudonym"] is None for row in [*posts, *comments])
    assert set(aggregates["tagging"]) == {
        "dictionary_version",
        "posts_with_rule_tags",
        "comments_with_rule_tags",
        "posts_with_aspect_tags",
        "comments_with_aspect_tags",
        "top_tags",
    }


def test_all_public_json_excludes_internal_strategy_and_collection_metadata() -> None:
    paths = [
        BASE / "manifest-public.json",
        BASE / "aggregates-public.json",
        BASE / "posts-public.json",
        BASE / "comments-public.json",
        BASE / "tag-dictionary-public.json",
        *sorted(INSIGHTS.rglob("*.json")),
        *sorted(REPORTS.rglob("*.json")),
    ]
    for path in paths:
        for location, key, value in walk(load(path)):
            assert key not in FORBIDDEN_KEYS, f"{path}:{location}"
            if key == "author_pseudonym":
                assert value is None, f"{path}:{location}"


def test_public_insights_and_reports_manifests_bind_exact_projected_files() -> None:
    for root in (INSIGHTS, REPORTS):
        manifest = load(root / "manifest.json")
        assert manifest["projection"]["audience"] == "public_ui"
        for relative_path, contract in manifest["files"].items():
            assert_file_contract(root, relative_path, contract)

    audit = load(INSIGHTS / "semantic-audit.json")
    for tag in audit["tags"]:
        for sample in tag["samples"]:
            assert set(sample) == {"audit_id", "review"}
            assert set(sample["review"]) == {"label_verdict", "taxonomy_fit", "reason_code"}


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _contract(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {"bytes": len(payload), "sha256": sha256(payload).hexdigest()}


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _analysis() -> dict[str, Any]:
    return {
        "analysis_version": "fixture-v2",
        "sentiment_label": "negative",
        "sentiment_score": -0.5,
        "topic": "product_experience",
        "severity": "high",
        "confidence": 0.9,
        "pain_points": ["reliability"],
        "provider_call": False,
    }


def _tagging() -> dict[str, Any]:
    return {
        "dictionary_version": "fixture-dictionary-v2",
        "tag_ids": ["risk-p0"],
        "aspect_tag_ids": ["risk-p0"],
        "brand_tag_ids": [],
        "semantic_validation_status": "governed_explicit",
        "matches": [
            {
                "tag_id": "risk-p0",
                "tag_scope": "aspect",
                "tag_sentiment": "negative",
                "evidence_keywords": ["failure"],
                "evidence_count": 1,
                "match_strength": "strong",
                "validation_status": "promoted",
            }
        ],
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


def _base_aggregates() -> dict[str, Any]:
    return {
        "schema_version": "reddit_voc_site_aggregates_v1",
        "headline": {"unique_posts": 1, "linked_comments": 1},
        "date_range": {"posts": ["2026-07-01", "2026-07-01"], "comments": ["2026-07-01", "2026-07-01"]},
        "post_sentiment": {"negative": 1, "neutral": 0, "positive": 0},
        "comment_sentiment": {"negative": 1, "neutral": 0, "positive": 0},
        "post_topics": {"product_experience": 1},
        "pain_points": {"reliability": 2},
        "subreddit_posts": {"NewParents": 1},
        "subreddit_comments": {"NewParents": 1},
        "monthly_posts": {"2026-07": 1},
        "brand_sample_mentions": [{"brand": "Momcozy", "posts": 1}],
        "coverage_grade": {"full": 1},
        "count_completeness_status": {"complete": 1},
        "parent_link_status": {"linked": 1},
        "metric_notes": {"counts": "observed entities"},
        "tagging": {
            "dictionary_version": "fixture-dictionary-v2",
            "posts_with_rule_tags": 1,
            "comments_with_rule_tags": 1,
            "posts_with_aspect_tags": 1,
            "comments_with_aspect_tags": 1,
            "top_tags": [],
        },
    }


def _write_source_manifest(
    directory: Path,
    *,
    dataset_version: str,
    file_names: list[str],
    extra: dict[str, Any],
) -> None:
    manifest = {
        "schema_version": "fixture_manifest_v1",
        "dataset_version": dataset_version,
        "files": {name: _contract(directory / name) for name in file_names},
        **extra,
    }
    _write(directory / "manifest.json", manifest)


def _report_payload(reports_version: str, period: str) -> dict[str, Any]:
    return {
        "schema_version": "reddit_voc_report_v1",
        "contract_extension": "reddit_voc_risk_report_v2",
        "identity": {
            "dataset_version": reports_version,
            "report_id": f"fixture-{period}",
            "period": period,
            "window_mode": "calendar_closed",
            "display_name": period,
        },
        "window": {"coverage_status": "complete", "comparison_status": "comparable"},
        "headline": {"posts": 1, "voc_comments": 1},
        "observed_timeline": [{"bucket": "2026-07-01", "observed_entities": 2}],
        "communities": [{"subreddit": "NewParents", "observed_entities": 2}],
        "topics": [{"topic": "product_experience", "observed_entities": 2}],
        "pain_points": [{"pain_point": "reliability", "observed_entities": 2}],
        "brand_mentions": [{"brand": "Momcozy", "observed_entities": 2}],
        "promoted_signals": [],
        "attention_items": [],
        "evidence_posts": [],
        "capabilities": {"supported": ["observed_entity_counts"]},
        "interpretation_boundaries": {"market_share_supported": False},
        "runtime_boundaries": {"provider_call": False},
        "momcozy_metrics": {"risk_theme_count": 1},
        "risk_themes": [
            {
                "tag_id": "risk-p0",
                "risk_level": "high",
                "dictionary_default_priority": "P0",
                "effective_priority": "P0",
                "suggested_action": "PRIVATE_ACTION_SENTINEL",
                "evidence_refs": [
                    {
                        "entity_type": "post",
                        "entity_id": "post-1",
                        "post_id": "post-1",
                        "event_created_at_utc": "2026-07-01T00:00:00+00:00",
                        "permalink": "https://example.invalid/private",
                    }
                ],
            }
        ],
        "product_analysis": {"category": [{"scope_id": "breast_pump", "observed_entities": 2}]},
        "product_period_analysis": {
            "schema_version": "reddit_voc_product_period_metrics_v1",
            "period": period,
            "decision_subject": "momcozy",
            "scope_order": ["category", "product_family", "spu_exact"],
            "metric_definitions": {
                "observed_count": "momcozy_brand_bound_observed_entities_by_entity_type"
            },
            "category": [],
            "product_family": [],
            "spu_exact": [],
            "interpretation_boundary": "posts_and_comments_are_separate",
        },
        "competitor_context": {"brands": []},
        "period_comparisons": {"previous_period": {"post": {"absolute_delta": 1}}},
        "observed_count_comparisons": {
            "previous_period": {"post": {}, "comment": {}},
            "year_over_year": {"post": {}, "comment": {}},
        },
        "trend": {"direction": "up"},
        "title": "PRIVATE_REPORT_TITLE_SENTINEL",
        "body": "PRIVATE_REPORT_BODY_SENTINEL",
        "author": "PRIVATE_REPORT_AUTHOR_SENTINEL",
    }


def _build_v2_fixture(root: Path) -> tuple[str, str, str, str]:
    base_version = "reddit_voc_site_snapshot_fixture_v2"
    insights_version = "reddit_voc_insights_fixture_v2"
    reports_version = "reddit_voc_reports_fixture_v2"
    personas_version = "reddit_voc_personas_fixture_v2"
    base = root / base_version
    insights = root / insights_version
    reports = root / reports_version
    personas = root / personas_version

    post = {
        "post_id": "post-1",
        "reddit_id": "t3_post-1",
        "title": "public post title",
        "content": "public post content",
        "subreddit": "NewParents",
        "permalink": "https://example.invalid/post-1",
        "created_at_utc": "2026-07-01T00:00:00+00:00",
        "event_created_at_utc": "2026-07-01T00:00:00+00:00",
        "score": 2,
        "upvote_ratio": 0.75,
        "num_comments_reported": 1,
        "linked_comment_count": 1,
        "structural_coverage_grade": "full",
        "count_completeness_status": "complete",
        "comment_coverage_status": "thread_complete",
        "mentioned_brands": ["Momcozy"],
        "brand_binding": "momcozy_sentence_bound",
        "product_bindings": [_product_binding()],
        "evidence_id": "post:post-1",
        "analysis": _analysis(),
        "tagging": _tagging(),
        "author_pseudonym": "PRIVATE_AUTHOR_SENTINEL",
        "collection_buckets": ["PRIVATE_COLLECTION_SENTINEL"],
        "source_kinds": ["PRIVATE_SOURCE_SENTINEL"],
        "source_occurrences": ["PRIVATE_RUN_SENTINEL"],
    }
    comment = {
        "comment_id": "comment-1",
        "reddit_id": "t1_comment-1",
        "post_id": "post-1",
        "parent_id": "t3_post-1",
        "body": "public comment body",
        "created_at_utc": "2026-07-01T00:01:00+00:00",
        "event_created_at_utc": "2026-07-01T00:01:00+00:00",
        "score": 1,
        "depth": 0,
        "deleted_or_removed": False,
        "is_bot": False,
        "include_in_voc_metrics": True,
        "mentioned_brands": ["Momcozy"],
        "brand_binding": "momcozy_sentence_bound",
        "product_bindings": [_product_binding()],
        "evidence_id": "comment:comment-1",
        "analysis": _analysis(),
        "tagging": _tagging(),
        "author_pseudonym": "PRIVATE_COMMENT_AUTHOR_SENTINEL",
        "source_occurrences": ["PRIVATE_COMMENT_RUN_SENTINEL"],
    }
    tag_dictionary = {
        "schema_version": "reddit_voc_tag_dictionary_snapshot_v1",
        "dictionary_version": "fixture-dictionary-v2",
        "dictionary_sha256": "a" * 64,
        "rules": [
            {
                "tag_id": "risk-p0",
                "name_cn": "可靠性风险",
                "name_en": "Reliability risk",
                "theme": "product",
                "sentiment": "negative",
                "tag_scope": "aspect",
            }
        ],
    }
    for name, payload in (
        ("aggregates.json", _base_aggregates()),
        ("posts.json", [post]),
        ("comments.json", [comment]),
        ("quarantine.json", []),
        ("tag-dictionary.json", tag_dictionary),
    ):
        _write(base / name, payload)
    _write_source_manifest(
        base,
        dataset_version=base_version,
        file_names=[
            "aggregates.json",
            "posts.json",
            "comments.json",
            "quarantine.json",
            "tag-dictionary.json",
        ],
        extra={
            "generated_at_utc": "2026-07-15T00:00:00+00:00",
            "delivery_mode": "versioned_static_snapshot",
            "all_checks_passed": True,
            "production_unchanged": True,
            "provider_call": False,
            "live_send": False,
            "canonical_counts": {
                "posts": 1,
                "linked_comments": 1,
                "stored_comments": 1,
                "quarantined_comments": 0,
            },
            "source_boundaries": {"private_run": "PRIVATE_SOURCE_BOUNDARY"},
            "fusion_accounting": {"run_id": "PRIVATE_RUN_ID"},
            "semantic_boundaries": {"product_category_analysis_supported": True},
            "tagging": {"product_entity_resolution": {"status": "resolved"}},
        },
    )

    insights_payload = {
        "schema_version": "reddit_voc_insights_v2",
        "dataset_version": insights_version,
        "base_dataset_version": base_version,
        "generated_at_utc": "2026-07-15T00:00:00+00:00",
        "headline": {"status": "available"},
        "signals": [],
        "reference_dimensions": {},
        "held_tags": [],
        "interpretation_boundaries": {"market_share_supported": False},
        "boundaries": {"provider_call": False},
        "legacy_compatibility": {"status": "not_supplied"},
        "input_contract": {"status": "passed"},
        "risk_command_center": {
            "risk_themes": [
                {
                    "tag_id": "risk-p0",
                    "risk_level": "high",
                    "dictionary_default_priority": "P0",
                    "effective_priority": "P0",
                    "biz_action": "PRIVATE_BIZ_ACTION_SENTINEL",
                    "business_impact": "PRIVATE_IMPACT_SENTINEL",
                    "dept_owner": "PRIVATE_OWNER_SENTINEL",
                    "strategy_package": "PRIVATE_STRATEGY_SENTINEL",
                    "suggested_action": "PRIVATE_SUGGESTION_SENTINEL",
                    "evidence_refs": [
                        {
                            "entity_type": "comment",
                            "entity_id": "comment-1",
                            "post_id": "post-1",
                            "event_created_at_utc": "2026-07-01T00:01:00+00:00",
                            "subreddit": "NewParents",
                            "permalink": "https://example.invalid/private-ref",
                        }
                    ],
                }
            ]
        },
        "product_analysis": {"category": [{"scope_id": "breast_pump", "observed_entities": 2}]},
        "report_booklets": {"dataset_version": reports_version},
        "control_evidence": {
            "evidence_level": "offline_snapshot_contract_build",
            "source_cutoffs": {"private": "PRIVATE_SOURCE_CUTOFF"},
        },
        "title": "PRIVATE_INSIGHTS_TITLE_SENTINEL",
        "content": "PRIVATE_INSIGHTS_BODY_SENTINEL",
        "author_pseudonym": "PRIVATE_INSIGHTS_AUTHOR_SENTINEL",
    }
    semantic_audit = {
        "schema_version": "reddit_voc_tag_semantic_audit_v2",
        "audit_version": "fixture-governance-v2",
        "base_dataset_version": base_version,
        "base_manifest_sha256": "b" * 64,
        "dictionary_version": "fixture-dictionary-v2",
        "dictionary_sha256": "a" * 64,
        "summary": {
            "promoted_tags": 1,
            "held_tags": 0,
            "promoted_tag_ids": ["risk-p0"],
            "held_tag_ids": [],
            "status": "governance_projection_no_raw_samples",
        },
        "boundaries": {"raw_review_samples_included": False},
    }
    _write(insights / "insights.json", insights_payload)
    _write(insights / "semantic-audit.json", semantic_audit)
    _write_source_manifest(
        insights,
        dataset_version=insights_version,
        file_names=["insights.json", "semantic-audit.json"],
        extra={"delivery_mode": "versioned_static_insights_overlay"},
    )

    report_index: dict[str, Any] = {
        "schema_version": "reddit_voc_report_index_v1",
        "contract_extension": "reddit_voc_report_index_v2",
        "dataset_version": reports_version,
        "as_of_utc": "2026-07-15T00:00:00+00:00",
        "timezone": "Asia/Shanghai",
        "current": {},
        "archive": {},
    }
    report_paths: list[str] = []
    for collection in ("current", "archive"):
        for period in ("daily", "weekly", "monthly"):
            path = f"{collection}/{period}.json"
            report_paths.append(path)
            report_index[collection][period] = {
                "path": path,
                "period": period,
                "posts": 1,
                "voc_comments": 1,
            }
            _write(reports / path, _report_payload(reports_version, period))
    _write(reports / "report-index.json", report_index)
    _write_source_manifest(
        reports,
        dataset_version=reports_version,
        file_names=["report-index.json", *report_paths],
        extra={"delivery_mode": "versioned_static_reports"},
    )

    personas_document = {
        "schema_version": "reddit_voc_personas_v1",
        "dataset_version": personas_version,
        "generated_at_utc": "2026-07-15T00:00:00+00:00",
        "persona_count": 1,
        "personas": [
            {
                "persona_id": "PER-FIXTURE-001",
                "name_cn": "内容证据 cohort",
                "avatar": {
                    "asset_path": "assets/persona-fixture.svg",
                    "synthetic": True,
                    "real_user_image": False,
                },
            }
        ],
        "interpretation_boundaries": {
            "identity_claim": False,
            "author_level_personas": False,
        },
    }
    persona_tags_document = {
        "schema_version": "reddit_voc_persona_tags_v1",
        "dataset_version": personas_version,
        "grain": "content_entity",
        "assignment_count": 1,
        "assignments": [
            {
                "persona_id": "PER-FIXTURE-001",
                "entity_type": "comment",
                "entity_id": "comment-1",
                "post_id": "post-1",
                "evidence_id": "comment:comment-1",
            }
        ],
        "boundaries": {
            "author_level_personas": False,
            "public_author_identifiers": False,
        },
    }
    _write(personas / "personas.json", personas_document)
    _write(personas / "persona-tags.json", persona_tags_document)
    avatar = personas / "assets/persona-fixture.svg"
    avatar.parent.mkdir(parents=True, exist_ok=True)
    avatar.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8" '
        'viewBox="0 0 8 8"><circle cx="4" cy="4" r="4"/></svg>\n',
        encoding="utf-8",
    )
    persona_manifest = {
        "schema_version": "reddit_voc_personas_manifest_v1",
        "dataset_version": personas_version,
        "delivery_mode": "versioned_static_evidence_personas",
        "generated_at_utc": "2026-07-15T00:00:00+00:00",
        "base_dataset_version": base_version,
        "base_manifest_sha256": sha256((base / "manifest.json").read_bytes()).hexdigest(),
        "insights_dataset_version": insights_version,
        "insights_manifest_sha256": sha256(
            (insights / "manifest.json").read_bytes()
        ).hexdigest(),
        "persona_count": 1,
        "assignment_count": 1,
        "boundaries": {
            "author_level_personas": False,
            "derived_from_reddit_media": False,
            "identity_claim": False,
            "public_author_identifiers": False,
            "real_user_image": False,
        },
        "files": {
            "personas.json": _contract(personas / "personas.json"),
            "persona-tags.json": _contract(personas / "persona-tags.json"),
            "assets/persona-fixture.svg": _contract(avatar),
        },
    }
    _write(personas / "manifest.json", persona_manifest)
    return base_version, insights_version, reports_version, personas_version


def test_synthetic_v2_projection_is_dynamic_minimized_and_fail_closed() -> None:
    with TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory)
        (
            base_version,
            insights_version,
            reports_version,
            personas_version,
        ) = _build_v2_fixture(root)
        output_root = root / "candidate"
        source_state = {
            version: _tree_bytes(root / version)
            for version in (
                base_version,
                insights_version,
                reports_version,
                personas_version,
            )
        }
        result = build_projection(
            root,
            output_root=output_root,
            base_version=base_version,
            insights_version=insights_version,
            reports_version=reports_version,
            personas_version=personas_version,
        )

        assert result["status"] == "created"
        assert result["reused"] is False
        assert source_state == {
            version: _tree_bytes(root / version)
            for version in source_state
        }
        assert not any(
            path.name.endswith("-public.json")
            for version in source_state
            for path in (root / version).rglob("*")
        )
        public_data_root = output_root / "data/reddit-voc"
        base = public_data_root / base_version
        public_post = load(base / "posts-public.json")[0]
        public_comment = load(base / "comments-public.json")[0]
        public_manifest = load(base / "manifest-public.json")
        for required in (
            "product_bindings",
            "brand_binding",
            "event_created_at_utc",
            "comment_coverage_status",
        ):
            assert required in public_post
        for required in ("product_bindings", "brand_binding", "event_created_at_utc"):
            assert required in public_comment
        for forbidden in (
            "author_pseudonym",
            "collection_buckets",
            "source_kinds",
            "source_occurrences",
        ):
            assert forbidden not in public_post
            assert forbidden not in public_comment
        assert "source_boundaries" not in public_manifest
        assert "fusion_accounting" not in public_manifest
        assert public_manifest["canonical_counts"]["posts"] == len(
            load(base / "posts-public.json")
        )

        public_insights_root = public_data_root / insights_version / "public"
        public_reports_root = public_data_root / reports_version / "public"
        public_personas_root = public_data_root / personas_version
        public_insights = load(public_insights_root / "insights.json")
        theme = public_insights["risk_command_center"]["risk_themes"][0]
        assert theme["risk_level"] == "high"
        assert theme["effective_priority"] == "P0"
        assert theme["evidence_refs"] == [
            {
                "entity_type": "comment",
                "entity_id": "comment-1",
                "post_id": "post-1",
            }
        ]
        assert public_insights["product_analysis"]["category"][0]["observed_entities"] == 2
        public_daily_report = load(public_reports_root / "current/daily.json")
        assert set(public_daily_report["observed_count_comparisons"]) == {
            "previous_period",
            "year_over_year",
        }
        assert public_daily_report["product_period_analysis"]["scope_order"] == [
            "category",
            "product_family",
            "spu_exact",
        ]

        public_paths = [
            public_insights_root / "manifest.json",
            public_insights_root / "insights.json",
            public_insights_root / "semantic-audit.json",
            *sorted(public_reports_root.rglob("*.json")),
        ]
        for path in public_paths:
            serialized = path.read_text(encoding="utf-8")
            for sentinel in (
                "PRIVATE_BIZ_ACTION_SENTINEL",
                "PRIVATE_IMPACT_SENTINEL",
                "PRIVATE_OWNER_SENTINEL",
                "PRIVATE_STRATEGY_SENTINEL",
                "PRIVATE_SUGGESTION_SENTINEL",
                "PRIVATE_INSIGHTS_TITLE_SENTINEL",
                "PRIVATE_INSIGHTS_BODY_SENTINEL",
                "PRIVATE_INSIGHTS_AUTHOR_SENTINEL",
                "PRIVATE_REPORT_TITLE_SENTINEL",
                "PRIVATE_REPORT_BODY_SENTINEL",
                "PRIVATE_REPORT_AUTHOR_SENTINEL",
            ):
                assert sentinel not in serialized
            for location, key, _value in walk(load(path)):
                assert key not in FORBIDDEN_KEYS, f"{path}:{location}"

        for public_root in (public_insights_root, public_reports_root):
            manifest = load(public_root / "manifest.json")
            for relative_path, contract in manifest["files"].items():
                assert_file_contract(public_root, relative_path, contract)
        assert load(public_personas_root / "personas.json")["persona_count"] == 1
        persona_manifest = load(public_personas_root / "manifest.json")
        for relative_path, contract in persona_manifest["files"].items():
            assert_file_contract(public_personas_root, relative_path, contract)
        assert not (output_root / "current-release.json").exists()


def test_risk_report_v2_projection_rejects_missing_business_fields(
    tmp_path: Path,
) -> None:
    for missing_field in (
        "observed_count_comparisons",
        "product_period_analysis",
    ):
        source_root = tmp_path / f"source-{missing_field}"
        (
            base_version,
            insights_version,
            reports_version,
            personas_version,
        ) = _build_v2_fixture(source_root)
        report_path = source_root / reports_version / "current/daily.json"
        report = load(report_path)
        report.pop(missing_field)
        _write(report_path, report)
        manifest_path = source_root / reports_version / "manifest.json"
        manifest = load(manifest_path)
        manifest["files"]["current/daily.json"] = _contract(report_path)
        _write(manifest_path, manifest)

        output_root = tmp_path / f"candidate-{missing_field}"
        try:
            build_projection(
                source_root,
                output_root=output_root,
                base_version=base_version,
                insights_version=insights_version,
                reports_version=reports_version,
                personas_version=personas_version,
            )
        except ValueError as exc:
            assert missing_field in str(exc)
        else:
            raise AssertionError(f"missing {missing_field} was not rejected")
        assert not output_root.exists()
        assert not list(tmp_path.glob(f".{output_root.name}.staging-*"))


def test_v2_report_index_rejects_report_downgrade(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    (
        base_version,
        insights_version,
        reports_version,
        personas_version,
    ) = _build_v2_fixture(source_root)
    report_path = source_root / reports_version / "current/daily.json"
    report = load(report_path)
    report.pop("contract_extension")
    _write(report_path, report)
    manifest_path = source_root / reports_version / "manifest.json"
    manifest = load(manifest_path)
    manifest["files"]["current/daily.json"] = _contract(report_path)
    _write(manifest_path, manifest)

    output_root = tmp_path / "candidate"
    try:
        build_projection(
            source_root,
            output_root=output_root,
            base_version=base_version,
            insights_version=insights_version,
            reports_version=reports_version,
            personas_version=personas_version,
        )
    except ValueError as exc:
        assert "required risk report v2 contract" in str(exc)
    else:
        raise AssertionError("report index v2 allowed a downgraded report payload")
    assert not output_root.exists()


def test_projection_reuses_exact_candidate_and_rejects_collision(tmp_path: Path) -> None:
    (
        base_version,
        insights_version,
        reports_version,
        personas_version,
    ) = _build_v2_fixture(tmp_path / "source")
    source_root = tmp_path / "source"
    output_root = tmp_path / "candidate"
    arguments = {
        "output_root": output_root,
        "base_version": base_version,
        "insights_version": insights_version,
        "reports_version": reports_version,
        "personas_version": personas_version,
    }

    first = build_projection(source_root, **arguments)
    manifest = (
        output_root
        / "data/reddit-voc"
        / base_version
        / "manifest-public.json"
    )
    first_mtime = manifest.stat().st_mtime_ns
    first_tree = _tree_bytes(output_root)

    second = build_projection(source_root, **arguments)
    assert first["status"] == "created"
    assert second["status"] == "no_change"
    assert second["reused"] is True
    assert manifest.stat().st_mtime_ns == first_mtime
    assert _tree_bytes(output_root) == first_tree

    manifest.write_bytes(manifest.read_bytes() + b"\n")
    try:
        build_projection(source_root, **arguments)
    except FileExistsError as exc:
        assert "output_root_collision" in str(exc)
    else:
        raise AssertionError("a differing immutable candidate was not rejected")
    assert manifest.read_bytes().endswith(b"\n\n")
    assert not list(tmp_path.glob(".candidate.staging-*"))


def test_late_persona_privacy_failure_leaves_no_partial_candidate_or_current(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    (
        base_version,
        insights_version,
        reports_version,
        personas_version,
    ) = _build_v2_fixture(source_root)
    personas_root = source_root / personas_version
    personas = load(personas_root / "personas.json")
    personas["personas"][0]["username"] = "PRIVATE_PERSONA_AUTHOR_SENTINEL"
    _write(personas_root / "personas.json", personas)
    manifest = load(personas_root / "manifest.json")
    manifest["files"]["personas.json"] = _contract(personas_root / "personas.json")
    _write(personas_root / "manifest.json", manifest)

    current = tmp_path / "current-release.json"
    current.write_bytes(b'{"release_id":"existing"}\n')
    current_before = current.read_bytes()
    output_root = tmp_path / "candidate"

    try:
        build_projection(
            source_root,
            output_root=output_root,
            base_version=base_version,
            insights_version=insights_version,
            reports_version=reports_version,
            personas_version=personas_version,
        )
    except ValueError as exc:
        assert "private fields" in str(exc)
    else:
        raise AssertionError("private persona fields were not rejected")

    assert not output_root.exists()
    assert current.read_bytes() == current_before
    assert not list(tmp_path.glob(".candidate.staging-*"))


def test_governed_base_projection_rejects_missing_required_event_time() -> None:
    row = {
        "post_id": "post-1",
        "reddit_id": "t3_post-1",
        "title": "title",
        "content": "content",
        "subreddit": "NewParents",
        "permalink": "https://example.invalid/post-1",
        "created_at_utc": "2026-07-01T00:00:00+00:00",
        "score": 1,
        "upvote_ratio": 1.0,
        "num_comments_reported": 0,
        "linked_comment_count": 0,
        "structural_coverage_grade": "full",
        "count_completeness_status": "complete",
        "comment_coverage_status": "thread_complete",
        "mentioned_brands": ["Momcozy"],
        "brand_binding": "momcozy_sentence_bound",
        "product_bindings": [],
        "evidence_id": "post:post-1",
        "analysis": _analysis(),
        "tagging": _tagging(),
    }
    try:
        project_posts([row], governed_fields=True)
    except ValueError as exc:
        assert "event_created_at_utc" in str(exc)
    else:
        raise AssertionError("missing governed event time was not rejected")
