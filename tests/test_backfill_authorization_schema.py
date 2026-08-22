from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from reddit_voc.backfill_storage import (
    BackfillSchemaError,
    BackfillStore,
)


BUDGET_EXTENSION_COLUMNS = (
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
)
HYDRATION_RESUME_COLUMNS = (
    "run_id",
    "authorization_sha256",
    "candidate_post_ids_json",
    "candidate_post_ids_sha256",
    "batch_membership_json",
    "batch_membership_sha256",
    "candidate_count",
    "batch_count",
    "applied_at_utc",
)
COLLECTION_RESUME_COLUMNS = (
    "run_id",
    "authorization_sha256",
    "expected_source_database_sha256",
    "expected_provider_request_count",
    "max_provider_requests",
    "discovery_request_ceiling",
    "lane_page_ceilings_sha256",
    "candidate_state_sha256",
    "include_subreddit_sweep",
    "required_lanes_sha256",
    "applied_at_utc",
)


class AuthorizationLedgerSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = BackfillStore(Path(self.temporary.name) / "staging.sqlite3")
        self.store.migrate()

    def _replace_with_unconstrained_table(
        self, table: str, columns: tuple[str, ...]
    ) -> None:
        with self.store.connect() as connection:
            connection.execute("PRAGMA foreign_keys=OFF")
            if table == "backfill_budget_extensions":
                connection.execute("DROP TABLE backfill_hydration_resumes")
            connection.execute(f"DROP TABLE {table}")
            connection.execute(
                f"CREATE TABLE {table}("
                + ", ".join(f"{column} TEXT" for column in columns)
                + ")"
            )

    def test_migrate_rejects_budget_extension_table_without_constraints(self) -> None:
        self._replace_with_unconstrained_table(
            "backfill_budget_extensions", BUDGET_EXTENSION_COLUMNS
        )

        with self.assertRaises(BackfillSchemaError):
            self.store.migrate()

    def test_migrate_rejects_hydration_resume_table_without_constraints(self) -> None:
        self._replace_with_unconstrained_table(
            "backfill_hydration_resumes", HYDRATION_RESUME_COLUMNS
        )

        with self.assertRaises(BackfillSchemaError):
            self.store.migrate()

    def test_migrate_rejects_collection_resume_table_without_constraints(self) -> None:
        self._replace_with_unconstrained_table(
            "backfill_collection_resumes", COLLECTION_RESUME_COLUMNS
        )

        with self.assertRaises(BackfillSchemaError):
            self.store.migrate()

    def test_reviewed_authorization_schema_remains_idempotent(self) -> None:
        self.store.migrate()


if __name__ == "__main__":
    unittest.main()
