from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.test_source_batch import _build_batch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/validate_reddit_source_batch.py"


class ValidateSourceBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_cli_writes_a_consumable_validation_receipt(self) -> None:
        manifest = _build_batch(self.root)
        output = self.root / "validation-receipt.json"

        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--manifest",
                str(manifest),
                "--batch-root",
                str(self.root),
                "--observed-at-utc",
                "2026-07-17T12:00:00Z",
                "--require-consumable",
                "--output",
                str(output),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        receipt = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "passed")
        self.assertTrue(receipt["consumable"])
        self.assertEqual(receipt["counts"]["posts"], 1)
        self.assertFalse(receipt["validation_boundaries"]["provider_call"])
        self.assertTrue(receipt["validation_boundaries"]["production_unchanged"])

    def test_cli_fails_closed_without_writing_a_receipt(self) -> None:
        manifest = _build_batch(self.root)
        output = self.root / "validation-receipt.json"
        (self.root / "posts.jsonl").write_text('{"post_id":"drift"}\n', encoding="utf-8")

        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--manifest",
                str(manifest),
                "--batch-root",
                str(self.root),
                "--observed-at-utc",
                "2026-07-17T12:00:00Z",
                "--require-consumable",
                "--output",
                str(output),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 1)
        self.assertIn("member physical binding mismatch:posts", completed.stderr)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
