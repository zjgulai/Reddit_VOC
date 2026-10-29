import json
import unittest
from unittest.mock import MagicMock

from reddit_voc.agents import ContentScoutAgent, ContentScoutResult
from reddit_voc.report_contracts import TokenUsage


class ContentScoutAgentTests(unittest.TestCase):
    def test_scout_fallback_mode_generates_structured_topic_idea(self) -> None:
        agent = ContentScoutAgent(client=None)
        result = agent.scout(
            post_id="post_001",
            subreddit="r/ExclusivelyPumping",
            title="My wearable pump leaks every time I bend over",
            content="I am so sick of spilling liquid gold all over my desk.",
        )

        self.assertIsInstance(result, ContentScoutResult)
        self.assertEqual(result.source_post_id, "post_001")
        self.assertEqual(result.subreddit, "r/ExclusivelyPumping")
        self.assertGreaterEqual(len(result.ideas), 1)

        first_idea = result.ideas[0]
        self.assertEqual(first_idea.target_platform, "TikTok")
        self.assertIn("leak", first_idea.hook_3s.lower())
        self.assertGreater(len(first_idea.visual_scene_script), 0)
        self.assertTrue(first_idea.call_to_action)

    def test_scout_with_mocked_llm_client_parses_json_schema_correctly(self) -> None:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = json.dumps(
            {
                "ideas": [
                    {
                        "topic_id": "topic_test_1",
                        "target_platform": "Instagram Reels",
                        "target_audience": "职场背奶妈妈",
                        "core_pain_point": "吸奶噪音大",
                        "hook_3s": "Can people hear your pump on Zoom?",
                        "story_conflict": "在安静会议室偷吸奶的心虚时刻",
                        "solution_angle": "超静音马达分贝实测",
                        "call_to_action": "Comment below your quietest pump!",
                        "visual_scene_script": [
                            {
                                "scene_num": "1",
                                "visual": "正在开 Zoom 会议的职场女性眼神慌张",
                                "audio": "背景隐约的噗嗤噗嗤吸奶声",
                                "text_overlay": "POV: Your mic might be unmuted",
                            }
                        ],
                        "hashtags": ["#workingmom", "#pumpinghacks"],
                    }
                ],
                "reasoning_summary": "Zoom 会议静音吸奶是职场女性极具共鸣的隐秘痛点，画面感极佳。",
            }
        )
        mock_response.usage = TokenUsage(100, 50, 0, 100, 150)
        mock_client.complete_json.return_value = mock_response

        agent = ContentScoutAgent(client=mock_client)
        result = agent.scout(
            post_id="post_zoom_1",
            subreddit="r/breastfeeding",
            title="Is wearable pump quiet enough for zoom calls?",
            content="I have meetings all day and need to pump discreetly.",
        )

        self.assertEqual(result.source_post_id, "post_zoom_1")
        self.assertEqual(len(result.ideas), 1)
        self.assertEqual(result.ideas[0].topic_id, "topic_test_1")
        self.assertEqual(result.ideas[0].target_platform, "Instagram Reels")
        self.assertEqual(result.ideas[0].hook_3s, "Can people hear your pump on Zoom?")
        self.assertIn("Zoom 会议", result.reasoning_summary)


if __name__ == "__main__":
    unittest.main()
