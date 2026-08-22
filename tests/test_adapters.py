from datetime import timezone
import json
from pathlib import Path
import unittest

from reddit_voc.adapters import BrowserJsonAdapter, BrowserJsonBlockedError, RssDiscoveryAdapter


FIXTURES = Path(__file__).parent / "fixtures"


class AdapterTests(unittest.TestCase):
    def test_browser_json_thread_parser_preserves_evidence_and_coverage(self):
        raw_text = (FIXTURES / "reddit_thread_browser_json.json").read_text(encoding="utf-8")
        adapter = BrowserJsonAdapter()
        capture = adapter.build_raw_capture(
            raw_text,
            run_id="run_adapter_test",
            source_url="https://www.reddit.com/r/ExclusivelyPumping/comments/1fixture/momcozy_m5_leaking_at_work/.json",
        )
        parsed = adapter.parse_thread_text(
            raw_text,
            run_id=capture.run_id,
            raw_capture_id=capture.raw_capture_id,
            source_url=capture.source_url,
        )

        self.assertEqual(capture.source_method, "browser_json")
        self.assertEqual(capture.auth_boundary, "browser_login")
        self.assertFalse(capture.secrets_written)
        self.assertEqual(parsed.thread.post_id, "1fixture")
        self.assertEqual(parsed.thread.subreddit, "ExclusivelyPumping")
        self.assertEqual(parsed.thread.parsed_comment_count, 2)
        self.assertEqual(parsed.thread.more_node_count, 1)
        self.assertEqual(parsed.thread.coverage_grade, "partial")
        self.assertIn("Momcozy", parsed.thread.matched_keywords)
        self.assertEqual([comment.comment_id for comment in parsed.comments], ["t1_c1", "t1_c2"])
        self.assertEqual(parsed.comments[1].parent_id, "t1_c1")
        self.assertIn("Elvie", parsed.comments[1].matched_keywords)

    def test_browser_json_listing_parser_discovers_posts(self):
        raw_text = (FIXTURES / "reddit_listing_browser_json.json").read_text(encoding="utf-8")
        posts = BrowserJsonAdapter().parse_listing_text(raw_text)

        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].post_id, "1fixture")
        self.assertEqual(posts[0].subreddit, "ExclusivelyPumping")
        self.assertEqual(posts[0].source_method, "browser_json")
        self.assertEqual(posts[0].num_comments_reported, 3)
        self.assertEqual(posts[0].coverage_grade, "discovery_only")

    def test_rss_parser_is_discovery_only(self):
        raw_text = (FIXTURES / "reddit_feed.xml").read_text(encoding="utf-8")
        posts = RssDiscoveryAdapter().parse_feed_text(raw_text)

        self.assertEqual(len(posts), 2)
        self.assertEqual(posts[0].post_id, "1fixture")
        self.assertEqual(posts[0].subreddit, "ExclusivelyPumping")
        self.assertEqual(posts[0].source_method, "rss")
        self.assertEqual(posts[0].coverage_grade, "discovery_only")
        self.assertEqual(posts[0].created_at_utc.tzinfo, timezone.utc)

    def test_browser_json_blocked_text_is_classified_before_json_parse(self):
        adapter = BrowserJsonAdapter()

        with self.assertRaises(BrowserJsonBlockedError) as caught:
            adapter.parse_listing_text("<html><body>Log in to continue</body></html>")

        self.assertEqual(caught.exception.browser_status, "login_required")
        self.assertEqual(caught.exception.blocked_reason, "html_login_wall")

    def test_thread_coverage_post_only_and_full_edges(self):
        raw_text = (FIXTURES / "reddit_thread_browser_json.json").read_text(encoding="utf-8")
        payload = json.loads(raw_text)
        adapter = BrowserJsonAdapter()

        payload[1]["data"]["children"] = []
        parsed = adapter.parse_thread_payload(
            payload,
            run_id="run_adapter_test",
            raw_capture_id="raw1",
            source_url="https://www.reddit.com/r/ExclusivelyPumping/comments/1fixture/momcozy_m5_leaking_at_work/.json",
        )
        self.assertEqual(parsed.thread.coverage_grade, "post_only")

        payload[0]["data"]["children"][0]["data"]["num_comments"] = 0
        parsed_empty = adapter.parse_thread_payload(
            payload,
            run_id="run_adapter_test",
            raw_capture_id="raw1",
            source_url="https://www.reddit.com/r/ExclusivelyPumping/comments/1fixture/momcozy_m5_leaking_at_work/.json",
        )
        self.assertEqual(parsed_empty.thread.coverage_grade, "full")

    def test_deleted_comment_does_not_store_author_hash(self):
        raw_text = (FIXTURES / "reddit_thread_browser_json.json").read_text(encoding="utf-8")
        payload = json.loads(raw_text)
        deleted_comment = payload[1]["data"]["children"][0]["data"]
        deleted_comment["body"] = "[deleted]"
        deleted_comment["author"] = "sample-deleted-author"

        parsed = BrowserJsonAdapter().parse_thread_payload(
            payload,
            run_id="run_adapter_test",
            raw_capture_id="raw1",
            source_url="https://www.reddit.com/r/ExclusivelyPumping/comments/1fixture/momcozy_m5_leaking_at_work/.json",
        )

        self.assertTrue(parsed.comments[0].deleted_or_removed)
        self.assertIsNone(parsed.comments[0].author_hash)


if __name__ == "__main__":
    unittest.main()
