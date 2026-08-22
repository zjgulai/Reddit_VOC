from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.build_reddit_v2_raw_snapshot import (
    SnapshotContractError,
    build,
    canonical_bytes,
    identity_hash,
    write_snapshot,
)


POST_ID = "abcde"
OTHER_POST_ID = "fghij"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")


def _inventory(
    path: Path,
    post_ids: list[str] | None = None,
    *,
    hash_field: str = "sha256",
) -> tuple[int, str]:
    values = post_ids or [POST_ID]
    digest = identity_hash(values)
    _write_json(
        path,
        {
            "schema_version": "test_identity_inventory_v1",
            "target_window_utc": {
                "start": "2025-01-01T00:00:00Z",
                "end": "2026-07-15T16:00:00Z",
            },
            "identity_sets": [
                {
                    "set_id": "target",
                    "count": len(values),
                    hash_field: digest,
                    "post_ids": values,
                }
            ],
        },
    )
    return len(values), digest


def _search_payload(
    post_id: str = POST_ID,
    *,
    created_at: str = "2026-07-14T00:00:00Z",
) -> dict:
    post = {
        "__typename": "SubredditPost",
        "id": f"t3_{post_id}",
        "permalink": f"https://www.reddit.com/r/MomCozy/comments/{post_id}/fixture/",
        "createdAt": created_at,
        "title": "Momcozy pump works great",
        "subreddit": {"name": "MomCozy"},
        "score": 9,
        "commentCount": 2,
    }
    return {
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
                                                "post": post,
                                            }
                                        ]
                                    }
                                }
                            ],
                            "pageInfo": {"endCursor": None, "hasNextPage": False},
                        }
                    }
                }
            }
        }
    }


def _terminal_empty_search_payload() -> dict:
    telemetry = {
        "__typename": "SearchElementTelemetry",
        "events": [],
        "trackingContext": {},
    }
    return {
        "data": {
            "search": {
                "dynamic": {
                    "components": {
                        "main": {
                            "edges": [
                                {
                                    "cursor": "",
                                    "node": {
                                        "__typename": "SearchErrorMessage",
                                        "behaviors": {},
                                        "presentation": {
                                            "__typename": "SearchErrorMessageDefaultPresentation",
                                            "ctaButtonText": "调整你的搜索",
                                            "explanation": "请仔细检查拼写或尝试不同的关键词",
                                            "icon": "EMPTY",
                                            "message": "嗯...我们找不到“fixture”的任何结果",
                                        },
                                        "telemetry": telemetry,
                                    },
                                }
                            ],
                            "pageInfo": {
                                "endCursor": "terminal-cursor",
                                "hasNextPage": False,
                                "hasPreviousPage": False,
                                "startCursor": "",
                            },
                        }
                    }
                }
            }
        }
    }


def _search_report(payload: dict, *, lane: int = 1) -> dict:
    return {
        "schema_version": "reddit_voc_search_lane_probe_v1",
        "run_id": "run-v2",
        "lane_index": lane,
        "endpoint": "/api/v1/reddit/app/fetch_dynamic_search",
        "http_status": 200,
        "response_validation": "passed",
        "payload_sha256": sha256(canonical_bytes(payload)).hexdigest(),
        "payload": payload,
        "provider_attempt_made": True,
        "live_send": False,
        "production_merge": False,
        "git_push": False,
        "dingtalk": False,
    }


def _comment_node(comment_id: str, body: str, *, parent_id: str | None = None) -> dict:
    return {
        "depth": 0 if parent_id is None else 1,
        "parentId": parent_id,
        "node": {
            "__typename": "Comment",
            "id": comment_id,
            "content": {"markdown": body},
            "createdAt": "2026-07-14T00:01:00Z",
            "authorInfo": {"name": "raw-user-must-not-survive"},
            "score": 3,
        },
    }


def _comment_payload(
    *,
    comments: list[dict] | None = None,
    cursors: list[str] | None = None,
    has_next_page: bool = False,
) -> dict:
    trees = list(comments or [])
    trees.extend({"more": {"cursor": cursor}} for cursor in (cursors or []))
    return {
        "data": {
            "postInfoById": {
                "id": f"t3_{POST_ID}",
                "commentCount": 2,
                "commentForest": {
                    "pageInfo": {"hasNextPage": has_next_page},
                    "trees": trees,
                },
            }
        }
    }


