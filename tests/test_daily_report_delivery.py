from __future__ import annotations

import json
import io
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from reddit_voc import cli
from reddit_voc.daily_report_delivery import (
    append_delivery_event,
    evaluate_duplicate_guard,
    load_and_verify_delivery_ledger,
    send_report_failure_alert,
    send_prepared_daily_report,
)
from reddit_voc.dingtalk import DingTalkSendResult, DingTalkTransportError, send_payload_bytes
from reddit_voc.prepared_report import (
    PreparedAttemptContext,
    build_blocked_translation_attempt,
    prepare_daily_report,
    write_blocked_attempt,
)
from reddit_voc.translation_pipeline import TranslationService
import tests.test_prepared_report as prepared_fixtures


CONFIG_ROOT = Path(__file__).resolve().parents[1] / "config"


class SyntheticSentTransport:
    transport_kind = "synthetic"

    def __init__(self) -> None:
        self.calls: list[bytes] = []
        self.credentials: list[tuple[str, str | None]] = []

    def __call__(
        self,
        *,
        webhook_url,
        body_bytes,
        secret,
        timeout_seconds,
        request_start_sink,
    ):
        if request_start_sink is not None:
            raise AssertionError("synthetic transport must not receive external sink")
        self.calls.append(body_bytes)
        self.credentials.append((webhook_url, secret))
        return DingTalkSendResult(
            status="sent",
            http_status=200,
            response_hash="sha256:" + "f" * 64,
            response_text="fixture-ok",
            live_send=False,
            external_attempt_made=False,
        )


class ExternalUnknownTransport:
    transport_kind = "external"

    def __call__(
        self,
        *,
        webhook_url,
        body_bytes,
        secret,
        timeout_seconds,
        request_start_sink,
    ):
        request_start_sink()
        raise DingTalkTransportError(
            "transport_timeout", external_attempt_made=True
        )


class ExternalSentTransport:
    transport_kind = "external"

    def __call__(
        self,
        *,
        webhook_url,
        body_bytes,
        secret,
        timeout_seconds,
        request_start_sink,
    ):
        request_start_sink()
        return DingTalkSendResult(
            status="sent",
            http_status=200,
            response_hash="sha256:" + "e" * 64,
            response_text="fixture-ok",
            live_send=True,
            external_attempt_made=True,
        )


