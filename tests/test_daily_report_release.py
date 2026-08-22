from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.build_daily_report_release import (
    RELEASE_FILE_ROLES,
    build_release,
    verify_release,
    verify_release_imports,
)


ROOT = Path(__file__).resolve().parents[1]


class DailyReportReleaseTests(unittest.TestCase):
    def test_builds_content_addressed_exact_allowlist_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release = build_release(
                source_root=ROOT,
                destination_root=Path(tmp),
                image_id="sha256:" + "a" * 64,
            )
            manifest = verify_release(release)
            self.assertEqual(release.name, manifest["release_sha256"])
            self.assertEqual(manifest["image_id"], "sha256:" + "a" * 64)
            entries = manifest["entries"]
            self.assertEqual(
                [entry["path"] for entry in entries], sorted(RELEASE_FILE_ROLES)
            )
            self.assertEqual(
                {entry["path"]: entry["role"] for entry in entries},
                RELEASE_FILE_ROLES,
            )
            self.assertTrue(all(entry["sha256"].startswith("sha256:") for entry in entries))

    def test_verify_rejects_tamper_extra_empty_directory_and_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp)
            release = build_release(
                source_root=ROOT,
                destination_root=destination,
                image_id="sha256:" + "b" * 64,
            )
            target = release / "src/reddit_voc/report_contracts.py"
            target.write_bytes(target.read_bytes() + b"\n# tampered\n")
            with self.assertRaisesRegex(RuntimeError, "release_entry_mismatch"):
                verify_release(release)

            release2 = build_release(
                source_root=ROOT,
                destination_root=destination,
                image_id="sha256:" + "c" * 64,
            )
            (release2 / "extra.txt").write_text("extra", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "release_file_set_mismatch"):
                verify_release(release2)

            release_with_extra_directory = build_release(
                source_root=ROOT,
                destination_root=destination,
                image_id="sha256:" + "f" * 64,
            )
            (release_with_extra_directory / "unexpected-empty").mkdir()
            with self.assertRaisesRegex(RuntimeError, "release_directory_set_mismatch"):
                verify_release(release_with_extra_directory)

            release3 = build_release(
                source_root=ROOT,
                destination_root=destination,
                image_id="sha256:" + "d" * 64,
            )
            victim = release3 / "src/reddit_voc/deepseek_client.py"
            victim.unlink()
            victim.symlink_to(ROOT / "src/reddit_voc/deepseek_client.py")
            with self.assertRaisesRegex(RuntimeError, "release_symlink_forbidden"):
                verify_release(release3)

    def test_manifest_has_no_duplicate_or_untracked_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release = build_release(
                source_root=ROOT,
                destination_root=Path(tmp),
                image_id="sha256:" + "e" * 64,
            )
            raw = (release / "report-release-manifest.json").read_text(encoding="utf-8")
            manifest = json.loads(raw)
            self.assertEqual(len(manifest["entries"]), len(RELEASE_FILE_ROLES))
            self.assertNotIn("api_key", raw.casefold())
            self.assertNotIn("webhook_url", raw.casefold())

    def test_cli_reports_actual_manifest_file_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release = build_release(
                source_root=ROOT,
                destination_root=Path(tmp),
                image_id="sha256:" + "9" * 64,
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/build_daily_report_release.py"),
                    "verify",
                    "--release-dir",
                    str(release),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            values = dict(
                line.split("=", 1)
                for line in completed.stdout.splitlines()
                if "=" in line
            )
            expected = hashlib.sha256(
                release.joinpath("report-release-manifest.json").read_bytes()
            ).hexdigest()
            self.assertEqual(values["manifest_sha256"], expected)
            self.assertNotEqual(values["manifest_sha256"], values["release_sha256"])

    def test_release_contains_admin_helper_and_complete_cli_import_closure(self) -> None:
        required = {
            "scripts/report_control.py",
            "tests/fixtures/reddit_thread_browser_json.json",
            "src/reddit_voc/__init__.py",
            "src/reddit_voc/adapters.py",
            "src/reddit_voc/analyzer.py",
            "src/reddit_voc/browser_profile.py",
            "src/reddit_voc/browser_runner.py",
            "src/reddit_voc/collector.py",
            "src/reddit_voc/exporter.py",
            "src/reddit_voc/keywords.py",
            "src/reddit_voc/models.py",
            "src/reddit_voc/ops.py",
            "src/reddit_voc/preflight.py",
            "src/reddit_voc/search_config.py",
            "src/reddit_voc/storage.py",
            "src/reddit_voc/tikhub.py",
            "src/reddit_voc/time_window.py",
            "src/reddit_voc/provider_attempt_ledger.py",
        }
        self.assertEqual(required - set(RELEASE_FILE_ROLES), set())
        self.assertEqual(RELEASE_FILE_ROLES["scripts/report_control.py"], "admin")
        self.assertEqual(
            RELEASE_FILE_ROLES["tests/fixtures/reddit_thread_browser_json.json"],
            "test",
        )
        self.assertTrue(
            all(RELEASE_FILE_ROLES[path] == "runtime" for path in required if path.startswith("src/"))
        )

    def test_release_is_self_contained_and_has_no_one_off_hotfix_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release = build_release(
                source_root=ROOT,
                destination_root=Path(tmp),
                image_id="sha256:" + "6" * 64,
            )
            verify_release(release)
            forbidden_markers = (b"runtime-hotfixes/", b"g6r2-a3-r")
            for entry, role in RELEASE_FILE_ROLES.items():
                if role == "test":
                    continue
                payload = release.joinpath(entry).read_bytes().lower()
                for marker in forbidden_markers:
                    self.assertNotIn(marker, payload, entry)
            self.assertEqual(
                release.joinpath("src/reddit_voc/prepared_report.py").read_bytes(),
                ROOT.joinpath("src/reddit_voc/prepared_report.py").read_bytes(),
            )
            launcher = release.joinpath("scripts/server_daily_report.sh").read_text(
                encoding="utf-8"
            )
            self.assertIn(
                'UPDATER="$RELEASE_DIR/scripts/server_update_daily_report_runtime_env.sh"',
                launcher,
            )
            self.assertIn('--public-staging-root "$PUBLIC_STAGING_ROOT"', launcher)
            self.assertIn('--private-staging-root "$PRIVATE_STAGING_ROOT"', launcher)

    def test_release_import_verifier_runs_without_repository_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release = build_release(
                source_root=ROOT,
                destination_root=Path(tmp),
                image_id="sha256:" + "8" * 64,
            )
            evidence = verify_release_imports(
                release,
                python_executable=Path(sys.executable),
                forbidden_root=ROOT,
            )
            self.assertEqual(evidence["status"], "ok")
            self.assertEqual(evidence["repository_fallback"], False)
            self.assertGreaterEqual(evidence["verified_module_count"], 10)

    def test_provider_free_runtime_smoke_does_not_add_release_bytecode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = build_release(
                source_root=ROOT,
                destination_root=root / "releases",
                image_id="sha256:" + "7" * 64,
            )
            environment = dict(os.environ)
            environment.update(
                {
                    "PYTHONPATH": os.pathsep.join(
                        [str(release / "src"), str(release)]
                    ),
                    "PYTHONNOUSERSITE": "1",
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "REDDIT_VOC_TRANSLATION_MODE": "dry_run",
                    "REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION": "0",
                    "REDDIT_VOC_DINGTALK_MODE": "dry_run",
                    "REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND": "0",
                    "REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT": "0",
                }
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(release / "scripts/report_runtime_smoke.py"),
                    "--config-root",
                    str(release / "config"),
                    "--work-root",
                    str(root / "smoke-work"),
                ],
                cwd=release,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("runtime_smoke=passed", completed.stdout)
            verify_release(release)
            self.assertEqual(list(release.rglob("*.pyc")), [])


if __name__ == "__main__":
    unittest.main()
