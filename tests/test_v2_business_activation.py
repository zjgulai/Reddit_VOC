from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from reddit_voc.report_contracts import canonical_json_bytes
from reddit_voc.v2_business_activation import (
    V2BusinessActivationError,
    build_business_activation,
    build_business_activation_value,
)


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "config/reddit-voc-v2-business-activation-20260715.json"


class V2BusinessActivationTests(unittest.TestCase):
    def setUp(self) -> None:
        if not SPEC.is_file():
            self.skipTest("full local activation fixture is unavailable")
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_full_local_activation_has_business_counts(self) -> None:
        value = build_business_activation_value(project_root=ROOT, spec_path=SPEC)
        self.assertEqual(value["business_counts"]["posts"], 3494)
        self.assertEqual(value["business_counts"]["stored_comments"], 27158)
        self.assertEqual(value["business_counts"]["analysis_ready_vocs"], 23586)
        self.assertEqual(value["business_counts"]["indicator_count"], 26)
        self.assertEqual(value["business_counts"]["persona_cohorts"], 8)
        self.assertFalse(value["promotable"])

    def test_replay_is_no_change(self) -> None:
        output = self.root / "manifest.json"
        first = build_business_activation(project_root=ROOT, spec_path=SPEC, output_path=output)
        second = build_business_activation(project_root=ROOT, spec_path=SPEC, output_path=output)
        self.assertEqual(first.manifest_sha256, second.manifest_sha256)
        self.assertEqual(second.write_status, "no_change")

    def test_tampered_artifact_binding_fails_closed(self) -> None:
        value = json.loads(SPEC.read_text())
        value["artifacts"]["metrics_manifest"]["sha256"] = "0" * 64
        tampered = self.root / "tampered-spec.json"
        tampered.write_bytes(canonical_json_bytes(value) + b"\n")
        with self.assertRaisesRegex(V2BusinessActivationError, "artifact binding mismatch"):
            build_business_activation_value(project_root=ROOT, spec_path=tampered)


if __name__ == "__main__":
    unittest.main()
