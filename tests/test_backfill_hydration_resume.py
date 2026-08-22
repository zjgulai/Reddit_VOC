from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from reddit_voc.backfill_models import (
    BackfillCheckpoint,
    BackfillManifest,
    RawArtifactMetadata,
)
from reddit_voc.backfill_storage import (
    BackfillConflictError,
    BackfillSchemaError,
    BackfillStore,
)
from reddit_voc.backfill_validation import operational_snapshot_sha256
from reddit_voc.models import RawCapture, RedditThread


NOW = datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc)
RUN_ID = "backfill_hydration_resume_test"
AUTHORIZATION_SHA256 = "c" * 64


def make_manifest() -> BackfillManifest:
    return BackfillManifest(
        run_id=RUN_ID,
        status="prepared",
        window_start_utc="2024-12-31T16:00:00+00:00",
        requested_end_utc="2026-07-11T16:00:00+00:00",
        effective_end_utc="2026-07-11T16:00:00+00:00",
        search_terms=("Momcozy",),
        subreddits=("ExclusivelyPumping",),
        include_subreddit_sweep=True,
        required_lanes_sha256="a" * 64,
        keyword_config_sha256="b" * 64,
        max_provider_requests=2,
        provider_request_count=0,
        provider_call=False,
        live_send=False,
        created_at_utc=NOW.isoformat(),
        updated_at_utc=NOW.isoformat(),
    )


def make_artifact(
    *,
    artifact_id: str,
    lane_type: str,
    lane_key: str,
    page_number: int,
) -> RawArtifactMetadata:
    digest = sha256(artifact_id.encode()).hexdigest()
    contracts = {
        "dynamic_search": (
            "discovery",
            "tikhub_discovery",
            "tikhub_dynamic_search",
            "/api/v1/reddit/app/fetch_dynamic_search",
        ),
        "detail_batch": (
            "detail",
            "tikhub_detail",
            "tikhub_detail",
            "/api/v1/reddit/app/fetch_post_details_batch_large",
        ),
        "comments": (
            "comments",
            "tikhub_comments",
            "tikhub_comments",
            "/api/v1/reddit/app/fetch_post_comments",
        ),
    }
    artifact_kind, parser_kind, source_method, endpoint = contracts[lane_type]
    return RawArtifactMetadata(
        artifact_id=artifact_id,
        run_id=RUN_ID,
        artifact_kind=artifact_kind,
        lane_type=lane_type,
        lane_key_hash=sha256(lane_key.encode()).hexdigest(),
        identity_hash=digest,
        raw_capture_id=f"capture-{artifact_id}",
        parser_kind=parser_kind,
        source_method=source_method,
        source_url=f"tikhub://{digest}",
        source_endpoint=endpoint,
        payload_sha256=digest,
        relative_path=f"{RUN_ID}/{lane_type}/{artifact_id}.json.gz",
        captured_at_utc=NOW.isoformat(),
        page_number=page_number,
        request_cursor=None,
        response_cursor="cursor-1" if lane_type == "dynamic_search" else None,
    )


class BackfillHydrationResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.store = self.new_store("default")

    def new_store(self, label: str) -> BackfillStore:
        store = BackfillStore(
            Path(self.temporary_directory.name) / f"{label}.sqlite3"
        )
        store.migrate()
        return store

    def prepare_authorized_state(
        self,
        store: BackfillStore,
        *,
        post_ids: tuple[str, ...] = ("post-1", "post-2"),
    ) -> tuple[object, ...]:
        store.create_manifest(make_manifest())
        lane_key = "Momcozy"
        discovery = make_artifact(
            artifact_id="discovery-source",
            lane_type="dynamic_search",
            lane_key=lane_key,
            page_number=1,
        )
        store.insert_raw_artifact(discovery)
        for ordinal, post_id in enumerate(post_ids):
            store.record_discovery_occurrence(
                run_id=RUN_ID,
                lane_type="dynamic_search",
                lane_key=lane_key,
                page_number=1,
                ordinal=ordinal,
                post_id=post_id,
                source_url=f"https://reddit.com/comments/{post_id}/title/",
                post_created_at_utc=NOW - timedelta(days=1),
                raw_artifact_id=discovery.artifact_id,
                discovered_at_utc=NOW,
                base_disposition="eligible",
            )
        batches = store.prepare_detail_batches(
            run_id=RUN_ID,
            post_ids=post_ids,
            created_at_utc=NOW + timedelta(seconds=1),
        )
        for batch in batches:
            store.finish_detail_batch(
                run_id=RUN_ID,
                batch_id=batch.batch_id,
                status="failed",
                stop_reason="budget_exhausted",
                updated_at_utc=NOW + timedelta(seconds=2),
            )
        for post_id in post_ids:
            store.finalize_candidate(
                run_id=RUN_ID,
                post_id=post_id,
                expected_statuses=("pending",),
                status="budget_deferred",
                status_reason="budget_exhausted",
                updated_at_utc=NOW + timedelta(seconds=3),
            )
        for request_number in (1, 2):
            at = NOW + timedelta(seconds=10 + request_number)
            self.assertEqual(
                store.reserve_provider_request(RUN_ID, "/search", at),
                request_number,
            )
            store.mark_provider_attempt_sent(RUN_ID, request_number, at)
            store.complete_provider_attempt(
                RUN_ID,
                request_number,
                status="succeeded",
                completed_at_utc=at,
            )
        store.set_backfill_status(RUN_ID, "partial", NOW + timedelta(minutes=1))
        self.assertTrue(
            store.extend_full_collection_budget(
                RUN_ID,
                expected_provider_request_count=2,
                expected_max_provider_requests=2,
                new_max_provider_requests_total=4,
                discovery_request_ceiling=3,
                lane_page_ceilings_sha256="d" * 64,
                include_subreddit_sweep=True,
                required_lanes_sha256="a" * 64,
                authorization_sha256=AUTHORIZATION_SHA256,
                updated_at_utc=NOW + timedelta(minutes=2),
            )
        )
        return batches

    def state(self, store: BackfillStore) -> tuple[object, ...]:
        with store.connect() as connection:
            candidates = [
                tuple(row)
                for row in connection.execute(
                    "SELECT post_id, status, status_reason, updated_at_utc "
                    "FROM backfill_candidates ORDER BY post_id"
                ).fetchall()
            ]
            batches = [
                tuple(row)
                for row in connection.execute(
                    "SELECT batch_id, batch_number, status, artifact_id, "
                    "stop_reason, updated_at_utc FROM backfill_detail_batches "
                    "ORDER BY batch_number"
                ).fetchall()
            ]
            resumes = [
                tuple(row)
                for row in connection.execute(
                    "SELECT run_id, authorization_sha256, candidate_post_ids_json, "
                    "candidate_post_ids_sha256, batch_membership_json, "
                    "batch_membership_sha256, candidate_count, batch_count, "
                    "applied_at_utc FROM backfill_hydration_resumes"
                ).fetchall()
            ]
        return candidates, batches, resumes

    def test_migrate_adds_exact_additive_resume_ledger(self) -> None:
        with self.store.connect() as connection:
            columns = [
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(backfill_hydration_resumes)"
                ).fetchall()
            ]
            foreign_keys = {
                (row["table"], row["from"], row["to"])
                for row in connection.execute(
                    "PRAGMA foreign_key_list(backfill_hydration_resumes)"
                ).fetchall()
            }
        self.assertEqual(
            columns,
            [
                "run_id",
                "authorization_sha256",
                "candidate_post_ids_json",
                "candidate_post_ids_sha256",
                "batch_membership_json",
                "batch_membership_sha256",
                "candidate_count",
                "batch_count",
                "applied_at_utc",
            ],
        )
        self.assertEqual(
            foreign_keys,
            {
                (
                    "backfill_budget_extensions",
                    "run_id",
                    "run_id",
                ),
                (
                    "backfill_budget_extensions",
                    "authorization_sha256",
                    "authorization_sha256",
                ),
            },
        )

        with self.store.connect() as connection:
            connection.execute("DROP TABLE backfill_hydration_resumes")
            connection.execute(
                "CREATE TABLE backfill_hydration_resumes(run_id TEXT PRIMARY KEY)"
            )
        with self.assertRaises(BackfillSchemaError):
            self.store.migrate()

    def test_resume_is_atomic_and_same_authorization_is_exact_idempotent(self) -> None:
        batches = self.prepare_authorized_state(self.store)
        applied_at = NOW + timedelta(minutes=3)

        self.assertTrue(
            self.store.resume_budget_exhausted_hydration(
                RUN_ID,
                authorization_sha256=AUTHORIZATION_SHA256,
                updated_at_utc=applied_at,
            )
        )
        first_state = self.state(self.store)
        candidate_json = '["post-1","post-2"]'
        membership_json = json.dumps(
            [
                [
                    batches[0].batch_id,
                    batches[0].batch_number,
                    ["post-1", "post-2"],
                ]
            ],
            separators=(",", ":"),
        )
        self.assertEqual(
            first_state,
            (
                [
                    ("post-1", "pending", None, applied_at.isoformat()),
                    ("post-2", "pending", None, applied_at.isoformat()),
                ],
                [
                    (
                        batches[0].batch_id,
                        batches[0].batch_number,
                        "prepared",
                        None,
                        None,
                        applied_at.isoformat(),
                    )
                ],
                [
                    (
                        RUN_ID,
                        AUTHORIZATION_SHA256,
                        candidate_json,
                        sha256(candidate_json.encode()).hexdigest(),
                        membership_json,
                        sha256(membership_json.encode()).hexdigest(),
                        2,
                        1,
                        applied_at.isoformat(),
                    )
                ],
            ),
        )

        self.assertFalse(
            self.store.resume_budget_exhausted_hydration(
                RUN_ID,
                authorization_sha256=AUTHORIZATION_SHA256,
                updated_at_utc=applied_at + timedelta(days=1),
            )
        )
        self.assertEqual(self.state(self.store), first_state)

    def test_same_authorization_rejects_state_or_membership_drift(self) -> None:
        for label, statement, parameters in (
            (
                "candidate_state",
                "UPDATE backfill_candidates SET status='failed', "
                "status_reason='provider_error' WHERE run_id=? AND post_id='post-2'",
                (RUN_ID,),
            ),
            (
                "batch_state",
                "UPDATE backfill_detail_batches SET status='failed', "
                "stop_reason='budget_exhausted' WHERE run_id=?",
                (RUN_ID,),
            ),
            (
                "membership",
                "DELETE FROM backfill_detail_batch_members "
                "WHERE run_id=? AND post_id='post-2'",
                (RUN_ID,),
            ),
            (
                "resume_ledger_sha",
                "UPDATE backfill_hydration_resumes "
                "SET batch_membership_sha256=? WHERE run_id=?",
                ("f" * 64, RUN_ID),
            ),
        ):
            with self.subTest(case=label):
                store = self.new_store(f"replay-{label}")
                self.prepare_authorized_state(store)
                self.assertTrue(
                    store.resume_budget_exhausted_hydration(
                        RUN_ID,
                        authorization_sha256=AUTHORIZATION_SHA256,
                        updated_at_utc=NOW + timedelta(minutes=3),
                    )
                )
                with store.connect() as connection:
                    connection.execute(statement, parameters)
                before = self.state(store)
                with self.assertRaises(BackfillConflictError):
                    store.resume_budget_exhausted_hydration(
                        RUN_ID,
                        authorization_sha256=AUTHORIZATION_SHA256,
                        updated_at_utc=NOW + timedelta(days=1),
                    )
                self.assertEqual(self.state(store), before)

    def test_resume_rejects_authorization_and_attempt_ledger_drift(self) -> None:
        def no_mutation(_: BackfillStore) -> None:
            return None

        def scope_drift(store: BackfillStore) -> None:
            with store.connect() as connection:
                connection.execute(
                    "UPDATE backfill_manifests SET required_lanes_sha256=? "
                    "WHERE run_id=?",
                    ("f" * 64, RUN_ID),
                )

        def attempt_drift(store: BackfillStore) -> None:
            with store.connect() as connection:
                connection.execute(
                    "UPDATE backfill_provider_attempts SET status='sent', "
                    "completed_at_utc=NULL WHERE run_id=? AND request_number=2",
                    (RUN_ID,),
                )

        def exceed_discovery_ceiling(store: BackfillStore) -> None:
            for request_number in (3, 4):
                at = NOW + timedelta(minutes=2, seconds=request_number)
                self.assertEqual(
                    store.reserve_provider_request(RUN_ID, "/search", at),
                    request_number,
                )
                store.mark_provider_attempt_sent(RUN_ID, request_number, at)
                store.complete_provider_attempt(
                    RUN_ID,
                    request_number,
                    status="succeeded",
                    completed_at_utc=at,
                )

        cases = (
            (
                "unknown_authorization",
                no_mutation,
                "e" * 64,
            ),
            (
                "scope",
                scope_drift,
                AUTHORIZATION_SHA256,
            ),
            (
                "attempt",
                attempt_drift,
                AUTHORIZATION_SHA256,
            ),
            (
                "beyond_discovery_ceiling",
                exceed_discovery_ceiling,
                AUTHORIZATION_SHA256,
            ),
        )
        for label, mutate, authorization in cases:
            with self.subTest(case=label):
                store = self.new_store(f"authorization-{label}")
                self.prepare_authorized_state(store)
                mutate(store)
                before = self.state(store)
                with self.assertRaises(BackfillConflictError):
                    store.resume_budget_exhausted_hydration(
                        RUN_ID,
                        authorization_sha256=authorization,
                        updated_at_utc=NOW + timedelta(minutes=3),
                    )
                self.assertEqual(self.state(store), before)

    def test_resume_rejects_mixed_candidate_batch_and_member_ledgers(self) -> None:
        mutations = (
            (
                "mixed_candidate",
                "UPDATE backfill_candidates SET status='failed', "
                "status_reason='provider_error' WHERE run_id=? AND post_id='post-2'",
            ),
            (
                "non_budget_batch",
                "UPDATE backfill_detail_batches SET stop_reason='provider_error' "
                "WHERE run_id=?",
            ),
            (
                "unassigned_candidate",
                "DELETE FROM backfill_detail_batch_members "
                "WHERE run_id=? AND post_id='post-2'",
            ),
        )
        for label, statement in mutations:
            with self.subTest(case=label):
                store = self.new_store(f"mixed-{label}")
                self.prepare_authorized_state(store)
                with store.connect() as connection:
                    connection.execute(statement, (RUN_ID,))
                before = self.state(store)
                with self.assertRaises(BackfillConflictError):
                    store.resume_budget_exhausted_hydration(
                        RUN_ID,
                        authorization_sha256=AUTHORIZATION_SHA256,
                        updated_at_utc=NOW + timedelta(minutes=3),
                    )
                self.assertEqual(self.state(store), before)

    def test_resume_rejects_detail_and_comment_evidence(self) -> None:
        def detail_artifact(store: BackfillStore, batch_id: str) -> None:
            store.insert_raw_artifact(
                make_artifact(
                    artifact_id="existing-detail",
                    lane_type="detail_batch",
                    lane_key=batch_id,
                    page_number=1,
                )
            )

        def comment_artifact(store: BackfillStore, _: str) -> None:
            store.insert_raw_artifact(
                make_artifact(
                    artifact_id="existing-comment",
                    lane_type="comments",
                    lane_key="post-1",
                    page_number=1,
                )
            )

        def comment_checkpoint(store: BackfillStore, _: str) -> None:
            store.save_checkpoint(
                BackfillCheckpoint(
                    run_id=RUN_ID,
                    lane_type="comments",
                    lane_key="post-1",
                    cursor=None,
                    previous_cursor=None,
                    page_number=0,
                    newest_seen_utc=None,
                    oldest_seen_utc=None,
                    discovered_count=0,
                    unique_count=0,
                    provider_request_count=2,
                    last_success_utc=None,
                    last_error="ProviderBudgetExhausted",
                    status="partial",
                    stop_reason="budget_exhausted",
                    cursor_json_path=None,
                    cursor_schema_sha256=None,
                    consecutive_old_pages=0,
                )
            )

        def attached_artifact(store: BackfillStore, batch_id: str) -> None:
            artifact = make_artifact(
                artifact_id="attached-but-wrong-lane",
                lane_type="dynamic_search",
                lane_key="different-lane",
                page_number=2,
            )
            store.insert_raw_artifact(artifact)
            with store.connect() as connection:
                connection.execute(
                    "UPDATE backfill_detail_batches SET artifact_id=? "
                    "WHERE run_id=? AND batch_id=?",
                    (artifact.artifact_id, RUN_ID, batch_id),
                )

        def structured_entity(store: BackfillStore, _: str) -> None:
            capture = RawCapture(
                raw_capture_id="existing-entity-capture",
                run_id=RUN_ID,
                source_method="provider",
                source_url="https://reddit.com/comments/post-1/title/",
                captured_at_utc=NOW,
                auth_boundary="provider_gate",
                raw_payload_hash="f" * 64,
                payload_format="json",
            )
            thread = RedditThread(
                post_id="post-1",
                run_id=RUN_ID,
                raw_capture_id=capture.raw_capture_id,
                subreddit="ExclusivelyPumping",
                title="Momcozy",
                source_url=capture.source_url,
                created_at_utc=NOW - timedelta(days=1),
                matched_keywords=["Momcozy"],
            )
            store.insert_entity_bundle(
                captures=(capture,),
                threads=(thread,),
                comments=(),
                analyses=(),
            )

        for label, mutate in (
            ("detail_artifact", detail_artifact),
            ("attached_artifact", attached_artifact),
            ("comment_artifact", comment_artifact),
            ("comment_checkpoint", comment_checkpoint),
            ("structured_entity", structured_entity),
        ):
            with self.subTest(case=label):
                store = self.new_store(f"evidence-{label}")
                batches = self.prepare_authorized_state(store)
                mutate(store, batches[0].batch_id)
                before = self.state(store)
                with self.assertRaises(BackfillConflictError):
                    store.resume_budget_exhausted_hydration(
                        RUN_ID,
                        authorization_sha256=AUTHORIZATION_SHA256,
                        updated_at_utc=NOW + timedelta(minutes=3),
                    )
                self.assertEqual(self.state(store), before)

    def test_resume_is_atomic_across_connections(self) -> None:
        self.prepare_authorized_state(self.store)

        def resume(offset: int) -> bool:
            return self.store.resume_budget_exhausted_hydration(
                RUN_ID,
                authorization_sha256=AUTHORIZATION_SHA256,
                updated_at_utc=NOW + timedelta(minutes=3, seconds=offset),
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(resume, (0, 1)))
        self.assertEqual(sorted(results), [False, True])
        candidates, batches, resumes = self.state(self.store)
        self.assertTrue(all(row[1:3] == ("pending", None) for row in candidates))
        self.assertTrue(
            all(row[2:5] == ("prepared", None, None) for row in batches)
        )
        self.assertEqual(len(resumes), 1)

    def test_hydration_resume_recorded_before_and_after_apply(self) -> None:
        self.prepare_authorized_state(self.store)
        self.assertFalse(
            self.store.hydration_resume_recorded(
                RUN_ID, AUTHORIZATION_SHA256
            )
        )
        self.assertTrue(
            self.store.resume_budget_exhausted_hydration(
                RUN_ID,
                authorization_sha256=AUTHORIZATION_SHA256,
                updated_at_utc=NOW + timedelta(minutes=3),
            )
        )
        self.assertTrue(
            self.store.hydration_resume_recorded(
                RUN_ID, AUTHORIZATION_SHA256
            )
        )

    def test_operational_snapshot_binds_authorization_and_resume_ledgers(self) -> None:
        self.prepare_authorized_state(self.store)
        self.assertTrue(
            self.store.resume_budget_exhausted_hydration(
                RUN_ID,
                authorization_sha256=AUTHORIZATION_SHA256,
                updated_at_utc=NOW + timedelta(minutes=3),
            )
        )
        with self.store.connect() as connection:
            before = operational_snapshot_sha256(connection, RUN_ID)
            connection.execute(
                "UPDATE backfill_hydration_resumes "
                "SET batch_membership_sha256=? WHERE run_id=?",
                ("f" * 64, RUN_ID),
            )
            after = operational_snapshot_sha256(connection, RUN_ID)

        self.assertNotEqual(before, after)

    def test_hydration_resume_recorded_allows_legal_forward_state(self) -> None:
        batches = self.prepare_authorized_state(self.store)
        self.assertTrue(
            self.store.resume_budget_exhausted_hydration(
                RUN_ID,
                authorization_sha256=AUTHORIZATION_SHA256,
                updated_at_utc=NOW + timedelta(minutes=3),
            )
        )
        batch = batches[0]
        artifact = make_artifact(
            artifact_id="forward-detail",
            lane_type="detail_batch",
            lane_key=batch.batch_id,
            page_number=batch.batch_number,
        )
        self.store.insert_raw_artifact(artifact)
        self.store.attach_detail_batch_artifact(
            run_id=RUN_ID,
            batch_id=batch.batch_id,
            artifact_id=artifact.artifact_id,
            updated_at_utc=NOW + timedelta(minutes=4),
        )
        for post_id in ("post-1", "post-2"):
            self.store.finalize_candidate(
                run_id=RUN_ID,
                post_id=post_id,
                expected_statuses=("pending",),
                status="failed",
                status_reason="detail_missing",
                updated_at_utc=NOW + timedelta(minutes=5),
            )
        self.store.finish_detail_batch(
            run_id=RUN_ID,
            batch_id=batch.batch_id,
            status="complete",
            stop_reason=None,
            updated_at_utc=NOW + timedelta(minutes=6),
        )

        self.assertTrue(
            self.store.hydration_resume_recorded(
                RUN_ID, AUTHORIZATION_SHA256
            )
        )

    def test_hydration_resume_recorded_rejects_ledger_and_membership_drift(
        self,
    ) -> None:
        def ledger_sha(store: BackfillStore) -> None:
            with store.connect() as connection:
                connection.execute(
                    "UPDATE backfill_hydration_resumes "
                    "SET candidate_post_ids_sha256=? WHERE run_id=?",
                    ("f" * 64, RUN_ID),
                )

        def membership(store: BackfillStore) -> None:
            with store.connect() as connection:
                connection.execute(
                    "DELETE FROM backfill_detail_batch_members "
                    "WHERE run_id=? AND post_id='post-2'",
                    (RUN_ID,),
                )

        def batch_number(store: BackfillStore) -> None:
            with store.connect() as connection:
                connection.execute(
                    "UPDATE backfill_detail_batches SET batch_number=2 "
                    "WHERE run_id=?",
                    (RUN_ID,),
                )

        def candidate_missing(store: BackfillStore) -> None:
            with store.connect() as connection:
                connection.execute("PRAGMA foreign_keys=OFF")
                connection.execute(
                    "DELETE FROM backfill_candidates "
                    "WHERE run_id=? AND post_id='post-2'",
                    (RUN_ID,),
                )

        def extension_missing(store: BackfillStore) -> None:
            with store.connect() as connection:
                connection.execute("PRAGMA foreign_keys=OFF")
                connection.execute(
                    "DELETE FROM backfill_budget_extensions "
                    "WHERE run_id=? AND authorization_sha256=?",
                    (RUN_ID, AUTHORIZATION_SHA256),
                )

        for label, mutate in (
            ("ledger_sha", ledger_sha),
            ("membership", membership),
            ("batch_number", batch_number),
            ("candidate_missing", candidate_missing),
            ("extension_missing", extension_missing),
        ):
            with self.subTest(case=label):
                store = self.new_store(f"recorded-{label}")
                self.prepare_authorized_state(store)
                self.assertTrue(
                    store.resume_budget_exhausted_hydration(
                        RUN_ID,
                        authorization_sha256=AUTHORIZATION_SHA256,
                        updated_at_utc=NOW + timedelta(minutes=3),
                    )
                )
                mutate(store)
                with self.assertRaises(BackfillConflictError):
                    store.hydration_resume_recorded(
                        RUN_ID, AUTHORIZATION_SHA256
                    )


if __name__ == "__main__":
    unittest.main()
