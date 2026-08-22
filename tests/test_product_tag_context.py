from pathlib import Path
import unittest

from reddit_voc.product_entity_resolution import ProductEntityResolver
from reddit_voc.product_tag_context import (
    ProductTagContextError,
    tag_contexts_from_product_bindings,
)


ROOT = Path(__file__).resolve().parents[1]


class ProductTagContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.resolver = ProductEntityResolver.from_ledger(
            ROOT / "config/product_entities/momcozy-product-entity-ledger-v1.json"
        )

    def _contexts(self, text: str):
        result = self.resolver.resolve(text)
        return tag_contexts_from_product_bindings(
            binding.to_record() for binding in result.product_bindings
        )

    def test_multiple_approved_products_map_to_explicit_spu_contexts(self) -> None:
        self.assertEqual(
            self._contexts(
                "Momcozy M9 Mobile Flow Hands-Free Breast Pump and "
                "Momcozy KleanPal Pro Baby Bottle Washer"
            ),
            (
                ("吸奶器", "吸奶器", ("SPU000168",)),
                ("喂养电器", "消毒器", ("SPU000714",)),
            ),
        )

    def test_family_only_m5_never_reactivates_legacy_dictionary_spu(self) -> None:
        self.assertEqual(
            self._contexts("Momcozy M5 Smart Wearable Breast Pump"),
            (("吸奶器", "吸奶器", ()),),
        )

    def test_bm03_taxonomy_drift_uses_safe_non_dictionary_category(self) -> None:
        self.assertEqual(
            self._contexts("Momcozy 5.5-inch Full HD Video Baby Monitor BM03"),
            (("智能母婴电器", "婴儿监视器", ()),),
        )

    def test_category_only_binding_enables_category_without_spu(self) -> None:
        self.assertEqual(
            self._contexts("Momcozy breast pump"),
            (("吸奶器", "吸奶器", ()),),
        )

    def test_malformed_exact_spu_governance_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            ProductTagContextError, "exact_spu_governance_invalid"
        ):
            tag_contexts_from_product_bindings(
                [
                    {
                        "brand_id": "momcozy",
                        "category": {"id": "breast_pump"},
                        "binding_level": "spu_exact",
                        "governance_status": "taxonomy_blocked",
                        "product_family": {"id": "fixture"},
                        "exact_spu": {"spu_id": "SPU000176"},
                    }
                ]
            )


if __name__ == "__main__":
    unittest.main()
