from __future__ import annotations

from datetime import date
import unittest

from reddit_voc.v3_reporting_periods import (
    ReportingPeriodError,
    build_sparkline,
    compare_periods,
    complete_period_windows,
    format_series_label,
)


def _metric(
    value: str | None,
    *,
    unit: str = "count",
    status: str = "available",
    profile: str = "profile-a",
    proven: bool = True,
) -> dict[str, object]:
    return {
        "comparison_contract_proven": proven,
        "coverage_profile_hash": profile,
        "metric_policy_version": "reddit-voc-metrics-v3",
        "retrieval_contract_hash": profile,
        "scope": "momcozy",
        "source_selection_profile_hash": profile,
        "status": status,
        "time_precision": "day",
        "unit": unit,
        "value": value,
        "voc_type": "post_voc",
    }


class ReportingPeriodTests(unittest.TestCase):
    def test_latest_complete_periods_and_baselines_are_calendar_exact(self) -> None:
        windows = complete_period_windows(date(2026, 7, 16))
        self.assertEqual(
            (windows["daily"].current.start, windows["daily"].current.end),
            (date(2026, 7, 15), date(2026, 7, 16)),
        )
        self.assertEqual(windows["daily"].previous.start, date(2026, 7, 14))
        self.assertEqual(windows["daily"].year_over_year.start, date(2025, 7, 15))
        self.assertEqual(
            (windows["weekly"].current.start, windows["weekly"].current.end),
            (date(2026, 7, 6), date(2026, 7, 13)),
        )
        self.assertEqual(
            (windows["monthly"].current.start, windows["monthly"].current.end),
            (date(2026, 6, 1), date(2026, 7, 1)),
        )
        self.assertTrue(all(row.entry_label == "最新完整周期" for row in windows.values()))

    def test_floating_day_week_month_are_timezone_invariant(self) -> None:
        for timezone in ("UTC", "Asia/Shanghai", "America/Los_Angeles"):
            self.assertEqual(format_series_label("2026-07-15", grain="day", timezone=timezone), "07-15")
            self.assertEqual(format_series_label("2026-07-06", grain="week", timezone=timezone), "07-06")
            self.assertEqual(format_series_label("2026-07", grain="month", timezone=timezone), "2026-07")
        self.assertEqual(
            format_series_label("2026-07-15T16:00:00+00:00", grain="hour"),
            "00:00",
        )

    def test_profile_hash_drift_closes_direction_claim(self) -> None:
        result = compare_periods(_metric("120"), _metric("100", profile="profile-b"))
        self.assertIsNone(result.value)
        self.assertEqual(result.display, "—")
        self.assertIn("source_selection_profile_hash_mismatch", result.reason_codes)
        self.assertEqual(result.line_color, "gray")

    def test_count_zero_baseline_is_unavailable_but_share_uses_pp(self) -> None:
        count = compare_periods(_metric("12"), _metric("0"))
        self.assertEqual(count.display, "—")
        self.assertIn("baseline_zero_relative_change_undefined", count.reason_codes)
        share = compare_periods(
            _metric("0.125", unit="share"),
            _metric("0", unit="share"),
        )
        self.assertEqual(share.value, "12.5")
        self.assertEqual(share.display, "+12.5 pp")
        self.assertEqual(share.line_color, "red")

    def test_formal_percent_ratio_and_log_delta_units_are_precomputed(self) -> None:
        percent = compare_periods(
            _metric("14.2", unit="percent"),
            _metric("10.0", unit="percent"),
        )
        self.assertEqual(percent.display, "+4.2 pp")
        ratio = compare_periods(
            _metric("1.5", unit="ratio"),
            _metric("1.0", unit="ratio"),
        )
        self.assertEqual(ratio.display, "+50%")
        acceleration = compare_periods(
            _metric("1.35", unit="log_delta2"),
            _metric("-0.60", unit="log_delta2"),
        )
        self.assertEqual(acceleration.display, "+2 points")

    def test_unavailable_and_unproven_same_profile_display_is_provisional(self) -> None:
        unavailable = compare_periods(_metric(None, status="unavailable"), _metric("8"))
        self.assertEqual(unavailable.display, "—")
        provisional = compare_periods(
            _metric("9", status="provisional"),
            _metric("8", status="provisional"),
        )
        self.assertEqual(provisional.display, "+12.5%")
        self.assertEqual(provisional.status, "provisional")
        self.assertIn("current_value_provisional", provisional.reason_codes)
        unproven = compare_periods(
            _metric("9", status="provisional", proven=False),
            _metric("8", status="provisional", proven=False),
        )
        self.assertEqual(unproven.display, "+12.5%")
        self.assertEqual(unproven.status, "provisional")
        self.assertEqual(unproven.line_color, "blue")
        self.assertIn(
            "owner_attestation_missing_observed_same_profile",
            unproven.reason_codes,
        )

    def test_sparkline_preserves_gaps_and_requires_three_contiguous_for_trend(self) -> None:
        short = build_sparkline([("2026-07-13", "1"), ("2026-07-14", None)])
        self.assertEqual(short.status, "unavailable")
        self.assertEqual(short.line_color, "gray")
        series = build_sparkline(
            [("2026-07-12", "1"), ("2026-07-13", "2"), ("2026-07-14", None), ("2026-07-15", "3")]
        )
        self.assertFalse(series.trend_claim_supported)
        self.assertEqual(series.points[2][1], None)
        rising = build_sparkline(
            [("2026-07-13", "1"), ("2026-07-14", "2"), ("2026-07-15", "3")]
        )
        self.assertTrue(rising.trend_claim_supported)
        self.assertEqual(rising.direction, "up")
        self.assertEqual(rising.line_color, "red")

    def test_hour_requires_timezone_aware_instant(self) -> None:
        with self.assertRaises(ReportingPeriodError):
            format_series_label("2026-07-15T00:00:00", grain="hour")

    def test_leap_day_yoy_is_explicitly_unavailable(self) -> None:
        windows = complete_period_windows(date(2024, 3, 1))
        self.assertIsNone(windows["daily"].year_over_year)


if __name__ == "__main__":
    unittest.main()
