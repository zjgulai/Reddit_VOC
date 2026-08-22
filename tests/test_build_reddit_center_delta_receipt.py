from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from scripts.build_reddit_center_delta_receipt import (
    CenterDeltaError,
    build_center_delta,
)


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _database(
    path: Path,
    *,
    posts: tuple[str, ...],
    comments: tuple[tuple[str, str], ...],
    debt: tuple[str, ...],
    occurrence_suffix: str,
) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE canonical_posts(
          post_id TEXT PRIMARY KEY, created_at_utc TEXT, last_observed_at_utc TEXT
        );
        CREATE TABLE canonical_comments(
          comment_id TEXT PRIMARY KEY, post_id TEXT, created_at_utc TEXT,
          last_observed_at_utc TEXT
        );
        CREATE TABLE relationship_debt(comment_id TEXT PRIMARY KEY);
        CREATE TABLE entity_occurrences(
          occurrence_id TEXT PRIMARY KEY, entity_type TEXT
        );
        """
    )
    for index, post_id in enumerate(posts):
        connection.execute(
            "INSERT INTO canonical_posts VALUES(?,?,?)",
            (post_id, f"2026-07-{index + 1:02d}T00:00:00Z", f"2026-07-{index + 1:02d}T00:00:00Z"),
        )
        connection.execute(
            "INSERT INTO entity_occurrences VALUES(?,?)",
            (f"post-{post_id}-{occurrence_suffix}", "post"),
        )
    for index, (comment_id, post_id) in enumerate(comments):
        connection.execute(
            "INSERT INTO canonical_comments VALUES(?,?,?,?)",
            (
                comment_id,
                post_id,
                f"2026-07-{index + 1:02d}T01:00:00Z",
                f"2026-07-{index + 1:02d}T01:00:00Z",
            ),
        )
        connection.execute(
            "INSERT INTO entity_occurrences VALUES(?,?)",
            (f"comment-{comment_id}-{occurrence_suffix}", "comment"),
        )
    for comment_id in debt:
        connection.execute("INSERT INTO relationship_debt VALUES(?)", (comment_id,))
    connection.commit()
    connection.close()


class CenterDeltaReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.before = self.root / "before.sqlite3"
        self.after = self.root / "after.sqlite3"
        self.batch = self.root / "batch"
        self.batch.mkdir()
        _database(
            self.before,
            posts=("t3_old",),
            comments=(("t1_old", "t3_old"),),
            debt=("t1_old",),
            occurrence_suffix="before",
        )
        _database(
            self.after,
            posts=("t3_old", "t3_new"),
            comments=(("t1_old", "t3_old"), ("t1_new", "t3_new")),
            debt=(),
            occurrence_suffix="after",
        )
        _write_jsonl(
            self.batch / "posts.jsonl",
            [{"post_id": "t3_old"}, {"post_id": "t3_new"}],
        )
        _write_jsonl(
            self.batch / "comments.jsonl",
            [{"comment_id": "t1_old"}, {"comment_id": "t1_new"}],
        )
        self.manifest = self.batch / "source-batch-manifest.json"
        _write_json(self.manifest, {"batch_id": "fixture_batch"})
        self.receipt = self.root / "validation.json"
        _write_json(
            self.receipt,
            {
                "status": "passed",
                "consumable": True,
                "manifest_sha256": _sha(self.manifest),
            },
        )

    def test_reports_net_new_existing_observations_and_repaired_links(self) -> None:
        result = build_center_delta(
            before_database=self.before,
            after_database=self.after,
            source_batch_root=self.batch,
            source_batch_validation_receipt=self.receipt,
        )
        self.assertEqual(
            result["net_new"],
            {
                "posts": 1,
                "comments": 1,
                "updated_historical_posts": 1,
                "observed_existing_comments": 1,
                "repaired_parent_links": 1,
            },
        )
        self.assertEqual(result["after"]["posts"], 2)
        self.assertEqual(result["after"]["comments"], 2)

    def test_rejects_new_entity_not_present_in_source_batch(self) -> None:
        _write_jsonl(self.batch / "posts.jsonl", [{"post_id": "t3_old"}])
        with self.assertRaisesRegex(CenterDeltaError, "new_posts_not_bound_to_source_batch"):
            build_center_delta(
                before_database=self.before,
                after_database=self.after,
                source_batch_root=self.batch,
                source_batch_validation_receipt=self.receipt,
            )

    def test_rejects_non_monotonic_center(self) -> None:
        smaller = self.root / "smaller.sqlite3"
        _database(
            smaller,
            posts=(),
            comments=(),
            debt=(),
            occurrence_suffix="small",
        )
        with self.assertRaisesRegex(CenterDeltaError, "canonical_posts_not_monotonic"):
            build_center_delta(
                before_database=self.before,
                after_database=smaller,
                source_batch_root=self.batch,
                source_batch_validation_receipt=self.receipt,
            )


if __name__ == "__main__":
    unittest.main()
