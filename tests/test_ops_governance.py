import json
import os
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from reddit_voc import cli


def run_cli(argv):
    stream = StringIO()
    with redirect_stdout(stream):
        rc = cli.main(argv)
    return rc, json.loads(stream.getvalue())


class OpsGovernanceTests(unittest.TestCase):
    def test_missed_run_check_reports_covered_window(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "voc.sqlite3"
            out = Path(tmp) / "out"
            run_id = "ops_window_run"
            run_cli(
                [
                    "run-adapter-fixture-loop",
                    "--database",
                    str(db),
                    "--output-dir",
                    str(out),
                    "--run-id",
                    run_id,
                ]
            )

            rc, result = run_cli(
                [
                    "missed-run-check",
                    "--database",
                    str(db),
                    "--anchor-utc",
                    "2026-07-07T23:00:00+00:00",
                ]
            )

            self.assertEqual(rc, 0)
            self.assertEqual(result["status"], "covered")
            self.assertEqual(result["matching_run_ids"], [run_id])
            self.assertFalse(result["provider_call"])
            self.assertFalse(result["live_send"])

    def test_missed_run_check_reports_missing_window(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "voc.sqlite3"
            cli.VocStore(db).migrate()

            rc, result = run_cli(
                [
                    "missed-run-check",
                    "--database",
                    str(db),
                    "--anchor-utc",
                    "2026-07-07T23:00:00+00:00",
                ]
            )

            self.assertEqual(rc, 2)
            self.assertEqual(result["status"], "missed")
            self.assertEqual(result["matching_run_ids"], [])

    def test_issue_summary_flags_partial_coverage_without_live_send(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "voc.sqlite3"
            out = Path(tmp) / "out"
            run_id = "ops_issue_run"
            run_cli(
                [
                    "run-adapter-fixture-loop",
                    "--database",
                    str(db),
                    "--output-dir",
                    str(out),
                    "--run-id",
                    run_id,
                ]
            )

            rc, result = run_cli(["issue-summary", "--database", str(db), "--run-id", run_id])

            self.assertEqual(rc, 1)
            self.assertEqual(result["operational_state"], "attention")
            self.assertEqual(result["issues"][0]["code"], "partial_coverage")
            self.assertFalse(result["provider_call"])
            self.assertFalse(result["live_send"])

    def test_prune_artifacts_removes_oldest_matching_logs_only_when_applied(self):
        with TemporaryDirectory() as tmp:
            log_dir = Path(tmp) / "logs"
            log_dir.mkdir()
            newest = log_dir / "newest.log"
            middle = log_dir / "middle.log"
            oldest = log_dir / "oldest.log"
            note = log_dir / "note.txt"
            for index, path in enumerate([oldest, middle, newest, note], start=1):
                path.write_text(path.name, encoding="utf-8")
                os.utime(path, (index, index))

            rc, result = run_cli(
                [
                    "prune-artifacts",
                    "--path",
                    str(log_dir),
                    "--pattern",
                    "*.log",
                    "--keep-last",
                    "2",
                    "--apply",
                ]
            )

            self.assertEqual(rc, 0)
            self.assertTrue(newest.exists())
            self.assertTrue(middle.exists())
            self.assertFalse(oldest.exists())
            self.assertTrue(note.exists())
            self.assertEqual(result["results"][0]["removed"], [str(oldest)])


if __name__ == "__main__":
    unittest.main()
