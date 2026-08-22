from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from reddit_voc.product_entity_resolution import ProductEntityResolver


ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = (
    ROOT
    / "config"
    / "product_entities"
    / "momcozy-product-entity-ledger-v1.json"
)


class ProductEntityResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.resolver = ProductEntityResolver.from_ledger(LEDGER_PATH)

    def test_metadata_records_resolver_ledger_version_and_file_sha(self) -> None:
        metadata = self.resolver.metadata

        self.assertEqual(metadata.resolver_version, "product-entity-resolver-v1")
        self.assertEqual(
            metadata.ledger_version,
            "momcozy-product-entity-ledger-2026-07-15.v1",
        )
        self.assertEqual(
            metadata.ledger_sha256,
            hashlib.sha256(LEDGER_PATH.read_bytes()).hexdigest(),
        )

    def test_naked_ambiguous_model_tokens_do_not_bind(self) -> None:
        for text in ("M5", "M6", "M9", "V2", "BM03"):
            with self.subTest(text=text):
                result = self.resolver.resolve(text)
                self.assertEqual(result.product_bindings, ())

    def test_momcozy_governed_category_without_model_binds_category_only(self) -> None:
        result = self.resolver.resolve("Momcozy breast pump")

        self.assertEqual(len(result.product_bindings), 1)
        binding = result.product_bindings[0]
        self.assertEqual(binding.category.entity_id, "breast_pump")
        self.assertIsNone(binding.product_family)
        self.assertIsNone(binding.exact_spu)
        self.assertEqual(binding.binding_level, "category")
        self.assertEqual(binding.governance_status, "category_only")
        self.assertEqual(binding.match_type, "category_context")
        self.assertIsNone(binding.governance_reason)

    def test_competitor_or_unsupported_momcozy_category_does_not_bind(self) -> None:
        for text in ("breast pump", "Spectra breast pump", "Momcozy stroller"):
            with self.subTest(text=text):
                self.assertEqual(self.resolver.resolve(text).product_bindings, ())

    def test_category_only_requires_brand_and_category_in_same_controlled_domain(self) -> None:
        cases = (
            "Momcozy stroller. Spectra breast pump",
            f"Momcozy {'unrelated ' * 20}breast pump",
        )

        for text in cases:
            with self.subTest(case=len(text)):
                self.assertEqual(self.resolver.resolve(text).product_bindings, ())

    def test_nearest_governed_brand_owns_category_in_mixed_brand_domain(self) -> None:
        competitor_only = self.resolver.resolve(
            "Momcozy stroller and Spectra breast pump"
        )
        mixed = self.resolver.resolve(
            "Momcozy breast pump and Spectra bottle washer"
        )

        self.assertEqual(competitor_only.product_bindings, ())
        self.assertEqual(
            [binding.category.entity_id for binding in mixed.product_bindings],
            ["breast_pump"],
        )

    def test_one_momcozy_domain_can_bind_multiple_governed_categories(self) -> None:
        result = self.resolver.resolve(
            "Momcozy breast pump, bottle washer, and baby monitor"
        )

        self.assertEqual(
            [binding.category.entity_id for binding in result.product_bindings],
            ["breast_pump", "bottle_washer", "baby_monitor"],
        )
        self.assertTrue(
            all(binding.product_family is None for binding in result.product_bindings)
        )
        self.assertTrue(
            all(binding.binding_level == "category" for binding in result.product_bindings)
        )

    def test_family_binding_suppresses_duplicate_category_only_binding(self) -> None:
        result = self.resolver.resolve("Momcozy M6 breast pump")

        self.assertEqual(len(result.product_bindings), 1)
        binding = result.product_bindings[0]
        self.assertIsNotNone(binding.product_family)
        assert binding.product_family is not None
        self.assertEqual(binding.product_family.entity_id, "m6-mobile-style")
        self.assertEqual(binding.binding_level, "spu_exact")

    def test_contextual_model_tokens_bind_with_brand_or_product_context(self) -> None:
        cases = (
            ("My Momcozy M6 arrived.", "m6-mobile-style", "SPU000167"),
            ("The M9 breast pump is compact.", "m9-mobile-flow", "SPU000168"),
            ("This V2 wearable pump is light.", "v2-pro", "SPU000932"),
        )

        for text, family_id, spu_id in cases:
            with self.subTest(family_id=family_id):
                binding = self.resolver.resolve(text).product_bindings[0]
                self.assertEqual(binding.category.entity_id, "breast_pump")
                self.assertIsNotNone(binding.product_family)
                assert binding.product_family is not None
                self.assertEqual(binding.product_family.entity_id, family_id)
                self.assertIsNotNone(binding.exact_spu)
                assert binding.exact_spu is not None
                self.assertEqual(binding.exact_spu.spu_id, spu_id)
                self.assertEqual(binding.binding_level, "spu_exact")
                self.assertEqual(binding.match_type, "contextual_alias")

    def test_strong_full_name_binds_without_separate_brand_context(self) -> None:
        result = self.resolver.resolve(
            "V2 Pro Hospital-Grade Wearable Breast Pump is ultra-light."
        )

        binding = result.product_bindings[0]
        self.assertIsNotNone(binding.product_family)
        assert binding.product_family is not None
        self.assertEqual(binding.product_family.entity_id, "v2-pro")
        self.assertIsNotNone(binding.exact_spu)
        assert binding.exact_spu is not None
        self.assertEqual(binding.exact_spu.spu_id, "SPU000932")
        self.assertEqual(binding.match_type, "strong_name")

    def test_all_publishable_verified_mappings_resolve_to_exact_spu(self) -> None:
        cases = (
            ("Momcozy M6", "m6-mobile-style", "SPU000167"),
            ("Momcozy M9", "m9-mobile-flow", "SPU000168"),
            ("Momcozy V2 Pro", "v2-pro", "SPU000932"),
            ("Momcozy Air 1 breast pump", "air-1", "SPU000209"),
            (
                "Momcozy KleanPal Pro bottle washer",
                "kleanpal-pro",
                "SPU000714",
            ),
        )

        for text, family_id, spu_id in cases:
            with self.subTest(family_id=family_id):
                binding = self.resolver.resolve(text).product_bindings[0]
                self.assertIsNotNone(binding.product_family)
                assert binding.product_family is not None
                self.assertEqual(binding.product_family.entity_id, family_id)
                self.assertIsNotNone(binding.exact_spu)
                assert binding.exact_spu is not None
                self.assertEqual(binding.exact_spu.spu_id, spu_id)
                if family_id == "m6-mobile-style":
                    self.assertEqual(binding.exact_spu.spu_name, "M6 吸奶器")
                self.assertIsNone(binding.governance_reason)

    def test_bm03_taxonomy_drift_blocks_exact_spu_publication(self) -> None:
        result = self.resolver.resolve("Momcozy BM03 baby monitor")

        binding = result.product_bindings[0]
        self.assertEqual(binding.category.entity_id, "baby_monitor")
        self.assertIsNotNone(binding.product_family)
        assert binding.product_family is not None
        self.assertEqual(binding.product_family.entity_id, "bm03-video-monitor")
        self.assertIsNone(binding.exact_spu)
        self.assertEqual(binding.binding_level, "product_family")
        self.assertEqual(
            binding.governance_reason,
            "taxonomy_drift_dictionary_temperature_vs_baby_monitor",
        )

    def test_m5_stays_family_only_even_with_clear_context(self) -> None:
        binding = self.resolver.resolve(
            "Momcozy M5 Smart wearable breast pump"
        ).product_bindings[0]

        self.assertIsNotNone(binding.product_family)
        assert binding.product_family is not None
        self.assertEqual(binding.product_family.entity_id, "m5-smart")
        self.assertIsNone(binding.exact_spu)
        self.assertEqual(binding.binding_level, "product_family")
        self.assertEqual(
            binding.governance_reason,
            "smart_variant_not_explicit_in_internal_spu",
        )

    def test_ambiguous_s9_s12_and_v1_stay_family_only(self) -> None:
        cases = (
            ("Momcozy S9 Pro wearable pump", "s9-pro"),
            ("Momcozy S12 Pro Quick wearable pump", "s12-pro-quick"),
            ("Momcozy V1 Pro wearable pump", "v1-pro"),
        )

        for text, family_id in cases:
            with self.subTest(family_id=family_id):
                binding = self.resolver.resolve(text).product_bindings[0]
                self.assertIsNotNone(binding.product_family)
                assert binding.product_family is not None
                self.assertEqual(binding.product_family.entity_id, family_id)
                self.assertIsNone(binding.exact_spu)
                self.assertEqual(binding.binding_level, "product_family")
                self.assertIsNotNone(binding.governance_reason)
                assert binding.governance_reason is not None
                self.assertIn("multiple_internal", binding.governance_reason)

    def test_multi_product_text_produces_multiple_deduplicated_bindings(self) -> None:
        result = self.resolver.resolve(
            "I compare the Momcozy Mobile Style M6 and Momcozy Mobile Flow M9 pumps."
        )

        family_ids: list[str] = []
        exact_spu_ids: list[str] = []
        for item in result.product_bindings:
            self.assertIsNotNone(item.product_family)
            assert item.product_family is not None
            family_ids.append(item.product_family.entity_id)
            self.assertIsNotNone(item.exact_spu)
            assert item.exact_spu is not None
            exact_spu_ids.append(item.exact_spu.spu_id)
        self.assertEqual(family_ids, ["m6-mobile-style", "m9-mobile-flow"])
        self.assertEqual(exact_spu_ids, ["SPU000167", "SPU000168"])
        self.assertTrue(all(item.match_type == "strong_name" for item in result.product_bindings))

    def test_batch_coverage_ledger_is_conserved(self) -> None:
        batch = self.resolver.resolve_many(
            (
                "Momcozy M6 and M9 breast pumps",
                "M5",
                "Momcozy BM03 baby monitor",
                "KleanPal Pro Baby Bottle Washer",
                "Momcozy breast pump",
            )
        )

        coverage = batch.coverage
        self.assertEqual(coverage.input_record_count, 5)
        self.assertEqual(coverage.bound_record_count, 4)
        self.assertEqual(coverage.unbound_record_count, 1)
        self.assertEqual(coverage.multi_binding_record_count, 1)
        self.assertEqual(coverage.binding_count, 5)
        self.assertEqual(coverage.exact_spu_binding_count, 3)
        self.assertEqual(coverage.family_only_binding_count, 1)
        self.assertEqual(coverage.category_only_binding_count, 1)
        self.assertEqual(coverage.taxonomy_blocked_binding_count, 1)
        self.assertEqual(
            dict(coverage.category_binding_counts),
            {"baby_monitor": 1, "bottle_washer": 1, "breast_pump": 3},
        )
        self.assertEqual(
            dict(coverage.family_binding_counts),
            {
                "bm03-video-monitor": 1,
                "kleanpal-pro": 1,
                "m6-mobile-style": 1,
                "m9-mobile-flow": 1,
            },
        )
        self.assertTrue(coverage.is_conserved)
        batch_record = batch.to_record()
        batch_coverage = batch_record["coverage"]
        self.assertIsInstance(batch_coverage, dict)
        assert isinstance(batch_coverage, dict)
        self.assertTrue(batch_coverage["is_conserved"])

    def test_resolution_output_does_not_repeat_source_text(self) -> None:
        source_text = "Momcozy M9 private free-form source text"
        record = self.resolver.resolve(source_text).to_record()

        self.assertNotIn(source_text, json.dumps(record, ensure_ascii=False))
        self.assertIn("product_bindings", record)
        record_metadata = record["metadata"]
        self.assertIsInstance(record_metadata, dict)
        assert isinstance(record_metadata, dict)
        self.assertEqual(
            record_metadata["ledger_sha256"],
            self.resolver.metadata.ledger_sha256,
        )

    def test_exact_spu_cannot_be_smuggled_through_family_definition(self) -> None:
        payload = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
        payload["families"][0]["exact_spu"] = {
            "spu_id": "SPU-NOT-APPROVED"
        }

        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "invalid-ledger.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsupported family fields"):
                ProductEntityResolver.from_ledger(path)

    def test_blocked_mapping_cannot_be_marked_publishable(self) -> None:
        payload = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
        blocked = next(
            item
            for item in payload["exact_spu_ledger"]
            if item["family_id"] == "bm03-video-monitor"
        )
        blocked["publish_exact_spu"] = True

        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "invalid-ledger.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError,
                "publishable exact SPU requires approved_for_publication",
            ):
                ProductEntityResolver.from_ledger(path)


if __name__ == "__main__":
    unittest.main()
