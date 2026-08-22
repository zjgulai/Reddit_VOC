from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/task31z_committed_target_acceptance.py"
RUN_ID = "backfill_momcozy_20250101_20260711"
RECOVERED_AT = "2026-07-27T11:42:19+00:00"

SPEC = importlib.util.spec_from_file_location("task31z_acceptance", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


class Task31ZCommittedTargetAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source.sqlite3"
        self.target = self.root / "target.sqlite3"
        self.report = self.root / "recovery-report.json"
        self.raw = self.root / "private-raw"
        self.raw.mkdir()
        (self.raw / "comments-page.json.gz").write_bytes(b"pinned-raw-payload")
        self.old_roots = {
            "Task31": self.root / "task31",
            "Task31X": self.root / "task31x",
        }
        for label, path in self.old_roots.items():
            path.mkdir()
            (path / "receipt.json").write_text(label, encoding="utf-8")
        self._create_source()
        shutil.copyfile(self.source, self.target)
        self._mutate_target()
        self.admission = self.root / "admission.json"
        self.execution = self.root / "execution.json"
        _write_json(
            self.admission,
            {"checks": {"all_pinned": True}, "status": "passed"},
        )
        self._refresh_execution_receipt()

    def _create_source(self) -> None:
        connection = sqlite3.connect(self.source)
        try:
            connection.executescript(
                """
                PRAGMA foreign_keys=ON;
                CREATE TABLE backfill_manifests (
                    run_id TEXT PRIMARY KEY,
                    max_provider_requests INTEGER NOT NULL,
                    provider_request_count INTEGER NOT NULL
                );
                CREATE TABLE backfill_provider_attempts (
                    run_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    PRIMARY KEY (run_id, attempt_id)
                );
                CREATE TABLE backfill_candidates (
                    run_id TEXT NOT NULL,
                    post_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    status_reason TEXT,
                    updated_at_utc TEXT NOT NULL,
                    PRIMARY KEY (run_id, post_id)
                );
                CREATE TABLE backfill_checkpoints (
                    run_id TEXT NOT NULL,
                    lane_type TEXT NOT NULL,
                    lane_key TEXT NOT NULL,
                    cursor TEXT,
                    previous_cursor TEXT,
                    page_number INTEGER NOT NULL,
                    discovered_count INTEGER NOT NULL,
                    unique_count INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    stop_reason TEXT,
                    last_error TEXT,
                    PRIMARY KEY (run_id, lane_type, lane_key)
                );
                CREATE TABLE backfill_raw_artifacts (
                    run_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    artifact_kind TEXT NOT NULL,
                    lane_type TEXT NOT NULL,
                    lane_key_hash TEXT NOT NULL,
                    page_number INTEGER NOT NULL,
                    request_cursor TEXT,
                    response_cursor TEXT,
                    payload_sha256 TEXT NOT NULL,
                    parser_kind TEXT NOT NULL,
                    source_method TEXT NOT NULL,
                    PRIMARY KEY (run_id, artifact_id)
                );
                CREATE TABLE backfill_detail_batches (
                    run_id TEXT NOT NULL,
                    batch_id TEXT NOT NULL,
                    batch_number INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    stop_reason TEXT,
                    artifact_id TEXT,
                    updated_at_utc TEXT NOT NULL,
                    PRIMARY KEY (run_id, batch_id)
                );
                CREATE TABLE backfill_detail_batch_members (
                    run_id TEXT NOT NULL,
                    batch_id TEXT NOT NULL,
                    post_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    PRIMARY KEY (run_id, batch_id, post_id)
                );
                CREATE TABLE reddit_threads (
                    run_id TEXT NOT NULL,
                    post_id TEXT NOT NULL,
                    parsed_comment_count INTEGER NOT NULL,
                    PRIMARY KEY (run_id, post_id)
                );
                CREATE TABLE reddit_comments (
                    run_id TEXT NOT NULL,
                    post_id TEXT NOT NULL,
                    comment_id TEXT NOT NULL,
                    PRIMARY KEY (run_id, comment_id)
                );
                CREATE TABLE analysis_results (
                    run_id TEXT NOT NULL,
                    post_id TEXT NOT NULL,
                    result TEXT NOT NULL,
                    PRIMARY KEY (run_id, post_id)
                );
                CREATE TABLE delivery_previews (
                    run_id TEXT NOT NULL,
                    preview_id TEXT NOT NULL,
                    PRIMARY KEY (run_id, preview_id)
                );
                CREATE TABLE backfill_post_occurrences (
                    run_id TEXT NOT NULL,
                    occurrence_id TEXT NOT NULL,
                    PRIMARY KEY (run_id, occurrence_id)
                );
                """
            )
            connection.execute(
                "INSERT INTO backfill_manifests VALUES (?,?,?)",
                (RUN_ID, 10, 2),
            )
            connection.executemany(
                "INSERT INTO backfill_provider_attempts VALUES (?,?,?)",
                [(RUN_ID, "attempt-1", "success"), (RUN_ID, "attempt-2", "success")],
            )
            candidate_ids = [f"candidate-{index:02d}" for index in range(12)]
            extra_ids = [f"extra-{index:03d}" for index in range(166)]
            connection.executemany(
                "INSERT INTO backfill_candidates VALUES (?,?,?,?,?)",
                [
                    (
                        RUN_ID,
                        post_id,
                        "failed",
                        "comments_schema_drift",
                        "2026-07-14T00:00:00+00:00",
                    )
                    for post_id in candidate_ids
                ],
            )
            connection.executemany(
                "INSERT INTO backfill_candidates VALUES (?,?,?,?,?)",
                [
                    (
                        RUN_ID,
                        post_id,
                        "excluded" if index % 7 == 0 else "hydrated",
                        None,
                        "2026-07-14T00:00:00+00:00",
                    )
                    for index, post_id in enumerate(extra_ids)
                ],
            )
            connection.executemany(
                "INSERT INTO backfill_checkpoints VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        RUN_ID,
                        "comments",
                        post_id,
                        None,
                        None,
                        0,
                        0,
                        0,
                        "partial",
                        "comments_schema_drift",
                        "TikHubSchemaDrift",
                    )
                    for post_id in candidate_ids
                ],
            )
            connection.execute(
                "INSERT INTO backfill_checkpoints VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    RUN_ID,
                    "dynamic_search",
                    "Momcozy",
                    None,
                    None,
                    1,
                    50,
                    50,
                    "partial",
                    "authorized_page_limit",
                    None,
                ),
            )
            artifact_rows = []
            for post_id in candidate_ids:
                lane_hash = hashlib.sha256(post_id.encode()).hexdigest()
                artifact_rows.append(
                    (
                        RUN_ID,
                        f"comments-{post_id}",
                        "comments",
                        "comments",
                        lane_hash,
                        1,
                        None,
                        None,
                        hashlib.sha256(f"payload-{post_id}".encode()).hexdigest(),
                        "tikhub_comments",
                        "tikhub_comments",
                    )
                )
            artifact_rows.append(
                (
                    RUN_ID,
                    "discovery-1",
                    "discovery",
                    "dynamic_search",
                    hashlib.sha256(b"Momcozy").hexdigest(),
                    1,
                    None,
                    None,
                    hashlib.sha256(b"discovery").hexdigest(),
                    "tikhub_search",
                    "tikhub_search",
                )
            )
            for batch_number in range(6):
                artifact_rows.append(
                    (
                        RUN_ID,
                        f"detail-{batch_number}",
                        "detail",
                        "detail_batch",
                        hashlib.sha256(f"batch-{batch_number}".encode()).hexdigest(),
                        1,
                        None,
                        None,
                        hashlib.sha256(f"detail-{batch_number}".encode()).hexdigest(),
                        "tikhub_detail",
                        "tikhub_detail",
                    )
                )
            connection.executemany(
                "INSERT INTO backfill_raw_artifacts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                artifact_rows,
            )
            connection.executemany(
                "INSERT INTO backfill_detail_batches VALUES (?,?,?,?,?,?,?)",
                [
                    (
                        RUN_ID,
                        f"batch-{index}",
                        index,
                        "failed",
                        "comments_schema_drift",
                        f"detail-{index}",
                        "2026-07-14T00:00:00+00:00",
                    )
                    for index in range(6)
                ],
            )
            members: list[tuple[object, ...]] = []
            all_members = candidate_ids + extra_ids
            for index, post_id in enumerate(all_members):
                batch_number = index % 6
                members.append(
                    (
                        RUN_ID,
                        f"batch-{batch_number}",
                        post_id,
                        index // 6,
                    )
                )
            connection.executemany(
                "INSERT INTO backfill_detail_batch_members VALUES (?,?,?,?)",
                members,
            )
            connection.execute(
                "INSERT INTO backfill_post_occurrences VALUES (?,?)",
                (RUN_ID, "occurrence-1"),
            )
            connection.commit()
        finally:
            connection.close()

    def _mutate_target(self) -> None:
        connection = sqlite3.connect(self.target)
        try:
            candidate_ids = [f"candidate-{index:02d}" for index in range(12)]
            for index, post_id in enumerate(candidate_ids):
                if index == 11:
                    status, reason = "excluded", None
                elif index == 10:
                    status, reason = "hydrated", "post_only_coverage"
                else:
                    status, reason = "hydrated", None
                connection.execute(
                    "UPDATE backfill_candidates SET status=?,status_reason=?,"
                    "updated_at_utc=? WHERE run_id=? AND post_id=?",
                    (status, reason, RECOVERED_AT, RUN_ID, post_id),
                )
                checkpoint_status = "partial" if index == 10 else "complete"
                checkpoint_reason = (
                    "post_only_coverage" if index == 10 else "cursor_exhausted"
                )
                connection.execute(
                    "UPDATE backfill_checkpoints SET page_number=1,status=?,"
                    "stop_reason=?,last_error=NULL WHERE run_id=? "
                    "AND lane_type='comments' "
                    "AND lane_key=?",
                    (
                        checkpoint_status,
                        checkpoint_reason,
                        RUN_ID,
                        post_id,
                    ),
                )
                if status == "hydrated":
                    connection.execute(
                        "INSERT INTO reddit_threads VALUES (?,?,?)",
                        (RUN_ID, post_id, 0),
                    )
                    connection.execute(
                        "INSERT INTO analysis_results VALUES (?,?,?)",
                        (RUN_ID, post_id, "archived"),
                    )
            connection.execute(
                "UPDATE backfill_detail_batches SET status='complete',"
                "stop_reason=NULL,updated_at_utc=? WHERE run_id=?",
                (RECOVERED_AT, RUN_ID),
            )
            connection.commit()
        finally:
            connection.close()

    def _refresh_execution_receipt(self) -> None:
        _write_json(
            self.execution,
            {
                "boundaries": {
                    "dingtalk_send": False,
                    "old_root_write": False,
                    "production_deploy": False,
                    "provider_call": False,
                    "raw_write": False,
                    "source_write": False,
                },
                "execution": {
                    "cli_reason": "collection_recovery_target_committed_needs_review",
                    "network_none_gate_passed": True,
                    "provider_call": False,
                    "provider_cap": 0,
                    "recover_collection_invocations": 1,
                    "retry_performed": False,
                    "wrapper_invocations": 1,
                },
                "postflight": {
                    "report_present": False,
                    "source_sha256": _sha256(self.source),
                    "target_sha256": _sha256(self.target),
                },
                "status": "blocked_target_committed_needs_review",
            },
        )

    def _command(self) -> list[str]:
        raw_sha = MODULE._tree_inventory(self.raw)["sha256"]
        command = [
            sys.executable,
            str(SCRIPT),
            "--source-database",
            str(self.source),
            "--raw-archive-dir",
            str(self.raw),
            "--target-database",
            str(self.target),
            "--report",
            str(self.report),
            "--admission-receipt",
            str(self.admission),
            "--execution-receipt",
            str(self.execution),
            "--run-id",
            RUN_ID,
            "--recovered-at-utc",
            RECOVERED_AT,
            "--expected-source-sha256",
            _sha256(self.source),
            "--expected-target-sha256",
            _sha256(self.target),
            "--expected-admission-sha256",
            _sha256(self.admission),
            "--expected-execution-sha256",
            _sha256(self.execution),
            "--expected-raw-inventory-sha256",
            raw_sha,
        ]
        for label, path in self.old_roots.items():
            command.extend(["--old-root", f"{label}={path}"])
            command.extend(
                [
                    "--expected-old-root-sha256",
                    f"{label}={MODULE._tree_inventory(path)['sha256']}",
                ]
            )
        return command

    def _run(self, command: list[str] | None = None) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        completed = subprocess.run(
            self._command() if command is None else command,
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        return completed, json.loads(completed.stdout)

    def test_accepts_bound_committed_target_without_writes(self) -> None:
        source_before = _sha256(self.source)
        target_before = _sha256(self.target)

        completed, receipt = self._run()

        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertEqual(receipt["status"], "passed")
        self.assertEqual(
            receipt["verdict"],
            "accepted_recovery_candidate_not_original_cli_complete",
        )
        self.assertTrue(receipt["reconstructed_recovery_contract_valid"])
        self.assertFalse(receipt["original_cli_recovery_contract_valid"])
        self.assertEqual(
            receipt["original_cli_contract_divergences"],
            ["recovered_discovery_lane_count_must_be_positive"],
        )
        self.assertEqual(
            receipt["reconstructed_recovery"]["recovered_discovery_lane_count"],
            0,
        )
        self.assertEqual(receipt["owner_batch_count"], 6)
        self.assertEqual(receipt["extra_owner_member_count"], 166)
        self.assertFalse(receipt["boundaries"]["target_write"])
        self.assertEqual(_sha256(self.source), source_before)
        self.assertEqual(_sha256(self.target), target_before)
        self.assertFalse(self.report.exists())
        self.assertFalse(Path(str(self.target) + "-wal").exists())

    def test_target_hash_drift_fails_closed(self) -> None:
        command = self._command()
        connection = sqlite3.connect(self.target)
        try:
            connection.execute(
                "UPDATE backfill_candidates SET status_reason='drift' "
                "WHERE run_id=? AND post_id='candidate-00'",
                (RUN_ID,),
            )
            connection.commit()
        finally:
            connection.close()

        completed, receipt = self._run(command)

        self.assertEqual(completed.returncode, 3)
        self.assertEqual(receipt["status"], "failed")
        self.assertIn("target_database_sha256_mismatch", receipt["errors"][0])
        self.assertFalse(self.report.exists())

    def test_existing_original_report_fails_closed(self) -> None:
        self.report.write_text("not-an-original-cli-report", encoding="utf-8")

        completed, receipt = self._run()

        self.assertEqual(completed.returncode, 3)
        self.assertEqual(receipt["verdict"], "quarantine_preserved")
        self.assertIn("original_recovery_report_present", receipt["errors"][0])

    def test_raw_or_old_root_inventory_drift_fails_closed(self) -> None:
        command = self._command()
        (self.raw / "comments-page.json.gz").write_bytes(b"drift")

        completed, receipt = self._run(command)

        self.assertEqual(completed.returncode, 3)
        self.assertIn("raw_inventory_sha256_mismatch", receipt["errors"][0])
        self.assertFalse(receipt["boundaries"]["remote_write"])


if __name__ == "__main__":
    unittest.main()
