from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from reddit_voc.v3_casebook_public import (
    CasebookPublicProjectionError,
    NEUTRAL_TITLE,
    build_public_projection,
    validate_public_projection,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tmp/reddit-voc-v3/reddit_add_data_20260715_v1"
CASEBOOK = SOURCE / "casebook-candidate-a1"
RECEIPT = SOURCE / "casebook-validation-a1/receipt.json"
CASEBOOK_SHA = "c0822ca4962f537b126090bc43104d5bbf8735df8e48ab3fd2936470229f93b4"
RECEIPT_SHA = "afb0cc4e5c8051d8d7e0b5eb513c4513ea43e422aa191936bfef5f71b3646107"


class PublicCasebookProjectionTest(unittest.TestCase):
    def test_builds_and_validates_read_only_public_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "public"
            built = build_public_projection(
                casebook_root=CASEBOOK,
                expected_casebook_manifest_sha256=CASEBOOK_SHA,
                receipt_path=RECEIPT,
                expected_receipt_sha256=RECEIPT_SHA,
                output_root=output,
                projection_id="reddit_voc_casebook_20260716_public_a1",
            )
            validated = validate_public_projection(
                public_root=output,
                expected_manifest_sha256=str(built["manifest_sha256"]),
            )
            casebook = json.loads((output / "casebook.json").read_text(encoding="utf-8"))
            dossier = casebook["dossiers"][0]
            self.assertEqual(validated["status"], "passed")
            self.assertEqual(dossier["title"], NEUTRAL_TITLE)
            self.assertEqual(
                (dossier["assessment"]["commercial_relation"], dossier["assessment"]["integrity_level"]),
                ("C2", "I3"),
            )
            self.assertFalse(dossier["assessment"]["brand_control_confirmed"])
            self.assertEqual([stage["label"] for stage in dossier["stages"]], ["洞察", "证据", "行动", "监测", "复盘"])
            payload = (output / "casebook.json").read_text(encoding="utf-8")
            self.assertNotIn("http://", payload)
            self.assertNotIn("https://", payload)
            self.assertNotIn('"author"', payload)

    def test_rejects_tampered_public_casebook(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "public"
            built = build_public_projection(
                casebook_root=CASEBOOK,
                expected_casebook_manifest_sha256=CASEBOOK_SHA,
                receipt_path=RECEIPT,
                expected_receipt_sha256=RECEIPT_SHA,
                output_root=output,
                projection_id="reddit_voc_casebook_20260716_public_a1",
            )
            casebook_path = output / "casebook.json"
            casebook_path.write_text(casebook_path.read_text(encoding="utf-8").replace("C2", "C3"), encoding="utf-8")
            with self.assertRaises(CasebookPublicProjectionError):
                validate_public_projection(
                    public_root=output,
                    expected_manifest_sha256=str(built["manifest_sha256"]),
                )


if __name__ == "__main__":
    unittest.main()
