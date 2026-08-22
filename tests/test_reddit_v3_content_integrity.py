from __future__ import annotations

import unittest

from reddit_voc.v3_content_integrity import (
    ContentIntegrityError,
    build_event_chain,
    classify_integrity,
    transition_brand_response,
    transition_review_status,
)


class ContentIntegrityTests(unittest.TestCase):
    def test_single_affiliate_and_ai_style_never_confirm_violation(self) -> None:
        result = classify_integrity(
            {
                "ai_style_signal": True,
                "commercial_disclosure": "affiliate",
                "entity_id": "t3_fixture",
                "signal_types": ["content"],
            }
        )
        self.assertEqual(result.commercial_relation, "C1")
        self.assertIn(result.integrity_level, {"I0", "I1", "I2"})
        self.assertNotEqual(result.commercial_relation, "C3")
        self.assertFalse(result.brand_control_confirmed)

    def test_two_independent_signal_types_reach_i2_but_not_i4(self) -> None:
        result = classify_integrity(
            {
                "entity_id": "t3_fixture",
                "repeated_propagation_pattern": True,
                "signal_types": ["content", "behavior"],
            }
        )
        self.assertEqual(result.commercial_relation, "C2")
        self.assertEqual(result.integrity_level, "I2")
        self.assertEqual(result.publication_label, "疑似非自然传播")

    def test_explicit_bot_exclusion_is_not_brand_attribution(self) -> None:
        result = classify_integrity(
            {
                "entity_id": "t1_bot",
                "explicit_automation": True,
                "signal_types": ["content", "behavior", "link"],
            }
        )
        self.assertEqual(result.commercial_relation, "C0")
        self.assertEqual(result.integrity_level, "I0")
        self.assertTrue(result.metric_excluded)

    def test_moderator_event_chain_is_c2_i3_not_brand_confirmed(self) -> None:
        roots = [
            {"post_id": post_id, "authority": "subreddit_moderator", "evidence_id": f"fact:{post_id}"}
            for post_id in ("1kkvihg", "1l2aofi", "1n2q1do", "1o1pqox", "1u2gvn4")
        ]
        result = build_event_chain(roots)
        self.assertEqual((result.commercial_relation, result.integrity_level), ("C2", "I3"))
        self.assertEqual(result.governance_authority, "subreddit_moderator")
        self.assertFalse(result.brand_control_confirmed)
        self.assertEqual(result.lifecycle_status, "review_required")

    def test_i4_requires_manual_rule_and_brand_attribution(self) -> None:
        incomplete = classify_integrity(
            {"entity_id": "t3_fixture", "manual_rule_violation_confirmed": True, "signal_types": ["content", "behavior"]}
        )
        self.assertNotEqual(incomplete.integrity_level, "I4")
        confirmed = classify_integrity(
            {
                "brand_attribution_confirmed": True,
                "entity_id": "t3_fixture",
                "manual_rule_violation_confirmed": True,
                "signal_types": ["content", "behavior"],
            }
        )
        self.assertEqual((confirmed.commercial_relation, confirmed.integrity_level), ("C3", "I4"))

    def test_brand_response_lifecycle_is_explicit(self) -> None:
        self.assertEqual(transition_brand_response("unanswered", "confirmed"), "confirmed")
        self.assertEqual(transition_brand_response("disputed", "retracted"), "retracted")
        with self.assertRaises(ContentIntegrityError):
            transition_brand_response("retracted", "unanswered")

    def test_review_resolution_requires_reviewer_and_evidence(self) -> None:
        self.assertEqual(transition_review_status("queued", "in_review"), "in_review")
        with self.assertRaisesRegex(ContentIntegrityError, "reviewer and evidence"):
            transition_review_status("in_review", "resolved_confirmed")
        self.assertEqual(
            transition_review_status(
                "in_review",
                "resolved_confirmed",
                reviewer_id="reviewer:fixture",
                evidence_id="review-evidence:fixture",
            ),
            "resolved_confirmed",
        )


if __name__ == "__main__":
    unittest.main()
