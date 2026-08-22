from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from reddit_voc.backfill_models import BackfillManifest, required_lanes_sha256
from reddit_voc.backfill_storage import BackfillConflictError, BackfillStore
from reddit_voc.keywords import keyword_rules_sha256


NOW = datetime(2026, 7, 14, 8, tzinfo=timezone.utc)
RUN_ID = "existing_budget_resume_test"


class ExistingBudgetResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = BackfillStore(Path(self.temporary.name) / "backfill.sqlite3")
        self.store.migrate()
        lanes_sha = required_lanes_sha256(
            search_terms=("Momcozy",),
            subreddits=("ExclusivelyPumping",),
            include_subreddit_sweep=True,
        )
        self.store.create_manifest(
            BackfillManifest(
                run_id=RUN_ID,
                status="prepared",
                window_start_utc="2024-12-31T16:00:00+00:00",
                requested_end_utc="2026-07-11T16:00:00+00:00",
                effective_end_utc="2026-07-11T04:17:09+00:00",
                search_terms=("Momcozy",),
                subreddits=("ExclusivelyPumping",),
                include_subreddit_sweep=True,
                required_lanes_sha256=lanes_sha,
                keyword_config_sha256=keyword_rules_sha256(),
                max_provider_requests=10,
                provider_request_count=0,
                provider_call=False,
                live_send=False,
                created_at_utc=NOW.isoformat(),
                updated_at_utc=NOW.isoformat(),
            )
        )
        for offset in range(3):
            instant = NOW + timedelta(seconds=offset)
            number = self.store.reserve_provider_request(
                RUN_ID, "/api/v1/reddit/app/fetch_post_comments", instant
            )
            self.assertEqual(number, offset + 1)
            self.store.mark_provider_attempt_sent(RUN_ID, number, instant)
            self.store.complete_provider_attempt(
                RUN_ID,
                number,
                status="succeeded",
                completed_at_utc=instant,
                http_status=200,
            )
        self.store.set_backfill_status(RUN_ID, "partial", NOW)
        self.scope_sha = lanes_sha

    def _record(self, *, authorization: str = "a" * 64, state: str = "b" * 64):
        return self.store.record_existing_budget_resume_authorization(
            RUN_ID,
            authorization_sha256=authorization,
            expected_source_database_sha256="c" * 64,
            expected_provider_request_count=3,
            max_provider_requests=10,
            discovery_request_ceiling=3,
            lane_page_ceilings_sha256="d" * 64,
            candidate_state_sha256=state,
            include_subreddit_sweep=True,
            required_lanes_sha256=self.scope_sha,
            applied_at_utc=NOW,
        )

    def test_records_once_without_changing_budget_or_provider_ledger(self) -> None:
        self.assertTrue(self._record())

        with sqlite3.connect(self.store.path) as connection:
            row = connection.execute(
                "SELECT expected_provider_request_count, max_provider_requests, "
                "discovery_request_ceiling, candidate_state_sha256 "
                "FROM backfill_collection_resumes WHERE run_id=?",
                (RUN_ID,),
            ).fetchone()
            manifest = connection.execute(
                "SELECT max_provider_requests, provider_request_count "
                "FROM backfill_manifests WHERE run_id=?",
                (RUN_ID,),
            ).fetchone()
            attempts = connection.execute(
                "SELECT COUNT(*) FROM backfill_provider_attempts WHERE run_id=?",
                (RUN_ID,),
            ).fetchone()[0]
        self.assertEqual(row, (3, 10, 3, "b" * 64))
        self.assertEqual(manifest, (10, 3))
        self.assertEqual(attempts, 3)

    def test_same_authorization_is_idempotent_in_legal_forward_state(self) -> None:
        self.assertTrue(self._record())
        instant = NOW + timedelta(seconds=10)
        number = self.store.reserve_provider_request(
            RUN_ID, "/api/v1/reddit/app/fetch_post_comments", instant
        )
        self.store.mark_provider_attempt_sent(RUN_ID, number, instant)
        self.store.complete_provider_attempt(
            RUN_ID,
            number,
            status="succeeded",
            completed_at_utc=instant,
            http_status=200,
        )

        self.assertFalse(self._record())

    def test_rejects_content_drift_and_duplicate_start_count(self) -> None:
        self.assertTrue(self._record())
        with self.assertRaises(BackfillConflictError):
            self._record(state="e" * 64)
        with self.assertRaises(BackfillConflictError):
            self._record(authorization="f" * 64)

    def test_rejects_nonmatching_live_state_before_insert(self) -> None:
        with self.assertRaisesRegex(ValueError, "expected state changed"):
            self.store.record_existing_budget_resume_authorization(
                RUN_ID,
                authorization_sha256="a" * 64,
                expected_source_database_sha256="c" * 64,
                expected_provider_request_count=2,
                max_provider_requests=10,
                discovery_request_ceiling=2,
                lane_page_ceilings_sha256="d" * 64,
                candidate_state_sha256="b" * 64,
                include_subreddit_sweep=True,
                required_lanes_sha256=self.scope_sha,
                applied_at_utc=NOW,
            )


if __name__ == "__main__":
    unittest.main()
