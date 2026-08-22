from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from reddit_voc.backfill_models import BackfillManifest
from reddit_voc.backfill_storage import BackfillConflictError, BackfillStore


NOW = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
RUN_ID = "backfill_budget_extension_test"


def make_manifest(*, max_provider_requests: int) -> BackfillManifest:
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
        max_provider_requests=max_provider_requests,
        provider_request_count=0,
        provider_call=False,
        live_send=False,
        created_at_utc=NOW.isoformat(),
        updated_at_utc=NOW.isoformat(),
    )


class BackfillBudgetExtensionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.store = BackfillStore(
            Path(self.temporary_directory.name) / "backfill.sqlite3"
        )
        self.store.migrate()

    def create_run(self, *, budget: int) -> None:
        self.store.create_manifest(make_manifest(max_provider_requests=budget))

    def reserve_terminal(self, request_number: int) -> None:
        at = NOW + timedelta(seconds=request_number)
        reserved = self.store.reserve_provider_request(RUN_ID, "/search", at)
        self.assertEqual(reserved, request_number)
        self.store.mark_provider_attempt_sent(RUN_ID, request_number, at)
        self.store.complete_provider_attempt(
            RUN_ID,
            request_number,
            status="succeeded",
            completed_at_utc=at,
        )

    def prepare_exhausted_partial_run(self, *, budget: int = 2) -> None:
        self.create_run(budget=budget)
        for request_number in range(1, budget + 1):
            self.reserve_terminal(request_number)
        self.store.set_backfill_status(RUN_ID, "partial", NOW + timedelta(minutes=1))

    def extension_kwargs(
        self,
        *,
        expected_count: int = 2,
        expected_max: int = 2,
        new_max: int = 4,
        discovery_request_ceiling: int = 3,
        lane_page_ceilings_sha256: str = "d" * 64,
        include_subreddit_sweep: bool = True,
        required_lanes_sha256: str = "a" * 64,
        authorization_sha256: str = "c" * 64,
        updated_at_utc: datetime = NOW + timedelta(minutes=2),
    ) -> dict[str, object]:
        return {
            "expected_provider_request_count": expected_count,
            "expected_max_provider_requests": expected_max,
            "new_max_provider_requests_total": new_max,
            "discovery_request_ceiling": discovery_request_ceiling,
            "lane_page_ceilings_sha256": lane_page_ceilings_sha256,
            "include_subreddit_sweep": include_subreddit_sweep,
            "required_lanes_sha256": required_lanes_sha256,
            "authorization_sha256": authorization_sha256,
            "updated_at_utc": updated_at_utc,
        }

    def manifest_state(self) -> tuple[object, ...]:
        with self.store.connect() as connection:
            return tuple(
                connection.execute(
                    "SELECT status, max_provider_requests, provider_request_count, "
                    "provider_call, updated_at_utc FROM backfill_manifests "
                    "WHERE run_id=?",
                    (RUN_ID,),
                ).fetchone()
            )

    def extension_rows(self) -> list[tuple[object, ...]]:
        with self.store.connect() as connection:
            return [
                tuple(row)
                for row in connection.execute(
                    "SELECT run_id, authorization_sha256, "
                    "expected_provider_request_count, expected_max_provider_requests, "
                    "new_max_provider_requests, discovery_request_ceiling, "
                    "lane_page_ceilings_sha256, include_subreddit_sweep, "
                    "required_lanes_sha256, applied_at_utc "
                    "FROM backfill_budget_extensions ORDER BY applied_at_utc"
                ).fetchall()
            ]

    def test_migrate_adds_budget_extension_ledger(self) -> None:
        self.create_run(budget=2)
        before = self.manifest_state()
        with self.store.connect() as connection:
            connection.execute("DROP TABLE backfill_budget_extensions")

        self.store.migrate()

        with self.store.connect() as connection:
            columns = [
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(backfill_budget_extensions)"
                ).fetchall()
            ]
            unique_indexes: set[tuple[str, ...]] = set()
            for index in connection.execute(
                "PRAGMA index_list(backfill_budget_extensions)"
            ).fetchall():
                if not bool(index["unique"]):
                    continue
                index_name = str(index["name"]).replace("'", "''")
                unique_indexes.add(
                    tuple(
                        row["name"]
                        for row in connection.execute(
                            f"PRAGMA index_info('{index_name}')"
                        ).fetchall()
                    )
                )
            foreign_keys = connection.execute(
                "PRAGMA foreign_key_list(backfill_budget_extensions)"
            ).fetchall()

        self.assertEqual(
            columns,
            [
                "run_id",
                "authorization_sha256",
                "expected_provider_request_count",
                "expected_max_provider_requests",
                "new_max_provider_requests",
                "discovery_request_ceiling",
                "lane_page_ceilings_sha256",
                "include_subreddit_sweep",
                "required_lanes_sha256",
                "applied_at_utc",
            ],
        )
        self.assertEqual(
            unique_indexes,
            {
                ("run_id", "authorization_sha256"),
                ("run_id", "expected_max_provider_requests"),
                ("run_id", "new_max_provider_requests"),
            },
        )
        self.assertEqual(
            [(row["table"], row["from"], row["to"]) for row in foreign_keys],
            [("backfill_manifests", "run_id", "run_id")],
        )
        self.assertEqual(self.manifest_state(), before)

    def test_extend_budget_is_atomic_monotonic_and_exact_idempotent(self) -> None:
        self.prepare_exhausted_partial_run()
        applied_at = NOW + timedelta(minutes=2)
        kwargs = self.extension_kwargs(updated_at_utc=applied_at)

        changed = self.store.extend_full_collection_budget(RUN_ID, **kwargs)
        first_manifest = self.manifest_state()
        first_rows = self.extension_rows()

        self.assertTrue(changed)
        self.assertEqual(
            first_manifest,
            ("partial", 4, 2, 1, applied_at.isoformat()),
        )
        self.assertEqual(
            first_rows,
            [
                (
                    RUN_ID,
                    "c" * 64,
                    2,
                    2,
                    4,
                    3,
                    "d" * 64,
                    1,
                    "a" * 64,
                    applied_at.isoformat(),
                )
            ],
        )

        replayed = self.store.extend_full_collection_budget(
            RUN_ID,
            **{
                **kwargs,
                "updated_at_utc": applied_at + timedelta(hours=1),
            },
        )
        self.assertFalse(replayed)
        self.assertEqual(self.manifest_state(), first_manifest)
        self.assertEqual(self.extension_rows(), first_rows)

        self.reserve_terminal(3)
        progressed_manifest = self.manifest_state()
        self.assertFalse(
            self.store.extend_full_collection_budget(
                RUN_ID,
                **{
                    **kwargs,
                    "updated_at_utc": applied_at + timedelta(hours=2),
                },
            )
        )
        self.assertEqual(self.manifest_state(), progressed_manifest)
        self.assertEqual(self.extension_rows(), first_rows)

    def test_extend_budget_rejects_stale_fork_and_unexhausted_state(self) -> None:
        self.prepare_exhausted_partial_run()
        kwargs = self.extension_kwargs()
        self.assertTrue(self.store.extend_full_collection_budget(RUN_ID, **kwargs))
        accepted_manifest = self.manifest_state()
        accepted_rows = self.extension_rows()

        with self.assertRaises(BackfillConflictError):
            self.store.extend_full_collection_budget(
                RUN_ID, **{**kwargs, "new_max_provider_requests_total": 5}
            )
        with self.assertRaises(ValueError):
            self.store.extend_full_collection_budget(
                RUN_ID,
                **self.extension_kwargs(
                    expected_count=2,
                    expected_max=2,
                    new_max=5,
                    authorization_sha256="d" * 64,
                ),
            )
        with self.assertRaises(ValueError):
            self.store.extend_full_collection_budget(
                RUN_ID,
                **self.extension_kwargs(
                    expected_count=2,
                    expected_max=4,
                    new_max=5,
                    authorization_sha256="e" * 64,
                ),
            )

        self.assertEqual(self.manifest_state(), accepted_manifest)
        self.assertEqual(self.extension_rows(), accepted_rows)

    def test_exact_authorization_rejects_bound_parameter_drift(self) -> None:
        self.prepare_exhausted_partial_run()
        kwargs = self.extension_kwargs()
        self.assertTrue(self.store.extend_full_collection_budget(RUN_ID, **kwargs))
        accepted_manifest = self.manifest_state()
        accepted_rows = self.extension_rows()

        cases = (
            ("discovery_ceiling", {"discovery_request_ceiling": 2}),
            ("lane_page_sha", {"lane_page_ceilings_sha256": "e" * 64}),
            ("subreddit_sweep", {"include_subreddit_sweep": False}),
            ("required_lanes", {"required_lanes_sha256": "f" * 64}),
        )
        for label, changed in cases:
            with self.subTest(case=label):
                with self.assertRaises(BackfillConflictError):
                    self.store.extend_full_collection_budget(
                        RUN_ID, **{**kwargs, **changed}
                    )

        self.assertEqual(self.manifest_state(), accepted_manifest)
        self.assertEqual(self.extension_rows(), accepted_rows)

    def test_extension_rejects_live_scope_drift_and_invalid_ceiling(self) -> None:
        for label, assignment, value in (
            ("sweep", "include_subreddit_sweep", 0),
            ("required_lanes", "required_lanes_sha256", "f" * 64),
        ):
            with self.subTest(case=label):
                path = Path(self.temporary_directory.name) / f"scope-{label}.sqlite3"
                store = BackfillStore(path)
                store.migrate()
                store.create_manifest(make_manifest(max_provider_requests=2))
                for request_number in (1, 2):
                    at = NOW + timedelta(seconds=request_number)
                    reserved = store.reserve_provider_request(RUN_ID, "/search", at)
                    self.assertEqual(reserved, request_number)
                    store.mark_provider_attempt_sent(RUN_ID, request_number, at)
                    store.complete_provider_attempt(
                        RUN_ID,
                        request_number,
                        status="succeeded",
                        completed_at_utc=at,
                    )
                store.set_backfill_status(RUN_ID, "partial", NOW)
                with store.connect() as connection:
                    connection.execute(
                        f"UPDATE backfill_manifests SET {assignment}=? WHERE run_id=?",
                        (value, RUN_ID),
                    )

                with self.assertRaises(ValueError):
                    store.extend_full_collection_budget(
                        RUN_ID, **self.extension_kwargs()
                    )
                with store.connect() as connection:
                    state = tuple(
                        connection.execute(
                            "SELECT max_provider_requests, provider_request_count "
                            "FROM backfill_manifests WHERE run_id=?",
                            (RUN_ID,),
                        ).fetchone()
                    )
                    extension_count = connection.execute(
                        "SELECT COUNT(*) FROM backfill_budget_extensions"
                    ).fetchone()[0]
                self.assertEqual(state, (2, 2))
                self.assertEqual(extension_count, 0)

        self.prepare_exhausted_partial_run()
        before = self.manifest_state()
        for invalid in (1, 4, 5, True, 2.5, "3"):
            with self.subTest(invalid_ceiling=invalid):
                with self.assertRaises((TypeError, ValueError)):
                    self.store.extend_full_collection_budget(
                        RUN_ID,
                        **self.extension_kwargs(
                            discovery_request_ceiling=invalid,
                        ),
                    )
        self.assertEqual(self.manifest_state(), before)
        self.assertEqual(self.extension_rows(), [])

    def test_extend_budget_rejects_inflight_attempt_without_mutation(self) -> None:
        for attempt_status in ("reserved", "sent"):
            with self.subTest(attempt_status=attempt_status):
                path = Path(self.temporary_directory.name) / f"{attempt_status}.sqlite3"
                store = BackfillStore(path)
                store.migrate()
                store.create_manifest(make_manifest(max_provider_requests=2))
                for request_number in (1, 2):
                    at = NOW + timedelta(seconds=request_number)
                    reserved = store.reserve_provider_request(RUN_ID, "/search", at)
                    self.assertEqual(reserved, request_number)
                    if request_number == 1 or attempt_status == "sent":
                        store.mark_provider_attempt_sent(
                            RUN_ID, request_number, at
                        )
                    if request_number == 1:
                        store.complete_provider_attempt(
                            RUN_ID,
                            request_number,
                            status="succeeded",
                            completed_at_utc=at,
                        )
                store.set_backfill_status(
                    RUN_ID, "partial", NOW + timedelta(minutes=1)
                )

                with self.assertRaises(ValueError):
                    store.extend_full_collection_budget(
                        RUN_ID, **self.extension_kwargs()
                    )

                with store.connect() as connection:
                    manifest = tuple(
                        connection.execute(
                            "SELECT max_provider_requests, provider_request_count "
                            "FROM backfill_manifests WHERE run_id=?",
                            (RUN_ID,),
                        ).fetchone()
                    )
                    extension_count = connection.execute(
                        "SELECT COUNT(*) FROM backfill_budget_extensions"
                    ).fetchone()[0]
                self.assertEqual(manifest, (2, 2))
                self.assertEqual(extension_count, 0)

    def test_reserve_provider_request_honors_absolute_ceiling(self) -> None:
        self.create_run(budget=5)

        self.assertEqual(
            self.store.reserve_provider_request(
                RUN_ID, "/search", NOW, request_ceiling=2
            ),
            1,
        )
        self.assertEqual(
            self.store.reserve_provider_request(
                RUN_ID,
                "/search",
                NOW + timedelta(seconds=1),
                request_ceiling=2,
            ),
            2,
        )
        self.assertIsNone(
            self.store.reserve_provider_request(
                RUN_ID,
                "/search",
                NOW + timedelta(seconds=2),
                request_ceiling=2,
            )
        )
        self.assertEqual(
            self.store.reserve_provider_request(
                RUN_ID, "/search", NOW + timedelta(seconds=3)
            ),
            3,
        )

        with self.store.connect() as connection:
            attempts = connection.execute(
                "SELECT request_number, status FROM backfill_provider_attempts "
                "WHERE run_id=? ORDER BY request_number",
                (RUN_ID,),
            ).fetchall()
            manifest = connection.execute(
                "SELECT max_provider_requests, provider_request_count "
                "FROM backfill_manifests WHERE run_id=?",
                (RUN_ID,),
            ).fetchone()
        self.assertEqual(
            [tuple(row) for row in attempts],
            [(1, "reserved"), (2, "reserved"), (3, "reserved")],
        )
        self.assertEqual(tuple(manifest), (5, 3))

        for invalid in (True, -1, 1.5, "2"):
            with self.subTest(invalid=invalid):
                with self.assertRaises((TypeError, ValueError)):
                    self.store.reserve_provider_request(
                        RUN_ID,
                        "/search",
                        NOW + timedelta(minutes=1),
                        request_ceiling=invalid,
                    )

    def test_request_ceiling_is_atomic_across_connections(self) -> None:
        self.create_run(budget=5)

        def reserve(offset: int) -> int | None:
            return self.store.reserve_provider_request(
                RUN_ID,
                "/search",
                NOW + timedelta(microseconds=offset),
                request_ceiling=2,
            )

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(reserve, range(8)))

        self.assertEqual(
            sorted(result for result in results if result is not None),
            [1, 2],
        )
        with self.store.connect() as connection:
            manifest = tuple(
                connection.execute(
                    "SELECT max_provider_requests, provider_request_count "
                    "FROM backfill_manifests WHERE run_id=?",
                    (RUN_ID,),
                ).fetchone()
            )
            request_numbers = [
                row[0]
                for row in connection.execute(
                    "SELECT request_number FROM backfill_provider_attempts "
                    "WHERE run_id=? ORDER BY request_number",
                    (RUN_ID,),
                ).fetchall()
            ]
        self.assertEqual(manifest, (5, 2))
        self.assertEqual(request_numbers, [1, 2])


if __name__ == "__main__":
    unittest.main()
