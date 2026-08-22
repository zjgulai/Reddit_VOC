from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from reddit_voc import cli
from reddit_voc.exporter import export_run
from reddit_voc.tikhub import (
    FETCH_COMMENT_REPLIES,
    FETCH_DYNAMIC_SEARCH,
    FETCH_POST_COMMENTS,
    FETCH_POST_DETAILS_BATCH_LARGE,
    FETCH_SUBREDDIT_FEED,
    _brand_first_search_terms,
    _is_brand_search_term,
    _parse_tikhub_app_detail_payload,
    collect_daily_tikhub,
    extract_tikhub_more_cursors,
)
from reddit_voc.storage import VocStore


FIXTURES = Path(__file__).parent / "fixtures"


class FakeTikHubClient:
    def __init__(self, listing_payload, detail_payload, comment_payload=None) -> None:
        self.listing_payload = listing_payload
        self.detail_payload = detail_payload
        self.comment_payload = comment_payload or {}
        self.get_calls = []

    def get_json(self, path, params=None):
        self.get_calls.append((path, params or {}))
        if path == FETCH_POST_DETAILS_BATCH_LARGE:
            return self.detail_payload
        if path == FETCH_POST_COMMENTS:
            return self.comment_payload
        return self.listing_payload

    def post_json(self, path, payload=None):
        raise AssertionError("TikHub app endpoints should be called with GET")


