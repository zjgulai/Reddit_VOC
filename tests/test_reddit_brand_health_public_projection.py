import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from reddit_voc.v3_brand_health_public import (
    BrandHealthPublicProjectionError,
    build_public_projection,
    validate_public_projection,
)
from reddit_voc.v3_integrity_snapshot import canonical_json_document


ROOT = Path(__file__).resolve().parents[1]
METRICS_ROOT = ROOT / "tmp/reddit-voc-v3/reddit_add_data_20260715_v1/metrics-candidate-a4"
RECEIPT = ROOT / "tmp/reddit-voc-v3/reddit_add_data_20260715_v1/metrics-validation-a4/receipt.json"
METRICS_MANIFEST_SHA = "1ab1c634f225f98d36025d5b1744c628d4dac8f90234eac60d4d83698751dec7"
RECEIPT_SHA = "b7d01c57cd85342f1eafc35d1daed91a39f91dd85e2c7aa89761673078641c85"
A5_METRICS_ROOT = ROOT / "tmp/reddit-voc-v3/reddit_add_data_20260715_v1/metrics-candidate-a5"
A5_RECEIPT = ROOT / "tmp/reddit-voc-v3/reddit_add_data_20260715_v1/metrics-validation-a5/receipt.json"
A5_METRICS_MANIFEST_SHA = "818f7eae762756eacd2b7605088cbdc900c7c28e18baada3a5da94674de86c4b"
A5_RECEIPT_SHA = "0c04c3786afaaff04fd994f8ed3b632c2db953861eeac9c0d4e53d1d099107b1"


class BrandHealthPublicProjectionTests(unittest.TestCase):
    def _build(self, output: Path) -> dict[str, object]:
        return build_public_projection(
            metrics_root=METRICS_ROOT,
            expected_metrics_manifest_sha256=METRICS_MANIFEST_SHA,
            receipt_path=RECEIPT,
            expected_receipt_sha256=RECEIPT_SHA,
            output_root=output,
            projection_id="reddit_voc_brand_health_20260716_public_a1",
        )

    def test_projects_only_governed_scores_and_preserves_unavailable_total(self) -> None:
        with TemporaryDirectory() as temporary:
            output = Path(temporary)
            result = self._build(output)
            validation = validate_public_projection(
                output_root=output,
                expected_manifest_sha256=str(result["manifest_sha256"]),
            )
            data = json.loads((output / "brand-health.json").read_text(encoding="utf-8"))

            self.assertEqual(validation["status"], "passed")
            self.assertEqual([item["score"] for item in data["dimensions"]], [None, 100.0, 50.41, None])
            self.assertEqual(data["overall"], {
                "reason_codes": [
                    "reputation:comment_context_voc:classification_coverage_below_80_percent",
                    "reputation:post_voc:classification_coverage_below_80_percent",
                    "risk_resilience:comment_context_voc:classification_coverage_below_80_percent",
                    "risk_resilience:comment_context_voc:classified_sample_below_10",
                    "risk_resilience:post_voc:classification_coverage_below_80_percent",
                    "risk_resilience:post_voc:classified_sample_below_10",
                ],
                "score": None,
                "status": "unavailable",
            })
            serialized = json.dumps(data, ensure_ascii=False)
            self.assertNotIn("included_entity_ids", serialized)
            self.assertNotIn("denominator_member_ids", serialized)
            self.assertNotIn('"author"', serialized)

    def test_rejects_an_axis_average_injected_as_the_total(self) -> None:
        with TemporaryDirectory() as temporary:
            output = Path(temporary)
            result = self._build(output)
            data_path = output / "brand-health.json"
            data = json.loads(data_path.read_text(encoding="utf-8"))
            data["overall"] = {"reason_codes": [], "score": 75.21, "status": "available"}
            payload = canonical_json_document(data)
            data_path.write_bytes(payload)
            manifest_path = output / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            from hashlib import sha256
            manifest["files"]["brand-health.json"] = {
                "bytes": len(payload),
                "media_type": "application/json",
                "sha256": sha256(payload).hexdigest(),
            }
            manifest_payload = canonical_json_document(manifest)
            manifest_path.write_bytes(manifest_payload)

            with self.assertRaisesRegex(BrandHealthPublicProjectionError, "overall"):
                validate_public_projection(
                    output_root=output,
                    expected_manifest_sha256=sha256(manifest_payload).hexdigest(),
                )

    def test_rejects_wrong_source_hash(self) -> None:
        with TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(BrandHealthPublicProjectionError, "metrics manifest SHA-256 mismatch"):
                build_public_projection(
                    metrics_root=METRICS_ROOT,
                    expected_metrics_manifest_sha256="0" * 64,
                    receipt_path=RECEIPT,
                    expected_receipt_sha256=RECEIPT_SHA,
                    output_root=Path(temporary),
                    projection_id="reddit_voc_brand_health_20260716_public_a1",
                )

    def test_projects_a5_provisional_total_and_all_four_dimensions(self) -> None:
        with TemporaryDirectory() as temporary:
            output = Path(temporary)
            result = build_public_projection(
                metrics_root=A5_METRICS_ROOT,
                expected_metrics_manifest_sha256=A5_METRICS_MANIFEST_SHA,
                receipt_path=A5_RECEIPT,
                expected_receipt_sha256=A5_RECEIPT_SHA,
                output_root=output,
                projection_id="reddit_voc_brand_health_20260716_public_a5",
            )
            validation = validate_public_projection(
                output_root=output,
                expected_manifest_sha256=str(result["manifest_sha256"]),
            )
            data = json.loads((output / "brand-health.json").read_text(encoding="utf-8"))

            self.assertEqual(validation["status"], "passed")
            self.assertEqual(data["overall"], {
                "reason_codes": [
                    "reputation:comment_context_voc:classification_coverage_below_90_percent",
                    "reputation:post_voc:classification_coverage_below_90_percent",
                    "risk_resilience:comment_context_voc:classification_coverage_below_90_percent",
                    "risk_resilience:post_voc:classification_coverage_below_90_percent",
                ],
                "score": 72.37,
                "status": "provisional",
            })
            self.assertEqual(
                [(item["dimension_id"], item["score"], item["status"]) for item in data["dimensions"]],
                [
                    ("reputation", 56.75, "provisional"),
                    ("product_experience", 99.93, "available"),
                    ("recommendation_trust", 50.41, "available"),
                    ("risk_resilience", 82.36, "provisional"),
                ],
            )
            serialized = json.dumps(data, ensure_ascii=False)
            self.assertNotIn("member_ids", serialized)
            self.assertNotIn('"author"', serialized)


if __name__ == "__main__":
    unittest.main()
