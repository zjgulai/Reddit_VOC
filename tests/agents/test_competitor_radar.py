import json
import unittest
from unittest.mock import MagicMock

from reddit_voc.agents import CompetitorComparison, CompetitorRadarAgent, CompetitorRadarResult
from reddit_voc.report_contracts import TokenUsage


class CompetitorRadarAgentTests(unittest.TestCase):
    def test_analyze_fallback_mode_generates_competitor_comparison(self) -> None:
        agent = CompetitorRadarAgent(client=None)
        result = agent.analyze(
            post_id="post_comp_001",
            subreddit="r/ExclusivelyPumping",
            title="Momcozy M5 vs Elvie Stride - my 3 month review",
            content="I used both Elvie and Momcozy. Momcozy empties me faster, Elvie is quieter.",
        )

        self.assertIsInstance(result, CompetitorRadarResult)
        self.assertEqual(result.source_post_id, "post_comp_001")
        self.assertEqual(result.subreddit, "r/ExclusivelyPumping")
        self.assertGreaterEqual(len(result.comparisons), 1)

        first_comp = result.comparisons[0]
        self.assertEqual(first_comp.competitor_brand, "Elvie")
        self.assertEqual(first_comp.our_product, "Momcozy M5")
        self.assertTrue(first_comp.our_advantage)
        self.assertTrue(first_comp.our_disadvantage)
        self.assertGreaterEqual(len(result.positioning_advice), 1)

    def test_analyze_with_mocked_llm_client_parses_json_schema_correctly(self) -> None:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = json.dumps(
            {
                "comparisons": [
                    {
                        "comparison_id": "comp_mock_1",
                        "competitor_brand": "Willow",
                        "competitor_model": "Willow 3.0",
                        "our_product": "Momcozy M5",
                        "dimension": "cost_and_bags",
                        "our_advantage": "No expensive proprietary milk bags required; reuseable cups save money",
                        "our_disadvantage": "Willow supports 360-degree leak-free lying down",
                        "sentiment_verdict": "prefer_momcozy",
                        "user_verbatim_quote": "Willow bags cost a fortune, Momcozy saves my wallet",
                    }
                ],
                "market_takeaway": "耗材成本是用户从 Willow 转向 Momcozy 的核心催化剂。",
                "positioning_advice": [
                    "在营销中持续放大 'Zero Ongoing Bag Costs' 的总体拥有成本优势。"
                ],
            }
        )
        mock_response.usage = TokenUsage(130, 70, 0, 130, 200)
        mock_client.complete_json.return_value = mock_response

        agent = CompetitorRadarAgent(client=mock_client)
        result = agent.analyze(
            post_id="post_willow_01",
            subreddit="r/breastfeeding",
            title="Willow bags are too expensive, switching to Momcozy",
            content="I cannot afford 50 cents per bag with Willow anymore.",
        )

        self.assertEqual(result.source_post_id, "post_willow_01")
        self.assertEqual(len(result.comparisons), 1)
        self.assertEqual(result.comparisons[0].competitor_brand, "Willow")
        self.assertEqual(result.comparisons[0].sentiment_verdict, "prefer_momcozy")
        self.assertIn("耗材成本", result.market_takeaway)


if __name__ == "__main__":
    unittest.main()