class DailyReportDeliveryTests(unittest.TestCase):
    def _prepared(self, root: Path):
        helper = prepared_fixtures.PreparedReportTests()
        database = helper._database(root)
        roots = helper._roots(root)
        preflight = helper._preflight(database, roots)
        result = prepare_daily_report(
            preflight,
            attempt=PreparedAttemptContext(
                attempt_id="attempt-delivery-fixture",
                artifact_version_id="20260713T020304567890Z-" + "a" * 32,
            ),
            translator=TranslationService(
                client=prepared_fixtures.PreparedFakeClient(), assets=preflight.translation_assets
            ),
            roots=roots,
            provider_authorization_id="provider-auth-delivery",
            prepare_action_authorization_id="prepare-action-delivery",
        )
        return database, roots, result

    def _send_cli_args(self, *, database, roots, prepared):
        return [
            "send-prepared-daily-report",
            "--database",
            str(database),
            "--run-id",
            prepared.run_id,
            "--expected-artifact-version-id",
            prepared.artifact_version_id,
            "--expected-bundle-sha256",
            prepared.bundle_sha256,
            "--expected-outbox-sha256",
            prepared.outbox_sha256,
            "--authorization-id",
            "send-auth-cli",
            "--public-root",
            str(roots.public_root),
            "--private-root",
            str(roots.private_root),
            "--state-root",
            str(roots.state_root),
            "--config-root",
            str(CONFIG_ROOT),
            "--timeout-seconds",
            "10",
        ]

    def test_fresh_cli_import_has_no_renderer_or_deepseek_modules(self) -> None:
        command = [
            sys.executable,
            "-c",
            (
                "import sys; import reddit_voc.cli; "
                "assert 'reddit_voc.daily_report' not in sys.modules; "
                "assert 'reddit_voc.deepseek_client' not in sys.modules; "
                "assert 'reddit_voc.translation_pipeline' not in sys.modules"
            ),
        ]
        completed = subprocess.run(
            command,
            cwd=CONFIG_ROOT.parent,
            env={**os.environ, "PYTHONPATH": str(CONFIG_ROOT.parent / "src")},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_artifact_head_checker_rejects_ssrf_target_before_network(self) -> None:
        checker = cli._prepared_artifact_head_checker()
        with patch("urllib.request.OpenerDirector.open") as mocked_open:
            with self.assertRaisesRegex(ValueError, "artifact_url_invalid"):
                checker("http://127.0.0.1:8080/redirect", timeout_seconds=2)
        mocked_open.assert_not_called()

    def test_prepared_dingtalk_credentials_read_only_primary_secret_file_values(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            secret_path = Path(tmp) / "reddit_voc_report.env"
            secret_path.write_bytes(
                b"# report runtime\n"
                b"REDDIT_VOC_DINGTALK_MODE=live\n"
                b"DINGTALK_WEBHOOK_URL=https://file.invalid/robot/send?token=file\n"
                b"DINGTALK_WEBHOOK_SECRET=synthetic-file-signing-secret\n"
                b"UNRELATED_FIELD=must-not-be-returned\n"
            )
            secret_path.chmod(0o600)

            credentials = cli._prepared_dingtalk_credentials(path=secret_path)

            self.assertEqual(
                credentials,
                (
                    "https://file.invalid/robot/send?token=file",
                    "synthetic-file-signing-secret",
                ),
            )

    def test_prepared_dingtalk_credentials_reject_symlink_and_wrong_mode(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target.env"
            target.write_bytes(
                b"DINGTALK_WEBHOOK_URL=https://file.invalid/robot/send\n"
                b"DINGTALK_WEBHOOK_SECRET=secret\n"
            )
            target.chmod(0o600)
            link = root / "linked.env"
            link.symlink_to(target)
            with self.assertRaisesRegex(
                RuntimeError, "dingtalk_secret_file_not_regular"
            ):
                cli._prepared_dingtalk_credentials(path=link)

            target.chmod(0o640)
            with self.assertRaisesRegex(
                RuntimeError, "dingtalk_secret_file_mode_invalid"
            ):
                cli._prepared_dingtalk_credentials(path=target)

    def test_prepared_dingtalk_credentials_reject_duplicates_secondary_and_size(
        self,
    ) -> None:
        cases = {
            "duplicate": (
                b"DINGTALK_WEBHOOK_URL=https://one.invalid/robot/send\n"
                b"DINGTALK_WEBHOOK_URL=https://two.invalid/robot/send\n"
                b"DINGTALK_WEBHOOK_SECRET=secret\n",
                "dingtalk_secret_file_duplicate_key",
            ),
            "secondary_url": (
                b"DINGTALK_WEBHOOK_URL=https://one.invalid/robot/send\n"
                b"DINGTALK_WEBHOOK_SECRET=secret\n"
                b"DINGTALK_WEBHOOK_URL_2=\n",
                "dingtalk_secret_file_secondary_forbidden",
            ),
            "secondary_secret": (
                b"DINGTALK_WEBHOOK_URL=https://one.invalid/robot/send\n"
                b"DINGTALK_WEBHOOK_SECRET=secret\n"
                b"DINGTALK_WEBHOOK_SECRET_2=\n",
                "dingtalk_secret_file_secondary_forbidden",
            ),
            "too_large": (
                b"DINGTALK_WEBHOOK_URL=https://one.invalid/robot/send\n"
                b"DINGTALK_WEBHOOK_SECRET=secret\n"
                + b"UNRELATED_FIELD="
                + b"x" * (64 * 1024),
                "dingtalk_secret_file_too_large",
            ),
        }
        for label, (payload, reason) in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                secret_path = Path(tmp) / "reddit_voc_report.env"
                secret_path.write_bytes(payload)
                secret_path.chmod(0o600)
                with self.assertRaisesRegex(RuntimeError, reason):
                    cli._prepared_dingtalk_credentials(path=secret_path)

    def test_send_prepared_cli_missing_gate_blocks_before_head_or_transport(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database, roots, prepared = self._prepared(Path(tmp))
            output = io.StringIO()
            with patch.dict(
                os.environ,
                {
                    "REDDIT_VOC_DINGTALK_MODE": "dry_run",
                    "REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND": "0",
                    "DINGTALK_WEBHOOK_URL": "https://oapi.dingtalk.com/robot/send?access_token=unit",
                },
                clear=False,
            ), patch(
                "reddit_voc.cli._prepared_artifact_head_checker",
                side_effect=AssertionError("HEAD forbidden"),
            ), patch(
                "reddit_voc.cli._prepared_delivery_transport",
                side_effect=AssertionError("transport forbidden"),
            ), redirect_stdout(output):
                result = cli.main(
                    self._send_cli_args(
                        database=database, roots=roots, prepared=prepared
                    )
                )
            self.assertEqual(result, 1)
            summary = json.loads(output.getvalue())
            self.assertEqual(summary["reason"], "dingtalk_mode_not_live")
            self.assertFalse(summary["live_send"])

    def test_send_cli_defers_dingtalk_credentials_until_after_artifact_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database, roots, prepared = self._prepared(Path(tmp))
            output = io.StringIO()
            with patch.dict(
                os.environ,
                {
                    "REDDIT_VOC_DINGTALK_MODE": "live",
                    "REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND": "1",
                    "DINGTALK_WEBHOOK_URL": "",
                    "DINGTALK_WEBHOOK_SECRET": "",
                },
                clear=False,
            ), patch(
                "reddit_voc.cli._prepared_artifact_head_checker",
                return_value=lambda url, timeout_seconds: 503,
            ), patch(
                "reddit_voc.cli._prepared_delivery_transport",
                return_value=SyntheticSentTransport(),
            ), redirect_stdout(output):
                result = cli.main(
                    [
                        *self._send_cli_args(
                            database=database, roots=roots, prepared=prepared
                        ),
                        "--authorize-live-send",
                    ]
                )

            self.assertEqual(result, 1)
            summary = json.loads(output.getvalue())
            self.assertEqual(summary["status"], "artifact_preflight_blocked")
            self.assertFalse(summary["report_live_send"])
            self.assertFalse(summary["live_send"])

    def test_send_prepared_cli_uses_synthetic_transport_without_provider_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database, roots, prepared = self._prepared(Path(tmp))
            secret_path = Path(tmp) / "reddit_voc_report.env"
            secret_path.write_bytes(
                b"DINGTALK_WEBHOOK_URL=https://file.invalid/robot/send?token=file\n"
                b"DINGTALK_WEBHOOK_SECRET=synthetic-file-signing-secret\n"
            )
            secret_path.chmod(0o600)
            transport = SyntheticSentTransport()
            output = io.StringIO()
            with patch.dict(
                os.environ,
                {
                    "REDDIT_VOC_DINGTALK_MODE": "live",
                    "REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND": "1",
                    "DINGTALK_WEBHOOK_URL": "https://env.invalid/must-not-be-used",
                    "DINGTALK_WEBHOOK_SECRET": "env-must-not-be-used",
                    "DINGTALK_WEBHOOK_URL_2": "https://env-secondary.invalid/must-not-be-used",
                    "DINGTALK_WEBHOOK_SECRET_2": "env-secondary-must-not-be-used",
                },
                clear=False,
            ), patch.object(
                cli,
                "_PREPARED_DINGTALK_CREDENTIAL_PATH",
                secret_path,
            ), patch(
                "reddit_voc.cli._prepared_artifact_head_checker",
                return_value=lambda url, timeout_seconds: 200,
            ), patch(
                "reddit_voc.cli._prepared_delivery_transport",
                return_value=transport,
            ), redirect_stdout(output):
                result = cli.main(
                    [
                        *self._send_cli_args(
                            database=database, roots=roots, prepared=prepared
                        ),
                        "--authorize-live-send",
                    ]
                )
            self.assertEqual(result, 0, output.getvalue())
            summary = json.loads(output.getvalue())
            self.assertEqual(summary["status"], "sent")
            self.assertFalse(summary["report_live_send"])
            self.assertFalse(summary["live_send"])
            self.assertEqual(len(transport.calls), 1)
            self.assertEqual(
                transport.credentials,
                [
                    (
                        "https://file.invalid/robot/send?token=file",
                        "synthetic-file-signing-secret",
                    )
                ],
            )

    def test_synthetic_send_uses_frozen_bytes_and_writes_hash_chain_and_db_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database, roots, prepared = self._prepared(Path(tmp))
            head_urls = []
            transport = SyntheticSentTransport()
            summary = send_prepared_daily_report(
                database=database,
                run_id=prepared.run_id,
                expected_artifact_version_id=prepared.artifact_version_id,
                expected_bundle_sha256=prepared.bundle_sha256,
                expected_outbox_sha256=prepared.outbox_sha256,
                authorization_id="send-auth-fixture",
                roots=roots,
                config_root=CONFIG_ROOT,
                webhook_url="https://oapi.dingtalk.com/robot/send?access_token=unit",
                webhook_secret=None,
                timeout_seconds=10,
                authorize_live_send=True,
                head_checker=lambda url, timeout_seconds: head_urls.append(url) or 200,
                transport=transport,
            )
            self.assertEqual(summary.status, "sent")
            self.assertEqual(summary.sent_part_indexes, (1,))
            self.assertFalse(summary.report_live_send)
            self.assertFalse(summary.live_send)
            frozen_path = prepared.private_dir / "outbox" / "part-0001.json"
            self.assertEqual(transport.calls, [frozen_path.read_bytes()])
            self.assertGreaterEqual(len(head_urls), 3)

            ledger_path = (
                roots.state_root / "delivery" / prepared.run_id / "ledger.jsonl"
            )
            entries = load_and_verify_delivery_ledger(
                ledger_path, run_id=prepared.run_id
            )
            self.assertEqual([row["status"] for row in entries], ["attempting", "sent"])
            self.assertTrue(all(not row["external_attempt_made"] for row in entries))
            with sqlite3.connect(database) as connection:
                rows = connection.execute(
                    "SELECT mode,status,live_send FROM delivery_previews WHERE run_id=?",
                    (prepared.run_id,),
                ).fetchall()
            self.assertEqual(rows, [("synthetic", "sent", 0)])

    def test_secondary_webhook_is_blocked_before_any_transport_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database, roots, prepared = self._prepared(Path(tmp))
            transport = SyntheticSentTransport()
            summary = send_prepared_daily_report(
                database=database,
                run_id=prepared.run_id,
                expected_artifact_version_id=prepared.artifact_version_id,
                expected_bundle_sha256=prepared.bundle_sha256,
                expected_outbox_sha256=prepared.outbox_sha256,
                authorization_id="send-auth-secondary-block",
                roots=roots,
                config_root=CONFIG_ROOT,
                webhook_url="https://oapi.dingtalk.com/robot/send?access_token=primary",
                webhook_secret=None,
                webhook_url_2="https://oapi.dingtalk.com/robot/send?access_token=secondary",
                webhook_secret_2=None,
                timeout_seconds=10,
                authorize_live_send=True,
                head_checker=lambda _url, timeout_seconds: 200,
                transport=transport,
            )

            self.assertEqual(summary.status, "secondary_webhook_not_supported")
            self.assertEqual(summary.attempted_part_indexes, ())
            self.assertEqual(transport.calls, [])


    def test_failed_or_zero_source_state_blocks_before_head_credentials_and_transport(self) -> None:
        for mutation in ("failed", "zero_success"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                database, roots, prepared = self._prepared(Path(tmp))
                with sqlite3.connect(database) as connection:
                    if mutation == "failed":
                        connection.execute(
                            "UPDATE runs SET status='failed' WHERE run_id=?",
                            (prepared.run_id,),
                        )
                    else:
                        connection.execute("DELETE FROM analysis_results WHERE run_id=?", (prepared.run_id,))
                        connection.execute("DELETE FROM reddit_comments WHERE run_id=?", (prepared.run_id,))
                        connection.execute("DELETE FROM reddit_threads WHERE run_id=?", (prepared.run_id,))
                head_calls = []
                credential_calls = []
                transport = SyntheticSentTransport()
                summary = send_prepared_daily_report(
                    database=database,
                    run_id=prepared.run_id,
                    expected_artifact_version_id=prepared.artifact_version_id,
                    expected_bundle_sha256=prepared.bundle_sha256,
                    expected_outbox_sha256=prepared.outbox_sha256,
                    authorization_id="send-auth-source-gate",
                    roots=roots,
                    config_root=CONFIG_ROOT,
                    webhook_url="",
                    webhook_secret=None,
                    timeout_seconds=10,
                    authorize_live_send=True,
                    head_checker=lambda url, timeout_seconds: head_calls.append(url) or 200,
                    credential_loader=lambda: credential_calls.append(True) or (
                        "https://oapi.dingtalk.com/robot/send?access_token=unit",
                        None,
                    ),
                    transport=transport,
                )
                self.assertEqual(summary.status, "source_state_not_sendable")
                self.assertEqual(head_calls, [])
                self.assertEqual(credential_calls, [])
                self.assertEqual(transport.calls, [])

    def test_send_blocks_when_sendable_source_state_changes_after_prepare(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database, roots, prepared = self._prepared(Path(tmp))
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "UPDATE runs SET status='partial' WHERE run_id=?", (prepared.run_id,)
                )
            transport = SyntheticSentTransport()
            summary = send_prepared_daily_report(
                database=database,
                run_id=prepared.run_id,
                expected_artifact_version_id=prepared.artifact_version_id,
                expected_bundle_sha256=prepared.bundle_sha256,
                expected_outbox_sha256=prepared.outbox_sha256,
                authorization_id="send-auth-source-changed",
                roots=roots,
                config_root=CONFIG_ROOT,
                webhook_url="https://oapi.dingtalk.com/robot/send?access_token=unit",
                webhook_secret=None,
                timeout_seconds=10,
                authorize_live_send=True,
                head_checker=lambda url, timeout_seconds: 200,
                transport=transport,
            )
            self.assertEqual(summary.status, "source_state_changed_after_prepare")
            self.assertEqual(transport.calls, [])

    def test_duplicate_db_or_ledger_blocks_before_head_and_transport(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database, roots, prepared = self._prepared(Path(tmp))
            first_transport = SyntheticSentTransport()
            send_prepared_daily_report(
                database=database,
                run_id=prepared.run_id,
                expected_artifact_version_id=prepared.artifact_version_id,
                expected_bundle_sha256=prepared.bundle_sha256,
                expected_outbox_sha256=prepared.outbox_sha256,
                authorization_id="send-auth-first",
                roots=roots,
                config_root=CONFIG_ROOT,
                webhook_url="https://oapi.dingtalk.com/robot/send?access_token=unit",
                webhook_secret=None,
                timeout_seconds=10,
                authorize_live_send=True,
                head_checker=lambda url, timeout_seconds: 200,
                transport=first_transport,
            )
            head_calls = []
            second_transport = SyntheticSentTransport()
            summary = send_prepared_daily_report(
                database=database,
                run_id=prepared.run_id,
                expected_artifact_version_id=prepared.artifact_version_id,
                expected_bundle_sha256=prepared.bundle_sha256,
                expected_outbox_sha256=prepared.outbox_sha256,
                authorization_id="send-auth-second",
                roots=roots,
                config_root=CONFIG_ROOT,
                webhook_url="https://oapi.dingtalk.com/robot/send?access_token=unit",
                webhook_secret=None,
                timeout_seconds=10,
                authorize_live_send=True,
                head_checker=lambda url, timeout_seconds: head_calls.append(url) or 200,
                transport=second_transport,
            )
            self.assertEqual(summary.status, "blocked_duplicate")
            self.assertEqual(head_calls, [])
            self.assertEqual(second_transport.calls, [])

    def test_external_attempt_failure_becomes_unknown_and_sets_live_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database, roots, prepared = self._prepared(Path(tmp))
            summary = send_prepared_daily_report(
                database=database,
                run_id=prepared.run_id,
                expected_artifact_version_id=prepared.artifact_version_id,
                expected_bundle_sha256=prepared.bundle_sha256,
                expected_outbox_sha256=prepared.outbox_sha256,
                authorization_id="send-auth-unknown",
                roots=roots,
                config_root=CONFIG_ROOT,
                webhook_url="https://oapi.dingtalk.com/robot/send?access_token=unit",
                webhook_secret=None,
                timeout_seconds=10,
                authorize_live_send=True,
                head_checker=lambda url, timeout_seconds: 200,
                transport=ExternalUnknownTransport(),
            )
            self.assertEqual(summary.status, "unknown_delivery_state")
            self.assertTrue(summary.report_live_send)
            self.assertTrue(summary.live_send)
            ledger_path = (
                roots.state_root / "delivery" / prepared.run_id / "ledger.jsonl"
            )
            entries = load_and_verify_delivery_ledger(
                ledger_path, run_id=prepared.run_id
            )
            self.assertEqual(
                [row["status"] for row in entries],
                ["attempting", "unknown_delivery_state"],
            )
            with sqlite3.connect(database) as connection:
                count = connection.execute(
                    "SELECT COUNT(*) FROM delivery_previews WHERE run_id=?",
                    (prepared.run_id,),
                ).fetchone()[0]
            self.assertEqual(count, 0)

    def test_terminal_ledger_failure_after_request_preserves_external_attempt_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database, roots, prepared = self._prepared(Path(tmp))

            def flaky_append(path, *, event):
                if event["status"] == "sent":
                    raise OSError("simulated terminal fsync failure")
                return append_delivery_event(path, event=event)

            with patch(
                "reddit_voc.daily_report_delivery.append_delivery_event",
                side_effect=flaky_append,
            ), self.assertRaisesRegex(
                RuntimeError, "delivery_terminal_ledger_write_failed"
            ) as raised:
                send_prepared_daily_report(
                    database=database,
                    run_id=prepared.run_id,
                    expected_artifact_version_id=prepared.artifact_version_id,
                    expected_bundle_sha256=prepared.bundle_sha256,
                    expected_outbox_sha256=prepared.outbox_sha256,
                    authorization_id="send-auth-ledger-failure",
                    roots=roots,
                    config_root=CONFIG_ROOT,
                    webhook_url="https://oapi.dingtalk.com/robot/send?access_token=unit",
                    webhook_secret=None,
                    timeout_seconds=10,
                    authorize_live_send=True,
                    head_checker=lambda url, timeout_seconds: 200,
                    transport=ExternalSentTransport(),
                )

            self.assertTrue(raised.exception.external_attempt_made)
            ledger = load_and_verify_delivery_ledger(
                roots.state_root / "delivery" / prepared.run_id / "ledger.jsonl",
                run_id=prepared.run_id,
            )
            self.assertEqual(
                [(row["status"], row["external_attempt_made"]) for row in ledger],
                [("attempting", True)],
            )

    def test_database_record_failure_after_sent_returns_live_failure_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database, roots, prepared = self._prepared(Path(tmp))
            with patch(
                "reddit_voc.daily_report_delivery._insert_delivery_record",
                side_effect=RuntimeError("delivery_database_write_failed"),
            ):
                summary = send_prepared_daily_report(
                    database=database,
                    run_id=prepared.run_id,
                    expected_artifact_version_id=prepared.artifact_version_id,
                    expected_bundle_sha256=prepared.bundle_sha256,
                    expected_outbox_sha256=prepared.outbox_sha256,
                    authorization_id="send-auth-db-failure",
                    roots=roots,
                    config_root=CONFIG_ROOT,
                    webhook_url="https://oapi.dingtalk.com/robot/send?access_token=unit",
                    webhook_secret=None,
                    timeout_seconds=10,
                    authorize_live_send=True,
                    head_checker=lambda url, timeout_seconds: 200,
                    transport=ExternalSentTransport(),
                )

            self.assertEqual(summary.status, "delivery_database_write_failed")
            self.assertEqual(summary.sent_part_indexes, (1,))
            self.assertTrue(summary.report_live_send)
            self.assertTrue(summary.live_send)

    def test_failure_alert_external_request_boundary_sets_live_evidence_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            helper = prepared_fixtures.PreparedReportTests()
            roots = helper._roots(root)
            manifest = build_blocked_translation_attempt(
                run_id="daily_collect_20260713_0700",
                attempt_id="attempt-alert-external",
                preflight=None,
                pipeline_evidence=None,
                stage="gate",
                reason_codes=["translation_mode_not_deepseek"],
                provider_authorization_id=None,
            )
            write_blocked_attempt(
                roots=roots,
                run_id="daily_collect_20260713_0700",
                attempt_id="attempt-alert-external",
                manifest=manifest,
            )
            captured = {}

            class FakeResponse:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

                def read(self, size=-1):
                    return b'{"errcode":0,"errmsg":"ok"}'

            def fake_urlopen(request, timeout):
                captured["body"] = json.loads(request.data.decode("utf-8"))
                captured["timeout"] = timeout
                return FakeResponse()

            with patch("reddit_voc.dingtalk.urlopen", side_effect=fake_urlopen):
                summary = send_report_failure_alert(
                    roots=roots,
                    run_id="daily_collect_20260713_0700",
                    attempt_id="attempt-alert-external",
                    stage="gate",
                    reason_code="translation_mode_not_deepseek",
                    occurred_at=datetime(2026, 7, 13, 2, 0, tzinfo=timezone.utc),
                    webhook_url="https://oapi.dingtalk.com/robot/send?access_token=unit",
                    webhook_secret=None,
                    timeout_seconds=10,
                    authorize_failure_alert=True,
                    transport=send_payload_bytes,
                )

            self.assertEqual(summary.status, "sent")
            self.assertTrue(summary.alert_live_send)
            self.assertTrue(summary.live_send)
            alert_text = captured["body"]["markdown"]["text"]
            self.assertNotIn("attempt_id=", alert_text)
            self.assertIn("run_id=daily_collect_20260713_0700", alert_text)
            entries = load_and_verify_delivery_ledger(
                roots.state_root
                / "delivery"
                / "daily_collect_20260713_0700"
                / "ledger.jsonl",
                run_id="daily_collect_20260713_0700",
            )
            self.assertEqual(
                [(row["status"], row["external_attempt_made"]) for row in entries],
                [("attempting", True), ("sent", True)],
            )

    def test_ledger_rejects_noncanonical_or_broken_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = root / "delivery" / "run-one" / "ledger.jsonl"
            event = {
                "schema_version": "delivery-event-v1",
                "run_id": "run-one",
                "artifact_version_id": None,
                "bundle_sha256": None,
                "outbox_sha256": None,
                "part_kind": "failure_alert",
                "part_index": 1,
                "part_sha256": "a" * 64,
                "authorization_id": "alert-auth",
                "attempt_id": "attempt-one",
                "timestamp": "2026-07-13T02:00:00+00:00",
                "status": "rejected",
                "external_attempt_made": False,
                "http_status": 400,
                "response_hash": "sha256:" + "b" * 64,
            }
            append_delivery_event(ledger, event=event)
            original = ledger.read_text(encoding="utf-8")
            ledger.write_text(original.replace("\":", "\": ", 1), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "delivery_ledger_noncanonical"):
                load_and_verify_delivery_ledger(ledger, run_id="run-one")

    def test_concurrent_ledger_appends_keep_one_canonical_hash_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "delivery" / "run-concurrent" / "ledger.jsonl"

            def append(index: int) -> None:
                append_delivery_event(
                    ledger,
                    event={
                        "schema_version": "delivery-event-v1",
                        "run_id": "run-concurrent",
                        "artifact_version_id": None,
                        "bundle_sha256": None,
                        "outbox_sha256": None,
                        "part_kind": "failure_alert",
                        "part_index": index + 1,
                        "part_sha256": f"{index + 1:064x}",
                        "authorization_id": f"alert-auth-{index}",
                        "attempt_id": f"attempt-{index}",
                        "timestamp": "2026-08-11T02:00:00+00:00",
                        "status": "rejected",
                        "external_attempt_made": False,
                        "http_status": 400,
                        "response_hash": "sha256:" + f"{index + 100:064x}",
                    },
                )

            with ThreadPoolExecutor(max_workers=8) as executor:
                tuple(executor.map(append, range(32)))

            entries = load_and_verify_delivery_ledger(
                ledger, run_id="run-concurrent"
            )
            self.assertEqual(len(entries), 32)
            self.assertEqual(
                [entry["sequence"] for entry in entries], list(range(1, 33))
            )
            self.assertEqual(
                {entry["attempt_id"] for entry in entries},
                {f"attempt-{index}" for index in range(32)},
            )

    def test_resend_guard_accepts_only_explicit_rejected_parts(self) -> None:
        ledger = [
            {
                "status": "rejected",
                "part_kind": "report",
                "part_index": 2,
                "outbox_sha256": "c" * 64,
                "external_attempt_made": True,
            }
        ]
        decision = evaluate_duplicate_guard(
            ledger_entries=ledger,
            db_records=(),
            expected_outbox_sha256="c" * 64,
            authorize_resend=True,
            requested_part_indexes=(2,),
        )
        self.assertEqual(decision.sendable_part_indexes, (2,))
        self.assertIsNone(decision.blocked_reason)
        blocked = evaluate_duplicate_guard(
            ledger_entries=ledger,
            db_records=(),
            expected_outbox_sha256="c" * 64,
            authorize_resend=False,
            requested_part_indexes=(),
        )
        self.assertEqual(blocked.blocked_reason, "resend_authorization_required")

    def test_resend_guard_allows_only_rejected_remainder_after_partial_success(self) -> None:
        outbox = "c" * 64
        sent_part_sha = "a" * 64
        ledger = [
            {
                "status": "sent",
                "part_kind": "report",
                "part_index": 1,
                "part_sha256": sent_part_sha,
                "outbox_sha256": outbox,
                "external_attempt_made": True,
            },
            {
                "status": "rejected",
                "part_kind": "report",
                "part_index": 2,
                "part_sha256": "b" * 64,
                "outbox_sha256": outbox,
                "external_attempt_made": True,
            },
        ]
        db_records = (
            {
                "delivery_id": "prepared-part-one",
                "status": "sent",
                "message_hash": "sha256:" + sent_part_sha,
                "live_send": True,
            },
        )
        decision = evaluate_duplicate_guard(
            ledger_entries=ledger,
            db_records=db_records,
            expected_outbox_sha256=outbox,
            authorize_resend=True,
            requested_part_indexes=(2,),
        )
        self.assertEqual(decision.sendable_part_indexes, (2,))
        self.assertIsNone(decision.blocked_reason)

        for unsafe_ledger in [
            [*ledger, {**ledger[0], "part_kind": "failure_alert", "part_index": 1}],
            [*ledger, {**ledger[1], "status": "unknown_delivery_state"}],
            [{**ledger[0], "outbox_sha256": "d" * 64}, ledger[1]],
        ]:
            with self.subTest(unsafe_ledger=unsafe_ledger):
                blocked = evaluate_duplicate_guard(
                    ledger_entries=unsafe_ledger,
                    db_records=db_records,
                    expected_outbox_sha256=outbox,
                    authorize_resend=True,
                    requested_part_indexes=(2,),
                )
                self.assertIsNotNone(blocked.blocked_reason)


if __name__ == "__main__":
    unittest.main()
