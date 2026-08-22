from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast
import unittest

from reddit_voc.risk_report_contracts import (
    InputContractError,
    build_contract_bundle,
    build_period_windows,
)
from scripts.build_reddit_site_insights import (
    materialise_coverage_ledger,
    normalise_semantic_governance,
    write_contract_bundle,
)


AS_OF = datetime(2026, 7, 15, 0, 30, tzinfo=timezone.utc)


def _product_binding(
    *,
    category_id: str = "breast_pump",
    family_id: str = "m9-mobile-flow",
    spu_id: str | None = "SPU000168",
    governance_status: str = "exact_spu_approved",
) -> dict[str, Any]:
    exact_spu = (
        {"spu_id": spu_id, "spu_name": "M9 Mobile Flow"}
        if spu_id is not None
        else None
    )
    return {
        "brand_id": "momcozy",
        "category": {
            "id": category_id,
            "name_en": "Breast Pump",
            "name_cn": "吸奶器",
        },
        "product_family": {
            "id": family_id,
            "name_en": "M9 Mobile Flow",
            "name_cn": "M9 产品族",
        },
        "exact_spu": exact_spu,
        "binding_level": "spu_exact" if exact_spu else "product_family",
        "match_type": "strong_name",
        "matched_alias": "M9 Mobile Flow",
        "governance_status": governance_status,
        "governance_reason": None,
    }


def _post(
    post_id: str,
    event_created_at_utc: str,
    *,
    sentiment: str = "negative",
    tag_ids: tuple[str, ...] = ("risk-p0",),
    brand_binding: str = "momcozy_sentence_bound",
    brand_names: tuple[str, ...] = ("Momcozy",),
    products: tuple[dict[str, object], ...] | None = None,
    subreddit: str = "NewParents",
    title: str = "PRIVATE_TITLE_SENTINEL",
    content: str = "PRIVATE_BODY_SENTINEL",
) -> dict[str, object]:
    return {
        "post_id": post_id,
        "reddit_id": post_id,
        "event_created_at_utc": event_created_at_utc,
        "subreddit": subreddit,
        "permalink": f"https://reddit.com/{post_id}",
        "comment_coverage_status": "thread_complete",
        "brand_binding": brand_binding,
        "mentioned_brands": list(brand_names),
        "product_bindings": list(
            products if products is not None else (_product_binding(),)
        ),
        "analysis": {
            "sentiment_label": sentiment,
            "topic": "product_experience",
            "pain_points": ["reliability"] if sentiment == "negative" else [],
        },
        "tagging": {
            "matches": [
                {"tag_id": tag_id, "evidence_keywords": ["failure"]}
                for tag_id in tag_ids
            ],
        },
        # These sentinels must never enter the analytical contract.
        "title": title,
        "content": content,
        "author_pseudonym": "PRIVATE_AUTHOR_SENTINEL",
    }


def _comment(
    comment_id: str,
    post_id: str,
    event_created_at_utc: str,
    *,
    sentiment: str = "negative",
    tag_ids: tuple[str, ...] = ("risk-p0",),
    products: tuple[dict[str, object], ...] | None = None,
) -> dict[str, object]:
    return {
        "comment_id": comment_id,
        "reddit_id": comment_id,
        "post_id": post_id,
        "event_created_at_utc": event_created_at_utc,
        "include_in_voc_metrics": True,
        "brand_binding": "momcozy_sentence_bound",
        "mentioned_brands": ["Momcozy"],
        "product_bindings": list(products or (_product_binding(),)),
        "analysis": {
            "sentiment_label": sentiment,
            "topic": "product_experience",
            "pain_points": ["reliability"] if sentiment == "negative" else [],
        },
        "tagging": {
            "matches": [
                {"tag_id": tag_id, "evidence_keywords": ["failure"]}
                for tag_id in tag_ids
            ],
        },
        "body": "PRIVATE_COMMENT_SENTINEL",
        "author_pseudonym": "PRIVATE_COMMENT_AUTHOR_SENTINEL",
    }


TAG_DICTIONARY: dict[str, object] = {
    "schema_version": "reddit_voc_tag_dictionary_v1",
    "dictionary_version": "dim_tag_v6.3_final",
    "dictionary_sha256": "a" * 64,
    "rules": [
        {
            "tag_id": "risk-p0",
            "name_cn": "关键故障",
            "name_en": "Critical failure",
            "theme": "产品风险",
            "sentiment": "negative",
            "default_priority": "P0",
            "risk_level": "高风险",
            "problem_type": "产品性能",
            "intent_type": "投诉",
            "story_lines": "核心体验问题",
            "business_impact": "品牌信任",
            "dept_owner": "产品中心",
            "biz_action": "核验故障证据并复核产品批次",
        },
        {
            "tag_id": "risk-p1-held",
            "name_cn": "待复核风险",
            "name_en": "Held risk",
            "theme": "服务风险",
            "sentiment": "negative",
            "default_priority": "P1",
            "risk_level": "中高风险",
            "problem_type": "售后服务",
            "intent_type": "投诉",
            "story_lines": "服务恢复问题",
            "business_impact": "品牌信任",
            "dept_owner": "客户服务部",
            "biz_action": "复核服务失败证据",
        },
    ],
}


