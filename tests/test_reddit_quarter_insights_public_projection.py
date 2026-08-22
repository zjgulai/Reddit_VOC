from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from reddit_voc.v3_integrity_snapshot import canonical_json_document
from reddit_voc.v3_quarter_insights_public import (
    QuarterInsightsPublicProjectionError,
    _analysis_for_record,
    build_public_projection,
    validate_public_projection,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tmp/reddit-voc-v3/reddit_add_data_20260715_v1"
CASEBOOK_PUBLIC = (
    ROOT
    / "ref/UI/momcozy-reddit-workbench/public/data/reddit-voc"
    / "reddit_voc_casebook_20260716_public_a1"
)
PRODUCT_LEDGER = ROOT / "config/product_entities/momcozy-product-entity-ledger-v1.json"
EXPECTED_HASHES = {
    "canonical_manifest": "36bbc15074437ab0b48732200a50a3356091391175e565f4e9769122ece2c1ce",
    "canonical_receipt": "9f7af1b27ae697b9e33b554dc4bca9dfa365366f66f3dc0fd5a944848001b4c2",
    "voc_manifest": "4a0b43f664cc8bd2cf0fbd63d0428aaeadec1a6b405a066123250e4f90675b77",
    "voc_receipt": "ff6ee119c5861cfad50d256caebaf3600564013b6069b97d047e9197c90eb61f",
    "governed_manifest": "44c66b198f3dc33873036912c239f89d28fabe36ed2aaacc5662c7686dd4c24a",
    "governed_receipt": "135d9f4a78dd772f5feae193783d98f78969d8b68d3cf6bf2b368f6fee98d9db",
    "persona_manifest": "bc366c0579029e8e1afb3705d8a3865d15cbdff5948634519abc43ea77a6c72b",
    "persona_receipt": "784e8b1cfd35368f3407a0cc2d22281c93afa89e6e288ac890f581dda8830816",
    "casebook_public_manifest": "8e79fe8c86e08e60b693ca93f3ca6560476bec53a979c67ed8120d00ec121126",
    "product_ledger": "cc66f565d64c19d0624baf9821ff4e765c692c8d85b8a4d7368214ab555451ab",
}


class QuarterInsightsPublicProjectionTests(unittest.TestCase):
    def test_preserves_existing_classified_analysis(self) -> None:
        existing = {
            "sentiment_label": "positive",
            "sentiment_score": 0.9,
            "topic": "product_evaluation",
        }
        self.assertEqual(
            _analysis_for_record({"title": "broken", "analysis": existing}, "post"),
            existing,
        )

    def test_classifies_incremental_rows_without_optional_analysis(self) -> None:
        post = _analysis_for_record(
            {"title": "Momcozy pump is broken", "content": "It hurts and leaks"},
            "post",
        )
        comment = _analysis_for_record({"body": "This works great and I love it"}, "comment")

        self.assertEqual(post["sentiment_label"], "negative")
        self.assertEqual(comment["sentiment_label"], "positive")
        self.assertEqual(post["analysis_version"], "local_rules_v1")
        self.assertFalse(post["provider_call"])

    def _build(self, output: Path) -> dict[str, object]:
        return build_public_projection(
            source_root=SOURCE,
            casebook_public_root=CASEBOOK_PUBLIC,
            product_ledger_path=PRODUCT_LEDGER,
            expected_hashes=EXPECTED_HASHES,
            output_root=output,
        )

    def test_builds_and_validates_governed_quarter_projection(self) -> None:
        with TemporaryDirectory() as temporary:
            output = Path(temporary)
            built = self._build(output)
            validated = validate_public_projection(
                output_root=output,
                expected_manifest_sha256=str(built["manifest_sha256"]),
            )
            data = json.loads((output / "quarter-insights.json").read_text(encoding="utf-8"))

            self.assertEqual(validated["status"], "passed")
            self.assertEqual(data["period"], {
                "anchor_date": "2026-07-15",
                "days": 90,
                "end_date": "2026-07-15",
                "inclusive": True,
                "start_date": "2026-04-17",
                "timezone": "Asia/Shanghai",
            })
            self.assertEqual(data["counts"]["momcozy"]["total_vocs"], 1708)
            self.assertEqual(data["counts"]["momcozy"]["sentiment"]["negative_rate"], 6.44)
            self.assertEqual(data["themes"]["reputation"]["automation_comments"], 306)
            self.assertEqual(data["themes"]["reputation"]["quarter_moderation_claim_evidence_count"], 1)
            self.assertEqual(len(data["personas"]["main_assignment_ids"]), 369)
            self.assertEqual(data["personas"]["main_unique_entities"], 226)
            exact_spus = {row["id"]: row["count"] for row in data["themes"]["new_product"]["exact_spu_rankings"]}
            self.assertEqual(exact_spus["SPU000167"], 73)
            self.assertNotIn("m5-smart", exact_spus)
            self.assertEqual([item["id"] for item in data["dashboard_windows"]], [
                "rolling_7_days", "rolling_30_days", "rolling_183_days"
            ])
            serialized = json.dumps(data, ensure_ascii=False)
            for forbidden in ('"author"', '"body"', '"content"', '"entity_id"', "https://", "/Users/"):
                self.assertNotIn(forbidden, serialized)

    def test_rejects_a_wrong_pinned_source_hash(self) -> None:
        with TemporaryDirectory() as temporary:
            hashes = dict(EXPECTED_HASHES)
            hashes["governed_manifest"] = "0" * 64
            with self.assertRaisesRegex(QuarterInsightsPublicProjectionError, "source manifest SHA-256 mismatch"):
                build_public_projection(
                    source_root=SOURCE,
                    casebook_public_root=CASEBOOK_PUBLIC,
                    product_ledger_path=PRODUCT_LEDGER,
                    expected_hashes=hashes,
                    output_root=Path(temporary),
                )

    def test_semantic_validator_rejects_a_rehashed_count_tamper(self) -> None:
        with TemporaryDirectory() as temporary:
            output = Path(temporary)
            self._build(output)
            data_path = output / "quarter-insights.json"
            data = json.loads(data_path.read_text(encoding="utf-8"))
            data["themes"]["reputation"]["automation_comments"] = 305
            data_payload = canonical_json_document(data)
            data_path.write_bytes(data_payload)

            manifest_path = output / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"]["quarter-insights.json"] = {
                "bytes": len(data_payload),
                "media_type": "application/json",
                "sha256": sha256(data_payload).hexdigest(),
            }
            manifest_payload = canonical_json_document(manifest)
            manifest_path.write_bytes(manifest_payload)

            with self.assertRaisesRegex(
                QuarterInsightsPublicProjectionError,
                "reputation counts do not reconcile",
            ):
                validate_public_projection(
                    output_root=output,
                    expected_manifest_sha256=sha256(manifest_payload).hexdigest(),
                )


if __name__ == "__main__":
    unittest.main()
