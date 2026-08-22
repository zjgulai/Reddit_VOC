from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
from pathlib import Path
import unittest

from reddit_voc.v3_indicators import canonical_json_bytes, load_indicator_registry
from reddit_voc.v3_periodized_metrics import (
    PeriodizedMetricsError,
    build_periodized_metrics_candidate,
    build_periodized_metrics_input,
    validate_periodized_metrics_input,
)
from reddit_voc.v3_reporting_periods import compare_periods


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = load_indicator_registry(
    ROOT / "config/analytics/reddit-voc-indicator-registry-v1.json"
)


def _observation(
    member_id: str,
    *,
    precision: str,
    instant: str | None = None,
    calendar_date: str | None = None,
    brand: str = "momcozy",
    thread_id: str | None = None,
    voc_type: str = "post_voc",
) -> dict[str, object]:
    return {
        "brand": brand,
        "brand_eligible": True,
        "event_created_at_utc": instant,
        "event_time_precision": precision,
        "metric_eligible": True,
        "metric_member_id": member_id,
        "product_bound": False,
        "product_problem_facts": [],
        "recommendation": "none",
        "recommendation_classification_status": "complete",
        "sentiment": "neutral",
        "sentiment_classification_status": "complete",
        "source_calendar_date": calendar_date,
        "thread_id": thread_id or member_id.removeprefix("t3_"),
        "voc_type": voc_type,
    }


