from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from reddit_voc.backfill_archive import PrivateRawArchive
from reddit_voc.backfill_models import BackfillManifest
from reddit_voc.backfill_source_batch import build_backfill_source_batch
from reddit_voc.backfill_storage import BackfillStore
from reddit_voc.models import RawCapture, RedditComment, RedditThread
from reddit_voc.source_batch import load_source_batch


class BackfillSourceBatchExportTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.database = self.root / "backfill.sqlite3"
        self.archive_root = self.root / "private-raw"
        self.run_id = "backfill-momcozy-20260717"
        self.store = BackfillStore(self.database)
        self.store.migrate()
        self.store.create_manifest(
            BackfillManifest(
                run_id=self.run_id,
                status="seed_complete",
                window_start_utc="2025-01-01T00:00:00+00:00",
                requested_end_utc="2026-07-17T00:00:00+00:00",
                effective_end_utc="2026-07-17T00:00:00+00:00",
                search_terms=("Momcozy",),
                subreddits=("ExclusivelyPumping",),
                include_subreddit_sweep=False,
                required_lanes_sha256="1" * 64,
                keyword_config_sha256="2" * 64,
                max_provider_requests=0,
                provider_request_count=0,
                provider_call=False,
                live_send=False,
                created_at_utc="2026-07-17T00:00:00+00:00",
                updated_at_utc="2026-07-17T00:00:00+00:00",
            )
        )
        payload = json.dumps({"fixture": True}, separators=(",", ":")).encode()
        captured_at = datetime(2026, 7, 17, tzinfo=timezone.utc)
        archive = PrivateRawArchive(self.archive_root)
        self.archive_root = archive.root
        artifact = archive.write(
            run_id=self.run_id,
            artifact_kind="seed",
            lane_type="seed",
            lane_key="fixture",
            identity="fixture.json",
            payload=payload,
            raw_capture_id="raw_fixture_1",
            parser_kind="reddit_json",
            source_method="seed_file",
            source_url="file:fixture.json",
            source_endpoint="local_seed",
            captured_at_utc=captured_at,
        )
        capture = RawCapture(
            raw_capture_id="raw_fixture_1",
            run_id=self.run_id,
            source_method="seed_file",
            source_url="file:fixture.json",
            captured_at_utc=captured_at,
            auth_boundary="local_file",
            raw_payload_hash="sha256:" + artifact.payload_sha256,
            payload_format="json",
        )
        self.store.persist_raw_capture_artifact(capture, artifact)
        self.store.insert_entity_bundle(
            captures=(),
            threads=(
                RedditThread(
                    post_id="abc123",
                    run_id=self.run_id,
                    raw_capture_id="raw_fixture_1",
                    subreddit="ExclusivelyPumping",
                    title="Momcozy fixture",
                    source_url="https://reddit.com/r/ExclusivelyPumping/comments/abc123/x/",
                    created_at_utc=captured_at,
                    parsed_comment_count=1,
                    coverage_grade="full",
                    matched_keywords=["Momcozy"],
                ),
            ),
            comments=(
                RedditComment(
                    comment_id="def456",
                    post_id="abc123",
                    run_id=self.run_id,
                    raw_capture_id="raw_fixture_1",
                    body="fixture comment",
                    created_at_utc=captured_at,
                    parent_id="abc123",
                ),
            ),
            analyses=(),
        )

    def test_seed_complete_exports_as_partial_with_explicit_coverage_debt(self) -> None:
        result = build_backfill_source_batch(
            database_path=self.database,
            archive_root=self.archive_root,
            run_id=self.run_id,
            output_root=self.root / "source-batches",
        )

        batch = load_source_batch(result.manifest_path, result.batch_root, require_consumable=True)
        issues = [
            json.loads(line)
            for line in (result.batch_root / "issues.jsonl").read_text().splitlines()
        ]
        self.assertEqual(batch.status, "partial")
        self.assertEqual(batch.counts.posts, 1)
        self.assertEqual(batch.counts.comments, 1)
        self.assertEqual(issues[0]["issue_id"], "historical_seed_only_coverage")
        self.assertFalse(batch.boundaries.database_write)

    def test_same_backfill_input_returns_no_change(self) -> None:
        arguments = {
            "database_path": self.database,
            "archive_root": self.archive_root,
            "run_id": self.run_id,
            "output_root": self.root / "source-batches",
        }
        first = build_backfill_source_batch(**arguments)
        second = build_backfill_source_batch(**arguments)

        self.assertEqual(first.manifest_sha256, second.manifest_sha256)
        self.assertEqual(second.write_status, "no_change")


if __name__ == "__main__":
    unittest.main()
