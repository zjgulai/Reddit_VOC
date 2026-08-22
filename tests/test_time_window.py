from datetime import date, datetime, timezone
import unittest

from reddit_voc.time_window import daily_window, historical_natural_day_window, rolling_window


class TimeWindowTests(unittest.TestCase):
    def test_daily_window_uses_previous_7am_when_anchor_before_run_hour(self):
        window = daily_window(anchor=datetime(2026, 7, 6, 22, 0, tzinfo=timezone.utc))
        self.assertEqual(window.end_local.hour, 7)
        self.assertLess(window.start_utc, window.end_utc)

    def test_window_contains_left_closed_right_open_utc_range(self):
        window = daily_window(anchor=datetime(2026, 7, 6, 23, 0, tzinfo=timezone.utc))
        self.assertTrue(window.contains_utc(window.start_utc))
        self.assertFalse(window.contains_utc(window.end_utc))

    def test_rolling_window_uses_exact_end_timestamp(self):
        window = rolling_window(end_utc=datetime(2026, 7, 9, 6, 48, 39, tzinfo=timezone.utc), hours=24)
        self.assertEqual(window.end_utc.isoformat(), "2026-07-09T06:48:39+00:00")
        self.assertEqual(window.start_utc.isoformat(), "2026-07-08T06:48:39+00:00")
        self.assertEqual(window.end_local.hour, 14)
        self.assertEqual(window.end_local.minute, 48)

    def test_historical_window_rejects_reversed_dates(self):
        with self.assertRaisesRegex(ValueError, "end_date_inclusive precedes start_date"):
            historical_natural_day_window(
                start_date=date(2026, 7, 12),
                end_date_inclusive=date(2026, 7, 11),
            )

    def test_historical_window_rejects_naive_effective_end(self):
        with self.assertRaisesRegex(ValueError, "effective_end_utc must be timezone-aware"):
            historical_natural_day_window(
                start_date=date(2025, 1, 1),
                end_date_inclusive=date(2026, 7, 11),
                effective_end_utc=datetime(2026, 7, 11, 4, 17, 9),
            )

    def test_historical_window_rejects_end_at_window_start(self):
        with self.assertRaisesRegex(ValueError, "effective_end_utc must be after window start"):
            historical_natural_day_window(
                start_date=date(2025, 1, 1),
                end_date_inclusive=date(2026, 7, 11),
                effective_end_utc=datetime(2024, 12, 31, 16, tzinfo=timezone.utc),
            )


if __name__ == "__main__":
    unittest.main()
