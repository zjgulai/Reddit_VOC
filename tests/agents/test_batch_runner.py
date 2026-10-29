import json
import tempfile
import unittest
from pathlib import Path

from reddit_voc.agents import AgentBatchRunner, BatchAgentOutput


class AgentBatchRunnerTests(unittest.TestCase):
    def test_run_batch_routes_posts_to_correct_agents(self) -> None:
        posts = [
            {
                "post_id": "post_leak_1",
                "subreddit": "r/ExclusivelyPumping",
                "title": "Severe milk leaking from valve",
                "selftext": "Every time I move the valve leaks.",
            },
            {
                "post_id": "post_vs_2",
                "subreddit": "r/breastfeeding",
                "title": "Momcozy M5 vs Elvie Stride review",
                "selftext": "Comparing Elvie and Momcozy pumps.",
            },
            {
                "post_id": "post_recommend_3",
                "subreddit": "r/WorkingMoms",
                "title": "Need recommend for quiet wearable pump for work office",
                "selftext": "What is worth it for working moms?",
            },
        ]

        runner = AgentBatchRunner(client=None)
        output = runner.run_batch(posts, run_id="test_run_001")

        self.assertIsInstance(output, BatchAgentOutput)
        self.assertEqual(output.run_id, "test_run_001")
        self.assertEqual(output.total_posts_analyzed, 3)

        # Defect agent should have captured leaking post
        self.assertGreaterEqual(len(output.rnd_voc_results), 1)
        self.assertEqual(output.rnd_voc_results[0].source_post_id, "post_leak_1")

        # Competitor radar should have captured Elvie post
        self.assertGreaterEqual(len(output.competitor_radar_results), 1)
        self.assertEqual(output.competitor_radar_results[0].source_post_id, "post_vs_2")

        # Content scout should have captured recommend post
        self.assertGreaterEqual(len(output.content_scout_results), 1)

    def test_persist_artifacts_creates_all_three_domain_files(self) -> None:
        posts = [
            {
                "post_id": "post_all_1",
                "subreddit": "r/ExclusivelyPumping",
                "title": "Momcozy vs Elvie leaking valve issue - is it worth it?",
                "selftext": "I need help with my Elvie comparison and leaky valve.",
            }
        ]
        runner = AgentBatchRunner(client=None)
        output = runner.run_batch(posts, run_id="run_persist_123")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            files = runner.persist_artifacts(output, tmp_path)

            self.assertIn("content_ideas", files)
            self.assertIn("rnd_tickets", files)
            self.assertIn("competitor_radar", files)

            # Check that files exist and contain valid JSON
            for key, file_path in files.items():
                self.assertTrue(file_path.exists())
                data = json.loads(file_path.read_text(encoding="utf-8"))
                self.assertEqual(data["run_id"], "run_persist_123")


if __name__ == "__main__":
    unittest.main()
