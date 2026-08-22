from __future__ import annotations

from pathlib import Path
import unittest

from reddit_voc.product_entity_resolution import ProductEntityResolver
from reddit_voc.tag_dictionary import TagDictionary
from scripts.build_reddit_site_snapshot import _enrich


ROOT = Path(__file__).resolve().parents[1]


class RedditSiteProductEnrichmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.resolver = ProductEntityResolver.from_ledger(
            ROOT
            / "config"
            / "product_entities"
            / "momcozy-product-entity-ledger-v1.json"
        )
        cls.dictionary = TagDictionary.from_csv(ROOT / "dim_tag_v6.3_final.csv")

    def test_enrichment_uses_governed_product_bindings_for_spu_and_category(self) -> None:
        posts = {
            "abcde": {
                "post_id": "abcde",
                "reddit_id": "t3_abcde",
                "title": "Momcozy M9 Mobile Flow breast pump",
                "content": "The suction is weak but the wearable design is compact.",
                "subreddit": "",
                "permalink": "https://www.reddit.com/r/fixture/comments/abcde/fixture/",
                "created_at_utc": "2026-07-14T00:00:00+00:00",
                "score": 1,
                "upvote_ratio": None,
                "num_comments_reported": 1,
                "parsed_comment_count": 1,
                "more_node_count": 0,
                "structural_coverage_grade": "full",
                "matched_keywords": [],
                "media_urls": [],
                "author_pseudonym": "anon_fixture",
                "pii_redaction_flags": [],
                "source_occurrences": [
                    {
                        "source_kind": "fixture",
                        "dataset_id": "fixture",
                        "collection_bucket": "Momcozy",
                        "run_id": None,
                        "coverage_grade": "full",
                    }
                ],
            }
        }
        comments = {
            "t1_c1": {
                "comment_id": "t1_c1",
                "reddit_id": "t1_c1",
                "post_id": "abcde",
                "parent_id": "t3_abcde",
                "body": "My Momcozy breast pump leaks.",
                "created_at_utc": "2026-07-14T00:01:00+00:00",
                "score": 1,
                "depth": 0,
                "is_submitter": False,
                "deleted_or_removed": False,
                "is_bot": False,
                "bot_detection_status": "fixture",
                "author_pseudonym": "anon_fixture_2",
                "pii_redaction_flags": [],
                "source_occurrences": [
                    {
                        "source_kind": "fixture",
                        "dataset_id": "fixture",
                        "collection_bucket": "Momcozy",
                        "run_id": None,
                        "coverage_grade": "full",
                    }
                ],
            }
        }

        enriched_posts, enriched_comments, quarantine, resolution, contexts = _enrich(
            posts,
            comments,
            analysis_code_sha256="a" * 64,
            tag_dictionary=self.dictionary,
            product_resolver=self.resolver,
        )

        self.assertEqual(quarantine, [])
        self.assertEqual(
            enriched_posts[0]["product_bindings"][0]["binding_level"],
            "spu_exact",
        )
        self.assertEqual(
            enriched_posts[0]["product_bindings"][0]["exact_spu"]["spu_id"],
            "SPU000168",
        )
        self.assertEqual(
            enriched_comments[0]["product_bindings"][0]["binding_level"],
            "category",
        )
        for entity in [*enriched_posts, *enriched_comments]:
            self.assertEqual(
                entity["tagging"]["context"]["spu_binding_mode"],
                "governed_explicit",
            )
            self.assertEqual(entity["brand_binding"], "momcozy_entity_reviewed")
            self.assertEqual(
                entity["event_created_at_utc"], entity["created_at_utc"]
            )
        self.assertEqual(
            enriched_posts[0]["comment_coverage_status"], "thread_complete"
        )
        self.assertEqual(enriched_posts[0]["subreddit"], "unknown")
        self.assertEqual(
            enriched_posts[0]["subreddit_normalization_status"],
            "source_empty_to_unknown",
        )
        self.assertEqual(
            contexts,
            (
                ("吸奶器", "吸奶器", ()),
                ("吸奶器", "吸奶器", ("SPU000168",)),
            ),
        )
        self.assertTrue(resolution["coverage"]["posts"]["is_conserved"])
        self.assertTrue(resolution["coverage"]["comments"]["is_conserved"])
        self.assertTrue(resolution["coverage"]["combined"]["is_conserved"])


if __name__ == "__main__":
    unittest.main()