SEMANTIC_GOVERNANCE: dict[str, object] = {
    "governance_version": "semantic-review-2026-07-15",
    "promoted_tag_ids": ["risk-p0"],
    "held_tag_ids": ["risk-p1-held"],
}


RISK_GATE_POLICY: dict[str, object] = {
    "schema_version": "reddit_voc_risk_theme_gate_policy_v1",
    "policy_version": "risk-theme-gate-reviewed-v1",
    "status": "frozen",
    "minimum_observed_entities": 1,
    "minimum_distinct_posts": 1,
    "minimum_communities": 1,
    "minimum_brand_binding_rate": 0.5,
}


BASE_IDENTITY: dict[str, object] = {
    "dataset_version": "reddit_voc_site_snapshot_20260715_rc1",
    "manifest_sha256": "b" * 64,
    "generated_at_utc": "2026-07-15T00:20:00+00:00",
    "source_cutoffs": {
        "search_semantic_cutoff_utc": "2026-07-15T04:15:20.214394Z",
        "comment_hydration_cutoff_utc": "2026-07-15T04:19:56.303367Z",
        "reply_hydration_cutoff_utc": "2026-07-15T04:28:28.244835Z",
    },
}


def _window_coverage(window: object, *, comment_status: str = "thread_complete") -> dict[str, object]:
    start = getattr(window, "start_utc")
    end = getattr(window, "end_utc")
    return {
        "start_utc": start.isoformat(),
        "end_utc": end.isoformat(),
        "is_closed": True,
        "query_profile_version": "reddit-v2-search-profile-v1",
        "source_set_version": "rc-source-union-v1",
        "tag_dictionary_version": "dim_tag_v6.3_final",
        "product_catalog_version": "momcozy-product-entity-ledger-2026-07-15.v1",
        "event_time_coverage": "complete",
        "search_has_next_truncates_window": False,
        "hydration_policy_version": "v2-first-and-replies-v1",
        "comment_coverage_status": comment_status,
        "schema_drift": False,
        "id_conflicts": 0,
        "source_missing": False,
        "recent_partition": False,
    }


def _coverage_ledger(*windows: object, comment_status: str = "thread_complete") -> dict[str, object]:
    rows: dict[tuple[str, str], dict[str, object]] = {}
    for window in windows:
        row = _window_coverage(window, comment_status=comment_status)
        rows[(str(row["start_utc"]), str(row["end_utc"]))] = row
    return {
        "schema_version": "reddit_voc_period_coverage_ledger_v1",
        "ledger_version": "coverage-ledger-test-v1",
        "windows": list(rows.values()),
    }


def _build(
    posts: list[dict[str, object]],
    comments: list[dict[str, object]] | None = None,
    *,
    coverage_ledger: dict[str, object] | None = None,
    risk_gate_policy: dict[str, object] | None = RISK_GATE_POLICY,
    legacy_insights: dict[str, object] | None = None,
) -> dict[str, Any]:
    return build_contract_bundle(
        posts=posts,
        comments=comments or [],
        tag_dictionary=TAG_DICTIONARY,
        semantic_governance=SEMANTIC_GOVERNANCE,
        base_identity=BASE_IDENTITY,
        insights_dataset_version="reddit_voc_insights_20260715_rc1",
        reports_dataset_version="reddit_voc_reports_20260715_rc1",
        as_of_utc=AS_OF,
        coverage_ledger=coverage_ledger,
        risk_gate_policy=risk_gate_policy,
        legacy_insights=legacy_insights,
    )


class PeriodWindowContractTests(unittest.TestCase):
    def test_closed_periods_use_asia_shanghai_half_open_windows(self) -> None:
        windows = build_period_windows(AS_OF)

        self.assertEqual(
            windows["daily"].current.start_utc.isoformat(),
            "2026-07-13T16:00:00+00:00",
        )
        self.assertEqual(
            windows["daily"].current.end_utc.isoformat(),
            "2026-07-14T16:00:00+00:00",
        )
        self.assertEqual(
            windows["weekly"].current.start_utc.isoformat(),
            "2026-07-05T16:00:00+00:00",
        )
        self.assertEqual(
            windows["weekly"].current.end_utc.isoformat(),
            "2026-07-12T16:00:00+00:00",
        )
        self.assertEqual(
            windows["monthly"].current.start_utc.isoformat(),
            "2026-05-31T16:00:00+00:00",
        )
        self.assertEqual(
            windows["monthly"].current.end_utc.isoformat(),
            "2026-06-30T16:00:00+00:00",
        )


