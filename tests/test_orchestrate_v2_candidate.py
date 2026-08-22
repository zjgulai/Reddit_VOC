from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from reddit_voc.report_contracts import canonical_json_bytes
from reddit_voc.v2_center import V2CenterStore
from tests.test_v2_center_pipeline import _batch, _comment, _receipt


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/orchestrate_reddit_v2_candidate.py"


class OrchestrateV2CandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.manifest = _batch(
            self.root / "batch",
            batch_id="daily-orchestrator-test",
            start="2026-07-16T23:00:00Z",
            end="2026-07-17T23:00:00Z",
            post_created="2026-07-17T08:00:00Z",
            comments=[_comment("t1_comment1", "2026-07-17T09:00:00Z")],
        )
        self.receipt = _receipt(self.manifest)

    def run_orchestrator(self, *, observed_at: datetime, quiescence: int) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--center-database",
                str(self.root / "center.sqlite3"),
                "--source-batch-manifest",
                str(self.manifest),
                "--source-batch-validation-receipt",
                str(self.receipt),
                "--output-root",
                str(self.root / "output"),
                "--cutoff-utc",
                "2026-07-17T23:00:00Z",
                "--observed-at-utc",
                observed_at.isoformat().replace("+00:00", "Z"),
                "--quiescence-seconds",
                str(quiescence),
                "--receipt",
                str(self.root / "orchestration.json"),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_zero_quiescence_is_rejected(self) -> None:
        result = self.run_orchestrator(
            observed_at=datetime.now(timezone.utc), quiescence=0
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("quiescence_seconds is invalid", result.stderr)

    def test_future_observation_is_rejected(self) -> None:
        result = self.run_orchestrator(
            observed_at=datetime.now(timezone.utc) + timedelta(minutes=1),
            quiescence=60,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("must not be in the future", result.stderr)

    def test_baseline_bridge_is_registered_before_later_increment(self) -> None:
        baseline = _batch(
            self.root / "baseline",
            batch_id="v3-baseline-test",
            start="2026-07-15T23:00:00Z",
            end="2026-07-16T23:00:00Z",
            post_created="2026-07-10T08:00:00Z",
            comments=[_comment("t1_comment1", "2026-07-16T08:00:00Z")],
        )
        baseline_receipt = _receipt(baseline)
        increment = _batch(
            self.root / "increment",
            batch_id="daily-increment-test",
            start="2026-07-16T23:00:00Z",
            end="2026-07-17T23:00:00Z",
            post_created="2026-07-10T08:00:00Z",
            comments=[
                _comment("t1_comment1", "2026-07-16T08:00:00Z"),
                _comment("t1_comment2", "2026-07-17T08:00:00Z"),
            ],
        )
        increment_receipt = _receipt(increment)
        bridge = self.root / "baseline-bridge.json"
        bridge.write_bytes(
            canonical_json_bytes(
                {
                    "bridge_version": "v3-canonical-to-source-batch-v1",
                    "counts": {
                        "comments_jsonl": 1,
                        "linked_comments": 1,
                        "posts": 1,
                        "quarantined_comments": 0,
                        "stored_comments": 1,
                        "unresolved_parent_comments": 0,
                    },
                    "schema_version": "reddit_voc_v3_baseline_bridge_receipt_v1",
                    "source_batch_manifest_sha256": hashlib.sha256(
                        baseline.read_bytes()
                    ).hexdigest(),
                    "source_batch_validation_receipt_sha256": hashlib.sha256(
                        baseline_receipt.read_bytes()
                    ).hexdigest(),
                    "source_canonical_manifest_sha256": "a" * 64,
                    "source_canonical_validation_receipt_sha256": "b" * 64,
                    "source_dataset_id": "v3-baseline-dataset-test",
                    "status": "passed",
                    "upstream_validation_status": "passed",
                }
            )
            + b"\n"
        )
        observed_at = datetime.now(timezone.utc)
        old_timestamp = (observed_at - timedelta(seconds=10)).timestamp()
        for path in self.root.rglob("*"):
            if path.is_file():
                os.utime(path, (old_timestamp, old_timestamp))
        center_path = self.root / "center-bridge.sqlite3"
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--center-database",
                str(center_path),
                "--source-batch-manifest",
                str(baseline),
                "--source-batch-validation-receipt",
                str(baseline_receipt),
                "--source-batch-manifest",
                str(increment),
                "--source-batch-validation-receipt",
                str(increment_receipt),
                "--output-root",
                str(self.root / "output-bridge"),
                "--cutoff-utc",
                "2026-07-17T23:00:00Z",
                "--observed-at-utc",
                observed_at.isoformat().replace("+00:00", "Z"),
                "--quiescence-seconds",
                "1",
                "--receipt",
                str(self.root / "orchestration-bridge.json"),
                "--v3-baseline-bridge-receipt",
                str(bridge),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads((self.root / "orchestration-bridge.json").read_text())
        self.assertEqual(receipt["baseline_bridge_status"], "registered")
        store = V2CenterStore(center_path, read_only=True)
        self.assertEqual(store.count("baseline_bridges"), 1)
        self.assertEqual(store.count("canonical_comments"), 2)


if __name__ == "__main__":
    unittest.main()
