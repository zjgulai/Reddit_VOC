from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/verify_version_consistency.py"
SPEC = importlib.util.spec_from_file_location("verify_version_consistency", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class VersionConsistencyTests(unittest.TestCase):
    def test_local_source_rebuilds_the_locked_daily_release(self) -> None:
        lock = MODULE._load_json(ROOT / "config/production-version-lock.json")
        result = MODULE.verify_local(lock)
        # The pinned release identity must equal the rebuilt-from-source SHA that
        # the lock records (re-pinned 2026-10-29 after the ADR-004 M-A changes:
        # content_entity/permalink joined the release list).
        self.assertEqual(
            result["daily_release_sha256"],
            "7a061a97e02e4e6cd0394b9e9f4f83bb06e552a6a544a8dbb373fb0609f6f811",
        )
        self.assertEqual(result["insights_source_alignment"], "artifact_manifest_only")

    def test_production_observer_never_reads_secret_content(self) -> None:
        observer = MODULE._REMOTE_OBSERVER
        self.assertIn("report_env.lstat()", observer)
        self.assertNotIn("report_env.read_text", observer)
        self.assertNotIn("report_env.read_bytes", observer)
        self.assertNotIn("open(report_env", observer)


if __name__ == "__main__":
    unittest.main()
