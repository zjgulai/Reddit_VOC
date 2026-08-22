from __future__ import annotations

import json
import io
import os
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from reddit_voc import cli
from reddit_voc.daily_report_delivery import (
    DingTalkDestinationCredential,
    load_and_verify_delivery_ledger,
    send_prepared_daily_report_to_destinations,
)
from reddit_voc.dingtalk import DingTalkSendResult
from reddit_voc.prepared_report import (
    PreparedAttemptContext,
    prepare_daily_report,
)
from reddit_voc.translation_pipeline import TranslationService
import tests.test_prepared_report as prepared_fixtures


CONFIG_ROOT = Path(__file__).resolve().parents[1] / "config"


class SimulatedHardCrash(BaseException):
    pass


class RoutingSyntheticTransport:
    transport_kind = "synthetic"

    def __init__(self, outcomes: dict[str, str | BaseException] | None = None):
        self.outcomes = outcomes or {}
        self.calls: list[tuple[str, bytes]] = []
        self._lock = threading.Lock()

    @staticmethod
    def destination(webhook_url: str) -> str:
        if webhook_url.endswith("=primary"):
            return "primary"
        if webhook_url.endswith("=secondary"):
            return "secondary"
        raise AssertionError("unexpected synthetic destination")

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
            raise AssertionError("synthetic transport received external sink")
        destination = self.destination(webhook_url)
        with self._lock:
            self.calls.append((destination, body_bytes))
        outcome = self.outcomes.get(destination, "sent")
        if isinstance(outcome, BaseException):
            raise outcome
        return DingTalkSendResult(
            status=outcome,
            http_status=200 if outcome == "sent" else 400,
            response_hash="sha256:" + ("a" if outcome == "sent" else "b") * 64,
            response_text="synthetic",
            live_send=False,
            external_attempt_made=False,
        )


