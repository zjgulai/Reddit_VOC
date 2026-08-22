from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from reddit_voc.report_contracts import canonical_json_bytes
from reddit_voc.server_snapshot_source_batch import (
    ServerSnapshotSourceBatchError,
    build_server_snapshot_source_batch,
)
from reddit_voc.source_batch import load_source_batch


def _write_profile(path: Path, schema: str, version: str, **extra: object) -> None:
    value = {"schema_version": schema, "version": version, **extra}
    path.write_bytes(canonical_json_bytes(value) + b"\n")


class ServerSnapshotSourceBatchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = self.root / "server.sqlite3"
        with sqlite3.connect(self.database) as connection:
            connection.executescript(
                """
                CREATE TABLE reddit_threads(
                    post_id TEXT PRIMARY KEY, run_id TEXT, raw_capture_id TEXT,
                    subreddit TEXT, title TEXT, selftext TEXT, source_url TEXT,
                    created_at_utc TEXT, score INTEGER, num_comments_reported INTEGER,
                    parsed_comment_count INTEGER, more_node_count INTEGER,
                    coverage_grade TEXT, matched_keywords TEXT, author_hash TEXT,
                    media_urls TEXT
                );
                CREATE TABLE reddit_comments(
                    comment_id TEXT PRIMARY KEY, post_id TEXT, run_id TEXT,
                    raw_capture_id TEXT, parent_id TEXT, body TEXT,
                    created_at_utc TEXT, score INTEGER, depth INTEGER,
                    is_submitter INTEGER, matched_keywords TEXT, author_hash TEXT,
                    deleted_or_removed INTEGER
                );
                CREATE TABLE runs(
                    run_id TEXT PRIMARY KEY, status TEXT, window_start_utc TEXT,
                    window_end_utc TEXT, provider_call INTEGER
                );
                """
            )
            connection.execute(
                "INSERT INTO runs VALUES(?,?,?,?,?)",
                ("daily_1", "partial", "2026-07-16T23:00:00Z", "2026-07-17T23:00:00Z", 1),
            )
            connection.execute(
                "INSERT INTO reddit_threads VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "abc", "daily_1", "raw-post", "pumping", "Title", "Body",
                    "https://www.reddit.com/comments/abc", "2026-07-17T01:00:00Z",
                    5, 1, 1, 0, "full", "[]", "author", "[]",
                ),
            )
            connection.execute(
                "INSERT INTO reddit_comments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "c1", "abc", "daily_1", "raw-comment", None, "Comment",
                    "2026-07-17T02:00:00Z", 2, 0, 0, "[]", "author-2", 0,
                ),
            )
        self.query = self.root / "query.json"
        self.coverage = self.root / "coverage.json"
        _write_profile(self.query, "reddit_voc_query_profile_v1", "query-v1")
        _write_profile(self.coverage, "reddit_voc_coverage_profile_v1", "coverage-v1")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _build(self):
        return build_server_snapshot_source_batch(
            source_database_path=self.database,
            output_root=self.root / "batches",
            batch_id="server_snapshot_20260718",
            window_start_utc=datetime(2026, 7, 16, 23, tzinfo=timezone.utc),
            window_end_utc=datetime(2026, 7, 17, 23, tzinfo=timezone.utc),
            query_profile_path=self.query,
            coverage_profile_path=self.coverage,
        )

    def test_builds_valid_immutable_source_batch(self) -> None:
        source_sha = hashlib.sha256(self.database.read_bytes()).hexdigest()
        first = self._build()
        second = self._build()
        self.assertEqual(first.write_status, "created")
        self.assertEqual(second.write_status, "no_change")
        self.assertEqual(first.source_database_sha256, source_sha)
        batch = load_source_batch(first.manifest_path, first.batch_root, require_consumable=True)
        self.assertEqual(batch.producer_type, "historical_backfill")
        self.assertEqual(batch.status, "partial")
        self.assertEqual(batch.counts.posts, 1)
        self.assertEqual(batch.counts.comments, 1)
        self.assertTrue(batch.boundaries.provider_call)
        comment = json.loads(
            (first.batch_root / batch.member("comments").relative_path).read_text().splitlines()[0]
        )
        self.assertEqual(comment["comment_id"], "t1_c1")
        self.assertEqual(comment["post_id"], "t3_abc")
        self.assertEqual(comment["parent_id"], "t3_abc")
        self.assertEqual(comment["relationship_status"], "linked")

    def test_same_batch_id_rejects_changed_database(self) -> None:
        self._build()
        with sqlite3.connect(self.database) as connection:
            connection.execute("UPDATE reddit_threads SET title='Changed' WHERE post_id='abc'")
        with self.assertRaisesRegex(
            ServerSnapshotSourceBatchError, "immutable collision"
        ):
            self._build()


if __name__ == "__main__":
    unittest.main()