class PeriodizedMetricsTests(unittest.TestCase):
    @staticmethod
    def _attestation(
        *,
        start: str = "2026-07-15",
        end: str = "2026-07-15",
        dataset_id: str = "fixture-dataset",
        source_snapshot_id: str = "fixture-snapshot",
        scope: str = "canonical_observation_pool",
    ) -> dict[str, object]:
        return {
            "attestation_basis": "data_owner_declaration",
            "attestation_date": "2026-07-16",
            "attestation_id": "fixture-owner-coverage-20260716",
            "boundaries": {
                "database_write": False,
                "deploy": False,
                "live_send": False,
                "production_unchanged": True,
                "provider_call": False,
                "remote_write": False,
            },
            "comparison_uses": [
                "period_over_period",
                "trend",
                "year_over_year",
            ],
            "completeness_percent": 100,
            "coverage_window": {
                "end_calendar_date_inclusive": end,
                "start_calendar_date_inclusive": start,
            },
            "dataset_id": dataset_id,
            "evidence_class": "owner_attested_not_crawler_proof",
            "schema_version": "reddit_voc_data_owner_coverage_attestation_v1",
            "scope": scope,
            "source_snapshot_id": source_snapshot_id,
            "statement_cn": "历史采集完整性100%，可以正常进行同环比和趋势分析",
        }

    @staticmethod
    def _attestation_sha(value: dict[str, object]) -> str:
        return sha256(canonical_json_bytes(value) + b"\n").hexdigest()

    def _input(self, *, attested: bool = False) -> dict[str, object]:
        observations = [
            _observation(
                "t3_day",
                precision="day",
                calendar_date="2026-07-15",
            ),
            _observation(
                "t3_instant",
                precision="instant",
                instant="2026-07-14T16:30:00+00:00",
            ),
        ]
        attestation = self._attestation() if attested else None
        return build_periodized_metrics_input(
            observations=observations,
            input_bindings={
                "canonical_manifest_sha256": "a" * 64,
                "canonical_receipt_sha256": "b" * 64,
                "facts_manifest_sha256": "c" * 64,
                "governed_manifest_sha256": "d" * 64,
                "governed_receipt_sha256": "e" * 64,
                "metric_eligibility_sha256": "f" * 64,
                "vocs_sha256": "1" * 64,
            },
            coverage_attestation=attestation,
            coverage_attestation_sha256=(
                self._attestation_sha(attestation) if attestation else None
            ),
            dataset_id="fixture-dataset",
            metric_policy_version=REGISTRY.registry_version,
            scope="canonical_observation_pool",
            source_snapshot_id="fixture-snapshot",
        )

    def test_floating_day_and_instant_share_local_day_without_day_timezone_conversion(self) -> None:
        document = self._input()
        daily = next(
            row
            for row in document["periods"]
            if row["period_id"] == "daily:2026-07-15:2026-07-16"
        )
        self.assertEqual(daily["member_ids"], ["t3_day", "t3_instant"])
        self.assertEqual(daily["time_precision"], "calendar_day_assignment_v1")
        self.assertEqual(daily["observed_time_precision"], "mixed")
        self.assertEqual(
            document["latest_complete_period_ids"]["daily"],
            "daily:2026-07-15:2026-07-16",
        )

    def test_profiles_are_hash_bound_and_historical_comparison_fails_closed(self) -> None:
        document = self._input()
        validate_periodized_metrics_input(document)
        self.assertFalse(document["comparison_contract_proven"])
        self.assertIn(
            "historical_collection_coverage_not_owner_attested_complete",
            document["comparison_unavailable_reason_codes"],
        )
        for row in document["periods"]:
            for key in (
                "source_selection_profile_hash",
                "coverage_profile_hash",
                "retrieval_contract_hash",
            ):
                self.assertEqual(row[key], document[key])

        tampered = deepcopy(document)
        tampered["profiles"]["coverage_profile"]["coverage_status"] = "complete"
        with self.assertRaisesRegex(PeriodizedMetricsError, "profile hash"):
            validate_periodized_metrics_input(tampered)

    def test_owner_attestation_enables_comparison_and_is_hash_scope_window_bound(self) -> None:
        document = self._input(attested=True)
        validate_periodized_metrics_input(document)
        self.assertTrue(document["comparison_contract_proven"])
        self.assertEqual(document["comparison_unavailable_reason_codes"], [])
        self.assertTrue(
            all(row["comparison_contract_proven"] is True for row in document["periods"])
        )

        tampered = deepcopy(document)
        tampered["data_owner_coverage_attestation"]["statement_cn"] = "tampered"
        with self.assertRaisesRegex(PeriodizedMetricsError, "attestation hash"):
            validate_periodized_metrics_input(tampered)

        mismatched = self._attestation(dataset_id="wrong-dataset")
        with self.assertRaisesRegex(PeriodizedMetricsError, "attestation dataset"):
            build_periodized_metrics_input(
                observations=[
                    _observation(
                        "t3_day",
                        precision="day",
                        calendar_date="2026-07-15",
                    )
                ],
                input_bindings={
                    "canonical_manifest_sha256": "a" * 64,
                    "canonical_receipt_sha256": "b" * 64,
                    "facts_manifest_sha256": "c" * 64,
                    "governed_manifest_sha256": "d" * 64,
                    "governed_receipt_sha256": "e" * 64,
                    "metric_eligibility_sha256": "f" * 64,
                    "vocs_sha256": "1" * 64,
                },
                coverage_attestation=mismatched,
                coverage_attestation_sha256=self._attestation_sha(mismatched),
                dataset_id="fixture-dataset",
                metric_policy_version=REGISTRY.registry_version,
                scope="canonical_observation_pool",
                source_snapshot_id="fixture-snapshot",
            )

    def test_attested_window_materializes_contiguous_empty_periods(self) -> None:
        observations = [
            _observation("t3_first", precision="day", calendar_date="2026-07-13"),
            _observation("t3_last", precision="day", calendar_date="2026-07-15"),
        ]
        observations[1]["integrity_level"] = "I3"
        attestation = self._attestation(start="2026-07-13", end="2026-07-15")
        document = build_periodized_metrics_input(
            observations=observations,
            input_bindings={
                "canonical_manifest_sha256": "a" * 64,
                "canonical_receipt_sha256": "b" * 64,
                "facts_manifest_sha256": "c" * 64,
                "governed_manifest_sha256": "d" * 64,
                "governed_receipt_sha256": "e" * 64,
                "metric_eligibility_sha256": "f" * 64,
                "vocs_sha256": "1" * 64,
            },
            coverage_attestation=attestation,
            coverage_attestation_sha256=self._attestation_sha(attestation),
            dataset_id="fixture-dataset",
            metric_policy_version=REGISTRY.registry_version,
            scope="canonical_observation_pool",
            source_snapshot_id="fixture-snapshot",
        )
        daily = [row for row in document["periods"] if row["grain"] == "daily"]
        self.assertEqual(len(daily), 3)
        self.assertEqual(daily[1]["period_id"], "daily:2026-07-14:2026-07-15")
        self.assertEqual(daily[1]["member_ids"], [])
        self.assertEqual(daily[1]["eligible_volume"], 0)
        self.assertEqual(daily[0]["time_precision"], daily[1]["time_precision"])
        self.assertEqual(daily[1]["observed_time_precision"], "unobserved")
        self.assertEqual(
            sum(len(row["member_ids"]) for row in daily),
            len(observations),
        )
        candidate = build_periodized_metrics_candidate(
            {
                "atomic_facts": [],
                "context": {},
                "eligibility_rows": [],
                "observations": observations,
                "periodized_metrics_input": document,
                "scope": "canonical_observation_pool",
            },
            registry=REGISTRY,
        )
        current = next(
            row
            for row in candidate["rows"]
            if row["period_id"] == "daily:2026-07-15:2026-07-16"
            and row["metric_id"] == "RV-CI-04"
        )
        empty_baseline = next(
            row
            for row in candidate["rows"]
            if row["period_id"] == "daily:2026-07-14:2026-07-15"
            and row["metric_id"] == "RV-CI-04"
        )
        comparison = compare_periods(current, empty_baseline)
        self.assertEqual(comparison.display, "—")
        self.assertEqual(
            comparison.reason_codes,
            ("baseline_zero_relative_change_undefined",),
        )

    def test_rv_in_05_consumes_three_same_grain_complete_periods(self) -> None:
        observations = []
        for day in ("2026-07-13", "2026-07-14", "2026-07-15"):
            for index in range(10):
                observations.append(
                    _observation(
                        f"t3_{day}_{index}",
                        precision="day",
                        calendar_date=day,
                    )
                )
        attestation = self._attestation(start="2026-07-13", end="2026-07-15")
        document = build_periodized_metrics_input(
            observations=observations,
            input_bindings={
                "canonical_manifest_sha256": "a" * 64,
                "canonical_receipt_sha256": "b" * 64,
                "facts_manifest_sha256": "c" * 64,
                "governed_manifest_sha256": "d" * 64,
                "governed_receipt_sha256": "e" * 64,
                "metric_eligibility_sha256": "f" * 64,
                "vocs_sha256": "1" * 64,
            },
            coverage_attestation=attestation,
            coverage_attestation_sha256=self._attestation_sha(attestation),
            dataset_id="fixture-dataset",
            metric_policy_version=REGISTRY.registry_version,
            scope="canonical_observation_pool",
            source_snapshot_id="fixture-snapshot",
        )
        source = {
            "atomic_facts": [],
            "context": {},
            "eligibility_rows": [],
            "observations": observations,
            "periodized_metrics_input": document,
            "scope": "canonical_observation_pool",
        }
        candidate = build_periodized_metrics_candidate(source, registry=REGISTRY)
        self.assertEqual(
            candidate["coverage_attestation"]["completeness_percent"], 100
        )
        self.assertEqual(
            candidate["coverage_attestation"]["evidence_class"],
            "owner_attested_not_crawler_proof",
        )
        latest_daily = document["latest_complete_period_ids"]["daily"]
        acceleration = next(
            row
            for row in candidate["rows"]
            if row["period_id"] == latest_daily and row["metric_id"] == "RV-IN-05"
        )
        self.assertTrue(acceleration["comparison_contract_proven"])
        self.assertEqual(acceleration["status"], "available")
        self.assertEqual(acceleration["unavailable_reason_codes"], [])

    def test_candidate_contains_all_registered_metrics_for_every_period(self) -> None:
        document = self._input()
        source = {
            "atomic_facts": [],
            "context": {
                "RV-BR-04": {"recommendation_closed_set_scan_complete": True},
                "RV-DH-04": {
                    "coverage_status": "unavailable",
                    "reason_codes": [
                        "independent_product_relevance_evidence_unavailable"
                    ],
                },
                "RV-PS-01": {
                    "coverage_status": "unavailable",
                    "reason_codes": [
                        "independent_parent_scope_eligibility_evidence_unavailable"
                    ],
                },
            },
            "eligibility_rows": [],
            "observations": [
                _observation(
                    "t3_day",
                    precision="day",
                    calendar_date="2026-07-15",
                ),
                _observation(
                    "t3_instant",
                    precision="instant",
                    instant="2026-07-14T16:30:00+00:00",
                ),
            ],
            "periodized_metrics_input": document,
            "scope": "canonical_observation_pool",
        }
        candidate = build_periodized_metrics_candidate(source, registry=REGISTRY)
        self.assertEqual(
            candidate["metric_row_count"],
            candidate["period_count"] * 26,
        )
        self.assertEqual(
            candidate["brand_health_dimension_row_count"],
            candidate["period_count"] * 8,
        )
        self.assertEqual(
            candidate["contract_extensions"],
            [
                "reddit_voc_brand_health_dimension_contribution_v1",
                "reddit_voc_period_activity_v1",
            ],
        )
        latest_month = document["latest_complete_period_ids"]["monthly"]
        monthly_dimensions = [
            row
            for row in candidate["brand_health_dimension_rows"]
            if row["period_id"] == latest_month
            and row["comparison_side"] == "qualified_organic"
        ]
        self.assertEqual(
            {row["dimension_id"] for row in monthly_dimensions},
            {
                "reputation",
                "product_experience",
                "recommendation_trust",
                "risk_resilience",
            },
        )
        self.assertEqual(
            sum(
                float(row["contribution_points"])
                for row in monthly_dimensions
                if row["contribution_points"] is not None
            ),
            sum(
                float(row["dimension_value"]) / 4
                for row in monthly_dimensions
                if row["dimension_value"] is not None
            ),
        )
        for row in monthly_dimensions:
            if row["dimension_value"] is None:
                self.assertIsNone(row["contribution_points"])
                continue
            expected = (Decimal(str(row["dimension_value"])) / Decimal(4)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            self.assertEqual(Decimal(str(row["contribution_points"])), expected)
        self.assertEqual(
            {row["metric_id"] for row in candidate["rows"]},
            {item.reddit_indicator_id for item in REGISTRY.indicators},
        )
        self.assertTrue(
            all(row["comparison_contract_proven"] is False for row in candidate["rows"])
        )

    def test_period_activity_separates_new_posts_and_historical_thread_comments(self) -> None:
        observations = [
            _observation(
                "t3_history",
                precision="day",
                calendar_date="2026-07-14",
                brand="momcozy",
                thread_id="history",
            ),
            _observation(
                "t3_current",
                precision="day",
                calendar_date="2026-07-15",
                brand="momcozy",
                thread_id="current",
            ),
            _observation(
                "t1_history_comment",
                precision="instant",
                instant="2026-07-14T17:00:00+00:00",
                brand="momcozy",
                thread_id="history",
                voc_type="comment_context_voc",
            ),
            _observation(
                "t1_current_comment",
                precision="instant",
                instant="2026-07-14T18:00:00+00:00",
                brand="momcozy",
                thread_id="current",
                voc_type="comment_context_voc",
            ),
            _observation(
                "t1_unassigned_comment",
                precision="instant",
                instant="2026-07-14T19:00:00+00:00",
                brand="unassigned",
                thread_id="history",
                voc_type="comment_context_voc",
            ),
        ]
        attestation = self._attestation(start="2026-07-14", end="2026-07-15")
        document = build_periodized_metrics_input(
            observations=observations,
            input_bindings={
                "canonical_manifest_sha256": "a" * 64,
                "canonical_receipt_sha256": "b" * 64,
                "facts_manifest_sha256": "c" * 64,
                "governed_manifest_sha256": "d" * 64,
                "governed_receipt_sha256": "e" * 64,
                "metric_eligibility_sha256": "f" * 64,
                "vocs_sha256": "1" * 64,
            },
            coverage_attestation=attestation,
            coverage_attestation_sha256=self._attestation_sha(attestation),
            dataset_id="fixture-dataset",
            metric_policy_version=REGISTRY.registry_version,
            scope="canonical_observation_pool",
            source_snapshot_id="fixture-snapshot",
        )
        candidate = build_periodized_metrics_candidate(
            {
                "atomic_facts": [],
                "context": {},
                "eligibility_rows": [],
                "observations": observations,
                "periodized_metrics_input": document,
                "scope": "canonical_observation_pool",
            },
            registry=REGISTRY,
        )
        activity = next(
            row
            for row in candidate["activity_rows"]
            if row["period_id"] == "daily:2026-07-15:2026-07-16"
        )
        self.assertEqual(candidate["activity_row_count"], candidate["period_count"])
        self.assertEqual(activity["all_observed"]["new_post_count"], 1)
        self.assertEqual(activity["all_observed"]["new_comment_count"], 3)
        self.assertEqual(
            activity["all_observed"]["comments_on_historical_posts"], 2
        )
        self.assertEqual(
            activity["all_observed"]["comments_on_current_period_posts"], 1
        )
        self.assertEqual(activity["all_observed"]["active_historical_post_count"], 1)
        self.assertEqual(activity["momcozy"]["new_post_count"], 1)
        self.assertEqual(activity["momcozy"]["new_comment_count"], 2)
        self.assertEqual(activity["momcozy"]["comments_on_historical_posts"], 1)
        self.assertEqual(activity["momcozy"]["comments_on_current_period_posts"], 1)


if __name__ == "__main__":
    unittest.main()