def _comment_report(payload: dict) -> dict:
    cursor_count = len(
        [tree for tree in payload["data"]["postInfoById"]["commentForest"]["trees"] if tree.get("more")]
    )
    comment_count = len(
        [tree for tree in payload["data"]["postInfoById"]["commentForest"]["trees"] if tree.get("node")]
    )
    return {
        "schema_version": "reddit_voc_comment_repair_probe_v1",
        "run_id": "run-v2",
        "post_id": POST_ID,
        "endpoint": "/api/v1/reddit/app/fetch_post_comments",
        "request_params": {
            "post_id": f"t3_{POST_ID}",
            "sort_type": "CONFIDENCE",
            "after": "",
            "need_format": "false",
        },
        "http_status": 200,
        "response_validation": "passed",
        "payload_sha256": sha256(canonical_bytes(payload)).hexdigest(),
        "parsed_comment_count": comment_count,
        "more_node_count": cursor_count,
        "more_cursor_count": cursor_count,
        "reported_comment_count": 2,
        "has_next_page": payload["data"]["postInfoById"]["commentForest"]["pageInfo"]["hasNextPage"],
        "payload": payload,
        "provider_attempt_made": True,
        "live_send": False,
        "production_merge": False,
        "git_push": False,
        "dingtalk": False,
    }


def _reply_report(
    payload: dict, *, cursor: str, source_sha256: str | None
) -> dict:
    cursor_count = len(
        [tree for tree in payload["data"]["postInfoById"]["commentForest"]["trees"] if tree.get("more")]
    )
    comment_count = len(
        [tree for tree in payload["data"]["postInfoById"]["commentForest"]["trees"] if tree.get("node")]
    )
    return {
        "schema_version": "reddit_voc_comment_reply_probe_v1",
        "run_id": "run-v2",
        "post_id": POST_ID,
        "cursor": cursor,
        "endpoint": "/api/v1/reddit/app/fetch_comment_replies",
        "request_params": {
            "post_id": f"t3_{POST_ID}",
            "cursor": cursor,
            "sort_type": "CONFIDENCE",
            "need_format": "false",
        },
        "http_status": 200,
        "response_validation": "passed",
        "payload_sha256": sha256(canonical_bytes(payload)).hexdigest(),
        "parsed_comment_count": comment_count,
        "more_node_count": cursor_count,
        "more_cursor_count": cursor_count,
        "payload": payload,
        "source_first_page_payload_sha256": source_sha256,
        "provider_attempt_made": True,
        "live_send": False,
        "production_merge": False,
        "git_push": False,
        "dingtalk": False,
    }


def _build(
    root: Path,
    *,
    search_reports: list[dict] | None = None,
    comment_reports: list[tuple[str, dict]] | None = None,
    post_ids: list[str] | None = None,
) -> dict:
    inventory = root / "inventory.json"
    count, digest = _inventory(inventory, post_ids)
    search_root = root / "search"
    comment_root = root / "comments"
    search_root.mkdir(parents=True, exist_ok=True)
    comment_root.mkdir(parents=True, exist_ok=True)
    for index, report in enumerate(search_reports or []):
        _write_json(search_root / str(index) / "search-lane-probe.json", report)
    for index, (name, report) in enumerate(comment_reports or []):
        _write_json(comment_root / str(index) / name, report)
    return build(
        inventory,
        set_id="target",
        expected_target_count=count,
        expected_target_sha256=digest,
        search_report_roots=[search_root],
        comment_report_roots=[comment_root],
    )


