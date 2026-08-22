from __future__ import annotations

import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from reddit_voc.comment_repair import (
    build_comment_repair_plan,
    build_comment_repair_plan_from_rows,
    parse_comment_repair_payload,
    write_comment_repair_plan,
)


class CommentRepairPlanTests(unittest.TestCase):
    def make_db(self, root: Path) -> Path:
        path = root / "staging.sqlite3"
        with sqlite3.connect(path) as connection:
            connection.executescript(
                """
                CREATE TABLE backfill_candidates(
                    run_id TEXT, post_id TEXT, status TEXT, status_reason TEXT
                );
                CREATE TABLE reddit_threads(
                    run_id TEXT, post_id TEXT, num_comments_reported INTEGER,
                    parsed_comment_count INTEGER, more_node_count INTEGER,
                    coverage_grade TEXT
                );
                CREATE TABLE backfill_checkpoints(
                    run_id TEXT, lane_type TEXT, lane_key TEXT, status TEXT,
                    stop_reason TEXT, page_number INTEGER
                );
                """
            )
            rows = (
                ("run", "post-z", "hydrated", "post_only_coverage", 10, 1, 0, "post_only", "complete", "cursor_exhausted", 1),
                ("run", "post-a", "hydrated", "unresolved_more", 200, 20, 3, "partial", "partial", "unresolved_more", 1),
                ("run", "post-b", "hydrated", "unresolved_more", 50, 49, 1, "partial", "partial", "unresolved_more", 1),
                ("run", "done", "hydrated", None, 1, 1, 0, "full", "complete", "cursor_exhausted", 1),
                ("other", "other", "hydrated", "unresolved_more", 5, 0, 1, "partial", "partial", "unresolved_more", 1),
            )
            for row in rows:
                connection.execute(
                    "INSERT INTO backfill_candidates VALUES (?, ?, ?, ?)", row[:4]
                )
                connection.execute(
                    "INSERT INTO reddit_threads VALUES (?, ?, ?, ?, ?, ?)",
                    (row[0], row[1], *row[4:8]),
                )
                connection.execute(
                    "INSERT INTO backfill_checkpoints VALUES (?, 'comments', ?, ?, ?, ?)",
                    (row[0], row[1], row[8], row[9], row[10]),
                )
        return path

    def test_selects_only_terminal_comment_debt_in_deterministic_priority(self):
        with TemporaryDirectory() as directory:
            plan = build_comment_repair_plan(
                self.make_db(Path(directory)),
                run_id="run",
                provider_request_ceiling=1,
            )
        self.assertEqual(plan.candidate_count, 3)
        self.assertEqual(plan.selected_candidate_count, 1)
        self.assertEqual(
            [candidate.post_id for candidate in plan.candidates],
            ["post-a", "post-b", "post-z"],
        )
        self.assertEqual(plan.minimum_first_page_requests, 3)
        self.assertEqual(plan.cursor_source, "fresh_tikhub_comments_page_required")

    def test_plan_write_is_canonical_and_hashed(self):
        with TemporaryDirectory() as directory:
            plan = build_comment_repair_plan(
                self.make_db(Path(directory)),
                run_id="run",
                provider_request_ceiling=2,
            )
            destination = Path(directory) / "reports" / "repair.json"
            digest = write_comment_repair_plan(plan, destination)
            self.assertEqual(digest, __import__("hashlib").sha256(destination.read_bytes()).hexdigest())
            self.assertTrue(destination.read_bytes().endswith(b"\n"))

    def test_remote_row_snapshot_binds_first_page_artifact(self):
        plan = build_comment_repair_plan_from_rows(
            [
                {
                    "post_id": "remote-post",
                    "status_reason": "unresolved_more",
                    "reported_count": 12,
                    "parsed_count": 8,
                    "more_count": 1,
                    "coverage_grade": "partial",
                    "checkpoint_status": "partial",
                    "checkpoint_stop_reason": "unresolved_more",
                    "checkpoint_page_number": 1,
                    "first_page_artifact_id": "raw_artifact_1",
                    "first_page_payload_sha256": "a" * 64,
                }
            ],
            run_id="remote-run",
            provider_request_ceiling=1,
        )
        candidate = plan.candidates[0]
        self.assertEqual(candidate.first_page_artifact_id, "raw_artifact_1")
        self.assertEqual(candidate.first_page_payload_sha256, "a" * 64)

    def test_parse_comment_repair_payload_extracts_comments_and_more_cursors(self):
        payload = {
            "data": {
                "postInfoById": {
                    "id": "t3_post-1",
                    "commentCount": 4,
                    "commentForest": {
                        "pageInfo": {"hasNextPage": True},
                        "trees": [
                            {
                                "depth": 0,
                                "node": {
                                    "__typename": "Comment",
                                    "id": "c1",
                                    "content": {"markdown": "first"},
                                    "createdAt": "2026-07-14T00:00:00Z",
                                },
                                "children": {
                                    "trees": [
                                        {
                                            "depth": 1,
                                            "node": {
                                                "__typename": "Comment",
                                                "id": "c2",
                                                "content": {"markdown": "reply"},
                                                "createdAt": "2026-07-14T00:01:00Z",
                                            },
                                            "parentId": "t1_c1",
                                        }
                                    ]
                                },
                            },
                            {"more": {"cursor": "cursor-1"}},
                        ],
                    },
                }
            }
        }
        result = parse_comment_repair_payload(payload, expected_post_id="post-1")
        self.assertEqual(result["parsed_comment_count"], 2)
        self.assertEqual(result["more_node_count"], 1)
        self.assertEqual(result["more_cursors"], ("cursor-1",))
        self.assertTrue(result["has_next_page"])
        self.assertEqual([row["comment_id"] for row in result["comments"]], ["t1_c1", "t1_c2"])

    def test_parse_comment_repair_payload_rejects_wrong_post(self):
        payload = {"data": {"postInfoById": {"id": "t3_other", "commentForest": {"trees": []}}}}
        with self.assertRaisesRegex(ValueError, "post_mismatch"):
            parse_comment_repair_payload(payload, expected_post_id="post-1")


if __name__ == "__main__":
    unittest.main()
