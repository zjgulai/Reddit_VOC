from __future__ import annotations

from datetime import datetime, timezone
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from reddit_voc.browser_runner import BrowserJsonCaptureResult
from reddit_voc.collector import build_listing_url, collect_daily_reddit
from reddit_voc.cli import main
from reddit_voc.daily_source_batch import DailySourceBatchError, build_daily_source_batch
from reddit_voc.report_contracts import canonical_json_bytes
from reddit_voc.source_batch import load_source_batch
from reddit_voc.storage import VocStore


FIXTURES = Path(__file__).parent / "fixtures"


class _Runner:
    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = responses

    def capture_json_url(self, url: str) -> BrowserJsonCaptureResult:
        raw_text = self.responses.get(url, "")
        return BrowserJsonCaptureResult(
            target_url=url,
            page_url=url,
            page_title="fixture",
            raw_text=raw_text,
            browser_status="ok" if raw_text else "blocked",
            blocked_reason=None if raw_text else "missing_fixture",
        )


def _write_profiles(root: Path) -> tuple[Path, Path]:
    query = root / "query-profile.json"
    coverage = root / "coverage-profile.json"
    query.write_bytes(
        canonical_json_bytes(
            {
                "schema_version": "reddit_voc_query_profile_v1",
                "search_terms": ["Momcozy"],
                "subreddits": ["ExclusivelyPumping"],
                "version": "momcozy-query-v2",
            }
        )
        + b"\n"
    )
    coverage.write_bytes(
        canonical_json_bytes(
            {
                "active_thread_policy": {
                    "normal_max_age_days": 30,
                    "normal_quiet_days": 7,
                    "priority_max_age_days": 90,
                    "priority_quiet_days": 30,
                    "priority_reason_codes": [
                        "admin_exposure",
                        "brand_intervention",
                        "content_compliance",
                        "high_risk",
                        "manual_case",
                    ],
                },
                "new_post_overlap_hours": 2,
                "schema_version": "reddit_voc_coverage_profile_v1",
                "version": "momcozy-coverage-v2",
            }
        )
        + b"\n"
    )
    return query, coverage


class DailySourceBatchExportTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = VocStore(self.root / "voc.sqlite3")
        self.store.migrate()
        self.raw_root = self.root / "raw-captures"
        listing_text = (FIXTURES / "reddit_listing_browser_json.json").read_text(encoding="utf-8")
        thread_text = (FIXTURES / "reddit_thread_browser_json.json").read_text(encoding="utf-8")
        listing_url = build_listing_url("ExclusivelyPumping", limit=100)
        detail_url = "https://www.reddit.com/r/ExclusivelyPumping/comments/1fixture/momcozy_m5_leaking_at_work/.json"
        summary = collect_daily_reddit(
            self.store,
            run_id="daily-20260717-0700",
            runner=_Runner({listing_url: listing_text, detail_url: thread_text}),
            subreddits=["ExclusivelyPumping"],
            anchor_utc=datetime(2026, 7, 7, 23, 0, tzinfo=timezone.utc),
            raw_artifact_root=self.raw_root,
        )
        self.summary = summary.as_dict()
        self.query_profile, self.coverage_profile = _write_profiles(self.root)

    def test_builds_a_consumable_daily_source_batch(self) -> None:
        result = build_daily_source_batch(
            self.store,
            run_id="daily-20260717-0700",
            raw_artifact_root=self.raw_root,
            output_root=self.root / "source-batches",
            query_profile_path=self.query_profile,
            coverage_profile_path=self.coverage_profile,
            collector_summary=self.summary,
        )

        batch = load_source_batch(result.manifest_path, result.batch_root, require_consumable=True)
        posts = [json.loads(line) for line in (result.batch_root / "posts.jsonl").read_text().splitlines()]
        comments = [json.loads(line) for line in (result.batch_root / "comments.jsonl").read_text().splitlines()]
        self.assertEqual(result.write_status, "created")
        self.assertEqual(batch.counts.posts, 1)
        self.assertEqual(batch.counts.comments, 2)
        self.assertEqual(posts[0]["post_id"], "t3_1fixture")
        self.assertTrue(all(row["comment_id"].startswith("t1_") for row in comments))
        self.assertEqual(batch.window.new_post_discovery_start_utc.hour, 21)

    def test_same_daily_input_returns_no_change(self) -> None:
        arguments = {
            "store": self.store,
            "run_id": "daily-20260717-0700",
            "raw_artifact_root": self.raw_root,
            "output_root": self.root / "source-batches",
            "query_profile_path": self.query_profile,
            "coverage_profile_path": self.coverage_profile,
            "collector_summary": self.summary,
        }
        first = build_daily_source_batch(**arguments)
        second = build_daily_source_batch(**arguments)

        self.assertEqual(first.manifest_sha256, second.manifest_sha256)
        self.assertEqual(second.write_status, "no_change")

    def test_missing_raw_payload_fails_closed(self) -> None:
        next(self.raw_root.rglob("*.json")).unlink()

        with self.assertRaisesRegex(DailySourceBatchError, "daily raw artifact unavailable"):
            build_daily_source_batch(
                self.store,
                run_id="daily-20260717-0700",
                raw_artifact_root=self.raw_root,
                output_root=self.root / "source-batches",
                query_profile_path=self.query_profile,
                coverage_profile_path=self.coverage_profile,
                collector_summary=self.summary,
            )

    def test_cli_builds_the_daily_source_batch(self) -> None:
        output_dir = self.root / "outputs"
        output_dir.mkdir()
        summary_path = output_dir / "daily-20260717-0700-collector-summary.json"
        summary_path.write_text(json.dumps(self.summary) + "\n", encoding="utf-8")
        stdout = StringIO()

        with redirect_stdout(stdout):
            return_code = main(
                [
                    "build-daily-source-batch",
                    "--database",
                    str(self.store.path),
                    "--output-dir",
                    str(output_dir),
                    "--run-id",
                    "daily-20260717-0700",
                    "--raw-artifact-root",
                    str(self.raw_root),
                    "--query-profile",
                    str(self.query_profile),
                    "--coverage-profile",
                    str(self.coverage_profile),
                ]
            )

        result = json.loads(stdout.getvalue())
        self.assertEqual(return_code, 0)
        self.assertEqual(result["write_status"], "created")
        self.assertTrue(result["production_unchanged"])
        self.assertFalse(result["database_write"])


if __name__ == "__main__":
    unittest.main()
