from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import unittest

from reddit_voc.v3_indicators import load_indicator_registry
from reddit_voc.v3_metrics_input import (
    MetricsInputError,
    canonical_json_bytes,
    materialize_metrics_input,
    metrics_input_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "config/analytics/reddit-voc-indicator-registry-v1.json"
SNAPSHOT_ID = "fixture-source-snapshot"


def _voc(
    voc_id: str,
    entity_id: str,
    voc_type: str,
    *,
    precision: str,
) -> dict[str, object]:
    instant = "2026-07-15T12:00:00Z" if precision != "day" else None
    calendar_date = "2026-07-15" if precision == "day" else None
    return {
        "analysis_text_status": "ready",
        "canonical_entity_id": entity_id,
        "context_status": "linked",
        "event_created_at_utc": instant,
        "event_time_precision": precision,
        "source_calendar_date": calendar_date,
        "source_timezone_status": "known" if precision != "day" else "floating_day",
        "thread_id": "t3_thread",
        "voc_id": voc_id,
        "voc_type": voc_type,
    }


def _fact(
    fact_id: str,
    voc_id: str,
    entity_id: str,
    value: str,
    *,
    status: str = "promoted",
    fact_type: str = "entity_brand_fact",
) -> dict[str, object]:
    return {
        "attributes": {},
        "canonical_entity_id": entity_id,
        "canonical_value": value,
        "decision_status": status,
        "fact_id": fact_id,
        "fact_type": fact_type,
        "source_snapshot_id": SNAPSHOT_ID,
        "voc_id": voc_id,
    }


class MetricsInputMaterializerTests(unittest.TestCase):
    def _build(
        self,
        *,
        recommendation_complete: bool = False,
        include_recommendation: bool = False,
    ) -> object:
        vocs = [
            _voc("v1", "t3_p1", "post_voc", precision="day"),
            _voc("v2", "t1_c1", "comment_context_voc", precision="instant"),
            _voc("v3", "t1_c2", "comment_context_voc", precision="hour"),
            _voc("v4", "t1_c3", "comment_context_voc", precision="day"),
            _voc("v5", "t1_bot", "comment_context_voc", precision="instant"),
        ]
        facts = [
            _fact("f1", "v1", "t3_p1", "momcozy"),
            _fact("f2", "v2", "t1_c1", "momcozy"),
            _fact("f3", "v2", "t1_c1", "competitor"),
            _fact("f4", "v3", "t1_c2", "competitor"),
            _fact(
                "f5",
                "v4",
                "t1_c3",
                "tag:held",
                status="held",
                fact_type="entity_tag_fact",
            ),
        ]
        if include_recommendation:
            facts.append(
                _fact(
                    "f6",
                    "v1",
                    "t3_p1",
                    "L0-GEN-103",
                    fact_type="entity_tag_fact",
                )
            )
        return materialize_metrics_input(
            vocs=vocs,
            automation_voc_ids=["v5"],
            automation_classifications=[
                {
                    "automation_determined": True,
                    "canonical_entity_id": "t1_bot",
                    "canonical_retained": True,
                    "excluded_reason": "explicit_automation",
                    "requires_organic_exclusion": True,
                }
            ],
            governed_facts=facts,
            source_eligibility_rows=[],
            canonical_posts=[
                {
                    "canonical_reddit_id": "t3_p1",
                    "record": {"content": "body", "title": "title"},
                }
            ],
            canonical_comments=[
                {
                    "canonical_reddit_id": "t1_c1",
                    "comment_state": "linked",
                    "record": {"body": "linked"},
                },
                {
                    "canonical_reddit_id": "t1_c2",
                    "comment_state": "unresolved_parent",
                    "record": {"body": "unresolved"},
                },
            ],
            quarantine_comments=[
                {
                    "canonical_reddit_id": "t1_q1",
                    "comment_state": "quarantined",
                }
            ],
            registry=load_indicator_registry(REGISTRY_PATH),
            source_snapshot_id=SNAPSHOT_ID,
            source_facts_manifest_sha256="a" * 64,
            period="all_observed_history",
            scope="canonical_observation_pool",
            expected_source_eligibility_rows=0,
            recommendation_closed_set_complete=recommendation_complete,
        )

    def test_conserves_sources_and_excludes_automation(self) -> None:
        result = self._build()
        self.assertEqual(result.counts["total_vocs"], 5)
        self.assertEqual(result.counts["organic_observations"], 4)
        self.assertEqual(result.counts["automation_excluded_vocs"], 1)
        self.assertEqual(result.counts["promoted_source_facts"], 4)
        self.assertEqual(result.counts["held_source_facts"], 1)
        self.assertEqual(result.counts["atomic_facts"], 4)
        self.assertEqual(result.counts["momcozy_observations"], 1)
        self.assertEqual(result.counts["competitor_observations"], 1)
        self.assertEqual(result.counts["ambiguous_brand_observations"], 1)
        self.assertEqual(result.counts["unassigned_brand_observations"], 1)
        self.assertEqual(result.counts["comments_jsonl"], 2)
        self.assertEqual(result.counts["stored_comments"], 3)
        self.assertNotIn(
            "t1_bot",
            {row["metric_member_id"] for row in result.document["observations"]},
        )

    def test_preserves_floating_day_and_builds_canonical_manifest(self) -> None:
        result = self._build()
        day_rows = [
            row
            for row in result.document["observations"]
            if row["event_time_precision"] == "day"
        ]
        self.assertEqual(result.counts["day_precision_observations"], 2)
        self.assertTrue(all(row["event_created_at_utc"] is None for row in day_rows))
        self.assertTrue(all(row["source_calendar_date"] == "2026-07-15" for row in day_rows))
        payload = canonical_json_bytes(result.document) + b"\n"
        manifest = metrics_input_manifest(
            document_payload=payload,
            counts=result.counts,
            input_bindings={"source": "b" * 64},
            source_snapshot_id=SNAPSHOT_ID,
        )
        self.assertEqual(
            manifest["files"]["metrics-input.json"]["sha256"],
            sha256(payload).hexdigest(),
        )
        self.assertEqual(manifest["independent_validation_status"], "pending")

    def test_rejects_floating_day_timestamp_synthesis(self) -> None:
        voc = _voc("v1", "t3_p1", "post_voc", precision="day")
        voc["event_created_at_utc"] = "2026-07-15T00:00:00Z"
        with self.assertRaisesRegex(MetricsInputError, "floating day"):
            materialize_metrics_input(
                vocs=[voc],
                automation_voc_ids=[],
                automation_classifications=[],
                governed_facts=[],
                source_eligibility_rows=[],
                canonical_posts=[],
                canonical_comments=[],
                quarantine_comments=[],
                registry=load_indicator_registry(REGISTRY_PATH),
                source_snapshot_id=SNAPSHOT_ID,
                source_facts_manifest_sha256="a" * 64,
                period="all_observed_history",
                scope="canonical_observation_pool",
            )

    def test_derives_recommendation_only_from_promoted_closed_set_tag(self) -> None:
        result = self._build(
            recommendation_complete=True,
            include_recommendation=True,
        )
        by_id = {
            row["metric_member_id"]: row for row in result.document["observations"]
        }
        self.assertEqual(by_id["t3_p1"]["recommendation"], "recommend")
        self.assertEqual(by_id["t3_p1"]["recommendation_fact_ids"], ["f6"])
        self.assertEqual(by_id["t1_c1"]["recommendation"], "none")
        self.assertTrue(
            all(
                row["recommendation_classification_status"] == "complete"
                for row in by_id.values()
            )
        )
        self.assertEqual(result.counts["recommendation_expression_observations"], 1)
        self.assertEqual(
            result.document["context"]["RV-DH-04"]["coverage_status"],
            "unavailable",
        )
        self.assertEqual(
            result.document["context"]["RV-PS-01"]["coverage_status"],
            "unavailable",
        )

    def test_uses_versioned_local_analysis_when_no_promoted_sentiment_fact_exists(self) -> None:
        voc = _voc("v1", "t3_p1", "post_voc", precision="day")
        result = materialize_metrics_input(
            vocs=[voc],
            automation_voc_ids=[],
            automation_classifications=[],
            governed_facts=[_fact("f1", "v1", "t3_p1", "momcozy")],
            source_eligibility_rows=[],
            canonical_posts=[{
                "canonical_reddit_id": "t3_p1",
                "record": {
                    "content": "body",
                    "title": "title",
                    "analysis": {
                        "analysis_version": "local_rules_v1",
                        "provider_call": False,
                        "sentiment_label": "negative",
                        "severity": "high",
                    },
                },
            }],
            canonical_comments=[],
            quarantine_comments=[],
            registry=load_indicator_registry(REGISTRY_PATH),
            source_snapshot_id=SNAPSHOT_ID,
            source_facts_manifest_sha256="a" * 64,
            period="all_observed_history",
            scope="canonical_observation_pool",
        )
        row = result.document["observations"][0]
        self.assertEqual(row["sentiment"], "negative")
        self.assertEqual(row["sentiment_classification_status"], "complete")
        self.assertEqual(row["sentiment_classification_source"], "canonical_local_rules_v1")
        self.assertEqual(row["priority"], "p1")
        self.assertEqual(row["priority_classification_status"], "complete")
        self.assertEqual(result.counts["canonical_analysis_fallback_observations"], 1)


if __name__ == "__main__":
    unittest.main()
