from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from reddit_voc import cli
from reddit_voc.collector import _reanalyze_run_with_deepseek
from reddit_voc.storage import VocStore


class OpencodeSafetyGateTests(unittest.TestCase):
    def test_reanalysis_helper_does_not_call_provider_without_explicit_authorization(self):
        with TemporaryDirectory() as tmp, patch.dict(
            "os.environ", {"DEEPSEEK_API_KEY": "fixture-key"}
        ), patch("reddit_voc.collector.analyze_batch_with_deepseek") as provider:
            store = VocStore(Path(tmp) / "voc.sqlite3")
            store.migrate()

            updated = _reanalyze_run_with_deepseek(store, "run-1")

        self.assertEqual(updated, 0)
        provider.assert_not_called()

    def test_reanalysis_cli_blocks_before_database_or_provider_without_gate(self):
        output = io.StringIO()
        with TemporaryDirectory() as tmp, patch.dict(
            "os.environ", {"DEEPSEEK_API_KEY": "fixture-key"}
        ), redirect_stdout(output):
            result = cli.main([
                "reanalyze-run",
                "--database",
                str(Path(tmp) / "missing-parent" / "voc.sqlite3"),
                "--run-id",
                "run-1",
            ])

        self.assertEqual(result, 1)
        self.assertEqual(
            json.loads(output.getvalue()),
            {"status": "blocked", "reason": "provider_call_not_authorized"},
        )


if __name__ == "__main__":
    unittest.main()
