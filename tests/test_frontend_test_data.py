from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/frontend_test_data.py"
SPEC = importlib.util.spec_from_file_location("frontend_test_data", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FrontendTestDataTests(unittest.TestCase):
    def test_committed_fixture_verifies_and_materializes_without_extra_files(self) -> None:
        fixture = ROOT / (
            "ref/UI/momcozy-reddit-workbench/test-fixtures/public-data-20260723"
        )
        manifest = MODULE.verify_fixture(fixture)
        self.assertEqual(manifest["file_count"], 81)
        self.assertEqual(manifest["total_bytes"], 77_069_664)
        with tempfile.TemporaryDirectory() as temporary:
            public = Path(temporary) / "public"
            public.mkdir()
            MODULE.materialize_fixture(fixture_root=fixture, public_root=public)
            pointer = json.loads(
                (public / "data/reddit-voc/current-release.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(pointer["release_id"], manifest["fixture_id"])
            self.assertTrue(
                next((public / "data/reddit-voc").glob("*/public/public-validation-receipt.json")).is_file()
            )

    def test_materialize_refuses_to_overwrite_existing_public_data(self) -> None:
        fixture = ROOT / (
            "ref/UI/momcozy-reddit-workbench/test-fixtures/public-data-20260723"
        )
        with tempfile.TemporaryDirectory() as temporary:
            public = Path(temporary) / "public"
            (public / "data").mkdir(parents=True)
            with self.assertRaisesRegex(MODULE.FixtureError, "destination_exists"):
                MODULE.materialize_fixture(fixture_root=fixture, public_root=public)


if __name__ == "__main__":
    unittest.main()
