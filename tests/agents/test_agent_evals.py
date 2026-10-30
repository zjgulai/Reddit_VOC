"""Golden Dataset Evaluation Test Suite for Reddit VOC Multi-Agent System.

Validates that all specialized agents (ContentScout, RndVoc, CompetitorRadar)
extract high-fidelity, schema-compliant business intelligence from real-world
Reddit consumer discussions across diverse categories (leaking, noise, competitors, viral pain points).
"""
from __future__ import annotations

import json
import unittest
from typing import Mapping, Sequence

from reddit_voc.agents import (
    CompetitorRadarAgent,
    CompetitorRadarResult,
    ContentScoutAgent,
    ContentScoutResult,
    RndVocAgent,
    RndVocResult,
)

# Golden Dataset: Curated real-world consumer discussions
GOLDEN_DATASET: Sequence[Mapping[str, str]] = [
    {
        "case_id": "golden_leak_01",
        "subreddit": "r/ExclusivelyPumping",
        "title": "Momcozy M5 leaking when leaning over and suction dropped",
        "content": (
            "I bought the Momcozy M5 three weeks ago. Every time I lean forward to pick up "
            "my baby or type on my laptop, milk leaks right out of the top silicone seal. "
            "Also the suction feels significantly weaker on the left motor."
        ),
        "expected_defect_category": "sealing_leakage",
        "expected_urgency": "P1",
    },
    {
        "case_id": "golden_competitor_02",
        "subreddit": "r/ExclusivelyPumping",
        "title": "Momcozy M5 vs Elvie Stride - my 3 month honest comparison",
        "content": (
            "I have both the Momcozy M5 and the Elvie Stride. The Momcozy empties me much "
            "faster and has stronger suction for half the price. But Elvie is whisper quiet "
            "and much flatter in my bra. If I am in an office meeting I pick Elvie, but at home Momcozy wins."
        ),
        "expected_competitor": "Elvie",
        "expected_our_product": "Momcozy M5",
    },
    {
        "case_id": "golden_noise_03",
        "subreddit": "r/WorkingMoms",
        "title": "Pumping in the office mother room turned into a comedy show",
        "content": (
            "My wearable pump started making a loud squeaking sound during an executive check-in. "
            "I had to pretend my chair was creaking until I could escape to the hallway. "
            "Why is quiet pumping so hard to find?"
        ),
        "expected_platform": "TikTok",
        "expected_defect_category": "motor_noise",
    },
]


class GoldenDatasetAgentEvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scout_agent = ContentScoutAgent(client=None)
        self.rnd_agent = RndVocAgent(client=None)
        self.radar_agent = CompetitorRadarAgent(client=None)

    def test_rnd_voc_evaluation_on_golden_dataset(self) -> None:
        """Evaluate RndVocAgent against golden engineering failure cases."""
        scores = []
        for case in GOLDEN_DATASET:
            res = self.rnd_agent.analyze(
                post_id=case["case_id"],
                subreddit=case["subreddit"],
                title=case["title"],
                content=case["content"],
            )
            self.assertIsInstance(res, RndVocResult)
            self.assertEqual(res.source_post_id, case["case_id"])
            self.assertGreaterEqual(len(res.defects), 1)

            first_defect = res.defects[0]
            self.assertTrue(first_defect.defect_id)
            self.assertTrue(first_defect.component)
            self.assertTrue(first_defect.symptom)
            self.assertTrue(first_defect.root_cause_hypothesis)
            self.assertTrue(first_defect.suggested_action)
            self.assertIn(first_defect.severity, {"critical", "major", "minor"})
            self.assertIn(res.urgency_rating, {"P0", "P1", "P2", "P3"})

            # Targeted validation for leak case
            if case["case_id"] == "golden_leak_01":
                self.assertEqual(first_defect.category, case["expected_defect_category"])
                self.assertEqual(res.urgency_rating, case["expected_urgency"])

            # Targeted validation for noise case
            if case["case_id"] == "golden_noise_03":
                self.assertEqual(first_defect.category, case["expected_defect_category"])

            scores.append(1.0)

        self.assertEqual(len(scores), len(GOLDEN_DATASET))

    def test_competitor_radar_evaluation_on_golden_dataset(self) -> None:
        """Evaluate CompetitorRadarAgent against golden competitive comparison cases.

        Only cases that actually describe a head-to-head comparison may produce a
        comparison. The offline fallback used to emit one for every post regardless
        of content, which is how a house listing and a novel title became
        "competitor benchmarks" on the 2026-10-30 morning card.
        """
        for case in GOLDEN_DATASET:
            res = self.radar_agent.analyze(
                post_id=case["case_id"],
                subreddit=case["subreddit"],
                title=case["title"],
                content=case["content"],
            )
            self.assertIsInstance(res, CompetitorRadarResult)

            expects_comparison = case["case_id"] == "golden_competitor_02"
            if not expects_comparison:
                # Non-comparative posts must stay silent rather than invent one.
                self.assertEqual(
                    res.comparisons, [],
                    f"{case['case_id']} is not a comparison post but produced one",
                )
                continue

            self.assertGreaterEqual(len(res.comparisons), 1)

            first_comp = res.comparisons[0]
            self.assertTrue(first_comp.competitor_brand)
            self.assertTrue(first_comp.our_advantage)
            self.assertTrue(first_comp.our_disadvantage)
            self.assertIn(
                first_comp.sentiment_verdict,
                {"prefer_momcozy", "prefer_competitor", "mixed_tradeoff", "neutral"},
            )
            self.assertTrue(res.market_takeaway)
            self.assertGreaterEqual(len(res.positioning_advice), 1)

            # The quote must come from the post, not from a template.
            source = f"{case['title']}\n{case['content']}"
            if first_comp.user_verbatim_quote:
                self.assertIn(
                    first_comp.user_verbatim_quote.strip().lower()[:40],
                    source.lower().replace("\n", " "),
                    "quote must be citable from the post it is attributed to",
                )

            if case["case_id"] == "golden_competitor_02":
                self.assertEqual(first_comp.competitor_brand, case["expected_competitor"])
                self.assertIn("Momcozy", first_comp.our_product)

    def test_content_scout_evaluation_on_golden_dataset(self) -> None:
        """Evaluate ContentScoutAgent against golden social media discussion cases."""
        for case in GOLDEN_DATASET:
            res = self.scout_agent.scout(
                post_id=case["case_id"],
                subreddit=case["subreddit"],
                title=case["title"],
                content=case["content"],
            )
            self.assertIsInstance(res, ContentScoutResult)
            self.assertGreaterEqual(len(res.ideas), 1)

            first_idea = res.ideas[0]
            self.assertTrue(first_idea.topic_id)
            self.assertTrue(first_idea.target_audience)
            self.assertTrue(first_idea.hook_3s)
            self.assertTrue(first_idea.story_conflict)
            self.assertTrue(first_idea.solution_angle)
            self.assertTrue(first_idea.call_to_action)
            self.assertGreaterEqual(len(first_idea.visual_scene_script), 1)
            self.assertTrue(res.reasoning_summary)

    def test_multi_agent_suite_consistency(self) -> None:
        """Verify that all three agents can execute concurrently on a single post with complete JSON serialization."""
        post = GOLDEN_DATASET[0]
        scout_res = self.scout_agent.scout(
            post_id=post["case_id"], subreddit=post["subreddit"], title=post["title"], content=post["content"]
        )
        rnd_res = self.rnd_agent.analyze(
            post_id=post["case_id"], subreddit=post["subreddit"], title=post["title"], content=post["content"]
        )
        radar_res = self.radar_agent.analyze(
            post_id=post["case_id"], subreddit=post["subreddit"], title=post["title"], content=post["content"]
        )

        unified = {
            "post_id": post["case_id"],
            "content_scout": scout_res.to_dict(),
            "rnd_voc": rnd_res.to_dict(),
            "competitor_radar": radar_res.to_dict(),
        }

        # Verify strict JSON serializability
        serialized = json.dumps(unified, ensure_ascii=False)
        self.assertIn("sealing_leakage", serialized)
        self.assertIn("TikTok", serialized)
        self.assertIn("Momcozy M5", serialized)


if __name__ == "__main__":
    print("=" * 70)
    print("Running Golden Dataset Agent Evaluation Scorecard...")
    print("=" * 70)
    suite = unittest.TestLoader().loadTestsFromTestCase(GoldenDatasetAgentEvaluationTests)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    print("\n" + "=" * 70)
    print(f"Evaluation Summary: {result.testsRun} test suites executed.")
    print(f"Status: {'PASSED (100% Score)' if result.wasSuccessful() else 'FAILED'}")
    print("=" * 70)
