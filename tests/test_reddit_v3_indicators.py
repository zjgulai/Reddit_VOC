from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import unittest


from reddit_voc.v3_indicators import (
    IndicatorComputationError,
    compute_indicator,
    load_indicator_registry,
)


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "config/analytics/reddit-voc-indicator-registry-v1.json"


def _entity(entity_id: str, **changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "metric_member_id": entity_id,
        "voc_type": "post_voc",
        "metric_eligible": True,
        "brand": "momcozy",
        "brand_eligible": True,
        "text_ready": True,
        "linked_parent": True,
        "tag_fact_ids": [],
        "evidence_complete": True,
        "product_relevant": True,
        "product_bound": True,
        "product_scope": "wearable_pump",
        "parent_scope": "breast_pump",
        "sentiment_classification_status": "complete",
        "sentiment": "neutral",
        "recommendation_classification_status": "complete",
        "recommendation": "none",
        "problem_classification_status": "complete",
        "product_problem_facts": [],
        "priority_classification_status": "complete",
        "priority": "none",
    }
    value.update(changes)
    return value


class IndicatorRegistryTests(unittest.TestCase):
    def test_registry_is_exact_19_core_plus_7_integrity_closed_set(self) -> None:
        registry = load_indicator_registry(REGISTRY_PATH)
        ids = {item.reddit_indicator_id for item in registry.indicators}
        expected = {
            *(f"RV-DH-{i:02d}" for i in range(1, 6)),
            *(f"RV-BR-{i:02d}" for i in range(1, 6)),
            *(f"RV-PS-{i:02d}" for i in range(1, 5)),
            *(f"RV-IN-{i:02d}" for i in range(1, 6)),
            *(f"RV-CI-{i:02d}" for i in range(1, 8)),
        }
        self.assertEqual(ids, expected)
        self.assertEqual(len(ids), 26)
        self.assertEqual(registry.core_indicator_count, 19)
        self.assertEqual(registry.integrity_indicator_count, 7)


