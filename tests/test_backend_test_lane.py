from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
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

    def test_known_failures_are_loaded_and_disjoint(self) -> None:
        genuine, lane = MODULE.load_known_failures(ROOT)
        self.assertEqual(len(genuine), 1)
        self.assertEqual(len(lane), 34)
        self.assertFalse(genuine & lane)

    def test_junit_parser_maps_classname_to_pytest_node(self) -> None:
        xml = """<?xml version="1.0"?>
<testsuites><testsuite>
  <testcase classname="tests.test_alpha" name="test_ok"/>
  <testcase classname="tests.test_alpha.TestGroup" name="test_bad[param]">
    <failure message="boom"/>
  </testcase>
  <testcase classname="tests.test_alpha" name="test_error">
    <error message="collection"/>
  </testcase>
</testsuite></testsuites>
"""
        with tempfile.TemporaryDirectory() as temporary:
            report = Path(temporary) / "junit.xml"
            report.write_text(xml, encoding="utf-8")
            failures = MODULE.parse_junit_failures(report)
        self.assertEqual(
            failures,
            {
                "tests/test_alpha.py::TestGroup::test_bad[param]",
                "tests/test_alpha.py::test_error",
            },
        )

    def test_classify_failures_keeps_known_and_flags_new(self) -> None:
        known, unknown = MODULE.classify_failures(
            {
                "tests/test_a.py::test_known",
                "tests/test_a.py::test_new",
            },
            {"tests/test_a.py::test_known"},
            set(),
        )
        self.assertEqual(known, {"tests/test_a.py::test_known"})
        self.assertEqual(unknown, {"tests/test_a.py::test_new"})

    def test_malformed_known_failures_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "known.json"
            path.write_text('{"schema_version":"wrong","genuine_preexisting":{"nodes":[]}}', encoding="utf-8")
            with self.assertRaises(MODULE.TestLaneError):
                MODULE.load_known_failures(ROOT, path)


if __name__ == "__main__":
    unittest.main()
