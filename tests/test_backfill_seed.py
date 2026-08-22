from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from reddit_voc.backfill_archive import PrivateRawArchive
from reddit_voc.backfill_models import BackfillManifest
from reddit_voc.backfill_seed import (
    SeedImportSummary,
    import_seed_directory,
    make_raw_capture_id,
)
from reddit_voc.backfill_storage import BackfillStore


WINDOW_START = datetime(2024, 12, 31, 16, tzinfo=timezone.utc)
EFFECTIVE_END = datetime(2026, 7, 11, 16, tzinfo=timezone.utc)
FIXED_NOW = datetime(2026, 7, 11, 4, 17, 9, tzinfo=timezone.utc)


def make_payload(
    *,
    post_id: str,
    post_created_at: datetime,
    title: str,
    selftext: str = "",
    comment_body: str | None = None,
    comment_created_at: datetime | None = None,
) -> list[object]:
    comments: list[dict[str, object]] = []
    if comment_body is not None:
        comments.append(
            {
                "kind": "t1",
                "data": {
                    "id": f"{post_id}_comment",
                    "name": f"t1_{post_id}_comment",
                    "parent_id": f"t3_{post_id}",
                    "body": comment_body,
                    "created_utc": (comment_created_at or post_created_at).timestamp(),
                    "score": 2,
                    "depth": 0,
                    "is_submitter": False,
                    "author": "fixture-comment-author",
                },
            }
        )
    return [
        {
            "kind": "Listing",
            "data": {
                "children": [
                    {
                        "kind": "t3",
                        "data": {
                            "id": post_id,
                            "name": f"t3_{post_id}",
                            "subreddit": "ExclusivelyPumping",
                            "title": title,
                            "selftext": selftext,
                            "permalink": (
                                "/r/ExclusivelyPumping/comments/"
                                f"{post_id}/fixture_thread/"
                            ),
                            "created_utc": post_created_at.timestamp(),
                            "score": 12,
                            "num_comments": len(comments),
                            "author": "fixture-post-author",
                        },
                    }
                ]
            },
        },
        {"kind": "Listing", "data": {"children": comments}},
    ]


class BackfillSeedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.store = BackfillStore(self.root / "backfill.sqlite3")
        self.store.migrate()
        self.store.create_manifest(
            BackfillManifest(
                run_id="backfill_test",
                status="prepared",
                window_start_utc=WINDOW_START.isoformat(),
                requested_end_utc=EFFECTIVE_END.isoformat(),
                effective_end_utc=EFFECTIVE_END.isoformat(),
                search_terms=("Momcozy",),
                subreddits=("ExclusivelyPumping",),
                include_subreddit_sweep=False,
                required_lanes_sha256="1" * 64,
                keyword_config_sha256="2" * 64,
                max_provider_requests=0,
                provider_request_count=0,
                provider_call=False,
                live_send=False,
                created_at_utc=FIXED_NOW.isoformat(),
                updated_at_utc=FIXED_NOW.isoformat(),
            )
        )
        self.archive = PrivateRawArchive(self.root / "private-raw")

    def write_payload(self, name: str, payload: list[object]) -> Path:
        path = self.source / name
        path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        return path

    def import_seed(
        self, *, captured_at_utc: datetime = FIXED_NOW
    ) -> SeedImportSummary:
        return import_seed_directory(
            self.store,
            self.archive,
            run_id="backfill_test",
            source_dir=self.source,
            window_start_utc=WINDOW_START,
            effective_end_utc=EFFECTIVE_END,
            captured_at_utc=captured_at_utc,
        )

    def test_summary_contract_is_exact_and_immutable(self):
        self.assertTrue(SeedImportSummary.__dataclass_params__.frozen)
        self.assertEqual(
            tuple(field.name for field in fields(SeedImportSummary)),
            (
                "run_id",
                "status",
                "files_total",
                "files_imported",
                "files_outside_window",
                "files_excluded",
                "files_duplicate",
                "parse_errors",
                "threads",
                "comments",
                "analyses",
                "coverage_full",
                "coverage_partial",
                "coverage_post_only",
                "provider_call",
                "live_send",
            ),
        )
        summary = SeedImportSummary(
            "run", "seed_complete", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
        )
        with self.assertRaises(FrozenInstanceError):
            summary.status = "failed"
        self.assertFalse(summary.provider_call)
        self.assertFalse(summary.live_send)

    def test_raw_capture_id_is_deterministic_and_run_scoped(self):
        arguments = {
            "run_id": "backfill_test",
            "source_method": "historical_seed",
            "source_url": "seed://" + "1" * 64,
            "payload_sha256": "2" * 64,
        }
        expected_hash = sha256(
            "\0".join(arguments.values()).encode()
        ).hexdigest()[:24]

        first = make_raw_capture_id(**arguments)
        second = make_raw_capture_id(**arguments)
        other_run = make_raw_capture_id(**{**arguments, "run_id": "other_run"})

        self.assertEqual(first, f"raw_backfill_{expected_hash}")
        self.assertEqual(second, first)
        self.assertNotEqual(other_run, first)

    def test_import_covers_window_relevance_parse_error_and_private_provenance(self):
        file_names = (
            "01-in-window.json",
            "02-outside-window.json",
            "03-comment-only.json",
            "04-excluded.json",
            "05-malformed.json",
        )
        self.write_payload(
            file_names[0],
            make_payload(
                post_id="in_window",
                post_created_at=WINDOW_START,
                title="Momcozy M5 leak",
                comment_body="Mine hurts and leaks.",
                comment_created_at=WINDOW_START.replace(year=2024),
            ),
        )
        self.write_payload(
            file_names[1],
            make_payload(
                post_id="outside",
                post_created_at=WINDOW_START - timedelta(seconds=1),
                title="Momcozy wearable pump",
            ),
        )
        self.write_payload(
            file_names[2],
            make_payload(
                post_id="comment_only",
                post_created_at=WINDOW_START.replace(year=2025),
                title="Need product advice",
                selftext="Nothing named in the post.",
                comment_body="My Momcozy wearable pump works well.",
                comment_created_at=EFFECTIVE_END.replace(year=2027),
            ),
        )
        self.write_payload(
            file_names[3],
            make_payload(
                post_id="excluded",
                post_created_at=WINDOW_START.replace(year=2025),
                title="Momcozy pump compared with BMW M5",
            ),
        )
        malformed_bytes = b'{"private_fixture_name":"05-malformed.json"'
        (self.source / file_names[4]).write_bytes(malformed_bytes)

        summary = self.import_seed()

        self.assertEqual(
            summary,
            SeedImportSummary(
                run_id="backfill_test",
                status="failed",
                files_total=5,
                files_imported=2,
                files_outside_window=1,
                files_excluded=1,
                files_duplicate=0,
                parse_errors=1,
                threads=2,
                comments=2,
                analyses=4,
                coverage_full=2,
                coverage_partial=0,
                coverage_post_only=0,
            ),
        )
        self.assertEqual(self.store.seed_file_count("backfill_test"), summary.files_total)
        self.assertFalse(summary.provider_call)
        self.assertFalse(summary.live_send)

        with self.store.connect() as conn:
            outcomes = {
                row["outcome"]: row["count"]
                for row in conn.execute(
                    "SELECT outcome, COUNT(*) AS count FROM backfill_seed_files "
                    "GROUP BY outcome"
                )
            }
            rows = conn.execute(
                "SELECT input_path_hash, payload_sha256, outcome, artifact_id, "
                "post_id, error_class FROM backfill_seed_files "
                "ORDER BY input_path_hash"
            ).fetchall()
            captures = conn.execute(
                "SELECT source_method, source_url, auth_boundary, raw_payload_hash, "
                "payload_format, secrets_written FROM raw_captures "
                "ORDER BY source_url"
            ).fetchall()
            artifacts = conn.execute(
                "SELECT source_url, payload_sha256, relative_path "
                "FROM backfill_raw_artifacts ORDER BY source_url"
            ).fetchall()
            stored_comments = conn.execute(
                "SELECT comment_id, created_at_utc FROM reddit_comments "
                "ORDER BY comment_id"
            ).fetchall()
            comment_only_thread = conn.execute(
                "SELECT matched_keywords FROM reddit_threads "
                "WHERE post_id='comment_only'"
            ).fetchone()
            analysis_ids = {
                row[0]
                for row in conn.execute(
                    "SELECT analysis_id FROM analysis_results"
                ).fetchall()
            }
            statuses = (
                conn.execute(
                    "SELECT status FROM backfill_manifests WHERE run_id='backfill_test'"
                ).fetchone()[0],
                conn.execute(
                    "SELECT status FROM runs WHERE run_id='backfill_test'"
                ).fetchone()[0],
            )

        self.assertEqual(
            outcomes,
            {"excluded": 1, "imported": 2, "outside_window": 1, "parse_error": 1},
        )
        self.assertEqual(statuses, ("failed", "failed"))
        self.assertEqual(len(rows), 5)
        self.assertEqual(len(captures), 5)
        self.assertEqual(len(artifacts), 5)
        self.assertEqual(
            [tuple(row) for row in stored_comments],
            [
                ("t1_comment_only_comment", "2027-07-11T16:00:00+00:00"),
                ("t1_in_window_comment", "2024-12-31T16:00:00+00:00"),
            ],
        )
        self.assertIn("Momcozy", comment_only_thread["matched_keywords"])
        self.assertEqual(
            analysis_ids,
            {
                "analysis_post_in_window",
                "analysis_comment_t1_in_window_comment",
                "analysis_post_comment_only",
                "analysis_comment_t1_comment_only_comment",
            },
        )
        self.assertEqual(
            [row["error_class"] for row in rows if row["outcome"] == "parse_error"],
            ["JSONDecodeError"],
        )
        expected_urls = {
            "seed://" + sha256(name.encode()).hexdigest() for name in file_names
        }
        self.assertEqual({row["source_url"] for row in captures}, expected_urls)
        self.assertEqual({row["source_url"] for row in artifacts}, expected_urls)
        for capture in captures:
            self.assertEqual(capture["source_method"], "historical_seed")
            self.assertEqual(capture["auth_boundary"], "local_seed")
            self.assertRegex(capture["raw_payload_hash"], r"\Asha256:[0-9a-f]{64}\Z")
            self.assertEqual(capture["payload_format"], "json")
            self.assertEqual(capture["secrets_written"], 0)
        stored_provenance = "\n".join(
            str(value)
            for row in (*rows, *captures, *artifacts)
            for value in tuple(row)
            if value is not None
        )
        for name in file_names:
            self.assertNotIn(name, stored_provenance)
        self.assertEqual(
            {row["payload_sha256"] for row in artifacts},
            {row["payload_sha256"] for row in rows},
        )
        for artifact in artifacts:
            self.assertNotIn("01-in-window", artifact["relative_path"])
            self.assertEqual(
                sha256(self.archive.read_verified(self._artifact_for_url(artifact["source_url"]))).hexdigest(),
                artifact["payload_sha256"],
            )

    def _artifact_for_url(self, source_url: str):
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT * FROM backfill_raw_artifacts WHERE source_url = ?",
                (source_url,),
            ).fetchone()
        from reddit_voc.backfill_models import RawArtifactMetadata

        return RawArtifactMetadata(**dict(row))

    def test_sorted_duplicate_and_exact_replay_keep_identical_summary(self):
        first_name = "a-first.json"
        second_name = "b-second.json"
        self.write_payload(
            second_name,
            make_payload(
                post_id="same_post",
                post_created_at=WINDOW_START.replace(year=2025),
                title="Momcozy second payload",
            ),
        )
        self.write_payload(
            first_name,
            make_payload(
                post_id="same_post",
                post_created_at=WINDOW_START.replace(year=2025),
                title="Momcozy first payload",
            ),
        )

        first_summary = self.import_seed()
        with self.store.connect() as conn:
            first_ledger = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM backfill_seed_files ORDER BY input_path_hash"
                ).fetchall()
            ]
            first_counts = tuple(
                conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "raw_captures",
                    "backfill_raw_artifacts",
                    "reddit_threads",
                    "reddit_comments",
                    "analysis_results",
                )
            )

        replay_summary = self.import_seed(
            captured_at_utc=FIXED_NOW + timedelta(hours=1)
        )
        with self.store.connect() as conn:
            replay_ledger = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM backfill_seed_files ORDER BY input_path_hash"
                ).fetchall()
            ]
            replay_counts = tuple(
                conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "raw_captures",
                    "backfill_raw_artifacts",
                    "reddit_threads",
                    "reddit_comments",
                    "analysis_results",
                )
            )
            stored_title = conn.execute(
                "SELECT title FROM reddit_threads WHERE post_id='same_post'"
            ).fetchone()[0]
            updated_at_utc = conn.execute(
                "SELECT updated_at_utc FROM backfill_manifests "
                "WHERE run_id='backfill_test'"
            ).fetchone()[0]

        self.assertEqual(first_summary, replay_summary)
        self.assertEqual(first_summary.files_imported, 1)
        self.assertEqual(first_summary.files_duplicate, 1)
        self.assertEqual(first_ledger, replay_ledger)
        self.assertEqual(first_counts, replay_counts)
        self.assertEqual(first_counts, (2, 2, 1, 0, 1))
        self.assertEqual(stored_title, "Momcozy first payload")
        self.assertEqual(updated_at_utc, FIXED_NOW.isoformat())
        by_hash = {row["input_path_hash"]: row["outcome"] for row in first_ledger}
        self.assertEqual(by_hash[sha256(first_name.encode()).hexdigest()], "imported")
        self.assertEqual(by_hash[sha256(second_name.encode()).hexdigest()], "duplicate")

    def test_crash_before_seed_ledger_reuses_persisted_capture_time(self):
        self.write_payload(
            "interrupted.json",
            make_payload(
                post_id="interrupted",
                post_created_at=WINDOW_START.replace(year=2025),
                title="Momcozy interrupted import",
            ),
        )

        with patch.object(
            self.store,
            "record_seed_file",
            side_effect=RuntimeError("fault before seed ledger"),
        ):
            with self.assertRaisesRegex(RuntimeError, "fault before seed ledger"):
                self.import_seed()

        with self.store.connect() as conn:
            interrupted_counts = tuple(
                conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "raw_captures",
                    "backfill_raw_artifacts",
                    "reddit_threads",
                    "analysis_results",
                    "backfill_seed_files",
                )
            )
        self.assertEqual(interrupted_counts, (1, 1, 1, 1, 0))

        summary = self.import_seed(
            captured_at_utc=FIXED_NOW + timedelta(hours=1)
        )

        with self.store.connect() as conn:
            resumed_counts = tuple(
                conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "raw_captures",
                    "backfill_raw_artifacts",
                    "reddit_threads",
                    "analysis_results",
                    "backfill_seed_files",
                )
            )
            captured_at_values = (
                conn.execute(
                    "SELECT captured_at_utc FROM raw_captures"
                ).fetchone()[0],
                conn.execute(
                    "SELECT captured_at_utc FROM backfill_raw_artifacts"
                ).fetchone()[0],
            )

        self.assertEqual(summary.files_imported, 1)
        self.assertEqual(resumed_counts, (1, 1, 1, 1, 1))
        self.assertEqual(
            captured_at_values,
            (FIXED_NOW.isoformat(), FIXED_NOW.isoformat()),
        )

    def test_crash_between_raw_capture_and_artifact_reuses_capture_time(self):
        self.write_payload(
            "raw-gap.json",
            make_payload(
                post_id="raw_gap",
                post_created_at=WINDOW_START.replace(year=2025),
                title="Momcozy raw artifact gap",
            ),
        )

        with patch.object(
            self.store,
            "insert_raw_artifact",
            side_effect=RuntimeError("fault before artifact metadata"),
        ):
            with self.assertRaisesRegex(RuntimeError, "fault before artifact metadata"):
                self.import_seed()

        with self.store.connect() as conn:
            interrupted_counts = (
                conn.execute("SELECT COUNT(*) FROM raw_captures").fetchone()[0],
                conn.execute(
                    "SELECT COUNT(*) FROM backfill_raw_artifacts"
                ).fetchone()[0],
                conn.execute("SELECT COUNT(*) FROM reddit_threads").fetchone()[0],
                conn.execute(
                    "SELECT COUNT(*) FROM backfill_seed_files"
                ).fetchone()[0],
            )
        self.assertEqual(interrupted_counts, (1, 0, 0, 0))

        summary = self.import_seed(
            captured_at_utc=FIXED_NOW + timedelta(hours=1)
        )

        with self.store.connect() as conn:
            resumed_counts = (
                conn.execute("SELECT COUNT(*) FROM raw_captures").fetchone()[0],
                conn.execute(
                    "SELECT COUNT(*) FROM backfill_raw_artifacts"
                ).fetchone()[0],
                conn.execute("SELECT COUNT(*) FROM reddit_threads").fetchone()[0],
                conn.execute(
                    "SELECT COUNT(*) FROM backfill_seed_files"
                ).fetchone()[0],
            )
            captured_at_values = (
                conn.execute(
                    "SELECT captured_at_utc FROM raw_captures"
                ).fetchone()[0],
                conn.execute(
                    "SELECT captured_at_utc FROM backfill_raw_artifacts"
                ).fetchone()[0],
            )

        self.assertEqual(summary.files_imported, 1)
        self.assertEqual(resumed_counts, (1, 1, 1, 1))
        self.assertEqual(
            captured_at_values,
            (FIXED_NOW.isoformat(), FIXED_NOW.isoformat()),
        )

    def test_json_symlink_escaping_source_directory_is_rejected(self):
        outside = self.root / "outside.json"
        outside.write_text("[]", encoding="utf-8")
        (self.source / "escape.json").symlink_to(outside)

        with self.assertRaisesRegex(ValueError, "source_dir"):
            self.import_seed()


if __name__ == "__main__":
    unittest.main()
