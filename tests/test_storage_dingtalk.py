from datetime import datetime, timezone
import unittest

from unittest.mock import patch

from reddit_voc.dingtalk import build_payload, render_markdown_digest, send_payload, with_required_keyword
from reddit_voc.models import RawCapture, RedditComment
from reddit_voc.storage import VocStore


class StorageDingTalkTests(unittest.TestCase):
    def test_store_migration_and_raw_capture_idempotent(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            store = VocStore(f"{tmp}/voc.sqlite3")
            store.migrate()
            store.upsert_run("run1", "success", "2026-07-06T20:00:00Z", "2026-07-07T20:00:00Z")
            capture = RawCapture(
                raw_capture_id="raw1",
                run_id="run1",
                source_method="manual_json",
                source_url="https://reddit.example/thread",
                captured_at_utc=datetime.now(timezone.utc),
                auth_boundary="manual_import",
                raw_payload_hash="sha256:test",
                payload_format="json",
            )
            store.insert_raw_capture(capture)
            store.insert_raw_capture(capture)
            self.assertEqual(store.table_count("raw_captures"), 1)

    def test_same_payload_is_preserved_as_a_capture_in_each_run(self):
        from dataclasses import replace
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            store = VocStore(f"{tmp}/voc.sqlite3")
            store.migrate()
            first = RawCapture(
                raw_capture_id="raw-run-1",
                run_id="run1",
                source_method="tikhub",
                source_url="https://api.example/detail",
                captured_at_utc=datetime.now(timezone.utc),
                auth_boundary="provider_api",
                raw_payload_hash="sha256:same",
                payload_format="json",
            )
            second = replace(first, raw_capture_id="raw-run-2", run_id="run2")
            store.insert_raw_capture(first)
            store.insert_raw_capture(second)

            self.assertEqual(store.table_count("raw_captures"), 2)

    def test_upsert_run_refreshes_window_and_flags(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            store = VocStore(f"{tmp}/voc.sqlite3")
            store.migrate()
            store.upsert_run("run1", "failed", "2026-07-05T23:00:00Z", "2026-07-06T23:00:00Z")
            store.upsert_run(
                "run1",
                "partial",
                "2026-07-06T23:00:00Z",
                "2026-07-07T23:00:00Z",
                provider_call=True,
                live_send=False,
            )

            run = store.get_run("run1")
            self.assertEqual(run["status"], "partial")
            self.assertEqual(run["window_start_utc"], "2026-07-06T23:00:00Z")
            self.assertEqual(run["window_end_utc"], "2026-07-07T23:00:00Z")
            self.assertTrue(run["provider_call"])
            self.assertFalse(run["live_send"])

    def test_upsert_comment_refreshes_run_scope_on_recollection(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            store = VocStore(f"{tmp}/voc.sqlite3")
            store.migrate()

            store.upsert_comment(
                RedditComment(
                    comment_id="t1_repeat",
                    post_id="post1",
                    run_id="run1",
                    raw_capture_id="raw1",
                    body="Momcozy comment from first run",
                    created_at_utc=datetime(2026, 7, 8, 1, 0, tzinfo=timezone.utc),
                )
            )
            store.upsert_comment(
                RedditComment(
                    comment_id="t1_repeat",
                    post_id="post1",
                    run_id="run2",
                    raw_capture_id="raw2",
                    body="Momcozy comment from second run",
                    created_at_utc=datetime(2026, 7, 9, 1, 0, tzinfo=timezone.utc),
                    score=3,
                    depth=1,
                )
            )

            self.assertEqual(store.count_for_run("reddit_comments", "run1"), 0)
            self.assertEqual(store.count_for_run("reddit_comments", "run2"), 1)
            stored = store.fetch_comments_for_run("run2")[0]
            self.assertEqual(stored["raw_capture_id"], "raw2")
            self.assertEqual(stored["body"], "Momcozy comment from second run")
            self.assertEqual(stored["score"], 3)

    def test_dingtalk_dry_run_payload_has_no_live_send(self):
        markdown = render_markdown_digest(
            title="Digest",
            summary_lines=["provider_call=false", "live_send=false"],
            artifact_paths=["outputs/example.json"],
        )
        payload = build_payload(title="Digest", markdown=markdown)
        self.assertEqual(payload.body["msgtype"], "markdown")
        self.assertFalse(payload.live_send)
        self.assertIsNone(payload.signed_url)
        self.assertTrue(payload.message_hash.startswith("sha256:"))

    def test_required_keyword_is_injected_when_absent(self):
        title, markdown = with_required_keyword(
            title="Momcozy Reddit VOC",
            markdown="# Momcozy Reddit VOC",
            required_keyword="LL",
        )

        self.assertNotIn("LL", title)
        self.assertIn("<!-- LL -->", markdown)

    def test_send_payload_marks_nonzero_dingtalk_errcode_rejected(self):
        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self, _limit=None):
                return b'{"errcode":310000,"errmsg":"keywords not in content"}'

        payload = build_payload(title="Digest", markdown="# Digest", live_send=True)
        with patch("reddit_voc.dingtalk.urlopen", return_value=FakeResponse()):
            result = send_payload(
                webhook_url=(
                    "https://oapi.dingtalk.com/robot/send?access_token=unit"
                ),
                payload=payload,
            )

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.http_status, 200)


if __name__ == "__main__":
    unittest.main()