class RiskAndReportContractTests(unittest.TestCase):
    def test_competitor_context_has_current_dimensions_comparisons_and_no_fake_taxonomy(self) -> None:
        windows = build_period_windows(AS_OF)
        daily = windows["daily"]
        posts = [
            _post(
                "elvie-current-negative",
                "2026-07-14T00:00:00Z",
                brand_binding="competitor_sentence_bound",
                brand_names=("Elvie",),
                products=(),
                sentiment="negative",
                subreddit="breastfeeding",
            ),
            _post(
                "elvie-current-positive",
                "2026-07-14T01:00:00Z",
                brand_binding="competitor_sentence_bound",
                brand_names=("Elvie",),
                products=(),
                sentiment="positive",
                subreddit="NewParents",
            ),
            _post(
                "elvie-previous",
                "2026-07-13T00:00:00Z",
                brand_binding="competitor_sentence_bound",
                brand_names=("Elvie",),
                products=(),
                sentiment="positive",
            ),
            _post(
                "elvie-yoy",
                "2025-07-14T00:00:00Z",
                brand_binding="competitor_sentence_bound",
                brand_names=("Elvie",),
                products=(),
                sentiment="negative",
            ),
        ]
        ledger = _coverage_ledger(
            daily.current,
            daily.previous,
            daily.year_over_year,
            *daily.trend,
        )
        report = _build(posts, coverage_ledger=ledger)["reports"]["current"]["daily"]
        competitor = next(
            row for row in report["competitor_context"] if row["brand_id"] == "elvie"
        )

        self.assertEqual(competitor["observed_count"]["post"]["value"], 2)
        self.assertEqual(
            competitor["negative_evidence_share"]["post"]["value"], 0.5
        )
        self.assertEqual(competitor["top_topics"][0]["observed_entities"], 2)
        self.assertEqual(len(competitor["top_communities"]), 2)
        self.assertEqual(
            competitor["product_taxonomy"]["status"],
            "unavailable_no_competitor_taxonomy",
        )
        self.assertEqual(
            competitor["product_scope_ids"],
            {"category": [], "product_family": [], "spu_exact": []},
        )
        pop = competitor["period_comparisons"]["previous_period"]["observed_count"]["post"]
        self.assertEqual(pop["current"]["value"], 2)
        self.assertEqual(pop["baseline"]["value"], 1)
        self.assertEqual(pop["absolute_delta"], 1.0)
        self.assertFalse(competitor["trend"]["direction_claim_supported"])
        self.assertTrue(pop["direction_claim_supported"])

    def test_missing_snapshot_fields_fail_closed_with_exact_paths(self) -> None:
        invalid = {
            "post_id": "missing-contract-fields",
            "created_at_utc": "2026-07-14T00:00:00Z",
            "analysis": {"sentiment_label": "negative"},
            "tagging": {"matches": []},
        }

        with self.assertRaises(InputContractError) as caught:
            _build([invalid])

        missing = caught.exception.missing_fields
        self.assertIn("posts[0].event_created_at_utc", missing)
        self.assertIn("posts[0].brand_binding", missing)
        self.assertIn("posts[0].mentioned_brands", missing)
        self.assertIn("posts[0].product_bindings", missing)
        self.assertIn("posts[0].comment_coverage_status", missing)

    def test_tag_grain_sentence_binding_is_not_inferred_from_entity_review_alone(self) -> None:
        posts = [
            _post(
                "same-sentence",
                "2026-07-14T00:00:00Z",
                brand_binding="momcozy_entity_reviewed",
                title="Momcozy has a critical failure.",
                content="",
            ),
            _post(
                "different-sentence",
                "2026-07-14T01:00:00Z",
                brand_binding="momcozy_entity_reviewed",
                title="Momcozy is one option. The failure concerns another device.",
                content="",
            ),
        ]

        theme = _build(posts)["insights"]["risk_command_center"]["risk_themes"][0]

        self.assertEqual(theme["brand_binding_counts"]["momcozy_sentence_bound"], 1)
        self.assertEqual(theme["brand_binding_counts"]["momcozy_entity_reviewed"], 1)

    def test_theme_evidence_refs_are_private_unique_owned_limited_and_stable(self) -> None:
        posts = [
            _post(
                f"p-{index:02d}",
                f"2026-07-{14 - index // 12:02d}T{index % 12:02d}:00:00Z",
            )
            for index in range(25)
        ]

        theme = _build(posts)["insights"]["risk_command_center"]["risk_themes"][0]
        refs = theme["evidence_refs"]

        self.assertEqual(len(refs), 20)
        self.assertEqual(theme["evidence_ref_count_total"], 25)
        self.assertTrue(theme["evidence_refs_truncated"])
        keys = {(row["entity_type"], row["entity_id"]) for row in refs}
        self.assertEqual(len(keys), len(refs))
        self.assertTrue(all(row["entity_id"].startswith("p-") for row in refs))
        self.assertEqual(
            [row["event_created_at_utc"] for row in refs],
            sorted(
                (row["event_created_at_utc"] for row in refs),
                reverse=True,
            ),
        )
        serialized = json.dumps(refs, ensure_ascii=False)
        for forbidden in ("title", "body", "content", "author"):
            self.assertNotIn(forbidden, serialized.casefold())

    def test_risk_priority_is_gate_then_p0_to_p3_or_insufficient(self) -> None:
        posts = [
            _post(
                "p-promoted",
                "2026-07-14T00:00:00Z",
                tag_ids=("risk-p0",),
            ),
            _post(
                "p-held",
                "2026-07-14T01:00:00Z",
                tag_ids=("risk-p1-held",),
            ),
        ]

        bundle = _build(posts)
        insights = bundle["insights"]
        self.assertIsInstance(insights, dict)
        assert isinstance(insights, dict)
        command = insights["risk_command_center"]
        self.assertIsInstance(command, dict)
        assert isinstance(command, dict)
        themes = {
            row["risk_theme_id"]: row
            for row in command["risk_themes"]
        }

        self.assertEqual(themes["risk-p0"]["effective_priority"], "P0")
        self.assertEqual(themes["risk-p0"]["evidence_gate"]["status"], "passed")
        self.assertEqual(
            themes["risk-p1-held"]["effective_priority"], "insufficient"
        )
        self.assertIn(
            "semantic_tag_not_promoted",
            themes["risk-p1-held"]["evidence_gate"]["reason_codes"],
        )
        self.assertEqual(
            command["primary_kpis"]["high_priority_risk_themes"]["value"],
            1,
        )
        serialized = json.dumps(bundle, ensure_ascii=False)
        self.assertNotIn("priority_score", serialized)
        self.assertNotIn("risk_score", serialized)

    def test_unfrozen_theme_threshold_keeps_priorities_insufficient(self) -> None:
        bundle = _build(
            [_post("p1", "2026-07-14T00:00:00Z")],
            risk_gate_policy=None,
        )
        command = bundle["insights"]["risk_command_center"]
        theme = command["risk_themes"][0]

        self.assertEqual(theme["effective_priority"], "insufficient")
        self.assertIn(
            "risk_theme_gate_policy_missing",
            theme["evidence_gate"]["reason_codes"],
        )
        self.assertIsNone(
            command["primary_kpis"]["high_priority_risk_themes"]["value"]
        )

    def test_unknown_subreddit_does_not_inflate_risk_community_breadth(self) -> None:
        policy = {**RISK_GATE_POLICY, "minimum_communities": 2}
        bundle = _build(
            [
                _post("known", "2026-07-14T00:00:00Z", subreddit="NewParents"),
                _post("unknown", "2026-07-14T01:00:00Z", subreddit="unknown"),
            ],
            risk_gate_policy=policy,
        )

        theme = bundle["reports"]["current"]["daily"]["risk_themes"][0]

        self.assertEqual(theme["communities"], 1)
        self.assertEqual(theme["effective_priority"], "insufficient")
        self.assertIn(
            "minimum_communities_not_met",
            theme["evidence_gate"]["reason_codes"],
        )

    def test_product_analysis_has_three_levels_and_only_publishable_exact_spu(self) -> None:
        family_only = _product_binding(
            family_id="m5-smart",
            spu_id=None,
            governance_status="family_only",
        )
        taxonomy_blocked = _product_binding(
            category_id="baby_monitor",
            family_id="bm03-video-monitor",
            spu_id=None,
            governance_status="taxonomy_blocked",
        )
        category_only: dict[str, object] = {
            "brand_id": "momcozy",
            "category": {
                "id": "bottle_washer",
                "name_en": "Bottle Washer",
                "name_cn": "洗奶瓶机",
            },
            "product_family": None,
            "exact_spu": None,
            "binding_level": "category",
            "match_type": "category_context",
            "matched_alias": "bottle washer",
            "governance_status": "category_only",
            "governance_reason": "category_context_without_family_alias",
        }
        posts = [
            _post("p-exact", "2026-07-14T00:00:00Z"),
            _post(
                "p-family",
                "2026-07-14T01:00:00Z",
                products=(family_only,),
            ),
            _post(
                "p-blocked",
                "2026-07-14T02:00:00Z",
                products=(taxonomy_blocked,),
            ),
            _post(
                "p-category",
                "2026-07-14T03:00:00Z",
                products=(category_only,),
            ),
        ]

        analysis = _build(posts)["insights"]["product_analysis"]

        self.assertEqual(
            [row["scope_id"] for row in analysis["spu_exact"]],
            ["SPU000168"],
        )
        self.assertEqual(
            {row["scope_id"] for row in analysis["product_family"]},
            {"m9-mobile-flow", "m5-smart", "bm03-video-monitor"},
        )
        self.assertEqual(
            {row["scope_id"] for row in analysis["category"]},
            {"breast_pump", "baby_monitor", "bottle_washer"},
        )
        self.assertEqual(
            analysis["coverage"]["taxonomy_blocked_bindings"],
            1,
        )

    def test_period_comparisons_keep_posts_and_comments_separate(self) -> None:
        windows = build_period_windows(AS_OF)
        daily = windows["daily"]
        posts = [
            _post("current-neg", "2026-07-14T00:00:00Z", sentiment="negative"),
            _post("current-pos", "2026-07-14T01:00:00Z", sentiment="positive"),
            _post("previous-neg", "2026-07-13T00:00:00Z", sentiment="negative"),
            _post("previous-pos-1", "2026-07-13T01:00:00Z", sentiment="positive"),
            _post("previous-pos-2", "2026-07-13T02:00:00Z", sentiment="positive"),
            _post("previous-pos-3", "2026-07-13T03:00:00Z", sentiment="positive"),
        ]
        comments = [
            _comment("c-current", "current-neg", "2026-07-14T02:00:00Z"),
            _comment(
                "c-previous",
                "previous-neg",
                "2026-07-13T04:00:00Z",
                sentiment="positive",
            ),
        ]
        ledger = _coverage_ledger(daily.current, daily.previous)

        report = _build(
            posts,
            comments,
            coverage_ledger=ledger,
        )["reports"]["current"]["daily"]

        previous_post = report["period_comparisons"]["previous_period"]["post"]
        self.assertEqual(previous_post["comparison_status"], "comparable")
        self.assertEqual(previous_post["current"]["value"], 0.5)
        self.assertEqual(previous_post["baseline"]["value"], 0.25)
        self.assertEqual(previous_post["absolute_delta"], 0.25)
        self.assertEqual(previous_post["relative_delta"], 1.0)
        self.assertEqual(
            report["momcozy_metrics"]["negative_evidence_share"]["post"]["denominator"],
            2,
        )
        self.assertEqual(
            report["momcozy_metrics"]["negative_evidence_share"]["comment"]["denominator"],
            1,
        )
        self.assertFalse(
            report["momcozy_metrics"]["negative_evidence_share"]["combined"]["supported"]
        )

    def test_observed_volume_has_current_pop_yoy_and_trend_by_entity_type(self) -> None:
        windows = build_period_windows(AS_OF)
        daily = windows["daily"]
        posts = [
            _post("current-1", "2026-07-14T00:00:00Z"),
            _post("current-2", "2026-07-14T01:00:00Z"),
            _post("previous", "2026-07-13T00:00:00Z"),
            _post("yoy", "2025-07-14T00:00:00Z"),
        ]
        comments = [
            _comment("current-c1", "current-1", "2026-07-14T02:00:00Z"),
            _comment("previous-c1", "previous", "2026-07-13T02:00:00Z"),
            _comment("previous-c2", "previous", "2026-07-13T03:00:00Z"),
            _comment("yoy-c1", "yoy", "2025-07-14T02:00:00Z"),
        ]
        ledger = _coverage_ledger(
            daily.current,
            daily.previous,
            daily.year_over_year,
            *daily.trend,
        )

        report = _build(
            posts,
            comments,
            coverage_ledger=ledger,
        )["reports"]["current"]["daily"]

        current = report["momcozy_metrics"]["observed_count"]
        self.assertEqual(current["post"]["value"], 2)
        self.assertEqual(current["comment"]["value"], 1)
        self.assertFalse(current["combined"]["supported"])
        pop_post = report["observed_count_comparisons"]["previous_period"]["post"]
        self.assertEqual(pop_post["current"]["value"], 2)
        self.assertEqual(pop_post["baseline"]["value"], 1)
        self.assertEqual(pop_post["absolute_delta"], 1.0)
        yoy_comment = report["observed_count_comparisons"]["year_over_year"]["comment"]
        self.assertEqual(yoy_comment["current"]["value"], 1)
        self.assertEqual(yoy_comment["baseline"]["value"], 1)
        latest_trend = report["trend"]["points"][-1]
        self.assertEqual(latest_trend["observed_count"]["post"]["value"], 2)
        self.assertEqual(
            latest_trend["observed_count_change_from_previous"]["comment"]["absolute_delta"],
            -1.0,
        )

    def test_product_period_metrics_include_volume_share_pop_yoy_and_trend(self) -> None:
        windows = build_period_windows(AS_OF)
        daily = windows["daily"]
        posts = [
            _post("current-neg", "2026-07-14T00:00:00Z", sentiment="negative"),
            _post("current-pos", "2026-07-14T01:00:00Z", sentiment="positive"),
            _post("previous-neg", "2026-07-13T00:00:00Z", sentiment="negative"),
            _post("yoy-pos", "2025-07-14T00:00:00Z", sentiment="positive"),
        ]
        ledger = _coverage_ledger(
            daily.current,
            daily.previous,
            daily.year_over_year,
            *daily.trend,
        )

        report = _build(posts, coverage_ledger=ledger)["reports"]["current"]["daily"]
        product = report["product_period_analysis"]
        category = next(
            row for row in product["category"] if row["scope_id"] == "breast_pump"
        )

        self.assertEqual(category["current"]["post"]["observed_count"]["value"], 2)
        self.assertEqual(
            category["current"]["post"]["negative_evidence_share"]["value"],
            0.5,
        )
        self.assertEqual(category["current"]["comment"]["observed_count"]["value"], 0)
        pop = category["period_comparisons"]["previous_period"]["post"]
        self.assertEqual(pop["observed_count"]["absolute_delta"], 1.0)
        self.assertEqual(pop["negative_evidence_share"]["absolute_delta"], -0.5)
        yoy = category["period_comparisons"]["year_over_year"]["post"]
        self.assertEqual(yoy["observed_count"]["absolute_delta"], 1.0)
        self.assertEqual(yoy["negative_evidence_share"]["absolute_delta"], 0.5)
        latest = category["trend"]["points"][-1]
        self.assertEqual(latest["metrics"]["post"]["observed_count"]["value"], 2)
        self.assertEqual(
            latest["change_from_previous"]["post"]["observed_count"]["absolute_delta"],
            1.0,
        )

    def test_missing_yoy_baseline_is_null_with_reason_not_zero(self) -> None:
        windows = build_period_windows(AS_OF)
        daily = windows["daily"]
        ledger = _coverage_ledger(daily.current, daily.previous)
        report = _build(
            [_post("current", "2026-07-14T00:00:00Z")],
            coverage_ledger=ledger,
        )["reports"]["current"]["daily"]

        yoy = report["period_comparisons"]["year_over_year"]["post"]

        self.assertEqual(yoy["comparison_status"], "unavailable")
        self.assertIsNone(yoy["baseline"])
        self.assertIsNone(yoy["absolute_delta"])
        self.assertIsNone(yoy["relative_delta"])
        self.assertIn("baseline_coverage_missing", yoy["reason_codes"])

    def test_empty_baseline_under_partial_coverage_is_not_reported_as_zero(self) -> None:
        windows = build_period_windows(AS_OF)
        daily = windows["daily"]
        ledger = _coverage_ledger(daily.current, daily.previous)
        for row in cast(list[dict[str, object]], ledger["windows"]):
            row["event_time_coverage"] = "partial"
            row["search_has_next_truncates_window"] = True
        report = _build(
            [_post("current", "2026-07-14T00:00:00Z")],
            coverage_ledger=ledger,
        )["reports"]["current"]["daily"]

        previous = report["period_comparisons"]["previous_period"]["post"]

        self.assertEqual(previous["comparison_status"], "unavailable")
        self.assertIsNone(previous["baseline"])
        self.assertIn(
            "baseline_observation_absent_under_incomplete_coverage",
            previous["reason_codes"],
        )
        product = report["product_period_analysis"]["category"][0]
        product_previous = product["period_comparisons"]["previous_period"]["post"]
        self.assertIsNone(product_previous["observed_count"]["baseline"])
        self.assertIn(
            "baseline_observation_absent_under_incomplete_coverage",
            product_previous["observed_count"]["reason_codes"],
        )

    def test_partial_comment_depth_downgrades_comments_not_posts(self) -> None:
        windows = build_period_windows(AS_OF)
        daily = windows["daily"]
        ledger = _coverage_ledger(
            daily.current,
            daily.previous,
            comment_status="observed_first_page",
        )
        posts = [
            _post("current", "2026-07-14T00:00:00Z"),
            _post("previous", "2026-07-13T00:00:00Z"),
        ]
        report = _build(posts, coverage_ledger=ledger)["reports"]["current"]["daily"]

        comparison = report["period_comparisons"]["previous_period"]
        self.assertEqual(comparison["post"]["comparison_status"], "comparable")
        self.assertEqual(
            comparison["comment"]["comparison_status"],
            "provisional_observed_sample",
        )
        self.assertIn(
            "comment_coverage_not_thread_complete",
            comparison["comment"]["reason_codes"],
        )

    def test_legacy_insights_fields_are_preserved_and_new_sections_are_added(self) -> None:
        legacy = {
            "headline": {"audited_tags": 10},
            "signals": [{"tag_id": "legacy-promoted"}],
            "reference_dimensions": {"consumer_card": {"Caregiver": 12}},
            "held_tags": [{"tag_id": "legacy-held"}],
            "interpretation_boundaries": {"market_share_supported": False},
            "boundaries": {
                "scope": "legacy_top_10_review",
                "production_unchanged": True,
            },
        }

        insights = _build(
            [_post("p1", "2026-07-14T00:00:00Z")],
            legacy_insights=legacy,
        )["insights"]

        for field in (
            "headline",
            "signals",
            "reference_dimensions",
            "held_tags",
        ):
            self.assertEqual(insights[field], legacy[field])
        self.assertIn("risk_command_center", insights)
        self.assertIn("product_analysis", insights)
        self.assertIn("report_booklets", insights)
        self.assertIn("control_evidence", insights)
        self.assertEqual(
            insights["boundaries"]["scope"],
            "momcozy_risk_command_center_and_report_booklets",
        )

    def test_outputs_never_copy_source_body_title_or_author_and_c_is_read_only(self) -> None:
        bundle = _build(
            [_post("p1", "2026-07-14T00:00:00Z")],
            [_comment("c1", "p1", "2026-07-14T01:00:00Z")],
        )
        serialized = json.dumps(bundle, ensure_ascii=False)

        for sentinel in (
            "PRIVATE_TITLE_SENTINEL",
            "PRIVATE_BODY_SENTINEL",
            "PRIVATE_AUTHOR_SENTINEL",
            "PRIVATE_COMMENT_SENTINEL",
            "PRIVATE_COMMENT_AUTHOR_SENTINEL",
        ):
            self.assertNotIn(sentinel, serialized)
        control = bundle["insights"]["control_evidence"]
        self.assertTrue(control["recommendations_only"])
        self.assertFalse(control["action_completion_supported"])
        self.assertNotIn("completion_rate", control)
        self.assertNotIn("assigned", serialized)
        self.assertNotIn('"action_state":"closed"', serialized)
        self.assertNotIn('"roi":', serialized.casefold())


