import json
import unittest
from unittest.mock import MagicMock

from reddit_voc.agents import RndVocAgent, RndVocResult
from reddit_voc.report_contracts import TokenUsage


class RndVocAgentTests(unittest.TestCase):
    def test_analyze_fallback_mode_generates_defect_findings(self) -> None:
        agent = RndVocAgent(client=None)
        result = agent.analyze(
            post_id="post_rnd_001",
            subreddit="r/ExclusivelyPumping",
            title="Momcozy M5 leaking when leaning over",
            content="Every time I bend forward milk spills out of the top silicone seal.",
        )

        self.assertIsInstance(result, RndVocResult)
        self.assertEqual(result.source_post_id, "post_rnd_001")
        self.assertEqual(result.subreddit, "r/ExclusivelyPumping")
        self.assertGreaterEqual(len(result.defects), 1)

        first_defect = result.defects[0]
        self.assertEqual(first_defect.category, "sealing_leakage")
        self.assertIn("flange", first_defect.component.lower())
        self.assertIn("dual-lip", first_defect.suggested_action.lower())
        self.assertTrue(first_defect.root_cause_hypothesis)
        self.assertEqual(result.urgency_rating, "P1")

    def test_analyze_with_mocked_llm_client_parses_json_schema_correctly(self) -> None:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = json.dumps(
            {
                "defects": [
                    {
                        "defect_id": "defect_mock_1",
                        "category": "motor_noise",
                        "component": "micro diaphragm pump motor",
                        "severity": "major",
                        "symptom": "Loud mechanical clicking sound during suction cycle",
                        "root_cause_hypothesis": "Gear backlash inside gearbox due to tolerance stackup",
                        "suggested_action": "Tighten gear mesh tolerance and switch to self-lubricating POM gears",
                        "frequency_signal": "recurring",
                        "user_quote": "It started clicking loudly on day 4",
                        "user_workaround": "Putting a pillow over my chest",
                    }
                ],
                "engineering_summary": "齿轮啮合背隙导致的周期性异响故障，需优化齿轮箱公差。",
                "urgency_rating": "P2",
            }
        )
        mock_response.usage = TokenUsage(120, 60, 0, 120, 180)
        mock_client.complete_json.return_value = mock_response

        agent = RndVocAgent(client=mock_client)
        result = agent.analyze(
            post_id="post_click_01",
            subreddit="r/breastfeeding",
            title="Clicking sound inside wearable pump",
            content="My pump makes a weird clicking sound.",
        )

        self.assertEqual(result.source_post_id, "post_click_01")
        self.assertEqual(len(result.defects), 1)
        self.assertEqual(result.defects[0].defect_id, "defect_mock_1")
        self.assertEqual(result.defects[0].category, "motor_noise")
        self.assertEqual(result.defects[0].severity, "major")
        self.assertIn("公差", result.engineering_summary)
        self.assertEqual(result.urgency_rating, "P2")


if __name__ == "__main__":
    unittest.main()
