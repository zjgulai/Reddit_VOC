from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from reddit_voc.browser_runner import BrowserJsonCaptureResult
from reddit_voc.collector import (
    DEFAULT_DAILY_SUBREDDITS,
    DailyCollectionSummary,
    build_listing_url,
    collect_daily_reddit,
)
from reddit_voc.models import DailyCollectionSummary as ModelDailyCollectionSummary
from reddit_voc.search_config import (
    DEFAULT_DAILY_SUBREDDITS as CONFIG_DEFAULT_DAILY_SUBREDDITS,
)
from reddit_voc.storage import VocStore


FIXTURES = Path(__file__).parent / "fixtures"


class FakeRunner:
    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = responses
        self.urls: list[str] = []

    def capture_json_url(self, url: str) -> BrowserJsonCaptureResult:
        self.urls.append(url)
        raw_text = self.responses.get(url, "")
        status = "ok" if raw_text else "blocked"
        return BrowserJsonCaptureResult(
            target_url=url,
            page_url=url,
            page_title="fixture",
            raw_text=raw_text,
            browser_status=status,
            blocked_reason=None if raw_text else "fixture_missing_url",
        )


class DailyCollectorTests(unittest.TestCase):
    def test_daily_contracts_are_reexported_from_neutral_modules(self):
        self.assertIs(DailyCollectionSummary, ModelDailyCollectionSummary)
        self.assertIs(DEFAULT_DAILY_SUBREDDITS, CONFIG_DEFAULT_DAILY_SUBREDDITS)
        self.assertIsInstance(DEFAULT_DAILY_SUBREDDITS, tuple)

    def test_collect_daily_reddit_filters_window_and_ingests_relevant_thread(self):
        listing_text = (FIXTURES / "reddit_listing_browser_json.json").read_text(encoding="utf-8")
        thread_text = (FIXTURES / "reddit_thread_browser_json.json").read_text(encoding="utf-8")
        listing_url = build_listing_url("ExclusivelyPumping", limit=100)
        detail_url = "https://www.reddit.com/r/ExclusivelyPumping/comments/1fixture/momcozy_m5_leaking_at_work/.json"
        runner = FakeRunner({listing_url: listing_text, detail_url: thread_text})

        with TemporaryDirectory() as tmp:
            store = VocStore(Path(tmp) / "voc.sqlite3")
            store.migrate()
            summary = collect_daily_reddit(
                store,
                run_id="daily_collect_test",
                runner=runner,
                subreddits=["ExclusivelyPumping"],
                anchor_utc=datetime(2026, 7, 7, 23, 0, tzinfo=timezone.utc),
            )

            self.assertEqual(summary.status, "partial")
            self.assertEqual(summary.discovered_posts, 1)
            self.assertEqual(summary.window_posts, 1)
            self.assertEqual(summary.relevant_posts, 1)
            self.assertEqual(summary.ingested_threads, 1)
            self.assertEqual(summary.ingested_comments, 2)
            self.assertEqual(summary.analysis_items, 3)
            self.assertIn(detail_url, runner.urls)
            self.assertEqual(store.count_for_run("reddit_threads", "daily_collect_test"), 1)
            self.assertFalse(summary.provider_call)
            self.assertFalse(summary.live_send)

    def test_collect_daily_reddit_supports_exact_rolling_window_end(self):
        listing_text = (FIXTURES / "reddit_listing_browser_json.json").read_text(encoding="utf-8")
        thread_text = (FIXTURES / "reddit_thread_browser_json.json").read_text(encoding="utf-8")
        listing_url = build_listing_url("ExclusivelyPumping", limit=100)
        detail_url = "https://www.reddit.com/r/ExclusivelyPumping/comments/1fixture/momcozy_m5_leaking_at_work/.json"
        runner = FakeRunner({listing_url: listing_text, detail_url: thread_text})

        with TemporaryDirectory() as tmp:
            store = VocStore(Path(tmp) / "voc.sqlite3")
            store.migrate()
            summary = collect_daily_reddit(
                store,
                run_id="daily_collect_exact_window_test",
                runner=runner,
                subreddits=["ExclusivelyPumping"],
                window_end_utc=datetime(2026, 7, 7, 6, 30, tzinfo=timezone.utc),
                rolling_window_hours=1,
            )

            self.assertEqual(summary.window_start_utc, "2026-07-07T05:30:00+00:00")
            self.assertEqual(summary.window_end_utc, "2026-07-07T06:30:00+00:00")
            self.assertEqual(summary.window_posts, 1)
            self.assertEqual(summary.ingested_threads, 1)

    def test_browser_overlap_is_discovered_but_excluded_from_metric_run_rows(self):
        listing_text = (FIXTURES / "reddit_listing_browser_json.json").read_text(encoding="utf-8")
        thread_text = (FIXTURES / "reddit_thread_browser_json.json").read_text(encoding="utf-8")
        listing_url = build_listing_url("ExclusivelyPumping", limit=100)
        detail_url = "https://www.reddit.com/r/ExclusivelyPumping/comments/1fixture/momcozy_m5_leaking_at_work/.json"
        runner = FakeRunner({listing_url: listing_text, detail_url: thread_text})

        with TemporaryDirectory() as tmp:
            store = VocStore(Path(tmp) / "voc.sqlite3")
            store.migrate()
            summary = collect_daily_reddit(
                store,
                run_id="daily_collect_overlap_test",
                runner=runner,
                subreddits=["ExclusivelyPumping"],
                window_end_utc=datetime(2026, 7, 7, 7, 30, tzinfo=timezone.utc),
                rolling_window_hours=1,
                new_post_overlap_hours=2,
            )

            self.assertEqual(summary.ingested_threads, 1)
            self.assertEqual(len(store.fetch_threads_for_run("daily_collect_overlap_test")), 1)
            self.assertEqual(store.fetch_metric_threads_for_run("daily_collect_overlap_test"), [])
            self.assertEqual(store.fetch_metric_comments_for_run("daily_collect_overlap_test"), [])

    def test_collect_daily_reddit_skips_old_posts_before_detail_fetch(self):
        listing_text = (FIXTURES / "reddit_listing_browser_json.json").read_text(encoding="utf-8")
        listing_url = build_listing_url("ExclusivelyPumping", limit=100)
        runner = FakeRunner({listing_url: listing_text})

        with TemporaryDirectory() as tmp:
            store = VocStore(Path(tmp) / "voc.sqlite3")
            store.migrate()
            summary = collect_daily_reddit(
                store,
                run_id="daily_collect_old_post_test",
                runner=runner,
                subreddits=["ExclusivelyPumping"],
                anchor_utc=datetime(2026, 7, 6, 23, 0, tzinfo=timezone.utc),
            )

            self.assertEqual(summary.status, "empty")
            self.assertEqual(summary.discovered_posts, 1)
            self.assertEqual(summary.window_posts, 0)
            self.assertEqual(summary.detail_attempts, 0)
            self.assertEqual(store.count_for_run("reddit_threads", "daily_collect_old_post_test"), 0)

    def test_collect_daily_reddit_persists_listing_and_detail_raw_payloads(self):
        listing_text = (FIXTURES / "reddit_listing_browser_json.json").read_text(encoding="utf-8")
        thread_text = (FIXTURES / "reddit_thread_browser_json.json").read_text(encoding="utf-8")
        listing_url = build_listing_url("ExclusivelyPumping", limit=100)
        detail_url = "https://www.reddit.com/r/ExclusivelyPumping/comments/1fixture/momcozy_m5_leaking_at_work/.json"
        runner = FakeRunner({listing_url: listing_text, detail_url: thread_text})

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = VocStore(root / "voc.sqlite3")
            store.migrate()
            summary = collect_daily_reddit(
                store,
                run_id="daily_collect_raw_test",
                runner=runner,
                subreddits=["ExclusivelyPumping"],
                anchor_utc=datetime(2026, 7, 7, 23, 0, tzinfo=timezone.utc),
                raw_artifact_root=root / "raw-captures",
            )

            artifacts = list((root / "raw-captures" / "daily_collect_raw_test").glob("*.json"))
            self.assertEqual(summary.ingested_threads, 1)
            self.assertEqual(len(artifacts), 2)
            self.assertEqual(
                {artifact.read_text(encoding="utf-8") for artifact in artifacts},
                {listing_text, thread_text},
            )


if __name__ == "__main__":
    unittest.main()
