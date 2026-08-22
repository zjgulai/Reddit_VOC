import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from reddit_voc import cli


class ExporterStatusTests(unittest.TestCase):
    def test_export_run_writes_posts_and_comments_jsonl_csv(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "voc.sqlite3"
            out = Path(tmp) / "out"

            rc_loop = cli.main(
                [
                    "run-adapter-fixture-loop",
                    "--database",
                    str(db),
                    "--output-dir",
                    str(out),
                    "--run-id",
                    "adapter_fixture_run_20260707",
                ]
            )
            rc_export = cli.main(
                [
                    "export-run",
                    "--database",
                    str(db),
                    "--output-dir",
                    str(out),
                    "--run-id",
                    "adapter_fixture_run_20260707",
                ]
            )

            posts_jsonl = out / "adapter_fixture_run_20260707-posts.jsonl"
            comments_jsonl = out / "adapter_fixture_run_20260707-comments.jsonl"
            analysis_jsonl = out / "adapter_fixture_run_20260707-analysis.jsonl"
            posts_csv = out / "adapter_fixture_run_20260707-posts.csv"
            comments_csv = out / "adapter_fixture_run_20260707-comments.csv"
            analysis_csv = out / "adapter_fixture_run_20260707-analysis.csv"

            self.assertEqual(rc_loop, 0)
            self.assertEqual(rc_export, 0)
            self.assertTrue(posts_jsonl.exists())
            self.assertTrue(comments_jsonl.exists())
            self.assertTrue(analysis_jsonl.exists())
            self.assertTrue(posts_csv.exists())
            self.assertTrue(comments_csv.exists())
            self.assertTrue(analysis_csv.exists())
            post_rows = [json.loads(line) for line in posts_jsonl.read_text(encoding="utf-8").splitlines()]
            comment_rows = [json.loads(line) for line in comments_jsonl.read_text(encoding="utf-8").splitlines()]
            analysis_rows = [json.loads(line) for line in analysis_jsonl.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(post_rows), 1)
            self.assertEqual(len(comment_rows), 2)
            self.assertEqual(len(analysis_rows), 3)
            self.assertEqual(post_rows[0]["coverage_grade"], "partial")
            self.assertEqual(comment_rows[0]["comment_id"], "t1_c1")
            self.assertIn("/c1/", comment_rows[0]["source_url"])
            self.assertEqual(analysis_rows[0]["sentiment_label"], "negative")
            self.assertIn("source_url", analysis_rows[0])

            with posts_csv.open(encoding="utf-8", newline="") as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 1)
            with comments_csv.open(encoding="utf-8", newline="") as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 2)
            with analysis_csv.open(encoding="utf-8", newline="") as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 3)

    def test_status_summary_reports_partial_run_counts(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "voc.sqlite3"
            out = Path(tmp) / "out"
            cli.main(
                [
                    "run-adapter-fixture-loop",
                    "--database",
                    str(db),
                    "--output-dir",
                    str(out),
                    "--run-id",
                    "adapter_fixture_run_20260707",
                ]
            )
            summary = cli.summarize_run_status(
                cli.VocStore(db),
                "adapter_fixture_run_20260707",
            )

            self.assertEqual(summary["status"], "partial")
            self.assertFalse(summary["provider_call"])
            self.assertFalse(summary["live_send"])
            self.assertEqual(summary["counts"]["threads"], 1)
            self.assertEqual(summary["counts"]["comments"], 2)
            self.assertEqual(summary["coverage"]["partial"], 1)

    def test_status_summary_missing_run_is_unavailable(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "voc.sqlite3"
            store = cli.VocStore(db)
            store.migrate()
            summary = cli.summarize_run_status(store, "missing")

            self.assertEqual(summary["status"], "failed")
            self.assertEqual(summary["reason"], "run_not_found")
            self.assertFalse(summary["provider_call"])
            self.assertFalse(summary["live_send"])


if __name__ == "__main__":
    unittest.main()
