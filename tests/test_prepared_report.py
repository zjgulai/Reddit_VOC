from __future__ import annotations

import hashlib
import json
import io
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from reddit_voc import cli
from reddit_voc.dingtalk import DingTalkSendResult
from reddit_voc.prepared_bundle import (
    PreparedReportRoots,
    build_commit_blocked_attempt_from_complete_manifest,
    commit_staged_blocked_attempt,
    commit_staged_prepared_report,
    generate_artifact_version_id,
    load_verified_prepared_report,
)
from reddit_voc.prepared_report import (
    PreparedAttemptContext,
    build_blocked_translation_attempt,
    prepare_daily_report,
    preflight_daily_report,
    stage_blocked_attempt,
    stage_daily_report,
    validate_prepared_public_artifact_url,
    write_blocked_attempt,
)
from reddit_voc.provider_attempt_ledger import (
    ZERO_TIP,
    ProviderAttemptLedger,
    ProviderAttemptLedgerError,
)
from reddit_voc.report_contracts import (
    AttemptEvidence,
    TokenUsage,
    canonical_json_bytes,
    load_report_schema_assets,
    sha256_hex,
)
from reddit_voc.storage import VocStore
from reddit_voc.translation_pipeline import TranslationService


ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOT = ROOT / "config"
ADMIN = ROOT / "scripts" / "server_daily_report_admin.sh"


@dataclass(frozen=True)
class FakeCompletion:
    request_id: str
    model: str
    system_fingerprint: str | None
    finish_reason: str
    content: str
    usage: TokenUsage
    attempts: tuple[AttemptEvidence, ...]


_PROTECTED_MARKER = re.compile(r"\[\[RVOC_P_[0-9a-f]{16}_[0-9]{6}\]\]")


def _fixture_translation_with_markers(source_text: str, zh: str) -> str:
    markers = _PROTECTED_MARKER.findall(source_text)
    return " ".join((zh, *markers)) if markers else zh


class PreparedFakeClient:
    def __init__(self, *, attempt_lifecycle_sink=None) -> None:
        self.calls: list[str] = []
        self.attempt_lifecycle_sink = attempt_lifecycle_sink

    def bind_lifecycle(self, lifecycle):
        self.attempt_lifecycle_sink = lifecycle
        return self

    def complete_json(
        self,
        *,
        phase,
        system_prompt,
        user_payload,
        deadline,
        attempt_budget,
    ):
        sequence = attempt_budget.reserve(phase)
        request_payload_sha256 = hashlib.sha256(
            canonical_json_bytes(
                {
                    "phase": phase,
                    "system_prompt": system_prompt,
                    "user_payload": user_payload,
                }
            )
        ).hexdigest()
        if self.attempt_lifecycle_sink is not None:
            self.attempt_lifecycle_sink.reserve(
                sequence=sequence,
                phase=phase,
                request_payload_sha256=request_payload_sha256,
            )
            self.attempt_lifecycle_sink.start(
                sequence=sequence,
                phase=phase,
                request_payload_sha256=request_payload_sha256,
            )
        usage = TokenUsage(3, 2, 1, 2, 5)
        attempt = AttemptEvidence(
            sequence=sequence,
            phase=phase,
            http_status=200,
            outcome="success",
            retryable=False,
            duration_ms=1,
            response_id=f"response-{sequence}",
            actual_model="deepseek-v4-flash",
            system_fingerprint="fixture",
            finish_reason="stop",
            usage=usage,
        )
        self.calls.append(phase)
        if phase == "translation":
            translations = []
            for item in user_payload["items"]:
                stable_id = item["id"]
                if stable_id.endswith(":title"):
                    zh = "吸奶器反馈"
                elif stable_id.startswith("comment:"):
                    zh = "Momcozy 声音很大。"
                elif item["source_text"]:
                    zh = "我不喜欢 Momcozy。"
                else:
                    zh = ""
                zh = _fixture_translation_with_markers(item["source_text"], zh)
                translations.append({"id": stable_id, "zh": zh})
            content = json.dumps({"translations": translations}, ensure_ascii=False)
        else:
            content = json.dumps(
                {
                    "verdicts": [
                        {
                            "id": item["id"],
                            "meaning_preserved": True,
                            "negation_preserved": True,
                            "comparison_preserved": True,
                            "sentiment_preserved": True,
                            "hallucination_free": True,
                            "critical_error_codes": [],
                        }
                        for item in user_payload["items"]
                    ]
                }
            )
        if self.attempt_lifecycle_sink is not None:
            self.attempt_lifecycle_sink.terminal(
                sequence=sequence,
                phase=phase,
                request_payload_sha256=request_payload_sha256,
                evidence=attempt,
            )
        return FakeCompletion(
            request_id=f"response-{sequence}",
            model="deepseek-v4-flash",
            system_fingerprint="fixture",
            finish_reason="stop",
            content=content,
            usage=usage,
            attempts=(attempt,),
        )


class PreparedRetryingFakeClient(PreparedFakeClient):
    def complete_json(
        self,
        *,
        phase,
        system_prompt,
        user_payload,
        deadline,
        attempt_budget,
    ):
        if phase != "translation":
            return super().complete_json(
                phase=phase,
                system_prompt=system_prompt,
                user_payload=user_payload,
                deadline=deadline,
                attempt_budget=attempt_budget,
            )
        first_sequence = attempt_budget.reserve(phase)
        second_sequence = attempt_budget.reserve(phase)
        retry_usage = TokenUsage(2, 1, 0, 2, 3)
        success_usage = TokenUsage(3, 2, 1, 2, 5)
        attempts = (
            AttemptEvidence(
                sequence=first_sequence,
                phase=phase,
                http_status=200,
                outcome="insufficient_system_resource",
                retryable=True,
                duration_ms=1,
                response_id=f"response-{first_sequence}-resource",
                actual_model="deepseek-v4-flash",
                system_fingerprint="fixture-retry",
                finish_reason="insufficient_system_resource",
                usage=retry_usage,
            ),
            AttemptEvidence(
                sequence=second_sequence,
                phase=phase,
                http_status=200,
                outcome="success",
                retryable=False,
                duration_ms=1,
                response_id=f"response-{second_sequence}",
                actual_model="deepseek-v4-flash",
                system_fingerprint="fixture-success",
                finish_reason="stop",
                usage=success_usage,
            ),
        )
        self.calls.append(phase)
        content = json.dumps(
            {
                "translations": [
                    {
                        "id": item["id"],
                        "zh": (
                            _fixture_translation_with_markers(
                                item["source_text"],
                                "吸奶器反馈"
                                if item["id"].endswith(":title")
                                else "Momcozy 声音很大。"
                                if item["id"].startswith("comment:")
                                else "我不喜欢 Momcozy。",
                            )
                        ),
                    }
                    for item in user_payload["items"]
                ]
            },
            ensure_ascii=False,
        )
        return FakeCompletion(
            request_id=f"response-{second_sequence}",
            model="deepseek-v4-flash",
            system_fingerprint="fixture-success",
            finish_reason="stop",
            content=content,
            usage=TokenUsage(5, 3, 1, 4, 8),
            attempts=attempts,
        )


class SyntheticFailureAlertTransport:
    transport_kind = "synthetic"

    def __init__(self, *, blocked_path: Path) -> None:
        self.blocked_path = blocked_path
        self.calls: list[bytes] = []

    def __call__(
        self,
        *,
        webhook_url,
        body_bytes,
        secret,
        timeout_seconds,
        request_start_sink,
    ):
        if not self.blocked_path.is_file() or self.blocked_path.is_symlink():
            raise AssertionError("blocked manifest must exist before alert transport")
        if request_start_sink is not None:
            raise AssertionError("synthetic transport must not receive external sink")
        self.calls.append(body_bytes)
        return DingTalkSendResult(
            status="sent",
            http_status=200,
            response_hash="sha256:" + "f" * 64,
            response_text="synthetic-ok",
            live_send=False,
            external_attempt_made=False,
        )