class RedditV2RawSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def test_builds_exact_private_snapshot_deterministically(self) -> None:
        search = _search_report(_search_payload())
        first = _comment_report(
            _comment_payload(comments=[_comment_node("c1", "Momcozy works great")])
        )
        snapshot = _build(
            self.root,
            search_reports=[search],
            comment_reports=[("comment-repair-probe.json", first)],
        )

        self.assertEqual(snapshot["status"], "complete")
        self.assertEqual(snapshot["accounting"]["canonical_post_count"], 1)
        self.assertEqual(snapshot["accounting"]["canonical_comment_count"], 1)
        self.assertEqual(snapshot["accounting"]["canonical_analysis_count"], 2)
        self.assertEqual(
            snapshot["accounting"]["blockers"],
            {
                "lineage_missing": 0,
                "search_post_conflicts": 0,
                "outside_target_window": 0,
                "first_page_missing": 0,
                "cursor_outstanding": 0,
                "cursor_cycles": 0,
                "page_pagination_outstanding": 0,
                "orphan_reply_reports": 0,
                "report_conflicts": 0,
                "comment_conflicts": 0,
                "failed_reports": 0,
            },
        )
        rendered = canonical_bytes(snapshot).decode("utf-8")
        self.assertNotIn("raw-user-must-not-survive", rendered)
        self.assertNotIn('"payload"', rendered)
        self.assertTrue(snapshot["comments"][0]["author_hash"])
        first_path = self.root / "first.json"
        second_path = self.root / "second.json"
        first_sha = write_snapshot(snapshot, first_path)
        second_sha = write_snapshot(snapshot, second_path)
        self.assertEqual(first_sha, second_sha)
        self.assertEqual(first_path.read_bytes(), second_path.read_bytes())
        self.assertEqual(first_path.stat().st_mode & 0o777, 0o600)

    def test_deduplicates_identical_search_and_comment_reports(self) -> None:
        search = _search_report(_search_payload())
        first = _comment_report(
            _comment_payload(comments=[_comment_node("c1", "same")])
        )
        snapshot = _build(
            self.root,
            search_reports=[search, search],
            comment_reports=[
                ("comment-repair-probe.json", first),
                ("comment-repair-probe.json", first),
            ],
        )

        self.assertEqual(snapshot["status"], "complete")
        self.assertEqual(
            snapshot["accounting"]["duplicate_search_occurrence_count"], 1
        )
        self.assertEqual(
            snapshot["accounting"]["duplicate_first_page_report_count"], 1
        )
        self.assertEqual(len(snapshot["posts"]), 1)
        self.assertEqual(len(snapshot["comments"]), 1)

    def test_accepts_reviewed_search_crosspost_primary_wrapper(self) -> None:
        payload = _search_payload()
        payload["data"]["search"]["dynamic"]["components"]["main"]["edges"][0][
            "node"
        ]["children"][0]["__typename"] = "SearchCrosspost"
        search = _search_report(payload)
        first = _comment_report(_comment_payload())

        snapshot = _build(
            self.root,
            search_reports=[search],
            comment_reports=[("comment-repair-probe.json", first)],
        )

        self.assertEqual(snapshot["status"], "complete")
        self.assertEqual(snapshot["accounting"]["canonical_post_count"], 1)
        self.assertEqual(snapshot["accounting"]["search_row_rejection_count"], 0)

    def test_rejects_invalid_row_without_discarding_valid_target_row(self) -> None:
        payload = _search_payload()
        children = payload["data"]["search"]["dynamic"]["components"]["main"][
            "edges"
        ][0]["node"]["children"]
        invalid = dict(children[0]["post"])
        invalid.update(
            {
                "__typename": "ProfilePost",
                "id": f"t3_{OTHER_POST_ID}",
                "permalink": (
                    "https://www.reddit.com/r/MomCozy/comments/"
                    f"{OTHER_POST_ID}/profile-fixture/"
                ),
            }
        )
        children.append({"__typename": "SearchPost", "post": invalid})
        search = _search_report(payload)
        first = _comment_report(_comment_payload())

        snapshot = _build(
            self.root,
            search_reports=[search],
            comment_reports=[("comment-repair-probe.json", first)],
        )

        self.assertEqual(snapshot["status"], "complete")
        self.assertEqual(snapshot["accounting"]["canonical_post_count"], 1)
        self.assertEqual(snapshot["accounting"]["blockers"]["failed_reports"], 0)
        self.assertEqual(snapshot["accounting"]["search_candidate_occurrence_count"], 2)
        self.assertEqual(
            snapshot["accounting"]["search_semantic_primary_occurrence_count"], 1
        )
        self.assertEqual(snapshot["accounting"]["search_row_rejection_count"], 1)
        self.assertEqual(
            snapshot["accounting"]["search_row_rejections"][0]["reason"],
            "search_primary_typename_invalid",
        )
        self.assertFalse(
            snapshot["accounting"]["search_row_rejections"][0]["is_target"]
        )

    def test_accepts_exact_reviewed_terminal_empty_search_page(self) -> None:
        search = _search_report(_terminal_empty_search_payload())

        snapshot = _build(self.root, search_reports=[search])

        self.assertEqual(snapshot["status"], "blocked")
        self.assertEqual(snapshot["accounting"]["canonical_post_count"], 0)
        self.assertEqual(snapshot["accounting"]["blockers"]["failed_reports"], 0)
        self.assertEqual(
            snapshot["accounting"]["search_terminal_empty_report_count"], 1
        )
        self.assertEqual(snapshot["accounting"]["search_row_rejection_count"], 0)
        self.assertEqual(
            snapshot["accounting"]["lineage_missing_post_ids"], [POST_ID]
        )

    def test_fails_closed_on_payload_hash_drift(self) -> None:
        search = _search_report(_search_payload())
        first = _comment_report(_comment_payload())
        first["payload_sha256"] = "0" * 64
        snapshot = _build(
            self.root,
            search_reports=[search],
            comment_reports=[("comment-repair-probe.json", first)],
        )

        self.assertEqual(snapshot["status"], "blocked")
        self.assertEqual(snapshot["accounting"]["blockers"]["failed_reports"], 1)
        self.assertEqual(
            snapshot["accounting"]["blockers"]["first_page_missing"], 1
        )
        self.assertEqual(
            snapshot["accounting"]["failed_reports"][0]["reason"],
            "report_payload_sha256_mismatch",
        )

    def test_fails_closed_on_comment_identity_conflict(self) -> None:
        cursor = "cursor-one"
        search = _search_report(_search_payload())
        first_payload = _comment_payload(
            comments=[_comment_node("c1", "first body")], cursors=[cursor]
        )
        first = _comment_report(first_payload)
        reply = _reply_report(
            _comment_payload(comments=[_comment_node("c1", "conflicting body")]),
            cursor=cursor,
            source_sha256=first["payload_sha256"],
        )
        snapshot = _build(
            self.root,
            search_reports=[search],
            comment_reports=[
                ("comment-repair-probe.json", first),
                ("comment-reply-probe.json", reply),
            ],
        )

        self.assertEqual(snapshot["status"], "blocked")
        self.assertEqual(
            snapshot["accounting"]["blockers"]["comment_conflicts"], 1
        )
        self.assertEqual(snapshot["comments"], [])
        conflict = snapshot["accounting"]["comment_conflicts"][0]
        self.assertEqual(conflict["comment_id"], "t1_c1")
        self.assertIn("body", conflict["differing_fields"])

    def test_closes_reachable_reply_cursor_chain(self) -> None:
        cursor = "cursor-one"
        search = _search_report(_search_payload())
        first_payload = _comment_payload(
            comments=[_comment_node("c1", "first")], cursors=[cursor]
        )
        first = _comment_report(first_payload)
        reply = _reply_report(
            _comment_payload(
                comments=[_comment_node("c2", "reply", parent_id="t1_c1")]
            ),
            cursor=cursor,
            source_sha256=first["payload_sha256"],
        )
        snapshot = _build(
            self.root,
            search_reports=[search],
            comment_reports=[
                ("comment-repair-probe.json", first),
                ("comment-reply-probe.json", reply),
            ],
        )

        self.assertEqual(snapshot["status"], "complete")
        self.assertEqual(snapshot["accounting"]["cursor_outstanding"], [])
        self.assertEqual(snapshot["accounting"]["orphan_reply_reports"], [])
        self.assertNotIn("reply_source_resolution", snapshot["accounting"])
        native_reply_source = next(
            row
            for row in snapshot["source_reports"]
            if row["report_kind"] == "reply"
        )
        self.assertNotIn("source_binding_mode", native_reply_source)
        self.assertEqual(
            [row["comment_id"] for row in snapshot["comments"]],
            ["t1_c1", "t1_c2"],
        )

    def test_derives_legacy_null_reply_source_from_unique_parent(self) -> None:
        cursor = "cursor-one"
        search = _search_report(_search_payload())
        first = _comment_report(
            _comment_payload(
                comments=[_comment_node("c1", "first")], cursors=[cursor]
            )
        )
        reply = _reply_report(
            _comment_payload(
                comments=[_comment_node("c2", "reply", parent_id="t1_c1")]
            ),
            cursor=cursor,
            source_sha256=None,
        )

        snapshot = _build(
            self.root,
            search_reports=[search],
            comment_reports=[
                ("comment-repair-probe.json", first),
                ("comment-reply-probe.json", reply),
            ],
        )

        self.assertEqual(snapshot["status"], "complete")
        reply_source = next(
            row
            for row in snapshot["source_reports"]
            if row["report_kind"] == "reply"
        )
        self.assertEqual(
            reply_source["source_payload_sha256"], first["payload_sha256"]
        )
        self.assertEqual(
            reply_source["source_binding_mode"],
            "legacy_structural_source_derived",
        )

    def test_rejects_legacy_null_reply_without_valid_parent(self) -> None:
        search = _search_report(_search_payload())
        first = _comment_report(_comment_payload())
        reply = _reply_report(
            _comment_payload(comments=[_comment_node("c2", "unbound")]),
            cursor="cursor-not-produced",
            source_sha256=None,
        )

        snapshot = _build(
            self.root,
            search_reports=[search],
            comment_reports=[
                ("comment-repair-probe.json", first),
                ("comment-reply-probe.json", reply),
            ],
        )

        self.assertEqual(snapshot["status"], "blocked")
        self.assertEqual(snapshot["accounting"]["blockers"]["failed_reports"], 1)
        self.assertEqual(
            snapshot["accounting"]["failed_reports"][0]["reason"],
            "legacy_reply_source_predecessor_missing",
        )

    def test_rejects_legacy_null_reply_with_ambiguous_parent(self) -> None:
        parent_a = "cursor-parent-a"
        parent_b = "cursor-parent-b"
        child = "cursor-child"
        search = _search_report(_search_payload())
        first = _comment_report(
            _comment_payload(cursors=[parent_a, parent_b])
        )
        reply_a = _reply_report(
            _comment_payload(
                comments=[_comment_node("c1", "parent a")], cursors=[child]
            ),
            cursor=parent_a,
            source_sha256=first["payload_sha256"],
        )
        reply_b = _reply_report(
            _comment_payload(
                comments=[_comment_node("c2", "parent b")], cursors=[child]
            ),
            cursor=parent_b,
            source_sha256=first["payload_sha256"],
        )
        child_reply = _reply_report(
            _comment_payload(comments=[_comment_node("c3", "child")]),
            cursor=child,
            source_sha256=None,
        )

        snapshot = _build(
            self.root,
            search_reports=[search],
            comment_reports=[
                ("comment-repair-probe.json", first),
                ("comment-reply-probe.json", reply_a),
                ("comment-reply-probe.json", reply_b),
                ("comment-reply-probe.json", child_reply),
            ],
        )

        reasons = {
            row["reason"] for row in snapshot["accounting"]["failed_reports"]
        }
        self.assertIn("legacy_reply_source_predecessor_ambiguous", reasons)

    def test_derives_legacy_null_reply_through_rooted_chain(self) -> None:
        parent = "cursor-parent"
        child = "cursor-child"
        search = _search_report(_search_payload())
        first = _comment_report(_comment_payload(cursors=[parent]))
        parent_reply = _reply_report(
            _comment_payload(
                comments=[_comment_node("c1", "parent")], cursors=[child]
            ),
            cursor=parent,
            source_sha256=None,
        )
        child_reply = _reply_report(
            _comment_payload(comments=[_comment_node("c2", "child")]),
            cursor=child,
            source_sha256=None,
        )

        snapshot = _build(
            self.root,
            search_reports=[search],
            comment_reports=[
                ("comment-repair-probe.json", first),
                ("comment-reply-probe.json", parent_reply),
                ("comment-reply-probe.json", child_reply),
            ],
        )

        self.assertEqual(snapshot["status"], "complete")
        resolution = snapshot["accounting"]["reply_source_resolution"]
        self.assertEqual(resolution["legacy_null_reply_report_count"], 2)
        self.assertEqual(
            resolution["legacy_structural_source_derived_count"], 2
        )

    def test_rejects_legacy_null_reply_cycle_without_first_page_root(self) -> None:
        cursor_a = "cursor-a"
        cursor_b = "cursor-b"
        search = _search_report(_search_payload())
        first = _comment_report(_comment_payload())
        reply_a = _reply_report(
            _comment_payload(cursors=[cursor_b]),
            cursor=cursor_a,
            source_sha256=None,
        )
        reply_b = _reply_report(
            _comment_payload(cursors=[cursor_a]),
            cursor=cursor_b,
            source_sha256=None,
        )

        snapshot = _build(
            self.root,
            search_reports=[search],
            comment_reports=[
                ("comment-repair-probe.json", first),
                ("comment-reply-probe.json", reply_a),
                ("comment-reply-probe.json", reply_b),
            ],
        )

        reasons = [
            row["reason"] for row in snapshot["accounting"]["failed_reports"]
        ]
        self.assertEqual(
            reasons.count("legacy_reply_source_chain_incomplete"), 2
        )

    def test_rejects_legacy_null_reply_with_two_same_payload_parents(self) -> None:
        parent_a = "cursor-parent-a"
        parent_b = "cursor-parent-b"
        child = "cursor-child"
        search = _search_report(_search_payload())
        first = _comment_report(
            _comment_payload(cursors=[parent_a, parent_b])
        )
        shared_parent_payload = _comment_payload(cursors=[child])
        reply_a = _reply_report(
            shared_parent_payload,
            cursor=parent_a,
            source_sha256=first["payload_sha256"],
        )
        reply_b = _reply_report(
            shared_parent_payload,
            cursor=parent_b,
            source_sha256=first["payload_sha256"],
        )
        child_reply = _reply_report(
            _comment_payload(), cursor=child, source_sha256=None
        )

        snapshot = _build(
            self.root,
            search_reports=[search],
            comment_reports=[
                ("comment-repair-probe.json", first),
                ("comment-reply-probe.json", reply_a),
                ("comment-reply-probe.json", reply_b),
                ("comment-reply-probe.json", child_reply),
            ],
        )

        reasons = {
            row["reason"] for row in snapshot["accounting"]["failed_reports"]
        }
        self.assertIn("legacy_reply_source_predecessor_ambiguous", reasons)

    def test_rejects_explicit_reply_source_that_is_not_direct_parent(self) -> None:
        parent = "cursor-parent"
        child = "cursor-child"
        search = _search_report(_search_payload())
        first = _comment_report(_comment_payload(cursors=[parent]))
        parent_reply = _reply_report(
            _comment_payload(
                comments=[_comment_node("c1", "parent")], cursors=[child]
            ),
            cursor=parent,
            source_sha256=first["payload_sha256"],
        )
        child_reply = _reply_report(
            _comment_payload(comments=[_comment_node("c2", "child")]),
            cursor=child,
            source_sha256=first["payload_sha256"],
        )

        snapshot = _build(
            self.root,
            search_reports=[search],
            comment_reports=[
                ("comment-repair-probe.json", first),
                ("comment-reply-probe.json", parent_reply),
                ("comment-reply-probe.json", child_reply),
            ],
        )

        reasons = {
            row["reason"] for row in snapshot["accounting"]["failed_reports"]
        }
        self.assertIn("comment_reply_source_payload_mismatch", reasons)

    def test_rejects_reply_with_absent_source_field(self) -> None:
        cursor = "cursor-one"
        search = _search_report(_search_payload())
        first = _comment_report(_comment_payload(cursors=[cursor]))
        reply = _reply_report(
            _comment_payload(comments=[_comment_node("c1", "reply")]),
            cursor=cursor,
            source_sha256=None,
        )
        del reply["source_first_page_payload_sha256"]

        snapshot = _build(
            self.root,
            search_reports=[search],
            comment_reports=[
                ("comment-repair-probe.json", first),
                ("comment-reply-probe.json", reply),
            ],
        )

        self.assertEqual(
            snapshot["accounting"]["failed_reports"][0]["reason"],
            "comment_reply_source_sha256_invalid",
        )

    def test_rejects_reply_with_malformed_non_null_source(self) -> None:
        cursor = "cursor-one"
        search = _search_report(_search_payload())
        first = _comment_report(_comment_payload(cursors=[cursor]))
        reply = _reply_report(
            _comment_payload(), cursor=cursor, source_sha256="not-a-sha"
        )

        snapshot = _build(
            self.root,
            search_reports=[search],
            comment_reports=[
                ("comment-repair-probe.json", first),
                ("comment-reply-probe.json", reply),
            ],
        )

        self.assertEqual(
            snapshot["accounting"]["failed_reports"][0]["reason"],
            "comment_reply_source_sha256_invalid",
        )

    def test_reports_missing_semantic_primary_lineage(self) -> None:
        search = _search_report(_search_payload(OTHER_POST_ID))
        first = _comment_report(_comment_payload())
        snapshot = _build(
            self.root,
            search_reports=[search],
            comment_reports=[("comment-repair-probe.json", first)],
        )

        self.assertEqual(snapshot["status"], "blocked")
        self.assertEqual(
            snapshot["accounting"]["lineage_missing_post_ids"], [POST_ID]
        )
        self.assertEqual(snapshot["accounting"]["blockers"]["lineage_missing"], 1)
        self.assertEqual(snapshot["posts"], [])

    def test_rejects_duplicate_identity_set_before_report_processing(self) -> None:
        inventory = self.root / "inventory.json"
        count, digest = _inventory(inventory, [POST_ID, POST_ID])
        search_root = self.root / "search"
        comments_root = self.root / "comments"
        search_root.mkdir()
        comments_root.mkdir()

        with self.assertRaisesRegex(
            SnapshotContractError, "identity_set_post_ids_duplicate"
        ):
            build(
                inventory,
                set_id="target",
                expected_target_count=count,
                expected_target_sha256=digest,
                search_report_roots=[search_root],
                comment_report_roots=[comments_root],
            )

    def test_rejects_expected_target_hash_mismatch(self) -> None:
        inventory = self.root / "inventory.json"
        count, _digest = _inventory(inventory)
        search_root = self.root / "search"
        comments_root = self.root / "comments"
        search_root.mkdir()
        comments_root.mkdir()

        with self.assertRaisesRegex(
            SnapshotContractError, "identity_set_count_or_sha256_mismatch"
        ):
            build(
                inventory,
                set_id="target",
                expected_target_count=count,
                expected_target_sha256="0" * 64,
                search_report_roots=[search_root],
                comment_report_roots=[comments_root],
            )

    def test_accepts_identity_freeze_lf_sha256_field(self) -> None:
        inventory = self.root / "inventory.json"
        count, digest = _inventory(inventory, hash_field="lf_sha256")
        search_root = self.root / "search"
        comments_root = self.root / "comments"
        search_root.mkdir()
        comments_root.mkdir()

        snapshot = build(
            inventory,
            set_id="target",
            expected_target_count=count,
            expected_target_sha256=digest,
            search_report_roots=[search_root],
            comment_report_roots=[comments_root],
        )

        self.assertEqual(snapshot["target"]["post_ids_sha256"], digest)
        self.assertEqual(snapshot["accounting"]["blockers"]["lineage_missing"], 1)

    def test_target_window_uses_half_open_end(self) -> None:
        snapshot = _build(
            self.root,
            search_reports=[
                _search_report(
                    _search_payload(created_at="2026-07-15T16:00:00Z")
                )
            ],
        )

        self.assertEqual(snapshot["accounting"]["blockers"]["outside_target_window"], 1)
        self.assertEqual(
            snapshot["accounting"]["outside_target_window_post_ids"],
            [POST_ID],
        )


if __name__ == "__main__":
    unittest.main()