class DualDestinationDeliveryTests(unittest.TestCase):
    def _prepared(self, root: Path):
        helper = prepared_fixtures.PreparedReportTests()
        database = helper._database(root)
        roots = helper._roots(root)
        preflight = helper._preflight(database, roots)
        result = prepare_daily_report(
            preflight,
            attempt=PreparedAttemptContext(
                attempt_id="attempt-dual-destination",
                artifact_version_id="20260811T131826000000Z-" + "b" * 32,
            ),
            translator=TranslationService(
                client=prepared_fixtures.PreparedFakeClient(),
                assets=preflight.translation_assets,
            ),
            roots=roots,
            provider_authorization_id="provider-auth-dual-fixture",
            prepare_action_authorization_id="prepare-action-dual-fixture",
        )
        return database, roots, result

    @staticmethod
    def _credentials():
        return (
            DingTalkDestinationCredential(
                destination_id="primary",
                webhook_url=(
                    "https://oapi.dingtalk.com/robot/send?access_token=primary"
                ),
                webhook_secret="primary-secret",
            ),
            DingTalkDestinationCredential(
                destination_id="secondary",
                webhook_url=(
                    "https://oapi.dingtalk.com/robot/send?access_token=secondary"
                ),
                webhook_secret="secondary-secret",
            ),
        )

    def _send(self, database, roots, prepared, transport, **overrides):
        values = {
            "database": database,
            "run_id": prepared.run_id,
            "expected_artifact_version_id": prepared.artifact_version_id,
            "expected_bundle_sha256": prepared.bundle_sha256,
            "expected_outbox_sha256": prepared.outbox_sha256,
            "authorization_id": "send-auth-dual",
            "roots": roots,
            "config_root": CONFIG_ROOT,
            "timeout_seconds": 10,
            "authorize_live_send": True,
            "head_checker": lambda _url, timeout_seconds: 200,
            "transport": transport,
            "destination_credentials": self._credentials(),
        }
        values.update(overrides)
        return send_prepared_daily_report_to_destinations(**values)

    @staticmethod
    def _destination_ledger(roots, run_id: str, destination_id: str) -> Path:
        return (
            roots.state_root
            / "delivery"
            / run_id
            / "destinations"
            / destination_id
            / "ledger.jsonl"
        )

    def test_dual_credentials_are_file_only_complete_and_ordered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.env"
            path.write_bytes(
                b"DINGTALK_WEBHOOK_URL=https://oapi.dingtalk.com/robot/send?access_token=primary\n"
                b"DINGTALK_WEBHOOK_SECRET=primary-secret\n"
                b"DINGTALK_WEBHOOK_URL_2=https://oapi.dingtalk.com/robot/send?access_token=secondary\n"
                b"DINGTALK_WEBHOOK_SECRET_2=secondary-secret\n"
                b"UNRELATED_FIELD=not-returned\n"
            )
            path.chmod(0o600)
            with patch.dict(
                os.environ,
                {
                    "DINGTALK_WEBHOOK_URL": "https://env.invalid/not-used",
                    "DINGTALK_WEBHOOK_SECRET": "not-used",
                    "DINGTALK_WEBHOOK_URL_2": "https://env.invalid/not-used-2",
                    "DINGTALK_WEBHOOK_SECRET_2": "not-used-2",
                },
                clear=False,
            ):
                credentials = cli._prepared_dingtalk_destination_credentials(
                    path=path
                )
            self.assertEqual(
                [item.destination_id for item in credentials],
                ["primary", "secondary"],
            )
            self.assertTrue(credentials[0].webhook_url.endswith("=primary"))
            self.assertTrue(credentials[1].webhook_url.endswith("=secondary"))

    def test_dual_credentials_reject_missing_duplicate_symlink_and_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = {
                "missing": (
                    b"DINGTALK_WEBHOOK_URL=https://oapi.dingtalk.com/robot/send?access_token=primary\n"
                    b"DINGTALK_WEBHOOK_SECRET=primary-secret\n",
                    "dingtalk_secret_file_dual_credentials_missing",
                ),
                "duplicate": (
                    b"DINGTALK_WEBHOOK_URL=https://oapi.dingtalk.com/robot/send?access_token=primary\n"
                    b"DINGTALK_WEBHOOK_SECRET=primary-secret\n"
                    b"DINGTALK_WEBHOOK_URL_2=https://oapi.dingtalk.com/robot/send?access_token=secondary\n"
                    b"DINGTALK_WEBHOOK_URL_2=https://oapi.dingtalk.com/robot/send?access_token=other\n"
                    b"DINGTALK_WEBHOOK_SECRET_2=secondary-secret\n",
                    "dingtalk_secret_file_duplicate_key",
                ),
            }
            for label, (payload, reason) in cases.items():
                with self.subTest(label=label):
                    path = root / f"{label}.env"
                    path.write_bytes(payload)
                    path.chmod(0o600)
                    with self.assertRaisesRegex(RuntimeError, reason):
                        cli._prepared_dingtalk_destination_credentials(path=path)

            target = root / "target.env"
            target.write_bytes(cases["missing"][0])
            target.chmod(0o600)
            link = root / "link.env"
            link.symlink_to(target)
            with self.assertRaisesRegex(RuntimeError, "not_regular"):
                cli._prepared_dingtalk_destination_credentials(path=link)
            target.chmod(0o640)
            with self.assertRaisesRegex(RuntimeError, "mode_invalid"):
                cli._prepared_dingtalk_destination_credentials(path=target)

    def test_both_destinations_share_frozen_bytes_but_have_isolated_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database, roots, prepared = self._prepared(Path(tmp))
            transport = RoutingSyntheticTransport()
            summary = self._send(database, roots, prepared, transport)

            self.assertEqual(summary.status, "sent")
            self.assertEqual(
                [item.status for item in summary.destinations], ["sent", "sent"]
            )
            frozen = (prepared.private_dir / "outbox" / "part-0001.json").read_bytes()
            self.assertEqual(
                transport.calls, [("primary", frozen), ("secondary", frozen)]
            )
            for destination in ("primary", "secondary"):
                entries = load_and_verify_delivery_ledger(
                    self._destination_ledger(roots, prepared.run_id, destination),
                    run_id=prepared.run_id,
                    destination_id=destination,
                )
                self.assertEqual(
                    [entry["status"] for entry in entries],
                    ["attempting", "sent"],
                )
                self.assertTrue(
                    all(entry["destination_id"] == destination for entry in entries)
                )
                self.assertTrue(
                    all(entry["schema_version"] == "delivery-event-v2" for entry in entries)
                )
            with sqlite3.connect(database) as connection:
                rows = connection.execute(
                    "SELECT channel,message_hash FROM delivery_previews "
                    "WHERE run_id=? ORDER BY channel",
                    (prepared.run_id,),
                ).fetchall()
            self.assertEqual(
                [row[0] for row in rows],
                ["dingtalk:primary", "dingtalk:secondary"],
            )
            self.assertEqual(rows[0][1], rows[1][1])

    def test_sent_plus_rejected_is_partial_and_explicit_resend_is_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database, roots, prepared = self._prepared(Path(tmp))
            first = RoutingSyntheticTransport({"secondary": "rejected"})
            summary = self._send(database, roots, prepared, first)
            self.assertEqual(summary.status, "partially_sent")
            self.assertEqual(
                [item.status for item in summary.destinations],
                ["sent", "rejected"],
            )

            blocked = RoutingSyntheticTransport()
            blocked_summary = self._send(database, roots, prepared, blocked)
            self.assertEqual(blocked_summary.status, "partially_sent")
            self.assertEqual(blocked.calls, [])
            self.assertEqual(
                [item.status for item in blocked_summary.destinations],
                ["already_sent", "blocked_duplicate"],
            )

            retry = RoutingSyntheticTransport()
            retry_summary = self._send(
                database,
                roots,
                prepared,
                retry,
                authorize_resend=True,
                resend_part_indexes=(1,),
            )
            self.assertEqual(retry_summary.status, "sent")
            self.assertEqual(retry.calls, [("secondary", retry.calls[0][1])])
            self.assertEqual(
                [item.status for item in retry_summary.destinations],
                ["already_sent", "sent"],
            )

    def test_sent_plus_unknown_is_partial_unknown_and_never_retried(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database, roots, prepared = self._prepared(Path(tmp))
            transport = RoutingSyntheticTransport(
                {"secondary": RuntimeError("synthetic-unknown")}
            )
            summary = self._send(database, roots, prepared, transport)
            self.assertEqual(summary.status, "partial_unknown_delivery_state")
            self.assertEqual(
                [item.status for item in summary.destinations],
                ["sent", "unknown_delivery_state"],
            )

            retry = RoutingSyntheticTransport()
            retry_summary = self._send(database, roots, prepared, retry)
            self.assertEqual(retry_summary.status, "partial_unknown_delivery_state")
            self.assertEqual(retry.calls, [])

    def test_hard_crash_after_primary_allows_only_clean_secondary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database, roots, prepared = self._prepared(Path(tmp))
            first = RoutingSyntheticTransport()

            def crash_after_primary(summary):
                if summary.destination_id == "primary":
                    raise SimulatedHardCrash()

            with self.assertRaises(SimulatedHardCrash):
                self._send(
                    database,
                    roots,
                    prepared,
                    first,
                    destination_completion_sink=crash_after_primary,
                )
            self.assertEqual([item[0] for item in first.calls], ["primary"])

            second = RoutingSyntheticTransport()
            summary = self._send(database, roots, prepared, second)
            self.assertEqual(summary.status, "sent")
            self.assertEqual([item[0] for item in second.calls], ["secondary"])
            self.assertEqual(
                [item.status for item in summary.destinations],
                ["already_sent", "sent"],
            )

    def test_concurrent_invocations_attempt_each_destination_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database, roots, prepared = self._prepared(Path(tmp))
            transport = RoutingSyntheticTransport()

            def invoke(_index):
                return self._send(database, roots, prepared, transport)

            with ThreadPoolExecutor(max_workers=2) as executor:
                summaries = list(executor.map(invoke, range(2)))
            self.assertEqual([item.status for item in summaries], ["sent", "sent"])
            self.assertEqual(
                sorted(destination for destination, _body in transport.calls),
                ["primary", "secondary"],
            )
            with sqlite3.connect(database) as connection:
                count = connection.execute(
                    "SELECT COUNT(*) FROM delivery_previews WHERE run_id=?",
                    (prepared.run_id,),
                ).fetchone()[0]
            self.assertEqual(count, 2)

    def test_duplicate_destination_url_blocks_before_transport(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database, roots, prepared = self._prepared(Path(tmp))
            same = "https://oapi.dingtalk.com/robot/send?access_token=same"
            credentials = (
                DingTalkDestinationCredential("primary", same, None),
                DingTalkDestinationCredential("secondary", same, None),
            )
            transport = RoutingSyntheticTransport()
            with self.assertRaisesRegex(RuntimeError, "destination_duplicate"):
                self._send(
                    database,
                    roots,
                    prepared,
                    transport,
                    destination_credentials=credentials,
                )
            self.assertEqual(transport.calls, [])

    def test_dual_cli_gate_blocks_without_loading_credentials_or_transport(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database, roots, prepared = self._prepared(Path(tmp))
            output: list[str] = []
            args = [
                "send-prepared-daily-report-dual",
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
                "send-auth-dual-cli",
                "--public-root",
                str(roots.public_root),
                "--private-root",
                str(roots.private_root),
                "--state-root",
                str(roots.state_root),
                "--config-root",
                str(CONFIG_ROOT),
            ]
            with patch.dict(
                os.environ,
                {
                    "REDDIT_VOC_DINGTALK_MODE": "dry_run",
                    "REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND": "0",
                },
                clear=False,
            ), patch(
                "reddit_voc.cli._prepared_dingtalk_destination_credentials",
                side_effect=AssertionError("credentials forbidden"),
            ), patch(
                "reddit_voc.cli._prepared_delivery_transport",
                side_effect=AssertionError("transport forbidden"),
            ), patch("builtins.print", side_effect=lambda value: output.append(value)):
                result = cli.main(args)
            self.assertEqual(result, 1)
            self.assertEqual(json.loads(output[0])["reason"], "dingtalk_mode_not_live")

    def test_dual_cli_uses_secret_file_and_outputs_no_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database, roots, prepared = self._prepared(root)
            secret_path = root / "report.env"
            secret_path.write_bytes(
                b"DINGTALK_WEBHOOK_URL=https://oapi.dingtalk.com/robot/send?access_token=primary\n"
                b"DINGTALK_WEBHOOK_SECRET=primary-secret\n"
                b"DINGTALK_WEBHOOK_URL_2=https://oapi.dingtalk.com/robot/send?access_token=secondary\n"
                b"DINGTALK_WEBHOOK_SECRET_2=secondary-secret\n"
            )
            secret_path.chmod(0o600)
            transport = RoutingSyntheticTransport()
            output = io.StringIO()
            args = [
                "send-prepared-daily-report-dual",
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
                "send-auth-dual-cli-live-gated",
                "--public-root",
                str(roots.public_root),
                "--private-root",
                str(roots.private_root),
                "--state-root",
                str(roots.state_root),
                "--config-root",
                str(CONFIG_ROOT),
                "--authorize-live-send",
            ]
            with patch.dict(
                os.environ,
                {
                    "REDDIT_VOC_DINGTALK_MODE": "live",
                    "REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND": "1",
                    "DINGTALK_WEBHOOK_URL": "https://env.invalid/not-used",
                    "DINGTALK_WEBHOOK_SECRET": "env-not-used",
                    "DINGTALK_WEBHOOK_URL_2": "https://env.invalid/not-used-2",
                    "DINGTALK_WEBHOOK_SECRET_2": "env-not-used-2",
                },
                clear=False,
            ), patch.object(
                cli, "_PREPARED_DINGTALK_CREDENTIAL_PATH", secret_path
            ), patch(
                "reddit_voc.cli._prepared_artifact_head_checker",
                return_value=lambda _url, timeout_seconds: 200,
            ), patch(
                "reddit_voc.cli._prepared_delivery_transport",
                return_value=transport,
            ), redirect_stdout(output):
                result = cli.main(args)
            self.assertEqual(result, 0, output.getvalue())
            summary = json.loads(output.getvalue())
            self.assertEqual(summary["status"], "sent")
            self.assertEqual(
                [item["destination_id"] for item in summary["destinations"]],
                ["primary", "secondary"],
            )
            self.assertNotIn("primary-secret", output.getvalue())
            self.assertNotIn("secondary-secret", output.getvalue())
            self.assertEqual(len(transport.calls), 2)


if __name__ == "__main__":
    unittest.main()