class RiskReportWriterTests(unittest.TestCase):
    def test_coverage_profile_materialises_all_report_windows_and_binds_base(self) -> None:
        profile: dict[str, object] = {
            "schema_version": "reddit_voc_period_coverage_profile_v1",
            "profile_version": "coverage-profile-test-v1",
            "applies_to_base_dataset_version": BASE_IDENTITY["dataset_version"],
            "applies_to_base_manifest_sha256": BASE_IDENTITY["manifest_sha256"],
            "query_profile_version": "fused-observed-source-v1",
            "source_set_version": BASE_IDENTITY["dataset_version"],
            "tag_dictionary_version": TAG_DICTIONARY["dictionary_version"],
            "tag_dictionary_sha256": TAG_DICTIONARY["dictionary_sha256"],
            "product_catalog_version": "momcozy-product-entity-ledger-v1",
            "product_catalog_sha256": "d" * 64,
            "event_time_coverage": "partial",
            "search_has_next_truncates_window": True,
            "hydration_policy_version": "mixed-hydration-v1",
            "comment_coverage_status": "mixed",
            "schema_drift": False,
            "id_conflicts": 0,
            "source_missing": False,
            "recent_partition": False,
        }

        ledger = materialise_coverage_ledger(
            profile,
            as_of_utc=AS_OF,
            base_identity=BASE_IDENTITY,
            tag_dictionary=TAG_DICTIONARY,
        )
        windows = cast(list[dict[str, object]], ledger["windows"])

        self.assertEqual(
            ledger["schema_version"], "reddit_voc_period_coverage_ledger_v1"
        )
        self.assertGreater(len(windows), 30)
        self.assertEqual(
            len(windows),
            len({(row["start_utc"], row["end_utc"]) for row in windows}),
        )
        self.assertTrue(all(row["event_time_coverage"] == "partial" for row in windows))
        with self.assertRaises(InputContractError):
            materialise_coverage_ledger(
                {**profile, "applies_to_base_manifest_sha256": "wrong"},
                as_of_utc=AS_OF,
                base_identity=BASE_IDENTITY,
                tag_dictionary=TAG_DICTIONARY,
            )

    def test_existing_insights_manifest_normalises_to_governance_contract(self) -> None:
        normalised = normalise_semantic_governance(
            {
                "dataset_version": "reddit_voc_insights_20260714_v1",
                "audit_summary": {
                    "promoted_tag_ids": ["risk-p0"],
                    "held_tag_ids": ["risk-p1-held"],
                },
            }
        )

        self.assertEqual(
            normalised,
            {
                "governance_version": "reddit_voc_insights_20260714_v1",
                "promoted_tag_ids": ["risk-p0"],
                "held_tag_ids": ["risk-p1-held"],
                "source_audit": {
                    "source_name": None,
                    "sha256": None,
                    "schema_version": None,
                    "audit_version": None,
                    "base_dataset_version": None,
                    "base_manifest_sha256": None,
                    "quality_gate": None,
                },
            },
        )

    def test_real_semantic_audit_summary_keeps_source_hash_provenance(self) -> None:
        normalised = normalise_semantic_governance(
            {
                "schema_version": "reddit_voc_tag_semantic_audit_v1",
                "audit_version": "semantic-audit-20260714-v1",
                "base_dataset_version": "reddit_voc_site_snapshot_20260714_v1",
                "base_manifest_sha256": "b" * 64,
                "quality_gate": "passed_with_scope_limits",
                "summary": {
                    "promoted_tag_ids": ["risk-p0"],
                    "held_tag_ids": ["risk-p1-held"],
                },
            },
            source_sha256="c" * 64,
            source_name="semantic-audit.json",
        )

        self.assertEqual(
            normalised["governance_version"], "semantic-audit-20260714-v1"
        )
        self.assertEqual(normalised["promoted_tag_ids"], ["risk-p0"])
        self.assertEqual(normalised["held_tag_ids"], ["risk-p1-held"])
        self.assertEqual(
            normalised["source_audit"],
            {
                "source_name": "semantic-audit.json",
                "sha256": "c" * 64,
                "schema_version": "reddit_voc_tag_semantic_audit_v1",
                "audit_version": "semantic-audit-20260714-v1",
                "base_dataset_version": "reddit_voc_site_snapshot_20260714_v1",
                "base_manifest_sha256": "b" * 64,
                "quality_gate": "passed_with_scope_limits",
            },
        )

    def test_writer_publishes_two_versioned_datasets_with_exact_manifests(self) -> None:
        bundle = _build([_post("p1", "2026-07-14T00:00:00Z")])
        with TemporaryDirectory() as temporary_directory:
            output_root = Path(temporary_directory) / "risk-release"
            receipt = write_contract_bundle(
                output_root,
                bundle=bundle,
                base_identity=BASE_IDENTITY,
                tag_dictionary=TAG_DICTIONARY,
                semantic_governance=SEMANTIC_GOVERNANCE,
                risk_gate_policy=RISK_GATE_POLICY,
                as_of_utc=AS_OF,
            )

            insights_dir = output_root / "reddit_voc_insights_20260715_rc1"
            reports_dir = output_root / "reddit_voc_reports_20260715_rc1"
            insights_manifest = json.loads(
                (insights_dir / "manifest.json").read_text(encoding="utf-8")
            )
            reports_manifest = json.loads(
                (reports_dir / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(output_root.stat().st_mode & 0o777, 0o700)
            self.assertTrue(
                all(
                    path.stat().st_mode & 0o777
                    == (0o700 if path.is_dir() else 0o600)
                    for path in output_root.rglob("*")
                )
            )
            self.assertEqual(
                set(insights_manifest["files"]),
                {"insights.json", "semantic-audit.json"},
            )
            self.assertEqual(reports_manifest["report_count"], 6)
            self.assertEqual(len(reports_manifest["files"]), 7)
            for directory, manifest in (
                (insights_dir, insights_manifest),
                (reports_dir, reports_manifest),
            ):
                for relative_path, contract in manifest["files"].items():
                    path = directory / relative_path
                    self.assertEqual(path.stat().st_size, contract["bytes"])
                    self.assertEqual(
                        sha256(path.read_bytes()).hexdigest(), contract["sha256"]
                    )
            self.assertEqual(receipt["report_count"], 6)
            self.assertTrue(receipt["production_unchanged"])
            self.assertFalse(receipt["provider_call"])
            with self.assertRaises(FileExistsError):
                write_contract_bundle(
                    output_root,
                    bundle=bundle,
                    base_identity=BASE_IDENTITY,
                    tag_dictionary=TAG_DICTIONARY,
                    semantic_governance=SEMANTIC_GOVERNANCE,
                    risk_gate_policy=RISK_GATE_POLICY,
                    as_of_utc=AS_OF,
                )


if __name__ == "__main__":
    unittest.main()