class IndicatorComputationTests(unittest.TestCase):
    def test_observation_count_keeps_zero_and_small_counts(self) -> None:
        empty = compute_indicator("RV-BR-01", [])
        self.assertEqual(empty.status, "available")
        self.assertEqual(empty.value, Decimal("0"))
        self.assertEqual(empty.denominator, Decimal("0"))
        self.assertEqual(empty.unavailable_reason_codes, ())

        small = compute_indicator(
            "RV-BR-01",
            [_entity("t3_1"), _entity("t3_2")],
        )
        self.assertEqual(small.status, "available")
        self.assertEqual(small.value, Decimal("2"))
        self.assertEqual(small.denominator, Decimal("2"))
        self.assertEqual(small.unavailable_reason_codes, ())

    def test_recommendation_requires_complete_closed_set_scan_and_governed_tag_evidence(self) -> None:
        entities = [
            _entity(
                "t3_0",
                recommendation="recommend",
                recommendation_fact_ids=["fact-recommend"],
            ),
            *[_entity(f"t3_{index}") for index in range(1, 30)],
        ]
        facts = [
            {
                "canonical_entity_id": "t3_0",
                "canonical_value": "L0-GEN-103",
                "decision_status": "promoted",
                "fact_id": "fact-recommend",
                "fact_type": "entity_tag_fact",
            }
        ]

        unproven = compute_indicator(
            "RV-BR-04",
            entities,
            atomic_facts=facts,
        )
        self.assertEqual(unproven.status, "unavailable")
        self.assertIsNone(unproven.value)
        self.assertIn(
            "recommendation_closed_set_scan_completeness_unproven",
            unproven.unavailable_reason_codes,
        )

        proven = compute_indicator(
            "RV-BR-04",
            entities,
            atomic_facts=facts,
            context={"recommendation_closed_set_scan_complete": True},
        )
        self.assertEqual(proven.status, "available")
        self.assertEqual(proven.value, Decimal("3.33"))
        self.assertEqual(proven.numerator, Decimal("1"))
        self.assertEqual(proven.denominator, Decimal("30"))
        self.assertEqual(proven.evidence_fact_ids, ("fact-recommend",))

    def test_product_binding_metrics_fail_closed_without_independent_scope_evidence(self) -> None:
        entities = [_entity(f"t3_{index}") for index in range(30)]
        cases = (
            (
                "RV-DH-04",
                "independent_product_relevance_evidence_unavailable",
            ),
            (
                "RV-PS-01",
                "independent_parent_scope_eligibility_evidence_unavailable",
            ),
        )
        for indicator_id, reason in cases:
            with self.subTest(indicator_id=indicator_id):
                result = compute_indicator(
                    indicator_id,
                    entities,
                    context={
                        "coverage_status": "unavailable",
                        "reason_codes": [reason],
                    },
                )
                self.assertEqual(result.status, "unavailable")
                self.assertIsNone(result.value)
                self.assertIn(reason, result.unavailable_reason_codes)

    def test_empty_product_problem_ranking_has_explicit_reason(self) -> None:
        result = compute_indicator(
            "RV-PS-03",
            [_entity(f"t3_{index}") for index in range(30)],
        )
        self.assertEqual(result.status, "available")
        self.assertEqual(result.value, ())
        self.assertIn("no_qualifying_items", result.unavailable_reason_codes)

    def test_product_problem_rate_requires_same_entity_promoted_negative_problem(self) -> None:
        entities = [
            _entity("t3_negative_only", sentiment="negative"),
            _entity(
                "t3_problem_only",
                product_problem_facts=[
                    {
                        "fact_id": "fact-problem-only",
                        "decision_status": "promoted",
                        "fact_type": "entity_problem_fact",
                        "polarity": "neutral",
                        "tag_id": "problem-a",
                    }
                ],
            ),
            _entity(
                "t3_both",
                sentiment="negative",
                product_problem_facts=[
                    {
                        "fact_id": "fact-both",
                        "decision_status": "promoted",
                        "fact_type": "entity_problem_fact",
                        "polarity": "negative",
                        "tag_id": "problem-b",
                    }
                ],
            ),
        ]
        result = compute_indicator("RV-PS-02", entities)
        self.assertEqual(result.numerator, Decimal("1"))
        self.assertEqual(result.denominator, Decimal("3"))
        self.assertEqual(result.numerator_member_ids, ("t3_both",))
        self.assertEqual(result.status, "provisional")
        self.assertEqual(result.value, Decimal("33.33"))

    def test_rate_uses_decimal_round_half_up_and_sample_thresholds(self) -> None:
        entities = [
            _entity(f"t3_{index}", sentiment="negative" if index < 2 else "neutral")
            for index in range(30)
        ]
        result = compute_indicator("RV-BR-02", entities, decimal_places=2)
        self.assertEqual(result.value, Decimal("6.67"))
        self.assertEqual(result.status, "available")

        provisional = compute_indicator("RV-BR-02", entities[:10])
        small = compute_indicator("RV-BR-02", entities[:9])
        self.assertEqual(provisional.status, "provisional")
        self.assertEqual(small.status, "provisional")
        self.assertEqual(small.value, Decimal("22.22"))

    def test_zero_denominator_is_unavailable_not_zero(self) -> None:
        result = compute_indicator("RV-DH-01", [])
        self.assertEqual(result.status, "unavailable")
        self.assertIsNone(result.value)
        self.assertEqual(result.unavailable_reason_codes, ("zero_denominator",))

    def test_evidence_members_must_join_governed_fact_and_eligibility_foreign_keys(self) -> None:
        entities = [
            _entity(
                "t3_a",
                product_problem_facts=[
                    {
                        "fact_id": "fact-a",
                        "decision_status": "promoted",
                        "fact_type": "entity_problem_fact",
                        "polarity": "negative",
                        "tag_id": "problem-a",
                    }
                ],
            )
        ]
        eligibility = [
            {
                "metric_member_id": "t3_a",
                "reddit_indicator_id": "RV-PS-02",
                "comparison_side": "momcozy",
                "period": "p",
                "scope": "wearable_pump",
                "voc_type": "post_voc",
                "status": "eligible",
            }
        ]
        facts = [
            {
                "fact_id": "fact-a",
                "canonical_entity_id": "t3_a",
                "decision_status": "promoted",
                "fact_type": "entity_problem_fact",
            }
        ]
        result = compute_indicator(
            "RV-PS-02",
            entities,
            comparison_side="momcozy",
            period="p",
            scope="wearable_pump",
            eligibility_rows=eligibility,
            atomic_facts=facts,
        )
        self.assertEqual(result.evidence_fact_ids, ("fact-a",))

        tampered = deepcopy(facts)
        tampered[0]["canonical_entity_id"] = "t3_other"
        with self.assertRaisesRegex(IndicatorComputationError, "fact foreign key"):
            compute_indicator(
                "RV-PS-02",
                entities,
                comparison_side="momcozy",
                period="p",
                scope="wearable_pump",
                eligibility_rows=eligibility,
                atomic_facts=tampered,
            )

    def test_ci06_rejects_count_and_rank_targets(self) -> None:
        with self.assertRaisesRegex(IndicatorComputationError, "sensitivity target"):
            compute_indicator(
                "RV-CI-06",
                [],
                context={
                    "target_raw": {
                        "reddit_indicator_id": "RV-BR-01",
                        "unit": "count",
                        "output_shape": "scalar",
                        "status": "available",
                        "value": "40",
                    },
                    "target_qualified": {
                        "reddit_indicator_id": "RV-BR-01",
                        "unit": "count",
                        "output_shape": "scalar",
                        "status": "available",
                        "value": "39",
                    },
                },
            )


if __name__ == "__main__":
    unittest.main()
