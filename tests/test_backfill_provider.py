from __future__ import annotations

import base64
from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from reddit_voc import backfill_provider, backfill_validation
from reddit_voc.backfill_archived_recovery import (
    prepare_failed_schema_drift_retry,
)
from reddit_voc.backfill_models import (
    BackfillCheckpoint,
    BackfillManifest,
    LaneResult,
    RawArtifactMetadata,
)
from reddit_voc.backfill_archive import PrivateRawArchive
from reddit_voc.backfill_provider import (
    CursorContract,
    ProviderBudgetExhausted,
    TikHubRequestExecutor,
    TikHubBackfillDiscoverer,
    TikHubSchemaDrift,
    extract_next_cursor,
    infer_cursor_contract,
)
from reddit_voc.backfill_storage import BackfillConflictError, BackfillStore
from reddit_voc.models import RawCapture, RedditThread
from reddit_voc.tikhub import (
    FETCH_DYNAMIC_SEARCH,
    FETCH_POST_COMMENTS,
    FETCH_POST_DETAILS_BATCH_LARGE,
    FETCH_SUBREDDIT_FEED,
    TikHubDiscoveryShapeError,
)
from reddit_voc.time_window import CollectionWindow


NOW = datetime(2026, 7, 11, 4, 17, 9, tzinfo=timezone.utc)


class BackfillProviderImportIsolationTests(unittest.TestCase):
    def test_import_does_not_load_daily_collector(self):
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    "from reddit_voc import backfill_provider; "
                    "raise SystemExit(int('reddit_voc.collector' in sys.modules))"
                ),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)


def make_manifest(*, max_provider_requests: int) -> BackfillManifest:
    return BackfillManifest(
        run_id="backfill_provider_test",
        status="prepared",
        window_start_utc="2024-12-31T16:00:00+00:00",
        requested_end_utc="2026-07-11T16:00:00+00:00",
        effective_end_utc="2026-07-11T04:17:09+00:00",
        search_terms=("Momcozy",),
        subreddits=("ExclusivelyPumping",),
        include_subreddit_sweep=False,
        required_lanes_sha256="1" * 64,
        keyword_config_sha256="0" * 64,
        max_provider_requests=max_provider_requests,
        provider_request_count=0,
        provider_call=False,
        live_send=False,
        created_at_utc=NOW.isoformat(),
        updated_at_utc=NOW.isoformat(),
    )


class FakeTikHubClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get_json(self, path, params):
        self.calls.append((path, dict(params)))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class KeyedFakeTikHubClient:
    def __init__(self, responses):
        self.responses = dict(responses)
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get_json(self, path, params):
        copied = dict(params)
        self.calls.append((path, copied))
        outcome = self.responses[(path, copied.get("after", ""))]
        if isinstance(outcome, list):
            outcome = outcome.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def http_error(status: int, message: str = "sensitive response") -> HTTPError:
    return HTTPError(
        url="https://provider.invalid/path?secret=must-not-persist",
        code=status,
        msg=message,
        hdrs=None,
        fp=None,
    )


class CursorContractTests(unittest.TestCase):
    def test_contract_is_frozen_and_uses_the_full_nested_path(self):
        payload = {
            "data": {
                "edges": [
                    {"node": {"id": "ignored"}},
                    {"pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"}},
                ]
            }
        }

        contract = infer_cursor_contract(payload)

        self.assertEqual(
            tuple(field.name for field in fields(CursorContract)),
            ("cursor_path", "schema_sha256"),
        )
        self.assertEqual(
            contract.cursor_path,
            ("data", "edges", 1, "pageInfo", "endCursor"),
        )
        self.assertEqual(len(contract.schema_sha256), 64)
        self.assertEqual(extract_next_cursor(payload, contract), "cursor-1")
        with self.assertRaises(FrozenInstanceError):
            contract.schema_sha256 = "changed"

    def test_inference_rejects_zero_ambiguous_and_wrong_typed_candidates(self):
        payloads = (
            {"data": {"pageInfo": {"endCursor": ""}}},
            {"data": {"pageInfo": {"endCursor": 123}}},
            {
                "data": {"pageInfo": {"endCursor": "one"}},
                "other": {"pageInfo": {"after": "two"}},
            },
            {
                "data": {
                    "pageInfo": {"endCursor": "one", "nextCursor": "two"}
                }
            },
            {"page_info": {"endCursor": "not-under-exact-key"}},
        )

        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaises(TikHubSchemaDrift):
                infer_cursor_contract(payload)

    def test_extraction_accepts_terminal_values_but_rejects_schema_drift(self):
        first = {
            "data": {
                "pageInfo": {
                    "hasNextPage": True,
                    "endCursor": "cursor-1",
                    "nested": {"count": 1},
                }
            }
        }
        contract = infer_cursor_contract(first)

        empty = {
            "data": {
                "pageInfo": {
                    "hasNextPage": False,
                    "endCursor": "",
                    "nested": {"count": 2},
                }
            }
        }
        null = {
            "data": {
                "pageInfo": {
                    "hasNextPage": False,
                    "endCursor": None,
                    "nested": {"count": 3},
                }
            }
        }
        self.assertIsNone(extract_next_cursor(empty, contract))
        self.assertIsNone(extract_next_cursor(null, contract))

        drifted_payloads = (
            {"data": {"pageInfo": {"hasNextPage": False, "nested": {"count": 2}}}},
            {
                "data": {
                    "pageInfo": {
                        "hasNextPage": False,
                        "endCursor": 7,
                        "nested": {"count": 2},
                    }
                }
            },
            {
                "data": {
                    "pageInfo": {
                        "hasNextPage": False,
                        "endCursor": "cursor-2",
                        "nested": {"count": "wrong-type"},
                    }
                }
            },
            {
                "data": {
                    "pageInfo": {
                        "hasNextPage": False,
                        "endCursor": "cursor-2",
                        "nested": {"count": 2},
                        "newField": True,
                    }
                }
            },
            {
                "data": {
                    "pageInfo": {
                        "hasNextPage": True,
                        "endCursor": "",
                        "nextCursor": "moved",
                        "nested": {"count": 2},
                    }
                }
            },
        )
        for payload in drifted_payloads:
            with self.subTest(payload=payload), self.assertRaises(TikHubSchemaDrift):
                extract_next_cursor(payload, contract)

    def test_comment_terminal_without_cursor_requires_explicit_reviewed_opt_in(self):
        contract = current_comment_contract()
        terminal = current_comment_response(
            "probe", trees=(comment_tree("probe", "c1", "synthetic"),)
        )

        with self.assertRaises(TikHubSchemaDrift):
            extract_next_cursor(terminal, contract)
        self.assertIsNone(
            extract_next_cursor(
                terminal, contract, allow_terminal_without_cursor=True
            )
        )

        nonterminal_without_cursor = current_comment_response("probe")
        nonterminal_without_cursor["data"]["postInfoById"]["commentForest"][
            "pageInfo"
        ]["hasNextPage"] = True
        with self.assertRaises(TikHubSchemaDrift):
            extract_next_cursor(
                nonterminal_without_cursor,
                contract,
                allow_terminal_without_cursor=True,
            )

    def test_explicit_has_next_false_with_cursor_is_terminal(self):
        first = {
            "data": {
                "pageInfo": {
                    "hasNextPage": True,
                    "endCursor": "cursor-1",
                    "nested": {"count": 1},
                }
            }
        }
        contract = infer_cursor_contract(first)
        terminal = {
            "data": {
                "pageInfo": {
                    "hasNextPage": False,
                    "endCursor": "cursor-terminal",
                    "nested": {"count": 2},
                }
            }
        }

        self.assertIsNone(extract_next_cursor(terminal, contract))

    def test_comment_terminal_nullable_count_schema_variant_is_reviewed(self):
        contract = current_comment_contract()
        terminal = current_comment_response("probe")
        terminal["data"]["postInfoById"]["commentForest"]["pageInfo"][
            "commentCount"
        ] = None

        self.assertIsNone(
            extract_next_cursor(
                terminal, contract, allow_terminal_without_cursor=True
            )
        )

        terminal["data"]["postInfoById"]["commentForest"]["pageInfo"][
            "unexpected"
        ] = False
        with self.assertRaises(TikHubSchemaDrift):
            extract_next_cursor(
                terminal, contract, allow_terminal_without_cursor=True
            )

    def test_extraction_rejects_any_remote_nonempty_cursor_path(self):
        first = {
            "data": {
                "primary": {
                    "pageInfo": {
                        "hasNextPage": True,
                        "endCursor": "cursor-1",
                    }
                }
            }
        }
        contract = infer_cursor_contract(first)
        later_payloads = (
            {
                "data": {
                    "primary": {
                        "pageInfo": {
                            "hasNextPage": False,
                            "endCursor": None,
                        }
                    },
                    "remote": {"pageInfo": {"after": "remote-cursor"}},
                }
            },
            {
                "data": {
                    "primary": {
                        "pageInfo": {
                            "hasNextPage": True,
                            "endCursor": "cursor-2",
                        }
                    },
                    "remote": {"pageInfo": {"nextCursor": "remote-cursor"}},
                }
            },
        )

        for payload in later_payloads:
            with self.subTest(payload=payload), self.assertRaises(TikHubSchemaDrift):
                extract_next_cursor(payload, contract)


class TikHubRequestExecutorTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.store_counter = 0

    def make_store(self, *, budget: int) -> BackfillStore:
        self.store_counter += 1
        store = BackfillStore(
            Path(self.temporary_directory.name)
            / f"{self.store_counter}-{budget}.sqlite3"
        )
        store.migrate()
        store.create_manifest(make_manifest(max_provider_requests=budget))
        return store

    @staticmethod
    def attempt_rows(store: BackfillStore):
        with store.connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM backfill_provider_attempts ORDER BY request_number"
                ).fetchall()
            ]

    def test_retries_four_total_attempts_with_exact_waits_and_sanitized_ledger(self):
        store = self.make_store(budget=4)
        client = FakeTikHubClient(
            [
                URLError("secret-network-message"),
                TimeoutError("secret-timeout-message"),
                http_error(503),
                {"ok": True},
            ]
        )
        waits: list[int] = []
        executor = TikHubRequestExecutor(
            client,
            store,
            "backfill_provider_test",
            sleep=waits.append,
            now=lambda: NOW,
        )

        result = executor.get_json(
            "/api/v1/reddit/app/fetch_dynamic_search",
            {"query": "secret-query", "after": "secret-cursor"},
        )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(waits, [2, 4, 8])
        self.assertEqual(len(client.calls), 4)
        rows = self.attempt_rows(store)
        self.assertEqual([row["status"] for row in rows], ["failed"] * 3 + ["succeeded"])
        self.assertEqual(
            [row["error_class"] for row in rows],
            ["URLError", "TimeoutError", "HTTPError", None],
        )
        self.assertEqual([row["http_status"] for row in rows], [None, None, 503, None])
        self.assertTrue(all(row["sent_at_utc"] == NOW.isoformat() for row in rows))
        self.assertTrue(all(row["completed_at_utc"] == NOW.isoformat() for row in rows))
        self.assertTrue(
            all(
                row["endpoint"] == "/api/v1/reddit/app/fetch_dynamic_search"
                for row in rows
            )
        )
        ledger_text = repr(rows)
        for secret in ("secret-query", "secret-cursor", "secret-network-message", "sensitive response"):
            self.assertNotIn(secret, ledger_text)

    def test_http_429_and_5xx_retry_but_401_403_422_do_not(self):
        for status in (401, 403, 422):
            with self.subTest(status=status):
                store = self.make_store(budget=4)
                client = FakeTikHubClient([http_error(status)])
                waits: list[int] = []
                executor = TikHubRequestExecutor(
                    client,
                    store,
                    "backfill_provider_test",
                    sleep=waits.append,
                    now=lambda: NOW,
                )

                with self.assertRaises(backfill_provider.TikHubProviderError):
                    executor.get_json("/provider/path", {"ignored": "secret"})

                self.assertEqual(len(client.calls), 1)
                self.assertEqual(waits, [])
                self.assertEqual(store.provider_request_count("backfill_provider_test"), 1)

        for status in (429, 500):
            with self.subTest(status=status):
                store = self.make_store(budget=2)
                client = FakeTikHubClient([http_error(status), {"ok": True}])
                waits: list[int] = []
                executor = TikHubRequestExecutor(
                    client,
                    store,
                    "backfill_provider_test",
                    sleep=waits.append,
                    now=lambda: NOW,
                )

                self.assertEqual(executor.get_json("/provider/path", {}), {"ok": True})
                self.assertEqual(len(client.calls), 2)
                self.assertEqual(waits, [2])

    def test_each_retry_consumes_budget_and_exhaustion_preserves_sent_evidence(self):
        store = self.make_store(budget=2)
        client = FakeTikHubClient(
            [ConnectionError("first"), ConnectionError("second")]
        )
        waits: list[int] = []
        executor = TikHubRequestExecutor(
            client,
            store,
            "backfill_provider_test",
            sleep=waits.append,
            now=lambda: NOW,
        )

        with self.assertRaises(ProviderBudgetExhausted):
            executor.get_json("/provider/path", {"after": "cursor"})

        self.assertEqual(store.provider_request_count("backfill_provider_test"), 2)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(waits, [2])
        self.assertEqual(
            [row["status"] for row in self.attempt_rows(store)],
            ["failed", "failed"],
        )
        with store.connect() as conn:
            manifest = conn.execute(
                "SELECT provider_call FROM backfill_manifests WHERE run_id = ?",
                ("backfill_provider_test",),
            ).fetchone()
        self.assertEqual(manifest["provider_call"], 1)

    def test_retries_consume_absolute_phase_ceiling_and_raise_distinct_error(self):
        phase_error_type = getattr(
            backfill_provider, "ProviderPhaseBudgetExhausted", None
        )
        self.assertIsNotNone(phase_error_type)
        self.assertFalse(issubclass(phase_error_type, ProviderBudgetExhausted))
        store = self.make_store(budget=4)
        client = FakeTikHubClient(
            [ConnectionError("first"), ConnectionError("second")]
        )
        waits: list[int] = []
        executor = TikHubRequestExecutor(
            client,
            store,
            "backfill_provider_test",
            sleep=waits.append,
            now=lambda: NOW,
            request_ceiling=2,
        )

        with self.assertRaises(phase_error_type):
            executor.get_json("/provider/path", {"after": "cursor"})

        self.assertEqual(store.provider_request_count("backfill_provider_test"), 2)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(waits, [2])
        self.assertEqual(
            [row["status"] for row in self.attempt_rows(store)],
            ["failed", "failed"],
        )

    def test_global_budget_exhaustion_remains_global_below_phase_ceiling(self):
        store = self.make_store(budget=1)
        client = FakeTikHubClient([ConnectionError("first")])
        executor = TikHubRequestExecutor(
            client,
            store,
            "backfill_provider_test",
            sleep=lambda _: None,
            now=lambda: NOW,
            request_ceiling=3,
        )

        with self.assertRaises(ProviderBudgetExhausted):
            executor.get_json("/provider/path", {})

        self.assertEqual(store.provider_request_count("backfill_provider_test"), 1)
        self.assertEqual(len(client.calls), 1)

    def test_global_budget_exhaustion_wins_when_phase_ceiling_is_equal(self):
        store = self.make_store(budget=2)
        client = FakeTikHubClient(
            [ConnectionError("first"), ConnectionError("second")]
        )
        waits: list[int] = []
        executor = TikHubRequestExecutor(
            client,
            store,
            "backfill_provider_test",
            sleep=waits.append,
            now=lambda: NOW,
            request_ceiling=2,
        )

        with self.assertRaises(ProviderBudgetExhausted):
            executor.get_json("/provider/path", {})

        self.assertEqual(store.provider_request_count("backfill_provider_test"), 2)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(waits, [2])

    def test_zero_budget_never_calls_client_or_sets_provider_call(self):
        store = self.make_store(budget=0)
        client = FakeTikHubClient([{"must": "not run"}])
        executor = TikHubRequestExecutor(
            client,
            store,
            "backfill_provider_test",
            sleep=lambda _: None,
            now=lambda: NOW,
        )

        with self.assertRaises(ProviderBudgetExhausted):
            executor.get_json("/provider/path", {})

        self.assertEqual(client.calls, [])
        self.assertEqual(self.attempt_rows(store), [])
        with store.connect() as conn:
            manifest = conn.execute(
                "SELECT provider_call FROM backfill_manifests WHERE run_id = ?",
                ("backfill_provider_test",),
            ).fetchone()
        self.assertEqual(manifest["provider_call"], 0)

    def test_client_failure_uses_a_dedicated_sanitized_provider_error(self):
        self.assertTrue(hasattr(backfill_provider, "TikHubProviderError"))
        provider_error_type = backfill_provider.TikHubProviderError
        store = self.make_store(budget=1)
        client = FakeTikHubClient([http_error(422)])
        executor = TikHubRequestExecutor(
            client,
            store,
            "backfill_provider_test",
            sleep=lambda _: None,
            now=lambda: NOW,
        )

        with self.assertRaises(provider_error_type) as raised:
            executor.get_json("/provider/path", {"query": "must-not-persist"})

        self.assertEqual(raised.exception.error_class, "HTTPError")
        self.assertEqual(raised.exception.http_status, 422)
        self.assertNotIn("sensitive response", str(raised.exception))


