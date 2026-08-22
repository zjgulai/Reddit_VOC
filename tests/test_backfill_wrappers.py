from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
LOCAL_WRAPPER = ROOT / "scripts" / "run_historical_backfill.sh"
SERVER_WRAPPER = ROOT / "scripts" / "server_historical_backfill.sh"
RUN_ID = "backfill_momcozy_20250101_20260711"
RELEASE_MANIFEST_RELATIVE_PATH = (
    "config/backfill/momcozy-backfill-release-manifest-20260711.json"
)
SEED_BASELINE_RELATIVE_PATH = (
    "config/backfill/momcozy-seed-baseline-20250101-20260711.json"
)
RELEASE_REVIEWED_PATHS = (
    "pyproject.toml",
    "scripts/run_historical_backfill.sh",
    "scripts/server_historical_backfill.sh",
    "src/reddit_voc/__init__.py",
    "src/reddit_voc/adapters.py",
    "src/reddit_voc/analyzer.py",
    "src/reddit_voc/backfill_archive.py",
    "src/reddit_voc/backfill_archived_recovery.py",
    "src/reddit_voc/backfill_cli.py",
    "src/reddit_voc/backfill_merge.py",
    "src/reddit_voc/backfill_models.py",
    "src/reddit_voc/backfill_provider.py",
    "src/reddit_voc/backfill_seed.py",
    "src/reddit_voc/backfill_storage.py",
    "src/reddit_voc/backfill_validation.py",
    "src/reddit_voc/keywords.py",
    "src/reddit_voc/models.py",
    "src/reddit_voc/search_config.py",
    "src/reddit_voc/storage.py",
    "src/reddit_voc/tikhub.py",
    "src/reddit_voc/time_window.py",
    SEED_BASELINE_RELATIVE_PATH,
    "config/backfill/momcozy-comment-cursor-contract-20260711.json",
)


class BackfillWrapperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve()
        self.capture = self.root / "arguments.bin"
        self.fake_python = self.root / "python3"
        self.fake_python.write_text(
            "#!/bin/sh\n"
            "printf '%s\\0' \"$@\" > \"$CAPTURE_FILE\"\n",
            encoding="utf-8",
        )
        self.fake_python.chmod(0o755)

        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        self.fake_docker = self.bin_dir / "docker"
        self.fake_docker.write_text(
            "#!/bin/sh\n"
            "printf '%s\\0' \"$@\" > \"$CAPTURE_FILE\"\n",
            encoding="utf-8",
        )
        self.fake_docker.chmod(0o755)

        self.code_root = self.root / "reviewed-code"
        self.host_run_root = self.root / "backfill" / RUN_ID
        self.code_root.mkdir()
        self.host_run_root.mkdir(parents=True)
        self.release_manifest_sha256 = self.create_reviewed_bundle()

    def create_reviewed_bundle(self) -> str:
        file_map: dict[str, str] = {}
        for relative_path in RELEASE_REVIEWED_PATHS:
            reviewed_file = self.code_root / relative_path
            reviewed_file.parent.mkdir(parents=True, exist_ok=True)
            if relative_path == "scripts/run_historical_backfill.sh":
                payload = (
                    "#!/usr/bin/env bash\n"
                    ": > \"${FAULT_EXECUTED_FILE:?}\"\n"
                ).encode("utf-8")
            else:
                payload = f"reviewed fixture: {relative_path}\n".encode("utf-8")
            reviewed_file.write_bytes(payload)
            file_map[relative_path] = sha256(payload).hexdigest()
        manifest = {
            "schema_version": "momcozy_backfill_release_manifest_v1",
            "run_id": RUN_ID,
            "seed_baseline": {
                "relative_path": SEED_BASELINE_RELATIVE_PATH,
                "sha256": file_map[SEED_BASELINE_RELATIVE_PATH],
            },
            "reviewed_files_sha256": file_map,
        }
        manifest_raw = (
            json.dumps(
                manifest,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        manifest_path = self.code_root / RELEASE_MANIFEST_RELATIVE_PATH
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_bytes(manifest_raw)
        return sha256(manifest_raw).hexdigest()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def read_arguments(self) -> list[str]:
        raw = self.capture.read_bytes()
        return [item.decode("utf-8") for item in raw.split(b"\0") if item]

    def run_local(
        self,
        phase: str,
        values: dict[str, str],
        *,
        expected_returncode: int = 0,
    ) -> list[str]:
        self.capture.unlink(missing_ok=True)
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "CAPTURE_FILE": str(self.capture),
            "REDDIT_VOC_BACKFILL_PYTHON": str(self.fake_python),
            "REDDIT_VOC_BACKFILL_PHASE": phase,
            **values,
        }
        result = subprocess.run(
            ["bash", str(LOCAL_WRAPPER)],
            cwd=ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, expected_returncode, result.stderr)
        if expected_returncode != 0:
            self.assertFalse(self.capture.exists())
            return []
        return self.read_arguments()

    def run_server(
        self,
        phase: str,
        values: dict[str, str],
        *,
        expected_returncode: int = 0,
    ) -> list[str]:
        self.capture.unlink(missing_ok=True)
        env = {
            "PATH": f"{self.bin_dir}:/usr/bin:/bin",
            "CAPTURE_FILE": str(self.capture),
            "REDDIT_VOC_BACKFILL_PHASE": phase,
            "REDDIT_VOC_BACKFILL_CONTAINER_IMAGE": (
                "fixture/image@sha256:" + "c" * 64
            ),
            "REDDIT_VOC_BACKFILL_CODE_ROOT": str(self.code_root),
            "REDDIT_VOC_BACKFILL_HOST_RUN_ROOT": str(self.host_run_root),
            "REDDIT_VOC_BACKFILL_CONTAINER_CODE_ROOT": "/app/backfill-code",
            "REDDIT_VOC_BACKFILL_RUN_ROOT": "/app/backfill-run",
            "REDDIT_VOC_BACKFILL_RUN_ID": RUN_ID,
            "REDDIT_VOC_BACKFILL_EXPECTED_RELEASE_MANIFEST_SHA256": (
                self.release_manifest_sha256
            ),
            **values,
        }
        result = subprocess.run(
            ["bash", str(SERVER_WRAPPER)],
            cwd=ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, expected_returncode, result.stderr)
        if expected_returncode != 0:
            self.assertFalse(self.capture.exists())
            return []
        return self.read_arguments()

    def run_server_with_mount_swap(
        self, target: str, values: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        executed = self.root / f"{target}-unverified-wrapper-executed"
        self.fake_docker.write_text(
            "#!/usr/bin/env python3\n"
            "import os\n"
            "from pathlib import Path\n"
            "import shutil\n"
            "import subprocess\n"
            "import sys\n"
            "args = sys.argv[1:]\n"
            "target = os.environ['FAULT_SWAP_TARGET']\n"
            "root_name = ('REDDIT_VOC_BACKFILL_CODE_ROOT' if target == 'code' "
            "else 'REDDIT_VOC_BACKFILL_HOST_RUN_ROOT')\n"
            "root = Path(os.environ[root_name])\n"
            "original = root.with_name(root.name + '.fault-original')\n"
            "root.rename(original)\n"
            "root.mkdir(parents=True)\n"
            "if target == 'code':\n"
            "    script = root / 'scripts' / 'run_historical_backfill.sh'\n"
            "    script.parent.mkdir(parents=True)\n"
            "    script.write_text('#!/bin/sh\\nexit 0\\n', encoding='utf-8')\n"
            "else:\n"
            "    markers = list(original.glob('.backfill-mount-identity.*'))\n"
            "    if len(markers) == 1:\n"
            "        markers[0].rename(root / markers[0].name)\n"
            "image = os.environ['REDDIT_VOC_BACKFILL_CONTAINER_IMAGE']\n"
            "image_index = args.index(image)\n"
            "command = args[image_index + 1:]\n"
            "try:\n"
            "    if len(command) < 13 or command[0] != '-c':\n"
            "        Path(os.environ['FAULT_EXECUTED_FILE']).write_text(\n"
            "            'unverified', encoding='utf-8'\n"
            "        )\n"
            "        return_code = 0\n"
            "    else:\n"
            "        volumes = {}\n"
            "        for index, value in enumerate(args[:-1]):\n"
            "            if value == '--volume':\n"
            "                host, container, _mode = args[index + 1].rsplit(':', 2)\n"
            "                volumes[container] = host\n"
            "        verifier_args = [\n"
            "            sys.executable, '-c', command[3],\n"
            "            volumes[command[4]], command[5], command[6], command[7],\n"
            "            volumes[command[8]], command[9], command[10],\n"
            "            command[11], command[12],\n"
            "        ]\n"
            "        return_code = subprocess.run(verifier_args, check=False).returncode\n"
            "finally:\n"
            "    shutil.rmtree(root)\n"
            "    original.rename(root)\n"
            "raise SystemExit(return_code)\n",
            encoding="utf-8",
        )
        self.fake_docker.chmod(0o755)
        env = {
            "PATH": f"{self.bin_dir}:/usr/bin:/bin",
            "CAPTURE_FILE": str(self.capture),
            "FAULT_SWAP_TARGET": target,
            "FAULT_EXECUTED_FILE": str(executed),
            "REDDIT_VOC_BACKFILL_PHASE": "replay",
            "REDDIT_VOC_BACKFILL_CONTAINER_IMAGE": (
                "fixture/image@sha256:" + "c" * 64
            ),
            "REDDIT_VOC_BACKFILL_CODE_ROOT": str(self.code_root),
            "REDDIT_VOC_BACKFILL_HOST_RUN_ROOT": str(self.host_run_root),
            "REDDIT_VOC_BACKFILL_CONTAINER_CODE_ROOT": "/app/backfill-code",
            "REDDIT_VOC_BACKFILL_RUN_ROOT": "/app/backfill-run",
            "REDDIT_VOC_BACKFILL_RUN_ID": RUN_ID,
            "REDDIT_VOC_BACKFILL_EXPECTED_RELEASE_MANIFEST_SHA256": (
                self.release_manifest_sha256
            ),
            **values,
        }
        result = subprocess.run(
            ["bash", str(SERVER_WRAPPER)],
            cwd=ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertFalse(executed.exists(), result.stderr)
        return result

    def reindex_server_values(self) -> dict[str, str]:
        source_payload = b"source-database-fixture"
        source = self.host_run_root / "reddit_voc_backfill.sqlite3"
        source.write_bytes(source_payload)
        (self.host_run_root / "private-raw").mkdir(exist_ok=True)
        (self.host_run_root / "reports").mkdir(exist_ok=True)
        return {
            "REDDIT_VOC_BACKFILL_SOURCE_DATABASE_PATH": (
                "/app/backfill-run/reddit_voc_backfill.sqlite3"
            ),
            "REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR": (
                "/app/backfill-run/private-raw"
            ),
            "REDDIT_VOC_BACKFILL_REINDEXED_DATABASE_PATH": (
                "/app/backfill-run/reindexed.sqlite3"
            ),
            "REDDIT_VOC_BACKFILL_EXPECTED_SOURCE_DATABASE_SHA256": (
                sha256(source_payload).hexdigest()
            ),
            "REDDIT_VOC_BACKFILL_RELEASE_MANIFEST": (
                "/app/backfill-code/" + RELEASE_MANIFEST_RELATIVE_PATH
            ),
            "REDDIT_VOC_BACKFILL_REPORT": (
                "/app/backfill-run/reports/reindex.json"
            ),
        }

    def test_static_boundaries_and_bash_array_dispatch(self) -> None:
        local = LOCAL_WRAPPER.read_text(encoding="utf-8")
        server = SERVER_WRAPPER.read_text(encoding="utf-8")
        lowered = f"{local}\n{server}".lower()
        for forbidden in (
            "server_daily_cycle",
            "server_daily_report",
            "daily_report",
            "dingtalk",
            "translation",
            "docker exec",
            "docker compose",
            "restart",
            "--network host",
            "eval ",
            ".env",
            ".pem",
        ):
            self.assertNotIn(forbidden, lowered)
        self.assertIn("args=(", local)
        self.assertIn("args+=(", local)
        self.assertIn("docker_args=(", server)
        self.assertIn("docker_args+=(", server)

    def test_local_maps_seed_and_replay_without_unrelated_arguments(self) -> None:
        seed = self.run_local(
            "seed",
            {
                "REDDIT_VOC_BACKFILL_RUN_ID": RUN_ID,
                "REDDIT_VOC_BACKFILL_DATABASE_PATH": "/run/reddit_voc_backfill.sqlite3",
                "REDDIT_VOC_BACKFILL_SOURCE_DIR": "/seed/input",
                "REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR": "/run/private-raw",
                "REDDIT_VOC_BACKFILL_REPORT_DIR": "/run/reports",
                "REDDIT_VOC_BACKFILL_WINDOW_START_UTC": "2024-12-31T16:00:00Z",
                "REDDIT_VOC_BACKFILL_REQUESTED_WINDOW_END_UTC": "2026-07-11T16:00:00Z",
                "REDDIT_VOC_BACKFILL_EFFECTIVE_WINDOW_END_UTC": "2026-07-11T16:00:00Z",
            },
        )
        self.assertEqual(seed[:3], ["-m", "reddit_voc.backfill_cli", "seed"])
        self.assertEqual(
            seed[3:],
            [
                "--run-id", RUN_ID,
                "--database", "/run/reddit_voc_backfill.sqlite3",
                "--source-dir", "/seed/input",
                "--raw-archive-dir", "/run/private-raw",
                "--report-dir", "/run/reports",
                "--window-start-utc", "2024-12-31T16:00:00Z",
                "--requested-window-end-utc", "2026-07-11T16:00:00Z",
                "--effective-window-end-utc", "2026-07-11T16:00:00Z",
            ],
        )

        replay = self.run_local(
            "replay",
            {
                "REDDIT_VOC_BACKFILL_RUN_ID": RUN_ID,
                "REDDIT_VOC_BACKFILL_SOURCE_DATABASE_PATH": "/run/reddit_voc_backfill.sqlite3",
                "REDDIT_VOC_BACKFILL_REPLAY_DATABASE_PATH": "/run/replay.sqlite3",
                "REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR": "/run/private-raw",
            },
        )
        self.assertEqual(
            replay,
            [
                "-m", "reddit_voc.backfill_cli", "replay",
                "--run-id", RUN_ID,
                "--source-database", "/run/reddit_voc_backfill.sqlite3",
                "--replay-database", "/run/replay.sqlite3",
                "--raw-archive-dir", "/run/private-raw",
            ],
        )

    def test_local_maps_reindex_discovery_exact_contract(self) -> None:
        arguments = self.run_local(
            "reindex-discovery",
            {
                "REDDIT_VOC_BACKFILL_RUN_ID": RUN_ID,
                "REDDIT_VOC_BACKFILL_SOURCE_DATABASE_PATH": (
                    "/run/reddit_voc_backfill.sqlite3"
                ),
                "REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR": "/run/private-raw",
                "REDDIT_VOC_BACKFILL_REINDEXED_DATABASE_PATH": (
                    "/run/reindexed.sqlite3"
                ),
                "REDDIT_VOC_BACKFILL_EXPECTED_SOURCE_DATABASE_SHA256": "a" * 64,
                "REDDIT_VOC_BACKFILL_RELEASE_MANIFEST": (
                    "/code/" + RELEASE_MANIFEST_RELATIVE_PATH
                ),
                "REDDIT_VOC_BACKFILL_EXPECTED_RELEASE_MANIFEST_SHA256": "b" * 64,
                "REDDIT_VOC_BACKFILL_REPORT": "/run/reports/reindex.json",
                "TIKHUB_API_KEY": "must-not-map",
                "REDDIT_VOC_BACKFILL_AUTHORIZE_PROVIDER_CALL": "1",
            },
        )
        self.assertEqual(
            arguments,
            [
                "-m", "reddit_voc.backfill_cli", "reindex-discovery",
                "--run-id", RUN_ID,
                "--source-database", "/run/reddit_voc_backfill.sqlite3",
                "--raw-archive-dir", "/run/private-raw",
                "--reindexed-database", "/run/reindexed.sqlite3",
                "--expected-source-database-sha256", "a" * 64,
                "--release-manifest", (
                    "/code/" + RELEASE_MANIFEST_RELATIVE_PATH
                ),
                "--expected-release-manifest-sha256", "b" * 64,
                "--report", "/run/reports/reindex.json",
            ],
        )

    def test_local_reindex_discovery_requires_every_input(self) -> None:
        values = {
            "REDDIT_VOC_BACKFILL_RUN_ID": RUN_ID,
            "REDDIT_VOC_BACKFILL_SOURCE_DATABASE_PATH": "/run/source.sqlite3",
            "REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR": "/run/private-raw",
            "REDDIT_VOC_BACKFILL_REINDEXED_DATABASE_PATH": "/run/reindexed.sqlite3",
            "REDDIT_VOC_BACKFILL_EXPECTED_SOURCE_DATABASE_SHA256": "a" * 64,
            "REDDIT_VOC_BACKFILL_RELEASE_MANIFEST": "/code/release.json",
            "REDDIT_VOC_BACKFILL_EXPECTED_RELEASE_MANIFEST_SHA256": "b" * 64,
            "REDDIT_VOC_BACKFILL_REPORT": "/run/reindex.json",
        }
        for missing in values:
            with self.subTest(missing=missing):
                incomplete = dict(values)
                incomplete.pop(missing)
                self.run_local(
                    "reindex-discovery", incomplete, expected_returncode=64
                )

    def test_local_maps_collection_recovery_exact_offline_contract(self) -> None:
        arguments = self.run_local(
            "recover-collection",
            {
                "REDDIT_VOC_BACKFILL_RUN_ID": RUN_ID,
                "REDDIT_VOC_BACKFILL_SOURCE_DATABASE_PATH": "/run/source.sqlite3",
                "REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR": "/run/private-raw",
                "REDDIT_VOC_BACKFILL_RECOVERED_DATABASE_PATH": (
                    "/run/recovered.sqlite3"
                ),
                "REDDIT_VOC_BACKFILL_EXPECTED_SOURCE_DATABASE_SHA256": "a" * 64,
                "REDDIT_VOC_BACKFILL_RECOVERED_AT_UTC": (
                    "2026-07-14T08:00:00+00:00"
                ),
                "REDDIT_VOC_BACKFILL_RELEASE_MANIFEST": "/code/release.json",
                "REDDIT_VOC_BACKFILL_EXPECTED_RELEASE_MANIFEST_SHA256": "b" * 64,
                "REDDIT_VOC_BACKFILL_REPORT": "/run/reports/recovery.json",
                "TIKHUB_API_KEY": "must-not-map",
            },
        )
        self.assertEqual(
            arguments,
            [
                "-m", "reddit_voc.backfill_cli", "recover-collection",
                "--run-id", RUN_ID,
                "--source-database", "/run/source.sqlite3",
                "--raw-archive-dir", "/run/private-raw",
                "--recovered-database", "/run/recovered.sqlite3",
                "--expected-source-database-sha256", "a" * 64,
                "--recovered-at-utc", "2026-07-14T08:00:00+00:00",
                "--release-manifest", "/code/release.json",
                "--expected-release-manifest-sha256", "b" * 64,
                "--report", "/run/reports/recovery.json",
            ],
        )

    def test_local_provider_authorization_flag_requires_exact_one(self) -> None:
        common = {
            "REDDIT_VOC_BACKFILL_RUN_ID": RUN_ID,
            "REDDIT_VOC_BACKFILL_DATABASE_PATH": "/run/reddit_voc_backfill.sqlite3",
            "REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR": "/run/private-raw",
            "REDDIT_VOC_BACKFILL_REPORT_DIR": "/run/reports",
            "REDDIT_VOC_BACKFILL_RELEASE_MANIFEST": "/code/config/release.json",
        }
        for value in (None, "0", "true", "01"):
            environment = dict(common)
            if value is not None:
                environment["REDDIT_VOC_BACKFILL_AUTHORIZE_PROVIDER_CALL"] = value
            arguments = self.run_local("probe", environment)
            self.assertNotIn("--authorize-provider-call", arguments)

        authorized = self.run_local(
            "probe",
            {
                **common,
                "REDDIT_VOC_BACKFILL_AUTHORIZE_PROVIDER_CALL": "1",
            },
        )
        self.assertEqual(authorized.count("--authorize-provider-call"), 1)
        self.assertNotIn("--max-provider-requests", authorized)

    def test_local_collect_maps_all_owner_approved_inputs(self) -> None:
        arguments = self.run_local(
            "collect",
            {
                "REDDIT_VOC_BACKFILL_RUN_ID": RUN_ID,
                "REDDIT_VOC_BACKFILL_DATABASE_PATH": "/run/reddit_voc_backfill.sqlite3",
                "REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR": "/run/private-raw",
                "REDDIT_VOC_BACKFILL_REPORT_DIR": "/run/reports",
                "REDDIT_VOC_BACKFILL_PROBE_REPORT": "/run/reports/probe.json",
                "REDDIT_VOC_BACKFILL_EXPECTED_PROBE_SHA256": "a" * 64,
                "REDDIT_VOC_BACKFILL_RELEASE_MANIFEST": "/code/config/release.json",
                "REDDIT_VOC_BACKFILL_EXPECTED_RELEASE_MANIFEST_SHA256": "b" * 64,
                "REDDIT_VOC_BACKFILL_COMMENT_CURSOR_CONTRACT": "/code/config/cursor.json",
                "REDDIT_VOC_BACKFILL_MAX_PROVIDER_REQUESTS_TOTAL": "100",
                "REDDIT_VOC_BACKFILL_INCLUDE_SUBREDDIT_SWEEP": "0",
                "REDDIT_VOC_BACKFILL_BUDGET_EXTENSION_AUTHORIZATION": (
                    "/run/reports/budget-extension-authorization.json"
                ),
                "REDDIT_VOC_BACKFILL_EXPECTED_BUDGET_EXTENSION_AUTHORIZATION_SHA256": (
                    "c" * 64
                ),
                "REDDIT_VOC_BACKFILL_AUTHORIZE_PROVIDER_CALL": "1",
            },
        )
        expected_pairs = {
            "--probe-report": "/run/reports/probe.json",
            "--expected-probe-sha256": "a" * 64,
            "--release-manifest": "/code/config/release.json",
            "--expected-release-manifest-sha256": "b" * 64,
            "--comment-cursor-contract": "/code/config/cursor.json",
            "--max-provider-requests-total": "100",
            "--include-subreddit-sweep": "0",
            "--budget-extension-authorization": (
                "/run/reports/budget-extension-authorization.json"
            ),
            "--expected-budget-extension-authorization-sha256": "c" * 64,
        }
        for flag, value in expected_pairs.items():
            index = arguments.index(flag)
            self.assertEqual(arguments[index + 1], value)
        self.assertEqual(arguments.count("--authorize-provider-call"), 1)

    def test_local_collect_budget_extension_authorization_is_all_or_none(self) -> None:
        common = {
            "REDDIT_VOC_BACKFILL_RUN_ID": RUN_ID,
            "REDDIT_VOC_BACKFILL_DATABASE_PATH": "/run/reddit_voc_backfill.sqlite3",
            "REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR": "/run/private-raw",
            "REDDIT_VOC_BACKFILL_REPORT_DIR": "/run/reports",
            "REDDIT_VOC_BACKFILL_PROBE_REPORT": "/run/reports/probe.json",
            "REDDIT_VOC_BACKFILL_EXPECTED_PROBE_SHA256": "a" * 64,
            "REDDIT_VOC_BACKFILL_RELEASE_MANIFEST": "/code/config/release.json",
            "REDDIT_VOC_BACKFILL_EXPECTED_RELEASE_MANIFEST_SHA256": "b" * 64,
            "REDDIT_VOC_BACKFILL_COMMENT_CURSOR_CONTRACT": "/code/config/cursor.json",
            "REDDIT_VOC_BACKFILL_MAX_PROVIDER_REQUESTS_TOTAL": "100",
            "REDDIT_VOC_BACKFILL_INCLUDE_SUBREDDIT_SWEEP": "0",
        }
        without_extension = self.run_local("collect", common)
        self.assertNotIn("--budget-extension-authorization", without_extension)
        self.assertNotIn(
            "--expected-budget-extension-authorization-sha256",
            without_extension,
        )

        for lone_name, lone_value in (
            (
                "REDDIT_VOC_BACKFILL_BUDGET_EXTENSION_AUTHORIZATION",
                "/run/reports/budget-extension-authorization.json",
            ),
            (
                "REDDIT_VOC_BACKFILL_EXPECTED_BUDGET_EXTENSION_AUTHORIZATION_SHA256",
                "c" * 64,
            ),
        ):
            with self.subTest(lone_name=lone_name):
                self.run_local(
                    "collect",
                    {**common, lone_name: lone_value},
                    expected_returncode=64,
                )

    def test_local_validate_maps_seed_and_full_contracts(self) -> None:
        common = {
            "REDDIT_VOC_BACKFILL_RUN_ID": RUN_ID,
            "REDDIT_VOC_BACKFILL_DATABASE_PATH": "/run/reddit_voc_backfill.sqlite3",
            "REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR": "/run/private-raw",
            "REDDIT_VOC_BACKFILL_SEED_BASELINE": "/code/config/baseline.json",
            "REDDIT_VOC_BACKFILL_RELEASE_MANIFEST": "/code/config/release.json",
            "REDDIT_VOC_BACKFILL_REPORT": "/run/reports/acceptance.json",
        }
        seed = self.run_local(
            "validate",
            {**common, "REDDIT_VOC_BACKFILL_SCOPE": "seed"},
        )
        self.assertIn("--seed-baseline", seed)
        self.assertIn("--release-manifest", seed)
        self.assertNotIn("--run-root", seed)
        self.assertNotIn("--expected-release-manifest-sha256", seed)

        full = self.run_local(
            "validate",
            {
                **common,
                "REDDIT_VOC_BACKFILL_SCOPE": "full",
                "REDDIT_VOC_BACKFILL_REPLAY_DATABASE_PATH": "/run/replay.sqlite3",
                "REDDIT_VOC_BACKFILL_RUN_ROOT": "/run",
                "REDDIT_VOC_BACKFILL_EXPECTED_RELEASE_MANIFEST_SHA256": "b" * 64,
            },
        )
        for flag, value in (
            ("--replay-database", "/run/replay.sqlite3"),
            ("--run-root", "/run"),
            ("--expected-release-manifest-sha256", "b" * 64),
        ):
            index = full.index(flag)
            self.assertEqual(full[index + 1], value)

    def test_local_rejects_unknown_phase_before_python(self) -> None:
        self.run_local("merge-plan", {}, expected_returncode=64)

    def test_server_all_phases_use_fresh_container_and_exact_mounts(self) -> None:
        online_values = {
            "REDDIT_VOC_BACKFILL_DATABASE_PATH": "/app/backfill-run/reddit_voc_backfill.sqlite3",
            "REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR": "/app/backfill-run/private-raw",
            "REDDIT_VOC_BACKFILL_REPORT_DIR": "/app/backfill-run/reports",
            "REDDIT_VOC_BACKFILL_RELEASE_MANIFEST": (
                "/app/backfill-code/" + RELEASE_MANIFEST_RELATIVE_PATH
            ),
            "REDDIT_VOC_ENABLE_TIKHUB": "1",
            "TIKHUB_BASE_URL": "https://fixture.invalid",
            "TIKHUB_API_KEY": "fixture-secret",
        }
        collect_values = {
            **online_values,
            "REDDIT_VOC_BACKFILL_PROBE_REPORT": "/app/backfill-run/reports/probe.json",
            "REDDIT_VOC_BACKFILL_EXPECTED_PROBE_SHA256": "a" * 64,
            "REDDIT_VOC_BACKFILL_EXPECTED_RELEASE_MANIFEST_SHA256": (
                self.release_manifest_sha256
            ),
            "REDDIT_VOC_BACKFILL_COMMENT_CURSOR_CONTRACT": "/app/backfill-code/config/cursor.json",
            "REDDIT_VOC_BACKFILL_MAX_PROVIDER_REQUESTS_TOTAL": "100",
            "REDDIT_VOC_BACKFILL_INCLUDE_SUBREDDIT_SWEEP": "0",
            "REDDIT_VOC_BACKFILL_BUDGET_EXTENSION_AUTHORIZATION": (
                "/app/backfill-run/reports/budget-extension-authorization.json"
            ),
            "REDDIT_VOC_BACKFILL_EXPECTED_BUDGET_EXTENSION_AUTHORIZATION_SHA256": (
                "d" * 64
            ),
        }
        offline_values = {
            "REDDIT_VOC_BACKFILL_SOURCE_DATABASE_PATH": "/app/backfill-run/reddit_voc_backfill.sqlite3",
            "REDDIT_VOC_BACKFILL_REPLAY_DATABASE_PATH": "/app/backfill-run/replay.sqlite3",
            "REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR": "/app/backfill-run/private-raw",
        }
        validate_values = {
            "REDDIT_VOC_BACKFILL_SCOPE": "full",
            "REDDIT_VOC_BACKFILL_DATABASE_PATH": "/app/backfill-run/reddit_voc_backfill.sqlite3",
            "REDDIT_VOC_BACKFILL_REPLAY_DATABASE_PATH": "/app/backfill-run/replay.sqlite3",
            "REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR": "/app/backfill-run/private-raw",
            "REDDIT_VOC_BACKFILL_SEED_BASELINE": (
                "/app/backfill-code/" + SEED_BASELINE_RELATIVE_PATH
            ),
            "REDDIT_VOC_BACKFILL_RELEASE_MANIFEST": (
                "/app/backfill-code/" + RELEASE_MANIFEST_RELATIVE_PATH
            ),
            "REDDIT_VOC_BACKFILL_EXPECTED_RELEASE_MANIFEST_SHA256": (
                self.release_manifest_sha256
            ),
            "REDDIT_VOC_BACKFILL_REPORT": "/app/backfill-run/reports/acceptance.json",
        }
        phase_values = {
            "probe": online_values,
            "collect": collect_values,
            "replay": offline_values,
            "validate": validate_values,
        }
        for phase, values in phase_values.items():
            with self.subTest(phase=phase):
                arguments = self.run_server(phase, values)
                self.assertEqual(arguments[:2], ["run", "--rm"])
                self.assertIn(
                    f"{self.code_root.resolve()}:/app/backfill-code:ro",
                    arguments,
                )
                self.assertIn(
                    f"{self.host_run_root.resolve()}:/app/backfill-run:rw",
                    arguments,
                )
                self.assertEqual(arguments.count("--volume"), 2)
                self.assertIn(
                    "fixture/image@sha256:" + "c" * 64,
                    arguments,
                )
                entrypoint_index = arguments.index("--entrypoint")
                self.assertEqual(arguments[entrypoint_index + 1], "/bin/bash")
                image_index = arguments.index(
                    "fixture/image@sha256:" + "c" * 64
                )
                bootstrap = arguments[image_index + 1:]
                self.assertEqual(bootstrap[0], "-c")
                self.assertIn("exec python3 -c", bootstrap[1])
                self.assertEqual(bootstrap[2], "backfill-mount-verifier")
                self.assertIn(
                    "momcozy_backfill_release_manifest_v1", bootstrap[3]
                )
                self.assertEqual(
                    bootstrap[4:9],
                    [
                        "/app/backfill-code",
                        RUN_ID,
                        self.release_manifest_sha256,
                        "exec",
                        "/app/backfill-run",
                    ],
                )
                self.assertRegex(
                    bootstrap[9],
                    r"^\.backfill-mount-identity\.[0-9a-f]{32}$",
                )
                self.assertRegex(bootstrap[10], r"^[0-9a-f]{64}$")
                self.assertRegex(bootstrap[11], r"^[0-9]+$")
                self.assertRegex(bootstrap[12], r"^[0-9]+$")
                if phase in {"replay", "validate"}:
                    network_index = arguments.index("--network")
                    self.assertEqual(arguments[network_index + 1], "none")
                    rendered = "\n".join(arguments)
                    self.assertNotIn("TIKHUB", rendered)
                    self.assertNotIn("fixture-secret", rendered)
                else:
                    self.assertNotIn("--network", arguments)
                    self.assertIn("REDDIT_VOC_ENABLE_TIKHUB", arguments)
                    self.assertIn("TIKHUB_BASE_URL", arguments)
                    self.assertIn("TIKHUB_API_KEY", arguments)
                    self.assertNotIn("fixture-secret", arguments)
                if phase == "collect":
                    self.assertIn(
                        "REDDIT_VOC_BACKFILL_BUDGET_EXTENSION_AUTHORIZATION",
                        arguments,
                    )
                    self.assertIn(
                        "REDDIT_VOC_BACKFILL_EXPECTED_BUDGET_EXTENSION_AUTHORIZATION_SHA256",
                        arguments,
                    )

    def test_server_reindex_discovery_is_offline_and_forwards_only_contract(self) -> None:
        arguments = self.run_server(
            "reindex-discovery",
            {
                **self.reindex_server_values(),
                "TIKHUB_API_KEY": "must-not-forward",
                "TIKHUB_BASE_URL": "https://must-not-forward.invalid",
                "REDDIT_VOC_ENABLE_TIKHUB": "1",
                "REDDIT_VOC_BACKFILL_AUTHORIZE_PROVIDER_CALL": "1",
                "REDDIT_VOC_BACKFILL_BUDGET_EXTENSION_AUTHORIZATION": (
                    "/app/backfill-run/provider-authorization.json"
                ),
            },
        )
        network_index = arguments.index("--network")
        self.assertEqual(arguments[network_index + 1], "none")
        forwarded = {
            arguments[index + 1]
            for index, value in enumerate(arguments[:-1])
            if value == "--env"
        }
        self.assertEqual(
            forwarded,
            {
                "PYTHONPATH=/app/backfill-code/src",
                "REDDIT_VOC_BACKFILL_PHASE",
                "REDDIT_VOC_BACKFILL_RUN_ID",
                "REDDIT_VOC_BACKFILL_SOURCE_DATABASE_PATH",
                "REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR",
                "REDDIT_VOC_BACKFILL_REINDEXED_DATABASE_PATH",
                "REDDIT_VOC_BACKFILL_EXPECTED_SOURCE_DATABASE_SHA256",
                "REDDIT_VOC_BACKFILL_RELEASE_MANIFEST",
                "REDDIT_VOC_BACKFILL_EXPECTED_RELEASE_MANIFEST_SHA256",
                "REDDIT_VOC_BACKFILL_REPORT",
            },
        )
        rendered = "\n".join(arguments)
        for forbidden in (
            "TIKHUB",
            "AUTHORIZE_PROVIDER_CALL",
            "BUDGET_EXTENSION_AUTHORIZATION",
            "must-not-forward",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_server_reindex_discovery_required_paths_fail_closed(self) -> None:
        values = self.reindex_server_values()
        required = (
            "REDDIT_VOC_BACKFILL_RUN_ID",
            "REDDIT_VOC_BACKFILL_SOURCE_DATABASE_PATH",
            "REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR",
            "REDDIT_VOC_BACKFILL_REINDEXED_DATABASE_PATH",
            "REDDIT_VOC_BACKFILL_EXPECTED_SOURCE_DATABASE_SHA256",
            "REDDIT_VOC_BACKFILL_RELEASE_MANIFEST",
            "REDDIT_VOC_BACKFILL_EXPECTED_RELEASE_MANIFEST_SHA256",
            "REDDIT_VOC_BACKFILL_REPORT",
        )
        for missing in required:
            with self.subTest(missing=missing):
                self.run_server(
                    "reindex-discovery",
                    {**values, missing: ""},
                    expected_returncode=64,
                )

        escaped_paths = (
            "REDDIT_VOC_BACKFILL_SOURCE_DATABASE_PATH",
            "REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR",
            "REDDIT_VOC_BACKFILL_REINDEXED_DATABASE_PATH",
            "REDDIT_VOC_BACKFILL_REPORT",
        )
        for name in escaped_paths:
            with self.subTest(escaped=name):
                self.run_server(
                    "reindex-discovery",
                    {**values, name: "/app/outside-run/value"},
                    expected_returncode=64,
                )

        self.run_server(
            "reindex-discovery",
            {
                **values,
                "REDDIT_VOC_BACKFILL_EXPECTED_SOURCE_DATABASE_SHA256": "A" * 64,
            },
            expected_returncode=64,
        )
        target = self.host_run_root / "reindexed.sqlite3"
        target.write_bytes(b"must-not-overwrite")
        self.run_server(
            "reindex-discovery", values, expected_returncode=64
        )

    def test_server_collection_recovery_is_network_none_and_provider_free(self) -> None:
        values = self.reindex_server_values()
        values.pop("REDDIT_VOC_BACKFILL_REINDEXED_DATABASE_PATH")
        values["REDDIT_VOC_BACKFILL_RECOVERED_DATABASE_PATH"] = (
            "/app/backfill-run/recovered.sqlite3"
        )
        values["REDDIT_VOC_BACKFILL_RECOVERED_AT_UTC"] = (
            "2026-07-14T08:00:00+00:00"
        )
        values["REDDIT_VOC_BACKFILL_REPORT"] = (
            "/app/backfill-run/reports/recovery.json"
        )
        values["TIKHUB_API_KEY"] = "must-not-forward"

        arguments = self.run_server("recover-collection", values)

        network_index = arguments.index("--network")
        self.assertEqual(arguments[network_index + 1], "none")
        rendered = "\n".join(arguments)
        self.assertNotIn("TIKHUB", rendered)
        self.assertNotIn("must-not-forward", rendered)
        self.assertIn("REDDIT_VOC_BACKFILL_RECOVERED_DATABASE_PATH", arguments)
        self.assertIn("REDDIT_VOC_BACKFILL_RECOVERED_AT_UTC", arguments)

    def test_server_collect_budget_extension_authorization_is_all_or_none(self) -> None:
        common = {
            "REDDIT_VOC_BACKFILL_DATABASE_PATH": (
                "/app/backfill-run/reddit_voc_backfill.sqlite3"
            ),
            "REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR": "/app/backfill-run/private-raw",
            "REDDIT_VOC_BACKFILL_REPORT_DIR": "/app/backfill-run/reports",
            "REDDIT_VOC_BACKFILL_PROBE_REPORT": "/app/backfill-run/reports/probe.json",
            "REDDIT_VOC_BACKFILL_EXPECTED_PROBE_SHA256": "a" * 64,
            "REDDIT_VOC_BACKFILL_RELEASE_MANIFEST": (
                "/app/backfill-code/" + RELEASE_MANIFEST_RELATIVE_PATH
            ),
            "REDDIT_VOC_BACKFILL_COMMENT_CURSOR_CONTRACT": (
                "/app/backfill-code/config/cursor.json"
            ),
            "REDDIT_VOC_BACKFILL_MAX_PROVIDER_REQUESTS_TOTAL": "100",
            "REDDIT_VOC_BACKFILL_INCLUDE_SUBREDDIT_SWEEP": "1",
        }
        for lone_name, lone_value in (
            (
                "REDDIT_VOC_BACKFILL_BUDGET_EXTENSION_AUTHORIZATION",
                "/app/backfill-run/reports/budget-extension-authorization.json",
            ),
            (
                "REDDIT_VOC_BACKFILL_EXPECTED_BUDGET_EXTENSION_AUTHORIZATION_SHA256",
                "d" * 64,
            ),
            (
                "REDDIT_VOC_BACKFILL_EXISTING_BUDGET_RESUME_AUTHORIZATION",
                "/app/backfill-run/reports/existing-budget-resume.json",
            ),
            (
                "REDDIT_VOC_BACKFILL_EXPECTED_EXISTING_BUDGET_RESUME_AUTHORIZATION_SHA256",
                "e" * 64,
            ),
        ):
            with self.subTest(lone_name=lone_name):
                self.run_server(
                    "collect",
                    {**common, lone_name: lone_value},
                    expected_returncode=64,
                )

    def test_server_rechecks_code_and_run_root_inside_the_mounted_container(self) -> None:
        replay_values = {
            "REDDIT_VOC_BACKFILL_SOURCE_DATABASE_PATH": (
                "/app/backfill-run/reddit_voc_backfill.sqlite3"
            ),
            "REDDIT_VOC_BACKFILL_REPLAY_DATABASE_PATH": (
                "/app/backfill-run/replay.sqlite3"
            ),
            "REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR": "/app/backfill-run/private-raw",
        }
        for target in ("code", "run"):
            with self.subTest(target=target):
                result = self.run_server_with_mount_swap(target, replay_values)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(
                    tuple(self.host_run_root.glob(".backfill-mount-identity.*")),
                    (),
                )

    def test_server_does_not_forward_unrelated_or_production_inputs(self) -> None:
        arguments = self.run_server(
            "replay",
            {
                "REDDIT_VOC_BACKFILL_SOURCE_DATABASE_PATH": "/app/backfill-run/reddit_voc_backfill.sqlite3",
                "REDDIT_VOC_BACKFILL_REPLAY_DATABASE_PATH": "/app/backfill-run/replay.sqlite3",
                "REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR": "/app/backfill-run/private-raw",
                "REDDIT_VOC_BACKFILL_PRODUCTION_DATABASE": "/prod/database.sqlite3",
                "AWS_SECRET_ACCESS_KEY": "must-not-forward",
                "TIKHUB_API_KEY": "must-not-forward-offline",
                "TIKHUB_BASE_URL": "https://must-not-forward.invalid",
            },
        )
        rendered = "\n".join(arguments)
        self.assertNotIn("PRODUCTION_DATABASE", rendered)
        self.assertNotIn("/prod/database.sqlite3", rendered)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", rendered)
        self.assertNotIn("must-not-forward", rendered)
        self.assertNotIn("TIKHUB", rendered)

    def test_server_rejects_parent_or_overlapping_write_mount(self) -> None:
        replay_values = {
            "REDDIT_VOC_BACKFILL_SOURCE_DATABASE_PATH": "/app/backfill-run/reddit_voc_backfill.sqlite3",
            "REDDIT_VOC_BACKFILL_REPLAY_DATABASE_PATH": "/app/backfill-run/replay.sqlite3",
            "REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR": "/app/backfill-run/private-raw",
        }
        self.run_server(
            "replay",
            {
                **replay_values,
                "REDDIT_VOC_BACKFILL_HOST_RUN_ROOT": str(self.host_run_root.parent),
            },
            expected_returncode=64,
        )

        nested_code = self.host_run_root / "code"
        nested_code.mkdir()
        self.run_server(
            "replay",
            {
                **replay_values,
                "REDDIT_VOC_BACKFILL_CODE_ROOT": str(nested_code),
            },
            expected_returncode=64,
        )

    def test_server_rejects_symlinked_run_root_or_ancestor_before_docker(self) -> None:
        replay_values = {
            "REDDIT_VOC_BACKFILL_SOURCE_DATABASE_PATH": (
                "/app/backfill-run/reddit_voc_backfill.sqlite3"
            ),
            "REDDIT_VOC_BACKFILL_REPLAY_DATABASE_PATH": (
                "/app/backfill-run/replay.sqlite3"
            ),
            "REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR": "/app/backfill-run/private-raw",
        }
        direct_target = self.root / "direct-target" / RUN_ID
        direct_target.mkdir(parents=True)
        direct_link = self.root / "direct-link" / RUN_ID
        direct_link.parent.mkdir()
        direct_link.symlink_to(direct_target, target_is_directory=True)

        ancestor_target = self.root / "ancestor-target"
        (ancestor_target / RUN_ID).mkdir(parents=True)
        ancestor_link = self.root / "ancestor-link"
        ancestor_link.symlink_to(ancestor_target, target_is_directory=True)

        for host_run_root in (direct_link, ancestor_link / RUN_ID):
            with self.subTest(host_run_root=host_run_root):
                self.run_server(
                    "replay",
                    {
                        **replay_values,
                        "REDDIT_VOC_BACKFILL_HOST_RUN_ROOT": str(host_run_root),
                    },
                    expected_returncode=64,
                )

    def test_server_rejects_seed_phase_without_invoking_container(self) -> None:
        self.run_server("seed", {}, expected_returncode=64)

    def test_server_rejects_wrong_bundle_sha_and_extra_file_before_docker(self) -> None:
        replay_values = {
            "REDDIT_VOC_BACKFILL_SOURCE_DATABASE_PATH": "/app/backfill-run/reddit_voc_backfill.sqlite3",
            "REDDIT_VOC_BACKFILL_REPLAY_DATABASE_PATH": "/app/backfill-run/replay.sqlite3",
            "REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR": "/app/backfill-run/private-raw",
        }
        self.run_server(
            "replay",
            {
                **replay_values,
                "REDDIT_VOC_BACKFILL_EXPECTED_RELEASE_MANIFEST_SHA256": "d" * 64,
            },
            expected_returncode=64,
        )

        (self.code_root / "unexpected.env").write_text(
            "must-not-enter-container\n",
            encoding="utf-8",
        )
        self.run_server("replay", replay_values, expected_returncode=64)

    def test_server_rejects_bundle_symlink_before_docker(self) -> None:
        (self.code_root / "unexpected-link").symlink_to(
            self.code_root / "pyproject.toml"
        )
        self.run_server(
            "replay",
            {
                "REDDIT_VOC_BACKFILL_SOURCE_DATABASE_PATH": "/app/backfill-run/reddit_voc_backfill.sqlite3",
                "REDDIT_VOC_BACKFILL_REPLAY_DATABASE_PATH": "/app/backfill-run/replay.sqlite3",
                "REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR": "/app/backfill-run/private-raw",
            },
            expected_returncode=64,
        )

    def test_server_rejects_symlinked_fixed_manifest_before_docker(self) -> None:
        manifest_path = self.code_root / RELEASE_MANIFEST_RELATIVE_PATH
        manifest_path.unlink()
        manifest_path.symlink_to(self.code_root / "pyproject.toml")
        self.run_server(
            "replay",
            {
                "REDDIT_VOC_BACKFILL_SOURCE_DATABASE_PATH": "/app/backfill-run/reddit_voc_backfill.sqlite3",
                "REDDIT_VOC_BACKFILL_REPLAY_DATABASE_PATH": "/app/backfill-run/replay.sqlite3",
                "REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR": "/app/backfill-run/private-raw",
            },
            expected_returncode=64,
        )

    def test_server_rejects_unpinned_or_option_like_image_before_docker(self) -> None:
        replay_values = {
            "REDDIT_VOC_BACKFILL_SOURCE_DATABASE_PATH": "/app/backfill-run/reddit_voc_backfill.sqlite3",
            "REDDIT_VOC_BACKFILL_REPLAY_DATABASE_PATH": "/app/backfill-run/replay.sqlite3",
            "REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR": "/app/backfill-run/private-raw",
        }
        for image in (
            "--privileged",
            "--entrypoint=/bin/sh",
            "fixture/image:latest",
            "fixture/image:/tmp@sha256:" + "c" * 64,
            "fixture/image@sha256:" + "D" * 64,
            "fixture/image@sha256:" + "c" * 63,
            "fixture/image@sha256:" + "c" * 64 + "\n--privileged",
        ):
            with self.subTest(image=image):
                self.run_server(
                    "replay",
                    {
                        **replay_values,
                        "REDDIT_VOC_BACKFILL_CONTAINER_IMAGE": image,
                    },
                    expected_returncode=64,
                )

    def test_server_rejects_nonfixed_manifest_and_broad_code_root(self) -> None:
        probe_values = {
            "REDDIT_VOC_BACKFILL_DATABASE_PATH": "/app/backfill-run/reddit_voc_backfill.sqlite3",
            "REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR": "/app/backfill-run/private-raw",
            "REDDIT_VOC_BACKFILL_REPORT_DIR": "/app/backfill-run/reports",
            "REDDIT_VOC_BACKFILL_RELEASE_MANIFEST": "/app/backfill-code/pyproject.toml",
        }
        self.run_server("probe", probe_values, expected_returncode=64)
        self.run_server(
            "probe",
            {
                **probe_values,
                "REDDIT_VOC_BACKFILL_CODE_ROOT": "/",
            },
            expected_returncode=64,
        )

    def test_server_rejects_mount_argument_injection_before_docker(self) -> None:
        replay_values = {
            "REDDIT_VOC_BACKFILL_SOURCE_DATABASE_PATH": "/app/backfill-run/reddit_voc_backfill.sqlite3",
            "REDDIT_VOC_BACKFILL_REPLAY_DATABASE_PATH": "/app/backfill-run/replay.sqlite3",
            "REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR": "/app/backfill-run/private-raw",
        }
        overrides = (
            {
                "REDDIT_VOC_BACKFILL_CODE_ROOT": str(self.code_root) + ":/tmp",
            },
            {
                "REDDIT_VOC_BACKFILL_CONTAINER_CODE_ROOT": "/app/code:/tmp",
            },
            {
                "REDDIT_VOC_BACKFILL_RUN_ROOT": "/app/run\n--privileged",
            },
        )
        for override in overrides:
            with self.subTest(override=override):
                self.run_server(
                    "replay",
                    {**replay_values, **override},
                    expected_returncode=64,
                )


if __name__ == "__main__":
    unittest.main()
