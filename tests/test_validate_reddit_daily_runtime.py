from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.validate_reddit_daily_runtime import (
    DailyRuntimeValidationError,
    validate_runtime,
)


CLI = """
def run_tikhub_collector_command(args):
    return collect_daily_tikhub(store, run_id='run', raw_artifact_root='raw')
"""
TIKHUB = """
def collect_daily_tikhub(store, *, run_id, raw_artifact_root=None):
    persist_raw_artifact(raw_artifact_root, one, data)
    persist_raw_artifact(raw_artifact_root, two, data)
"""


class DailyRuntimeValidationTests(unittest.TestCase):
    def fixture(self, *, tikhub: str = TIKHUB, source_receipt: bool = False) -> Path:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        package = root / "src/reddit_voc"
        scripts = root / "scripts"
        package.mkdir(parents=True)
        scripts.mkdir()
        (package / "cli.py").write_text(CLI, encoding="utf-8")
        (package / "tikhub.py").write_text(tikhub, encoding="utf-8")
        (package / "raw_artifacts.py").write_text("VALUE = 1\n", encoding="utf-8")
        runner = "python -m reddit_voc.cli run-tikhub-collector\n"
        if source_receipt:
            runner += "python -m reddit_voc.cli build-daily-source-batch\n"
            (package / "daily_source_batch.py").write_text("VALUE = 1\n", encoding="utf-8")
            (package / "schema_migration.py").write_text("VALUE = 1\n", encoding="utf-8")
            profiles = root / "config/source-batch"
            profiles.mkdir(parents=True)
            (profiles / "momcozy-query-v2.json").write_text("{}\n", encoding="utf-8")
            (profiles / "momcozy-coverage-v2.json").write_text("{}\n", encoding="utf-8")
        (scripts / "run_daily_collect.sh").write_text(runner, encoding="utf-8")
        return root

    def test_accepts_collect_only_abi_with_raw_persistence(self) -> None:
        result = validate_runtime(self.fixture(), require_source_receipt=False)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["profile"], "collect_only")

    def test_rejects_cli_collector_keyword_drift(self) -> None:
        incompatible = """
def collect_daily_tikhub(store, *, run_id):
    pass
"""
        with self.assertRaisesRegex(
            DailyRuntimeValidationError, "collector_cli_abi_mismatch:raw_artifact_root"
        ):
            validate_runtime(
                self.fixture(tikhub=incompatible), require_source_receipt=False
            )

    def test_source_receipt_profile_requires_atomic_closure(self) -> None:
        with self.assertRaisesRegex(
            DailyRuntimeValidationError, "source_receipt_runtime_incomplete"
        ):
            validate_runtime(self.fixture(), require_source_receipt=True)

        result = validate_runtime(
            self.fixture(source_receipt=True), require_source_receipt=True
        )
        self.assertTrue(all(result["source_receipt_checks"].values()))


if __name__ == "__main__":
    unittest.main()