def discovery_post(post_id: str, created_at: str | None) -> dict[str, object]:
    row: dict[str, object] = {
        "id": f"t3_{post_id}",
        "postTitle": f"Momcozy post {post_id}",
        "url": f"https://www.reddit.com/r/ExclusivelyPumping/comments/{post_id}/title/",
        "subreddit": {"name": "ExclusivelyPumping"},
    }
    if created_at is not None:
        row["createdAt"] = created_at
    return {"post": row}


def discovery_page(cursor: str | None, posts: list[dict[str, object]]):
    return verified_dynamic_discovery_page(cursor, posts)


def verified_dynamic_discovery_page(
    cursor: str | None, posts: list[dict[str, object]]
) -> dict[str, object]:
    children: list[dict[str, object]] = []
    for value in posts:
        post = value.get("post")
        if not isinstance(post, dict):
            raise ValueError("verified dynamic fixture requires wrapped posts")
        children.append({"__typename": "SearchPost", "post": post})
    return {
        "data": {
            "search": {
                "dynamic": {
                    "components": {
                        "main": {
                            "edges": [{"node": {"children": children}}],
                            "pageInfo": {
                                "hasNextPage": cursor is not None,
                                "endCursor": cursor,
                            },
                        }
                    }
                }
            }
        }
    }


def _encoded_reddit_id(value: str) -> str:
    return base64.b64encode(value.encode("ascii")).decode("ascii")


def subreddit_v3_page(
    cursor: str | None,
    *,
    subreddit: str = "ExclusivelyPumping",
    posts: tuple[tuple[str, bool], ...] = (("abc123", False),),
) -> dict[str, object]:
    edges: list[dict[str, object]] = []
    for post_id, title_with_thumbnail in posts:
        fullname = f"t3_{post_id}"
        metadata = {
            "__typename": "MetadataCell",
            "authorName": "synthetic-author",
            "color": None,
            "createdAt": "2026-07-01T00:00:00Z",
            "detailsLink": None,
            "detailsString": "synthetic",
            "iconPath": None,
            "iconShape": None,
            "id": _encoded_reddit_id(f"metadata:{fullname}"),
            "isBrandAffiliate": False,
            "isJoinButtonShown": False,
            "isOverflowButtonHidden": False,
            "isRecommended": False,
            "joinSubredditId": None,
            "mediaDomain": None,
            "mediaPath": None,
            "modUserNoteLabel": None,
            "statusIndicators": [],
        }
        title_cell = {
            "__typename": "TitleCell",
            "id": _encoded_reddit_id(f"title:{fullname}"),
            "isVisited": False,
            "title": f"Momcozy synthetic post {post_id}",
        }
        if title_with_thumbnail:
            title: dict[str, object] = {
                "__typename": "TitleWithThumbnailCell",
                "id": _encoded_reddit_id(f"title-thumbnail:{fullname}"),
                "indicatorsCell": None,
                "previewTextCell": None,
                "thumbnail": None,
                "titleCell": title_cell,
            }
        else:
            title = title_cell
        action = {
            "__typename": "ActionCell",
            "commentCount": 3,
            "goldenUpvoteInfo": None,
            "id": _encoded_reddit_id(f"action:{fullname}"),
            "isModeratable": False,
            "isScoreHidden": False,
            "isShareButtonHidden": False,
            "isTranslatable": False,
            "isTranslated": False,
            "score": 7,
            "shareCount": 0,
            "voteState": "NONE",
        }
        edges.append(
            {
                "__typename": "FeedElementEdge",
                "node": {
                    "__typename": "CellGroup",
                    "adPayload": None,
                    "cells": [metadata, title, action],
                    "crosspostCells": None,
                    "groupId": _encoded_reddit_id(fullname),
                    "groupRecommendationContext": None,
                    "id": _encoded_reddit_id(fullname),
                    "payload": None,
                },
            }
        )
    return {
        "data": {
            "subredditV3": {
                "elements": {
                    "dist": len(edges),
                    "edges": edges,
                    "pageInfo": {"endCursor": cursor},
                }
            }
        }
    }


def reviewed_subreddit_v3_cell_page(
    cell_types: tuple[str, ...],
    *,
    post_id: str = "reviewed123",
    subreddit: str = "ExclusivelyPumping",
) -> dict[str, object]:
    payload = subreddit_v3_page(
        "subreddit-cursor",
        subreddit=subreddit,
        posts=((post_id, False),),
    )
    node = payload["data"]["subredditV3"]["elements"]["edges"][0]["node"]
    original = {
        cell["__typename"]: cell
        for cell in node["cells"]
    }
    fullname = f"t3_{post_id}"
    reviewed_cells: dict[str, dict[str, object]] = {
        "MetadataCell": original["MetadataCell"],
        "TitleCell": original["TitleCell"],
        "FlairCell": {
            "__typename": "FlairCell",
            "flair": [],
            "id": _encoded_reddit_id(f"flair:{fullname}"),
        },
        "PreviewTextCell": {
            "__typename": "PreviewTextCell",
            "id": _encoded_reddit_id(f"preview:{fullname}"),
            "isRead": False,
            "text": "Synthetic preview",
        },
        "ImageCell": {
            "__typename": "ImageCell",
            "id": _encoded_reddit_id(f"image:{fullname}"),
            "media": {},
        },
        "GalleryCell": {
            "__typename": "GalleryCell",
            "height": 320,
            "id": _encoded_reddit_id(f"gallery:{fullname}"),
            "pages": [],
        },
        "EmptyContentCell": {"__typename": "EmptyContentCell"},
        "CrossPostCell": {
            "__typename": "CrossPostCell",
            "id": _encoded_reddit_id(f"crosspost:{fullname}"),
        },
        "ActionCell": original["ActionCell"],
        "MarginCell": {"__typename": "MarginCell"},
    }
    node["cells"] = [dict(reviewed_cells[name]) for name in cell_types]
    node["crosspostCells"] = []
    for name in cell_types:
        mirror: dict[str, object] = {"__typename": name}
        if name == "CrossPostCell":
            mirror["innerPost"] = {"id": fullname}
        node["crosspostCells"].append(mirror)
    return payload


def empty_subreddit_v3_page() -> dict[str, object]:
    return {"data": {"subredditV3": {"elements": None}}}


def collection_window() -> CollectionWindow:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 7, 11, tzinfo=timezone.utc)
    return CollectionWindow(
        timezone_name="UTC",
        run_at_local=end,
        start_local=start,
        end_local=end,
        start_utc=start,
        end_utc=end,
    )


class HydrationFakeTikHubClient:
    def __init__(self, responses):
        self.responses = dict(responses)
        self.calls: list[tuple[str, dict[str, object]]] = []

    @staticmethod
    def response_key(path: str, params: dict[str, object]):
        if path == FETCH_POST_DETAILS_BATCH_LARGE:
            return path, params.get("post_ids")
        if path == FETCH_POST_COMMENTS:
            return path, params.get("post_id"), params.get("after", "")
        return path,

    def get_json(self, path, params):
        copied = dict(params)
        self.calls.append((path, copied))
        key = self.response_key(path, copied)
        if key not in self.responses:
            raise AssertionError(f"unexpected fake TikHub request: {key!r}")
        outcome = self.responses[key]
        if isinstance(outcome, list):
            if not outcome:
                raise AssertionError(f"exhausted fake TikHub response: {key!r}")
            outcome = outcome.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def post_json(self, path, payload=None):
        raise AssertionError("TikHub hydration endpoints must use GET")


def detail_post(
    post_id: str,
    *,
    created_at: datetime | str | None = None,
    title: str | None = None,
    body: str = "",
    reported_comments: int = 0,
) -> dict[str, object]:
    created = created_at or (NOW - timedelta(days=1))
    if isinstance(created, datetime):
        created = created.isoformat()
    return {
        "id": f"t3_{post_id}",
        "createdAt": created,
        "postTitle": title or f"Momcozy wearable pump {post_id}",
        "url": f"https://www.reddit.com/r/ExclusivelyPumping/comments/{post_id}/title/",
        "content": {"markdown": body},
        "score": 7,
        "commentCount": reported_comments,
        "subreddit": {"name": "ExclusivelyPumping"},
        "authorInfo": {"name": "submitter"},
    }


def detail_response(*posts: dict[str, object]) -> dict[str, object]:
    return {"data": {"postsInfoByIds": list(posts)}}


def comment_tree(
    post_id: str,
    comment_id: str,
    body: str,
    *,
    created_at: datetime | str | None = None,
    parent_id: str | None = None,
    score: int = 3,
    depth: int = 0,
    author: str = "helper",
) -> dict[str, object]:
    created = created_at or NOW
    if isinstance(created, datetime):
        created = created.isoformat()
    return {
        "depth": depth,
        "parentId": parent_id or f"t3_{post_id}",
        "node": {
            "__typename": "Comment",
            "id": comment_id,
            "createdAt": created,
            "content": {"markdown": body},
            "authorInfo": {"name": author},
            "score": score,
        },
    }


def comment_response(
    post_id: str,
    cursor: str | None,
    *,
    trees: tuple[dict[str, object], ...] = (),
    unresolved_more: bool = False,
) -> dict[str, object]:
    forest = list(trees)
    if unresolved_more:
        forest.append({"node": {"__typename": "MoreComments"}})
    return {
        "data": {
            "postInfoById": {
                "id": f"t3_{post_id}",
                "commentForest": {"trees": forest},
            },
            "pageInfo": {
                "hasNextPage": cursor is not None,
                "endCursor": cursor,
            },
        }
    }


def comment_contract() -> CursorContract:
    return infer_cursor_contract(comment_response("probe", "probe-cursor"))


def current_comment_response(
    post_id: str,
    *,
    trees: tuple[dict[str, object], ...] = (),
) -> dict[str, object]:
    return {
        "data": {
            "postInfoById": {
                "id": f"t3_{post_id}",
                "commentForest": {
                    "__typename": "CommentForest",
                    "pageInfo": {
                        "commentCount": len(trees),
                        "hasNextPage": False,
                    },
                    "trees": list(trees),
                },
            }
        }
    }


def current_nonterminal_missing_cursor_response(
    post_id: str,
    *,
    trees: tuple[dict[str, object], ...] = (),
    include_more: bool = True,
) -> dict[str, object]:
    forest = list(trees)
    if include_more:
        forest.append(
            {
                "childCount": 1,
                "depth": 0,
                "more": {"children": []},
                "node": None,
                "parentId": f"t3_{post_id}",
            }
        )
    payload = current_comment_response(post_id, trees=tuple(forest))
    payload["data"]["postInfoById"]["commentForest"]["pageInfo"][
        "hasNextPage"
    ] = True
    return payload


def current_comment_contract() -> CursorContract:
    return CursorContract(
        cursor_path=(
            "data",
            "postInfoById",
            "commentForest",
            "pageInfo",
            "endCursor",
        ),
        schema_sha256=(
            "67c3b44ef86da5d844320d676e6a6e6cc0dccfc1e94b4509b9cb0ce89ff5edc1"
        ),
    )


class TikHubBackfillDiscovererTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        self.store = BackfillStore(root / "backfill.sqlite3")
        self.store.migrate()
        self.store.create_manifest(make_manifest(max_provider_requests=10))
        self.archive = PrivateRawArchive(root / "raw")
        self.reset_counter = 0

    def reset_store(self, *, budget: int) -> None:
        root = Path(self.temporary_directory.name)
        self.reset_counter += 1
        self.store = BackfillStore(
            root / f"backfill-{self.reset_counter}-{budget}.sqlite3"
        )
        self.store.migrate()
        self.store.create_manifest(make_manifest(max_provider_requests=budget))
        self.archive = PrivateRawArchive(root / f"raw-{budget}")

    def make_discoverer(self, client, *, request_ceiling: int | None = None):
        executor = TikHubRequestExecutor(
            client,
            self.store,
            "backfill_provider_test",
            sleep=lambda _: None,
            now=lambda: NOW,
            request_ceiling=request_ceiling,
        )
        return TikHubBackfillDiscoverer(
            executor,
            self.store,
            self.archive,
            "backfill_provider_test",
            now=lambda: NOW,
        )

    def save_discovery_checkpoint(
        self,
        *,
        page_number: int,
        status: str,
        stop_reason: str | None,
        last_error: str | None = None,
    ) -> BackfillCheckpoint:
        checkpoint = BackfillCheckpoint(
            run_id="backfill_provider_test",
            lane_type="dynamic_search",
            lane_key="Momcozy",
            cursor=None if stop_reason == "cursor_exhausted" else "saved-cursor",
            previous_cursor=None,
            page_number=page_number,
            newest_seen_utc=NOW.isoformat() if page_number else None,
            oldest_seen_utc=NOW.isoformat() if page_number else None,
            discovered_count=page_number,
            unique_count=page_number,
            provider_request_count=0,
            last_success_utc=NOW.isoformat() if page_number else None,
            last_error=last_error,
            status=status,
            stop_reason=stop_reason,
            cursor_json_path=(
                '["data","search","dynamic","components","main",'
                '"pageInfo","endCursor"]'
                if page_number
                else None
            ),
            cursor_schema_sha256="a" * 64 if page_number else None,
            consecutive_old_pages=0,
        )
        self.store.save_checkpoint(checkpoint)
        return checkpoint

    def test_dynamic_two_page_discovery_records_each_appearance_before_dedupe(self):
        first = discovery_page(
            "cursor-1",
            [
                discovery_post("post-1", "2026-07-01T00:00:00Z"),
                discovery_post("post-1", "2026-07-01T00:00:00Z"),
                discovery_post("invalid-time", None),
            ],
        )
        second = discovery_page(
            None,
            [
                discovery_post("post-1", "2026-07-01T00:00:00Z"),
                discovery_post("post-2", "2026-06-01T00:00:00Z"),
            ],
        )
        client = KeyedFakeTikHubClient(
            {
                (FETCH_DYNAMIC_SEARCH, ""): first,
                (FETCH_DYNAMIC_SEARCH, "cursor-1"): second,
            }
        )

        result = self.make_discoverer(client).run_dynamic_search(
            "Momcozy", collection_window()
        )

        self.assertEqual(result.status, "complete")
        self.assertEqual(result.stop_reason, "cursor_exhausted")
        self.assertEqual(result.pages, 2)
        self.assertEqual(result.discovered_occurrences, 5)
        self.assertEqual(result.unique_candidates, 2)
        self.assertEqual(result.provider_request_count, 2)
        self.assertTrue(result.provider_call)
        self.assertFalse(result.live_send)
        self.assertEqual(
            self.store.discovery_occurrence_counts(
                "backfill_provider_test", "dynamic_search", "Momcozy"
            ),
            {
                "new_candidate": 2,
                "duplicate_occurrence": 2,
                "invalid": 1,
            },
        )
        self.assertEqual(self.store.candidate_count("backfill_provider_test"), 2)
        self.assertEqual(
            client.calls,
            [
                (
                    FETCH_DYNAMIC_SEARCH,
                    {
                        "query": "Momcozy",
                        "search_type": "post",
                        "sort": "NEW",
                        "time_range": "all",
                        "after": "",
                        "need_format": "false",
                    },
                ),
                (
                    FETCH_DYNAMIC_SEARCH,
                    {
                        "query": "Momcozy",
                        "search_type": "post",
                        "sort": "NEW",
                        "time_range": "all",
                        "after": "cursor-1",
                        "need_format": "false",
                    },
                ),
            ],
        )
        checkpoint = self.store.load_checkpoint(
            run_id="backfill_provider_test",
            lane_type="dynamic_search",
            lane_key="Momcozy",
        )
        self.assertEqual(checkpoint.status, "complete")
        self.assertEqual(checkpoint.page_number, 2)
        self.assertEqual(checkpoint.stop_reason, "cursor_exhausted")
        self.assertIsNone(checkpoint.cursor)
        self.assertEqual(
            checkpoint.cursor_json_path,
            '["data","search","dynamic","components","main","pageInfo","endCursor"]',
        )
        self.assertEqual(len(checkpoint.cursor_schema_sha256), 64)
        with self.store.connect() as conn:
            raw_rows = conn.execute(
                "SELECT source_url, raw_payload_hash "
                "FROM raw_captures ORDER BY raw_capture_id"
            ).fetchall()
            artifact_rows = conn.execute(
                "SELECT source_endpoint, response_cursor, parser_kind "
                "FROM backfill_raw_artifacts ORDER BY page_number"
            ).fetchall()
        self.assertEqual(len(raw_rows), 2)
        self.assertTrue(all(row["source_url"].startswith("tikhub://") for row in raw_rows))
        self.assertTrue(
            all(
                row["source_endpoint"] == FETCH_DYNAMIC_SEARCH
                for row in artifact_rows
            )
        )
        self.assertEqual(
            [row["response_cursor"] for row in artifact_rows], ["cursor-1", None]
        )
        self.assertEqual(
            {row["parser_kind"] for row in artifact_rows},
            {"tikhub_discovery_strict_v2"},
        )

    def test_subreddit_v3_page_records_reviewed_title_variants(self):
        payload = subreddit_v3_page(
            "subreddit-cursor",
            posts=(("plain123", False), ("thumb456", True)),
        )
        client = KeyedFakeTikHubClient({(FETCH_SUBREDDIT_FEED, ""): payload})

        result = self.make_discoverer(client).run_subreddit_feed(
            "ExclusivelyPumping", collection_window(), max_pages=1
        )

        self.assertEqual(
            (result.status, result.stop_reason, result.pages),
            ("partial", "probe_page_limit", 1),
        )
        self.assertEqual(result.discovered_occurrences, 2)
        self.assertEqual(result.unique_candidates, 2)
        self.assertEqual(
            client.calls,
            [
                (
                    FETCH_SUBREDDIT_FEED,
                    {
                        "subreddit_name": "ExclusivelyPumping",
                        "sort": "NEW",
                        "after": "",
                        "need_format": "false",
                    },
                )
            ],
        )
        checkpoint = self.store.load_checkpoint(
            run_id="backfill_provider_test",
            lane_type="subreddit_feed",
            lane_key="ExclusivelyPumping",
        )
        self.assertEqual(
            checkpoint.cursor_json_path,
            '["data","subredditV3","elements","pageInfo","endCursor"]',
        )
        self.assertEqual(
            checkpoint.cursor_schema_sha256,
            "3bc27a141e675230d962942491bb87b8378a956142a75bfc79a631f10b479dbf",
        )

    def test_subreddit_v3_accepts_reviewed_real_cell_sequences_and_mirrors(self):
        reviewed_sequences = (
            ("MetadataCell", "TitleCell", "CrossPostCell", "ActionCell", "MarginCell"),
            ("MetadataCell", "TitleCell", "EmptyContentCell", "ActionCell", "MarginCell"),
            (
                "MetadataCell",
                "TitleCell",
                "FlairCell",
                "EmptyContentCell",
                "ActionCell",
                "MarginCell",
            ),
            (
                "MetadataCell",
                "TitleCell",
                "FlairCell",
                "GalleryCell",
                "ActionCell",
                "MarginCell",
            ),
            (
                "MetadataCell",
                "TitleCell",
                "FlairCell",
                "ImageCell",
                "ActionCell",
                "MarginCell",
            ),
            (
                "MetadataCell",
                "TitleCell",
                "FlairCell",
                "PreviewTextCell",
                "ActionCell",
                "MarginCell",
            ),
            ("MetadataCell", "TitleCell", "GalleryCell", "ActionCell", "MarginCell"),
            ("MetadataCell", "TitleCell", "ImageCell", "ActionCell", "MarginCell"),
            (
                "MetadataCell",
                "TitleCell",
                "PreviewTextCell",
                "ActionCell",
                "MarginCell",
            ),
        )
        for index, sequence in enumerate(reviewed_sequences):
            with self.subTest(sequence=sequence):
                payload = reviewed_subreddit_v3_cell_page(
                    sequence, post_id=f"reviewed{index}"
                )
                records = backfill_provider._extract_backfill_discovery_posts(
                    payload,
                    "tikhub_subreddit_feed",
                    lane_key="ExclusivelyPumping",
                )
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0].post_id, f"reviewed{index}")

    def test_subreddit_v3_real_cell_contract_rejects_mirror_and_key_drift(self):
        sequence = (
            "MetadataCell",
            "TitleCell",
            "FlairCell",
            "PreviewTextCell",
            "ActionCell",
            "MarginCell",
        )
        payloads = []

        mirror_type_drift = reviewed_subreddit_v3_cell_page(sequence)
        mirror_type_drift["data"]["subredditV3"]["elements"]["edges"][0][
            "node"
        ]["crosspostCells"][2]["__typename"] = "ImageCell"
        payloads.append(mirror_type_drift)

        mirror_key_drift = reviewed_subreddit_v3_cell_page(sequence)
        mirror_key_drift["data"]["subredditV3"]["elements"]["edges"][0][
            "node"
        ]["crosspostCells"][2]["unreviewed"] = True
        payloads.append(mirror_key_drift)

        main_key_drift = reviewed_subreddit_v3_cell_page(sequence)
        main_key_drift["data"]["subredditV3"]["elements"]["edges"][0][
            "node"
        ]["cells"][2]["unreviewed"] = True
        payloads.append(main_key_drift)

        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaises(
                TikHubDiscoveryShapeError
            ):
                backfill_provider._extract_backfill_discovery_posts(
                    payload,
                    "tikhub_subreddit_feed",
                    lane_key="ExclusivelyPumping",
                )

    def test_subreddit_v3_none_elements_is_reviewed_terminal_empty_page(self):
        client = KeyedFakeTikHubClient(
            {(FETCH_SUBREDDIT_FEED, ""): empty_subreddit_v3_page()}
        )

        result = self.make_discoverer(client).run_subreddit_feed(
            "breastpumps", collection_window()
        )

        self.assertEqual(
            (result.status, result.stop_reason, result.pages),
            ("complete", "cursor_exhausted", 1),
        )
        self.assertEqual(result.discovered_occurrences, 0)
        self.assertEqual(result.unique_candidates, 0)
        checkpoint = self.store.load_checkpoint(
            run_id="backfill_provider_test",
            lane_type="subreddit_feed",
            lane_key="breastpumps",
        )
        self.assertEqual(
            checkpoint.cursor_json_path,
            '["data","subredditV3","elements","pageInfo","endCursor"]',
        )

    def test_subreddit_v3_invalid_base64_identity_archives_then_fails_closed(self):
        payload = subreddit_v3_page("subreddit-cursor")
        payload["data"]["subredditV3"]["elements"]["edges"][0]["node"][
            "id"
        ] = "not-base64"
        client = KeyedFakeTikHubClient({(FETCH_SUBREDDIT_FEED, ""): payload})

        result = self.make_discoverer(client).run_subreddit_feed(
            "ExclusivelyPumping", collection_window(), max_pages=1
        )

        self.assertEqual(
            (result.status, result.stop_reason, result.pages),
            ("partial", "schema_drift", 0),
        )
        self.assertEqual(
            self.store.raw_artifact_count(
                "backfill_provider_test", ("subreddit_feed",)
            ),
            1,
        )

    def test_dynamic_discovery_ignores_nested_metadata_identity_fields(self):
        payload = verified_dynamic_discovery_page(
            "cursor-1", [discovery_post("actual-post", "2026-07-01T00:00:00Z")]
        )
        child = payload["data"]["search"]["dynamic"]["components"]["main"][
            "edges"
        ][0]["node"]["children"][0]
        child["metadata"] = {
            "id": "metadata-id-must-not-be-a-post",
            "url": "https://example.invalid/not-a-reddit-post",
        }
        client = KeyedFakeTikHubClient({(FETCH_DYNAMIC_SEARCH, ""): payload})

        result = self.make_discoverer(client).run_dynamic_search(
            "Momcozy", collection_window(), max_pages=1
        )

        self.assertEqual(
            (result.status, result.stop_reason), ("partial", "probe_page_limit")
        )
        self.assertEqual(result.discovered_occurrences, 1)
        self.assertEqual(result.unique_candidates, 1)
        self.assertEqual(
            self.store.discovery_occurrence_counts(
                "backfill_provider_test", "dynamic_search", "Momcozy"
            ),
            {"new_candidate": 1},
        )

    def test_dynamic_discovery_unknown_post_container_archives_then_fails_closed(self):
        payload = verified_dynamic_discovery_page("cursor-1", [])
        payload["data"]["search"]["legacy"] = discovery_post(
            "legacy-post", "2026-07-01T00:00:00Z"
        )
        client = KeyedFakeTikHubClient({(FETCH_DYNAMIC_SEARCH, ""): payload})

        result = self.make_discoverer(client).run_dynamic_search(
            "Momcozy", collection_window(), max_pages=1
        )

        self.assertEqual(
            (result.status, result.stop_reason), ("partial", "schema_drift")
        )
        self.assertEqual(result.pages, 0)
        self.assertEqual(result.discovered_occurrences, 0)
        self.assertEqual(self.store.candidate_count("backfill_provider_test"), 0)
        self.assertEqual(
            self.store.raw_artifact_count(
                "backfill_provider_test", ("dynamic_search",)
            ),
            1,
        )

    def test_discovery_occurrence_ordinals_follow_reviewed_search_post_list_order(
        self,
    ):
        payload = discovery_page(
            "cursor-1",
            [
                discovery_post("z-list-first", "2026-07-01T00:00:00Z"),
                discovery_post("a-list-second", "2026-07-01T00:00:00Z"),
            ],
        )
        client = KeyedFakeTikHubClient(
            {(FETCH_DYNAMIC_SEARCH, ""): payload}
        )

        result = self.make_discoverer(client).run_dynamic_search(
            "Momcozy", collection_window(), max_pages=1
        )

        self.assertEqual(
            (result.status, result.stop_reason), ("partial", "probe_page_limit")
        )
        self.assertEqual(result.discovered_occurrences, 2)
        with self.store.connect() as connection:
            rows = connection.execute(
                "SELECT ordinal, post_id "
                "FROM backfill_discovery_occurrences "
                "WHERE run_id=? AND lane_type=? AND lane_key=? "
                "ORDER BY ordinal",
                ("backfill_provider_test", "dynamic_search", "Momcozy"),
            ).fetchall()
        self.assertEqual(
            [(row["ordinal"], row["post_id"]) for row in rows],
            [(0, "z-list-first"), (1, "a-list-second")],
        )

    def test_lane_result_contract_and_saved_cursor_resume_use_persisted_schema(self):
        terminal = discovery_page(
            None, [discovery_post("resumed-post", "2026-06-01T00:00:00Z")]
        )
        contract_payload = discovery_page(
            "contract-cursor",
            [discovery_post("contract-only", "2026-06-01T00:00:00Z")],
        )
        contract = infer_cursor_contract(contract_payload)
        checkpoint = BackfillCheckpoint(
            run_id="backfill_provider_test",
            lane_type="dynamic_search",
            lane_key="Momcozy",
            cursor="saved-cursor",
            previous_cursor="older-cursor",
            page_number=3,
            newest_seen_utc="2026-06-02T00:00:00+00:00",
            oldest_seen_utc="2026-05-01T00:00:00+00:00",
            discovered_count=4,
            unique_count=3,
            provider_request_count=0,
            last_success_utc=NOW.isoformat(),
            last_error=None,
            status="partial",
            stop_reason="probe_page_limit",
            cursor_json_path=(
                '["data","search","dynamic","components","main",'
                '"pageInfo","endCursor"]'
            ),
            cursor_schema_sha256=contract.schema_sha256,
            consecutive_old_pages=0,
        )
        self.store.save_checkpoint(checkpoint)
        client = KeyedFakeTikHubClient(
            {(FETCH_DYNAMIC_SEARCH, "saved-cursor"): terminal}
        )

        result = self.make_discoverer(client).run_dynamic_search(
            "Momcozy", collection_window()
        )

        self.assertEqual(
            tuple(field.name for field in fields(LaneResult)),
            (
                "run_id",
                "lane_type",
                "lane_key",
                "status",
                "stop_reason",
                "pages",
                "discovered_occurrences",
                "unique_candidates",
                "provider_request_count",
                "provider_call",
                "live_send",
            ),
        )
        self.assertTrue(LaneResult.__dataclass_params__.frozen)
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.stop_reason, "cursor_exhausted")
        self.assertEqual(result.pages, 4)
        self.assertEqual(client.calls[0][1]["after"], "saved-cursor")
        saved = self.store.load_checkpoint(
            run_id="backfill_provider_test",
            lane_type="dynamic_search",
            lane_key="Momcozy",
        )
        self.assertEqual(saved.previous_cursor, "saved-cursor")
        self.assertEqual(saved.cursor_schema_sha256, contract.schema_sha256)

    def test_repeated_cursor_stops_partial_after_committing_the_page(self):
        client = KeyedFakeTikHubClient(
            {
                (FETCH_DYNAMIC_SEARCH, ""): discovery_page(
                    "cursor-1",
                    [discovery_post("post-1", "2026-07-01T00:00:00Z")],
                ),
                (FETCH_DYNAMIC_SEARCH, "cursor-1"): discovery_page(
                    "cursor-1",
                    [discovery_post("post-2", "2026-06-01T00:00:00Z")],
                ),
            }
        )

        result = self.make_discoverer(client).run_dynamic_search(
            "Momcozy", collection_window()
        )

        self.assertEqual(result.status, "partial")
        self.assertEqual(result.stop_reason, "cursor_loop")
        self.assertEqual(result.pages, 2)
        self.assertEqual(result.discovered_occurrences, 2)
        self.assertEqual(self.store.candidate_count("backfill_provider_test"), 2)

    def test_two_consecutive_old_pages_complete_without_fetching_a_third(self):
        client = KeyedFakeTikHubClient(
            {
                (FETCH_DYNAMIC_SEARCH, ""): discovery_page(
                    "cursor-1",
                    [discovery_post("old-1", "2024-12-01T00:00:00Z")],
                ),
                (FETCH_DYNAMIC_SEARCH, "cursor-1"): discovery_page(
                    "cursor-2",
                    [discovery_post("old-2", "2024-11-01T00:00:00Z")],
                ),
            }
        )

        result = self.make_discoverer(client).run_dynamic_search(
            "Momcozy", collection_window()
        )

        self.assertEqual(result.status, "complete")
        self.assertEqual(result.stop_reason, "older_than_window")
        self.assertEqual(result.pages, 2)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(result.unique_candidates, 0)
        checkpoint = self.store.load_checkpoint(
            run_id="backfill_provider_test",
            lane_type="dynamic_search",
            lane_key="Momcozy",
        )
        self.assertEqual(checkpoint.consecutive_old_pages, 2)
        self.assertEqual(checkpoint.cursor, "cursor-2")

    def test_feed_uses_exact_params_but_unreviewed_shape_fails_closed(self):
        client = KeyedFakeTikHubClient(
            {
                (FETCH_SUBREDDIT_FEED, ""): discovery_page(
                    "feed-cursor",
                    [discovery_post("feed-1", "2026-07-01T00:00:00Z")],
                ),
                (FETCH_SUBREDDIT_FEED, "feed-cursor"): discovery_page(
                    None,
                    [discovery_post("feed-2", "2026-06-01T00:00:00Z")],
                ),
            }
        )

        result = self.make_discoverer(client).run_subreddit_feed(
            "ExclusivelyPumping", collection_window()
        )

        self.assertEqual((result.status, result.stop_reason), ("partial", "schema_drift"))
        self.assertEqual(result.lane_type, "subreddit_feed")
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(
            client.calls[0],
            (
                FETCH_SUBREDDIT_FEED,
                {
                    "subreddit_name": "ExclusivelyPumping",
                    "sort": "NEW",
                    "after": "",
                    "need_format": "false",
                },
            ),
        )
        self.assertNotIn("limit", client.calls[0][1])

    def test_occurrence_equation_includes_outside_invalid_and_structured_duplicate(self):
        capture = RawCapture(
            raw_capture_id="raw-structured",
            run_id="backfill_provider_test",
            source_method="historical_seed",
            source_url="seed://structured",
            captured_at_utc=NOW,
            auth_boundary="local_seed",
            raw_payload_hash="sha256:" + "e" * 64,
            payload_format="json",
        )
        thread = RedditThread(
            post_id="structured",
            run_id="backfill_provider_test",
            raw_capture_id=capture.raw_capture_id,
            subreddit="ExclusivelyPumping",
            title="Momcozy structured",
            selftext="body",
            source_url="https://www.reddit.com/r/test/comments/structured/title/",
            created_at_utc=datetime(2026, 6, 1, tzinfo=timezone.utc),
            score=None,
            num_comments_reported=0,
            parsed_comment_count=0,
            more_node_count=0,
            coverage_grade="post_only",
            matched_keywords=("Momcozy",),
        )
        self.store.insert_entity_bundle(
            captures=(capture,), threads=(thread,), comments=(), analyses=()
        )
        client = KeyedFakeTikHubClient(
            {
                (FETCH_DYNAMIC_SEARCH, ""): discovery_page(
                    "cursor-1",
                    [
                        discovery_post("new", "2026-06-01T00:00:00Z"),
                        discovery_post("outside", "2024-01-01T00:00:00Z"),
                        discovery_post("invalid", None),
                        {
                            "post": {
                                "id": "t3_missing-url",
                                "postTitle": "broken provider row",
                                "createdAt": "2026-06-01T00:00:00Z",
                            }
                        },
                        {"post": {"id": "", "postTitle": "", "url": ""}},
                        {
                            "post": {
                                "id": "t3_missing-title",
                                "postTitle": "",
                                "url": (
                                    "https://www.reddit.com/r/ExclusivelyPumping/"
                                    "comments/missing-title/title/"
                                ),
                                "createdAt": "2026-06-01T00:00:00Z",
                            }
                        },
                        discovery_post("structured", "2026-06-01T00:00:00Z"),
                    ],
                ),
                (FETCH_DYNAMIC_SEARCH, "cursor-1"): discovery_page(
                    None, [discovery_post("new", "2026-06-01T00:00:00Z")]
                ),
            }
        )

        result = self.make_discoverer(client).run_dynamic_search(
            "Momcozy", collection_window()
        )

        counts = self.store.discovery_occurrence_counts(
            "backfill_provider_test", "dynamic_search", "Momcozy"
        )
        self.assertEqual(
            counts,
            {
                "new_candidate": 1,
                "duplicate_occurrence": 1,
                "outside_window": 1,
                "duplicate_existing_structured": 1,
                "invalid": 4,
            },
        )
        with sqlite3.connect(self.store.path) as connection:
            invalid_rows = connection.execute(
                "SELECT ordinal, post_id, source_url, post_created_at_utc, disposition "
                "FROM backfill_discovery_occurrences "
                "WHERE run_id='backfill_provider_test' "
                "AND lane_type='dynamic_search' AND lane_key='Momcozy' "
                "AND disposition='invalid' ORDER BY page_number, ordinal"
            ).fetchall()
        self.assertEqual(
            invalid_rows,
            [
                (
                    2,
                    "invalid",
                    (
                        "https://www.reddit.com/r/ExclusivelyPumping/"
                        "comments/invalid/title/"
                    ),
                    None,
                    "invalid",
                ),
                (
                    3,
                    "missing-url",
                    None,
                    "2026-06-01T00:00:00+00:00",
                    "invalid",
                ),
                (4, None, None, None, "invalid"),
                (
                    5,
                    "missing-title",
                    (
                        "https://www.reddit.com/r/ExclusivelyPumping/"
                        "comments/missing-title/title/"
                    ),
                    "2026-06-01T00:00:00+00:00",
                    "invalid",
                ),
            ],
        )
        self.assertEqual(result.discovered_occurrences, sum(counts.values()))
        self.assertEqual(result.unique_candidates, 1)
        self.assertEqual(self.store.candidate_count("backfill_provider_test"), 1)

    def test_probe_page_limit_and_budget_exhaustion_save_resumable_cursor(self):
        probe_client = KeyedFakeTikHubClient(
            {
                (FETCH_DYNAMIC_SEARCH, ""): discovery_page(
                    "cursor-1",
                    [discovery_post("post-1", "2026-07-01T00:00:00Z")],
                )
            }
        )
        result = self.make_discoverer(probe_client).run_dynamic_search(
            "Momcozy", collection_window(), max_pages=1
        )
        self.assertEqual((result.status, result.stop_reason), ("partial", "probe_page_limit"))
        checkpoint = self.store.load_checkpoint(
            run_id="backfill_provider_test",
            lane_type="dynamic_search",
            lane_key="Momcozy",
        )
        self.assertEqual(checkpoint.cursor, "cursor-1")

        self.reset_store(budget=1)
        budget_client = KeyedFakeTikHubClient(
            {
                (FETCH_DYNAMIC_SEARCH, ""): discovery_page(
                    "cursor-1",
                    [discovery_post("post-1", "2026-07-01T00:00:00Z")],
                )
            }
        )
        result = self.make_discoverer(budget_client).run_dynamic_search(
            "Momcozy", collection_window()
        )
        self.assertEqual(
            (result.status, result.stop_reason),
            ("partial", "budget_exhausted"),
        )
        self.assertEqual(result.pages, 1)
        self.assertEqual(result.provider_request_count, 1)
        self.assertTrue(result.provider_call)
        checkpoint = self.store.load_checkpoint(
            run_id="backfill_provider_test",
            lane_type="dynamic_search",
            lane_key="Momcozy",
        )
        self.assertEqual(checkpoint.cursor, "cursor-1")

    def test_round_robin_and_authorized_page_limits_are_distinct_and_resumable(self):
        client = KeyedFakeTikHubClient(
            {
                (FETCH_DYNAMIC_SEARCH, ""): discovery_page(
                    "round-robin-cursor",
                    [discovery_post("round-robin-post", "2026-07-01T00:00:00Z")],
                ),
                (FETCH_DYNAMIC_SEARCH, "round-robin-cursor"): discovery_page(
                    "authorized-cursor",
                    [discovery_post("authorized-post", "2026-06-01T00:00:00Z")],
                ),
            }
        )
        discoverer = self.make_discoverer(client)

        round_robin = discoverer.run_dynamic_search(
            "Momcozy",
            collection_window(),
            max_pages=1,
            absolute_page_ceiling=2,
            page_limit_stop_reason="round_robin_yield",
        )

        self.assertEqual(
            (round_robin.status, round_robin.stop_reason),
            ("partial", "round_robin_yield"),
        )
        self.assertEqual(round_robin.pages, 1)

        authorized = discoverer.run_dynamic_search(
            "Momcozy",
            collection_window(),
            max_pages=1,
            absolute_page_ceiling=2,
            page_limit_stop_reason="round_robin_yield",
        )

        self.assertEqual(
            (authorized.status, authorized.stop_reason),
            ("partial", "authorized_page_limit"),
        )
        self.assertEqual(authorized.pages, 2)
        self.assertEqual(authorized.provider_request_count, 2)
        self.assertEqual(len(client.calls), 2)

        restart_client = KeyedFakeTikHubClient({})
        restarted = self.make_discoverer(restart_client).run_dynamic_search(
            "Momcozy",
            collection_window(),
            max_pages=1,
            absolute_page_ceiling=2,
            page_limit_stop_reason="round_robin_yield",
        )

        self.assertEqual(
            (restarted.status, restarted.stop_reason, restarted.pages),
            ("partial", "authorized_page_limit", 2),
        )
        self.assertEqual(restart_client.calls, [])
        self.assertEqual(restarted.provider_request_count, 2)

    def test_absolute_ceiling_preserves_terminal_checkpoint_without_request(self):
        terminal_cases = (
            ("complete", "cursor_exhausted", None),
            ("failed", "manual_failure", "ManualFailure"),
            ("partial", "provider_error", "HTTPError"),
            ("partial", "schema_drift", "TikHubSchemaDrift"),
            ("partial", "cursor_loop", None),
        )
        for status, stop_reason, last_error in terminal_cases:
            with self.subTest(status=status, stop_reason=stop_reason):
                self.reset_store(budget=10)
                original = self.save_discovery_checkpoint(
                    page_number=1,
                    status=status,
                    stop_reason=stop_reason,
                    last_error=last_error,
                )
                client = KeyedFakeTikHubClient({})

                result = self.make_discoverer(client).run_dynamic_search(
                    "Momcozy",
                    collection_window(),
                    max_pages=1,
                    absolute_page_ceiling=1,
                    page_limit_stop_reason="round_robin_yield",
                )

                self.assertEqual(
                    (result.status, result.stop_reason), (status, stop_reason)
                )
                self.assertEqual(client.calls, [])
                self.assertEqual(
                    self.store.load_checkpoint(
                        run_id="backfill_provider_test",
                        lane_type="dynamic_search",
                        lane_key="Momcozy",
                    ),
                    original,
                )

    def test_absolute_ceiling_relabels_only_recoverable_checkpoint_states(self):
        recoverable_cases = (
            ("running", None, None),
            ("partial", "probe_page_limit", None),
            ("partial", "round_robin_yield", None),
            ("partial", "authorized_page_limit", None),
            ("partial", "budget_exhausted", "ProviderBudgetExhausted"),
            (
                "partial",
                "discovery_budget_exhausted",
                "ProviderPhaseBudgetExhausted",
            ),
        )
        for status, stop_reason, last_error in recoverable_cases:
            with self.subTest(status=status, stop_reason=stop_reason):
                self.reset_store(budget=10)
                self.save_discovery_checkpoint(
                    page_number=1,
                    status=status,
                    stop_reason=stop_reason,
                    last_error=last_error,
                )
                client = KeyedFakeTikHubClient({})

                result = self.make_discoverer(client).run_dynamic_search(
                    "Momcozy",
                    collection_window(),
                    max_pages=1,
                    absolute_page_ceiling=1,
                    page_limit_stop_reason="round_robin_yield",
                )

                checkpoint = self.store.load_checkpoint(
                    run_id="backfill_provider_test",
                    lane_type="dynamic_search",
                    lane_key="Momcozy",
                )
                self.assertEqual(
                    (result.status, result.stop_reason),
                    ("partial", "authorized_page_limit"),
                )
                self.assertEqual(checkpoint.status, "partial")
                self.assertEqual(checkpoint.stop_reason, "authorized_page_limit")
                self.assertIsNone(checkpoint.last_error)
                self.assertEqual(client.calls, [])

    def test_absolute_ceiling_below_checkpoint_fails_closed_without_request(self):
        for status, stop_reason in (
            ("partial", "round_robin_yield"),
            ("complete", "cursor_exhausted"),
            ("failed", "provider_error"),
        ):
            with self.subTest(status=status, stop_reason=stop_reason):
                self.reset_store(budget=10)
                original = self.save_discovery_checkpoint(
                    page_number=2,
                    status=status,
                    stop_reason=stop_reason,
                )
                client = KeyedFakeTikHubClient({})

                with self.assertRaises(BackfillConflictError):
                    self.make_discoverer(client).run_dynamic_search(
                        "Momcozy",
                        collection_window(),
                        max_pages=1,
                        absolute_page_ceiling=1,
                        page_limit_stop_reason="round_robin_yield",
                    )

                self.assertEqual(client.calls, [])
                self.assertEqual(
                    self.store.load_checkpoint(
                        run_id="backfill_provider_test",
                        lane_type="dynamic_search",
                        lane_key="Momcozy",
                    ),
                    original,
                )

    def test_discovery_phase_budget_exhaustion_has_dedicated_stop_reason(self):
        client = KeyedFakeTikHubClient(
            {
                (FETCH_DYNAMIC_SEARCH, ""): discovery_page(
                    "cursor-1",
                    [discovery_post("post-1", "2026-07-01T00:00:00Z")],
                )
            }
        )

        result = self.make_discoverer(
            client, request_ceiling=1
        ).run_dynamic_search("Momcozy", collection_window())

        self.assertEqual(
            (result.status, result.stop_reason),
            ("partial", "discovery_budget_exhausted"),
        )
        self.assertEqual(result.pages, 1)
        self.assertEqual(result.provider_request_count, 1)
        self.assertEqual(len(client.calls), 1)
        checkpoint = self.store.load_checkpoint(
            run_id="backfill_provider_test",
            lane_type="dynamic_search",
            lane_key="Momcozy",
        )
        self.assertEqual(checkpoint.last_error, "ProviderPhaseBudgetExhausted")

    def test_page_ceiling_and_stop_reason_arguments_fail_closed_before_request(self):
        invalid_cases = (
            {"absolute_page_ceiling": True},
            {"absolute_page_ceiling": -1},
            {"absolute_page_ceiling": 1.5},
            {"page_limit_stop_reason": "budget_exhausted"},
            {"page_limit_stop_reason": "authorized_page_limit"},
            {"page_limit_stop_reason": "authorized_page_limit "},
        )
        for index, kwargs in enumerate(invalid_cases):
            with self.subTest(index=index, kwargs=kwargs):
                client = KeyedFakeTikHubClient({})

                with self.assertRaises(ValueError):
                    self.make_discoverer(client).run_dynamic_search(
                        "Momcozy", collection_window(), **kwargs
                    )

                self.assertEqual(client.calls, [])

    def test_schema_drift_archives_raw_with_null_response_cursor_and_trusts_saved_contract(self):
        client = KeyedFakeTikHubClient(
            {(FETCH_DYNAMIC_SEARCH, ""): {"data": {"unexpected": []}}}
        )
        result = self.make_discoverer(client).run_dynamic_search(
            "Momcozy", collection_window()
        )
        self.assertEqual((result.status, result.stop_reason), ("partial", "schema_drift"))
        self.assertEqual(result.pages, 0)
        with self.store.connect() as conn:
            artifact = conn.execute(
                "SELECT response_cursor FROM backfill_raw_artifacts"
            ).fetchone()
            raw_count = conn.execute("SELECT COUNT(*) FROM raw_captures").fetchone()[0]
        self.assertIsNone(artifact["response_cursor"])
        self.assertEqual(raw_count, 1)

        self.reset_store(budget=2)
        wrong_contract = BackfillCheckpoint(
            run_id="backfill_provider_test",
            lane_type="dynamic_search",
            lane_key="Momcozy",
            cursor="saved",
            previous_cursor=None,
            page_number=1,
            newest_seen_utc=None,
            oldest_seen_utc=None,
            discovered_count=0,
            unique_count=0,
            provider_request_count=0,
            last_success_utc=None,
            last_error=None,
            status="partial",
            stop_reason="probe_page_limit",
            cursor_json_path='["wrong","pageInfo","endCursor"]',
            cursor_schema_sha256="0" * 64,
            consecutive_old_pages=0,
        )
        self.store.save_checkpoint(wrong_contract)
        valid_payload = discovery_page(
            "next", [discovery_post("post-1", "2026-07-01T00:00:00Z")]
        )
        client = KeyedFakeTikHubClient(
            {(FETCH_DYNAMIC_SEARCH, "saved"): valid_payload}
        )
        result = self.make_discoverer(client).run_dynamic_search(
            "Momcozy", collection_window()
        )
        self.assertEqual((result.status, result.stop_reason), ("partial", "schema_drift"))
        self.assertEqual(result.pages, 1)
        self.assertEqual(self.store.candidate_count("backfill_provider_test"), 0)

    def test_post_parser_exception_is_persisted_as_schema_drift_lineage(self):
        payload = discovery_page(
            "cursor-1",
            [discovery_post("overflow-time", "1e100")],
        )
        client = KeyedFakeTikHubClient(
            {(FETCH_DYNAMIC_SEARCH, ""): payload}
        )

        result = self.make_discoverer(client).run_dynamic_search(
            "Momcozy", collection_window()
        )

        self.assertEqual((result.status, result.stop_reason), ("partial", "schema_drift"))
        self.assertEqual(result.pages, 0)
        checkpoint = self.store.load_checkpoint(
            run_id="backfill_provider_test",
            lane_type="dynamic_search",
            lane_key="Momcozy",
        )
        self.assertEqual(checkpoint.status, "partial")
        self.assertEqual(checkpoint.stop_reason, "schema_drift")
        self.assertEqual(checkpoint.last_error, "TikHubSchemaDrift")
        with self.store.connect() as conn:
            raw_rows = conn.execute(
                "SELECT raw_capture_id FROM raw_captures"
            ).fetchall()
            artifact_rows = conn.execute(
                "SELECT raw_capture_id, response_cursor "
                "FROM backfill_raw_artifacts"
            ).fetchall()
            occurrence_count = conn.execute(
                "SELECT COUNT(*) FROM backfill_discovery_occurrences"
            ).fetchone()[0]
        archive_files = list(self.archive.root.rglob("*.json.gz"))
        self.assertEqual(len(archive_files), 1)
        self.assertEqual(len(raw_rows), 1)
        self.assertEqual(len(artifact_rows), 1)
        self.assertEqual(
            artifact_rows[0]["raw_capture_id"], raw_rows[0]["raw_capture_id"]
        )
        self.assertIsNone(artifact_rows[0]["response_cursor"])
        self.assertEqual(occurrence_count, 0)

    def test_provider_error_is_failed_before_any_page_and_partial_after_a_page(self):
        before_client = KeyedFakeTikHubClient(
            {(FETCH_DYNAMIC_SEARCH, ""): http_error(422)}
        )
        before = self.make_discoverer(before_client).run_dynamic_search(
            "Momcozy", collection_window()
        )
        self.assertEqual((before.status, before.stop_reason), ("failed", "provider_error"))
        self.assertEqual(before.pages, 0)

        self.reset_store(budget=4)
        after_client = KeyedFakeTikHubClient(
            {
                (FETCH_DYNAMIC_SEARCH, ""): discovery_page(
                    "cursor-1",
                    [discovery_post("post-1", "2026-07-01T00:00:00Z")],
                ),
                (FETCH_DYNAMIC_SEARCH, "cursor-1"): http_error(403),
            }
        )
        after = self.make_discoverer(after_client).run_dynamic_search(
            "Momcozy", collection_window()
        )
        self.assertEqual((after.status, after.stop_reason), ("partial", "provider_error"))
        self.assertEqual(after.pages, 1)
        self.assertEqual(after.discovered_occurrences, 1)

    def test_executor_internal_storage_errors_escape_without_provider_checkpoint(self):
        payload = discovery_page(
            "cursor-1",
            [discovery_post("post-1", "2026-07-01T00:00:00Z")],
        )
        for method_name, expected_attempt_status in (
            ("reserve_provider_request", None),
            ("mark_provider_attempt_sent", "reserved"),
            ("complete_provider_attempt", "sent"),
        ):
            with self.subTest(method_name=method_name):
                self.reset_store(budget=2)
                client = KeyedFakeTikHubClient(
                    {(FETCH_DYNAMIC_SEARCH, ""): payload}
                )

                def injected_internal_error(*args, **kwargs):
                    raise sqlite3.OperationalError(f"injected {method_name}")

                setattr(self.store, method_name, injected_internal_error)

                with self.assertRaisesRegex(
                    sqlite3.OperationalError, f"injected {method_name}"
                ):
                    self.make_discoverer(client).run_dynamic_search(
                        "Momcozy", collection_window()
                    )

                self.assertIsNone(
                    self.store.load_checkpoint(
                        run_id="backfill_provider_test",
                        lane_type="dynamic_search",
                        lane_key="Momcozy",
                    )
                )
                with self.store.connect() as conn:
                    attempts = conn.execute(
                        "SELECT status FROM backfill_provider_attempts "
                        "ORDER BY request_number"
                    ).fetchall()
                self.assertEqual(
                    [row["status"] for row in attempts],
                    [] if expected_attempt_status is None else [expected_attempt_status],
                )

    def test_failed_ledger_completion_is_not_wrapped_as_provider_error(self):
        client = KeyedFakeTikHubClient(
            {(FETCH_DYNAMIC_SEARCH, ""): http_error(422)}
        )

        def injected_completion_error(*args, **kwargs):
            raise sqlite3.OperationalError("injected completion failure")

        self.store.complete_provider_attempt = injected_completion_error

        with self.assertRaisesRegex(
            sqlite3.OperationalError, "injected completion failure"
        ):
            self.make_discoverer(client).run_dynamic_search(
                "Momcozy", collection_window()
            )
        self.assertIsNone(
            self.store.load_checkpoint(
                run_id="backfill_provider_test",
                lane_type="dynamic_search",
                lane_key="Momcozy",
            )
        )

    def test_partial_page_crash_replays_exact_rows_and_reuses_capture_time(self):
        payload = discovery_page(
            "cursor-1",
            [
                discovery_post("post-1", "2026-07-01T00:00:00Z"),
                discovery_post("post-2", "2026-06-01T00:00:00Z"),
            ],
        )
        client = KeyedFakeTikHubClient(
            {(FETCH_DYNAMIC_SEARCH, ""): [payload, payload]}
        )
        discoverer = self.make_discoverer(client)
        original_record = self.store.record_discovery_occurrence
        calls = 0

        def crash_on_second(**kwargs):
            nonlocal calls
            calls += 1
            with self.store.connect() as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM raw_captures").fetchone()[0], 1)
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM backfill_raw_artifacts").fetchone()[0],
                    1,
                )
            if calls == 2:
                raise RuntimeError("simulated crash")
            return original_record(**kwargs)

        self.store.record_discovery_occurrence = crash_on_second
        with self.assertRaisesRegex(RuntimeError, "simulated crash"):
            discoverer.run_dynamic_search(
                "Momcozy", collection_window(), max_pages=1
            )
        self.assertIsNone(
            self.store.load_checkpoint(
                run_id="backfill_provider_test",
                lane_type="dynamic_search",
                lane_key="Momcozy",
            )
        )
        self.store.record_discovery_occurrence = original_record
        discoverer.now = lambda: NOW + timedelta(days=1)

        result = discoverer.run_dynamic_search(
            "Momcozy", collection_window(), max_pages=1
        )

        self.assertEqual((result.status, result.stop_reason), ("partial", "probe_page_limit"))
        self.assertEqual(result.discovered_occurrences, 2)
        self.assertEqual(result.unique_candidates, 2)
        with self.store.connect() as conn:
            counts = {
                table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "raw_captures",
                    "backfill_raw_artifacts",
                    "backfill_discovery_occurrences",
                    "backfill_candidates",
                )
            }
            captured_at = conn.execute(
                "SELECT captured_at_utc FROM raw_captures"
            ).fetchone()[0]
        self.assertEqual(
            counts,
            {
                "raw_captures": 1,
                "backfill_raw_artifacts": 1,
                "backfill_discovery_occurrences": 2,
                "backfill_candidates": 2,
            },
        )
        self.assertEqual(captured_at, NOW.isoformat())


class TikHubDetailHydratorTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.store_counter = 0
        self.cursor_contract = comment_contract()
        self.reset_store(budget=100)

    def reset_store(self, *, budget: int) -> None:
        self.store_counter += 1
        self.store = BackfillStore(
            self.root / f"hydration-{self.store_counter}-{budget}.sqlite3"
        )
        self.store.migrate()
        self.store.create_manifest(make_manifest(max_provider_requests=budget))
        self.archive = PrivateRawArchive(
            self.root / f"hydration-raw-{self.store_counter}-{budget}"
        )

    def add_candidates(self, post_ids: tuple[str, ...]) -> None:
        lane_key = "Momcozy"
        artifact = RawArtifactMetadata(
            artifact_id="hydration-discovery-artifact",
            run_id="backfill_provider_test",
            artifact_kind="discovery",
            lane_type="dynamic_search",
            lane_key_hash=sha256(lane_key.encode()).hexdigest(),
            identity_hash="a" * 64,
            raw_capture_id="hydration-discovery-capture",
            parser_kind="tikhub_discovery",
            source_method="tikhub_dynamic_search",
            source_url="tikhub://" + "a" * 64,
            source_endpoint=FETCH_DYNAMIC_SEARCH,
            payload_sha256="b" * 64,
            relative_path=(
                "backfill_provider_test/discovery/hydration/page-000001.json.gz"
            ),
            captured_at_utc=NOW.isoformat(),
            page_number=1,
            request_cursor=None,
            response_cursor=None,
        )
        self.store.insert_raw_artifact(artifact)
        for ordinal, post_id in enumerate(post_ids):
            self.store.record_discovery_occurrence(
                run_id="backfill_provider_test",
                lane_type="dynamic_search",
                lane_key=lane_key,
                page_number=1,
                ordinal=ordinal,
                post_id=post_id,
                source_url=(
                    "https://www.reddit.com/r/ExclusivelyPumping/comments/"
                    f"{post_id}/title/"
                ),
                post_created_at_utc=NOW - timedelta(days=1),
                raw_artifact_id=artifact.artifact_id,
                discovered_at_utc=NOW,
                base_disposition="eligible",
            )

    def insert_structured_thread(self, post_id: str) -> None:
        capture = RawCapture(
            raw_capture_id=f"structured-capture-{post_id}",
            run_id="backfill_provider_test",
            source_method="historical_seed",
            source_url=f"seed://{post_id}",
            captured_at_utc=NOW,
            auth_boundary="local_seed",
            raw_payload_hash="sha256:" + "c" * 64,
            payload_format="json",
        )
        thread = RedditThread(
            post_id=post_id,
            run_id="backfill_provider_test",
            raw_capture_id=capture.raw_capture_id,
            subreddit="ExclusivelyPumping",
            title="Momcozy structured seed thread",
            selftext="Already structured.",
            source_url=(
                "https://www.reddit.com/r/ExclusivelyPumping/comments/"
                f"{post_id}/title/"
            ),
            created_at_utc=NOW - timedelta(days=1),
            parsed_comment_count=0,
            more_node_count=0,
            coverage_grade="full",
            matched_keywords=["Momcozy"],
        )
        self.store.insert_entity_bundle(
            captures=(capture,), threads=(thread,), comments=(), analyses=()
        )

    def make_hydrator(self, client):
        hydrator_type = getattr(backfill_provider, "TikHubDetailHydrator")
        executor = TikHubRequestExecutor(
            client,
            self.store,
            "backfill_provider_test",
            sleep=lambda _: None,
            now=lambda: NOW,
        )
        return hydrator_type(
            executor,
            self.store,
            self.archive,
            "backfill_provider_test",
            now=lambda: NOW,
        )

    def hydrate(self, client, post_ids: tuple[str, ...]):
        return self.make_hydrator(client).hydrate(
            post_ids=post_ids,
            window=collection_window(),
            comment_cursor_contract=self.cursor_contract,
        )

    @staticmethod
    def detail_key(post_ids: tuple[str, ...]):
        return (
            FETCH_POST_DETAILS_BATCH_LARGE,
            ",".join(f"t3_{post_id}" for post_id in post_ids),
        )

    @staticmethod
    def comments_key(post_id: str, cursor: str = ""):
        return FETCH_POST_COMMENTS, f"t3_{post_id}", cursor

    def candidate_rows(self, post_ids: tuple[str, ...]):
        return self.store.load_candidates(
            run_id="backfill_provider_test", post_ids=post_ids
        )

    def snapshot_tables(self):
        tables = (
            "runs",
            "raw_captures",
            "reddit_threads",
            "reddit_comments",
            "analysis_results",
            "delivery_previews",
            "backfill_manifests",
            "backfill_seed_files",
            "backfill_raw_artifacts",
            "backfill_provider_attempts",
            "backfill_checkpoints",
            "backfill_candidates",
            "backfill_discovery_occurrences",
            "backfill_detail_batches",
            "backfill_detail_batch_members",
        )
        with self.store.connect() as conn:
            return {
                table: tuple(
                    tuple(row)
                    for row in conn.execute(
                        f"SELECT * FROM {table} ORDER BY rowid"
                    ).fetchall()
                )
                for table in tables
            }

    def persist_two_page_comment_chain_before_finalize(self, post_id: str):
        self.add_candidates((post_id,))
        client = HydrationFakeTikHubClient(
            {
                self.detail_key((post_id,)): detail_response(
                    detail_post(post_id, reported_comments=2)
                ),
                self.comments_key(post_id): comment_response(
                    post_id,
                    "cursor-1",
                    trees=(comment_tree(post_id, "c1", "Momcozy first page"),),
                ),
                self.comments_key(post_id, "cursor-1"): comment_response(
                    post_id,
                    None,
                    trees=(comment_tree(post_id, "c2", "Second page"),),
                ),
            }
        )
        hydrator = self.make_hydrator(client)
        original_finalize = self.store.finalize_candidate

        def crash_before_finalize(**kwargs):
            if kwargs["post_id"] == post_id:
                raise RuntimeError("simulated pre-finalize crash")
            return original_finalize(**kwargs)

        self.store.finalize_candidate = crash_before_finalize
        try:
            with self.assertRaisesRegex(RuntimeError, "pre-finalize crash"):
                hydrator.hydrate(
                    post_ids=(post_id,),
                    window=collection_window(),
                    comment_cursor_contract=self.cursor_contract,
                )
        finally:
            self.store.finalize_candidate = original_finalize

        checkpoint = self.store.load_checkpoint(
            run_id="backfill_provider_test",
            lane_type="comments",
            lane_key=post_id,
        )
        self.assertEqual(checkpoint.page_number, 2)
        self.assertEqual(
            len(
                self.store.load_raw_artifacts(
                    run_id="backfill_provider_test",
                    lane_type="comments",
                    lane_key=post_id,
                )
            ),
            2,
        )
        self.assertEqual(self.candidate_rows((post_id,))[0]["status"], "pending")
        return client, hydrator

    def test_hydration_batches_31_ids_as_30_plus_1_with_exact_get_params(self):
        post_ids = tuple(f"post-{index:02d}" for index in range(31))
        self.add_candidates(post_ids)
        first, second = post_ids[:30], post_ids[30:]
        responses = {
            self.detail_key(first): detail_response(
                *(detail_post(post_id) for post_id in first)
            ),
            self.detail_key(second): detail_response(
                *(detail_post(post_id) for post_id in second)
            ),
        }

        responses.update(
            {
                self.comments_key(post_id): comment_response(post_id, None)
                for post_id in post_ids
            }
        )
        client = HydrationFakeTikHubClient(responses)

        result = self.hydrate(client, tuple(reversed(post_ids)))

        detail_calls = [
            call for call in client.calls if call[0] == FETCH_POST_DETAILS_BATCH_LARGE
        ]
        comment_calls = [
            call for call in client.calls if call[0] == FETCH_POST_COMMENTS
        ]
        self.assertEqual(
            [params for _, params in detail_calls],
            [
                {
                    "post_ids": ",".join(f"t3_{post_id}" for post_id in first),
                    "include_comment_id": "false",
                    "comment_id": "",
                    "need_format": "false",
                },
                {
                    "post_ids": ",".join(f"t3_{post_id}" for post_id in second),
                    "include_comment_id": "false",
                    "comment_id": "",
                    "need_format": "false",
                },
            ],
        )
        self.assertEqual(len(comment_calls), 31)
        self.assertTrue(
            all(
                params["sort_type"] == "CONFIDENCE"
                and params["after"] == ""
                and params["need_format"] == "false"
                for _, params in comment_calls
            )
        )
        self.assertEqual(
            (result.status, result.stop_reason, result.pages),
            ("complete", "hydration_complete", 33),
        )
        self.assertEqual(result.discovered_occurrences, 31)
        self.assertEqual(result.unique_candidates, 31)
        self.assertEqual(result.provider_request_count, 33)
        self.assertTrue(result.provider_call)
        self.assertFalse(result.live_send)
        self.assertEqual(
            self.store.candidate_status_counts("backfill_provider_test"),
            {"hydrated": 31},
        )
        self.assertEqual(
            [batch.status for batch in self.store.load_detail_batches(
                run_id="backfill_provider_test"
            )],
            ["complete", "complete"],
        )

    def test_current_terminal_comment_forest_without_end_cursor_hydrates(self):
        post_id = "current-comment-shape"
        self.add_candidates((post_id,))
        self.cursor_contract = current_comment_contract()
        responses = {
            self.detail_key((post_id,)): detail_response(
                detail_post(post_id, reported_comments=1)
            ),
            self.comments_key(post_id): current_comment_response(
                post_id,
                trees=(
                    comment_tree(
                        post_id,
                        "current-c1",
                        "Synthetic Momcozy comment",
                    ),
                ),
            ),
        }

        result = self.hydrate(HydrationFakeTikHubClient(responses), (post_id,))

        self.assertEqual(
            (result.status, result.stop_reason),
            ("complete", "hydration_complete"),
        )
        self.assertEqual(
            self.store.candidate_status_counts("backfill_provider_test"),
            {"hydrated": 1},
        )
        with self.store.connect() as connection:
            row = connection.execute(
                "SELECT parsed_comment_count, coverage_grade "
                "FROM reddit_threads WHERE post_id = ?",
                (post_id,),
            ).fetchone()
        self.assertEqual(
            (row["parsed_comment_count"], row["coverage_grade"]),
            (1, "full"),
        )

    def test_empty_terminal_nullable_count_shape_hydrates_without_schema_drift(self):
        post_id = "empty-terminal-nullable-count"
        self.add_candidates((post_id,))
        self.cursor_contract = current_comment_contract()
        comment_payload = current_comment_response(post_id)
        post_info = comment_payload["data"]["postInfoById"]
        post_info.update(
            {
                "__typename": "SubredditPost",
                "commentCount": 0,
                "title": "Synthetic empty terminal post",
            }
        )
        post_info["commentForest"]["pageInfo"]["commentCount"] = None
        comment_payload.update(
            {
                "code": 200,
                "params": {
                    "after": "",
                    "need_format": "false",
                    "post_id": f"t3_{post_id}",
                    "sort_type": "CONFIDENCE",
                },
            }
        )
        responses = {
            self.detail_key((post_id,)): detail_response(
                detail_post(post_id, reported_comments=0)
            ),
            self.comments_key(post_id): comment_payload,
        }

        result = self.hydrate(HydrationFakeTikHubClient(responses), (post_id,))

        self.assertEqual(
            (result.status, result.stop_reason),
            ("complete", "hydration_complete"),
        )
        candidate = self.store.load_candidates(
            run_id="backfill_provider_test",
            post_ids=(post_id,),
        )[0]
        self.assertEqual(
            (candidate["status"], candidate["status_reason"]),
            ("hydrated", None),
        )
        with self.store.connect() as connection:
            row = connection.execute(
                "SELECT parsed_comment_count, coverage_grade "
                "FROM reddit_threads WHERE post_id = ?",
                (post_id,),
            ).fetchone()
        self.assertEqual(
            (row["parsed_comment_count"], row["coverage_grade"]),
            (0, "full"),
        )

    def test_nonterminal_missing_cursor_with_more_preserves_incomplete_comments(self):
        post_id = "nonterminal-missing-cursor"
        self.add_candidates((post_id,))
        self.cursor_contract = current_comment_contract()
        responses = {
            self.detail_key((post_id,)): detail_response(
                detail_post(post_id, reported_comments=9)
            ),
            self.comments_key(post_id): current_nonterminal_missing_cursor_response(
                post_id,
                trees=(
                    comment_tree(
                        post_id,
                        "visible-c1",
                        "Visible Momcozy comment",
                    ),
                ),
            ),
        }
        client = HydrationFakeTikHubClient(responses)
        hydrator = self.make_hydrator(client)

        result = hydrator.hydrate(
            post_ids=(post_id,),
            window=collection_window(),
            comment_cursor_contract=self.cursor_contract,
        )

        self.assertEqual(
            (result.status, result.stop_reason),
            ("partial", "unresolved_comments"),
        )
        candidate = self.candidate_rows((post_id,))[0]
        self.assertEqual(
            (candidate["status"], candidate["status_reason"]),
            ("hydrated", "unresolved_more"),
        )
        checkpoint = self.store.load_checkpoint(
            run_id="backfill_provider_test",
            lane_type="comments",
            lane_key=post_id,
        )
        self.assertEqual(
            (
                checkpoint.status,
                checkpoint.stop_reason,
                checkpoint.page_number,
                checkpoint.cursor,
                checkpoint.discovered_count,
                checkpoint.unique_count,
            ),
            ("partial", "unresolved_more", 1, None, 1, 1),
        )
        with self.store.connect() as connection:
            thread = connection.execute(
                "SELECT parsed_comment_count, more_node_count, coverage_grade "
                "FROM reddit_threads WHERE post_id = ?",
                (post_id,),
            ).fetchone()
            comment_count = connection.execute(
                "SELECT COUNT(*) FROM reddit_comments WHERE post_id = ?",
                (post_id,),
            ).fetchone()[0]
        self.assertEqual(
            dict(thread),
            {
                "parsed_comment_count": 1,
                "more_node_count": 1,
                "coverage_grade": "partial",
            },
        )
        self.assertEqual(comment_count, 1)
        calls_before_resume = tuple(client.calls)
        resumed = hydrator.hydrate(
            post_ids=(post_id,),
            window=collection_window(),
            comment_cursor_contract=self.cursor_contract,
        )
        self.assertEqual(tuple(client.calls), calls_before_resume)
        self.assertEqual(resumed, result)

    def test_archived_hydration_recovery_reuses_raw_without_provider_call(self):
        post_id = "archived-incomplete-comments"
        self.add_candidates((post_id,))
        self.cursor_contract = current_comment_contract()
        responses = {
            self.detail_key((post_id,)): detail_response(
                detail_post(post_id, reported_comments=9)
            ),
            self.comments_key(post_id): current_nonterminal_missing_cursor_response(
                post_id,
                trees=(
                    comment_tree(
                        post_id,
                        "archived-visible-c1",
                        "Archived visible Momcozy comment",
                    ),
                ),
            ),
        }
        with patch.object(
            backfill_provider,
            "_parse_tikhub_comment_payload",
            side_effect=RuntimeError("pre-fix parser gap"),
        ):
            failed = self.hydrate(
                HydrationFakeTikHubClient(responses), (post_id,)
            )
        self.assertEqual(
            (failed.status, failed.stop_reason),
            ("partial", "candidate_failures"),
        )
        provider_count = self.store.provider_request_count(
            "backfill_provider_test"
        )
        with self.store.connect() as connection:
            connection.execute(
                "UPDATE backfill_detail_batches SET status='failed', "
                "stop_reason='comments_schema_drift' WHERE run_id=?",
                ("backfill_provider_test",),
            )
        self.store.set_backfill_status("backfill_provider_test", "partial", NOW)

        reset = backfill_validation._reset_schema_drift_hydration_state(
            self.store.path,
            run_id="backfill_provider_test",
            expected_failed_candidate_ids={post_id},
            recovered_at_utc=NOW,
        )

        self.assertEqual(
            reset,
            {
                "reset_candidate_count": 1,
                "reset_batch_count": 1,
                "reset_comment_checkpoint_count": 1,
                "raw_persisted_batch_count": 1,
                "prepared_batch_count": 0,
            },
        )

        no_provider = HydrationFakeTikHubClient({})
        recovered = self.make_hydrator(no_provider).recover_archived(
            window=collection_window()
        )

        self.assertEqual(recovered, (post_id,))
        self.assertEqual(no_provider.calls, [])
        self.assertEqual(
            self.store.provider_request_count("backfill_provider_test"),
            provider_count,
        )
        candidate = self.candidate_rows((post_id,))[0]
        self.assertEqual(
            (candidate["status"], candidate["status_reason"]),
            ("hydrated", "unresolved_more"),
        )
        checkpoint = self.store.load_checkpoint(
            run_id="backfill_provider_test",
            lane_type="comments",
            lane_key=post_id,
        )
        self.assertEqual(
            (
                checkpoint.status,
                checkpoint.stop_reason,
                checkpoint.page_number,
                checkpoint.discovered_count,
            ),
            ("partial", "unresolved_more", 1, 1),
        )

    def test_completed_mixed_batch_failed_comment_retry_reuses_archive(self):
        failed_post_id = "archived-null-comment-count"
        valid_post_id = "archived-valid-comment-count"
        post_ids = (failed_post_id, valid_post_id)
        self.add_candidates(post_ids)
        self.cursor_contract = current_comment_contract()
        responses = {
            self.detail_key(post_ids): detail_response(
                detail_post(failed_post_id), detail_post(valid_post_id)
            ),
            self.comments_key(failed_post_id): current_comment_response(
                failed_post_id
            ),
            self.comments_key(valid_post_id): current_comment_response(
                valid_post_id,
                trees=(
                    comment_tree(
                        valid_post_id,
                        "archived-valid-c1",
                        "Archived valid Momcozy comment",
                    ),
                ),
            ),
        }
        original_parser = backfill_provider._parse_tikhub_comment_payload

        def fail_one(payload, **kwargs):
            post_info = payload["data"]["postInfoById"]
            if post_info["id"] == f"t3_{failed_post_id}":
                raise RuntimeError("pre-fix nullable commentCount parser gap")
            return original_parser(payload, **kwargs)

        with patch.object(
            backfill_provider,
            "_parse_tikhub_comment_payload",
            side_effect=fail_one,
        ):
            failed = self.hydrate(
                HydrationFakeTikHubClient(responses), post_ids
            )
        self.assertEqual(
            (failed.status, failed.stop_reason),
            ("partial", "candidate_failures"),
        )
        self.assertEqual(
            self.store.candidate_status_counts("backfill_provider_test"),
            {"failed": 1, "hydrated": 1},
        )
        provider_count = self.store.provider_request_count(
            "backfill_provider_test"
        )
        self.store.set_backfill_status("backfill_provider_test", "partial", NOW)
        with self.assertRaisesRegex(
            ValueError, "failed_schema_drift_retry_candidate_mismatch"
        ):
            prepare_failed_schema_drift_retry(
                self.store,
                run_id="backfill_provider_test",
                post_ids=(failed_post_id, "unreviewed-failure"),
                now=NOW,
            )
        reset = prepare_failed_schema_drift_retry(
            self.store,
            run_id="backfill_provider_test",
            post_ids=(failed_post_id,),
            now=NOW,
        )
        self.assertEqual(
            reset,
            {
                "reset_candidate_count": 1,
                "reset_batch_count": 1,
                "reset_comment_checkpoint_count": 1,
                "raw_persisted_batch_count": 1,
                "prepared_batch_count": 0,
            },
        )

        no_provider = HydrationFakeTikHubClient({})
        recovered = self.make_hydrator(no_provider).recover_archived(
            window=collection_window()
        )

        self.assertEqual(recovered, (failed_post_id,))
        self.assertEqual(no_provider.calls, [])
        self.assertEqual(
            self.store.provider_request_count("backfill_provider_test"),
            provider_count,
        )
        self.assertEqual(
            self.store.candidate_status_counts("backfill_provider_test"),
            {"hydrated": 2},
        )
        self.assertEqual(
            self.store.load_detail_batches(run_id="backfill_provider_test")[0].status,
            "complete",
        )

    def test_nonterminal_missing_cursor_without_more_remains_schema_drift(self):
        post_id = "nonterminal-without-more"
        self.add_candidates((post_id,))
        self.cursor_contract = current_comment_contract()
        responses = {
            self.detail_key((post_id,)): detail_response(detail_post(post_id)),
            self.comments_key(post_id): current_nonterminal_missing_cursor_response(
                post_id,
                include_more=False,
            ),
        }

        result = self.hydrate(HydrationFakeTikHubClient(responses), (post_id,))

        candidate = self.candidate_rows((post_id,))[0]
        self.assertEqual(
            (candidate["status"], candidate["status_reason"]),
            ("failed", "comments_schema_drift"),
        )
        self.assertEqual(
            (result.status, result.stop_reason),
            ("partial", "candidate_failures"),
        )

    def test_existing_structured_candidate_is_closed_without_provider_request(self):
        self.add_candidates(("structured-post",))
        self.insert_structured_thread("structured-post")
        client = HydrationFakeTikHubClient({})

        result = self.hydrate(client, ("structured-post",))

        self.assertEqual(client.calls, [])
        self.assertEqual(
            self.candidate_rows(("structured-post",))[0]["status"],
            "duplicate_existing_structured",
        )
        self.assertEqual(
            (result.status, result.stop_reason),
            ("complete", "hydration_complete"),
        )
        self.assertEqual(
            self.store.load_detail_batches(run_id="backfill_provider_test"), ()
        )

    def test_detail_timestamp_is_final_left_closed_right_open_window(self):
        post_ids = ("at-start", "at-end")
        self.add_candidates(post_ids)
        ordered = tuple(sorted(post_ids))
        responses = {
            self.detail_key(ordered): detail_response(
                detail_post("at-start", created_at=collection_window().start_utc),
                detail_post("at-end", created_at=collection_window().end_utc),
            ),
            self.comments_key("at-start"): comment_response("at-start", None),
        }
        client = HydrationFakeTikHubClient(responses)

        result = self.hydrate(client, post_ids)

        rows = {row["post_id"]: row for row in self.candidate_rows(post_ids)}
        self.assertEqual(rows["at-start"]["status"], "hydrated")
        self.assertEqual(rows["at-end"]["status"], "outside_window_detail")
        self.assertEqual(
            [params["post_id"] for path, params in client.calls if path == FETCH_POST_COMMENTS],
            ["t3_at-start"],
        )
        self.assertEqual((result.status, result.stop_reason), ("complete", "hydration_complete"))

    def test_detail_missing_raw_source_url_is_local_unparseable(self):
        post_ids = ("bad-url", "valid-url")
        self.add_candidates(post_ids)
        malformed = detail_post("bad-url")
        malformed.pop("url")
        responses = {
            self.detail_key(post_ids): detail_response(
                malformed,
                detail_post("valid-url"),
            ),
            self.comments_key("valid-url"): comment_response("valid-url", None),
        }
        client = HydrationFakeTikHubClient(responses)

        result = self.hydrate(client, post_ids)

        rows = {row["post_id"]: row for row in self.candidate_rows(post_ids)}
        self.assertEqual(
            (rows["bad-url"]["status"], rows["bad-url"]["status_reason"]),
            ("failed", "detail_unparseable"),
        )
        self.assertEqual(rows["valid-url"]["status"], "hydrated")
        self.assertEqual(
            [
                params["post_id"]
                for path, params in client.calls
                if path == FETCH_POST_COMMENTS
            ],
            ["t3_valid-url"],
        )
        batch = self.store.load_detail_batches(
            run_id="backfill_provider_test"
        )[0]
        self.assertEqual((batch.status, batch.stop_reason), ("complete", None))
        self.assertEqual(
            (result.status, result.stop_reason),
            ("partial", "candidate_failures"),
        )

    def test_two_comment_pages_preserve_page_lineage_dedupe_and_all_comment_times(self):
        post_id = "paged-post"
        self.add_candidates((post_id,))
        first_comment = comment_tree(
            post_id, "c1", "Momcozy pump comment one", created_at=NOW
        )
        late_comment = comment_tree(
            post_id,
            "c2",
            "A late comment after the post window",
            created_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
        )
        responses = {
            self.detail_key((post_id,)): detail_response(
                detail_post(post_id, reported_comments=2)
            ),
            self.comments_key(post_id): comment_response(
                post_id, "cursor-1", trees=(first_comment,)
            ),
            self.comments_key(post_id, "cursor-1"): comment_response(
                post_id, None, trees=(first_comment, late_comment)
            ),
        }
        client = HydrationFakeTikHubClient(responses)

        result = self.hydrate(client, (post_id,))

        artifacts = self.store.load_raw_artifacts(
            run_id="backfill_provider_test",
            lane_type="comments",
            lane_key=post_id,
        )
        self.assertEqual(len(artifacts), 2)
        with self.store.connect() as conn:
            comments = conn.execute(
                "SELECT comment_id, raw_capture_id, created_at_utc "
                "FROM reddit_comments ORDER BY comment_id"
            ).fetchall()
            thread = conn.execute(
                "SELECT parsed_comment_count, coverage_grade FROM reddit_threads "
                "WHERE post_id = ?",
                (post_id,),
            ).fetchone()
        self.assertEqual([row["comment_id"] for row in comments], ["t1_c1", "t1_c2"])
        self.assertEqual(comments[0]["raw_capture_id"], artifacts[0].raw_capture_id)
        self.assertEqual(comments[1]["raw_capture_id"], artifacts[1].raw_capture_id)
        self.assertTrue(comments[1]["created_at_utc"].startswith("2027-01-01"))
        self.assertEqual(dict(thread), {"parsed_comment_count": 2, "coverage_grade": "full"})
        checkpoint = self.store.load_checkpoint(
            run_id="backfill_provider_test", lane_type="comments", lane_key=post_id
        )
        self.assertEqual(
            (
                checkpoint.status,
                checkpoint.stop_reason,
                checkpoint.page_number,
                checkpoint.discovered_count,
                checkpoint.unique_count,
            ),
            ("complete", "cursor_exhausted", 2, 3, 2),
        )
        self.assertEqual(
            [
                params["after"]
                for path, params in client.calls
                if path == FETCH_POST_COMMENTS
            ],
            ["", "cursor-1"],
        )
        self.assertEqual((result.status, result.stop_reason), ("complete", "hydration_complete"))

    def test_combined_comment_relevance_hydrates_and_combined_exclude_drops_entities(self):
        post_ids = ("comment-match", "excluded-match")
        self.add_candidates(post_ids)
        ordered = tuple(sorted(post_ids))
        responses = {
            self.detail_key(ordered): detail_response(
                detail_post(
                    "comment-match",
                    title="Need advice",
                    body="No product is named in the post.",
                    reported_comments=1,
                ),
                detail_post(
                    "excluded-match",
                    title="Another advice request",
                    body="No product is named here either.",
                    reported_comments=1,
                ),
            ),
            self.comments_key("comment-match"): comment_response(
                "comment-match",
                None,
                trees=(
                    comment_tree(
                        "comment-match",
                        "relevant",
                        "The Momcozy wearable pump worked for me.",
                    ),
                ),
            ),
            self.comments_key("excluded-match"): comment_response(
                "excluded-match",
                None,
                trees=(
                    comment_tree(
                        "excluded-match",
                        "excluded",
                        "Momcozy pump compared with BMW M5.",
                    ),
                ),
            ),
        }
        client = HydrationFakeTikHubClient(responses)

        result = self.hydrate(client, post_ids)

        rows = {row["post_id"]: row for row in self.candidate_rows(post_ids)}
        self.assertEqual(rows["comment-match"]["status"], "hydrated")
        self.assertEqual(rows["excluded-match"]["status"], "excluded")
        with self.store.connect() as conn:
            threads = conn.execute(
                "SELECT post_id, matched_keywords FROM reddit_threads"
            ).fetchall()
            excluded_thread = conn.execute(
                "SELECT 1 FROM reddit_threads WHERE post_id = 'excluded-match'"
            ).fetchone()
        self.assertEqual([row["post_id"] for row in threads], ["comment-match"])
        self.assertIn("Momcozy", threads[0]["matched_keywords"])
        self.assertIsNone(excluded_thread)
        self.assertEqual((result.status, result.stop_reason), ("complete", "hydration_complete"))

    def test_unresolved_more_and_post_only_are_hydrated_but_result_is_partial(self):
        post_ids = ("more-post", "post-only")
        self.add_candidates(post_ids)
        responses = {
            self.detail_key(tuple(sorted(post_ids))): detail_response(
                detail_post("more-post", reported_comments=1),
                detail_post("post-only", reported_comments=2),
            ),
            self.comments_key("more-post"): comment_response(
                "more-post",
                None,
                trees=(comment_tree("more-post", "visible", "Visible reply"),),
                unresolved_more=True,
            ),
            self.comments_key("post-only"): comment_response("post-only", None),
        }
        client = HydrationFakeTikHubClient(responses)

        result = self.hydrate(client, post_ids)

        rows = {row["post_id"]: row for row in self.candidate_rows(post_ids)}
        self.assertEqual(
            (rows["more-post"]["status"], rows["more-post"]["status_reason"]),
            ("hydrated", "unresolved_more"),
        )
        self.assertEqual(
            (rows["post-only"]["status"], rows["post-only"]["status_reason"]),
            ("hydrated", "post_only_coverage"),
        )
        with self.store.connect() as conn:
            coverage = {
                row["post_id"]: row["coverage_grade"]
                for row in conn.execute(
                    "SELECT post_id, coverage_grade FROM reddit_threads"
                ).fetchall()
            }
        self.assertEqual(coverage, {"more-post": "partial", "post-only": "post_only"})
        for post_id, stop_reason in (
            ("more-post", "unresolved_more"),
            ("post-only", "post_only_coverage"),
        ):
            checkpoint = self.store.load_checkpoint(
                run_id="backfill_provider_test",
                lane_type="comments",
                lane_key=post_id,
            )
            self.assertEqual((checkpoint.status, checkpoint.stop_reason), ("partial", stop_reason))
        self.assertEqual((result.status, result.stop_reason), ("partial", "unresolved_comments"))

    def test_detail_artifact_attachment_crash_replays_without_refetch(self):
        post_id = "detail-crash"
        self.add_candidates((post_id,))
        client = HydrationFakeTikHubClient(
            {
                self.detail_key((post_id,)): detail_response(detail_post(post_id)),
                self.comments_key(post_id): comment_response(post_id, None),
            }
        )
        hydrator = self.make_hydrator(client)
        original_attach = self.store.attach_detail_batch_artifact
        crashed = False

        def attach_then_crash(**kwargs):
            nonlocal crashed
            attached = original_attach(**kwargs)
            if not crashed:
                crashed = True
                raise RuntimeError("simulated detail-ledger crash")
            return attached

        self.store.attach_detail_batch_artifact = attach_then_crash
        try:
            with self.assertRaisesRegex(RuntimeError, "detail-ledger crash"):
                hydrator.hydrate(
                    post_ids=(post_id,),
                    window=collection_window(),
                    comment_cursor_contract=self.cursor_contract,
                )
        finally:
            self.store.attach_detail_batch_artifact = original_attach

        batch = self.store.load_detail_batches(
            run_id="backfill_provider_test", post_ids=(post_id,)
        )[0]
        self.assertEqual(batch.status, "raw_persisted")
        self.assertIsNotNone(batch.artifact_id)

        result = hydrator.hydrate(
            post_ids=(post_id,),
            window=collection_window(),
            comment_cursor_contract=self.cursor_contract,
        )

        self.assertEqual(
            len([call for call in client.calls if call[0] == FETCH_POST_DETAILS_BATCH_LARGE]),
            1,
        )
        self.assertEqual(
            len([call for call in client.calls if call[0] == FETCH_POST_COMMENTS]),
            1,
        )
        self.assertEqual(self.candidate_rows((post_id,))[0]["status"], "hydrated")
        self.assertEqual((result.status, result.stop_reason), ("complete", "hydration_complete"))

    def test_finish_detail_batch_crash_is_repaired_without_provider_refetch(self):
        post_id = "finish-batch-crash"
        self.add_candidates((post_id,))
        client = HydrationFakeTikHubClient(
            {
                self.detail_key((post_id,)): detail_response(detail_post(post_id)),
                self.comments_key(post_id): comment_response(post_id, None),
            }
        )
        hydrator = self.make_hydrator(client)
        original_finish = self.store.finish_detail_batch

        def crash_on_complete(**kwargs):
            if kwargs["status"] == "complete":
                raise RuntimeError("simulated finish-detail crash")
            return original_finish(**kwargs)

        self.store.finish_detail_batch = crash_on_complete
        try:
            with self.assertRaisesRegex(RuntimeError, "finish-detail crash"):
                hydrator.hydrate(
                    post_ids=(post_id,),
                    window=collection_window(),
                    comment_cursor_contract=self.cursor_contract,
                )
        finally:
            self.store.finish_detail_batch = original_finish

        self.assertEqual(self.candidate_rows((post_id,))[0]["status"], "hydrated")
        batch = self.store.load_detail_batches(
            run_id="backfill_provider_test"
        )[0]
        self.assertEqual(batch.status, "raw_persisted")
        calls_before_resume = tuple(client.calls)

        result = hydrator.hydrate(
            post_ids=(post_id,),
            window=collection_window(),
            comment_cursor_contract=self.cursor_contract,
        )

        self.assertEqual(tuple(client.calls), calls_before_resume)
        repaired = self.store.load_detail_batches(
            run_id="backfill_provider_test"
        )[0]
        self.assertEqual((repaired.status, repaired.stop_reason), ("complete", None))
        self.assertEqual((result.status, result.stop_reason), ("complete", "hydration_complete"))

    def test_nonterminal_batch_prevents_complete_and_empty_prepared_repair_conflicts(self):
        post_id = "terminal-prepared-batch"
        self.add_candidates((post_id,))
        self.store.prepare_detail_batches(
            run_id="backfill_provider_test",
            post_ids=(post_id,),
            created_at_utc=NOW,
        )
        self.store.finalize_candidate(
            run_id="backfill_provider_test",
            post_id=post_id,
            expected_statuses=("pending",),
            status="excluded",
            status_reason=None,
            updated_at_utc=NOW,
        )
        client = HydrationFakeTikHubClient({})
        hydrator = self.make_hydrator(client)

        result = hydrator._result()

        self.assertEqual(
            (result.status, result.stop_reason),
            ("partial", "pending_candidates"),
        )
        with self.assertRaises(BackfillConflictError):
            hydrator.hydrate(
                post_ids=(post_id,),
                window=collection_window(),
                comment_cursor_contract=self.cursor_contract,
            )
        self.assertEqual(client.calls, [])

    def test_comment_checkpoint_crash_replays_prior_page_and_continues_cursor(self):
        post_id = "comment-crash"
        self.add_candidates((post_id,))
        responses = {
            self.detail_key((post_id,)): detail_response(
                detail_post(post_id, reported_comments=2)
            ),
            self.comments_key(post_id): comment_response(
                post_id,
                "cursor-1",
                trees=(comment_tree(post_id, "c1", "Momcozy first page"),),
            ),
            self.comments_key(post_id, "cursor-1"): comment_response(
                post_id,
                None,
                trees=(comment_tree(post_id, "c2", "Second page"),),
            ),
        }
        client = HydrationFakeTikHubClient(responses)
        hydrator = self.make_hydrator(client)
        original_save = self.store.save_checkpoint
        crashed = False

        def save_then_crash(checkpoint):
            nonlocal crashed
            original_save(checkpoint)
            if (
                not crashed
                and checkpoint.lane_type == "comments"
                and checkpoint.lane_key == post_id
                and checkpoint.page_number == 1
                and checkpoint.cursor == "cursor-1"
            ):
                crashed = True
                raise RuntimeError("simulated comment-checkpoint crash")

        self.store.save_checkpoint = save_then_crash
        try:
            with self.assertRaisesRegex(RuntimeError, "comment-checkpoint crash"):
                hydrator.hydrate(
                    post_ids=(post_id,),
                    window=collection_window(),
                    comment_cursor_contract=self.cursor_contract,
                )
        finally:
            self.store.save_checkpoint = original_save

        result = hydrator.hydrate(
            post_ids=(post_id,),
            window=collection_window(),
            comment_cursor_contract=self.cursor_contract,
        )

        self.assertEqual(
            [
                params["after"]
                for path, params in client.calls
                if path == FETCH_POST_COMMENTS
            ],
            ["", "cursor-1"],
        )
        self.assertEqual(
            len([call for call in client.calls if call[0] == FETCH_POST_DETAILS_BATCH_LARGE]),
            1,
        )
        with self.store.connect() as conn:
            comment_ids = [
                row["comment_id"]
                for row in conn.execute(
                    "SELECT comment_id FROM reddit_comments ORDER BY comment_id"
                ).fetchall()
            ]
        self.assertEqual(comment_ids, ["t1_c1", "t1_c2"])
        self.assertEqual((result.status, result.stop_reason), ("complete", "hydration_complete"))

    def test_comment_preparse_internal_crash_replays_raw_without_refetch(self):
        post_id = "comment-preparse-crash"
        self.add_candidates((post_id,))
        client = HydrationFakeTikHubClient(
            {
                self.detail_key((post_id,)): detail_response(
                    detail_post(post_id, reported_comments=1)
                ),
                self.comments_key(post_id): comment_response(
                    post_id,
                    None,
                    trees=(comment_tree(post_id, "only", "Momcozy comment"),),
                ),
            }
        )
        hydrator = self.make_hydrator(client)
        original_parse = hydrator._parse_comment_payload
        crashed = False

        def crash_before_parse(**kwargs):
            nonlocal crashed
            if not crashed:
                crashed = True
                raise RuntimeError("simulated comment preparse crash")
            return original_parse(**kwargs)

        hydrator._parse_comment_payload = crash_before_parse
        with self.assertRaisesRegex(RuntimeError, "comment preparse crash"):
            hydrator.hydrate(
                post_ids=(post_id,),
                window=collection_window(),
                comment_cursor_contract=self.cursor_contract,
            )
        hydrator._parse_comment_payload = original_parse

        artifacts_after_crash = self.store.load_raw_artifacts(
            run_id="backfill_provider_test",
            lane_type="comments",
            lane_key=post_id,
        )
        self.assertEqual(len(artifacts_after_crash), 1)
        self.assertIsNone(artifacts_after_crash[0].response_cursor)
        with self.store.connect() as conn:
            comment_capture_count = conn.execute(
                "SELECT COUNT(*) FROM raw_captures "
                "WHERE run_id = ? AND source_method = 'tikhub_comments'",
                ("backfill_provider_test",),
            ).fetchone()[0]
        self.assertEqual(comment_capture_count, 1)

        result = hydrator.hydrate(
            post_ids=(post_id,),
            window=collection_window(),
            comment_cursor_contract=self.cursor_contract,
        )

        self.assertEqual(
            len([call for call in client.calls if call[0] == FETCH_POST_COMMENTS]),
            1,
        )
        self.assertEqual(
            len(
                self.store.load_raw_artifacts(
                    run_id="backfill_provider_test",
                    lane_type="comments",
                    lane_key=post_id,
                )
            ),
            1,
        )
        with self.store.connect() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM raw_captures "
                    "WHERE run_id = ? AND source_method = 'tikhub_comments'",
                    ("backfill_provider_test",),
                ).fetchone()[0],
                1,
            )
        self.assertEqual((result.status, result.stop_reason), ("complete", "hydration_complete"))

    def test_comment_archive_chain_corruptions_fail_before_any_new_provider_request(self):
        for corruption in (
            "missing_page",
            "duplicate_committed_page",
            "broken_cursor",
            "count_mismatch",
        ):
            with self.subTest(corruption=corruption):
                self.reset_store(budget=10)
                post_id = f"comment-chain-{corruption}"
                client, hydrator = self.persist_two_page_comment_chain_before_finalize(
                    post_id
                )

                with self.store.connect() as conn:
                    if corruption == "missing_page":
                        conn.execute(
                            "DELETE FROM backfill_raw_artifacts "
                            "WHERE run_id = ? AND lane_type = 'comments' "
                            "AND lane_key_hash = ? AND page_number = 1",
                            (
                                "backfill_provider_test",
                                sha256(post_id.encode()).hexdigest(),
                            ),
                        )
                    elif corruption == "duplicate_committed_page":
                        conn.execute(
                            "UPDATE backfill_raw_artifacts "
                            "SET page_number = 1, request_cursor = NULL "
                            "WHERE run_id = ? AND lane_type = 'comments' "
                            "AND lane_key_hash = ? AND page_number = 2",
                            (
                                "backfill_provider_test",
                                sha256(post_id.encode()).hexdigest(),
                            ),
                        )
                    elif corruption == "broken_cursor":
                        conn.execute(
                            "UPDATE backfill_raw_artifacts "
                            "SET request_cursor = 'wrong-cursor' "
                            "WHERE run_id = ? AND lane_type = 'comments' "
                            "AND lane_key_hash = ? AND page_number = 2",
                            (
                                "backfill_provider_test",
                                sha256(post_id.encode()).hexdigest(),
                            ),
                        )
                    else:
                        conn.execute(
                            "UPDATE backfill_checkpoints "
                            "SET unique_count = unique_count + 1 "
                            "WHERE run_id = ? AND lane_type = 'comments' "
                            "AND lane_key = ?",
                            ("backfill_provider_test", post_id),
                        )

                calls_before_resume = tuple(client.calls)
                with self.assertRaises(BackfillConflictError):
                    hydrator.hydrate(
                        post_ids=(post_id,),
                        window=collection_window(),
                        comment_cursor_contract=self.cursor_contract,
                    )

                self.assertEqual(tuple(client.calls), calls_before_resume)

    def test_budget_provider_and_detail_schema_aborts_close_candidates_and_batches(self):
        cases = (
            ("budget", 0, {}, "budget_deferred", "budget_exhausted", ("partial", "budget_exhausted")),
            (
                "provider",
                5,
                "provider_error",
                "failed",
                "provider_error",
                ("failed", "provider_error"),
            ),
            (
                "detail_schema",
                5,
                "detail_schema_drift",
                "failed",
                "detail_schema_drift",
                ("partial", "candidate_failures"),
            ),
        )
        for name, budget, response_kind, status, reason, result_state in cases:
            with self.subTest(name=name):
                self.reset_store(budget=budget)
                post_ids = (f"{name}-a", f"{name}-b")
                self.add_candidates(post_ids)
                ordered = tuple(sorted(post_ids))
                if response_kind == "provider_error":
                    responses = {self.detail_key(ordered): http_error(422)}
                elif response_kind == "detail_schema_drift":
                    responses = {
                        self.detail_key(ordered): detail_response(
                            *(detail_post(post_id) for post_id in ordered),
                            detail_post("unrequested-extra"),
                        )
                    }
                else:
                    responses = {}
                client = HydrationFakeTikHubClient(responses)

                result = self.hydrate(client, post_ids)

                self.assertEqual(
                    {(row["status"], row["status_reason"]) for row in self.candidate_rows(post_ids)},
                    {(status, reason)},
                )
                batches = self.store.load_detail_batches(
                    run_id="backfill_provider_test"
                )
                self.assertEqual(len(batches), 1)
                self.assertEqual((batches[0].status, batches[0].stop_reason), ("failed", reason))
                self.assertEqual((result.status, result.stop_reason), result_state)
                if name == "budget":
                    self.assertEqual(client.calls, [])

    def test_comment_schema_and_cursor_loop_abort_without_incomplete_entity(self):
        for name in ("schema", "cursor_loop"):
            with self.subTest(name=name):
                self.reset_store(budget=10)
                post_id = f"comment-{name}"
                self.add_candidates((post_id,))
                responses = {
                    self.detail_key((post_id,)): detail_response(detail_post(post_id))
                }
                if name == "schema":
                    responses[self.comments_key(post_id)] = {
                        "data": {
                            "postInfoById": {
                                "id": f"t3_{post_id}",
                                "commentForest": {"trees": []},
                            }
                        }
                    }
                    expected_reason = "comments_schema_drift"
                else:
                    responses[self.comments_key(post_id)] = comment_response(
                        post_id, "loop-cursor"
                    )
                    responses[self.comments_key(post_id, "loop-cursor")] = comment_response(
                        post_id, "loop-cursor"
                    )
                    expected_reason = "cursor_loop"
                client = HydrationFakeTikHubClient(responses)

                result = self.hydrate(client, (post_id,))

                candidate = self.candidate_rows((post_id,))[0]
                self.assertEqual(
                    (candidate["status"], candidate["status_reason"]),
                    ("failed", expected_reason),
                )
                with self.store.connect() as conn:
                    self.assertIsNone(
                        conn.execute(
                            "SELECT 1 FROM reddit_threads WHERE post_id = ?",
                            (post_id,),
                        ).fetchone()
                    )
                checkpoint = self.store.load_checkpoint(
                    run_id="backfill_provider_test",
                    lane_type="comments",
                    lane_key=post_id,
                )
                self.assertEqual(
                    (checkpoint.status, checkpoint.stop_reason),
                    ("partial", expected_reason),
                )
                batches = self.store.load_detail_batches(
                    run_id="backfill_provider_test"
                )
                self.assertEqual(
                    (batches[0].status, batches[0].stop_reason),
                    ("complete", None),
                )
                self.assertEqual((result.status, result.stop_reason), ("partial", "candidate_failures"))

    def test_comment_schema_drift_isolates_candidate_and_continues_batch(self):
        post_ids = ("a-schema-drift", "b-valid")
        self.add_candidates(post_ids)
        responses = {
            self.detail_key(post_ids): detail_response(
                *(detail_post(post_id) for post_id in post_ids)
            ),
            self.comments_key("a-schema-drift"): {
                "data": {
                    "postInfoById": {
                        "id": "t3_a-schema-drift",
                        "commentForest": {"trees": []},
                    }
                }
            },
            self.comments_key("b-valid"): comment_response(
                "b-valid",
                None,
                trees=(
                    comment_tree(
                        "b-valid",
                        "valid-c1",
                        "Momcozy valid candidate comment",
                    ),
                ),
            ),
        }
        client = HydrationFakeTikHubClient(responses)

        result = self.hydrate(client, post_ids)

        rows = {row["post_id"]: row for row in self.candidate_rows(post_ids)}
        self.assertEqual(
            (rows["a-schema-drift"]["status"], rows["a-schema-drift"]["status_reason"]),
            ("failed", "comments_schema_drift"),
        )
        self.assertEqual(
            (rows["b-valid"]["status"], rows["b-valid"]["status_reason"]),
            ("hydrated", None),
        )
        self.assertEqual(
            [
                params["post_id"]
                for path, params in client.calls
                if path == FETCH_POST_COMMENTS
            ],
            ["t3_a-schema-drift", "t3_b-valid"],
        )
        batch = self.store.load_detail_batches(
            run_id="backfill_provider_test"
        )[0]
        self.assertEqual((batch.status, batch.stop_reason), ("complete", None))
        self.assertEqual(
            (result.status, result.stop_reason),
            ("partial", "candidate_failures"),
        )

    def test_partial_selection_of_persisted_pending_batch_fails_before_request(self):
        post_ids = ("batch-a", "batch-b")
        self.add_candidates(post_ids)
        self.store.prepare_detail_batches(
            run_id="backfill_provider_test", post_ids=post_ids, created_at_utc=NOW
        )
        client = HydrationFakeTikHubClient({})
        hydrator = self.make_hydrator(client)

        with self.assertRaises(ValueError):
            hydrator.hydrate(
                post_ids=("batch-a",),
                window=collection_window(),
                comment_cursor_contract=self.cursor_contract,
            )

        self.assertEqual(client.calls, [])
        self.assertEqual(
            self.store.candidate_status_counts("backfill_provider_test"),
            {"pending": 2},
        )

    def test_failed_batch_resume_closes_all_pending_members_from_persisted_reason(self):
        cases = (
            (
                "provider_error",
                "failed",
                ("failed", "provider_error"),
            ),
            (
                "detail_schema_drift",
                "failed",
                ("partial", "candidate_failures"),
            ),
            (
                "budget_exhausted",
                "budget_deferred",
                ("partial", "budget_exhausted"),
            ),
        )
        for reason, candidate_status, result_state in cases:
            with self.subTest(reason=reason):
                self.reset_store(budget=10)
                post_ids = (f"{reason}-a", f"{reason}-b")
                self.add_candidates(post_ids)
                batch = self.store.prepare_detail_batches(
                    run_id="backfill_provider_test",
                    post_ids=post_ids,
                    created_at_utc=NOW,
                )[0]
                self.store.finish_detail_batch(
                    run_id="backfill_provider_test",
                    batch_id=batch.batch_id,
                    status="failed",
                    stop_reason=reason,
                    updated_at_utc=NOW,
                )
                client = HydrationFakeTikHubClient({})

                result = self.hydrate(client, post_ids)

                self.assertEqual(client.calls, [])
                self.assertEqual(
                    {
                        (row["status"], row["status_reason"])
                        for row in self.candidate_rows(post_ids)
                    },
                    {(candidate_status, reason)},
                )
                self.assertEqual((result.status, result.stop_reason), result_state)

    def test_run_level_priority_includes_unselected_failed_and_budget_candidates(self):
        cases = (
            (
                "provider_error",
                "failed",
                ("partial", "provider_error"),
            ),
            (
                "budget_exhausted",
                "budget_deferred",
                ("partial", "budget_exhausted"),
            ),
        )
        for reason, terminal_status, expected_result in cases:
            with self.subTest(reason=reason):
                self.reset_store(budget=10)
                selected = f"selected-{reason}"
                unselected = f"unselected-{reason}"
                self.add_candidates((selected, unselected))
                self.store.finalize_candidate(
                    run_id="backfill_provider_test",
                    post_id=unselected,
                    expected_statuses=("pending",),
                    status=terminal_status,
                    status_reason=reason,
                    updated_at_utc=NOW,
                )
                self.insert_structured_thread(selected)
                client = HydrationFakeTikHubClient({})

                result = self.hydrate(client, (selected,))

                self.assertEqual(client.calls, [])
                self.assertEqual(
                    (
                        result.status,
                        result.stop_reason,
                        result.discovered_occurrences,
                        result.unique_candidates,
                    ),
                    (*expected_result, 2, 2),
                )
                self.assertEqual(
                    self.candidate_rows((selected,))[0]["status"],
                    "duplicate_existing_structured",
                )

    def test_run_level_priority_includes_unselected_unresolved_candidate(self):
        selected = "selected-after-unresolved"
        unresolved = "unselected-unresolved"
        self.add_candidates((selected, unresolved))
        first_client = HydrationFakeTikHubClient(
            {
                self.detail_key((unresolved,)): detail_response(
                    detail_post(unresolved, reported_comments=1)
                ),
                self.comments_key(unresolved): comment_response(
                    unresolved,
                    None,
                    trees=(
                        comment_tree(unresolved, "visible", "Momcozy comment"),
                    ),
                    unresolved_more=True,
                ),
            }
        )
        first_result = self.hydrate(first_client, (unresolved,))
        self.assertEqual(
            (first_result.status, first_result.stop_reason),
            ("partial", "unresolved_comments"),
        )

        self.insert_structured_thread(selected)
        no_op_client = HydrationFakeTikHubClient({})
        second_result = self.hydrate(no_op_client, (selected,))

        self.assertEqual(no_op_client.calls, [])
        self.assertEqual(
            (
                second_result.status,
                second_result.stop_reason,
                second_result.discovered_occurrences,
                second_result.unique_candidates,
            ),
            ("partial", "unresolved_comments", 2, 2),
        )

    def test_run_level_unresolved_priority_uses_candidate_reason_without_redundancy(self):
        selected = "selected-candidate-reason"
        unresolved = "unresolved-candidate-reason"
        self.add_candidates((selected, unresolved))
        self.insert_structured_thread(selected)
        self.insert_structured_thread(unresolved)
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE backfill_candidates "
                "SET status = 'hydrated', status_reason = 'unresolved_more' "
                "WHERE run_id = ? AND post_id = ?",
                ("backfill_provider_test", unresolved),
            )
        client = HydrationFakeTikHubClient({})

        result = self.hydrate(client, (selected,))

        self.assertEqual(client.calls, [])
        self.assertEqual(
            (result.status, result.stop_reason),
            ("partial", "unresolved_comments"),
        )

    def test_unexpected_pure_parser_errors_become_schema_outcomes_after_raw_persist(self):
        cases = ("detail", "comments")
        for parser_kind in cases:
            with self.subTest(parser_kind=parser_kind):
                self.reset_store(budget=10)
                post_id = f"unexpected-{parser_kind}-parser"
                self.add_candidates((post_id,))
                responses = {
                    self.detail_key((post_id,)): detail_response(
                        detail_post(post_id)
                    )
                }
                if parser_kind == "comments":
                    responses[self.comments_key(post_id)] = comment_response(
                        post_id, None
                    )
                client = HydrationFakeTikHubClient(responses)
                attribute = (
                    "_parse_tikhub_app_detail_payload"
                    if parser_kind == "detail"
                    else "_parse_tikhub_comment_payload"
                )
                original = getattr(backfill_provider, attribute)

                def fail_parser(*_args, **_kwargs):
                    raise RuntimeError("unexpected pure parser failure")

                setattr(backfill_provider, attribute, fail_parser)
                try:
                    result = self.hydrate(client, (post_id,))
                finally:
                    setattr(backfill_provider, attribute, original)

                expected_reason = (
                    "detail_schema_drift"
                    if parser_kind == "detail"
                    else "comments_schema_drift"
                )
                candidate = self.candidate_rows((post_id,))[0]
                self.assertEqual(
                    (candidate["status"], candidate["status_reason"]),
                    ("failed", expected_reason),
                )
                batch = self.store.load_detail_batches(
                    run_id="backfill_provider_test"
                )[0]
                self.assertEqual(
                    (batch.status, batch.stop_reason),
                    (
                        ("failed", expected_reason)
                        if parser_kind == "detail"
                        else ("complete", None)
                    ),
                )
                self.assertEqual(
                    self.store.raw_artifact_count(
                        "backfill_provider_test",
                        (
                            "detail_batch",
                            "comments",
                        ),
                    ),
                    1 if parser_kind == "detail" else 2,
                )
                self.assertEqual(
                    (result.status, result.stop_reason),
                    ("partial", "candidate_failures"),
                )

    def test_storage_and_archive_errors_escape_unchanged(self):
        cases = ("storage", "archive")
        for failure_kind in cases:
            with self.subTest(failure_kind=failure_kind):
                self.reset_store(budget=10)
                post_id = f"internal-{failure_kind}"
                self.add_candidates((post_id,))
                responses = (
                    {
                        self.detail_key((post_id,)): detail_response(
                            detail_post(post_id)
                        )
                    }
                    if failure_kind == "archive"
                    else {}
                )
                client = HydrationFakeTikHubClient(responses)
                hydrator = self.make_hydrator(client)

                if failure_kind == "storage":
                    failure = sqlite3.OperationalError("storage sentinel")
                    original = self.store.prepare_detail_batches

                    def fail_storage(**_kwargs):
                        raise failure

                    self.store.prepare_detail_batches = fail_storage
                    restore = lambda: setattr(
                        self.store, "prepare_detail_batches", original
                    )
                else:
                    failure = OSError("archive sentinel")
                    original = self.archive.write

                    def fail_archive(**_kwargs):
                        raise failure

                    self.archive.write = fail_archive
                    restore = lambda: setattr(self.archive, "write", original)

                try:
                    with self.assertRaises(type(failure)) as caught:
                        hydrator.hydrate(
                            post_ids=(post_id,),
                            window=collection_window(),
                            comment_cursor_contract=self.cursor_contract,
                        )
                finally:
                    restore()

                self.assertIs(caught.exception, failure)
                self.assertEqual(
                    self.candidate_rows((post_id,))[0]["status"], "pending"
                )
                if failure_kind == "storage":
                    self.assertEqual(client.calls, [])
                    self.assertEqual(
                        self.store.load_detail_batches(
                            run_id="backfill_provider_test"
                        ),
                        (),
                    )
                else:
                    self.assertEqual(
                        [path for path, _params in client.calls],
                        [FETCH_POST_DETAILS_BATCH_LARGE],
                    )
                    batch = self.store.load_detail_batches(
                        run_id="backfill_provider_test"
                    )[0]
                    self.assertEqual((batch.status, batch.artifact_id), ("prepared", None))

    def test_conflicting_duplicate_comment_id_fails_without_structured_thread(self):
        post_id = "comment-conflict"
        self.add_candidates((post_id,))
        responses = {
            self.detail_key((post_id,)): detail_response(detail_post(post_id)),
            self.comments_key(post_id): comment_response(
                post_id,
                "cursor-1",
                trees=(comment_tree(post_id, "same", "Momcozy original body"),),
            ),
            self.comments_key(post_id, "cursor-1"): comment_response(
                post_id,
                None,
                trees=(comment_tree(post_id, "same", "Momcozy changed body"),),
            ),
        }
        client = HydrationFakeTikHubClient(responses)

        result = self.hydrate(client, (post_id,))

        candidate = self.candidate_rows((post_id,))[0]
        self.assertEqual(
            (candidate["status"], candidate["status_reason"]),
            ("failed", "comment_conflict"),
        )
        self.assertEqual(
            len(
                self.store.load_raw_artifacts(
                    run_id="backfill_provider_test",
                    lane_type="comments",
                    lane_key=post_id,
                )
            ),
            2,
        )
        with self.store.connect() as conn:
            self.assertIsNone(
                conn.execute(
                    "SELECT 1 FROM reddit_threads WHERE post_id = ?", (post_id,)
                ).fetchone()
            )
        checkpoint = self.store.load_checkpoint(
            run_id="backfill_provider_test", lane_type="comments", lane_key=post_id
        )
        self.assertEqual(
            (checkpoint.status, checkpoint.stop_reason),
            ("partial", "comment_conflict"),
        )
        self.assertEqual((result.status, result.stop_reason), ("partial", "candidate_failures"))

    def test_exact_second_hydration_is_stable_no_op(self):
        post_id = "exact-replay"
        self.add_candidates((post_id,))
        responses = {
            self.detail_key((post_id,)): detail_response(
                detail_post(post_id, reported_comments=1)
            ),
            self.comments_key(post_id): comment_response(
                post_id,
                None,
                trees=(comment_tree(post_id, "only", "Momcozy replay comment"),),
            ),
        }
        client = HydrationFakeTikHubClient(responses)
        hydrator = self.make_hydrator(client)

        first = hydrator.hydrate(
            post_ids=(post_id,),
            window=collection_window(),
            comment_cursor_contract=self.cursor_contract,
        )
        first_calls = tuple(client.calls)
        first_snapshot = self.snapshot_tables()

        second = hydrator.hydrate(
            post_ids=(post_id,),
            window=collection_window(),
            comment_cursor_contract=self.cursor_contract,
        )

        self.assertEqual(second, first)
        self.assertEqual(tuple(client.calls), first_calls)
        self.assertEqual(self.snapshot_tables(), first_snapshot)
        self.assertEqual((second.status, second.stop_reason), ("complete", "hydration_complete"))


if __name__ == "__main__":
    unittest.main()
