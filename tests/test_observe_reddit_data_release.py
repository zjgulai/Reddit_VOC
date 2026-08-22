from __future__ import annotations

from datetime import datetime, timezone
import unittest

from scripts.observe_reddit_data_release import classify, expected_close


def utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


class ObserveRedditDataReleaseTests(unittest.TestCase):
    def test_expected_close_is_latest_0700_asia_shanghai(self) -> None:
        self.assertEqual(
            expected_close(utc("2026-07-23T00:15:00Z")),
            utc("2026-07-22T23:00:00Z"),
        )
        self.assertEqual(
            expected_close(utc("2026-07-22T22:59:59Z")),
            utc("2026-07-21T23:00:00Z"),
        )

    def test_full_and_partial_current_period_are_observable(self) -> None:
        common = {
            "observed": utc("2026-07-23T00:00:00Z"),
            "data_as_of": utc("2026-07-22T23:00:00Z"),
            "slo_minutes": 90,
            "current_release_id": "reddit_voc_release_fixture",
        }
        full = classify(freshness_status="full", **common)
        partial = classify(freshness_status="partial", **common)
        self.assertEqual(full["state"], "fresh")
        self.assertEqual(partial["state"], "partial")
        self.assertTrue(full["slo_met"])
        self.assertEqual(partial["metrics"]["partial"], 1)

    def test_failed_stalled_stale_and_rollback_are_distinct(self) -> None:
        common = {
            "observed": utc("2026-07-23T01:00:01Z"),
            "data_as_of": utc("2026-07-21T23:00:00Z"),
            "freshness_status": "full",
            "slo_minutes": 90,
            "current_release_id": "reddit_voc_release_old",
        }
        failed = classify(
            latest_attempt={
                "status": "failed",
                "period_end_utc": "2026-07-22T23:00:00Z",
            },
            **common,
        )
        stalled = classify(**common)
        stale = classify(
            latest_attempt={
                "status": "shadow_validated",
                "period_end_utc": "2026-07-22T23:00:00Z",
            },
            **common,
        )
        rollback = classify(
            latest_control={
                "schema_version": "reddit_voc_data_release_rollback_receipt_v1",
                "status": "rolled_back",
                "to_release_id": "reddit_voc_release_old",
            },
            **common,
        )
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(stalled["state"], "stalled")
        self.assertEqual(stale["state"], "stale")
        self.assertEqual(rollback["state"], "rollback")
        self.assertFalse(stale["slo_met"])

    def test_waiting_within_slo_is_not_called_stale(self) -> None:
        result = classify(
            observed=utc("2026-07-23T00:00:00Z"),
            data_as_of=utc("2026-07-21T23:00:00Z"),
            freshness_status="full",
            slo_minutes=90,
            current_release_id="reddit_voc_release_old",
        )
        self.assertEqual(result["state"], "awaiting")

    def test_rejects_future_unclosed_data(self) -> None:
        with self.assertRaisesRegex(
            ValueError, "data_as_of_after_latest_closed_period"
        ):
            classify(
                observed=utc("2026-07-23T00:00:00Z"),
                data_as_of=utc("2026-07-23T23:00:00Z"),
                freshness_status="full",
                slo_minutes=90,
                current_release_id="reddit_voc_release_future",
            )


if __name__ == "__main__":
    unittest.main()
