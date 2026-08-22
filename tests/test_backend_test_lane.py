from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/run_backend_test_lane.py"
SPEC = importlib.util.spec_from_file_location("run_backend_test_lane", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BackendTestLaneTests(unittest.TestCase):
    def test_registry_is_complete_and_new_tests_default_to_repository_lane(self) -> None:
        lanes = MODULE.classify_tests(ROOT)

        self.assertEqual(len(lanes["local-artifact"]), 38)
        self.assertGreater(len(lanes["repository"]), 100)
        self.assertIn("tests/test_backend_test_lane.py", lanes["repository"])
        self.assertNotIn(
            "tests/test_reddit_add_data_workbooks.py",
            lanes["repository"],
        )
        self.assertFalse(set(lanes["repository"]) & set(lanes["local-artifact"]))


if __name__ == "__main__":
    unittest.main()