class TikHubCollectorTests(unittest.TestCase):
    def test_app_detail_prefers_permalink_over_media_url(self):
        media_url = "https://i.redd.it/o70f03x161dh1.jpeg"
        permalink = "/r/babywearing/comments/1uvhtgg/momcozy_carrier/"
        payload = {
            "data": {
                "postsInfoByIds": [
                    {
                        "id": "t3_1uvhtgg",
                        "createdAt": "2026-07-13T17:17:27+0000",
                        "postTitle": "Momcozy carrier",
                        "permalink": permalink,
                        "url": media_url,
                        "content": {"markdown": "Momcozy carrier question."},
                        "subreddit": {"name": "babywearing"},
                    }
                ]
            }
        }

        thread, comments = _parse_tikhub_app_detail_payload(
            payload,
            comment_payloads={},
            run_id="tikhub_permalink_test",
            raw_capture_id="raw_tikhub_permalink_test",
        )[0]

        self.assertEqual(thread.source_url, "https://www.reddit.com" + permalink)
        self.assertIn(media_url, thread.media_urls)
        self.assertEqual(comments, [])

    def test_tikhub_api_plan_is_docs_only(self):
        self.assertEqual(cli.main(["tikhub-api-plan"]), 0)

    def test_extract_more_cursors_preserves_response_order_without_guessing(self):
        payload = {
            "data": {
                "postInfoById": {
                    "commentForest": {
                        "trees": [
                            {"more": {"cursor": "commenttree:ex:(first)"}},
                            {
                                "node": {"__typename": "Comment"},
                                "replies": {
                                    "trees": [
                                        {"more": {"cursor": "commenttree:ex:(second)"}},
                                        {"more": {"cursor": "commenttree:ex:(first)"}},
                                    ]
                                },
                            },
                            {"more": {"cursor": ""}},
                            {"more": {"cursor": 7}},
                        ]
                    }
                }
            }
        }

        self.assertEqual(
            extract_tikhub_more_cursors(payload),
            ("commenttree:ex:(first)", "commenttree:ex:(second)"),
        )
        self.assertEqual(
            FETCH_COMMENT_REPLIES,
            "/api/v1/reddit/app/fetch_comment_replies",
        )

    def test_tikhub_cli_blocks_without_provider_gate(self):
        with TemporaryDirectory() as tmp:
            rc = cli.main(
                [
                    "run-tikhub-collector",
                    "--database",
                    str(Path(tmp) / "voc.sqlite3"),
                    "--output-dir",
                    str(Path(tmp) / "out"),
                    "--run-id",
                    "blocked_tikhub_test",
                ]
            )
        self.assertEqual(rc, 1)

    def test_brand_first_search_terms_prioritize_broad_momcozy_queries(self):
        terms = _brand_first_search_terms(["Momcozy", "\"Momcozy M5\"", "\"wearable pump\""])
        self.assertEqual(terms[:5], ["Momcozy", "momcozy", "\"Momcozy\"", "\"momcozy\"", "\"mom cozy\""])
        self.assertEqual(terms.count("Momcozy"), 1)
        self.assertTrue(_is_brand_search_term("\"Momcozy M5\""))
        self.assertTrue(_is_brand_search_term("\"mom cozy\""))
        self.assertFalse(_is_brand_search_term("\"wearable pump\""))

    def test_collect_daily_tikhub_uses_7am_window_and_ingests_details(self):
        listing_payload = json.loads((FIXTURES / "reddit_listing_browser_json.json").read_text(encoding="utf-8"))
        detail_payload = {"data": [json.loads((FIXTURES / "reddit_thread_browser_json.json").read_text(encoding="utf-8"))]}
        client = FakeTikHubClient(listing_payload, detail_payload)

        with TemporaryDirectory() as tmp:
            store = VocStore(Path(tmp) / "voc.sqlite3")
            store.migrate()
            summary = collect_daily_tikhub(
                store,
                run_id="tikhub_collect_test",
                client=client,
                subreddits=["ExclusivelyPumping"],
                search_terms=["Momcozy"],
                anchor_utc=datetime(2026, 7, 7, 23, 0, tzinfo=timezone.utc),
                run_hour=7,
            )

            self.assertEqual(summary.status, "partial")
            self.assertTrue(summary.provider_call)
            self.assertFalse(summary.live_send)
            self.assertGreaterEqual(summary.discovered_posts, 6)
            self.assertGreaterEqual(summary.window_posts, 6)
            self.assertEqual(summary.relevant_posts, 1)
            self.assertEqual(summary.ingested_threads, 1)
            self.assertEqual(summary.ingested_comments, 2)
            self.assertEqual(client.get_calls[0][0], FETCH_DYNAMIC_SEARCH)
            self.assertEqual(client.get_calls[0][1]["query"], "Momcozy")
            self.assertNotIn("keyword", client.get_calls[1][1])
            feed_calls = [call for call in client.get_calls if call[0] == FETCH_SUBREDDIT_FEED]
            self.assertEqual(feed_calls[0][1]["subreddit_name"], "ExclusivelyPumping")
            self.assertEqual(feed_calls[0][1]["sort"], "NEW")
            self.assertEqual(feed_calls[0][1]["after"], "")
            self.assertEqual(feed_calls[0][1]["need_format"], "false")
            self.assertNotIn("limit", feed_calls[0][1])
            self.assertNotIn("subreddit", feed_calls[0][1])
            detail_calls = [call for call in client.get_calls if call[0] == FETCH_POST_DETAILS_BATCH_LARGE]
            comment_calls = [call for call in client.get_calls if call[0] == FETCH_POST_COMMENTS]
            self.assertEqual(detail_calls[0][1]["post_ids"], "t3_1fixture")
            self.assertEqual(detail_calls[0][1]["need_format"], "false")
            self.assertEqual(comment_calls[0][1]["post_id"], "t3_1fixture")
            self.assertEqual(store.count_for_run("reddit_threads", "tikhub_collect_test"), 1)
            self.assertTrue(store.get_run("tikhub_collect_test")["provider_call"])

    def test_collect_daily_tikhub_supports_exact_rolling_window_end(self):
        listing_payload = json.loads((FIXTURES / "reddit_listing_browser_json.json").read_text(encoding="utf-8"))
        detail_payload = {"data": [json.loads((FIXTURES / "reddit_thread_browser_json.json").read_text(encoding="utf-8"))]}
        client = FakeTikHubClient(listing_payload, detail_payload)

        with TemporaryDirectory() as tmp:
            store = VocStore(Path(tmp) / "voc.sqlite3")
            store.migrate()
            summary = collect_daily_tikhub(
                store,
                run_id="tikhub_exact_window_test",
                client=client,
                subreddits=["ExclusivelyPumping"],
                search_terms=["Momcozy"],
                window_end_utc=datetime(2026, 7, 7, 6, 30, tzinfo=timezone.utc),
                rolling_window_hours=1,
            )

            self.assertEqual(summary.window_start_utc, "2026-07-07T05:30:00+00:00")
            self.assertEqual(summary.window_end_utc, "2026-07-07T06:30:00+00:00")
            self.assertGreaterEqual(summary.window_posts, 6)
            self.assertEqual(summary.relevant_posts, 1)
            self.assertEqual(summary.ingested_threads, 1)

    def test_collect_daily_tikhub_persists_discovery_detail_and_comment_raw_payloads(self):
        listing_payload = json.loads((FIXTURES / "reddit_listing_browser_json.json").read_text(encoding="utf-8"))
        detail_payload = {"data": [json.loads((FIXTURES / "reddit_thread_browser_json.json").read_text(encoding="utf-8"))]}
        comment_payload = {"data": {"postInfoById": {"id": "t3_1fixture", "commentForest": {"trees": []}}}}
        client = FakeTikHubClient(listing_payload, detail_payload, comment_payload)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = VocStore(root / "voc.sqlite3")
            store.migrate()
            summary = collect_daily_tikhub(
                store,
                run_id="tikhub_raw_test",
                client=client,
                subreddits=["ExclusivelyPumping"],
                search_terms=["Momcozy"],
                anchor_utc=datetime(2026, 7, 7, 23, 0, tzinfo=timezone.utc),
                raw_artifact_root=root / "raw-captures",
            )

            artifacts = list((root / "raw-captures" / "tikhub_raw_test").glob("*.json"))
            self.assertEqual(summary.ingested_threads, 1)
            self.assertGreater(len(artifacts), 1)
            payload = next(
                value
                for value in (
                    json.loads(artifact.read_text(encoding="utf-8"))
                    for artifact in artifacts
                )
                if "detail" in value
            )
            self.assertEqual(payload["detail"], detail_payload)
            self.assertIn("t3_1fixture", payload["comments_by_post_id"])

    def test_tikhub_cli_persists_raw_and_builds_source_batch_from_same_output_dir(self):
        listing_payload = json.loads((FIXTURES / "reddit_listing_browser_json.json").read_text(encoding="utf-8"))
        detail_payload = {"data": [json.loads((FIXTURES / "reddit_thread_browser_json.json").read_text(encoding="utf-8"))]}
        comment_payload = {"data": {"postInfoById": {"id": "t3_1fixture", "commentForest": {"trees": []}}}}
        client = FakeTikHubClient(listing_payload, detail_payload, comment_payload)

        with TemporaryDirectory() as tmp, patch.dict(
            "os.environ",
            {"REDDIT_VOC_ENABLE_TIKHUB": "1", "TIKHUB_API_KEY": "test-only"},
            clear=False,
        ), patch("reddit_voc.cli.TikHubClient", return_value=client):
            root = Path(tmp)
            output_dir = root / "out"
            database = root / "voc.sqlite3"
            run_id = "tikhub_cli_raw_source_batch_test"
            collector_stdout = StringIO()
            with redirect_stdout(collector_stdout):
                collector_rc = cli.main(
                    [
                        "run-tikhub-collector",
                        "--database",
                        str(database),
                        "--output-dir",
                        str(output_dir),
                        "--run-id",
                        run_id,
                        "--anchor-utc",
                        "2026-07-07T23:00:00+00:00",
                        "--subreddit",
                        "ExclusivelyPumping",
                        "--search-term",
                        "Momcozy",
                        "--authorize-provider-call",
                    ]
                )

            self.assertEqual(collector_rc, 0)
            collector_summary = json.loads(collector_stdout.getvalue())
            canonical_summary = output_dir / f"{run_id}-collector-summary.json"
            canonical_summary.write_text(
                json.dumps(collector_summary, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            raw_artifacts = list((output_dir / "raw-captures" / run_id).glob("*.json"))
            self.assertGreater(len(raw_artifacts), 1)

            project_root = Path(__file__).parents[1]
            source_batch_stdout = StringIO()
            with redirect_stdout(source_batch_stdout):
                source_batch_rc = cli.main(
                    [
                        "build-daily-source-batch",
                        "--database",
                        str(database),
                        "--output-dir",
                        str(output_dir),
                        "--run-id",
                        run_id,
                        "--query-profile",
                        str(project_root / "config/source-batch/momcozy-query-v2.json"),
                        "--coverage-profile",
                        str(project_root / "config/source-batch/momcozy-coverage-v2.json"),
                    ]
                )

            self.assertEqual(source_batch_rc, 0)
            source_batch = json.loads(source_batch_stdout.getvalue())
            self.assertEqual(source_batch["write_status"], "created")
            self.assertTrue(Path(source_batch["manifest_path"]).is_file())

    def test_collect_daily_tikhub_keeps_brand_search_candidate_without_title_keyword(self):
        listing_payload = {
            "data": {
                "search": {
                    "dynamic": {
                        "components": {
                            "main": {
                                "edges": [
                                    {
                                        "node": {
                                            "children": [
                                                {
                                                    "__typename": "SearchPost",
                                                    "post": {
                                                        "id": "t3_brand_body_only",
                                                        "createdAt": "2026-07-07T05:57:31+0000",
                                                        "postTitle": "Need help choosing a pump for night feeds",
                                                        "url": "https://www.reddit.com/r/ExclusivelyPumping/comments/brand_body_only/pump_help/",
                                                        "score": 8,
                                                        "commentCount": 2,
                                                        "subreddit": {"name": "ExclusivelyPumping"},
                                                    },
                                                }
                                            ]
                                        }
                                    }
                                ]
                            }
                        }
                    }
                }
            }
        }
        detail_payload = {
            "data": {
                "postsInfoByIds": [
                    {
                        "id": "t3_brand_body_only",
                        "createdAt": "2026-07-07T05:57:31+0000",
                        "postTitle": "Need help choosing a pump for night feeds",
                        "url": "https://www.reddit.com/r/ExclusivelyPumping/comments/brand_body_only/pump_help/",
                        "content": {"markdown": "I am considering Momcozy because it might work better at night."},
                        "score": 8,
                        "commentCount": 0,
                        "subreddit": {"name": "ExclusivelyPumping"},
                        "authorInfo": {"name": "poster"},
                    }
                ]
            }
        }
        client = FakeTikHubClient(listing_payload, detail_payload)

        with TemporaryDirectory() as tmp:
            store = VocStore(Path(tmp) / "voc.sqlite3")
            store.migrate()
            summary = collect_daily_tikhub(
                store,
                run_id="tikhub_brand_body_candidate_test",
                client=client,
                subreddits=[],
                search_terms=["Momcozy"],
                anchor_utc=datetime(2026, 7, 7, 23, 0, tzinfo=timezone.utc),
                run_hour=7,
            )

            self.assertEqual(summary.relevant_posts, 1)
            self.assertEqual(summary.ingested_threads, 1)
            stored = store.fetch_threads_for_run("tikhub_brand_body_candidate_test")[0]
            self.assertEqual(stored["title"], "Need help choosing a pump for night feeds")
            self.assertIn("Momcozy", stored["selftext"])

    def test_collect_daily_tikhub_parses_search_post_components(self):
        listing_payload = {
            "data": {
                "search": {
                    "dynamic": {
                        "components": {
                            "main": {
                                "edges": [
                                    {
                                        "node": {
                                            "children": [
                                                {
                                                    "__typename": "SearchPost",
                                                    "post": {
                                                        "id": "t3_1fixture",
                                                        "createdAt": "2026-07-07T05:57:31+0000",
                                                        "postTitle": "Momcozy M5 leaking at work",
                                                        "url": "https://www.reddit.com/r/ExclusivelyPumping/comments/1fixture/momcozy_m5_leaking_at_work/",
                                                        "score": 12,
                                                        "commentCount": 3,
                                                        "subreddit": {"name": "ExclusivelyPumping"},
                                                    },
                                                }
                                            ]
                                        }
                                    }
                                ]
                            }
                        }
                    }
                }
            }
        }
        detail_payload = {
            "data": {
                "postsInfoByIds": [
                    {
                        "id": "t3_1fixture",
                        "createdAt": "2026-07-07T05:57:31+0000",
                        "postTitle": "Momcozy M5 leaking at work",
                        "url": "https://www.reddit.com/r/ExclusivelyPumping/comments/1fixture/momcozy_m5_leaking_at_work/",
                        "content": {"markdown": "The Momcozy M5 leaked during my commute."},
                        "score": 12,
                        "commentCount": 1,
                        "preview": {
                            "images": [
                                {
                                    "source": {
                                        "url": "https://preview.redd.it/momcozy-m5-leak.jpg?width=960&format=pjpg&auto=webp"
                                    }
                                }
                            ]
                        },
                        "thumbnail": "https://preview.redd.it/momcozy-m5-thumb.jpg?width=140&format=pjpg&auto=webp",
                        "subreddit": {"name": "ExclusivelyPumping"},
                        "authorInfo": {"name": "poster"},
                    }
                ]
            }
        }
        comment_payload = {
            "data": {
                "postInfoById": {
                    "id": "t3_1fixture",
                    "commentCount": 1,
                    "commentForest": {
                        "trees": [
                            {
                                "depth": 0,
                                "parentId": "t3_1fixture",
                                "node": {
                                    "__typename": "Comment",
                                    "id": "t1_c1",
                                    "createdAt": "2026-07-07T06:10:00+0000",
                                    "content": {"markdown": "Try a smaller flange insert."},
                                    "authorInfo": {"name": "helper"},
                                    "score": 4,
                                    "permalink": "/r/ExclusivelyPumping/comments/1fixture/momcozy_m5_leaking_at_work/c1/",
                                },
                            }
                        ]
                    },
                }
            }
        }
        client = FakeTikHubClient(listing_payload, detail_payload, comment_payload)

        with TemporaryDirectory() as tmp:
            store = VocStore(Path(tmp) / "voc.sqlite3")
            store.migrate()
            summary = collect_daily_tikhub(
                store,
                run_id="tikhub_component_test",
                client=client,
                subreddits=[],
                search_terms=["Momcozy"],
                anchor_utc=datetime(2026, 7, 7, 23, 0, tzinfo=timezone.utc),
                run_hour=7,
            )

            self.assertGreaterEqual(summary.discovered_posts, 5)
            self.assertEqual(summary.relevant_posts, 1)
            detail_calls = [call for call in client.get_calls if call[0] == FETCH_POST_DETAILS_BATCH_LARGE]
            comment_calls = [call for call in client.get_calls if call[0] == FETCH_POST_COMMENTS]
            self.assertEqual(detail_calls[0][1]["post_ids"], "t3_1fixture")
            self.assertEqual(comment_calls[0][1]["sort_type"], "CONFIDENCE")
            self.assertEqual(summary.ingested_threads, 1)
            self.assertEqual(summary.ingested_comments, 1)
            stored = store.fetch_threads_for_run("tikhub_component_test")[0]
            self.assertIn("https://preview.redd.it/momcozy-m5-leak.jpg?width=960&format=pjpg&auto=webp", stored["media_urls"])
            exported = export_run(store, run_id="tikhub_component_test", output_dir=Path(tmp) / "out")
            posts_csv = exported.posts_csv.read_text(encoding="utf-8")
            self.assertIn("media_urls", posts_csv.splitlines()[0])
            self.assertIn("https://preview.redd.it/momcozy-m5-leak.jpg?width=960&format=pjpg&auto=webp", posts_csv)

    def test_tikhub_cli_blocks_without_api_key_even_when_authorized(self):
        with TemporaryDirectory() as tmp, patch.dict("os.environ", {"REDDIT_VOC_ENABLE_TIKHUB": "1", "TIKHUB_API_KEY": ""}, clear=False):
            rc = cli.main(
                [
                    "run-tikhub-collector",
                    "--database",
                    str(Path(tmp) / "voc.sqlite3"),
                    "--output-dir",
                    str(Path(tmp) / "out"),
                    "--run-id",
                    "missing_key_test",
                    "--authorize-provider-call",
                ]
            )
        self.assertEqual(rc, 1)
