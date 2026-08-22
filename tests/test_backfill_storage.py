from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import get_type_hints
import unittest

from reddit_voc import backfill_models, backfill_storage
from reddit_voc.backfill_models import (
    AnalysisRow,
    BackfillCheckpoint,
    BackfillManifest,
    InsertCounts,
    LaneResult,
    LaneType,
    ProviderAttempt,
    RawArtifactMetadata,
    required_lanes_sha256,
    required_lanes_snapshot,
)
from reddit_voc.backfill_storage import BackfillStore
from reddit_voc.models import RawCapture, RedditComment, RedditThread


NOW = datetime(2026, 7, 11, 4, 17, 9, tzinfo=timezone.utc)


def make_manifest(*, max_provider_requests: int) -> BackfillManifest:
    return BackfillManifest(
        run_id="backfill_test",
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


def make_checkpoint(*, cursor: str | None, page_number: int) -> BackfillCheckpoint:
    return BackfillCheckpoint(
        run_id="backfill_test",
        lane_type="dynamic_search",
        lane_key="Momcozy",
        cursor=cursor,
        previous_cursor=None,
        page_number=page_number,
        newest_seen_utc=None,
        oldest_seen_utc=None,
        discovered_count=0,
        unique_count=0,
        provider_request_count=0,
        last_success_utc=None,
        last_error=None,
        status="running",
        stop_reason=None,
        cursor_json_path=None,
        cursor_schema_sha256=None,
        consecutive_old_pages=0,
    )


def make_raw_artifact(**overrides) -> RawArtifactMetadata:
    values = {
        "artifact_id": "raw-artifact-1",
        "run_id": "backfill_test",
        "artifact_kind": "seed",
        "lane_type": "seed",
        "lane_key_hash": "1" * 64,
        "identity_hash": "2" * 64,
        "raw_capture_id": "raw-backfill-1",
        "parser_kind": "seed_browser_thread",
        "source_method": "historical_seed",
        "source_url": "seed://fixture.json",
        "source_endpoint": "seed_file",
        "payload_sha256": "3" * 64,
        "relative_path": "backfill_test/seed/1111/page.json.gz",
        "captured_at_utc": NOW.isoformat(),
        "page_number": 0,
        "request_cursor": None,
        "response_cursor": None,
    }
    values.update(overrides)
    return RawArtifactMetadata(**values)


def make_entity_bundle(
    *,
    run_id: str = "backfill_test",
    post_id: str = "post1",
    comment_id: str = "comment1",
    raw_prefix: str = "raw",
) -> tuple[
    tuple[RawCapture, ...],
    tuple[RedditThread, ...],
    tuple[RedditComment, ...],
    tuple[AnalysisRow, ...],
]:
    post_capture = RawCapture(
        raw_capture_id=f"{raw_prefix}-post",
        run_id=run_id,
        source_method="seed",
        source_url=f"https://reddit.example/{post_id}",
        captured_at_utc=NOW,
        auth_boundary="public",
        raw_payload_hash="3" * 64,
        payload_format="json",
        http_status=200,
    )
    comments_capture = RawCapture(
        raw_capture_id=f"{raw_prefix}-comments",
        run_id=run_id,
        source_method="provider",
        source_url=f"https://api.example.invalid/comments/{post_id}",
        captured_at_utc=NOW + timedelta(seconds=1),
        auth_boundary="provider_gate",
        raw_payload_hash="4" * 64,
        payload_format="json",
        http_status=200,
    )
    thread = RedditThread(
        post_id=post_id,
        run_id=run_id,
        raw_capture_id=post_capture.raw_capture_id,
        subreddit="ExclusivelyPumping",
        title="Momcozy wearable pump",
        selftext="The pump leaks during longer sessions.",
        source_url=post_capture.source_url,
        created_at_utc=NOW - timedelta(days=1),
        score=12,
        num_comments_reported=1,
        parsed_comment_count=1,
        more_node_count=0,
        coverage_grade="full",
        matched_keywords=["Momcozy", "wearable pump"],
        media_urls=["https://images.example.invalid/pump.jpg"],
        author_hash="author-post",
    )
    comment = RedditComment(
        comment_id=comment_id,
        post_id=post_id,
        run_id=run_id,
        raw_capture_id=comments_capture.raw_capture_id,
        parent_id=f"t3_{post_id}",
        body="Mine leaked and support was slow.",
        created_at_utc=NOW - timedelta(hours=12),
        score=3,
        depth=0,
        is_submitter=False,
        matched_keywords=["Momcozy"],
        author_hash="author-comment",
        deleted_or_removed=False,
    )
    analyses = (
        AnalysisRow(
            analysis_id=f"analysis-{post_id}",
            run_id=run_id,
            source_type="post",
            source_id=post_id,
            analysis_version="local_rules_v1",
            sentiment_label="negative",
            sentiment_score=-0.7,
            topic="product_experience",
            severity="high",
            confidence=0.9,
            pain_points=("leak", "slow service"),
        ),
        AnalysisRow(
            analysis_id=f"analysis-{comment_id}",
            run_id=run_id,
            source_type="comment",
            source_id=comment_id,
            analysis_version="local_rules_v1",
            sentiment_label="negative",
            sentiment_score=-0.6,
            topic="customer_service",
            severity="medium",
            confidence=0.8,
            pain_points=("slow service",),
        ),
    )
    return (post_capture, comments_capture), (thread,), (comment,), analyses


class BackfillModelTests(unittest.TestCase):
    def test_required_lanes_snapshot_is_ordered_canonical_and_fail_closed(self):
        arguments = {
            "search_terms": ("Momcozy", '"wearable pump"'),
            "subreddits": ("ExclusivelyPumping", "beyondthebump"),
            "include_subreddit_sweep": True,
        }
        snapshot = required_lanes_snapshot(**arguments)
        self.assertEqual(
            snapshot,
            (
                ("dynamic_search", "Momcozy"),
                ("dynamic_search", '"wearable pump"'),
                ("subreddit_feed", "ExclusivelyPumping"),
                ("subreddit_feed", "beyondthebump"),
            ),
        )
        expected_bytes = (
            '[["dynamic_search","Momcozy"],["dynamic_search","\\"wearable pump\\""],'
            '["subreddit_feed","ExclusivelyPumping"],'
            '["subreddit_feed","beyondthebump"]]'
        ).encode("utf-8")
        self.assertEqual(required_lanes_sha256(**arguments), sha256(expected_bytes).hexdigest())

        invalid_cases = (
            {**arguments, "search_terms": ()},
            {**arguments, "search_terms": ("Momcozy", "")},
            {**arguments, "search_terms": ("Momcozy", 1)},
            {**arguments, "search_terms": ("Momcozy", "Momcozy")},
            {**arguments, "subreddits": ()},
            {**arguments, "subreddits": ("ExclusivelyPumping", "")},
            {**arguments, "subreddits": ("ExclusivelyPumping", 1)},
            {**arguments, "subreddits": ("same", "same")},
            {
                **arguments,
                "subreddits": (),
                "include_subreddit_sweep": False,
            },
            {**arguments, "include_subreddit_sweep": 1},
        )
        for invalid in invalid_cases:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    required_lanes_snapshot(**invalid)

    def test_records_are_frozen_and_have_exact_persisted_fields(self):
        expected_fields = {
            BackfillManifest: (
                "run_id",
                "status",
                "window_start_utc",
                "requested_end_utc",
                "effective_end_utc",
                "search_terms",
                "subreddits",
                "include_subreddit_sweep",
                "required_lanes_sha256",
                "keyword_config_sha256",
                "max_provider_requests",
                "provider_request_count",
                "provider_call",
                "live_send",
                "created_at_utc",
                "updated_at_utc",
            ),
            BackfillCheckpoint: (
                "run_id",
                "lane_type",
                "lane_key",
                "cursor",
                "previous_cursor",
                "page_number",
                "newest_seen_utc",
                "oldest_seen_utc",
                "discovered_count",
                "unique_count",
                "provider_request_count",
                "last_success_utc",
                "last_error",
                "status",
                "stop_reason",
                "cursor_json_path",
                "cursor_schema_sha256",
                "consecutive_old_pages",
            ),
            RawArtifactMetadata: (
                "artifact_id",
                "run_id",
                "artifact_kind",
                "lane_type",
                "lane_key_hash",
                "identity_hash",
                "raw_capture_id",
                "parser_kind",
                "source_method",
                "source_url",
                "source_endpoint",
                "payload_sha256",
                "relative_path",
                "captured_at_utc",
                "page_number",
                "request_cursor",
                "response_cursor",
            ),
            ProviderAttempt: (
                "run_id",
                "request_number",
                "endpoint",
                "status",
                "reserved_at_utc",
                "sent_at_utc",
                "completed_at_utc",
                "http_status",
                "error_class",
            ),
            AnalysisRow: (
                "analysis_id",
                "run_id",
                "source_type",
                "source_id",
                "analysis_version",
                "sentiment_label",
                "sentiment_score",
                "topic",
                "severity",
                "confidence",
                "pain_points",
                "provider_call",
            ),
            InsertCounts: ("raw_captures", "threads", "comments", "analyses"),
        }

        for record_type, names in expected_fields.items():
            with self.subTest(record_type=record_type.__name__):
                self.assertTrue(record_type.__dataclass_params__.frozen)
                self.assertEqual(tuple(field.name for field in fields(record_type)), names)

        manifest = make_manifest(max_provider_requests=1)
        with self.assertRaises(FrozenInstanceError):
            manifest.status = "running"
        self.assertEqual(InsertCounts(), InsertCounts(0, 0, 0, 0))

    def test_manifest_defensively_copies_mutable_sequences(self):
        search_terms = ["Momcozy"]
        subreddits = ["ExclusivelyPumping"]
        manifest = replace(
            make_manifest(max_provider_requests=1),
            search_terms=search_terms,
            subreddits=subreddits,
        )

        self.assertIsInstance(manifest.search_terms, tuple)
        self.assertIsInstance(manifest.subreddits, tuple)
        search_terms[0] = "mutated"
        subreddits.append("new-subreddit")
        self.assertEqual(manifest.search_terms, ("Momcozy",))
        self.assertEqual(manifest.subreddits, ("ExclusivelyPumping",))
        with self.assertRaises(FrozenInstanceError):
            manifest.search_terms += ("other",)

    def test_lane_result_widens_only_lane_type_annotation(self):
        self.assertEqual(get_type_hints(LaneResult)["lane_type"], LaneType)
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

    def test_detail_batch_record_is_frozen_and_exact(self):
        self.assertTrue(hasattr(backfill_models, "DetailBatch"))
        record_type = backfill_models.DetailBatch
        self.assertTrue(record_type.__dataclass_params__.frozen)
        self.assertEqual(
            tuple(field.name for field in fields(record_type)),
            (
                "run_id",
                "batch_id",
                "batch_number",
                "post_ids",
                "status",
                "artifact_id",
                "stop_reason",
                "created_at_utc",
                "updated_at_utc",
            ),
        )


class BackfillStorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.store = BackfillStore(Path(self.temporary_directory.name) / "backfill.sqlite3")
        self.store.migrate()

    def create_manifest(self, *, max_provider_requests: int = 2) -> BackfillManifest:
        manifest = make_manifest(max_provider_requests=max_provider_requests)
        self.store.create_manifest(manifest)
        return manifest

    def add_candidates(self, post_ids: tuple[str, ...]) -> RawArtifactMetadata:
        lane_key = "Momcozy"
        artifact = make_raw_artifact(
            artifact_id="candidate-source-artifact",
            artifact_kind="discovery",
            lane_type="dynamic_search",
            lane_key_hash=sha256(lane_key.encode()).hexdigest(),
            raw_capture_id="candidate-source-capture",
            parser_kind="tikhub_discovery",
            source_method="tikhub_dynamic_search",
            source_url="tikhub://" + "a" * 64,
            source_endpoint="/api/v1/reddit/app/fetch_dynamic_search",
            relative_path="backfill_test/discovery/candidates/page.json.gz",
            request_cursor=None,
            response_cursor="cursor-1",
        )
        self.store.insert_raw_artifact(artifact)
        for ordinal, post_id in enumerate(post_ids):
            self.store.record_discovery_occurrence(
                run_id="backfill_test",
                lane_type="dynamic_search",
                lane_key=lane_key,
                page_number=1,
                ordinal=ordinal,
                post_id=post_id,
                source_url=f"https://www.reddit.com/r/test/comments/{post_id}/title/",
                post_created_at_utc=NOW - timedelta(days=1),
                raw_artifact_id=artifact.artifact_id,
                discovered_at_utc=NOW,
                base_disposition="eligible",
            )
        return artifact

    def prepare_two_standard_runs(self) -> None:
        first_manifest = self.create_manifest()
        self.store.create_manifest(replace(first_manifest, run_id="backfill_second"))
        insert_sql = """
            INSERT INTO raw_captures(
                raw_capture_id, run_id, source_method, source_url, captured_at_utc,
                auth_boundary, raw_payload_hash, payload_format, browser_status,
                http_status, selector_version, blocked_reason, secrets_written
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self.store.connect() as conn:
            conn.execute(
                insert_sql,
                (
                    "raw-one",
                    "backfill_test",
                    "provider",
                    "https://api.example.invalid/run-one",
                    NOW.isoformat(),
                    "provider_gate",
                    "1" * 64,
                    "json",
                    "ok",
                    None,
                    None,
                    None,
                    0,
                ),
            )
            conn.execute(
                insert_sql,
                (
                    "raw-two",
                    "backfill_second",
                    "provider",
                    "https://api.example.invalid/run-two",
                    NOW.isoformat(),
                    "provider_gate",
                    "2" * 64,
                    "json",
                    "ok",
                    None,
                    None,
                    None,
                    0,
                ),
            )

    @staticmethod
    def insert_thread(
        conn: sqlite3.Connection, *, post_id: str, run_id: str, raw_capture_id: str
    ) -> None:
        conn.execute(
            """
            INSERT INTO reddit_threads(
                post_id, run_id, raw_capture_id, subreddit, title, selftext,
                source_url, created_at_utc, score, num_comments_reported,
                parsed_comment_count, more_node_count, coverage_grade,
                matched_keywords, author_hash, media_urls
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                post_id,
                run_id,
                raw_capture_id,
                "ExclusivelyPumping",
                "Momcozy",
                "body",
                f"https://reddit.example/{run_id}/{post_id}",
                NOW.isoformat(),
                None,
                0,
                0,
                0,
                "post_only",
                "Momcozy",
                None,
                "[]",
            ),
        )

    def test_migrate_creates_only_dedicated_staging_tables(self):
        expected_tables = {
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
            "backfill_budget_extensions",
            "backfill_hydration_resumes",
            "backfill_collection_resumes",
            "backfill_checkpoints",
            "backfill_candidates",
            "backfill_discovery_occurrences",
            "backfill_detail_batches",
            "backfill_detail_batch_members",
            "backfill_issues",
            "backfill_merge_conflicts",
        }
        with self.store.connect() as conn:
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            occurrence_sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name='backfill_discovery_occurrences'"
            ).fetchone()["sql"]
            compatible_columns = {
                table: {
                    row["name"]
                    for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
                }
                for table in (
                    "runs",
                    "raw_captures",
                    "reddit_threads",
                    "reddit_comments",
                    "analysis_results",
                    "delivery_previews",
                )
            }

        self.assertEqual(tables, expected_tables)
        self.assertEqual(
            compatible_columns,
            {
                "runs": {
                    "run_id",
                    "status",
                    "window_start_utc",
                    "window_end_utc",
                    "provider_call",
                    "live_send",
                },
                "raw_captures": {
                    "raw_capture_id",
                    "run_id",
                    "source_method",
                    "source_url",
                    "captured_at_utc",
                    "auth_boundary",
                    "raw_payload_hash",
                    "payload_format",
                    "browser_status",
                    "http_status",
                    "selector_version",
                    "blocked_reason",
                    "secrets_written",
                },
                "reddit_threads": {
                    "post_id",
                    "run_id",
                    "raw_capture_id",
                    "subreddit",
                    "title",
                    "selftext",
                    "source_url",
                    "created_at_utc",
                    "score",
                    "num_comments_reported",
                    "parsed_comment_count",
                    "more_node_count",
                    "coverage_grade",
                    "matched_keywords",
                    "author_hash",
                    "media_urls",
                },
                "reddit_comments": {
                    "comment_id",
                    "post_id",
                    "run_id",
                    "raw_capture_id",
                    "parent_id",
                    "body",
                    "created_at_utc",
                    "score",
                    "depth",
                    "is_submitter",
                    "matched_keywords",
                    "author_hash",
                    "deleted_or_removed",
                },
                "analysis_results": {
                    "analysis_id",
                    "run_id",
                    "source_type",
                    "source_id",
                    "analysis_version",
                    "sentiment_label",
                    "sentiment_score",
                    "topic",
                    "severity",
                    "confidence",
                    "pain_points",
                    "provider_call",
                },
                "delivery_previews": {
                    "delivery_id",
                    "run_id",
                    "channel",
                    "mode",
                    "status",
                    "message_hash",
                    "artifact_paths",
                    "live_send",
                },
            },
        )
        for disposition in (
            "new_candidate",
            "duplicate_occurrence",
            "outside_window",
            "duplicate_existing_structured",
            "invalid",
        ):
            self.assertIn(disposition, occurrence_sql)

    def test_standard_entity_ids_are_global_primary_keys_with_run_indexes(self):
        expected_primary_keys = {
            "raw_captures": "raw_capture_id",
            "reddit_threads": "post_id",
            "reddit_comments": "comment_id",
            "analysis_results": "analysis_id",
            "delivery_previews": "delivery_id",
        }
        primary_keys: dict[str, tuple[str, ...]] = {}
        unique_indexes: dict[str, set[tuple[str, ...]]] = {}
        with self.store.connect() as conn:
            for table in expected_primary_keys:
                table_info = conn.execute(f"PRAGMA table_info({table})").fetchall()
                primary_keys[table] = tuple(
                    row["name"]
                    for row in sorted(table_info, key=lambda row: row["pk"])
                    if row["pk"]
                )
                unique_indexes[table] = {
                    tuple(
                        column["name"]
                        for column in conn.execute(
                            f"PRAGMA index_info('{index['name']}')"
                        ).fetchall()
                    )
                    for index in conn.execute(
                        f"PRAGMA index_list({table})"
                    ).fetchall()
                    if index["unique"]
                }

        self.assertEqual(
            primary_keys,
            {table: (column,) for table, column in expected_primary_keys.items()},
        )
        self.assertIn(
            ("run_id", "source_method", "source_url", "raw_payload_hash"),
            unique_indexes["raw_captures"],
        )
        self.assertIn(
            ("run_id", "raw_capture_id"), unique_indexes["raw_captures"]
        )
        self.assertIn(("run_id", "post_id"), unique_indexes["reddit_threads"])

    def test_post_id_cannot_repeat_across_runs(self):
        self.prepare_two_standard_runs()
        with self.store.connect() as conn:
            self.insert_thread(
                conn,
                post_id="shared-post",
                run_id="backfill_test",
                raw_capture_id="raw-one",
            )
            with self.assertRaises(sqlite3.IntegrityError):
                self.insert_thread(
                    conn,
                    post_id="shared-post",
                    run_id="backfill_second",
                    raw_capture_id="raw-two",
                )

    def test_comment_id_cannot_repeat_across_runs(self):
        self.prepare_two_standard_runs()
        with self.store.connect() as conn:
            self.insert_thread(
                conn,
                post_id="post-one",
                run_id="backfill_test",
                raw_capture_id="raw-one",
            )
            self.insert_thread(
                conn,
                post_id="post-two",
                run_id="backfill_second",
                raw_capture_id="raw-two",
            )
            insert_sql = """
                INSERT INTO reddit_comments(
                    comment_id, post_id, run_id, raw_capture_id, parent_id,
                    body, created_at_utc, score, depth, is_submitter,
                    matched_keywords, author_hash, deleted_or_removed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            conn.execute(
                insert_sql,
                (
                    "shared-comment",
                    "post-one",
                    "backfill_test",
                    "raw-one",
                    None,
                    "body",
                    NOW.isoformat(),
                    None,
                    0,
                    0,
                    "Momcozy",
                    None,
                    0,
                ),
            )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    insert_sql,
                    (
                        "shared-comment",
                        "post-two",
                        "backfill_second",
                        "raw-two",
                        None,
                        "body",
                        NOW.isoformat(),
                        None,
                        0,
                        0,
                        "Momcozy",
                        None,
                        0,
                    ),
                )

    def test_analysis_id_cannot_repeat_across_runs(self):
        self.prepare_two_standard_runs()
        insert_sql = """
            INSERT INTO analysis_results(
                analysis_id, run_id, source_type, source_id, analysis_version,
                sentiment_label, sentiment_score, topic, severity, confidence,
                pain_points, provider_call
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self.store.connect() as conn:
            conn.execute(
                insert_sql,
                (
                    "shared-analysis",
                    "backfill_test",
                    "post",
                    "post-one",
                    "local-rules-v1",
                    "neutral",
                    0.0,
                    "product_evaluation",
                    "low",
                    0.6,
                    "[]",
                    0,
                ),
            )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    insert_sql,
                    (
                        "shared-analysis",
                        "backfill_second",
                        "post",
                        "post-two",
                        "local-rules-v1",
                        "neutral",
                        0.0,
                        "product_evaluation",
                        "low",
                        0.6,
                        "[]",
                        0,
                    ),
                )

    def test_manifest_live_send_check_rejects_true(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.create_manifest(
                replace(make_manifest(max_provider_requests=1), live_send=True)
            )

    def test_manifest_provider_call_requires_sent_attempt_evidence(self):
        with self.assertRaisesRegex(
            ValueError, "provider_call requires a sent provider attempt"
        ):
            self.store.create_manifest(
                replace(make_manifest(max_provider_requests=1), provider_call=True)
            )

    def test_create_manifest_atomically_creates_compatible_run(self):
        manifest = self.create_manifest(max_provider_requests=1)

        with self.store.connect() as conn:
            run = conn.execute(
                "SELECT * FROM runs WHERE run_id = ?", (manifest.run_id,)
            ).fetchone()

        self.assertEqual(
            dict(run),
            {
                "run_id": manifest.run_id,
                "status": manifest.status,
                "window_start_utc": manifest.window_start_utc,
                "window_end_utc": manifest.effective_end_utc,
                "provider_call": 0,
                "live_send": 0,
            },
        )

    def test_create_manifest_rolls_back_metadata_when_compatible_run_conflicts(self):
        manifest = make_manifest(max_provider_requests=1)
        with self.store.connect() as conn:
            conn.execute(
                "INSERT INTO runs(run_id, status, window_start_utc, window_end_utc, "
                "provider_call, live_send) VALUES (?, ?, ?, ?, 0, 0)",
                (
                    manifest.run_id,
                    manifest.status,
                    manifest.window_start_utc,
                    manifest.effective_end_utc,
                ),
            )

        with self.assertRaises(sqlite3.IntegrityError):
            self.store.create_manifest(manifest)

        with self.store.connect() as conn:
            metadata_count = conn.execute(
                "SELECT COUNT(*) AS count FROM backfill_manifests WHERE run_id = ?",
                (manifest.run_id,),
            ).fetchone()["count"]
        self.assertEqual(metadata_count, 0)

    def test_request_budget_counts_each_reservation(self):
        self.create_manifest(max_provider_requests=2)
        self.assertEqual(
            self.store.reserve_provider_request("backfill_test", "/search", NOW), 1
        )
        self.assertEqual(
            self.store.reserve_provider_request("backfill_test", "/search", NOW), 2
        )
        self.assertIsNone(
            self.store.reserve_provider_request("backfill_test", "/search", NOW)
        )
        self.assertEqual(self.store.provider_request_count("backfill_test"), 2)
        with self.store.connect() as conn:
            attempt_count = conn.execute(
                "SELECT COUNT(*) AS count FROM backfill_provider_attempts "
                "WHERE run_id='backfill_test'"
            ).fetchone()["count"]
        self.assertEqual(attempt_count, 2)

    def test_unsafe_endpoints_are_rejected_without_consuming_budget(self):
        unsafe_endpoints = (
            "",
            " ",
            "/",
            "search",
            "https://api.example.invalid/search",
            "//api.example.invalid/search",
            "/search?q=Momcozy",
            "/search#fragment",
            "/search path",
            "/search\tvalue",
            "Authorization: Bearer token",
            "/search\r\nAuthorization:Bearer",
            "/search\x00value",
        )

        for index, endpoint in enumerate(unsafe_endpoints):
            run_id = f"unsafe-endpoint-{index}"
            self.store.create_manifest(
                replace(make_manifest(max_provider_requests=1), run_id=run_id)
            )
            with self.subTest(endpoint=repr(endpoint)):
                with self.assertRaisesRegex(ValueError, "invalid provider endpoint"):
                    self.store.reserve_provider_request(run_id, endpoint, NOW)
                self.assertEqual(self.store.provider_request_count(run_id), 0)
                with self.store.connect() as conn:
                    attempt_count = conn.execute(
                        "SELECT COUNT(*) AS count FROM backfill_provider_attempts "
                        "WHERE run_id = ?",
                        (run_id,),
                    ).fetchone()["count"]
                self.assertEqual(attempt_count, 0)

    def test_request_reservation_is_atomic_across_connections(self):
        self.create_manifest(max_provider_requests=3)

        def reserve(offset: int) -> int | None:
            return self.store.reserve_provider_request(
                "backfill_test", "/search", NOW + timedelta(microseconds=offset)
            )

        with ThreadPoolExecutor(max_workers=8) as executor:
            reservations = list(executor.map(reserve, range(8)))

        self.assertEqual(sorted(result for result in reservations if result is not None), [1, 2, 3])
        self.assertEqual(self.store.provider_request_count("backfill_test"), 3)
        with self.store.connect() as conn:
            request_numbers = [
                row["request_number"]
                for row in conn.execute(
                    "SELECT request_number FROM backfill_provider_attempts "
                    "WHERE run_id='backfill_test' ORDER BY request_number"
                ).fetchall()
            ]
        self.assertEqual(request_numbers, [1, 2, 3])

    def test_unknown_manifest_cannot_reserve_or_report_budget(self):
        with self.assertRaisesRegex(KeyError, "unknown backfill run: missing"):
            self.store.reserve_provider_request("missing", "/search", NOW)
        with self.assertRaisesRegex(KeyError, "unknown backfill run: missing"):
            self.store.provider_request_count("missing")

    def test_checkpoint_round_trip_preserves_next_cursor(self):
        self.create_manifest()
        checkpoint = make_checkpoint(cursor="cursor-2", page_number=1)
        self.store.save_checkpoint(checkpoint)
        self.assertEqual(
            self.store.load_checkpoint(
                run_id="backfill_test", lane_type="dynamic_search", lane_key="Momcozy"
            ),
            checkpoint,
        )

    def test_checkpoint_save_replaces_same_lane_and_missing_returns_none(self):
        self.create_manifest()
        first = make_checkpoint(cursor="cursor-1", page_number=1)
        second = replace(
            first,
            cursor="cursor-2",
            previous_cursor="cursor-1",
            page_number=2,
            discovered_count=25,
            unique_count=20,
            consecutive_old_pages=1,
        )
        self.store.save_checkpoint(first)
        self.store.save_checkpoint(second)

        self.assertEqual(
            self.store.load_checkpoint(
                run_id="backfill_test", lane_type="dynamic_search", lane_key="Momcozy"
            ),
            second,
        )
        self.assertIsNone(
            self.store.load_checkpoint(
                run_id="backfill_test", lane_type="comments", lane_key="missing"
            )
        )

    def test_discovery_occurrences_are_atomic_append_safe_and_close_the_equation(self):
        self.create_manifest()
        artifact = make_raw_artifact(
            artifact_id="discovery-artifact",
            artifact_kind="discovery",
            lane_type="dynamic_search",
            lane_key_hash="a" * 64,
            raw_capture_id="discovery-capture",
            parser_kind="tikhub_discovery",
            source_method="tikhub_dynamic_search",
            source_url="tikhub://" + "b" * 64,
            source_endpoint="/api/v1/reddit/app/fetch_dynamic_search",
            relative_path="backfill_test/discovery/aaaa/page.json.gz",
            request_cursor=None,
            response_cursor="cursor-1",
        )
        self.store.insert_raw_artifact(artifact)

        first = self.store.record_discovery_occurrence(
            run_id="backfill_test",
            lane_type="dynamic_search",
            lane_key="Momcozy",
            page_number=1,
            ordinal=0,
            post_id="new-post",
            source_url="https://www.reddit.com/r/test/comments/new-post/title/",
            post_created_at_utc=NOW - timedelta(days=1),
            raw_artifact_id=artifact.artifact_id,
            discovered_at_utc=NOW,
            base_disposition="eligible",
        )
        replay = self.store.record_discovery_occurrence(
            run_id="backfill_test",
            lane_type="dynamic_search",
            lane_key="Momcozy",
            page_number=1,
            ordinal=0,
            post_id="new-post",
            source_url="https://www.reddit.com/r/test/comments/new-post/title/",
            post_created_at_utc=NOW - timedelta(days=1),
            raw_artifact_id=artifact.artifact_id,
            discovered_at_utc=NOW,
            base_disposition="eligible",
        )
        duplicate = self.store.record_discovery_occurrence(
            run_id="backfill_test",
            lane_type="dynamic_search",
            lane_key="Momcozy",
            page_number=1,
            ordinal=1,
            post_id="new-post",
            source_url="https://www.reddit.com/r/test/comments/new-post/title/",
            post_created_at_utc=NOW - timedelta(days=1),
            raw_artifact_id=artifact.artifact_id,
            discovered_at_utc=NOW,
            base_disposition="eligible",
        )
        outside = self.store.record_discovery_occurrence(
            run_id="backfill_test",
            lane_type="dynamic_search",
            lane_key="Momcozy",
            page_number=1,
            ordinal=2,
            post_id="old-post",
            source_url="https://www.reddit.com/r/test/comments/old-post/title/",
            post_created_at_utc=NOW - timedelta(days=900),
            raw_artifact_id=artifact.artifact_id,
            discovered_at_utc=NOW,
            base_disposition="outside_window",
        )
        invalid = self.store.record_discovery_occurrence(
            run_id="backfill_test",
            lane_type="dynamic_search",
            lane_key="Momcozy",
            page_number=1,
            ordinal=3,
            post_id="invalid-post",
            source_url="https://www.reddit.com/r/test/comments/invalid-post/title/",
            post_created_at_utc=None,
            raw_artifact_id=artifact.artifact_id,
            discovered_at_utc=NOW,
            base_disposition="invalid",
        )

        self.assertEqual(first, "new_candidate")
        self.assertEqual(replay, "new_candidate")
        self.assertEqual(duplicate, "duplicate_occurrence")
        self.assertEqual(outside, "outside_window")
        self.assertEqual(invalid, "invalid")
        self.assertEqual(
            self.store.discovery_occurrence_counts(
                "backfill_test", "dynamic_search", "Momcozy"
            ),
            {
                "new_candidate": 1,
                "duplicate_occurrence": 1,
                "outside_window": 1,
                "invalid": 1,
            },
        )
        self.assertEqual(self.store.candidate_count("backfill_test"), 1)
        with self.store.connect() as conn:
            candidate = conn.execute(
                "SELECT * FROM backfill_candidates WHERE run_id = ? AND post_id = ?",
                ("backfill_test", "new-post"),
            ).fetchone()
            occurrence_count = conn.execute(
                "SELECT COUNT(*) FROM backfill_discovery_occurrences"
            ).fetchone()[0]
        self.assertEqual(candidate["first_lane_type"], "dynamic_search")
        self.assertEqual(candidate["first_lane_key"], "Momcozy")
        self.assertEqual(candidate["raw_artifact_id"], artifact.artifact_id)
        self.assertEqual(candidate["post_created_at_utc"], (NOW - timedelta(days=1)).isoformat())
        self.assertEqual(candidate["status"], "pending")
        self.assertIsNone(candidate["status_reason"])
        self.assertEqual(occurrence_count, 4)

        with self.assertRaises(backfill_storage.BackfillConflictError):
            self.store.record_discovery_occurrence(
                run_id="backfill_test",
                lane_type="dynamic_search",
                lane_key="Momcozy",
                page_number=1,
                ordinal=0,
                post_id="new-post",
                source_url="https://www.reddit.com/r/test/comments/new-post/changed/",
                post_created_at_utc=NOW - timedelta(days=1),
                raw_artifact_id=artifact.artifact_id,
                discovered_at_utc=NOW,
                base_disposition="eligible",
            )
        self.assertEqual(self.store.candidate_count("backfill_test"), 1)

    def test_discovery_checks_global_structured_ids_and_archived_request_cursors(self):
        self.create_manifest()
        captures, threads, _, _ = make_entity_bundle(post_id="already-structured")
        self.store.insert_entity_bundle(
            captures=(captures[0],), threads=threads, comments=(), analyses=()
        )
        artifact = make_raw_artifact(
            artifact_id="cursor-artifact",
            artifact_kind="discovery",
            lane_type="dynamic_search",
            lane_key_hash="c" * 64,
            raw_capture_id="cursor-capture",
            parser_kind="tikhub_discovery",
            source_method="tikhub_dynamic_search",
            source_url="tikhub://" + "d" * 64,
            source_endpoint="/api/v1/reddit/app/fetch_dynamic_search",
            relative_path="backfill_test/discovery/cccc/page.json.gz",
            request_cursor="cursor-seen",
            response_cursor="cursor-next",
        )
        self.store.insert_raw_artifact(artifact)

        disposition = self.store.record_discovery_occurrence(
            run_id="backfill_test",
            lane_type="dynamic_search",
            lane_key="Momcozy",
            page_number=2,
            ordinal=0,
            post_id="already-structured",
            source_url="https://www.reddit.com/r/test/comments/already-structured/title/",
            post_created_at_utc=NOW - timedelta(days=1),
            raw_artifact_id=artifact.artifact_id,
            discovered_at_utc=NOW,
            base_disposition="eligible",
        )

        self.assertEqual(disposition, "duplicate_existing_structured")
        self.assertEqual(self.store.candidate_count("backfill_test"), 0)
        self.assertTrue(
            self.store.request_cursor_seen(
                "backfill_test", "dynamic_search", "c" * 64, "cursor-seen"
            )
        )
        self.assertFalse(
            self.store.request_cursor_seen(
                "backfill_test", "dynamic_search", "c" * 64, "missing"
            )
        )

    def test_reserved_attempt_consumes_budget_without_provider_call(self):
        self.create_manifest(max_provider_requests=1)
        self.store.reserve_provider_request("backfill_test", "/search", NOW)

        with self.store.connect() as conn:
            manifest = conn.execute(
                "SELECT provider_request_count, provider_call FROM backfill_manifests "
                "WHERE run_id='backfill_test'"
            ).fetchone()
            run = conn.execute(
                "SELECT provider_call FROM runs WHERE run_id='backfill_test'"
            ).fetchone()
            attempt = conn.execute(
                "SELECT * FROM backfill_provider_attempts WHERE run_id='backfill_test'"
            ).fetchone()

        self.assertEqual(manifest["provider_request_count"], 1)
        self.assertEqual(manifest["provider_call"], 0)
        self.assertEqual(run["provider_call"], 0)
        self.assertEqual(attempt["status"], "reserved")
        self.assertIsNone(attempt["sent_at_utc"])

    def test_sent_and_completed_attempt_transitions_preserve_evidence(self):
        self.create_manifest(max_provider_requests=1)
        request_number = self.store.reserve_provider_request(
            "backfill_test", "/search", NOW
        )
        sent_at = NOW + timedelta(seconds=1)
        completed_at = NOW + timedelta(seconds=2)

        self.store.mark_provider_attempt_sent(
            "backfill_test", request_number, sent_at
        )
        self.store.complete_provider_attempt(
            "backfill_test",
            request_number,
            status="succeeded",
            completed_at_utc=completed_at,
            http_status=200,
        )

        with self.store.connect() as conn:
            manifest = conn.execute(
                "SELECT provider_call FROM backfill_manifests WHERE run_id='backfill_test'"
            ).fetchone()
            run = conn.execute(
                "SELECT provider_call FROM runs WHERE run_id='backfill_test'"
            ).fetchone()
            attempt = conn.execute(
                "SELECT * FROM backfill_provider_attempts WHERE run_id='backfill_test'"
            ).fetchone()
            derived_provider_call = conn.execute(
                "SELECT EXISTS(SELECT 1 FROM backfill_provider_attempts "
                "WHERE run_id='backfill_test' AND sent_at_utc IS NOT NULL) AS value"
            ).fetchone()["value"]

        self.assertEqual(manifest["provider_call"], 1)
        self.assertEqual(run["provider_call"], 1)
        self.assertEqual(derived_provider_call, 1)
        self.assertEqual(attempt["status"], "succeeded")
        self.assertEqual(attempt["sent_at_utc"], sent_at.isoformat())
        self.assertEqual(attempt["completed_at_utc"], completed_at.isoformat())
        self.assertEqual(attempt["http_status"], 200)
        self.assertIsNone(attempt["error_class"])

    def test_failed_attempt_stores_only_sanitized_error_class(self):
        self.create_manifest(max_provider_requests=1)
        request_number = self.store.reserve_provider_request(
            "backfill_test", "/search", NOW
        )
        self.store.mark_provider_attempt_sent(
            "backfill_test", request_number, NOW + timedelta(seconds=1)
        )
        self.store.complete_provider_attempt(
            "backfill_test",
            request_number,
            status="failed",
            completed_at_utc=NOW + timedelta(seconds=2),
            http_status=503,
            error_class="TimeoutError",
        )

        with self.store.connect() as conn:
            attempt = conn.execute(
                "SELECT status, http_status, error_class FROM backfill_provider_attempts "
                "WHERE run_id='backfill_test' AND request_number=1"
            ).fetchone()

        self.assertEqual(dict(attempt), {
            "status": "failed",
            "http_status": 503,
            "error_class": "TimeoutError",
        })

    def test_provider_attempt_transitions_reject_missing_out_of_order_and_unsafe_error(self):
        self.create_manifest(max_provider_requests=2)
        first = self.store.reserve_provider_request("backfill_test", "/search", NOW)
        with self.assertRaises(ValueError):
            self.store.complete_provider_attempt(
                "backfill_test",
                first,
                status="succeeded",
                completed_at_utc=NOW,
            )
        with self.assertRaises(ValueError):
            self.store.mark_provider_attempt_sent("backfill_test", 99, NOW)

        self.store.mark_provider_attempt_sent("backfill_test", first, NOW)
        with self.assertRaises(ValueError):
            self.store.mark_provider_attempt_sent("backfill_test", first, NOW)
        with self.assertRaisesRegex(ValueError, "invalid error_class"):
            self.store.complete_provider_attempt(
                "backfill_test",
                first,
                status="failed",
                completed_at_utc=NOW,
                error_class="TimeoutError: https://secret.example/?token=secret",
            )

        with self.store.connect() as conn:
            attempt = conn.execute(
                "SELECT status, completed_at_utc, error_class "
                "FROM backfill_provider_attempts "
                "WHERE run_id='backfill_test' AND request_number=1"
            ).fetchone()
        self.assertEqual(attempt["status"], "sent")
        self.assertIsNone(attempt["completed_at_utc"])
        self.assertIsNone(attempt["error_class"])

    def test_entity_bundle_first_insert_persists_every_field_and_counts_multiple_captures(self):
        self.create_manifest()
        captures, threads, comments, analyses = make_entity_bundle()

        counts = self.store.insert_entity_bundle(
            captures=captures,
            threads=threads,
            comments=comments,
            analyses=analyses,
        )

        self.assertEqual(counts, InsertCounts(2, 1, 1, 2))
        with self.store.connect() as conn:
            capture_row = conn.execute(
                "SELECT * FROM raw_captures WHERE raw_capture_id = ?",
                (captures[0].raw_capture_id,),
            ).fetchone()
            thread_row = conn.execute(
                "SELECT * FROM reddit_threads WHERE post_id = ?",
                (threads[0].post_id,),
            ).fetchone()
            comment_row = conn.execute(
                "SELECT * FROM reddit_comments WHERE comment_id = ?",
                (comments[0].comment_id,),
            ).fetchone()
            analysis_row = conn.execute(
                "SELECT * FROM analysis_results WHERE analysis_id = ?",
                (analyses[0].analysis_id,),
            ).fetchone()

        self.assertEqual(
            dict(capture_row),
            {**captures[0].as_record(), "secrets_written": 0},
        )
        self.assertEqual(dict(thread_row), threads[0].as_record())
        self.assertEqual(
            dict(comment_row),
            {
                **comments[0].as_record(),
                "is_submitter": 0,
                "deleted_or_removed": 0,
            },
        )
        self.assertEqual(
            dict(analysis_row),
            {
                "analysis_id": analyses[0].analysis_id,
                "run_id": analyses[0].run_id,
                "source_type": analyses[0].source_type,
                "source_id": analyses[0].source_id,
                "analysis_version": analyses[0].analysis_version,
                "sentiment_label": analyses[0].sentiment_label,
                "sentiment_score": analyses[0].sentiment_score,
                "topic": analyses[0].topic,
                "severity": analyses[0].severity,
                "confidence": analyses[0].confidence,
                "pain_points": '["leak","slow service"]',
                "provider_call": 0,
            },
        )

    def test_entity_bundle_exact_replay_is_a_no_op(self):
        self.create_manifest()
        captures, threads, comments, analyses = make_entity_bundle()
        first_counts = self.store.insert_entity_bundle(
            captures=captures,
            threads=threads,
            comments=comments,
            analyses=analyses,
        )

        replay_counts = self.store.insert_entity_bundle(
            captures=captures,
            threads=threads,
            comments=comments,
            analyses=analyses,
        )

        self.assertEqual(first_counts, InsertCounts(2, 1, 1, 2))
        self.assertEqual(replay_counts, InsertCounts())
        with self.store.connect() as conn:
            counts = tuple(
                conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "raw_captures",
                    "reddit_threads",
                    "reddit_comments",
                    "analysis_results",
                )
            )
        self.assertEqual(counts, (2, 1, 1, 2))

    def test_entity_bundle_preserves_same_raw_source_and_payload_across_runs(self):
        first_manifest = self.create_manifest()
        self.store.create_manifest(replace(first_manifest, run_id="backfill_second"))
        captures, _, _, _ = make_entity_bundle()
        first_capture = captures[0]
        second_capture = replace(
            first_capture,
            raw_capture_id="raw-second-run",
            run_id="backfill_second",
        )

        first_counts = self.store.insert_entity_bundle(
            captures=[first_capture], threads=[], comments=[], analyses=[]
        )
        second_counts = self.store.insert_entity_bundle(
            captures=[second_capture], threads=[], comments=[], analyses=[]
        )
        replay_counts = self.store.insert_entity_bundle(
            captures=[first_capture], threads=[], comments=[], analyses=[]
        )

        self.assertEqual(first_counts, InsertCounts(raw_captures=1))
        self.assertEqual(second_counts, InsertCounts(raw_captures=1))
        self.assertEqual(replay_counts, InsertCounts())
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT run_id, raw_capture_id FROM raw_captures ORDER BY run_id"
            ).fetchall()
        self.assertEqual(
            [(row["run_id"], row["raw_capture_id"]) for row in rows],
            [
                ("backfill_second", "raw-second-run"),
                ("backfill_test", first_capture.raw_capture_id),
            ],
        )

    def test_entity_bundle_rejects_same_run_raw_natural_key_collision_and_rolls_back(self):
        self.create_manifest()
        captures, threads, _, _ = make_entity_bundle()
        persisted_capture = captures[0]
        new_capture = captures[1]
        conflicting_capture = replace(
            persisted_capture,
            raw_capture_id="raw-natural-key-conflict",
        )
        new_thread = replace(
            threads[0],
            post_id="post-new",
            raw_capture_id=new_capture.raw_capture_id,
            source_url=new_capture.source_url,
        )
        self.store.insert_entity_bundle(
            captures=[persisted_capture], threads=[], comments=[], analyses=[]
        )

        with self.assertRaisesRegex(
            backfill_storage.BackfillConflictError,
            "raw_captures:raw-natural-key-conflict",
        ):
            self.store.insert_entity_bundle(
                captures=[new_capture, conflicting_capture],
                threads=[new_thread],
                comments=[],
                analyses=[],
            )

        with self.store.connect() as conn:
            raw_ids = [
                row["raw_capture_id"]
                for row in conn.execute(
                    "SELECT raw_capture_id FROM raw_captures ORDER BY raw_capture_id"
                ).fetchall()
            ]
            thread_count = conn.execute(
                "SELECT COUNT(*) FROM reddit_threads"
            ).fetchone()[0]
        self.assertEqual(raw_ids, [persisted_capture.raw_capture_id])
        self.assertEqual(thread_count, 0)

    def test_entity_bundle_rejects_cross_run_thread_lineage_and_rolls_back_raw(self):
        first_manifest = self.create_manifest()
        self.store.create_manifest(replace(first_manifest, run_id="other_run"))
        captures, threads, comments, analyses = make_entity_bundle()
        self.store.insert_entity_bundle(
            captures=captures,
            threads=threads,
            comments=comments,
            analyses=analyses,
        )
        other_capture = replace(
            captures[0], raw_capture_id="raw-other", run_id="other_run"
        )
        conflicting_thread = replace(
            threads[0], run_id="other_run", raw_capture_id=other_capture.raw_capture_id
        )

        with self.assertRaisesRegex(
            backfill_storage.BackfillConflictError, "reddit_threads:post1"
        ):
            self.store.insert_entity_bundle(
                captures=[other_capture],
                threads=[conflicting_thread],
                comments=[],
                analyses=[],
            )

        with self.store.connect() as conn:
            other_raw_count = conn.execute(
                "SELECT COUNT(*) FROM raw_captures WHERE run_id = 'other_run'"
            ).fetchone()[0]
            persisted_thread = conn.execute(
                "SELECT run_id, raw_capture_id FROM reddit_threads WHERE post_id = 'post1'"
            ).fetchone()
        self.assertEqual(other_raw_count, 0)
        self.assertEqual(
            tuple(persisted_thread),
            ("backfill_test", captures[0].raw_capture_id),
        )

    def test_entity_bundle_analysis_conflict_rolls_back_all_earlier_tables(self):
        self.create_manifest()
        captures, threads, comments, analyses = make_entity_bundle()
        self.store.insert_entity_bundle(
            captures=captures,
            threads=threads,
            comments=comments,
            analyses=analyses,
        )
        new_captures, new_threads, new_comments, new_analyses = make_entity_bundle(
            post_id="post2", comment_id="comment2", raw_prefix="raw-second"
        )
        conflicting_analysis = replace(
            new_analyses[0],
            analysis_id=analyses[0].analysis_id,
            topic="different_topic",
        )

        with self.assertRaisesRegex(
            backfill_storage.BackfillConflictError,
            "analysis_results:analysis-post1",
        ):
            self.store.insert_entity_bundle(
                captures=new_captures,
                threads=new_threads,
                comments=new_comments,
                analyses=[conflicting_analysis],
            )

        with self.store.connect() as conn:
            counts = tuple(
                conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "raw_captures",
                    "reddit_threads",
                    "reddit_comments",
                    "analysis_results",
                )
            )
            new_rows = tuple(
                conn.execute(query).fetchone()[0]
                for query in (
                    "SELECT COUNT(*) FROM raw_captures WHERE raw_capture_id LIKE 'raw-second%'",
                    "SELECT COUNT(*) FROM reddit_threads WHERE post_id = 'post2'",
                    "SELECT COUNT(*) FROM reddit_comments WHERE comment_id = 'comment2'",
                )
            )
        self.assertEqual(counts, (2, 1, 1, 2))
        self.assertEqual(new_rows, (0, 0, 0))

    def test_two_runs_preserve_same_source_and_payload_as_distinct_raw_captures(self):
        first_manifest = self.create_manifest()
        second_manifest = replace(first_manifest, run_id="backfill_second")
        self.store.create_manifest(second_manifest)

        insert_sql = """
            INSERT INTO raw_captures(
                raw_capture_id, run_id, source_method, source_url, captured_at_utc,
                auth_boundary, raw_payload_hash, payload_format, browser_status,
                http_status, selector_version, blocked_reason, secrets_written
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        source_method = "provider"
        source_url = "https://api.example.invalid/search?q=Momcozy"
        payload_sha256 = "4" * 64
        with self.store.connect() as conn:
            for suffix, run_id in (("one", "backfill_test"), ("two", "backfill_second")):
                conn.execute(
                    insert_sql,
                    (
                        f"raw-{suffix}",
                        run_id,
                        source_method,
                        source_url,
                        NOW.isoformat(),
                        "provider_gate",
                        payload_sha256,
                        "json",
                        "ok",
                        None,
                        None,
                        None,
                        0,
                    ),
                )
            rows = conn.execute(
                "SELECT run_id, raw_capture_id FROM raw_captures ORDER BY run_id"
            ).fetchall()

            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    insert_sql,
                    (
                        "raw-duplicate",
                        "backfill_test",
                        source_method,
                        source_url,
                        NOW.isoformat(),
                        "provider_gate",
                        payload_sha256,
                        "json",
                        "ok",
                        None,
                        None,
                        None,
                        0,
                    ),
                )

        self.assertEqual(
            [(row["run_id"], row["raw_capture_id"]) for row in rows],
            [("backfill_second", "raw-two"), ("backfill_test", "raw-one")],
        )

    def test_raw_artifact_insert_persists_exact_metadata_and_replay_no_ops(self):
        self.create_manifest()
        artifact = make_raw_artifact()

        self.assertTrue(self.store.insert_raw_artifact(artifact))
        self.assertFalse(self.store.insert_raw_artifact(artifact))

        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT * FROM backfill_raw_artifacts WHERE run_id = ? AND artifact_id = ?",
                (artifact.run_id, artifact.artifact_id),
            ).fetchone()
        self.assertEqual(dict(row), artifact.__dict__)

    def test_raw_artifact_insert_rejects_conflicting_metadata_without_mutation(self):
        self.create_manifest()
        artifact = make_raw_artifact()
        self.store.insert_raw_artifact(artifact)

        with self.assertRaisesRegex(
            backfill_storage.BackfillConflictError,
            "backfill_raw_artifacts:raw-artifact-1",
        ):
            self.store.insert_raw_artifact(
                replace(artifact, parser_kind="different_parser")
            )

        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT * FROM backfill_raw_artifacts WHERE run_id = ? AND artifact_id = ?",
                (artifact.run_id, artifact.artifact_id),
            ).fetchone()
        self.assertEqual(dict(row), artifact.__dict__)

    def test_raw_artifact_insert_maps_unique_metadata_collisions_to_conflict(self):
        self.create_manifest()
        artifact = make_raw_artifact()
        self.store.insert_raw_artifact(artifact)
        collisions = (
            replace(
                artifact,
                artifact_id="path-collision",
                raw_capture_id="raw-path-collision",
                source_url="seed://path-collision.json",
            ),
            replace(
                artifact,
                artifact_id="capture-collision",
                relative_path="backfill_test/seed/2222/capture.json.gz",
                source_url="seed://capture-collision.json",
            ),
            replace(
                artifact,
                artifact_id="source-collision",
                raw_capture_id="raw-source-collision",
                relative_path="backfill_test/seed/3333/source.json.gz",
            ),
        )

        for collision in collisions:
            with self.subTest(artifact_id=collision.artifact_id):
                with self.assertRaisesRegex(
                    backfill_storage.BackfillConflictError,
                    f"backfill_raw_artifacts:{collision.artifact_id}",
                ):
                    self.store.insert_raw_artifact(collision)

        with self.store.connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM backfill_raw_artifacts"
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_seed_ledger_exact_replay_is_append_safe_and_path_secret_free(self):
        self.create_manifest()
        artifact = make_raw_artifact(source_url="seed://" + "a" * 64)
        self.store.insert_raw_artifact(artifact)
        arguments = {
            "run_id": "backfill_test",
            "input_path_hash": "a" * 64,
            "payload_sha256": artifact.payload_sha256,
            "outcome": "imported",
            "artifact_id": artifact.artifact_id,
            "post_id": "post1",
            "error_class": None,
            "processed_at_utc": NOW,
        }

        self.assertTrue(self.store.record_seed_file(**arguments))
        self.assertFalse(self.store.record_seed_file(**arguments))

        loaded = self.store.load_seed_file("backfill_test", "a" * 64)
        self.assertEqual(loaded["input_path_hash"], "a" * 64)
        self.assertEqual(loaded["payload_sha256"], artifact.payload_sha256)
        self.assertEqual(loaded["outcome"], "imported")
        self.assertEqual(self.store.seed_file_count("backfill_test"), 1)
        self.assertEqual(
            self.store.seed_outcome_counts("backfill_test"), {"imported": 1}
        )
        with self.store.connect() as conn:
            columns = {
                row["name"]
                for row in conn.execute(
                    "PRAGMA table_info(backfill_seed_files)"
                ).fetchall()
            }
            stored_text = "\n".join(
                str(value)
                for value in conn.execute(
                    "SELECT * FROM backfill_seed_files"
                ).fetchone()
                if value is not None
            )
        self.assertIn("input_path_hash", columns)
        self.assertNotIn("input_path", columns)
        self.assertNotIn("fixture.json", stored_text)

    def test_seed_ledger_conflicting_payload_or_metadata_fails_without_mutation(self):
        self.create_manifest()
        artifact = make_raw_artifact()
        self.store.insert_raw_artifact(artifact)
        arguments = {
            "run_id": "backfill_test",
            "input_path_hash": "a" * 64,
            "payload_sha256": artifact.payload_sha256,
            "outcome": "parse_error",
            "artifact_id": artifact.artifact_id,
            "post_id": None,
            "error_class": "JSONDecodeError",
            "processed_at_utc": NOW,
        }
        self.store.record_seed_file(**arguments)

        for changed in (
            {"payload_sha256": "4" * 64},
            {"outcome": "excluded"},
            {"post_id": "post1"},
            {"error_class": "ValueError"},
        ):
            with self.subTest(changed=changed):
                with self.assertRaisesRegex(
                    backfill_storage.BackfillConflictError,
                    "backfill_seed_files:backfill_test/" + "a" * 64,
                ):
                    self.store.record_seed_file(**{**arguments, **changed})

        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT payload_sha256, outcome, post_id, error_class "
                "FROM backfill_seed_files"
            ).fetchone()
        self.assertEqual(
            dict(row),
            {
                "payload_sha256": artifact.payload_sha256,
                "outcome": "parse_error",
                "post_id": None,
                "error_class": "JSONDecodeError",
            },
        )

    def test_set_backfill_status_updates_manifest_and_run_atomically(self):
        self.create_manifest()

        self.store.set_backfill_status("backfill_test", "seed_complete", NOW)

        with self.store.connect() as conn:
            statuses = (
                conn.execute(
                    "SELECT status FROM backfill_manifests WHERE run_id='backfill_test'"
                ).fetchone()[0],
                conn.execute(
                    "SELECT status FROM runs WHERE run_id='backfill_test'"
                ).fetchone()[0],
            )
            updated_at = conn.execute(
                "SELECT updated_at_utc FROM backfill_manifests "
                "WHERE run_id='backfill_test'"
            ).fetchone()[0]
        self.assertEqual(statuses, ("seed_complete", "seed_complete"))
        self.assertEqual(updated_at, NOW.isoformat())

    def test_freeze_full_collection_contract_is_atomic_and_exact_replay_is_no_op(self):
        self.create_manifest(max_provider_requests=4)
        self.store.set_backfill_status("backfill_test", "seed_complete", NOW)
        for request_number in range(2):
            reserved = self.store.reserve_provider_request(
                "backfill_test", "/search", NOW + timedelta(seconds=request_number)
            )
            self.assertEqual(reserved, request_number + 1)
            self.store.mark_provider_attempt_sent(
                "backfill_test", reserved, NOW + timedelta(seconds=request_number)
            )
            self.store.complete_provider_attempt(
                "backfill_test",
                reserved,
                status="succeeded",
                completed_at_utc=NOW + timedelta(seconds=request_number),
            )
        frozen_at = NOW + timedelta(minutes=1)

        self.store.freeze_full_collection_contract(
            "backfill_test",
            expected_probe_request_count=2,
            max_provider_requests_total=100,
            include_subreddit_sweep=True,
            required_lanes_sha256="a" * 64,
            updated_at_utc=frozen_at,
        )
        with self.store.connect() as conn:
            first_manifest = dict(
                conn.execute(
                    "SELECT status, max_provider_requests, provider_request_count, "
                    "include_subreddit_sweep, required_lanes_sha256, updated_at_utc "
                    "FROM backfill_manifests WHERE run_id='backfill_test'"
                ).fetchone()
            )
            first_run = dict(
                conn.execute(
                    "SELECT status, provider_call, live_send FROM runs "
                    "WHERE run_id='backfill_test'"
                ).fetchone()
            )

        self.store.freeze_full_collection_contract(
            "backfill_test",
            expected_probe_request_count=2,
            max_provider_requests_total=100,
            include_subreddit_sweep=True,
            required_lanes_sha256="a" * 64,
            updated_at_utc=frozen_at + timedelta(hours=1),
        )
        with self.store.connect() as conn:
            replay_manifest = dict(
                conn.execute(
                    "SELECT status, max_provider_requests, provider_request_count, "
                    "include_subreddit_sweep, required_lanes_sha256, updated_at_utc "
                    "FROM backfill_manifests WHERE run_id='backfill_test'"
                ).fetchone()
            )
            replay_run = dict(
                conn.execute(
                    "SELECT status, provider_call, live_send FROM runs "
                    "WHERE run_id='backfill_test'"
                ).fetchone()
            )

        self.assertEqual(
            first_manifest,
            {
                "status": "running",
                "max_provider_requests": 100,
                "provider_request_count": 2,
                "include_subreddit_sweep": 1,
                "required_lanes_sha256": "a" * 64,
                "updated_at_utc": frozen_at.isoformat(),
            },
        )
        self.assertEqual(
            first_run,
            {"status": "running", "provider_call": 1, "live_send": 0},
        )
        self.assertEqual(replay_manifest, first_manifest)
        self.assertEqual(replay_run, first_run)

    def test_freeze_full_collection_contract_rejects_mismatch_and_refreeze(self):
        self.create_manifest(max_provider_requests=4)
        self.store.set_backfill_status("backfill_test", "seed_complete", NOW)
        request_number = self.store.reserve_provider_request(
            "backfill_test", "/search", NOW
        )
        self.assertEqual(request_number, 1)
        self.store.mark_provider_attempt_sent("backfill_test", request_number, NOW)
        self.store.complete_provider_attempt(
            "backfill_test",
            request_number,
            status="succeeded",
            completed_at_utc=NOW,
        )

        invalid_calls = (
            {
                "expected_probe_request_count": 0,
                "max_provider_requests_total": 10,
                "include_subreddit_sweep": False,
                "required_lanes_sha256": "a" * 64,
            },
            {
                "expected_probe_request_count": 1,
                "max_provider_requests_total": 3,
                "include_subreddit_sweep": False,
                "required_lanes_sha256": "a" * 64,
            },
            {
                "expected_probe_request_count": True,
                "max_provider_requests_total": 10,
                "include_subreddit_sweep": False,
                "required_lanes_sha256": "a" * 64,
            },
            {
                "expected_probe_request_count": 1,
                "max_provider_requests_total": 10,
                "include_subreddit_sweep": 1,
                "required_lanes_sha256": "a" * 64,
            },
            {
                "expected_probe_request_count": 1,
                "max_provider_requests_total": 10,
                "include_subreddit_sweep": False,
                "required_lanes_sha256": "not-a-sha",
            },
        )
        for index, kwargs in enumerate(invalid_calls):
            with self.subTest(index=index):
                with self.assertRaises((TypeError, ValueError)):
                    self.store.freeze_full_collection_contract(
                        "backfill_test", updated_at_utc=NOW, **kwargs
                    )

        self.store.freeze_full_collection_contract(
            "backfill_test",
            expected_probe_request_count=1,
            max_provider_requests_total=10,
            include_subreddit_sweep=False,
            required_lanes_sha256="a" * 64,
            updated_at_utc=NOW + timedelta(minutes=1),
        )
        resumed_request = self.store.reserve_provider_request(
            "backfill_test", "/search", NOW + timedelta(minutes=1, seconds=1)
        )
        self.assertEqual(resumed_request, 2)
        self.store.mark_provider_attempt_sent(
            "backfill_test", resumed_request, NOW + timedelta(minutes=1, seconds=1)
        )
        self.store.complete_provider_attempt(
            "backfill_test",
            resumed_request,
            status="succeeded",
            completed_at_utc=NOW + timedelta(minutes=1, seconds=2),
        )
        self.store.set_backfill_status(
            "backfill_test", "partial", NOW + timedelta(minutes=2)
        )
        self.store.freeze_full_collection_contract(
            "backfill_test",
            expected_probe_request_count=1,
            max_provider_requests_total=10,
            include_subreddit_sweep=False,
            required_lanes_sha256="a" * 64,
            updated_at_utc=NOW + timedelta(minutes=3),
        )
        with self.store.connect() as conn:
            before = tuple(
                conn.execute(
                    "SELECT status, max_provider_requests, provider_request_count, "
                    "include_subreddit_sweep, required_lanes_sha256, updated_at_utc "
                    "FROM backfill_manifests WHERE run_id='backfill_test'"
                ).fetchone()
            )
        for max_total, include_sweep, lane_hash in (
            (11, False, "a" * 64),
            (10, True, "b" * 64),
            (10, False, "b" * 64),
        ):
            with self.subTest(
                max_total=max_total,
                include_sweep=include_sweep,
                lane_hash=lane_hash[:1],
            ):
                with self.assertRaises(ValueError):
                    self.store.freeze_full_collection_contract(
                        "backfill_test",
                        expected_probe_request_count=1,
                        max_provider_requests_total=max_total,
                        include_subreddit_sweep=include_sweep,
                        required_lanes_sha256=lane_hash,
                        updated_at_utc=NOW + timedelta(hours=1),
                    )
        with self.store.connect() as conn:
            after = tuple(
                conn.execute(
                    "SELECT status, max_provider_requests, provider_request_count, "
                    "include_subreddit_sweep, required_lanes_sha256, updated_at_utc "
                    "FROM backfill_manifests WHERE run_id='backfill_test'"
                ).fetchone()
            )
        self.assertEqual(after, before)

    def test_freeze_full_collection_contract_requires_seed_complete_probe_state(self):
        self.create_manifest(max_provider_requests=4)
        with self.assertRaises(ValueError):
            self.store.freeze_full_collection_contract(
                "backfill_test",
                expected_probe_request_count=0,
                max_provider_requests_total=4,
                include_subreddit_sweep=False,
                required_lanes_sha256="a" * 64,
                updated_at_utc=NOW,
            )

        with self.assertRaises(KeyError):
            self.store.freeze_full_collection_contract(
                "missing",
                expected_probe_request_count=1,
                max_provider_requests_total=4,
                include_subreddit_sweep=False,
                required_lanes_sha256="a" * 64,
                updated_at_utc=NOW,
            )

    def test_migrate_rejects_legacy_seed_schema_without_mutation(self):
        legacy_path = Path(self.temporary_directory.name) / "legacy.sqlite3"
        with sqlite3.connect(legacy_path) as conn:
            conn.executescript(
                """
                CREATE TABLE backfill_seed_files (
                    run_id TEXT NOT NULL,
                    input_path TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    artifact_id TEXT,
                    error_class TEXT,
                    processed_at_utc TEXT NOT NULL,
                    PRIMARY KEY (run_id, input_path)
                );
                INSERT INTO backfill_seed_files(
                    run_id, input_path, outcome, artifact_id,
                    error_class, processed_at_utc
                ) VALUES (
                    'legacy_run', 'private/fixture.json', 'imported',
                    'legacy_artifact', NULL, '2026-07-11T04:17:09+00:00'
                );
                """
            )

        legacy_store = BackfillStore(legacy_path)
        with self.assertRaisesRegex(
            backfill_storage.BackfillSchemaError,
            "fresh isolated staging DB",
        ):
            legacy_store.migrate()

        with sqlite3.connect(legacy_path) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            columns = tuple(
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(backfill_seed_files)"
                ).fetchall()
            )
            row = conn.execute(
                "SELECT * FROM backfill_seed_files"
            ).fetchone()

        self.assertEqual(tables, {"backfill_seed_files"})
        self.assertEqual(
            columns,
            (
                "run_id",
                "input_path",
                "outcome",
                "artifact_id",
                "error_class",
                "processed_at_utc",
            ),
        )
        self.assertEqual(
            row,
            (
                "legacy_run",
                "private/fixture.json",
                "imported",
                "legacy_artifact",
                None,
                "2026-07-11T04:17:09+00:00",
            ),
        )

    def test_task7_query_apis_order_rows_reconstruct_artifacts_and_fail_unknown_run(self):
        self.create_manifest()
        self.add_candidates(("post-b", "post-a", "post-c"))
        lane_key_hash = sha256("post-a".encode()).hexdigest()
        artifacts = (
            make_raw_artifact(
                artifact_id="comments-b",
                artifact_kind="comments",
                lane_type="comments",
                lane_key_hash=lane_key_hash,
                identity_hash="b" * 64,
                raw_capture_id="comments-capture-b",
                parser_kind="tikhub_comments",
                source_method="tikhub_comments",
                source_url="tikhub://" + "b" * 64,
                source_endpoint="/api/v1/reddit/app/fetch_post_comments",
                payload_sha256="b" * 64,
                relative_path="backfill_test/comments/post-a/b.json.gz",
                page_number=1,
            ),
            make_raw_artifact(
                artifact_id="comments-a",
                artifact_kind="comments",
                lane_type="comments",
                lane_key_hash=lane_key_hash,
                identity_hash="c" * 64,
                raw_capture_id="comments-capture-a",
                parser_kind="tikhub_comments",
                source_method="tikhub_comments",
                source_url="tikhub://" + "c" * 64,
                source_endpoint="/api/v1/reddit/app/fetch_post_comments",
                payload_sha256="c" * 64,
                relative_path="backfill_test/comments/post-a/a.json.gz",
                page_number=1,
            ),
            make_raw_artifact(
                artifact_id="comments-page-2",
                artifact_kind="comments",
                lane_type="comments",
                lane_key_hash=lane_key_hash,
                identity_hash="d" * 64,
                raw_capture_id="comments-capture-2",
                parser_kind="tikhub_comments",
                source_method="tikhub_comments",
                source_url="tikhub://" + "d" * 64,
                source_endpoint="/api/v1/reddit/app/fetch_post_comments",
                payload_sha256="d" * 64,
                relative_path="backfill_test/comments/post-a/2.json.gz",
                page_number=2,
            ),
        )
        for artifact in artifacts:
            self.store.insert_raw_artifact(artifact)

        loaded_candidates = self.store.load_candidates(
            run_id="backfill_test", post_ids=("post-c", "post-a")
        )
        self.assertEqual(
            [row["post_id"] for row in loaded_candidates], ["post-c", "post-a"]
        )
        self.assertEqual(
            self.store.load_raw_artifacts(
                run_id="backfill_test", lane_type="comments", lane_key="post-a"
            ),
            (artifacts[1], artifacts[0], artifacts[2]),
        )
        self.assertEqual(
            self.store.candidate_status_counts("backfill_test"), {"pending": 3}
        )
        self.assertEqual(self.store.discovery_occurrence_total("backfill_test"), 3)
        self.assertEqual(
            self.store.raw_artifact_count(
                "backfill_test", ("dynamic_search", "comments")
            ),
            4,
        )
        self.assertIsNone(self.store.structured_thread_run_id("structured-post"))
        captures, threads, _, _ = make_entity_bundle(post_id="structured-post")
        self.store.insert_entity_bundle(
            captures=(captures[0],), threads=threads, comments=(), analyses=()
        )
        self.assertEqual(
            self.store.structured_thread_run_id("structured-post"), "backfill_test"
        )

        with self.assertRaises(ValueError):
            self.store.load_candidates(
                run_id="backfill_test", post_ids=("post-a", "post-a")
            )
        with self.assertRaises(ValueError):
            self.store.load_candidates(run_id="backfill_test", post_ids=("",))
        with self.assertRaises(KeyError):
            self.store.load_candidates(
                run_id="backfill_test", post_ids=("missing",)
            )
        unknown_run_queries = (
            lambda: self.store.load_candidates(
                run_id="missing", post_ids=("post-a",)
            ),
            lambda: self.store.load_raw_artifacts(
                run_id="missing", lane_type="comments", lane_key="post-a"
            ),
            lambda: self.store.candidate_status_counts("missing"),
            lambda: self.store.discovery_occurrence_total("missing"),
            lambda: self.store.raw_artifact_count("missing", ("comments",)),
        )
        for query in unknown_run_queries:
            with self.subTest(query=query), self.assertRaises(KeyError):
                query()

    def test_task7_load_raw_capture_reconstructs_full_record(self):
        self.create_manifest()
        capture = RawCapture(
            raw_capture_id="task7-capture",
            run_id="backfill_test",
            source_method="tikhub_detail",
            source_url="tikhub://" + "7" * 64,
            captured_at_utc=NOW,
            auth_boundary="provider_gate",
            raw_payload_hash="sha256:" + "8" * 64,
            payload_format="json",
        )
        self.store.insert_entity_bundle(
            captures=(capture,), threads=(), comments=(), analyses=()
        )

        self.assertEqual(self.store.load_raw_capture("task7-capture"), capture)
        self.assertIsNone(self.store.load_raw_capture("missing-capture"))
        with self.assertRaises(ValueError):
            self.store.load_raw_capture("")

    def test_task7_raw_capture_artifact_is_atomic_and_response_cursor_completes_once(self):
        self.create_manifest()
        lane_key = "comment-post"
        capture = RawCapture(
            raw_capture_id="comment-preparse-capture",
            run_id="backfill_test",
            source_method="tikhub_comments",
            source_url="tikhub://" + "4" * 64,
            captured_at_utc=NOW,
            auth_boundary="provider_gate",
            raw_payload_hash="sha256:" + "5" * 64,
            payload_format="json",
        )
        artifact = make_raw_artifact(
            artifact_id="comment-preparse-artifact",
            artifact_kind="comments",
            lane_type="comments",
            lane_key_hash=sha256(lane_key.encode()).hexdigest(),
            identity_hash="6" * 64,
            raw_capture_id=capture.raw_capture_id,
            parser_kind="tikhub_comments",
            source_method="tikhub_comments",
            source_url=capture.source_url,
            source_endpoint="/api/v1/reddit/app/fetch_post_comments",
            payload_sha256="5" * 64,
            relative_path="backfill_test/comments/comment-post/page-1.json.gz",
            page_number=1,
            request_cursor=None,
            response_cursor=None,
        )

        self.assertEqual(
            self.store.persist_raw_capture_artifact(capture, artifact), artifact
        )
        self.assertEqual(
            self.store.persist_raw_capture_artifact(capture, artifact), artifact
        )
        self.assertEqual(self.store.load_raw_capture(capture.raw_capture_id), capture)

        completed = self.store.complete_raw_artifact_response_cursor(
            run_id="backfill_test",
            artifact_id=artifact.artifact_id,
            response_cursor="cursor-1",
        )
        self.assertEqual(completed.response_cursor, "cursor-1")
        self.assertEqual(
            self.store.complete_raw_artifact_response_cursor(
                run_id="backfill_test",
                artifact_id=artifact.artifact_id,
                response_cursor="cursor-1",
            ),
            completed,
        )
        with self.assertRaises(backfill_storage.BackfillConflictError):
            self.store.complete_raw_artifact_response_cursor(
                run_id="backfill_test",
                artifact_id=artifact.artifact_id,
                response_cursor="different-cursor",
            )

        detail_artifact = make_raw_artifact(
            artifact_id="detail-cursor-forbidden",
            artifact_kind="detail",
            lane_type="detail_batch",
            lane_key_hash="9" * 64,
            identity_hash="8" * 64,
            raw_capture_id="detail-cursor-capture",
            parser_kind="tikhub_detail",
            source_method="tikhub_detail",
            source_url="tikhub://" + "9" * 64,
            source_endpoint="/api/v1/reddit/app/fetch_post_details_batch_large",
            payload_sha256="7" * 64,
            relative_path="backfill_test/detail/cursor-forbidden.json.gz",
            page_number=1,
            response_cursor=None,
        )
        self.store.insert_raw_artifact(detail_artifact)
        with self.assertRaises(ValueError):
            self.store.complete_raw_artifact_response_cursor(
                run_id="backfill_test",
                artifact_id=detail_artifact.artifact_id,
                response_cursor="forbidden-cursor",
            )

        colliding_capture = replace(
            capture, raw_capture_id="rolled-back-comment-capture"
        )
        colliding_artifact = replace(
            artifact,
            artifact_id="colliding-comment-artifact",
            raw_capture_id=colliding_capture.raw_capture_id,
            response_cursor=None,
        )
        with self.assertRaises(backfill_storage.BackfillConflictError):
            self.store.persist_raw_capture_artifact(
                colliding_capture, colliding_artifact
            )
        self.assertIsNone(
            self.store.load_raw_capture(colliding_capture.raw_capture_id)
        )

    def test_task7_hydration_outcomes_include_unselected_reason_and_coverage(self):
        self.create_manifest()
        post_ids = ("provider-failed", "budget-deferred", "unresolved")
        self.add_candidates(post_ids)
        self.store.finalize_candidate(
            run_id="backfill_test",
            post_id="provider-failed",
            expected_statuses=("pending",),
            status="failed",
            status_reason="provider_error",
            updated_at_utc=NOW,
        )
        self.store.finalize_candidate(
            run_id="backfill_test",
            post_id="budget-deferred",
            expected_statuses=("pending",),
            status="budget_deferred",
            status_reason="budget_exhausted",
            updated_at_utc=NOW,
        )
        captures, threads, comments, analyses = make_entity_bundle(
            post_id="unresolved", comment_id="unresolved-comment"
        )
        partial_thread = replace(threads[0], coverage_grade="partial")
        self.store.finalize_candidate(
            run_id="backfill_test",
            post_id="unresolved",
            expected_statuses=("pending",),
            status="hydrated",
            status_reason="unresolved_more",
            updated_at_utc=NOW,
            captures=captures,
            threads=(partial_thread,),
            comments=comments,
            analyses=analyses,
        )
        self.store.save_checkpoint(
            replace(
                make_checkpoint(cursor=None, page_number=1),
                lane_type="comments",
                lane_key="unresolved",
                discovered_count=1,
                unique_count=1,
                status="partial",
                stop_reason="unresolved_more",
            )
        )

        self.assertEqual(
            self.store.load_hydration_outcomes("backfill_test"),
            (
                {
                    "post_id": "budget-deferred",
                    "status": "budget_deferred",
                    "status_reason": "budget_exhausted",
                    "coverage_grade": None,
                    "checkpoint_status": None,
                    "checkpoint_stop_reason": None,
                },
                {
                    "post_id": "provider-failed",
                    "status": "failed",
                    "status_reason": "provider_error",
                    "coverage_grade": None,
                    "checkpoint_status": None,
                    "checkpoint_stop_reason": None,
                },
                {
                    "post_id": "unresolved",
                    "status": "hydrated",
                    "status_reason": "unresolved_more",
                    "coverage_grade": "partial",
                    "checkpoint_status": "partial",
                    "checkpoint_stop_reason": "unresolved_more",
                },
            ),
        )
        with self.assertRaises(KeyError):
            self.store.load_hydration_outcomes("missing")

    def test_detail_batches_prepare_30_plus_1_and_replay_membership(self):
        self.create_manifest()
        post_ids = tuple(f"post-{index:02d}" for index in range(31))
        self.add_candidates(post_ids)

        batches = self.store.prepare_detail_batches(
            run_id="backfill_test",
            post_ids=tuple(reversed(post_ids)),
            created_at_utc=NOW,
        )

        self.assertEqual(len(batches), 2)
        self.assertEqual([batch.batch_number for batch in batches], [1, 2])
        self.assertEqual(batches[0].post_ids, post_ids[:30])
        self.assertEqual(batches[1].post_ids, post_ids[30:])
        self.assertTrue(all(batch.status == "prepared" for batch in batches))
        self.assertTrue(all(batch.batch_id.startswith("detail_batch_") for batch in batches))
        self.assertTrue(all(post_id not in batch.batch_id for batch in batches for post_id in post_ids))
        replay = self.store.prepare_detail_batches(
            run_id="backfill_test",
            post_ids=post_ids,
            created_at_utc=NOW + timedelta(days=1),
        )
        self.assertEqual(replay, batches)
        self.assertEqual(
            self.store.load_detail_batches(run_id="backfill_test"), batches
        )
        self.assertEqual(
            self.store.load_detail_batches(
                run_id="backfill_test", post_ids=(post_ids[-1], post_ids[0])
            ),
            batches,
        )
        with self.store.connect() as conn:
            member_counts = [
                row["count"]
                for row in conn.execute(
                    "SELECT batch_id, COUNT(*) AS count "
                    "FROM backfill_detail_batch_members "
                    "GROUP BY batch_id ORDER BY batch_id"
                ).fetchall()
            ]
            unique_members = conn.execute(
                "SELECT COUNT(DISTINCT post_id) FROM backfill_detail_batch_members"
            ).fetchone()[0]
        self.assertEqual(sorted(member_counts), [1, 30])
        self.assertEqual(unique_members, 31)

        with self.assertRaises(ValueError):
            self.store.prepare_detail_batches(
                run_id="backfill_test",
                post_ids=(post_ids[0], post_ids[0]),
                created_at_utc=NOW,
            )
        with self.assertRaises(ValueError):
            self.store.prepare_detail_batches(
                run_id="backfill_test", post_ids=("",), created_at_utc=NOW
            )
        with self.assertRaises(KeyError):
            self.store.prepare_detail_batches(
                run_id="missing", post_ids=(post_ids[0],), created_at_utc=NOW
            )
        with self.assertRaises(KeyError):
            self.store.load_detail_batches(run_id="missing")

    def test_detail_batch_loader_rejects_invalid_member_contracts(self):
        for corruption in ("empty", "oversize", "ordinal_gap", "hash_mismatch"):
            with self.subTest(corruption=corruption):
                self.store = BackfillStore(
                    Path(self.temporary_directory.name)
                    / f"member-contract-{corruption}.sqlite3"
                )
                self.store.migrate()
                self.create_manifest()
                member_count = 31 if corruption == "oversize" else 3
                post_ids = tuple(
                    f"{corruption}-post-{index:02d}"
                    for index in range(member_count)
                )
                self.add_candidates(post_ids)
                assigned = post_ids[:30] if corruption == "oversize" else post_ids
                batch = self.store.prepare_detail_batches(
                    run_id="backfill_test",
                    post_ids=assigned,
                    created_at_utc=NOW,
                )[0]

                with sqlite3.connect(self.store.path) as conn:
                    if corruption == "empty":
                        conn.execute(
                            "DELETE FROM backfill_detail_batch_members "
                            "WHERE run_id = ? AND batch_id = ?",
                            ("backfill_test", batch.batch_id),
                        )
                    elif corruption == "oversize":
                        conn.execute(
                            "INSERT INTO backfill_detail_batch_members("
                            "run_id, batch_id, ordinal, post_id"
                            ") VALUES (?, ?, 30, ?)",
                            ("backfill_test", batch.batch_id, post_ids[30]),
                        )
                    elif corruption == "ordinal_gap":
                        conn.execute(
                            "UPDATE backfill_detail_batch_members SET ordinal = 7 "
                            "WHERE run_id = ? AND batch_id = ? AND ordinal = 1",
                            ("backfill_test", batch.batch_id),
                        )
                    else:
                        wrong_batch_id = "detail_batch_000000000000000000000000"
                        conn.execute(
                            "UPDATE backfill_detail_batches SET batch_id = ? "
                            "WHERE run_id = ? AND batch_id = ?",
                            (wrong_batch_id, "backfill_test", batch.batch_id),
                        )
                        conn.execute(
                            "UPDATE backfill_detail_batch_members SET batch_id = ? "
                            "WHERE run_id = ? AND batch_id = ?",
                            (wrong_batch_id, "backfill_test", batch.batch_id),
                        )

                with self.assertRaises(backfill_storage.BackfillConflictError):
                    self.store.load_detail_batches(run_id="backfill_test")

    def test_detail_batch_attach_finish_and_exact_replay(self):
        self.create_manifest()
        self.add_candidates(("post-1", "post-2"))
        first = self.store.prepare_detail_batches(
            run_id="backfill_test", post_ids=("post-1",), created_at_utc=NOW
        )[0]
        second = self.store.prepare_detail_batches(
            run_id="backfill_test", post_ids=("post-2",), created_at_utc=NOW
        )[0]
        artifact = make_raw_artifact(
            artifact_id="detail-artifact-1",
            artifact_kind="detail",
            lane_type="detail_batch",
            lane_key_hash=sha256(first.batch_id.encode()).hexdigest(),
            identity_hash="e" * 64,
            raw_capture_id="detail-capture-1",
            parser_kind="tikhub_detail",
            source_method="tikhub_detail",
            source_url="tikhub://" + "e" * 64,
            source_endpoint="/api/v1/reddit/app/fetch_post_details_batch_large",
            payload_sha256="e" * 64,
            relative_path="backfill_test/detail/1.json.gz",
            page_number=first.batch_number,
        )
        self.store.insert_raw_artifact(artifact)

        attached = self.store.attach_detail_batch_artifact(
            run_id="backfill_test",
            batch_id=first.batch_id,
            artifact_id=artifact.artifact_id,
            updated_at_utc=NOW + timedelta(seconds=1),
        )
        self.assertEqual(attached.status, "raw_persisted")
        self.assertEqual(attached.artifact_id, artifact.artifact_id)
        self.assertEqual(
            self.store.attach_detail_batch_artifact(
                run_id="backfill_test",
                batch_id=first.batch_id,
                artifact_id=artifact.artifact_id,
                updated_at_utc=NOW + timedelta(days=1),
            ),
            attached,
        )
        wrong_type_artifact = make_raw_artifact(
            artifact_id="wrong-type-after-attach",
            raw_capture_id="wrong-type-after-attach-capture",
            source_url="seed://wrong-type-after-attach",
            payload_sha256="6" * 64,
            relative_path="backfill_test/seed/wrong-type-after-attach.json.gz",
        )
        self.store.insert_raw_artifact(wrong_type_artifact)
        for conflicting_artifact_id in (
            "missing-after-attach",
            wrong_type_artifact.artifact_id,
        ):
            with self.subTest(conflicting_artifact_id=conflicting_artifact_id):
                with self.assertRaises(backfill_storage.BackfillConflictError):
                    self.store.attach_detail_batch_artifact(
                        run_id="backfill_test",
                        batch_id=first.batch_id,
                        artifact_id=conflicting_artifact_id,
                        updated_at_utc=NOW + timedelta(days=1),
                    )
        with self.assertRaises(ValueError):
            self.store.finish_detail_batch(
                run_id="backfill_test",
                batch_id=first.batch_id,
                status="complete",
                stop_reason="unexpected_reason",
                updated_at_utc=NOW + timedelta(seconds=2),
            )
        with self.assertRaises(ValueError):
            self.store.finish_detail_batch(
                run_id="backfill_test",
                batch_id=second.batch_id,
                status="failed",
                stop_reason=None,
                updated_at_utc=NOW + timedelta(seconds=2),
            )
        with self.assertRaises(backfill_storage.BackfillConflictError):
            self.store.finish_detail_batch(
                run_id="backfill_test",
                batch_id=first.batch_id,
                status="complete",
                stop_reason=None,
                updated_at_utc=NOW + timedelta(seconds=2),
            )

        with self.store.connect() as conn:
            conn.execute(
                "UPDATE backfill_candidates SET status='excluded', "
                "updated_at_utc=? WHERE run_id=? AND post_id=?",
                ((NOW + timedelta(seconds=2)).isoformat(), "backfill_test", "post-1"),
            )
        completed = self.store.finish_detail_batch(
            run_id="backfill_test",
            batch_id=first.batch_id,
            status="complete",
            stop_reason=None,
            updated_at_utc=NOW + timedelta(seconds=3),
        )
        self.assertEqual(completed.status, "complete")
        self.assertEqual(
            self.store.finish_detail_batch(
                run_id="backfill_test",
                batch_id=first.batch_id,
                status="complete",
                stop_reason=None,
                updated_at_utc=NOW + timedelta(days=2),
            ),
            completed,
        )
        failed = self.store.finish_detail_batch(
            run_id="backfill_test",
            batch_id=second.batch_id,
            status="failed",
            stop_reason="provider_error",
            updated_at_utc=NOW + timedelta(seconds=4),
        )
        self.assertEqual((failed.status, failed.stop_reason), ("failed", "provider_error"))
        with self.assertRaises(backfill_storage.BackfillConflictError):
            self.store.finish_detail_batch(
                run_id="backfill_test",
                batch_id=second.batch_id,
                status="failed",
                stop_reason="budget_exhausted",
                updated_at_utc=NOW + timedelta(days=2),
            )

        invalid_artifact = make_raw_artifact(
            artifact_id="invalid-detail-artifact",
            artifact_kind="detail",
            lane_type="detail_batch",
            lane_key_hash=sha256(second.batch_id.encode()).hexdigest(),
            identity_hash="f" * 64,
            raw_capture_id="invalid-detail-capture",
            parser_kind="wrong_parser",
            source_method="tikhub_detail",
            source_url="tikhub://" + "f" * 64,
            source_endpoint="/api/v1/reddit/app/fetch_post_details_batch_large",
            payload_sha256="f" * 64,
            relative_path="backfill_test/detail/invalid.json.gz",
            page_number=second.batch_number,
        )
        self.store.insert_raw_artifact(invalid_artifact)
        with self.assertRaises(ValueError):
            self.store.attach_detail_batch_artifact(
                run_id="backfill_test",
                batch_id=second.batch_id,
                artifact_id=invalid_artifact.artifact_id,
                updated_at_utc=NOW,
            )

    def test_exact_detail_attachment_revalidates_persisted_artifact(self):
        self.create_manifest()
        self.add_candidates(("post-revalidate",))
        batch = self.store.prepare_detail_batches(
            run_id="backfill_test",
            post_ids=("post-revalidate",),
            created_at_utc=NOW,
        )[0]
        artifact = make_raw_artifact(
            artifact_id="detail-artifact-revalidate",
            artifact_kind="detail",
            lane_type="detail_batch",
            lane_key_hash=sha256(batch.batch_id.encode()).hexdigest(),
            identity_hash="7" * 64,
            raw_capture_id="detail-capture-revalidate",
            parser_kind="tikhub_detail",
            source_method="tikhub_detail",
            source_url="tikhub://" + "7" * 64,
            source_endpoint="/api/v1/reddit/app/fetch_post_details_batch_large",
            payload_sha256="7" * 64,
            relative_path="backfill_test/detail/revalidate.json.gz",
            page_number=batch.batch_number,
        )
        self.store.insert_raw_artifact(artifact)
        self.store.attach_detail_batch_artifact(
            run_id="backfill_test",
            batch_id=batch.batch_id,
            artifact_id=artifact.artifact_id,
            updated_at_utc=NOW,
        )
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE backfill_raw_artifacts SET parser_kind = 'tampered' "
                "WHERE run_id = ? AND artifact_id = ?",
                ("backfill_test", artifact.artifact_id),
            )

        with self.assertRaises(ValueError):
            self.store.attach_detail_batch_artifact(
                run_id="backfill_test",
                batch_id=batch.batch_id,
                artifact_id=artifact.artifact_id,
                updated_at_utc=NOW + timedelta(seconds=1),
            )

    def test_finalize_candidate_terminal_replay_precedes_expected_status_and_preserves_time(self):
        self.create_manifest()
        self.add_candidates(("excluded-post", "failed-post"))

        first = self.store.finalize_candidate(
            run_id="backfill_test",
            post_id="excluded-post",
            expected_statuses=("pending",),
            status="excluded",
            status_reason="detail_unparseable",
            updated_at_utc=NOW,
        )
        replay = self.store.finalize_candidate(
            run_id="backfill_test",
            post_id="excluded-post",
            expected_statuses=("pending",),
            status="excluded",
            status_reason="detail_unparseable",
            updated_at_utc=NOW + timedelta(days=1),
        )
        self.assertEqual(first, InsertCounts())
        self.assertEqual(replay, InsertCounts())
        candidate = self.store.load_candidates(
            run_id="backfill_test", post_ids=("excluded-post",)
        )[0]
        self.assertEqual(candidate["updated_at_utc"], NOW.isoformat())
        with self.assertRaises(backfill_storage.BackfillConflictError):
            self.store.finalize_candidate(
                run_id="backfill_test",
                post_id="excluded-post",
                expected_statuses=("pending",),
                status="excluded",
                status_reason="detail_missing",
                updated_at_utc=NOW,
            )
        with self.assertRaises(backfill_storage.BackfillConflictError):
            self.store.finalize_candidate(
                run_id="backfill_test",
                post_id="excluded-post",
                expected_statuses=("pending",),
                status="failed",
                status_reason="provider_error",
                updated_at_utc=NOW,
            )

        for unsafe_reason in (
            "",
            "ProviderError",
            "provider-error",
            "provider error",
            "https://secret.invalid/token",
            "x" * 65,
        ):
            with self.subTest(unsafe_reason=unsafe_reason), self.assertRaises(ValueError):
                self.store.finalize_candidate(
                    run_id="backfill_test",
                    post_id="failed-post",
                    expected_statuses=("pending",),
                    status="failed",
                    status_reason=unsafe_reason,
                    updated_at_utc=NOW,
                )
        captures, _, _, _ = make_entity_bundle(post_id="failed-post")
        with self.assertRaises(ValueError):
            self.store.finalize_candidate(
                run_id="backfill_test",
                post_id="failed-post",
                expected_statuses=("pending",),
                status="failed",
                status_reason="provider_error",
                updated_at_utc=NOW,
                captures=(captures[0],),
            )
        with self.assertRaises(KeyError):
            self.store.finalize_candidate(
                run_id="missing",
                post_id="failed-post",
                expected_statuses=("pending",),
                status="failed",
                status_reason="provider_error",
                updated_at_utc=NOW,
            )

    def test_finalize_hydrated_bundle_is_atomic_replay_safe_and_rolls_back_conflicts(self):
        self.create_manifest()
        self.add_candidates(("post1", "bad-post", "conflict-post"))
        captures, threads, comments, analyses = make_entity_bundle(post_id="post1")

        inserted = self.store.finalize_candidate(
            run_id="backfill_test",
            post_id="post1",
            expected_statuses=("pending",),
            status="hydrated",
            status_reason=None,
            updated_at_utc=NOW,
            captures=captures,
            threads=threads,
            comments=comments,
            analyses=analyses,
        )
        replay = self.store.finalize_candidate(
            run_id="backfill_test",
            post_id="post1",
            expected_statuses=("pending",),
            status="hydrated",
            status_reason=None,
            updated_at_utc=NOW + timedelta(days=1),
            captures=captures,
            threads=threads,
            comments=comments,
            analyses=analyses,
        )
        self.assertEqual(inserted, InsertCounts(2, 1, 1, 2))
        self.assertEqual(replay, InsertCounts())
        hydrated = self.store.load_candidates(
            run_id="backfill_test", post_ids=("post1",)
        )[0]
        self.assertEqual(hydrated["status"], "hydrated")
        self.assertEqual(hydrated["updated_at_utc"], NOW.isoformat())
        with self.assertRaises(backfill_storage.BackfillConflictError):
            self.store.finalize_candidate(
                run_id="backfill_test",
                post_id="post1",
                expected_statuses=("pending",),
                status="hydrated",
                status_reason=None,
                updated_at_utc=NOW,
                captures=(),
                threads=threads,
                comments=comments,
                analyses=analyses,
            )
        with self.assertRaises(backfill_storage.BackfillConflictError):
            self.store.finalize_candidate(
                run_id="backfill_test",
                post_id="post1",
                expected_statuses=("pending",),
                status="hydrated",
                status_reason=None,
                updated_at_utc=NOW,
                captures=captures,
                threads=threads,
                comments=comments,
                analyses=analyses[:-1],
            )
        with self.assertRaises(backfill_storage.BackfillConflictError):
            self.store.finalize_candidate(
                run_id="backfill_test",
                post_id="post1",
                expected_statuses=("pending",),
                status="hydrated",
                status_reason=None,
                updated_at_utc=NOW,
                captures=captures,
                threads=(replace(threads[0], title="changed"),),
                comments=comments,
                analyses=analyses,
            )

        bad_captures, bad_threads, bad_comments, bad_analyses = make_entity_bundle(
            post_id="bad-post", comment_id="bad-comment", raw_prefix="bad"
        )
        with self.assertRaises(ValueError):
            self.store.finalize_candidate(
                run_id="backfill_test",
                post_id="bad-post",
                expected_statuses=("pending",),
                status="hydrated",
                status_reason=None,
                updated_at_utc=NOW,
                captures=bad_captures,
                threads=bad_threads,
                comments=bad_comments,
                analyses=bad_analyses[:-1],
            )
        self.assertEqual(
            self.store.load_candidates(
                run_id="backfill_test", post_ids=("bad-post",)
            )[0]["status"],
            "pending",
        )

        conflict_captures, conflict_threads, conflict_comments, conflict_analyses = (
            make_entity_bundle(
                post_id="conflict-post",
                comment_id="conflict-comment",
                raw_prefix="conflict",
            )
        )
        self.store.insert_entity_bundle(
            captures=(
                replace(
                    conflict_captures[1],
                    source_url="https://different.example.invalid/conflict",
                ),
            ),
            threads=(),
            comments=(),
            analyses=(),
        )
        with self.assertRaises(backfill_storage.BackfillConflictError):
            self.store.finalize_candidate(
                run_id="backfill_test",
                post_id="conflict-post",
                expected_statuses=("pending",),
                status="hydrated",
                status_reason=None,
                updated_at_utc=NOW,
                captures=conflict_captures,
                threads=conflict_threads,
                comments=conflict_comments,
                analyses=conflict_analyses,
            )
        with self.store.connect() as conn:
            rolled_back_capture = conn.execute(
                "SELECT 1 FROM raw_captures WHERE raw_capture_id = ?",
                (conflict_captures[0].raw_capture_id,),
            ).fetchone()
            rolled_back_thread = conn.execute(
                "SELECT 1 FROM reddit_threads WHERE post_id = 'conflict-post'"
            ).fetchone()
        self.assertIsNone(rolled_back_capture)
        self.assertIsNone(rolled_back_thread)
        self.assertEqual(
            self.store.load_candidates(
                run_id="backfill_test", post_ids=("conflict-post",)
            )[0]["status"],
            "pending",
        )

    def test_migrate_rejects_incompatible_detail_batch_ledgers(self):
        for table in ("backfill_detail_batches", "backfill_detail_batch_members"):
            with self.subTest(table=table):
                path = Path(self.temporary_directory.name) / f"legacy-{table}.sqlite3"
                with sqlite3.connect(path) as conn:
                    conn.execute(f"CREATE TABLE {table}(run_id TEXT NOT NULL)")
                store = BackfillStore(path)
                with self.assertRaisesRegex(
                    backfill_storage.BackfillSchemaError,
                    "fresh isolated staging DB",
                ):
                    store.migrate()
                with sqlite3.connect(path) as conn:
                    tables = {
                        row[0]
                        for row in conn.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        ).fetchall()
                    }
                    columns = tuple(
                        row[1]
                        for row in conn.execute(
                            f"PRAGMA table_info({table})"
                        ).fetchall()
                    )
                self.assertEqual(tables, {table})
                self.assertEqual(columns, ("run_id",))

    def test_migrate_rejects_same_columns_without_detail_ledger_constraints(self):
        table_definitions = {
            "backfill_detail_batches": """
                CREATE TABLE backfill_detail_batches (
                    run_id TEXT,
                    batch_id TEXT,
                    batch_number INTEGER,
                    status TEXT,
                    artifact_id TEXT,
                    stop_reason TEXT,
                    created_at_utc TEXT,
                    updated_at_utc TEXT
                )
            """,
            "backfill_detail_batch_members": """
                CREATE TABLE backfill_detail_batch_members (
                    run_id TEXT,
                    batch_id TEXT,
                    ordinal INTEGER,
                    post_id TEXT
                )
            """,
        }
        for table, ddl in table_definitions.items():
            with self.subTest(table=table):
                path = Path(self.temporary_directory.name) / f"weak-{table}.sqlite3"
                with sqlite3.connect(path) as conn:
                    conn.execute(ddl)
                store = BackfillStore(path)

                with self.assertRaisesRegex(
                    backfill_storage.BackfillSchemaError,
                    "fresh isolated staging DB",
                ):
                    store.migrate()

                with sqlite3.connect(path) as conn:
                    indexes = conn.execute(
                        f"PRAGMA index_list({table})"
                    ).fetchall()
                    foreign_keys = conn.execute(
                        f"PRAGMA foreign_key_list({table})"
                    ).fetchall()
                    tables = {
                        row[0]
                        for row in conn.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        ).fetchall()
                    }
                self.assertEqual(indexes, [])
                self.assertEqual(foreign_keys, [])
                self.assertEqual(tables, {table})

    def test_migrate_rejects_missing_checks_and_changed_detail_fk_actions(self):
        cases = {
            "missing_checks": """
                CREATE TABLE backfill_detail_batches (
                    run_id TEXT NOT NULL,
                    batch_id TEXT NOT NULL,
                    batch_number INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    artifact_id TEXT,
                    stop_reason TEXT,
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL,
                    PRIMARY KEY (run_id, batch_id),
                    UNIQUE (run_id, batch_number),
                    FOREIGN KEY (run_id) REFERENCES backfill_manifests(run_id),
                    FOREIGN KEY (run_id, artifact_id)
                        REFERENCES backfill_raw_artifacts(run_id, artifact_id)
                )
            """,
            "changed_fk_action": """
                CREATE TABLE backfill_detail_batches (
                    run_id TEXT NOT NULL,
                    batch_id TEXT NOT NULL,
                    batch_number INTEGER NOT NULL CHECK (batch_number > 0),
                    status TEXT NOT NULL CHECK (
                        status IN ('prepared', 'raw_persisted', 'complete', 'failed')
                    ),
                    artifact_id TEXT,
                    stop_reason TEXT,
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL,
                    PRIMARY KEY (run_id, batch_id),
                    UNIQUE (run_id, batch_number),
                    FOREIGN KEY (run_id) REFERENCES backfill_manifests(run_id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (run_id, artifact_id)
                        REFERENCES backfill_raw_artifacts(run_id, artifact_id)
                )
            """,
        }
        for name, ddl in cases.items():
            with self.subTest(name=name):
                path = Path(self.temporary_directory.name) / f"exact-{name}.sqlite3"
                with sqlite3.connect(path) as conn:
                    conn.execute(ddl)
                store = BackfillStore(path)

                with self.assertRaisesRegex(
                    backfill_storage.BackfillSchemaError,
                    "fresh isolated staging DB",
                ):
                    store.migrate()


if __name__ == "__main__":
    unittest.main()
