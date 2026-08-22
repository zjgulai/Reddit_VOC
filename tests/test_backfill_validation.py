from __future__ import annotations

import ast
import builtins
from contextlib import ExitStack
from dataclasses import asdict, fields, replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import stat
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import reddit_voc.backfill_validation as backfill_validation_module
from reddit_voc.backfill_archive import PrivateRawArchive
from reddit_voc.adapters import BrowserJsonAdapter
from reddit_voc.analyzer import analyze_text
from reddit_voc.backfill_models import (
    AnalysisRow,
    BackfillCheckpoint,
    BackfillManifest,
    SeedBaseline,
)
from reddit_voc.backfill_seed import import_seed_directory
from reddit_voc.backfill_storage import BackfillStore
from reddit_voc.backfill_validation import (
    replay_from_archive,
    required_lanes_sha256,
    validate_backfill,
)
from reddit_voc.keywords import keyword_rules_sha256
from reddit_voc.models import RawCapture
from reddit_voc.search_config import DEFAULT_TIKHUB_SEARCH_TERMS
from reddit_voc.tikhub import (
    _parse_tikhub_app_detail_payload,
    _parse_tikhub_comment_payload,
)


RUN_ID = "backfill_validation_fixture"
WINDOW_START = datetime(2024, 12, 31, 16, tzinfo=timezone.utc)
REQUESTED_END = datetime(2026, 7, 11, 16, tzinfo=timezone.utc)
EFFECTIVE_END = datetime(2026, 7, 11, 4, 17, 9, tzinfo=timezone.utc)
CAPTURED_AT = datetime(2026, 7, 11, 4, 18, tzinfo=timezone.utc)
REVIEWED_SUBREDDITS = ("ExclusivelyPumping", "beyondthebump")
PARTIAL_POST_IDS = ("seed_post_000", "seed_post_001", "seed_post_002")
DYNAMIC_ENDPOINT = "/api/v1/reddit/app/fetch_dynamic_search"
DETAIL_ENDPOINT = "/api/v1/reddit/app/fetch_post_details_batch_large"
COMMENTS_ENDPOINT = "/api/v1/reddit/app/fetch_post_comments"
TEST_TEMP_PARENT = Path(__file__).resolve().parents[1] / ".superpowers" / "sdd"
REVIEWED_SOURCE_INVENTORY_SHA256 = (
    "1cabbfe4bb3f197eb01c3654469d49aee3e670fc43ce5769d5f3476837746b96"
)
REVIEWED_PARTIAL_POST_IDS_SHA256 = (
    "a27f8e7fa3a47371e842de8faedb33af44ce65714fa09dd17e7e951b176d1f6a"
)
REVIEWED_SEARCH_TERMS_SHA256 = (
    "5510dfee16938d4a279183939db0bd37b6c2fe6464dd1e791028bafd7cab98f0"
)
REVIEWED_SUBREDDITS_SHA256 = (
    "09343f96c2872f75d6f80943dc60088f6a4a7e64b8d0656d8df8da69ea716df4"
)
REVIEWED_BASELINE_SHA256 = (
    "cc59db2610fc18fb9a5ea343c170bbfa9356e0e1ed704bb57215226729cc3ada"
)

RESULT_KEYS = (
    "schema_version",
    "run_id",
    "scope",
    "status",
    "stop_reason",
    "replay_status",
    "full_ready",
    "source_provider_call",
    "provider_attempt_made",
    "live_send",
    "seed_baseline_sha256",
    "known_seed_partial_count",
    "known_seed_partial_post_ids_sha256",
    "run_root_scan",
    "counts",
    "candidate_status_counts",
    "occurrence_disposition_counts",
    "required_lanes",
    "source_fingerprints",
    "replay_fingerprints",
    "operational_metadata",
    "checks",
    "issues",
)
REPLAY_RESULT_KEYS = (
    "schema_version",
    "status",
    "stop_reason",
    "provider_attempt_made",
    "live_send",
    "fingerprints",
    "metadata_mirrored_count",
    "provider_attempts",
)


def _canonical_sha(value: object, *, sort_keys: bool = False) -> str:
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=sort_keys,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _tikhub_source_url(
    *,
    run_id: str,
    lane_type: str,
    lane_key: str,
    endpoint: str,
    page_number: int,
    request_cursor: str | None,
) -> str:
    identity = json.dumps(
        [run_id, lane_type, lane_key, endpoint, page_number, request_cursor],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return "tikhub://" + sha256(identity).hexdigest()


def _raw_capture_id(
    *, run_id: str, source_method: str, source_url: str, payload_sha256: str
) -> str:
    return "raw_backfill_" + sha256(
        "\0".join((run_id, source_method, source_url, payload_sha256)).encode(
            "utf-8"
        )
    ).hexdigest()[:24]


def _cursor_schema_sha256() -> str:
    shape = {
        "type": "object",
        "properties": {"endCursor": "cursor", "hasNextPage": "boolean"},
    }
    return _canonical_sha(shape, sort_keys=True)


def _discovery_post(post_id: str, created_at: datetime | None) -> dict[str, object]:
    post: dict[str, object] = {
        "id": f"t3_{post_id}",
        "postTitle": f"candidate {post_id}",
        "url": f"https://www.reddit.com/r/ExclusivelyPumping/comments/{post_id}/title/",
        "subreddit": {"name": "ExclusivelyPumping"},
    }
    if created_at is not None:
        post["createdAt"] = created_at.isoformat()
    return {"post": post}


def _discovery_page(
    cursor: str | None, posts: list[dict[str, object]]
) -> dict[str, object]:
    children: list[dict[str, object]] = []
    for value in posts:
        post = value.get("post")
        if not isinstance(post, dict):
            raise ValueError("verified discovery fixture requires wrapped posts")
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


class ArchivedCursorExtractionTests(unittest.TestCase):
    def test_current_comment_terminal_without_cursor_is_explicitly_replayable(self):
        payload = {
            "data": {
                "postInfoById": {
                    "commentForest": {
                        "pageInfo": {
                            "commentCount": 1,
                            "hasNextPage": False,
                        },
                        "trees": [],
                    }
                }
            }
        }
        checkpoint = {
            "cursor_json_path": json.dumps(
                [
                    "data",
                    "postInfoById",
                    "commentForest",
                    "pageInfo",
                    "endCursor",
                ]
            ),
            "cursor_schema_sha256": (
                "67c3b44ef86da5d844320d676e6a6e6cc0dccfc1e94b4509b9cb0ce89ff5edc1"
            ),
        }

        self.assertIsNone(
            backfill_validation_module._cursor_from_checkpoint(
                payload,
                checkpoint,
                allow_terminal_without_cursor=True,
            )
        )

        payload["data"]["postInfoById"]["commentForest"]["pageInfo"][
            "hasNextPage"
        ] = True
        with self.assertRaises(backfill_validation_module._ReplayDataError):
            backfill_validation_module._cursor_from_checkpoint(
                payload,
                checkpoint,
                allow_terminal_without_cursor=True,
            )

    def test_subreddit_none_elements_is_explicitly_replayable(self):
        checkpoint = {
            "cursor_json_path": json.dumps(
                [
                    "data",
                    "subredditV3",
                    "elements",
                    "pageInfo",
                    "endCursor",
                ]
            ),
            "cursor_schema_sha256": (
                "3bc27a141e675230d962942491bb87b8378a956142a75bfc79a631f10b479dbf"
            ),
        }

        self.assertIsNone(
            backfill_validation_module._cursor_from_checkpoint(
                {"data": {"subredditV3": {"elements": None}}},
                checkpoint,
                allow_subreddit_terminal_empty=True,
            )
        )

        with self.assertRaises(backfill_validation_module._ReplayDataError):
            backfill_validation_module._cursor_from_checkpoint(
                {"data": {"subredditV3": {}}},
                checkpoint,
                allow_subreddit_terminal_empty=True,
            )


def _detail_post(
    post_id: str,
    *,
    title: str,
    body: str,
    reported_comments: int,
) -> dict[str, object]:
    return {
        "id": f"t3_{post_id}",
        "createdAt": (WINDOW_START + timedelta(days=40)).isoformat(),
        "postTitle": title,
        "url": f"https://www.reddit.com/r/ExclusivelyPumping/comments/{post_id}/title/",
        "content": {"markdown": body},
        "score": 7,
        "commentCount": reported_comments,
        "subreddit": {"name": "ExclusivelyPumping"},
        "authorInfo": {"name": "submitter"},
    }


def _comment_tree(
    post_id: str,
    comment_id: str,
    body: str,
    *,
    created_at: datetime,
) -> dict[str, object]:
    return {
        "depth": 0,
        "parentId": f"t3_{post_id}",
        "node": {
            "__typename": "Comment",
            "id": comment_id,
            "createdAt": created_at.isoformat(),
            "content": {"markdown": body},
            "authorInfo": {"name": "helper"},
            "score": 3,
        },
    }


def _comment_page(
    post_id: str,
    cursor: str | None,
    trees: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "data": {
            "postInfoById": {
                "id": f"t3_{post_id}",
                "commentForest": {"trees": trees},
            },
            "pageInfo": {
                "hasNextPage": cursor is not None,
                "endCursor": cursor,
            },
        }
    }


def _analysis_row(
    *, analysis_id: str, run_id: str, source_type: str, source_id: str, text: str
) -> AnalysisRow:
    analysis = analyze_text(text)
    return AnalysisRow(
        analysis_id=analysis_id,
        run_id=run_id,
        source_type=source_type,
        source_id=source_id,
        analysis_version="local_rules_v1",
        sentiment_label=analysis.sentiment_label,
        sentiment_score=analysis.sentiment_score,
        topic=analysis.topic,
        severity=analysis.severity,
        confidence=analysis.confidence,
        pain_points=tuple(analysis.pain_points),
        provider_call=False,
    )


def _payload(*, post_id: str, created_at: datetime, comments: int, partial: bool) -> bytes:
    comment_nodes: list[dict[str, object]] = []
    for ordinal in range(comments):
        comment_nodes.append(
            {
                "kind": "t1",
                "data": {
                    "id": f"{post_id}_comment_{ordinal:04d}",
                    "name": f"t1_{post_id}_comment_{ordinal:04d}",
                    "parent_id": f"t3_{post_id}",
                    "body": f"Momcozy pump fixture comment {ordinal}",
                    # Deliberately outside the post window: comments are not filtered by time.
                    "created_utc": (EFFECTIVE_END + timedelta(days=ordinal + 1)).timestamp(),
                    "score": ordinal % 7,
                    "depth": 0,
                    "is_submitter": False,
                    "author": f"fixture-comment-author-{ordinal}",
                },
            }
        )
    if partial:
        comment_nodes.append(
            {
                "kind": "more",
                "data": {"id": f"more_{post_id}", "children": ["unresolved"]},
            }
        )
    payload = [
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
                            "title": f"Momcozy wearable pump fixture {post_id}",
                            "selftext": "Local historical seed fixture.",
                            "permalink": (
                                "/r/ExclusivelyPumping/comments/"
                                f"{post_id}/fixture_thread/"
                            ),
                            "created_utc": created_at.timestamp(),
                            "score": 12,
                            "num_comments": comments + int(partial),
                            "author": f"fixture-post-author-{post_id}",
                        },
                    }
                ]
            },
        },
        {"kind": "Listing", "data": {"children": comment_nodes}},
    ]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _reviewed_seed_baseline() -> SeedBaseline:
    return SeedBaseline(
        schema_version="momcozy_seed_baseline_v1",
        files_total=55,
        files_imported=48,
        files_outside_window=7,
        files_excluded=0,
        files_duplicate=0,
        parse_errors=0,
        threads=48,
        comments=1894,
        analyses=1942,
        coverage_full=45,
        coverage_partial=3,
        coverage_post_only=0,
        source_inventory_sha256=REVIEWED_SOURCE_INVENTORY_SHA256,
        known_partial_post_ids_sha256=REVIEWED_PARTIAL_POST_IDS_SHA256,
        reviewed_search_terms_sha256=REVIEWED_SEARCH_TERMS_SHA256,
        reviewed_subreddits=REVIEWED_SUBREDDITS,
        reviewed_subreddits_sha256=REVIEWED_SUBREDDITS_SHA256,
        baseline_sha256=REVIEWED_BASELINE_SHA256,
    )


def _snapshot_db(path: Path) -> dict[str, object]:
    file_stat = path.stat()
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        tables = tuple(
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        )
        counts = tuple(
            (table, int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]))
            for table in tables
        )
    finally:
        conn.close()
    return {
        "sha256": sha256(path.read_bytes()).hexdigest(),
        "size": file_stat.st_size,
        "mode": stat.S_IMODE(file_stat.st_mode),
        "mtime_ns": file_stat.st_mtime_ns,
        "table_counts": counts,
        "directory_entries": tuple(sorted(item.name for item in path.parent.iterdir())),
        "sidecars": tuple(
            sorted(
                item.name
                for item in path.parent.iterdir()
                if item.name in {path.name + "-wal", path.name + "-shm", path.name + "-journal"}
            )
        ),
    }


def _snapshot_regular_file(path: Path) -> dict[str, object]:
    file_stat = path.stat()
    return {
        "sha256": sha256(path.read_bytes()).hexdigest(),
        "size": file_stat.st_size,
        "mode": stat.S_IMODE(file_stat.st_mode),
        "mtime_ns": file_stat.st_mtime_ns,
    }


def _snapshot_archive(root: Path) -> tuple[tuple[object, ...], ...]:
    return tuple(
        sorted(
            (
                item.relative_to(root).as_posix(),
                "symlink" if item.is_symlink() else "directory" if item.is_dir() else "file",
                stat.S_IMODE(item.lstat().st_mode),
                item.lstat().st_size,
                item.lstat().st_mtime_ns,
                sha256(item.read_bytes()).hexdigest()
                if item.is_file() and not item.is_symlink()
                else None,
            )
            for item in root.rglob("*")
        )
    )


def _rehash_baseline(baseline: SeedBaseline, **changes: object) -> SeedBaseline:
    values = asdict(replace(baseline, **changes))
    values["baseline_sha256"] = _canonical_sha(
        {key: value for key, value in values.items() if key != "baseline_sha256"},
        sort_keys=True,
    )
    return SeedBaseline(**values)


def _issue_codes(result: dict[str, object]) -> set[str]:
    return {str(issue["code"]) for issue in result["issues"]}


def _replay_temporary_paths(path: Path) -> tuple[Path, ...]:
    return (
        path,
        Path(str(path) + "-wal"),
        Path(str(path) + "-shm"),
        Path(str(path) + "-journal"),
    )


def _assert_replay_temporary_absent(test: unittest.TestCase, path: Path) -> None:
    for candidate in _replay_temporary_paths(path):
        test.assertFalse(os.path.lexists(candidate), str(candidate))


def _assert_publication_error(
    test: unittest.TestCase,
    error: BaseException,
    *,
    target: Path,
    temporary_path: Path,
    underlying_detail: str,
) -> None:
    error_type = getattr(
        backfill_validation_module, "ReplayPublicationError", None
    )
    test.assertIsNotNone(error_type)
    test.assertIs(type(error), error_type)
    test.assertEqual(
        error.publication_state, "target_exists_needs_review"
    )
    rendered = f"{error!s} {error.args!r}"
    for forbidden in (str(target), str(temporary_path), underlying_detail):
        test.assertNotIn(forbidden, rendered)


def _assert_replay_target_equivalent(
    test: unittest.TestCase, *, source: Path, target: Path
) -> None:
    with sqlite3.connect(f"{target.resolve().as_uri()}?mode=ro", uri=True) as conn:
        test.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
    test.assertEqual(
        backfill_validation_module._fingerprints_for_path(target, RUN_ID),
        backfill_validation_module._fingerprints_for_path(source, RUN_ID),
    )


class _TrackingConnection:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.statements: list[str] = []
        self.rollback_called = False
        self.close_called = False

    @property
    def row_factory(self):
        return self.connection.row_factory

    @row_factory.setter
    def row_factory(self, value):
        self.connection.row_factory = value

    def execute(self, statement: str, parameters: tuple[object, ...] = ()):
        self.statements.append(" ".join(statement.strip().split()))
        return self.connection.execute(statement, parameters)

    def rollback(self) -> None:
        self.rollback_called = True
        self.connection.rollback()

    def close(self) -> None:
        self.close_called = True
        self.connection.close()


class BackfillValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._base_temporary_directory = TemporaryDirectory(dir=TEST_TEMP_PARENT)
        cls.base_root = Path(cls._base_temporary_directory.name)
        source = cls.base_root / "source"
        source.mkdir()
        inventory: list[tuple[str, str]] = []

        for index in range(48):
            name = f"{index:03d}-imported.json"
            comment_count = 39 if index < 47 else 61
            payload = _payload(
                post_id=f"seed_post_{index:03d}",
                created_at=WINDOW_START + timedelta(days=index + 1),
                comments=comment_count,
                partial=index < 3,
            )
            (source / name).write_bytes(payload)
            inventory.append((sha256(name.encode()).hexdigest(), sha256(payload).hexdigest()))

        for index in range(7):
            name = f"{index + 48:03d}-outside.json"
            payload = _payload(
                post_id=f"outside_post_{index:03d}",
                created_at=WINDOW_START - timedelta(days=index + 1),
                comments=0,
                partial=False,
            )
            (source / name).write_bytes(payload)
            inventory.append((sha256(name.encode()).hexdigest(), sha256(payload).hexdigest()))

        assertion = unittest.TestCase()
        assertion.assertEqual(
            _canonical_sha(
                [[path_hash, payload_hash] for path_hash, payload_hash in sorted(inventory)]
            ),
            REVIEWED_SOURCE_INVENTORY_SHA256,
        )
        assertion.assertEqual(
            _canonical_sha(sorted(PARTIAL_POST_IDS)),
            REVIEWED_PARTIAL_POST_IDS_SHA256,
        )
        assertion.assertEqual(
            _canonical_sha(list(DEFAULT_TIKHUB_SEARCH_TERMS)),
            REVIEWED_SEARCH_TERMS_SHA256,
        )
        assertion.assertEqual(
            _canonical_sha(list(REVIEWED_SUBREDDITS)),
            REVIEWED_SUBREDDITS_SHA256,
        )
        cls.baseline = _reviewed_seed_baseline()
        baseline_payload = asdict(cls.baseline)
        baseline_payload.pop("baseline_sha256")
        assertion.assertEqual(
            _canonical_sha(baseline_payload, sort_keys=True),
            REVIEWED_BASELINE_SHA256,
        )
        cls.base_db = cls.base_root / "backfill.sqlite3"
        cls.base_archive_root = cls.base_root / "private-raw"
        store = BackfillStore(cls.base_db)
        store.migrate()
        store.create_manifest(
            BackfillManifest(
                run_id=RUN_ID,
                status="prepared",
                window_start_utc=WINDOW_START.isoformat(),
                requested_end_utc=REQUESTED_END.isoformat(),
                effective_end_utc=EFFECTIVE_END.isoformat(),
                search_terms=tuple(DEFAULT_TIKHUB_SEARCH_TERMS),
                subreddits=REVIEWED_SUBREDDITS,
                include_subreddit_sweep=False,
                required_lanes_sha256=required_lanes_sha256(
                    search_terms=DEFAULT_TIKHUB_SEARCH_TERMS,
                    subreddits=REVIEWED_SUBREDDITS,
                    include_subreddit_sweep=False,
                ),
                keyword_config_sha256=keyword_rules_sha256(),
                max_provider_requests=0,
                provider_request_count=0,
                provider_call=False,
                live_send=False,
                created_at_utc=CAPTURED_AT.isoformat(),
                updated_at_utc=CAPTURED_AT.isoformat(),
            )
        )
        summary = import_seed_directory(
            store,
            PrivateRawArchive(cls.base_archive_root),
            run_id=RUN_ID,
            source_dir=source,
            window_start_utc=WINDOW_START,
            effective_end_utc=EFFECTIVE_END,
            captured_at_utc=CAPTURED_AT,
        )
        cls.assertEqual(
            unittest.TestCase(),
            (
                summary.files_total,
                summary.files_imported,
                summary.files_outside_window,
                summary.files_excluded,
                summary.files_duplicate,
                summary.parse_errors,
                summary.threads,
                summary.comments,
                summary.analyses,
                summary.coverage_full,
                summary.coverage_partial,
                summary.coverage_post_only,
            ),
            (55, 48, 7, 0, 0, 0, 48, 1894, 1942, 45, 3, 0),
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._base_temporary_directory.cleanup()

    def _case(self) -> tuple[BackfillStore, PrivateRawArchive, Path]:
        temporary_directory = TemporaryDirectory(dir=TEST_TEMP_PARENT)
        self.addCleanup(temporary_directory.cleanup)
        root = Path(temporary_directory.name)
        db = root / "backfill.sqlite3"
        archive_root = root / "private-raw"
        shutil.copy2(self.base_db, db)
        shutil.copytree(self.base_archive_root, archive_root, copy_function=shutil.copy2)
        return BackfillStore(db), PrivateRawArchive(archive_root, read_only=True), root

    def _full_operational_case(
        self,
    ) -> tuple[BackfillStore, PrivateRawArchive, Path]:
        store, reader, root = self._case()
        writer = PrivateRawArchive(reader.root)
        self._sql(
            store.path,
            "UPDATE backfill_manifests SET max_provider_requests=? WHERE run_id=?",
            (len(DEFAULT_TIKHUB_SEARCH_TERMS), RUN_ID),
        )
        for index, term in enumerate(DEFAULT_TIKHUB_SEARCH_TERMS, start=1):
            captured_at = CAPTURED_AT + timedelta(seconds=index)
            artifact = self._write_provider_artifact(
                store,
                writer,
                run_id=RUN_ID,
                artifact_kind="discovery",
                lane_type="dynamic_search",
                lane_key=term,
                parser_kind="tikhub_discovery",
                source_method="tikhub_dynamic_search",
                endpoint=DYNAMIC_ENDPOINT,
                page_number=1,
                request_cursor=None,
                response_cursor=None,
                payload=_discovery_page(None, []),
                captured_at=captured_at,
            )
            request_number = store.reserve_provider_request(
                RUN_ID, DYNAMIC_ENDPOINT, captured_at
            )
            self.assertEqual(request_number, index)
            store.mark_provider_attempt_sent(RUN_ID, index, captured_at)
            store.complete_provider_attempt(
                RUN_ID,
                index,
                status="succeeded",
                completed_at_utc=captured_at,
                http_status=200,
            )
            store.save_checkpoint(
                BackfillCheckpoint(
                    run_id=RUN_ID,
                    lane_type="dynamic_search",
                    lane_key=term,
                    cursor=None,
                    previous_cursor=None,
                    page_number=1,
                    newest_seen_utc=None,
                    oldest_seen_utc=None,
                    discovered_count=0,
                    unique_count=0,
                    provider_request_count=index,
                    last_success_utc=captured_at.isoformat(),
                    last_error=None,
                    status="complete",
                    stop_reason="cursor_exhausted",
                    cursor_json_path=json.dumps(
                        [
                            "data",
                            "search",
                            "dynamic",
                            "components",
                            "main",
                            "pageInfo",
                            "endCursor",
                        ],
                        separators=(",", ":"),
                    ),
                    cursor_schema_sha256=_cursor_schema_sha256(),
                    consecutive_old_pages=0,
                )
            )
        return store, PrivateRawArchive(reader.root, read_only=True), root

    @staticmethod
    def _sql(path: Path, statement: str, parameters: tuple[object, ...] = ()) -> None:
        with sqlite3.connect(path) as conn:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute(statement, parameters)

    def _validate_seed(self, store: BackfillStore, archive: PrivateRawArchive, **kwargs):
        return validate_backfill(
            store,
            archive,
            run_id=RUN_ID,
            seed_baseline=self.baseline,
            scope="seed",
            **kwargs,
        )

    def _small_seed_case(
        self,
        seed_payloads: tuple[tuple[str, bytes], ...],
        *,
        run_id: str,
    ) -> tuple[BackfillStore, PrivateRawArchive, PrivateRawArchive, Path]:
        temporary_directory = TemporaryDirectory(dir=TEST_TEMP_PARENT)
        self.addCleanup(temporary_directory.cleanup)
        root = Path(temporary_directory.name)
        source = root / "source"
        source.mkdir()
        for name, payload in seed_payloads:
            (source / name).write_bytes(payload)
        store = BackfillStore(root / "source.sqlite3")
        store.migrate()
        store.create_manifest(
            BackfillManifest(
                run_id=run_id,
                status="prepared",
                window_start_utc=WINDOW_START.isoformat(),
                requested_end_utc=REQUESTED_END.isoformat(),
                effective_end_utc=EFFECTIVE_END.isoformat(),
                search_terms=("Momcozy",),
                subreddits=("ExclusivelyPumping",),
                include_subreddit_sweep=False,
                required_lanes_sha256=required_lanes_sha256(
                    search_terms=("Momcozy",),
                    subreddits=("ExclusivelyPumping",),
                    include_subreddit_sweep=False,
                ),
                keyword_config_sha256=keyword_rules_sha256(),
                max_provider_requests=16,
                provider_request_count=0,
                provider_call=False,
                live_send=False,
                created_at_utc=CAPTURED_AT.isoformat(),
                updated_at_utc=CAPTURED_AT.isoformat(),
            )
        )
        writer = PrivateRawArchive(root / "private-raw")
        import_seed_directory(
            store,
            writer,
            run_id=run_id,
            source_dir=source,
            window_start_utc=WINDOW_START,
            effective_end_utc=EFFECTIVE_END,
            captured_at_utc=CAPTURED_AT,
        )
        reader = PrivateRawArchive(writer.root, read_only=True)
        return store, writer, reader, root

    def _write_provider_artifact(
        self,
        store: BackfillStore,
        writer: PrivateRawArchive,
        *,
        run_id: str,
        artifact_kind: str,
        lane_type: str,
        lane_key: str,
        parser_kind: str,
        source_method: str,
        endpoint: str,
        page_number: int,
        request_cursor: str | None,
        response_cursor: str | None,
        payload: object,
        captured_at: datetime,
    ):
        payload_bytes = _canonical_json_bytes(payload)
        payload_sha256 = sha256(payload_bytes).hexdigest()
        source_url = _tikhub_source_url(
            run_id=run_id,
            lane_type=lane_type,
            lane_key=lane_key,
            endpoint=endpoint,
            page_number=page_number,
            request_cursor=request_cursor,
        )
        raw_capture_id = _raw_capture_id(
            run_id=run_id,
            source_method=source_method,
            source_url=source_url,
            payload_sha256=payload_sha256,
        )
        artifact = writer.write(
            run_id=run_id,
            artifact_kind=artifact_kind,
            lane_type=lane_type,
            lane_key=lane_key,
            identity=source_url.removeprefix("tikhub://"),
            payload=payload_bytes,
            raw_capture_id=raw_capture_id,
            parser_kind=parser_kind,
            source_method=source_method,
            source_url=source_url,
            source_endpoint=endpoint,
            captured_at_utc=captured_at,
            page_number=page_number,
            request_cursor=request_cursor,
            response_cursor=response_cursor,
        )
        store.persist_raw_capture_artifact(
            RawCapture(
                raw_capture_id=raw_capture_id,
                run_id=run_id,
                source_method=source_method,
                source_url=source_url,
                captured_at_utc=captured_at,
                auth_boundary="provider_gate",
                raw_payload_hash=f"sha256:{payload_sha256}",
                payload_format="json",
            ),
            artifact,
        )
        return artifact

    def _complete_local_attempt(
        self, store: BackfillStore, *, run_id: str, endpoint: str, number: int
    ) -> None:
        reserved = store.reserve_provider_request(run_id, endpoint, CAPTURED_AT)
        self.assertEqual(reserved, number)
        store.mark_provider_attempt_sent(run_id, number, CAPTURED_AT)
        store.complete_provider_attempt(
            run_id,
            number,
            status="succeeded",
            completed_at_utc=CAPTURED_AT,
            http_status=200,
        )

    def _add_discovery_replay_source(
        self,
        store: BackfillStore,
        writer: PrivateRawArchive,
        *,
        run_id: str,
        seed_post_id: str,
        candidate_post_id: str,
        invalid_shapes: bool = False,
        mixed_parser_versions: bool = False,
    ) -> None:
        term = "Momcozy"
        outside_id = "outside_discovery"
        page_one_posts = [
            _discovery_post(candidate_post_id, WINDOW_START + timedelta(days=30)),
            _discovery_post(outside_id, WINDOW_START - timedelta(seconds=1)),
            {"post": {"id": "", "postTitle": "", "url": ""}},
        ]
        page_one = _discovery_page(
            "cursor-2",
            page_one_posts,
        )
        if invalid_shapes:
            page_one_data = page_one["data"]
            self.assertIsInstance(page_one_data, dict)
            page_one_search = page_one_data["search"]
            self.assertIsInstance(page_one_search, dict)
            page_one_search["legacyRows"] = {
                "z_fully_empty": {
                    "post": {"id": "", "postTitle": "", "url": ""}
                },
                "y_missing_title": {
                    "post": {
                        "id": "t3_missing_title",
                        "postTitle": "",
                        "url": (
                            "https://www.reddit.com/r/ExclusivelyPumping/"
                            "comments/missing_title/title/"
                        ),
                        "createdAt": (
                            WINDOW_START + timedelta(days=20)
                        ).isoformat(),
                    }
                },
                "a_partial_identity": {
                    "post": {
                        "id": "t3_partial_identity",
                        "postTitle": "broken provider row",
                    }
                },
            }
        page_two = _discovery_page(
            None,
            [
                _discovery_post(candidate_post_id, WINDOW_START + timedelta(days=30)),
                _discovery_post(seed_post_id, WINDOW_START + timedelta(days=1)),
            ],
        )
        if mixed_parser_versions:
            first_child = page_two["data"]["search"]["dynamic"]["components"][
                "main"
            ]["edges"][0]["node"]["children"][0]
            first_child["metadata"] = {
                "id": "t3_v2_metadata_must_not_be_an_occurrence",
                "url": (
                    "https://www.reddit.com/r/ExclusivelyPumping/comments/"
                    "v2_metadata_must_not_be_an_occurrence/title/"
                ),
            }
        artifact_one = self._write_provider_artifact(
            store,
            writer,
            run_id=run_id,
            artifact_kind="discovery",
            lane_type="dynamic_search",
            lane_key=term,
            parser_kind="tikhub_discovery",
            source_method="tikhub_dynamic_search",
            endpoint=DYNAMIC_ENDPOINT,
            page_number=1,
            request_cursor=None,
            response_cursor="cursor-2",
            payload=page_one,
            captured_at=CAPTURED_AT + timedelta(seconds=1),
        )
        artifact_two = self._write_provider_artifact(
            store,
            writer,
            run_id=run_id,
            artifact_kind="discovery",
            lane_type="dynamic_search",
            lane_key=term,
            parser_kind=(
                "tikhub_discovery_strict_v2"
                if mixed_parser_versions
                else "tikhub_discovery"
            ),
            source_method="tikhub_dynamic_search",
            endpoint=DYNAMIC_ENDPOINT,
            page_number=2,
            request_cursor="cursor-2",
            response_cursor=None,
            payload=page_two,
            captured_at=CAPTURED_AT + timedelta(seconds=2),
        )
        occurrence_arguments = [
            (
                1,
                0,
                candidate_post_id,
                f"https://www.reddit.com/r/ExclusivelyPumping/comments/{candidate_post_id}/title/",
                WINDOW_START + timedelta(days=30),
                artifact_one.artifact_id,
                "eligible",
            ),
            (
                1,
                1,
                outside_id,
                f"https://www.reddit.com/r/ExclusivelyPumping/comments/{outside_id}/title/",
                WINDOW_START - timedelta(seconds=1),
                artifact_one.artifact_id,
                "outside_window",
            ),
            (1, 2, None, None, None, artifact_one.artifact_id, "invalid"),
            (
                2,
                0,
                candidate_post_id,
                f"https://www.reddit.com/r/ExclusivelyPumping/comments/{candidate_post_id}/title/",
                WINDOW_START + timedelta(days=30),
                artifact_two.artifact_id,
                "eligible",
            ),
            (
                2,
                1,
                seed_post_id,
                f"https://www.reddit.com/r/ExclusivelyPumping/comments/{seed_post_id}/title/",
                WINDOW_START + timedelta(days=1),
                artifact_two.artifact_id,
                "eligible",
            ),
        ]
        if invalid_shapes:
            occurrence_arguments[3:3] = [
                (
                    1,
                    3,
                    None,
                    None,
                    None,
                    artifact_one.artifact_id,
                    "invalid",
                ),
                (
                    1,
                    4,
                    "missing_title",
                    (
                        "https://www.reddit.com/r/ExclusivelyPumping/"
                        "comments/missing_title/title/"
                    ),
                    WINDOW_START + timedelta(days=20),
                    artifact_one.artifact_id,
                    "invalid",
                ),
                (
                    1,
                    5,
                    "partial_identity",
                    None,
                    None,
                    artifact_one.artifact_id,
                    "invalid",
                ),
            ]
        for page_number, ordinal, post_id, source_url, created_at, artifact_id, base in occurrence_arguments:
            store.record_discovery_occurrence(
                run_id=run_id,
                lane_type="dynamic_search",
                lane_key=term,
                page_number=page_number,
                ordinal=ordinal,
                post_id=post_id,
                source_url=source_url,
                post_created_at_utc=created_at,
                raw_artifact_id=artifact_id,
                discovered_at_utc=CAPTURED_AT + timedelta(seconds=page_number),
                base_disposition=base,
            )
        self._complete_local_attempt(
            store, run_id=run_id, endpoint=DYNAMIC_ENDPOINT, number=1
        )
        self._complete_local_attempt(
            store, run_id=run_id, endpoint=DYNAMIC_ENDPOINT, number=2
        )
        store.save_checkpoint(
            BackfillCheckpoint(
                run_id=run_id,
                lane_type="dynamic_search",
                lane_key=term,
                cursor=None,
                previous_cursor="cursor-2",
                page_number=2,
                newest_seen_utc=(WINDOW_START + timedelta(days=30)).isoformat(),
                oldest_seen_utc=(WINDOW_START - timedelta(seconds=1)).isoformat(),
                discovered_count=8 if invalid_shapes else 5,
                unique_count=1,
                provider_request_count=2,
                last_success_utc=artifact_two.captured_at_utc,
                last_error=None,
                status="complete",
                stop_reason="cursor_exhausted",
                cursor_json_path=json.dumps(
                    [
                        "data",
                        "search",
                        "dynamic",
                        "components",
                        "main",
                        "pageInfo",
                        "endCursor",
                    ],
                    separators=(",", ":"),
                ),
                cursor_schema_sha256=_cursor_schema_sha256(),
                consecutive_old_pages=0,
            )
        )

    def _zero_page_budget_checkpoint_case(
        self, label: str
    ) -> tuple[
        BackfillStore,
        PrivateRawArchive,
        Path,
        str,
        BackfillCheckpoint,
    ]:
        run_id = f"replay_discovery_zero_page_{label}"
        seed_id = "seed_existing"
        candidate_id = "discovered_candidate"
        store, writer, archive, root = self._small_seed_case(
            (
                (
                    "seed-existing.json",
                    _payload(
                        post_id=seed_id,
                        created_at=WINDOW_START + timedelta(days=1),
                        comments=1,
                        partial=False,
                    ),
                ),
            ),
            run_id=run_id,
        )
        self._add_discovery_replay_source(
            store,
            writer,
            run_id=run_id,
            seed_post_id=seed_id,
            candidate_post_id=candidate_id,
        )
        provider_count = store.provider_request_count(run_id)
        self.assertEqual(provider_count, 2)
        required_hash = required_lanes_sha256(
            search_terms=("Momcozy",),
            subreddits=("ExclusivelyPumping",),
            include_subreddit_sweep=True,
        )
        with store.connect() as connection:
            connection.execute(
                "UPDATE backfill_manifests "
                "SET include_subreddit_sweep=1, required_lanes_sha256=?, "
                "max_provider_requests=? WHERE run_id=?",
                (required_hash, provider_count, run_id),
            )
        checkpoint = BackfillCheckpoint(
            run_id=run_id,
            lane_type="subreddit_feed",
            lane_key="ExclusivelyPumping",
            cursor=None,
            previous_cursor=None,
            page_number=0,
            newest_seen_utc=None,
            oldest_seen_utc=None,
            discovered_count=0,
            unique_count=0,
            provider_request_count=provider_count,
            last_success_utc=None,
            last_error="ProviderBudgetExhausted",
            status="partial",
            stop_reason="budget_exhausted",
            cursor_json_path=None,
            cursor_schema_sha256=None,
            consecutive_old_pages=0,
        )
        store.save_checkpoint(checkpoint)
        store.set_backfill_status(
            run_id,
            "partial",
            CAPTURED_AT + timedelta(seconds=3),
        )
        return store, archive, root, run_id, checkpoint

    def _add_detail_comment_replay_source(
        self,
        store: BackfillStore,
        writer: PrivateRawArchive,
        *,
        run_id: str,
        post_id: str,
    ) -> None:
        batch = store.prepare_detail_batches(
            run_id=run_id,
            post_ids=(post_id,),
            created_at_utc=CAPTURED_AT + timedelta(seconds=3),
        )[0]
        detail_payload = {
            "data": {
                "postsInfoByIds": [
                    _detail_post(
                        post_id,
                        title="Need advice",
                        body="Nothing named in the post.",
                        reported_comments=3,
                    )
                ]
            }
        }
        detail_artifact = self._write_provider_artifact(
            store,
            writer,
            run_id=run_id,
            artifact_kind="detail",
            lane_type="detail_batch",
            lane_key=batch.batch_id,
            parser_kind="tikhub_detail",
            source_method="tikhub_detail",
            endpoint=DETAIL_ENDPOINT,
            page_number=batch.batch_number,
            request_cursor=None,
            response_cursor=None,
            payload=detail_payload,
            captured_at=CAPTURED_AT + timedelta(seconds=3),
        )
        store.attach_detail_batch_artifact(
            run_id=run_id,
            batch_id=batch.batch_id,
            artifact_id=detail_artifact.artifact_id,
            updated_at_utc=CAPTURED_AT + timedelta(seconds=3),
        )

        duplicate_time = CAPTURED_AT + timedelta(days=1)
        page_one_payload = _comment_page(
            post_id,
            "comments-2",
            [
                _comment_tree(
                    post_id,
                    "duplicate_comment",
                    "same semantic comment",
                    created_at=duplicate_time,
                ),
                _comment_tree(
                    post_id,
                    "comment_only_match",
                    "My Momcozy wearable pump works.",
                    created_at=CAPTURED_AT + timedelta(days=2),
                ),
            ],
        )
        page_two_payload = _comment_page(
            post_id,
            None,
            [
                _comment_tree(
                    post_id,
                    "duplicate_comment",
                    "same semantic comment",
                    created_at=duplicate_time,
                ),
                _comment_tree(
                    post_id,
                    "late_comment",
                    "Retain this Momcozy comment outside the post window.",
                    created_at=EFFECTIVE_END + timedelta(days=20),
                ),
            ],
        )
        page_one = self._write_provider_artifact(
            store,
            writer,
            run_id=run_id,
            artifact_kind="comments",
            lane_type="comments",
            lane_key=post_id,
            parser_kind="tikhub_comments",
            source_method="tikhub_comments",
            endpoint=COMMENTS_ENDPOINT,
            page_number=1,
            request_cursor=None,
            response_cursor="comments-2",
            payload=page_one_payload,
            captured_at=CAPTURED_AT + timedelta(seconds=4),
        )
        page_two = self._write_provider_artifact(
            store,
            writer,
            run_id=run_id,
            artifact_kind="comments",
            lane_type="comments",
            lane_key=post_id,
            parser_kind="tikhub_comments",
            source_method="tikhub_comments",
            endpoint=COMMENTS_ENDPOINT,
            page_number=2,
            request_cursor="comments-2",
            response_cursor=None,
            payload=page_two_payload,
            captured_at=CAPTURED_AT + timedelta(seconds=5),
        )

        parsed_thread = _parse_tikhub_app_detail_payload(
            detail_payload,
            comment_payloads={},
            run_id=run_id,
            raw_capture_id=detail_artifact.raw_capture_id,
        )[0][0]
        page_one_comments, page_one_more = _parse_tikhub_comment_payload(
            page_one_payload,
            post_id=post_id,
            run_id=run_id,
            raw_capture_id=page_one.raw_capture_id,
            submitter_name="submitter",
        )
        page_two_comments, page_two_more = _parse_tikhub_comment_payload(
            page_two_payload,
            post_id=post_id,
            run_id=run_id,
            raw_capture_id=page_two.raw_capture_id,
            submitter_name="submitter",
        )
        comments_by_id = {comment.comment_id: comment for comment in page_one_comments}
        for comment in page_two_comments:
            comments_by_id.setdefault(comment.comment_id, comment)
        comments = tuple(comments_by_id.values())
        combined = analyze_text(
            "\n".join(
                (
                    parsed_thread.title,
                    parsed_thread.selftext,
                    *(comment.body for comment in comments),
                )
            )
        )
        final_thread = replace(
            parsed_thread,
            parsed_comment_count=len(comments),
            more_node_count=page_one_more + page_two_more,
            coverage_grade=BrowserJsonAdapter._coverage_grade(
                parsed_comment_count=len(comments),
                more_node_count=page_one_more + page_two_more,
                reported_count=parsed_thread.num_comments_reported,
            ),
            matched_keywords=combined.keyword_match.matched_terms,
        )
        store.save_checkpoint(
            BackfillCheckpoint(
                run_id=run_id,
                lane_type="comments",
                lane_key=post_id,
                cursor=None,
                previous_cursor="comments-2",
                page_number=2,
                newest_seen_utc=None,
                oldest_seen_utc=None,
                discovered_count=4,
                unique_count=3,
                provider_request_count=5,
                last_success_utc=page_two.captured_at_utc,
                last_error=None,
                status="complete",
                stop_reason="cursor_exhausted",
                cursor_json_path=json.dumps(
                    ["data", "pageInfo", "endCursor"], separators=(",", ":")
                ),
                cursor_schema_sha256=_cursor_schema_sha256(),
                consecutive_old_pages=0,
            )
        )
        analyses = (
            _analysis_row(
                analysis_id=f"analysis_post_{post_id}",
                run_id=run_id,
                source_type="post",
                source_id=post_id,
                text=f"{final_thread.title}\n{final_thread.selftext}",
            ),
            *(
                _analysis_row(
                    analysis_id=f"analysis_comment_{comment.comment_id}",
                    run_id=run_id,
                    source_type="comment",
                    source_id=comment.comment_id,
                    text=comment.body,
                )
                for comment in comments
            ),
        )
        captures = tuple(
            store.load_raw_capture(raw_capture_id)
            for raw_capture_id in (
                detail_artifact.raw_capture_id,
                page_one.raw_capture_id,
                page_two.raw_capture_id,
            )
        )
        self.assertTrue(all(capture is not None for capture in captures))
        store.finalize_candidate(
            run_id=run_id,
            post_id=post_id,
            expected_statuses=("pending",),
            status="hydrated",
            status_reason=None,
            updated_at_utc=CAPTURED_AT + timedelta(seconds=5),
            captures=captures,
            threads=(final_thread,),
            comments=comments,
            analyses=analyses,
        )
        store.finish_detail_batch(
            run_id=run_id,
            batch_id=batch.batch_id,
            status="complete",
            stop_reason=None,
            updated_at_utc=CAPTURED_AT + timedelta(seconds=5),
        )
        self._complete_local_attempt(
            store, run_id=run_id, endpoint=DETAIL_ENDPOINT, number=3
        )
        self._complete_local_attempt(
            store, run_id=run_id, endpoint=COMMENTS_ENDPOINT, number=4
        )
        self._complete_local_attempt(
            store, run_id=run_id, endpoint=COMMENTS_ENDPOINT, number=5
        )

    def _detail_comment_case(
        self, label: str
    ) -> tuple[
        BackfillStore,
        PrivateRawArchive,
        PrivateRawArchive,
        Path,
        str,
        str,
    ]:
        run_id = f"phase_c3_{label}"
        seed_id = f"seed_{label}"
        post_id = f"candidate_{label}"
        store, writer, archive, root = self._small_seed_case(
            (
                (
                    "seed.json",
                    _payload(
                        post_id=seed_id,
                        created_at=WINDOW_START + timedelta(days=1),
                        comments=1,
                        partial=False,
                    ),
                ),
            ),
            run_id=run_id,
        )
        self._add_discovery_replay_source(
            store,
            writer,
            run_id=run_id,
            seed_post_id=seed_id,
            candidate_post_id=post_id,
        )
        self._add_detail_comment_replay_source(
            store,
            writer,
            run_id=run_id,
            post_id=post_id,
        )
        return store, writer, archive, root, run_id, post_id

    def _replace_provider_payload(
        self,
        store: BackfillStore,
        writer: PrivateRawArchive,
        *,
        run_id: str,
        lane_type: str,
        lane_key: str,
        page_number: int,
        payload: object,
    ):
        old = next(
            artifact
            for artifact in store.load_raw_artifacts(
                run_id=run_id,
                lane_type=lane_type,
                lane_key=lane_key,
            )
            if artifact.page_number == page_number
        )
        payload_bytes = _canonical_json_bytes(payload)
        payload_sha256 = sha256(payload_bytes).hexdigest()
        raw_capture_id = _raw_capture_id(
            run_id=run_id,
            source_method=old.source_method,
            source_url=old.source_url,
            payload_sha256=payload_sha256,
        )
        replacement = writer.write(
            run_id=run_id,
            artifact_kind=old.artifact_kind,
            lane_type=old.lane_type,
            lane_key=lane_key,
            identity=old.source_url.removeprefix("tikhub://"),
            payload=payload_bytes,
            raw_capture_id=raw_capture_id,
            parser_kind=old.parser_kind,
            source_method=old.source_method,
            source_url=old.source_url,
            source_endpoint=old.source_endpoint,
            captured_at_utc=datetime.fromisoformat(old.captured_at_utc),
            page_number=old.page_number,
            request_cursor=old.request_cursor,
            response_cursor=old.response_cursor,
        )
        store.persist_raw_capture_artifact(
            RawCapture(
                raw_capture_id=raw_capture_id,
                run_id=run_id,
                source_method=old.source_method,
                source_url=old.source_url,
                captured_at_utc=datetime.fromisoformat(old.captured_at_utc),
                auth_boundary="provider_gate",
                raw_payload_hash=f"sha256:{payload_sha256}",
                payload_format="json",
            ),
            replacement,
        )
        with sqlite3.connect(store.path) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute(
                "UPDATE reddit_comments SET raw_capture_id=? "
                "WHERE run_id=? AND raw_capture_id=?",
                (raw_capture_id, run_id, old.raw_capture_id),
            )
            conn.execute(
                "DELETE FROM backfill_raw_artifacts "
                "WHERE run_id=? AND artifact_id=?",
                (run_id, old.artifact_id),
            )
            conn.execute(
                "DELETE FROM raw_captures "
                "WHERE run_id=? AND raw_capture_id=?",
                (run_id, old.raw_capture_id),
            )
        (writer.root / old.relative_path).unlink()
        return replacement

    def test_seed_scope_accepts_clean_seed_without_replay_but_never_claims_full(self):
        store, archive, root = self._case()
        result = self._validate_seed(store, archive)

        self.assertEqual(tuple(result), RESULT_KEYS)
        self.assertEqual(result["schema_version"], "backfill_validation_v1")
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["stop_reason"], "seed_validation_complete")
        self.assertEqual(result["replay_status"], "not_run")
        self.assertFalse(result["full_ready"])
        self.assertFalse(result["source_provider_call"])
        self.assertFalse(result["provider_attempt_made"])
        self.assertFalse(result["live_send"])
        self.assertEqual(result["seed_baseline_sha256"], self.baseline.baseline_sha256)
        self.assertEqual(result["known_seed_partial_count"], 3)
        self.assertEqual(
            result["known_seed_partial_post_ids_sha256"],
            self.baseline.known_partial_post_ids_sha256,
        )
        self.assertEqual(result["run_root_scan"], "not_run")
        self.assertTrue(result["required_lanes"])
        self.assertTrue(all(lane["status"] == "not_run" for lane in result["required_lanes"]))
        self.assertFalse(result["issues"])
        operational_check = next(
            check
            for check in result["checks"]
            if check["code"] == "operational_accounting"
        )
        self.assertRegex(operational_check["actual"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            operational_check["actual"], operational_check["expected"]
        )
        serialized = json.dumps(result, ensure_ascii=False, sort_keys=False, separators=(",", ":"))
        self.assertNotIn(str(root), serialized)
        self.assertNotIn("https://", serialized)
        self.assertNotIn("seed_post_", serialized)

        full_result = validate_backfill(
            store,
            archive,
            run_id=RUN_ID,
            seed_baseline=self.baseline,
            scope="full",
            replay_db=None,
            run_root=root,
        )
        self.assertEqual(full_result["status"], "rejected")
        self.assertEqual(full_result["replay_status"], "required")
        self.assertFalse(full_result["full_ready"])
        self.assertFalse(full_result["provider_attempt_made"])
        self.assertFalse(full_result["live_send"])

    def test_seed_baseline_is_mandatory_external_and_hash_checked(self):
        self.assertTrue(SeedBaseline.__dataclass_params__.frozen)
        self.assertEqual(
            tuple(field.name for field in fields(SeedBaseline)),
            (
                "schema_version",
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
                "source_inventory_sha256",
                "known_partial_post_ids_sha256",
                "reviewed_search_terms_sha256",
                "reviewed_subreddits",
                "reviewed_subreddits_sha256",
                "baseline_sha256",
            ),
        )
        baseline_dict = asdict(self.baseline)
        missing = dict(baseline_dict)
        missing.pop("comments")
        extra = {**baseline_dict, "release_manifest_sha256": "0" * 64}
        cases = {
            "none": None,
            "missing_field": missing,
            "extra_field": extra,
            "wrong_type": replace(self.baseline, files_total=True),
            "negative_count": replace(self.baseline, comments=-1),
            "bad_sha": replace(self.baseline, source_inventory_sha256="A" * 64),
            "bad_canonical_hash": replace(self.baseline, baseline_sha256="0" * 64),
            "fixed_numeric_contract": replace(self.baseline, files_total=56),
            "inventory_mismatch": replace(
                self.baseline,
                source_inventory_sha256="1" * 64,
                baseline_sha256="2" * 64,
            ),
            "partial_mismatch": replace(
                self.baseline,
                known_partial_post_ids_sha256="3" * 64,
                baseline_sha256="4" * 64,
            ),
        }

        for label, baseline in cases.items():
            with self.subTest(case=label):
                store, archive, _ = self._case()
                result = validate_backfill(
                    store,
                    archive,
                    run_id=RUN_ID,
                    seed_baseline=baseline,
                    scope="seed",
                )
                self.assertEqual(result["status"], "rejected")
                self.assertEqual(result["stop_reason"], "manifest_or_keyword_contract_invalid")
                self.assertIn("seed_baseline_invalid", _issue_codes(result))

        # A self-consistent but source-mismatched external baseline must still fail closed.
        values = asdict(self.baseline)
        values["source_inventory_sha256"] = "5" * 64
        values["baseline_sha256"] = _canonical_sha(
            {key: value for key, value in values.items() if key != "baseline_sha256"},
            sort_keys=True,
        )
        store, archive, _ = self._case()
        result = validate_backfill(
            store,
            archive,
            run_id=RUN_ID,
            seed_baseline=SeedBaseline(**values),
            scope="seed",
        )
        self.assertEqual(result["status"], "rejected")
        self.assertIn("seed_inventory_mismatch", _issue_codes(result))

        semantic_cases = {
            "self_consistent_wrong_numeric": (
                _rehash_baseline(self.baseline, files_total=56),
                "seed_baseline_invalid",
            ),
            "self_consistent_wrong_known_partial": (
                _rehash_baseline(
                    self.baseline, known_partial_post_ids_sha256="7" * 64
                ),
                "known_seed_partial_mismatch",
            ),
            "self_consistent_wrong_search_hash": (
                _rehash_baseline(
                    self.baseline, reviewed_search_terms_sha256="8" * 64
                ),
                "reviewed_search_terms_hash_mismatch",
            ),
        }
        for label, (baseline, expected_code) in semantic_cases.items():
            with self.subTest(case=label):
                store, archive, _ = self._case()
                result = validate_backfill(
                    store,
                    archive,
                    run_id=RUN_ID,
                    seed_baseline=baseline,
                    scope="seed",
                )
                self.assertEqual(result["status"], "rejected")
                self.assertIn(expected_code, _issue_codes(result))

    def test_malformed_baseline_types_return_safe_rejection(self):
        malformed = {
            "non_json_sha": replace(
                self.baseline, source_inventory_sha256=b"not-a-sha"
            ),
            "non_json_subreddit": replace(
                self.baseline, reviewed_subreddits=(object(),)
            ),
        }
        for label, baseline in malformed.items():
            with self.subTest(case=label):
                store, archive, _ = self._case()
                result = validate_backfill(
                    store,
                    archive,
                    run_id=RUN_ID,
                    seed_baseline=baseline,
                    scope="seed",
                )
                self.assertEqual(result["status"], "rejected")
                self.assertEqual(
                    result["stop_reason"], "manifest_or_keyword_contract_invalid"
                )
                self.assertIn("seed_baseline_invalid", _issue_codes(result))

    def test_validation_is_strictly_query_only(self):
        store, archive, root = self._case()
        allowed_non_gzip_temp = archive.root / RUN_ID / ".writer-residue.tmp"
        allowed_non_gzip_temp.write_bytes(b"non-gzip files are outside the untracked contract")
        before_db = _snapshot_db(store.path)
        before_archive = _snapshot_archive(archive.root)
        write_methods = (
            "migrate",
            "create_manifest",
            "insert_entity_bundle",
            "insert_raw_artifact",
            "persist_raw_capture_artifact",
            "complete_raw_artifact_response_cursor",
            "prepare_detail_batches",
            "attach_detail_batch_artifact",
            "finish_detail_batch",
            "finalize_candidate",
            "record_seed_file",
            "set_backfill_status",
            "reserve_provider_request",
            "mark_provider_attempt_sent",
            "complete_provider_attempt",
            "record_discovery_occurrence",
            "save_checkpoint",
        )
        with ExitStack() as stack:
            stack.enter_context(patch.object(BackfillStore, "connect", side_effect=AssertionError("connect called")))
            for method in write_methods:
                stack.enter_context(
                    patch.object(BackfillStore, method, side_effect=AssertionError(f"{method} called"))
                )
            stack.enter_context(patch.object(archive, "write", side_effect=AssertionError("archive write called")))
            result = self._validate_seed(store, archive)

        self.assertEqual(result["status"], "accepted")
        self.assertEqual(_snapshot_db(store.path), before_db)
        self.assertEqual(_snapshot_archive(archive.root), before_archive)

        missing_db = root / "missing.sqlite3"
        missing_store = BackfillStore(missing_db)
        before_entries = tuple(sorted(item.name for item in root.iterdir()))
        missing_result = validate_backfill(
            missing_store,
            archive,
            run_id=RUN_ID,
            seed_baseline=self.baseline,
            scope="seed",
        )
        self.assertEqual(missing_result["status"], "rejected")
        self.assertEqual(missing_result["stop_reason"], "source_unreadable")
        self.assertFalse(missing_db.exists())
        self.assertEqual(tuple(sorted(item.name for item in root.iterdir())), before_entries)

    def test_validation_rejects_source_database_symlink_without_mutation(self):
        store, archive, root = self._case()
        source_link = root / "source-link.sqlite3"
        source_link.symlink_to(store.path)
        before_db = _snapshot_db(store.path)
        before_entries = tuple(sorted(item.name for item in root.iterdir()))

        result = validate_backfill(
            BackfillStore(source_link),
            archive,
            run_id=RUN_ID,
            seed_baseline=self.baseline,
            scope="seed",
        )

        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["stop_reason"], "source_unreadable")
        self.assertIn("source_db_unreadable", _issue_codes(result))
        self.assertTrue(source_link.is_symlink())
        self.assertEqual(_snapshot_db(store.path), before_db)
        self.assertEqual(tuple(sorted(item.name for item in root.iterdir())), before_entries)

    def test_validation_rejects_source_database_with_lexical_parent_symlink(self):
        store, archive, root = self._case()
        linked_parent = root / "linked-parent"
        linked_parent.symlink_to(root, target_is_directory=True)
        linked_store = BackfillStore(linked_parent / store.path.name)
        before_db = _snapshot_db(store.path)
        before_archive = _snapshot_archive(archive.root)
        before_entries = tuple(sorted(item.name for item in root.iterdir()))

        result = validate_backfill(
            linked_store,
            archive,
            run_id=RUN_ID,
            seed_baseline=self.baseline,
            scope="seed",
        )

        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["stop_reason"], "source_unreadable")
        self.assertIn("source_db_unreadable", _issue_codes(result))
        self.assertTrue(linked_parent.is_symlink())
        self.assertEqual(_snapshot_db(store.path), before_db)
        self.assertEqual(_snapshot_archive(archive.root), before_archive)
        self.assertEqual(tuple(sorted(item.name for item in root.iterdir())), before_entries)

    def test_validation_reads_existing_wal_snapshot_without_mutation(self):
        store, archive, root = self._case()
        writer = sqlite3.connect(store.path)
        try:
            self.assertEqual(writer.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
            writer.execute("PRAGMA wal_autocheckpoint=0")
            writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            clean_main = _snapshot_regular_file(store.path)
            main_only_copy = root / "main-only.sqlite3"
            shutil.copy2(store.path, main_only_copy)
            main_only = sqlite3.connect(
                f"file:{main_only_copy}?mode=ro", uri=True
            )
            try:
                main_keyword_hash = main_only.execute(
                    "SELECT keyword_config_sha256 FROM backfill_manifests WHERE run_id=?",
                    (RUN_ID,),
                ).fetchone()[0]
            finally:
                main_only.close()
            self.assertEqual(main_keyword_hash, keyword_rules_sha256())

            writer.execute(
                "UPDATE backfill_manifests SET keyword_config_sha256=? WHERE run_id=?",
                ("0" * 64, RUN_ID),
            )
            writer.commit()
            self.assertEqual(_snapshot_regular_file(store.path), clean_main)
            self.assertTrue(Path(str(store.path) + "-wal").is_file())
            self.assertTrue(Path(str(store.path) + "-shm").is_file())
            before_db = _snapshot_db(store.path)
            before_wal = _snapshot_regular_file(Path(str(store.path) + "-wal"))
            before_archive = _snapshot_archive(archive.root)

            result = self._validate_seed(store, archive)

            self.assertEqual(result["status"], "rejected")
            self.assertEqual(
                result["stop_reason"], "manifest_or_keyword_contract_invalid"
            )
            self.assertIn("keyword_config_mismatch", _issue_codes(result))
            self.assertEqual(_snapshot_db(store.path), before_db)
            self.assertEqual(
                _snapshot_regular_file(Path(str(store.path) + "-wal")), before_wal
            )
            self.assertEqual(_snapshot_archive(archive.root), before_archive)
        finally:
            writer.close()

    def test_validation_configures_and_closes_sqlite_connection_on_all_paths(self):
        real_connect = sqlite3.connect

        def run_tracked(*, force_exception: bool) -> _TrackingConnection:
            store, archive, _ = self._case()
            calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
            tracked: list[_TrackingConnection] = []

            def connect(*args, **kwargs):
                calls.append((args, kwargs))
                wrapper = _TrackingConnection(real_connect(*args, **kwargs))
                tracked.append(wrapper)
                return wrapper

            with patch(
                "reddit_voc.backfill_validation.sqlite3.connect", side_effect=connect
            ):
                if force_exception:
                    with patch(
                        "reddit_voc.backfill_validation._validate_connection",
                        side_effect=RuntimeError("local-fixture-failure"),
                    ):
                        with self.assertRaisesRegex(RuntimeError, "local-fixture-failure"):
                            self._validate_seed(store, archive)
                else:
                    result = self._validate_seed(store, archive)
                    self.assertEqual(result["status"], "accepted")

            self.assertEqual(len(calls), 1)
            self.assertEqual(len(tracked), 1)
            args, kwargs = calls[0]
            self.assertIn("mode=ro", str(args[0]))
            self.assertNotIn("immutable=1", str(args[0]))
            self.assertTrue(kwargs["uri"])
            connection = tracked[0]
            self.assertIn("PRAGMA query_only = ON", connection.statements)
            self.assertIn("PRAGMA foreign_keys = ON", connection.statements)
            self.assertIn("BEGIN", connection.statements)
            self.assertTrue(connection.rollback_called)
            self.assertTrue(connection.close_called)
            return connection

        run_tracked(force_exception=False)
        run_tracked(force_exception=True)

    def test_malformed_source_rows_fail_closed_without_leaking_or_connection_mutation(self):
        real_connect = sqlite3.connect

        def validate_tracked(store, archive, *, scope: str, run_root: Path | None = None):
            tracked: list[_TrackingConnection] = []

            def connect(*args, **kwargs):
                wrapper = _TrackingConnection(real_connect(*args, **kwargs))
                tracked.append(wrapper)
                return wrapper

            with patch(
                "reddit_voc.backfill_validation.sqlite3.connect", side_effect=connect
            ):
                result = validate_backfill(
                    store,
                    archive,
                    run_id=RUN_ID,
                    seed_baseline=self.baseline,
                    scope=scope,
                    replay_db=None,
                    run_root=run_root,
                )

            self.assertEqual(len(tracked), 1)
            self.assertTrue(tracked[0].rollback_called)
            self.assertTrue(tracked[0].close_called)
            return result

        cases = (
            (
                "seed_thread_numeric",
                self._case,
                lambda store: self._sql(
                    store.path,
                    "UPDATE reddit_threads SET more_node_count=? "
                    "WHERE post_id='seed_post_000'",
                    ("fixture-secret-thread-numeric",),
                ),
                "seed",
            ),
            (
                "full_checkpoint_numeric",
                self._full_operational_case,
                lambda store: self._sql(
                    store.path,
                    "UPDATE backfill_checkpoints SET page_number=? "
                    "WHERE run_id=? AND lane_type='dynamic_search' "
                    "AND lane_key=?",
                    (
                        "fixture-secret-checkpoint-numeric",
                        RUN_ID,
                        DEFAULT_TIKHUB_SEARCH_TERMS[0],
                    ),
                ),
                "full",
            ),
            (
                "full_attempt_numeric",
                self._full_operational_case,
                lambda store: self._sql(
                    store.path,
                    "UPDATE backfill_provider_attempts SET request_number=? "
                    "WHERE run_id=? AND request_number=1",
                    ("fixture-secret-attempt-numeric", RUN_ID),
                ),
                "full",
            ),
        )
        for label, case_factory, mutate, scope in cases:
            with self.subTest(case=label):
                store, archive, root = case_factory()
                mutate(store)
                before_db = _snapshot_db(store.path)
                before_archive = _snapshot_archive(archive.root)

                result = validate_tracked(
                    store,
                    archive,
                    scope=scope,
                    run_root=root if scope == "full" else None,
                )

                self.assertEqual(tuple(result), RESULT_KEYS)
                self.assertEqual(result["schema_version"], "backfill_validation_v1")
                self.assertEqual(result["status"], "rejected")
                self.assertEqual(
                    result["stop_reason"], "schema_or_sqlite_integrity_failed"
                )
                self.assertIn("source_row_decode_failed", _issue_codes(result))
                serialized = json.dumps(
                    result, ensure_ascii=False, sort_keys=False, separators=(",", ":")
                )
                self.assertNotIn("fixture-secret-", serialized)
                self.assertNotIn("ValueError", serialized)
                self.assertNotIn("invalid literal", serialized)
                self.assertEqual(_snapshot_db(store.path), before_db)
                self.assertEqual(_snapshot_archive(archive.root), before_archive)

    def test_required_table_missing_column_fails_closed_at_read_boundary(self):
        store, archive, _ = self._case()
        with sqlite3.connect(store.path) as conn:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute(
                "ALTER TABLE delivery_previews RENAME TO delivery_previews_old"
            )
            conn.execute(
                "CREATE TABLE delivery_previews ("
                "delivery_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, "
                "channel TEXT NOT NULL, mode TEXT NOT NULL, status TEXT NOT NULL, "
                "message_hash TEXT NOT NULL, artifact_paths TEXT NOT NULL)"
            )
            conn.execute("DROP TABLE delivery_previews_old")
        before_db = _snapshot_db(store.path)
        before_archive = _snapshot_archive(archive.root)

        result = self._validate_seed(store, archive)

        self.assertEqual(tuple(result), RESULT_KEYS)
        self.assertEqual(result["schema_version"], "backfill_validation_v1")
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(
            result["stop_reason"], "schema_or_sqlite_integrity_failed"
        )
        self.assertIn("required_column_missing", _issue_codes(result))
        self.assertEqual(_snapshot_db(store.path), before_db)
        self.assertEqual(_snapshot_archive(archive.root), before_archive)

    def test_run_root_symlink_or_symlinked_parent_fails_before_target_scan(self):
        cases = ("final_component", "parent_component")
        for label in cases:
            with self.subTest(case=label):
                store, archive, root = self._case()
                target_parent = root / "target-parent"
                target_root = target_parent / "actual-run-root"
                target_root.mkdir(parents=True)
                live_send = target_root / "forbidden-live-send.json"
                live_send.write_text("fixture-secret-live-send", encoding="utf-8")
                if label == "final_component":
                    run_root = root / "run-root-link"
                    run_root.symlink_to(target_root, target_is_directory=True)
                else:
                    linked_parent = root / "linked-parent"
                    linked_parent.symlink_to(target_parent, target_is_directory=True)
                    run_root = linked_parent / target_root.name
                before_target = _snapshot_archive(target_root)
                before_entries = tuple(sorted(item.name for item in root.iterdir()))

                result = self._validate_seed(store, archive, run_root=run_root)

                self.assertEqual(result["status"], "rejected")
                self.assertEqual(
                    result["stop_reason"], "live_send_boundary_violation"
                )
                self.assertEqual(result["run_root_scan"], "failed")
                self.assertIn("run_root_scan_failed", _issue_codes(result))
                self.assertNotIn("live_send_artifact_found", _issue_codes(result))
                self.assertEqual(_snapshot_archive(target_root), before_target)
                self.assertEqual(
                    tuple(sorted(item.name for item in root.iterdir())), before_entries
                )

    def test_malformed_artifact_metadata_returns_safe_rejection(self):
        store, archive, _ = self._case()
        self._sql(
            store.path,
            "UPDATE backfill_raw_artifacts SET page_number='bad' "
            "WHERE artifact_id=(SELECT artifact_id FROM backfill_raw_artifacts "
            "ORDER BY artifact_id LIMIT 1)",
        )

        result = self._validate_seed(store, archive)

        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["stop_reason"], "archive_integrity_failed")
        self.assertIn("archive_integrity_failed", _issue_codes(result))

    def test_archive_inventory_scan_error_fails_closed(self):
        store, archive, _ = self._case()
        unreadable = archive.root / RUN_ID / "unreadable"
        unreadable.mkdir()
        (unreadable / "untracked.json.gz").write_bytes(b"untracked")
        unreadable.chmod(0)
        try:
            result = self._validate_seed(store, archive)
        finally:
            unreadable.chmod(stat.S_IRWXU)

        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["stop_reason"], "archive_integrity_failed")
        self.assertIn("archive_inventory_unreadable", _issue_codes(result))

    def test_full_operational_control_has_only_replay_required_issue(self):
        store, archive, root = self._full_operational_case()

        result = validate_backfill(
            store,
            archive,
            run_id=RUN_ID,
            seed_baseline=self.baseline,
            scope="full",
            replay_db=None,
            run_root=root,
        )

        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["stop_reason"], "replay_required")
        self.assertEqual(result["replay_status"], "required")
        self.assertEqual(_issue_codes(result), {"replay_required"})
        self.assertTrue(result["source_provider_call"])
        self.assertTrue(result["required_lanes"])
        self.assertTrue(
            all(lane["status"] == "complete" for lane in result["required_lanes"])
        )

    def test_full_operational_false_success_cases_are_isolated(self):
        first_term = DEFAULT_TIKHUB_SEARCH_TERMS[0]
        first_lane_hash = sha256(first_term.encode()).hexdigest()

        def occurrence_count(store, archive, root):
            with sqlite3.connect(store.path) as conn:
                artifact_id = conn.execute(
                    "SELECT artifact_id FROM backfill_raw_artifacts "
                    "WHERE run_id=? AND lane_type='dynamic_search' "
                    "AND lane_key_hash=?",
                    (RUN_ID, first_lane_hash),
                ).fetchone()[0]
                conn.execute(
                    "UPDATE backfill_checkpoints SET discovered_count=2 "
                    "WHERE run_id=? AND lane_type='dynamic_search' AND lane_key=?",
                    (RUN_ID, first_term),
                )
                conn.execute(
                    "INSERT INTO backfill_discovery_occurrences VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        RUN_ID,
                        "dynamic_search",
                        first_term,
                        1,
                        0,
                        None,
                        None,
                        None,
                        artifact_id,
                        CAPTURED_AT.isoformat(),
                        "invalid",
                    ),
                )

        def candidate_first(store, archive, root):
            with sqlite3.connect(store.path) as conn:
                artifact_id = conn.execute(
                    "SELECT artifact_id FROM backfill_raw_artifacts "
                    "WHERE run_id=? AND lane_type='dynamic_search' "
                    "AND lane_key_hash=?",
                    (RUN_ID, first_lane_hash),
                ).fetchone()[0]
                conn.execute(
                    "UPDATE backfill_checkpoints SET discovered_count=1, unique_count=1 "
                    "WHERE run_id=? AND lane_type='dynamic_search' AND lane_key=?",
                    (RUN_ID, first_term),
                )
                occurrence = (
                    RUN_ID,
                    "dynamic_search",
                    first_term,
                    1,
                    0,
                    "seed_post_000",
                    "local://candidate",
                    WINDOW_START.isoformat(),
                    artifact_id,
                    CAPTURED_AT.isoformat(),
                    "new_candidate",
                )
                conn.execute(
                    "INSERT INTO backfill_discovery_occurrences VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?)",
                    occurrence,
                )
                conn.execute(
                    "INSERT INTO backfill_candidates VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        RUN_ID,
                        "seed_post_000",
                        "dynamic_search",
                        "wrong-term",
                        CAPTURED_AT.isoformat(),
                        "local://candidate",
                        WINDOW_START.isoformat(),
                        artifact_id,
                        "duplicate_existing_structured",
                        None,
                        CAPTURED_AT.isoformat(),
                    ),
                )

        def missing_page_one(store, archive, root):
            with sqlite3.connect(store.path) as conn:
                conn.execute("PRAGMA foreign_keys=OFF")
                row = conn.execute(
                    "SELECT artifact_id, raw_capture_id, relative_path "
                    "FROM backfill_raw_artifacts WHERE run_id=? "
                    "AND lane_type='dynamic_search' AND lane_key_hash=?",
                    (RUN_ID, first_lane_hash),
                ).fetchone()
                conn.execute(
                    "DELETE FROM backfill_raw_artifacts WHERE run_id=? AND artifact_id=?",
                    (RUN_ID, row[0]),
                )
                conn.execute(
                    "DELETE FROM raw_captures WHERE run_id=? AND raw_capture_id=?",
                    (RUN_ID, row[1]),
                )
            (archive.root / row[2]).unlink()

        def missing_provider_evidence(store, archive, root):
            with sqlite3.connect(store.path) as conn:
                conn.execute(
                    "DELETE FROM backfill_provider_attempts WHERE run_id=?", (RUN_ID,)
                )
                conn.execute(
                    "UPDATE backfill_manifests SET provider_request_count=0, "
                    "provider_call=0 WHERE run_id=?",
                    (RUN_ID,),
                )
                conn.execute(
                    "UPDATE runs SET provider_call=0 WHERE run_id=?", (RUN_ID,)
                )

        def attempt_gap(store, archive, root):
            self._sql(
                store.path,
                "DELETE FROM backfill_provider_attempts "
                "WHERE run_id=? AND request_number=2",
                (RUN_ID,),
            )

        def attempt_state(store, archive, root):
            self._sql(
                store.path,
                "UPDATE backfill_provider_attempts SET sent_at_utc=NULL "
                "WHERE run_id=? AND request_number=1",
                (RUN_ID,),
            )

        def attempt_count(store, archive, root):
            self._sql(
                store.path,
                "UPDATE backfill_manifests SET provider_request_count=14 WHERE run_id=?",
                (RUN_ID,),
            )

        def attempt_budget(store, archive, root):
            with sqlite3.connect(store.path) as conn:
                conn.execute("PRAGMA ignore_check_constraints=ON")
                conn.execute(
                    "UPDATE backfill_manifests SET max_provider_requests=14 "
                    "WHERE run_id=?",
                    (RUN_ID,),
                )

        def attempt_flags(store, archive, root):
            with sqlite3.connect(store.path) as conn:
                conn.execute(
                    "UPDATE backfill_manifests SET provider_call=0 WHERE run_id=?",
                    (RUN_ID,),
                )
                conn.execute(
                    "UPDATE runs SET provider_call=0 WHERE run_id=?", (RUN_ID,)
                )

        cases = (
            ("occurrence_count", occurrence_count, "occurrence_equation_mismatch"),
            ("candidate_first", candidate_first, "candidate_first_occurrence_mismatch"),
            ("missing_page_one", missing_page_one, "required_lane_page_missing"),
            (
                "missing_provider_evidence",
                missing_provider_evidence,
                "required_lane_endpoint_attempt_missing",
            ),
            ("attempt_gap", attempt_gap, "attempt_ledger_invalid"),
            ("attempt_state", attempt_state, "attempt_ledger_invalid"),
            ("attempt_count", attempt_count, "attempt_ledger_invalid"),
            ("attempt_budget", attempt_budget, "attempt_ledger_invalid"),
            ("attempt_flags", attempt_flags, "attempt_ledger_invalid"),
        )
        for label, mutate, expected_code in cases:
            with self.subTest(case=label):
                store, archive, root = self._full_operational_case()
                mutate(store, archive, root)
                result = validate_backfill(
                    store,
                    archive,
                    run_id=RUN_ID,
                    seed_baseline=self.baseline,
                    scope="full",
                    replay_db=None,
                    run_root=root,
                )
                self.assertEqual(result["status"], "rejected")
                expected_codes = {expected_code, "replay_required"}
                if label == "occurrence_count":
                    expected_codes.add("invalid_discovery_occurrence")
                if label == "missing_page_one":
                    expected_codes.add("required_lane_endpoint_attempt_missing")
                self.assertEqual(_issue_codes(result), expected_codes)

    def test_result_is_exact_deterministic_prioritized_and_secret_free(self):
        store, archive, root = self._case()
        secret = "fixture-secret-webhook-token"
        raw_url = "https://example.invalid/private/raw"
        cursor = "private-cursor-value"
        self._sql(
            store.path,
            "UPDATE backfill_manifests SET keyword_config_sha256=? WHERE run_id=?",
            (secret, RUN_ID),
        )
        self._sql(
            store.path,
            "UPDATE reddit_threads SET title=? WHERE post_id='seed_post_000'",
            (f"{raw_url} {cursor} {secret}",),
        )
        self._sql(
            store.path,
            "INSERT INTO delivery_previews VALUES "
            "('delivery-secret', ?, 'dingtalk', 'dry-run', 'prepared', ?, ?, 0)",
            (RUN_ID, secret, json.dumps([raw_url, cursor])),
        )
        live_send = root / "nested" / "forbidden-live-send.json"
        live_send.parent.mkdir()
        live_send.write_text(secret, encoding="utf-8")

        first = self._validate_seed(store, archive, run_root=root)
        second = self._validate_seed(store, archive, run_root=root)

        self.assertEqual(tuple(first), RESULT_KEYS)
        self.assertEqual(first["status"], "rejected")
        self.assertEqual(first["stop_reason"], "live_send_boundary_violation")
        self.assertEqual(
            json.dumps(first, ensure_ascii=False, separators=(",", ":")),
            json.dumps(second, ensure_ascii=False, separators=(",", ":")),
        )
        check_codes: list[str] = []
        for check in first["checks"]:
            self.assertEqual(tuple(check), ("code", "ok", "actual", "expected"))
            self.assertIs(type(check["ok"]), bool)
            self.assertIn(type(check["actual"]), {str, int, bool, type(None)})
            self.assertIn(type(check["expected"]), {str, int, bool, type(None)})
            check_codes.append(str(check["code"]))
        self.assertEqual(len(check_codes), len(set(check_codes)))

        expected_count_keys = (
            "manifests",
            "runs",
            "seed_files",
            "raw_artifacts",
            "raw_captures",
            "threads",
            "comments",
            "analyses",
            "delivery_previews",
            "provider_attempts",
            "checkpoints",
            "candidates",
            "discovery_occurrences",
            "detail_batches",
            "detail_batch_members",
        )
        expected_candidate_keys = (
            "pending",
            "duplicate_existing_structured",
            "hydrated",
            "excluded",
            "outside_window_detail",
            "failed",
            "budget_deferred",
        )
        expected_occurrence_keys = (
            "new_candidate",
            "duplicate_occurrence",
            "outside_window",
            "duplicate_existing_structured",
            "invalid",
        )
        for field, expected_keys in (
            ("counts", expected_count_keys),
            ("candidate_status_counts", expected_candidate_keys),
            ("occurrence_disposition_counts", expected_occurrence_keys),
        ):
            self.assertEqual(tuple(first[field]), expected_keys)
            self.assertTrue(
                all(type(value) is int for value in first[field].values())
            )

        expected_fingerprint_tables = (
            "runs",
            "backfill_raw_artifacts",
            "raw_captures",
            "reddit_threads",
            "reddit_comments",
            "analysis_results",
        )
        self.assertEqual(
            tuple(first["source_fingerprints"]), expected_fingerprint_tables
        )
        for table, fingerprint in first["source_fingerprints"].items():
            expected_keys = (
                "row_count",
                "id_set_sha256",
                "canonical_rows_sha256",
            )
            if table in {"backfill_raw_artifacts", "raw_captures"}:
                expected_keys += ("raw_payload_hash_set_sha256",)
            self.assertEqual(tuple(fingerprint), expected_keys)
            self.assertIs(type(fingerprint["row_count"]), int)
            for key in expected_keys[1:]:
                self.assertRegex(str(fingerprint[key]), r"\A[0-9a-f]{64}\Z")
        self.assertIsNone(first["replay_fingerprints"])

        issue_sort_keys: list[tuple[str, str, str, str]] = []
        for issue in first["issues"]:
            self.assertEqual(
                tuple(issue), ("code", "severity", "entity_type", "entity_hash")
            )
            self.assertRegex(str(issue["entity_hash"]), r"\A[0-9a-f]{64}\Z")
            issue_sort_keys.append(
                (
                    str(issue["severity"]),
                    str(issue["code"]),
                    str(issue["entity_type"]),
                    str(issue["entity_hash"]),
                )
            )
        self.assertEqual(issue_sort_keys, sorted(issue_sort_keys))
        self.assertGreaterEqual(len(first["issues"]), 3)
        operational_metadata = first["operational_metadata"]
        self.assertEqual(
            tuple(operational_metadata),
            (
                "mode",
                "failure_only_metadata",
                "metadata_mirrored_count",
                "provider_attempts",
            ),
        )
        self.assertIs(type(operational_metadata["mode"]), str)
        self.assertIs(type(operational_metadata["failure_only_metadata"]), str)
        self.assertIs(type(operational_metadata["metadata_mirrored_count"]), int)
        self.assertIs(type(operational_metadata["provider_attempts"]), str)
        self.assertEqual(
            operational_metadata,
            {
                "mode": "constraints_checked",
                "failure_only_metadata": "none",
                "metadata_mirrored_count": 0,
                "provider_attempts": "source_only_not_replayed",
            },
        )
        expected_required_lanes = [
            {
                "lane_type": "dynamic_search",
                "lane_key_sha256": sha256(term.encode()).hexdigest(),
                "status": "not_run",
            }
            for term in DEFAULT_TIKHUB_SEARCH_TERMS
        ]
        self.assertEqual(first["required_lanes"], expected_required_lanes)
        for lane in first["required_lanes"]:
            self.assertEqual(
                tuple(lane), ("lane_type", "lane_key_sha256", "status")
            )
            self.assertIs(type(lane["lane_type"]), str)
            self.assertIs(type(lane["lane_key_sha256"]), str)
            self.assertIs(type(lane["status"]), str)
            self.assertIn(lane["lane_type"], {"dynamic_search", "subreddit_feed"})
            self.assertRegex(str(lane["lane_key_sha256"]), r"\A[0-9a-f]{64}\Z")
            self.assertEqual(lane["status"], "not_run")
        serialized = json.dumps(first, ensure_ascii=False, separators=(",", ":"))
        for forbidden in (str(root), secret, raw_url, cursor, "seed_post_000"):
            self.assertNotIn(forbidden, serialized)

    def test_false_success_rejects_lineage_orphans_and_entity_parity(self):
        def cross_run_raw(path: Path) -> None:
            with sqlite3.connect(path) as conn:
                conn.execute("PRAGMA foreign_keys=OFF")
                conn.execute(
                    "INSERT INTO runs VALUES ('other_run','seed_complete',?,?,0,0)",
                    (WINDOW_START.isoformat(), EFFECTIVE_END.isoformat()),
                )
                conn.execute(
                    "INSERT INTO raw_captures VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        "other_capture",
                        "other_run",
                        "historical_seed",
                        "seed://other",
                        CAPTURED_AT.isoformat(),
                        "local_seed",
                        "sha256:" + "9" * 64,
                        "json",
                        "ok",
                        None,
                        None,
                        None,
                        0,
                    ),
                )
                conn.execute(
                    "UPDATE reddit_threads SET raw_capture_id='other_capture' "
                    "WHERE post_id='seed_post_000'"
                )

        mutations = (
            ("cross_run_raw", cross_run_raw, "raw_cross_run"),
            (
                "orphan_comment",
                lambda path: self._sql(
                    path,
                    "UPDATE reddit_comments SET post_id='missing_post' "
                    "WHERE comment_id=(SELECT comment_id FROM reddit_comments LIMIT 1)",
                ),
                "orphan_comment",
            ),
            (
                "analysis_missing",
                lambda path: self._sql(
                    path,
                    "DELETE FROM analysis_results WHERE source_type='post' "
                    "AND source_id='seed_post_000'",
                ),
                "analysis_parity_mismatch",
            ),
            (
                "analysis_extra",
                lambda path: self._sql(
                    path,
                    "INSERT INTO analysis_results SELECT 'analysis_extra', run_id, source_type, "
                    "source_id, analysis_version, sentiment_label, sentiment_score, topic, "
                    "severity, confidence, pain_points, provider_call FROM analysis_results LIMIT 1",
                ),
                "analysis_parity_mismatch",
            ),
            (
                "analysis_wrong_type",
                lambda path: self._sql(
                    path,
                    "UPDATE analysis_results SET source_type='comment' "
                    "WHERE analysis_id='analysis_post_seed_post_000'",
                ),
                "analysis_parity_mismatch",
            ),
            (
                "analysis_provider_call",
                lambda path: self._sql(
                    path,
                    "UPDATE analysis_results SET provider_call=1 "
                    "WHERE analysis_id='analysis_post_seed_post_000'",
                ),
                "analysis_provider_call",
            ),
            (
                "parsed_comment_count",
                lambda path: self._sql(
                    path,
                    "UPDATE reddit_threads SET parsed_comment_count=parsed_comment_count+1 "
                    "WHERE post_id='seed_post_000'",
                ),
                "parsed_comment_count_mismatch",
            ),
            (
                "coverage",
                lambda path: self._sql(
                    path,
                    "UPDATE reddit_threads SET coverage_grade='full' "
                    "WHERE post_id='seed_post_000'",
                ),
                "coverage_mismatch",
            ),
            (
                "end_boundary_thread",
                lambda path: self._sql(
                    path,
                    "UPDATE reddit_threads SET created_at_utc=? WHERE post_id='seed_post_000'",
                    (EFFECTIVE_END.isoformat(),),
                ),
                "thread_outside_window",
            ),
        )
        for label, mutate, expected_code in mutations:
            with self.subTest(case=label):
                store, archive, _ = self._case()
                mutate(store.path)
                result = self._validate_seed(store, archive)
                self.assertEqual(result["status"], "rejected")
                self.assertIn(expected_code, _issue_codes(result))

    def test_false_success_rejects_occurrence_candidate_and_required_lane_mismatch(self):
        first_term = DEFAULT_TIKHUB_SEARCH_TERMS[0]

        def checkpoint(path: Path, *, status: str, stop_reason: str | None, page: int) -> None:
            with sqlite3.connect(path) as conn:
                conn.execute(
                    "INSERT INTO backfill_checkpoints VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        RUN_ID,
                        "dynamic_search",
                        first_term,
                        None,
                        None,
                        page,
                        None,
                        None,
                        0,
                        0,
                        0,
                        CAPTURED_AT.isoformat(),
                        None,
                        status,
                        stop_reason,
                        "data.after",
                        "6" * 64,
                        0,
                    ),
                )

        def occurrence_equation(path: Path) -> None:
            with sqlite3.connect(path) as conn:
                artifact_id = conn.execute(
                    "SELECT artifact_id FROM backfill_raw_artifacts ORDER BY artifact_id LIMIT 1"
                ).fetchone()[0]
                conn.execute(
                    "INSERT INTO backfill_checkpoints VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        RUN_ID,
                        "dynamic_search",
                        first_term,
                        None,
                        None,
                        1,
                        None,
                        None,
                        2,
                        0,
                        0,
                        CAPTURED_AT.isoformat(),
                        None,
                        "complete",
                        "cursor_exhausted",
                        "data.after",
                        "6" * 64,
                        0,
                    ),
                )
                conn.execute(
                    "INSERT INTO backfill_discovery_occurrences VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        RUN_ID,
                        "dynamic_search",
                        first_term,
                        1,
                        0,
                        None,
                        None,
                        None,
                        artifact_id,
                        CAPTURED_AT.isoformat(),
                        "invalid",
                    ),
                )

        def candidate_first_mismatch(path: Path) -> None:
            with sqlite3.connect(path) as conn:
                artifact_id = conn.execute(
                    "SELECT artifact_id FROM backfill_raw_artifacts ORDER BY artifact_id LIMIT 1"
                ).fetchone()[0]
                conn.execute(
                    "INSERT INTO backfill_discovery_occurrences VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        RUN_ID,
                        "dynamic_search",
                        first_term,
                        1,
                        0,
                        "candidate_post",
                        "local://candidate",
                        WINDOW_START.isoformat(),
                        artifact_id,
                        CAPTURED_AT.isoformat(),
                        "new_candidate",
                    ),
                )
                conn.execute(
                    "INSERT INTO backfill_candidates VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        RUN_ID,
                        "candidate_post",
                        "dynamic_search",
                        "wrong_term",
                        CAPTURED_AT.isoformat(),
                        "local://candidate",
                        WINDOW_START.isoformat(),
                        artifact_id,
                        "pending",
                        None,
                        CAPTURED_AT.isoformat(),
                    ),
                )

        def invalid_occurrence(path: Path) -> None:
            with sqlite3.connect(path) as conn:
                artifact_id = conn.execute(
                    "SELECT artifact_id FROM backfill_raw_artifacts "
                    "ORDER BY artifact_id LIMIT 1"
                ).fetchone()[0]
                conn.execute(
                    "INSERT INTO backfill_checkpoints VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        RUN_ID,
                        "dynamic_search",
                        first_term,
                        None,
                        None,
                        1,
                        None,
                        None,
                        1,
                        0,
                        0,
                        CAPTURED_AT.isoformat(),
                        None,
                        "complete",
                        "cursor_exhausted",
                        "data.after",
                        "6" * 64,
                        0,
                    ),
                )
                conn.execute(
                    "INSERT INTO backfill_discovery_occurrences VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        RUN_ID,
                        "dynamic_search",
                        first_term,
                        1,
                        0,
                        None,
                        None,
                        None,
                        artifact_id,
                        CAPTURED_AT.isoformat(),
                        "invalid",
                    ),
                )

        cases: tuple[tuple[str, object, str], ...] = (
            (
                "occurrence_equation",
                occurrence_equation,
                "occurrence_equation_mismatch",
            ),
            (
                "candidate_first_occurrence",
                candidate_first_mismatch,
                "candidate_first_occurrence_mismatch",
            ),
            (
                "invalid_occurrence",
                invalid_occurrence,
                "invalid_discovery_occurrence",
            ),
            (
                "required_hash",
                lambda path: self._sql(
                    path,
                    "UPDATE backfill_manifests SET required_lanes_sha256=? WHERE run_id=?",
                    ("0" * 64, RUN_ID),
                ),
                "required_lanes_hash_mismatch",
            ),
            (
                "unconfigured_lane",
                lambda path: self._sql(
                    path,
                    "INSERT INTO backfill_checkpoints VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        RUN_ID,
                        "dynamic_search",
                        "not_reviewed",
                        None,
                        None,
                        0,
                        None,
                        None,
                        0,
                        0,
                        0,
                        None,
                        None,
                        "prepared",
                        None,
                        None,
                        None,
                        0,
                    ),
                ),
                "unconfigured_lane",
            ),
            (
                "empty_search_terms",
                lambda path: self._sql(
                    path,
                    "UPDATE backfill_manifests SET search_terms_json='[]' WHERE run_id=?",
                    (RUN_ID,),
                ),
                "search_terms_invalid",
            ),
            (
                "truncated_search_terms",
                lambda path: self._sql(
                    path,
                    "UPDATE backfill_manifests SET search_terms_json=? WHERE run_id=?",
                    (json.dumps([DEFAULT_TIKHUB_SEARCH_TERMS[0]]), RUN_ID),
                ),
                "search_terms_invalid",
            ),
            (
                "reordered_search_terms",
                lambda path: self._sql(
                    path,
                    "UPDATE backfill_manifests SET search_terms_json=? WHERE run_id=?",
                    (
                        json.dumps(list(reversed(DEFAULT_TIKHUB_SEARCH_TERMS))),
                        RUN_ID,
                    ),
                ),
                "search_terms_invalid",
            ),
            (
                "sweep_empty_subreddits",
                lambda path: self._sql(
                    path,
                    "UPDATE backfill_manifests SET include_subreddit_sweep=1, "
                    "subreddits_json='[]' WHERE run_id=?",
                    (RUN_ID,),
                ),
                "subreddits_invalid",
            ),
            (
                "sweep_nonreviewed_subreddits",
                lambda path: self._sql(
                    path,
                    "UPDATE backfill_manifests SET include_subreddit_sweep=1, "
                    "subreddits_json='[\"wrong\"]' WHERE run_id=?",
                    (RUN_ID,),
                ),
                "subreddits_invalid",
            ),
            (
                "complete_zero_page",
                lambda path: checkpoint(path, status="complete", stop_reason="cursor_exhausted", page=0),
                "required_lane_zero_pages",
            ),
            (
                "missing_page_one_raw",
                lambda path: checkpoint(path, status="complete", stop_reason="cursor_exhausted", page=1),
                "required_lane_page_missing",
            ),
            (
                "missing_sent_endpoint_attempt",
                lambda path: checkpoint(path, status="complete", stop_reason="cursor_exhausted", page=1),
                "required_lane_endpoint_attempt_missing",
            ),
            (
                "running_lane",
                lambda path: checkpoint(path, status="running", stop_reason=None, page=0),
                "required_lane_nonterminal",
            ),
            (
                "partial_lane",
                lambda path: checkpoint(path, status="partial", stop_reason="budget_exhausted", page=1),
                "required_lane_nonterminal",
            ),
            (
                "bad_stop",
                lambda path: checkpoint(path, status="complete", stop_reason="budget_exhausted", page=1),
                "required_lane_bad_stop",
            ),
        )

        store, archive, root = self._case()
        missing = validate_backfill(
            store,
            archive,
            run_id=RUN_ID,
            seed_baseline=self.baseline,
            scope="full",
            replay_db=None,
            run_root=root,
        )
        self.assertIn("required_lane_missing", _issue_codes(missing))

        for label, mutate, expected_code in cases:
            with self.subTest(case=label):
                store, archive, root = self._case()
                mutate(store.path)
                result = validate_backfill(
                    store,
                    archive,
                    run_id=RUN_ID,
                    seed_baseline=self.baseline,
                    scope="full",
                    replay_db=None,
                    run_root=root,
                )
                self.assertEqual(result["status"], "rejected")
                self.assertIn(expected_code, _issue_codes(result))

    def test_false_success_rejects_attempt_delivery_archive_and_live_send_evidence(self):
        def attempt_gap(path: Path) -> None:
            with sqlite3.connect(path) as conn:
                conn.execute(
                    "UPDATE backfill_manifests SET max_provider_requests=3, "
                    "provider_request_count=2 WHERE run_id=?",
                    (RUN_ID,),
                )
                for number in (1, 3):
                    conn.execute(
                        "INSERT INTO backfill_provider_attempts VALUES "
                        "(?,?,?,?,?,?,?,?,?)",
                        (
                            RUN_ID,
                            number,
                            "/search",
                            "reserved",
                            CAPTURED_AT.isoformat(),
                            None,
                            None,
                            None,
                            None,
                        ),
                    )

        def attempt_state(path: Path) -> None:
            with sqlite3.connect(path) as conn:
                conn.execute(
                    "UPDATE backfill_manifests SET max_provider_requests=1, "
                    "provider_request_count=1 WHERE run_id=?",
                    (RUN_ID,),
                )
                conn.execute(
                    "INSERT INTO backfill_provider_attempts VALUES "
                    "(?,?,?,?,?,?,?,?,?)",
                    (
                        RUN_ID,
                        1,
                        "/search",
                        "succeeded",
                        CAPTURED_AT.isoformat(),
                        None,
                        None,
                        200,
                        None,
                    ),
                )

        def attempt_count(path: Path) -> None:
            with sqlite3.connect(path) as conn:
                conn.execute(
                    "UPDATE backfill_manifests SET max_provider_requests=2, "
                    "provider_request_count=2 WHERE run_id=?",
                    (RUN_ID,),
                )
                conn.execute(
                    "INSERT INTO backfill_provider_attempts VALUES "
                    "(?,?,?,?,?,?,?,?,?)",
                    (
                        RUN_ID,
                        1,
                        "/search",
                        "reserved",
                        CAPTURED_AT.isoformat(),
                        None,
                        None,
                        None,
                        None,
                    ),
                )

        database_cases = (
            ("attempt_gap", attempt_gap, "attempt_ledger_invalid"),
            ("attempt_state", attempt_state, "attempt_ledger_invalid"),
            ("attempt_count", attempt_count, "attempt_ledger_invalid"),
            (
                "delivery_row",
                lambda path: self._sql(
                    path,
                    "INSERT INTO delivery_previews VALUES "
                    "('delivery-fixture', ?, 'dingtalk', 'dry-run', 'prepared', "
                    "'message-hash', '[]', 0)",
                    (RUN_ID,),
                ),
                "delivery_boundary_violation",
            ),
            (
                "artifact_capture_mismatch",
                lambda path: self._sql(
                    path,
                    "UPDATE raw_captures SET raw_payload_hash='sha256:' || ? "
                    "WHERE raw_capture_id=(SELECT raw_capture_id FROM raw_captures LIMIT 1)",
                    ("8" * 64,),
                ),
                "artifact_capture_mismatch",
            ),
        )
        for label, mutate, expected_code in database_cases:
            with self.subTest(case=label):
                store, archive, _ = self._case()
                mutate(store.path)
                result = self._validate_seed(store, archive)
                self.assertEqual(result["status"], "rejected")
                self.assertIn(expected_code, _issue_codes(result))

        with self.subTest(case="gzip_tamper"):
            store, archive, _ = self._case()
            with sqlite3.connect(store.path) as conn:
                relative = conn.execute(
                    "SELECT relative_path FROM backfill_raw_artifacts ORDER BY artifact_id LIMIT 1"
                ).fetchone()[0]
            path = archive.root / relative
            path.write_bytes(path.read_bytes() + b"tamper")
            result = self._validate_seed(store, archive)
            self.assertEqual(result["status"], "rejected")
            self.assertIn("archive_integrity_failed", _issue_codes(result))

        with self.subTest(case="untracked_archive"):
            store, archive, _ = self._case()
            untracked = archive.root / RUN_ID / "seed" / "untracked.json.gz"
            untracked.parent.mkdir(parents=True, exist_ok=True)
            untracked.write_bytes(b"not tracked")
            result = self._validate_seed(store, archive)
            self.assertEqual(result["status"], "rejected")
            self.assertIn("untracked_archive_file", _issue_codes(result))

        with self.subTest(case="live_send_artifact"):
            store, archive, root = self._case()
            live_send = root / "nested" / "forbidden-live-send.json"
            live_send.parent.mkdir()
            live_send.write_text("{}", encoding="utf-8")
            result = self._validate_seed(store, archive, run_root=root)
            self.assertEqual(result["status"], "rejected")
            self.assertEqual(result["run_root_scan"], "failed")
            self.assertIn("live_send_artifact_found", _issue_codes(result))

    def test_seed_replay_reconstructs_from_raw_not_source_structured_rows(self):
        store, archive, root = self._case()
        clean_target = root / "seed-replay-clean.sqlite3"
        clean = replay_from_archive(
            store, archive, target_db=clean_target, run_id=RUN_ID
        )
        self.assertEqual(clean["status"], "complete")
        self.assertTrue(clean["fingerprints"]["equivalent"])
        with sqlite3.connect(clean_target) as conn:
            clean_title = conn.execute(
                "SELECT title FROM reddit_threads WHERE post_id='seed_post_000'"
            ).fetchone()[0]
            clean_topic = conn.execute(
                "SELECT topic FROM analysis_results "
                "WHERE analysis_id='analysis_post_seed_post_000'"
            ).fetchone()[0]
            clean_attempts = conn.execute(
                "SELECT COUNT(*) FROM backfill_provider_attempts"
            ).fetchone()[0]

        self._sql(
            store.path,
            "UPDATE reddit_threads SET title='tampered-source-title' "
            "WHERE post_id='seed_post_000'",
        )
        self._sql(
            store.path,
            "UPDATE analysis_results SET topic='tampered_source_topic' "
            "WHERE analysis_id='analysis_post_seed_post_000'",
        )
        target = root / "seed-replay-mismatch.sqlite3"

        result = replay_from_archive(
            store, archive, target_db=target, run_id=RUN_ID
        )

        self.assertEqual(tuple(result), REPLAY_RESULT_KEYS)
        self.assertEqual(result["schema_version"], "backfill_replay_v1")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["stop_reason"], "replay_mismatch")
        self.assertFalse(result["provider_attempt_made"])
        self.assertFalse(result["live_send"])
        self.assertFalse(result["fingerprints"]["equivalent"])
        self.assertEqual(
            result["fingerprints"]["target"], clean["fingerprints"]["target"]
        )
        self.assertNotEqual(
            result["fingerprints"]["source"], result["fingerprints"]["target"]
        )
        self.assertFalse(target.exists())
        self.assertEqual(
            clean_title, "Momcozy wearable pump fixture seed_post_000"
        )
        self.assertNotEqual(clean_topic, "tampered_source_topic")
        self.assertEqual(clean_attempts, 0)

    def test_seed_replay_rejects_orphan_raw_artifact_without_ledger(self):
        run_id = "replay_orphan_seed_artifact"
        store, writer, archive, root = self._small_seed_case(
            (
                (
                    "tracked.json",
                    _payload(
                        post_id="tracked_seed",
                        created_at=WINDOW_START + timedelta(days=1),
                        comments=1,
                        partial=False,
                    ),
                ),
            ),
            run_id=run_id,
        )
        orphan_payload = _payload(
            post_id="orphan_seed",
            created_at=WINDOW_START + timedelta(days=2),
            comments=1,
            partial=False,
        )
        input_path_hash = sha256(b"orphan.json").hexdigest()
        payload_sha256 = sha256(orphan_payload).hexdigest()
        source_url = f"seed://{input_path_hash}"
        raw_capture_id = _raw_capture_id(
            run_id=run_id,
            source_method="historical_seed",
            source_url=source_url,
            payload_sha256=payload_sha256,
        )
        orphan_artifact = writer.write(
            run_id=run_id,
            artifact_kind="seed",
            lane_type="seed",
            lane_key=input_path_hash,
            identity=payload_sha256,
            payload=orphan_payload,
            raw_capture_id=raw_capture_id,
            parser_kind="seed_browser_thread",
            source_method="historical_seed",
            source_url=source_url,
            source_endpoint="seed_file",
            captured_at_utc=CAPTURED_AT + timedelta(seconds=1),
            page_number=0,
        )
        store.persist_raw_capture_artifact(
            RawCapture(
                raw_capture_id=raw_capture_id,
                run_id=run_id,
                source_method="historical_seed",
                source_url=source_url,
                captured_at_utc=CAPTURED_AT + timedelta(seconds=1),
                auth_boundary="local_seed",
                raw_payload_hash=f"sha256:{payload_sha256}",
                payload_format="json",
            ),
            orphan_artifact,
        )
        target = root / "orphan-seed-replay.sqlite3"

        result = replay_from_archive(
            store, archive, target_db=target, run_id=run_id
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["stop_reason"], "seed_lineage_invalid")
        self.assertFalse(result["provider_attempt_made"])
        self.assertFalse(result["live_send"])
        self.assertFalse(target.exists())

    def test_seed_duplicate_replay_uses_source_ledger_precedence(self):
        run_id = "replay_seed_duplicate"
        winner = json.loads(
            _payload(
                post_id="duplicate_post",
                created_at=WINDOW_START + timedelta(days=5),
                comments=1,
                partial=False,
            ).decode("utf-8")
        )
        duplicate = json.loads(json.dumps(winner))
        winner[0]["data"]["children"][0]["data"]["title"] = "Momcozy winner payload"
        duplicate[0]["data"]["children"][0]["data"]["title"] = (
            "Momcozy duplicate payload"
        )
        winner_bytes = _canonical_json_bytes(winner)
        duplicate_bytes = _canonical_json_bytes(duplicate)

        def predicted_artifact_id(name: str, payload: bytes) -> str:
            input_hash = sha256(name.encode()).hexdigest()
            lane_hash = sha256(input_hash.encode()).hexdigest()
            payload_hash = sha256(payload).hexdigest()
            identity_hash = sha256(payload_hash.encode()).hexdigest()
            relative = (
                Path(run_id)
                / "seed"
                / lane_hash[:16]
                / (
                    f"page-000000-{identity_hash[:24]}-"
                    f"{payload_hash[:16]}.json.gz"
                )
            ).as_posix()
            return "raw_artifact_" + sha256(relative.encode()).hexdigest()[:24]

        names = None
        for index in range(100):
            winner_name = f"{index:03d}-winner.json"
            duplicate_name = f"{index + 100:03d}-duplicate.json"
            if predicted_artifact_id(
                duplicate_name, duplicate_bytes
            ) < predicted_artifact_id(winner_name, winner_bytes):
                names = winner_name, duplicate_name
                break
        self.assertIsNotNone(names)
        winner_name, duplicate_name = names
        store, _writer, archive, root = self._small_seed_case(
            ((winner_name, winner_bytes), (duplicate_name, duplicate_bytes)),
            run_id=run_id,
        )
        with sqlite3.connect(store.path) as conn:
            rows = conn.execute(
                "SELECT seed.outcome, artifact.artifact_id "
                "FROM backfill_seed_files AS seed "
                "JOIN backfill_raw_artifacts AS artifact "
                "ON artifact.run_id=seed.run_id AND artifact.artifact_id=seed.artifact_id "
                "ORDER BY artifact.artifact_id"
            ).fetchall()
        self.assertEqual(rows[0][0], "duplicate")
        target = root / "duplicate-replay.sqlite3"

        result = replay_from_archive(
            store, archive, target_db=target, run_id=run_id
        )

        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["fingerprints"]["equivalent"])
        with sqlite3.connect(target) as conn:
            title = conn.execute(
                "SELECT title FROM reddit_threads WHERE post_id='duplicate_post'"
            ).fetchone()[0]
            outcomes = conn.execute(
                "SELECT outcome, COUNT(*) FROM backfill_seed_files GROUP BY outcome"
            ).fetchall()
        self.assertEqual(title, "Momcozy winner payload")
        self.assertEqual(dict(outcomes), {"duplicate": 1, "imported": 1})

    def test_discovery_replay_reconstructs_occurrences_and_initial_candidates(self):
        run_id = "replay_discovery"
        seed_id = "seed_existing"
        candidate_id = "discovered_candidate"
        store, writer, archive, root = self._small_seed_case(
            (
                (
                    "seed-existing.json",
                    _payload(
                        post_id=seed_id,
                        created_at=WINDOW_START + timedelta(days=1),
                        comments=1,
                        partial=False,
                    ),
                ),
            ),
            run_id=run_id,
        )
        self._add_discovery_replay_source(
            store,
            writer,
            run_id=run_id,
            seed_post_id=seed_id,
            candidate_post_id=candidate_id,
        )
        target = root / "discovery-replay.sqlite3"

        result = replay_from_archive(
            store, archive, target_db=target, run_id=run_id
        )

        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["fingerprints"]["equivalent"])
        with sqlite3.connect(store.path) as source, sqlite3.connect(target) as replay:
            source_occurrences = source.execute(
                "SELECT * FROM backfill_discovery_occurrences ORDER BY page_number, ordinal"
            ).fetchall()
            replay_occurrences = replay.execute(
                "SELECT * FROM backfill_discovery_occurrences ORDER BY page_number, ordinal"
            ).fetchall()
            source_candidates = source.execute(
                "SELECT * FROM backfill_candidates ORDER BY post_id"
            ).fetchall()
            replay_candidates = replay.execute(
                "SELECT * FROM backfill_candidates ORDER BY post_id"
            ).fetchall()
            target_attempts = replay.execute(
                "SELECT COUNT(*) FROM backfill_provider_attempts"
            ).fetchone()[0]
        self.assertEqual(replay_occurrences, source_occurrences)
        self.assertEqual(replay_candidates, source_candidates)
        self.assertEqual(
            [row[-1] for row in replay_occurrences],
            [
                "new_candidate",
                "outside_window",
                "invalid",
                "duplicate_occurrence",
                "duplicate_existing_structured",
            ],
        )
        self.assertEqual(target_attempts, 0)

    def test_discovery_replay_preserves_zero_page_budget_checkpoint_only_lane(self):
        store, archive, root, run_id, expected_checkpoint = (
            self._zero_page_budget_checkpoint_case("accepted")
        )
        target = root / "zero-page-budget-replay.sqlite3"

        result = replay_from_archive(
            store, archive, target_db=target, run_id=run_id
        )

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["stop_reason"], "replay_complete")
        self.assertTrue(result["fingerprints"]["equivalent"])
        self.assertFalse(result["provider_attempt_made"])
        self.assertFalse(result["live_send"])
        self.assertTrue(target.exists())
        replay_store = BackfillStore(target)
        self.assertEqual(
            replay_store.load_checkpoint(
                run_id=run_id,
                lane_type="subreddit_feed",
                lane_key="ExclusivelyPumping",
            ),
            expected_checkpoint,
        )
        with sqlite3.connect(target) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM backfill_checkpoints WHERE run_id=?",
                    (run_id,),
                ).fetchone()[0],
                2,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM backfill_provider_attempts WHERE run_id=?",
                    (run_id,),
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT provider_request_count, provider_call, live_send "
                    "FROM backfill_manifests WHERE run_id=?",
                    (run_id,),
                ).fetchone(),
                (0, 0, 0),
            )

    def test_discovery_replay_accepts_authorized_historical_budget_boundary(self):
        store, archive, root, run_id, expected_checkpoint = (
            self._zero_page_budget_checkpoint_case("authorized_old_boundary")
        )
        store.extend_full_collection_budget(
            run_id,
            expected_provider_request_count=2,
            expected_max_provider_requests=2,
            new_max_provider_requests_total=4,
            discovery_request_ceiling=3,
            lane_page_ceilings_sha256="d" * 64,
            include_subreddit_sweep=True,
            required_lanes_sha256=required_lanes_sha256(
                search_terms=("Momcozy",),
                subreddits=("ExclusivelyPumping",),
                include_subreddit_sweep=True,
            ),
            authorization_sha256="e" * 64,
            updated_at_utc=CAPTURED_AT + timedelta(seconds=4),
        )
        target = root / "authorized-old-boundary-replay.sqlite3"

        result = replay_from_archive(
            store, archive, target_db=target, run_id=run_id
        )

        self.assertEqual(result["status"], "complete", result)
        self.assertEqual(
            BackfillStore(target).load_checkpoint(
                run_id=run_id,
                lane_type="subreddit_feed",
                lane_key="ExclusivelyPumping",
            ),
            expected_checkpoint,
        )
        with sqlite3.connect(target) as connection:
            self.assertEqual(
                sum(
                    connection.execute(
                        f"SELECT COUNT(*) FROM {table}"
                    ).fetchone()[0]
                    for table in (
                        "backfill_budget_extensions",
                        "backfill_hydration_resumes",
                    )
                ),
                0,
            )

    def test_discovery_replay_accepts_authorized_phase_budget_boundary(self):
        store, archive, root, run_id, _ = self._zero_page_budget_checkpoint_case(
            "authorized_phase_boundary"
        )
        store.extend_full_collection_budget(
            run_id,
            expected_provider_request_count=2,
            expected_max_provider_requests=2,
            new_max_provider_requests_total=4,
            discovery_request_ceiling=3,
            lane_page_ceilings_sha256="d" * 64,
            include_subreddit_sweep=True,
            required_lanes_sha256=required_lanes_sha256(
                search_terms=("Momcozy",),
                subreddits=("ExclusivelyPumping",),
                include_subreddit_sweep=True,
            ),
            authorization_sha256="e" * 64,
            updated_at_utc=CAPTURED_AT + timedelta(seconds=4),
        )
        request_number = store.reserve_provider_request(
            run_id,
            DYNAMIC_ENDPOINT,
            CAPTURED_AT + timedelta(seconds=5),
            request_ceiling=3,
        )
        self.assertEqual(request_number, 3)
        store.mark_provider_attempt_sent(
            run_id, request_number, CAPTURED_AT + timedelta(seconds=5)
        )
        store.complete_provider_attempt(
            run_id,
            request_number,
            status="succeeded",
            completed_at_utc=CAPTURED_AT + timedelta(seconds=5),
            http_status=200,
        )
        with sqlite3.connect(store.path) as connection:
            connection.execute(
                "UPDATE backfill_checkpoints SET provider_request_count=3, "
                "last_error='ProviderPhaseBudgetExhausted', "
                "stop_reason='discovery_budget_exhausted' "
                "WHERE run_id=? AND lane_type='subreddit_feed'",
                (run_id,),
            )
        target = root / "authorized-phase-boundary-replay.sqlite3"

        result = replay_from_archive(
            store, archive, target_db=target, run_id=run_id
        )

        self.assertEqual(result["status"], "complete", result)

    def test_discovery_replay_rejects_tampered_budget_extension_ledger(self):
        store, archive, root, run_id, _ = self._zero_page_budget_checkpoint_case(
            "tampered_extension"
        )
        store.extend_full_collection_budget(
            run_id,
            expected_provider_request_count=2,
            expected_max_provider_requests=2,
            new_max_provider_requests_total=4,
            discovery_request_ceiling=3,
            lane_page_ceilings_sha256="d" * 64,
            include_subreddit_sweep=True,
            required_lanes_sha256=required_lanes_sha256(
                search_terms=("Momcozy",),
                subreddits=("ExclusivelyPumping",),
                include_subreddit_sweep=True,
            ),
            authorization_sha256="e" * 64,
            updated_at_utc=CAPTURED_AT + timedelta(seconds=4),
        )
        with sqlite3.connect(store.path) as connection:
            connection.execute(
                "UPDATE backfill_budget_extensions "
                "SET required_lanes_sha256=? WHERE run_id=?",
                ("f" * 64, run_id),
            )
        target = root / "tampered-extension-replay.sqlite3"

        result = replay_from_archive(
            store, archive, target_db=target, run_id=run_id
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(
            result["stop_reason"], "budget_extension_ledger_invalid"
        )
        _assert_replay_temporary_absent(self, target)

    def test_discovery_replay_rejects_zero_page_checkpoint_tampering(self):
        cases = (
            ("page_number", "page_number=?", (1,)),
            ("page_number_real", "page_number=?", (0.5,)),
            ("cursor", "cursor=?", ("unexpected",)),
            ("cursor_empty", "cursor=?", ("",)),
            ("previous_cursor", "previous_cursor=?", ("unexpected",)),
            (
                "newest_seen_utc",
                "newest_seen_utc=?",
                (CAPTURED_AT.isoformat(),),
            ),
            (
                "oldest_seen_utc",
                "oldest_seen_utc=?",
                (CAPTURED_AT.isoformat(),),
            ),
            ("discovered_count", "discovered_count=?", (1,)),
            ("unique_count", "unique_count=?", (1,)),
            ("provider_request_count", "provider_request_count=?", (1,)),
            (
                "last_success_utc",
                "last_success_utc=?",
                (CAPTURED_AT.isoformat(),),
            ),
            ("last_error", "last_error=?", (None,)),
            ("status", "status=?", ("prepared",)),
            ("stop_reason", "stop_reason=?", (None,)),
            (
                "cursor_json_path",
                "cursor_json_path=?",
                ('["data","search","pageInfo","endCursor"]',),
            ),
            (
                "cursor_schema_sha256",
                "cursor_schema_sha256=?",
                ("0" * 64,),
            ),
            ("consecutive_old_pages", "consecutive_old_pages=?", (1,)),
            ("unconfigured_lane", "lane_key=?", ("NotConfigured",)),
        )
        for label, assignment, parameters in cases:
            with self.subTest(case=label):
                store, archive, root, run_id, _ = (
                    self._zero_page_budget_checkpoint_case(label)
                )
                with sqlite3.connect(store.path) as connection:
                    connection.execute(
                        f"UPDATE backfill_checkpoints SET {assignment} "
                        "WHERE run_id=? AND lane_type='subreddit_feed'",
                        (*parameters, run_id),
                    )
                target = root / f"zero-page-{label}-replay.sqlite3"

                result = replay_from_archive(
                    store, archive, target_db=target, run_id=run_id
                )

                self.assertEqual(result["status"], "failed")
                self.assertEqual(
                    result["stop_reason"], "discovery_checkpoint_mismatch"
                )
                self.assertFalse(result["provider_attempt_made"])
                self.assertFalse(result["live_send"])
                _assert_replay_temporary_absent(self, target)

    def test_discovery_replay_rejects_checkpoint_only_lane_before_budget_exhaustion(
        self,
    ):
        store, archive, root, run_id, _ = self._zero_page_budget_checkpoint_case(
            "manifest_not_exhausted"
        )
        with sqlite3.connect(store.path) as connection:
            connection.execute(
                "UPDATE backfill_manifests SET max_provider_requests=3 "
                "WHERE run_id=?",
                (run_id,),
            )
        target = root / "zero-page-manifest-not-exhausted-replay.sqlite3"

        result = replay_from_archive(
            store, archive, target_db=target, run_id=run_id
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["stop_reason"], "discovery_checkpoint_mismatch")
        self.assertFalse(result["provider_attempt_made"])
        self.assertFalse(result["live_send"])
        _assert_replay_temporary_absent(self, target)

    def test_discovery_replay_rejects_zero_page_checkpoint_for_nonpartial_run(self):
        store, archive, root, run_id, _ = self._zero_page_budget_checkpoint_case(
            "nonpartial_run"
        )
        with sqlite3.connect(store.path) as connection:
            connection.execute(
                "UPDATE backfill_manifests SET status='seed_complete' "
                "WHERE run_id=?",
                (run_id,),
            )
            connection.execute(
                "UPDATE runs SET status='seed_complete' WHERE run_id=?",
                (run_id,),
            )
        target = root / "zero-page-nonpartial-run-replay.sqlite3"

        result = replay_from_archive(
            store, archive, target_db=target, run_id=run_id
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["stop_reason"], "discovery_checkpoint_mismatch")
        self.assertFalse(result["provider_attempt_made"])
        self.assertFalse(result["live_send"])
        _assert_replay_temporary_absent(self, target)

    def test_discovery_replay_still_rejects_artifact_without_checkpoint(self):
        store, archive, root, run_id, _ = self._zero_page_budget_checkpoint_case(
            "artifact_without_checkpoint"
        )
        with sqlite3.connect(store.path) as connection:
            connection.execute(
                "DELETE FROM backfill_checkpoints "
                "WHERE run_id=? AND lane_type='dynamic_search' "
                "AND lane_key='Momcozy'",
                (run_id,),
            )
        target = root / "artifact-without-checkpoint-replay.sqlite3"

        result = replay_from_archive(
            store, archive, target_db=target, run_id=run_id
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["stop_reason"], "discovery_checkpoint_missing")
        self.assertFalse(result["provider_attempt_made"])
        self.assertFalse(result["live_send"])
        _assert_replay_temporary_absent(self, target)

    def test_discovery_replay_reconciles_canonicalized_invalid_row_order(
        self,
    ):
        run_id = "replay_discovery_canonicalized_invalid_order"
        seed_id = "seed_existing"
        candidate_id = "discovered_candidate"
        store, writer, archive, root = self._small_seed_case(
            (
                (
                    "seed-existing.json",
                    _payload(
                        post_id=seed_id,
                        created_at=WINDOW_START + timedelta(days=1),
                        comments=1,
                        partial=False,
                    ),
                ),
            ),
            run_id=run_id,
        )
        self._add_discovery_replay_source(
            store,
            writer,
            run_id=run_id,
            seed_post_id=seed_id,
            candidate_post_id=candidate_id,
            invalid_shapes=True,
        )
        target = root / "discovery-canonicalized-invalid-order-replay.sqlite3"

        result = replay_from_archive(
            store, archive, target_db=target, run_id=run_id
        )

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["stop_reason"], "replay_complete")
        self.assertTrue(result["fingerprints"]["equivalent"])
        self.assertFalse(result["provider_attempt_made"])
        self.assertFalse(result["live_send"])
        self.assertTrue(target.exists())
        with sqlite3.connect(store.path) as source, sqlite3.connect(target) as replay:
            source_invalid = source.execute(
                "SELECT ordinal, post_id, source_url, post_created_at_utc, disposition "
                "FROM backfill_discovery_occurrences "
                "WHERE run_id=? AND page_number=1 AND disposition='invalid' "
                "ORDER BY ordinal",
                (run_id,),
            ).fetchall()
            replay_invalid = replay.execute(
                "SELECT ordinal, post_id, source_url, post_created_at_utc, disposition "
                "FROM backfill_discovery_occurrences "
                "WHERE run_id=? AND page_number=1 AND disposition='invalid' "
                "ORDER BY ordinal",
                (run_id,),
            ).fetchall()
        self.assertEqual(replay_invalid, source_invalid)
        self.assertEqual(
            source_invalid,
            [
                (2, None, None, None, "invalid"),
                (3, None, None, None, "invalid"),
                (
                    4,
                    "missing_title",
                    (
                        "https://www.reddit.com/r/ExclusivelyPumping/"
                        "comments/missing_title/title/"
                    ),
                    (WINDOW_START + timedelta(days=20)).isoformat(),
                    "invalid",
                ),
                (5, "partial_identity", None, None, "invalid"),
            ],
        )

    def test_discovery_replay_selects_parser_per_mixed_version_artifact(self):
        run_id = "replay_discovery_mixed_parser_versions"
        seed_id = "seed_existing"
        candidate_id = "discovered_candidate"
        store, writer, archive, root = self._small_seed_case(
            (
                (
                    "seed-existing.json",
                    _payload(
                        post_id=seed_id,
                        created_at=WINDOW_START + timedelta(days=1),
                        comments=1,
                        partial=False,
                    ),
                ),
            ),
            run_id=run_id,
        )
        self._add_discovery_replay_source(
            store,
            writer,
            run_id=run_id,
            seed_post_id=seed_id,
            candidate_post_id=candidate_id,
            invalid_shapes=True,
            mixed_parser_versions=True,
        )
        target = root / "discovery-mixed-parser-versions-replay.sqlite3"

        result = replay_from_archive(
            store, archive, target_db=target, run_id=run_id
        )

        self.assertEqual(result["status"], "complete", result["stop_reason"])
        self.assertEqual(result["stop_reason"], "replay_complete")
        self.assertTrue(result["fingerprints"]["equivalent"])
        with sqlite3.connect(store.path) as source, sqlite3.connect(target) as replay:
            parser_kinds = source.execute(
                "SELECT parser_kind FROM backfill_raw_artifacts "
                "WHERE run_id=? AND artifact_kind='discovery' ORDER BY page_number",
                (run_id,),
            ).fetchall()
            source_occurrences = source.execute(
                "SELECT * FROM backfill_discovery_occurrences "
                "WHERE run_id=? ORDER BY page_number, ordinal",
                (run_id,),
            ).fetchall()
            replay_occurrences = replay.execute(
                "SELECT * FROM backfill_discovery_occurrences "
                "WHERE run_id=? ORDER BY page_number, ordinal",
                (run_id,),
            ).fetchall()
        self.assertEqual(
            parser_kinds,
            [("tikhub_discovery",), ("tikhub_discovery_strict_v2",)],
        )
        self.assertEqual(replay_occurrences, source_occurrences)
        self.assertNotIn(
            "v2_metadata_must_not_be_an_occurrence",
            {row[5] for row in replay_occurrences},
        )

    def test_discovery_replay_rejects_unknown_parser_kind(self):
        run_id = "replay_discovery_unknown_parser_kind"
        seed_id = "seed_existing"
        store, writer, archive, root = self._small_seed_case(
            (
                (
                    "seed-existing.json",
                    _payload(
                        post_id=seed_id,
                        created_at=WINDOW_START + timedelta(days=1),
                        comments=1,
                        partial=False,
                    ),
                ),
            ),
            run_id=run_id,
        )
        self._add_discovery_replay_source(
            store,
            writer,
            run_id=run_id,
            seed_post_id=seed_id,
            candidate_post_id="discovered_candidate",
        )
        unknown_parser = "tikhub_discovery_strict_v999"
        self._sql(
            store.path,
            "UPDATE backfill_raw_artifacts SET parser_kind=? "
            "WHERE run_id=? AND artifact_kind='discovery' AND page_number=2",
            (unknown_parser, run_id),
        )
        target = root / "discovery-unknown-parser-must-not-publish.sqlite3"

        result = replay_from_archive(
            store, archive, target_db=target, run_id=run_id
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["stop_reason"], "archive_metadata_invalid")
        self.assertFalse(result["provider_attempt_made"])
        self.assertFalse(result["live_send"])
        _assert_replay_temporary_absent(self, target)
        self.assertNotIn(unknown_parser, json.dumps(result, separators=(",", ":")))

    def test_discovery_replay_rejects_source_occurrence_tampering(self):
        for corruption in (
            "post_id",
            "ordinal",
            "raw_artifact_id",
            "discovered_at_utc",
        ):
            with self.subTest(corruption=corruption):
                run_id = f"replay_discovery_tamper_{corruption}"
                seed_id = "seed_existing"
                candidate_id = "discovered_candidate"
                store, writer, archive, root = self._small_seed_case(
                    (
                        (
                            "seed-existing.json",
                            _payload(
                                post_id=seed_id,
                                created_at=WINDOW_START + timedelta(days=1),
                                comments=1,
                                partial=False,
                            ),
                        ),
                    ),
                    run_id=run_id,
                )
                self._add_discovery_replay_source(
                    store,
                    writer,
                    run_id=run_id,
                    seed_post_id=seed_id,
                    candidate_post_id=candidate_id,
                    invalid_shapes=True,
                )
                with sqlite3.connect(store.path) as connection:
                    if corruption == "post_id":
                        connection.execute(
                            "UPDATE backfill_discovery_occurrences "
                            "SET post_id='tampered_partial_identity' "
                            "WHERE run_id=? AND page_number=1 AND ordinal=5",
                            (run_id,),
                        )
                    elif corruption == "ordinal":
                        connection.execute(
                            "UPDATE backfill_discovery_occurrences SET ordinal=9 "
                            "WHERE run_id=? AND page_number=1 AND ordinal=5",
                            (run_id,),
                        )
                    elif corruption == "raw_artifact_id":
                        page_two_artifact = connection.execute(
                            "SELECT artifact_id FROM backfill_raw_artifacts "
                            "WHERE run_id=? AND parser_kind='tikhub_discovery' "
                            "AND page_number=2",
                            (run_id,),
                        ).fetchone()[0]
                        connection.execute(
                            "UPDATE backfill_discovery_occurrences "
                            "SET raw_artifact_id=? "
                            "WHERE run_id=? AND page_number=1 AND ordinal=5",
                            (page_two_artifact, run_id),
                        )
                    else:
                        connection.execute(
                            "UPDATE backfill_discovery_occurrences "
                            "SET discovered_at_utc=? "
                            "WHERE run_id=? AND page_number=1 AND ordinal=5",
                            (
                                (CAPTURED_AT + timedelta(seconds=9)).isoformat(),
                                run_id,
                            ),
                        )
                target = root / f"discovery-tamper-{corruption}-replay.sqlite3"

                result = replay_from_archive(
                    store, archive, target_db=target, run_id=run_id
                )

                self.assertEqual(result["status"], "failed")
                self.assertEqual(
                    result["stop_reason"], "discovery_occurrence_mismatch"
                )
                self.assertFalse(result["provider_attempt_made"])
                self.assertFalse(result["live_send"])
                _assert_replay_temporary_absent(self, target)

    def test_detail_comment_replay_reconstructs_full_entity_and_first_page_lineage(self):
        run_id = "replay_detail_comments"
        seed_id = "seed_existing"
        post_id = "hydrated_candidate"
        store, writer, archive, root = self._small_seed_case(
            (
                (
                    "seed-existing.json",
                    _payload(
                        post_id=seed_id,
                        created_at=WINDOW_START + timedelta(days=1),
                        comments=1,
                        partial=False,
                    ),
                ),
            ),
            run_id=run_id,
        )
        self._add_discovery_replay_source(
            store,
            writer,
            run_id=run_id,
            seed_post_id=seed_id,
            candidate_post_id=post_id,
        )
        self._add_detail_comment_replay_source(
            store, writer, run_id=run_id, post_id=post_id
        )
        target = root / "detail-comments-replay.sqlite3"

        result = replay_from_archive(
            store, archive, target_db=target, run_id=run_id
        )

        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["fingerprints"]["equivalent"])
        with sqlite3.connect(target) as conn:
            thread = conn.execute(
                "SELECT parsed_comment_count, coverage_grade, matched_keywords "
                "FROM reddit_threads WHERE post_id=?",
                (post_id,),
            ).fetchone()
            comments = conn.execute(
                "SELECT comment_id, raw_capture_id, created_at_utc "
                "FROM reddit_comments WHERE post_id=? ORDER BY comment_id",
                (post_id,),
            ).fetchall()
            page_one_capture = conn.execute(
                "SELECT raw_capture_id FROM backfill_raw_artifacts "
                "WHERE lane_type='comments' AND page_number=1"
            ).fetchone()[0]
            member_rows = conn.execute(
                "SELECT ordinal, post_id FROM backfill_detail_batch_members"
            ).fetchall()
            analysis_count = conn.execute(
                "SELECT COUNT(*) FROM analysis_results WHERE source_id=? "
                "OR source_id IN (SELECT comment_id FROM reddit_comments WHERE post_id=?)",
                (post_id, post_id),
            ).fetchone()[0]
            candidate = conn.execute(
                "SELECT status, status_reason FROM backfill_candidates WHERE post_id=?",
                (post_id,),
            ).fetchone()
            attempts = conn.execute(
                "SELECT COUNT(*) FROM backfill_provider_attempts"
            ).fetchone()[0]
        self.assertEqual(thread[0:2], (3, "full"))
        self.assertIn("Momcozy", thread[2])
        self.assertEqual(len(comments), 3)
        duplicate = next(row for row in comments if row[0] == "t1_duplicate_comment")
        late = next(row for row in comments if row[0] == "t1_late_comment")
        self.assertEqual(duplicate[1], page_one_capture)
        self.assertGreater(datetime.fromisoformat(late[2]), EFFECTIVE_END)
        self.assertEqual(member_rows, [(0, post_id)])
        self.assertEqual(analysis_count, 4)
        self.assertEqual(candidate, ("hydrated", None))
        self.assertEqual(attempts, 0)

    def test_detail_replay_restores_exact_source_batches_without_regrouping(self):
        run_id = "replay_exact_detail_batches"
        seed_id = "seed_existing"
        post_id = "hydrated_candidate"
        store, writer, archive, root = self._small_seed_case(
            (
                (
                    "seed-existing.json",
                    _payload(
                        post_id=seed_id,
                        created_at=WINDOW_START + timedelta(days=1),
                        comments=1,
                        partial=False,
                    ),
                ),
            ),
            run_id=run_id,
        )
        self._add_discovery_replay_source(
            store,
            writer,
            run_id=run_id,
            seed_post_id=seed_id,
            candidate_post_id=post_id,
        )
        self._add_detail_comment_replay_source(
            store, writer, run_id=run_id, post_id=post_id
        )
        target = root / "exact-detail-batches-replay.sqlite3"

        with patch.object(
            BackfillStore,
            "prepare_detail_batches",
            side_effect=AssertionError("replay regrouped source detail members"),
        ):
            result = replay_from_archive(
                store, archive, target_db=target, run_id=run_id
            )

        self.assertEqual(result["status"], "complete")
        with sqlite3.connect(store.path) as source_conn, sqlite3.connect(
            target
        ) as target_conn:
            for table, order_by in (
                ("backfill_detail_batches", "batch_number"),
                ("backfill_detail_batch_members", "batch_id, ordinal"),
            ):
                source_rows = source_conn.execute(
                    f"SELECT * FROM {table} WHERE run_id=? ORDER BY {order_by}",
                    (run_id,),
                ).fetchall()
                target_rows = target_conn.execute(
                    f"SELECT * FROM {table} WHERE run_id=? ORDER BY {order_by}",
                    (run_id,),
                ).fetchall()
                self.assertEqual(target_rows, source_rows)

    def test_failure_only_outcome_is_metadata_mirrored_not_structured(self):
        run_id = "replay_failure_only"
        seed_id = "seed_existing"
        failed_id = "failed_candidate"
        store, writer, archive, root = self._small_seed_case(
            (
                (
                    "seed-existing.json",
                    _payload(
                        post_id=seed_id,
                        created_at=WINDOW_START + timedelta(days=1),
                        comments=1,
                        partial=False,
                    ),
                ),
            ),
            run_id=run_id,
        )
        self._add_discovery_replay_source(
            store,
            writer,
            run_id=run_id,
            seed_post_id=seed_id,
            candidate_post_id=failed_id,
        )
        store.finalize_candidate(
            run_id=run_id,
            post_id=failed_id,
            expected_statuses=("pending",),
            status="failed",
            status_reason="provider_error",
            updated_at_utc=CAPTURED_AT + timedelta(seconds=9),
        )
        target = root / "failure-only-replay.sqlite3"

        result = replay_from_archive(
            store, archive, target_db=target, run_id=run_id
        )

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["metadata_mirrored_count"], 1)
        self.assertEqual(result["provider_attempts"], "source_only_not_replayed")
        self.assertTrue(result["fingerprints"]["equivalent"])
        with sqlite3.connect(target) as conn:
            candidate = conn.execute(
                "SELECT status, status_reason FROM backfill_candidates WHERE post_id=?",
                (failed_id,),
            ).fetchone()
            thread_count = conn.execute(
                "SELECT COUNT(*) FROM reddit_threads WHERE post_id=?", (failed_id,)
            ).fetchone()[0]
            attempts = conn.execute(
                "SELECT COUNT(*) FROM backfill_provider_attempts"
            ).fetchone()[0]
        self.assertEqual(candidate, ("failed", "provider_error"))
        self.assertEqual(thread_count, 0)
        self.assertEqual(attempts, 0)

    def test_replay_validates_source_provider_attempts_without_copying_them(self):
        def make_case(
            label: str,
        ) -> tuple[BackfillStore, PrivateRawArchive, Path, str]:
            run_id = f"replay_provider_attempts_{label}"
            seed_id = f"seed_{label}"
            candidate_id = f"candidate_{label}"
            store, writer, archive, root = self._small_seed_case(
                (
                    (
                        "seed.json",
                        _payload(
                            post_id=seed_id,
                            created_at=WINDOW_START + timedelta(days=1),
                            comments=1,
                            partial=False,
                        ),
                    ),
                ),
                run_id=run_id,
            )
            self._add_discovery_replay_source(
                store,
                writer,
                run_id=run_id,
                seed_post_id=seed_id,
                candidate_post_id=candidate_id,
            )
            return store, archive, root, run_id

        valid_store, valid_archive, valid_root, valid_run_id = make_case("valid")
        valid_target = valid_root / "valid-attempts-replay.sqlite3"
        valid = replay_from_archive(
            valid_store,
            valid_archive,
            target_db=valid_target,
            run_id=valid_run_id,
        )
        self.assertEqual(valid["status"], "complete")
        with sqlite3.connect(valid_target) as conn:
            target_attempts = conn.execute(
                "SELECT COUNT(*) FROM backfill_provider_attempts"
            ).fetchone()[0]
            target_manifest = conn.execute(
                "SELECT provider_request_count, provider_call, live_send "
                "FROM backfill_manifests WHERE run_id=?",
                (valid_run_id,),
            ).fetchone()
            target_run = conn.execute(
                "SELECT provider_call, live_send FROM runs WHERE run_id=?",
                (valid_run_id,),
            ).fetchone()
        self.assertEqual(target_attempts, 0)
        self.assertEqual(target_manifest, (0, 0, 0))
        self.assertEqual(target_run, (0, 0))

        failed_store, failed_archive, failed_root, failed_run_id = make_case(
            "valid_failed"
        )
        self._sql(
            failed_store.path,
            "UPDATE backfill_provider_attempts SET status='failed', "
            "http_status=503, error_class='TimeoutError' "
            "WHERE run_id=? AND request_number=1",
            (failed_run_id,),
        )
        failed_target = failed_root / "valid-failed-attempt-replay.sqlite3"
        failed = replay_from_archive(
            failed_store,
            failed_archive,
            target_db=failed_target,
            run_id=failed_run_id,
        )
        self.assertEqual(failed["status"], "complete")
        with sqlite3.connect(failed_target) as conn:
            failed_target_attempts = conn.execute(
                "SELECT COUNT(*) FROM backfill_provider_attempts"
            ).fetchone()[0]
            failed_target_manifest = conn.execute(
                "SELECT provider_request_count, provider_call, live_send "
                "FROM backfill_manifests WHERE run_id=?",
                (failed_run_id,),
            ).fetchone()
            failed_target_run = conn.execute(
                "SELECT provider_call, live_send FROM runs WHERE run_id=?",
                (failed_run_id,),
            ).fetchone()
        self.assertEqual(failed_target_attempts, 0)
        self.assertEqual(failed_target_manifest, (0, 0, 0))
        self.assertEqual(failed_target_run, (0, 0))

        def force_over_budget(store: BackfillStore, run_id: str) -> None:
            with sqlite3.connect(store.path) as conn:
                conn.execute("PRAGMA ignore_check_constraints=ON")
                conn.execute(
                    "UPDATE backfill_manifests SET max_provider_requests=1 "
                    "WHERE run_id=?",
                    (run_id,),
                )

        corruptions = (
            (
                "request_gap",
                lambda store, run_id: self._sql(
                    store.path,
                    "UPDATE backfill_provider_attempts SET request_number=3 "
                    "WHERE run_id=? AND request_number=2",
                    (run_id,),
                ),
            ),
            (
                "count_budget_mismatch",
                lambda store, run_id: self._sql(
                    store.path,
                    "UPDATE backfill_manifests SET provider_request_count=1, "
                    "max_provider_requests=1 WHERE run_id=?",
                    (run_id,),
                ),
            ),
            ("over_budget", force_over_budget),
            (
                "manifest_flag_mismatch",
                lambda store, run_id: self._sql(
                    store.path,
                    "UPDATE backfill_manifests SET provider_call=0 WHERE run_id=?",
                    (run_id,),
                ),
            ),
            (
                "run_flag_mismatch",
                lambda store, run_id: self._sql(
                    store.path,
                    "UPDATE runs SET provider_call=0 WHERE run_id=?",
                    (run_id,),
                ),
            ),
            (
                "malformed_reserved_time",
                lambda store, run_id: self._sql(
                    store.path,
                    "UPDATE backfill_provider_attempts SET reserved_at_utc='bad-time' "
                    "WHERE run_id=? AND request_number=1",
                    (run_id,),
                ),
            ),
            (
                "naive_sent_time",
                lambda store, run_id: self._sql(
                    store.path,
                    "UPDATE backfill_provider_attempts "
                    "SET sent_at_utc='2026-07-11T04:18:00' "
                    "WHERE run_id=? AND request_number=1",
                    (run_id,),
                ),
            ),
            (
                "succeeded_without_sent_time",
                lambda store, run_id: self._sql(
                    store.path,
                    "UPDATE backfill_provider_attempts SET sent_at_utc=NULL "
                    "WHERE run_id=? AND request_number=1",
                    (run_id,),
                ),
            ),
            (
                "succeeded_without_completed_time",
                lambda store, run_id: self._sql(
                    store.path,
                    "UPDATE backfill_provider_attempts SET completed_at_utc=NULL "
                    "WHERE run_id=? AND request_number=1",
                    (run_id,),
                ),
            ),
            (
                "succeeded_with_error_class",
                lambda store, run_id: self._sql(
                    store.path,
                    "UPDATE backfill_provider_attempts "
                    "SET error_class='UnexpectedError' "
                    "WHERE run_id=? AND request_number=1",
                    (run_id,),
                ),
            ),
            (
                "failed_with_unsafe_error_class",
                lambda store, run_id: self._sql(
                    store.path,
                    "UPDATE backfill_provider_attempts SET status='failed', "
                    "error_class='unsafe-error' "
                    "WHERE run_id=? AND request_number=1",
                    (run_id,),
                ),
            ),
            (
                "failed_without_sent_time",
                lambda store, run_id: self._sql(
                    store.path,
                    "UPDATE backfill_provider_attempts SET status='failed', "
                    "sent_at_utc=NULL, error_class='TimeoutError' "
                    "WHERE run_id=? AND request_number=1",
                    (run_id,),
                ),
            ),
            (
                "failed_without_completed_time",
                lambda store, run_id: self._sql(
                    store.path,
                    "UPDATE backfill_provider_attempts SET status='failed', "
                    "completed_at_utc=NULL, error_class='TimeoutError' "
                    "WHERE run_id=? AND request_number=1",
                    (run_id,),
                ),
            ),
            (
                "noninteger_http_status",
                lambda store, run_id: self._sql(
                    store.path,
                    "UPDATE backfill_provider_attempts SET http_status='not-an-int' "
                    "WHERE run_id=? AND request_number=1",
                    (run_id,),
                ),
            ),
            (
                "inflight_reserved",
                lambda store, run_id: self._sql(
                    store.path,
                    "UPDATE backfill_provider_attempts SET status='reserved', "
                    "sent_at_utc=NULL, completed_at_utc=NULL, http_status=NULL, "
                    "error_class=NULL WHERE run_id=? AND request_number=1",
                    (run_id,),
                ),
            ),
            (
                "inflight_sent",
                lambda store, run_id: self._sql(
                    store.path,
                    "UPDATE backfill_provider_attempts SET status='sent', "
                    "completed_at_utc=NULL, http_status=NULL, error_class=NULL "
                    "WHERE run_id=? AND request_number=1",
                    (run_id,),
                ),
            ),
        )
        for label, mutate in corruptions:
            with self.subTest(case=label):
                store, archive, root, run_id = make_case(label)
                mutate(store, run_id)
                target = root / f"{label}-replay.sqlite3"

                result = replay_from_archive(
                    store,
                    archive,
                    target_db=target,
                    run_id=run_id,
                )

                self.assertEqual(result["status"], "failed")
                self.assertEqual(
                    result["stop_reason"], "source_provider_attempts_invalid"
                )
                self.assertFalse(result["provider_attempt_made"])
                self.assertFalse(result["live_send"])
                self.assertFalse(target.exists())

    def test_full_scope_requires_run_root_and_equivalent_replay(self):
        store, archive, root = self._full_operational_case()
        replay_db = root / "full-scope-replay.sqlite3"
        replay = replay_from_archive(
            store,
            archive,
            target_db=replay_db,
            run_id=RUN_ID,
        )
        self.assertEqual(replay["status"], "complete")
        self.assertTrue(replay["fingerprints"]["equivalent"])

        missing_replay = validate_backfill(
            store,
            archive,
            run_id=RUN_ID,
            seed_baseline=self.baseline,
            scope="full",
            replay_db=None,
            run_root=root,
        )
        self.assertEqual(missing_replay["status"], "rejected")
        self.assertEqual(missing_replay["stop_reason"], "replay_required")
        self.assertEqual(missing_replay["replay_status"], "required")
        self.assertIn("replay_required", _issue_codes(missing_replay))

        missing_root = validate_backfill(
            store,
            archive,
            run_id=RUN_ID,
            seed_baseline=self.baseline,
            scope="full",
            replay_db=replay_db,
            run_root=None,
        )
        self.assertEqual(missing_root["status"], "rejected")
        self.assertEqual(missing_root["stop_reason"], "replay_required")
        self.assertEqual(missing_root["replay_status"], "equivalent")
        self.assertEqual(missing_root["run_root_scan"], "not_run")
        self.assertIn("run_root_required", _issue_codes(missing_root))

        unreadable_replay = root / "unreadable-replay.sqlite3"
        unreadable_replay.write_bytes(b"not-a-sqlite-database")
        unreadable_before = _snapshot_regular_file(unreadable_replay)
        unreadable = validate_backfill(
            store,
            archive,
            run_id=RUN_ID,
            seed_baseline=self.baseline,
            scope="full",
            replay_db=unreadable_replay,
            run_root=root,
        )
        self.assertEqual(unreadable["status"], "rejected")
        self.assertEqual(unreadable["stop_reason"], "replay_failed")
        self.assertEqual(unreadable["replay_status"], "failed")
        self.assertIn("replay_unreadable", _issue_codes(unreadable))
        self.assertEqual(_snapshot_regular_file(unreadable_replay), unreadable_before)

        mismatched_replay = root / "mismatched-replay.sqlite3"
        shutil.copy2(replay_db, mismatched_replay)
        self._sql(
            mismatched_replay,
            "UPDATE reddit_threads SET title='same-id-different-title' "
            "WHERE post_id='seed_post_010'",
        )
        mismatch_before = _snapshot_db(mismatched_replay)
        mismatch = validate_backfill(
            store,
            archive,
            run_id=RUN_ID,
            seed_baseline=self.baseline,
            scope="full",
            replay_db=mismatched_replay,
            run_root=root,
        )
        self.assertEqual(mismatch["status"], "rejected")
        self.assertEqual(mismatch["stop_reason"], "replay_mismatch")
        self.assertEqual(mismatch["replay_status"], "mismatch")
        self.assertIn("replay_mismatch", _issue_codes(mismatch))
        self.assertNotEqual(
            mismatch["source_fingerprints"], mismatch["replay_fingerprints"]
        )
        self.assertEqual(_snapshot_db(mismatched_replay), mismatch_before)

        source_as_replay = validate_backfill(
            store,
            archive,
            run_id=RUN_ID,
            seed_baseline=self.baseline,
            scope="full",
            replay_db=store.path,
            run_root=root,
        )
        self.assertEqual(source_as_replay["status"], "rejected")
        self.assertEqual(source_as_replay["stop_reason"], "replay_failed")
        self.assertEqual(source_as_replay["replay_status"], "failed")
        self.assertIn(
            "replay_operational_boundary_invalid",
            _issue_codes(source_as_replay),
        )

        operational_mutations = (
            (
                "manifest_flags",
                "UPDATE backfill_manifests SET provider_call=1 WHERE run_id=?",
                (RUN_ID,),
            ),
            (
                "run_flags",
                "UPDATE runs SET provider_call=1 WHERE run_id=?",
                (RUN_ID,),
            ),
            (
                "attempt_row",
                "INSERT INTO backfill_provider_attempts VALUES "
                "(?,1,'/replay-forbidden','reserved',?,NULL,NULL,NULL,NULL)",
                (RUN_ID, CAPTURED_AT.isoformat()),
            ),
            (
                "delivery_row",
                "INSERT INTO delivery_previews VALUES "
                "('replay-delivery',?,'dingtalk','dry-run','prepared',"
                "'message-hash','[]',0)",
                (RUN_ID,),
            ),
        )
        for label, statement, parameters in operational_mutations:
            with self.subTest(replay_operational_boundary=label):
                operational_replay = root / f"operational-{label}.sqlite3"
                shutil.copy2(replay_db, operational_replay)
                self._sql(operational_replay, statement, parameters)
                operational_before = _snapshot_db(operational_replay)

                result = validate_backfill(
                    store,
                    archive,
                    run_id=RUN_ID,
                    seed_baseline=self.baseline,
                    scope="full",
                    replay_db=operational_replay,
                    run_root=root,
                )

                self.assertEqual(result["status"], "rejected")
                self.assertEqual(result["stop_reason"], "replay_failed")
                self.assertEqual(result["replay_status"], "failed")
                self.assertIn(
                    "replay_operational_boundary_invalid",
                    _issue_codes(result),
                )
                self.assertEqual(_snapshot_db(operational_replay), operational_before)

        source_before = _snapshot_db(store.path)
        replay_before = _snapshot_db(replay_db)
        archive_before = _snapshot_archive(archive.root)
        real_connect = sqlite3.connect
        tracked: list[_TrackingConnection] = []
        calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

        def connect(*args, **kwargs):
            calls.append((args, kwargs))
            wrapper = _TrackingConnection(real_connect(*args, **kwargs))
            tracked.append(wrapper)
            return wrapper

        with (
            patch(
                "reddit_voc.backfill_validation.sqlite3.connect",
                side_effect=connect,
            ),
            patch.object(
                BackfillStore,
                "connect",
                side_effect=AssertionError("validation used writable store connect"),
            ),
            patch.object(
                BackfillStore,
                "migrate",
                side_effect=AssertionError("validation migrated replay database"),
            ),
        ):
            accepted = validate_backfill(
                store,
                archive,
                run_id=RUN_ID,
                seed_baseline=self.baseline,
                scope="full",
                replay_db=replay_db,
                run_root=root,
            )

        self.assertEqual(accepted["status"], "accepted")
        self.assertEqual(accepted["stop_reason"], "full_validation_complete")
        self.assertEqual(accepted["replay_status"], "equivalent")
        self.assertTrue(accepted["full_ready"])
        self.assertEqual(
            accepted["replay_fingerprints"], accepted["source_fingerprints"]
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(tracked), 2)
        for (args, kwargs), connection in zip(calls, tracked, strict=True):
            self.assertIn("mode=ro", str(args[0]))
            self.assertNotIn("immutable=1", str(args[0]))
            self.assertTrue(kwargs["uri"])
            self.assertIn("PRAGMA query_only = ON", connection.statements)
            self.assertIn("PRAGMA foreign_keys = ON", connection.statements)
            self.assertIn("BEGIN", connection.statements)
            self.assertTrue(connection.rollback_called)
            self.assertTrue(connection.close_called)
        self.assertEqual(_snapshot_db(store.path), source_before)
        self.assertEqual(_snapshot_db(replay_db), replay_before)
        self.assertEqual(_snapshot_archive(archive.root), archive_before)

    def test_full_accepts_only_exact_three_baseline_bound_historical_seed_partials(self):
        base_store, base_archive, base_root = self._full_operational_case()
        base_replay = base_root / "partial-gate-replay.sqlite3"
        replay = replay_from_archive(
            base_store,
            base_archive,
            target_db=base_replay,
            run_id=RUN_ID,
        )
        self.assertEqual(replay["status"], "complete")

        accepted = validate_backfill(
            base_store,
            base_archive,
            run_id=RUN_ID,
            seed_baseline=self.baseline,
            scope="full",
            replay_db=base_replay,
            run_root=base_root,
        )
        self.assertEqual(accepted["status"], "accepted")
        self.assertEqual(accepted["known_seed_partial_count"], 3)
        self.assertEqual(
            accepted["known_seed_partial_post_ids_sha256"],
            self.baseline.known_partial_post_ids_sha256,
        )

        def mutate_known_full(conn: sqlite3.Connection) -> None:
            conn.execute(
                "UPDATE reddit_threads SET more_node_count=0, coverage_grade='full' "
                "WHERE post_id='seed_post_000'"
            )

        def mutate_known_missing(conn: sqlite3.Connection) -> None:
            conn.execute(
                "DELETE FROM analysis_results WHERE source_id='seed_post_000' "
                "OR source_id IN (SELECT comment_id FROM reddit_comments "
                "WHERE post_id='seed_post_000')"
            )
            conn.execute(
                "DELETE FROM reddit_comments WHERE post_id='seed_post_000'"
            )
            conn.execute("DELETE FROM reddit_threads WHERE post_id='seed_post_000'")

        def mutate_replacement(conn: sqlite3.Connection) -> None:
            mutate_known_full(conn)
            conn.execute(
                "UPDATE reddit_threads SET more_node_count=1, "
                "coverage_grade='partial' WHERE post_id='seed_post_003'"
            )

        def mutate_fourth(conn: sqlite3.Connection) -> None:
            conn.execute(
                "UPDATE reddit_threads SET more_node_count=1, "
                "coverage_grade='partial' WHERE post_id='seed_post_003'"
            )

        def mutate_provider_origin(conn: sqlite3.Connection) -> None:
            capture_id = conn.execute(
                "SELECT raw_capture_id FROM reddit_threads "
                "WHERE post_id='seed_post_000'"
            ).fetchone()[0]
            conn.execute(
                "UPDATE raw_captures SET source_method='tikhub_detail', "
                "auth_boundary='provider_gate' WHERE raw_capture_id=?",
                (capture_id,),
            )

        def mutate_post_only(conn: sqlite3.Connection) -> None:
            conn.execute(
                "UPDATE reddit_threads SET coverage_grade='post_only' "
                "WHERE post_id='seed_post_003'"
            )

        cases = (
            ("known_full", mutate_known_full, 2, "known_seed_partial_mismatch"),
            ("known_missing", mutate_known_missing, 2, "known_seed_partial_mismatch"),
            ("replacement", mutate_replacement, 3, "known_seed_partial_mismatch"),
            ("fourth", mutate_fourth, 4, "known_seed_partial_mismatch"),
            (
                "provider_origin",
                mutate_provider_origin,
                2,
                "known_seed_partial_mismatch",
            ),
            ("post_only", mutate_post_only, 3, "post_only_coverage"),
        )
        for label, mutate, expected_count, expected_issue in cases:
            with self.subTest(case=label):
                temporary_directory = TemporaryDirectory(dir=TEST_TEMP_PARENT)
                self.addCleanup(temporary_directory.cleanup)
                case_root = Path(temporary_directory.name)
                source_path = case_root / "source.sqlite3"
                replay_path = case_root / "replay.sqlite3"
                archive_root = case_root / "private-raw"
                shutil.copy2(base_store.path, source_path)
                shutil.copy2(base_replay, replay_path)
                shutil.copytree(
                    base_archive.root,
                    archive_root,
                    copy_function=shutil.copy2,
                )
                for path in (source_path, replay_path):
                    with sqlite3.connect(path) as conn:
                        mutate(conn)

                result = validate_backfill(
                    BackfillStore(source_path),
                    PrivateRawArchive(archive_root, read_only=True),
                    run_id=RUN_ID,
                    seed_baseline=self.baseline,
                    scope="full",
                    replay_db=replay_path,
                    run_root=case_root,
                )

                self.assertEqual(result["status"], "rejected")
                self.assertEqual(result["replay_status"], "equivalent")
                self.assertEqual(
                    result["known_seed_partial_count"], expected_count
                )
                self.assertIn(expected_issue, _issue_codes(result))
                serialized = json.dumps(
                    result,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                self.assertNotIn("seed_post_", serialized)
                self.assertNotIn("historical_seed", serialized)

    def test_comment_chain_corruption_rejects_before_target_publication(self):
        def missing_page(
            store: BackfillStore,
            writer: PrivateRawArchive,
            run_id: str,
            post_id: str,
        ) -> None:
            artifact = next(
                item
                for item in store.load_raw_artifacts(
                    run_id=run_id,
                    lane_type="comments",
                    lane_key=post_id,
                )
                if item.page_number == 2
            )
            self._sql(
                store.path,
                "DELETE FROM backfill_raw_artifacts "
                "WHERE run_id=? AND artifact_id=?",
                (run_id, artifact.artifact_id),
            )
            (writer.root / artifact.relative_path).unlink()

        def duplicate_page(
            store: BackfillStore,
            writer: PrivateRawArchive,
            run_id: str,
            post_id: str,
        ) -> None:
            self._write_provider_artifact(
                store,
                writer,
                run_id=run_id,
                artifact_kind="comments",
                lane_type="comments",
                lane_key=post_id,
                parser_kind="tikhub_comments",
                source_method="tikhub_comments",
                endpoint=COMMENTS_ENDPOINT,
                page_number=2,
                request_cursor="comments-2",
                response_cursor=None,
                payload=_comment_page(
                    post_id,
                    None,
                    [
                        _comment_tree(
                            post_id,
                            "duplicate_logical_page_fixture",
                            "Momcozy duplicate logical page fixture.",
                            created_at=CAPTURED_AT + timedelta(days=3),
                        )
                    ],
                ),
                captured_at=CAPTURED_AT + timedelta(seconds=8),
            )

        def extra_page(
            store: BackfillStore,
            writer: PrivateRawArchive,
            run_id: str,
            post_id: str,
        ) -> None:
            self._write_provider_artifact(
                store,
                writer,
                run_id=run_id,
                artifact_kind="comments",
                lane_type="comments",
                lane_key=post_id,
                parser_kind="tikhub_comments",
                source_method="tikhub_comments",
                endpoint=COMMENTS_ENDPOINT,
                page_number=3,
                request_cursor=None,
                response_cursor=None,
                payload=_comment_page(post_id, None, []),
                captured_at=CAPTURED_AT + timedelta(seconds=8),
            )

        def broken_cursor(
            store: BackfillStore,
            _writer: PrivateRawArchive,
            run_id: str,
            _post_id: str,
        ) -> None:
            self._sql(
                store.path,
                "UPDATE backfill_raw_artifacts SET request_cursor=? "
                "WHERE run_id=? AND lane_type='comments' AND page_number=2",
                ("broken-cursor-fixture-secret", run_id),
            )

        def count_mismatch(
            store: BackfillStore,
            writer: PrivateRawArchive,
            run_id: str,
            post_id: str,
        ) -> None:
            self._replace_provider_payload(
                store,
                writer,
                run_id=run_id,
                lane_type="comments",
                lane_key=post_id,
                page_number=2,
                payload=_comment_page(
                    post_id,
                    None,
                    [
                        _comment_tree(
                            post_id,
                            "duplicate_comment",
                            "same semantic comment",
                            created_at=CAPTURED_AT + timedelta(days=1),
                        )
                    ],
                ),
            )

        def wrong_response_post_id(
            store: BackfillStore,
            writer: PrivateRawArchive,
            run_id: str,
            post_id: str,
        ) -> None:
            self._replace_provider_payload(
                store,
                writer,
                run_id=run_id,
                lane_type="comments",
                lane_key=post_id,
                page_number=2,
                payload=_comment_page(
                    "wrong_response_post_id_fixture_secret",
                    None,
                    [
                        _comment_tree(
                            post_id,
                            "duplicate_comment",
                            "same semantic comment",
                            created_at=CAPTURED_AT + timedelta(days=1),
                        ),
                        _comment_tree(
                            post_id,
                            "late_comment",
                            "Retain this Momcozy comment outside the post window.",
                            created_at=EFFECTIVE_END + timedelta(days=20),
                        ),
                    ],
                ),
            )

        def missing_comment_forest(
            store: BackfillStore,
            writer: PrivateRawArchive,
            run_id: str,
            post_id: str,
        ) -> None:
            self._replace_provider_payload(
                store,
                writer,
                run_id=run_id,
                lane_type="comments",
                lane_key=post_id,
                page_number=2,
                payload={
                    "data": {
                        "postInfoById": {"id": f"t3_{post_id}"},
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                },
            )
            self._sql(
                store.path,
                "UPDATE backfill_checkpoints SET discovered_count=2, unique_count=2 "
                "WHERE run_id=? AND lane_type='comments'",
                (run_id,),
            )

        def invalid_comment_trees(
            store: BackfillStore,
            writer: PrivateRawArchive,
            run_id: str,
            post_id: str,
        ) -> None:
            self._replace_provider_payload(
                store,
                writer,
                run_id=run_id,
                lane_type="comments",
                lane_key=post_id,
                page_number=2,
                payload={
                    "data": {
                        "postInfoById": {
                            "id": f"t3_{post_id}",
                            "commentForest": {"trees": {"invalid": True}},
                        },
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                },
            )
            self._sql(
                store.path,
                "UPDATE backfill_checkpoints SET discovered_count=2, unique_count=2 "
                "WHERE run_id=? AND lane_type='comments'",
                (run_id,),
            )

        def orphan_comment_lane(
            store: BackfillStore,
            writer: PrivateRawArchive,
            run_id: str,
            _post_id: str,
        ) -> None:
            orphan_post_id = "orphan_comment_lane_fixture_secret"
            self._write_provider_artifact(
                store,
                writer,
                run_id=run_id,
                artifact_kind="comments",
                lane_type="comments",
                lane_key=orphan_post_id,
                parser_kind="tikhub_comments",
                source_method="tikhub_comments",
                endpoint=COMMENTS_ENDPOINT,
                page_number=1,
                request_cursor=None,
                response_cursor=None,
                payload=_comment_page(orphan_post_id, None, []),
                captured_at=CAPTURED_AT + timedelta(seconds=8),
            )

        def last_success_drift(
            store: BackfillStore,
            _writer: PrivateRawArchive,
            run_id: str,
            _post_id: str,
        ) -> None:
            self._sql(
                store.path,
                "UPDATE backfill_checkpoints SET last_success_utc=? "
                "WHERE run_id=? AND lane_type='comments'",
                ("2026-07-11T04:18:09+00:00", run_id),
            )

        def comment_marker_masquerade(
            store: BackfillStore,
            writer: PrivateRawArchive,
            run_id: str,
            _post_id: str,
        ) -> None:
            masquerade_post_id = "comment_marker_masquerade_fixture_secret"
            artifact = self._write_provider_artifact(
                store,
                writer,
                run_id=run_id,
                artifact_kind="comments",
                lane_type="comments",
                lane_key=masquerade_post_id,
                parser_kind="tikhub_comments",
                source_method="tikhub_comments",
                endpoint=COMMENTS_ENDPOINT,
                page_number=1,
                request_cursor=None,
                response_cursor=None,
                payload=_comment_page(masquerade_post_id, None, []),
                captured_at=CAPTURED_AT + timedelta(seconds=8),
            )
            self._sql(
                store.path,
                "UPDATE backfill_raw_artifacts SET lane_type='detail_batch' "
                "WHERE run_id=? AND artifact_id=?",
                (run_id, artifact.artifact_id),
            )

        def checkpoint_previous_cursor_drift(
            store: BackfillStore,
            _writer: PrivateRawArchive,
            run_id: str,
            _post_id: str,
        ) -> None:
            self._sql(
                store.path,
                "UPDATE backfill_checkpoints SET previous_cursor=? "
                "WHERE run_id=? AND lane_type='comments'",
                ("checkpoint-previous-cursor-fixture-secret", run_id),
            )

        cases = (
            ("missing", missing_page),
            ("duplicate", duplicate_page),
            ("extra", extra_page),
            ("broken_cursor", broken_cursor),
            ("count_mismatch", count_mismatch),
            ("wrong_post_id", wrong_response_post_id),
            ("missing_forest", missing_comment_forest),
            ("invalid_trees", invalid_comment_trees),
            ("orphan_lane", orphan_comment_lane),
            ("last_success", last_success_drift),
            ("marker_masquerade", comment_marker_masquerade),
            ("checkpoint_previous_cursor", checkpoint_previous_cursor_drift),
        )
        for label, corrupt in cases:
            with self.subTest(case=label):
                store, writer, archive, root, run_id, post_id = (
                    self._detail_comment_case(label)
                )
                corrupt(store, writer, run_id, post_id)
                target = root / f"{label}-must-not-publish.sqlite3"

                validation = validate_backfill(
                    store,
                    archive,
                    run_id=run_id,
                    seed_baseline=self.baseline,
                    scope="full",
                    replay_db=None,
                    run_root=root,
                )
                replay = replay_from_archive(
                    store,
                    archive,
                    target_db=target,
                    run_id=run_id,
                )

                self.assertEqual(validation["status"], "rejected")
                self.assertIn("comment_chain_invalid", _issue_codes(validation))
                self.assertEqual(replay["status"], "failed")
                self.assertFalse(replay["provider_attempt_made"])
                self.assertFalse(replay["live_send"])
                self.assertFalse(os.path.lexists(target))
                self.assertFalse(
                    any(item.name.startswith(".replay-") for item in root.iterdir())
                )
                serialized = json.dumps(
                    {"validation": validation, "replay": replay},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                for forbidden in (
                    str(root),
                    post_id,
                    "broken-cursor-fixture-secret",
                    "duplicate_logical_page_fixture",
                    "wrong_response_post_id_fixture_secret",
                    "orphan_comment_lane_fixture_secret",
                    "comment_marker_masquerade_fixture_secret",
                    "checkpoint-previous-cursor-fixture-secret",
                ):
                    self.assertNotIn(forbidden, serialized)

    def test_unknown_parser_or_keyword_drift_fails_closed(self):
        def unknown_parser(store: BackfillStore, run_id: str) -> str:
            token = "unknown-parser-fixture-secret"
            self._sql(
                store.path,
                "UPDATE backfill_raw_artifacts SET parser_kind=? "
                "WHERE run_id=? AND lane_type='comments' AND page_number=1",
                (token, run_id),
            )
            return token

        def cursor_contract_drift(store: BackfillStore, run_id: str) -> str:
            token = "unknown-cursor-contract-fixture-secret"
            self._sql(
                store.path,
                "UPDATE backfill_checkpoints SET cursor_json_path=? "
                "WHERE run_id=? AND lane_type='comments'",
                (json.dumps([token, "endCursor"], separators=(",", ":")), run_id),
            )
            return token

        def keyword_drift(store: BackfillStore, run_id: str) -> str:
            token = "unknown-keyword-hash-fixture-secret"
            self._sql(
                store.path,
                "UPDATE backfill_manifests SET keyword_config_sha256=? WHERE run_id=?",
                (token, run_id),
            )
            return token

        cases = (
            ("parser", unknown_parser, "comment_chain_invalid"),
            ("cursor_contract", cursor_contract_drift, "comment_chain_invalid"),
            ("keyword", keyword_drift, "keyword_config_mismatch"),
        )
        for label, drift, validation_issue in cases:
            with self.subTest(case=label):
                store, _writer, archive, root, run_id, post_id = (
                    self._detail_comment_case(f"unknown_{label}")
                )
                secret = drift(store, run_id)
                target = root / f"{label}-must-not-publish.sqlite3"

                validation = validate_backfill(
                    store,
                    archive,
                    run_id=run_id,
                    seed_baseline=self.baseline,
                    scope="full",
                    replay_db=None,
                    run_root=root,
                )
                replay = replay_from_archive(
                    store,
                    archive,
                    target_db=target,
                    run_id=run_id,
                )

                self.assertEqual(validation["status"], "rejected")
                self.assertIn(validation_issue, _issue_codes(validation))
                self.assertEqual(replay["status"], "failed")
                self.assertFalse(replay["provider_attempt_made"])
                self.assertFalse(replay["live_send"])
                self.assertFalse(os.path.lexists(target))
                self.assertFalse(
                    any(item.name.startswith(".replay-") for item in root.iterdir())
                )
                serialized = json.dumps(
                    {"validation": validation, "replay": replay},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                for forbidden in (str(root), post_id, secret):
                    self.assertNotIn(forbidden, serialized)

    def test_validation_and_replay_never_reach_provider_report_or_send_modules(self):
        source_path = Path(backfill_validation_module.__file__)
        source_tree = ast.parse(source_path.read_text(encoding="utf-8"))
        forbidden_modules = {
            "backfill_provider",
            "collector",
            "daily_report",
            "dingtalk",
            "cli",
            "ops",
        }
        forbidden_symbols = {
            "TikHubClient",
            "TikHubRequestExecutor",
            "collect_daily_reddit",
            "collect_daily_tikhub",
            "build_daily_report",
            "translate_to_chinese",
            "render_business_dingtalk_markdown",
            "render_business_dingtalk_markdown_parts",
            "send_payload",
            "build_missed_run_report",
            "daily_window",
            "infer_cursor_contract",
            "extract_next_cursor",
            "urlopen",
        }
        imported_modules: set[str] = set()
        imported_symbols: set[str] = set()
        called_symbols: set[str] = set()
        for node in ast.walk(source_tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name.rsplit(".", 1)[-1] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_modules.add(node.module.rsplit(".", 1)[-1])
                imported_symbols.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    called_symbols.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    called_symbols.add(node.func.attr)
        self.assertFalse(imported_modules & forbidden_modules)
        self.assertFalse(imported_symbols & forbidden_symbols)
        self.assertFalse(called_symbols & forbidden_symbols)

        store, archive, root = self._case()
        target = root / "local-only-replay.sqlite3"
        (
            deep_store,
            _deep_writer,
            deep_archive,
            deep_root,
            deep_run_id,
            _deep_post_id,
        ) = self._detail_comment_case("runtime_boundary")
        deep_target = deep_root / "local-only-detail-comment-replay.sqlite3"
        boundary_error = AssertionError("phase-c3-external-boundary-reached")

        real_import = builtins.__import__
        blocked_imports = {
            "reddit_voc.backfill_provider",
            "reddit_voc.collector",
            "reddit_voc.daily_report",
            "reddit_voc.dingtalk",
            "reddit_voc.cli",
            "reddit_voc.ops",
        }

        def guarded_import(
            name,
            globals=None,
            locals=None,
            fromlist=(),
            level=0,
        ):
            candidates = {name}
            package = (globals or {}).get("__package__")
            if level and package:
                try:
                    candidates.add(
                        importlib.util.resolve_name("." * level + name, package)
                    )
                except (ImportError, ValueError):
                    raise boundary_error from None
            for base in tuple(candidates):
                candidates.update(
                    f"{base}.{member}"
                    for member in fromlist
                    if isinstance(member, str) and member != "*"
                )
            if any(
                candidate == blocked
                or candidate.startswith(blocked + ".")
                for candidate in candidates
                for blocked in blocked_imports
            ):
                raise boundary_error
            return real_import(name, globals, locals, fromlist, level)

        optional_entry_points = {
            "reddit_voc.backfill_provider": ("TikHubRequestExecutor",),
            "reddit_voc.collector": ("collect_daily_reddit",),
            "reddit_voc.daily_report": (
                "build_daily_report",
                "translate_to_chinese",
                "render_business_dingtalk_markdown",
                "render_business_dingtalk_markdown_parts",
            ),
            "reddit_voc.dingtalk": ("send_payload",),
            "reddit_voc.ops": ("build_missed_run_report",),
        }
        with ExitStack() as stack:
            comment_validator = stack.enter_context(
                patch.object(
                    backfill_validation_module,
                    "_validate_full_detail_and_comment_ledgers",
                    wraps=backfill_validation_module._validate_full_detail_and_comment_ledgers,
                )
            )
            stack.enter_context(
                patch.object(
                    sys.modules["reddit_voc.tikhub"].TikHubClient,
                    "_send",
                    side_effect=boundary_error,
                )
            )
            stack.enter_context(
                patch.object(
                    sys.modules["reddit_voc.tikhub"],
                    "urlopen",
                    side_effect=boundary_error,
                )
            )
            stack.enter_context(
                patch.object(
                    sys.modules["reddit_voc.tikhub"],
                    "collect_daily_tikhub",
                    side_effect=boundary_error,
                )
            )
            stack.enter_context(
                patch.object(socket, "create_connection", side_effect=boundary_error)
            )
            stack.enter_context(
                patch.object(
                    backfill_validation_module.os,
                    "getenv",
                    side_effect=boundary_error,
                )
            )
            for module_name, names in optional_entry_points.items():
                module = sys.modules.get(module_name)
                if module is None:
                    continue
                for name in names:
                    value = getattr(module, name, None)
                    if value is None:
                        continue
                    if name == "TikHubRequestExecutor":
                        stack.enter_context(
                            patch.object(value, "get_json", side_effect=boundary_error)
                        )
                    else:
                        stack.enter_context(
                            patch.object(module, name, side_effect=boundary_error)
                        )
            stack.enter_context(patch.object(builtins, "__import__", new=guarded_import))

            validation = self._validate_seed(store, archive)
            replay = replay_from_archive(
                store,
                archive,
                target_db=target,
                run_id=RUN_ID,
            )
            deep_validation = validate_backfill(
                deep_store,
                deep_archive,
                run_id=deep_run_id,
                seed_baseline=self.baseline,
                scope="full",
                replay_db=None,
                run_root=deep_root,
            )
            deep_replay = replay_from_archive(
                deep_store,
                deep_archive,
                target_db=deep_target,
                run_id=deep_run_id,
            )

        self.assertEqual(validation["status"], "accepted")
        self.assertEqual(replay["status"], "complete")
        self.assertEqual(deep_validation["status"], "rejected")
        self.assertEqual(comment_validator.call_count, 1)
        self.assertNotIn("comment_chain_invalid", _issue_codes(deep_validation))
        self.assertEqual(deep_replay["status"], "complete")
        self.assertFalse(validation["provider_attempt_made"])
        self.assertFalse(validation["live_send"])
        self.assertFalse(replay["provider_attempt_made"])
        self.assertFalse(replay["live_send"])
        self.assertFalse(deep_validation["provider_attempt_made"])
        self.assertFalse(deep_validation["live_send"])
        self.assertFalse(deep_replay["provider_attempt_made"])
        self.assertFalse(deep_replay["live_send"])
        self.assertTrue(target.is_file())
        self.assertTrue(deep_target.is_file())

    def test_report_is_deterministic_secret_free_and_uses_stop_priority(self):
        store, archive, root = self._case()
        secret = "phase-c3-secret-webhook-token"
        raw_url = "https://example.invalid/private/raw"
        cursor = "phase-c3-private-cursor"
        error_detail = "OSError: phase-c3-private-error-detail"
        self._sql(
            store.path,
            "UPDATE backfill_manifests SET keyword_config_sha256=? WHERE run_id=?",
            (secret, RUN_ID),
        )
        self._sql(
            store.path,
            "UPDATE reddit_threads SET title=? WHERE post_id='seed_post_000'",
            (f"{raw_url} {cursor} {error_detail}",),
        )
        self._sql(
            store.path,
            "INSERT INTO delivery_previews VALUES "
            "('phase-c3-delivery', ?, 'dingtalk', 'dry-run', 'prepared', ?, ?, 0)",
            (RUN_ID, secret, json.dumps([raw_url, cursor, error_detail])),
        )
        live_send_artifact = root / "nested" / "phase-c3-live-send.json"
        live_send_artifact.parent.mkdir()
        live_send_artifact.write_text(secret, encoding="utf-8")
        archived_payload = next(archive.root.rglob("*.json.gz"))
        archived_payload.write_bytes(f"corrupt {secret}".encode("utf-8"))

        first = self._validate_seed(store, archive, run_root=root)
        second = self._validate_seed(store, archive, run_root=root)

        self.assertEqual(
            backfill_validation_module._STOP_PRIORITY,
            (
                "source_unreadable",
                "schema_or_sqlite_integrity_failed",
                "archive_integrity_failed",
                "live_send_boundary_violation",
                "manifest_or_keyword_contract_invalid",
                "lineage_invalid",
                "entity_or_analysis_parity_invalid",
                "operational_accounting_invalid",
                "seed_incomplete",
                "required_lanes_incomplete",
                "candidate_hydration_incomplete",
                "replay_required",
                "replay_failed",
                "replay_mismatch",
            ),
        )
        self.assertEqual(tuple(first), RESULT_KEYS)
        self.assertEqual(first["status"], "rejected")
        self.assertEqual(first["stop_reason"], "archive_integrity_failed")
        self.assertEqual(
            json.dumps(
                first,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            json.dumps(
                second,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        self.assertFalse(first["provider_attempt_made"])
        self.assertFalse(first["live_send"])
        self.assertIn("archive_integrity_failed", _issue_codes(first))
        self.assertIn("live_send_artifact_found", _issue_codes(first))
        self.assertIn("delivery_boundary_violation", _issue_codes(first))
        self.assertIn("keyword_config_mismatch", _issue_codes(first))
        serialized = json.dumps(
            first,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for forbidden in (
            str(root),
            secret,
            raw_url,
            cursor,
            error_detail,
            *PARTIAL_POST_IDS,
        ):
            self.assertNotIn(forbidden, serialized)

    def test_replay_requires_fresh_confined_target_and_atomic_publication(self):
        store, archive, root = self._case()
        source_before = _snapshot_regular_file(store.path)
        existing_target = root / "existing.sqlite3"
        existing_target.write_bytes(b"existing-target-bytes")
        dangling_target = root / "dangling.sqlite3"
        dangling_target.symlink_to(root / "missing-dangling-target.sqlite3")
        hardlink_target = root / "source-hardlink.sqlite3"
        os.link(store.path, hardlink_target)
        actual_parent = root / "actual-parent"
        actual_parent.mkdir()
        linked_parent = root / "linked-parent"
        linked_parent.symlink_to(actual_parent, target_is_directory=True)
        missing_parent_target = root / "missing-parent" / "target.sqlite3"
        outside_directory = TemporaryDirectory(dir=TEST_TEMP_PARENT)
        self.addCleanup(outside_directory.cleanup)
        outside_target = Path(outside_directory.name) / "outside.sqlite3"
        archive_target = archive.root / "inside-archive.sqlite3"
        invalid_targets = (
            ("existing_regular", existing_target),
            ("dangling_final_symlink", dangling_target),
            ("source_same", store.path),
            ("source_hardlink_alias", hardlink_target),
            ("symlinked_parent", linked_parent / "target.sqlite3"),
            ("missing_parent", missing_parent_target),
            ("outside_source_run_dir", outside_target),
            ("archive_contained", archive_target),
        )
        with patch.object(
            backfill_validation_module,
            "_create_replay_temporary",
            side_effect=AssertionError("preflight reached temp creation"),
        ):
            for label, target in invalid_targets:
                with self.subTest(preflight=label):
                    with self.assertRaises(ValueError):
                        replay_from_archive(
                            store,
                            archive,
                            target_db=target,
                            run_id=RUN_ID,
                        )
        self.assertEqual(existing_target.read_bytes(), b"existing-target-bytes")
        self.assertTrue(dangling_target.is_symlink())
        self.assertTrue(os.path.samefile(store.path, hardlink_target))
        self.assertEqual(_snapshot_regular_file(store.path), source_before)

        real_subdirectory = root / "replays"
        real_subdirectory.mkdir()
        for target in (
            root / "source-parent-positive.sqlite3",
            real_subdirectory / "real-subdirectory-positive.sqlite3",
        ):
            with self.subTest(positive_parent=target.name):
                result = replay_from_archive(
                    store,
                    archive,
                    target_db=target,
                    run_id=RUN_ID,
                )
                self.assertEqual(result["status"], "complete")
                self.assertTrue(target.is_file())

        lexical_child = real_subdirectory / "lexical-child"
        lexical_child.mkdir()
        lexical_target = lexical_child / ".." / "atomic-success.sqlite3"
        canonical_target = lexical_target.resolve(strict=False)
        events: list[str] = []
        temporary_paths: list[Path] = []
        temporary_descriptors: list[int] = []
        real_create_temporary = (
            backfill_validation_module._create_replay_temporary
        )
        real_fsync = backfill_validation_module.os.fsync
        real_link = backfill_validation_module._link_replay_name
        real_unlink = backfill_validation_module._unlink_replay_name
        real_replay_result = backfill_validation_module._replay_result

        def tracked_create_temporary(**kwargs):
            created = real_create_temporary(**kwargs)
            temporary_descriptors.append(created[0])
            temporary_paths.append(created[2])
            return created

        def tracked_fsync(descriptor: int) -> None:
            if descriptor in temporary_descriptors:
                events.append("file_fsync")
                self.assertTrue(temporary_paths)
                for sidecar in _replay_temporary_paths(temporary_paths[0])[1:]:
                    self.assertFalse(os.path.lexists(sidecar))
            real_fsync(descriptor)

        def tracked_link(
            source_name, target_name, *, parent_fd: int, **kwargs
        ) -> None:
            events.append("link")
            self.assertEqual(source_name, temporary_paths[0].name)
            self.assertEqual(target_name, canonical_target.name)
            real_link(
                source_name, target_name, parent_fd=parent_fd, **kwargs
            )

        def tracked_parent_fsync(parent_fd: int) -> None:
            events.append("parent_fsync")

        def tracked_unlink(name: str, *, parent_fd: int) -> None:
            if temporary_paths and name == temporary_paths[0].name:
                events.append("temp_unlink")
            real_unlink(name, parent_fd=parent_fd)

        def tracked_result(**kwargs):
            if kwargs.get("status") == "complete":
                events.append("complete")
            return real_replay_result(**kwargs)

        with (
            patch.object(
                backfill_validation_module,
                "_create_replay_temporary",
                side_effect=tracked_create_temporary,
            ),
            patch.object(
                backfill_validation_module.os, "fsync", side_effect=tracked_fsync
            ),
            patch.object(
                backfill_validation_module,
                "_link_replay_name",
                side_effect=tracked_link,
            ),
            patch.object(
                backfill_validation_module,
                "_fsync_replay_parent",
                side_effect=tracked_parent_fsync,
            ),
            patch.object(
                backfill_validation_module,
                "_unlink_replay_name",
                side_effect=tracked_unlink,
            ),
            patch.object(
                backfill_validation_module,
                "_replay_result",
                side_effect=tracked_result,
            ),
        ):
            result = replay_from_archive(
                store,
                archive,
                target_db=lexical_target,
                run_id=RUN_ID,
            )

        self.assertEqual(result["status"], "complete")
        self.assertEqual(
            events,
            [
                "file_fsync",
                "link",
                "parent_fsync",
                "temp_unlink",
                "parent_fsync",
                "complete",
            ],
        )
        self.assertTrue(os.path.samefile(lexical_target, canonical_target))
        _assert_replay_temporary_absent(self, temporary_paths[0])

    def test_replay_prelink_faults_cleanup_owned_temporary_files(self):
        for label in ("mid_replay", "file_fsync"):
            with self.subTest(fault=label):
                store, archive, root = self._case()
                target_parent = root / "replays"
                target_parent.mkdir()
                target = target_parent / f"{label}.sqlite3"
                fault = RuntimeError(f"{label}-fixture-detail")
                temporary_paths: list[Path] = []
                parent_fsyncs: list[int] = []
                real_create_temporary = (
                    backfill_validation_module._create_replay_temporary
                )
                real_fsync = backfill_validation_module.os.fsync

                def tracked_create_temporary(**kwargs):
                    created = real_create_temporary(**kwargs)
                    temporary_paths.append(created[2])
                    return created

                def fail_migrate(target_store: BackfillStore) -> None:
                    for sidecar in _replay_temporary_paths(target_store.path)[1:]:
                        sidecar.write_bytes(b"owned-sidecar")
                    raise fault

                def fail_file_fsync(descriptor: int) -> None:
                    if stat.S_ISREG(os.fstat(descriptor).st_mode):
                        raise fault
                    real_fsync(descriptor)

                def tracked_parent_fsync(parent_fd: int) -> None:
                    parent_fsyncs.append(parent_fd)

                with ExitStack() as stack:
                    stack.enter_context(
                        patch.object(
                            backfill_validation_module,
                            "_create_replay_temporary",
                            side_effect=tracked_create_temporary,
                        )
                    )
                    stack.enter_context(
                        patch.object(
                            backfill_validation_module,
                            "_fsync_replay_parent",
                            side_effect=tracked_parent_fsync,
                        )
                    )
                    if label == "mid_replay":
                        stack.enter_context(
                            patch.object(
                                BackfillStore,
                                "migrate",
                                new=fail_migrate,
                            )
                        )
                    else:
                        stack.enter_context(
                            patch.object(
                                backfill_validation_module.os,
                                "fsync",
                                side_effect=fail_file_fsync,
                            )
                        )
                    with self.assertRaises(RuntimeError) as raised:
                        replay_from_archive(
                            store,
                            archive,
                            target_db=target,
                            run_id=RUN_ID,
                        )

                self.assertIs(raised.exception, fault)
                self.assertEqual(len(temporary_paths), 1)
                self.assertFalse(os.path.lexists(target))
                _assert_replay_temporary_absent(self, temporary_paths[0])
                self.assertEqual(len(parent_fsyncs), 1)

    def test_replay_toctou_target_exists_requires_stable_review_error(self):
        store, archive, root = self._case()
        target_parent = root / "replays"
        target_parent.mkdir()
        target = target_parent / "competitor.sqlite3"
        competitor_bytes = b"competitor-owned-target-bytes"
        competitor_sidecar = Path(str(target) + "-wal")
        competitor_sidecar_bytes = b"competitor-owned-sidecar"
        temporary_paths: list[Path] = []
        link_calls: list[tuple[Path, Path]] = []
        parent_fsyncs: list[int] = []
        real_create_temporary = (
            backfill_validation_module._create_replay_temporary
        )
        underlying_detail = "fixture-sensitive-file-exists-detail"

        def tracked_create_temporary(**kwargs):
            created = real_create_temporary(**kwargs)
            temporary_paths.append(created[2])
            return created

        def competitor_link(
            source_name: str,
            destination_name: str,
            *,
            parent_fd: int,
            **kwargs,
        ) -> None:
            source_path = target_parent / source_name
            destination_path = target_parent / destination_name
            link_calls.append((source_path, destination_path))
            owned_sidecars = _replay_temporary_paths(source_path)[1:]
            owned_sidecars[0].write_bytes(b"owned-race-sidecar")
            owned_sidecars[1].symlink_to(competitor_sidecar)
            owned_sidecars[2].write_bytes(b"owned-race-sidecar")
            destination_path.write_bytes(competitor_bytes)
            competitor_sidecar.write_bytes(competitor_sidecar_bytes)
            raise FileExistsError(underlying_detail)

        def tracked_parent_fsync(parent_fd: int) -> None:
            parent_fsyncs.append(parent_fd)

        error_type = getattr(
            backfill_validation_module, "ReplayPublicationError", RuntimeError
        )
        with (
            patch.object(
                backfill_validation_module,
                "_create_replay_temporary",
                side_effect=tracked_create_temporary,
            ),
            patch.object(
                backfill_validation_module,
                "_link_replay_name",
                side_effect=competitor_link,
            ),
            patch.object(
                backfill_validation_module,
                "_fsync_replay_parent",
                side_effect=tracked_parent_fsync,
            ),
        ):
            with self.assertRaises(error_type) as raised:
                replay_from_archive(
                    store,
                    archive,
                    target_db=target,
                    run_id=RUN_ID,
                )

        self.assertEqual(len(link_calls), 1)
        self.assertEqual(target.read_bytes(), competitor_bytes)
        self.assertEqual(competitor_sidecar.read_bytes(), competitor_sidecar_bytes)
        self.assertEqual(len(temporary_paths), 1)
        _assert_replay_temporary_absent(self, temporary_paths[0])
        self.assertEqual(len(parent_fsyncs), 1)
        _assert_publication_error(
            self,
            raised.exception,
            target=target,
            temporary_path=temporary_paths[0],
            underlying_detail=underlying_detail,
        )

    def test_replay_postcommit_faults_preserve_target_for_review(self):
        cases = (
            ("first_parent_fsync", ["link", "parent_fsync"], True),
            (
                "temp_unlink",
                ["link", "parent_fsync", "temp_unlink"],
                True,
            ),
            (
                "second_parent_fsync",
                [
                    "link",
                    "parent_fsync",
                    "temp_unlink",
                    "parent_fsync",
                ],
                False,
            ),
        )
        for label, expected_events, temporary_remains in cases:
            with self.subTest(fault=label):
                store, archive, root = self._case()
                target_parent = root / "replays"
                target_parent.mkdir()
                target = target_parent / f"{label}.sqlite3"
                target_text = os.fspath(target)
                events: list[str] = []
                temporary_paths: list[Path] = []
                link_calls: list[tuple[Path, Path]] = []
                target_unlinks: list[Path] = []
                state = {"committed": False, "parent_fsync_count": 0}
                real_create_temporary = (
                    backfill_validation_module._create_replay_temporary
                )
                real_link = backfill_validation_module._link_replay_name
                real_unlink = backfill_validation_module._unlink_replay_name
                real_exists = Path.exists
                underlying_detail = f"{label}-fixture-sensitive-detail"

                def tracked_create_temporary(**kwargs):
                    created = real_create_temporary(**kwargs)
                    temporary_paths.append(created[2])
                    return created

                def tracked_link(
                    source_name: str,
                    destination_name: str,
                    *,
                    parent_fd: int,
                    **kwargs,
                ) -> None:
                    events.append("link")
                    link_calls.append(
                        (
                            target_parent / source_name,
                            target_parent / destination_name,
                        )
                    )
                    real_link(
                        source_name,
                        destination_name,
                        parent_fd=parent_fd,
                        **kwargs,
                    )
                    state["committed"] = True

                def faulting_parent_fsync(parent_fd: int) -> None:
                    events.append("parent_fsync")
                    state["parent_fsync_count"] += 1
                    if label == "first_parent_fsync" or (
                        label == "second_parent_fsync"
                        and state["parent_fsync_count"] == 2
                    ):
                        raise OSError(underlying_detail)

                def faulting_unlink(name: str, *, parent_fd: int) -> None:
                    candidate = target_parent / name
                    if os.fspath(candidate) == target_text:
                        target_unlinks.append(candidate)
                    if temporary_paths and candidate == temporary_paths[0]:
                        events.append("temp_unlink")
                        if label == "temp_unlink":
                            raise OSError(underlying_detail)
                    real_unlink(name, parent_fd=parent_fd)

                def guarded_exists(path: Path) -> bool:
                    if state["committed"] and os.fspath(path) == target_text:
                        raise AssertionError(
                            "post-commit state inferred from target.exists"
                        )
                    return real_exists(path)

                error_type = getattr(
                    backfill_validation_module,
                    "ReplayPublicationError",
                    RuntimeError,
                )
                with (
                        patch.object(
                            backfill_validation_module,
                            "_create_replay_temporary",
                            side_effect=tracked_create_temporary,
                        ),
                        patch.object(
                            backfill_validation_module,
                            "_link_replay_name",
                            side_effect=tracked_link,
                        ),
                        patch.object(
                            backfill_validation_module,
                            "_fsync_replay_parent",
                            side_effect=faulting_parent_fsync,
                        ),
                        patch.object(
                            backfill_validation_module,
                            "_unlink_replay_name",
                            side_effect=faulting_unlink,
                        ),
                    patch.object(Path, "exists", new=guarded_exists),
                ):
                    with self.assertRaises(error_type) as raised:
                        replay_from_archive(
                            store,
                            archive,
                            target_db=target,
                            run_id=RUN_ID,
                        )

                self.assertEqual(events, expected_events)
                self.assertEqual(len(link_calls), 1)
                self.assertFalse(target_unlinks)
                self.assertTrue(target.is_file())
                self.assertEqual(len(temporary_paths), 1)
                self.assertEqual(
                    os.path.lexists(temporary_paths[0]), temporary_remains
                )
                _assert_replay_target_equivalent(
                    self, source=store.path, target=target
                )
                _assert_publication_error(
                    self,
                    raised.exception,
                    target=target,
                    temporary_path=temporary_paths[0],
                    underlying_detail=underlying_detail,
                )

    def test_replay_parent_swap_before_temp_creation_is_confined(self):
        store, archive, root = self._case()
        target_parent = root / "replays"
        target_parent.mkdir()
        held_parent = root / "replays-held"
        outside_directory = TemporaryDirectory(dir=TEST_TEMP_PARENT)
        self.addCleanup(outside_directory.cleanup)
        outside_parent = Path(outside_directory.name)
        target = target_parent / "parent-race.sqlite3"
        real_load_snapshot = backfill_validation_module._load_replay_snapshot

        def swap_parent(*args, **kwargs):
            snapshot = real_load_snapshot(*args, **kwargs)
            target_parent.rename(held_parent)
            target_parent.symlink_to(outside_parent, target_is_directory=True)
            return snapshot

        try:
            with patch.object(
                backfill_validation_module,
                "_load_replay_snapshot",
                side_effect=swap_parent,
            ):
                with self.assertRaises(
                    backfill_validation_module._ReplayOperationalBoundaryError
                ):
                    replay_from_archive(
                        store,
                        archive,
                        target_db=target,
                        run_id=RUN_ID,
                    )

            self.assertEqual(list(outside_parent.iterdir()), [])
            self.assertEqual(list(held_parent.iterdir()), [])
        finally:
            if target_parent.is_symlink():
                target_parent.unlink()
            if held_parent.exists():
                held_parent.rename(target_parent)

    def test_replay_parent_swap_during_sqlite_phase_is_cwd_anchored(self):
        store, archive, root = self._case()
        target_parent = root / "replays"
        target_parent.mkdir()
        held_parent = root / "replays-held"
        outside_directory = TemporaryDirectory(dir=TEST_TEMP_PARENT)
        self.addCleanup(outside_directory.cleanup)
        outside_parent = Path(outside_directory.name)
        target = target_parent / "phase-race.sqlite3"
        real_migrate = BackfillStore.migrate
        cwd_before = Path.cwd()
        cwd_before_stat = os.stat(".")

        def swap_during_migrate(target_store: BackfillStore) -> None:
            target_parent.rename(held_parent)
            target_parent.symlink_to(outside_parent, target_is_directory=True)
            real_migrate(target_store)

        try:
            with patch.object(BackfillStore, "migrate", new=swap_during_migrate):
                with self.assertRaises(
                    backfill_validation_module._ReplayOperationalBoundaryError
                ):
                    replay_from_archive(
                        store,
                        archive,
                        target_db=target,
                        run_id=RUN_ID,
                    )

            self.assertEqual(Path.cwd(), cwd_before)
            cwd_after_stat = os.stat(".")
            self.assertEqual(
                (cwd_after_stat.st_dev, cwd_after_stat.st_ino),
                (cwd_before_stat.st_dev, cwd_before_stat.st_ino),
            )
            self.assertEqual(list(outside_parent.iterdir()), [])
            self.assertEqual(list(held_parent.iterdir()), [])
            self.assertFalse(os.path.lexists(target))
        finally:
            os.chdir(cwd_before)
            if target_parent.is_symlink():
                target_parent.unlink()
            if held_parent.exists():
                held_parent.rename(target_parent)

    def test_replay_temp_substitution_before_fsync_fails_closed(self):
        for substitution in ("symlink", "hardlink"):
            with self.subTest(substitution=substitution):
                store, archive, root = self._case()
                target_parent = root / "replays"
                target_parent.mkdir()
                target = target_parent / f"{substitution}-race.sqlite3"
                source_before = _snapshot_regular_file(store.path)
                stolen_paths: list[Path] = []
                replaced_paths: list[Path] = []
                real_prepare = (
                    backfill_validation_module._prepare_replay_temp_for_publish
                )

                def substitute(path: Path) -> None:
                    real_prepare(path)
                    owned_path = Path(path)
                    stolen_path = Path(str(owned_path) + ".attacker-held")
                    owned_path.rename(stolen_path)
                    stolen_paths.append(stolen_path)
                    replaced_paths.append(owned_path)
                    if substitution == "symlink":
                        owned_path.symlink_to(store.path)
                    else:
                        os.link(store.path, owned_path)

                try:
                    with patch.object(
                        backfill_validation_module,
                        "_prepare_replay_temp_for_publish",
                        side_effect=substitute,
                    ):
                        with self.assertRaises(
                            backfill_validation_module._ReplayOperationalBoundaryError
                        ):
                            replay_from_archive(
                                store,
                                archive,
                                target_db=target,
                                run_id=RUN_ID,
                            )

                    self.assertFalse(os.path.lexists(target))
                    self.assertEqual(_snapshot_regular_file(store.path), source_before)
                    self.assertEqual(len(replaced_paths), 1)
                    self.assertFalse(os.path.lexists(replaced_paths[0]))
                finally:
                    for candidate in (target, *replaced_paths, *stolen_paths):
                        if os.path.lexists(candidate):
                            candidate.unlink()

    def test_replay_temp_substitution_at_link_is_stable_and_not_complete(self):
        store, archive, root = self._case()
        target_parent = root / "replays"
        target_parent.mkdir()
        target = target_parent / "link-window-race.sqlite3"
        source_before = _snapshot_regular_file(store.path)
        source_stat_before = store.path.stat()
        temporary_names: list[str] = []
        real_link_replay_name = backfill_validation_module._link_replay_name

        def substitute_at_link(
            source_name: str,
            target_name: str,
            *,
            parent_fd: int,
            **kwargs,
        ) -> None:
            temporary_names.append(source_name)
            os.unlink(source_name, dir_fd=parent_fd)
            os.link(
                store.path,
                source_name,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
            real_link_replay_name(
                source_name,
                target_name,
                parent_fd=parent_fd,
                **kwargs,
            )

        try:
            with patch.object(
                backfill_validation_module,
                "_link_replay_name",
                side_effect=substitute_at_link,
            ):
                with self.assertRaises(
                    backfill_validation_module._ReplayOperationalBoundaryError
                ):
                    replay_from_archive(
                        store,
                        archive,
                        target_db=target,
                        run_id=RUN_ID,
                    )

            self.assertEqual(len(temporary_names), 1)
            self.assertFalse(os.path.lexists(target))
            self.assertFalse(
                os.path.lexists(target_parent / temporary_names[0])
            )
            self.assertEqual(_snapshot_regular_file(store.path), source_before)
            self.assertEqual(store.path.stat().st_nlink, source_stat_before.st_nlink)
        finally:
            for candidate in (
                target,
                *(
                    (target_parent / name for name in temporary_names)
                    if temporary_names
                    else ()
                ),
            ):
                if os.path.lexists(candidate):
                    candidate.unlink()

    def test_replay_initial_temp_descriptor_close_fault_cleans_owned_names(self):
        store, archive, root = self._case()
        target_parent = root / "replays"
        target_parent.mkdir()
        target = target_parent / "descriptor-close.sqlite3"
        fault = OSError("descriptor-close-sensitive-detail")
        real_close = os.close

        def close_then_fail(descriptor: int) -> None:
            real_close(descriptor)
            raise fault

        with patch.object(
            backfill_validation_module,
            "_close_replay_temp_descriptor",
            side_effect=close_then_fail,
            create=True,
        ):
            with self.assertRaises(OSError) as raised:
                replay_from_archive(
                    store,
                    archive,
                    target_db=target,
                    run_id=RUN_ID,
                )

        self.assertIs(raised.exception, fault)
        self.assertFalse(os.path.lexists(target))
        self.assertEqual(
            [entry for entry in target_parent.iterdir() if ".replay-" in entry.name],
            [],
        )

    def test_replay_prelink_cleanup_secondary_faults_preserve_primary(self):
        store, archive, root = self._case()
        target_parent = root / "replays"
        target_parent.mkdir()
        target = target_parent / "cleanup-secondary.sqlite3"
        primary = RuntimeError("primary-sentinel-sensitive-detail")
        secondary = OSError("cleanup-secondary-sensitive-detail")
        temporary_names: list[str] = []
        unlink_calls: list[str] = []
        parent_fsync_calls: list[int] = []
        cleanup_faults = {"unlink": 0, "fsync": 0}
        real_unlink_name = getattr(
            backfill_validation_module, "_unlink_replay_name", None
        )
        real_fsync_parent = getattr(
            backfill_validation_module, "_fsync_replay_parent", None
        )

        def fail_migrate(target_store: BackfillStore) -> None:
            temporary_names.append(target_store.path.name)
            for sidecar in _replay_temporary_paths(target_store.path)[1:]:
                sidecar.write_bytes(b"owned-sidecar")
            raise primary

        def unlink_then_maybe_fail(name: str, *, parent_fd: int) -> None:
            unlink_calls.append(name)
            if name.endswith("-shm") and cleanup_faults["unlink"] == 0:
                cleanup_faults["unlink"] += 1
                raise secondary
            if real_unlink_name is None:
                os.unlink(name, dir_fd=parent_fd)
            else:
                real_unlink_name(name, parent_fd=parent_fd)

        def fsync_then_fail(parent_fd: int) -> None:
            parent_fsync_calls.append(parent_fd)
            if cleanup_faults["fsync"] == 0:
                cleanup_faults["fsync"] += 1
                raise secondary
            if real_fsync_parent is None:
                os.fsync(parent_fd)
            else:
                real_fsync_parent(parent_fd)

        with (
            patch.object(BackfillStore, "migrate", new=fail_migrate),
            patch.object(
                backfill_validation_module,
                "_unlink_replay_name",
                side_effect=unlink_then_maybe_fail,
                create=True,
            ),
            patch.object(
                backfill_validation_module,
                "_fsync_replay_parent",
                side_effect=fsync_then_fail,
                create=True,
            ),
        ):
            with self.assertRaises(RuntimeError) as raised:
                replay_from_archive(
                    store,
                    archive,
                    target_db=target,
                    run_id=RUN_ID,
                )

        self.assertIs(raised.exception, primary)
        self.assertEqual(len(temporary_names), 1)
        expected_names = {
            temporary_names[0],
            temporary_names[0] + "-wal",
            temporary_names[0] + "-shm",
            temporary_names[0] + "-journal",
        }
        self.assertEqual(set(unlink_calls), expected_names)
        self.assertEqual(len(unlink_calls), 5)
        self.assertEqual(len(parent_fsync_calls), 2)
        for name in expected_names:
            self.assertFalse(os.path.lexists(target_parent / name))
        self.assertFalse(os.path.lexists(target))

    def test_replay_toctou_cleanup_secondary_faults_stay_stable(self):
        store, archive, root = self._case()
        target_parent = root / "replays"
        target_parent.mkdir()
        target = target_parent / "toctou-secondary.sqlite3"
        competitor_bytes = b"competitor-owned-target-bytes"
        secondary = OSError("toctou-cleanup-secondary-sensitive-detail")
        temporary_names: list[str] = []
        unlink_calls: list[str] = []
        parent_fsync_calls: list[int] = []
        cleanup_faults = {"unlink": 0, "fsync": 0, "race_started": False}
        real_unlink_name = getattr(
            backfill_validation_module, "_unlink_replay_name", None
        )
        real_fsync_parent = getattr(
            backfill_validation_module, "_fsync_replay_parent", None
        )

        def competitor_link(
            source_name: str,
            target_name: str,
            *,
            parent_fd: int,
            **kwargs,
        ) -> None:
            unlink_calls.clear()
            cleanup_faults["race_started"] = True
            temporary_names.append(source_name)
            descriptor = os.open(
                target_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=parent_fd,
            )
            try:
                os.write(descriptor, competitor_bytes)
            finally:
                os.close(descriptor)
            for suffix in ("-wal", "-shm", "-journal"):
                sidecar = os.open(
                    source_name + suffix,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=parent_fd,
                )
                os.close(sidecar)
            raise FileExistsError("toctou-sensitive-detail")

        def unlink_then_maybe_fail(name: str, *, parent_fd: int) -> None:
            unlink_calls.append(name)
            if (
                cleanup_faults["race_started"]
                and name.endswith("-journal")
                and cleanup_faults["unlink"] == 0
            ):
                cleanup_faults["unlink"] += 1
                raise secondary
            if real_unlink_name is None:
                os.unlink(name, dir_fd=parent_fd)
            else:
                real_unlink_name(name, parent_fd=parent_fd)

        def fsync_then_fail(parent_fd: int) -> None:
            parent_fsync_calls.append(parent_fd)
            if cleanup_faults["fsync"] == 0:
                cleanup_faults["fsync"] += 1
                raise secondary
            if real_fsync_parent is None:
                os.fsync(parent_fd)
            else:
                real_fsync_parent(parent_fd)

        with (
            patch.object(
                backfill_validation_module,
                "_link_replay_name",
                side_effect=competitor_link,
                create=True,
            ),
            patch.object(
                backfill_validation_module,
                "_unlink_replay_name",
                side_effect=unlink_then_maybe_fail,
                create=True,
            ),
            patch.object(
                backfill_validation_module,
                "_fsync_replay_parent",
                side_effect=fsync_then_fail,
                create=True,
            ),
        ):
            with self.assertRaises(
                backfill_validation_module.ReplayPublicationError
            ) as raised:
                replay_from_archive(
                    store,
                    archive,
                    target_db=target,
                    run_id=RUN_ID,
                )

        self.assertEqual(target.read_bytes(), competitor_bytes)
        self.assertEqual(len(temporary_names), 1)
        expected_names = {
            temporary_names[0],
            temporary_names[0] + "-wal",
            temporary_names[0] + "-shm",
            temporary_names[0] + "-journal",
        }
        self.assertEqual(set(unlink_calls), expected_names)
        self.assertEqual(len(unlink_calls), 5)
        self.assertEqual(len(parent_fsync_calls), 2)
        for name in expected_names:
            self.assertFalse(os.path.lexists(target_parent / name))
        _assert_publication_error(
            self,
            raised.exception,
            target=target,
            temporary_path=target_parent / temporary_names[0],
            underlying_detail="toctou-sensitive-detail",
        )

    def test_replay_postlink_inode_verification_fault_is_stable(self):
        store, archive, root = self._case()
        target_parent = root / "replays"
        target_parent.mkdir()
        target = target_parent / "postlink-stat-fault.sqlite3"
        temporary_paths: list[Path] = []
        state = {"committed": False, "links": 0}
        real_create_temporary = (
            backfill_validation_module._create_replay_temporary
        )
        real_link = os.link
        real_stat = os.stat
        underlying_detail = "postlink-stat-sensitive-detail"

        def tracked_create_temporary(**kwargs):
            created = real_create_temporary(**kwargs)
            temporary_paths.append(created[2])
            return created

        def tracked_os_link(source, destination, *args, **kwargs):
            state["links"] += 1
            real_link(source, destination, *args, **kwargs)
            state["committed"] = True

        def faulting_stat(path, *args, dir_fd=None, **kwargs):
            if (
                state["committed"]
                and dir_fd is not None
                and os.fspath(path) == target.name
            ):
                raise OSError(underlying_detail)
            return real_stat(path, *args, dir_fd=dir_fd, **kwargs)

        with (
            patch.object(
                backfill_validation_module,
                "_create_replay_temporary",
                side_effect=tracked_create_temporary,
            ),
            patch.object(
                backfill_validation_module.os,
                "link",
                side_effect=tracked_os_link,
            ),
            patch.object(
                backfill_validation_module.os,
                "stat",
                side_effect=faulting_stat,
            ),
        ):
            with self.assertRaises(
                backfill_validation_module.ReplayPublicationError
            ) as raised:
                replay_from_archive(
                    store,
                    archive,
                    target_db=target,
                    run_id=RUN_ID,
                )

        self.assertEqual(state["links"], 1)
        self.assertEqual(len(temporary_paths), 1)
        self.assertTrue(target.is_file())
        self.assertTrue(os.path.lexists(temporary_paths[0]))
        _assert_replay_target_equivalent(self, source=store.path, target=target)
        _assert_publication_error(
            self,
            raised.exception,
            target=target,
            temporary_path=temporary_paths[0],
            underlying_detail=underlying_detail,
        )

    def test_replay_failed_results_require_complete_temporary_cleanup(self):
        for mode in ("data_error", "mismatch"):
            with self.subTest(mode=mode):
                store, archive, root = self._case()
                target_parent = root / "replays"
                target_parent.mkdir()
                target = target_parent / f"{mode}.sqlite3"
                temporary_paths: list[Path] = []
                real_create_temporary = (
                    backfill_validation_module._create_replay_temporary
                )
                real_unlink_name = backfill_validation_module._unlink_replay_name

                def tracked_create_temporary(**kwargs):
                    created = real_create_temporary(**kwargs)
                    temporary_paths.append(created[2])
                    return created

                def persistently_fail_main(
                    name: str, *, parent_fd: int
                ) -> None:
                    if temporary_paths and name == temporary_paths[0].name:
                        raise OSError("persistent-cleanup-sensitive-detail")
                    real_unlink_name(name, parent_fd=parent_fd)

                with ExitStack() as stack:
                    stack.enter_context(
                        patch.object(
                            backfill_validation_module,
                            "_create_replay_temporary",
                            side_effect=tracked_create_temporary,
                        )
                    )
                    stack.enter_context(
                        patch.object(
                            backfill_validation_module,
                            "_unlink_replay_name",
                            side_effect=persistently_fail_main,
                        )
                    )
                    if mode == "data_error":
                        stack.enter_context(
                            patch.object(
                                backfill_validation_module,
                                "_verify_replay_operational_constraints",
                                side_effect=backfill_validation_module._ReplayDataError(
                                    "fixture_data_error"
                                ),
                            )
                        )
                    else:
                        stack.enter_context(
                            patch.object(
                                backfill_validation_module,
                                "_fingerprints_for_path",
                                return_value={},
                            )
                        )
                    with self.assertRaises(
                        backfill_validation_module._ReplayOperationalBoundaryError
                    ):
                        replay_from_archive(
                            store,
                            archive,
                            target_db=target,
                            run_id=RUN_ID,
                        )

                self.assertEqual(len(temporary_paths), 1)
                self.assertTrue(os.path.lexists(temporary_paths[0]))
                self.assertFalse(os.path.lexists(target))
                temporary_paths[0].unlink()

    def test_replay_source_closes_before_commit_and_final_target_is_opaque(self):
        for mode in (
            "source_close_preclose_fault",
            "source_close_fault",
            "file_exists_race",
            "postcommit_fault",
            "complete",
        ):
            with self.subTest(mode=mode):
                store, archive, root = self._case()
                target_parent = root / "replays"
                target_parent.mkdir()
                target = target_parent / f"{mode}.sqlite3"
                target_name = target.name
                events: list[str] = []
                link_snapshots: list[tuple[os.stat_result, os.stat_result]] = []
                competitor_snapshots: list[tuple[int, int, bytes]] = []
                source_connections: list[sqlite3.Connection] = []
                state = {
                    "final_opaque": False,
                    "source_close_count": 0,
                    "link_calls": 0,
                }
                real_connect = sqlite3.connect
                real_link = os.link
                real_fsync_parent = getattr(
                    backfill_validation_module, "_fsync_replay_parent", None
                )

                class CloseOnceConnection(_TrackingConnection):
                    def close(self) -> None:
                        state["source_close_count"] += 1
                        events.append("source_close")
                        if (
                            mode == "source_close_preclose_fault"
                            and state["source_close_count"] == 1
                        ):
                            raise OSError("source-close-preclose-primary-detail")
                        if (
                            state["source_close_count"] > 1
                            and mode != "source_close_preclose_fault"
                        ):
                            raise RuntimeError("source-close-sensitive-detail")
                        self.connection.close()
                        if mode == "source_close_fault":
                            raise OSError("source-close-primary-detail")

                def ensure_source_closed(connection: sqlite3.Connection) -> None:
                    try:
                        connection.close()
                    except sqlite3.Error:
                        pass

                def connect(*args, **kwargs):
                    connection = real_connect(*args, **kwargs)
                    if "mode=ro" in str(args[0]) and str(store.path) in str(args[0]):
                        source_connections.append(connection)
                        self.addCleanup(ensure_source_closed, connection)
                        return CloseOnceConnection(connection)
                    return connection

                def tracked_link(
                    source_name: str,
                    destination_name: str,
                    *,
                    parent_fd: int,
                    **kwargs,
                ) -> None:
                    self.assertEqual(state["source_close_count"], 1)
                    self.assertEqual(destination_name, target_name)
                    events.append("link")
                    state["link_calls"] += 1
                    if mode == "file_exists_race":
                        competitor_bytes = b"opaque-competitor-owned-bytes"
                        descriptor = os.open(
                            destination_name,
                            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                            0o600,
                            dir_fd=parent_fd,
                        )
                        try:
                            os.write(descriptor, competitor_bytes)
                            competitor_stat = os.fstat(descriptor)
                        finally:
                            os.close(descriptor)
                        competitor_snapshots.append(
                            (
                                competitor_stat.st_dev,
                                competitor_stat.st_ino,
                                competitor_bytes,
                            )
                        )
                        state["final_opaque"] = True
                        raise FileExistsError("opaque-race-sensitive-detail")
                    real_link(
                        source_name,
                        destination_name,
                        src_dir_fd=parent_fd,
                        dst_dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                    source_stat = os.stat(
                        source_name, dir_fd=parent_fd, follow_symlinks=False
                    )
                    target_stat = os.stat(
                        destination_name, dir_fd=parent_fd, follow_symlinks=False
                    )
                    link_snapshots.append((source_stat, target_stat))
                    state["final_opaque"] = True

                def fault_or_fsync(parent_fd: int) -> None:
                    if mode == "postcommit_fault" and state["final_opaque"]:
                        raise OSError("postcommit-sensitive-detail")
                    if real_fsync_parent is None:
                        os.fsync(parent_fd)
                    else:
                        real_fsync_parent(parent_fd)

                real_os_open = os.open
                real_os_lstat = os.lstat
                real_os_unlink = os.unlink
                real_os_remove = os.remove
                real_os_rename = os.rename
                real_os_replace = os.replace
                real_os_stat = os.stat
                real_path_is_file = Path.is_file
                real_path_is_symlink = Path.is_symlink
                real_path_lstat = Path.lstat
                real_path_exists = Path.exists
                real_path_open = Path.open
                real_path_read_bytes = Path.read_bytes
                real_path_rename = Path.rename
                real_path_replace = Path.replace
                real_path_stat = Path.stat
                real_path_unlink = Path.unlink
                real_path_write_bytes = Path.write_bytes
                real_os_path_exists = os.path.exists
                real_os_path_isfile = os.path.isfile
                real_os_path_islink = os.path.islink
                real_os_path_lexists = os.path.lexists
                real_os_path_samefile = os.path.samefile

                def is_final(candidate, *, dir_fd=None) -> bool:
                    if not state["final_opaque"]:
                        return False
                    if dir_fd is not None:
                        return os.fspath(candidate) == target_name
                    return Path(candidate) == target

                def guarded_open(path, *args, dir_fd=None, **kwargs):
                    if is_final(path, dir_fd=dir_fd):
                        raise AssertionError("opened final target after commit")
                    return real_os_open(path, *args, dir_fd=dir_fd, **kwargs)

                def guarded_unlink(path, *args, dir_fd=None, **kwargs):
                    if is_final(path, dir_fd=dir_fd):
                        raise AssertionError("unlinked final target after commit")
                    return real_os_unlink(path, *args, dir_fd=dir_fd, **kwargs)

                def guarded_remove(path, *args, dir_fd=None, **kwargs):
                    if is_final(path, dir_fd=dir_fd):
                        raise AssertionError("removed final target after commit")
                    return real_os_remove(path, *args, dir_fd=dir_fd, **kwargs)

                def guarded_rename(
                    source,
                    destination,
                    *args,
                    src_dir_fd=None,
                    dst_dir_fd=None,
                    **kwargs,
                ):
                    if is_final(source, dir_fd=src_dir_fd) or is_final(
                        destination, dir_fd=dst_dir_fd
                    ):
                        raise AssertionError("renamed final target after commit")
                    return real_os_rename(
                        source,
                        destination,
                        *args,
                        src_dir_fd=src_dir_fd,
                        dst_dir_fd=dst_dir_fd,
                        **kwargs,
                    )

                def guarded_replace(
                    source,
                    destination,
                    *args,
                    src_dir_fd=None,
                    dst_dir_fd=None,
                    **kwargs,
                ):
                    if is_final(source, dir_fd=src_dir_fd) or is_final(
                        destination, dir_fd=dst_dir_fd
                    ):
                        raise AssertionError("replaced final target after commit")
                    return real_os_replace(
                        source,
                        destination,
                        *args,
                        src_dir_fd=src_dir_fd,
                        dst_dir_fd=dst_dir_fd,
                        **kwargs,
                    )

                def guarded_stat(path, *args, dir_fd=None, **kwargs):
                    if is_final(path, dir_fd=dir_fd):
                        raise AssertionError("statted final target after commit")
                    return real_os_stat(path, *args, dir_fd=dir_fd, **kwargs)

                def guarded_lstat(path, *args, dir_fd=None, **kwargs):
                    if is_final(path, dir_fd=dir_fd):
                        raise AssertionError("lstat final target after commit")
                    return real_os_lstat(path, *args, dir_fd=dir_fd, **kwargs)

                def guarded_os_path(real_function, label: str):
                    def guard(path, *args, **kwargs):
                        candidates = (path, *args) if label == "samefile" else (path,)
                        if any(is_final(candidate) for candidate in candidates):
                            raise AssertionError(f"{label} final target after commit")
                        return real_function(path, *args, **kwargs)

                    return guard

                def guarded_path_exists(path: Path) -> bool:
                    if is_final(path):
                        raise AssertionError("checked final target existence")
                    return real_path_exists(path)

                def guarded_path_open(path: Path, *args, **kwargs):
                    if is_final(path):
                        raise AssertionError("opened final target through Path")
                    return real_path_open(path, *args, **kwargs)

                def guarded_path_unlink(path: Path, *args, **kwargs):
                    if is_final(path):
                        raise AssertionError("unlinked final target through Path")
                    return real_path_unlink(path, *args, **kwargs)

                def guarded_path_method(real_function, label: str):
                    def guard(path: Path, *args, **kwargs):
                        candidates = (
                            (path, args[0])
                            if label in {"rename", "replace"} and args
                            else (path,)
                        )
                        if any(is_final(candidate) for candidate in candidates):
                            raise AssertionError(
                                f"{label} final target through Path"
                            )
                        return real_function(path, *args, **kwargs)

                    return guard

                patchers = (
                    patch.object(
                        backfill_validation_module.sqlite3,
                        "connect",
                        side_effect=connect,
                    ),
                    patch.object(
                        backfill_validation_module,
                        "_link_replay_name",
                        side_effect=tracked_link,
                        create=True,
                    ),
                    patch.object(
                        backfill_validation_module,
                        "_fsync_replay_parent",
                        side_effect=fault_or_fsync,
                        create=True,
                    ),
                    patch.object(backfill_validation_module.os, "open", new=guarded_open),
                    patch.object(backfill_validation_module.os, "lstat", new=guarded_lstat),
                    patch.object(
                        backfill_validation_module.os, "unlink", new=guarded_unlink
                    ),
                    patch.object(
                        backfill_validation_module.os, "remove", new=guarded_remove
                    ),
                    patch.object(
                        backfill_validation_module.os, "rename", new=guarded_rename
                    ),
                    patch.object(
                        backfill_validation_module.os, "replace", new=guarded_replace
                    ),
                    patch.object(backfill_validation_module.os, "stat", new=guarded_stat),
                    patch.object(
                        backfill_validation_module.os.path,
                        "exists",
                        new=guarded_os_path(real_os_path_exists, "exists"),
                    ),
                    patch.object(
                        backfill_validation_module.os.path,
                        "lexists",
                        new=guarded_os_path(real_os_path_lexists, "lexists"),
                    ),
                    patch.object(
                        backfill_validation_module.os.path,
                        "isfile",
                        new=guarded_os_path(real_os_path_isfile, "isfile"),
                    ),
                    patch.object(
                        backfill_validation_module.os.path,
                        "islink",
                        new=guarded_os_path(real_os_path_islink, "islink"),
                    ),
                    patch.object(
                        backfill_validation_module.os.path,
                        "samefile",
                        new=guarded_os_path(real_os_path_samefile, "samefile"),
                    ),
                    patch.object(Path, "exists", new=guarded_path_exists),
                    patch.object(
                        Path,
                        "is_file",
                        new=guarded_path_method(real_path_is_file, "is_file"),
                    ),
                    patch.object(
                        Path,
                        "is_symlink",
                        new=guarded_path_method(real_path_is_symlink, "is_symlink"),
                    ),
                    patch.object(
                        Path,
                        "lstat",
                        new=guarded_path_method(real_path_lstat, "lstat"),
                    ),
                    patch.object(Path, "open", new=guarded_path_open),
                    patch.object(
                        Path,
                        "read_bytes",
                        new=guarded_path_method(real_path_read_bytes, "read_bytes"),
                    ),
                    patch.object(
                        Path,
                        "rename",
                        new=guarded_path_method(real_path_rename, "rename"),
                    ),
                    patch.object(
                        Path,
                        "replace",
                        new=guarded_path_method(real_path_replace, "replace"),
                    ),
                    patch.object(
                        Path,
                        "stat",
                        new=guarded_path_method(real_path_stat, "stat"),
                    ),
                    patch.object(Path, "unlink", new=guarded_path_unlink),
                    patch.object(
                        Path,
                        "write_bytes",
                        new=guarded_path_method(real_path_write_bytes, "write_bytes"),
                    ),
                )
                with ExitStack() as stack:
                    for patcher in patchers:
                        stack.enter_context(patcher)
                    if mode in {
                        "source_close_preclose_fault",
                        "source_close_fault",
                    }:
                        with self.assertRaises(OSError) as raised:
                            replay_from_archive(
                                store,
                                archive,
                                target_db=target,
                                run_id=RUN_ID,
                            )
                        expected_detail = (
                            "source-close-preclose-primary-detail"
                            if mode == "source_close_preclose_fault"
                            else "source-close-primary-detail"
                        )
                        self.assertEqual(str(raised.exception), expected_detail)
                    elif mode == "file_exists_race":
                        with self.assertRaises(
                            backfill_validation_module.ReplayPublicationError
                        ) as raised:
                            replay_from_archive(
                                store,
                                archive,
                                target_db=target,
                                run_id=RUN_ID,
                            )
                        _assert_publication_error(
                            self,
                            raised.exception,
                            target=target,
                            temporary_path=target_parent / "owned-temp",
                            underlying_detail="opaque-race-sensitive-detail",
                        )
                    elif mode == "postcommit_fault":
                        with self.assertRaises(
                            backfill_validation_module.ReplayPublicationError
                        ) as raised:
                            replay_from_archive(
                                store,
                                archive,
                                target_db=target,
                                run_id=RUN_ID,
                            )
                        _assert_publication_error(
                            self,
                            raised.exception,
                            target=target,
                            temporary_path=target_parent / "owned-temp",
                            underlying_detail="postcommit-sensitive-detail",
                        )
                    else:
                        result = replay_from_archive(
                            store,
                            archive,
                            target_db=target,
                            run_id=RUN_ID,
                        )
                        self.assertEqual(result["status"], "complete")

                if mode == "source_close_preclose_fault":
                    self.assertGreaterEqual(state["source_close_count"], 2)
                    self.assertEqual(events[:2], ["source_close", "source_close"])
                    self.assertEqual(state["link_calls"], 0)
                    self.assertEqual(link_snapshots, [])
                    self.assertFalse(os.path.lexists(target))
                    self.assertEqual(len(source_connections), 1)
                    with self.assertRaises(sqlite3.ProgrammingError):
                        source_connections[0].execute("SELECT 1")
                elif mode == "source_close_fault":
                    self.assertGreaterEqual(state["source_close_count"], 2)
                    self.assertEqual(events[:2], ["source_close", "source_close"])
                    self.assertEqual(link_snapshots, [])
                    self.assertFalse(os.path.lexists(target))
                    self.assertEqual(len(source_connections), 1)
                    with self.assertRaises(sqlite3.ProgrammingError):
                        source_connections[0].execute("SELECT 1")
                elif mode == "file_exists_race":
                    self.assertEqual(state["source_close_count"], 1)
                    self.assertEqual(events[:2], ["source_close", "link"])
                    self.assertEqual(state["link_calls"], 1)
                    self.assertEqual(link_snapshots, [])
                    self.assertEqual(len(competitor_snapshots), 1)
                    before_dev, before_ino, before_bytes = competitor_snapshots[0]
                    after_stat = target.lstat()
                    self.assertEqual(
                        (after_stat.st_dev, after_stat.st_ino),
                        (before_dev, before_ino),
                    )
                    self.assertEqual(target.read_bytes(), before_bytes)
                else:
                    self.assertEqual(state["source_close_count"], 1)
                    self.assertEqual(events[:2], ["source_close", "link"])
                    self.assertEqual(state["link_calls"], 1)
                    self.assertEqual(len(link_snapshots), 1)
                    source_stat, target_stat = link_snapshots[0]
                    self.assertEqual(
                        (source_stat.st_dev, source_stat.st_ino),
                        (target_stat.st_dev, target_stat.st_ino),
                    )
                    self.assertTrue(target.is_file())

    def test_replay_publication_error_contract_is_exported_and_secret_free(self):
        error_type = getattr(
            backfill_validation_module, "ReplayPublicationError", None
        )
        self.assertIsNotNone(error_type)
        self.assertIn("ReplayPublicationError", backfill_validation_module.__all__)
        error = error_type(publication_state="target_exists_needs_review")
        _assert_publication_error(
            self,
            error,
            target=Path("/fixture/private/target.sqlite3"),
            temporary_path=Path("/fixture/private/.owned-temp.sqlite3"),
            underlying_detail="fixture-sensitive-underlying-detail",
        )

    def test_two_fresh_replays_have_identical_complete_fingerprints(self):
        store, archive, root = self._case()
        first_target = root / "replay-one.sqlite3"
        second_target = root / "replay-two.sqlite3"

        forbidden = AssertionError("replay crossed the local-only boundary")
        with (
            patch(
                "reddit_voc.tikhub.TikHubClient.get_json", side_effect=forbidden
            ),
            patch("reddit_voc.tikhub.urlopen", side_effect=forbidden),
            patch(
                "reddit_voc.backfill_provider.TikHubRequestExecutor.get_json",
                side_effect=forbidden,
            ),
        ):
            first = replay_from_archive(
                store, archive, target_db=first_target, run_id=RUN_ID
            )
            second = replay_from_archive(
                store, archive, target_db=second_target, run_id=RUN_ID
            )

        self.assertEqual(first["status"], "complete")
        self.assertEqual(second["status"], "complete")
        self.assertEqual(first["fingerprints"], second["fingerprints"])
        self.assertTrue(first["fingerprints"]["equivalent"])
        self.assertEqual(first["metadata_mirrored_count"], 0)
        self.assertEqual(second["metadata_mirrored_count"], 0)
        self.assertTrue(first_target.is_file())
        self.assertTrue(second_target.is_file())


if __name__ == "__main__":
    unittest.main()
