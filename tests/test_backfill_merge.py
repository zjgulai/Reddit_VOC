from __future__ import annotations

from dataclasses import fields, replace
from datetime import datetime, timezone
from hashlib import sha256
import inspect
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from reddit_voc import backfill_merge as merge_module
from reddit_voc.backfill_merge import (
    PLAN_KEYS,
    MergeAuthorizationError,
    MergeCommittedReviewError,
    MergeInvariantError,
    MergePreconditionError,
    MergeSummary,
    merge_staging_insert_only,
    plan_insert_only_merge,
)
from reddit_voc.backfill_models import AnalysisRow, BackfillManifest
from reddit_voc.backfill_storage import BackfillStore
from reddit_voc.models import RawCapture, RedditComment, RedditThread
from reddit_voc.storage import VocStore


RUN_ID = "backfill_momcozy_20250101_20260711"
NOW = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)


def _manifest() -> BackfillManifest:
    return BackfillManifest(
        run_id=RUN_ID,
        status="seed_complete",
        window_start_utc="2024-12-31T16:00:00+00:00",
        requested_end_utc="2026-07-11T16:00:00+00:00",
        effective_end_utc="2026-07-11T16:00:00+00:00",
        search_terms=("Momcozy",),
        subreddits=("ExclusivelyPumping",),
        include_subreddit_sweep=False,
        required_lanes_sha256="1" * 64,
        keyword_config_sha256="2" * 64,
        max_provider_requests=0,
        provider_request_count=0,
        provider_call=False,
        live_send=False,
        created_at_utc=NOW.isoformat(),
        updated_at_utc=NOW.isoformat(),
    )


def _capture(raw_id: str, *, source_suffix: str, payload_char: str) -> RawCapture:
    return RawCapture(
        raw_capture_id=raw_id,
        run_id=RUN_ID,
        source_method="seed_browser_thread",
        source_url=f"https://reddit.invalid/{source_suffix}",
        captured_at_utc=NOW,
        auth_boundary="public",
        raw_payload_hash=f"sha256:{payload_char * 64}",
        payload_format="json",
        browser_status="ok",
        http_status=200,
        selector_version="fixture-v1",
        blocked_reason=None,
        secrets_written=False,
    )


def _prepare_merge_staging(
    store: BackfillStore, *, status: str = "success"
) -> None:
    store.create_manifest(replace(_manifest(), max_provider_requests=1))
    request_number = store.reserve_provider_request(
        RUN_ID,
        "/api/v1/reddit/app/fetch_dynamic_search",
        NOW,
    )
    store.mark_provider_attempt_sent(RUN_ID, request_number, NOW)
    store.complete_provider_attempt(
        RUN_ID,
        request_number,
        status="succeeded",
        completed_at_utc=NOW,
        http_status=200,
    )
    store.set_backfill_status(RUN_ID, status, NOW)


class BackfillMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.staging_path = self.root / "staging.sqlite3"
        self.production_path = self.root / "production.sqlite3"
        self.backup_path = self.root / "production.before-merge.sqlite3"
        self.staging = BackfillStore(self.staging_path)
        self.staging.migrate()
        _prepare_merge_staging(self.staging)
        self.production = VocStore(self.production_path)
        self.production.migrate()

    def _add_post(
        self,
        post_id: str,
        *,
        shared_post_capture: RawCapture | None = None,
        include_comment: bool = True,
    ) -> tuple[RawCapture, RawCapture | None]:
        post_capture = shared_post_capture or _capture(
            f"raw-post-{post_id}", source_suffix=post_id, payload_char="a"
        )
        comment_id = f"comment-{post_id}"
        comment_capture = (
            _capture(
                f"raw-comment-{post_id}",
                source_suffix=f"{post_id}/comments",
                payload_char="b",
            )
            if include_comment
            else None
        )
        thread = RedditThread(
            post_id=post_id,
            run_id=RUN_ID,
            raw_capture_id=post_capture.raw_capture_id,
            subreddit="ExclusivelyPumping",
            title=f"Momcozy wearable pump {post_id}",
            selftext="The pump leaks during longer sessions.",
            source_url=f"https://reddit.invalid/{post_id}",
            created_at_utc=NOW,
            score=12,
            num_comments_reported=int(include_comment),
            parsed_comment_count=int(include_comment),
            more_node_count=0,
            coverage_grade="full" if include_comment else "post_only",
            matched_keywords=["Momcozy", "wearable pump"],
            author_hash=f"author-{post_id}",
            media_urls=[],
        )
        comments: tuple[RedditComment, ...] = ()
        if comment_capture is not None:
            comments = (
                RedditComment(
                    comment_id=comment_id,
                    post_id=post_id,
                    run_id=RUN_ID,
                    raw_capture_id=comment_capture.raw_capture_id,
                    parent_id=f"t3_{post_id}",
                    body="Mine leaked too.",
                    created_at_utc=NOW,
                    score=3,
                    depth=0,
                    is_submitter=False,
                    matched_keywords=["Momcozy"],
                    author_hash=f"comment-author-{post_id}",
                    deleted_or_removed=False,
                ),
            )
        analyses = [
            AnalysisRow(
                analysis_id=f"analysis-post-{post_id}",
                run_id=RUN_ID,
                source_type="post",
                source_id=post_id,
                analysis_version="local_rules_v1",
                sentiment_label="negative",
                sentiment_score=-0.7,
                topic="product_experience",
                severity="high",
                confidence=0.9,
                pain_points=("leak",),
            )
        ]
        if include_comment:
            analyses.append(
                AnalysisRow(
                    analysis_id=f"analysis-comment-{post_id}",
                    run_id=RUN_ID,
                    source_type="comment",
                    source_id=comment_id,
                    analysis_version="local_rules_v1",
                    sentiment_label="negative",
                    sentiment_score=-0.6,
                    topic="product_experience",
                    severity="medium",
                    confidence=0.8,
                    pain_points=("leak",),
                )
            )
        captures = (post_capture,) + (
            () if comment_capture is None else (comment_capture,)
        )
        self.staging.insert_entity_bundle(
            captures=captures,
            threads=(thread,),
            comments=comments,
            analyses=tuple(analyses),
        )
        return post_capture, comment_capture

    def _row(self, path: Path, table: str, key: str, value: str) -> sqlite3.Row:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                f"SELECT * FROM {table} WHERE {key}=?", (value,)
            ).fetchone()
            self.assertIsNotNone(row)
            return row
        finally:
            conn.close()

    def _copy_staging_row(
        self,
        table: str,
        key: str,
        value: str,
        *,
        overrides: dict[str, object] | None = None,
    ) -> None:
        row = self._row(self.staging_path, table, key, value)
        record = dict(row)
        record.update(overrides or {})
        columns = tuple(record)
        with sqlite3.connect(self.production_path) as conn:
            conn.execute(
                f"INSERT INTO {table}({', '.join(columns)}) VALUES "
                f"({', '.join('?' for _ in columns)})",
                tuple(record[column] for column in columns),
            )

    def _sha(self, path: Path) -> str:
        return sha256(path.read_bytes()).hexdigest()

    def _plan_sha(
        self,
        staging_path: Path | None = None,
        production_path: Path | None = None,
    ) -> str:
        plan = plan_insert_only_merge(
            staging_path or self.staging_path,
            production_path or self.production_path,
            run_id=RUN_ID,
        )
        plan_sha256 = plan["plan_sha256"]
        self.assertIsInstance(plan_sha256, str)
        return str(plan_sha256)

    def _merge(self) -> MergeSummary:
        expected_plan_sha256 = self._plan_sha()
        with patch.dict(
            os.environ, {"REDDIT_VOC_ENABLE_PRODUCTION_MERGE": "1"}, clear=False
        ):
            return merge_staging_insert_only(
                self.staging_path,
                self.production_path,
                run_id=RUN_ID,
                backup_path=self.backup_path,
                expected_production_sha256=self._sha(self.production_path),
                expected_plan_sha256=expected_plan_sha256,
                authorized=True,
            )

    def test_public_api_and_plan_contract_are_exact_deterministic_and_query_only(self) -> None:
        self._add_post("post-one")
        staging_before = (self._sha(self.staging_path), self.staging_path.stat().st_mtime_ns)
        production_before = (
            self._sha(self.production_path),
            self.production_path.stat().st_mtime_ns,
        )
        first = plan_insert_only_merge(
            self.staging_path, self.production_path, run_id=RUN_ID
        )
        second = plan_insert_only_merge(
            self.staging_path, self.production_path, run_id=RUN_ID
        )
        self.assertEqual(first, second)
        self.assertEqual(tuple(first), PLAN_KEYS)
        self.assertEqual(first["schema_version"], "backfill_insert_only_merge_plan_v1")
        self.assertTrue(first["query_only"])
        self.assertFalse(first["production_write"])
        self.assertFalse(first["provider_attempt_made"])
        self.assertFalse(first["live_send"])
        self.assertEqual(first["run_action"], "insert")
        self.assertEqual(first["approved_counts"]["reddit_threads_to_insert"], 1)
        self.assertEqual(tuple(first["staging_fingerprints"]), (
            "runs",
            "backfill_raw_artifacts",
            "raw_captures",
            "reddit_threads",
            "reddit_comments",
            "analysis_results",
        ))
        payload = dict(first)
        plan_hash = payload.pop("plan_sha256")
        expected_hash = sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(plan_hash, expected_hash)
        serialized = json.dumps(first, ensure_ascii=False)
        for secret_value in ("post-one", "reddit.invalid", "Mine leaked too"):
            self.assertNotIn(secret_value, serialized)
        self.assertEqual(
            staging_before,
            (self._sha(self.staging_path), self.staging_path.stat().st_mtime_ns),
        )
        self.assertEqual(
            production_before,
            (self._sha(self.production_path), self.production_path.stat().st_mtime_ns),
        )

    def test_plan_closes_staging_when_production_open_fails(self) -> None:
        real_open = merge_module._open_readonly_database
        opened: list[sqlite3.Connection] = []

        def fail_second(path: Path) -> sqlite3.Connection:
            if path == self.production_path.resolve():
                raise MergePreconditionError("database_readonly_open_failed")
            connection = real_open(path)
            opened.append(connection)
            return connection

        with patch.object(
            merge_module, "_open_readonly_database", side_effect=fail_second
        ):
            with self.assertRaisesRegex(
                MergePreconditionError, r"\Adatabase_readonly_open_failed\Z"
            ):
                plan_insert_only_merge(
                    self.staging_path, self.production_path, run_id=RUN_ID
                )
        self.assertEqual(len(opened), 1)
        with self.assertRaises(sqlite3.ProgrammingError):
            opened[0].execute("SELECT 1")

    def test_plan_requires_manifest_and_run_status_success(self) -> None:
        for status in ("seed_complete", "partial"):
            with self.subTest(status=status), TemporaryDirectory() as isolated:
                staging_path = Path(isolated) / "staging.sqlite3"
                production_path = Path(isolated) / "production.sqlite3"
                staging = BackfillStore(staging_path)
                staging.migrate()
                _prepare_merge_staging(staging, status=status)
                VocStore(production_path).migrate()
                production_before = production_path.read_bytes()

                with self.assertRaisesRegex(
                    MergePreconditionError,
                    r"\Astaging_run_manifest_mismatch\Z",
                ):
                    plan_insert_only_merge(
                        staging_path, production_path, run_id=RUN_ID
                    )

                self.assertEqual(production_path.read_bytes(), production_before)

    def test_plan_requires_manifest_and_run_provider_call_true(self) -> None:
        production_before = self.production_path.read_bytes()
        with sqlite3.connect(self.staging_path) as connection:
            connection.execute(
                "UPDATE backfill_manifests SET provider_call=0 WHERE run_id=?",
                (RUN_ID,),
            )
            connection.execute(
                "UPDATE runs SET provider_call=0 WHERE run_id=?", (RUN_ID,)
            )

        with self.assertRaisesRegex(
            MergePreconditionError,
            r"\Astaging_run_manifest_mismatch\Z",
        ):
            plan_insert_only_merge(
                self.staging_path, self.production_path, run_id=RUN_ID
            )

        self.assertEqual(self.production_path.read_bytes(), production_before)

    def test_clean_merge_has_exact_deltas_backup_and_zero_delivery(self) -> None:
        self._add_post("post-one")
        summary = self._merge()
        self.assertIsInstance(summary, MergeSummary)
        self.assertEqual(summary.status, "merged")
        self.assertTrue(summary.authorized)
        self.assertTrue(summary.production_write)
        self.assertEqual(summary.planned_runs, summary.inserted_runs)
        self.assertEqual(summary.planned_raw_captures, summary.inserted_raw_captures)
        self.assertEqual(summary.planned_threads, summary.inserted_threads)
        self.assertEqual(summary.planned_comments, summary.inserted_comments)
        self.assertEqual(summary.planned_analyses, summary.inserted_analyses)
        self.assertEqual(
            (
                summary.inserted_runs,
                summary.inserted_raw_captures,
                summary.inserted_threads,
                summary.inserted_comments,
                summary.inserted_analyses,
            ),
            (1, 2, 1, 1, 2),
        )
        self.assertEqual(summary.delivery_delta, 0)
        self.assertEqual(summary.updated, 0)
        self.assertEqual(summary.deleted, 0)
        self.assertFalse(summary.provider_attempt_made)
        self.assertFalse(summary.live_send)
        self.assertTrue(self.backup_path.is_file())
        with sqlite3.connect(self.production_path) as conn:
            counts = tuple(
                conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "runs",
                    "raw_captures",
                    "reddit_threads",
                    "reddit_comments",
                    "analysis_results",
                    "delivery_previews",
                )
            )
        self.assertEqual(counts, (1, 2, 1, 1, 2, 0))

    def test_unauthorized_or_missing_env_gate_touches_no_path(self) -> None:
        missing_staging = self.root / "missing-staging.sqlite3"
        missing_production = self.root / "missing-production.sqlite3"
        for authorized, env in ((False, "1"), (True, "0"), (1, "1")):
            with self.subTest(authorized=authorized, env=env):
                with patch.dict(
                    os.environ,
                    {"REDDIT_VOC_ENABLE_PRODUCTION_MERGE": env},
                    clear=False,
                ):
                    with self.assertRaisesRegex(
                        MergeAuthorizationError,
                        r"\Aproduction_merge_not_authorized\Z",
                    ):
                        merge_staging_insert_only(
                            missing_staging,
                            missing_production,
                            run_id=RUN_ID,
                            backup_path=self.backup_path,
                            expected_production_sha256="0" * 64,
                            expected_plan_sha256=None,
                            authorized=authorized,
                        )
                self.assertFalse(missing_staging.exists())
                self.assertFalse(missing_production.exists())
                self.assertFalse(self.backup_path.exists())

    def test_authorized_missing_or_invalid_expected_plan_hash_touches_no_path(self) -> None:
        missing_staging = self.root / "missing-staging.sqlite3"
        missing_production = self.root / "missing-production.sqlite3"
        for expected_plan_sha256 in (None, "", "A" * 64, 1):
            with self.subTest(expected_plan_sha256=expected_plan_sha256), patch.dict(
                os.environ,
                {"REDDIT_VOC_ENABLE_PRODUCTION_MERGE": "1"},
                clear=False,
            ), patch.object(
                merge_module,
                "_database_file",
                side_effect=AssertionError("path touched before plan hash admission"),
            ), patch.object(
                merge_module,
                "_sha256_file",
                side_effect=AssertionError("hash touched before plan hash admission"),
            ):
                with self.assertRaisesRegex(
                    MergePreconditionError,
                    r"\Aexpected_plan_sha256_invalid\Z",
                ):
                    merge_staging_insert_only(
                        missing_staging,
                        missing_production,
                        run_id=RUN_ID,
                        backup_path=self.backup_path,
                        expected_production_sha256="0" * 64,
                        expected_plan_sha256=expected_plan_sha256,
                        authorized=True,
                    )
        self.assertFalse(missing_staging.exists())
        self.assertFalse(missing_production.exists())
        self.assertFalse(self.backup_path.exists())

    def test_wrong_expected_plan_hash_fails_before_backup_or_write(self) -> None:
        self._add_post("post-one")
        production_before = self._sha(self.production_path)
        reviewed_plan_sha256 = self._plan_sha()
        wrong_plan_sha256 = (
            "f" * 64 if reviewed_plan_sha256 != "f" * 64 else "e" * 64
        )
        with patch.dict(
            os.environ,
            {"REDDIT_VOC_ENABLE_PRODUCTION_MERGE": "1"},
            clear=False,
        ), patch.object(
            merge_module,
            "_create_sqlite_backup",
            side_effect=AssertionError("backup created before plan hash admission"),
        ):
            with self.assertRaisesRegex(
                MergePreconditionError,
                r"\Amerge_plan_sha256_mismatch\Z",
            ):
                merge_staging_insert_only(
                    self.staging_path,
                    self.production_path,
                    run_id=RUN_ID,
                    backup_path=self.backup_path,
                    expected_production_sha256=production_before,
                    expected_plan_sha256=wrong_plan_sha256,
                    authorized=True,
                )
        self.assertEqual(self._sha(self.production_path), production_before)
        self.assertFalse(self.backup_path.exists())

    def test_run_exact_is_allowed_but_mismatch_is_fatal(self) -> None:
        self._add_post("post-one")
        self._copy_staging_row("runs", "run_id", RUN_ID)
        exact = plan_insert_only_merge(
            self.staging_path, self.production_path, run_id=RUN_ID
        )
        self.assertEqual(exact["run_action"], "exact")
        self.assertEqual(exact["approved_counts"]["runs_to_insert"], 0)
        with sqlite3.connect(self.production_path) as conn:
            conn.execute(
                "UPDATE runs SET window_end_utc=? WHERE run_id=?",
                ("2026-07-10T16:00:00+00:00", RUN_ID),
            )
        with self.assertRaisesRegex(
            MergePreconditionError, r"\Aproduction_run_mismatch\Z"
        ):
            plan_insert_only_merge(
                self.staging_path, self.production_path, run_id=RUN_ID
            )

    def test_existing_post_skips_whole_closure_and_unreferenced_raw(self) -> None:
        self._add_post("post-one")
        self._copy_staging_row("reddit_threads", "post_id", "post-one")
        plan = plan_insert_only_merge(
            self.staging_path, self.production_path, run_id=RUN_ID
        )
        self.assertEqual(plan["skipped_post_count"], 1)
        self.assertEqual(plan["approved_counts"]["reddit_threads_to_insert"], 0)
        self.assertEqual(plan["approved_counts"]["reddit_comments_to_insert"], 0)
        self.assertEqual(plan["approved_counts"]["analysis_results_to_insert"], 0)
        self.assertEqual(plan["approved_counts"]["raw_captures_to_insert"], 0)
        self.assertEqual(plan["conflict_counts"]["post_primary_key_conflict"], 1)

    def test_raw_exact_is_reused(self) -> None:
        post_capture, comment_capture = self._add_post("post-one")
        self._copy_staging_row(
            "raw_captures", "raw_capture_id", post_capture.raw_capture_id
        )
        self._copy_staging_row(
            "raw_captures", "raw_capture_id", comment_capture.raw_capture_id
        )
        plan = plan_insert_only_merge(
            self.staging_path, self.production_path, run_id=RUN_ID
        )
        self.assertEqual(plan["approved_counts"]["raw_captures_exact"], 2)
        self.assertEqual(plan["approved_counts"]["raw_captures_to_insert"], 0)
        summary = self._merge()
        self.assertEqual(summary.reused_raw_captures, 2)
        self.assertEqual(summary.inserted_raw_captures, 0)
        self.assertEqual(summary.inserted_threads, 1)

    def test_raw_primary_or_unique_conflict_skips_whole_post(self) -> None:
        for conflict_kind in ("primary", "unique"):
            with self.subTest(conflict_kind=conflict_kind):
                with TemporaryDirectory() as isolated:
                    staging_path = Path(isolated) / "staging.sqlite3"
                    production_path = Path(isolated) / "production.sqlite3"
                    staging = BackfillStore(staging_path)
                    staging.migrate()
                    _prepare_merge_staging(staging)
                    production = VocStore(production_path)
                    production.migrate()
                    old_staging = self.staging
                    old_staging_path = self.staging_path
                    old_production_path = self.production_path
                    self.staging = staging
                    self.staging_path = staging_path
                    self.production_path = production_path
                    try:
                        post_capture, _ = self._add_post("post-one")
                        row = dict(
                            self._row(
                                staging_path,
                                "raw_captures",
                                "raw_capture_id",
                                post_capture.raw_capture_id,
                            )
                        )
                        if conflict_kind == "primary":
                            row["source_url"] = "https://different.invalid/raw"
                        else:
                            row["raw_capture_id"] = "different-existing-raw"
                        columns = tuple(row)
                        with sqlite3.connect(production_path) as conn:
                            conn.execute(
                                f"INSERT INTO raw_captures({', '.join(columns)}) "
                                f"VALUES ({', '.join('?' for _ in columns)})",
                                tuple(row[column] for column in columns),
                            )
                        plan = plan_insert_only_merge(
                            staging_path, production_path, run_id=RUN_ID
                        )
                    finally:
                        self.staging = old_staging
                        self.staging_path = old_staging_path
                        self.production_path = old_production_path
                self.assertEqual(plan["skipped_post_count"], 1)
                expected = (
                    "raw_primary_key_conflict"
                    if conflict_kind == "primary"
                    else "raw_unique_conflict"
                )
                self.assertEqual(plan["conflict_counts"][expected], 1)
                self.assertEqual(plan["approved_counts"]["reddit_threads_to_insert"], 0)

    def test_comment_or_analysis_primary_key_conflict_skips_whole_post(self) -> None:
        for table, key, identity, expected_kind in (
            (
                "reddit_comments",
                "comment_id",
                "comment-post-one",
                "comment_primary_key_conflict",
            ),
            (
                "analysis_results",
                "analysis_id",
                "analysis-post-post-one",
                "analysis_primary_key_conflict",
            ),
        ):
            with self.subTest(table=table):
                with TemporaryDirectory() as isolated:
                    staging_path = Path(isolated) / "staging.sqlite3"
                    production_path = Path(isolated) / "production.sqlite3"
                    staging = BackfillStore(staging_path)
                    staging.migrate()
                    _prepare_merge_staging(staging)
                    VocStore(production_path).migrate()
                    old_staging = self.staging
                    old_staging_path = self.staging_path
                    old_production_path = self.production_path
                    self.staging = staging
                    self.staging_path = staging_path
                    self.production_path = production_path
                    try:
                        self._add_post("post-one")
                        self._copy_staging_row(table, key, identity)
                        plan = plan_insert_only_merge(
                            staging_path, production_path, run_id=RUN_ID
                        )
                    finally:
                        self.staging = old_staging
                        self.staging_path = old_staging_path
                        self.production_path = old_production_path
                self.assertEqual(plan["skipped_post_count"], 1)
                self.assertEqual(plan["conflict_counts"][expected_kind], 1)
                self.assertEqual(plan["approved_counts"]["raw_captures_to_insert"], 0)

    def test_shared_raw_is_deduplicated_or_conflict_propagates(self) -> None:
        shared = _capture(
            "shared-post-raw", source_suffix="shared", payload_char="c"
        )
        self._add_post("post-one", shared_post_capture=shared)
        self._add_post("post-two", shared_post_capture=shared)
        clean = plan_insert_only_merge(
            self.staging_path, self.production_path, run_id=RUN_ID
        )
        self.assertEqual(clean["approved_counts"]["reddit_threads_to_insert"], 2)
        self.assertEqual(clean["approved_counts"]["raw_captures_to_insert"], 3)
        self._copy_staging_row(
            "raw_captures",
            "raw_capture_id",
            shared.raw_capture_id,
            overrides={"source_url": "https://different.invalid/shared"},
        )
        conflict = plan_insert_only_merge(
            self.staging_path, self.production_path, run_id=RUN_ID
        )
        self.assertEqual(conflict["skipped_post_count"], 2)
        self.assertEqual(conflict["conflict_counts"]["raw_primary_key_conflict"], 2)
        self.assertEqual(conflict["approved_counts"]["reddit_threads_to_insert"], 0)

    def test_intrinsic_staging_parity_corruption_is_fatal_and_secret_free(self) -> None:
        self._add_post("secret-post-identifier")
        with sqlite3.connect(self.staging_path) as conn:
            conn.execute(
                "UPDATE reddit_threads SET parsed_comment_count=9 WHERE post_id=?",
                ("secret-post-identifier",),
            )
        with self.assertRaises(MergePreconditionError) as captured:
            plan_insert_only_merge(
                self.staging_path, self.production_path, run_id=RUN_ID
            )
        self.assertEqual(captured.exception.reason, "staging_comment_parity_invalid")
        self.assertNotIn("secret-post-identifier", str(captured.exception))

    def test_intrinsic_staging_corruption_matrix_is_fatal(self) -> None:
        cases = (
            ("missing_raw", "staging_foreign_key_check_failed"),
            ("orphan_comment", "staging_foreign_key_check_failed"),
            ("cross_run_comment", "staging_foreign_key_check_failed"),
            ("duplicate_analysis", "staging_analysis_parity_invalid"),
            ("unknown_source", "staging_analysis_lineage_invalid"),
            ("secret_raw", "staging_secret_boundary_invalid"),
            (
                "provider_analysis",
                "staging_analysis_provider_boundary_invalid",
            ),
            ("target_delivery", "staging_delivery_not_empty"),
        )
        for case, expected_reason in cases:
            with self.subTest(case=case), TemporaryDirectory() as isolated:
                staging_path = Path(isolated) / "staging.sqlite3"
                production_path = Path(isolated) / "production.sqlite3"
                staging = BackfillStore(staging_path)
                staging.migrate()
                _prepare_merge_staging(staging)
                VocStore(production_path).migrate()
                old_staging = self.staging
                old_staging_path = self.staging_path
                old_production_path = self.production_path
                self.staging = staging
                self.staging_path = staging_path
                self.production_path = production_path
                try:
                    post_capture, _ = self._add_post("post-one")
                finally:
                    self.staging = old_staging
                    self.staging_path = old_staging_path
                    self.production_path = old_production_path

                with sqlite3.connect(staging_path) as conn:
                    if case == "missing_raw":
                        conn.execute("PRAGMA foreign_keys=OFF")
                        conn.execute(
                            "DELETE FROM raw_captures WHERE raw_capture_id=?",
                            (post_capture.raw_capture_id,),
                        )
                    elif case == "orphan_comment":
                        conn.execute("PRAGMA foreign_keys=OFF")
                        conn.execute(
                            "UPDATE reddit_comments SET post_id='missing-post' "
                            "WHERE comment_id='comment-post-one'"
                        )
                    elif case == "cross_run_comment":
                        conn.execute("PRAGMA foreign_keys=OFF")
                        conn.execute(
                            "UPDATE reddit_comments SET run_id='other-run' "
                            "WHERE comment_id='comment-post-one'"
                        )
                        conn.execute(
                            "UPDATE analysis_results SET run_id='other-run' "
                            "WHERE analysis_id='analysis-comment-post-one'"
                        )
                        conn.execute(
                            "UPDATE reddit_threads SET parsed_comment_count=0 "
                            "WHERE post_id='post-one'"
                        )
                    elif case == "duplicate_analysis":
                        conn.execute(
                            "INSERT INTO analysis_results("
                            "analysis_id, run_id, source_type, source_id, "
                            "analysis_version, sentiment_label, sentiment_score, "
                            "topic, severity, confidence, pain_points, provider_call"
                            ") SELECT 'duplicate-post-analysis', run_id, source_type, "
                            "source_id, analysis_version, sentiment_label, "
                            "sentiment_score, topic, severity, confidence, "
                            "pain_points, provider_call FROM analysis_results "
                            "WHERE analysis_id='analysis-post-post-one'"
                        )
                    elif case == "unknown_source":
                        conn.execute("PRAGMA ignore_check_constraints=ON")
                        conn.execute(
                            "UPDATE analysis_results SET source_type='unknown' "
                            "WHERE analysis_id='analysis-post-post-one'"
                        )
                    elif case == "secret_raw":
                        conn.execute(
                            "UPDATE raw_captures SET secrets_written=1 "
                            "WHERE raw_capture_id=?",
                            (post_capture.raw_capture_id,),
                        )
                    elif case == "provider_analysis":
                        conn.execute(
                            "UPDATE analysis_results SET provider_call=1 "
                            "WHERE analysis_id='analysis-post-post-one'"
                        )
                    elif case == "target_delivery":
                        conn.execute(
                            "INSERT INTO delivery_previews("
                            "delivery_id, run_id, channel, mode, status, "
                            "message_hash, artifact_paths, live_send"
                            ") VALUES ('delivery-fixture', ?, 'fixture', 'fixture', "
                            "'fixture', ?, '[]', 0)",
                            (RUN_ID, "0" * 64),
                        )
                with self.assertRaises(MergePreconditionError) as captured:
                    plan_insert_only_merge(
                        staging_path, production_path, run_id=RUN_ID
                    )
                self.assertEqual(captured.exception.reason, expected_reason)

    def test_hash_backup_and_alias_preconditions_fail_before_transaction(self) -> None:
        self._add_post("post-one")
        with patch.dict(
            os.environ, {"REDDIT_VOC_ENABLE_PRODUCTION_MERGE": "1"}, clear=False
        ):
            with self.assertRaisesRegex(
                MergePreconditionError, r"\Aproduction_sha256_mismatch\Z"
            ):
                merge_staging_insert_only(
                    self.staging_path,
                    self.production_path,
                    run_id=RUN_ID,
                    backup_path=self.backup_path,
                    expected_production_sha256="0" * 64,
                    expected_plan_sha256=self._plan_sha(),
                    authorized=True,
                )
            self.backup_path.write_bytes(b"owner backup")
            with self.assertRaisesRegex(
                MergePreconditionError, r"\Abackup_path_exists\Z"
            ):
                merge_staging_insert_only(
                    self.staging_path,
                    self.production_path,
                    run_id=RUN_ID,
                    backup_path=self.backup_path,
                    expected_production_sha256=self._sha(self.production_path),
                    expected_plan_sha256=self._plan_sha(),
                    authorized=True,
                )
        self.assertEqual(self.backup_path.read_bytes(), b"owner backup")
        with self.assertRaisesRegex(
            MergePreconditionError, r"\Adatabase_path_alias\Z"
        ):
            plan_insert_only_merge(
                self.staging_path, self.staging_path, run_id=RUN_ID
            )

    def test_symlink_schema_drift_and_sidecar_fail_closed(self) -> None:
        link = self.root / "staging-link.sqlite3"
        link.symlink_to(self.staging_path)
        with self.assertRaisesRegex(
            MergePreconditionError, r"\Adatabase_path_invalid\Z"
        ):
            plan_insert_only_merge(link, self.production_path, run_id=RUN_ID)
        sidecar = Path(str(self.staging_path) + "-wal")
        sidecar.write_bytes(b"not a sqlite wal")
        with self.assertRaisesRegex(
            MergePreconditionError, r"\Asqlite_sidecar_present\Z"
        ):
            plan_insert_only_merge(
                self.staging_path, self.production_path, run_id=RUN_ID
            )
        sidecar.unlink()
        dangling_sidecar = Path(str(self.staging_path) + "-journal")
        dangling_sidecar.symlink_to(self.root / "missing-journal-target")
        with self.assertRaisesRegex(
            MergePreconditionError, r"\Asqlite_sidecar_present\Z"
        ):
            plan_insert_only_merge(
                self.staging_path, self.production_path, run_id=RUN_ID
            )
        dangling_sidecar.unlink()
        with sqlite3.connect(self.production_path) as conn:
            conn.execute(
                "CREATE UNIQUE INDEX extra_raw_unique "
                "ON raw_captures(run_id, source_method)"
            )
        with self.assertRaisesRegex(
            MergePreconditionError, r"\Adatabase_unique_index_mismatch\Z"
        ):
            plan_insert_only_merge(
                self.staging_path, self.production_path, run_id=RUN_ID
            )

    def test_partial_unique_generated_column_and_trigger_schema_drift_fail(self) -> None:
        partial_path = self.root / "partial-index.sqlite3"
        unique_clause = (
            "    secrets_written INTEGER NOT NULL DEFAULT 0,\n"
            "    UNIQUE(run_id, source_method, source_url, raw_payload_hash)\n"
        )
        schema_without_raw_unique = merge_module.PRODUCTION_SCHEMA.replace(
            unique_clause,
            "    secrets_written INTEGER NOT NULL DEFAULT 0\n",
            1,
        )
        self.assertNotEqual(
            schema_without_raw_unique, merge_module.PRODUCTION_SCHEMA
        )
        with sqlite3.connect(partial_path) as conn:
            conn.executescript(schema_without_raw_unique)
            conn.execute(
                "CREATE UNIQUE INDEX partial_raw_unique ON raw_captures("
                "source_method, source_url, raw_payload_hash) WHERE 0"
            )
        with self.assertRaisesRegex(
            MergePreconditionError, r"\Adatabase_unique_index_mismatch\Z"
        ):
            plan_insert_only_merge(
                self.staging_path, partial_path, run_id=RUN_ID
            )

        generated_path = self.root / "generated-column.sqlite3"
        generated_schema = merge_module.PRODUCTION_SCHEMA.replace(
            "    live_send INTEGER NOT NULL DEFAULT 0\n);",
            "    live_send INTEGER NOT NULL DEFAULT 0,\n"
            "    hidden_generated TEXT GENERATED ALWAYS AS (run_id) VIRTUAL\n);",
            1,
        )
        with sqlite3.connect(generated_path) as conn:
            conn.executescript(generated_schema)
        with self.assertRaisesRegex(
            MergePreconditionError, r"\Adatabase_schema_mismatch\Z"
        ):
            plan_insert_only_merge(
                self.staging_path, generated_path, run_id=RUN_ID
            )

        with sqlite3.connect(self.production_path) as conn:
            conn.execute(
                "CREATE TRIGGER unexpected_raw_trigger "
                "AFTER INSERT ON raw_captures BEGIN SELECT 1; END"
            )
        with self.assertRaisesRegex(
            MergePreconditionError, r"\Adatabase_trigger_not_allowed\Z"
        ):
            plan_insert_only_merge(
                self.staging_path, self.production_path, run_id=RUN_ID
            )

    def test_check_definition_drift_and_bypassed_status_are_rejected(self) -> None:
        drifted_staging = self.root / "drifted-check.sqlite3"
        status_check = (
            "    status TEXT NOT NULL CHECK (\n"
            "        status IN ('prepared', 'seed_complete', 'running', 'partial',\n"
            "                   'success', 'blocked', 'failed')\n"
            "    ),"
        )
        drifted_schema = merge_module.STAGING_SCHEMA.replace(
            status_check, "    status TEXT NOT NULL,", 1
        )
        self.assertNotEqual(drifted_schema, merge_module.STAGING_SCHEMA)
        with sqlite3.connect(drifted_staging) as conn:
            conn.executescript(drifted_schema)
        drifted_store = BackfillStore(drifted_staging)
        invalid_manifest = _manifest()
        object.__setattr__(invalid_manifest, "status", "invalid_status")
        drifted_store.create_manifest(invalid_manifest)
        with self.assertRaisesRegex(
            MergePreconditionError,
            r"\Adatabase_table_definition_mismatch\Z",
        ):
            plan_insert_only_merge(
                drifted_staging, self.production_path, run_id=RUN_ID
            )

        with sqlite3.connect(self.staging_path) as conn:
            conn.execute("PRAGMA ignore_check_constraints=ON")
            conn.execute(
                "UPDATE runs SET status='invalid_status' WHERE run_id=?", (RUN_ID,)
            )
            conn.execute(
                "UPDATE backfill_manifests SET status='invalid_status' WHERE run_id=?",
                (RUN_ID,),
            )
        with self.assertRaisesRegex(
            MergePreconditionError, r"\Astaging_run_manifest_mismatch\Z"
        ):
            plan_insert_only_merge(
                self.staging_path, self.production_path, run_id=RUN_ID
            )

    def test_actual_table_delta_catches_unplanned_helper_write(self) -> None:
        self._add_post("post-one")
        production_before = self._sha(self.production_path)
        real_insert = merge_module._insert_raw_captures

        def insert_extra(
            conn: sqlite3.Connection, identities: tuple[str, ...]
        ) -> int:
            inserted = real_insert(conn, identities)
            conn.execute(
                "INSERT INTO main.raw_captures("
                "raw_capture_id, run_id, source_method, source_url, captured_at_utc, "
                "auth_boundary, raw_payload_hash, payload_format, browser_status, "
                "http_status, selector_version, blocked_reason, secrets_written"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "unexpected-shadow-raw",
                    RUN_ID,
                    "fixture-shadow",
                    "https://shadow.invalid",
                    NOW.isoformat(),
                    "public",
                    "sha256:" + "f" * 64,
                    "json",
                    "ok",
                    200,
                    None,
                    None,
                    0,
                ),
            )
            return inserted

        with patch.dict(
            os.environ, {"REDDIT_VOC_ENABLE_PRODUCTION_MERGE": "1"}, clear=False
        ), patch.object(
            merge_module, "_insert_raw_captures", side_effect=insert_extra
        ):
            with self.assertRaisesRegex(
                MergeInvariantError, r"\Ainsert_delta_mismatch\Z"
            ):
                merge_staging_insert_only(
                    self.staging_path,
                    self.production_path,
                    run_id=RUN_ID,
                    backup_path=self.backup_path,
                    expected_production_sha256=production_before,
                    expected_plan_sha256=self._plan_sha(),
                    authorized=True,
                )
        self.assertEqual(self._sha(self.production_path), production_before)

    def test_unrelated_legacy_orphan_does_not_block_approved_closure(self) -> None:
        self._add_post("post-one")
        self._copy_staging_row("runs", "run_id", RUN_ID)
        self._copy_staging_row(
            "reddit_threads",
            "post_id",
            "post-one",
            overrides={
                "post_id": "legacy-orphan-post",
                "raw_capture_id": "missing-legacy-raw",
                "source_url": "https://legacy.invalid/orphan",
            },
        )
        summary = self._merge()
        self.assertEqual(summary.inserted_threads, 1)
        with sqlite3.connect(self.production_path) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM reddit_threads").fetchone()[0],
                2,
            )

    def test_postcommit_delivery_race_requires_review(self) -> None:
        self._add_post("post-one")
        production_before = self._sha(self.production_path)
        real_postcheck = merge_module._verify_postcommit

        def insert_delivery_then_check(
            path: Path, preflight: object, backup: object
        ) -> tuple[int, str]:
            with sqlite3.connect(path) as conn:
                conn.execute(
                    "INSERT INTO delivery_previews("
                    "delivery_id, run_id, channel, mode, status, message_hash, "
                    "artifact_paths, live_send) VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
                    (
                        "external-delivery",
                        RUN_ID,
                        "fixture",
                        "fixture",
                        "fixture",
                        "0" * 64,
                        "[]",
                    ),
                )
            return real_postcheck(path, preflight, backup)

        with patch.dict(
            os.environ, {"REDDIT_VOC_ENABLE_PRODUCTION_MERGE": "1"}, clear=False
        ), patch.object(
            merge_module, "_verify_postcommit", side_effect=insert_delivery_then_check
        ):
            with self.assertRaisesRegex(
                MergeCommittedReviewError, r"\Acommitted_requires_review\Z"
            ):
                merge_staging_insert_only(
                    self.staging_path,
                    self.production_path,
                    run_id=RUN_ID,
                    backup_path=self.backup_path,
                    expected_production_sha256=production_before,
                    expected_plan_sha256=self._plan_sha(),
                    authorized=True,
                )
        self.assertTrue(self.backup_path.is_file())

    def test_connection_close_fault_after_commit_requires_review(self) -> None:
        self._add_post("post-one")
        production_before = self._sha(self.production_path)
        real_open = merge_module._open_merge_database

        class CloseFaultConnection:
            def __init__(self, connection: sqlite3.Connection) -> None:
                self.connection = connection

            def __getattr__(self, name: str) -> object:
                return getattr(self.connection, name)

            def close(self) -> None:
                self.connection.close()
                raise sqlite3.OperationalError("secret-close-detail")

        def open_with_close_fault(path: Path) -> CloseFaultConnection:
            return CloseFaultConnection(real_open(path))

        with patch.dict(
            os.environ, {"REDDIT_VOC_ENABLE_PRODUCTION_MERGE": "1"}, clear=False
        ), patch.object(
            merge_module, "_open_merge_database", side_effect=open_with_close_fault
        ):
            with self.assertRaisesRegex(
                MergeCommittedReviewError, r"\Acommitted_requires_review\Z"
            ) as captured:
                merge_staging_insert_only(
                    self.staging_path,
                    self.production_path,
                    run_id=RUN_ID,
                    backup_path=self.backup_path,
                    expected_production_sha256=production_before,
                    expected_plan_sha256=self._plan_sha(),
                    authorized=True,
                )
        self.assertNotIn("secret", str(captured.exception))
        with sqlite3.connect(self.production_path) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM reddit_threads").fetchone()[0],
                1,
            )
        self.assertTrue(self.backup_path.is_file())

    def test_backup_allocation_and_fsync_errors_are_secret_free(self) -> None:
        self._add_post("post-one")
        production_before = self._sha(self.production_path)
        with patch.dict(
            os.environ, {"REDDIT_VOC_ENABLE_PRODUCTION_MERGE": "1"}, clear=False
        ), patch.object(
            merge_module.tempfile,
            "NamedTemporaryFile",
            side_effect=OSError("secret-backup-path-leak"),
        ):
            with self.assertRaisesRegex(
                MergePreconditionError, r"\Abackup_creation_failed\Z"
            ) as captured:
                merge_staging_insert_only(
                    self.staging_path,
                    self.production_path,
                    run_id=RUN_ID,
                    backup_path=self.backup_path,
                    expected_production_sha256=production_before,
                    expected_plan_sha256=self._plan_sha(),
                    authorized=True,
                )
        self.assertNotIn("secret", str(captured.exception))
        self.assertFalse(self.backup_path.exists())

        with patch.dict(
            os.environ, {"REDDIT_VOC_ENABLE_PRODUCTION_MERGE": "1"}, clear=False
        ), patch.object(
            merge_module,
            "_verify_backup",
            side_effect=OSError("secret-fsync-path-leak"),
        ):
            with self.assertRaisesRegex(
                MergePreconditionError, r"\Abackup_verification_failed\Z"
            ) as captured:
                merge_staging_insert_only(
                    self.staging_path,
                    self.production_path,
                    run_id=RUN_ID,
                    backup_path=self.backup_path,
                    expected_production_sha256=production_before,
                    expected_plan_sha256=self._plan_sha(),
                    authorized=True,
                )
        self.assertNotIn("secret", str(captured.exception))
        self.assertTrue(self.backup_path.is_file())

    def test_failure_in_each_insert_phase_rolls_back_and_preserves_backup(self) -> None:
        for seam in (
            "_insert_run",
            "_insert_raw_captures",
            "_insert_threads",
            "_insert_comments",
            "_insert_analyses",
        ):
            with self.subTest(seam=seam), TemporaryDirectory() as isolated:
                staging_path = Path(isolated) / "staging.sqlite3"
                production_path = Path(isolated) / "production.sqlite3"
                backup_path = Path(isolated) / "production.backup.sqlite3"
                staging = BackfillStore(staging_path)
                staging.migrate()
                _prepare_merge_staging(staging)
                VocStore(production_path).migrate()
                old_staging = self.staging
                old_staging_path = self.staging_path
                old_production_path = self.production_path
                self.staging = staging
                self.staging_path = staging_path
                self.production_path = production_path
                try:
                    self._add_post("post-one")
                finally:
                    self.staging = old_staging
                    self.staging_path = old_staging_path
                    self.production_path = old_production_path
                production_before = self._sha(production_path)
                with patch.dict(
                    os.environ,
                    {"REDDIT_VOC_ENABLE_PRODUCTION_MERGE": "1"},
                    clear=False,
                ), patch.object(
                    merge_module,
                    seam,
                    side_effect=RuntimeError("secret injected detail"),
                ):
                    with self.assertRaisesRegex(
                        MergeInvariantError, r"\Amerge_transaction_failed\Z"
                    ):
                        merge_staging_insert_only(
                            staging_path,
                            production_path,
                            run_id=RUN_ID,
                            backup_path=backup_path,
                            expected_production_sha256=production_before,
                            expected_plan_sha256=self._plan_sha(
                                staging_path, production_path
                            ),
                            authorized=True,
                        )
                self.assertEqual(self._sha(production_path), production_before)
                self.assertTrue(backup_path.is_file())
                with sqlite3.connect(production_path) as conn:
                    counts = tuple(
                        conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                        for table in (
                            "runs",
                            "raw_captures",
                            "reddit_threads",
                            "reddit_comments",
                            "analysis_results",
                        )
                    )
                self.assertEqual(counts, (0, 0, 0, 0, 0))

    def test_backup_precedes_begin_and_toctou_drift_rolls_back(self) -> None:
        self._add_post("post-one")
        production_before = self._sha(self.production_path)
        events: list[str] = []
        original_backup = merge_module._create_sqlite_backup
        original_verify = merge_module._verify_backup
        original_begin = merge_module._begin_immediate

        def traced_backup(production_path: Path, backup_path: Path) -> object:
            result = original_backup(production_path, backup_path)
            events.append("backup")
            return result

        def mutate_then_begin(conn: sqlite3.Connection) -> None:
            self.assertTrue(self.backup_path.is_file())
            events.append("begin")
            with sqlite3.connect(self.staging_path) as mutator:
                mutator.execute(
                    "UPDATE reddit_threads SET title='drifted' WHERE post_id='post-one'"
                )
            original_begin(conn)

        def traced_verify(
            published: object, preflight: object
        ) -> object:
            result = original_verify(published, preflight)
            events.append("verify")
            return result

        with patch.dict(
            os.environ, {"REDDIT_VOC_ENABLE_PRODUCTION_MERGE": "1"}, clear=False
        ), patch.object(
            merge_module, "_create_sqlite_backup", side_effect=traced_backup
        ), patch.object(
            merge_module, "_verify_backup", side_effect=traced_verify
        ), patch.object(
            merge_module, "_begin_immediate", side_effect=mutate_then_begin
        ):
            with self.assertRaisesRegex(
                MergePreconditionError, r"\Adatabase_snapshot_changed\Z"
            ):
                merge_staging_insert_only(
                    self.staging_path,
                    self.production_path,
                    run_id=RUN_ID,
                    backup_path=self.backup_path,
                    expected_production_sha256=production_before,
                    expected_plan_sha256=self._plan_sha(),
                    authorized=True,
                )
        self.assertEqual(events, ["backup", "verify", "begin"])
        self.assertEqual(self._sha(self.production_path), production_before)
        self.assertTrue(self.backup_path.is_file())

    def test_locked_replan_must_match_owner_hash_even_if_preflight_object_drifts(
        self,
    ) -> None:
        self._add_post("post-one")
        production_before = self._sha(self.production_path)
        expected_plan_sha256 = self._plan_sha()
        forged_plan_sha256 = (
            "f" * 64 if expected_plan_sha256 != "f" * 64 else "e" * 64
        )
        real_build = merge_module._build_internal_plan
        preflight_results: list[object] = []

        def forge_matching_preflight_and_locked_plans(
            *args: object, **kwargs: object
        ) -> object:
            result = real_build(*args, **kwargs)
            if not preflight_results:
                preflight_results.append(result)
                return result
            preflight = preflight_results[0]
            preflight.public["plan_sha256"] = forged_plan_sha256
            locked_public = dict(result.public)
            locked_public["plan_sha256"] = forged_plan_sha256
            return replace(
                result,
                public=locked_public,
                internal_sha256=preflight.internal_sha256,
            )

        with patch.dict(
            os.environ,
            {"REDDIT_VOC_ENABLE_PRODUCTION_MERGE": "1"},
            clear=False,
        ), patch.object(
            merge_module,
            "_build_internal_plan",
            side_effect=forge_matching_preflight_and_locked_plans,
        ):
            with self.assertRaisesRegex(
                MergePreconditionError,
                r"\Amerge_plan_sha256_mismatch\Z",
            ):
                merge_staging_insert_only(
                    self.staging_path,
                    self.production_path,
                    run_id=RUN_ID,
                    backup_path=self.backup_path,
                    expected_production_sha256=production_before,
                    expected_plan_sha256=expected_plan_sha256,
                    authorized=True,
                )
        self.assertEqual(self._sha(self.production_path), production_before)
        self.assertTrue(self.backup_path.is_file())

    def test_backup_publication_race_preserves_competing_target(self) -> None:
        self._add_post("post-one")
        production_before = self._sha(self.production_path)
        real_link = os.link

        def competing_link(source: Path, target: Path) -> None:
            Path(target).write_bytes(b"owner competing backup")
            real_link(source, target)

        with patch.dict(
            os.environ, {"REDDIT_VOC_ENABLE_PRODUCTION_MERGE": "1"}, clear=False
        ), patch.object(merge_module.os, "link", side_effect=competing_link):
            with self.assertRaisesRegex(
                MergePreconditionError, r"\Abackup_path_exists\Z"
            ):
                merge_staging_insert_only(
                    self.staging_path,
                    self.production_path,
                    run_id=RUN_ID,
                    backup_path=self.backup_path,
                    expected_production_sha256=production_before,
                    expected_plan_sha256=self._plan_sha(),
                    authorized=True,
                )
        self.assertEqual(self.backup_path.read_bytes(), b"owner competing backup")
        self.assertEqual(self._sha(self.production_path), production_before)

    def test_backup_replaced_with_production_hardlink_fails_before_write(self) -> None:
        self._add_post("post-one")
        production_before = self._sha(self.production_path)
        real_link = os.link

        def replace_with_production(source: Path, target: Path) -> None:
            real_link(source, target)
            Path(target).unlink()
            real_link(self.production_path, target)

        with patch.dict(
            os.environ, {"REDDIT_VOC_ENABLE_PRODUCTION_MERGE": "1"}, clear=False
        ), patch.object(
            merge_module.os, "link", side_effect=replace_with_production
        ):
            with self.assertRaisesRegex(
                MergePreconditionError, r"\Adatabase_path_alias\Z"
            ):
                merge_staging_insert_only(
                    self.staging_path,
                    self.production_path,
                    run_id=RUN_ID,
                    backup_path=self.backup_path,
                    expected_production_sha256=production_before,
                    expected_plan_sha256=self._plan_sha(),
                    authorized=True,
                )
        self.assertTrue(os.path.samefile(self.backup_path, self.production_path))
        self.assertEqual(self._sha(self.production_path), production_before)

    def test_write_path_uses_only_explicit_insert_select(self) -> None:
        source = inspect.getsource(merge_module._insert_selected_rows).upper()
        self.assertIn("INSERT INTO MAIN.", source)
        self.assertIn("SELECT", source)
        self.assertIn("NOT EXISTS", source)
        self.assertNotIn("INSERT OR", source)
        for forbidden in (" REPLACE ", " UPDATE ", " DELETE ", " UPSERT "):
            self.assertNotIn(forbidden, source)

    def test_second_merge_is_idempotent_and_summary_contract_is_frozen(self) -> None:
        self._add_post("post-one")
        first = self._merge()
        second_backup = self.root / "production.before-second.sqlite3"
        with patch.dict(
            os.environ, {"REDDIT_VOC_ENABLE_PRODUCTION_MERGE": "1"}, clear=False
        ):
            second = merge_staging_insert_only(
                self.staging_path,
                self.production_path,
                run_id=RUN_ID,
                backup_path=second_backup,
                expected_production_sha256=self._sha(self.production_path),
                expected_plan_sha256=self._plan_sha(),
                authorized=True,
            )
        self.assertEqual(
            tuple(field.name for field in fields(MergeSummary)),
            (
                "schema_version",
                "run_id",
                "status",
                "stop_reason",
                "authorized",
                "production_write",
                "plan_sha256",
                "staging_sha256",
                "expected_production_sha256",
                "premerge_production_sha256",
                "backup_sha256",
                "postmerge_production_sha256",
                "planned_runs",
                "planned_raw_captures",
                "reused_raw_captures",
                "planned_threads",
                "planned_comments",
                "planned_analyses",
                "inserted_runs",
                "inserted_raw_captures",
                "inserted_threads",
                "inserted_comments",
                "inserted_analyses",
                "skipped_posts",
                "conflict_count",
                "delivery_before",
                "delivery_after",
                "delivery_delta",
                "updated",
                "deleted",
                "provider_attempt_made",
                "live_send",
            ),
        )
        self.assertEqual(first.inserted_threads, 1)
        self.assertEqual(
            (
                second.inserted_runs,
                second.inserted_raw_captures,
                second.inserted_threads,
                second.inserted_comments,
                second.inserted_analyses,
            ),
            (0, 0, 0, 0, 0),
        )
        self.assertEqual(second.skipped_posts, 1)


if __name__ == "__main__":
    unittest.main()
