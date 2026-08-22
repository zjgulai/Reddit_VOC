from __future__ import annotations

import unittest

from reddit_voc.v3_storylines import StorylineError, build_storyline


class StorylineTests(unittest.TestCase):
    def metric(self, *, status: str = "available") -> dict[str, object]:
        return {
            "metric_id": "RV-PS-02",
            "period_id": "daily:2026-07-15",
            "scope": "momcozy:family:m5-smart",
            "status": status,
            "value": "0.25" if status != "unavailable" else None,
            "unit": "rate",
            "voc_type": "comment_context_voc",
        }

    def test_builds_six_evidence_bound_sections(self) -> None:
        result = build_storyline(
            metric=self.metric(),
            direction="up",
            root_cause_evidence_ids=["fact-1"],
            evidence_registry={"fact-1": {"snapshot_id": "snapshot-a"}},
            snapshot_id="snapshot-a",
            comparison={"status": "available", "display": "+3.2 pp"},
            impact="观察样本中的产品体验风险上升。",
            action={"owner_role": "Product Ops", "priority": "P1", "approval_status": "proposed"},
            monitoring={"metric_id": "RV-PS-02", "cadence": "weekly", "review_date": "2026-07-23"},
        )
        self.assertEqual(
            tuple(result["sections"]),
            ("signal", "root_cause", "counter_intuitive", "impact", "action", "monitoring"),
        )
        self.assertEqual(result["sections"]["root_cause"]["evidence_ids"], ["fact-1"])
        self.assertTrue(result["direction_claim_supported"])

    def test_unavailable_metric_cannot_trigger_direction_claim(self) -> None:
        with self.assertRaisesRegex(StorylineError, "unavailable"):
            build_storyline(
                metric=self.metric(status="unavailable"),
                direction="down",
                root_cause_evidence_ids=[],
                evidence_registry={},
                snapshot_id="snapshot-a",
                comparison={"status": "unavailable", "reason_codes": ["missing_baseline"]},
                impact="无可发布方向结论。",
                action={"owner_role": "Insights", "priority": "P2", "approval_status": "proposed"},
                monitoring={"metric_id": "RV-PS-02", "cadence": "weekly", "review_date": "2026-07-23"},
            )

    def test_missing_root_evidence_is_explicitly_unconfirmed(self) -> None:
        result = build_storyline(
            metric=self.metric(),
            direction="flat",
            root_cause_evidence_ids=[],
            evidence_registry={},
            snapshot_id="snapshot-a",
            comparison={"status": "unavailable", "reason_codes": ["profile_mismatch"]},
            impact="仅描述观察样本。",
            action={"owner_role": "Insights", "priority": "P2", "approval_status": "proposed"},
            monitoring={"metric_id": "RV-PS-02", "cadence": "weekly", "review_date": "2026-07-23"},
        )
        self.assertEqual(result["sections"]["root_cause"]["statement"], "根因未确认")
        self.assertFalse(result["sections"]["counter_intuitive"]["supported"])

    def test_cross_snapshot_or_sales_causality_claim_fails_closed(self) -> None:
        with self.assertRaisesRegex(StorylineError, "snapshot"):
            build_storyline(
                metric=self.metric(), direction="up", root_cause_evidence_ids=["fact-1"],
                evidence_registry={"fact-1": {"snapshot_id": "snapshot-b"}}, snapshot_id="snapshot-a",
                comparison={"status": "available", "display": "+1 pp"}, impact="观察样本风险。",
                action={"owner_role": "Ops", "priority": "P1", "approval_status": "proposed"},
                monitoring={"metric_id": "RV-PS-02", "cadence": "weekly", "review_date": "2026-07-23"},
            )
        with self.assertRaisesRegex(StorylineError, "sales causality"):
            build_storyline(
                metric=self.metric(), direction="up", root_cause_evidence_ids=[], evidence_registry={},
                snapshot_id="snapshot-a", comparison={"status": "available", "display": "+1 pp"},
                impact="该变化必然导致销量下降。",
                action={"owner_role": "Ops", "priority": "P1", "approval_status": "proposed"},
                monitoring={"metric_id": "RV-PS-02", "cadence": "weekly", "review_date": "2026-07-23"},
            )


if __name__ == "__main__":
    unittest.main()