class PreparedReportTests(unittest.TestCase):
    def _admin(self, *arguments: str):
        return subprocess.run(
            ["bash", str(ADMIN), *arguments],
            env={**os.environ, "REDDIT_VOC_LOCAL_TEST_MODE": "1"},
            capture_output=True,
            text=True,
            check=False,
        )

    def _shadow_roots(
        self, root: Path, *, release_sha256: str
    ) -> tuple[Path, PreparedReportRoots]:
        shadow = root / "shadow"
        initialized = self._admin(
            "init-shadow-root",
            "--shadow-root",
            str(shadow),
            "--authorization-id",
            "shadow-prepared-provision",
            "--expected-release-sha256",
            release_sha256,
            "--candidate-sha256",
            "f" * 64,
            "--authorize-shadow-provisioning",
        )
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        shadow = shadow.resolve(strict=True)
        env_path = shadow / "secrets" / "reddit-voc-report.env"
        env_path.write_bytes(
            b"REDDIT_VOC_TRANSLATION_MODE=dry_run\n"
            b"REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=0\n"
            b"REDDIT_VOC_DINGTALK_MODE=dry_run\n"
            b"REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=0\n"
            b"REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT=0\n"
        )
        env_path.chmod(0o600)
        (shadow / "public").chmod(0o755)
        return shadow, PreparedReportRoots(
            public_root=shadow / "public",
            private_root=shadow / "private",
            public_staging_root=shadow / "public-staging",
            private_staging_root=shadow / "private-staging",
            state_root=shadow / "state",
            blocked_root=shadow / "blocked",
            handoff_root=shadow / "handoff",
        )

    def _install_reserved_prepare_permit(
        self,
        *,
        shadow: Path,
        release_sha256: str,
        run_id: str,
        authorization_id: str,
    ) -> None:
        installed = self._admin(
            "install-prepare-permit",
            "--control-root",
            str(shadow / "control"),
            "--authorization-id",
            authorization_id,
            "--expected-release-sha256",
            release_sha256,
            "--run-id",
            run_id,
            "--max-attempts",
            "100",
            "--expires-at",
            "2030-07-14T00:00:00+00:00",
        )
        self.assertEqual(installed.returncode, 0, installed.stderr)
        reserved = self._admin(
            "reserve-permit",
            "--control-root",
            str(shadow / "control"),
            "--authorization-id",
            authorization_id,
            "--expected-release-sha256",
            release_sha256,
            "--run-id",
            run_id,
        )
        self.assertEqual(reserved.returncode, 0, reserved.stderr)

    def _install_reserved_shadow_provider_permit(
        self,
        *,
        shadow: Path,
        release_sha256: str,
        run_id: str,
        authorization_id: str,
    ) -> None:
        installed = self._admin(
            "install-shadow-permit",
            "--shadow-root",
            str(shadow),
            "--authorization-id",
            authorization_id,
            "--expected-release-sha256",
            release_sha256,
            "--run-id",
            run_id,
            "--copied-database-sha256",
            "e" * 64,
            "--max-attempts",
            "100",
            "--expires-at",
            "2030-07-14T00:00:00+00:00",
        )
        self.assertEqual(installed.returncode, 0, installed.stderr)
        reserved = self._admin(
            "reserve-permit",
            "--control-root",
            str(shadow / "control"),
            "--authorization-id",
            authorization_id,
            "--expected-release-sha256",
            release_sha256,
            "--run-id",
            run_id,
        )
        self.assertEqual(reserved.returncode, 0, reserved.stderr)

    def _database(self, root: Path, *, visible: bool = True) -> Path:
        database = root / "data" / "voc.sqlite3"
        store = VocStore(database)
        store.migrate()
        run_id = "daily_collect_20260713_0700"
        with sqlite3.connect(database) as connection:
            connection.execute(
                "INSERT INTO runs(run_id,status,window_start_utc,window_end_utc,provider_call,live_send) VALUES(?,?,?,?,?,?)",
                (run_id, "success", "2026-07-12T23:00:00+00:00", "2026-07-13T23:00:00+00:00", 0, 0),
            )
            body = "I do not like Momcozy." if visible else "No explicit brand in the body."
            connection.execute(
                """
                INSERT INTO reddit_threads(
                    post_id,run_id,raw_capture_id,subreddit,title,selftext,source_url,
                    created_at_utc,score,num_comments_reported,parsed_comment_count,
                    more_node_count,coverage_grade,matched_keywords,author_hash,media_urls
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    "p1",
                    run_id,
                    "raw1",
                    "ExclusivelyPumping",
                    "Pump feedback",
                    body,
                    "https://www.reddit.com/r/ExclusivelyPumping/comments/p1/exact/",
                    "2026-07-13T01:00:00+00:00",
                    10,
                    1,
                    1 if visible else 0,
                    0,
                    "full",
                    "Momcozy" if visible else "pump",
                    "hash",
                    "[]",
                ),
            )
            if visible:
                connection.execute(
                    """
                    INSERT INTO reddit_comments(
                        comment_id,post_id,run_id,raw_capture_id,parent_id,body,
                        created_at_utc,score,depth,is_submitter,matched_keywords,
                        author_hash,deleted_or_removed
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        "c1",
                        "p1",
                        run_id,
                        "raw1",
                        None,
                        "Momcozy is loud.",
                        "2026-07-13T01:10:00+00:00",
                        2,
                        0,
                        0,
                        "Momcozy",
                        "comment-hash",
                        0,
                    ),
                )
            connection.execute(
                """
                INSERT INTO analysis_results(
                    analysis_id,run_id,source_type,source_id,analysis_version,
                    sentiment_label,sentiment_score,topic,severity,confidence,
                    pain_points,provider_call
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    "a1",
                    run_id,
                    "post",
                    "p1",
                    "local",
                    "negative",
                    -0.5,
                    "product_evaluation",
                    "medium",
                    0.8,
                    '["operations"]',
                    0,
                ),
            )
        return database

    def _roots(self, root: Path, *, suffix: str = "one") -> PreparedReportRoots:
        paths = {
            "public_root": root / "public",
            "private_root": root / "private",
            "public_staging_root": root / f"public-staging-{suffix}",
            "private_staging_root": root / f"private-staging-{suffix}",
            "state_root": root / "state",
            "blocked_root": root / "blocked",
            "handoff_root": root / f"handoff-{suffix}",
        }
        for path in paths.values():
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.chmod(0o700)
        paths["public_root"].chmod(0o755)
        return PreparedReportRoots(**paths)

    def _preflight(self, database: Path, roots: PreparedReportRoots):
        return preflight_daily_report(
            database=database,
            run_id="daily_collect_20260713_0700",
            roots=roots,
            config_root=CONFIG_ROOT,
            artifact_base_url="https://reddit.lute-tlz-dddd.top/artifacts",
            dingtalk_required_keyword="LL",
            dingtalk_max_bytes=5000,
            dingtalk_max_parts=2,
        )

    def _prepare_cli_args(
        self,
        *,
        database: Path,
        roots: PreparedReportRoots,
        provider_attempt_root: Path,
        attempt_id: str,
        artifact_version_id: str,
        extra: list[str] | None = None,
    ) -> list[str]:
        return [
            "prepare-daily-report",
            "--database",
            str(database),
            "--run-id",
            "daily_collect_20260713_0700",
            "--attempt-id",
            attempt_id,
            "--artifact-version-id",
            artifact_version_id,
            "--public-root",
            str(roots.public_root),
            "--private-root",
            str(roots.private_root),
            "--public-staging-root",
            str(roots.public_staging_root),
            "--private-staging-root",
            str(roots.private_staging_root),
            "--state-root",
            str(roots.state_root),
            "--blocked-root",
            str(roots.blocked_root),
            "--handoff-root",
            str(roots.handoff_root),
            "--provider-attempt-root",
            str(provider_attempt_root),
            "--config-root",
            str(CONFIG_ROOT),
            "--artifact-base-url",
            "https://reddit.lute-tlz-dddd.top/artifacts",
            "--dingtalk-required-keyword",
            "LL",
            "--dingtalk-max-bytes",
            "5000",
            "--dingtalk-max-parts",
            "2",
            "--prepare-action-authorization-id",
            "prepare-action-cli-1",
            *(extra or []),
        ]

    def test_prepare_cli_empty_visible_commits_without_key_or_deepseek_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self._database(root, visible=False)
            roots = self._roots(root)
            provider_attempt_root = root / "provider-attempts"
            provider_attempt_root.mkdir(mode=0o700)
            provider_attempt_root.chmod(0o700)
            output = io.StringIO()
            with patch.dict(
                os.environ,
                {
                    "REDDIT_VOC_TRANSLATION_MODE": "disabled",
                    "REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION": "0",
                },
                clear=False,
            ), patch(
                "reddit_voc.cli._read_deepseek_key",
                side_effect=AssertionError("key read forbidden"),
            ), redirect_stdout(output):
                result = cli.main(
                    self._prepare_cli_args(
                        database=database,
                        roots=roots,
                        provider_attempt_root=provider_attempt_root,
                        attempt_id="attempt-cli-empty",
                        artifact_version_id="20260713T010203456789Z-" + "c" * 32,
                    )
                )
            self.assertEqual(result, 0, output.getvalue())
            summary = json.loads(output.getvalue())
            self.assertTrue(summary["current_advanced"])
            self.assertFalse(summary["translation_provider_call"])
            self.assertFalse(summary["provider_attempt_made"])
            self.assertFalse(summary["report_live_send"])
            self.assertFalse(summary["alert_live_send"])
            self.assertFalse(summary["live_send"])
            self.assertFalse(provider_attempt_root.joinpath("provider-auth-cli").exists())

    def test_prepare_cli_missing_provider_gate_blocks_after_preflight_without_key_or_http(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self._database(root)
            roots = self._roots(root)
            provider_attempt_root = root / "provider-attempts"
            provider_attempt_root.mkdir(mode=0o700)
            provider_attempt_root.chmod(0o700)
            output = io.StringIO()
            sys.modules.pop("reddit_voc.deepseek_client", None)
            with patch.dict(
                os.environ,
                {
                    "REDDIT_VOC_TRANSLATION_MODE": "disabled",
                    "REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION": "0",
                },
                clear=False,
            ), patch(
                "reddit_voc.cli._read_deepseek_key",
                side_effect=AssertionError("key read forbidden"),
            ), redirect_stdout(output):
                result = cli.main(
                    self._prepare_cli_args(
                        database=database,
                        roots=roots,
                        provider_attempt_root=provider_attempt_root,
                        attempt_id="attempt-cli-blocked",
                        artifact_version_id="20260713T010203456789Z-" + "d" * 32,
                    )
                )
            self.assertEqual(result, 1)
            summary = json.loads(output.getvalue())
            self.assertEqual(summary["reason_codes"], ["translation_mode_not_deepseek"])
            self.assertFalse(summary["provider_attempt_made"])
            self.assertFalse((roots.state_root / "prepared-current.json").exists())
            self.assertNotIn("reddit_voc.deepseek_client", sys.modules)
            self.assertTrue(
                roots.blocked_root.joinpath(
                    "daily_collect_20260713_0700",
                    "attempt-cli-blocked",
                    "blocked-manifest.json",
                ).exists()
            )

    def test_deferred_prepare_failure_writes_handoff_only_until_host_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self._database(root)
            roots = self._roots(root)
            provider_attempt_root = root / "provider-attempts"
            provider_attempt_root.mkdir(mode=0o700)
            provider_attempt_root.chmod(0o700)
            output = io.StringIO()
            with patch.dict(
                os.environ,
                {
                    "REDDIT_VOC_TRANSLATION_MODE": "disabled",
                    "REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION": "0",
                },
                clear=False,
            ), redirect_stdout(output):
                result = cli.main(
                    self._prepare_cli_args(
                        database=database,
                        roots=roots,
                        provider_attempt_root=provider_attempt_root,
                        attempt_id="attempt-cli-deferred-blocked",
                        artifact_version_id="20260713T010203456789Z-" + "e" * 32,
                        extra=["--defer-host-commit"],
                    )
                )
            self.assertEqual(result, 1)
            self.assertFalse(
                roots.blocked_root.joinpath(
                    "daily_collect_20260713_0700",
                    "attempt-cli-deferred-blocked",
                ).exists()
            )
            self.assertTrue(
                roots.handoff_root.joinpath(
                    "daily_collect_20260713_0700",
                    "attempt-cli-deferred-blocked",
                    "blocked-manifest.json",
                ).exists()
            )
            summary = json.loads(output.getvalue())
            self.assertEqual(summary["failure_alert_status"], "deferred_to_host")
            self.assertFalse(summary["alert_live_send"])
            self.assertFalse(summary["live_send"])

    def test_prepare_cli_failure_alert_requires_both_gates_and_runs_after_blocked_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self._database(root)
            roots = self._roots(root)
            provider_attempt_root = root / "provider-attempts"
            provider_attempt_root.mkdir(mode=0o700)
            provider_attempt_root.chmod(0o700)
            blocked_path = roots.blocked_root.joinpath(
                "daily_collect_20260713_0700",
                "attempt-cli-alert",
                "blocked-manifest.json",
            )
            transport = SyntheticFailureAlertTransport(blocked_path=blocked_path)
            output = io.StringIO()

            with patch.dict(
                os.environ,
                {
                    "REDDIT_VOC_TRANSLATION_MODE": "disabled",
                    "REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION": "0",
                    "REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT": "1",
                    "DINGTALK_WEBHOOK_URL": "https://example.invalid/robot/send?access_token=synthetic",
                    "DINGTALK_WEBHOOK_SECRET": "",
                },
                clear=False,
            ), patch(
                "reddit_voc.cli._read_deepseek_key",
                side_effect=AssertionError("key read forbidden"),
            ), patch(
                "reddit_voc.cli._prepared_delivery_transport",
                return_value=transport,
            ), redirect_stdout(output):
                result = cli.main(
                    self._prepare_cli_args(
                        database=database,
                        roots=roots,
                        provider_attempt_root=provider_attempt_root,
                        attempt_id="attempt-cli-alert",
                        artifact_version_id="20260713T010203456789Z-" + "f" * 32,
                        extra=["--authorize-failure-alert"],
                    )
                )

            self.assertEqual(result, 1)
            summary = json.loads(output.getvalue())
            self.assertEqual(summary["failure_alert_status"], "sent")
            self.assertFalse(summary["alert_live_send"])
            self.assertFalse(summary["live_send"])
            self.assertEqual(len(transport.calls), 1)
            alert_body = json.loads(transport.calls[0].decode("utf-8"))
            alert_text = alert_body["markdown"]["text"]
            self.assertIn("run_id=daily_collect_20260713_0700", alert_text)
            self.assertNotIn("attempt_id=", alert_text)
            self.assertIn("stage=gate", alert_text)
            self.assertIn("reason_code=translation_mode_not_deepseek", alert_text)
            self.assertNotIn("synthetic", output.getvalue())

            second_root = root / "missing-cli-gate"
            second_root.mkdir()
            second_database = self._database(second_root)
            second_roots = self._roots(second_root)
            second_attempt_root = second_root / "provider-attempts"
            second_attempt_root.mkdir(mode=0o700)
            second_attempt_root.chmod(0o700)
            with patch(
                "reddit_voc.cli._prepared_delivery_transport",
                side_effect=AssertionError("alert transport forbidden without CLI authorization"),
            ), redirect_stdout(io.StringIO()):
                second_result = cli.main(
                    self._prepare_cli_args(
                        database=second_database,
                        roots=second_roots,
                        provider_attempt_root=second_attempt_root,
                        attempt_id="attempt-cli-no-alert",
                        artifact_version_id="20260713T010203456789Z-" + "0" * 32,
                    )
                )
            self.assertEqual(second_result, 1)

    def test_prepare_cli_key_metadata_failure_keeps_approved_provider_authorization_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self._database(root)
            roots = self._roots(root)
            provider_attempt_root = root / "provider-attempts"
            provider_attempt_root.mkdir(mode=0o700)
            provider_attempt_root.chmod(0o700)
            output = io.StringIO()
            missing_key_path = root / "missing-deepseek-key"

            with patch.dict(
                os.environ,
                {
                    "REDDIT_VOC_TRANSLATION_MODE": "deepseek",
                    "REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION": "1",
                    "REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT": "0",
                },
                clear=False,
            ), patch(
                "reddit_voc.cli._DEEPSEEK_KEY_PATH", missing_key_path
            ), redirect_stdout(output):
                result = cli.main(
                    self._prepare_cli_args(
                        database=database,
                        roots=roots,
                        provider_attempt_root=provider_attempt_root,
                        attempt_id="attempt-cli-key-missing",
                        artifact_version_id="20260713T010203456789Z-" + "1" * 32,
                        extra=[
                            "--authorize-provider-call",
                            "--provider-authorization-id",
                            "provider-auth-cli-key-missing",
                        ],
                    )
                )

            self.assertEqual(result, 1)
            summary = json.loads(output.getvalue())
            self.assertEqual(summary["stage"], "key_metadata")
            self.assertFalse(summary["provider_attempt_made"])
            manifest = json.loads(
                roots.blocked_root.joinpath(
                    "daily_collect_20260713_0700",
                    "attempt-cli-key-missing",
                    "blocked-manifest.json",
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(
                manifest["provider_authorization_id"],
                "provider-auth-cli-key-missing",
            )

    def test_prepare_cli_existing_started_attempt_becomes_unknown_and_never_retries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self._database(root)
            roots = self._roots(root)
            provider_attempt_root = root / "provider-attempts"
            provider_attempt_root.mkdir(mode=0o700)
            provider_attempt_root.chmod(0o700)
            release_sha256 = cli._provider_runtime_release_sha256(
                config_root=CONFIG_ROOT
            )
            ledger, lifecycle = cli._create_provider_attempt_lifecycle(
                root=provider_attempt_root,
                provider_authorization_id="provider-auth-cli-recovery",
                run_id="daily_collect_20260713_0700",
                attempt_id="attempt-cli-recovery",
                release_sha256=release_sha256,
            )
            lifecycle.reserve(
                sequence=1,
                phase="translation",
                request_payload_sha256="a" * 64,
            )
            lifecycle.start(
                sequence=1,
                phase="translation",
                request_payload_sha256="a" * 64,
            )
            output = io.StringIO()

            with patch.dict(
                os.environ,
                {
                    "REDDIT_VOC_TRANSLATION_MODE": "deepseek",
                    "REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION": "1",
                },
                clear=False,
            ), patch(
                "reddit_voc.cli._read_deepseek_key",
                side_effect=AssertionError("existing unknown must block before key read"),
            ), redirect_stdout(output):
                result = cli.main(
                    self._prepare_cli_args(
                        database=database,
                        roots=roots,
                        provider_attempt_root=provider_attempt_root,
                        attempt_id="attempt-cli-recovery",
                        artifact_version_id="20260713T010203456789Z-" + "9" * 32,
                        extra=[
                            "--authorize-provider-call",
                            "--provider-authorization-id",
                            "provider-auth-cli-recovery",
                        ],
                    )
                )

            self.assertEqual(result, 1, output.getvalue())
            summary = json.loads(output.getvalue())
            self.assertEqual(summary["reason_codes"], ["provider_attempt_ledger_exists"])
            self.assertTrue(summary["provider_attempt_made"])
            self.assertEqual(ledger.load().entries[-1]["event_type"], "unknown")
            blocked = json.loads(
                Path(summary["blocked_manifest"]).read_text(encoding="utf-8")
            )
            self.assertEqual(blocked["request_count"], 1)
            self.assertEqual(
                blocked["provider_attempt_ledger"]["unknown_attempt_count"], 1
            )

    def test_prepare_cli_all_gates_stage_deferred_and_reserve_each_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self._database(root)
            roots = self._roots(root)
            provider_attempt_root = root / "provider-attempts"
            provider_attempt_root.mkdir(mode=0o700)
            provider_attempt_root.chmod(0o700)
            key_path = root / "deepseek_api_key"
            key_path.write_text("synthetic-unit-test-key\n", encoding="utf-8")
            key_path.chmod(0o600)
            fake_client = PreparedFakeClient()
            output = io.StringIO()
            with patch.dict(
                os.environ,
                {
                    "REDDIT_VOC_TRANSLATION_MODE": "deepseek",
                    "REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION": "1",
                },
                clear=False,
            ), patch(
                "reddit_voc.cli._DEEPSEEK_KEY_PATH", key_path
            ), patch(
                "reddit_voc.deepseek_client.DeepSeekClient",
                side_effect=lambda **kwargs: fake_client.bind_lifecycle(
                    kwargs["attempt_lifecycle_sink"]
                ),
            ), redirect_stdout(output):
                result = cli.main(
                    self._prepare_cli_args(
                        database=database,
                        roots=roots,
                        provider_attempt_root=provider_attempt_root,
                        attempt_id="attempt-cli-provider",
                        artifact_version_id="20260713T010203456789Z-" + "e" * 32,
                        extra=[
                            "--authorize-provider-call",
                            "--provider-authorization-id",
                            "provider-auth-cli",
                            "--defer-host-commit",
                        ],
                    )
                )
            self.assertEqual(result, 0, output.getvalue())
            summary = json.loads(output.getvalue())
            self.assertFalse(summary["current_advanced"])
            self.assertTrue(summary["translation_provider_call"])
            self.assertTrue(summary["translation_phase_attempt_made"])
            self.assertTrue(summary["semantic_validation_phase_attempt_made"])
            self.assertTrue(summary["provider_attempt_made"])
            self.assertFalse(summary["report_live_send"])
            self.assertFalse(summary["alert_live_send"])
            self.assertFalse(summary["live_send"])
            self.assertNotIn("synthetic-unit-test-key", output.getvalue())
            self.assertEqual(fake_client.calls, ["translation", "semantic_validation"])
            reservation_path = (
                provider_attempt_root
                / "provider-auth-cli"
                / "daily_collect_20260713_0700"
                / "attempt-cli-provider"
                / "provider-attempts-v2.jsonl"
            )
            reservations = [
                json.loads(line)
                for line in reservation_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(
                [
                    (row["sequence"], row["phase"])
                    for row in reservations
                    if row["event_type"] == "reservation"
                ],
                [(1, "translation"), (2, "semantic_validation")],
            )
            self.assertEqual(
                [row["event_type"] for row in reservations],
                ["reservation", "start", "terminal"] * 2,
            )
            self.assertNotIn("response-1", reservation_path.read_text(encoding="utf-8"))
            manifest = json.loads(
                (roots.private_staging_root / "translation-manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                manifest["provider_attempt_ledger"]["ledger_tip"],
                reservations[-1]["entry_hash"],
            )
            self.assertFalse((roots.state_root / "prepared-current.json").exists())

    def test_preflight_is_one_readonly_snapshot_and_never_migrates_or_mutates_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self._database(root)
            roots = self._roots(root)
            before_bytes = database.read_bytes()
            before_stat = database.stat()
            with patch.object(VocStore, "migrate", side_effect=AssertionError("migrate forbidden")):
                preflight = self._preflight(database, roots)
            after_stat = database.stat()
            self.assertEqual(database.read_bytes(), before_bytes)
            self.assertEqual(after_stat.st_ino, before_stat.st_ino)
            self.assertEqual(after_stat.st_size, before_stat.st_size)
            self.assertEqual(after_stat.st_mtime_ns, before_stat.st_mtime_ns)
            with sqlite3.connect(database) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM delivery_previews").fetchone()[0], 0)
            self.assertEqual(preflight.visible_post_ids, ("p1",))
            self.assertEqual(preflight.provider_phases_required, ("translation", "semantic_validation"))
            self.assertIsNone(preflight.provider_authorization_id)
            self.assertEqual(
                [item.stable_id for item in preflight.bundles[0].items],
                ["post:p1:title", "post:p1:body", "comment:c1:body"],
            )

    def test_preflight_blocks_failed_run_before_translation_or_artifact_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self._database(root)
            roots = self._roots(root)
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "UPDATE runs SET status='failed' WHERE run_id='daily_collect_20260713_0700'"
                )
            with self.assertRaisesRegex(RuntimeError, "report_source_run_failed"):
                self._preflight(database, roots)
            self.assertEqual(list(roots.public_staging_root.iterdir()), [])
            self.assertEqual(list(roots.private_staging_root.iterdir()), [])

    def test_preflight_blocks_success_or_partial_without_observations(self) -> None:
        for status in ("success", "partial"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                database = self._database(root)
                roots = self._roots(root)
                with sqlite3.connect(database) as connection:
                    connection.execute("DELETE FROM analysis_results")
                    connection.execute("DELETE FROM reddit_comments")
                    connection.execute("DELETE FROM reddit_threads")
                    connection.execute(
                        "UPDATE runs SET status=? WHERE run_id='daily_collect_20260713_0700'",
                        (status,),
                    )
                with self.assertRaisesRegex(RuntimeError, "report_source_no_observations"):
                    self._preflight(database, roots)

    def test_preflight_accepts_attested_empty_success_without_fabricating_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self._database(root)
            roots = self._roots(root)
            with sqlite3.connect(database) as connection:
                connection.execute("DELETE FROM analysis_results")
                connection.execute("DELETE FROM reddit_comments")
                connection.execute("DELETE FROM reddit_threads")
                connection.execute(
                    "UPDATE runs SET status='empty' WHERE run_id='daily_collect_20260713_0700'"
                )
            preflight = self._preflight(database, roots)
            self.assertEqual(preflight.visible_post_ids, ())
            self.assertEqual(preflight.provider_phases_required, ())
            self.assertEqual(
                preflight.report_static_inputs["source_state"],
                {
                    "schema_version": "daily-report-source-state-v1",
                    "status": "empty",
                    "mode": "empty_success",
                    "post_count": 0,
                    "comment_count": 0,
                    "business_report_allowed": True,
                    "failure_alert_allowed": False,
                },
            )

    def test_preflight_rejects_empty_status_when_observations_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self._database(root)
            roots = self._roots(root)
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "UPDATE runs SET status='empty' WHERE run_id='daily_collect_20260713_0700'"
                )
            with self.assertRaisesRegex(RuntimeError, "report_source_empty_has_observations"):
                self._preflight(database, roots)

    def test_preflight_blocks_single_post_above_40000_source_characters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self._database(root)
            roots = self._roots(root)
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "UPDATE reddit_threads SET selftext=? WHERE post_id='p1'",
                    ("Momcozy " + "a" * 40_001,),
                )
            with self.assertRaisesRegex(
                RuntimeError, "translation_post_source_cap_exceeded"
            ):
                self._preflight(database, roots)

    def test_preflight_blocks_report_above_250000_source_characters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self._database(root)
            roots = self._roots(root)
            run_id = "daily_collect_20260713_0700"
            rows = []
            for index in range(2, 9):
                post_id = f"p{index}"
                rows.append(
                    (
                        post_id,
                        run_id,
                        f"raw{index}",
                        "ExclusivelyPumping",
                        "Pump feedback",
                        "Momcozy " + "a" * 39_900,
                        f"https://www.reddit.com/r/ExclusivelyPumping/comments/{post_id}/exact/",
                        f"2026-07-13T0{index}:00:00+00:00",
                        1,
                        0,
                        0,
                        0,
                        "full",
                        "Momcozy",
                        f"hash-{index}",
                        "[]",
                    )
                )
            with sqlite3.connect(database) as connection:
                connection.executemany(
                    """
                    INSERT INTO reddit_threads(
                        post_id,run_id,raw_capture_id,subreddit,title,selftext,source_url,
                        created_at_utc,score,num_comments_reported,parsed_comment_count,
                        more_node_count,coverage_grade,matched_keywords,author_hash,media_urls
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    rows,
                )
            with self.assertRaisesRegex(
                RuntimeError, "translation_report_source_cap_exceeded"
            ):
                self._preflight(database, roots)

    def test_preflight_does_not_confuse_100_http_attempt_cap_with_item_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self._database(root)
            roots = self._roots(root)
            run_id = "daily_collect_20260713_0700"
            comments = [
                (
                    f"c{index}",
                    "p1",
                    run_id,
                    f"raw-comment-{index}",
                    None,
                    "Momcozy ok.",
                    "2026-07-13T01:10:00+00:00",
                    1,
                    0,
                    0,
                    "Momcozy",
                    f"comment-hash-{index}",
                    0,
                )
                for index in range(2, 101)
            ]
            with sqlite3.connect(database) as connection:
                connection.executemany(
                    """
                    INSERT INTO reddit_comments(
                        comment_id,post_id,run_id,raw_capture_id,parent_id,body,
                        created_at_utc,score,depth,is_submitter,matched_keywords,
                        author_hash,deleted_or_removed
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    comments,
                )
            preflight = self._preflight(database, roots)
            self.assertEqual(len(preflight.bundles), 1)
            self.assertEqual(len(preflight.bundles[0].items), 102)

    def test_preflight_rejects_non_reddit_source_url_before_provider_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self._database(root)
            roots = self._roots(root)
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "UPDATE reddit_threads SET source_url=? WHERE post_id='p1'",
                    ("javascript:alert(1)",),
                )
            with self.assertRaisesRegex(RuntimeError, "reddit_source_url_invalid"):
                self._preflight(database, roots)

    def test_preflight_canonicalizes_reddit_media_and_gallery_urls(self) -> None:
        for source_url in (
            "https://i.redd.it/media-object.png",
            "https://www.reddit.com/gallery/p1",
        ):
            with self.subTest(source_url=source_url), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                database = self._database(root)
                roots = self._roots(root)
                with sqlite3.connect(database) as connection:
                    connection.execute(
                        "UPDATE reddit_threads SET source_url=? WHERE post_id='p1'",
                        (source_url,),
                    )
                preflight = self._preflight(database, roots)
                self.assertEqual(
                    preflight.source.posts[0]["source_url"],
                    "https://www.reddit.com/r/ExclusivelyPumping/comments/p1/",
                )

    def test_preflight_rejects_unsafe_artifact_base_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self._database(root)
            roots = self._roots(root)
            with self.assertRaisesRegex(ValueError, "artifact_base_url_invalid"):
                preflight_daily_report(
                    database=database,
                    run_id="daily_collect_20260713_0700",
                    roots=roots,
                    config_root=CONFIG_ROOT,
                    artifact_base_url="https://reddit.lute-tlz-dddd.top/artifacts\nhttps://evil.example",
                    dingtalk_required_keyword="LL",
                    dingtalk_max_bytes=5000,
                    dingtalk_max_parts=2,
                )

    def test_artifact_origin_and_public_urls_are_project_exact(self) -> None:
        valid = (
            "https://reddit.lute-tlz-dddd.top/artifacts/prepared/"
            "daily_collect_20260812_0700/20260812T000000000000Z-"
            + "a" * 32
            + "/daily_collect_20260812_0700-insight-report.html"
        )
        self.assertEqual(validate_prepared_public_artifact_url(valid), valid)
        invalid = [
            "https://evil.example/artifacts/prepared/run/version/report.html",
            "https://reddit.lute-tlz-dddd.top.evil.example/artifacts/prepared/run/version/report.html",
            "https://reddit.lute-tlz-dddd.top:443/artifacts/prepared/run/version/report.html",
            "https://reddit.lute-tlz-dddd.top/artifacts/../admin",
            "https://reddit.lute-tlz-dddd.top/artifacts/prepared/..",
            "https://reddit.lute-tlz-dddd.top/artifacts/prepared/run/version/.",
            "https://reddit.lute-tlz-dddd.top/artifacts/prepared/run/version/report.html?x=1",
            "https://reddit.lute-tlz-dddd.top/artifacts/prepared/run/version/report.html#x",
            "https://reddit.lute-tlz-dddd.top/artifacts/prepared/run/version/%2e%2e",
        ]
        for candidate in invalid:
            with self.subTest(candidate=candidate), self.assertRaisesRegex(
                ValueError, "artifact_url_invalid"
            ):
                validate_prepared_public_artifact_url(candidate)

    def test_missing_database_does_not_create_parent_and_schema_drift_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            roots = self._roots(root)
            missing = root / "missing-parent" / "voc.sqlite3"
            with self.assertRaisesRegex(RuntimeError, "database_missing"):
                self._preflight(missing, roots)
            self.assertFalse(missing.parent.exists())

            database = root / "bad.sqlite3"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE runs(run_id TEXT PRIMARY KEY)")
            with self.assertRaisesRegex(RuntimeError, "database_schema_invalid"):
                self._preflight(database, roots)

    def test_version_format_stage_is_immutable_and_neutral_commit_advances_current(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self._database(root)
            roots = self._roots(root)
            preflight = self._preflight(database, roots)
            version = generate_artifact_version_id(
                now_utc=datetime(2026, 7, 13, 1, 2, 3, 456789, tzinfo=timezone.utc),
                random_hex=lambda count: "a" * (count * 2),
            )
            self.assertEqual(version, "20260713T010203456789Z-" + "a" * 32)
            attempt = PreparedAttemptContext(
                attempt_id="attempt-20260713-001",
                artifact_version_id=version,
            )
            client = PreparedFakeClient()
            translator = TranslationService(
                client=client,
                assets=preflight.translation_assets,
            )
            staged = stage_daily_report(
                preflight,
                attempt=attempt,
                translator=translator,
                roots=roots,
                provider_authorization_id="provider-auth-1",
                prepare_action_authorization_id="prepare-action-1",
            )
            self.assertEqual(staged.attempt_id, attempt.attempt_id)
            self.assertEqual(staged.artifact_version_id, attempt.artifact_version_id)
            self.assertTrue(staged.staged_public_dir.exists())
            self.assertTrue(staged.staged_private_dir.exists())
            self.assertFalse(staged.final_public_dir.exists())
            self.assertFalse(staged.final_private_dir.exists())
            self.assertFalse((roots.state_root / "prepared-current.json").exists())
            self.assertEqual(client.calls, ["translation", "semantic_validation"])

            with self.assertRaisesRegex(RuntimeError, "commit_request_mismatch"):
                commit_staged_prepared_report(
                    roots=roots,
                    expected_run_id=preflight.run_id,
                    expected_artifact_version_id=version,
                    expected_bundle_sha256=staged.bundle_sha256,
                    expected_outbox_sha256=staged.outbox_sha256,
                    expected_commit_request_sha256=staged.commit_request_sha256,
                    expected_provider_authorization_id="provider-auth-1",
                    expected_prepare_action_authorization_id="wrong-action",
                    expected_attempt_id=attempt.attempt_id,
                    schema_assets=preflight.schema_assets,
                )
            self.assertFalse(staged.final_public_dir.exists())

            result = commit_staged_prepared_report(
                roots=roots,
                expected_run_id=preflight.run_id,
                expected_artifact_version_id=version,
                expected_bundle_sha256=staged.bundle_sha256,
                expected_outbox_sha256=staged.outbox_sha256,
                expected_commit_request_sha256=staged.commit_request_sha256,
                expected_provider_authorization_id="provider-auth-1",
                expected_prepare_action_authorization_id="prepare-action-1",
                expected_attempt_id=attempt.attempt_id,
                schema_assets=preflight.schema_assets,
            )
            self.assertEqual(result.attempt_id, attempt.attempt_id)
            self.assertTrue(result.public_dir.exists())
            self.assertTrue(result.private_dir.exists())
            self.assertFalse(roots.public_staging_root.exists())
            current = json.loads((roots.state_root / "prepared-current.json").read_text(encoding="utf-8"))
            self.assertEqual(
                set(current),
                {
                    "schema_version",
                    "run_id",
                    "artifact_version_id",
                    "bundle_sha256",
                    "report_input_fingerprint",
                    "outbox_sha256",
                },
            )
            self.assertEqual(current["artifact_version_id"], version)
            self.assertTrue((roots.state_root / "prepared-commits" / preflight.run_id / "registry.jsonl").exists())
            self.assertTrue((roots.public_root / f"{preflight.run_id}-daily-detail.csv").is_symlink())

            verified = load_verified_prepared_report(
                roots=roots,
                expected_run_id=preflight.run_id,
                expected_artifact_version_id=version,
                expected_bundle_sha256=staged.bundle_sha256,
                expected_outbox_sha256=staged.outbox_sha256,
                schema_assets=preflight.schema_assets,
            )
            self.assertEqual(verified.translation_status, "complete")
            self.assertEqual(len(verified.parts), 1)
            self.assertEqual(verified.parts[0].body_bytes, verified.parts[0].path.read_bytes())
            self.assertIn(b"LL", verified.parts[0].body_bytes)
            self.assertGreaterEqual(len(verified.public_artifact_urls), 3)

            cached = self._preflight(database, self._roots(root, suffix="cache"))
            self.assertEqual(cached.provider_phases_required, ())
            self.assertGreaterEqual(len(cached.cached_manifests), 1)

    def test_stage_accepts_only_exact_empty_host_precreated_handoff_leaf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self._database(root, visible=False)
            roots = self._roots(root)
            preflight = self._preflight(database, roots)
            attempt = PreparedAttemptContext(
                attempt_id="attempt-precreated-handoff",
                artifact_version_id="20260713T010203456789Z-" + "f" * 32,
            )
            leaf = roots.handoff_root / preflight.run_id / attempt.attempt_id
            leaf.mkdir(parents=True, mode=0o700)
            leaf.parent.chmod(0o700)
            leaf.chmod(0o700)
            staged = stage_daily_report(
                preflight,
                attempt=attempt,
                translator=TranslationService(
                    client=None, assets=preflight.translation_assets
                ),
                roots=roots,
                provider_authorization_id=None,
                prepare_action_authorization_id="prepare-precreated-handoff",
            )
            self.assertEqual(staged.commit_request_path.parent, leaf)
            self.assertEqual(
                [path.name for path in leaf.iterdir()], ["commit-request.json"]
            )

            second_roots = self._roots(root, suffix="precreated-extra")
            second_preflight = self._preflight(database, second_roots)
            second_attempt = PreparedAttemptContext(
                attempt_id="attempt-precreated-extra",
                artifact_version_id="20260713T010203456789Z-" + "0" * 32,
            )
            extra_leaf = (
                second_roots.handoff_root
                / second_preflight.run_id
                / second_attempt.attempt_id
            )
            extra_leaf.mkdir(parents=True, mode=0o700)
            extra_leaf.parent.chmod(0o700)
            extra_leaf.chmod(0o700)
            extra = extra_leaf / "unexpected"
            extra.write_text("unexpected", encoding="utf-8")
            extra.chmod(0o600)
            with self.assertRaisesRegex(RuntimeError, "handoff_attempt_not_empty"):
                stage_daily_report(
                    second_preflight,
                    attempt=second_attempt,
                    translator=TranslationService(
                        client=None, assets=second_preflight.translation_assets
                    ),
                    roots=second_roots,
                    provider_authorization_id=None,
                    prepare_action_authorization_id="prepare-precreated-extra",
                )

            blocked_roots = self._roots(root, suffix="precreated-blocked")
            blocked_run = blocked_roots.handoff_root / preflight.run_id
            blocked_leaf = blocked_run / "attempt-precreated-blocked"
            blocked_leaf.mkdir(parents=True, mode=0o700)
            blocked_run.chmod(0o700)
            blocked_leaf.chmod(0o700)
            blocked_manifest = build_blocked_translation_attempt(
                run_id=preflight.run_id,
                attempt_id="attempt-precreated-blocked",
                preflight=None,
                pipeline_evidence=None,
                stage="preflight",
                reason_codes=["database_missing"],
                provider_authorization_id=None,
            )
            blocked_path = stage_blocked_attempt(
                roots=blocked_roots,
                run_id=preflight.run_id,
                attempt_id="attempt-precreated-blocked",
                manifest=blocked_manifest,
            )
            self.assertEqual(blocked_path.parent, blocked_leaf)

    def test_complete_manifest_keeps_each_parsed_provider_response_and_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self._database(root)
            roots = self._roots(root)
            preflight = self._preflight(database, roots)
            client = PreparedRetryingFakeClient()
            staged = stage_daily_report(
                preflight,
                attempt=PreparedAttemptContext(
                    attempt_id="attempt-retry-evidence",
                    artifact_version_id="20260713T010203456789Z-" + "d" * 32,
                ),
                translator=TranslationService(
                    client=client,
                    assets=preflight.translation_assets,
                ),
                roots=roots,
                provider_authorization_id="provider-auth-retry-evidence",
                prepare_action_authorization_id="prepare-action-retry-evidence",
            )
            manifest = json.loads(
                staged.staged_private_dir.joinpath(
                    "translation-manifest.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["request_count"], 3)
            self.assertEqual(manifest["retry_count"], 1)
            self.assertEqual(
                [response["request_id"] for response in manifest["responses"]],
                ["response-1-resource", "response-2", "response-3"],
            )
            self.assertEqual(
                [response["usage"]["total_tokens"] for response in manifest["responses"]],
                [3, 5, 5],
            )
            self.assertEqual(manifest["usage"]["total_tokens"], 13)

    def test_local_convenience_prepare_commits_empty_visible_report_without_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self._database(root, visible=False)
            roots = self._roots(root)
            preflight = self._preflight(database, roots)
            self.assertEqual(preflight.visible_post_ids, ())
            self.assertEqual(preflight.provider_phases_required, ())
            attempt = PreparedAttemptContext(
                attempt_id="attempt-empty-001",
                artifact_version_id="20260713T010203456789Z-" + "b" * 32,
            )
            result = prepare_daily_report(
                preflight,
                attempt=attempt,
                translator=TranslationService(client=None, assets=preflight.translation_assets),
                roots=roots,
                provider_authorization_id=None,
                prepare_action_authorization_id="prepare-empty-1",
            )
            self.assertIsNone(result.provider_authorization_id)
            manifest = json.loads((result.private_dir / "translation-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["items"], [])
            self.assertEqual(manifest["request_count"], 0)
            self.assertFalse(manifest["translation_provider_attempt_made"])
            self.assertFalse(manifest["translation_reused"])
            self.assertFalse(manifest["semantic_validation_reused"])

    def test_blocked_manifest_is_sanitized_schema_valid_and_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            roots = self._roots(root)
            manifest = build_blocked_translation_attempt(
                run_id="daily_collect_20260713_0700",
                attempt_id="attempt-blocked-1",
                preflight=None,
                pipeline_evidence=None,
                stage="preflight",
                reason_codes=["database_missing"],
                provider_authorization_id=None,
            )
            encoded = canonical_json_bytes(manifest)
            self.assertNotIn(b"source_text", encoded)
            self.assertNotIn(b'"zh"', encoded)
            self.assertNotIn(b"api_key", encoded.lower())
            path = write_blocked_attempt(
                roots=roots,
                run_id="daily_collect_20260713_0700",
                attempt_id="attempt-blocked-1",
                manifest=manifest,
            )
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            with self.assertRaisesRegex(RuntimeError, "blocked_attempt_exists"):
                write_blocked_attempt(
                    roots=roots,
                    run_id="daily_collect_20260713_0700",
                    attempt_id="attempt-blocked-1",
                    manifest=manifest,
                )

    def test_host_commit_blocked_moves_exact_handoff_without_touching_current(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            roots = self._roots(root)
            manifest = build_blocked_translation_attempt(
                run_id="daily_collect_20260713_0700",
                attempt_id="attempt-blocked-handoff",
                preflight=None,
                pipeline_evidence=None,
                stage="preflight",
                reason_codes=["database_missing"],
                provider_authorization_id=None,
            )
            staged = stage_blocked_attempt(
                roots=roots,
                run_id="daily_collect_20260713_0700",
                attempt_id="attempt-blocked-handoff",
                manifest=manifest,
            )
            payload_sha = sha256_hex(staged.read_bytes())
            with self.assertRaisesRegex(RuntimeError, "blocked_handoff_mismatch"):
                commit_staged_blocked_attempt(
                    roots=roots,
                    expected_run_id="daily_collect_20260713_0700",
                    expected_attempt_id="attempt-blocked-handoff",
                    expected_manifest_sha256="0" * 64,
                    expected_provider_authorization_id=None,
                    schema_assets=load_report_schema_assets(config_root=CONFIG_ROOT),
                )
            self.assertFalse((roots.state_root / "prepared-current.json").exists())
            committed = commit_staged_blocked_attempt(
                roots=roots,
                expected_run_id="daily_collect_20260713_0700",
                expected_attempt_id="attempt-blocked-handoff",
                expected_manifest_sha256=payload_sha,
                expected_provider_authorization_id=None,
                schema_assets=load_report_schema_assets(config_root=CONFIG_ROOT),
            )
            self.assertTrue(committed.exists())
            self.assertFalse(staged.exists())
            self.assertFalse((roots.state_root / "prepared-current.json").exists())
            self.assertEqual(list(roots.public_root.iterdir()), [])
            self.assertEqual(list(roots.private_root.iterdir()), [])

    def test_host_commit_blocked_rejects_extra_handoff_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            roots = self._roots(root)
            manifest = build_blocked_translation_attempt(
                run_id="daily_collect_20260713_0700",
                attempt_id="attempt-blocked-extra",
                preflight=None,
                pipeline_evidence=None,
                stage="preflight",
                reason_codes=["database_missing"],
                provider_authorization_id=None,
            )
            staged = stage_blocked_attempt(
                roots=roots,
                run_id="daily_collect_20260713_0700",
                attempt_id="attempt-blocked-extra",
                manifest=manifest,
            )
            extra = staged.parent / "unexpected.txt"
            extra.write_text("unexpected", encoding="utf-8")
            extra.chmod(0o600)
            with self.assertRaisesRegex(RuntimeError, "blocked_handoff_file_set_invalid"):
                commit_staged_blocked_attempt(
                    roots=roots,
                    expected_run_id="daily_collect_20260713_0700",
                    expected_attempt_id="attempt-blocked-extra",
                    expected_manifest_sha256=sha256_hex(staged.read_bytes()),
                    expected_provider_authorization_id=None,
                    schema_assets=load_report_schema_assets(config_root=CONFIG_ROOT),
                )
            self.assertFalse((roots.state_root / "prepared-current.json").exists())

    def test_admin_commit_prepared_requires_reserved_permit_and_terminals_after_verify(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release_sha = "a" * 64
            shadow, roots = self._shadow_roots(
                root, release_sha256=release_sha
            )
            run_id = "daily_collect_20260713_0700"
            action_id = "prepare-action-host-success"
            self._install_reserved_prepare_permit(
                shadow=shadow,
                release_sha256=release_sha,
                run_id=run_id,
                authorization_id=action_id,
            )
            database = self._database(root, visible=False)
            preflight = self._preflight(database, roots)
            attempt = PreparedAttemptContext(
                attempt_id="attempt-host-success",
                artifact_version_id="20260713T010203456789Z-" + "a" * 32,
            )
            staged = stage_daily_report(
                preflight,
                attempt=attempt,
                translator=TranslationService(
                    client=None, assets=preflight.translation_assets
                ),
                roots=roots,
                provider_authorization_id=None,
                prepare_action_authorization_id=action_id,
            )
            committed = self._admin(
                "commit-prepared",
                "--shadow-root",
                str(shadow),
                "--release-dir",
                str(ROOT),
                "--config-root",
                str(CONFIG_ROOT),
                "--authorization-id",
                action_id,
                "--expected-release-sha256",
                release_sha,
                "--run-id",
                run_id,
                "--attempt-id",
                attempt.attempt_id,
                "--expected-artifact-version-id",
                attempt.artifact_version_id,
                "--expected-bundle-sha256",
                staged.bundle_sha256,
                "--expected-outbox-sha256",
                staged.outbox_sha256,
                "--expected-commit-request-sha256",
                staged.commit_request_sha256,
            )
            self.assertEqual(committed.returncode, 0, committed.stderr)
            self.assertIn("status=committed", committed.stdout)
            self.assertIn("provider_call=false", committed.stdout)
            self.assertIn("live_send=false", committed.stdout)
            current = json.loads(
                (roots.state_root / "prepared-current.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                current["artifact_version_id"], attempt.artifact_version_id
            )
            state = json.loads(
                shadow.joinpath(
                    "control", "permit-state", f"{action_id}.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(state["status"], "consumed")

    def test_admin_commit_prepared_mismatch_keeps_current_absent_and_burns_permit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release_sha = "b" * 64
            shadow, roots = self._shadow_roots(
                root, release_sha256=release_sha
            )
            run_id = "daily_collect_20260713_0700"
            action_id = "prepare-action-host-mismatch"
            self._install_reserved_prepare_permit(
                shadow=shadow,
                release_sha256=release_sha,
                run_id=run_id,
                authorization_id=action_id,
            )
            database = self._database(root, visible=False)
            preflight = self._preflight(database, roots)
            attempt = PreparedAttemptContext(
                attempt_id="attempt-host-mismatch",
                artifact_version_id="20260713T010203456789Z-" + "b" * 32,
            )
            staged = stage_daily_report(
                preflight,
                attempt=attempt,
                translator=TranslationService(
                    client=None, assets=preflight.translation_assets
                ),
                roots=roots,
                provider_authorization_id=None,
                prepare_action_authorization_id=action_id,
            )
            rejected = self._admin(
                "commit-prepared",
                "--shadow-root",
                str(shadow),
                "--release-dir",
                str(ROOT),
                "--config-root",
                str(CONFIG_ROOT),
                "--authorization-id",
                action_id,
                "--expected-release-sha256",
                release_sha,
                "--run-id",
                run_id,
                "--attempt-id",
                attempt.attempt_id,
                "--expected-artifact-version-id",
                attempt.artifact_version_id,
                "--expected-bundle-sha256",
                staged.bundle_sha256,
                "--expected-outbox-sha256",
                staged.outbox_sha256,
                "--expected-commit-request-sha256",
                "0" * 64,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertFalse((roots.state_root / "prepared-current.json").exists())
            state = json.loads(
                shadow.joinpath(
                    "control", "permit-state", f"{action_id}.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(state["status"], "blocked")

    def test_admin_commit_blocked_publishes_only_sanitized_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release_sha = "c" * 64
            shadow, roots = self._shadow_roots(
                root, release_sha256=release_sha
            )
            run_id = "daily_collect_20260713_0700"
            action_id = "prepare-action-host-blocked"
            attempt_id = "attempt-host-blocked"
            self._install_reserved_prepare_permit(
                shadow=shadow,
                release_sha256=release_sha,
                run_id=run_id,
                authorization_id=action_id,
            )
            manifest = build_blocked_translation_attempt(
                run_id=run_id,
                attempt_id=attempt_id,
                preflight=None,
                pipeline_evidence=None,
                stage="preflight",
                reason_codes=["database_missing"],
                provider_authorization_id=None,
            )
            staged = stage_blocked_attempt(
                roots=roots,
                run_id=run_id,
                attempt_id=attempt_id,
                manifest=manifest,
            )
            committed = self._admin(
                "commit-blocked",
                "--shadow-root",
                str(shadow),
                "--release-dir",
                str(ROOT),
                "--config-root",
                str(CONFIG_ROOT),
                "--authorization-id",
                action_id,
                "--expected-release-sha256",
                release_sha,
                "--run-id",
                run_id,
                "--attempt-id",
                attempt_id,
                "--expected-blocked-manifest-sha256",
                sha256_hex(staged.read_bytes()),
            )
            self.assertEqual(committed.returncode, 0, committed.stderr)
            self.assertIn("status=blocked_committed", committed.stdout)
            self.assertTrue(
                roots.blocked_root.joinpath(
                    run_id, attempt_id, "blocked-manifest.json"
                ).exists()
            )
            self.assertFalse((roots.state_root / "prepared-current.json").exists())
            self.assertEqual(list(roots.public_root.iterdir()), [])
            state = json.loads(
                shadow.joinpath(
                    "control", "permit-state", f"{action_id}.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(state["status"], "blocked")

    def test_admin_commit_blocked_provider_candidate_requires_attempt_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release_sha = "9" * 64
            shadow, roots = self._shadow_roots(
                root, release_sha256=release_sha
            )
            run_id = "daily_collect_20260713_0700"
            action_id = "prepare-action-host-blocked-provider"
            provider_id = "provider-action-host-blocked-provider"
            attempt_id = "attempt-host-blocked-provider"
            self._install_reserved_prepare_permit(
                shadow=shadow,
                release_sha256=release_sha,
                run_id=run_id,
                authorization_id=action_id,
            )
            self._install_reserved_shadow_provider_permit(
                shadow=shadow,
                release_sha256=release_sha,
                run_id=run_id,
                authorization_id=provider_id,
            )
            bound = self._admin(
                "bind-provider-attempt",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                provider_id,
                "--prepare-action-authorization-id",
                action_id,
                "--expected-release-sha256",
                release_sha,
                "--run-id",
                run_id,
                "--attempt-id",
                attempt_id,
            )
            self.assertEqual(bound.returncode, 0, bound.stderr)
            manifest = build_blocked_translation_attempt(
                run_id=run_id,
                attempt_id=attempt_id,
                preflight=None,
                pipeline_evidence=None,
                stage="pipeline",
                reason_codes=["translation_pipeline_blocked"],
                provider_authorization_id=provider_id,
            )
            staged = stage_blocked_attempt(
                roots=roots,
                run_id=run_id,
                attempt_id=attempt_id,
                manifest=manifest,
            )
            rejected = self._admin(
                "commit-blocked",
                "--shadow-root",
                str(shadow),
                "--release-dir",
                str(ROOT),
                "--config-root",
                str(CONFIG_ROOT),
                "--authorization-id",
                action_id,
                "--provider-authorization-id",
                provider_id,
                "--expected-release-sha256",
                release_sha,
                "--run-id",
                run_id,
                "--attempt-id",
                attempt_id,
                "--expected-blocked-manifest-sha256",
                sha256_hex(staged.read_bytes()),
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertFalse(
                roots.blocked_root.joinpath(
                    run_id, attempt_id, "blocked-manifest.json"
                ).exists()
            )
            for authorization_id in (action_id, provider_id):
                state = json.loads(
                    shadow.joinpath(
                        "control",
                        "permit-state",
                        f"{authorization_id}.json",
                    ).read_text(encoding="utf-8")
                )
                self.assertEqual(state["status"], "blocked")

    def test_admin_commit_blocked_invalid_handoff_terminalizes_permits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release_sha = "7" * 64
            shadow, roots = self._shadow_roots(
                root, release_sha256=release_sha
            )
            run_id = "daily_collect_20260713_0700"
            action_id = "prepare-action-host-invalid-handoff"
            provider_id = "provider-action-host-invalid-handoff"
            attempt_id = "attempt-host-invalid-handoff"
            self._install_reserved_prepare_permit(
                shadow=shadow,
                release_sha256=release_sha,
                run_id=run_id,
                authorization_id=action_id,
            )
            self._install_reserved_shadow_provider_permit(
                shadow=shadow,
                release_sha256=release_sha,
                run_id=run_id,
                authorization_id=provider_id,
            )
            bound = self._admin(
                "bind-provider-attempt",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                provider_id,
                "--prepare-action-authorization-id",
                action_id,
                "--expected-release-sha256",
                release_sha,
                "--run-id",
                run_id,
                "--attempt-id",
                attempt_id,
            )
            self.assertEqual(bound.returncode, 0, bound.stderr)
            manifest = build_blocked_translation_attempt(
                run_id=run_id,
                attempt_id=attempt_id,
                preflight=None,
                pipeline_evidence=None,
                stage="key_metadata",
                reason_codes=["deepseek_client_invalid"],
                provider_authorization_id=provider_id,
            )
            staged = stage_blocked_attempt(
                roots=roots,
                run_id=run_id,
                attempt_id=attempt_id,
                manifest=manifest,
            )
            invalid_manifest = json.loads(staged.read_text(encoding="utf-8"))
            invalid_manifest["translation_provider_attempt_made"] = "false"
            staged.write_bytes(canonical_json_bytes(invalid_manifest))
            rejected = self._admin(
                "commit-blocked",
                "--shadow-root",
                str(shadow),
                "--release-dir",
                str(ROOT),
                "--config-root",
                str(CONFIG_ROOT),
                "--authorization-id",
                action_id,
                "--provider-authorization-id",
                provider_id,
                "--expected-release-sha256",
                release_sha,
                "--run-id",
                run_id,
                "--attempt-id",
                attempt_id,
                "--expected-blocked-manifest-sha256",
                sha256_hex(staged.read_bytes()),
            )
            self.assertNotEqual(rejected.returncode, 0)
            for authorization_id in (action_id, provider_id):
                state = json.loads(
                    shadow.joinpath(
                        "control",
                        "permit-state",
                        f"{authorization_id}.json",
                    ).read_text(encoding="utf-8")
                )
                self.assertEqual(state["status"], "blocked")

    def test_admin_commit_blocked_accepts_bound_provider_with_empty_attempt_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release_sha = "8" * 64
            shadow, roots = self._shadow_roots(
                root, release_sha256=release_sha
            )
            run_id = "daily_collect_20260713_0700"
            action_id = "prepare-action-host-no-provider-attempt"
            provider_id = "provider-action-host-no-provider-attempt"
            attempt_id = "attempt-host-no-provider-attempt"
            self._install_reserved_prepare_permit(
                shadow=shadow,
                release_sha256=release_sha,
                run_id=run_id,
                authorization_id=action_id,
            )
            self._install_reserved_shadow_provider_permit(
                shadow=shadow,
                release_sha256=release_sha,
                run_id=run_id,
                authorization_id=provider_id,
            )
            bound = self._admin(
                "bind-provider-attempt",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                provider_id,
                "--prepare-action-authorization-id",
                action_id,
                "--expected-release-sha256",
                release_sha,
                "--run-id",
                run_id,
                "--attempt-id",
                attempt_id,
            )
            self.assertEqual(bound.returncode, 0, bound.stderr)
            ledger, _lifecycle = cli._create_provider_attempt_lifecycle(
                root=shadow / "provider-attempts",
                provider_authorization_id=provider_id,
                run_id=run_id,
                attempt_id=attempt_id,
                release_sha256="f" * 64,
            )
            manifest = build_blocked_translation_attempt(
                run_id=run_id,
                attempt_id=attempt_id,
                preflight=None,
                pipeline_evidence=None,
                stage="key_metadata",
                reason_codes=["deepseek_client_invalid"],
                provider_authorization_id=provider_id,
                provider_attempt_ledger=ledger,
            )
            staged = stage_blocked_attempt(
                roots=roots,
                run_id=run_id,
                attempt_id=attempt_id,
                manifest=manifest,
            )
            committed = self._admin(
                "commit-blocked",
                "--shadow-root",
                str(shadow),
                "--release-dir",
                str(ROOT),
                "--config-root",
                str(CONFIG_ROOT),
                "--authorization-id",
                action_id,
                "--provider-authorization-id",
                provider_id,
                "--expected-release-sha256",
                release_sha,
                "--run-id",
                run_id,
                "--attempt-id",
                attempt_id,
                "--expected-blocked-manifest-sha256",
                sha256_hex(staged.read_bytes()),
            )
            self.assertEqual(committed.returncode, 0, committed.stderr)
            action_state = json.loads(
                shadow.joinpath(
                    "control", "permit-state", f"{action_id}.json"
                ).read_text(encoding="utf-8")
            )
            provider_state = json.loads(
                shadow.joinpath(
                    "control", "permit-state", f"{provider_id}.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(action_state["status"], "blocked")
            self.assertEqual(provider_state["status"], "closed_no_attempt")

    def test_admin_recover_prepared_state_finishes_projection_journal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release_sha = "d" * 64
            shadow, roots = self._shadow_roots(
                root, release_sha256=release_sha
            )
            run_id = "daily_collect_20260713_0700"
            version = "20260713T010203456789Z-" + "d" * 32
            final_public = roots.public_root / "prepared" / run_id / version
            final_public.mkdir(parents=True, mode=0o700)
            final_public.chmod(0o700)
            target = final_public / "artifact.txt"
            target.write_text("artifact", encoding="utf-8")
            target.chmod(0o600)
            current = roots.state_root / "prepared-current.json"
            current.write_text(
                json.dumps(
                    {
                        "schema_version": "prepared-current-v1",
                        "run_id": run_id,
                        "artifact_version_id": version,
                        "bundle_sha256": "1" * 64,
                        "report_input_fingerprint": "2" * 64,
                        "outbox_sha256": "3" * 64,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            current.chmod(0o600)
            journal = roots.state_root / "prepared-projection-journal.json"
            journal.write_text(
                json.dumps(
                    {
                        "schema_version": "prepared-projection-journal-v1",
                        "final_public_dir": str(final_public),
                        "projections": {
                            "artifact.txt": (
                                f"prepared/{run_id}/{version}/artifact.txt"
                            )
                        },
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            journal.chmod(0o600)
            recovered = self._admin(
                "recover-prepared-state",
                "--shadow-root",
                str(shadow),
                "--release-dir",
                str(ROOT),
                "--config-root",
                str(CONFIG_ROOT),
                "--expected-release-sha256",
                release_sha,
            )
            self.assertEqual(recovered.returncode, 0, recovered.stderr)
            self.assertFalse(journal.exists())
            self.assertTrue((roots.public_root / "artifact.txt").is_symlink())
            self.assertEqual(
                (roots.public_root / "artifact.txt").resolve(), target.resolve()
            )

    def test_admin_commit_provider_candidate_requires_bound_attempt_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release_sha = "e" * 64
            shadow, roots = self._shadow_roots(
                root, release_sha256=release_sha
            )
            run_id = "daily_collect_20260713_0700"
            action_id = "prepare-action-host-provider"
            provider_id = "provider-action-host-provider"
            attempt_id = "attempt-host-provider"
            self._install_reserved_prepare_permit(
                shadow=shadow,
                release_sha256=release_sha,
                run_id=run_id,
                authorization_id=action_id,
            )
            self._install_reserved_shadow_provider_permit(
                shadow=shadow,
                release_sha256=release_sha,
                run_id=run_id,
                authorization_id=provider_id,
            )
            bound = self._admin(
                "bind-provider-attempt",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                provider_id,
                "--prepare-action-authorization-id",
                action_id,
                "--expected-release-sha256",
                release_sha,
                "--run-id",
                run_id,
                "--attempt-id",
                attempt_id,
            )
            self.assertEqual(bound.returncode, 0, bound.stderr)
            database = self._database(root)
            preflight = self._preflight(database, roots)
            attempt = PreparedAttemptContext(
                attempt_id=attempt_id,
                artifact_version_id="20260713T010203456789Z-" + "e" * 32,
            )
            ledger, lifecycle = cli._create_provider_attempt_lifecycle(
                root=shadow / "provider-attempts",
                provider_authorization_id=provider_id,
                run_id=run_id,
                attempt_id=attempt_id,
                release_sha256="f" * 64,
            )
            client = PreparedFakeClient(attempt_lifecycle_sink=lifecycle)
            staged = stage_daily_report(
                preflight,
                attempt=attempt,
                translator=TranslationService(
                    client=client,
                    assets=preflight.translation_assets,
                ),
                roots=roots,
                provider_authorization_id=provider_id,
                prepare_action_authorization_id=action_id,
                provider_attempt_ledger=ledger,
            )
            committed = self._admin(
                "commit-prepared",
                "--shadow-root",
                str(shadow),
                "--release-dir",
                str(ROOT),
                "--config-root",
                str(CONFIG_ROOT),
                "--authorization-id",
                action_id,
                "--provider-authorization-id",
                provider_id,
                "--expected-release-sha256",
                release_sha,
                "--run-id",
                run_id,
                "--attempt-id",
                attempt_id,
                "--expected-artifact-version-id",
                attempt.artifact_version_id,
                "--expected-bundle-sha256",
                staged.bundle_sha256,
                "--expected-outbox-sha256",
                staged.outbox_sha256,
                "--expected-commit-request-sha256",
                staged.commit_request_sha256,
            )
            self.assertEqual(committed.returncode, 0, committed.stderr)
            for authorization_id in (action_id, provider_id):
                state = json.loads(
                    shadow.joinpath(
                        "control",
                        "permit-state",
                        f"{authorization_id}.json",
                    ).read_text(encoding="utf-8")
                )
                self.assertEqual(state["status"], "consumed")

    def test_admin_commit_provider_accepts_single_production_prepare_permit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release_sha = "7" * 64
            shadow, roots = self._shadow_roots(
                root, release_sha256=release_sha
            )
            run_id = "daily_collect_20260713_0700"
            authorization_id = "prepare-action-production-provider"
            attempt_id = "attempt-production-provider"
            self._install_reserved_prepare_permit(
                shadow=shadow,
                release_sha256=release_sha,
                run_id=run_id,
                authorization_id=authorization_id,
            )
            bound = self._admin(
                "bind-provider-attempt",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                authorization_id,
                "--prepare-action-authorization-id",
                authorization_id,
                "--expected-release-sha256",
                release_sha,
                "--run-id",
                run_id,
                "--attempt-id",
                attempt_id,
            )
            self.assertEqual(bound.returncode, 0, bound.stderr)
            database = self._database(root)
            preflight = self._preflight(database, roots)
            attempt = PreparedAttemptContext(
                attempt_id=attempt_id,
                artifact_version_id="20260713T010203456789Z-" + "7" * 32,
            )
            ledger, lifecycle = cli._create_provider_attempt_lifecycle(
                root=shadow / "provider-attempts",
                provider_authorization_id=authorization_id,
                run_id=run_id,
                attempt_id=attempt_id,
                release_sha256="f" * 64,
            )
            staged = stage_daily_report(
                preflight,
                attempt=attempt,
                translator=TranslationService(
                    client=PreparedFakeClient(attempt_lifecycle_sink=lifecycle),
                    assets=preflight.translation_assets,
                ),
                roots=roots,
                provider_authorization_id=authorization_id,
                prepare_action_authorization_id=authorization_id,
                provider_attempt_ledger=ledger,
            )
            committed = self._admin(
                "commit-prepared",
                "--shadow-root",
                str(shadow),
                "--release-dir",
                str(ROOT),
                "--config-root",
                str(CONFIG_ROOT),
                "--authorization-id",
                authorization_id,
                "--provider-authorization-id",
                authorization_id,
                "--expected-release-sha256",
                release_sha,
                "--run-id",
                run_id,
                "--attempt-id",
                attempt_id,
                "--expected-artifact-version-id",
                attempt.artifact_version_id,
                "--expected-bundle-sha256",
                staged.bundle_sha256,
                "--expected-outbox-sha256",
                staged.outbox_sha256,
                "--expected-commit-request-sha256",
                staged.commit_request_sha256,
            )
            self.assertEqual(committed.returncode, 0, committed.stderr)
            state = json.loads(
                shadow.joinpath(
                    "control",
                    "permit-state",
                    f"{authorization_id}.json",
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(state["status"], "consumed")

    def test_commit_failure_builder_strips_complete_text(self) -> None:
        complete = {
            "schema_version": "daily-translation-manifest-v1",
            "manifest_id": "manifest",
            "run_id": "daily_collect_20260713_0700",
            "status": "complete",
            "provider_authorization_id": "provider-auth-1",
            "provider_call": True,
            "translation_provider_call": True,
            "translation_provider_attempt_made": True,
            "translation_phase_attempt_made": True,
            "semantic_validation_phase_attempt_made": True,
            "request_count": 2,
            "retry_count": 0,
            "duration_ms": 2,
            "usage": {
                "prompt_tokens": 6,
                "completion_tokens": 4,
                "prompt_cache_hit_tokens": 2,
                "prompt_cache_miss_tokens": 4,
                "total_tokens": 10,
            },
            "responses": [],
            "counts": {"posts": 1, "titles": 1, "bodies": 1, "comments": 0, "items": 2},
            "items": [
                {
                    "stable_id": "post:p1:title",
                    "input_sha256": "a" * 64,
                    "zh": "不应复制",
                    "status": "accepted",
                    "critical_error_codes": [],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            ledger_root = Path(temporary) / "ledger"
            ledger_root.mkdir(mode=0o700)
            ledger = ProviderAttemptLedger(
                path=ledger_root / "provider-attempts-v2.jsonl",
                authorization_id="provider-auth-1",
                release_sha256="d" * 64,
                run_id="daily_collect_20260713_0700",
                attempt_id="attempt-commit-blocked",
                clock=lambda: "2026-08-11T01:02:03+00:00",
            )
            tip = ZERO_TIP
            usage = {
                "prompt_tokens": 3,
                "completion_tokens": 2,
                "prompt_cache_hit_tokens": 1,
                "prompt_cache_miss_tokens": 2,
                "total_tokens": 5,
            }
            metadata = {
                "http_status": 200,
                "response_id": None,
                "actual_model": "deepseek-chat",
                "system_fingerprint": None,
                "finish_reason": "stop",
                "retryable": False,
                "duration_ms": 1,
            }
            for sequence, phase, request_hash in (
                (1, "translation", "b" * 64),
                (2, "semantic_validation", "c" * 64),
            ):
                reserved = ledger.reserve(
                    phase=phase,
                    sequence=sequence,
                    request_payload_sha256=request_hash,
                    expected_tip=tip,
                )
                started = ledger.start(
                    phase=phase,
                    sequence=sequence,
                    request_payload_sha256=request_hash,
                    expected_tip=reserved.entry_hash,
                )
                terminal = ledger.terminal(
                    phase=phase,
                    sequence=sequence,
                    request_payload_sha256=request_hash,
                    result="succeeded",
                    response_metadata=metadata,
                    usage=usage,
                    expected_tip=started.entry_hash,
                )
                tip = terminal.entry_hash
            complete["provider_attempt_ledger"] = ledger.build_manifest_binding(
                status="complete"
            )

            blocked = build_commit_blocked_attempt_from_complete_manifest(
                verified_complete_manifest=complete,
                attempt_id="attempt-commit-blocked",
                stage="commit",
                reason_codes=["projection_failed"],
            )

        encoded = canonical_json_bytes(blocked)
        self.assertNotIn("不应复制".encode("utf-8"), encoded)
        self.assertNotIn(b'"zh"', encoded)
        self.assertEqual(blocked["provider_authorization_id"], "provider-auth-1")
        expected_binding = {
            **complete["provider_attempt_ledger"],
            "status": "blocked",
        }
        self.assertEqual(blocked["provider_attempt_ledger"], expected_binding)

    def test_commit_failure_builder_rejects_ledger_binding_drift(self) -> None:
        complete = {
            "schema_version": "daily-translation-manifest-v1",
            "run_id": "daily_collect_20260713_0700",
            "status": "complete",
            "provider_authorization_id": "provider-auth-1",
            "provider_call": True,
            "translation_provider_call": True,
            "translation_provider_attempt_made": True,
            "translation_phase_attempt_made": True,
            "semantic_validation_phase_attempt_made": False,
            "request_count": 1,
            "retry_count": 0,
            "duration_ms": 1,
            "usage": {
                "prompt_tokens": 3,
                "completion_tokens": 2,
                "prompt_cache_hit_tokens": 1,
                "prompt_cache_miss_tokens": 2,
                "total_tokens": 5,
            },
            "counts": {"posts": 1},
            "items": [],
        }
        with tempfile.TemporaryDirectory() as temporary:
            ledger_root = Path(temporary) / "ledger"
            ledger_root.mkdir(mode=0o700)
            ledger = ProviderAttemptLedger(
                path=ledger_root / "provider-attempts-v2.jsonl",
                authorization_id="provider-auth-1",
                release_sha256="d" * 64,
                run_id="daily_collect_20260713_0700",
                attempt_id="attempt-commit-blocked",
                clock=lambda: "2026-08-11T01:02:03+00:00",
            )
            reserved = ledger.reserve(
                phase="translation",
                sequence=1,
                request_payload_sha256="b" * 64,
                expected_tip=ZERO_TIP,
            )
            started = ledger.start(
                phase="translation",
                sequence=1,
                request_payload_sha256="b" * 64,
                expected_tip=reserved.entry_hash,
            )
            terminal = ledger.terminal(
                phase="translation",
                sequence=1,
                request_payload_sha256="b" * 64,
                result="succeeded",
                response_metadata={
                    "http_status": 200,
                    "response_id": None,
                    "actual_model": "deepseek-chat",
                    "system_fingerprint": None,
                    "finish_reason": "stop",
                    "retryable": False,
                    "duration_ms": 1,
                },
                usage=complete["usage"],
                expected_tip=started.entry_hash,
            )
            self.assertNotEqual(terminal.entry_hash, "e" * 64)
            complete["provider_attempt_ledger"] = ledger.build_manifest_binding(
                status="complete"
            )

        drift_cases = {
            "attempt_identity": (
                "provider_attempt_ledger.attempt_id",
                "wrong-attempt",
            ),
            "run_identity": (
                "provider_attempt_ledger.run_id",
                "wrong-run",
            ),
            "authorization_identity": (
                "provider_attempt_ledger.authorization_id",
                "wrong-auth",
            ),
            "tip": ("provider_attempt_ledger.ledger_tip", "e" * 64),
            "event_count": ("provider_attempt_ledger.event_count", 4),
            "external_count": (
                "provider_attempt_ledger.external_attempt_count",
                2,
            ),
            "top_level_request_count": ("request_count", 2),
        }
        for label, (path, value) in drift_cases.items():
            with self.subTest(label=label):
                tampered = json.loads(json.dumps(complete))
                target = tampered
                components = path.split(".")
                for component in components[:-1]:
                    target = target[component]
                target[components[-1]] = value
                with self.assertRaises(ProviderAttemptLedgerError):
                    build_commit_blocked_attempt_from_complete_manifest(
                        verified_complete_manifest=tampered,
                        attempt_id="attempt-commit-blocked",
                        stage="commit",
                        reason_codes=["projection_failed"],
                    )


if __name__ == "__main__":
    unittest.main()
