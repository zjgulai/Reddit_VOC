from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from reddit_voc.report_contracts import canonical_json_bytes
from reddit_voc.v2_center import (
    V2CenterStore,
    build_metric_release,
    compute_candidate_value,
    register_candidate,
)
from tests.test_v2_center_pipeline import _batch, _comment, _receipt


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/validate_reddit_v2_candidate.py"


class ValidateV2CandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.center = V2CenterStore(self.root / "center.sqlite3")
        manifest = _batch(
            self.root / "batch",
            batch_id="daily-20260717",
            start="2026-07-16T23:00:00Z",
            end="2026-07-17T23:00:00Z",
            post_created="2026-07-17T08:00:00Z",
            comments=[_comment("t1_comment1", "2026-07-17T09:00:00Z")],
        )
        self.center.consume_source_batch(
            manifest, validation_receipt_path=_receipt(manifest)
        )
        self.metric = build_metric_release(
            self.center,
            cutoff_utc=datetime(2026, 7, 17, 23, tzinfo=timezone.utc),
            output_path=self.root / "metric.json",
        )
        self.candidate = register_candidate(
            self.center,
            metric_release_path=self.metric.path,
            registry_root=self.root / "registry",
        )

    def run_validator(self, output: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--center-database",
                str(self.center.path),
                "--metric-release",
                str(self.metric.path),
                "--candidate",
                str(self.candidate.path),
                "--output",
                str(output),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_validator_passes_the_exact_chain(self) -> None:
        result = self.run_validator(self.root / "receipt.json")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "passed")

    def test_validator_rejects_tampered_metric_release(self) -> None:
        value = json.loads(self.metric.path.read_text())
        value["totals"]["voc"] += 1
        self.metric.path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")

        result = self.run_validator(self.root / "receipt.json")

        self.assertEqual(result.returncode, 1)
        self.assertIn("candidate metric binding mismatch", result.stderr)

    def test_validator_recomputes_metrics_even_when_candidate_hash_is_resigned(self) -> None:
        value = json.loads(self.metric.path.read_text())
        value["totals"]["voc"] = 999
        payload = canonical_json_bytes(value) + b"\n"
        self.metric.path.write_bytes(payload)
        resigned = compute_candidate_value(value, payload)
        self.candidate.path.write_bytes(canonical_json_bytes(resigned) + b"\n")

        result = self.run_validator(self.root / "receipt.json")

        self.assertEqual(result.returncode, 1)
        self.assertIn("metric release recomputation mismatch", result.stderr)


if __name__ == "__main__":
    unittest.main()
