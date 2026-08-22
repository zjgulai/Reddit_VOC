import unittest

from reddit_voc.loop_engineering import DEFAULT_LOOP_COMPONENTS, loop_config_markdown


class LoopEngineeringTests(unittest.TestCase):
    def test_loop_has_five_components(self):
        self.assertEqual(
            [component.name for component in DEFAULT_LOOP_COMPONENTS],
            ["objective", "state", "policy", "executor", "evaluator"],
        )

    def test_loop_markdown_mentions_provider_gate(self):
        markdown = loop_config_markdown()
        self.assertIn("provider", markdown.lower())
        self.assertIn("live", markdown.lower())


if __name__ == "__main__":
    unittest.main()
