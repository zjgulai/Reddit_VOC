from pathlib import Path
import unittest

from reddit_voc.tag_dictionary import TagDictionary


ROOT = Path(__file__).resolve().parents[1]


class TagDictionaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dictionary = TagDictionary.from_csv(ROOT / "dim_tag_v6.3_final.csv")

    def test_governed_dictionary_loads_and_selects_pump_context(self):
        profile = self.dictionary.profile(product_line="吸奶器", voc_category="吸奶器")
        self.assertEqual(profile["row_count"], 2346)
        self.assertEqual(profile["base_context"]["eligible_rule_count"], 470)
        self.assertEqual(
            profile["supported_model_spu_aliases"],
            {"m5": "SPU001001001003016", "m9": "SPU000168"},
        )

    def test_unique_phrase_confirms_tag(self):
        result = self.dictionary.extract(
            "The battery lasts all day and still has charge.",
            product_line="吸奶器",
            voc_category="吸奶器",
        )
        self.assertIn("L0-GEN-003", result["tag_ids"])

    def test_shared_phrase_is_candidate_not_silent_choice(self):
        result = self.dictionary.extract(
            "It is easy to clean.",
            product_line="吸奶器",
            voc_category="吸奶器",
        )
        candidates = {
            item["keyword"]: item["candidate_tag_ids"]
            for item in result["ambiguous_keyword_matches"]
        }
        self.assertNotIn("L0-GEN-002", result["tag_ids"])
        self.assertEqual(
            candidates["easy to clean"],
            ["L0-GEN-002", "L1-PUMP-026", "L1-PUMP-029"],
        )

    def test_negated_phrase_is_not_confirmed(self):
        result = self.dictionary.extract(
            "It is not easy to assemble.",
            product_line="吸奶器",
            voc_category="吸奶器",
        )
        self.assertNotIn("L0-GEN-006", result["tag_ids"])
        self.assertTrue(
            any(
                item["keyword"] == "easy to assemble"
                for item in result["negated_keyword_matches"]
            )
        )

    def test_explicit_model_alias_enables_spu_rule(self):
        result = self.dictionary.extract(
            "My Momcozy M5 has flange ring aging after a few months.",
            product_line="吸奶器",
            voc_category="吸奶器",
        )
        self.assertEqual(
            result["context"]["detected_spu_ids"], ["SPU001001001003016"]
        )
        self.assertIn("L2S-003016-005", result["tag_ids"])

    def test_governed_empty_spu_set_disables_legacy_model_alias(self):
        result = self.dictionary.extract(
            "My Momcozy M5 has flange ring aging after a few months.",
            product_line="吸奶器",
            voc_category="吸奶器",
            spu_ids=(),
        )
        self.assertEqual(result["context"]["detected_spu_ids"], [])
        self.assertEqual(result["context"]["spu_binding_mode"], "governed_explicit")
        self.assertNotIn("L2S-003016-005", result["tag_ids"])

    def test_governed_multi_product_context_unions_approved_spu_rules(self):
        contexts = [
            ("吸奶器", "吸奶器", ["SPU000168"]),
            ("喂养电器", "消毒器", ["SPU000714"]),
        ]
        result = self.dictionary.extract_for_contexts(
            "The app connectivity is smooth, but it uses too much water per cycle.",
            contexts=contexts,
        )
        self.assertEqual(
            result["context"]["detected_spu_ids"],
            ["SPU000168", "SPU000714"],
        )
        self.assertIn("L2S-000168-001", result["tag_ids"])
        self.assertIn("L2S-000714-001", result["tag_ids"])
        executable_ids = {
            row["tag_id"]
            for row in self.dictionary.executable_dictionary_records_for_contexts(
                contexts
            )
        }
        self.assertIn("L2S-000168-001", executable_ids)
        self.assertIn("L2S-000714-001", executable_ids)

    def test_unbound_governed_context_is_l0_only(self):
        result = self.dictionary.extract_for_contexts(
            "The battery lasts all day and still has charge.",
            contexts=[],
        )
        expected_l0 = self.dictionary.select_rules(
            product_line="", voc_category="", spu_ids=()
        )
        self.assertEqual(result["eligible_rule_count"], len(expected_l0))
        self.assertEqual(result["context"]["contexts"][0]["product_line"], "")
        self.assertIn("L0-GEN-003", result["tag_ids"])

    def test_single_token_collision_is_review_candidate(self):
        result = self.dictionary.extract(
            "I charge the battery every day.",
            product_line="吸奶器",
            voc_category="吸奶器",
        )
        self.assertNotIn("L0-SVC-025", result["tag_ids"])
        self.assertTrue(
            any(
                item["keyword"] == "charge"
                and item["reason"] == "single_token_keyword"
                for item in result["low_specificity_keyword_matches"]
            )
        )

    def test_brand_tag_requires_real_brand_alias(self):
        generic = self.dictionary.extract(
            "I also need a baby carrier.",
            product_line="吸奶器",
            voc_category="吸奶器",
        )
        branded = self.dictionary.extract(
            "I use a Spectra pump.",
            product_line="吸奶器",
            voc_category="吸奶器",
        )
        self.assertNotIn("L0-BRD-001", generic["tag_ids"])
        self.assertIn("L0-BRD-015", branded["tag_ids"])
        self.assertIn("L0-BRD-015", branded["brand_tag_ids"])
        self.assertNotIn("L0-BRD-015", branded["aspect_tag_ids"])


if __name__ == "__main__":
    unittest.main()
