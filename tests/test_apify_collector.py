import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from reddit_voc.apify_collector import ApifyRedditClient, collect_daily_apify
from reddit_voc.storage import VocStore


class ApifyCollectorTests(unittest.TestCase):
    def test_collect_daily_apify_ingests_threads_and_comments(self) -> None:
        mock_client = MagicMock(spec=ApifyRedditClient)
        mock_client.run_actor_sync.return_value = [
            {
                "dataType": "post",
                "id": "t3_test123",
                "title": "Momcozy M5 is amazing for pumping at work",
                "body": "I love the quiet motor and hospital grade suction.",
                "communityName": "ExclusivelyPumping",
                "url": "https://reddit.com/r/ExclusivelyPumping/comments/test123/",
                "createdAt": "2026-10-26T10:00:00Z",
                "upVotes": 15,
                "numberOfComments": 1,
            },
            {
                "dataType": "comment",
                "id": "t1_comm456",
                "postId": "t3_test123",
                "parentId": "t3_test123",
                "body": "Agreed! It never leaks for me either.",
                "createdAt": "2026-10-26T10:15:00Z",
                "upVotes": 5,
            },
        ]

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "apify_test.sqlite3"
            store = VocStore(db_path)
            store.migrate()

            summary = collect_daily_apify(
                store=store,
                run_id="run_apify_test_01",
                client=mock_client,
            )

            self.assertEqual(summary.status, "success")
            self.assertEqual(summary.ingested_threads, 1)
            self.assertEqual(summary.ingested_comments, 1)

            # Verify SQLite contents
            threads = store.fetch_threads_for_run("run_apify_test_01")
            self.assertEqual(len(threads), 1)
            self.assertEqual(threads[0]["post_id"], "test123")
            self.assertEqual(threads[0]["subreddit"], "ExclusivelyPumping")
            self.assertIn("Momcozy", threads[0]["title"])

            comments = store.fetch_comments_for_run("run_apify_test_01")
            self.assertEqual(len(comments), 1)
            self.assertEqual(comments[0]["comment_id"], "comm456")
            self.assertEqual(comments[0]["post_id"], "test123")


if __name__ == "__main__":
    unittest.main()
