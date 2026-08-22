from __future__ import annotations

from pathlib import Path
import unittest

from reddit_voc.v3_casebook_resolution import (
    CasebookResolutionError,
    validate_latest_resolution,
)


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "tmp/reddit-voc-v3/candidate-orchestration/v3-center-refresh-002"
CASEBOOK = (
    ROOT
    / "ref/UI/momcozy-reddit-workbench/public/data/reddit-voc"
    / "reddit_voc_casebook_20260716_public_a1"
)


class CasebookLatestResolutionTests(unittest.TestCase):
    def test_all_historical_evidence_resolves_in_latest_center(self) -> None:
        result = validate_latest_resolution(
            casebook_public_root=CASEBOOK,
            expected_casebook_manifest_sha256="8e79fe8c86e08e60b693ca93f3ca6560476bec53a979c67ed8120d00ec121126",
            canonical_root=BASE / "canonical",
            expected_canonical_manifest_sha256="f9b94272242d7a40256a0eb6b5c18d4eb68b80564839ab59918c8356e44c20cd",
            canonical_receipt_path=BASE / "canonical-validation/receipt.json",
            expected_canonical_receipt_sha256="629aa310881101b68323c3f8c0ec6bd53f4e79ffb98503f99846d92c856a14e3",
            generated_at_utc="2026-07-19T00:00:00+00:00",
        )
        self.assertEqual(result["receipt"]["status"], "passed")
        self.assertEqual(result["receipt"]["resolution"]["resolved_canonical_post_ids"], 4)
        self.assertEqual(result["receipt"]["resolution"]["resolved_evidence_comment_ids"], 16)
        self.assertTrue(result["receipt"]["casebook"]["historical_content_preserved"])

    def test_rejects_wrong_canonical_hash(self) -> None:
        with self.assertRaisesRegex(CasebookResolutionError, "canonical manifest SHA-256 mismatch"):
            validate_latest_resolution(
                casebook_public_root=CASEBOOK,
                expected_casebook_manifest_sha256="8e79fe8c86e08e60b693ca93f3ca6560476bec53a979c67ed8120d00ec121126",
                canonical_root=BASE / "canonical",
                expected_canonical_manifest_sha256="0" * 64,
                canonical_receipt_path=BASE / "canonical-validation/receipt.json",
                expected_canonical_receipt_sha256="629aa310881101b68323c3f8c0ec6bd53f4e79ffb98503f99846d92c856a14e3",
                generated_at_utc="2026-07-19T00:00:00+00:00",
            )


if __name__ == "__main__":
    unittest.main()
