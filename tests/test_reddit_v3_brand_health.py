from __future__ import annotations

from decimal import Decimal
import unittest


from reddit_voc.v3_brand_health import compute_brand_health


def _grain(prefix: str, voc_type: str, count: int = 30) -> list[dict[str, object]]:
    return [
        {
            "metric_member_id": f"{prefix}_{index}",
            "voc_type": voc_type,
            "metric_eligible": True,
            "brand": "momcozy",
            "brand_eligible": True,
            "product_bound": True,
            "sentiment_classification_status": "complete",
            "sentiment": "neutral",
            "problem_classification_status": "complete",
            "product_problem_facts": [],
            "recommendation_classification_status": "complete",
            "recommendation": "none",
            "priority_classification_status": "complete",
            "priority": "none",
            "commercial_level": "C0",
            "integrity_level": "I0",
            "manual_confirmation": False,
        }
        for index in range(count)
    ]


class BrandHealthTests(unittest.TestCase):
    def test_post_comment_are_equal_weight_and_total_rounds_half_up_once(self) -> None:
        posts = _grain("t3", "post_voc")
        comments = _grain("t1", "comment_context_voc")
        for row in posts[:3]:
            row["sentiment"] = "positive"
        for row in comments[:6]:
            row["sentiment"] = "negative"
        result = compute_brand_health(posts + comments, decimal_places=1)
        reputation = result.raw.dimensions["reputation"]
        self.assertEqual(reputation.grain_scores["post_voc"].value, Decimal("55.0"))
        self.assertEqual(
            reputation.grain_scores["comment_context_voc"].value,
            Decimal("40.0"),
        )
        self.assertEqual(reputation.value, Decimal("47.5"))
        self.assertEqual(result.raw.total.status, "available")

    def test_low_processed_coverage_keeps_descriptive_score_provisional(self) -> None:
        posts = _grain("t3", "post_voc")
        comments = _grain("t1", "comment_context_voc")
        for row in posts[:7]:
            row["problem_classification_status"] = "unprocessed"
        result = compute_brand_health(posts + comments)
        dimension = result.raw.dimensions["product_experience"]
        self.assertEqual(dimension.status, "provisional")
        self.assertIsNotNone(dimension.value)
        self.assertEqual(result.raw.total.status, "provisional")
        self.assertIsNotNone(result.raw.total.value)

    def test_integrity_i1_i2_does_not_penalize_raw_index(self) -> None:
        baseline = _grain("t3", "post_voc") + _grain(
            "t1", "comment_context_voc"
        )
        signalled = [dict(row) for row in baseline]
        for row in signalled:
            row["integrity_level"] = "I2"
        self.assertEqual(
            compute_brand_health(baseline).raw.total.value,
            compute_brand_health(signalled).raw.total.value,
        )

    def test_qualified_excludes_only_manual_c3_i4_and_raw_retains_it(self) -> None:
        entities = _grain("t3", "post_voc", 31) + _grain(
            "t1", "comment_context_voc", 31
        )
        confirmed = entities[0]
        confirmed.update(
            {
                "commercial_level": "C3",
                "integrity_level": "I4",
                "manual_confirmation": True,
                "sentiment": "negative",
            }
        )
        unconfirmed = entities[1]
        unconfirmed.update(
            {
                "commercial_level": "C3",
                "integrity_level": "I4",
                "manual_confirmation": False,
                "sentiment": "negative",
            }
        )
        result = compute_brand_health(entities)
        self.assertIn(str(confirmed["metric_member_id"]), result.qualified.excluded_entity_ids)
        self.assertNotIn(str(unconfirmed["metric_member_id"]), result.qualified.excluded_entity_ids)
        self.assertEqual(result.raw.excluded_entity_ids, ())


if __name__ == "__main__":
    unittest.main()
