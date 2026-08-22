from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict, replace
from datetime import datetime, timezone
from hashlib import sha256
from io import StringIO
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from reddit_voc import backfill_cli
from reddit_voc.backfill_merge import MergeSummary
from reddit_voc.backfill_models import (
    AnalysisRow,
    BackfillCheckpoint,
    BackfillManifest,
    LaneResult,
    RawArtifactMetadata,
    SeedBaseline,
)
from reddit_voc.backfill_storage import BackfillStore
from reddit_voc.keywords import keyword_rules_sha256
from reddit_voc.models import RawCapture, RedditComment, RedditThread
from reddit_voc.search_config import (
    DEFAULT_REVIEWED_SUBREDDITS,
    DEFAULT_TIKHUB_SEARCH_TERMS,
)
from reddit_voc.storage import VocStore


RUN_ID = "backfill_momcozy_20250101_20260711"
NOW = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def canonical_sha(value: object) -> str:
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def budget_extension_authorization(
    source_database: Path,
    *,
    release_manifest_sha256: str = "b" * 64,
    probe_report_sha256: str = "a" * 64,
    expected_provider_request_count: int = 670,
    new_max_provider_requests_total: int = 870,
    discovery_request_ceiling: int = 820,
    include_subreddit_sweep: bool = True,
    expected_page_numbers: dict[tuple[str, str], int] | None = None,
    absolute_page_ceiling: int = 5,
) -> dict[str, object]:
    expected_page_numbers = expected_page_numbers or {}
    lanes = [
        {
            "lane_type": lane_type,
            "lane_key": lane_key,
            "expected_page_number": expected_page_numbers.get(
                (lane_type, lane_key), 0
            ),
            "absolute_page_ceiling": max(
                absolute_page_ceiling,
                expected_page_numbers.get((lane_type, lane_key), 0),
            ),
        }
        for lane_type, lane_key in backfill_cli.required_lanes_snapshot(
            search_terms=DEFAULT_TIKHUB_SEARCH_TERMS,
            subreddits=DEFAULT_REVIEWED_SUBREDDITS,
            include_subreddit_sweep=include_subreddit_sweep,
        )
    ]
    return {
        "schema_version": "momcozy_backfill_budget_extension_authorization_v1",
        "run_id": RUN_ID,
        "release_manifest_sha256": release_manifest_sha256,
        "probe_report_sha256": probe_report_sha256,
        "expected_source_database_sha256": sha256(
            source_database.read_bytes()
        ).hexdigest(),
        "expected_provider_request_count": expected_provider_request_count,
        "expected_max_provider_requests": expected_provider_request_count,
        "new_max_provider_requests_total": new_max_provider_requests_total,
        "discovery_request_ceiling": discovery_request_ceiling,
        "hydration_request_reserve": (
            new_max_provider_requests_total - discovery_request_ceiling
        ),
        "include_subreddit_sweep": include_subreddit_sweep,
        "required_lanes_sha256": backfill_cli.required_lanes_sha256(
            search_terms=DEFAULT_TIKHUB_SEARCH_TERMS,
            subreddits=DEFAULT_REVIEWED_SUBREDDITS,
            include_subreddit_sweep=include_subreddit_sweep,
        ),
        "lane_page_ceilings_sha256": canonical_sha(lanes),
        "lane_page_ceilings": lanes,
        "live_send": False,
    }


def existing_budget_resume_authorization(
    source_database: Path,
    *,
    release_manifest_sha256: str = "b" * 64,
    probe_report_sha256: str = "a" * 64,
    expected_provider_request_count: int = 3,
    max_provider_requests_total: int = 10,
    discovery_request_ceiling: int = 6,
    include_subreddit_sweep: bool = False,
    expected_page_numbers: dict[tuple[str, str], int] | None = None,
    absolute_page_ceiling: int = 1,
) -> dict[str, object]:
    expected_page_numbers = expected_page_numbers or {}
    lanes = [
        {
            "lane_type": lane_type,
            "lane_key": lane_key,
            "expected_page_number": expected_page_numbers.get(
                (lane_type, lane_key), 0
            ),
            "absolute_page_ceiling": max(
                absolute_page_ceiling,
                expected_page_numbers.get((lane_type, lane_key), 0),
            ),
        }
        for lane_type, lane_key in backfill_cli.required_lanes_snapshot(
            search_terms=DEFAULT_TIKHUB_SEARCH_TERMS,
            subreddits=DEFAULT_REVIEWED_SUBREDDITS,
            include_subreddit_sweep=include_subreddit_sweep,
        )
    ]
    return {
        "schema_version": "momcozy_backfill_existing_budget_resume_authorization_v1",
        "run_id": RUN_ID,
        "release_manifest_sha256": release_manifest_sha256,
        "probe_report_sha256": probe_report_sha256,
        "expected_source_database_sha256": sha256(
            source_database.read_bytes()
        ).hexdigest(),
        "expected_provider_request_count": expected_provider_request_count,
        "max_provider_requests_total": max_provider_requests_total,
        "discovery_request_ceiling": discovery_request_ceiling,
        "hydration_request_reserve": (
            max_provider_requests_total - discovery_request_ceiling
        ),
        "include_subreddit_sweep": include_subreddit_sweep,
        "required_lanes_sha256": backfill_cli.required_lanes_sha256(
            search_terms=DEFAULT_TIKHUB_SEARCH_TERMS,
            subreddits=DEFAULT_REVIEWED_SUBREDDITS,
            include_subreddit_sweep=include_subreddit_sweep,
        ),
        "lane_page_ceilings_sha256": canonical_sha(lanes),
        "lane_page_ceilings": lanes,
        "candidate_state_sha256": (
            backfill_cli._collection_resume_candidate_state_sha256(
                source_database, run_id=RUN_ID
            )
        ),
        "live_send": False,
    }


def baseline_payload() -> dict[str, object]:
    values: dict[str, object] = {
        "schema_version": "momcozy_seed_baseline_v1",
        "files_total": 55,
        "files_imported": 48,
        "files_outside_window": 7,
        "files_excluded": 0,
        "files_duplicate": 0,
        "parse_errors": 0,
        "threads": 48,
        "comments": 1894,
        "analyses": 1942,
        "coverage_full": 45,
        "coverage_partial": 3,
        "coverage_post_only": 0,
        "source_inventory_sha256": "1" * 64,
        "known_partial_post_ids_sha256": "2" * 64,
        "reviewed_search_terms_sha256": canonical_sha(
            list(DEFAULT_TIKHUB_SEARCH_TERMS)
        ),
        "reviewed_subreddits": list(DEFAULT_REVIEWED_SUBREDDITS),
        "reviewed_subreddits_sha256": canonical_sha(
            list(DEFAULT_REVIEWED_SUBREDDITS)
        ),
    }
    values["baseline_sha256"] = canonical_sha(values)
    return values


def validation_fingerprints(
    row_counts: dict[str, int] | None = None,
) -> dict[str, object]:
    counts = {
        "runs": 1,
        "backfill_raw_artifacts": 60,
        "raw_captures": 60,
        "reddit_threads": 50,
        "reddit_comments": 1900,
        "analysis_results": 1950,
        **(row_counts or {}),
    }
    result: dict[str, object] = {}
    for index, table in enumerate(backfill_cli._VALIDATION_FINGERPRINT_TABLES):
        fingerprint: dict[str, object] = {
            "row_count": counts[table],
            "id_set_sha256": f"{index + 1:x}" * 64,
            "canonical_rows_sha256": f"{index + 7:x}" * 64,
        }
        if table in {"backfill_raw_artifacts", "raw_captures"}:
            fingerprint["raw_payload_hash_set_sha256"] = f"{index + 9:x}" * 64
        result[table] = fingerprint
    return result


def validation_result(
    *,
    status: str = "accepted",
    scope: str = "full",
    source_fingerprints: dict[str, object] | None = None,
) -> dict[str, object]:
    accepted = status == "accepted"
    fingerprints = (
        validation_fingerprints()
        if source_fingerprints is None
        else source_fingerprints
    )
    fingerprint_counts = {
        table: int(fingerprint["row_count"])
        for table, fingerprint in fingerprints.items()
    }
    required_lanes = [
        {
            "lane_type": "dynamic_search",
            "lane_key_sha256": sha256(term.encode("utf-8")).hexdigest(),
            "status": "complete",
        }
        for term in DEFAULT_TIKHUB_SEARCH_TERMS
    ]
    counts = {
        "manifests": 1,
        "runs": fingerprint_counts.get("runs", 0),
        "seed_files": 55,
        "raw_artifacts": fingerprint_counts.get("backfill_raw_artifacts", 0),
        "raw_captures": fingerprint_counts.get("raw_captures", 0),
        "threads": fingerprint_counts.get("reddit_threads", 0),
        "comments": fingerprint_counts.get("reddit_comments", 0),
        "analyses": fingerprint_counts.get("analysis_results", 0),
        "delivery_previews": 0,
        "provider_attempts": max(1, len(required_lanes)),
        "checkpoints": len(required_lanes),
        "candidates": 0,
        "discovery_occurrences": 0,
        "detail_batches": 0,
        "detail_batch_members": 0,
    }
    return {
        "schema_version": "backfill_validation_v1",
        "run_id": RUN_ID,
        "scope": scope,
        "status": status,
        "stop_reason": (
            "full_validation_complete" if accepted and scope == "full" else
            "seed_validation_complete" if accepted else
            "source_unreadable"
        ),
        "replay_status": "equivalent" if scope == "full" else "not_run",
        "full_ready": accepted and scope == "full",
        "source_provider_call": accepted and scope == "full",
        "provider_attempt_made": False,
        "live_send": False,
        "seed_baseline_sha256": "3" * 64,
        "known_seed_partial_count": 3,
        "known_seed_partial_post_ids_sha256": "2" * 64,
        "run_root_scan": "clean" if scope == "full" else "not_run",
        "counts": counts,
        "candidate_status_counts": {
            key: 0 for key in backfill_cli._VALIDATION_CANDIDATE_KEYS
        },
        "occurrence_disposition_counts": {
            key: 0 for key in backfill_cli._VALIDATION_OCCURRENCE_KEYS
        },
        "required_lanes": required_lanes,
        "source_fingerprints": fingerprints,
        "replay_fingerprints": (
            json.loads(json.dumps(fingerprints)) if scope == "full" else None
        ),
        "operational_metadata": {
            "mode": "constraints_checked",
            "failure_only_metadata": "none",
            "metadata_mirrored_count": 0,
            "provider_attempts": "source_only_not_replayed",
        },
        "checks": [
            {
                "code": code,
                "ok": True,
                "actual": "valid",
                "expected": "valid",
            }
            for code in sorted(backfill_cli._REQUIRED_ACCEPTANCE_CHECK_CODES)
        ],
        "issues": [],
    }


def acceptance_envelope(
    *, source_fingerprints: dict[str, object] | None = None
) -> dict[str, object]:
    return {
        "schema_version": "backfill_validation_cli_envelope_v1",
        "run_id": RUN_ID,
        "scope": "full",
        "release_manifest_sha256": "a" * 64,
        "validation": validation_result(
            source_fingerprints=source_fingerprints
        ),
    }


def staging_acceptance_envelope(
    database: Path, *, source_fingerprints: dict[str, object]
) -> dict[str, object]:
    envelope = acceptance_envelope(source_fingerprints=source_fingerprints)
    validation = envelope["validation"]
    assert isinstance(validation, dict)
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        inventory = sorted(
            [str(row[0]), str(row[1])]
            for row in connection.execute(
                "SELECT input_path_hash, payload_sha256 "
                "FROM backfill_seed_files WHERE run_id=?",
                (RUN_ID,),
            ).fetchall()
        )
        operational_snapshot = backfill_cli.operational_snapshot_sha256(
            connection, RUN_ID
        )
        partial_ids = sorted(
            str(row[0])
            for row in connection.execute(
                "SELECT t.post_id FROM reddit_threads AS t "
                "JOIN backfill_seed_files AS s "
                "ON s.run_id=t.run_id AND s.post_id=t.post_id "
                "WHERE t.run_id=? AND s.outcome='imported' "
                "AND t.coverage_grade='partial'",
                (RUN_ID,),
            ).fetchall()
        )
    numeric_contract = {
        "files_total": 55,
        "files_imported": 48,
        "files_outside_window": 7,
        "files_excluded": 0,
        "files_duplicate": 0,
        "parse_errors": 0,
        "threads": 48,
        "comments": 1894,
        "analyses": 1942,
        "coverage_full": 45,
        "coverage_partial": 3,
        "coverage_post_only": 0,
    }
    bound_values = {
        "seed_numeric_contract": canonical_sha(numeric_contract),
        "seed_inventory": canonical_sha(inventory),
        "known_seed_partials": canonical_sha(partial_ids),
        "operational_accounting": operational_snapshot,
    }
    validation["known_seed_partial_post_ids_sha256"] = bound_values[
        "known_seed_partials"
    ]
    for check in validation["checks"]:
        code = check["code"]
        if code in bound_values:
            check["actual"] = bound_values[code]
            check["expected"] = bound_values[code]
    return envelope


def merge_plan_payload(
    *, staging_fingerprints: dict[str, object] | None = None
) -> dict[str, object]:
    values: dict[str, object] = {
        "schema_version": "backfill_insert_only_merge_plan_v1",
        "run_id": RUN_ID,
        "status": "ready",
        "stop_reason": "merge_plan_ready",
        "query_only": True,
        "production_write": False,
        "provider_attempt_made": False,
        "live_send": False,
        "staging_sha256": "4" * 64,
        "production_sha256": "5" * 64,
        "staging_fingerprints": (
            validation_fingerprints()
            if staging_fingerprints is None
            else staging_fingerprints
        ),
        "production_baseline_counts": {},
        "delivery_baseline_count": 0,
        "run_action": "insert",
        "staging_run_sha256": "6" * 64,
        "existing_run_sha256": "0" * 64,
        "approved_counts": {},
        "approved_post_ids_sha256": "7" * 64,
        "skipped_post_count": 0,
        "conflict_counts": {},
        "conflicts": [],
    }
    values["plan_sha256"] = canonical_sha(values)
    return {key: values[key] for key in backfill_cli.PLAN_KEYS}


class FakeTikHubClient:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get_json(self, path: str, params: dict[str, object]) -> object:
        self.calls.append((path, dict(params)))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def discovery_page(cursor: str | None, post_id: str) -> dict[str, object]:
    return {
        "data": {
            "search": {
                "dynamic": {
                    "components": {
                        "main": {
                            "pageInfo": {
                                "hasNextPage": cursor is not None,
                                "endCursor": cursor,
                            },
                            "edges": [
                                {
                                    "node": {
                                        "children": [
                                            {
                                                "__typename": "SearchPost",
                                                "post": {
                                                    "id": f"t3_{post_id}",
                                                    "postTitle": f"Momcozy post {post_id}",
                                                    "url": (
                                                        "https://www.reddit.com/r/"
                                                        "ExclusivelyPumping/"
                                                        f"comments/{post_id}/title/"
                                                    ),
                                                    "subreddit": {
                                                        "name": "ExclusivelyPumping"
                                                    },
                                                    "createdAt": (
                                                        "2026-01-01T00:00:00+00:00"
                                                    ),
                                                },
                                            }
                                        ]
                                    }
                                }
                            ],
                        }
                    }
                }
            }
        }
    }


class BackfillCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name).resolve()

    def call_main(self, argv: list[str]) -> tuple[int, dict[str, object]]:
        output = StringIO()
        errors = StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            result = backfill_cli.main(argv)
        self.assertEqual(errors.getvalue(), "")
        lines = [line for line in output.getvalue().splitlines() if line]
        self.assertEqual(len(lines), 1, output.getvalue())
        return result, json.loads(lines[0])

    def seed_argv(self, *, run_id: str = RUN_ID) -> list[str]:
        run_root = self.root / "run"
        return [
            "seed",
            "--run-id", run_id,
            "--database", str(run_root / "reddit_voc_backfill.sqlite3"),
            "--source-dir", str(self.root / "source"),
            "--raw-archive-dir", str(run_root / "private-raw"),
            "--report-dir", str(run_root / "reports"),
            "--window-start-utc", "2024-12-31T16:00:00Z",
            "--requested-window-end-utc", "2026-07-11T16:00:00Z",
            "--effective-window-end-utc", "2026-07-11T16:00:00Z",
        ]

    def v2_seed_argv(self, source: Path) -> list[str]:
        run_root = self.root / "v2-run"
        profile = (
            Path(__file__).resolve().parents[1]
            / "config/backfill/momcozy-search-profile-v2-candidate-20260714.json"
        )
        return [
            "v2-seed",
            "--run-id", "backfill_momcozy_v2_20250101_20260711",
            "--database", str(run_root / "reddit_voc_backfill.sqlite3"),
            "--source-dir", str(source),
            "--raw-archive-dir", str(run_root / "private-raw"),
            "--report-dir", str(run_root / "reports"),
            "--window-start-utc", "2025-01-01T00:00:00Z",
            "--requested-window-end-utc", "2026-07-11T16:00:00Z",
            "--effective-window-end-utc", "2026-07-11T16:00:00Z",
            "--profile", str(profile),
            "--expected-profile-sha256",
            "38706378f42c6648fe43bb50f60947863816363d65714f16a3092f40d91b604d",
            "--max-provider-requests", "69",
        ]

    def reindex_args(
        self, *, name: str = "reindex-run"
    ) -> tuple[SimpleNamespace, Path, Path, Path, Path, str]:
        run_root = self.root / name
        run_root.mkdir()
        source = run_root / "reddit_voc_backfill.sqlite3"
        source.write_bytes(b"fixture-source-database")
        raw_archive = run_root / "private-raw"
        raw_archive.mkdir()
        target = run_root / "reindexed.sqlite3"
        reports = run_root / "reports"
        reports.mkdir()
        report = reports / "reindex.json"
        source_sha256 = sha256(source.read_bytes()).hexdigest()
        return (
            SimpleNamespace(
                run_id=RUN_ID,
                source_database=source,
                raw_archive_dir=raw_archive,
                reindexed_database=target,
                expected_source_database_sha256=source_sha256,
                release_manifest=self.root / "release.json",
                expected_release_manifest_sha256="b" * 64,
                report=report,
            ),
            source,
            raw_archive,
            target,
            report,
            source_sha256,
        )

    @staticmethod
    def reindex_result(
        *, source_sha256: str, target_sha256: str | None
    ) -> dict[str, object]:
        complete = target_sha256 is not None
        ledger_sha256 = "d" * 64
        return {
            "schema_version": "backfill_discovery_reindex_v1",
            "status": "complete" if complete else "failed",
            "stop_reason": (
                "reindex_complete" if complete else "strict_discovery_schema_unknown"
            ),
            "provider_attempt_made": False,
            "live_send": False,
            "source_db_sha256": source_sha256,
            "raw_inventory_sha256": "c" * 64,
            "target_db_sha256": target_sha256,
            "source_max_provider_requests": 670,
            "source_provider_request_count": 670,
            "source_provider_ledger_sha256": ledger_sha256,
            "target_max_provider_requests": 670 if complete else None,
            "target_provider_request_count": 670 if complete else None,
            "target_provider_ledger_sha256": ledger_sha256 if complete else None,
            "discovery_artifact_count": 12 if complete else 0,
            "discovery_occurrence_count": 24 if complete else 0,
            "candidate_count": 8 if complete else 0,
        }

    def recovery_args(
        self,
    ) -> tuple[SimpleNamespace, Path, Path, Path, Path, str]:
        args, source, raw_archive, target, report, source_sha256 = (
            self.reindex_args(name="recovery-run")
        )
        args.recovered_at_utc = "2026-07-14T08:00:00+00:00"
        return args, source, raw_archive, target, report, source_sha256

    @staticmethod
    def recovery_result(
        *, source_sha256: str, target_sha256: str | None
    ) -> dict[str, object]:
        complete = target_sha256 is not None
        ledger_sha256 = "d" * 64
        counts = {
            "discovery_artifact_count": 32,
            "discovery_occurrence_count": 300,
            "candidate_count": 260,
            "new_candidate_count": 8,
            "recovered_discovery_lane_count": 14,
            "reset_candidate_count": 252,
            "reset_batch_count": 9,
            "reset_comment_checkpoint_count": 1,
            "raw_persisted_batch_count": 1,
            "prepared_batch_count": 8,
            "archived_hydrated_candidate_count": 1,
        }
        if not complete:
            counts = {key: 0 for key in counts}
        return {
            "schema_version": "backfill_collection_recovery_v1",
            "status": "complete" if complete else "failed",
            "stop_reason": (
                "collection_recovery_complete"
                if complete
                else "schema_drift_recovery_batch_mismatch"
            ),
            "run_id": RUN_ID,
            "provider_call": False,
            "provider_attempt_made": False,
            "database_write": "recovery_target_only" if complete else False,
            "live_send": False,
            "source_db_sha256": source_sha256,
            "raw_inventory_sha256": "c" * 64,
            "target_db_sha256": target_sha256,
            "source_max_provider_requests": 1200,
            "source_provider_request_count": 702,
            "source_provider_ledger_sha256": ledger_sha256,
            "target_max_provider_requests": 1200 if complete else None,
            "target_provider_request_count": 702 if complete else None,
            "target_provider_ledger_sha256": ledger_sha256 if complete else None,
            **counts,
        }

    def make_release_bundle(self) -> tuple[Path, Path, Path, str, SeedBaseline]:
        code_root = self.root / "code"
        for relative_path in backfill_cli.RELEASE_REVIEWED_PATHS:
            path = code_root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"reviewed:{relative_path}\n".encode("utf-8"))

        baseline_path = code_root / backfill_cli.SEED_BASELINE_RELATIVE_PATH
        baseline = baseline_payload()
        baseline_path.write_bytes(canonical_bytes(baseline))
        comment_path = code_root / backfill_cli.COMMENT_CURSOR_RELATIVE_PATH
        comment_payload = {
            "schema_version": "tikhub_comment_cursor_contract_v1",
            "cursor_path": list(
                backfill_cli.REVIEWED_COMMENT_CURSOR_CONTRACT.cursor_path
            ),
            "cursor_schema_sha256": backfill_cli.REVIEWED_COMMENT_CURSOR_SCHEMA_SHA256,
        }
        comment_path.write_bytes(canonical_bytes(comment_payload))

        reviewed = {
            relative_path: sha256((code_root / relative_path).read_bytes()).hexdigest()
            for relative_path in backfill_cli.RELEASE_REVIEWED_PATHS
        }
        reviewed[backfill_cli.SEED_BASELINE_RELATIVE_PATH] = sha256(
            baseline_path.read_bytes()
        ).hexdigest()
        reviewed[backfill_cli.COMMENT_CURSOR_RELATIVE_PATH] = sha256(
            comment_path.read_bytes()
        ).hexdigest()
        manifest = {
            "schema_version": "momcozy_backfill_release_manifest_v1",
            "run_id": RUN_ID,
            "seed_baseline": {
                "relative_path": backfill_cli.SEED_BASELINE_RELATIVE_PATH,
                "sha256": reviewed[backfill_cli.SEED_BASELINE_RELATIVE_PATH],
            },
            "reviewed_files_sha256": reviewed,
        }
        manifest_path = code_root / backfill_cli.RELEASE_MANIFEST_RELATIVE_PATH
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_bytes(canonical_bytes(manifest))
        manifest_sha = sha256(manifest_path.read_bytes()).hexdigest()
        baseline_object = SeedBaseline(
            **{
                **baseline,
                "reviewed_subreddits": tuple(baseline["reviewed_subreddits"]),
            }
        )
        return code_root, baseline_path, manifest_path, manifest_sha, baseline_object

    def make_staging(self, *, budget: int = 4, status: str = "seed_complete") -> Path:
        path = self.root / "run" / "reddit_voc_backfill.sqlite3"
        store = BackfillStore(path)
        store.migrate()
        store.create_manifest(
            BackfillManifest(
                run_id=RUN_ID,
                status="prepared",
                window_start_utc="2024-12-31T16:00:00+00:00",
                requested_end_utc="2026-07-11T16:00:00+00:00",
                effective_end_utc="2026-07-11T16:00:00+00:00",
                search_terms=DEFAULT_TIKHUB_SEARCH_TERMS,
                subreddits=DEFAULT_REVIEWED_SUBREDDITS,
                include_subreddit_sweep=False,
                required_lanes_sha256=backfill_cli.required_lanes_sha256(
                    search_terms=DEFAULT_TIKHUB_SEARCH_TERMS,
                    subreddits=DEFAULT_REVIEWED_SUBREDDITS,
                    include_subreddit_sweep=False,
                ),
                keyword_config_sha256=keyword_rules_sha256(),
                max_provider_requests=budget,
                provider_request_count=0,
                provider_call=False,
                live_send=False,
                created_at_utc=NOW.isoformat(),
                updated_at_utc=NOW.isoformat(),
            )
        )
        store.set_backfill_status(RUN_ID, status, NOW)
        return path

    def make_merge_staging(self) -> Path:
        path = self.make_staging(
            budget=len(DEFAULT_TIKHUB_SEARCH_TERMS), status="seed_complete"
        )
        store = BackfillStore(path)
        self.add_baseline_staging_entities(path)
        for term in DEFAULT_TIKHUB_SEARCH_TERMS:
            lane_hash = sha256(term.encode("utf-8")).hexdigest()
            payload_sha256 = sha256(
                f"fixture-discovery-payload:{term}".encode("utf-8")
            ).hexdigest()
            source_url = f"tikhub://fixture/dynamic-search/{lane_hash}"
            raw_capture_id = f"raw-discovery-{lane_hash[:24]}"
            store.persist_raw_capture_artifact(
                RawCapture(
                    raw_capture_id=raw_capture_id,
                    run_id=RUN_ID,
                    source_method="tikhub_dynamic_search",
                    source_url=source_url,
                    captured_at_utc=NOW,
                    auth_boundary="api_key_env",
                    raw_payload_hash=f"sha256:{payload_sha256}",
                    payload_format="json",
                    http_status=200,
                ),
                RawArtifactMetadata(
                    artifact_id=f"discovery-{lane_hash[:24]}",
                    run_id=RUN_ID,
                    artifact_kind="discovery",
                    lane_type="dynamic_search",
                    lane_key_hash=lane_hash,
                    identity_hash=sha256(
                        source_url.removeprefix("tikhub://").encode("utf-8")
                    ).hexdigest(),
                    raw_capture_id=raw_capture_id,
                    parser_kind="tikhub_discovery",
                    source_method="tikhub_dynamic_search",
                    source_url=source_url,
                    source_endpoint=(
                        "/api/v1/reddit/app/fetch_dynamic_search"
                    ),
                    payload_sha256=payload_sha256,
                    relative_path=(
                        f"{RUN_ID}/dynamic_search/{lane_hash}/page-000001.json.gz"
                    ),
                    captured_at_utc=NOW.isoformat(),
                    page_number=1,
                    request_cursor=None,
                    response_cursor=None,
                ),
            )
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
            store.save_checkpoint(
                BackfillCheckpoint(
                    run_id=RUN_ID,
                    lane_type="dynamic_search",
                    lane_key=term,
                    cursor=None,
                    previous_cursor=None,
                    page_number=1,
                    newest_seen_utc=NOW.isoformat(),
                    oldest_seen_utc=NOW.isoformat(),
                    discovered_count=0,
                    unique_count=0,
                    provider_request_count=1,
                    last_success_utc=NOW.isoformat(),
                    last_error=None,
                    status="complete",
                    stop_reason="cursor_exhausted",
                    cursor_json_path="data.pageInfo.endCursor",
                    cursor_schema_sha256="c" * 64,
                    consecutive_old_pages=0,
                )
            )
        store.set_backfill_status(RUN_ID, "success", NOW)
        return path

    def add_baseline_staging_entities(self, database: Path) -> None:
        store = BackfillStore(database)
        captures: list[RawCapture] = []
        threads: list[RedditThread] = []
        comments: list[RedditComment] = []
        analyses: list[AnalysisRow] = []
        seed_rows: list[tuple[str, str, str, str, str]] = []
        for seed_index in range(55):
            imported = seed_index < 48
            post_id = (
                f"reviewed-seed-post-{seed_index:03d}"
                if imported
                else f"outside-seed-post-{seed_index - 48:03d}"
            )
            input_path_hash = sha256(
                f"fixture-seed-path-{seed_index:03d}".encode("utf-8")
            ).hexdigest()
            payload_sha256 = sha256(
                f"fixture-seed-payload-{seed_index:03d}".encode("utf-8")
            ).hexdigest()
            artifact_id = f"seed-artifact-{seed_index:03d}"
            raw_capture_id = f"raw-reviewed-seed-{seed_index:03d}"
            source_url = f"seed://{input_path_hash}"
            captures.append(
                RawCapture(
                    raw_capture_id=raw_capture_id,
                    run_id=RUN_ID,
                    source_method="historical_seed",
                    source_url=source_url,
                    captured_at_utc=NOW,
                    auth_boundary="local_seed",
                    raw_payload_hash=f"sha256:{payload_sha256}",
                    payload_format="json",
                )
            )
            store.insert_raw_artifact(
                RawArtifactMetadata(
                    artifact_id=artifact_id,
                    run_id=RUN_ID,
                    artifact_kind="seed",
                    lane_type="seed",
                    lane_key_hash=sha256(input_path_hash.encode("utf-8")).hexdigest(),
                    identity_hash=sha256(payload_sha256.encode("utf-8")).hexdigest(),
                    raw_capture_id=raw_capture_id,
                    parser_kind="seed_browser_thread",
                    source_method="historical_seed",
                    source_url=source_url,
                    source_endpoint="seed_file",
                    payload_sha256=payload_sha256,
                    relative_path=(
                        f"{RUN_ID}/seed/{input_path_hash[:2]}/{artifact_id}.json.gz"
                    ),
                    captured_at_utc=NOW.isoformat(),
                    page_number=0,
                    request_cursor=None,
                    response_cursor=None,
                )
            )
            seed_rows.append(
                (
                    input_path_hash,
                    payload_sha256,
                    "imported" if imported else "outside_window",
                    artifact_id,
                    post_id,
                )
            )
            if not imported:
                continue
            comment_count = 39 if seed_index < 47 else 61
            partial = seed_index < 3
            threads.append(
                RedditThread(
                    post_id=post_id,
                    run_id=RUN_ID,
                    raw_capture_id=raw_capture_id,
                    subreddit="ExclusivelyPumping",
                    title=f"Momcozy reviewed seed {seed_index}",
                    selftext="Reviewed historical seed fixture.",
                    source_url=f"https://www.reddit.com/comments/{post_id}/",
                    created_at_utc=NOW,
                    score=1,
                    num_comments_reported=comment_count + int(partial),
                    parsed_comment_count=comment_count,
                    more_node_count=int(partial),
                    coverage_grade="partial" if partial else "full",
                    matched_keywords=("Momcozy",),
                    author_hash=f"reviewed-author-{seed_index:03d}",
                    media_urls=(),
                )
            )
            analyses.append(
                AnalysisRow(
                    analysis_id=f"analysis-reviewed-post-{seed_index:03d}",
                    run_id=RUN_ID,
                    source_type="post",
                    source_id=post_id,
                    analysis_version="local_rules_v1",
                    sentiment_label="neutral",
                    sentiment_score=0.0,
                    topic="product_experience",
                    severity="low",
                    confidence=1.0,
                    pain_points=(),
                    provider_call=False,
                )
            )
            for comment_index in range(comment_count):
                comment_id = (
                    f"reviewed-comment-{seed_index:03d}-{comment_index:03d}"
                )
                comments.append(
                    RedditComment(
                        comment_id=comment_id,
                        post_id=post_id,
                        run_id=RUN_ID,
                        raw_capture_id=raw_capture_id,
                        parent_id=f"t3_{post_id}",
                        body="Reviewed Momcozy seed comment.",
                        created_at_utc=NOW,
                        score=1,
                        depth=0,
                        is_submitter=False,
                        matched_keywords=("Momcozy",),
                        author_hash=(
                            f"reviewed-comment-author-{seed_index:03d}-"
                            f"{comment_index:03d}"
                        ),
                        deleted_or_removed=False,
                    )
                )
                analyses.append(
                    AnalysisRow(
                        analysis_id=f"analysis-{comment_id}",
                        run_id=RUN_ID,
                        source_type="comment",
                        source_id=comment_id,
                        analysis_version="local_rules_v1",
                        sentiment_label="neutral",
                        sentiment_score=0.0,
                        topic="product_experience",
                        severity="low",
                        confidence=1.0,
                        pain_points=(),
                        provider_call=False,
                    )
                )
        store.insert_entity_bundle(
            captures=tuple(captures),
            threads=tuple(threads),
            comments=tuple(comments),
            analyses=tuple(analyses),
        )
        for input_path_hash, payload_sha256, outcome, artifact_id, post_id in seed_rows:
            store.record_seed_file(
                run_id=RUN_ID,
                input_path_hash=input_path_hash,
                payload_sha256=payload_sha256,
                outcome=outcome,
                artifact_id=artifact_id,
                post_id=post_id,
                error_class=None,
                processed_at_utc=NOW,
            )

    def add_complete_staging_entity(self, database: Path) -> None:
        capture = RawCapture(
            raw_capture_id="raw-stale-acceptance-post",
            run_id=RUN_ID,
            source_method="historical_seed",
            source_url="seed://stale-acceptance-post",
            captured_at_utc=NOW,
            auth_boundary="local_seed",
            raw_payload_hash="sha256:" + "d" * 64,
            payload_format="json",
        )
        thread = RedditThread(
            post_id="stale-acceptance-post",
            run_id=RUN_ID,
            raw_capture_id=capture.raw_capture_id,
            subreddit="ExclusivelyPumping",
            title="Momcozy stale acceptance fixture",
            selftext="Complete entity closure added after validation.",
            source_url="https://www.reddit.com/r/ExclusivelyPumping/comments/stale/",
            created_at_utc=NOW,
            score=1,
            num_comments_reported=0,
            parsed_comment_count=0,
            more_node_count=0,
            coverage_grade="full",
            matched_keywords=("Momcozy",),
            author_hash="fixture-author-hash",
            media_urls=(),
        )
        analysis = AnalysisRow(
            analysis_id="analysis-stale-acceptance-post",
            run_id=RUN_ID,
            source_type="post",
            source_id=thread.post_id,
            analysis_version="local_rules_v1",
            sentiment_label="neutral",
            sentiment_score=0.0,
            topic="product_experience",
            severity="low",
            confidence=1.0,
            pain_points=(),
            provider_call=False,
        )
        BackfillStore(database).insert_entity_bundle(
            captures=(capture,),
            threads=(thread,),
            comments=(),
            analyses=(analysis,),
        )

    def test_import_isolation_excludes_all_daily_and_delivery_modules(self) -> None:
        script = """
import sys
import reddit_voc.backfill_cli
for name in (
    'reddit_voc.cli', 'reddit_voc.collector',
    'reddit_voc.daily_report', 'reddit_voc.dingtalk',
):
    assert name not in sys.modules, name
"""
        env = dict(os.environ)
        env["PYTHONPATH"] = "src:."
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_profile_admission_pins_v2_delta_to_a_distinct_future_run(self) -> None:
        root = Path(__file__).resolve().parents[1]
        profile = root / "config/backfill/momcozy-search-profile-v2-candidate-20260714.json"

        return_code, payload = self.call_main(
            [
                "profile-admission",
                "--run-id", "backfill_momcozy_v2_20250101_20260711",
                "--profile", str(profile),
                "--expected-profile-sha256",
                "38706378f42c6648fe43bb50f60947863816363d65714f16a3092f40d91b604d",
            ]
        )

        self.assertEqual(return_code, 0)
        self.assertEqual(payload["status"], "ready_for_new_isolated_run")
        self.assertEqual(payload["legacy_run_id"], RUN_ID)
        self.assertEqual(payload["candidate_term_count"], 75)
        self.assertEqual(payload["delta_term_count"], 69)
        self.assertFalse(payload["provider_call"])
        self.assertFalse(payload["production_merge"])
        self.assertFalse(payload["git_push"])
        self.assertFalse(payload["live_send"])

    def test_profile_admission_rejects_legacy_run_reuse(self) -> None:
        root = Path(__file__).resolve().parents[1]
        profile = root / "config/backfill/momcozy-search-profile-v2-candidate-20260714.json"

        return_code, payload = self.call_main(
            [
                "profile-admission",
                "--run-id", RUN_ID,
                "--profile", str(profile),
                "--expected-profile-sha256",
                "38706378f42c6648fe43bb50f60947863816363d65714f16a3092f40d91b604d",
            ]
        )

        self.assertEqual(return_code, 1)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "v2_profile_requires_distinct_run")
        self.assertFalse(payload["provider_call"])

    def test_v2_seed_imports_existing_raw_archive_into_an_isolated_delta_run(self) -> None:
        source = self.root / "source"
        nested = source / "Momcozy"
        nested.mkdir(parents=True)
        fixture = (
            Path(__file__).resolve().parent
            / "fixtures/reddit_thread_browser_json.json"
        )
        (nested / "thread.json").write_bytes(fixture.read_bytes())

        return_code, payload = self.call_main(self.v2_seed_argv(source))

        self.assertEqual(return_code, 0)
        self.assertEqual(payload["schema_version"], "backfill_v2_seed_cli_v1")
        self.assertEqual(payload["delta_term_count"], 69)
        self.assertEqual(payload["max_provider_requests"], 69)
        self.assertEqual(payload["seed"]["files_total"], 1)
        self.assertEqual(payload["seed"]["files_imported"], 1)
        self.assertFalse(payload["provider_call"])
        self.assertFalse(payload["production_merge"])
        self.assertFalse(payload["git_push"])
        self.assertFalse(payload["live_send"])

        database = self.root / "v2-run/reddit_voc_backfill.sqlite3"
        with sqlite3.connect(database) as connection:
            row = connection.execute(
                "SELECT status, provider_request_count, max_provider_requests, "
                "search_terms_json FROM backfill_manifests WHERE run_id = ?",
                ("backfill_momcozy_v2_20250101_20260711",),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[:3], ("seed_complete", 0, 69))
        self.assertEqual(len(json.loads(row[3])), 69)

        replay_code, replay_payload = self.call_main(self.v2_seed_argv(source))
        self.assertEqual(replay_code, 0)
        self.assertEqual(replay_payload["seed"]["files_imported"], 1)
        self.assertFalse(replay_payload["provider_call"])

    def test_invalid_run_id_is_redacted_before_handler_or_path_touch(self) -> None:
        invalid_run_id = "../../private/staging.sqlite3"

        return_code, payload = self.call_main(
            self.seed_argv(run_id=invalid_run_id)
        )

        self.assertEqual(return_code, 1)
        self.assertEqual(payload["reason"], "run_id_invalid")
        self.assertIsNone(payload["run_id"])
        self.assertNotIn(invalid_run_id, canonical_bytes(payload).decode("utf-8"))
        self.assertFalse((self.root / "run").exists())

    def test_domain_and_unexpected_errors_emit_stable_secret_free_json(self) -> None:
        source = self.root / "source"
        source.mkdir()
        run_root = self.root / "run"
        run_root.mkdir()
        database = run_root / "reddit_voc_backfill.sqlite3"
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE backfill_manifests(run_id TEXT)")
            connection.execute("CREATE TABLE backfill_seed_files(input_path TEXT)")

        completed = subprocess.run(
            [sys.executable, "-m", "reddit_voc.backfill_cli", *self.seed_argv()],
            cwd=Path(__file__).resolve().parents[1],
            env={
                **os.environ,
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": "src:.",
            },
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stderr, "")
        domain_payload = json.loads(completed.stdout)
        self.assertEqual(domain_payload["reason"], "staging_schema_invalid")
        self.assertNotIn(str(self.root), completed.stdout)
        self.assertNotIn("incompatible backfill_seed_files", completed.stdout)

        sensitive = "token=must-not-leak /private/fixture.sqlite3"
        with patch.object(
            backfill_cli, "run_seed", side_effect=RuntimeError(sensitive)
        ):
            return_code, internal_payload = self.call_main(self.seed_argv())
        self.assertEqual(return_code, 1)
        self.assertEqual(internal_payload["reason"], "cli_internal_error")
        self.assertNotIn(
            sensitive, canonical_bytes(internal_payload).decode("utf-8")
        )

    def test_provider_gate_blocks_before_any_path_client_or_store_touch(self) -> None:
        argv = [
            "probe",
            "--run-id", RUN_ID,
            "--database", str(self.root / "missing" / "staging.sqlite3"),
            "--raw-archive-dir", str(self.root / "missing" / "raw"),
            "--report-dir", str(self.root / "missing" / "reports"),
            "--release-manifest", str(self.root / "missing.json"),
        ]
        with patch.dict(os.environ, {}, clear=True), patch.object(
            backfill_cli, "BackfillStore"
        ) as store_type, patch.object(backfill_cli, "TikHubClient") as client_type:
            return_code, payload = self.call_main(argv)

        self.assertEqual(return_code, 1)
        self.assertEqual(payload["schema_version"], "backfill_provider_gate_v1")
        self.assertEqual(payload["status"], "blocked")
        self.assertFalse(payload["provider_call"])
        self.assertFalse(payload["provider_attempt_made"])
        self.assertFalse(payload["live_send"])
        store_type.assert_not_called()
        client_type.assert_not_called()
        self.assertFalse((self.root / "missing").exists())

    def test_parser_exposes_no_probe_budget_or_page_override(self) -> None:
        parser = backfill_cli.build_parser()
        with self.assertRaises(backfill_cli.BackfillArgumentError):
            parser.parse_args(
                [
                    "probe",
                    "--run-id", RUN_ID,
                    "--database", "db",
                    "--raw-archive-dir", "raw",
                    "--report-dir", "reports",
                    "--release-manifest", "manifest",
                    "--max-provider-requests", "99",
                ]
            )

    def test_invalid_cli_arguments_emit_one_secret_free_stable_error(self) -> None:
        sensitive = "SENSITIVE_MARKER/private/provider-token"
        output = StringIO()
        errors = StringIO()
        argv = [*self.seed_argv(), "--unexpected-sensitive-path", sensitive]

        with redirect_stdout(output), redirect_stderr(errors):
            return_code = backfill_cli.main(argv)

        self.assertEqual(return_code, 1)
        self.assertEqual(errors.getvalue(), "")
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        payload = json.loads(lines[0])
        self.assertEqual(payload["schema_version"], "backfill_cli_error_v1")
        self.assertEqual(payload["command"], "seed")
        self.assertIsNone(payload["run_id"])
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "cli_arguments_invalid")
        self.assertFalse(payload["provider_call"])
        self.assertFalse(payload["production_write"])
        self.assertFalse(payload["live_send"])
        self.assertNotIn(sensitive, output.getvalue())
        self.assertNotIn(sensitive, errors.getvalue())

    def test_release_bundle_loader_is_fixed_path_exact_and_owner_sha_first(self) -> None:
        code_root, baseline_path, manifest_path, manifest_sha, baseline = (
            self.make_release_bundle()
        )
        with patch.object(backfill_cli, "CODE_ROOT", code_root):
            loaded = backfill_cli.load_release_bundle(
                manifest_path,
                baseline_path=baseline_path,
                comment_cursor_path=code_root / backfill_cli.COMMENT_CURSOR_RELATIVE_PATH,
                run_id=RUN_ID,
                expected_manifest_sha256=manifest_sha,
            )
        self.assertEqual(loaded.manifest_sha256, manifest_sha)
        self.assertEqual(loaded.seed_baseline, baseline)
        self.assertEqual(
            loaded.comment_cursor_contract.cursor_path,
            (
                "data",
                "postInfoById",
                "commentForest",
                "pageInfo",
                "endCursor",
            ),
        )

        wrong_expected = "f" * 64
        with patch.object(backfill_cli, "CODE_ROOT", code_root):
            with self.assertRaisesRegex(
                backfill_cli.BackfillCliError, "release_manifest_sha256_mismatch"
            ):
                backfill_cli.load_release_bundle(
                    manifest_path,
                    baseline_path=baseline_path,
                    comment_cursor_path=code_root / backfill_cli.COMMENT_CURSOR_RELATIVE_PATH,
                    run_id=RUN_ID,
                    expected_manifest_sha256=wrong_expected,
                )

    def test_release_bundle_rejects_duplicate_json_missing_map_and_symlink(self) -> None:
        code_root, baseline_path, manifest_path, _, _ = self.make_release_bundle()
        duplicate = (
            '{"schema_version":"momcozy_backfill_release_manifest_v1",'
            '"schema_version":"momcozy_backfill_release_manifest_v1"}'
        ).encode("utf-8")
        manifest_path.write_bytes(duplicate)
        with patch.object(backfill_cli, "CODE_ROOT", code_root):
            with self.assertRaisesRegex(
                backfill_cli.BackfillCliError, "release_manifest_invalid"
            ):
                backfill_cli.load_release_bundle(
                    manifest_path,
                    baseline_path=baseline_path,
                    comment_cursor_path=code_root / backfill_cli.COMMENT_CURSOR_RELATIVE_PATH,
                    run_id=RUN_ID,
                )

    def test_release_bundle_rejects_baseline_inode_swap_during_admission(self) -> None:
        code_root, baseline_path, manifest_path, _, _ = self.make_release_bundle()
        original_reader = backfill_cli._read_pinned_reviewed_file
        swapped = False

        def swap_after_pinned_read(path: Path, *, reason: str):
            nonlocal swapped
            pinned = original_reader(path, reason=reason)
            if path == baseline_path and not swapped:
                replacement = baseline_payload()
                replacement["source_inventory_sha256"] = "f" * 64
                replacement_without_hash = dict(replacement)
                replacement_without_hash.pop("baseline_sha256")
                replacement["baseline_sha256"] = canonical_sha(
                    replacement_without_hash
                )
                temporary = baseline_path.with_name("replacement-baseline.json")
                temporary.write_bytes(canonical_bytes(replacement))
                temporary.replace(baseline_path)
                swapped = True
            return pinned

        with patch.object(backfill_cli, "CODE_ROOT", code_root), patch.object(
            backfill_cli,
            "_read_pinned_reviewed_file",
            side_effect=swap_after_pinned_read,
        ):
            with self.assertRaisesRegex(
                backfill_cli.BackfillCliError,
                "reviewed_file_changed_during_admission",
            ):
                backfill_cli.load_release_bundle(
                    manifest_path,
                    baseline_path=baseline_path,
                    comment_cursor_path=(
                        code_root / backfill_cli.COMMENT_CURSOR_RELATIVE_PATH
                    ),
                    run_id=RUN_ID,
                )

        code_root, baseline_path, manifest_path, _, _ = self.make_release_bundle()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["reviewed_files_sha256"].pop(backfill_cli.RELEASE_REVIEWED_PATHS[0])
        manifest_path.write_bytes(canonical_bytes(manifest))
        with patch.object(backfill_cli, "CODE_ROOT", code_root):
            with self.assertRaisesRegex(
                backfill_cli.BackfillCliError, "release_manifest_file_map_invalid"
            ):
                backfill_cli.load_release_bundle(
                    manifest_path,
                    baseline_path=baseline_path,
                    comment_cursor_path=code_root / backfill_cli.COMMENT_CURSOR_RELATIVE_PATH,
                    run_id=RUN_ID,
                )

        code_root, baseline_path, manifest_path, _, _ = self.make_release_bundle()
        real_baseline = code_root / "real-baseline.json"
        baseline_path.replace(real_baseline)
        baseline_path.symlink_to(real_baseline)
        with patch.object(backfill_cli, "CODE_ROOT", code_root):
            with self.assertRaisesRegex(
                backfill_cli.BackfillCliError, "reviewed_file_unsafe"
            ):
                backfill_cli.load_release_bundle(
                    manifest_path,
                    baseline_path=baseline_path,
                    comment_cursor_path=code_root / backfill_cli.COMMENT_CURSOR_RELATIVE_PATH,
                    run_id=RUN_ID,
                )

    def test_seed_creates_budget_four_manifest_and_is_idempotent(self) -> None:
        source = self.root / "source"
        source.mkdir()
        database = self.root / "run" / "reddit_voc_backfill.sqlite3"
        raw = self.root / "run" / "private-raw"
        reports = self.root / "run" / "reports"
        argv = [
            "seed",
            "--run-id", RUN_ID,
            "--database", str(database),
            "--source-dir", str(source),
            "--raw-archive-dir", str(raw),
            "--report-dir", str(reports),
            "--window-start-utc", "2024-12-31T16:00:00Z",
            "--requested-window-end-utc", "2026-07-11T16:00:00Z",
            "--effective-window-end-utc", "2026-07-11T16:00:00Z",
        ]
        first_code, first = self.call_main(argv)
        second_code, second = self.call_main(argv)
        self.assertEqual((first_code, second_code), (0, 0))
        self.assertEqual(first, second)
        self.assertEqual(first["schema_version"], "backfill_seed_cli_v1")
        self.assertFalse(first["seed"]["provider_call"])
        self.assertFalse(first["seed"]["live_send"])
        with sqlite3.connect(database) as conn:
            row = conn.execute(
                "SELECT max_provider_requests, provider_request_count, "
                "include_subreddit_sweep, provider_call, live_send "
                "FROM backfill_manifests WHERE run_id=?",
                (RUN_ID,),
            ).fetchone()
        self.assertEqual(row, (4, 0, 0, 0, 0))

    def test_seed_rejects_production_like_and_hardlinked_database_without_mutation(self) -> None:
        source = self.root / "source"
        source.mkdir()
        production = self.root / "production.sqlite3"
        VocStore(production).migrate()
        production_before = production.read_bytes()

        for case in ("hardlink", "copy"):
            with self.subTest(case=case):
                run_root = self.root / f"{case}-run"
                run_root.mkdir()
                database = run_root / "reddit_voc_backfill.sqlite3"
                if case == "hardlink":
                    os.link(production, database)
                else:
                    database.write_bytes(production_before)
                database_before = database.read_bytes()
                argv = [
                    "seed",
                    "--run-id", RUN_ID,
                    "--database", str(database),
                    "--source-dir", str(source),
                    "--raw-archive-dir", str(run_root / "private-raw"),
                    "--report-dir", str(run_root / "reports"),
                    "--window-start-utc", "2024-12-31T16:00:00Z",
                    "--requested-window-end-utc", "2026-07-11T16:00:00Z",
                    "--effective-window-end-utc", "2026-07-11T16:00:00Z",
                ]
                return_code, payload = self.call_main(argv)
                self.assertEqual(return_code, 1)
                self.assertEqual(
                    payload["reason"],
                    (
                        "staging_database_link_count_invalid"
                        if case == "hardlink"
                        else "existing_database_is_not_backfill_staging"
                    ),
                )
                self.assertEqual(database.read_bytes(), database_before)
                self.assertEqual(production.read_bytes(), production_before)
                with sqlite3.connect(production) as connection:
                    backfill_table = connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' "
                        "AND name='backfill_manifests'"
                    ).fetchone()
                self.assertIsNone(backfill_table)

    def test_seed_rejects_inode_swap_before_migrate_without_external_mutation(self) -> None:
        source = self.root / "source"
        source.mkdir()
        run_root = self.root / "run"
        run_root.mkdir()
        database = run_root / "reddit_voc_backfill.sqlite3"
        database.touch()
        production = self.root / "fixture-production.sqlite3"
        VocStore(production).migrate()
        production_before = production.read_bytes()
        production_inode = production.stat().st_ino
        original_admission = backfill_cli._admit_existing_seed_database

        def swap_after_admission(path: Path):
            admission = original_admission(path)
            path.unlink()
            os.link(production, path)
            self.assertEqual(path.stat().st_ino, production_inode)
            return admission

        argv = [
            "seed",
            "--run-id", RUN_ID,
            "--database", str(database),
            "--source-dir", str(source),
            "--raw-archive-dir", str(run_root / "private-raw"),
            "--report-dir", str(run_root / "reports"),
            "--window-start-utc", "2024-12-31T16:00:00Z",
            "--requested-window-end-utc", "2026-07-11T16:00:00Z",
            "--effective-window-end-utc", "2026-07-11T16:00:00Z",
        ]
        with patch.object(
            backfill_cli,
            "_admit_existing_seed_database",
            side_effect=swap_after_admission,
        ):
            return_code, payload = self.call_main(argv)

        database.unlink()
        self.assertEqual(return_code, 1)
        self.assertEqual(payload["reason"], "staging_database_link_count_invalid")
        self.assertEqual(production.read_bytes(), production_before)
        with sqlite3.connect(production) as connection:
            backfill_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='backfill_manifests'"
            ).fetchone()
        self.assertIsNone(backfill_table)

    def test_seed_does_not_write_connection_opened_during_swap_and_restore(self) -> None:
        source = self.root / "source"
        source.mkdir()
        run_root = self.root / "run"
        database = run_root / "reddit_voc_backfill.sqlite3"
        BackfillStore(database).migrate()
        admitted_database = run_root / "admitted-backfill.sqlite3"
        production = self.root / "fixture-production.sqlite3"
        VocStore(production).migrate()
        production_before = production.read_bytes()
        production_inode = production.stat().st_ino
        original_connect = BackfillStore.connect
        restored = False

        def restore_after_connection_open(store: BackfillStore):
            nonlocal restored
            if not restored:
                database.replace(admitted_database)
                os.link(production, database)
                self.assertEqual(database.stat().st_ino, production_inode)
                if store.path == database:
                    connection = sqlite3.connect(production, timeout=5.0)
                    connection.row_factory = sqlite3.Row
                    connection.execute("PRAGMA foreign_keys = ON")
                else:
                    connection = original_connect(store)
                database.unlink()
                admitted_database.replace(database)
                restored = True
                return connection
            return original_connect(store)

        argv = [
            "seed",
            "--run-id", RUN_ID,
            "--database", str(database),
            "--source-dir", str(source),
            "--raw-archive-dir", str(run_root / "private-raw"),
            "--report-dir", str(run_root / "reports"),
            "--window-start-utc", "2024-12-31T16:00:00Z",
            "--requested-window-end-utc", "2026-07-11T16:00:00Z",
            "--effective-window-end-utc", "2026-07-11T16:00:00Z",
        ]
        try:
            with patch.object(
                BackfillStore,
                "connect",
                autospec=True,
                side_effect=restore_after_connection_open,
            ):
                self.call_main(argv)
        finally:
            if admitted_database.exists():
                if database.exists():
                    database.unlink()
                admitted_database.replace(database)

        self.assertTrue(restored)
        self.assertEqual(production.read_bytes(), production_before)
        with sqlite3.connect(production) as connection:
            backfill_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='backfill_manifests'"
            ).fetchone()
        self.assertIsNone(backfill_table)

    def test_seed_reports_identity_drift_when_migration_also_fails(self) -> None:
        source = self.root / "source"
        source.mkdir()
        run_root = self.root / "run"
        run_root.mkdir()
        database = run_root / "reddit_voc_backfill.sqlite3"
        database.touch()
        admitted_database = run_root / "admitted-backfill.sqlite3"
        production = self.root / "fixture-production.sqlite3"
        VocStore(production).migrate()
        production_before = production.read_bytes()

        def fail_after_public_path_swap(store: BackfillStore) -> None:
            self.assertNotEqual(store.path, database)
            database.replace(admitted_database)
            os.link(production, database)
            raise backfill_cli.BackfillSchemaError("fixture_migration_failure")

        argv = [
            "seed",
            "--run-id", RUN_ID,
            "--database", str(database),
            "--source-dir", str(source),
            "--raw-archive-dir", str(run_root / "private-raw"),
            "--report-dir", str(run_root / "reports"),
            "--window-start-utc", "2024-12-31T16:00:00Z",
            "--requested-window-end-utc", "2026-07-11T16:00:00Z",
            "--effective-window-end-utc", "2026-07-11T16:00:00Z",
        ]
        try:
            with patch.object(
                BackfillStore,
                "migrate",
                autospec=True,
                side_effect=fail_after_public_path_swap,
            ):
                return_code, payload = self.call_main(argv)
        finally:
            if admitted_database.exists():
                if database.exists():
                    database.unlink()
                admitted_database.replace(database)

        self.assertEqual(return_code, 1)
        self.assertEqual(payload["reason"], "staging_database_link_count_invalid")
        self.assertEqual(production.read_bytes(), production_before)
        with sqlite3.connect(production) as connection:
            backfill_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='backfill_manifests'"
            ).fetchone()
        self.assertIsNone(backfill_table)

    def test_probe_uses_two_total_pages_and_replays_existing_report_without_calls(self) -> None:
        staging = self.make_staging()
        raw = staging.parent / "private-raw"
        raw.mkdir()
        reports = staging.parent / "reports"
        code_root, _, manifest_path, _, _ = self.make_release_bundle()
        client = FakeTikHubClient(
            [discovery_page("cursor-1", "one"), discovery_page("cursor-2", "two")]
        )
        argv = [
            "probe",
            "--run-id", RUN_ID,
            "--database", str(staging),
            "--raw-archive-dir", str(raw),
            "--report-dir", str(reports),
            "--release-manifest", str(manifest_path),
            "--authorize-provider-call",
        ]
        environment = {
            "REDDIT_VOC_BACKFILL_AUTHORIZE_PROVIDER_CALL": "1",
            "REDDIT_VOC_ENABLE_TIKHUB": "1",
            "TIKHUB_API_KEY": "fixture-key",
        }
        with patch.dict(os.environ, environment, clear=True), patch.object(
            backfill_cli, "CODE_ROOT", code_root
        ), patch.object(backfill_cli, "TikHubClient", return_value=client):
            first_code, first = self.call_main(argv)
            second_code, second = self.call_main(argv)

        self.assertEqual((first_code, second_code), (0, 0))
        self.assertEqual(first, second)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(first["contract_probe_max_requests"], 4)
        self.assertEqual(first["committed_pages"], 2)
        self.assertEqual(first["provider_request_count_after"], 2)
        self.assertTrue(first["provider_call"])
        self.assertFalse(first["live_send"])
        self.assertEqual(
            tuple(first["cursor_path"]),
            (
                "data",
                "search",
                "dynamic",
                "components",
                "main",
                "pageInfo",
                "endCursor",
            ),
        )

    def test_rejected_probe_snapshot_does_not_block_resume_to_ready_report(self) -> None:
        staging = self.make_staging()
        raw = staging.parent / "private-raw"
        raw.mkdir()
        reports = staging.parent / "reports"
        code_root, _, manifest_path, _, _ = self.make_release_bundle()
        client = FakeTikHubClient(
            [
                discovery_page("cursor-1", "one"),
                HTTPError("https://fixture.invalid", 422, "invalid", None, None),
                discovery_page("cursor-2", "two"),
            ]
        )
        argv = [
            "probe",
            "--run-id", RUN_ID,
            "--database", str(staging),
            "--raw-archive-dir", str(raw),
            "--report-dir", str(reports),
            "--release-manifest", str(manifest_path),
            "--authorize-provider-call",
        ]
        environment = {
            "REDDIT_VOC_BACKFILL_AUTHORIZE_PROVIDER_CALL": "1",
            "REDDIT_VOC_ENABLE_TIKHUB": "1",
            "TIKHUB_API_KEY": "fixture-key",
        }
        with patch.dict(os.environ, environment, clear=True), patch.object(
            backfill_cli, "CODE_ROOT", code_root
        ), patch.object(backfill_cli, "TikHubClient", return_value=client):
            first_code, first = self.call_main(argv)
            self.assertFalse((reports / f"{RUN_ID}-probe.json").exists())
            second_code, second = self.call_main(argv)

        self.assertEqual((first_code, second_code), (1, 0))
        self.assertEqual(first["status"], "rejected")
        self.assertEqual(second["status"], "ready")
        self.assertEqual(second["committed_pages"], 2)
        self.assertEqual(second["provider_request_count_after"], 3)
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(
            len(list(reports.glob(f"{RUN_ID}-probe-rejected-*.json"))), 1
        )
        self.assertTrue((reports / f"{RUN_ID}-probe.json").is_file())

    def test_probe_cursor_loop_is_rejected_and_never_published_as_ready(self) -> None:
        staging = self.make_staging()
        raw = staging.parent / "private-raw"
        raw.mkdir()
        reports = staging.parent / "reports"
        code_root, _, manifest_path, _, _ = self.make_release_bundle()
        client = FakeTikHubClient(
            [discovery_page("same-cursor", "one"), discovery_page("same-cursor", "two")]
        )
        argv = [
            "probe",
            "--run-id", RUN_ID,
            "--database", str(staging),
            "--raw-archive-dir", str(raw),
            "--report-dir", str(reports),
            "--release-manifest", str(manifest_path),
            "--authorize-provider-call",
        ]
        environment = {
            "REDDIT_VOC_BACKFILL_AUTHORIZE_PROVIDER_CALL": "1",
            "REDDIT_VOC_ENABLE_TIKHUB": "1",
            "TIKHUB_API_KEY": "fixture-key",
        }
        with patch.dict(os.environ, environment, clear=True), patch.object(
            backfill_cli, "CODE_ROOT", code_root
        ), patch.object(backfill_cli, "TikHubClient", return_value=client):
            return_code, payload = self.call_main(argv)
        self.assertEqual(return_code, 1)
        self.assertEqual(payload["status"], "rejected")
        self.assertEqual(payload["stop_reason"], "cursor_loop")
        self.assertFalse((reports / f"{RUN_ID}-probe.json").exists())
        self.assertEqual(
            len(list(reports.glob(f"{RUN_ID}-probe-rejected-*.json"))), 1
        )

    def test_collect_rejects_probe_sha_before_client_or_contract_freeze(self) -> None:
        staging = self.make_staging()
        raw = staging.parent / "private-raw"
        raw.mkdir()
        reports = staging.parent / "reports"
        reports.mkdir()
        probe_report = reports / f"{RUN_ID}-probe.json"
        probe_report.write_bytes(b"{}\n")
        code_root, _, manifest_path, manifest_sha, _ = self.make_release_bundle()
        argv = [
            "collect",
            "--run-id", RUN_ID,
            "--database", str(staging),
            "--raw-archive-dir", str(raw),
            "--report-dir", str(reports),
            "--probe-report", str(probe_report),
            "--expected-probe-sha256", "f" * 64,
            "--release-manifest", str(manifest_path),
            "--expected-release-manifest-sha256", manifest_sha,
            "--comment-cursor-contract", str(
                code_root / backfill_cli.COMMENT_CURSOR_RELATIVE_PATH
            ),
            "--max-provider-requests-total", "100",
            "--include-subreddit-sweep", "0",
            "--authorize-provider-call",
        ]
        environment = {
            "REDDIT_VOC_BACKFILL_AUTHORIZE_PROVIDER_CALL": "1",
            "REDDIT_VOC_ENABLE_TIKHUB": "1",
            "TIKHUB_API_KEY": "fixture-key",
        }
        with patch.dict(os.environ, environment, clear=True), patch.object(
            backfill_cli, "CODE_ROOT", code_root
        ), patch.object(backfill_cli, "TikHubClient") as client_type:
            return_code, payload = self.call_main(argv)
        self.assertEqual(return_code, 1)
        self.assertEqual(payload["reason"], "probe_report_sha256_mismatch")
        client_type.assert_not_called()
        with sqlite3.connect(staging) as conn:
            row = conn.execute(
                "SELECT status, max_provider_requests FROM backfill_manifests "
                "WHERE run_id=?",
                (RUN_ID,),
            ).fetchone()
        self.assertEqual(row, ("seed_complete", 4))

    def test_collect_budget_extension_arguments_are_strict_all_or_none(self) -> None:
        argv = [
            "collect",
            "--run-id", RUN_ID,
            "--database", str(self.root / "staging.sqlite3"),
            "--raw-archive-dir", str(self.root / "private-raw"),
            "--report-dir", str(self.root / "reports"),
            "--probe-report", str(self.root / "reports" / f"{RUN_ID}-probe.json"),
            "--expected-probe-sha256", "a" * 64,
            "--release-manifest", str(self.root / "release.json"),
            "--expected-release-manifest-sha256", "b" * 64,
            "--comment-cursor-contract", str(self.root / "cursor.json"),
            "--max-provider-requests-total", "8",
            "--include-subreddit-sweep", "0",
            "--budget-extension-authorization", str(
                self.root / "reports" / f"{RUN_ID}-budget-extension-authorization.json"
            ),
            "--authorize-provider-call",
        ]
        with patch.object(backfill_cli, "_provider_gate") as provider_gate:
            return_code, payload = self.call_main(argv)

        self.assertEqual(return_code, 1)
        self.assertEqual(
            payload["reason"], "budget_extension_authorization_pair_required"
        )
        provider_gate.assert_not_called()

    def test_collect_existing_budget_resume_arguments_are_strict_all_or_none(self) -> None:
        argv = [
            "collect",
            "--run-id", RUN_ID,
            "--database", str(self.root / "staging.sqlite3"),
            "--raw-archive-dir", str(self.root / "private-raw"),
            "--report-dir", str(self.root / "reports"),
            "--probe-report", str(self.root / "reports" / f"{RUN_ID}-probe.json"),
            "--expected-probe-sha256", "a" * 64,
            "--release-manifest", str(self.root / "release.json"),
            "--expected-release-manifest-sha256", "b" * 64,
            "--comment-cursor-contract", str(self.root / "cursor.json"),
            "--max-provider-requests-total", "10",
            "--include-subreddit-sweep", "0",
            "--existing-budget-resume-authorization", str(
                self.root / "reports"
                / f"{RUN_ID}-existing-budget-resume-authorization.json"
            ),
            "--authorize-provider-call",
        ]
        with patch.object(backfill_cli, "_provider_gate") as provider_gate:
            return_code, payload = self.call_main(argv)

        self.assertEqual(return_code, 1)
        self.assertEqual(
            payload["reason"],
            "existing_budget_resume_authorization_pair_required",
        )
        provider_gate.assert_not_called()

    def test_existing_budget_resume_authorization_is_exact_state_bound(self) -> None:
        source = self.make_staging(budget=10, status="partial")
        store = BackfillStore(source)
        for _ in range(3):
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
            )
        reports = source.parent / "reports"
        reports.mkdir()
        path = reports / f"{RUN_ID}-existing-budget-resume-authorization.json"
        packet = existing_budget_resume_authorization(source)
        raw = canonical_bytes(packet)
        path.write_bytes(raw)

        loaded = backfill_cli._load_existing_budget_resume_authorization(
            path,
            expected_path=path,
            expected_sha256=sha256(raw).hexdigest(),
            run_id=RUN_ID,
            release_manifest_sha256="b" * 64,
            probe_report_sha256="a" * 64,
            source_database=source,
            expected_lanes=backfill_cli.required_lanes_snapshot(
                search_terms=DEFAULT_TIKHUB_SEARCH_TERMS,
                subreddits=DEFAULT_REVIEWED_SUBREDDITS,
                include_subreddit_sweep=False,
            ),
        )
        self.assertEqual(loaded, packet)

        # A first continuation authorization is validated before its ledger
        # row is written.  A source hash that differs from the live snapshot
        # exercises that non-initial path with no pre-existing ledger.
        continuation_packet = {
            **packet,
            "expected_source_database_sha256": "c" * 64,
        }
        continuation_raw = canonical_bytes(continuation_packet)
        path.write_bytes(continuation_raw)
        continuation_loaded = backfill_cli._load_existing_budget_resume_authorization(
            path,
            expected_path=path,
            expected_sha256=sha256(continuation_raw).hexdigest(),
            run_id=RUN_ID,
            release_manifest_sha256="b" * 64,
            probe_report_sha256="a" * 64,
            source_database=source,
            expected_lanes=backfill_cli.required_lanes_snapshot(
                search_terms=DEFAULT_TIKHUB_SEARCH_TERMS,
                subreddits=DEFAULT_REVIEWED_SUBREDDITS,
                include_subreddit_sweep=False,
            ),
        )
        self.assertEqual(continuation_loaded, continuation_packet)

        # Once a ledger exists, a mismatched row must not be accepted.
        continuation_sha256 = sha256(continuation_raw).hexdigest()
        store.record_existing_budget_resume_authorization(
            RUN_ID,
            authorization_sha256=continuation_sha256,
            expected_source_database_sha256="d" * 64,
            expected_provider_request_count=3,
            max_provider_requests=10,
            discovery_request_ceiling=6,
            lane_page_ceilings_sha256=continuation_packet[
                "lane_page_ceilings_sha256"
            ],
            candidate_state_sha256=continuation_packet["candidate_state_sha256"],
            include_subreddit_sweep=False,
            required_lanes_sha256=continuation_packet["required_lanes_sha256"],
            applied_at_utc=NOW,
        )
        with self.assertRaisesRegex(
            backfill_cli.BackfillCliError,
            "existing_budget_resume_authorization_invalid",
        ):
            backfill_cli._load_existing_budget_resume_authorization(
                path,
                expected_path=path,
                expected_sha256=continuation_sha256,
                run_id=RUN_ID,
                release_manifest_sha256="b" * 64,
                probe_report_sha256="a" * 64,
                source_database=source,
                expected_lanes=backfill_cli.required_lanes_snapshot(
                    search_terms=DEFAULT_TIKHUB_SEARCH_TERMS,
                    subreddits=DEFAULT_REVIEWED_SUBREDDITS,
                    include_subreddit_sweep=False,
                ),
            )

        store.save_checkpoint(
            BackfillCheckpoint(
                run_id=RUN_ID,
                lane_type="comments",
                lane_key="drift-post",
                cursor=None,
                previous_cursor=None,
                page_number=0,
                newest_seen_utc=None,
                oldest_seen_utc=None,
                discovered_count=0,
                unique_count=0,
                provider_request_count=3,
                last_success_utc=None,
                last_error=None,
                status="prepared",
                stop_reason=None,
                cursor_json_path=None,
                cursor_schema_sha256=None,
                consecutive_old_pages=0,
            )
        )
        drift_packet = {
            **packet,
            "expected_source_database_sha256": sha256(
                source.read_bytes()
            ).hexdigest(),
        }
        drift_raw = canonical_bytes(drift_packet)
        path.write_bytes(drift_raw)
        with self.assertRaisesRegex(
            backfill_cli.BackfillCliError,
            "existing_budget_resume_authorization_invalid",
        ):
            backfill_cli._load_existing_budget_resume_authorization(
                path,
                expected_path=path,
                expected_sha256=sha256(drift_raw).hexdigest(),
                run_id=RUN_ID,
                release_manifest_sha256="b" * 64,
                probe_report_sha256="a" * 64,
                source_database=source,
                expected_lanes=backfill_cli.required_lanes_snapshot(
                    search_terms=DEFAULT_TIKHUB_SEARCH_TERMS,
                    subreddits=DEFAULT_REVIEWED_SUBREDDITS,
                    include_subreddit_sweep=False,
                ),
            )

    def test_budget_extension_authorization_is_exact_sha_bound_and_canonical(self) -> None:
        root = self.root
        source = root / "continuation.sqlite3"
        source.write_bytes(b"exact-source-snapshot")
        reports = root / "reports"
        reports.mkdir()
        path = reports / f"{RUN_ID}-budget-extension-authorization.json"
        packet = budget_extension_authorization(source)
        raw = canonical_bytes(packet)
        path.write_bytes(raw)

        loaded = backfill_cli._load_budget_extension_authorization(
            path,
            expected_path=path,
            expected_sha256=sha256(raw).hexdigest(),
            run_id=RUN_ID,
            release_manifest_sha256="b" * 64,
            probe_report_sha256="a" * 64,
            source_database=source,
            expected_lanes=backfill_cli.required_lanes_snapshot(
                search_terms=DEFAULT_TIKHUB_SEARCH_TERMS,
                subreddits=DEFAULT_REVIEWED_SUBREDDITS,
                include_subreddit_sweep=True,
            ),
        )

        self.assertEqual(loaded, packet)

    def test_budget_extension_authorization_rejects_drift_fail_closed(self) -> None:
        root = self.root
        source = root / "continuation.sqlite3"
        source.write_bytes(b"exact-source-snapshot")
        reports = root / "reports"
        reports.mkdir()
        expected = reports / f"{RUN_ID}-budget-extension-authorization.json"
        baseline = budget_extension_authorization(source)
        cases = {
            "wrong_source": {
                **baseline,
                "expected_source_database_sha256": "f" * 64,
            },
            "wrong_lane_hash": {
                **baseline,
                "lane_page_ceilings_sha256": "e" * 64,
            },
            "wrong_lane_order": {
                **baseline,
                "lane_page_ceilings": list(
                    reversed(baseline["lane_page_ceilings"])
                ),
                "lane_page_ceilings_sha256": canonical_sha(
                    list(reversed(baseline["lane_page_ceilings"]))
                ),
            },
            "page_ceiling_regression": {
                **baseline,
                "lane_page_ceilings": [
                    {
                        **baseline["lane_page_ceilings"][0],
                        "expected_page_number": 2,
                        "absolute_page_ceiling": 1,
                    },
                    *baseline["lane_page_ceilings"][1:],
                ],
            },
            "reserve_mismatch": {
                **baseline,
                "hydration_request_reserve": 49,
            },
            "wrong_probe_report": {
                **baseline,
                "probe_report_sha256": "c" * 64,
            },
            "live_send": {**baseline, "live_send": True},
            "extra_key": {**baseline, "unexpected": "value"},
        }
        cases["page_ceiling_regression"]["lane_page_ceilings_sha256"] = canonical_sha(
            cases["page_ceiling_regression"]["lane_page_ceilings"]
        )
        for label, packet in cases.items():
            with self.subTest(case=label):
                raw = canonical_bytes(packet)
                expected.write_bytes(raw)
                with self.assertRaises(backfill_cli.BackfillCliError):
                    backfill_cli._load_budget_extension_authorization(
                        expected,
                        expected_path=expected,
                        expected_sha256=sha256(raw).hexdigest(),
                        run_id=RUN_ID,
                        release_manifest_sha256="b" * 64,
                        probe_report_sha256="a" * 64,
                        source_database=source,
                        expected_lanes=backfill_cli.required_lanes_snapshot(
                            search_terms=DEFAULT_TIKHUB_SEARCH_TERMS,
                            subreddits=DEFAULT_REVIEWED_SUBREDDITS,
                            include_subreddit_sweep=True,
                        ),
                    )

        noncanonical = json.dumps(baseline, indent=2).encode("utf-8") + b"\n"
        expected.write_bytes(noncanonical)
        with self.assertRaises(backfill_cli.BackfillCliError):
            backfill_cli._load_budget_extension_authorization(
                expected,
                expected_path=expected,
                expected_sha256=sha256(noncanonical).hexdigest(),
                run_id=RUN_ID,
                release_manifest_sha256="b" * 64,
                probe_report_sha256="a" * 64,
                source_database=source,
                expected_lanes=backfill_cli.required_lanes_snapshot(
                    search_terms=DEFAULT_TIKHUB_SEARCH_TERMS,
                    subreddits=DEFAULT_REVIEWED_SUBREDDITS,
                    include_subreddit_sweep=True,
                ),
            )

    def test_budget_extension_same_authorization_restart_keeps_absolute_cap(self) -> None:
        source = self.make_staging(status="partial")
        store = BackfillStore(source)
        for _ in range(4):
            request_number = store.reserve_provider_request(
                RUN_ID,
                "/api/v1/reddit/app/fetch_dynamic_search",
                NOW,
            )
            self.assertIsNotNone(request_number)
            store.mark_provider_attempt_sent(RUN_ID, request_number, NOW)
            store.complete_provider_attempt(
                RUN_ID,
                request_number,
                status="succeeded",
                completed_at_utc=NOW,
            )
        packet = budget_extension_authorization(
            source,
            expected_provider_request_count=4,
            new_max_provider_requests_total=8,
            discovery_request_ceiling=6,
            include_subreddit_sweep=False,
        )
        path = self.root / "run" / "reports" / (
            f"{RUN_ID}-budget-extension-authorization.json"
        )
        path.parent.mkdir()
        raw = canonical_bytes(packet)
        path.write_bytes(raw)
        authorization_sha256 = sha256(raw).hexdigest()
        with sqlite3.connect(source) as connection:
            connection.execute(
                "INSERT INTO backfill_budget_extensions("
                "run_id, authorization_sha256, expected_provider_request_count, "
                "expected_max_provider_requests, new_max_provider_requests, "
                "discovery_request_ceiling, lane_page_ceilings_sha256, "
                "include_subreddit_sweep, required_lanes_sha256, applied_at_utc"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    RUN_ID,
                    authorization_sha256,
                    4,
                    4,
                    8,
                    6,
                    packet["lane_page_ceilings_sha256"],
                    0,
                    packet["required_lanes_sha256"],
                    NOW.isoformat(),
                ),
            )
            connection.execute(
                "UPDATE backfill_manifests SET max_provider_requests = 8 "
                "WHERE run_id = ?",
                (RUN_ID,),
            )

        loaded = backfill_cli._load_budget_extension_authorization(
            path,
            expected_path=path,
            expected_sha256=authorization_sha256,
            run_id=RUN_ID,
            release_manifest_sha256="b" * 64,
            probe_report_sha256="a" * 64,
            source_database=source,
            expected_lanes=backfill_cli.required_lanes_snapshot(
                search_terms=DEFAULT_TIKHUB_SEARCH_TERMS,
                subreddits=DEFAULT_REVIEWED_SUBREDDITS,
                include_subreddit_sweep=False,
            ),
        )
        self.assertEqual(loaded["discovery_request_ceiling"], 6)

        with sqlite3.connect(source) as connection:
            connection.execute(
                "UPDATE backfill_provider_attempts SET status = 'sent' "
                "WHERE run_id = ? AND request_number = 4",
                (RUN_ID,),
            )
        with self.assertRaisesRegex(
            backfill_cli.BackfillCliError,
            "budget_extension_authorization_invalid",
        ):
            backfill_cli._load_budget_extension_authorization(
                path,
                expected_path=path,
                expected_sha256=authorization_sha256,
                run_id=RUN_ID,
                release_manifest_sha256="b" * 64,
                probe_report_sha256="a" * 64,
                source_database=source,
                expected_lanes=backfill_cli.required_lanes_snapshot(
                    search_terms=DEFAULT_TIKHUB_SEARCH_TERMS,
                    subreddits=DEFAULT_REVIEWED_SUBREDDITS,
                    include_subreddit_sweep=False,
                ),
            )
        with sqlite3.connect(source) as connection:
            connection.execute(
                "UPDATE backfill_provider_attempts SET status = 'succeeded' "
                "WHERE run_id = ? AND request_number = 4",
                (RUN_ID,),
            )

        reset_packet = {
            **packet,
            "discovery_request_ceiling": 7,
            "hydration_request_reserve": 1,
        }
        reset_raw = canonical_bytes(reset_packet)
        path.write_bytes(reset_raw)
        with self.assertRaisesRegex(
            backfill_cli.BackfillCliError,
            "budget_extension_authorization_invalid",
        ):
            backfill_cli._load_budget_extension_authorization(
                path,
                expected_path=path,
                expected_sha256=sha256(reset_raw).hexdigest(),
                run_id=RUN_ID,
                release_manifest_sha256="b" * 64,
                probe_report_sha256="a" * 64,
                source_database=source,
                expected_lanes=backfill_cli.required_lanes_snapshot(
                    search_terms=DEFAULT_TIKHUB_SEARCH_TERMS,
                    subreddits=DEFAULT_REVIEWED_SUBREDDITS,
                    include_subreddit_sweep=False,
                ),
            )

    def test_continuation_checkpoint_drift_rejects_before_mutation_or_client(self) -> None:
        staging = self.make_staging(status="partial")
        raw_archive = staging.parent / "private-raw"
        raw_archive.mkdir()
        reports = staging.parent / "reports"
        reports.mkdir()
        probe_path = reports / f"{RUN_ID}-probe.json"
        probe_path.write_bytes(b"{}\n")
        _, _, _, _, baseline = self.make_release_bundle()
        first_lane = ("dynamic_search", DEFAULT_TIKHUB_SEARCH_TERMS[0])
        packet = budget_extension_authorization(
            staging,
            expected_provider_request_count=4,
            new_max_provider_requests_total=8,
            discovery_request_ceiling=6,
            include_subreddit_sweep=False,
            expected_page_numbers={first_lane: 1},
        )
        authorization_path = reports / (
            f"{RUN_ID}-budget-extension-authorization.json"
        )
        authorization_raw = canonical_bytes(packet)
        authorization_path.write_bytes(authorization_raw)
        database_sha256_before = sha256(staging.read_bytes()).hexdigest()
        argv = [
            "collect",
            "--run-id", RUN_ID,
            "--database", str(staging),
            "--raw-archive-dir", str(raw_archive),
            "--report-dir", str(reports),
            "--probe-report", str(probe_path),
            "--expected-probe-sha256", "a" * 64,
            "--release-manifest", str(self.root / "release.json"),
            "--expected-release-manifest-sha256", "b" * 64,
            "--comment-cursor-contract", str(self.root / "cursor.json"),
            "--max-provider-requests-total", "8",
            "--include-subreddit-sweep", "0",
            "--budget-extension-authorization", str(authorization_path),
            "--expected-budget-extension-authorization-sha256",
            sha256(authorization_raw).hexdigest(),
            "--authorize-provider-call",
        ]
        bundle = backfill_cli.LoadedReleaseBundle(
            manifest_sha256="b" * 64,
            seed_baseline=baseline,
            comment_cursor_contract=backfill_cli.REVIEWED_COMMENT_CURSOR_CONTRACT,
        )
        probe = {
            "provider_request_count_after": 4,
        }
        with patch.object(
            backfill_cli, "_provider_gate", return_value="fixture-key"
        ), patch.object(
            backfill_cli, "_require_isolated_staging_paths"
        ), patch.object(
            backfill_cli, "_verify_approved_probe_sha"
        ), patch.object(
            backfill_cli, "load_release_bundle", return_value=bundle
        ), patch.object(
            backfill_cli, "_load_approved_probe", return_value=probe
        ), patch.object(
            backfill_cli, "_assert_seed_manifest_contract"
        ), patch.object(backfill_cli, "TikHubClient") as client_type:
            return_code, payload = self.call_main(argv)

        self.assertEqual(return_code, 1)
        self.assertEqual(
            payload["reason"], "budget_extension_checkpoint_state_mismatch"
        )
        client_type.assert_not_called()
        self.assertEqual(
            sha256(staging.read_bytes()).hexdigest(), database_sha256_before
        )
        with sqlite3.connect(staging) as connection:
            manifest = connection.execute(
                "SELECT status, max_provider_requests, provider_request_count "
                "FROM backfill_manifests WHERE run_id = ?",
                (RUN_ID,),
            ).fetchone()
            extension_count = connection.execute(
                "SELECT COUNT(*) FROM backfill_budget_extensions"
            ).fetchone()[0]
        self.assertEqual(manifest, ("partial", 4, 0))
        self.assertEqual(extension_count, 0)

    def test_round_robin_gives_each_lane_one_page_before_returning_to_first(self) -> None:
        lanes = (
            {
                "lane_type": "dynamic_search",
                "lane_key": "lane-one",
                "expected_page_number": 0,
                "absolute_page_ceiling": 2,
            },
            {
                "lane_type": "dynamic_search",
                "lane_key": "lane-two",
                "expected_page_number": 0,
                "absolute_page_ceiling": 2,
            },
        )

        class FixtureStore:
            def __init__(self) -> None:
                self.pages: dict[tuple[str, str], int] = {}
                self.request_count = 0

            def load_checkpoint(
                self, *, run_id: str, lane_type: str, lane_key: str
            ) -> object | None:
                del run_id
                page = self.pages.get((lane_type, lane_key))
                return None if page is None else SimpleNamespace(page_number=page)

            def provider_request_count(self, run_id: str) -> int:
                del run_id
                return self.request_count

            def provider_call_evidence(self, run_id: str) -> bool:
                del run_id
                return bool(self.request_count)

        class FixtureDiscoverer:
            def __init__(self, store: FixtureStore) -> None:
                self.store = store
                self.calls: list[tuple[str, str]] = []

            def run_dynamic_search(
                self,
                lane_key: str,
                window: object,
                max_pages: int | None = None,
                *,
                absolute_page_ceiling: int | None = None,
                page_limit_stop_reason: str = "probe_page_limit",
            ) -> LaneResult:
                del window, max_pages
                self.calls.append((lane_key, page_limit_stop_reason))
                key = ("dynamic_search", lane_key)
                page = self.store.pages.get(key, 0)
                if absolute_page_ceiling is not None and page < absolute_page_ceiling:
                    page += 1
                    self.store.pages[key] = page
                    self.store.request_count += 1
                result_stop_reason = (
                    "authorized_page_limit"
                    if absolute_page_ceiling is not None
                    and page >= absolute_page_ceiling
                    else page_limit_stop_reason
                )
                return LaneResult(
                    run_id=RUN_ID,
                    lane_type="dynamic_search",
                    lane_key=lane_key,
                    status="partial",
                    stop_reason=result_stop_reason,
                    pages=page,
                    discovered_occurrences=page,
                    unique_candidates=page,
                    provider_request_count=self.store.request_count,
                    provider_call=True,
                    live_send=False,
                )

        store = FixtureStore()
        discoverer = FixtureDiscoverer(store)
        results = backfill_cli._run_discovery_round_robin(
            discoverer,
            store,
            run_id=RUN_ID,
            window=Mock(),
            lane_page_ceilings=lanes,
        )

        self.assertEqual(
            discoverer.calls,
            [
                ("lane-one", "round_robin_yield"),
                ("lane-two", "round_robin_yield"),
                ("lane-one", "round_robin_yield"),
                ("lane-two", "round_robin_yield"),
            ],
        )
        self.assertEqual([result.pages for result in results], [2, 2])
        self.assertEqual(
            [result.stop_reason for result in results],
            ["authorized_page_limit", "authorized_page_limit"],
        )

    def test_round_robin_skips_persisted_terminal_lanes_below_ceiling(self) -> None:
        terminal_states = (
            ("failed", "provider_error"),
            ("partial", "provider_error"),
            ("partial", "schema_drift"),
            ("partial", "cursor_loop"),
        )
        lane = {
            "lane_type": "dynamic_search",
            "lane_key": "terminal-lane",
            "expected_page_number": 1,
            "absolute_page_ceiling": 5,
        }

        for status, stop_reason in terminal_states:
            with self.subTest(status=status, stop_reason=stop_reason):
                checkpoint = SimpleNamespace(
                    status=status,
                    stop_reason=stop_reason,
                    page_number=1,
                    discovered_count=3,
                    unique_count=2,
                )
                store = Mock()
                store.load_checkpoint.return_value = checkpoint
                store.provider_request_count.return_value = 4
                store.provider_call_evidence.return_value = True
                discoverer = Mock()
                discoverer.run_dynamic_search.return_value = LaneResult(
                    run_id=RUN_ID,
                    lane_type="dynamic_search",
                    lane_key="terminal-lane",
                    status="complete",
                    stop_reason="unexpected_retry",
                    pages=2,
                    discovered_occurrences=4,
                    unique_candidates=3,
                    provider_request_count=5,
                    provider_call=True,
                    live_send=False,
                )

                results = backfill_cli._run_discovery_round_robin(
                    discoverer,
                    store,
                    run_id=RUN_ID,
                    window=Mock(),
                    lane_page_ceilings=(lane,),
                )

                discoverer.run_dynamic_search.assert_not_called()
                self.assertEqual(results[0].status, status)
                self.assertEqual(results[0].stop_reason, stop_reason)
                self.assertEqual(results[0].pages, 1)

    def test_phase_exhaustion_does_not_mask_unvisited_failed_lane(self) -> None:
        lanes = (
            {
                "lane_type": "dynamic_search",
                "lane_key": "budget-lane",
                "expected_page_number": 0,
                "absolute_page_ceiling": 5,
            },
            {
                "lane_type": "dynamic_search",
                "lane_key": "failed-lane",
                "expected_page_number": 1,
                "absolute_page_ceiling": 5,
            },
        )
        checkpoints = {
            "budget-lane": SimpleNamespace(
                status="partial",
                stop_reason="discovery_budget_exhausted",
                page_number=0,
                discovered_count=0,
                unique_count=0,
            ),
            "failed-lane": SimpleNamespace(
                status="failed",
                stop_reason="provider_error",
                page_number=1,
                discovered_count=3,
                unique_count=2,
            ),
        }
        store = Mock()
        store.load_checkpoint.side_effect = (
            lambda *, run_id, lane_type, lane_key: checkpoints[lane_key]
        )
        store.provider_request_count.return_value = 4
        store.provider_call_evidence.return_value = True
        discoverer = Mock()
        discoverer.run_dynamic_search.return_value = LaneResult(
            run_id=RUN_ID,
            lane_type="dynamic_search",
            lane_key="budget-lane",
            status="partial",
            stop_reason="discovery_budget_exhausted",
            pages=0,
            discovered_occurrences=0,
            unique_candidates=0,
            provider_request_count=4,
            provider_call=True,
            live_send=False,
        )

        results = backfill_cli._run_discovery_round_robin(
            discoverer,
            store,
            run_id=RUN_ID,
            window=Mock(),
            lane_page_ceilings=lanes,
        )

        discoverer.run_dynamic_search.assert_called_once()
        self.assertEqual(results[0].stop_reason, "discovery_budget_exhausted")
        self.assertEqual(results[1].status, "failed")
        self.assertEqual(results[1].stop_reason, "provider_error")

    def test_phase_exhaustion_overrides_prior_round_robin_yield(self) -> None:
        lanes = tuple(
            {
                "lane_type": "dynamic_search",
                "lane_key": lane_key,
                "expected_page_number": 0,
                "absolute_page_ceiling": 5,
            }
            for lane_key in ("yielded-lane", "budget-lane")
        )
        checkpoints: dict[str, SimpleNamespace | None] = {
            "yielded-lane": None,
            "budget-lane": None,
        }
        store = Mock()
        store.load_checkpoint.side_effect = (
            lambda *, run_id, lane_type, lane_key: checkpoints[lane_key]
        )
        store.provider_request_count.return_value = 4
        store.provider_call_evidence.return_value = True

        def discover(lane_key: str, *_args: object, **_kwargs: object) -> LaneResult:
            stop_reason = (
                "round_robin_yield"
                if lane_key == "yielded-lane"
                else "discovery_budget_exhausted"
            )
            page_number = 1 if lane_key == "yielded-lane" else 0
            discovered_count = 1 if lane_key == "yielded-lane" else 0
            unique_count = 1 if lane_key == "yielded-lane" else 0
            checkpoints[lane_key] = SimpleNamespace(
                status="partial",
                stop_reason=stop_reason,
                page_number=page_number,
                discovered_count=discovered_count,
                unique_count=unique_count,
            )
            return LaneResult(
                run_id=RUN_ID,
                lane_type="dynamic_search",
                lane_key=lane_key,
                status="partial",
                stop_reason=stop_reason,
                pages=page_number,
                discovered_occurrences=discovered_count,
                unique_candidates=unique_count,
                provider_request_count=4,
                provider_call=True,
                live_send=False,
            )

        discoverer = Mock()
        discoverer.run_dynamic_search.side_effect = discover
        results = backfill_cli._run_discovery_round_robin(
            discoverer,
            store,
            run_id=RUN_ID,
            window=Mock(),
            lane_page_ceilings=lanes,
        )

        self.assertEqual(
            [result.stop_reason for result in results],
            ["discovery_budget_exhausted", "discovery_budget_exhausted"],
        )

    def test_reindex_discovery_parser_maps_exact_offline_contract(self) -> None:
        args = backfill_cli.build_parser().parse_args(
            [
                "reindex-discovery",
                "--run-id", RUN_ID,
                "--source-database", "/run/source.sqlite3",
                "--raw-archive-dir", "/run/private-raw",
                "--reindexed-database", "/run/reindexed.sqlite3",
                "--expected-source-database-sha256", "a" * 64,
                "--release-manifest", "/code/release.json",
                "--expected-release-manifest-sha256", "b" * 64,
                "--report", "/run/reports/reindex.json",
            ]
        )

        self.assertEqual(args.command, "reindex-discovery")
        self.assertEqual(args.source_database, Path("/run/source.sqlite3"))
        self.assertEqual(args.raw_archive_dir, Path("/run/private-raw"))
        self.assertEqual(args.reindexed_database, Path("/run/reindexed.sqlite3"))
        self.assertEqual(args.report, Path("/run/reports/reindex.json"))

    def test_collection_recovery_parser_maps_exact_offline_contract(self) -> None:
        args = backfill_cli.build_parser().parse_args(
            [
                "recover-collection",
                "--run-id", RUN_ID,
                "--source-database", "/run/source.sqlite3",
                "--raw-archive-dir", "/run/private-raw",
                "--recovered-database", "/run/recovered.sqlite3",
                "--expected-source-database-sha256", "a" * 64,
                "--recovered-at-utc", "2026-07-14T08:00:00+00:00",
                "--release-manifest", "/code/release.json",
                "--expected-release-manifest-sha256", "b" * 64,
                "--report", "/run/reports/recovery.json",
            ]
        )

        self.assertEqual(args.command, "recover-collection")
        self.assertEqual(args.reindexed_database, Path("/run/recovered.sqlite3"))
        self.assertEqual(args.recovered_at_utc, "2026-07-14T08:00:00+00:00")

    def test_collection_recovery_publishes_verified_offline_envelope(self) -> None:
        args, _, _, target, report, source_sha256 = self.recovery_args()
        _, _, _, _, baseline = self.make_release_bundle()
        bundle = backfill_cli.LoadedReleaseBundle(
            manifest_sha256="b" * 64,
            seed_baseline=baseline,
            comment_cursor_contract=backfill_cli.REVIEWED_COMMENT_CURSOR_CONTRACT,
        )
        target_payload = b"fixture-recovered-database"
        target_sha256 = sha256(target_payload).hexdigest()
        result = self.recovery_result(
            source_sha256=source_sha256,
            target_sha256=target_sha256,
        )

        def execute_recovery(*_args: object, **_kwargs: object) -> dict[str, object]:
            target.write_bytes(target_payload)
            return result

        with patch.object(
            backfill_cli, "load_release_bundle", return_value=bundle
        ), patch.object(
            backfill_cli,
            "recover_collection_from_archive",
            side_effect=execute_recovery,
        ) as recover, patch.object(backfill_cli, "TikHubClient") as client_type:
            return_code, envelope = backfill_cli.run_recover_collection(args)

        self.assertEqual(return_code, 0)
        self.assertEqual(
            envelope,
            {
                "schema_version": "backfill_collection_recovery_cli_envelope_v1",
                "run_id": RUN_ID,
                "release_manifest_sha256": "b" * 64,
                "expected_source_database_sha256": source_sha256,
                "recovered_at_utc": "2026-07-14T08:00:00+00:00",
                "recovery": result,
            },
        )
        self.assertEqual(json.loads(report.read_text("utf-8")), envelope)
        self.assertEqual(
            recover.call_args.kwargs["expected_source_db_sha256"],
            source_sha256,
        )
        client_type.assert_not_called()

    def test_collection_recovery_rejects_result_drift_without_report(self) -> None:
        args, _, _, target, report, source_sha256 = self.recovery_args()
        _, _, _, _, baseline = self.make_release_bundle()
        bundle = backfill_cli.LoadedReleaseBundle(
            manifest_sha256="b" * 64,
            seed_baseline=baseline,
            comment_cursor_contract=backfill_cli.REVIEWED_COMMENT_CURSOR_CONTRACT,
        )
        target_payload = b"fixture-recovered-database"
        result = self.recovery_result(
            source_sha256=source_sha256,
            target_sha256=sha256(target_payload).hexdigest(),
        )
        result["provider_attempt_made"] = True

        def execute_recovery(*_args: object, **_kwargs: object) -> dict[str, object]:
            target.write_bytes(target_payload)
            return result

        with patch.object(
            backfill_cli, "load_release_bundle", return_value=bundle
        ), patch.object(
            backfill_cli,
            "recover_collection_from_archive",
            side_effect=execute_recovery,
        ):
            with self.assertRaisesRegex(
                backfill_cli.BackfillCliError,
                "collection_recovery_target_committed_needs_review",
            ):
                backfill_cli.run_recover_collection(args)

        self.assertFalse(report.exists())

    def test_reindex_discovery_rejects_wrong_source_sha_before_release(self) -> None:
        args, _, _, _, report, _ = self.reindex_args()
        args.expected_source_database_sha256 = "a" * 64

        with patch.object(backfill_cli, "load_release_bundle") as load_bundle, patch.object(
            backfill_cli, "reindex_discovery_from_archive", create=True
        ) as reindex:
            with self.assertRaisesRegex(
                backfill_cli.BackfillCliError,
                "reindex_source_database_sha256_mismatch",
            ):
                backfill_cli.run_reindex_discovery(args)

        load_bundle.assert_not_called()
        reindex.assert_not_called()
        self.assertFalse(report.exists())

    def test_reindex_discovery_publishes_verified_offline_envelope(self) -> None:
        args, _, _, target, report, source_sha256 = self.reindex_args()
        _, _, _, _, baseline = self.make_release_bundle()
        bundle = backfill_cli.LoadedReleaseBundle(
            manifest_sha256="b" * 64,
            seed_baseline=baseline,
            comment_cursor_contract=backfill_cli.REVIEWED_COMMENT_CURSOR_CONTRACT,
        )
        target_payload = b"fixture-reindexed-database"
        target_sha256 = sha256(target_payload).hexdigest()
        result = self.reindex_result(
            source_sha256=source_sha256, target_sha256=target_sha256
        )

        def execute_reindex(*_args: object, **_kwargs: object) -> dict[str, object]:
            target.write_bytes(target_payload)
            return result

        with patch.object(
            backfill_cli, "load_release_bundle", return_value=bundle
        ) as load_bundle, patch.object(
            backfill_cli,
            "reindex_discovery_from_archive",
            side_effect=execute_reindex,
            create=True,
        ) as reindex, patch.object(backfill_cli, "TikHubClient") as client_type:
            return_code, envelope = backfill_cli.run_reindex_discovery(args)

        self.assertEqual(return_code, 0)
        self.assertEqual(
            envelope,
            {
                "schema_version": "backfill_discovery_reindex_cli_envelope_v1",
                "run_id": RUN_ID,
                "release_manifest_sha256": "b" * 64,
                "expected_source_database_sha256": source_sha256,
                "reindex": result,
            },
        )
        self.assertEqual(json.loads(report.read_text("utf-8")), envelope)
        load_bundle.assert_called_once()
        self.assertEqual(
            reindex.call_args.kwargs["expected_source_db_sha256"], source_sha256
        )
        client_type.assert_not_called()

    def test_reindex_result_drift_after_publish_requires_manual_review(self) -> None:
        args, _, _, target, report, source_sha256 = self.reindex_args()
        _, _, _, _, baseline = self.make_release_bundle()
        bundle = backfill_cli.LoadedReleaseBundle(
            manifest_sha256="b" * 64,
            seed_baseline=baseline,
            comment_cursor_contract=backfill_cli.REVIEWED_COMMENT_CURSOR_CONTRACT,
        )
        target_payload = b"fixture-reindexed-database"
        result = self.reindex_result(
            source_sha256=source_sha256,
            target_sha256=sha256(target_payload).hexdigest(),
        )
        result["target_provider_request_count"] = 669

        def execute_reindex(*_args: object, **_kwargs: object) -> dict[str, object]:
            target.write_bytes(target_payload)
            return result

        with patch.object(
            backfill_cli, "load_release_bundle", return_value=bundle
        ), patch.object(
            backfill_cli,
            "reindex_discovery_from_archive",
            side_effect=execute_reindex,
            create=True,
        ):
            with self.assertRaisesRegex(
                backfill_cli.BackfillCliError,
                "reindex_target_committed_needs_review",
            ):
                backfill_cli.run_reindex_discovery(args)

        self.assertTrue(target.exists())
        self.assertFalse(report.exists())

    def test_reindex_unreadable_postlibrary_target_state_fails_as_committed(self) -> None:
        args, _, _, target, report, source_sha256 = self.reindex_args(
            name="postlibrary-target-unreadable"
        )
        _, _, _, _, baseline = self.make_release_bundle()
        bundle = backfill_cli.LoadedReleaseBundle(
            manifest_sha256="b" * 64,
            seed_baseline=baseline,
            comment_cursor_contract=backfill_cli.REVIEWED_COMMENT_CURSOR_CONTRACT,
        )
        target_payload = b"fixture-reindexed-database"
        result = self.reindex_result(
            source_sha256=source_sha256,
            target_sha256=sha256(target_payload).hexdigest(),
        )
        result["target_provider_request_count"] = 669
        original_residue = backfill_cli._reindex_target_has_residue
        calls = 0

        def execute_reindex(*_args: object, **_kwargs: object) -> dict[str, object]:
            target.write_bytes(target_payload)
            return result

        def residue_then_unreadable(path: Path) -> bool:
            nonlocal calls
            calls += 1
            if calls == 1:
                return original_residue(path)
            raise backfill_cli.BackfillCliError(
                "reindex_target_state_unreadable"
            )

        with (
            patch.object(
                backfill_cli, "load_release_bundle", return_value=bundle
            ),
            patch.object(
                backfill_cli,
                "reindex_discovery_from_archive",
                side_effect=execute_reindex,
            ),
            patch.object(
                backfill_cli,
                "_reindex_target_has_residue",
                side_effect=residue_then_unreadable,
            ),
        ):
            with self.assertRaisesRegex(
                backfill_cli.BackfillCliError,
                "reindex_target_committed_needs_review",
            ):
                backfill_cli.run_reindex_discovery(args)

        self.assertTrue(target.exists())
        self.assertFalse(report.exists())

    def test_reindex_rejects_source_and_target_sidecar_namespace_overlap(self) -> None:
        cases = ("target_is_source_wal", "report_is_source_journal", "report_is_target_shm")
        for case in cases:
            with self.subTest(case=case):
                args, source, _, target, _, _ = self.reindex_args(name=case)
                if case == "target_is_source_wal":
                    args.reindexed_database = Path(str(source) + "-wal")
                elif case == "report_is_source_journal":
                    args.report = Path(str(source) + "-journal")
                else:
                    args.report = Path(str(target) + "-shm")

                with self.assertRaisesRegex(
                    backfill_cli.BackfillCliError, "reindex_paths_overlap"
                ):
                    backfill_cli._admit_reindex_paths(args)

    def test_reindex_target_sidecar_after_publish_requires_manual_review(self) -> None:
        args, _, _, target, report, source_sha256 = self.reindex_args()
        _, _, _, _, baseline = self.make_release_bundle()
        bundle = backfill_cli.LoadedReleaseBundle(
            manifest_sha256="b" * 64,
            seed_baseline=baseline,
            comment_cursor_contract=backfill_cli.REVIEWED_COMMENT_CURSOR_CONTRACT,
        )
        target_payload = b"fixture-reindexed-database"
        result = self.reindex_result(
            source_sha256=source_sha256,
            target_sha256=sha256(target_payload).hexdigest(),
        )

        def execute_reindex(*_args: object, **_kwargs: object) -> dict[str, object]:
            target.write_bytes(target_payload)
            Path(str(target) + "-wal").write_bytes(b"unexpected-wal")
            return result

        with patch.object(
            backfill_cli, "load_release_bundle", return_value=bundle
        ), patch.object(
            backfill_cli,
            "reindex_discovery_from_archive",
            side_effect=execute_reindex,
        ):
            with self.assertRaisesRegex(
                backfill_cli.BackfillCliError,
                "reindex_target_committed_needs_review",
            ):
                backfill_cli.run_reindex_discovery(args)

        self.assertTrue(target.exists())
        self.assertTrue(Path(str(target) + "-wal").exists())
        self.assertFalse(report.exists())

    def test_reindex_removes_success_report_if_target_sidecar_appears_during_publish(
        self,
    ) -> None:
        args, _, _, target, report, source_sha256 = self.reindex_args(
            name="report-publish-sidecar"
        )
        _, _, _, _, baseline = self.make_release_bundle()
        bundle = backfill_cli.LoadedReleaseBundle(
            manifest_sha256="b" * 64,
            seed_baseline=baseline,
            comment_cursor_contract=backfill_cli.REVIEWED_COMMENT_CURSOR_CONTRACT,
        )
        target_payload = b"fixture-reindexed-database"
        result = self.reindex_result(
            source_sha256=source_sha256,
            target_sha256=sha256(target_payload).hexdigest(),
        )
        original_publish = backfill_cli._publish_json

        def execute_reindex(*_args: object, **_kwargs: object) -> dict[str, object]:
            target.write_bytes(target_payload)
            return result

        def publish_then_add_target_wal(path: Path, payload: object) -> None:
            original_publish(path, payload)
            if path == report:
                Path(str(target) + "-wal").write_bytes(b"late-target-wal")

        with (
            patch.object(
                backfill_cli, "load_release_bundle", return_value=bundle
            ),
            patch.object(
                backfill_cli,
                "reindex_discovery_from_archive",
                side_effect=execute_reindex,
            ),
            patch.object(
                backfill_cli,
                "_publish_json",
                side_effect=publish_then_add_target_wal,
            ),
        ):
            with self.assertRaisesRegex(
                backfill_cli.BackfillCliError,
                "reindex_target_committed_needs_review",
            ):
                backfill_cli.run_reindex_discovery(args)

        self.assertTrue(target.exists())
        self.assertTrue(Path(str(target) + "-wal").exists())
        self.assertFalse(report.exists())

    def test_reindex_removes_success_report_after_postlink_publish_error(self) -> None:
        args, _, _, target, report, source_sha256 = self.reindex_args(
            name="report-postlink-error"
        )
        _, _, _, _, baseline = self.make_release_bundle()
        bundle = backfill_cli.LoadedReleaseBundle(
            manifest_sha256="b" * 64,
            seed_baseline=baseline,
            comment_cursor_contract=backfill_cli.REVIEWED_COMMENT_CURSOR_CONTRACT,
        )
        target_payload = b"fixture-reindexed-database"
        result = self.reindex_result(
            source_sha256=source_sha256,
            target_sha256=sha256(target_payload).hexdigest(),
        )
        original_publish = backfill_cli._publish_json

        def execute_reindex(*_args: object, **_kwargs: object) -> dict[str, object]:
            target.write_bytes(target_payload)
            return result

        def publish_then_fail(path: Path, payload: object) -> None:
            original_publish(path, payload)
            if path == report:
                raise backfill_cli.BackfillCliError(
                    "output_committed_needs_review"
                )

        with (
            patch.object(
                backfill_cli, "load_release_bundle", return_value=bundle
            ),
            patch.object(
                backfill_cli,
                "reindex_discovery_from_archive",
                side_effect=execute_reindex,
            ),
            patch.object(
                backfill_cli,
                "_publish_json",
                side_effect=publish_then_fail,
            ),
        ):
            with self.assertRaisesRegex(
                backfill_cli.BackfillCliError,
                "reindex_target_committed_needs_review",
            ):
                backfill_cli.run_reindex_discovery(args)

        self.assertTrue(target.exists())
        self.assertFalse(report.exists())

    def test_reindex_rejects_target_main_drift_during_report_publish(self) -> None:
        args, _, _, target, report, source_sha256 = self.reindex_args(
            name="report-target-main-drift"
        )
        _, _, _, _, baseline = self.make_release_bundle()
        bundle = backfill_cli.LoadedReleaseBundle(
            manifest_sha256="b" * 64,
            seed_baseline=baseline,
            comment_cursor_contract=backfill_cli.REVIEWED_COMMENT_CURSOR_CONTRACT,
        )
        target_payload = b"fixture-reindexed-database"
        result = self.reindex_result(
            source_sha256=source_sha256,
            target_sha256=sha256(target_payload).hexdigest(),
        )
        original_publish = backfill_cli._publish_json

        def execute_reindex(*_args: object, **_kwargs: object) -> dict[str, object]:
            target.write_bytes(target_payload)
            return result

        def publish_then_mutate_target(path: Path, payload: object) -> None:
            original_publish(path, payload)
            if path == report:
                target.write_bytes(b"mutated-after-report-publish")

        with (
            patch.object(
                backfill_cli, "load_release_bundle", return_value=bundle
            ),
            patch.object(
                backfill_cli,
                "reindex_discovery_from_archive",
                side_effect=execute_reindex,
            ),
            patch.object(
                backfill_cli,
                "_publish_json",
                side_effect=publish_then_mutate_target,
            ),
        ):
            with self.assertRaisesRegex(
                backfill_cli.BackfillCliError,
                "reindex_target_committed_needs_review",
            ):
                backfill_cli.run_reindex_discovery(args)

        self.assertTrue(target.exists())
        self.assertNotEqual(sha256(target.read_bytes()).hexdigest(), result["target_db_sha256"])
        self.assertFalse(report.exists())

    def test_reindex_postcommit_exceptions_require_manual_review(self) -> None:
        exceptions = (
            backfill_cli.ReplayPublicationError(
                publication_state="target_exists_needs_review"
            ),
            sqlite3.DatabaseError("postcommit fixture"),
        )
        for index, exception in enumerate(exceptions):
            with self.subTest(exception=type(exception).__name__):
                args, _, _, target, report, _ = self.reindex_args(
                    name=f"postcommit-{index}"
                )
                _, _, _, _, baseline = self.make_release_bundle()
                bundle = backfill_cli.LoadedReleaseBundle(
                    manifest_sha256="b" * 64,
                    seed_baseline=baseline,
                    comment_cursor_contract=(
                        backfill_cli.REVIEWED_COMMENT_CURSOR_CONTRACT
                    ),
                )

                def execute_reindex(
                    *_args: object,
                    error: Exception = exception,
                    **_kwargs: object,
                ) -> dict[str, object]:
                    target.write_bytes(b"committed-target")
                    raise error

                with patch.object(
                    backfill_cli, "load_release_bundle", return_value=bundle
                ), patch.object(
                    backfill_cli,
                    "reindex_discovery_from_archive",
                    side_effect=execute_reindex,
                ):
                    with self.assertRaisesRegex(
                        backfill_cli.BackfillCliError,
                        "reindex_target_committed_needs_review",
                    ):
                        backfill_cli.run_reindex_discovery(args)

                self.assertTrue(target.exists())
                self.assertFalse(report.exists())

    def test_historical_probe_release_is_only_accepted_for_bound_continuation(self) -> None:
        recommendations = backfill_cli._probe_recommendations(
            pages=1, unique_candidates=1
        )
        report = {
            "schema_version": "backfill_contract_probe_v1",
            "run_id": RUN_ID,
            "status": "ready",
            "stop_reason": "cursor_exhausted",
            "contract_probe_max_requests": 4,
            "provider_request_count_before": 0,
            "provider_request_count_after": 1,
            "attempts_used": 1,
            "dynamic_search_term_sha256": sha256(
                DEFAULT_TIKHUB_SEARCH_TERMS[0].encode("utf-8")
            ).hexdigest(),
            "committed_pages": 1,
            "unique_candidates": 1,
            "cursor_path": ["data", "pageInfo", "endCursor"],
            "cursor_schema_sha256": "c" * 64,
            "observed_page_span_seconds": 0.0,
            "recommended_max_provider_requests": recommendations[0],
            "recommended_max_provider_requests_with_subreddit_sweep": (
                recommendations[1]
            ),
            "cost_uncertainty": "high_unbounded_comment_pagination",
            "release_manifest_sha256": "d" * 64,
            "provider_call": True,
            "live_send": False,
        }
        path = self.root / f"{RUN_ID}-probe.json"
        raw = canonical_bytes(report)
        path.write_bytes(raw)

        continuation = backfill_cli._load_approved_probe(
            path,
            expected_path=path,
            expected_sha256=sha256(raw).hexdigest(),
            run_id=RUN_ID,
            release_manifest_sha256="b" * 64,
            allow_historical_release_manifest=True,
        )
        self.assertEqual(continuation, report)
        with self.assertRaisesRegex(
            backfill_cli.BackfillCliError, "probe_report_invalid"
        ):
            backfill_cli._load_approved_probe(
                path,
                expected_path=path,
                expected_sha256=sha256(raw).hexdigest(),
                run_id=RUN_ID,
                release_manifest_sha256="b" * 64,
            )

    def test_partial_continuation_requires_extension_before_client(self) -> None:
        staging = self.make_staging(status="partial")
        reports = staging.parent / "reports"
        reports.mkdir()
        argv = [
            "collect",
            "--run-id", RUN_ID,
            "--database", str(staging),
            "--raw-archive-dir", str(staging.parent / "private-raw"),
            "--report-dir", str(reports),
            "--probe-report", str(reports / f"{RUN_ID}-probe.json"),
            "--expected-probe-sha256", "a" * 64,
            "--release-manifest", str(self.root / "release.json"),
            "--expected-release-manifest-sha256", "b" * 64,
            "--comment-cursor-contract", str(self.root / "cursor.json"),
            "--max-provider-requests-total", "8",
            "--include-subreddit-sweep", "0",
            "--authorize-provider-call",
        ]
        _, _, _, _, baseline = self.make_release_bundle()
        bundle = backfill_cli.LoadedReleaseBundle(
            manifest_sha256="b" * 64,
            seed_baseline=baseline,
            comment_cursor_contract=backfill_cli.REVIEWED_COMMENT_CURSOR_CONTRACT,
        )
        with patch.object(
            backfill_cli, "_provider_gate", return_value="fixture-key"
        ), patch.object(
            backfill_cli, "_require_isolated_staging_paths"
        ), patch.object(
            backfill_cli, "_verify_approved_probe_sha"
        ), patch.object(
            backfill_cli, "load_release_bundle", return_value=bundle
        ), patch.object(
            backfill_cli, "_assert_seed_manifest_contract"
        ), patch.object(backfill_cli, "TikHubClient") as client_type:
            return_code, payload = self.call_main(argv)

        self.assertEqual(return_code, 1)
        self.assertEqual(
            payload["reason"], "budget_extension_authorization_pair_required"
        )
        client_type.assert_not_called()

    def test_continuation_wrong_probe_sha_rejects_before_client(self) -> None:
        staging = self.make_staging(status="partial")
        reports = staging.parent / "reports"
        reports.mkdir()
        probe_path = reports / f"{RUN_ID}-probe.json"
        probe_path.write_bytes(b"{}\n")
        authorization_path = reports / (
            f"{RUN_ID}-budget-extension-authorization.json"
        )
        argv = [
            "collect",
            "--run-id", RUN_ID,
            "--database", str(staging),
            "--raw-archive-dir", str(staging.parent / "private-raw"),
            "--report-dir", str(reports),
            "--probe-report", str(probe_path),
            "--expected-probe-sha256", "a" * 64,
            "--release-manifest", str(self.root / "release.json"),
            "--expected-release-manifest-sha256", "b" * 64,
            "--comment-cursor-contract", str(self.root / "cursor.json"),
            "--max-provider-requests-total", "8",
            "--include-subreddit-sweep", "0",
            "--budget-extension-authorization", str(authorization_path),
            "--expected-budget-extension-authorization-sha256", "c" * 64,
            "--authorize-provider-call",
        ]
        with patch.object(
            backfill_cli, "_provider_gate", return_value="fixture-key"
        ), patch.object(
            backfill_cli, "_require_isolated_staging_paths"
        ), patch.object(backfill_cli, "TikHubClient") as client_type:
            return_code, payload = self.call_main(argv)

        self.assertEqual(return_code, 1)
        self.assertEqual(payload["reason"], "probe_report_sha256_mismatch")
        client_type.assert_not_called()

    def test_discovery_phase_ceiling_preserves_hydration_reserve(self) -> None:
        staging = self.make_staging(status="partial")
        reports = staging.parent / "reports"
        authorization_path = reports / (
            f"{RUN_ID}-budget-extension-authorization.json"
        )
        packet = budget_extension_authorization(
            staging,
            expected_provider_request_count=4,
            new_max_provider_requests_total=8,
            discovery_request_ceiling=6,
            include_subreddit_sweep=False,
        )
        authorization_sha256 = "c" * 64
        args = backfill_cli.build_parser().parse_args(
            [
                "collect",
                "--run-id", RUN_ID,
                "--database", str(staging),
                "--raw-archive-dir", str(staging.parent / "private-raw"),
                "--report-dir", str(reports),
                "--probe-report", str(reports / f"{RUN_ID}-probe.json"),
                "--expected-probe-sha256", "a" * 64,
                "--release-manifest", str(self.root / "release.json"),
                "--expected-release-manifest-sha256", "b" * 64,
                "--comment-cursor-contract", str(self.root / "cursor.json"),
                "--max-provider-requests-total", "8",
                "--include-subreddit-sweep", "0",
                "--budget-extension-authorization", str(authorization_path),
                "--expected-budget-extension-authorization-sha256",
                authorization_sha256,
                "--authorize-provider-call",
            ]
        )
        _, _, _, _, baseline = self.make_release_bundle()
        bundle = backfill_cli.LoadedReleaseBundle(
            manifest_sha256="b" * 64,
            seed_baseline=baseline,
            comment_cursor_contract=backfill_cli.REVIEWED_COMMENT_CURSOR_CONTRACT,
        )
        row = {
            "status": "partial",
            "window_start_utc": "2024-12-31T16:00:00+00:00",
            "effective_end_utc": "2026-07-11T16:00:00+00:00",
        }
        phase_result = LaneResult(
            run_id=RUN_ID,
            lane_type="dynamic_search",
            lane_key=DEFAULT_TIKHUB_SEARCH_TERMS[0],
            status="partial",
            stop_reason="discovery_budget_exhausted",
            pages=1,
            discovered_occurrences=1,
            unique_candidates=1,
            provider_request_count=6,
            provider_call=True,
            live_send=False,
        )
        hydration_result = replace(
            phase_result,
            lane_type="detail_batch",
            lane_key="hydration",
            status="complete",
            stop_reason="hydration_complete",
            provider_request_count=8,
        )
        store = Mock()
        store.hydration_resume_recorded.return_value = True
        store.provider_request_count.side_effect = [4, 6, 8]
        store.load_hydration_outcomes.return_value = []
        store.provider_call_evidence.return_value = True
        discovery_executor = Mock(name="discovery_executor")
        hydration_executor = Mock(name="hydration_executor")
        executor_type = Mock(
            side_effect=[discovery_executor, hydration_executor]
        )
        hydrator_type = Mock()
        hydrator_type.return_value.hydrate.return_value = hydration_result

        with patch.object(
            backfill_cli, "_provider_gate", return_value="fixture-key"
        ), patch.object(
            backfill_cli, "_require_isolated_staging_paths"
        ), patch.object(
            backfill_cli, "_verify_approved_probe_sha"
        ), patch.object(
            backfill_cli, "load_release_bundle", return_value=bundle
        ), patch.object(
            backfill_cli, "BackfillStore", return_value=store
        ), patch.object(
            backfill_cli, "_manifest_row", side_effect=[row, row]
        ), patch.object(
            backfill_cli, "_assert_seed_manifest_contract"
        ), patch.object(
            backfill_cli,
            "_load_budget_extension_authorization",
            return_value=packet,
        ) as load_authorization, patch.object(
            backfill_cli, "_assert_budget_extension_checkpoint_state"
        ), patch.object(
            backfill_cli,
            "_load_approved_probe",
            return_value={"provider_request_count_after": 4},
        ), patch.object(
            backfill_cli, "PrivateRawArchive", return_value=Mock()
        ), patch.object(
            backfill_cli, "TikHubClient", return_value=Mock()
        ), patch.object(
            backfill_cli, "TikHubRequestExecutor", executor_type
        ), patch.object(
            backfill_cli, "TikHubBackfillDiscoverer", return_value=Mock()
        ), patch.object(
            backfill_cli,
            "_run_discovery_round_robin",
            return_value=[phase_result],
        ), patch.object(
            backfill_cli, "TikHubDetailHydrator", hydrator_type
        ), patch.object(backfill_cli, "_publish_evidence_snapshot"):
            return_code, payload = backfill_cli.run_collect(args)

        self.assertEqual(return_code, 1)
        load_authorization.assert_called_once()
        store.extend_full_collection_budget.assert_called_once()
        store.resume_budget_exhausted_hydration.assert_not_called()
        self.assertEqual(
            executor_type.call_args_list[0].kwargs["request_ceiling"], 6
        )
        self.assertNotIn("request_ceiling", executor_type.call_args_list[1].kwargs)
        self.assertIs(hydrator_type.call_args.args[0], hydration_executor)
        hydrator_type.return_value.hydrate.assert_called_once()
        self.assertEqual(payload["stop_reason"], "discovery_budget_exhausted")
        self.assertEqual(payload["discovery_request_ceiling"], 6)
        self.assertEqual(payload["hydration_request_reserve"], 2)
        self.assertEqual(payload["discovery_provider_requests_used"], 2)
        self.assertEqual(payload["hydration_provider_requests_used"], 2)
        self.assertEqual(
            payload["budget_extension_authorization_sha256"],
            authorization_sha256,
        )
        self.assertEqual(
            set(payload),
            {
                "schema_version",
                "run_id",
                "status",
                "stop_reason",
                "max_provider_requests_total",
                "provider_request_count",
                "include_subreddit_sweep",
                "required_lanes_sha256",
                "lane_results",
                "hydration",
                "provider_call",
                "live_send",
                "provider_request_count_before",
                "provider_request_count_after_discovery",
                "discovery_provider_requests_used",
                "hydration_provider_requests_used",
                "budget_extension_authorization_sha256",
                "discovery_request_ceiling",
                "hydration_request_reserve",
                "lane_page_ceilings_sha256",
            },
        )
        self.assertEqual(payload["schema_version"], "backfill_collect_v2")

    def test_existing_budget_resume_uses_remaining_budget_without_extension(self) -> None:
        staging = self.make_staging(budget=10, status="partial")
        reports = staging.parent / "reports"
        authorization_path = reports / (
            f"{RUN_ID}-existing-budget-resume-authorization.json"
        )
        packet = existing_budget_resume_authorization(staging)
        authorization_sha256 = "d" * 64
        args = backfill_cli.build_parser().parse_args(
            [
                "collect",
                "--run-id", RUN_ID,
                "--database", str(staging),
                "--raw-archive-dir", str(staging.parent / "private-raw"),
                "--report-dir", str(reports),
                "--probe-report", str(reports / f"{RUN_ID}-probe.json"),
                "--expected-probe-sha256", "a" * 64,
                "--release-manifest", str(self.root / "release.json"),
                "--expected-release-manifest-sha256", "b" * 64,
                "--comment-cursor-contract", str(self.root / "cursor.json"),
                "--max-provider-requests-total", "10",
                "--include-subreddit-sweep", "0",
                "--existing-budget-resume-authorization", str(authorization_path),
                "--expected-existing-budget-resume-authorization-sha256",
                authorization_sha256,
                "--authorize-provider-call",
            ]
        )
        _, _, _, _, baseline = self.make_release_bundle()
        bundle = backfill_cli.LoadedReleaseBundle(
            manifest_sha256="b" * 64,
            seed_baseline=baseline,
            comment_cursor_contract=backfill_cli.REVIEWED_COMMENT_CURSOR_CONTRACT,
        )
        row = {
            "status": "partial",
            "window_start_utc": "2024-12-31T16:00:00+00:00",
            "effective_end_utc": "2026-07-11T16:00:00+00:00",
        }
        phase_result = LaneResult(
            run_id=RUN_ID,
            lane_type="dynamic_search",
            lane_key=DEFAULT_TIKHUB_SEARCH_TERMS[0],
            status="partial",
            stop_reason="discovery_budget_exhausted",
            pages=1,
            discovered_occurrences=1,
            unique_candidates=1,
            provider_request_count=6,
            provider_call=True,
            live_send=False,
        )
        hydration_result = replace(
            phase_result,
            lane_type="detail_batch",
            lane_key="hydration",
            status="complete",
            stop_reason="hydration_complete",
            provider_request_count=10,
        )
        store = Mock()
        store.provider_request_count.side_effect = [3, 6, 10]
        store.load_hydration_outcomes.return_value = []
        store.provider_call_evidence.return_value = True
        discovery_executor = Mock(name="discovery_executor")
        hydration_executor = Mock(name="hydration_executor")
        executor_type = Mock(
            side_effect=[discovery_executor, hydration_executor]
        )
        hydrator_type = Mock()
        hydrator_type.return_value.hydrate.return_value = hydration_result

        with patch.object(
            backfill_cli, "_provider_gate", return_value="fixture-key"
        ), patch.object(
            backfill_cli, "_require_isolated_staging_paths"
        ), patch.object(
            backfill_cli, "_verify_approved_probe_sha"
        ), patch.object(
            backfill_cli, "load_release_bundle", return_value=bundle
        ), patch.object(
            backfill_cli, "BackfillStore", return_value=store
        ), patch.object(
            backfill_cli, "_manifest_row", side_effect=[row, row]
        ), patch.object(
            backfill_cli, "_assert_seed_manifest_contract"
        ), patch.object(
            backfill_cli,
            "_load_existing_budget_resume_authorization",
            return_value=packet,
        ), patch.object(
            backfill_cli, "_assert_existing_budget_resume_checkpoint_state"
        ), patch.object(
            backfill_cli,
            "_load_approved_probe",
            return_value={"provider_request_count_after": 3},
        ), patch.object(
            backfill_cli, "PrivateRawArchive", return_value=Mock()
        ), patch.object(
            backfill_cli, "TikHubClient", return_value=Mock()
        ), patch.object(
            backfill_cli, "TikHubRequestExecutor", executor_type
        ), patch.object(
            backfill_cli, "TikHubBackfillDiscoverer", return_value=Mock()
        ), patch.object(
            backfill_cli,
            "_run_discovery_round_robin",
            return_value=[phase_result],
        ), patch.object(
            backfill_cli, "TikHubDetailHydrator", hydrator_type
        ), patch.object(backfill_cli, "_publish_evidence_snapshot"):
            return_code, payload = backfill_cli.run_collect(args)

        self.assertEqual(return_code, 1)
        store.record_existing_budget_resume_authorization.assert_called_once()
        store.extend_full_collection_budget.assert_not_called()
        store.resume_budget_exhausted_hydration.assert_not_called()
        self.assertEqual(
            executor_type.call_args_list[0].kwargs["request_ceiling"], 6
        )
        self.assertNotIn("request_ceiling", executor_type.call_args_list[1].kwargs)
        self.assertEqual(payload["schema_version"], "backfill_collect_v3")
        self.assertEqual(
            payload["existing_budget_resume_authorization_sha256"],
            authorization_sha256,
        )
        self.assertNotIn("budget_extension_authorization_sha256", payload)
        self.assertEqual(payload["discovery_provider_requests_used"], 3)
        self.assertEqual(payload["hydration_provider_requests_used"], 4)

    def test_collect_stop_reason_identifies_the_incomplete_component(self) -> None:
        complete_lane = LaneResult(
            run_id=RUN_ID,
            lane_type="dynamic_search",
            lane_key="fixture",
            status="complete",
            stop_reason="cursor_exhausted",
            pages=1,
            discovered_occurrences=0,
            unique_candidates=0,
            provider_request_count=1,
            provider_call=True,
            live_send=False,
        )
        partial_lane = replace(
            complete_lane,
            status="partial",
            stop_reason="provider_budget_exhausted",
        )
        complete_hydration = replace(
            complete_lane,
            lane_type="detail_batch",
            lane_key="hydration",
            stop_reason="hydration_complete",
        )
        partial_hydration = replace(
            complete_hydration,
            status="partial",
            stop_reason="provider_error",
        )

        self.assertEqual(
            backfill_cli._collection_stop_reason(
                [partial_lane], complete_hydration
            ),
            "provider_budget_exhausted",
        )
        self.assertEqual(
            backfill_cli._collection_stop_reason(
                [complete_lane], partial_hydration
            ),
            "provider_error",
        )
        self.assertEqual(
            backfill_cli._collection_stop_reason(
                [complete_lane], complete_hydration
            ),
            "collection_complete",
        )

    def test_collect_initial_freezes_contract_and_partial_resume_requires_extension(
        self,
    ) -> None:
        staging = self.make_staging()
        raw = staging.parent / "private-raw"
        raw.mkdir()
        reports = staging.parent / "reports"
        code_root, _, manifest_path, manifest_sha, _ = self.make_release_bundle()
        probe_client = FakeTikHubClient(
            [discovery_page("cursor-1", "one"), discovery_page("cursor-2", "two")]
        )
        probe_argv = [
            "probe",
            "--run-id", RUN_ID,
            "--database", str(staging),
            "--raw-archive-dir", str(raw),
            "--report-dir", str(reports),
            "--release-manifest", str(manifest_path),
            "--authorize-provider-call",
        ]
        environment = {
            "REDDIT_VOC_BACKFILL_AUTHORIZE_PROVIDER_CALL": "1",
            "REDDIT_VOC_ENABLE_TIKHUB": "1",
            "TIKHUB_API_KEY": "fixture-key",
        }
        with patch.dict(os.environ, environment, clear=True), patch.object(
            backfill_cli, "CODE_ROOT", code_root
        ), patch.object(backfill_cli, "TikHubClient", return_value=probe_client):
            probe_code, _ = self.call_main(probe_argv)
        self.assertEqual(probe_code, 0)
        probe_report = reports / f"{RUN_ID}-probe.json"
        probe_sha = sha256(probe_report.read_bytes()).hexdigest()

        collect_argv = [
            "collect",
            "--run-id", RUN_ID,
            "--database", str(staging),
            "--raw-archive-dir", str(raw),
            "--report-dir", str(reports),
            "--probe-report", str(probe_report),
            "--expected-probe-sha256", probe_sha,
            "--release-manifest", str(manifest_path),
            "--expected-release-manifest-sha256", manifest_sha,
            "--comment-cursor-contract", str(
                code_root / backfill_cli.COMMENT_CURSOR_RELATIVE_PATH
            ),
            "--max-provider-requests-total", "100",
            "--include-subreddit-sweep", "0",
            "--authorize-provider-call",
        ]
        complete_lane = LaneResult(
            run_id=RUN_ID,
            lane_type="dynamic_search",
            lane_key="fixture",
            status="complete",
            stop_reason="cursor_exhausted",
            pages=2,
            discovered_occurrences=2,
            unique_candidates=2,
            provider_request_count=2,
            provider_call=True,
            live_send=False,
        )
        complete_hydration = replace(
            complete_lane,
            lane_type="detail_batch",
            lane_key="hydration",
            stop_reason="hydration_complete",
        )
        partial_hydration = replace(
            complete_hydration,
            status="partial",
            stop_reason="provider_error",
        )
        discoverer_type = Mock()
        discoverer_type.return_value.run_dynamic_search.return_value = complete_lane
        first_hydrator_type = Mock()
        first_hydrator_type.return_value.hydrate.return_value = partial_hydration
        with patch.dict(os.environ, environment, clear=True), patch.object(
            backfill_cli, "CODE_ROOT", code_root
        ), patch.object(backfill_cli, "TikHubClient", return_value=Mock()), patch.object(
            backfill_cli, "TikHubBackfillDiscoverer", discoverer_type
        ), patch.object(backfill_cli, "TikHubDetailHydrator", first_hydrator_type):
            first_code, first = self.call_main(collect_argv)
        second_hydrator_type = Mock()
        second_hydrator_type.return_value.hydrate.return_value = complete_hydration
        with patch.dict(os.environ, environment, clear=True), patch.object(
            backfill_cli, "CODE_ROOT", code_root
        ), patch.object(backfill_cli, "TikHubClient", return_value=Mock()), patch.object(
            backfill_cli, "TikHubBackfillDiscoverer", discoverer_type
        ), patch.object(backfill_cli, "TikHubDetailHydrator", second_hydrator_type):
            second_code, second = self.call_main(collect_argv)

        self.assertEqual((first_code, second_code), (1, 1))
        self.assertEqual(first["status"], "partial")
        self.assertEqual(first["schema_version"], "backfill_collect_v1")
        self.assertEqual(
            set(first),
            {
                "schema_version",
                "run_id",
                "status",
                "stop_reason",
                "max_provider_requests_total",
                "provider_request_count",
                "include_subreddit_sweep",
                "required_lanes_sha256",
                "lane_results",
                "hydration",
                "provider_call",
                "live_send",
            },
        )
        self.assertEqual(
            second["reason"], "budget_extension_authorization_pair_required"
        )
        second_hydrator_type.assert_not_called()
        self.assertEqual(
            len(list(reports.glob(f"{RUN_ID}-collect-*.json"))), 1
        )
        with sqlite3.connect(staging) as connection:
            row = connection.execute(
                "SELECT status, max_provider_requests, provider_request_count, "
                "include_subreddit_sweep, required_lanes_sha256 "
                "FROM backfill_manifests WHERE run_id=?",
                (RUN_ID,),
            ).fetchone()
        self.assertEqual(row[0:4], ("partial", 100, 2, 0))
        self.assertEqual(
            row[4],
            backfill_cli.required_lanes_sha256(
                search_terms=DEFAULT_TIKHUB_SEARCH_TERMS,
                subreddits=DEFAULT_REVIEWED_SUBREDDITS,
                include_subreddit_sweep=False,
            ),
        )

    def test_validate_writes_exact_envelope_without_mutating_nested_result(self) -> None:
        result = validation_result()
        baseline = SeedBaseline(
            **{
                **baseline_payload(),
                "reviewed_subreddits": tuple(DEFAULT_REVIEWED_SUBREDDITS),
            }
        )
        bundle = backfill_cli.LoadedReleaseBundle(
            manifest_sha256="a" * 64,
            seed_baseline=baseline,
            comment_cursor_contract=backfill_cli.REVIEWED_COMMENT_CURSOR_CONTRACT,
        )
        report = self.root / "acceptance.json"
        (self.root / "staging.sqlite3").touch()
        (self.root / "replay.sqlite3").touch()
        argv = [
            "validate",
            "--scope", "full",
            "--run-id", RUN_ID,
            "--database", str(self.root / "staging.sqlite3"),
            "--raw-archive-dir", str(self.root / "raw"),
            "--replay-database", str(self.root / "replay.sqlite3"),
            "--run-root", str(self.root),
            "--seed-baseline", str(self.root / "baseline.json"),
            "--release-manifest", str(self.root / "manifest.json"),
            "--expected-release-manifest-sha256", "a" * 64,
            "--report", str(report),
        ]
        with patch.object(
            backfill_cli, "load_release_bundle", return_value=bundle
        ), patch.object(backfill_cli, "BackfillStore") as store_type, patch.object(
            backfill_cli, "PrivateRawArchive"
        ) as archive_type, patch.object(
            backfill_cli, "validate_backfill", return_value=result
        ) as validate:
            return_code, payload = self.call_main(argv)

        self.assertEqual(return_code, 0)
        self.assertEqual(
            set(payload),
            {
                "schema_version",
                "run_id",
                "scope",
                "release_manifest_sha256",
                "validation",
            },
        )
        self.assertEqual(payload["validation"], result)
        self.assertIsNot(payload["validation"], result)
        self.assertEqual(json.loads(report.read_text(encoding="utf-8")), payload)
        call = validate.call_args
        self.assertIs(call.kwargs["seed_baseline"], baseline)
        self.assertNotIn("release_manifest", call.kwargs)
        store_type.assert_called_once()
        archive_type.assert_called_once_with(self.root / "raw", read_only=True)

    def test_validate_full_requires_owner_manifest_sha_and_replay_inputs(self) -> None:
        parser = backfill_cli.build_parser()
        args = parser.parse_args(
            [
                "validate",
                "--scope", "full",
                "--run-id", RUN_ID,
                "--database", "db",
                "--raw-archive-dir", "raw",
                "--seed-baseline", "baseline",
                "--release-manifest", "manifest",
                "--report", "report",
            ]
        )
        with self.assertRaisesRegex(
            backfill_cli.BackfillCliError, "full_validation_inputs_required"
        ):
            backfill_cli.run_validate(args)

    def test_merge_production_gate_precedes_all_file_reads(self) -> None:
        argv = [
            "merge-production",
            "--run-id", RUN_ID,
            "--staging-database", str(self.root / "missing-staging"),
            "--production-database", str(self.root / "missing-production"),
            "--acceptance-report", str(self.root / "missing-acceptance"),
            "--expected-acceptance-report-sha256", "a" * 64,
            "--merge-plan", str(self.root / "missing-plan"),
            "--expected-merge-plan-sha256", "b" * 64,
            "--backup-database", str(self.root / "missing-backup"),
            "--expected-production-sha256", "c" * 64,
            "--output", str(self.root / "missing-output"),
        ]
        with patch.dict(os.environ, {}, clear=True), patch.object(
            backfill_cli, "merge_staging_insert_only"
        ) as merge:
            return_code, payload = self.call_main(argv)
        self.assertEqual(return_code, 1)
        self.assertEqual(payload["reason"], "production_merge_not_authorized")
        merge.assert_not_called()
        self.assertFalse(any(self.root.iterdir()))

    def test_merge_commands_reject_incomplete_full_acceptance_contract(self) -> None:
        def empty_counts(envelope):
            envelope["validation"]["counts"] = {}

        def empty_candidate_counts(envelope):
            envelope["validation"]["candidate_status_counts"] = {}

        def empty_occurrence_counts(envelope):
            envelope["validation"]["occurrence_disposition_counts"] = {}

        def empty_required_lanes(envelope):
            envelope["validation"]["required_lanes"] = []

        def empty_source_fingerprints(envelope):
            envelope["validation"]["source_fingerprints"] = {}

        def empty_checks(envelope):
            envelope["validation"]["checks"] = []

        def provider_call_false(envelope):
            envelope["validation"]["source_provider_call"] = False

        def missing_required_check(envelope):
            envelope["validation"]["checks"].pop()

        def incomplete_lane(envelope):
            envelope["validation"]["required_lanes"][0]["status"] = "partial"

        def replay_fingerprint_mismatch(envelope):
            envelope["validation"]["replay_fingerprints"]["runs"][
                "canonical_rows_sha256"
            ] = "f" * 64

        def seed_files_below_baseline(envelope):
            envelope["validation"]["counts"]["seed_files"] = 54

        def threads_below_baseline(envelope):
            validation = envelope["validation"]
            validation["counts"]["threads"] = 47
            validation["counts"]["analyses"] = (
                47 + validation["counts"]["comments"]
            )
            for field in ("source_fingerprints", "replay_fingerprints"):
                validation[field]["reddit_threads"]["row_count"] = 47
                validation[field]["analysis_results"]["row_count"] = validation[
                    "counts"
                ]["analyses"]

        def comments_below_baseline(envelope):
            validation = envelope["validation"]
            validation["counts"]["comments"] = 1893
            validation["counts"]["analyses"] = (
                validation["counts"]["threads"] + 1893
            )
            for field in ("source_fingerprints", "replay_fingerprints"):
                validation[field]["reddit_comments"]["row_count"] = 1893
                validation[field]["analysis_results"]["row_count"] = validation[
                    "counts"
                ]["analyses"]

        def analysis_count_not_entity_parity(envelope):
            validation = envelope["validation"]
            validation["counts"]["analyses"] += 1
            for field in ("source_fingerprints", "replay_fingerprints"):
                validation[field]["analysis_results"]["row_count"] = validation[
                    "counts"
                ]["analyses"]

        def invalid_occurrence(envelope):
            validation = envelope["validation"]
            validation["occurrence_disposition_counts"]["invalid"] = 1
            validation["counts"]["discovery_occurrences"] = 1

        def missing_reviewed_dynamic_lane(envelope):
            envelope["validation"]["required_lanes"].pop()

        def arbitrary_dynamic_lane(envelope):
            envelope["validation"]["required_lanes"][0][
                "lane_key_sha256"
            ] = "f" * 64

        def partial_reviewed_subreddit_lanes(envelope):
            validation = envelope["validation"]
            validation["required_lanes"].append(
                {
                    "lane_type": "subreddit_feed",
                    "lane_key_sha256": sha256(
                        DEFAULT_REVIEWED_SUBREDDITS[0].encode("utf-8")
                    ).hexdigest(),
                    "status": "complete",
                }
            )
            validation["counts"]["checkpoints"] += 1

        cases = (
            ("empty_counts", empty_counts),
            ("empty_candidate_counts", empty_candidate_counts),
            ("empty_occurrence_counts", empty_occurrence_counts),
            ("empty_required_lanes", empty_required_lanes),
            ("empty_source_fingerprints", empty_source_fingerprints),
            ("empty_checks", empty_checks),
            ("provider_call_false", provider_call_false),
            ("missing_required_check", missing_required_check),
            ("incomplete_lane", incomplete_lane),
            ("replay_fingerprint_mismatch", replay_fingerprint_mismatch),
            ("seed_files_below_baseline", seed_files_below_baseline),
            ("threads_below_baseline", threads_below_baseline),
            ("comments_below_baseline", comments_below_baseline),
            ("analysis_count_not_entity_parity", analysis_count_not_entity_parity),
            ("invalid_occurrence", invalid_occurrence),
            ("missing_reviewed_dynamic_lane", missing_reviewed_dynamic_lane),
            ("arbitrary_dynamic_lane", arbitrary_dynamic_lane),
            ("partial_reviewed_subreddit_lanes", partial_reviewed_subreddit_lanes),
        )
        for label, mutate in cases:
            for command in ("merge-plan", "merge-production"):
                with self.subTest(case=label, command=command):
                    acceptance = acceptance_envelope()
                    mutate(acceptance)
                    acceptance_path = self.root / f"{label}-{command}-acceptance.json"
                    acceptance_path.write_bytes(canonical_bytes(acceptance))
                    acceptance_sha = sha256(acceptance_path.read_bytes()).hexdigest()
                    output = self.root / f"{label}-{command}-output.json"
                    plan = merge_plan_payload()
                    plan_path = self.root / f"{label}-{command}-plan.json"
                    plan_path.write_bytes(canonical_bytes(plan))
                    plan_sha = sha256(plan_path.read_bytes()).hexdigest()
                    if command == "merge-plan":
                        argv = [
                            command,
                            "--run-id", RUN_ID,
                            "--staging-database", str(self.root / "staging.sqlite3"),
                            "--production-database", str(self.root / "production.sqlite3"),
                            "--acceptance-report", str(acceptance_path),
                            "--output", str(output),
                        ]
                        environment = {}
                    else:
                        argv = [
                            command,
                            "--run-id", RUN_ID,
                            "--staging-database", str(self.root / "staging.sqlite3"),
                            "--production-database", str(self.root / "production.sqlite3"),
                            "--acceptance-report", str(acceptance_path),
                            "--expected-acceptance-report-sha256", acceptance_sha,
                            "--merge-plan", str(plan_path),
                            "--expected-merge-plan-sha256", plan_sha,
                            "--backup-database", str(self.root / "backup.sqlite3"),
                            "--expected-production-sha256", str(plan["production_sha256"]),
                            "--output", str(output),
                            "--authorize-production-write",
                        ]
                        environment = {"REDDIT_VOC_ENABLE_PRODUCTION_MERGE": "1"}
                    with patch.dict(
                        os.environ, environment, clear=True
                    ), patch.object(
                        backfill_cli, "plan_insert_only_merge", return_value=plan
                    ) as planner, patch.object(
                        backfill_cli,
                        "merge_staging_insert_only",
                        side_effect=AssertionError("invalid acceptance reached merge"),
                    ) as merge:
                        return_code, payload = self.call_main(argv)
                    self.assertEqual(return_code, 1)
                    self.assertEqual(payload["reason"], "acceptance_report_invalid")
                    planner.assert_not_called()
                    merge.assert_not_called()
                    self.assertFalse(output.exists())

    def test_merge_commands_bind_acceptance_to_current_staging_fingerprints(self) -> None:
        staging = self.make_merge_staging()
        production = self.root / "production.sqlite3"
        VocStore(production).migrate()
        accepted_plan = backfill_cli.plan_insert_only_merge(
            staging, production, run_id=RUN_ID
        )
        acceptance = staging_acceptance_envelope(
            staging,
            source_fingerprints=accepted_plan["staging_fingerprints"]
        )
        acceptance_path = self.root / "acceptance.json"
        acceptance_path.write_bytes(canonical_bytes(acceptance))
        acceptance_sha = sha256(acceptance_path.read_bytes()).hexdigest()
        production_before = production.read_bytes()

        self.add_complete_staging_entity(staging)
        merge_plan_output = self.root / "merge-plan-after-drift.json"
        merge_plan_argv = [
            "merge-plan",
            "--run-id", RUN_ID,
            "--staging-database", str(staging),
            "--production-database", str(production),
            "--acceptance-report", str(acceptance_path),
            "--output", str(merge_plan_output),
        ]
        plan_code, plan_payload = self.call_main(merge_plan_argv)
        self.assertEqual(plan_code, 1)
        self.assertEqual(
            plan_payload["reason"],
            "acceptance_report_staging_fingerprint_mismatch",
        )
        self.assertFalse(merge_plan_output.exists())

        reviewed_plan = backfill_cli.plan_insert_only_merge(
            staging, production, run_id=RUN_ID
        )
        reviewed_plan_path = self.root / "reviewed-plan-after-drift.json"
        reviewed_plan_path.write_bytes(canonical_bytes(reviewed_plan))
        reviewed_plan_sha = sha256(reviewed_plan_path.read_bytes()).hexdigest()
        merge_output = self.root / "merge-result-after-drift.json"
        merge_argv = [
            "merge-production",
            "--run-id", RUN_ID,
            "--staging-database", str(staging),
            "--production-database", str(production),
            "--acceptance-report", str(acceptance_path),
            "--expected-acceptance-report-sha256", acceptance_sha,
            "--merge-plan", str(reviewed_plan_path),
            "--expected-merge-plan-sha256", reviewed_plan_sha,
            "--backup-database", str(self.root / "production.backup.sqlite3"),
            "--expected-production-sha256", str(reviewed_plan["production_sha256"]),
            "--output", str(merge_output),
            "--authorize-production-write",
        ]
        with patch.dict(
            os.environ, {"REDDIT_VOC_ENABLE_PRODUCTION_MERGE": "1"}, clear=True
        ), patch.object(
            backfill_cli,
            "merge_staging_insert_only",
            side_effect=AssertionError("stale acceptance reached production merge"),
        ) as merge:
            merge_code, merge_payload = self.call_main(merge_argv)
        self.assertEqual(merge_code, 1)
        self.assertEqual(
            merge_payload["reason"],
            "acceptance_report_staging_fingerprint_mismatch",
        )
        merge.assert_not_called()
        self.assertEqual(production.read_bytes(), production_before)
        self.assertFalse(merge_output.exists())
        self.assertFalse((self.root / "production.backup.sqlite3").exists())

    def test_merge_plan_rejects_unbound_staging_operational_ledgers(self) -> None:
        staging = self.make_merge_staging()
        production = self.root / "production.sqlite3"
        VocStore(production).migrate()
        plan = backfill_cli.plan_insert_only_merge(
            staging, production, run_id=RUN_ID
        )
        acceptance = staging_acceptance_envelope(
            staging,
            source_fingerprints=plan["staging_fingerprints"]
        )
        acceptance_path = self.root / "unbound-acceptance.json"
        acceptance_path.write_bytes(canonical_bytes(acceptance))
        output = self.root / "unbound-merge-plan.json"
        with sqlite3.connect(staging) as connection:
            connection.execute(
                "DELETE FROM backfill_seed_files WHERE run_id=?", (RUN_ID,)
            )
            connection.execute(
                "DELETE FROM backfill_checkpoints WHERE run_id=?", (RUN_ID,)
            )
            connection.execute(
                "DELETE FROM backfill_provider_attempts "
                "WHERE run_id=? AND request_number>1",
                (RUN_ID,),
            )
            connection.execute(
                "UPDATE backfill_manifests SET provider_request_count=1 "
                "WHERE run_id=?",
                (RUN_ID,),
            )

        return_code, payload = self.call_main(
            [
                "merge-plan",
                "--run-id", RUN_ID,
                "--staging-database", str(staging),
                "--production-database", str(production),
                "--acceptance-report", str(acceptance_path),
                "--output", str(output),
            ]
        )

        self.assertEqual(return_code, 1)
        self.assertEqual(
            payload["reason"], "acceptance_report_staging_evidence_mismatch"
        )
        self.assertFalse(output.exists())

    def test_merge_plan_rejects_stale_provider_attempt_content(self) -> None:
        staging = self.make_merge_staging()
        production = self.root / "production.sqlite3"
        VocStore(production).migrate()
        plan = backfill_cli.plan_insert_only_merge(
            staging, production, run_id=RUN_ID
        )
        acceptance = staging_acceptance_envelope(
            staging, source_fingerprints=plan["staging_fingerprints"]
        )
        acceptance_path = self.root / "stale-attempt-acceptance.json"
        acceptance_path.write_bytes(canonical_bytes(acceptance))
        with sqlite3.connect(staging) as connection:
            connection.execute(
                "UPDATE backfill_provider_attempts SET status='reserved', "
                "sent_at_utc=NULL, completed_at_utc=NULL, http_status=NULL "
                "WHERE run_id=? AND request_number=1",
                (RUN_ID,),
            )
        output = self.root / "stale-attempt-plan.json"

        return_code, payload = self.call_main(
            [
                "merge-plan",
                "--run-id", RUN_ID,
                "--staging-database", str(staging),
                "--production-database", str(production),
                "--acceptance-report", str(acceptance_path),
                "--output", str(output),
            ]
        )

        self.assertEqual(return_code, 1)
        self.assertEqual(
            payload["reason"], "acceptance_report_staging_evidence_mismatch"
        )
        self.assertFalse(output.exists())

    def test_merge_plan_rejects_stale_checkpoint_content(self) -> None:
        staging = self.make_merge_staging()
        production = self.root / "production.sqlite3"
        VocStore(production).migrate()
        plan = backfill_cli.plan_insert_only_merge(
            staging, production, run_id=RUN_ID
        )
        acceptance = staging_acceptance_envelope(
            staging, source_fingerprints=plan["staging_fingerprints"]
        )
        acceptance_path = self.root / "stale-checkpoint-acceptance.json"
        acceptance_path.write_bytes(canonical_bytes(acceptance))
        with sqlite3.connect(staging) as connection:
            connection.execute(
                "UPDATE backfill_checkpoints SET stop_reason='budget_exhausted', "
                "page_number=0, discovered_count=7 WHERE run_id=? "
                "AND lane_type='dynamic_search' AND lane_key=?",
                (RUN_ID, DEFAULT_TIKHUB_SEARCH_TERMS[0]),
            )
        output = self.root / "stale-checkpoint-plan.json"

        return_code, payload = self.call_main(
            [
                "merge-plan",
                "--run-id", RUN_ID,
                "--staging-database", str(staging),
                "--production-database", str(production),
                "--acceptance-report", str(acceptance_path),
                "--output", str(output),
            ]
        )

        self.assertEqual(return_code, 1)
        self.assertEqual(
            payload["reason"], "acceptance_report_staging_evidence_mismatch"
        )
        self.assertFalse(output.exists())

    def test_merge_commands_reject_current_non_success_staging_status(self) -> None:
        staging = self.make_merge_staging()
        production = self.root / "production.sqlite3"
        VocStore(production).migrate()
        reviewed_plan = backfill_cli.plan_insert_only_merge(
            staging, production, run_id=RUN_ID
        )
        acceptance = staging_acceptance_envelope(
            staging,
            source_fingerprints=reviewed_plan["staging_fingerprints"]
        )
        acceptance_path = self.root / "acceptance.json"
        acceptance_path.write_bytes(canonical_bytes(acceptance))
        acceptance_sha = sha256(acceptance_path.read_bytes()).hexdigest()
        reviewed_plan_path = self.root / "reviewed-plan.json"
        reviewed_plan_path.write_bytes(canonical_bytes(reviewed_plan))
        reviewed_plan_sha = sha256(reviewed_plan_path.read_bytes()).hexdigest()
        production_before = production.read_bytes()
        BackfillStore(staging).set_backfill_status(RUN_ID, "partial", NOW)

        plan_output = self.root / "partial-plan.json"
        plan_code, plan_payload = self.call_main(
            [
                "merge-plan",
                "--run-id", RUN_ID,
                "--staging-database", str(staging),
                "--production-database", str(production),
                "--acceptance-report", str(acceptance_path),
                "--output", str(plan_output),
            ]
        )
        self.assertEqual(plan_code, 1)
        self.assertEqual(plan_payload["reason"], "staging_run_manifest_mismatch")
        self.assertFalse(plan_output.exists())

        merge_output = self.root / "partial-merge.json"
        with patch.dict(
            os.environ, {"REDDIT_VOC_ENABLE_PRODUCTION_MERGE": "1"}, clear=True
        ), patch.object(backfill_cli, "merge_staging_insert_only") as merge:
            merge_code, merge_payload = self.call_main(
                [
                    "merge-production",
                    "--run-id", RUN_ID,
                    "--staging-database", str(staging),
                    "--production-database", str(production),
                    "--acceptance-report", str(acceptance_path),
                    "--expected-acceptance-report-sha256", acceptance_sha,
                    "--merge-plan", str(reviewed_plan_path),
                    "--expected-merge-plan-sha256", reviewed_plan_sha,
                    "--backup-database", str(self.root / "partial-backup.sqlite3"),
                    "--expected-production-sha256", str(reviewed_plan["production_sha256"]),
                    "--output", str(merge_output),
                    "--authorize-production-write",
                ]
            )
        self.assertEqual(merge_code, 1)
        self.assertEqual(merge_payload["reason"], "staging_run_manifest_mismatch")
        merge.assert_not_called()
        self.assertEqual(production.read_bytes(), production_before)
        self.assertFalse(merge_output.exists())
        self.assertFalse((self.root / "partial-backup.sqlite3").exists())

    def test_merge_commands_reject_current_provider_call_false(self) -> None:
        staging = self.make_merge_staging()
        production = self.root / "production.sqlite3"
        VocStore(production).migrate()
        reviewed_plan = backfill_cli.plan_insert_only_merge(
            staging, production, run_id=RUN_ID
        )
        acceptance = staging_acceptance_envelope(
            staging,
            source_fingerprints=reviewed_plan["staging_fingerprints"]
        )
        acceptance_path = self.root / "acceptance.json"
        acceptance_path.write_bytes(canonical_bytes(acceptance))
        acceptance_sha = sha256(acceptance_path.read_bytes()).hexdigest()
        reviewed_plan_path = self.root / "reviewed-plan.json"
        reviewed_plan_path.write_bytes(canonical_bytes(reviewed_plan))
        reviewed_plan_sha = sha256(reviewed_plan_path.read_bytes()).hexdigest()
        production_before = production.read_bytes()
        with sqlite3.connect(staging) as connection:
            connection.execute(
                "UPDATE backfill_manifests SET provider_call=0 WHERE run_id=?",
                (RUN_ID,),
            )
            connection.execute(
                "UPDATE runs SET provider_call=0 WHERE run_id=?", (RUN_ID,)
            )

        plan_output = self.root / "provider-false-plan.json"
        plan_code, plan_payload = self.call_main(
            [
                "merge-plan",
                "--run-id", RUN_ID,
                "--staging-database", str(staging),
                "--production-database", str(production),
                "--acceptance-report", str(acceptance_path),
                "--output", str(plan_output),
            ]
        )
        self.assertEqual(plan_code, 1)
        self.assertEqual(plan_payload["reason"], "staging_run_manifest_mismatch")
        self.assertFalse(plan_output.exists())

        merge_output = self.root / "provider-false-merge.json"
        with patch.dict(
            os.environ, {"REDDIT_VOC_ENABLE_PRODUCTION_MERGE": "1"}, clear=True
        ), patch.object(backfill_cli, "merge_staging_insert_only") as merge:
            merge_code, merge_payload = self.call_main(
                [
                    "merge-production",
                    "--run-id", RUN_ID,
                    "--staging-database", str(staging),
                    "--production-database", str(production),
                    "--acceptance-report", str(acceptance_path),
                    "--expected-acceptance-report-sha256", acceptance_sha,
                    "--merge-plan", str(reviewed_plan_path),
                    "--expected-merge-plan-sha256", reviewed_plan_sha,
                    "--backup-database", str(self.root / "provider-false-backup.sqlite3"),
                    "--expected-production-sha256", str(reviewed_plan["production_sha256"]),
                    "--output", str(merge_output),
                    "--authorize-production-write",
                ]
            )
        self.assertEqual(merge_code, 1)
        self.assertEqual(merge_payload["reason"], "staging_run_manifest_mismatch")
        merge.assert_not_called()
        self.assertEqual(production.read_bytes(), production_before)
        self.assertFalse(merge_output.exists())
        self.assertFalse(
            (self.root / "provider-false-backup.sqlite3").exists()
        )

    def test_merge_plan_requires_full_acceptance_and_writes_exact_task9_plan(self) -> None:
        staging = self.make_merge_staging()
        production = self.root / "production.sqlite3"
        VocStore(production).migrate()
        plan = backfill_cli.plan_insert_only_merge(
            staging, production, run_id=RUN_ID
        )
        acceptance = staging_acceptance_envelope(
            staging, source_fingerprints=plan["staging_fingerprints"]
        )
        acceptance_path = self.root / "acceptance.json"
        acceptance_path.write_bytes(canonical_bytes(acceptance))
        output = self.root / "merge-plan.json"
        argv = [
            "merge-plan",
            "--run-id", RUN_ID,
            "--staging-database", str(staging),
            "--production-database", str(production),
            "--acceptance-report", str(acceptance_path),
            "--output", str(output),
        ]
        return_code, payload = self.call_main(argv)
        self.assertEqual(return_code, 0)
        self.assertEqual(payload, plan)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8")), plan)

    def test_merge_production_admits_reviewed_files_and_passes_semantic_plan_sha(self) -> None:
        staging = self.make_merge_staging()
        production = self.root / "production.sqlite3"
        VocStore(production).migrate()
        plan = backfill_cli.plan_insert_only_merge(
            staging, production, run_id=RUN_ID
        )
        acceptance = staging_acceptance_envelope(
            staging, source_fingerprints=plan["staging_fingerprints"]
        )
        acceptance_path = self.root / "acceptance.json"
        acceptance_path.write_bytes(canonical_bytes(acceptance))
        acceptance_sha = sha256(acceptance_path.read_bytes()).hexdigest()
        plan_path = self.root / "merge-plan.json"
        plan_path.write_bytes(canonical_bytes(plan))
        plan_file_sha = sha256(plan_path.read_bytes()).hexdigest()
        output = self.root / "merge-result.json"
        summary = MergeSummary(
            schema_version="backfill_insert_only_merge_result_v1",
            run_id=RUN_ID,
            status="merged",
            stop_reason="merge_complete",
            authorized=True,
            production_write=True,
            plan_sha256=str(plan["plan_sha256"]),
            staging_sha256=str(plan["staging_sha256"]),
            expected_production_sha256=str(plan["production_sha256"]),
            premerge_production_sha256=str(plan["production_sha256"]),
            backup_sha256="8" * 64,
            postmerge_production_sha256="9" * 64,
            planned_runs=1,
            planned_raw_captures=0,
            reused_raw_captures=0,
            planned_threads=0,
            planned_comments=0,
            planned_analyses=0,
            inserted_runs=1,
            inserted_raw_captures=0,
            inserted_threads=0,
            inserted_comments=0,
            inserted_analyses=0,
            skipped_posts=0,
            conflict_count=0,
            delivery_before=0,
            delivery_after=0,
            delivery_delta=0,
            updated=0,
            deleted=0,
            provider_attempt_made=False,
            live_send=False,
        )
        argv = [
            "merge-production",
            "--run-id", RUN_ID,
            "--staging-database", str(staging),
            "--production-database", str(production),
            "--acceptance-report", str(acceptance_path),
            "--expected-acceptance-report-sha256", acceptance_sha,
            "--merge-plan", str(plan_path),
            "--expected-merge-plan-sha256", plan_file_sha,
            "--backup-database", str(self.root / "backup.sqlite3"),
            "--expected-production-sha256", str(plan["production_sha256"]),
            "--output", str(output),
            "--authorize-production-write",
        ]
        with patch.dict(
            os.environ, {"REDDIT_VOC_ENABLE_PRODUCTION_MERGE": "1"}, clear=True
        ), patch.object(
            backfill_cli, "merge_staging_insert_only", return_value=summary
        ) as merge:
            return_code, payload = self.call_main(argv)
        self.assertEqual(return_code, 0)
        self.assertEqual(payload["status"], "merged")
        self.assertFalse(payload["provider_attempt_made"])
        self.assertFalse(payload["live_send"])
        self.assertEqual(
            merge.call_args.kwargs["expected_plan_sha256"], plan["plan_sha256"]
        )


if __name__ == "__main__":
    unittest.main()
