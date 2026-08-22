from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from reddit_voc.cli import build_daily_source_batch_command
from reddit_voc.schema_migration import migrate_database_schema, sha256_file
from reddit_voc.storage import SCHEMA, VocStore


_CURRENT_UNIQUE = "UNIQUE(run_id, source_method, source_url, raw_payload_hash)"
_LEGACY_UNIQUE = "UNIQUE(source_method, source_url, raw_payload_hash)"


def _create_legacy_database(path: Path) -> None:
    legacy_schema = SCHEMA.replace(_CURRENT_UNIQUE, _LEGACY_UNIQUE, 1)
    if legacy_schema == SCHEMA:
        raise AssertionError("legacy schema fixture replacement failed")
    with sqlite3.connect(path) as conn:
        conn.executescript(legacy_schema)
        conn.execute(
            """
            INSERT INTO runs(
                run_id, status, window_start_utc, window_end_utc,
                provider_call, live_send
            ) VALUES (?, ?, ?, ?, 0, 0)
            """,
            (
                "daily_collect_fixture",
                "success",
                "2026-08-01T00:00:00+00:00",
                "2026-08-02T00:00:00+00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO raw_captures(
                raw_capture_id, run_id, source_method, source_url,
                captured_at_utc, auth_boundary, raw_payload_hash,
                payload_format, browser_status, http_status,
                selector_version, blocked_reason, secrets_written
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "raw_fixture",
                "daily_collect_fixture",
                "fixture",
                "https://example.invalid/raw",
                "2026-08-02T00:00:00+00:00",
                "fixture",
                "a" * 64,
                "json",
                "success",
                200,
                None,
                None,
                0,
            ),
        )


def _source_batch_args(root: Path, database: Path) -> Namespace:
    summary = root / "collector-summary.json"
    summary.write_text("{}\n", encoding="utf-8")
    return Namespace(
        database=database,
        run_id="daily_collect_fixture",
        collector_summary=summary,
        output_dir=root / "output",
        raw_artifact_root=None,
        source_batch_root=None,
        query_profile=root / "query.json",
        coverage_profile=root / "coverage.json",
    )


class ReadonlySourceBatchTests(unittest.TestCase):
    def test_current_schema_source_batch_keeps_database_sha(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = root / "voc.sqlite3"
            VocStore(database).migrate()
            before = sha256_file(database)
            result = SimpleNamespace(
                batch_root=root / "source-batch",
                manifest_path=root / "source-batch" / "source-batch-manifest.json",
                manifest_sha256="b" * 64,
                write_status="created",
            )
            output = io.StringIO()
            with patch(
                "reddit_voc.daily_source_batch.build_daily_source_batch",
                return_value=result,
            ), redirect_stdout(output):
                status = build_daily_source_batch_command(_source_batch_args(root, database))

            payload = json.loads(output.getvalue())
            self.assertEqual(status, 0)
            self.assertEqual(sha256_file(database), before)
            self.assertEqual(payload["database_sha256_before"], before)
            self.assertEqual(payload["database_sha256_after"], before)
            self.assertFalse(payload["database_write"])

    def test_legacy_schema_source_batch_fails_closed_without_db_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = root / "voc.sqlite3"
            _create_legacy_database(database)
            before = sha256_file(database)
            with patch("reddit_voc.daily_source_batch.build_daily_source_batch") as builder:
                with self.assertRaisesRegex(
                    RuntimeError, "daily_source_batch_schema_migration_required"
                ):
                    build_daily_source_batch_command(_source_batch_args(root, database))
            builder.assert_not_called()
            self.assertEqual(sha256_file(database), before)

    def test_readonly_store_forbids_migration_and_sql_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "voc.sqlite3"
            VocStore(database).migrate()
            store = VocStore(database, read_only=True)
            with self.assertRaisesRegex(RuntimeError, "readonly_store_migration_forbidden"):
                store.migrate()
            with store.connect() as conn:
                with self.assertRaises(sqlite3.OperationalError):
                    conn.execute(
                        "INSERT INTO runs VALUES (?, ?, ?, ?, 0, 0)",
                        ("x", "success", "a", "b"),
                    )


class ExplicitSchemaMigrationTests(unittest.TestCase):
    def _migrate(self, root: Path, database: Path, suffix: str = "") -> dict[str, object]:
        return migrate_database_schema(
            database_path=database,
            expected_database_sha256=sha256_file(database),
            backup_path=root / f"backup{suffix}.sqlite3",
            rollback_path=root / f"rollback{suffix}.sqlite3",
            authorization_id=f"TASK32AL-LOCAL{suffix or '-1'}",
        )

    def test_explicit_migration_preserves_rows_and_creates_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = root / "voc.sqlite3"
            _create_legacy_database(database)
            before = sha256_file(database)

            result = self._migrate(root, database)

            self.assertEqual(result["write_status"], "migrated")
            self.assertTrue(result["database_write"])
            self.assertNotEqual(sha256_file(database), before)
            self.assertEqual(sha256_file(root / "backup.sqlite3"), before)
            self.assertEqual(sha256_file(root / "rollback.sqlite3"), before)
            self.assertEqual(result["counts_before"], result["counts_after"])
            VocStore(database, read_only=True).require_daily_source_batch_schema()

    def test_repeat_migration_is_database_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = root / "voc.sqlite3"
            _create_legacy_database(database)
            self._migrate(root, database)
            before = sha256_file(database)

            result = self._migrate(root, database, "-repeat")

            self.assertEqual(result["write_status"], "no_change")
            self.assertFalse(result["database_write"])
            self.assertEqual(sha256_file(database), before)

    def test_post_swap_failure_restores_exact_source_sha(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = root / "voc.sqlite3"
            _create_legacy_database(database)
            before = sha256_file(database)

            with patch(
                "reddit_voc.schema_migration._verify_post_swap",
                side_effect=RuntimeError("injected_post_swap_failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "schema_migration_rolled_back"):
                    self._migrate(root, database, "-failure")

            self.assertEqual(sha256_file(database), before)

    def test_expected_sha_mismatch_fails_before_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = root / "voc.sqlite3"
            _create_legacy_database(database)
            backup = root / "backup.sqlite3"
            rollback = root / "rollback.sqlite3"
            with self.assertRaisesRegex(RuntimeError, "schema_migration_source_sha_mismatch"):
                migrate_database_schema(
                    database_path=database,
                    expected_database_sha256="0" * 64,
                    backup_path=backup,
                    rollback_path=rollback,
                    authorization_id="TASK32AL-LOCAL-MISMATCH",
                )
            self.assertFalse(backup.exists())
            self.assertFalse(rollback.exists())


if __name__ == "__main__":
    unittest.main()
