import json
import unittest
from unittest.mock import patch

from reddit_voc.analyzer import DeepSeekAnalysisItem, analyze_batch_with_deepseek, analyze_text
from reddit_voc.keywords import match_keywords


class KeywordAnalyzerTests(unittest.TestCase):
    def test_deepseek_batch_ignores_unknown_and_duplicate_provider_ids(self):
        provider_payload = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "results": [
                            {"id": "rogue", "sentiment": "negative"},
                            {"id": "post:1", "sentiment": "positive", "sentiment_score": 0.8, "topic": "product_evaluation", "severity": "low", "pain_points": []},
                            {"id": "post:1", "sentiment": "negative", "sentiment_score": -1, "topic": "other", "severity": "high", "pain_points": ["health"]},
                        ]
                    })
                }
            }]
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(provider_payload).encode("utf-8")

        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "fixture-key"}), patch(
            "reddit_voc.analyzer.urlopen", return_value=FakeResponse()
        ):
            results = analyze_batch_with_deepseek([
                DeepSeekAnalysisItem(item_id="post:1", text="works well"),
            ])

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].item_id, "post:1")
        self.assertEqual(results[0].sentiment_label, "positive")

    def test_momcozy_model_with_pump_context_matches(self):
        match = match_keywords("Momcozy M5 wearable pump vs eufy S1 Pro")
        self.assertTrue(match.is_relevant)
        self.assertIn("Momcozy", match.brands)
        self.assertIn("M5", match.products)
        self.assertIn("eufy", match.competitors)

    def test_model_false_positive_is_excluded(self):
        match = match_keywords("BMW M5 is not a breast pump")
        self.assertTrue(match.excluded)
        self.assertFalse(match.is_relevant)

    def test_analyzer_detects_negative_support_pain(self):
        analysis = analyze_text("The pump keeps leaking and customer service refused a refund.")
        self.assertEqual(analysis.sentiment_label, "negative")
        self.assertEqual(analysis.severity, "high")
        self.assertIn("leakage", analysis.pain_points)
        self.assertIn("support", analysis.pain_points)

    def test_bottle_washer_product_line_matches(self):
        match = match_keywords("KleanPal bottle washer vs Baby Brezza Washer Pro for pump parts")
        self.assertTrue(match.is_relevant)
        self.assertIn("KleanPal", match.products)
        self.assertIn("bottle washer", match.categories)
        self.assertIn("Baby Brezza", match.competitors)

    def test_contextual_baby_gear_term_requires_brand_product_or_competitor(self):
        generic = match_keywords("Which high chair is easiest to clean?")
        self.assertFalse(generic.is_relevant)

        branded = match_keywords("Momcozy DinerPal high chair looks easier to clean than Graco.")
        self.assertTrue(branded.is_relevant)
        self.assertIn("DinerPal", branded.products)
        self.assertIn("high chair", branded.categories)
        self.assertIn("Graco", branded.competitors)

    def test_analyzer_detects_family_scenario_and_operations(self):
        analysis = analyze_text("NICU twins made me need replacement parts and better charging.")
        self.assertIn("family_scenario", analysis.pain_points)
        self.assertIn("operations", analysis.pain_points)


if __name__ == "__main__":
    unittest.main()
