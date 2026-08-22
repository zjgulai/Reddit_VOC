from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "run_daily_report.sh"


class DailyReportWrapperTests(unittest.TestCase):
    def _env_file(
        self,
        root: Path,
        *,
        provider: bool = False,
        live: bool = False,
        failure_alert: bool = False,
        dual: bool = False,
    ) -> Path:
        values = {
            "REDDIT_VOC_DATABASE_PATH": str(root / "voc.sqlite3"),
            "REDDIT_VOC_RUN_ID": "daily_collect_20260713_0700",
            "REDDIT_VOC_ATTEMPT_ID": "attempt-wrapper-1",
            "REDDIT_VOC_ARTIFACT_VERSION_ID": "20260713T030405678901Z-" + "a" * 32,
            "REDDIT_VOC_REPORT_PUBLIC_ROOT": str(root / "public"),
            "REDDIT_VOC_REPORT_PRIVATE_ROOT": str(root / "private"),
            "REDDIT_VOC_REPORT_PUBLIC_STAGING_ROOT": "" if live else str(root / "public-staging"),
            "REDDIT_VOC_REPORT_PRIVATE_STAGING_ROOT": "" if live else str(root / "private-staging"),
            "REDDIT_VOC_REPORT_STATE_ROOT": str(root / "state"),
            "REDDIT_VOC_REPORT_BLOCKED_ROOT": "" if live else str(root / "blocked"),
            "REDDIT_VOC_REPORT_HANDOFF_ROOT": "" if live else str(root / "handoff"),
            "REDDIT_VOC_PROVIDER_ATTEMPT_ROOT": "" if live else str(root / "provider-attempts"),
            "REDDIT_VOC_CONFIG_ROOT": str(ROOT / "config"),
            "REDDIT_VOC_ARTIFACT_BASE_URL": "https://files.example/reddit-voc",
            "DINGTALK_REQUIRED_KEYWORD": "LL",
            "REDDIT_VOC_DINGTALK_MAX_BYTES": "5000",
            "REDDIT_VOC_DINGTALK_MAX_PARTS": "2",
            "REDDIT_VOC_DINGTALK_CREDENTIAL_EPOCH_ID": "fixture-epoch-1",
            "REDDIT_VOC_DINGTALK_DESTINATION_ALIAS": "HighValueAsset",
            "REDDIT_VOC_TRANSLATION_MODE": "deepseek" if provider else "dry_run",
            "REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION": "1" if provider else "0",
            "REDDIT_VOC_DINGTALK_MODE": "live" if live else "dry_run",
            "REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND": "1" if live else "0",
            "REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT": "1" if failure_alert else "0",
            "DINGTALK_WEBHOOK_URL": "https://example.invalid/robot/send?access_token=fixture" if live or failure_alert else "",
            "DINGTALK_WEBHOOK_SECRET": "",
        }
        if dual:
            values["REDDIT_VOC_DINGTALK_CREDENTIAL_SET_EPOCH_ID"] = (
                "fixture-set-epoch-1"
            )
            values["REDDIT_VOC_DINGTALK_DESTINATION_SET_ID"] = (
                "HighValueAssetDual"
            )
            values["REDDIT_VOC_DINGTALK_PRIMARY_DESTINATION_ALIAS"] = (
                "HighValueAsset"
            )
            values["REDDIT_VOC_DINGTALK_SECONDARY_DESTINATION_ALIAS"] = (
                "HighValueAssetSecondary"
            )
            values["DINGTALK_WEBHOOK_URL_2"] = (
                "https://example.invalid/robot/send?access_token=fixture-secondary"
            )
            values["DINGTALK_WEBHOOK_SECRET_2"] = ""
        path = root / "reddit-voc-report.env"
        path.write_text("\n".join(f"{key}={value}" for key, value in values.items()) + "\n", encoding="utf-8")
        path.chmod(0o600)
        return path

    def _fake_python(self, root: Path) -> tuple[Path, Path]:
        capture = root / "argv.bin"
        fake = root / "fake-python"
        fake.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f"if [[ -n \"${{DINGTALK_WEBHOOK_URL:-}}\" ]]; then printf '1' > {str(root / 'webhook-present')!r}; else printf '0' > {str(root / 'webhook-present')!r}; fi\n"
            f"printf '%s\\0' \"$@\" > {str(capture)!r}\n",
            encoding="utf-8",
        )
        fake.chmod(0o755)
        return fake, capture

    def _run(self, root: Path, env_file: Path, *args: str) -> subprocess.CompletedProcess[str]:
        fake, _capture = self._fake_python(root)
        env = {
            **os.environ,
            "REDDIT_VOC_REPORT_ENV_FILE": str(env_file),
            "REDDIT_VOC_CLI_PYTHON_BIN": str(fake),
            "PYTHONPATH": str(ROOT / "src"),
        }
        return subprocess.run(
            ["bash", str(WRAPPER), *args],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_prepare_is_deferred_and_provider_args_follow_exact_gates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = self._env_file(root, provider=False)
            completed = self._run(
                root,
                env_file,
                "prepare",
                "--prepare-action-authorization-id",
                "prepare-action-wrapper",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            argv = (root / "argv.bin").read_bytes().split(b"\0")[:-1]
            self.assertIn(b"prepare-daily-report", argv)
            self.assertIn(b"--defer-host-commit", argv)
            self.assertIn(b"--prepare-action-authorization-id", argv)
            self.assertNotIn(b"--authorize-provider-call", argv)

            root2 = root / "provider"
            root2.mkdir()
            env_file2 = self._env_file(root2, provider=True)
            completed = self._run(
                root2,
                env_file2,
                "prepare",
                "--prepare-action-authorization-id",
                "prepare-action-wrapper",
                "--provider-authorization-id",
                "provider-auth-wrapper",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            argv2 = (root2 / "argv.bin").read_bytes().split(b"\0")[:-1]
            self.assertIn(b"--authorize-provider-call", argv2)
            provider_index = argv2.index(b"--provider-authorization-id")
            self.assertEqual(argv2[provider_index + 1], b"provider-auth-wrapper")

    def test_send_passes_owner_tuple_byte_for_byte(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = self._env_file(root, live=True)
            version = "20260713T030405678901Z-" + "b" * 32
            bundle = "c" * 64
            outbox = "d" * 64
            completed = self._run(
                root,
                env_file,
                "send",
                "--expected-artifact-version-id",
                version,
                "--expected-bundle-sha256",
                bundle,
                "--expected-outbox-sha256",
                outbox,
                "--authorization-id",
                "send-auth-wrapper",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            argv = (root / "argv.bin").read_bytes().split(b"\0")[:-1]
            self.assertIn(b"send-prepared-daily-report", argv)
            self.assertIn(b"--authorize-live-send", argv)
            for value in (version.encode(), bundle.encode(), outbox.encode(), b"send-auth-wrapper"):
                self.assertIn(value, argv)
            self.assertNotIn(b"send-daily-report-live", argv)
            self.assertEqual((root / "webhook-present").read_text(), "0")

    def test_send_dual_selects_dual_cli_and_requires_distinct_secondary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = self._env_file(root, live=True, dual=True)
            version = "20260713T030405678901Z-" + "b" * 32
            completed = self._run(
                root,
                env_file,
                "send-dual",
                "--expected-artifact-version-id",
                version,
                "--expected-bundle-sha256",
                "c" * 64,
                "--expected-outbox-sha256",
                "d" * 64,
                "--authorization-id",
                "send-auth-wrapper-dual",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            argv = (root / "argv.bin").read_bytes().split(b"\0")[:-1]
            self.assertIn(b"send-prepared-daily-report-dual", argv)
            self.assertNotIn(b"send-prepared-daily-report", argv)
            self.assertEqual((root / "webhook-present").read_text(), "0")

            payload = env_file.read_text(encoding="utf-8").replace(
                "access_token=fixture-secondary", "access_token=fixture"
            )
            env_file.write_text(payload, encoding="utf-8")
            env_file.chmod(0o600)
            completed = self._run(
                root,
                env_file,
                "send-dual",
                "--expected-artifact-version-id",
                version,
                "--expected-bundle-sha256",
                "c" * 64,
                "--expected-outbox-sha256",
                "d" * 64,
                "--authorization-id",
                "send-auth-wrapper-dual",
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("dingtalk_destination_duplicate", completed.stderr)

    def test_failure_alert_needs_independent_wrapper_authorization_and_env_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = self._env_file(root, failure_alert=True)
            completed = self._run(
                root,
                env_file,
                "prepare",
                "--prepare-action-authorization-id",
                "prepare-action-wrapper",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            argv = (root / "argv.bin").read_bytes().split(b"\0")[:-1]
            self.assertNotIn(b"--authorize-failure-alert", argv)
            self.assertEqual((root / "webhook-present").read_text(), "0")

            completed = self._run(
                root,
                env_file,
                "prepare",
                "--prepare-action-authorization-id",
                "prepare-action-wrapper",
                "--authorize-failure-alert",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            argv = (root / "argv.bin").read_bytes().split(b"\0")[:-1]
            self.assertIn(b"--authorize-failure-alert", argv)
            self.assertEqual((root / "webhook-present").read_text(), "1")

            disabled_root = root / "disabled"
            disabled_root.mkdir()
            disabled_env = self._env_file(disabled_root, failure_alert=False)
            completed = self._run(
                disabled_root,
                disabled_env,
                "prepare",
                "--prepare-action-authorization-id",
                "prepare-action-wrapper",
                "--authorize-failure-alert",
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("failure_alert_authorization_without_gate", completed.stderr)

    def test_env_parser_rejects_unknown_key_without_invoking_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = self._env_file(root)
            with env_file.open("a", encoding="utf-8") as handle:
                handle.write("UNEXPECTED_SECRET=value\n")
            completed = self._run(
                root,
                env_file,
                "prepare",
                "--prepare-action-authorization-id",
                "prepare-action-wrapper",
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertFalse((root / "argv.bin").exists())
            self.assertNotIn("value", completed.stdout + completed.stderr)

    def test_send_requires_opaque_destination_authority_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = self._env_file(root, live=True)
            payload = env_file.read_text(encoding="utf-8").replace(
                "REDDIT_VOC_DINGTALK_DESTINATION_ALIAS=HighValueAsset\n",
                "REDDIT_VOC_DINGTALK_DESTINATION_ALIAS=\n",
            )
            env_file.write_text(payload, encoding="utf-8")
            env_file.chmod(0o600)
            completed = self._run(
                root,
                env_file,
                "send",
                "--expected-artifact-version-id",
                "20260713T030405678901Z-" + "b" * 32,
                "--expected-bundle-sha256",
                "c" * 64,
                "--expected-outbox-sha256",
                "d" * 64,
                "--authorization-id",
                "send-auth-wrapper",
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("destination_alias_invalid", completed.stderr)
            self.assertFalse((root / "argv.bin").exists())

    def test_send_rejects_any_prepare_or_provider_runtime_path_before_cli(self) -> None:
        """Catches a send worker accidentally regaining Provider/staging access."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = self._env_file(root, live=True)
            payload = env_file.read_text(encoding="utf-8").replace(
                "REDDIT_VOC_PROVIDER_ATTEMPT_ROOT=\n",
                f"REDDIT_VOC_PROVIDER_ATTEMPT_ROOT={root / 'provider-attempts'}\n",
            )
            env_file.write_text(payload, encoding="utf-8")
            env_file.chmod(0o600)
            completed = self._run(
                root,
                env_file,
                "send",
                "--expected-artifact-version-id",
                "20260713T030405678901Z-" + "b" * 32,
                "--expected-bundle-sha256",
                "c" * 64,
                "--expected-outbox-sha256",
                "d" * 64,
                "--authorization-id",
                "send-auth-wrapper",
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("send_runtime_scope_invalid", completed.stderr)
            self.assertFalse((root / "argv.bin").exists())


if __name__ == "__main__":
    unittest.main()
