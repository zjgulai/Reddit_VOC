from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from threading import RLock
from typing import Any

from .adapters import BrowserJsonAdapter
from .analyzer import analyze_text
from .backfill_archive import (
    ArchiveIntegrityError,
    PrivateRawArchive,
    _path_has_existing_symlink_component,
)
from .backfill_archived_recovery import recover_archived_candidates
from .backfill_models import (
    AnalysisRow,
    BackfillCheckpoint,
    BackfillManifest,
    CursorContract,
    DiscoveryBaseDisposition,
    RawArtifactMetadata,
    SeedBaseline,
    ValidationScope,
    discovery_occurrence_contract,
    required_lanes_sha256,
    required_lanes_snapshot,
)
from .backfill_storage import (
    BackfillStore,
    _authorization_ledger_schema_is_compatible,
    _decode_hydration_resume_ledger,
)
from .keywords import keyword_rules_sha256
from .models import RawCapture
from .search_config import DEFAULT_TIKHUB_SEARCH_TERMS
from .tikhub import (
    FETCH_DYNAMIC_SEARCH,
    FETCH_SUBREDDIT_FEED,
    STRICT_SUBREDDIT_V3_CURSOR_PATH,
    STRICT_SUBREDDIT_V3_CURSOR_SCHEMA_SHA256,
    TikHubDiscoveryShapeError,
    _author_name,
    _extract_backfill_discovery_post_records,
    _extract_backfill_discovery_posts,
    _extract_discovery_posts,
    _extract_tikhub_posts_info,
    _is_strict_subreddit_v3_terminal_empty,
    _normalize_post_id,
    _parse_tikhub_app_detail_payload,
    _parse_strict_tikhub_comment_payload,
)
from .time_window import CollectionWindow


__all__ = [
    "SeedBaseline",
    "ValidationScope",
    "required_lanes_snapshot",
    "required_lanes_sha256",
    "validate_backfill",
    "replay_from_archive",
    "audit_discovery_reindex_from_archive",
    "reindex_discovery_from_archive",
    "recover_collection_from_archive",
    "validate_collection_recovery_postflight",
    "ReplayPublicationError",
]


_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_SAFE_REASON_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}")
_ERROR_CLASS_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}")
_REPLAY_CWD_LOCK = RLock()
_TIKHUB_DISCOVERY_LEGACY_PARSER_KIND = "tikhub_discovery"
_TIKHUB_DISCOVERY_STRICT_PARSER_KIND = "tikhub_discovery_strict_v2"
_TIKHUB_DISCOVERY_PARSER_KINDS = frozenset(
    (
        _TIKHUB_DISCOVERY_LEGACY_PARSER_KIND,
        _TIKHUB_DISCOVERY_STRICT_PARSER_KIND,
    )
)
_OPTIONAL_AUTHORIZATION_TABLES = (
    "backfill_budget_extensions",
    "backfill_hydration_resumes",
    "backfill_collection_resumes",
)
_LEGACY_AUTHORIZATION_TABLES = frozenset(
    ("backfill_budget_extensions", "backfill_hydration_resumes")
)
_SEED_NUMERIC_CONTRACT = {
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
_REQUIRED_TABLES = (
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
    "backfill_detail_batches",
    "backfill_detail_batch_members",
    "backfill_discovery_occurrences",
    "backfill_issues",
    "backfill_merge_conflicts",
)
_REINDEX_ADDITIVE_TABLES = (
    "backfill_budget_extensions",
    "backfill_hydration_resumes",
    "backfill_collection_resumes",
)
_REQUIRED_COLUMNS = {
    "runs": (
        "run_id",
        "status",
        "window_start_utc",
        "window_end_utc",
        "provider_call",
        "live_send",
    ),
    "raw_captures": (
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
    ),
    "reddit_threads": (
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
    ),
    "reddit_comments": (
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
    ),
    "analysis_results": (
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
    "delivery_previews": (
        "delivery_id",
        "run_id",
        "channel",
        "mode",
        "status",
        "message_hash",
        "artifact_paths",
        "live_send",
    ),
    "backfill_manifests": (
        "run_id",
        "status",
        "window_start_utc",
        "requested_end_utc",
        "effective_end_utc",
        "search_terms_json",
        "subreddits_json",
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
    "backfill_seed_files": (
        "run_id",
        "input_path_hash",
        "payload_sha256",
        "outcome",
        "artifact_id",
        "post_id",
        "error_class",
        "processed_at_utc",
    ),
    "backfill_raw_artifacts": (
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
    "backfill_provider_attempts": (
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
    "backfill_checkpoints": (
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
    "backfill_candidates": (
        "run_id",
        "post_id",
        "first_lane_type",
        "first_lane_key",
        "first_discovered_at_utc",
        "source_url",
        "post_created_at_utc",
        "raw_artifact_id",
        "status",
        "status_reason",
        "updated_at_utc",
    ),
    "backfill_detail_batches": (
        "run_id",
        "batch_id",
        "batch_number",
        "status",
        "artifact_id",
        "stop_reason",
        "created_at_utc",
        "updated_at_utc",
    ),
    "backfill_detail_batch_members": (
        "run_id",
        "batch_id",
        "ordinal",
        "post_id",
    ),
    "backfill_discovery_occurrences": (
        "run_id",
        "lane_type",
        "lane_key",
        "page_number",
        "ordinal",
        "post_id",
        "source_url",
        "post_created_at_utc",
        "raw_artifact_id",
        "discovered_at_utc",
        "disposition",
    ),
    "backfill_issues": (
        "run_id",
        "issue_id",
        "issue_kind",
        "lane_type",
        "lane_key",
        "entity_id",
        "fatal",
        "error_class",
        "detail",
        "created_at_utc",
    ),
    "backfill_merge_conflicts": (
        "merge_id",
        "entity_type",
        "entity_id",
        "run_id",
        "conflict_kind",
        "staging_sha256",
        "existing_sha256",
        "created_at_utc",
    ),
    "backfill_budget_extensions": (
        "run_id",
        "authorization_sha256",
        "expected_provider_request_count",
        "expected_max_provider_requests",
        "new_max_provider_requests",
        "discovery_request_ceiling",
        "lane_page_ceilings_sha256",
        "include_subreddit_sweep",
        "required_lanes_sha256",
        "applied_at_utc",
    ),
    "backfill_hydration_resumes": (
        "run_id",
        "authorization_sha256",
        "candidate_post_ids_json",
        "candidate_post_ids_sha256",
        "batch_membership_json",
        "batch_membership_sha256",
        "candidate_count",
        "batch_count",
        "applied_at_utc",
    ),
    "backfill_collection_resumes": (
        "run_id",
        "authorization_sha256",
        "expected_source_database_sha256",
        "expected_provider_request_count",
        "max_provider_requests",
        "discovery_request_ceiling",
        "lane_page_ceilings_sha256",
        "candidate_state_sha256",
        "include_subreddit_sweep",
        "required_lanes_sha256",
        "applied_at_utc",
    ),
}
_COUNT_TABLES = (
    "backfill_manifests",
    "runs",
    "backfill_seed_files",
    "backfill_raw_artifacts",
    "raw_captures",
    "reddit_threads",
    "reddit_comments",
    "analysis_results",
    "delivery_previews",
    "backfill_provider_attempts",
    "backfill_checkpoints",
    "backfill_candidates",
    "backfill_discovery_occurrences",
    "backfill_detail_batches",
    "backfill_detail_batch_members",
)
_OPERATIONAL_SNAPSHOT_TABLES = (
    "runs",
    "delivery_previews",
    "backfill_manifests",
    "backfill_seed_files",
    "backfill_provider_attempts",
    "backfill_checkpoints",
    "backfill_candidates",
    "backfill_discovery_occurrences",
    "backfill_detail_batches",
    "backfill_detail_batch_members",
    "backfill_budget_extensions",
    "backfill_hydration_resumes",
    "backfill_collection_resumes",
    "backfill_issues",
    "backfill_merge_conflicts",
)
_COUNT_NAMES = {
    "backfill_manifests": "manifests",
    "runs": "runs",
    "backfill_seed_files": "seed_files",
    "backfill_raw_artifacts": "raw_artifacts",
    "raw_captures": "raw_captures",
    "reddit_threads": "threads",
    "reddit_comments": "comments",
    "analysis_results": "analyses",
    "delivery_previews": "delivery_previews",
    "backfill_provider_attempts": "provider_attempts",
    "backfill_checkpoints": "checkpoints",
    "backfill_candidates": "candidates",
    "backfill_discovery_occurrences": "discovery_occurrences",
    "backfill_detail_batches": "detail_batches",
    "backfill_detail_batch_members": "detail_batch_members",
}
_CANDIDATE_STATUSES = (
    "pending",
    "duplicate_existing_structured",
    "hydrated",
    "excluded",
    "outside_window_detail",
    "failed",
    "budget_deferred",
)
_DISCOVERY_DISPOSITIONS = (
    "new_candidate",
    "duplicate_occurrence",
    "outside_window",
    "duplicate_existing_structured",
    "invalid",
)
_STOP_PRIORITY = (
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
)
_FINGERPRINT_TABLES = (
    ("runs", "run_id"),
    ("backfill_raw_artifacts", "artifact_id"),
    ("raw_captures", "raw_capture_id"),
    ("reddit_threads", "post_id"),
    ("reddit_comments", "comment_id"),
    ("analysis_results", "analysis_id"),
)
_COMMENT_ENDPOINT = "/api/v1/reddit/app/fetch_post_comments"


def _artifact_contract_value(
    artifact: RawArtifactMetadata | dict[str, object], field: str
) -> object:
    if isinstance(artifact, dict):
        return artifact.get(field)
    return getattr(artifact, field)


def _artifact_has_comment_marker(
    artifact: RawArtifactMetadata | dict[str, object],
) -> bool:
    return bool(
        _artifact_contract_value(artifact, "artifact_kind") == "comments"
        or _artifact_contract_value(artifact, "lane_type") == "comments"
        or _artifact_contract_value(artifact, "parser_kind") == "tikhub_comments"
        or _artifact_contract_value(artifact, "source_method") == "tikhub_comments"
        or _artifact_contract_value(artifact, "source_endpoint")
        == _COMMENT_ENDPOINT
    )


def _artifact_is_exact_comment_contract(
    artifact: RawArtifactMetadata | dict[str, object],
) -> bool:
    return bool(
        _artifact_contract_value(artifact, "artifact_kind") == "comments"
        and _artifact_contract_value(artifact, "lane_type") == "comments"
        and _artifact_contract_value(artifact, "parser_kind") == "tikhub_comments"
        and _artifact_contract_value(artifact, "source_method") == "tikhub_comments"
        and _artifact_contract_value(artifact, "source_endpoint")
        == _COMMENT_ENDPOINT
    )


class _Recorder:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.categories: set[str] = set()
        self._issues: set[tuple[str, str, str, str]] = set()
        self.checks: list[dict[str, object]] = []

    def issue(
        self,
        code: str,
        category: str,
        entity_type: str,
        identity: object,
        *,
        severity: str = "error",
    ) -> None:
        self.categories.add(category)
        identity_hash = sha256(str(identity).encode("utf-8")).hexdigest()
        self._issues.add((severity, code, entity_type, identity_hash))

    def check(
        self,
        code: str,
        ok: bool,
        actual: str | int | bool | None,
        expected: str | int | bool | None,
    ) -> None:
        self.checks.append(
            {"code": code, "ok": bool(ok), "actual": actual, "expected": expected}
        )

    def public_issues(self) -> list[dict[str, object]]:
        return [
            {
                "code": code,
                "severity": severity,
                "entity_type": entity_type,
                "entity_hash": entity_hash,
            }
            for severity, code, entity_type, entity_hash in sorted(self._issues)
        ]


class _ReplayDataError(RuntimeError):
    def __init__(self, stop_reason: str) -> None:
        self.stop_reason = stop_reason
        super().__init__(stop_reason)


class _DiscoveryReindexDataError(RuntimeError):
    def __init__(self, stop_reason: str) -> None:
        self.stop_reason = stop_reason
        super().__init__(stop_reason)


class _ReplayOperationalBoundaryError(RuntimeError):
    pass


class _ReplayPostCommitVerificationError(RuntimeError):
    pass


class _ReplayPreCommitVerificationError(RuntimeError):
    pass


class ReplayPublicationError(RuntimeError):
    def __init__(self, *, publication_state: str) -> None:
        if publication_state != "target_exists_needs_review":
            raise ValueError("invalid replay publication state")
        self.publication_state = publication_state
        super().__init__("replay target exists and requires review")


def _authorization_ledger_rows(
    conn: sqlite3.Connection, *, run_id: str
) -> dict[str, list[dict[str, object]]]:
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    present = set(_OPTIONAL_AUTHORIZATION_TABLES).intersection(tables)
    if not present:
        return {table: [] for table in _OPTIONAL_AUTHORIZATION_TABLES}
    if not _LEGACY_AUTHORIZATION_TABLES.issubset(present):
        raise _ReplayDataError("authorization_ledger_schema_invalid")

    result: dict[str, list[dict[str, object]]] = {}
    for table in _OPTIONAL_AUTHORIZATION_TABLES:
        if table not in present:
            result[table] = []
            continue
        columns = {
            str(row["name"])
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if (
            columns != set(_REQUIRED_COLUMNS[table])
            or not _authorization_ledger_schema_is_compatible(conn, table)
        ):
            raise _ReplayDataError("authorization_ledger_schema_invalid")
        result[table] = [
            dict(row)
            for row in conn.execute(
                f"SELECT * FROM {table} WHERE run_id=? ORDER BY rowid",
                (run_id,),
            ).fetchall()
        ]
    return result


def _validated_budget_extension_boundaries(
    manifest: dict[str, object],
    rows: tuple[dict[str, object], ...] | list[dict[str, object]],
) -> tuple[frozenset[int], frozenset[int]]:
    if not rows:
        if (
            manifest.get("run_id")
            == "backfill_momcozy_20250101_20260711"
            and type(manifest.get("max_provider_requests")) is int
            and int(manifest["max_provider_requests"]) > 670
        ):
            raise _ReplayDataError("budget_extension_ledger_invalid")
        return frozenset(), frozenset()

    run_id = manifest.get("run_id")
    manifest_count = manifest.get("provider_request_count")
    manifest_maximum = manifest.get("max_provider_requests")
    manifest_sweep = manifest.get("include_subreddit_sweep")
    manifest_lanes = manifest.get("required_lanes_sha256")
    if (
        type(run_id) is not str
        or type(manifest_count) is not int
        or type(manifest_maximum) is not int
        or type(manifest_sweep) is not int
        or manifest_sweep not in {0, 1}
        or type(manifest_lanes) is not str
        or _SHA256_PATTERN.fullmatch(manifest_lanes) is None
    ):
        raise _ReplayDataError("budget_extension_ledger_invalid")

    expected_keys = set(_REQUIRED_COLUMNS["backfill_budget_extensions"])
    normalized: list[tuple[int, int, int]] = []
    authorizations: set[str] = set()
    new_maxima: set[int] = set()
    expected_maxima: set[int] = set()
    for row in rows:
        authorization = row.get("authorization_sha256")
        expected_count = row.get("expected_provider_request_count")
        expected_maximum = row.get("expected_max_provider_requests")
        new_maximum = row.get("new_max_provider_requests")
        discovery_ceiling = row.get("discovery_request_ceiling")
        lane_sha = row.get("lane_page_ceilings_sha256")
        sweep = row.get("include_subreddit_sweep")
        lanes_sha = row.get("required_lanes_sha256")
        applied_at = row.get("applied_at_utc")
        try:
            applied = (
                datetime.fromisoformat(applied_at)
                if type(applied_at) is str
                else None
            )
        except ValueError:
            applied = None
        valid = bool(
            set(row) == expected_keys
            and row.get("run_id") == run_id
            and type(authorization) is str
            and _SHA256_PATTERN.fullmatch(authorization) is not None
            and type(expected_count) is int
            and type(expected_maximum) is int
            and type(new_maximum) is int
            and type(discovery_ceiling) is int
            and expected_count == expected_maximum
            and 0 <= expected_count < new_maximum
            and expected_count <= discovery_ceiling < new_maximum
            and type(lane_sha) is str
            and _SHA256_PATTERN.fullmatch(lane_sha) is not None
            and type(sweep) is int
            and sweep == manifest_sweep
            and lanes_sha == manifest_lanes
            and type(lanes_sha) is str
            and _SHA256_PATTERN.fullmatch(lanes_sha) is not None
            and applied is not None
            and applied.tzinfo is not None
            and applied.utcoffset() is not None
        )
        if not valid:
            raise _ReplayDataError("budget_extension_ledger_invalid")
        assert isinstance(authorization, str)
        assert isinstance(expected_count, int)
        assert isinstance(new_maximum, int)
        assert isinstance(discovery_ceiling, int)
        if (
            authorization in authorizations
            or expected_count in expected_maxima
            or new_maximum in new_maxima
        ):
            raise _ReplayDataError("budget_extension_ledger_invalid")
        authorizations.add(authorization)
        expected_maxima.add(expected_count)
        new_maxima.add(new_maximum)
        normalized.append((expected_count, new_maximum, discovery_ceiling))

    normalized.sort(key=lambda item: item[0])
    if (
        run_id == "backfill_momcozy_20250101_20260711"
        and normalized[0][0] != 670
    ):
        raise _ReplayDataError("budget_extension_ledger_invalid")
    for previous, current in zip(normalized, normalized[1:]):
        if current[0] != previous[1]:
            raise _ReplayDataError("budget_extension_ledger_invalid")
    last_expected, last_maximum, _ = normalized[-1]
    if (
        manifest_maximum != last_maximum
        or not last_expected <= manifest_count <= last_maximum
    ):
        raise _ReplayDataError("budget_extension_ledger_invalid")
    return (
        frozenset(item[0] for item in normalized),
        frozenset(item[2] for item in normalized),
    )


def _validate_hydration_resume_ledgers(
    *,
    run_id: str,
    extension_rows: list[dict[str, object]],
    resume_rows: list[dict[str, object]],
    source_rows: dict[str, list[dict[str, object]]],
) -> None:
    if not resume_rows:
        if (
            run_id == "backfill_momcozy_20250101_20260711"
            and extension_rows
        ):
            raise _ReplayDataError("hydration_resume_ledger_invalid")
        return
    extension_authorizations = {
        str(row["authorization_sha256"]) for row in extension_rows
    }
    candidate_ids = {
        str(row["post_id"]) for row in source_rows["backfill_candidates"]
    }
    batches = {
        str(row["batch_id"]): row
        for row in source_rows["backfill_detail_batches"]
    }
    members_by_batch: dict[str, list[dict[str, object]]] = {}
    for member in source_rows["backfill_detail_batch_members"]:
        members_by_batch.setdefault(str(member["batch_id"]), []).append(member)

    seen_authorizations: set[str] = set()
    expected_keys = set(_REQUIRED_COLUMNS["backfill_hydration_resumes"])
    for row in resume_rows:
        authorization = row.get("authorization_sha256")
        applied_at = row.get("applied_at_utc")
        try:
            applied = (
                datetime.fromisoformat(applied_at)
                if type(applied_at) is str
                else None
            )
            resumed_candidates, membership = _decode_hydration_resume_ledger(row)
        except (TypeError, ValueError, json.JSONDecodeError):
            raise _ReplayDataError("hydration_resume_ledger_invalid") from None
        if (
            set(row) != expected_keys
            or row.get("run_id") != run_id
            or type(authorization) is not str
            or authorization not in extension_authorizations
            or authorization in seen_authorizations
            or applied is None
            or applied.tzinfo is None
            or applied.utcoffset() is None
            or not set(resumed_candidates).issubset(candidate_ids)
        ):
            raise _ReplayDataError("hydration_resume_ledger_invalid")
        seen_authorizations.add(authorization)
        for batch_id, batch_number, post_ids in membership:
            batch = batches.get(batch_id)
            members = sorted(
                members_by_batch.get(batch_id, []),
                key=lambda member: int(member["ordinal"]),
            )
            actual_post_ids = tuple(str(member["post_id"]) for member in members)
            if (
                batch is None
                or int(batch["batch_number"]) != batch_number
                or [int(member["ordinal"]) for member in members]
                != list(range(len(members)))
                or actual_post_ids != post_ids
            ):
                raise _ReplayDataError("hydration_resume_ledger_invalid")
    if (
        run_id == "backfill_momcozy_20250101_20260711"
        and seen_authorizations != extension_authorizations
    ):
        raise _ReplayDataError("hydration_resume_ledger_invalid")


def _validate_collection_resume_ledgers(
    *,
    manifest: dict[str, object],
    resume_rows: list[dict[str, object]],
) -> None:
    if not resume_rows:
        return

    run_id = manifest.get("run_id")
    manifest_count = manifest.get("provider_request_count")
    manifest_maximum = manifest.get("max_provider_requests")
    manifest_sweep = manifest.get("include_subreddit_sweep")
    manifest_lanes = manifest.get("required_lanes_sha256")
    if (
        type(run_id) is not str
        or type(manifest_count) is not int
        or type(manifest_maximum) is not int
        or type(manifest_sweep) is not int
        or manifest_sweep not in {0, 1}
        or type(manifest_lanes) is not str
        or _SHA256_PATTERN.fullmatch(manifest_lanes) is None
    ):
        raise _ReplayDataError("collection_resume_ledger_invalid")

    expected_keys = set(_REQUIRED_COLUMNS["backfill_collection_resumes"])
    authorizations: set[str] = set()
    expected_counts: set[int] = set()
    for row in resume_rows:
        authorization = row.get("authorization_sha256")
        source_database_sha = row.get("expected_source_database_sha256")
        expected_count = row.get("expected_provider_request_count")
        maximum = row.get("max_provider_requests")
        discovery_ceiling = row.get("discovery_request_ceiling")
        lane_sha = row.get("lane_page_ceilings_sha256")
        candidate_state_sha = row.get("candidate_state_sha256")
        sweep = row.get("include_subreddit_sweep")
        lanes_sha = row.get("required_lanes_sha256")
        applied_at = row.get("applied_at_utc")
        try:
            applied = (
                datetime.fromisoformat(applied_at)
                if type(applied_at) is str
                else None
            )
        except ValueError:
            applied = None
        valid = bool(
            set(row) == expected_keys
            and row.get("run_id") == run_id
            and type(authorization) is str
            and _SHA256_PATTERN.fullmatch(authorization) is not None
            and type(source_database_sha) is str
            and _SHA256_PATTERN.fullmatch(source_database_sha) is not None
            and type(expected_count) is int
            and type(maximum) is int
            and type(discovery_ceiling) is int
            and 0 <= expected_count < maximum
            and expected_count <= discovery_ceiling <= maximum
            and expected_count <= manifest_count <= maximum
            and maximum == manifest_maximum
            and type(lane_sha) is str
            and _SHA256_PATTERN.fullmatch(lane_sha) is not None
            and type(candidate_state_sha) is str
            and _SHA256_PATTERN.fullmatch(candidate_state_sha) is not None
            and type(sweep) is int
            and sweep == manifest_sweep
            and lanes_sha == manifest_lanes
            and type(lanes_sha) is str
            and _SHA256_PATTERN.fullmatch(lanes_sha) is not None
            and applied is not None
            and applied.tzinfo is not None
            and applied.utcoffset() is not None
        )
        if not valid:
            raise _ReplayDataError("collection_resume_ledger_invalid")
        assert isinstance(authorization, str)
        assert isinstance(expected_count, int)
        if authorization in authorizations or expected_count in expected_counts:
            raise _ReplayDataError("collection_resume_ledger_invalid")
        authorizations.add(authorization)
        expected_counts.add(expected_count)


def _validate_replay_paths(
    *, source_path: Path, archive_root: Path, target_db: Path
) -> tuple[Path, Path, Path, tuple[int, int]]:
    try:
        if _path_has_existing_symlink_component(source_path):
            raise ValueError
        resolved_source = source_path.resolve(strict=True)
        if not resolved_source.is_file():
            raise ValueError
        if _path_has_existing_symlink_component(target_db):
            raise ValueError
        target_parent = target_db.parent.resolve(strict=True)
        if not target_parent.is_dir():
            raise ValueError
        parent_stat = os.stat(target_parent, follow_symlinks=False)
        if not stat.S_ISDIR(parent_stat.st_mode):
            raise ValueError
        canonical_target = target_db.resolve(strict=False)
        if canonical_target.parent != target_parent:
            raise ValueError
        if os.path.lexists(canonical_target):
            raise ValueError
        target_parent.relative_to(resolved_source.parent)
        resolved_archive = archive_root.resolve(strict=True)
        try:
            canonical_target.relative_to(resolved_archive)
        except ValueError:
            pass
        else:
            raise ValueError
    except (FileNotFoundError, OSError, ValueError):
        raise ValueError("replay source and target paths are invalid") from None
    return (
        resolved_source,
        canonical_target,
        target_parent,
        (parent_stat.st_dev, parent_stat.st_ino),
    )


def _open_replay_parent(
    target_parent: Path, expected_identity: tuple[int, int]
) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW
    descriptor = os.open(target_parent, flags)
    try:
        _assert_replay_parent_identity(
            target_parent,
            parent_fd=descriptor,
            expected_identity=expected_identity,
        )
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


def _assert_replay_parent_identity(
    target_parent: Path,
    *,
    parent_fd: int,
    expected_identity: tuple[int, int],
) -> None:
    try:
        fixed_stat = os.fstat(parent_fd)
        lexical_stat = os.stat(target_parent, follow_symlinks=False)
    except OSError:
        raise _ReplayOperationalBoundaryError from None
    fixed_identity = (fixed_stat.st_dev, fixed_stat.st_ino)
    lexical_identity = (lexical_stat.st_dev, lexical_stat.st_ino)
    if (
        not stat.S_ISDIR(fixed_stat.st_mode)
        or not stat.S_ISDIR(lexical_stat.st_mode)
        or fixed_identity != expected_identity
        or lexical_identity != expected_identity
    ):
        raise _ReplayOperationalBoundaryError


def _assert_replay_name_absent(name: str, *, parent_fd: int) -> None:
    try:
        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError:
        raise _ReplayOperationalBoundaryError from None
    raise _ReplayOperationalBoundaryError


def _create_replay_temporary(
    *,
    target_parent: Path,
    target_name: str,
    parent_fd: int,
    parent_identity: tuple[int, int],
) -> tuple[int, str, Path, tuple[int, int]]:
    _assert_replay_parent_identity(
        target_parent,
        parent_fd=parent_fd,
        expected_identity=parent_identity,
    )
    _assert_replay_name_absent(target_name, parent_fd=parent_fd)
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    for _ in range(128):
        temporary_name = f".replay-{os.urandom(16).hex()}.sqlite3"
        try:
            descriptor = os.open(
                temporary_name,
                flags,
                0o600,
                dir_fd=parent_fd,
            )
        except FileExistsError:
            continue
        break
    else:
        raise FileExistsError("unable to allocate replay temporary file")

    try:
        descriptor_stat = os.fstat(descriptor)
        entry_stat = os.stat(
            temporary_name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        identity = (descriptor_stat.st_dev, descriptor_stat.st_ino)
        if (
            not stat.S_ISREG(descriptor_stat.st_mode)
            or not stat.S_ISREG(entry_stat.st_mode)
            or (entry_stat.st_dev, entry_stat.st_ino) != identity
        ):
            raise _ReplayOperationalBoundaryError
        _assert_replay_parent_identity(
            target_parent,
            parent_fd=parent_fd,
            expected_identity=parent_identity,
        )
    except Exception:
        try:
            os.unlink(temporary_name, dir_fd=parent_fd)
        except OSError:
            pass
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise
    return (
        descriptor,
        temporary_name,
        target_parent / temporary_name,
        identity,
    )


def _assert_owned_replay_temporary(
    temporary_name: str,
    *,
    parent_fd: int,
    temporary_identity: tuple[int, int],
    temporary_fd: int | None,
) -> None:
    try:
        entry_stat = os.stat(
            temporary_name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        if temporary_fd is not None:
            descriptor_stat = os.fstat(temporary_fd)
            if (
                not stat.S_ISREG(descriptor_stat.st_mode)
                or (descriptor_stat.st_dev, descriptor_stat.st_ino)
                != temporary_identity
            ):
                raise _ReplayOperationalBoundaryError
    except _ReplayOperationalBoundaryError:
        raise
    except OSError:
        raise _ReplayOperationalBoundaryError from None
    if (
        not stat.S_ISREG(entry_stat.st_mode)
        or (entry_stat.st_dev, entry_stat.st_ino) != temporary_identity
    ):
        raise _ReplayOperationalBoundaryError


def _run_replay_path_phase(
    operation,
    *,
    target_parent: Path,
    parent_fd: int,
    parent_identity: tuple[int, int],
    temporary_name: str,
    temporary_identity: tuple[int, int],
    temporary_fd: int,
):
    with _REPLAY_CWD_LOCK:
        cwd_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW
        cwd_fd = os.open(".", cwd_flags)
        phase_error: BaseException | None = None
        phase_traceback = None
        restore_error: OSError | None = None
        close_error: OSError | None = None
        changed_directory = False
        result = None
        try:
            _assert_replay_parent_identity(
                target_parent,
                parent_fd=parent_fd,
                expected_identity=parent_identity,
            )
            _assert_owned_replay_temporary(
                temporary_name,
                parent_fd=parent_fd,
                temporary_identity=temporary_identity,
                temporary_fd=temporary_fd,
            )
            os.fchdir(parent_fd)
            changed_directory = True
            result = operation()
        except BaseException as exc:
            phase_error = exc
            phase_traceback = exc.__traceback__
        finally:
            if changed_directory:
                try:
                    os.fchdir(cwd_fd)
                except OSError as exc:
                    restore_error = exc
            try:
                os.close(cwd_fd)
            except OSError as exc:
                close_error = exc

        if phase_error is not None:
            raise phase_error.with_traceback(phase_traceback)
        if restore_error is not None or close_error is not None:
            raise _ReplayOperationalBoundaryError from None
        _assert_replay_parent_identity(
            target_parent,
            parent_fd=parent_fd,
            expected_identity=parent_identity,
        )
        _assert_owned_replay_temporary(
            temporary_name,
            parent_fd=parent_fd,
            temporary_identity=temporary_identity,
            temporary_fd=temporary_fd,
        )
        return result


def replay_from_archive(
    source_store: BackfillStore,
    archive: PrivateRawArchive,
    *,
    target_db: Path,
    run_id: str,
    _source_connection: sqlite3.Connection | None = None,
) -> dict[str, object]:
    """Rebuild a fresh staging DB from verified raw without external calls."""
    if not isinstance(source_store, BackfillStore):
        raise ValueError("source_store must be a BackfillStore")
    if not isinstance(archive, PrivateRawArchive) or archive.read_only is not True:
        raise ValueError("replay requires a read-only raw archive")
    if type(run_id) is not str or not run_id.strip():
        raise ValueError("run_id must be a non-empty string")
    if not isinstance(target_db, Path):
        raise ValueError("target_db must be a Path")
    if _source_connection is not None and not isinstance(
        _source_connection, sqlite3.Connection
    ):
        raise ValueError("source connection must be a sqlite3 connection")

    (
        resolved_source,
        canonical_target,
        target_parent,
        parent_identity,
    ) = _validate_replay_paths(
        source_path=source_store.path,
        archive_root=archive.root,
        target_db=target_db,
    )

    parent_fd: int | None = None
    source_conn: sqlite3.Connection | None = None
    temporary_fd: int | None = None
    temporary_pin_fd: int | None = None
    temporary_name: str | None = None
    temporary_path: Path | None = None
    temporary_identity: tuple[int, int] | None = None
    metadata_mirrored_count = 0
    source_connection_owned = _source_connection is None
    try:
        parent_fd = _open_replay_parent(target_parent, parent_identity)
        source_conn = _source_connection
        if source_conn is None:
            source_conn = sqlite3.connect(
                f"{resolved_source.as_uri()}?mode=ro&immutable=1",
                uri=True,
                timeout=5.0,
            )
        source_conn.row_factory = sqlite3.Row
        source_conn.execute("PRAGMA query_only = ON")
        source_conn.execute("PRAGMA foreign_keys = ON")
        source_conn.execute("BEGIN")
        snapshot = _load_replay_snapshot(
            source_conn, archive=archive, run_id=run_id
        )
        _validate_replay_comment_lane_closure(snapshot)

        (
            temporary_fd,
            temporary_name,
            _temporary_absolute_path,
            temporary_identity,
        ) = _create_replay_temporary(
            target_parent=target_parent,
            target_name=canonical_target.name,
            parent_fd=parent_fd,
            parent_identity=parent_identity,
        )
        temporary_path = Path(temporary_name)
        target_store = BackfillStore(temporary_path)
        phase_kwargs = {
            "target_parent": target_parent,
            "parent_fd": parent_fd,
            "parent_identity": parent_identity,
            "temporary_name": temporary_name,
            "temporary_identity": temporary_identity,
            "temporary_fd": temporary_fd,
        }
        _run_replay_path_phase(target_store.migrate, **phase_kwargs)
        _run_replay_path_phase(
            lambda: _create_replay_manifest(target_store, snapshot["manifest"]),
            **phase_kwargs,
        )
        _run_replay_path_phase(
            lambda: _replay_verified_artifacts(target_store, snapshot),
            **phase_kwargs,
        )
        _run_replay_path_phase(
            lambda: _replay_seed(target_store, snapshot), **phase_kwargs
        )
        _run_replay_path_phase(
            lambda: _replay_discovery(target_store, snapshot), **phase_kwargs
        )
        metadata_mirrored_count = _run_replay_path_phase(
            lambda: _replay_detail_comments_and_failures(target_store, snapshot),
            **phase_kwargs,
        )
        _run_replay_path_phase(
            lambda: _verify_replay_operational_constraints(target_store, snapshot),
            **phase_kwargs,
        )

        source_fingerprints = _replay_fingerprints(source_conn, run_id)
        target_fingerprints = _run_replay_path_phase(
            lambda: _fingerprints_for_path(temporary_path, run_id),
            **phase_kwargs,
        )
        fingerprints = {
            "source": source_fingerprints,
            "target": target_fingerprints,
            "equivalent": source_fingerprints == target_fingerprints,
        }
        if not fingerprints["equivalent"]:
            connection_to_close = source_conn
            _close_replay_source_connection(
                connection_to_close, close=source_connection_owned
            )
            source_conn = None
            descriptor_to_close = temporary_fd
            try:
                _close_replay_temp_descriptor(descriptor_to_close)
            except Exception:
                _best_effort_close_descriptor(descriptor_to_close)
                temporary_fd = None
                raise
            temporary_fd = None
            cleanup_complete = _best_effort_cleanup_replay_names(
                temporary_name, parent_fd=parent_fd
            )
            if not cleanup_complete:
                raise _ReplayOperationalBoundaryError
            temporary_name = None
            temporary_path = None
            return _replay_result(
                status="failed",
                stop_reason="replay_mismatch",
                fingerprints=fingerprints,
                metadata_mirrored_count=metadata_mirrored_count,
            )

        _run_replay_path_phase(
            lambda: _prepare_replay_temp_for_publish(temporary_path),
            **phase_kwargs,
        )
        _remove_replay_sidecars_for_publish(
            temporary_name, parent_fd=parent_fd
        )
        _assert_replay_parent_identity(
            target_parent,
            parent_fd=parent_fd,
            expected_identity=parent_identity,
        )
        _assert_owned_replay_temporary(
            temporary_name,
            parent_fd=parent_fd,
            temporary_identity=temporary_identity,
            temporary_fd=temporary_fd,
        )
        os.fsync(temporary_fd)
        _assert_replay_parent_identity(
            target_parent,
            parent_fd=parent_fd,
            expected_identity=parent_identity,
        )
        _assert_owned_replay_temporary(
            temporary_name,
            parent_fd=parent_fd,
            temporary_identity=temporary_identity,
            temporary_fd=temporary_fd,
        )

        connection_to_close = source_conn
        _close_replay_source_connection(
            connection_to_close, close=source_connection_owned
        )
        source_conn = None
        temporary_pin_fd = os.dup(temporary_fd)
        descriptor_to_close = temporary_fd
        try:
            _close_replay_temp_descriptor(descriptor_to_close)
        except Exception:
            _best_effort_close_descriptor(descriptor_to_close)
            temporary_fd = None
            raise
        temporary_fd = None
        _assert_owned_replay_temporary(
            temporary_name,
            parent_fd=parent_fd,
            temporary_identity=temporary_identity,
            temporary_fd=temporary_pin_fd,
        )
        _publish_replay_target(
            temporary_name=temporary_name,
            target_name=canonical_target.name,
            target_parent=target_parent,
            parent_fd=parent_fd,
            parent_identity=parent_identity,
            temporary_identity=temporary_identity,
            temporary_pin_fd=temporary_pin_fd,
        )
        temporary_pin_fd = None
        temporary_name = None
        temporary_path = None
        return _replay_result(
            status="complete",
            stop_reason="replay_complete",
            fingerprints=fingerprints,
            metadata_mirrored_count=metadata_mirrored_count,
        )
    except _ReplayDataError as exc:
        if temporary_name is not None and parent_fd is not None:
            cleanup_complete = _best_effort_cleanup_replay_names(
                temporary_name, parent_fd=parent_fd
            )
            if not cleanup_complete:
                raise _ReplayOperationalBoundaryError
        return _replay_result(
            status="failed",
            stop_reason=exc.stop_reason,
            fingerprints={"source": {}, "target": {}, "equivalent": False},
            metadata_mirrored_count=0,
        )
    except ReplayPublicationError:
        raise
    except Exception:
        if temporary_name is not None and parent_fd is not None:
            _best_effort_cleanup_replay_names(
                temporary_name, parent_fd=parent_fd
            )
        raise
    finally:
        if source_conn is not None:
            _best_effort_close_source_connection(
                source_conn, close=source_connection_owned
            )
        if temporary_fd is not None:
            _best_effort_close_descriptor(temporary_fd)
        if temporary_pin_fd is not None:
            _best_effort_close_descriptor(temporary_pin_fd)
        if parent_fd is not None:
            _best_effort_close_descriptor(parent_fd)


def audit_discovery_reindex_from_archive(
    source_store: BackfillStore,
    archive: PrivateRawArchive,
    *,
    run_id: str,
    expected_source_db_sha256: str | None = None,
) -> dict[str, object]:
    """Validate a strict discovery reindex corpus without writing a database."""
    if not isinstance(source_store, BackfillStore):
        raise ValueError("source_store must be a BackfillStore")
    if not isinstance(archive, PrivateRawArchive) or archive.read_only is not True:
        raise ValueError("audit requires a read-only raw archive")
    if type(run_id) is not str or not run_id.strip():
        raise ValueError("run_id must be a non-empty string")
    if expected_source_db_sha256 is not None and (
        type(expected_source_db_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", expected_source_db_sha256) is None
    ):
        raise ValueError(
            "expected source database sha256 must be lowercase hexadecimal"
        )

    try:
        if _path_has_existing_symlink_component(source_store.path):
            raise ValueError
        resolved_source = source_store.path.resolve(strict=True)
        source_path_stat = resolved_source.lstat()
        if (
            not stat.S_ISREG(source_path_stat.st_mode)
            or source_path_stat.st_nlink != 1
        ):
            raise ValueError
    except (FileNotFoundError, OSError, ValueError):
        raise ValueError("audit source path is invalid") from None

    _assert_reindex_source_sidecars_absent(resolved_source)
    source_fd: int | None = None
    connection: sqlite3.Connection | None = None
    try:
        source_fd = os.open(
            resolved_source,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        source_stat = os.fstat(source_fd)
        source_identity = (
            source_stat.st_dev,
            source_stat.st_ino,
            source_stat.st_size,
        )
        if (
            not stat.S_ISREG(source_stat.st_mode)
            or source_stat.st_nlink != 1
            or source_identity
            != (
                source_path_stat.st_dev,
                source_path_stat.st_ino,
                source_path_stat.st_size,
            )
        ):
            raise _ReplayOperationalBoundaryError

        source_sha256 = _reindex_fd_sha256(source_fd)
        if (
            expected_source_db_sha256 is not None
            and source_sha256 != expected_source_db_sha256
        ):
            raise ValueError("source database sha256 mismatch")
        raw_inventory_sha256 = _reindex_archive_inventory_sha256(archive.root)
        connection = _open_approved_reindex_source_connection(
            source_fd,
            expected_identity=(source_stat.st_dev, source_stat.st_ino),
            expected_sha256=source_sha256,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN")
        try:
            snapshot = _load_replay_snapshot(
                connection, archive=archive, run_id=run_id
            )
        except _ReplayDataError as exc:
            raise _DiscoveryReindexDataError(exc.stop_reason) from None
        plan = _plan_strict_discovery_reindex(snapshot)

        try:
            _assert_reindex_source_sidecars_absent(resolved_source)
            current_path_stat = resolved_source.lstat()
        except (OSError, ValueError):
            raise _DiscoveryReindexDataError(
                "source_changed_during_reindex"
            ) from None
        if (
            not stat.S_ISREG(current_path_stat.st_mode)
            or current_path_stat.st_nlink != 1
            or source_identity
            != (
                current_path_stat.st_dev,
                current_path_stat.st_ino,
                current_path_stat.st_size,
            )
            or _reindex_fd_sha256(source_fd) != source_sha256
            or _reindex_archive_inventory_sha256(archive.root)
            != raw_inventory_sha256
        ):
            raise _DiscoveryReindexDataError("source_changed_during_reindex")

        occurrences: list[tuple[object, ...]] = plan["occurrences"]
        disposition_counts = Counter(str(row[10]) for row in occurrences)
        outside_window_count = disposition_counts.get("outside_window", 0)
        return {
            "schema_version": "backfill_discovery_reindex_audit_v1",
            "status": "ready",
            "stop_reason": "strict_discovery_corpus_ready",
            "run_id": run_id,
            "source_db_sha256": source_sha256,
            "raw_inventory_sha256": raw_inventory_sha256,
            "discovery_artifact_count": len(plan["artifact_ids"]),
            "strict_pass_artifact_count": len(plan["artifact_ids"]),
            "discovery_occurrence_count": len(occurrences),
            "recognized_occurrence_count": len(occurrences),
            "eligible_occurrence_count": len(occurrences)
            - outside_window_count,
            "outside_window_count": outside_window_count,
            "invalid_count": 0,
            "payload_sha_mismatch_count": 0,
            "candidate_count": len(plan["candidate_first"]),
            "wrapper_counts": dict(sorted(plan["wrapper_counts"].items())),
            "disposition_counts": dict(sorted(disposition_counts.items())),
            "candidate_set_equal": True,
            "candidate_first_provenance_match": True,
            "provider_call": False,
            "provider_attempt_made": False,
            "database_write": False,
            "live_send": False,
        }
    except (OSError, sqlite3.Error):
        raise _ReplayOperationalBoundaryError from None
    finally:
        if connection is not None:
            try:
                connection.rollback()
            finally:
                connection.close()
        if source_fd is not None:
            os.close(source_fd)


def reindex_discovery_from_archive(
    source_store: BackfillStore,
    archive: PrivateRawArchive,
    *,
    target_db: Path,
    run_id: str,
    expected_source_db_sha256: str | None = None,
) -> dict[str, object]:
    """Publish a strict-v2 discovery index without mutating source or raw data."""
    if not isinstance(source_store, BackfillStore):
        raise ValueError("source_store must be a BackfillStore")
    if not isinstance(archive, PrivateRawArchive) or archive.read_only is not True:
        raise ValueError("reindex requires a read-only raw archive")
    if type(run_id) is not str or not run_id.strip():
        raise ValueError("run_id must be a non-empty string")
    if not isinstance(target_db, Path):
        raise ValueError("target_db must be a Path")
    if expected_source_db_sha256 is not None and (
        type(expected_source_db_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", expected_source_db_sha256) is None
    ):
        raise ValueError(
            "expected source database sha256 must be lowercase hexadecimal"
        )

    (
        resolved_source,
        canonical_target,
        target_parent,
        parent_identity,
    ) = _validate_replay_paths(
        source_path=source_store.path,
        archive_root=archive.root,
        target_db=target_db,
    )
    approved_source_db = target_parent / (
        f".discovery-reindex-source-{os.urandom(16).hex()}.sqlite3"
    )
    replay_validation_db = target_parent / (
        f".discovery-reindex-proof-{os.urandom(16).hex()}.sqlite3"
    )
    staging_db = target_parent / (
        f".discovery-reindex-{os.urandom(16).hex()}.sqlite3"
    )
    source_fd: int | None = None
    source_identity: tuple[int, int, int] | None = None
    approved_source_fd: int | None = None
    approved_source_identity: tuple[int, int] | None = None
    approved_source_connection: sqlite3.Connection | None = None
    approved_source_owned = False
    replay_validation_owned = False
    staging_owned = False
    parent_fd: int | None = None
    staging_fd: int | None = None
    target_pin_fd: int | None = None
    try:
        parent_fd = _open_replay_parent(target_parent, parent_identity)
        (
            source_fd,
            source_identity,
            approved_source_fd,
            approved_source_identity,
            source_sha256,
            approved_source_connection,
        ) = _create_approved_reindex_source_snapshot(
            resolved_source=resolved_source,
            approved_source_db=approved_source_db,
            target_parent=target_parent,
            parent_fd=parent_fd,
            parent_identity=parent_identity,
            expected_source_db_sha256=expected_source_db_sha256,
        )
        approved_source_owned = True
        raw_inventory_sha256 = _reindex_archive_inventory_sha256(archive.root)
        try:
            source_provider = _reindex_provider_evidence_from_connection(
                approved_source_connection, run_id=run_id
            )
        except _DiscoveryReindexDataError:
            raise ValueError("source provider ledger invalid") from None

        replay_validation_owned = True
        replay = replay_from_archive(
            BackfillStore(approved_source_db),
            archive,
            target_db=replay_validation_db,
            run_id=run_id,
            _source_connection=approved_source_connection,
        )
        if replay["status"] != "complete" or not replay["fingerprints"][
            "equivalent"
        ]:
            return _discovery_reindex_result(
                status="failed",
                stop_reason=str(replay["stop_reason"]),
                source_db_sha256=source_sha256,
                raw_inventory_sha256=raw_inventory_sha256,
                source_provider=source_provider,
            )
        if not _best_effort_cleanup_replay_names(
            replay_validation_db.name, parent_fd=parent_fd
        ):
            raise _ReplayOperationalBoundaryError
        replay_validation_owned = False

        staging_fd, staging_identity = _create_reindex_source_snapshot(
            resolved_source=approved_source_db,
            staging_db=staging_db,
            target_parent=target_parent,
            parent_fd=parent_fd,
            parent_identity=parent_identity,
            source_connection=approved_source_connection,
        )
        staging_owned = True
        BackfillStore(staging_db).migrate()
        _assert_owned_replay_temporary(
            staging_db.name,
            parent_fd=parent_fd,
            temporary_identity=staging_identity,
            temporary_fd=staging_fd,
        )

        snapshot = _load_reindex_snapshot(
            staging_db, archive=archive, run_id=run_id
        )
        plan = _plan_strict_discovery_reindex(snapshot)
        _apply_strict_discovery_reindex(
            staging_db,
            run_id=run_id,
            plan=plan,
        )
        _prepare_replay_temp_for_publish(staging_db)
        _assert_owned_replay_temporary(
            staging_db.name,
            parent_fd=parent_fd,
            temporary_identity=staging_identity,
            temporary_fd=staging_fd,
        )

        try:
            _assert_approved_reindex_source_snapshot(
                resolved_source=resolved_source,
                source_fd=source_fd,
                source_identity=source_identity,
                approved_source_db=approved_source_db,
                approved_source_fd=approved_source_fd,
                approved_source_identity=approved_source_identity,
                parent_fd=parent_fd,
                expected_sha256=source_sha256,
            )
        except _ReplayOperationalBoundaryError:
            raise _DiscoveryReindexDataError(
                "source_changed_during_reindex"
            ) from None
        if _reindex_archive_inventory_sha256(archive.root) != raw_inventory_sha256:
            raise _DiscoveryReindexDataError("source_changed_during_reindex")
        staging_provider = _reindex_provider_evidence(staging_db, run_id=run_id)
        if staging_provider != source_provider:
            raise _DiscoveryReindexDataError("provider_ledger_changed")

        _assert_replay_name_absent(canonical_target.name, parent_fd=parent_fd)
        _assert_owned_replay_temporary(
            staging_db.name,
            parent_fd=parent_fd,
            temporary_identity=staging_identity,
            temporary_fd=staging_fd,
        )
        _remove_replay_sidecars_for_publish(
            staging_db.name, parent_fd=parent_fd
        )
        os.fsync(staging_fd)
        staging_sha256 = _reindex_fd_sha256(staging_fd)
        target_pin_fd = os.dup(staging_fd)
        descriptor_for_publish = staging_fd
        staging_fd = None
        try:
            _publish_replay_target(
                temporary_name=staging_db.name,
                target_name=canonical_target.name,
                target_parent=target_parent,
                parent_fd=parent_fd,
                parent_identity=parent_identity,
                temporary_identity=staging_identity,
                temporary_pin_fd=descriptor_for_publish,
            )
        except Exception:
            _best_effort_close_descriptor(descriptor_for_publish)
            raise
        staging_owned = False
        try:
            _assert_discovery_reindex_names_absent(staging_db)
            _assert_owned_replay_temporary(
                canonical_target.name,
                parent_fd=parent_fd,
                temporary_identity=staging_identity,
                temporary_fd=target_pin_fd,
            )
            _assert_reindex_sqlite_sidecars_absent(
                canonical_target.name, parent_fd=parent_fd
            )
            _assert_approved_reindex_source_snapshot(
                resolved_source=resolved_source,
                source_fd=source_fd,
                source_identity=source_identity,
                approved_source_db=approved_source_db,
                approved_source_fd=approved_source_fd,
                approved_source_identity=approved_source_identity,
                parent_fd=parent_fd,
                expected_sha256=source_sha256,
            )
            if (
                _reindex_archive_inventory_sha256(archive.root)
                != raw_inventory_sha256
            ):
                raise _ReplayOperationalBoundaryError
            target_sha256 = _reindex_fd_sha256(target_pin_fd)
            if target_sha256 != staging_sha256:
                raise _ReplayOperationalBoundaryError
            _assert_owned_replay_temporary(
                canonical_target.name,
                parent_fd=parent_fd,
                temporary_identity=staging_identity,
                temporary_fd=target_pin_fd,
            )
            _assert_reindex_sqlite_sidecars_absent(
                canonical_target.name, parent_fd=parent_fd
            )
        except Exception:
            raise _publication_error() from None
        target_provider = staging_provider
        return _discovery_reindex_result(
            status="complete",
            stop_reason="reindex_complete",
            source_db_sha256=source_sha256,
            raw_inventory_sha256=raw_inventory_sha256,
            target_db_sha256=target_sha256,
            source_provider=source_provider,
            target_provider=target_provider,
            discovery_artifact_count=len(plan["artifact_ids"]),
            discovery_occurrence_count=len(plan["occurrences"]),
            candidate_count=len(plan["candidate_first"]),
        )
    except _DiscoveryReindexDataError as exc:
        return _discovery_reindex_result(
            status="failed",
            stop_reason=exc.stop_reason,
            source_db_sha256=source_sha256,
            raw_inventory_sha256=raw_inventory_sha256,
            source_provider=source_provider,
        )
    finally:
        cleanup_failed = False
        if staging_fd is not None:
            _best_effort_close_descriptor(staging_fd)
        if target_pin_fd is not None:
            _best_effort_close_descriptor(target_pin_fd)
        if approved_source_connection is not None:
            try:
                approved_source_connection.close()
            except sqlite3.Error:
                pass
        if approved_source_fd is not None:
            _best_effort_close_descriptor(approved_source_fd)
        if source_fd is not None:
            _best_effort_close_descriptor(source_fd)
        if parent_fd is not None:
            owned_names = (
                (replay_validation_owned, replay_validation_db.name),
                (staging_owned, staging_db.name),
                (approved_source_owned, approved_source_db.name),
            )
            for owned, name in owned_names:
                if not owned:
                    continue
                try:
                    cleanup_complete = _best_effort_cleanup_replay_names(
                        name, parent_fd=parent_fd
                    )
                except Exception:
                    cleanup_complete = False
                if not cleanup_complete:
                    cleanup_failed = True
            _best_effort_close_descriptor(parent_fd)
        elif replay_validation_owned or staging_owned or approved_source_owned:
            cleanup_failed = True
        if cleanup_failed:
            raise _ReplayOperationalBoundaryError


def recover_collection_from_archive(
    source_store: BackfillStore,
    archive: PrivateRawArchive,
    *,
    target_db: Path,
    run_id: str,
    expected_source_db_sha256: str,
    recovered_at_utc: datetime,
) -> dict[str, object]:
    """Publish a repaired collection target using only pinned DB/raw evidence."""
    if not isinstance(source_store, BackfillStore):
        raise ValueError("source_store must be a BackfillStore")
    if not isinstance(archive, PrivateRawArchive) or archive.read_only is not True:
        raise ValueError("collection recovery requires a read-only raw archive")
    if type(run_id) is not str or not run_id.strip():
        raise ValueError("run_id must be a non-empty string")
    if not isinstance(target_db, Path):
        raise ValueError("target_db must be a Path")
    if (
        type(expected_source_db_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", expected_source_db_sha256) is None
    ):
        raise ValueError(
            "expected source database sha256 must be lowercase hexadecimal"
        )
    if (
        not isinstance(recovered_at_utc, datetime)
        or recovered_at_utc.tzinfo is None
        or recovered_at_utc.utcoffset() is None
    ):
        raise ValueError("recovered_at_utc must be timezone-aware")

    (
        resolved_source,
        canonical_target,
        target_parent,
        parent_identity,
    ) = _validate_replay_paths(
        source_path=source_store.path,
        archive_root=archive.root,
        target_db=target_db,
    )
    approved_source_db = target_parent / (
        f".collection-recovery-source-{os.urandom(16).hex()}.sqlite3"
    )
    staging_db = target_parent / (
        f".collection-recovery-{os.urandom(16).hex()}.sqlite3"
    )
    source_fd: int | None = None
    source_identity: tuple[int, int, int] | None = None
    approved_source_fd: int | None = None
    approved_source_identity: tuple[int, int] | None = None
    approved_source_connection: sqlite3.Connection | None = None
    approved_source_owned = False
    staging_owned = False
    parent_fd: int | None = None
    staging_fd: int | None = None
    target_pin_fd: int | None = None
    source_sha256 = expected_source_db_sha256
    raw_inventory_sha256 = ""
    source_provider: dict[str, object] = {
        "max_provider_requests": 0,
        "provider_request_count": 0,
        "ledger_sha256": "",
    }
    try:
        parent_fd = _open_replay_parent(target_parent, parent_identity)
        (
            source_fd,
            source_identity,
            approved_source_fd,
            approved_source_identity,
            source_sha256,
            approved_source_connection,
        ) = _create_approved_reindex_source_snapshot(
            resolved_source=resolved_source,
            approved_source_db=approved_source_db,
            target_parent=target_parent,
            parent_fd=parent_fd,
            parent_identity=parent_identity,
            expected_source_db_sha256=expected_source_db_sha256,
        )
        approved_source_owned = True
        raw_inventory_sha256 = _reindex_archive_inventory_sha256(archive.root)
        source_provider = _reindex_provider_evidence_from_connection(
            approved_source_connection, run_id=run_id
        )
        try:
            snapshot = _load_replay_snapshot(
                approved_source_connection,
                archive=archive,
                run_id=run_id,
            )
        except _ReplayDataError as exc:
            raise _DiscoveryReindexDataError(exc.stop_reason) from None
        plan = _plan_strict_discovery_reindex(
            snapshot, allow_schema_drift_recovery=True
        )
        expected_failed_candidate_ids = {
            str(row["post_id"])
            for row in snapshot["rows"]["backfill_candidates"]
            if row["status"] == "failed"
            and row["status_reason"] == "comments_schema_drift"
        }
        if not expected_failed_candidate_ids:
            raise _DiscoveryReindexDataError(
                "schema_drift_recovery_candidate_mismatch"
            )
        recovered_lanes = set(plan["recovered_lanes"])
        if not recovered_lanes and (
            plan["new_candidate_ids"]
            or plan["checkpoint_updates"]
            or plan["artifact_response_cursors"]
        ):
            raise _DiscoveryReindexDataError(
                "schema_drift_recovery_discovery_state_invalid"
            )

        staging_fd, staging_identity = _create_reindex_source_snapshot(
            resolved_source=approved_source_db,
            staging_db=staging_db,
            target_parent=target_parent,
            parent_fd=parent_fd,
            parent_identity=parent_identity,
            source_connection=approved_source_connection,
        )
        staging_owned = True
        BackfillStore(staging_db).migrate()
        _assert_owned_replay_temporary(
            staging_db.name,
            parent_fd=parent_fd,
            temporary_identity=staging_identity,
            temporary_fd=staging_fd,
        )
        if recovered_lanes:
            _apply_strict_discovery_reindex(
                staging_db,
                run_id=run_id,
                plan=plan,
                allow_schema_drift_recovery=True,
            )
        reset = _reset_schema_drift_hydration_state(
            staging_db,
            run_id=run_id,
            expected_failed_candidate_ids=expected_failed_candidate_ids,
            recovered_at_utc=recovered_at_utc,
        )
        window_start, effective_end = _manifest_window(snapshot["manifest"])
        if window_start is None or effective_end is None:
            raise _DiscoveryReindexDataError("source_manifest_invalid")
        recovery_store = BackfillStore(staging_db)
        recovered_candidates = recover_archived_candidates(
            recovery_store,
            archive,
            run_id=run_id,
            now=lambda: recovered_at_utc,
            window=CollectionWindow(
                timezone_name="UTC",
                run_at_local=effective_end,
                start_local=window_start,
                end_local=effective_end,
                start_utc=window_start,
                end_utc=effective_end,
            ),
        )
        if not recovered_candidates:
            raise _DiscoveryReindexDataError(
                "schema_drift_recovery_archived_hydration_missing"
            )

        with sqlite3.connect(staging_db, timeout=5.0) as connection:
            connection.row_factory = sqlite3.Row
            if (
                connection.execute("PRAGMA foreign_key_check").fetchone()
                is not None
                or [
                    str(row[0])
                    for row in connection.execute(
                        "PRAGMA integrity_check"
                    ).fetchall()
                ]
                != ["ok"]
                or connection.execute(
                    "SELECT 1 FROM delivery_previews WHERE run_id=? LIMIT 1",
                    (run_id,),
                ).fetchone()
                is not None
                or connection.execute(
                    "SELECT 1 FROM backfill_candidates WHERE run_id=? "
                    "AND status='failed' AND status_reason='comments_schema_drift' "
                    "LIMIT 1",
                    (run_id,),
                ).fetchone()
                is not None
            ):
                raise _DiscoveryReindexDataError(
                    "schema_drift_recovery_target_invalid"
                )

        _prepare_replay_temp_for_publish(staging_db)
        _assert_owned_replay_temporary(
            staging_db.name,
            parent_fd=parent_fd,
            temporary_identity=staging_identity,
            temporary_fd=staging_fd,
        )
        try:
            _assert_approved_reindex_source_snapshot(
                resolved_source=resolved_source,
                source_fd=source_fd,
                source_identity=source_identity,
                approved_source_db=approved_source_db,
                approved_source_fd=approved_source_fd,
                approved_source_identity=approved_source_identity,
                parent_fd=parent_fd,
                expected_sha256=source_sha256,
            )
        except _ReplayOperationalBoundaryError:
            raise _DiscoveryReindexDataError(
                "source_changed_during_recovery"
            ) from None
        if _reindex_archive_inventory_sha256(archive.root) != raw_inventory_sha256:
            raise _DiscoveryReindexDataError(
                "source_changed_during_recovery"
            )
        target_provider = _reindex_provider_evidence(staging_db, run_id=run_id)
        if target_provider != source_provider:
            raise _DiscoveryReindexDataError("provider_ledger_changed")

        _assert_replay_name_absent(canonical_target.name, parent_fd=parent_fd)
        _remove_replay_sidecars_for_publish(
            staging_db.name, parent_fd=parent_fd
        )
        os.fsync(staging_fd)
        staging_sha256 = _reindex_fd_sha256(staging_fd)
        target_pin_fd = os.dup(staging_fd)
        descriptor_for_publish = staging_fd
        staging_fd = None
        try:
            _publish_replay_target(
                temporary_name=staging_db.name,
                target_name=canonical_target.name,
                target_parent=target_parent,
                parent_fd=parent_fd,
                parent_identity=parent_identity,
                temporary_identity=staging_identity,
                temporary_pin_fd=descriptor_for_publish,
            )
        except Exception:
            _best_effort_close_descriptor(descriptor_for_publish)
            raise
        staging_owned = False
        try:
            _assert_discovery_reindex_names_absent(staging_db)
            _assert_owned_replay_temporary(
                canonical_target.name,
                parent_fd=parent_fd,
                temporary_identity=staging_identity,
                temporary_fd=target_pin_fd,
            )
            _assert_reindex_sqlite_sidecars_absent(
                canonical_target.name, parent_fd=parent_fd
            )
            _assert_approved_reindex_source_snapshot(
                resolved_source=resolved_source,
                source_fd=source_fd,
                source_identity=source_identity,
                approved_source_db=approved_source_db,
                approved_source_fd=approved_source_fd,
                approved_source_identity=approved_source_identity,
                parent_fd=parent_fd,
                expected_sha256=source_sha256,
            )
            if _reindex_archive_inventory_sha256(archive.root) != raw_inventory_sha256:
                raise _ReplayOperationalBoundaryError
            target_sha256 = _reindex_fd_sha256(target_pin_fd)
            if target_sha256 != staging_sha256:
                raise _ReplayOperationalBoundaryError
        except Exception:
            raise _publication_error() from None
        return {
            "schema_version": "backfill_collection_recovery_v1",
            "status": "complete",
            "stop_reason": "collection_recovery_complete",
            "run_id": run_id,
            "provider_call": False,
            "provider_attempt_made": False,
            "database_write": "recovery_target_only",
            "live_send": False,
            "source_db_sha256": source_sha256,
            "raw_inventory_sha256": raw_inventory_sha256,
            "target_db_sha256": target_sha256,
            "source_max_provider_requests": source_provider[
                "max_provider_requests"
            ],
            "source_provider_request_count": source_provider[
                "provider_request_count"
            ],
            "source_provider_ledger_sha256": source_provider[
                "ledger_sha256"
            ],
            "target_max_provider_requests": target_provider[
                "max_provider_requests"
            ],
            "target_provider_request_count": target_provider[
                "provider_request_count"
            ],
            "target_provider_ledger_sha256": target_provider[
                "ledger_sha256"
            ],
            "discovery_artifact_count": len(plan["artifact_ids"]),
            "discovery_occurrence_count": len(plan["occurrences"]),
            "candidate_count": len(plan["candidate_first"]),
            "new_candidate_count": len(plan["new_candidate_ids"]),
            "recovered_discovery_lane_count": len(plan["recovered_lanes"]),
            **reset,
            "archived_hydrated_candidate_count": len(recovered_candidates),
        }
    except _DiscoveryReindexDataError as exc:
        return {
            "schema_version": "backfill_collection_recovery_v1",
            "status": "failed",
            "stop_reason": exc.stop_reason,
            "run_id": run_id,
            "provider_call": False,
            "provider_attempt_made": False,
            "database_write": False,
            "live_send": False,
            "source_db_sha256": source_sha256,
            "raw_inventory_sha256": raw_inventory_sha256,
            "target_db_sha256": None,
            "source_max_provider_requests": source_provider[
                "max_provider_requests"
            ],
            "source_provider_request_count": source_provider[
                "provider_request_count"
            ],
            "source_provider_ledger_sha256": source_provider["ledger_sha256"],
            "target_max_provider_requests": None,
            "target_provider_request_count": None,
            "target_provider_ledger_sha256": None,
            "discovery_artifact_count": 0,
            "discovery_occurrence_count": 0,
            "candidate_count": 0,
            "new_candidate_count": 0,
            "recovered_discovery_lane_count": 0,
            "reset_candidate_count": 0,
            "reset_batch_count": 0,
            "reset_comment_checkpoint_count": 0,
            "raw_persisted_batch_count": 0,
            "prepared_batch_count": 0,
            "archived_hydrated_candidate_count": 0,
        }
    finally:
        cleanup_failed = False
        if staging_fd is not None:
            _best_effort_close_descriptor(staging_fd)
        if target_pin_fd is not None:
            _best_effort_close_descriptor(target_pin_fd)
        if approved_source_connection is not None:
            try:
                approved_source_connection.close()
            except sqlite3.Error:
                pass
        if approved_source_fd is not None:
            _best_effort_close_descriptor(approved_source_fd)
        if source_fd is not None:
            _best_effort_close_descriptor(source_fd)
        if parent_fd is not None:
            for owned, name in (
                (staging_owned, staging_db.name),
                (approved_source_owned, approved_source_db.name),
            ):
                if not owned:
                    continue
                try:
                    cleanup_complete = _best_effort_cleanup_replay_names(
                        name, parent_fd=parent_fd
                    )
                except Exception:
                    cleanup_complete = False
                if not cleanup_complete:
                    cleanup_failed = True
            _best_effort_close_descriptor(parent_fd)
        elif staging_owned or approved_source_owned:
            cleanup_failed = True
        if cleanup_failed:
            raise _ReplayOperationalBoundaryError


def validate_collection_recovery_postflight(
    *,
    recovery: dict[str, object],
    recovery_exit_code: int,
    result_report_match: bool,
    source_database_unchanged: bool,
    source_raw_unchanged: bool,
    provider_ledger_unchanged: bool,
    production_unchanged: bool,
    target_database_name: str,
    target_database_present: bool,
    target_database_sha256: str | None,
    target_residue: tuple[str, ...],
    recovery_report_name: str,
    active_operation_process_count: int,
    one_shot_container_count: int,
) -> dict[str, object]:
    """Validate either terminal recovery outcome without changing its status."""

    def plain_filename(value: object) -> bool:
        return bool(
            type(value) is str
            and value not in {"", ".", ".."}
            and "/" not in value
            and "\\" not in value
        )

    if (
        not isinstance(recovery, dict)
        or type(recovery_exit_code) is not int
        or type(result_report_match) is not bool
        or type(source_database_unchanged) is not bool
        or type(source_raw_unchanged) is not bool
        or type(provider_ledger_unchanged) is not bool
        or type(production_unchanged) is not bool
        or type(target_database_present) is not bool
        or type(target_residue) is not tuple
        or any(type(value) is not str for value in target_residue)
        or type(active_operation_process_count) is not int
        or active_operation_process_count < 0
        or type(one_shot_container_count) is not int
        or one_shot_container_count < 0
    ):
        raise ValueError("collection_recovery_postflight_invalid")

    status = recovery.get("status")
    stop_reason = recovery.get("stop_reason")
    residue_is_canonical = bool(
        len(target_residue) == len(set(target_residue))
        and target_residue == tuple(sorted(target_residue))
    )
    common_invariants = {
        "recovery_schema_exact": recovery.get("schema_version")
        == "backfill_collection_recovery_v1",
        "recovery_status_terminal": status == "complete" or status == "failed",
        "recovery_stop_reason_safe": type(stop_reason) is str
        and _SAFE_REASON_PATTERN.fullmatch(stop_reason) is not None,
        "result_report_match": result_report_match,
        "source_database_unchanged": source_database_unchanged,
        "source_raw_unchanged": source_raw_unchanged,
        "provider_ledger_unchanged": provider_ledger_unchanged,
        "production_unchanged": production_unchanged,
        "provider_not_called": recovery.get("provider_call") is False
        and recovery.get("provider_attempt_made") is False,
        "live_send_false": recovery.get("live_send") is False,
        "target_names_valid": plain_filename(target_database_name)
        and plain_filename(recovery_report_name)
        and target_database_name != recovery_report_name,
        "target_residue_canonical": residue_is_canonical,
        "active_operation_process_count_zero": active_operation_process_count == 0,
        "one_shot_container_count_zero": one_shot_container_count == 0,
    }

    if status == "complete":
        outcome_invariants = {
            "recovery_exit_code_exact": recovery_exit_code == 0,
            "recovery_outcome_exact": stop_reason == "collection_recovery_complete"
            and recovery.get("database_write") == "recovery_target_only",
            "target_database_exact": target_database_present
            and type(target_database_sha256) is str
            and _SHA256_PATTERN.fullmatch(target_database_sha256) is not None
            and recovery.get("target_db_sha256") == target_database_sha256,
            "target_residue_exact": target_residue
            == tuple(sorted((target_database_name, recovery_report_name))),
        }
        target_database_published = True
    elif status == "failed":
        outcome_invariants = {
            "recovery_exit_code_exact": recovery_exit_code == 1,
            "recovery_outcome_exact": stop_reason != "collection_recovery_complete"
            and recovery.get("database_write") is False,
            "target_database_exact": not target_database_present
            and target_database_sha256 is None
            and recovery.get("target_db_sha256") is None,
            "target_residue_exact": target_residue == (recovery_report_name,),
        }
        target_database_published = False
    else:
        outcome_invariants = {
            "recovery_exit_code_exact": False,
            "recovery_outcome_exact": False,
            "target_database_exact": False,
            "target_residue_exact": False,
        }
        target_database_published = False

    invariants = {**common_invariants, **outcome_invariants}
    if not all(invariants.values()):
        raise ValueError("collection_recovery_postflight_invalid")
    return {
        "schema_version": "backfill_collection_recovery_postflight_v1",
        "postflight_status": "verified",
        "status": status,
        "stop_reason": stop_reason,
        "recovery_exit_code": recovery_exit_code,
        "target_database_published": target_database_published,
        "target_database_sha256": target_database_sha256,
        "provider_call": False,
        "provider_attempt_made": False,
        "database_write": recovery["database_write"],
        "production_unchanged": True,
        "live_send": False,
        "all_invariants_passed": True,
        "invariants": invariants,
    }


def _reindex_sqlite_sidecar_paths(path: Path) -> tuple[Path, ...]:
    return tuple(
        Path(str(path) + suffix) for suffix in ("-wal", "-shm", "-journal")
    )


def _assert_reindex_source_sidecars_absent(path: Path) -> None:
    try:
        present = any(
            os.path.lexists(sidecar)
            for sidecar in _reindex_sqlite_sidecar_paths(path)
        )
    except OSError:
        raise ValueError("source database sidecar state unreadable") from None
    if present:
        raise ValueError("source database sidecar present")


def _reindex_fd_sha256(descriptor: int) -> str:
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise _ReplayOperationalBoundaryError
        os.lseek(descriptor, 0, os.SEEK_SET)
        digest = sha256()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(descriptor)
    except _ReplayOperationalBoundaryError:
        raise
    except OSError:
        raise _ReplayOperationalBoundaryError from None
    if (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_nlink,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_nlink,
    ):
        raise _ReplayOperationalBoundaryError
    return digest.hexdigest()


def _sqlite_memory_snapshot_supports_serialize() -> bool:
    return callable(getattr(sqlite3.Connection, "serialize", None)) and callable(
        getattr(sqlite3.Connection, "deserialize", None)
    )


def _open_approved_reindex_source_connection(
    descriptor: int,
    *,
    expected_identity: tuple[int, int],
    expected_sha256: str,
) -> sqlite3.Connection:
    dev_fd_path = Path(f"/dev/fd/{descriptor}")
    file_connection: sqlite3.Connection | None = None
    memory_connection: sqlite3.Connection | None = None
    try:
        descriptor_stat = os.fstat(descriptor)
        dev_fd_stat = os.stat(dev_fd_path)
        if (
            not stat.S_ISREG(descriptor_stat.st_mode)
            or not stat.S_ISREG(dev_fd_stat.st_mode)
            or (descriptor_stat.st_dev, descriptor_stat.st_ino)
            != expected_identity
            or dev_fd_stat.st_ino != expected_identity[1]
        ):
            raise _ReplayOperationalBoundaryError
        file_connection = sqlite3.connect(
            f"{dev_fd_path.as_uri()}?mode=ro&immutable=1",
            uri=True,
            timeout=5.0,
        )
        file_connection.row_factory = sqlite3.Row
        file_connection.execute("PRAGMA query_only=ON")
        if _sqlite_memory_snapshot_supports_serialize():
            serialized = file_connection.serialize()
            if sha256(serialized).hexdigest() != expected_sha256:
                raise _ReplayOperationalBoundaryError
            memory_connection = sqlite3.connect(":memory:", timeout=5.0)
            memory_connection.deserialize(serialized)
            del serialized
            if sha256(memory_connection.serialize()).hexdigest() != expected_sha256:
                raise _ReplayOperationalBoundaryError
        else:
            if _reindex_fd_sha256(descriptor) != expected_sha256:
                raise _ReplayOperationalBoundaryError
            memory_connection = sqlite3.connect(":memory:", timeout=5.0)
            file_connection.backup(memory_connection)
            if _reindex_fd_sha256(descriptor) != expected_sha256:
                raise _ReplayOperationalBoundaryError
        memory_connection.row_factory = sqlite3.Row
        memory_connection.execute("PRAGMA query_only=ON")
        descriptor_after = os.fstat(descriptor)
        dev_fd_after = os.stat(dev_fd_path)
        if (
            (descriptor_after.st_dev, descriptor_after.st_ino)
            != expected_identity
            or dev_fd_after.st_ino != expected_identity[1]
        ):
            raise _ReplayOperationalBoundaryError
        file_connection.close()
        file_connection = None
        return memory_connection
    except _ReplayOperationalBoundaryError:
        if memory_connection is not None:
            memory_connection.close()
        if file_connection is not None:
            file_connection.close()
        raise
    except (OSError, sqlite3.Error, ValueError):
        if memory_connection is not None:
            memory_connection.close()
        if file_connection is not None:
            file_connection.close()
        raise _ReplayOperationalBoundaryError from None


def _create_approved_reindex_source_snapshot(
    *,
    resolved_source: Path,
    approved_source_db: Path,
    target_parent: Path,
    parent_fd: int,
    parent_identity: tuple[int, int],
    expected_source_db_sha256: str | None,
) -> tuple[
    int,
    tuple[int, int, int],
    int,
    tuple[int, int],
    str,
    sqlite3.Connection,
]:
    _assert_replay_parent_identity(
        target_parent,
        parent_fd=parent_fd,
        expected_identity=parent_identity,
    )
    _assert_reindex_source_sidecars_absent(resolved_source)
    _assert_replay_name_absent(approved_source_db.name, parent_fd=parent_fd)
    source_fd: int | None = None
    approved_fd: int | None = None
    approved_connection: sqlite3.Connection | None = None
    try:
        source_fd = os.open(
            resolved_source,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        source_stat = os.fstat(source_fd)
        path_stat = resolved_source.lstat()
        source_identity = (
            source_stat.st_dev,
            source_stat.st_ino,
            source_stat.st_size,
        )
        if (
            not stat.S_ISREG(source_stat.st_mode)
            or not stat.S_ISREG(path_stat.st_mode)
            or source_stat.st_nlink != 1
            or path_stat.st_nlink != 1
            or source_identity
            != (path_stat.st_dev, path_stat.st_ino, path_stat.st_size)
        ):
            raise _ReplayOperationalBoundaryError

        approved_fd = os.open(
            approved_source_db.name,
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent_fd,
        )
        approved_stat = os.fstat(approved_fd)
        approved_identity = (approved_stat.st_dev, approved_stat.st_ino)
        _assert_owned_replay_temporary(
            approved_source_db.name,
            parent_fd=parent_fd,
            temporary_identity=approved_identity,
            temporary_fd=approved_fd,
        )

        os.lseek(source_fd, 0, os.SEEK_SET)
        digest = sha256()
        while True:
            chunk = os.read(source_fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            remaining = memoryview(chunk)
            while remaining:
                written = os.write(approved_fd, remaining)
                if written <= 0:
                    raise _ReplayOperationalBoundaryError
                remaining = remaining[written:]
        os.fsync(approved_fd)
        source_sha256 = digest.hexdigest()
        if (
            expected_source_db_sha256 is not None
            and source_sha256 != expected_source_db_sha256
        ):
            raise ValueError("source database sha256 mismatch")

        _assert_reindex_source_sidecars_absent(resolved_source)
        if _reindex_fd_sha256(source_fd) != source_sha256:
            raise _ReplayOperationalBoundaryError
        current_path_stat = resolved_source.lstat()
        if (
            not stat.S_ISREG(current_path_stat.st_mode)
            or current_path_stat.st_nlink != 1
            or source_identity
            != (
                current_path_stat.st_dev,
                current_path_stat.st_ino,
                current_path_stat.st_size,
            )
        ):
            raise _ReplayOperationalBoundaryError
        if _reindex_fd_sha256(approved_fd) != source_sha256:
            raise _ReplayOperationalBoundaryError
        _assert_owned_replay_temporary(
            approved_source_db.name,
            parent_fd=parent_fd,
            temporary_identity=approved_identity,
            temporary_fd=approved_fd,
        )
        approved_connection = _open_approved_reindex_source_connection(
            approved_fd,
            expected_identity=approved_identity,
            expected_sha256=source_sha256,
        )
        return (
            source_fd,
            source_identity,
            approved_fd,
            approved_identity,
            source_sha256,
            approved_connection,
        )
    except Exception:
        if approved_connection is not None:
            approved_connection.close()
        if approved_fd is not None:
            _best_effort_close_descriptor(approved_fd)
        if source_fd is not None:
            _best_effort_close_descriptor(source_fd)
        _best_effort_cleanup_replay_names(
            approved_source_db.name, parent_fd=parent_fd
        )
        raise


def _assert_approved_reindex_source_snapshot(
    *,
    resolved_source: Path,
    source_fd: int,
    source_identity: tuple[int, int, int],
    approved_source_db: Path,
    approved_source_fd: int,
    approved_source_identity: tuple[int, int],
    parent_fd: int,
    expected_sha256: str,
) -> None:
    try:
        _assert_reindex_source_sidecars_absent(resolved_source)
    except ValueError:
        raise _ReplayOperationalBoundaryError from None
    try:
        path_stat = resolved_source.lstat()
    except OSError:
        raise _ReplayOperationalBoundaryError from None
    if (
        not stat.S_ISREG(path_stat.st_mode)
        or path_stat.st_nlink != 1
        or source_identity
        != (path_stat.st_dev, path_stat.st_ino, path_stat.st_size)
        or _reindex_fd_sha256(source_fd) != expected_sha256
    ):
        raise _ReplayOperationalBoundaryError
    _assert_owned_replay_temporary(
        approved_source_db.name,
        parent_fd=parent_fd,
        temporary_identity=approved_source_identity,
        temporary_fd=approved_source_fd,
    )
    if any(
        os.path.lexists(path)
        for path in _reindex_sqlite_sidecar_paths(approved_source_db)
    ) or _reindex_fd_sha256(approved_source_fd) != expected_sha256:
        raise _ReplayOperationalBoundaryError


def _assert_reindex_sqlite_sidecars_absent(
    database_name: str, *, parent_fd: int
) -> None:
    if any(
        not _replay_name_is_absent(name, parent_fd=parent_fd)
        for name in _replay_temporary_names(database_name)[1:]
    ):
        raise _ReplayOperationalBoundaryError


def _create_reindex_source_snapshot(
    *,
    resolved_source: Path,
    staging_db: Path,
    target_parent: Path,
    parent_fd: int,
    parent_identity: tuple[int, int],
    source_connection: sqlite3.Connection | None = None,
) -> tuple[int, tuple[int, int]]:
    _assert_replay_parent_identity(
        target_parent,
        parent_fd=parent_fd,
        expected_identity=parent_identity,
    )
    _assert_replay_name_absent(staging_db.name, parent_fd=parent_fd)
    descriptor = os.open(
        staging_db.name,
        os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=parent_fd,
    )
    descriptor_stat = os.fstat(descriptor)
    identity = (descriptor_stat.st_dev, descriptor_stat.st_ino)
    try:
        _assert_owned_replay_temporary(
            staging_db.name,
            parent_fd=parent_fd,
            temporary_identity=identity,
            temporary_fd=descriptor,
        )
        source = source_connection
        source_owned = source is None
        if source is None:
            source = sqlite3.connect(
                f"{resolved_source.as_uri()}?mode=ro&immutable=1",
                uri=True,
                timeout=5.0,
            )
        target: sqlite3.Connection | None = None
        try:
            source.row_factory = sqlite3.Row
            source.execute("PRAGMA query_only=ON")
            target = sqlite3.connect(staging_db, timeout=5.0)
            source.backup(target)
            target.commit()
        finally:
            if target is not None:
                target.close()
            if source_owned:
                source.close()
        _assert_owned_replay_temporary(
            staging_db.name,
            parent_fd=parent_fd,
            temporary_identity=identity,
            temporary_fd=descriptor,
        )
        return descriptor, identity
    except Exception:
        _best_effort_close_descriptor(descriptor)
        _cleanup_discovery_reindex_staging(staging_db)
        raise


def _load_reindex_snapshot(
    staging_db: Path,
    *,
    archive: PrivateRawArchive,
    run_id: str,
) -> dict[str, object]:
    connection = sqlite3.connect(
        f"{staging_db.resolve(strict=True).as_uri()}?mode=ro&immutable=1",
        uri=True,
        timeout=5.0,
    )
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN")
        return _load_replay_snapshot(connection, archive=archive, run_id=run_id)
    finally:
        try:
            connection.rollback()
        finally:
            connection.close()


def _ordered_discovery_artifact_ids(
    discovery_artifacts: dict[tuple[str, str], list[RawArtifactMetadata]],
) -> list[str]:
    active_lanes = [
        (lane, sorted(artifacts, key=lambda artifact: int(artifact.page_number or 0)))
        for lane, artifacts in discovery_artifacts.items()
        if artifacts
    ]
    if len(active_lanes) <= 1:
        return [
            artifact.artifact_id
            for _lane, artifacts in active_lanes
            for artifact in artifacts
        ]

    ordered_inputs: list[tuple[datetime, tuple[str, str], RawArtifactMetadata]] = []
    seen_instants: set[datetime] = set()
    for lane, artifacts in active_lanes:
        lane_times: list[datetime] = []
        for artifact in artifacts:
            try:
                captured_at = datetime.fromisoformat(artifact.captured_at_utc)
                offset = captured_at.utcoffset()
            except (TypeError, ValueError):
                raise ValueError("discovery capture order invalid") from None
            if captured_at.tzinfo is None or offset is None:
                raise ValueError("discovery capture order invalid")
            if captured_at in seen_instants:
                raise ValueError("discovery capture order invalid")
            seen_instants.add(captured_at)
            lane_times.append(captured_at)
            ordered_inputs.append((captured_at, lane, artifact))
        if any(
            later <= earlier
            for earlier, later in zip(lane_times, lane_times[1:])
        ):
            raise ValueError("discovery capture order invalid")

    ordered_inputs.sort(key=lambda item: item[0])
    observed_pages: dict[tuple[str, str], list[int]] = {}
    for _captured_at, lane, artifact in ordered_inputs:
        observed_pages.setdefault(lane, []).append(int(artifact.page_number or 0))
    if any(
        pages != list(range(1, len(pages) + 1))
        for pages in observed_pages.values()
    ):
        raise ValueError("discovery capture order invalid")
    return [artifact.artifact_id for _captured_at, _lane, artifact in ordered_inputs]


def _schema_drift_recovery_attempt_is_valid(
    *,
    checkpoint: dict[str, object],
    attempts: list[dict[str, object]],
    manifest_provider_request_count: object,
    expected_endpoint: str,
) -> bool:
    request_number = checkpoint.get("provider_request_count")
    if (
        type(request_number) is not int
        or type(manifest_provider_request_count) is not int
        or request_number < 1
        or request_number > manifest_provider_request_count
    ):
        return False
    matches = [
        attempt
        for attempt in attempts
        if type(attempt.get("request_number")) is int
        and attempt.get("request_number") == request_number
    ]
    if len(matches) != 1:
        return False
    attempt = matches[0]
    return bool(
        attempt.get("run_id") == checkpoint.get("run_id")
        and attempt.get("status") == "succeeded"
        and attempt.get("endpoint") == expected_endpoint
        and _replay_timestamp(attempt.get("sent_at_utc")) is not None
        and _replay_timestamp(attempt.get("completed_at_utc")) is not None
        and attempt.get("error_class") is None
    )


def _plan_strict_discovery_reindex(
    snapshot: dict[str, object],
    *,
    allow_schema_drift_recovery: bool = False,
) -> dict[str, object]:
    if type(allow_schema_drift_recovery) is not bool:
        raise ValueError("allow_schema_drift_recovery must be a bool")
    run_id = str(snapshot["run_id"])
    manifest: dict[str, object] = snapshot["manifest"]
    rows: dict[str, list[dict[str, object]]] = snapshot["rows"]
    artifacts: dict[str, RawArtifactMetadata] = snapshot["artifacts"]
    payloads: dict[str, bytes] = snapshot["payloads"]
    window_start, effective_end = _manifest_window(manifest)
    if window_start is None or effective_end is None:
        raise _DiscoveryReindexDataError("source_manifest_invalid")

    configured_lanes = required_lanes_snapshot(
        search_terms=snapshot["search_terms"],
        subreddits=snapshot["subreddits"],
        include_subreddit_sweep=bool(manifest["include_subreddit_sweep"]),
    )
    lane_by_hash: dict[tuple[str, str], list[str]] = {}
    for lane_type, lane_key in configured_lanes:
        lane_by_hash.setdefault(
            (lane_type, sha256(lane_key.encode()).hexdigest()), []
        ).append(lane_key)
    checkpoints = {
        (str(row["lane_type"]), str(row["lane_key"])): row
        for row in rows["backfill_checkpoints"]
    }
    candidate_rows = {
        str(row["post_id"]): row for row in rows["backfill_candidates"]
    }
    candidate_ids = set(candidate_rows)
    structured_post_ids = {
        str(row["post_id"]) for row in rows["reddit_threads"]
    }
    # Hydrated candidates already have structured rows. Existing candidate
    # identity wins so a historical candidate is not reclassified as a seed
    # duplicate during this index-only rebuild.
    preexisting_structured_ids = structured_post_ids - candidate_ids

    discovery_artifacts: dict[tuple[str, str], list[RawArtifactMetadata]] = {}
    for artifact in artifacts.values():
        has_discovery_marker = bool(
            artifact.artifact_kind == "discovery"
            or artifact.lane_type in {"dynamic_search", "subreddit_feed"}
            or artifact.parser_kind in _TIKHUB_DISCOVERY_PARSER_KINDS
            or artifact.source_method
            in {"tikhub_dynamic_search", "tikhub_subreddit_feed"}
        )
        if not has_discovery_marker:
            continue
        matches = lane_by_hash.get(
            (artifact.lane_type, artifact.lane_key_hash), []
        )
        if (
            artifact.artifact_kind != "discovery"
            or artifact.lane_type not in {"dynamic_search", "subreddit_feed"}
            or artifact.parser_kind not in _TIKHUB_DISCOVERY_PARSER_KINDS
            or len(matches) != 1
        ):
            raise _DiscoveryReindexDataError(
                "strict_discovery_artifact_invalid"
            )
        discovery_artifacts.setdefault(
            (artifact.lane_type, matches[0]), []
        ).append(artifact)

    occurrences: list[tuple[object, ...]] = []
    candidate_first: dict[str, tuple[object, ...]] = {}
    lane_discovered = {lane: 0 for lane in configured_lanes}
    lane_unique = {lane: 0 for lane in configured_lanes}
    prepared_pages: dict[
        str,
        tuple[tuple[str, str], int, RawArtifactMetadata, list[object]],
    ] = {}
    artifact_ids: set[str] = set()
    recovered_lanes: set[tuple[str, str]] = set()
    artifact_response_cursors: dict[str, str | None] = {}
    checkpoint_updates: dict[tuple[str, str], dict[str, object]] = {}
    wrapper_counts: Counter[str] = Counter()
    for lane in configured_lanes:
        lane_artifacts = discovery_artifacts.get(lane, [])
        checkpoint = checkpoints.get(lane)
        if checkpoint is None:
            raise _DiscoveryReindexDataError("strict_discovery_checkpoint_missing")
        lane_artifacts.sort(key=lambda artifact: int(artifact.page_number or 0))
        checkpoint_page = int(checkpoint["page_number"])
        page_numbers_valid = [
            artifact.page_number for artifact in lane_artifacts
        ] == list(range(1, len(lane_artifacts) + 1))
        expected_endpoint = (
            FETCH_DYNAMIC_SEARCH
            if lane[0] == "dynamic_search"
            else FETCH_SUBREDDIT_FEED
        )
        recoverable_extra_page = bool(
            allow_schema_drift_recovery
            and page_numbers_valid
            and len(lane_artifacts) == checkpoint_page + 1
            and checkpoint.get("status") == "partial"
            and checkpoint.get("stop_reason") == "schema_drift"
            and checkpoint.get("last_error") == "TikHubSchemaDrift"
        )
        if recoverable_extra_page and not _schema_drift_recovery_attempt_is_valid(
            checkpoint=checkpoint,
            attempts=rows["backfill_provider_attempts"],
            manifest_provider_request_count=manifest.get("provider_request_count"),
            expected_endpoint=expected_endpoint,
        ):
            raise _DiscoveryReindexDataError(
                "strict_discovery_provider_attempt_invalid"
            )
        if not page_numbers_valid or not (
            checkpoint_page == len(lane_artifacts) or recoverable_extra_page
        ):
            raise _DiscoveryReindexDataError("strict_discovery_page_chain_invalid")
        if recoverable_extra_page:
            recovered_lanes.add(lane)

        previous_cursor: str | None = None
        lane_times: list[datetime] = []
        recovered_contract: CursorContract | None = None
        recovered_artifact: RawArtifactMetadata | None = None
        for artifact in lane_artifacts:
            page_number = int(artifact.page_number or 0)
            endpoint = expected_endpoint
            source_method = f"tikhub_{lane[0]}"
            expected_url = _replay_tikhub_source_url(
                run_id=run_id,
                lane_type=lane[0],
                lane_key=lane[1],
                endpoint=endpoint,
                page_number=page_number,
                request_cursor=previous_cursor,
            )
            if (
                artifact.source_method != source_method
                or artifact.source_endpoint != endpoint
                or artifact.request_cursor != previous_cursor
                or artifact.source_url != expected_url
                or artifact.identity_hash
                != sha256(expected_url.removeprefix("tikhub://").encode()).hexdigest()
            ):
                raise _DiscoveryReindexDataError(
                    "strict_discovery_artifact_invalid"
                )
            payload = _decode_reindex_json(payloads[artifact.artifact_id])
            try:
                is_uncommitted_recovery_page = bool(
                    recoverable_extra_page and page_number == len(lane_artifacts)
                )
                if is_uncommitted_recovery_page:
                    if checkpoint.get("cursor") != previous_cursor:
                        raise _ReplayDataError("discovery_checkpoint_mismatch")
                    if artifact.response_cursor is not None:
                        raise _ReplayDataError("discovery_checkpoint_mismatch")
                    if artifact.source_method == "tikhub_subreddit_feed":
                        recovered_contract = CursorContract(
                            cursor_path=STRICT_SUBREDDIT_V3_CURSOR_PATH,
                            schema_sha256=STRICT_SUBREDDIT_V3_CURSOR_SCHEMA_SHA256,
                        )
                        if _is_strict_subreddit_v3_terminal_empty(payload):
                            next_cursor = None
                        else:
                            next_cursor = _cursor_from_recovery_contract(
                                payload, recovered_contract
                            )
                    else:
                        recovered_contract = _recovery_cursor_contract(payload)
                        next_cursor = _cursor_from_recovery_contract(
                            payload, recovered_contract
                        )
                    recovered_artifact = artifact
                    artifact_response_cursors[artifact.artifact_id] = next_cursor
                else:
                    next_cursor = _cursor_from_checkpoint(
                        payload,
                        checkpoint,
                        allow_subreddit_terminal_empty=(
                            artifact.source_method == "tikhub_subreddit_feed"
                        ),
                    )
            except _ReplayDataError:
                raise _DiscoveryReindexDataError(
                    "strict_discovery_cursor_invalid"
                ) from None
            if not is_uncommitted_recovery_page and artifact.response_cursor != next_cursor:
                raise _DiscoveryReindexDataError(
                    "strict_discovery_page_chain_invalid"
                )
            try:
                post_records = _extract_backfill_discovery_post_records(
                    payload, artifact.source_method, lane_key=lane[1]
                )
            except TikHubDiscoveryShapeError:
                raise _DiscoveryReindexDataError(
                    "strict_discovery_schema_unknown"
                ) from None
            posts = [post for _typename, post in post_records]
            lane_times.extend(
                post.created_at_utc
                for post in posts
                if post.created_at_utc is not None
            )
            wrapper_counts.update(
                typename for typename, _post in post_records
            )

            artifact_ids.add(artifact.artifact_id)
            prepared_pages[artifact.artifact_id] = (
                lane,
                page_number,
                artifact,
                list(posts),
            )
            previous_cursor = next_cursor

        if recoverable_extra_page:
            if recovered_contract is None or recovered_artifact is None:
                raise _DiscoveryReindexDataError(
                    "strict_discovery_page_chain_invalid"
                )
            prior_times = [
                value
                for value in (
                    _replay_timestamp(checkpoint.get("newest_seen_utc")),
                    _replay_timestamp(checkpoint.get("oldest_seen_utc")),
                )
                if value is not None
            ]
            all_times = [*prior_times, *lane_times]
            newest_seen = max(all_times).isoformat() if all_times else None
            oldest_seen = min(all_times).isoformat() if all_times else None
            page_times = [
                post.created_at_utc
                for post in prepared_pages[recovered_artifact.artifact_id][3]
                if post.created_at_utc is not None
            ]
            consecutive_old_pages = (
                int(checkpoint.get("consecutive_old_pages") or 0) + 1
                if page_times and max(page_times) < window_start
                else 0
            )
            if previous_cursor is None:
                recovered_status = "complete"
                recovered_stop_reason = "cursor_exhausted"
            elif consecutive_old_pages >= 2:
                recovered_status = "complete"
                recovered_stop_reason = "older_than_window"
            else:
                recovered_status = "partial"
                recovered_stop_reason = "round_robin_yield"
            checkpoint_updates[lane] = {
                "cursor": previous_cursor,
                "previous_cursor": recovered_artifact.request_cursor,
                "page_number": len(lane_artifacts),
                "newest_seen_utc": newest_seen,
                "oldest_seen_utc": oldest_seen,
                "provider_request_count": manifest["provider_request_count"],
                "last_success_utc": recovered_artifact.captured_at_utc,
                "last_error": None,
                "status": recovered_status,
                "stop_reason": recovered_stop_reason,
                "cursor_json_path": json.dumps(
                    list(recovered_contract.cursor_path),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "cursor_schema_sha256": recovered_contract.schema_sha256,
                "consecutive_old_pages": consecutive_old_pages,
            }

    try:
        ordered_artifact_ids = _ordered_discovery_artifact_ids(
            discovery_artifacts
        )
    except ValueError:
        raise _DiscoveryReindexDataError(
            "strict_discovery_capture_order_invalid"
        ) from None

    seen_candidates: set[str] = set()
    for artifact_id in ordered_artifact_ids:
        lane, page_number, artifact, posts = prepared_pages[artifact_id]
        for ordinal, post in enumerate(posts):
            try:
                (
                    base_disposition,
                    post_id,
                    source_url,
                    created_at,
                ) = discovery_occurrence_contract(
                    post_id=post.post_id,
                    source_url=post.source_url,
                    title=post.title,
                    created_at_utc=post.created_at_utc,
                    window_start_utc=window_start,
                    window_end_utc=effective_end,
                )
            except AttributeError:
                raise _DiscoveryReindexDataError(
                    "strict_discovery_invalid_occurrence"
                ) from None
            if base_disposition == "invalid":
                raise _DiscoveryReindexDataError(
                    "strict_discovery_invalid_occurrence"
                )
            if base_disposition == "outside_window":
                disposition = "outside_window"
            else:
                if post_id is None:
                    raise _DiscoveryReindexDataError(
                        "strict_discovery_invalid_occurrence"
                    )
                if post_id in seen_candidates:
                    disposition = "duplicate_occurrence"
                elif post_id in preexisting_structured_ids:
                    disposition = "duplicate_existing_structured"
                else:
                    disposition = "new_candidate"
                    seen_candidates.add(post_id)
                    lane_unique[lane] += 1
                    candidate_first[post_id] = (
                        lane[0],
                        lane[1],
                        artifact.captured_at_utc,
                        source_url,
                        None if created_at is None else created_at.isoformat(),
                        artifact.artifact_id,
                    )
            occurrences.append(
                (
                    run_id,
                    lane[0],
                    lane[1],
                    page_number,
                    ordinal,
                    post_id,
                    source_url,
                    None if created_at is None else created_at.isoformat(),
                    artifact.artifact_id,
                    artifact.captured_at_utc,
                    disposition,
                )
            )
            lane_discovered[lane] += 1

    checkpoint_counts = {
        lane: (lane_discovered[lane], lane_unique[lane])
        for lane in configured_lanes
    }

    configured_set = set(configured_lanes)
    artifact_lanes = set(discovery_artifacts)
    checkpoint_lanes = {
        (str(row["lane_type"]), str(row["lane_key"]))
        for row in rows["backfill_checkpoints"]
        if row["lane_type"] in {"dynamic_search", "subreddit_feed"}
    }
    if artifact_lanes - configured_set or checkpoint_lanes != configured_set:
        raise _DiscoveryReindexDataError("strict_discovery_lane_mismatch")
    planned_candidate_ids = set(candidate_first)
    if allow_schema_drift_recovery:
        if not candidate_ids.issubset(seen_candidates):
            raise _DiscoveryReindexDataError("strict_candidate_set_mismatch")
    elif seen_candidates != candidate_ids:
        raise _DiscoveryReindexDataError("strict_candidate_set_mismatch")
    if not candidate_ids.issubset(planned_candidate_ids):
        raise _DiscoveryReindexDataError("strict_candidate_set_mismatch")
    for post_id in candidate_ids:
        first = candidate_first[post_id]
        source_candidate = candidate_rows[post_id]
        if first != (
            source_candidate["first_lane_type"],
            source_candidate["first_lane_key"],
            source_candidate["first_discovered_at_utc"],
            source_candidate["source_url"],
            source_candidate["post_created_at_utc"],
            source_candidate["raw_artifact_id"],
        ):
            raise _DiscoveryReindexDataError(
                "strict_candidate_first_mismatch"
            )
    return {
        "artifact_ids": artifact_ids,
        "occurrences": occurrences,
        "candidate_first": candidate_first,
        "source_candidate_ids": candidate_ids,
        "new_candidate_ids": planned_candidate_ids - candidate_ids,
        "checkpoint_counts": checkpoint_counts,
        "checkpoint_updates": checkpoint_updates,
        "recovered_lanes": recovered_lanes,
        "artifact_response_cursors": artifact_response_cursors,
        "wrapper_counts": dict(sorted(wrapper_counts.items())),
    }


def _apply_strict_discovery_reindex(
    staging_db: Path,
    *,
    run_id: str,
    plan: dict[str, object],
    allow_schema_drift_recovery: bool = False,
) -> None:
    if type(allow_schema_drift_recovery) is not bool:
        raise ValueError("allow_schema_drift_recovery must be a bool")
    artifact_ids: set[str] = plan["artifact_ids"]
    occurrences: list[tuple[object, ...]] = plan["occurrences"]
    candidate_first: dict[str, tuple[object, ...]] = plan["candidate_first"]
    new_candidate_ids: set[str] = plan.get("new_candidate_ids", set())
    checkpoint_counts: dict[tuple[str, str], tuple[int, int]] = plan[
        "checkpoint_counts"
    ]
    checkpoint_updates: dict[tuple[str, str], dict[str, object]] = plan.get(
        "checkpoint_updates", {}
    )
    recovered_lanes: set[tuple[str, str]] = plan.get("recovered_lanes", set())
    artifact_response_cursors: dict[str, str | None] = plan.get(
        "artifact_response_cursors", {}
    )
    if not allow_schema_drift_recovery and (
        new_candidate_ids
        or checkpoint_updates
        or recovered_lanes
        or artifact_response_cursors
    ):
        raise _DiscoveryReindexDataError("strict_discovery_recovery_not_allowed")
    if (
        set(checkpoint_updates) != recovered_lanes
        or not set(artifact_response_cursors).issubset(artifact_ids)
        or not new_candidate_ids.issubset(candidate_first)
    ):
        raise _DiscoveryReindexDataError("strict_discovery_recovery_plan_invalid")
    connection = sqlite3.connect(staging_db, timeout=5.0)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        protected_before = _discovery_reindex_protected_snapshot(
            connection,
            run_id=run_id,
            artifact_ids=artifact_ids,
            allowed_new_candidate_ids=new_candidate_ids,
            recovered_lanes=recovered_lanes,
            recovered_artifact_ids=set(artifact_response_cursors),
        )
        connection.execute(
            "DELETE FROM backfill_discovery_occurrences WHERE run_id=?",
            (run_id,),
        )
        connection.executemany(
            """
            INSERT INTO backfill_discovery_occurrences(
                run_id, lane_type, lane_key, page_number, ordinal,
                post_id, source_url, post_created_at_utc, raw_artifact_id,
                discovered_at_utc, disposition
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            occurrences,
        )
        for post_id, first in candidate_first.items():
            if post_id in new_candidate_ids:
                cursor = connection.execute(
                    """
                    INSERT INTO backfill_candidates(
                        run_id, post_id, first_lane_type, first_lane_key,
                        first_discovered_at_utc, source_url,
                        post_created_at_utc, raw_artifact_id, status,
                        status_reason, updated_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL, ?)
                    """,
                    (run_id, post_id, *first, first[2]),
                )
            else:
                cursor = connection.execute(
                    """
                    UPDATE backfill_candidates
                    SET first_lane_type=?, first_lane_key=?,
                        first_discovered_at_utc=?, source_url=?,
                        post_created_at_utc=?, raw_artifact_id=?
                    WHERE run_id=? AND post_id=?
                    """,
                    (*first, run_id, post_id),
                )
            if cursor.rowcount != 1:
                raise _DiscoveryReindexDataError(
                    "strict_candidate_set_mismatch"
                )
        for (lane_type, lane_key), counts in checkpoint_counts.items():
            update = checkpoint_updates.get((lane_type, lane_key))
            if update is None:
                cursor = connection.execute(
                    """
                    UPDATE backfill_checkpoints
                    SET discovered_count=?, unique_count=?
                    WHERE run_id=? AND lane_type=? AND lane_key=?
                    """,
                    (*counts, run_id, lane_type, lane_key),
                )
            else:
                cursor = connection.execute(
                    """
                    UPDATE backfill_checkpoints SET
                        cursor=?, previous_cursor=?, page_number=?,
                        newest_seen_utc=?, oldest_seen_utc=?,
                        discovered_count=?, unique_count=?,
                        provider_request_count=?, last_success_utc=?,
                        last_error=?, status=?, stop_reason=?,
                        cursor_json_path=?, cursor_schema_sha256=?,
                        consecutive_old_pages=?
                    WHERE run_id=? AND lane_type=? AND lane_key=?
                    """,
                    (
                        update["cursor"],
                        update["previous_cursor"],
                        update["page_number"],
                        update["newest_seen_utc"],
                        update["oldest_seen_utc"],
                        *counts,
                        update["provider_request_count"],
                        update["last_success_utc"],
                        update["last_error"],
                        update["status"],
                        update["stop_reason"],
                        update["cursor_json_path"],
                        update["cursor_schema_sha256"],
                        update["consecutive_old_pages"],
                        run_id,
                        lane_type,
                        lane_key,
                    ),
                )
            if cursor.rowcount != 1:
                raise _DiscoveryReindexDataError(
                    "strict_discovery_checkpoint_missing"
                )
        for artifact_id in artifact_ids:
            cursor = connection.execute(
                """
                UPDATE backfill_raw_artifacts
                SET parser_kind=?
                WHERE run_id=? AND artifact_id=?
                  AND parser_kind IN (?, ?)
                """,
                (
                    _TIKHUB_DISCOVERY_STRICT_PARSER_KIND,
                    run_id,
                    artifact_id,
                    _TIKHUB_DISCOVERY_LEGACY_PARSER_KIND,
                    _TIKHUB_DISCOVERY_STRICT_PARSER_KIND,
                ),
            )
            if cursor.rowcount != 1:
                raise _DiscoveryReindexDataError(
                    "strict_discovery_artifact_invalid"
                )
        for artifact_id, response_cursor in artifact_response_cursors.items():
            cursor = connection.execute(
                """
                UPDATE backfill_raw_artifacts
                SET response_cursor=?
                WHERE run_id=? AND artifact_id=? AND response_cursor IS NULL
                """,
                (response_cursor, run_id, artifact_id),
            )
            if cursor.rowcount != 1:
                raise _DiscoveryReindexDataError(
                    "strict_discovery_page_chain_invalid"
                )

        actual_candidate_ids = {
            str(row[0])
            for row in connection.execute(
                "SELECT post_id FROM backfill_candidates WHERE run_id=?",
                (run_id,),
            ).fetchall()
        }
        if actual_candidate_ids != set(candidate_first):
            raise _DiscoveryReindexDataError("strict_candidate_set_mismatch")
        if connection.execute(
            "SELECT COUNT(*) FROM backfill_discovery_occurrences "
            "WHERE run_id=? AND disposition='invalid'",
            (run_id,),
        ).fetchone()[0]:
            raise _DiscoveryReindexDataError(
                "strict_discovery_invalid_occurrence"
            )
        protected_after = _discovery_reindex_protected_snapshot(
            connection,
            run_id=run_id,
            artifact_ids=artifact_ids,
            allowed_new_candidate_ids=new_candidate_ids,
            recovered_lanes=recovered_lanes,
            recovered_artifact_ids=set(artifact_response_cursors),
        )
        if protected_after != protected_before:
            raise _DiscoveryReindexDataError("reindex_protected_state_changed")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise _DiscoveryReindexDataError("reindex_foreign_key_failed")
        if [str(row[0]) for row in connection.execute("PRAGMA integrity_check")] != [
            "ok"
        ]:
            raise _DiscoveryReindexDataError("reindex_integrity_failed")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _discovery_reindex_protected_snapshot(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    artifact_ids: set[str],
    allowed_new_candidate_ids: set[str] | frozenset[str] = frozenset(),
    recovered_lanes: set[tuple[str, str]] | frozenset[tuple[str, str]] = frozenset(),
    recovered_artifact_ids: set[str] | frozenset[str] = frozenset(),
) -> str:
    payload: dict[str, list[dict[str, object]]] = {}
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    for table in (*_REQUIRED_TABLES, *_REINDEX_ADDITIVE_TABLES):
        if table not in tables:
            raise _DiscoveryReindexDataError("reindex_schema_incomplete")
        if table == "backfill_discovery_occurrences":
            continue
        rows = [
            dict(row)
            for row in connection.execute(
                f"SELECT * FROM {table} WHERE run_id=?", (run_id,)
            ).fetchall()
        ]
        if table == "backfill_candidates":
            rows = [
                {
                    key: row[key]
                    for key in (
                        "run_id",
                        "post_id",
                        "status",
                        "status_reason",
                        "updated_at_utc",
                    )
                }
                for row in rows
                if row["post_id"] not in allowed_new_candidate_ids
            ]
        elif table == "backfill_checkpoints":
            for row in rows:
                if row["lane_type"] in {"dynamic_search", "subreddit_feed"}:
                    row["discovered_count"] = "strict_reindex_allowed"
                    row["unique_count"] = "strict_reindex_allowed"
                if (row["lane_type"], row["lane_key"]) in recovered_lanes:
                    for key in (
                        "cursor",
                        "previous_cursor",
                        "page_number",
                        "newest_seen_utc",
                        "oldest_seen_utc",
                        "provider_request_count",
                        "last_success_utc",
                        "last_error",
                        "status",
                        "stop_reason",
                        "cursor_json_path",
                        "cursor_schema_sha256",
                        "consecutive_old_pages",
                    ):
                        row[key] = "strict_recovery_allowed"
        elif table == "backfill_raw_artifacts":
            for row in rows:
                if row["artifact_id"] in artifact_ids:
                    row["parser_kind"] = "strict_reindex_allowed"
                if row["artifact_id"] in recovered_artifact_ids:
                    row["response_cursor"] = "strict_recovery_allowed"
        payload[table] = rows
    return _canonical_sha(payload, sort_keys=True)


def _decode_reindex_json(payload: bytes) -> object:
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _DiscoveryReindexDataError("strict_discovery_json_invalid") from None


def _reset_schema_drift_hydration_state(
    staging_db: Path,
    *,
    run_id: str,
    expected_failed_candidate_ids: set[str],
    recovered_at_utc: datetime,
) -> dict[str, int]:
    """Reset only the broad Task 23 comments-schema-drift failure footprint."""
    if not isinstance(staging_db, Path):
        raise ValueError("staging_db must be a Path")
    if type(run_id) is not str or not run_id.strip():
        raise ValueError("run_id must be a non-empty string")
    if (
        type(expected_failed_candidate_ids) is not set
        or not expected_failed_candidate_ids
        or any(type(post_id) is not str or not post_id for post_id in expected_failed_candidate_ids)
    ):
        raise ValueError("expected_failed_candidate_ids must be a non-empty string set")
    if (
        not isinstance(recovered_at_utc, datetime)
        or recovered_at_utc.tzinfo is None
        or recovered_at_utc.utcoffset() is None
    ):
        raise ValueError("recovered_at_utc must be timezone-aware")

    connection = sqlite3.connect(staging_db, timeout=5.0)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        manifest = connection.execute(
            "SELECT status, provider_request_count, live_send "
            "FROM backfill_manifests WHERE run_id=?",
            (run_id,),
        ).fetchone()
        run = connection.execute(
            "SELECT status, live_send FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if (
            manifest is None
            or run is None
            or manifest["status"] != "partial"
            or run["status"] != "partial"
            or manifest["live_send"] != 0
            or run["live_send"] != 0
        ):
            raise _DiscoveryReindexDataError(
                "schema_drift_recovery_state_invalid"
            )

        placeholders = ",".join("?" for _ in expected_failed_candidate_ids)
        ordered_ids = tuple(sorted(expected_failed_candidate_ids))
        candidate_rows = connection.execute(
            "SELECT post_id, status, status_reason "
            f"FROM backfill_candidates WHERE run_id=? AND post_id IN ({placeholders})",
            (run_id, *ordered_ids),
        ).fetchall()
        if (
            {str(row["post_id"]) for row in candidate_rows}
            != expected_failed_candidate_ids
            or any(
                row["status"] != "failed"
                or row["status_reason"] != "comments_schema_drift"
                for row in candidate_rows
            )
        ):
            raise _DiscoveryReindexDataError(
                "schema_drift_recovery_candidate_mismatch"
            )
        all_matching_failures = {
            str(row[0])
            for row in connection.execute(
                "SELECT post_id FROM backfill_candidates "
                "WHERE run_id=? AND (status='failed' "
                "OR status_reason='comments_schema_drift')",
                (run_id,),
            ).fetchall()
        }
        if all_matching_failures != expected_failed_candidate_ids:
            raise _DiscoveryReindexDataError(
                "schema_drift_recovery_candidate_mismatch"
            )

        batch_rows = connection.execute(
            "SELECT DISTINCT b.batch_id, b.status, b.artifact_id, "
            "b.stop_reason, b.batch_number "
            "FROM backfill_detail_batches AS b "
            "JOIN backfill_detail_batch_members AS m "
            "ON m.run_id=b.run_id AND m.batch_id=b.batch_id "
            f"WHERE b.run_id=? AND m.post_id IN ({placeholders}) "
            "ORDER BY b.batch_number",
            (run_id, *ordered_ids),
        ).fetchall()
        if not batch_rows:
            raise _DiscoveryReindexDataError(
                "schema_drift_recovery_batch_mismatch"
            )
        affected_batch_ids = tuple(
            str(row["batch_id"]) for row in batch_rows
        )
        batch_placeholders = ",".join("?" for _ in affected_batch_ids)
        member_rows = connection.execute(
            "SELECT m.batch_id, m.post_id, c.status, c.status_reason "
            "FROM backfill_detail_batch_members AS m "
            "JOIN backfill_candidates AS c "
            "ON c.run_id=m.run_id AND c.post_id=m.post_id "
            f"WHERE m.run_id=? AND m.batch_id IN ({batch_placeholders}) "
            "ORDER BY m.batch_id, m.ordinal",
            (run_id, *affected_batch_ids),
        ).fetchall()
        if (
            not expected_failed_candidate_ids.issubset(
                {str(row["post_id"]) for row in member_rows}
            )
            or any(
                not (
                    row["status"] == "complete"
                    and row["stop_reason"] is None
                )
                and not (
                    row["status"] == "failed"
                    and row["stop_reason"] == "comments_schema_drift"
                )
                for row in batch_rows
            )
            or {str(row["batch_id"]) for row in member_rows}
            != {str(row["batch_id"]) for row in batch_rows}
            or any(
                str(row["post_id"]) not in expected_failed_candidate_ids
                and row["status"] not in {"hydrated", "excluded"}
                for row in member_rows
            )
        ):
            raise _DiscoveryReindexDataError(
                "schema_drift_recovery_batch_mismatch"
            )

        raw_persisted_batch_count = 0
        for batch in batch_rows:
            artifact_id = batch["artifact_id"]
            if artifact_id is None:
                continue
            artifact = connection.execute(
                "SELECT artifact_kind, lane_type, parser_kind, source_method "
                "FROM backfill_raw_artifacts WHERE run_id=? AND artifact_id=?",
                (run_id, artifact_id),
            ).fetchone()
            if artifact is None or tuple(artifact) != (
                "detail",
                "detail_batch",
                "tikhub_detail",
                "tikhub_detail",
            ):
                raise _DiscoveryReindexDataError(
                    "schema_drift_recovery_batch_mismatch"
                )
            raw_persisted_batch_count += 1

        ordered_lane_hashes = tuple(
            sha256(post_id.encode()).hexdigest() for post_id in ordered_ids
        )
        lane_hash_placeholders = ",".join("?" for _ in ordered_lane_hashes)
        comment_artifacts = connection.execute(
            "SELECT artifact_id, lane_key_hash, page_number, request_cursor, "
            "response_cursor FROM backfill_raw_artifacts "
            "WHERE run_id=? AND lane_type='comments' "
            f"AND lane_key_hash IN ({lane_hash_placeholders}) "
            "ORDER BY page_number, artifact_id",
            (run_id, *ordered_lane_hashes),
        ).fetchall()
        comment_checkpoints = connection.execute(
            "SELECT lane_key, cursor, previous_cursor, page_number, "
            "discovered_count, unique_count, last_success_utc, last_error, "
            "status, stop_reason, cursor_json_path, cursor_schema_sha256 "
            "FROM backfill_checkpoints WHERE run_id=? AND lane_type='comments' "
            f"AND lane_key IN ({placeholders})",
            (run_id, *ordered_ids),
        ).fetchall()
        checkpoint_by_hash: dict[str, list[sqlite3.Row]] = {}
        for checkpoint in comment_checkpoints:
            checkpoint_by_hash.setdefault(
                sha256(str(checkpoint["lane_key"]).encode()).hexdigest(), []
            ).append(checkpoint)
        if (
            len(comment_artifacts) != len(expected_failed_candidate_ids)
            or len(comment_checkpoints) != len(expected_failed_candidate_ids)
            or {str(row["lane_key"]) for row in comment_checkpoints}
            != expected_failed_candidate_ids
        ):
            raise _DiscoveryReindexDataError(
                "schema_drift_recovery_comment_mismatch"
            )
        for artifact in comment_artifacts:
            matches = checkpoint_by_hash.get(str(artifact["lane_key_hash"]), [])
            if (
                len(matches) != 1
                or str(matches[0]["lane_key"]) not in expected_failed_candidate_ids
                or artifact["page_number"] != 1
                or artifact["request_cursor"] is not None
                or artifact["response_cursor"] is not None
            ):
                raise _DiscoveryReindexDataError(
                    "schema_drift_recovery_comment_mismatch"
                )
            checkpoint = matches[0]
            if (
                checkpoint["cursor"] is not None
                or checkpoint["previous_cursor"] is not None
                or checkpoint["page_number"] != 0
                or checkpoint["discovered_count"] != 0
                or checkpoint["unique_count"] != 0
                or checkpoint["last_success_utc"] is not None
                or checkpoint["last_error"] != "TikHubSchemaDrift"
                or checkpoint["status"] != "partial"
                or checkpoint["stop_reason"] != "comments_schema_drift"
                or type(checkpoint["cursor_json_path"]) is not str
                or type(checkpoint["cursor_schema_sha256"]) is not str
            ):
                raise _DiscoveryReindexDataError(
                    "schema_drift_recovery_comment_mismatch"
                )

        if connection.execute(
            "SELECT 1 FROM reddit_threads "
            f"WHERE run_id=? AND post_id IN ({placeholders}) LIMIT 1",
            (run_id, *ordered_ids),
        ).fetchone() is not None or connection.execute(
            "SELECT 1 FROM reddit_comments "
            f"WHERE run_id=? AND post_id IN ({placeholders}) LIMIT 1",
            (run_id, *ordered_ids),
        ).fetchone() is not None:
            raise _DiscoveryReindexDataError(
                "schema_drift_recovery_structured_state_present"
            )

        recovered_text = recovered_at_utc.isoformat()
        candidate_cursor = connection.execute(
            "UPDATE backfill_candidates SET status='pending', "
            "status_reason=NULL, updated_at_utc=? "
            f"WHERE run_id=? AND post_id IN ({placeholders}) "
            "AND status='failed' AND status_reason='comments_schema_drift'",
            (recovered_text, run_id, *ordered_ids),
        )
        for batch in batch_rows:
            target_status = (
                "raw_persisted" if batch["artifact_id"] is not None else "prepared"
            )
            cursor = connection.execute(
                "UPDATE backfill_detail_batches SET status=?, stop_reason=NULL, "
                "updated_at_utc=? WHERE run_id=? AND batch_id=? "
                "AND status=? AND stop_reason IS ?",
                (
                    target_status,
                    recovered_text,
                    run_id,
                    batch["batch_id"],
                    batch["status"],
                    batch["stop_reason"],
                ),
            )
            if cursor.rowcount != 1:
                raise _DiscoveryReindexDataError(
                    "schema_drift_recovery_batch_mismatch"
                )
        checkpoint_cursor = connection.execute(
            "UPDATE backfill_checkpoints SET status='prepared', "
            "stop_reason=NULL, last_error=NULL "
            "WHERE run_id=? AND lane_type='comments' "
            "AND status='partial' AND stop_reason='comments_schema_drift' "
            f"AND lane_key IN ({placeholders})",
            (run_id, *ordered_ids),
        )
        if (
            candidate_cursor.rowcount != len(expected_failed_candidate_ids)
            or checkpoint_cursor.rowcount != len(expected_failed_candidate_ids)
            or connection.execute("PRAGMA foreign_key_check").fetchone() is not None
            or [
                str(row[0])
                for row in connection.execute("PRAGMA integrity_check").fetchall()
            ]
            != ["ok"]
        ):
            raise _DiscoveryReindexDataError(
                "schema_drift_recovery_write_invalid"
            )
        connection.commit()
        return {
            "reset_candidate_count": len(expected_failed_candidate_ids),
            "reset_batch_count": len(batch_rows),
            "reset_comment_checkpoint_count": len(comment_checkpoints),
            "raw_persisted_batch_count": raw_persisted_batch_count,
            "prepared_batch_count": len(batch_rows) - raw_persisted_batch_count,
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _reindex_regular_file_sha256(path: Path) -> str:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise _ReplayOperationalBoundaryError
        digest = sha256()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(descriptor)
        if (
            (before.st_dev, before.st_ino, before.st_size)
            != (after.st_dev, after.st_ino, after.st_size)
        ):
            raise _ReplayOperationalBoundaryError
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _reindex_archive_inventory_sha256(root: Path) -> str:
    inventory: list[list[str]] = []
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError:
            raise _ReplayOperationalBoundaryError from None
        for entry in entries:
            try:
                if entry.is_symlink():
                    raise _ReplayOperationalBoundaryError
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    raise _ReplayOperationalBoundaryError
                path = Path(entry.path)
                relative = path.relative_to(root).as_posix()
                inventory.append([relative, _reindex_regular_file_sha256(path)])
            except OSError:
                raise _ReplayOperationalBoundaryError from None
    return _canonical_sha(sorted(inventory), sort_keys=True)


def _reindex_provider_evidence(path: Path, *, run_id: str) -> dict[str, object]:
    connection = sqlite3.connect(
        f"{path.resolve(strict=True).as_uri()}?mode=ro&immutable=1",
        uri=True,
        timeout=5.0,
    )
    connection.row_factory = sqlite3.Row
    try:
        return _reindex_provider_evidence_from_connection(
            connection, run_id=run_id
        )
    finally:
        connection.close()


def _reindex_provider_evidence_from_connection(
    connection: sqlite3.Connection, *, run_id: str
) -> dict[str, object]:
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        manifest = connection.execute(
            "SELECT max_provider_requests, provider_request_count "
            "FROM backfill_manifests WHERE run_id=?",
            (run_id,),
        ).fetchall()
        if len(manifest) != 1:
            raise _DiscoveryReindexDataError("source_manifest_invalid")
        attempts = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM backfill_provider_attempts WHERE run_id=? "
                "ORDER BY request_number",
                (run_id,),
            ).fetchall()
        ]
        return {
            "max_provider_requests": int(manifest[0]["max_provider_requests"]),
            "provider_request_count": int(manifest[0]["provider_request_count"]),
            "ledger_sha256": _canonical_sha(attempts, sort_keys=True),
        }
    finally:
        connection.rollback()


def _discovery_reindex_names(staging_db: Path) -> tuple[Path, ...]:
    return tuple(
        Path(str(staging_db) + suffix)
        for suffix in ("", "-wal", "-shm", "-journal")
    )


def _assert_discovery_reindex_names_absent(staging_db: Path) -> None:
    try:
        if any(os.path.lexists(path) for path in _discovery_reindex_names(staging_db)):
            raise _ReplayOperationalBoundaryError
    except OSError:
        raise _ReplayOperationalBoundaryError from None


def _cleanup_discovery_reindex_staging(staging_db: Path) -> None:
    for path in _discovery_reindex_names(staging_db):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    try:
        parent_descriptor = os.open(
            staging_db.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW,
        )
    except OSError:
        raise _ReplayOperationalBoundaryError from None
    try:
        os.fsync(parent_descriptor)
    except OSError:
        raise _ReplayOperationalBoundaryError from None
    finally:
        os.close(parent_descriptor)
    _assert_discovery_reindex_names_absent(staging_db)


def _discovery_reindex_result(
    *,
    status: str,
    stop_reason: str,
    source_db_sha256: str,
    raw_inventory_sha256: str,
    source_provider: dict[str, object],
    target_db_sha256: str | None = None,
    target_provider: dict[str, object] | None = None,
    discovery_artifact_count: int = 0,
    discovery_occurrence_count: int = 0,
    candidate_count: int = 0,
) -> dict[str, object]:
    return {
        "schema_version": "backfill_discovery_reindex_v1",
        "status": status,
        "stop_reason": stop_reason,
        "provider_attempt_made": False,
        "live_send": False,
        "source_db_sha256": source_db_sha256,
        "raw_inventory_sha256": raw_inventory_sha256,
        "target_db_sha256": target_db_sha256,
        "source_max_provider_requests": source_provider["max_provider_requests"],
        "source_provider_request_count": source_provider["provider_request_count"],
        "source_provider_ledger_sha256": source_provider["ledger_sha256"],
        "target_max_provider_requests": (
            None if target_provider is None else target_provider["max_provider_requests"]
        ),
        "target_provider_request_count": (
            None if target_provider is None else target_provider["provider_request_count"]
        ),
        "target_provider_ledger_sha256": (
            None if target_provider is None else target_provider["ledger_sha256"]
        ),
        "discovery_artifact_count": discovery_artifact_count,
        "discovery_occurrence_count": discovery_occurrence_count,
        "candidate_count": candidate_count,
    }


def _load_replay_snapshot(
    conn: sqlite3.Connection,
    *,
    archive: PrivateRawArchive,
    run_id: str,
) -> dict[str, object]:
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if any(table not in tables for table in _REQUIRED_TABLES):
        raise _ReplayDataError("source_schema_invalid")
    for table in _REQUIRED_TABLES:
        columns = {
            str(row["name"])
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if any(column not in columns for column in _REQUIRED_COLUMNS[table]):
            raise _ReplayDataError("source_schema_invalid")
    if [str(row[0]) for row in conn.execute("PRAGMA integrity_check")] != ["ok"]:
        raise _ReplayDataError("source_integrity_failed")
    if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise _ReplayDataError("source_integrity_failed")

    manifests = conn.execute(
        "SELECT * FROM backfill_manifests WHERE run_id=?", (run_id,)
    ).fetchall()
    runs = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchall()
    if len(manifests) != 1 or len(runs) != 1:
        raise _ReplayDataError("source_manifest_invalid")
    manifest = dict(manifests[0])
    run = dict(runs[0])
    if (
        manifest["run_id"] != run_id
        or run["run_id"] != run_id
        or manifest["status"] != run["status"]
        or manifest["window_start_utc"] != run["window_start_utc"]
        or manifest["effective_end_utc"] != run["window_end_utc"]
        or manifest["live_send"] != 0
        or run["live_send"] != 0
        or manifest["keyword_config_sha256"] != keyword_rules_sha256()
    ):
        raise _ReplayDataError("source_manifest_invalid")
    search_terms = _json_string_list(manifest["search_terms_json"])
    subreddits = _json_string_list(manifest["subreddits_json"])
    if search_terms is None or subreddits is None:
        raise _ReplayDataError("source_manifest_invalid")
    try:
        required_hash = required_lanes_sha256(
            search_terms=search_terms,
            subreddits=subreddits,
            include_subreddit_sweep=bool(manifest["include_subreddit_sweep"]),
        )
    except ValueError:
        raise _ReplayDataError("source_manifest_invalid") from None
    if manifest["required_lanes_sha256"] != required_hash:
        raise _ReplayDataError("source_manifest_invalid")
    if conn.execute(
        "SELECT COUNT(*) FROM delivery_previews WHERE run_id=?", (run_id,)
    ).fetchone()[0]:
        raise _ReplayDataError("live_send_boundary_violation")

    table_rows: dict[str, list[dict[str, object]]] = {}
    for table in (
        "backfill_seed_files",
        "backfill_raw_artifacts",
        "raw_captures",
        "reddit_threads",
        "reddit_comments",
        "analysis_results",
        "backfill_provider_attempts",
        "backfill_checkpoints",
        "backfill_candidates",
        "backfill_detail_batches",
        "backfill_detail_batch_members",
        "backfill_discovery_occurrences",
    ):
        table_rows[table] = [
            dict(row)
            for row in conn.execute(
                f"SELECT * FROM {table} WHERE run_id=?", (run_id,)
            ).fetchall()
        ]
    authorization_rows = _authorization_ledger_rows(conn, run_id=run_id)
    table_rows.update(authorization_rows)
    global_budget_boundaries, discovery_phase_boundaries = (
        _validated_budget_extension_boundaries(
            manifest,
            authorization_rows["backfill_budget_extensions"],
        )
    )
    _validate_hydration_resume_ledgers(
        run_id=run_id,
        extension_rows=authorization_rows["backfill_budget_extensions"],
        resume_rows=authorization_rows["backfill_hydration_resumes"],
        source_rows=table_rows,
    )
    _validate_collection_resume_ledgers(
        manifest=manifest,
        resume_rows=authorization_rows["backfill_collection_resumes"],
    )
    if not _source_provider_attempts_valid(
        manifest=manifest,
        run=run,
        attempts=table_rows["backfill_provider_attempts"],
    ):
        raise _ReplayDataError("source_provider_attempts_invalid")

    capture_rows = {
        str(row["raw_capture_id"]): row for row in table_rows["raw_captures"]
    }
    payloads: dict[str, bytes] = {}
    artifacts: dict[str, RawArtifactMetadata] = {}
    captures: dict[str, RawCapture] = {}
    tracked_paths: set[str] = set()
    allowed_parsers = {
        "seed_browser_thread",
        *_TIKHUB_DISCOVERY_PARSER_KINDS,
        "tikhub_detail",
        "tikhub_comments",
    }
    for row in table_rows["backfill_raw_artifacts"]:
        try:
            artifact = RawArtifactMetadata(**row)
        except (TypeError, ValueError):
            raise _ReplayDataError("archive_metadata_invalid") from None
        if (
            not _artifact_metadata_types_valid(artifact)
            or artifact.parser_kind not in allowed_parsers
        ):
            raise _ReplayDataError("archive_metadata_invalid")
        try:
            payload = archive.read_verified(artifact)
        except ArchiveIntegrityError:
            raise _ReplayDataError("archive_integrity_failed") from None
        capture_row = capture_rows.get(artifact.raw_capture_id)
        if not _capture_matches_artifact(capture_row, artifact):
            raise _ReplayDataError("archive_capture_mismatch")
        capture = _raw_capture_from_artifact(artifact)
        if _raw_capture_record(capture) != capture_row:
            raise _ReplayDataError("archive_capture_mismatch")
        artifacts[artifact.artifact_id] = artifact
        payloads[artifact.artifact_id] = payload
        captures[capture.raw_capture_id] = capture
        tracked_paths.add(artifact.relative_path)
    if set(capture_rows) != set(captures):
        raise _ReplayDataError("archive_capture_mismatch")
    try:
        inventory = _archive_json_gzip_files(archive.root, run_id)
    except ArchiveIntegrityError:
        raise _ReplayDataError("archive_integrity_failed") from None
    if inventory != tracked_paths:
        raise _ReplayDataError("archive_inventory_mismatch")
    return {
        "run_id": run_id,
        "manifest": manifest,
        "run": run,
        "search_terms": search_terms,
        "subreddits": subreddits,
        "rows": table_rows,
        "artifacts": artifacts,
        "payloads": payloads,
        "captures": captures,
        "global_budget_boundaries": global_budget_boundaries,
        "discovery_phase_boundaries": discovery_phase_boundaries,
    }


def _source_provider_attempts_valid(
    *,
    manifest: dict[str, object],
    run: dict[str, object],
    attempts: list[dict[str, object]],
) -> bool:
    request_count = manifest.get("provider_request_count")
    max_requests = manifest.get("max_provider_requests")
    if (
        type(request_count) is not int
        or type(max_requests) is not int
        or request_count < 0
        or max_requests < 0
        or request_count > max_requests
    ):
        return False

    request_numbers = [attempt.get("request_number") for attempt in attempts]
    if any(type(number) is not int for number in request_numbers):
        return False
    ordered_numbers = sorted(request_numbers)
    if (
        ordered_numbers != list(range(1, request_count + 1))
        or len(attempts) != request_count
        or max(ordered_numbers, default=0) != request_count
    ):
        return False

    for attempt in attempts:
        reserved_at = _replay_timestamp(attempt.get("reserved_at_utc"))
        sent_at = _replay_timestamp(attempt.get("sent_at_utc"))
        completed_at = _replay_timestamp(attempt.get("completed_at_utc"))
        status = attempt.get("status")
        error_class = attempt.get("error_class")
        http_status = attempt.get("http_status")
        if reserved_at is None or (
            http_status is not None and type(http_status) is not int
        ):
            return False
        if status == "succeeded":
            if sent_at is None or completed_at is None or error_class is not None:
                return False
        elif status == "failed":
            if (
                sent_at is None
                or completed_at is None
                or type(error_class) is not str
                or _ERROR_CLASS_PATTERN.fullmatch(error_class) is None
            ):
                return False
        else:
            # Replay snapshots must be terminal; in-flight attempts are not stable
            # operational evidence and cannot explain a completed reconstruction.
            return False

    sent_evidence = any(attempt.get("sent_at_utc") is not None for attempt in attempts)
    expected_flag = int(sent_evidence)
    return (
        manifest.get("provider_call") == expected_flag
        and run.get("provider_call") == expected_flag
    )


def _validate_replay_comment_lane_closure(snapshot: dict[str, object]) -> None:
    artifacts: dict[str, RawArtifactMetadata] = snapshot["artifacts"]
    rows: dict[str, list[dict[str, object]]] = snapshot["rows"]
    checkpoint_posts_by_hash: dict[str, list[str]] = {}
    for checkpoint in rows["backfill_checkpoints"]:
        if checkpoint["lane_type"] != "comments":
            continue
        post_id = str(checkpoint["lane_key"])
        checkpoint_posts_by_hash.setdefault(
            sha256(post_id.encode()).hexdigest(), []
        ).append(post_id)
    hydrated_posts_by_hash: dict[str, list[str]] = {}
    for candidate in rows["backfill_candidates"]:
        if candidate["status"] != "hydrated":
            continue
        post_id = str(candidate["post_id"])
        hydrated_posts_by_hash.setdefault(
            sha256(post_id.encode()).hexdigest(), []
        ).append(post_id)
    for artifact in artifacts.values():
        if not _artifact_has_comment_marker(artifact):
            continue
        checkpoint_posts = checkpoint_posts_by_hash.get(artifact.lane_key_hash, [])
        candidate_posts = hydrated_posts_by_hash.get(artifact.lane_key_hash, [])
        if (
            not _artifact_is_exact_comment_contract(artifact)
            or len(checkpoint_posts) != 1
            or len(candidate_posts) != 1
            or checkpoint_posts[0] != candidate_posts[0]
        ):
            raise _ReplayDataError("comment_chain_invalid")


def _replay_timestamp(value: object) -> datetime | None:
    if type(value) is not str or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _create_replay_manifest(
    target_store: BackfillStore, manifest: dict[str, object]
) -> None:
    target_store.create_manifest(
        BackfillManifest(
            run_id=str(manifest["run_id"]),
            status=manifest["status"],
            window_start_utc=str(manifest["window_start_utc"]),
            requested_end_utc=str(manifest["requested_end_utc"]),
            effective_end_utc=str(manifest["effective_end_utc"]),
            search_terms=tuple(json.loads(str(manifest["search_terms_json"]))),
            subreddits=tuple(json.loads(str(manifest["subreddits_json"]))),
            include_subreddit_sweep=bool(manifest["include_subreddit_sweep"]),
            required_lanes_sha256=str(manifest["required_lanes_sha256"]),
            keyword_config_sha256=str(manifest["keyword_config_sha256"]),
            max_provider_requests=int(manifest["max_provider_requests"]),
            provider_request_count=0,
            provider_call=False,
            live_send=False,
            created_at_utc=str(manifest["created_at_utc"]),
            updated_at_utc=str(manifest["updated_at_utc"]),
        )
    )


def _replay_verified_artifacts(
    target_store: BackfillStore, snapshot: dict[str, object]
) -> None:
    artifacts: dict[str, RawArtifactMetadata] = snapshot["artifacts"]
    captures: dict[str, RawCapture] = snapshot["captures"]
    for artifact_id in sorted(artifacts):
        artifact = artifacts[artifact_id]
        target_store.persist_raw_capture_artifact(
            captures[artifact.raw_capture_id], artifact
        )


def _replay_seed(target_store: BackfillStore, snapshot: dict[str, object]) -> None:
    rows: dict[str, list[dict[str, object]]] = snapshot["rows"]
    artifacts: dict[str, RawArtifactMetadata] = snapshot["artifacts"]
    payloads: dict[str, bytes] = snapshot["payloads"]
    run_id = str(snapshot["run_id"])
    manifest: dict[str, object] = snapshot["manifest"]
    window_start, effective_end = _manifest_window(manifest)
    if window_start is None or effective_end is None:
        raise _ReplayDataError("source_manifest_invalid")
    adapter = BrowserJsonAdapter()
    ledger_artifact_ids = [
        row.get("artifact_id") for row in rows["backfill_seed_files"]
    ]
    seed_artifact_ids = {
        artifact_id
        for artifact_id, artifact in artifacts.items()
        if (
            artifact.artifact_kind == "seed"
            or artifact.lane_type == "seed"
            or artifact.parser_kind == "seed_browser_thread"
            or artifact.source_method == "historical_seed"
            or artifact.source_endpoint == "seed_file"
        )
    }
    if (
        any(type(artifact_id) is not str for artifact_id in ledger_artifact_ids)
        or len(set(ledger_artifact_ids)) != len(ledger_artifact_ids)
        or set(ledger_artifact_ids) != seed_artifact_ids
    ):
        raise _ReplayDataError("seed_lineage_invalid")
    seed_rows = sorted(
        rows["backfill_seed_files"],
        key=lambda row: (row["outcome"] != "imported", str(row["input_path_hash"])),
    )
    seen_imported: set[str] = set()
    for ledger in seed_rows:
        artifact = artifacts.get(str(ledger["artifact_id"]))
        if artifact is None or not _seed_artifact_matches_ledger(artifact, ledger):
            raise _ReplayDataError("seed_lineage_invalid")
        payload = payloads[artifact.artifact_id]
        parsed = None
        parse_error: str | None = None
        try:
            parsed = adapter.parse_thread_payload(
                json.loads(payload.decode("utf-8")),
                run_id=run_id,
                raw_capture_id=artifact.raw_capture_id,
                source_url=artifact.source_url,
            )
        except Exception as exc:
            parse_error = type(exc).__name__

        outcome = str(ledger["outcome"])
        if parsed is None:
            if outcome != "parse_error" or ledger["error_class"] != parse_error:
                raise _ReplayDataError("seed_outcome_mismatch")
            post_id = None
        else:
            thread = parsed.thread
            comments = tuple(parsed.comments)
            combined = analyze_text(
                "\n".join(
                    (thread.title, thread.selftext, *(comment.body for comment in comments))
                )
            )
            if not window_start <= thread.created_at_utc < effective_end:
                derived_outcome = "outside_window"
            elif not combined.keyword_match.is_relevant:
                derived_outcome = "excluded"
            elif thread.post_id in seen_imported:
                derived_outcome = "duplicate"
            else:
                derived_outcome = "imported"
            if outcome != derived_outcome or ledger["post_id"] != thread.post_id:
                raise _ReplayDataError("seed_outcome_mismatch")
            post_id = thread.post_id
            if outcome == "imported":
                seen_imported.add(thread.post_id)
                thread = replace(
                    thread, matched_keywords=combined.keyword_match.matched_terms
                )
                analyses = _analysis_models_for_entities(
                    run_id=run_id, thread=thread, comments=comments
                )
                target_store.insert_entity_bundle(
                    captures=(),
                    threads=(thread,),
                    comments=comments,
                    analyses=analyses,
                )
        target_store.record_seed_file(
            run_id=run_id,
            input_path_hash=str(ledger["input_path_hash"]),
            payload_sha256=str(ledger["payload_sha256"]),
            outcome=outcome,
            artifact_id=str(ledger["artifact_id"]),
            post_id=post_id,
            error_class=ledger["error_class"],
            processed_at_utc=datetime.fromisoformat(str(ledger["processed_at_utc"])),
        )


def _is_replayable_zero_page_budget_checkpoint(
    row: dict[str, object],
    manifest: dict[str, object],
    run: dict[str, object],
    *,
    global_budget_boundaries: frozenset[int] = frozenset(),
    discovery_phase_boundaries: frozenset[int] = frozenset(),
) -> bool:
    zero_fields = (
        "page_number",
        "discovered_count",
        "unique_count",
        "consecutive_old_pages",
    )
    empty_fields = (
        "cursor",
        "previous_cursor",
        "newest_seen_utc",
        "oldest_seen_utc",
        "last_success_utc",
        "cursor_json_path",
        "cursor_schema_sha256",
    )
    request_count = row.get("provider_request_count")
    manifest_request_count = manifest.get("provider_request_count")
    max_provider_requests = manifest.get("max_provider_requests")
    current_global_exhaustion = bool(
        type(request_count) is int
        and type(manifest_request_count) is int
        and type(max_provider_requests) is int
        and request_count == manifest_request_count == max_provider_requests
    )
    historical_global_exhaustion = bool(
        type(request_count) is int
        and request_count in global_budget_boundaries
    )
    discovery_phase_exhaustion = bool(
        type(request_count) is int
        and request_count in discovery_phase_boundaries
    )
    stop_contract_is_valid = bool(
        (
            (current_global_exhaustion or historical_global_exhaustion)
            and row.get("stop_reason") == "budget_exhausted"
            and row.get("last_error") == "ProviderBudgetExhausted"
        )
        or (
            discovery_phase_exhaustion
            and row.get("stop_reason") == "discovery_budget_exhausted"
            and row.get("last_error") == "ProviderPhaseBudgetExhausted"
        )
    )
    return (
        type(row.get("run_id")) is str
        and type(row.get("lane_type")) is str
        and type(row.get("lane_key")) is str
        and all(
            type(row.get(field)) is int and row[field] == 0
            for field in zero_fields
        )
        and all(row.get(field) is None for field in empty_fields)
        and stop_contract_is_valid
        and manifest.get("status") == "partial"
        and run.get("status") == "partial"
        and row.get("status") == "partial"
    )


def _replay_discovery(
    target_store: BackfillStore, snapshot: dict[str, object]
) -> None:
    rows: dict[str, list[dict[str, object]]] = snapshot["rows"]
    artifacts: dict[str, RawArtifactMetadata] = snapshot["artifacts"]
    payloads: dict[str, bytes] = snapshot["payloads"]
    run_id = str(snapshot["run_id"])
    manifest: dict[str, object] = snapshot["manifest"]
    run: dict[str, object] = snapshot["run"]
    window_start, effective_end = _manifest_window(manifest)
    if window_start is None or effective_end is None:
        raise _ReplayDataError("source_manifest_invalid")
    configured_lanes = required_lanes_snapshot(
        search_terms=snapshot["search_terms"],
        subreddits=snapshot["subreddits"],
        include_subreddit_sweep=bool(manifest["include_subreddit_sweep"]),
    )
    lane_by_hash: dict[tuple[str, str], list[str]] = {}
    for lane_type, lane_key in configured_lanes:
        lane_by_hash.setdefault(
            (lane_type, sha256(lane_key.encode()).hexdigest()), []
        ).append(lane_key)
    checkpoints = {
        (str(row["lane_type"]), str(row["lane_key"])): row
        for row in rows["backfill_checkpoints"]
    }
    source_occurrences = rows["backfill_discovery_occurrences"]
    discovery_artifacts: dict[tuple[str, str], list[RawArtifactMetadata]] = {}
    for artifact in artifacts.values():
        if artifact.parser_kind not in _TIKHUB_DISCOVERY_PARSER_KINDS:
            continue
        matches = lane_by_hash.get((artifact.lane_type, artifact.lane_key_hash), [])
        if len(matches) != 1:
            raise _ReplayDataError("discovery_lane_unknown")
        discovery_artifacts.setdefault((artifact.lane_type, matches[0]), []).append(
            artifact
        )

    prepared_pages: dict[
        str,
        tuple[
            tuple[str, str],
            int,
            RawArtifactMetadata,
            list[dict[str, object]],
            list[
                tuple[
                    DiscoveryBaseDisposition,
                    str | None,
                    str | None,
                    str | None,
                ]
            ],
        ],
    ] = {}
    for lane in configured_lanes:
        lane_artifacts = discovery_artifacts.get(lane, [])
        if not lane_artifacts:
            continue
        checkpoint_row = checkpoints.get(lane)
        if checkpoint_row is None:
            raise _ReplayDataError("discovery_checkpoint_missing")
        lane_artifacts.sort(key=lambda artifact: int(artifact.page_number or 0))
        if [artifact.page_number for artifact in lane_artifacts] != list(
            range(1, len(lane_artifacts) + 1)
        ):
            raise _ReplayDataError("discovery_page_chain_invalid")
        previous_cursor: str | None = None
        for artifact in lane_artifacts:
            page_number = int(artifact.page_number or 0)
            endpoint = (
                "/api/v1/reddit/app/fetch_dynamic_search"
                if lane[0] == "dynamic_search"
                else "/api/v1/reddit/app/fetch_subreddit_feed"
            )
            source_method = f"tikhub_{lane[0]}"
            expected_url = _replay_tikhub_source_url(
                run_id=run_id,
                lane_type=lane[0],
                lane_key=lane[1],
                endpoint=endpoint,
                page_number=page_number,
                request_cursor=previous_cursor,
            )
            if (
                artifact.artifact_kind != "discovery"
                or artifact.source_method != source_method
                or artifact.source_endpoint != endpoint
                or artifact.request_cursor != previous_cursor
                or artifact.source_url != expected_url
                or artifact.identity_hash
                != sha256(expected_url.removeprefix("tikhub://").encode()).hexdigest()
            ):
                raise _ReplayDataError("discovery_artifact_invalid")
            payload = _decode_replay_json(payloads[artifact.artifact_id])
            next_cursor = _cursor_from_checkpoint(
                payload,
                checkpoint_row,
                allow_subreddit_terminal_empty=(
                    artifact.source_method == "tikhub_subreddit_feed"
                ),
            )
            if artifact.response_cursor != next_cursor:
                raise _ReplayDataError("discovery_page_chain_invalid")
            try:
                if artifact.parser_kind == _TIKHUB_DISCOVERY_LEGACY_PARSER_KIND:
                    posts = _extract_discovery_posts(
                        payload, artifact.source_method, dedupe=False
                    )
                elif (
                    artifact.parser_kind
                    == _TIKHUB_DISCOVERY_STRICT_PARSER_KIND
                ):
                    posts = _extract_backfill_discovery_posts(
                        payload,
                        artifact.source_method,
                        dedupe=False,
                        lane_key=lane[1],
                    )
                else:
                    raise _ReplayDataError("archive_metadata_invalid")
            except TikHubDiscoveryShapeError:
                raise _ReplayDataError("discovery_payload_invalid") from None
            page_occurrences = sorted(
                (
                    row
                    for row in source_occurrences
                    if row["lane_type"] == lane[0]
                    and row["lane_key"] == lane[1]
                    and row["page_number"] == page_number
                ),
                key=lambda row: int(row["ordinal"]),
            )
            if len(posts) != len(page_occurrences):
                raise _ReplayDataError("discovery_occurrence_mismatch")
            parsed_contracts: list[
                tuple[
                    DiscoveryBaseDisposition,
                    str | None,
                    str | None,
                    str | None,
                ]
            ] = []
            for post in posts:
                (
                    base_disposition,
                    post_id,
                    source_url,
                    created_at,
                ) = discovery_occurrence_contract(
                    post_id=post.post_id,
                    source_url=post.source_url,
                    title=post.title,
                    created_at_utc=post.created_at_utc,
                    window_start_utc=window_start,
                    window_end_utc=effective_end,
                )
                parsed_contracts.append(
                    (
                        base_disposition,
                        post_id,
                        source_url,
                        None if created_at is None else created_at.isoformat(),
                    )
                )

            if [row["ordinal"] for row in page_occurrences] != list(
                range(len(page_occurrences))
            ) or any(
                row["raw_artifact_id"] != artifact.artifact_id
                or row["discovered_at_utc"] != artifact.captured_at_utc
                for row in page_occurrences
            ):
                raise _ReplayDataError("discovery_occurrence_mismatch")

            source_contracts: list[
                tuple[
                    DiscoveryBaseDisposition,
                    str | None,
                    str | None,
                    str | None,
                ]
            ] = []
            for source_row in page_occurrences:
                source_disposition = source_row["disposition"]
                if source_disposition in {
                    "new_candidate",
                    "duplicate_occurrence",
                    "duplicate_existing_structured",
                }:
                    source_base_disposition: DiscoveryBaseDisposition = "eligible"
                elif source_disposition == "outside_window":
                    source_base_disposition = "outside_window"
                elif source_disposition == "invalid":
                    source_base_disposition = "invalid"
                else:
                    raise _ReplayDataError("discovery_occurrence_mismatch")
                source_post_id = source_row["post_id"]
                source_url = source_row["source_url"]
                source_created_at = source_row["post_created_at_utc"]
                if (
                    source_post_id is not None
                    and type(source_post_id) is not str
                ) or (
                    source_url is not None and type(source_url) is not str
                ) or (
                    source_created_at is not None
                    and type(source_created_at) is not str
                ):
                    raise _ReplayDataError("discovery_occurrence_mismatch")
                source_contracts.append(
                    (
                        source_base_disposition,
                        source_post_id,
                        source_url,
                        source_created_at,
                    )
                )

            # Canonical JSON sorts object keys. Historical collection parsed the
            # pre-serialization mapping, so only the exact page multiset—not raw
            # parser ordinals—survives as an archive-verifiable contract.
            if Counter(parsed_contracts) != Counter(source_contracts):
                raise _ReplayDataError("discovery_occurrence_mismatch")
            prepared_pages[artifact.artifact_id] = (
                lane,
                page_number,
                artifact,
                page_occurrences,
                source_contracts,
            )
            previous_cursor = next_cursor
        if int(checkpoint_row["page_number"]) != len(lane_artifacts):
            raise _ReplayDataError("discovery_checkpoint_mismatch")

    try:
        ordered_artifact_ids = _ordered_discovery_artifact_ids(
            discovery_artifacts
        )
    except ValueError:
        raise _ReplayDataError("discovery_capture_order_invalid") from None

    for artifact_id in ordered_artifact_ids:
        (
            lane,
            page_number,
            artifact,
            page_occurrences,
            source_contracts,
        ) = prepared_pages[artifact_id]
        for ordinal, (source_row, source_contract) in enumerate(
            zip(page_occurrences, source_contracts, strict=True)
        ):
            (
                base_disposition,
                post_id,
                source_url,
                created_text,
            ) = source_contract
            created_at = (
                None
                if created_text is None
                else datetime.fromisoformat(created_text)
            )
            disposition = target_store.record_discovery_occurrence(
                run_id=run_id,
                lane_type=lane[0],
                lane_key=lane[1],
                page_number=page_number,
                ordinal=ordinal,
                post_id=post_id,
                source_url=source_url,
                post_created_at_utc=created_at,
                raw_artifact_id=artifact.artifact_id,
                discovered_at_utc=datetime.fromisoformat(
                    str(source_row["discovered_at_utc"])
                ),
                base_disposition=base_disposition,
            )
            if disposition != source_row["disposition"]:
                raise _ReplayDataError("discovery_occurrence_mismatch")

    for lane in configured_lanes:
        lane_artifacts = discovery_artifacts.get(lane, [])
        if not lane_artifacts:
            continue
        checkpoint_row = checkpoints[lane]
        target_store.save_checkpoint(_checkpoint_from_row(checkpoint_row))

    discovery_checkpoint_lanes = {
        (str(row["lane_type"]), str(row["lane_key"]))
        for row in rows["backfill_checkpoints"]
        if row["lane_type"] in {"dynamic_search", "subreddit_feed"}
    }
    artifact_lanes = set(discovery_artifacts)
    if not discovery_checkpoint_lanes.issubset(set(configured_lanes)):
        raise _ReplayDataError("discovery_checkpoint_mismatch")
    for lane in sorted(
        discovery_checkpoint_lanes - artifact_lanes,
        key=configured_lanes.index,
    ):
        checkpoint_row = checkpoints[lane]
        if not _is_replayable_zero_page_budget_checkpoint(
            checkpoint_row,
            manifest,
            run,
            global_budget_boundaries=snapshot["global_budget_boundaries"],
            discovery_phase_boundaries=snapshot[
                "discovery_phase_boundaries"
            ],
        ):
            raise _ReplayDataError("discovery_checkpoint_mismatch")
        target_store.save_checkpoint(_checkpoint_from_row(checkpoint_row))


def _replay_detail_comments_and_failures(
    target_store: BackfillStore, snapshot: dict[str, object]
) -> int:
    rows: dict[str, list[dict[str, object]]] = snapshot["rows"]
    artifacts: dict[str, RawArtifactMetadata] = snapshot["artifacts"]
    payloads: dict[str, bytes] = snapshot["payloads"]
    captures: dict[str, RawCapture] = snapshot["captures"]
    run_id = str(snapshot["run_id"])
    manifest: dict[str, object] = snapshot["manifest"]
    window_start, effective_end = _manifest_window(manifest)
    if window_start is None or effective_end is None:
        raise _ReplayDataError("source_manifest_invalid")
    source_candidates = {
        str(row["post_id"]): row for row in rows["backfill_candidates"]
    }
    members_by_batch: dict[str, list[dict[str, object]]] = {}
    for member in rows["backfill_detail_batch_members"]:
        members_by_batch.setdefault(str(member["batch_id"]), []).append(member)
    source_batches = sorted(
        rows["backfill_detail_batches"], key=lambda row: int(row["batch_number"])
    )
    _restore_detail_batch_ledgers(
        target_store,
        run_id=run_id,
        batches=source_batches,
        members_by_batch=members_by_batch,
    )
    comment_checkpoints = {
        str(row["lane_key"]): row
        for row in rows["backfill_checkpoints"]
        if row["lane_type"] == "comments"
    }
    raw_derived_posts: set[str] = set()
    batched_posts: set[str] = set()

    for batch_row in source_batches:
        batch_id = str(batch_row["batch_id"])
        members = sorted(
            members_by_batch.get(batch_id, []), key=lambda row: int(row["ordinal"])
        )
        post_ids = tuple(str(member["post_id"]) for member in members)
        if (
            not post_ids
            or [int(member["ordinal"]) for member in members]
            != list(range(len(post_ids)))
        ):
            raise _ReplayDataError("detail_membership_invalid")
        batched_posts.update(post_ids)
        if batch_row["status"] == "failed":
            if batch_row["artifact_id"] is not None or not batch_row["stop_reason"]:
                raise _ReplayDataError("detail_batch_invalid")
            target_store.finish_detail_batch(
                run_id=run_id,
                batch_id=batch_id,
                status="failed",
                stop_reason=str(batch_row["stop_reason"]),
                updated_at_utc=datetime.fromisoformat(str(batch_row["updated_at_utc"])),
            )
            continue
        if batch_row["status"] != "complete" or batch_row["stop_reason"] is not None:
            raise _ReplayDataError("detail_batch_invalid")
        artifact = artifacts.get(str(batch_row["artifact_id"]))
        if artifact is None:
            raise _ReplayDataError("detail_artifact_missing")
        expected_url = _replay_tikhub_source_url(
            run_id=run_id,
            lane_type="detail_batch",
            lane_key=batch_id,
            endpoint="/api/v1/reddit/app/fetch_post_details_batch_large",
            page_number=int(batch_row["batch_number"]),
            request_cursor=None,
        )
        if (
            artifact.parser_kind != "tikhub_detail"
            or artifact.artifact_kind != "detail"
            or artifact.lane_type != "detail_batch"
            or artifact.lane_key_hash != sha256(batch_id.encode()).hexdigest()
            or artifact.source_method != "tikhub_detail"
            or artifact.source_endpoint
            != "/api/v1/reddit/app/fetch_post_details_batch_large"
            or artifact.source_url != expected_url
            or artifact.page_number != batch_row["batch_number"]
            or artifact.request_cursor is not None
            or artifact.response_cursor is not None
        ):
            raise _ReplayDataError("detail_artifact_invalid")
        target_store.attach_detail_batch_artifact(
            run_id=run_id,
            batch_id=batch_id,
            artifact_id=artifact.artifact_id,
            updated_at_utc=datetime.fromisoformat(str(batch_row["updated_at_utc"])),
        )
        detail_payload = _decode_replay_json(payloads[artifact.artifact_id])
        post_infos = _extract_tikhub_posts_info(detail_payload)
        returned_ids = [_normalize_post_id(row.get("id")) for row in post_infos]
        if (
            len(returned_ids) != len(set(returned_ids))
            or any(post_id not in post_ids for post_id in returned_ids)
        ):
            raise _ReplayDataError("detail_response_invalid")
        try:
            parsed_threads = _parse_tikhub_app_detail_payload(
                detail_payload,
                comment_payloads={},
                run_id=run_id,
                raw_capture_id=artifact.raw_capture_id,
            )
        except Exception:
            raise _ReplayDataError("detail_response_invalid") from None
        threads = {thread.post_id: thread for thread, _ in parsed_threads}
        submitters = {
            _normalize_post_id(row.get("id")): (
                _author_name(row.get("authorInfo"))
                or str(row.get("author") or "")
            )
            for row in post_infos
        }
        for post_id in post_ids:
            source_candidate = source_candidates.get(post_id)
            if source_candidate is None:
                raise _ReplayDataError("detail_candidate_missing")
            if post_id not in returned_ids:
                _finalize_replay_without_entities(
                    target_store,
                    source_candidate,
                    expected_status="failed",
                    expected_reason="detail_missing",
                )
                raw_derived_posts.add(post_id)
                continue
            thread = threads.get(post_id)
            if thread is None:
                _finalize_replay_without_entities(
                    target_store,
                    source_candidate,
                    expected_status="failed",
                    expected_reason="detail_unparseable",
                )
                raw_derived_posts.add(post_id)
                continue
            if not window_start <= thread.created_at_utc < effective_end:
                _finalize_replay_without_entities(
                    target_store,
                    source_candidate,
                    expected_status="outside_window_detail",
                    expected_reason=None,
                )
                raw_derived_posts.add(post_id)
                continue
            _replay_hydrated_candidate(
                target_store,
                snapshot=snapshot,
                source_candidate=source_candidate,
                detail_thread=thread,
                detail_capture=captures[artifact.raw_capture_id],
                submitter_name=submitters.get(post_id, ""),
                checkpoint_row=comment_checkpoints.get(post_id),
            )
            raw_derived_posts.add(post_id)
        target_store.finish_detail_batch(
            run_id=run_id,
            batch_id=batch_id,
            status="complete",
            stop_reason=None,
            updated_at_utc=datetime.fromisoformat(str(batch_row["updated_at_utc"])),
        )

    metadata_mirrored_count = 0
    with target_store.connect() as target_conn:
        target_candidates = {
            str(row["post_id"]): row
            for row in target_conn.execute(
                """
                SELECT *
                FROM backfill_candidates
                WHERE run_id = ?
                ORDER BY post_id
                """,
                (run_id,),
            ).fetchall()
        }
    for post_id, source_candidate in source_candidates.items():
        target_candidate = target_candidates.get(post_id)
        if target_candidate is None:
            raise _ReplayDataError("candidate_replay_mismatch")
        if post_id in raw_derived_posts:
            continue
        source_status = str(source_candidate["status"])
        source_reason = source_candidate["status_reason"]
        if source_status == "pending":
            if target_candidate["status"] != "pending":
                raise _ReplayDataError("candidate_replay_mismatch")
            continue
        if source_status == "duplicate_existing_structured":
            if target_store.structured_thread_run_id(post_id) is None:
                raise _ReplayDataError("candidate_replay_mismatch")
            target_store.finalize_candidate(
                run_id=run_id,
                post_id=post_id,
                expected_statuses=("pending",),
                status="duplicate_existing_structured",
                status_reason=None,
                updated_at_utc=datetime.fromisoformat(
                    str(source_candidate["updated_at_utc"])
                ),
            )
            continue
        allowed_failure = (
            (source_status, source_reason)
            in {
                ("failed", "provider_error"),
                ("failed", "detail_schema_drift"),
                ("failed", "comments_schema_drift"),
                ("failed", "comment_conflict"),
                ("failed", "cursor_loop"),
                ("budget_deferred", "budget_exhausted"),
            }
            and (
                post_id not in batched_posts
                or any(
                    row["batch_id"] in members_by_batch
                    and row["status"] == "failed"
                    for row in rows["backfill_detail_batches"]
                    for member in members_by_batch.get(str(row["batch_id"]), [])
                    if member["post_id"] == post_id
                )
            )
        )
        if not allowed_failure:
            raise _ReplayDataError("candidate_outcome_not_raw_derived")
        target_store.finalize_candidate(
            run_id=run_id,
            post_id=post_id,
            expected_statuses=("pending",),
            status=source_status,
            status_reason=source_reason,
            updated_at_utc=datetime.fromisoformat(
                str(source_candidate["updated_at_utc"])
            ),
        )
        metadata_mirrored_count += 1
    return metadata_mirrored_count


def _restore_detail_batch_ledgers(
    target_store: BackfillStore,
    *,
    run_id: str,
    batches: list[dict[str, object]],
    members_by_batch: dict[str, list[dict[str, object]]],
) -> None:
    prepared_rows: list[tuple[object, ...]] = []
    member_rows: list[tuple[object, ...]] = []
    assigned_posts: set[str] = set()
    batch_ids: set[str] = set()

    for batch in batches:
        batch_id = batch.get("batch_id")
        batch_number = batch.get("batch_number")
        status = batch.get("status")
        artifact_id = batch.get("artifact_id")
        stop_reason = batch.get("stop_reason")
        if (
            type(batch_id) is not str
            or not batch_id.strip()
            or type(batch_number) is not int
            or batch_number <= 0
            or batch_id in batch_ids
        ):
            raise _ReplayDataError("detail_membership_invalid")
        batch_ids.add(batch_id)

        created_at = _replay_aware_datetime(batch.get("created_at_utc"))
        updated_at = _replay_aware_datetime(batch.get("updated_at_utc"))
        if updated_at < created_at:
            raise _ReplayDataError("detail_batch_invalid")
        if status == "complete":
            if type(artifact_id) is not str or not artifact_id or stop_reason is not None:
                raise _ReplayDataError("detail_batch_invalid")
        elif status == "failed":
            if (
                artifact_id is not None
                or type(stop_reason) is not str
                or _SAFE_REASON_PATTERN.fullmatch(stop_reason) is None
            ):
                raise _ReplayDataError("detail_batch_invalid")
        else:
            raise _ReplayDataError("detail_batch_invalid")

        members = sorted(
            members_by_batch.get(batch_id, []), key=lambda row: int(row["ordinal"])
        )
        if not 1 <= len(members) <= 30:
            raise _ReplayDataError("detail_membership_invalid")
        ordinals: list[int] = []
        post_ids: list[str] = []
        for member in members:
            ordinal = member.get("ordinal")
            post_id = member.get("post_id")
            if (
                member.get("run_id") != run_id
                or member.get("batch_id") != batch_id
                or type(ordinal) is not int
                or type(post_id) is not str
                or not post_id.strip()
            ):
                raise _ReplayDataError("detail_membership_invalid")
            ordinals.append(ordinal)
            post_ids.append(post_id)
        if (
            ordinals != list(range(len(post_ids)))
            or len(set(post_ids)) != len(post_ids)
            or assigned_posts.intersection(post_ids)
            or batch_id
            != "detail_batch_"
            + sha256(
                json.dumps(
                    [run_id, post_ids], ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest()[:24]
        ):
            raise _ReplayDataError("detail_membership_invalid")
        assigned_posts.update(post_ids)

        created_text = str(batch["created_at_utc"])
        prepared_rows.append(
            (
                run_id,
                batch_id,
                batch_number,
                "prepared",
                None,
                None,
                created_text,
                created_text,
            )
        )
        member_rows.extend(
            (run_id, batch_id, ordinal, post_id)
            for ordinal, post_id in enumerate(post_ids)
        )

    if set(members_by_batch) != batch_ids:
        raise _ReplayDataError("detail_membership_invalid")

    with target_store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        target_candidates = {
            str(row["post_id"]): str(row["status"])
            for row in conn.execute(
                "SELECT post_id, status FROM backfill_candidates WHERE run_id=?",
                (run_id,),
            ).fetchall()
        }
        if any(target_candidates.get(post_id) != "pending" for post_id in assigned_posts):
            raise _ReplayDataError("detail_membership_invalid")
        conn.executemany(
            """
            INSERT INTO backfill_detail_batches(
                run_id, batch_id, batch_number, status, artifact_id,
                stop_reason, created_at_utc, updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            prepared_rows,
        )
        conn.executemany(
            """
            INSERT INTO backfill_detail_batch_members(
                run_id, batch_id, ordinal, post_id
            ) VALUES (?, ?, ?, ?)
            """,
            member_rows,
        )


def _replay_aware_datetime(value: object) -> datetime:
    if type(value) is not str:
        raise _ReplayDataError("detail_batch_invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise _ReplayDataError("detail_batch_invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _ReplayDataError("detail_batch_invalid")
    return parsed


def _replay_hydrated_candidate(
    target_store: BackfillStore,
    *,
    snapshot: dict[str, object],
    source_candidate: dict[str, object],
    detail_thread: Any,
    detail_capture: RawCapture,
    submitter_name: str,
    checkpoint_row: dict[str, object] | None,
) -> None:
    if checkpoint_row is None:
        raise _ReplayDataError("comment_checkpoint_missing")
    artifacts: dict[str, RawArtifactMetadata] = snapshot["artifacts"]
    payloads: dict[str, bytes] = snapshot["payloads"]
    captures: dict[str, RawCapture] = snapshot["captures"]
    run_id = str(snapshot["run_id"])
    post_id = detail_thread.post_id
    pages = sorted(
        (
            artifact
            for artifact in artifacts.values()
            if artifact.parser_kind == "tikhub_comments"
            and artifact.lane_key_hash == sha256(post_id.encode()).hexdigest()
        ),
        key=lambda artifact: int(artifact.page_number or 0),
    )
    if not pages or [artifact.page_number for artifact in pages] != list(
        range(1, int(checkpoint_row["page_number"]) + 1)
    ):
        raise _ReplayDataError("comment_chain_invalid")
    previous_cursor: str | None = None
    comments_by_id: dict[str, Any] = {}
    more_node_count = 0
    occurrence_count = 0
    comment_capture_ids: set[str] = set()
    for artifact in pages:
        page_number = int(artifact.page_number or 0)
        expected_url = _replay_tikhub_source_url(
            run_id=run_id,
            lane_type="comments",
            lane_key=post_id,
            endpoint="/api/v1/reddit/app/fetch_post_comments",
            page_number=page_number,
            request_cursor=previous_cursor,
        )
        if (
            artifact.artifact_kind != "comments"
            or artifact.lane_type != "comments"
            or artifact.source_method != "tikhub_comments"
            or artifact.source_endpoint != "/api/v1/reddit/app/fetch_post_comments"
            or artifact.request_cursor != previous_cursor
            or artifact.source_url != expected_url
        ):
            raise _ReplayDataError("comment_artifact_invalid")
        payload = _decode_replay_json(payloads[artifact.artifact_id])
        next_cursor = _cursor_from_checkpoint(
            payload,
            checkpoint_row,
            allow_terminal_without_cursor=True,
        )
        if artifact.response_cursor != next_cursor:
            raise _ReplayDataError("comment_chain_invalid")
        try:
            comments, page_more = _parse_strict_tikhub_comment_payload(
                payload,
                post_id=post_id,
                run_id=run_id,
                raw_capture_id=artifact.raw_capture_id,
                submitter_name=submitter_name,
            )
        except Exception:
            raise _ReplayDataError("comment_payload_invalid") from None
        occurrence_count += len(comments)
        more_node_count += page_more
        comment_capture_ids.add(artifact.raw_capture_id)
        for comment in comments:
            existing = comments_by_id.get(comment.comment_id)
            if existing is None:
                comments_by_id[comment.comment_id] = comment
            elif _comment_semantic_key(existing) != _comment_semantic_key(comment):
                raise _ReplayDataError("comment_semantic_conflict")
        previous_cursor = next_cursor
    if (
        checkpoint_row["cursor"] != previous_cursor
        or checkpoint_row["previous_cursor"] != pages[-1].request_cursor
        or int(checkpoint_row["discovered_count"]) != occurrence_count
        or int(checkpoint_row["unique_count"]) != len(comments_by_id)
        or checkpoint_row["last_success_utc"] != pages[-1].captured_at_utc
        or checkpoint_row["status"] != "complete"
        or checkpoint_row["stop_reason"] != "cursor_exhausted"
        or previous_cursor is not None
    ):
        raise _ReplayDataError("comment_checkpoint_mismatch")
    target_store.save_checkpoint(_checkpoint_from_row(checkpoint_row))
    comments = tuple(comments_by_id.values())
    combined = analyze_text(
        "\n".join(
            (
                detail_thread.title,
                detail_thread.selftext,
                *(comment.body for comment in comments),
            )
        )
    )
    if not combined.keyword_match.is_relevant:
        _finalize_replay_without_entities(
            target_store,
            source_candidate,
            expected_status="excluded",
            expected_reason=None,
        )
        return
    coverage = BrowserJsonAdapter._coverage_grade(
        parsed_comment_count=len(comments),
        more_node_count=more_node_count,
        reported_count=detail_thread.num_comments_reported,
    )
    status_reason = (
        "unresolved_more"
        if more_node_count
        else "post_only_coverage"
        if coverage == "post_only"
        else None
    )
    if (
        source_candidate["status"] != "hydrated"
        or source_candidate["status_reason"] != status_reason
    ):
        raise _ReplayDataError("candidate_outcome_mismatch")
    final_thread = replace(
        detail_thread,
        parsed_comment_count=len(comments),
        more_node_count=more_node_count,
        coverage_grade=coverage,
        matched_keywords=combined.keyword_match.matched_terms,
    )
    analyses = _analysis_models_for_entities(
        run_id=run_id, thread=final_thread, comments=comments
    )
    required_captures = [detail_capture]
    required_captures.extend(captures[capture_id] for capture_id in sorted(comment_capture_ids))
    target_store.finalize_candidate(
        run_id=run_id,
        post_id=post_id,
        expected_statuses=("pending",),
        status="hydrated",
        status_reason=status_reason,
        updated_at_utc=datetime.fromisoformat(str(source_candidate["updated_at_utc"])),
        captures=tuple(required_captures),
        threads=(final_thread,),
        comments=comments,
        analyses=analyses,
    )


def _finalize_replay_without_entities(
    target_store: BackfillStore,
    source_candidate: dict[str, object],
    *,
    expected_status: str,
    expected_reason: str | None,
) -> None:
    if (
        source_candidate["status"] != expected_status
        or source_candidate["status_reason"] != expected_reason
    ):
        raise _ReplayDataError("candidate_outcome_mismatch")
    target_store.finalize_candidate(
        run_id=str(source_candidate["run_id"]),
        post_id=str(source_candidate["post_id"]),
        expected_statuses=("pending",),
        status=expected_status,
        status_reason=expected_reason,
        updated_at_utc=datetime.fromisoformat(str(source_candidate["updated_at_utc"])),
    )


def _verify_replay_operational_constraints(
    target_store: BackfillStore, snapshot: dict[str, object]
) -> None:
    source_rows: dict[str, list[dict[str, object]]] = snapshot["rows"]
    run_id = str(snapshot["run_id"])
    tables = (
        "backfill_seed_files",
        "backfill_checkpoints",
        "backfill_candidates",
        "backfill_detail_batches",
        "backfill_detail_batch_members",
        "backfill_discovery_occurrences",
    )
    with target_store.connect() as conn:
        for table in tables:
            source_canonical = _canonical_table_rows(source_rows[table])
            target_canonical = _canonical_table_rows(
                [
                    dict(row)
                    for row in conn.execute(
                        f"SELECT * FROM {table} WHERE run_id=?", (run_id,)
                    ).fetchall()
                ]
            )
            if source_canonical != target_canonical:
                raise _ReplayDataError("operational_metadata_mismatch")
        if conn.execute(
            "SELECT COUNT(*) FROM backfill_provider_attempts WHERE run_id=?",
            (run_id,),
        ).fetchone()[0]:
            raise _ReplayDataError("provider_attempt_replayed")
        if any(
            conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            for table in _OPTIONAL_AUTHORIZATION_TABLES
        ):
            raise _ReplayDataError("authorization_ledger_replayed")
        manifest = conn.execute(
            "SELECT provider_request_count, provider_call, live_send "
            "FROM backfill_manifests WHERE run_id=?",
            (run_id,),
        ).fetchone()
        run = conn.execute(
            "SELECT provider_call, live_send FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if manifest is None or run is None or tuple(manifest) != (0, 0, 0) or tuple(run) != (0, 0):
            raise _ReplayDataError("target_boundary_invalid")


def _replay_fingerprints(
    conn: sqlite3.Connection, run_id: str
) -> dict[str, object]:
    surfaces = (
        ("runs", ("run_id", "window_start_utc", "window_end_utc"), "run_id", None),
        (
            "backfill_raw_artifacts",
            tuple(_REQUIRED_COLUMNS["backfill_raw_artifacts"]),
            "artifact_id",
            "payload_sha256",
        ),
        (
            "raw_captures",
            tuple(_REQUIRED_COLUMNS["raw_captures"]),
            "raw_capture_id",
            "raw_payload_hash",
        ),
        (
            "reddit_threads",
            tuple(_REQUIRED_COLUMNS["reddit_threads"]),
            "post_id",
            None,
        ),
        (
            "reddit_comments",
            tuple(_REQUIRED_COLUMNS["reddit_comments"]),
            "comment_id",
            None,
        ),
        (
            "analysis_results",
            tuple(_REQUIRED_COLUMNS["analysis_results"]),
            "analysis_id",
            None,
        ),
    )
    result: dict[str, object] = {}
    for table, columns, identity_column, raw_hash_column in surfaces:
        order_columns = [
            str(row["name"])
            for row in sorted(
                (
                    row
                    for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
                    if int(row["pk"]) > 0
                ),
                key=lambda row: int(row["pk"]),
            )
        ]
        rows = conn.execute(
            f"SELECT {', '.join(columns)} FROM {table} WHERE run_id=? "
            f"ORDER BY {', '.join(order_columns or [identity_column])}",
            (run_id,),
        ).fetchall()
        encoded = [[row[column] for column in columns] for row in rows]
        table_result: dict[str, object] = {
            "row_count": len(rows),
            "id_set_sha256": _canonical_sha(
                sorted(str(row[identity_column]) for row in rows)
            ),
            "canonical_rows_sha256": _canonical_sha(encoded),
        }
        if raw_hash_column is not None:
            table_result["raw_payload_hash_set_sha256"] = _canonical_sha(
                sorted(str(row[raw_hash_column]) for row in rows)
            )
        result[table] = table_result
    return result


def operational_snapshot_sha256(
    conn: sqlite3.Connection, run_id: str
) -> str:
    payload: dict[str, object] = {}
    available_tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    for table in _OPERATIONAL_SNAPSHOT_TABLES:
        if table in _OPTIONAL_AUTHORIZATION_TABLES:
            if table not in available_tables:
                payload[table] = None
                continue
            table_info = sorted(
                conn.execute(f"PRAGMA table_info({table})").fetchall(),
                key=lambda row: int(row["cid"]),
            )
            column_names = [str(row["name"]) for row in table_info]
            rows = [
                [row[column] for column in column_names]
                for row in conn.execute(
                    f"SELECT * FROM {table} WHERE run_id=?", (run_id,)
                ).fetchall()
            ]
            rows.sort(
                key=lambda row: json.dumps(
                    row, ensure_ascii=False, separators=(",", ":")
                )
            )
            schema_row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            payload[table] = {
                "schema_sha256": sha256(
                    str(schema_row["sql"] if schema_row else "").encode()
                ).hexdigest(),
                "columns": [
                    [
                        str(row["name"]),
                        str(row["type"]),
                        int(row["notnull"]),
                        row["dflt_value"],
                        int(row["pk"]),
                    ]
                    for row in table_info
                ],
                "rows": rows,
            }
            continue
        columns = _REQUIRED_COLUMNS[table]
        primary_key = [
            str(row["name"])
            for row in sorted(
                (
                    row
                    for row in conn.execute(
                        f"PRAGMA table_info({table})"
                    ).fetchall()
                    if int(row["pk"]) > 0
                ),
                key=lambda row: int(row["pk"]),
            )
        ]
        if not primary_key:
            raise sqlite3.DatabaseError("operational table has no primary key")
        rows = conn.execute(
            f"SELECT {', '.join(columns)} FROM {table} WHERE run_id=? "
            f"ORDER BY {', '.join(primary_key)}",
            (run_id,),
        ).fetchall()
        payload[table] = [
            [row[column] for column in columns] for row in rows
        ]
    return _canonical_sha(payload, sort_keys=True)


def _fingerprints_for_path(path: Path, run_id: str) -> dict[str, object]:
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("BEGIN")
        return _replay_fingerprints(conn, run_id)
    finally:
        try:
            conn.rollback()
        finally:
            conn.close()


def _checkpoint_from_row(row: dict[str, object]) -> BackfillCheckpoint:
    return BackfillCheckpoint(
        run_id=str(row["run_id"]),
        lane_type=row["lane_type"],
        lane_key=str(row["lane_key"]),
        cursor=row["cursor"],
        previous_cursor=row["previous_cursor"],
        page_number=int(row["page_number"]),
        newest_seen_utc=row["newest_seen_utc"],
        oldest_seen_utc=row["oldest_seen_utc"],
        discovered_count=int(row["discovered_count"]),
        unique_count=int(row["unique_count"]),
        provider_request_count=int(row["provider_request_count"]),
        last_success_utc=row["last_success_utc"],
        last_error=row["last_error"],
        status=row["status"],
        stop_reason=row["stop_reason"],
        cursor_json_path=row["cursor_json_path"],
        cursor_schema_sha256=row["cursor_schema_sha256"],
        consecutive_old_pages=int(row["consecutive_old_pages"]),
    )


def _nonempty_cursor_candidates(
    value: object,
    path: tuple[str | int, ...] = (),
) -> list[tuple[tuple[str | int, ...], dict[str, object]]]:
    candidates: list[tuple[tuple[str | int, ...], dict[str, object]]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = (*path, key)
            if key == "pageInfo" and isinstance(child, dict):
                for cursor_key in ("endCursor", "nextCursor", "after"):
                    cursor = child.get(cursor_key)
                    if isinstance(cursor, str) and cursor:
                        candidates.append(((*child_path, cursor_key), child))
            candidates.extend(_nonempty_cursor_candidates(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            candidates.extend(
                _nonempty_cursor_candidates(child, (*path, index))
            )
    return candidates


def _recovery_cursor_contract(payload: object) -> CursorContract:
    candidates = _nonempty_cursor_candidates(payload)
    if len(candidates) != 1:
        raise _ReplayDataError("cursor_contract_invalid")
    path, page_info = candidates[0]
    return CursorContract(
        cursor_path=path,
        schema_sha256=_page_info_schema_sha256(page_info),
    )


def _cursor_from_recovery_contract(
    payload: object, contract: CursorContract
) -> str | None:
    checkpoint = {
        "cursor_json_path": json.dumps(
            list(contract.cursor_path),
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "cursor_schema_sha256": contract.schema_sha256,
    }
    cursor = _cursor_from_checkpoint(payload, checkpoint)
    actual_paths = {
        path for path, _page_info in _nonempty_cursor_candidates(payload)
    }
    expected_paths = {contract.cursor_path} if cursor else set()
    if actual_paths != expected_paths:
        raise _ReplayDataError("cursor_contract_invalid")
    return cursor


def _cursor_from_checkpoint(
    payload: object,
    checkpoint: dict[str, object],
    *,
    allow_terminal_without_cursor: bool = False,
    allow_subreddit_terminal_empty: bool = False,
) -> str | None:
    if (
        type(allow_terminal_without_cursor) is not bool
        or type(allow_subreddit_terminal_empty) is not bool
    ):
        raise TypeError("cursor replay options must be bool")
    try:
        path = json.loads(str(checkpoint["cursor_json_path"]))
    except (TypeError, ValueError):
        raise _ReplayDataError("cursor_contract_invalid") from None
    if (
        type(path) is not list
        or len(path) < 2
        or any(type(component) not in {str, int} for component in path)
        or path[-1] not in {"endCursor", "nextCursor", "after"}
    ):
        raise _ReplayDataError("cursor_contract_invalid")
    if allow_subreddit_terminal_empty and _is_strict_subreddit_v3_terminal_empty(
        payload
    ):
        if (
            tuple(path) != STRICT_SUBREDDIT_V3_CURSOR_PATH
            or checkpoint["cursor_schema_sha256"]
            != STRICT_SUBREDDIT_V3_CURSOR_SCHEMA_SHA256
        ):
            raise _ReplayDataError("cursor_contract_invalid")
        return None
    current = payload
    parent = None
    cursor_missing = False
    for index, component in enumerate(path):
        parent = current
        if type(component) is str:
            if not isinstance(current, dict) or component not in current:
                if (
                    allow_terminal_without_cursor
                    and index == len(path) - 1
                    and isinstance(current, dict)
                    and current.get("hasNextPage") is False
                ):
                    parent = current
                    current = None
                    cursor_missing = True
                    break
                raise _ReplayDataError("cursor_contract_invalid")
            current = current[component]
        else:
            if not isinstance(current, list) or component < 0 or component >= len(current):
                raise _ReplayDataError("cursor_contract_invalid")
            current = current[component]
    if not isinstance(parent, dict):
        raise _ReplayDataError("cursor_contract_invalid")
    if _page_info_schema_sha256(parent) != checkpoint["cursor_schema_sha256"]:
        raise _ReplayDataError("cursor_contract_invalid")
    if cursor_missing:
        return None
    if current is None or current == "":
        return None
    if type(current) is not str:
        raise _ReplayDataError("cursor_contract_invalid")
    return current


def _page_info_schema_sha256(value: dict[str, object]) -> str:
    def shape(item: object, *, page_container: bool = False) -> object:
        if isinstance(item, dict):
            return {
                "type": "object",
                "properties": {
                    key: (
                        "cursor"
                        if page_container
                        and key in {"endCursor", "nextCursor", "after"}
                        and (item[key] is None or isinstance(item[key], str))
                        else shape(item[key])
                    )
                    for key in sorted(item)
                },
            }
        if isinstance(item, list):
            return {"type": "array", "items": [shape(child) for child in item]}
        if item is None:
            return "null"
        if isinstance(item, bool):
            return "boolean"
        if isinstance(item, int):
            return "integer"
        if isinstance(item, float):
            return "number"
        if isinstance(item, str):
            return "string"
        return type(item).__name__

    return _canonical_sha(shape(value, page_container=True), sort_keys=True)


def _raw_capture_from_artifact(artifact: RawArtifactMetadata) -> RawCapture:
    return RawCapture(
        raw_capture_id=artifact.raw_capture_id,
        run_id=artifact.run_id,
        source_method=artifact.source_method,
        source_url=artifact.source_url,
        captured_at_utc=datetime.fromisoformat(artifact.captured_at_utc),
        auth_boundary=(
            "local_seed" if artifact.source_method == "historical_seed" else "provider_gate"
        ),
        raw_payload_hash=f"sha256:{artifact.payload_sha256}",
        payload_format="json",
    )


def _raw_capture_record(capture: RawCapture) -> dict[str, object]:
    record = capture.as_record()
    record["secrets_written"] = int(capture.secrets_written)
    return record


def _seed_artifact_matches_ledger(
    artifact: RawArtifactMetadata, ledger: dict[str, object]
) -> bool:
    input_hash = str(ledger["input_path_hash"])
    payload_hash = str(ledger["payload_sha256"])
    return (
        artifact.artifact_kind == "seed"
        and artifact.lane_type == "seed"
        and artifact.parser_kind == "seed_browser_thread"
        and artifact.source_method == "historical_seed"
        and artifact.source_endpoint == "seed_file"
        and artifact.source_url == f"seed://{input_hash}"
        and artifact.lane_key_hash == sha256(input_hash.encode()).hexdigest()
        and artifact.identity_hash == sha256(payload_hash.encode()).hexdigest()
        and artifact.payload_sha256 == payload_hash
        and artifact.page_number == 0
        and artifact.request_cursor is None
        and artifact.response_cursor is None
    )


def _analysis_models_for_entities(
    *, run_id: str, thread: Any, comments: tuple[Any, ...]
) -> tuple[AnalysisRow, ...]:
    return (
        _analysis_model(
            analysis_id=f"analysis_post_{thread.post_id}",
            run_id=run_id,
            source_type="post",
            source_id=thread.post_id,
            text=f"{thread.title}\n{thread.selftext}",
        ),
        *(
            _analysis_model(
                analysis_id=f"analysis_comment_{comment.comment_id}",
                run_id=run_id,
                source_type="comment",
                source_id=comment.comment_id,
                text=comment.body,
            )
            for comment in comments
        ),
    )


def _analysis_model(
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


def _comment_semantic_key(comment: Any) -> tuple[object, ...]:
    return (
        comment.body,
        comment.post_id,
        comment.parent_id,
        comment.created_at_utc,
        comment.score,
        comment.depth,
        comment.is_submitter,
        comment.author_hash,
        comment.deleted_or_removed,
        tuple(comment.matched_keywords),
    )


def _replay_tikhub_source_url(
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


def _decode_replay_json(payload: bytes) -> object:
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _ReplayDataError("archive_json_invalid") from None


def _canonical_table_rows(rows: list[dict[str, object]]) -> list[str]:
    return sorted(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for row in rows
    )


def _replay_result(
    *,
    status: str,
    stop_reason: str,
    fingerprints: dict[str, object],
    metadata_mirrored_count: int,
) -> dict[str, object]:
    return {
        "schema_version": "backfill_replay_v1",
        "status": status,
        "stop_reason": stop_reason,
        "provider_attempt_made": False,
        "live_send": False,
        "fingerprints": fingerprints,
        "metadata_mirrored_count": metadata_mirrored_count,
        "provider_attempts": "source_only_not_replayed",
    }


def _prepare_replay_temp_for_publish(path: Path) -> None:
    connection = sqlite3.connect(path, timeout=5.0)
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
        connection.commit()
    finally:
        connection.close()


def _close_replay_source_connection(
    connection: sqlite3.Connection, *, close: bool = True
) -> None:
    primary: Exception | None = None
    try:
        connection.rollback()
    except Exception as exc:
        primary = exc
    if close:
        try:
            connection.close()
        except Exception as exc:
            if primary is None:
                primary = exc
    if primary is not None:
        raise primary


def _best_effort_close_source_connection(
    connection: sqlite3.Connection, *, close: bool = True
) -> None:
    try:
        connection.rollback()
    except Exception:
        pass
    if close:
        try:
            connection.close()
        except Exception:
            pass


def _close_replay_temp_descriptor(descriptor: int) -> None:
    os.close(descriptor)


def _best_effort_close_descriptor(descriptor: int) -> None:
    try:
        os.fstat(descriptor)
    except OSError:
        return
    try:
        os.close(descriptor)
    except OSError:
        pass


def _replay_temporary_names(temporary_name: str) -> tuple[str, ...]:
    return (
        temporary_name,
        temporary_name + "-wal",
        temporary_name + "-shm",
        temporary_name + "-journal",
    )


def _unlink_replay_name(name: str, *, parent_fd: int) -> None:
    os.unlink(name, dir_fd=parent_fd)


def _fsync_replay_parent(parent_fd: int) -> None:
    os.fsync(parent_fd)


def _link_replay_name(
    source_name: str,
    target_name: str,
    *,
    parent_fd: int,
    temporary_fd: int,
    temporary_identity: tuple[int, int],
) -> None:
    try:
        pinned_stat = os.fstat(temporary_fd)
        source_stat = os.stat(
            source_name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
    except OSError:
        raise _ReplayPreCommitVerificationError from None
    if (
        not stat.S_ISREG(pinned_stat.st_mode)
        or not stat.S_ISREG(source_stat.st_mode)
        or (pinned_stat.st_dev, pinned_stat.st_ino) != temporary_identity
        or (source_stat.st_dev, source_stat.st_ino) != temporary_identity
    ):
        raise _ReplayPreCommitVerificationError

    os.link(
        source_name,
        target_name,
        src_dir_fd=parent_fd,
        dst_dir_fd=parent_fd,
        follow_symlinks=False,
    )
    try:
        pinned_stat = os.fstat(temporary_fd)
        source_stat = os.stat(
            source_name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        target_stat = os.stat(
            target_name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
    except OSError:
        raise _ReplayPostCommitVerificationError from None
    if (
        not stat.S_ISREG(pinned_stat.st_mode)
        or not stat.S_ISREG(source_stat.st_mode)
        or not stat.S_ISREG(target_stat.st_mode)
        or (pinned_stat.st_dev, pinned_stat.st_ino) != temporary_identity
        or (source_stat.st_dev, source_stat.st_ino) != temporary_identity
        or (target_stat.st_dev, target_stat.st_ino) != temporary_identity
    ):
        raise _ReplayPostCommitVerificationError


def _replay_name_is_absent(name: str, *, parent_fd: int) -> bool:
    try:
        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return False


def _best_effort_cleanup_replay_names(
    temporary_name: str, *, parent_fd: int
) -> bool:
    names = _replay_temporary_names(temporary_name)
    for name in names:
        try:
            _unlink_replay_name(name, parent_fd=parent_fd)
        except FileNotFoundError:
            pass
        except Exception:
            pass
    fsync_succeeded = False
    try:
        _fsync_replay_parent(parent_fd)
        fsync_succeeded = True
    except Exception:
        pass
    remaining = [
        name
        for name in names
        if not _replay_name_is_absent(name, parent_fd=parent_fd)
    ]
    for name in remaining:
        try:
            _unlink_replay_name(name, parent_fd=parent_fd)
        except FileNotFoundError:
            pass
        except Exception:
            pass
    if remaining or not fsync_succeeded:
        try:
            _fsync_replay_parent(parent_fd)
            fsync_succeeded = True
        except Exception:
            pass
    return fsync_succeeded and all(
        _replay_name_is_absent(name, parent_fd=parent_fd) for name in names
    )


def _remove_replay_sidecars_for_publish(
    temporary_name: str, *, parent_fd: int
) -> None:
    for name in _replay_temporary_names(temporary_name)[1:]:
        try:
            _unlink_replay_name(name, parent_fd=parent_fd)
        except FileNotFoundError:
            pass
        except OSError:
            if not _replay_name_is_absent(name, parent_fd=parent_fd):
                raise _ReplayOperationalBoundaryError from None
    if any(
        not _replay_name_is_absent(name, parent_fd=parent_fd)
        for name in _replay_temporary_names(temporary_name)[1:]
    ):
        raise _ReplayOperationalBoundaryError


def _publication_error() -> ReplayPublicationError:
    return ReplayPublicationError(
        publication_state="target_exists_needs_review"
    )


def _publish_replay_target(
    *,
    temporary_name: str,
    target_name: str,
    target_parent: Path,
    parent_fd: int,
    parent_identity: tuple[int, int],
    temporary_identity: tuple[int, int],
    temporary_pin_fd: int,
) -> None:
    _assert_replay_parent_identity(
        target_parent,
        parent_fd=parent_fd,
        expected_identity=parent_identity,
    )
    _assert_owned_replay_temporary(
        temporary_name,
        parent_fd=parent_fd,
        temporary_identity=temporary_identity,
        temporary_fd=temporary_pin_fd,
    )
    try:
        _link_replay_name(
            temporary_name,
            target_name,
            parent_fd=parent_fd,
            temporary_fd=temporary_pin_fd,
            temporary_identity=temporary_identity,
        )
    except FileExistsError:
        _best_effort_cleanup_replay_names(
            temporary_name, parent_fd=parent_fd
        )
        raise _publication_error() from None
    except _ReplayPostCommitVerificationError:
        raise _publication_error() from None
    except _ReplayPreCommitVerificationError:
        cleanup_complete = _best_effort_cleanup_replay_names(
            temporary_name, parent_fd=parent_fd
        )
        if not cleanup_complete:
            raise _ReplayOperationalBoundaryError from None
        raise _ReplayOperationalBoundaryError from None

    try:
        os.close(temporary_pin_fd)
    except OSError:
        raise _publication_error() from None

    try:
        _fsync_replay_parent(parent_fd)
        _unlink_replay_name(temporary_name, parent_fd=parent_fd)
        _fsync_replay_parent(parent_fd)
        _assert_replay_parent_identity(
            target_parent,
            parent_fd=parent_fd,
            expected_identity=parent_identity,
        )
    except (OSError, _ReplayOperationalBoundaryError):
        raise _publication_error() from None


def _read_replay_fingerprints(
    replay_db: Path, *, run_id: str
) -> dict[str, object]:
    replay_path = replay_db.resolve(strict=True)
    if not replay_path.is_file():
        raise FileNotFoundError

    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            f"{replay_path.as_uri()}?mode=ro", uri=True, timeout=5.0
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN")
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if any(table not in tables for table in _REQUIRED_TABLES):
            raise sqlite3.DatabaseError
        for table in _REQUIRED_TABLES:
            columns = {
                str(row["name"])
                for row in connection.execute(
                    f"PRAGMA table_info({table})"
                ).fetchall()
            }
            if any(column not in columns for column in _REQUIRED_COLUMNS[table]):
                raise sqlite3.DatabaseError
        if [str(row[0]) for row in connection.execute("PRAGMA integrity_check")] != [
            "ok"
        ]:
            raise sqlite3.DatabaseError
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise sqlite3.DatabaseError
        _validate_replay_operational_boundary(connection, run_id=run_id)
        return _replay_fingerprints(connection, run_id)
    finally:
        if connection is not None:
            try:
                connection.rollback()
            finally:
                connection.close()


def _validate_replay_operational_boundary(
    connection: sqlite3.Connection, *, run_id: str
) -> None:
    manifests = connection.execute(
        "SELECT run_id, provider_request_count, provider_call, live_send "
        "FROM backfill_manifests ORDER BY run_id"
    ).fetchall()
    runs = connection.execute(
        "SELECT run_id, provider_call, live_send FROM runs ORDER BY run_id"
    ).fetchall()
    attempt_count = int(
        connection.execute("SELECT COUNT(*) FROM backfill_provider_attempts").fetchone()[0]
    )
    delivery_count = int(
        connection.execute("SELECT COUNT(*) FROM delivery_previews").fetchone()[0]
    )
    authorization_count = sum(
        int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in _OPTIONAL_AUTHORIZATION_TABLES
    )
    if (
        len(manifests) != 1
        or tuple(manifests[0]) != (run_id, 0, 0, 0)
        or len(runs) != 1
        or tuple(runs[0]) != (run_id, 0, 0)
        or attempt_count != 0
        or delivery_count != 0
        or authorization_count != 0
    ):
        raise _ReplayOperationalBoundaryError from None


def validate_backfill(
    store: BackfillStore,
    archive: PrivateRawArchive,
    *,
    run_id: str,
    seed_baseline: SeedBaseline | None,
    scope: ValidationScope = "full",
    replay_db: Path | None = None,
    run_root: Path | None = None,
) -> dict[str, object]:
    """Validate a staged backfill through read-only SQLite and archive access."""
    if scope not in {"seed", "full"}:
        raise ValueError("scope must be 'seed' or 'full'")
    if type(run_id) is not str or not run_id.strip():
        raise ValueError("run_id must be a non-empty string")
    if not isinstance(store, BackfillStore):
        raise ValueError("store must be a BackfillStore")
    if not isinstance(archive, PrivateRawArchive) or archive.read_only is not True:
        raise ValueError("validation requires a read-only raw archive")

    recorder = _Recorder(run_id)
    baseline_ok = _validate_seed_baseline(seed_baseline, recorder)
    recorder.check(
        "seed_baseline_contract",
        baseline_ok,
        _safe_sha(getattr(seed_baseline, "baseline_sha256", None)),
        _safe_sha(getattr(seed_baseline, "baseline_sha256", None)) if baseline_ok else "valid",
    )
    run_root_scan = _scan_run_root(run_root, scope=scope, recorder=recorder)

    source_path = store.path
    try:
        if _path_has_existing_symlink_component(source_path):
            raise FileNotFoundError
        resolved_source = source_path.resolve(strict=True)
        if not resolved_source.is_file():
            raise FileNotFoundError
    except (FileNotFoundError, OSError, ValueError):
        recorder.issue("source_db_unreadable", "source_unreadable", "database", run_id)
        recorder.check("source_database_readable", False, "unreadable", "readable")
        return _result(
            run_id=run_id,
            scope=scope,
            baseline=seed_baseline,
            recorder=recorder,
            replay_status="not_run" if scope == "seed" else "required",
            run_root_scan=run_root_scan,
        )

    recorder.check("source_database_readable", True, "readable", "readable")
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            f"{resolved_source.as_uri()}?mode=ro", uri=True, timeout=5.0
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN")
        context = _validate_connection(
            connection,
            archive=archive,
            run_id=run_id,
            scope=scope,
            seed_baseline=seed_baseline,
            baseline_ok=baseline_ok,
            recorder=recorder,
        )
    except (TypeError, ValueError, KeyError, IndexError, OverflowError):
        recorder.issue(
            "source_row_decode_failed",
            "schema_or_sqlite_integrity_failed",
            "database",
            run_id,
        )
        recorder.check("source_row_decode", False, "invalid", "valid")
        context = {}
    except (OSError, sqlite3.DatabaseError):
        recorder.issue("source_db_unreadable", "source_unreadable", "database", run_id)
        context = {}
    finally:
        if connection is not None:
            try:
                connection.rollback()
            finally:
                connection.close()

    replay_status = "not_run"
    replay_fingerprints: dict[str, object] | None = None
    if scope == "full":
        if replay_db is None:
            replay_status = "required"
            recorder.issue("replay_required", "replay_required", "replay", run_id)
        else:
            try:
                replay_fingerprints = _read_replay_fingerprints(
                    Path(replay_db), run_id=run_id
                )
            except _ReplayOperationalBoundaryError:
                replay_status = "failed"
                recorder.issue(
                    "replay_operational_boundary_invalid",
                    "replay_failed",
                    "replay",
                    run_id,
                )
            except (
                FileNotFoundError,
                OSError,
                sqlite3.DatabaseError,
                TypeError,
                ValueError,
                KeyError,
                IndexError,
                OverflowError,
            ):
                replay_status = "failed"
                recorder.issue(
                    "replay_unreadable", "replay_failed", "replay", run_id
                )
            else:
                source_fingerprints = context.get("source_fingerprints", {})
                if replay_fingerprints == source_fingerprints:
                    replay_status = "equivalent"
                else:
                    replay_status = "mismatch"
                    recorder.issue(
                        "replay_mismatch", "replay_mismatch", "replay", run_id
                    )
        recorder.check(
            "replay_equivalence",
            replay_status == "equivalent",
            replay_status,
            "equivalent",
        )

    return _result(
        run_id=run_id,
        scope=scope,
        baseline=seed_baseline,
        recorder=recorder,
        replay_status=replay_status,
        replay_fingerprints=replay_fingerprints,
        run_root_scan=run_root_scan,
        **context,
    )


def _validate_connection(
    conn: sqlite3.Connection,
    *,
    archive: PrivateRawArchive,
    run_id: str,
    scope: ValidationScope,
    seed_baseline: SeedBaseline | None,
    baseline_ok: bool,
    recorder: _Recorder,
) -> dict[str, object]:
    table_names = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    missing_tables = tuple(table for table in _REQUIRED_TABLES if table not in table_names)
    if missing_tables:
        for table in missing_tables:
            recorder.issue(
                "required_table_missing",
                "schema_or_sqlite_integrity_failed",
                "table",
                table,
            )
        recorder.check("required_schema", False, len(missing_tables), 0)
        return {}
    recorder.check("required_schema", True, 0, 0)

    missing_columns: list[tuple[str, str]] = []
    for table in _REQUIRED_TABLES:
        table_columns = {
            str(row["name"])
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        missing_columns.extend(
            (table, column)
            for column in _REQUIRED_COLUMNS[table]
            if column not in table_columns
        )
    if missing_columns:
        for table, column in missing_columns:
            recorder.issue(
                "required_column_missing",
                "schema_or_sqlite_integrity_failed",
                "column",
                f"{table}.{column}",
            )
        recorder.check("required_columns", False, len(missing_columns), 0)
        return {}
    recorder.check("required_columns", True, 0, 0)

    integrity_rows = [str(row[0]) for row in conn.execute("PRAGMA integrity_check")]
    integrity_ok = integrity_rows == ["ok"]
    if not integrity_ok:
        recorder.issue(
            "sqlite_integrity_failed",
            "schema_or_sqlite_integrity_failed",
            "database",
            run_id,
        )
    recorder.check(
        "sqlite_integrity", integrity_ok, "ok" if integrity_ok else "failed", "ok"
    )

    foreign_key_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    foreign_keys_ok = not foreign_key_rows
    if not foreign_keys_ok:
        recorder.issue(
            "foreign_key_check_failed",
            "schema_or_sqlite_integrity_failed",
            "database",
            run_id,
        )
    recorder.check("foreign_key_integrity", foreign_keys_ok, len(foreign_key_rows), 0)

    manifest_rows = conn.execute(
        "SELECT * FROM backfill_manifests WHERE run_id = ?", (run_id,)
    ).fetchall()
    run_rows = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchall()
    manifest = dict(manifest_rows[0]) if len(manifest_rows) == 1 else None
    run = dict(run_rows[0]) if len(run_rows) == 1 else None
    if manifest is None or run is None:
        recorder.issue(
            "manifest_run_identity_invalid",
            "manifest_or_keyword_contract_invalid",
            "run",
            run_id,
        )
    recorder.check("manifest_row_count", len(manifest_rows) == 1, len(manifest_rows), 1)
    recorder.check("run_row_count", len(run_rows) == 1, len(run_rows), 1)

    counts = {
        _COUNT_NAMES[table]: int(
            conn.execute(f"SELECT COUNT(*) FROM {table} WHERE run_id = ?", (run_id,)).fetchone()[0]
        )
        for table in _COUNT_TABLES
    }
    candidate_status_counts = _grouped_counts(
        conn,
        table="backfill_candidates",
        column="status",
        values=_CANDIDATE_STATUSES,
        run_id=run_id,
    )
    occurrence_disposition_counts = _grouped_counts(
        conn,
        table="backfill_discovery_occurrences",
        column="disposition",
        values=_DISCOVERY_DISPOSITIONS,
        run_id=run_id,
    )
    source_fingerprints = _replay_fingerprints(conn, run_id)

    manifest_context = _validate_manifest_and_run(
        manifest,
        run,
        scope=scope,
        baseline=seed_baseline,
        baseline_ok=baseline_ok,
        recorder=recorder,
    )
    artifact_rows = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM backfill_raw_artifacts WHERE run_id = ? ORDER BY artifact_id",
            (run_id,),
        )
    ]
    seed_rows = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM backfill_seed_files WHERE run_id = ? ORDER BY input_path_hash",
            (run_id,),
        )
    ]
    capture_rows = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM raw_captures WHERE run_id = ? ORDER BY raw_capture_id",
            (run_id,),
        )
    ]
    thread_rows = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM reddit_threads WHERE run_id = ? ORDER BY post_id", (run_id,)
        )
    ]
    comment_rows = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM reddit_comments WHERE run_id = ? ORDER BY comment_id", (run_id,)
        )
    ]
    analysis_rows = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM analysis_results WHERE run_id = ? ORDER BY analysis_id", (run_id,)
        )
    ]

    archive_context = _validate_archive_and_seed(
        conn,
        archive=archive,
        run_id=run_id,
        scope=scope,
        manifest=manifest,
        baseline=seed_baseline,
        baseline_ok=baseline_ok,
        artifact_rows=artifact_rows,
        seed_rows=seed_rows,
        capture_rows=capture_rows,
        thread_rows=thread_rows,
        comment_rows=comment_rows,
        analysis_rows=analysis_rows,
        recorder=recorder,
    )
    _validate_entity_parity(
        conn,
        run_id=run_id,
        manifest=manifest,
        capture_rows=capture_rows,
        thread_rows=thread_rows,
        comment_rows=comment_rows,
        analysis_rows=analysis_rows,
        recorder=recorder,
    )
    manifest_context["required_lanes"] = _validate_operational_ledgers(
        conn,
        run_id=run_id,
        scope=scope,
        manifest=manifest,
        expected_lanes=manifest_context["expected_lanes"],
        artifact_rows=artifact_rows,
        payload_by_artifact=archive_context["payload_by_artifact"],
        recorder=recorder,
    )

    delivery_count = counts["delivery_previews"]
    if delivery_count:
        recorder.issue(
            "delivery_boundary_violation",
            "live_send_boundary_violation",
            "delivery",
            run_id,
        )
    recorder.check("delivery_rows", delivery_count == 0, delivery_count, 0)

    if scope == "seed":
        prohibited_counts = {
            "provider_attempts": counts["provider_attempts"],
            "checkpoints": counts["checkpoints"],
            "candidates": counts["candidates"],
            "discovery_occurrences": counts["discovery_occurrences"],
            "detail_batches": counts["detail_batches"],
            "detail_batch_members": counts["detail_batch_members"],
            "provider_artifacts": sum(
                1 for row in artifact_rows if row["lane_type"] != "seed"
            ),
        }
        for name, count in prohibited_counts.items():
            if count:
                recorder.issue(
                    "seed_contains_provider_state", "seed_incomplete", name, run_id
                )
        recorder.check(
            "seed_provider_state",
            not any(prohibited_counts.values()),
            sum(prohibited_counts.values()),
            0,
        )

    return {
        "source_provider_call": bool(manifest and manifest.get("provider_call") == 1),
        "counts": counts,
        "candidate_status_counts": candidate_status_counts,
        "occurrence_disposition_counts": occurrence_disposition_counts,
        "required_lanes": manifest_context["required_lanes"],
        "source_fingerprints": source_fingerprints,
        "known_seed_partial_count": archive_context["known_seed_partial_count"],
        "known_seed_partial_post_ids_sha256": archive_context[
            "known_seed_partial_post_ids_sha256"
        ],
    }


def _validate_seed_baseline(
    baseline: SeedBaseline | None, recorder: _Recorder
) -> bool:
    if type(baseline) is not SeedBaseline:
        recorder.issue(
            "seed_baseline_invalid",
            "manifest_or_keyword_contract_invalid",
            "seed_baseline",
            recorder.run_id,
        )
        return False

    values = {
        name: getattr(baseline, name) for name in SeedBaseline.__dataclass_fields__
    }
    sha_names = (
        "source_inventory_sha256",
        "known_partial_post_ids_sha256",
        "reviewed_search_terms_sha256",
        "reviewed_subreddits_sha256",
        "baseline_sha256",
    )
    json_types_ok = (
        type(baseline.schema_version) is str
        and all(type(values[name]) is int for name in _SEED_NUMERIC_CONTRACT)
        and all(type(values[name]) is str for name in sha_names)
        and type(baseline.reviewed_subreddits) is tuple
        and all(type(value) is str for value in baseline.reviewed_subreddits)
    )
    if not json_types_ok:
        recorder.issue(
            "seed_baseline_invalid",
            "manifest_or_keyword_contract_invalid",
            "seed_baseline",
            recorder.run_id,
        )
        return False

    valid = True
    if baseline.schema_version != "momcozy_seed_baseline_v1":
        valid = False
    for name, expected in _SEED_NUMERIC_CONTRACT.items():
        value = values[name]
        if type(value) is not int or value < 0 or value != expected:
            valid = False
    for name in sha_names:
        if not _is_sha(values[name]):
            valid = False
    if (
        type(baseline.reviewed_subreddits) is not tuple
        or not baseline.reviewed_subreddits
        or any(
            type(value) is not str or not value.strip()
            for value in baseline.reviewed_subreddits
        )
        or len(set(baseline.reviewed_subreddits))
        != len(baseline.reviewed_subreddits)
    ):
        valid = False

    equations_ok = (
        baseline.files_total
        == baseline.files_imported
        + baseline.files_outside_window
        + baseline.files_excluded
        + baseline.files_duplicate
        + baseline.parse_errors
        and baseline.threads
        == baseline.coverage_full
        + baseline.coverage_partial
        + baseline.coverage_post_only
        and baseline.analyses == baseline.threads + baseline.comments
        and baseline.coverage_partial == 3
        and baseline.coverage_post_only == 0
    )
    valid = valid and equations_ok

    payload = dict(values)
    payload.pop("baseline_sha256")
    expected_baseline_hash = _canonical_sha(payload, sort_keys=True)
    if baseline.baseline_sha256 != expected_baseline_hash:
        valid = False
    if _is_sha(baseline.reviewed_subreddits_sha256):
        if baseline.reviewed_subreddits_sha256 != _canonical_sha(
            list(baseline.reviewed_subreddits)
        ):
            valid = False

    if not valid:
        recorder.issue(
            "seed_baseline_invalid",
            "manifest_or_keyword_contract_invalid",
            "seed_baseline",
            recorder.run_id,
        )
    return valid


def _validate_manifest_and_run(
    manifest: dict[str, object] | None,
    run: dict[str, object] | None,
    *,
    scope: ValidationScope,
    baseline: SeedBaseline | None,
    baseline_ok: bool,
    recorder: _Recorder,
) -> dict[str, object]:
    expected_lanes: tuple[tuple[str, str], ...] = ()
    required_lanes: list[dict[str, object]] = []
    if manifest is None or run is None:
        return {"expected_lanes": expected_lanes, "required_lanes": required_lanes}

    identity_ok = (
        manifest["run_id"] == run["run_id"] == recorder.run_id
        and manifest["status"] == run["status"]
        and manifest["window_start_utc"] == run["window_start_utc"]
        and manifest["effective_end_utc"] == run["window_end_utc"]
        and manifest["provider_call"] == run["provider_call"]
        and manifest["live_send"] == run["live_send"]
    )
    if not identity_ok:
        recorder.issue(
            "manifest_run_identity_invalid",
            "manifest_or_keyword_contract_invalid",
            "run",
            recorder.run_id,
        )
    recorder.check("manifest_run_identity", identity_ok, identity_ok, True)

    windows_ok = False
    try:
        start = datetime.fromisoformat(str(manifest["window_start_utc"]))
        requested_end = datetime.fromisoformat(str(manifest["requested_end_utc"]))
        effective_end = datetime.fromisoformat(str(manifest["effective_end_utc"]))
        windows_ok = (
            start.tzinfo is not None
            and requested_end.tzinfo is not None
            and effective_end.tzinfo is not None
            and start < effective_end <= requested_end
        )
    except (TypeError, ValueError):
        pass
    if not windows_ok:
        recorder.issue(
            "manifest_window_invalid",
            "manifest_or_keyword_contract_invalid",
            "run",
            recorder.run_id,
        )
    recorder.check("manifest_window", windows_ok, windows_ok, True)

    live_flags_ok = manifest["live_send"] == 0 and run["live_send"] == 0
    if not live_flags_ok:
        recorder.issue(
            "live_send_flag_set",
            "live_send_boundary_violation",
            "run",
            recorder.run_id,
        )
    recorder.check("live_send_flags", live_flags_ok, live_flags_ok, True)

    expected_status = "seed_complete" if scope == "seed" else None
    if expected_status is not None and (
        manifest["status"] != expected_status or run["status"] != expected_status
    ):
        recorder.issue(
            "seed_status_invalid", "seed_incomplete", "run", recorder.run_id
        )
    recorder.check(
        "scope_status",
        expected_status is None
        or (manifest["status"] == expected_status and run["status"] == expected_status),
        str(manifest["status"]),
        expected_status or "validated_full_status",
    )

    search_terms = _json_string_list(manifest.get("search_terms_json"))
    subreddits = _json_string_list(manifest.get("subreddits_json"))
    sweep = manifest.get("include_subreddit_sweep") == 1
    search_terms_ok = search_terms == tuple(DEFAULT_TIKHUB_SEARCH_TERMS)
    if not search_terms_ok:
        recorder.issue(
            "search_terms_invalid",
            "manifest_or_keyword_contract_invalid",
            "search_terms",
            recorder.run_id,
        )
    recorder.check(
        "reviewed_search_terms",
        search_terms_ok,
        _canonical_sha(list(search_terms)) if search_terms is not None else "invalid",
        _canonical_sha(list(DEFAULT_TIKHUB_SEARCH_TERMS)),
    )

    keyword_ok = manifest.get("keyword_config_sha256") == keyword_rules_sha256()
    if not keyword_ok:
        recorder.issue(
            "keyword_config_mismatch",
            "manifest_or_keyword_contract_invalid",
            "keyword_config",
            recorder.run_id,
        )
    recorder.check(
        "keyword_config",
        keyword_ok,
        _safe_sha(manifest.get("keyword_config_sha256")),
        keyword_rules_sha256(),
    )

    baseline_search_ok = baseline_ok and bool(
        baseline
        and baseline.reviewed_search_terms_sha256
        == _canonical_sha(list(DEFAULT_TIKHUB_SEARCH_TERMS))
    )
    if baseline_ok and not baseline_search_ok:
        recorder.issue(
            "reviewed_search_terms_hash_mismatch",
            "manifest_or_keyword_contract_invalid",
            "seed_baseline",
            recorder.run_id,
        )
    recorder.check(
        "baseline_search_terms",
        baseline_search_ok,
        _safe_sha(getattr(baseline, "reviewed_search_terms_sha256", None)),
        _canonical_sha(list(DEFAULT_TIKHUB_SEARCH_TERMS)),
    )

    subreddits_ok = subreddits is not None and bool(subreddits)
    if sweep:
        subreddits_ok = bool(
            baseline_ok
            and baseline
            and subreddits == baseline.reviewed_subreddits
            and baseline.reviewed_subreddits_sha256
            == _canonical_sha(list(subreddits or ()))
        )
    if not subreddits_ok:
        recorder.issue(
            "subreddits_invalid",
            "manifest_or_keyword_contract_invalid",
            "subreddits",
            recorder.run_id,
        )
    recorder.check("reviewed_subreddits", subreddits_ok, subreddits_ok, True)

    required_hash_ok = False
    if search_terms is not None and subreddits is not None:
        try:
            expected_lanes = required_lanes_snapshot(
                search_terms=search_terms,
                subreddits=subreddits,
                include_subreddit_sweep=sweep,
            )
            expected_hash = required_lanes_sha256(
                search_terms=search_terms,
                subreddits=subreddits,
                include_subreddit_sweep=sweep,
            )
            required_hash_ok = manifest.get("required_lanes_sha256") == expected_hash
        except ValueError:
            expected_lanes = ()
            expected_hash = "invalid"
    else:
        expected_hash = "invalid"
    if not required_hash_ok:
        recorder.issue(
            "required_lanes_hash_mismatch",
            "manifest_or_keyword_contract_invalid",
            "required_lanes",
            recorder.run_id,
        )
    recorder.check(
        "required_lanes_hash",
        required_hash_ok,
        _safe_sha(manifest.get("required_lanes_sha256")),
        expected_hash,
    )

    required_lanes = [
        {"lane_type": lane_type, "lane_key_sha256": sha256(lane_key.encode()).hexdigest(), "status": "not_run"}
        for lane_type, lane_key in expected_lanes
    ]
    return {"expected_lanes": expected_lanes, "required_lanes": required_lanes}


def _validate_archive_and_seed(
    conn: sqlite3.Connection,
    *,
    archive: PrivateRawArchive,
    run_id: str,
    scope: ValidationScope,
    manifest: dict[str, object] | None,
    baseline: SeedBaseline | None,
    baseline_ok: bool,
    artifact_rows: list[dict[str, object]],
    seed_rows: list[dict[str, object]],
    capture_rows: list[dict[str, object]],
    thread_rows: list[dict[str, object]],
    comment_rows: list[dict[str, object]],
    analysis_rows: list[dict[str, object]],
    recorder: _Recorder,
) -> dict[str, object]:
    capture_by_id = {str(row["raw_capture_id"]): row for row in capture_rows}
    artifact_by_id = {str(row["artifact_id"]): row for row in artifact_rows}
    ledger_by_artifact = {str(row["artifact_id"]): row for row in seed_rows}
    payload_by_artifact: dict[str, bytes] = {}
    tracked_paths: set[str] = set()
    archive_issue_count = 0

    for row in artifact_rows:
        artifact_id = str(row["artifact_id"])
        try:
            artifact = RawArtifactMetadata(**row)
            if not _artifact_metadata_types_valid(artifact):
                raise ValueError("invalid raw artifact metadata")
            payload = archive.read_verified(artifact)
            expected_artifact_id = "raw_artifact_" + sha256(
                artifact.relative_path.encode()
            ).hexdigest()[:24]
            expected_relative = (
                Path(artifact.run_id)
                / artifact.artifact_kind
                / artifact.lane_key_hash[:16]
                / (
                    f"page-{artifact.page_number or 0:06d}-{artifact.identity_hash[:24]}-"
                    f"{artifact.payload_sha256[:16]}.json.gz"
                )
            ).as_posix()
        except (ArchiveIntegrityError, OverflowError, TypeError, ValueError):
            recorder.issue(
                "archive_integrity_failed",
                "archive_integrity_failed",
                "raw_artifact",
                artifact_id,
            )
            archive_issue_count += 1
            continue
        payload_by_artifact[artifact_id] = payload
        tracked_paths.add(artifact.relative_path)

        metadata_ok = (
            artifact.run_id == run_id
            and artifact.artifact_id == expected_artifact_id
            and artifact.relative_path == expected_relative
            and _is_sha(artifact.lane_key_hash)
            and _is_sha(artifact.identity_hash)
            and artifact.source_method
            in {
                "historical_seed",
                "tikhub_dynamic_search",
                "tikhub_subreddit_feed",
                "tikhub_detail",
                "tikhub_comments",
            }
        )
        if not metadata_ok:
            recorder.issue(
                "artifact_metadata_mismatch",
                "archive_integrity_failed",
                "raw_artifact",
                artifact_id,
            )
            archive_issue_count += 1

        capture = capture_by_id.get(artifact.raw_capture_id)
        if not _capture_matches_artifact(capture, artifact):
            recorder.issue(
                "artifact_capture_mismatch",
                "lineage_invalid",
                "raw_artifact",
                artifact_id,
            )

    artifact_capture_ids = {str(row["raw_capture_id"]) for row in artifact_rows}
    capture_ids = set(capture_by_id)
    if artifact_capture_ids != capture_ids:
        recorder.issue(
            "artifact_capture_mismatch",
            "lineage_invalid",
            "raw_capture",
            run_id,
        )

    try:
        actual_archive_files = _archive_json_gzip_files(archive.root, run_id)
    except ArchiveIntegrityError:
        recorder.issue(
            "archive_inventory_unreadable",
            "archive_integrity_failed",
            "archive",
            run_id,
        )
        archive_issue_count += 1
        actual_archive_files = set(tracked_paths)
    untracked = actual_archive_files - tracked_paths
    missing = tracked_paths - actual_archive_files
    for relative_path in sorted(untracked):
        recorder.issue(
            "untracked_archive_file",
            "archive_integrity_failed",
            "raw_artifact",
            relative_path,
        )
        archive_issue_count += 1
    for relative_path in sorted(missing):
        recorder.issue(
            "archive_integrity_failed",
            "archive_integrity_failed",
            "raw_artifact",
            relative_path,
        )
        archive_issue_count += 1
    recorder.check("archive_integrity", archive_issue_count == 0, archive_issue_count, 0)

    seed_artifacts = [row for row in artifact_rows if row["lane_type"] == "seed"]
    ledger_artifact_ids = {str(row["artifact_id"]) for row in seed_rows}
    seed_artifact_ids = {str(row["artifact_id"]) for row in seed_artifacts}
    one_to_one_ok = ledger_artifact_ids == seed_artifact_ids and len(seed_rows) == len(
        seed_artifacts
    )
    if not one_to_one_ok:
        recorder.issue(
            "seed_artifact_ledger_mismatch",
            "seed_incomplete",
            "seed_ledger",
            run_id,
        )
    recorder.check(
        "seed_artifact_ledger", one_to_one_ok, len(ledger_artifact_ids ^ seed_artifact_ids), 0
    )

    outcome_counts = {
        outcome: sum(1 for row in seed_rows if row["outcome"] == outcome)
        for outcome in (
            "imported",
            "outside_window",
            "excluded",
            "duplicate",
            "parse_error",
        )
    }
    inventory = sorted(
        [[str(row["input_path_hash"]), str(row["payload_sha256"])] for row in seed_rows]
    )
    inventory_hash = _canonical_sha(inventory)
    if baseline_ok and baseline and inventory_hash != baseline.source_inventory_sha256:
        recorder.issue(
            "seed_inventory_mismatch",
            "seed_incomplete",
            "seed_inventory",
            run_id,
        )

    expected_seed_threads: dict[str, dict[str, object]] = {}
    expected_seed_comments: dict[str, dict[str, object]] = {}
    expected_seed_analyses: dict[str, dict[str, object]] = {}
    adapter = BrowserJsonAdapter()
    window_start, effective_end = _manifest_window(manifest)
    imported_posts = {
        str(row["post_id"]) for row in seed_rows if row["outcome"] == "imported"
    }

    for ledger in seed_rows:
        artifact_id = str(ledger["artifact_id"])
        artifact_row = artifact_by_id.get(artifact_id)
        payload = payload_by_artifact.get(artifact_id)
        if artifact_row is None or payload is None:
            continue
        input_path_hash = str(ledger["input_path_hash"])
        payload_sha256 = str(ledger["payload_sha256"])
        seed_metadata_ok = (
            _is_sha(input_path_hash)
            and _is_sha(payload_sha256)
            and artifact_row["artifact_kind"] == "seed"
            and artifact_row["lane_type"] == "seed"
            and artifact_row["lane_key_hash"] == sha256(input_path_hash.encode()).hexdigest()
            and artifact_row["identity_hash"] == sha256(payload_sha256.encode()).hexdigest()
            and artifact_row["payload_sha256"] == payload_sha256
            and artifact_row["source_url"] == f"seed://{input_path_hash}"
            and artifact_row["source_endpoint"] == "seed_file"
            and artifact_row["source_method"] == "historical_seed"
            and artifact_row["parser_kind"] == "seed_browser_thread"
            and artifact_row["page_number"] == 0
            and artifact_row["request_cursor"] is None
            and artifact_row["response_cursor"] is None
        )
        if not seed_metadata_ok:
            recorder.issue(
                "seed_artifact_metadata_mismatch",
                "archive_integrity_failed",
                "seed_file",
                input_path_hash,
            )

        try:
            parsed = adapter.parse_thread_payload(
                json.loads(payload.decode("utf-8")),
                run_id=run_id,
                raw_capture_id=str(artifact_row["raw_capture_id"]),
                source_url=str(artifact_row["source_url"]),
            )
        except Exception as exc:
            reproducible = (
                ledger["outcome"] == "parse_error"
                and ledger["error_class"] == type(exc).__name__
            )
            if not reproducible:
                recorder.issue(
                    "seed_raw_reparse_mismatch",
                    "seed_incomplete",
                    "seed_file",
                    input_path_hash,
                )
            continue

        thread = parsed.thread
        comments = tuple(parsed.comments)
        combined = "\n".join(
            (thread.title, thread.selftext, *(comment.body for comment in comments))
        )
        combined_analysis = analyze_text(combined)
        in_window = bool(
            window_start is not None
            and effective_end is not None
            and window_start <= thread.created_at_utc < effective_end
        )
        expected_outcome = (
            "outside_window"
            if not in_window
            else "excluded"
            if not combined_analysis.keyword_match.is_relevant
            else "duplicate"
            if thread.post_id in imported_posts and ledger["outcome"] != "imported"
            else "imported"
        )
        if ledger["outcome"] != expected_outcome or ledger["post_id"] != thread.post_id:
            recorder.issue(
                "seed_raw_reparse_mismatch",
                "seed_incomplete",
                "seed_file",
                input_path_hash,
            )
            continue
        if expected_outcome != "imported":
            continue

        thread = replace(
            thread, matched_keywords=combined_analysis.keyword_match.matched_terms
        )
        expected_seed_threads[thread.post_id] = thread.as_record()
        for comment in comments:
            expected_seed_comments[comment.comment_id] = _comment_record(comment)
        expected_seed_analyses[f"analysis_post_{thread.post_id}"] = _analysis_record(
            analysis_id=f"analysis_post_{thread.post_id}",
            run_id=run_id,
            source_type="post",
            source_id=thread.post_id,
            text=f"{thread.title}\n{thread.selftext}",
        )
        for comment in comments:
            analysis_id = f"analysis_comment_{comment.comment_id}"
            expected_seed_analyses[analysis_id] = _analysis_record(
                analysis_id=analysis_id,
                run_id=run_id,
                source_type="comment",
                source_id=comment.comment_id,
                text=comment.body,
            )

    actual_threads = {str(row["post_id"]): row for row in thread_rows}
    actual_comments = {str(row["comment_id"]): row for row in comment_rows}
    actual_analyses = {str(row["analysis_id"]): row for row in analysis_rows}
    for table_name, expected_rows, actual_rows in (
        ("thread", expected_seed_threads, actual_threads),
        ("comment", expected_seed_comments, actual_comments),
        ("analysis", expected_seed_analyses, actual_analyses),
    ):
        if scope == "seed" and set(expected_rows) != set(actual_rows):
            recorder.issue(
                "seed_entity_set_mismatch",
                "entity_or_analysis_parity_invalid",
                table_name,
                run_id,
            )
        for identity, expected in expected_rows.items():
            actual = actual_rows.get(identity)
            if actual is None or any(actual.get(key) != value for key, value in expected.items()):
                recorder.issue(
                    "seed_entity_content_mismatch",
                    "entity_or_analysis_parity_invalid",
                    table_name,
                    identity,
                )

    partial_ids = sorted(
        str(row["post_id"])
        for row in thread_rows
        if row["coverage_grade"] == "partial"
        and capture_by_id.get(str(row["raw_capture_id"]), {}).get("source_method")
        == "historical_seed"
    )
    partial_hash = _canonical_sha(partial_ids)
    if baseline_ok and baseline and (
        len(partial_ids) != baseline.coverage_partial
        or partial_hash != baseline.known_partial_post_ids_sha256
    ):
        recorder.issue(
            "known_seed_partial_mismatch",
            "seed_incomplete",
            "seed_partial",
            run_id,
        )

    actual_numeric = {
        "files_total": len(seed_rows),
        "files_imported": outcome_counts["imported"],
        "files_outside_window": outcome_counts["outside_window"],
        "files_excluded": outcome_counts["excluded"],
        "files_duplicate": outcome_counts["duplicate"],
        "parse_errors": outcome_counts["parse_error"],
        "threads": len(thread_rows),
        "comments": len(comment_rows),
        "analyses": len(analysis_rows),
        "coverage_full": sum(1 for row in thread_rows if row["coverage_grade"] == "full"),
        "coverage_partial": sum(
            1 for row in thread_rows if row["coverage_grade"] == "partial"
        ),
        "coverage_post_only": sum(
            1 for row in thread_rows if row["coverage_grade"] == "post_only"
        ),
    }
    seed_counts_ok = baseline_ok and baseline is not None and all(
        actual_numeric[name] == getattr(baseline, name) for name in actual_numeric
    )
    if baseline_ok and not seed_counts_ok:
        recorder.issue(
            "seed_counts_mismatch", "seed_incomplete", "seed_counts", run_id
        )
    if actual_numeric["parse_errors"]:
        recorder.issue(
            "seed_parse_errors", "seed_incomplete", "seed_counts", run_id
        )
    recorder.check(
        "seed_numeric_contract",
        seed_counts_ok,
        _canonical_sha(actual_numeric, sort_keys=True),
        _canonical_sha(_SEED_NUMERIC_CONTRACT, sort_keys=True),
    )
    recorder.check(
        "seed_inventory",
        bool(baseline_ok and baseline and inventory_hash == baseline.source_inventory_sha256),
        inventory_hash,
        _safe_sha(getattr(baseline, "source_inventory_sha256", None)),
    )
    recorder.check(
        "known_seed_partials",
        bool(
            baseline_ok
            and baseline
            and len(partial_ids) == baseline.coverage_partial
            and partial_hash == baseline.known_partial_post_ids_sha256
        ),
        partial_hash,
        _safe_sha(getattr(baseline, "known_partial_post_ids_sha256", None)),
    )
    return {
        "known_seed_partial_count": len(partial_ids),
        "known_seed_partial_post_ids_sha256": partial_hash,
        "payload_by_artifact": payload_by_artifact,
    }


def _validate_entity_parity(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    manifest: dict[str, object] | None,
    capture_rows: list[dict[str, object]],
    thread_rows: list[dict[str, object]],
    comment_rows: list[dict[str, object]],
    analysis_rows: list[dict[str, object]],
    recorder: _Recorder,
) -> None:
    global_capture_runs = {
        str(row["raw_capture_id"]): str(row["run_id"])
        for row in conn.execute("SELECT raw_capture_id, run_id FROM raw_captures")
    }
    threads = {str(row["post_id"]): row for row in thread_rows}
    comments = {str(row["comment_id"]): row for row in comment_rows}
    analyses = {str(row["analysis_id"]): row for row in analysis_rows}
    window_start, effective_end = _manifest_window(manifest)

    for thread in thread_rows:
        post_id = str(thread["post_id"])
        capture_run = global_capture_runs.get(str(thread["raw_capture_id"]))
        if capture_run != run_id:
            recorder.issue(
                "raw_cross_run", "lineage_invalid", "thread", post_id
            )
        try:
            created_at = datetime.fromisoformat(str(thread["created_at_utc"]))
            in_window = bool(
                window_start is not None
                and effective_end is not None
                and created_at.tzinfo is not None
                and window_start <= created_at < effective_end
            )
        except (TypeError, ValueError):
            in_window = False
        if not in_window:
            recorder.issue(
                "thread_outside_window",
                "entity_or_analysis_parity_invalid",
                "thread",
                post_id,
            )

        actual_comment_count = sum(
            1 for comment in comment_rows if comment["post_id"] == post_id
        )
        if thread["parsed_comment_count"] != actual_comment_count:
            recorder.issue(
                "parsed_comment_count_mismatch",
                "entity_or_analysis_parity_invalid",
                "thread",
                post_id,
            )
        expected_coverage = (
            "partial"
            if int(thread["more_node_count"]) > 0
            else "post_only"
            if actual_comment_count == 0
            and thread["num_comments_reported"] is not None
            and int(thread["num_comments_reported"]) > 0
            else "full"
        )
        if thread["coverage_grade"] != expected_coverage:
            recorder.issue(
                "coverage_mismatch",
                "entity_or_analysis_parity_invalid",
                "thread",
                post_id,
            )
        if thread["coverage_grade"] == "post_only":
            recorder.issue(
                "post_only_coverage",
                "entity_or_analysis_parity_invalid",
                "thread",
                post_id,
            )

        analysis_id = f"analysis_post_{post_id}"
        expected_analysis = _analysis_record(
            analysis_id=analysis_id,
            run_id=run_id,
            source_type="post",
            source_id=post_id,
            text=f"{thread['title']}\n{thread['selftext']}",
        )
        actual_analysis = analyses.get(analysis_id)
        if actual_analysis is None or any(
            actual_analysis.get(key) != value for key, value in expected_analysis.items()
        ):
            recorder.issue(
                "analysis_parity_mismatch",
                "entity_or_analysis_parity_invalid",
                "thread",
                post_id,
            )

    for comment in comment_rows:
        comment_id = str(comment["comment_id"])
        if comment["post_id"] not in threads:
            recorder.issue(
                "orphan_comment", "lineage_invalid", "comment", comment_id
            )
        capture_run = global_capture_runs.get(str(comment["raw_capture_id"]))
        if capture_run != run_id:
            recorder.issue(
                "raw_cross_run", "lineage_invalid", "comment", comment_id
            )
        analysis_id = f"analysis_comment_{comment_id}"
        expected_analysis = _analysis_record(
            analysis_id=analysis_id,
            run_id=run_id,
            source_type="comment",
            source_id=comment_id,
            text=str(comment["body"]),
        )
        actual_analysis = analyses.get(analysis_id)
        if actual_analysis is None or any(
            actual_analysis.get(key) != value for key, value in expected_analysis.items()
        ):
            recorder.issue(
                "analysis_parity_mismatch",
                "entity_or_analysis_parity_invalid",
                "comment",
                comment_id,
            )

    expected_analysis_ids = {
        *(f"analysis_post_{post_id}" for post_id in threads),
        *(f"analysis_comment_{comment_id}" for comment_id in comments),
    }
    if set(analyses) != expected_analysis_ids:
        recorder.issue(
            "analysis_parity_mismatch",
            "entity_or_analysis_parity_invalid",
            "analysis",
            run_id,
        )
    for analysis in analysis_rows:
        identity = str(analysis["analysis_id"])
        if analysis["provider_call"] != 0:
            recorder.issue(
                "analysis_provider_call",
                "entity_or_analysis_parity_invalid",
                "analysis",
                identity,
            )
        if analysis["run_id"] != run_id:
            recorder.issue(
                "analysis_parity_mismatch",
                "entity_or_analysis_parity_invalid",
                "analysis",
                identity,
            )
        if analysis["source_type"] == "post":
            source_ok = analysis["source_id"] in threads
        elif analysis["source_type"] == "comment":
            source_ok = analysis["source_id"] in comments
        else:
            source_ok = False
        if not source_ok:
            recorder.issue(
                "analysis_parity_mismatch",
                "entity_or_analysis_parity_invalid",
                "analysis",
                identity,
            )

    parity_issues = {
        "analysis_parity_mismatch",
        "analysis_provider_call",
        "parsed_comment_count_mismatch",
        "coverage_mismatch",
        "thread_outside_window",
        "post_only_coverage",
    }
    current_codes = {issue[1] for issue in recorder._issues}
    recorder.check(
        "entity_analysis_parity",
        not bool(current_codes & parity_issues),
        len(current_codes & parity_issues),
        0,
    )


def _validate_operational_ledgers(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    scope: ValidationScope,
    manifest: dict[str, object] | None,
    expected_lanes: tuple[tuple[str, str], ...],
    artifact_rows: list[dict[str, object]],
    payload_by_artifact: dict[str, bytes],
    recorder: _Recorder,
) -> list[dict[str, object]]:
    checkpoints = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM backfill_checkpoints WHERE run_id=? "
            "ORDER BY lane_type, lane_key",
            (run_id,),
        )
    ]
    occurrences = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM backfill_discovery_occurrences WHERE run_id=? "
            "ORDER BY lane_type, lane_key, page_number, ordinal",
            (run_id,),
        )
    ]
    candidates = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM backfill_candidates WHERE run_id=? ORDER BY post_id",
            (run_id,),
        )
    ]
    attempts = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM backfill_provider_attempts WHERE run_id=? ORDER BY request_number",
            (run_id,),
        )
    ]
    detail_batches = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM backfill_detail_batches WHERE run_id=? "
            "ORDER BY batch_number, batch_id",
            (run_id,),
        )
    ]
    detail_members = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM backfill_detail_batch_members WHERE run_id=? "
            "ORDER BY batch_id, ordinal",
            (run_id,),
        )
    ]

    authorization_ledger_ok = manifest is not None
    try:
        authorization_rows = _authorization_ledger_rows(conn, run_id=run_id)
        if manifest is None:
            raise _ReplayDataError("budget_extension_ledger_invalid")
        _validated_budget_extension_boundaries(
            manifest,
            authorization_rows["backfill_budget_extensions"],
        )
        _validate_hydration_resume_ledgers(
            run_id=run_id,
            extension_rows=authorization_rows["backfill_budget_extensions"],
            resume_rows=authorization_rows["backfill_hydration_resumes"],
            source_rows={
                "backfill_candidates": candidates,
                "backfill_detail_batches": detail_batches,
                "backfill_detail_batch_members": detail_members,
            },
        )
        _validate_collection_resume_ledgers(
            manifest=manifest,
            resume_rows=authorization_rows["backfill_collection_resumes"],
        )
    except _ReplayDataError as exc:
        authorization_ledger_ok = False
        recorder.issue(
            exc.stop_reason,
            "operational_accounting_invalid",
            "authorization_ledger",
            run_id,
        )
    recorder.check(
        "authorization_ledgers",
        authorization_ledger_ok,
        "valid" if authorization_ledger_ok else "invalid",
        "valid",
    )

    invalid_occurrence_count = sum(
        1 for row in occurrences if row["disposition"] == "invalid"
    )
    invalid_occurrences_ok = scope != "full" or invalid_occurrence_count == 0
    if not invalid_occurrences_ok:
        recorder.issue(
            "invalid_discovery_occurrence",
            "operational_accounting_invalid",
            "run",
            run_id,
        )
    recorder.check(
        "invalid_discovery_occurrences",
        invalid_occurrences_ok,
        invalid_occurrence_count,
        0,
    )

    checkpoint_by_lane = {
        (str(row["lane_type"]), str(row["lane_key"])): row for row in checkpoints
    }
    expected_lane_set = set(expected_lanes)
    required_lane_report = [
        {
            "lane_type": lane_type,
            "lane_key_sha256": sha256(lane_key.encode()).hexdigest(),
            "status": "not_run" if scope == "seed" else (
                str(checkpoint_by_lane[(lane_type, lane_key)]["status"])
                if (lane_type, lane_key) in checkpoint_by_lane
                else "missing"
            ),
        }
        for lane_type, lane_key in expected_lanes
    ]
    for checkpoint in checkpoints:
        lane = (str(checkpoint["lane_type"]), str(checkpoint["lane_key"]))
        if checkpoint["lane_type"] in {"dynamic_search", "subreddit_feed"} and lane not in expected_lane_set:
            recorder.issue(
                "unconfigured_lane",
                "required_lanes_incomplete",
                "lane",
                f"{lane[0]}:{lane[1]}",
            )

    for checkpoint in checkpoints:
        if checkpoint["lane_type"] not in {"dynamic_search", "subreddit_feed"}:
            continue
        lane_occurrences = [
            row
            for row in occurrences
            if row["lane_type"] == checkpoint["lane_type"]
            and row["lane_key"] == checkpoint["lane_key"]
        ]
        new_count = sum(
            1 for row in lane_occurrences if row["disposition"] == "new_candidate"
        )
        if (
            int(checkpoint["discovered_count"]) != len(lane_occurrences)
            or int(checkpoint["unique_count"]) != new_count
        ):
            recorder.issue(
                "occurrence_equation_mismatch",
                "operational_accounting_invalid",
                "lane",
                f"{checkpoint['lane_type']}:{checkpoint['lane_key']}",
            )

    artifact_by_id = {str(row["artifact_id"]): row for row in artifact_rows}
    for occurrence in occurrences:
        artifact = artifact_by_id.get(str(occurrence["raw_artifact_id"]))
        occurrence_artifact_ok = bool(
            artifact
            and artifact["run_id"] == run_id
            and artifact["lane_type"] == occurrence["lane_type"]
            and artifact["lane_key_hash"]
            == sha256(str(occurrence["lane_key"]).encode()).hexdigest()
            and artifact["page_number"] == occurrence["page_number"]
        )
        if not occurrence_artifact_ok:
            recorder.issue(
                "occurrence_artifact_mismatch",
                "operational_accounting_invalid",
                "occurrence",
                (
                    f"{occurrence['lane_type']}:{occurrence['lane_key']}:"
                    f"{occurrence['page_number']}:{occurrence['ordinal']}"
                ),
            )

    new_occurrences_by_post: dict[str, list[dict[str, object]]] = {}
    for occurrence in occurrences:
        if occurrence["disposition"] == "new_candidate" and occurrence["post_id"]:
            new_occurrences_by_post.setdefault(str(occurrence["post_id"]), []).append(
                occurrence
            )
    candidate_by_post = {str(row["post_id"]): row for row in candidates}
    if set(new_occurrences_by_post) != set(candidate_by_post):
        recorder.issue(
            "candidate_first_occurrence_mismatch",
            "operational_accounting_invalid",
            "candidate",
            run_id,
        )
    for post_id, candidate in candidate_by_post.items():
        first_rows = new_occurrences_by_post.get(post_id, [])
        if len(first_rows) != 1:
            recorder.issue(
                "candidate_first_occurrence_mismatch",
                "operational_accounting_invalid",
                "candidate",
                post_id,
            )
            continue
        first = first_rows[0]
        if any(
            (
                candidate["first_lane_type"] != first["lane_type"],
                candidate["first_lane_key"] != first["lane_key"],
                candidate["first_discovered_at_utc"] != first["discovered_at_utc"],
                candidate["source_url"] != first["source_url"],
                candidate["post_created_at_utc"] != first["post_created_at_utc"],
                candidate["raw_artifact_id"] != first["raw_artifact_id"],
            )
        ):
            recorder.issue(
                "candidate_first_occurrence_mismatch",
                "operational_accounting_invalid",
                "candidate",
                post_id,
            )

    attempt_numbers = [int(row["request_number"]) for row in attempts]
    manifest_count = int(manifest["provider_request_count"]) if manifest else 0
    max_requests = int(manifest["max_provider_requests"]) if manifest else 0
    attempts_ok = (
        len(attempts) == manifest_count
        and (max(attempt_numbers, default=0) == manifest_count)
        and attempt_numbers == list(range(1, manifest_count + 1))
        and manifest_count <= max_requests
    )
    for attempt in attempts:
        status = attempt["status"]
        reserved_at = attempt["reserved_at_utc"]
        sent_at = attempt["sent_at_utc"]
        completed_at = attempt["completed_at_utc"]
        error_class = attempt["error_class"]
        shape_ok = bool(reserved_at)
        if status == "reserved":
            shape_ok = (
                shape_ok
                and sent_at is None
                and completed_at is None
                and attempt["http_status"] is None
                and error_class is None
            )
        elif status == "sent":
            shape_ok = (
                shape_ok
                and sent_at is not None
                and completed_at is None
                and attempt["http_status"] is None
                and error_class is None
            )
        elif status == "succeeded":
            shape_ok = shape_ok and sent_at is not None and completed_at is not None and error_class is None
        elif status == "failed":
            shape_ok = (
                shape_ok
                and sent_at is not None
                and completed_at is not None
                and type(error_class) is str
                and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", error_class)
                is not None
            )
        else:
            shape_ok = False
        attempts_ok = attempts_ok and shape_ok
        if scope == "full" and status in {"reserved", "sent"}:
            attempts_ok = False
    sent_evidence = any(row["sent_at_utc"] is not None for row in attempts)
    if manifest and bool(manifest["provider_call"]) != sent_evidence:
        attempts_ok = False
    if scope == "seed" and attempts:
        attempts_ok = False
    if not attempts_ok:
        recorder.issue(
            "attempt_ledger_invalid",
            "operational_accounting_invalid",
            "provider_attempt",
            run_id,
        )
    recorder.check("provider_attempt_ledger", attempts_ok, len(attempts), manifest_count)

    if scope == "full":
        artifacts_by_lane: dict[tuple[str, str], list[dict[str, object]]] = {}
        for lane_type, lane_key in expected_lanes:
            lane_hash = sha256(lane_key.encode()).hexdigest()
            artifacts_by_lane[(lane_type, lane_key)] = [
                row
                for row in artifact_rows
                if row["lane_type"] == lane_type and row["lane_key_hash"] == lane_hash
            ]
        for lane in expected_lanes:
            checkpoint = checkpoint_by_lane.get(lane)
            lane_identity = f"{lane[0]}:{lane[1]}"
            if checkpoint is None:
                recorder.issue(
                    "required_lane_missing",
                    "required_lanes_incomplete",
                    "lane",
                    lane_identity,
                )
                continue
            if checkpoint["status"] != "complete":
                recorder.issue(
                    "required_lane_nonterminal",
                    "required_lanes_incomplete",
                    "lane",
                    lane_identity,
                )
            if checkpoint["stop_reason"] not in {
                "cursor_exhausted",
                "older_than_window",
            }:
                recorder.issue(
                    "required_lane_bad_stop",
                    "required_lanes_incomplete",
                    "lane",
                    lane_identity,
                )
            page_number = int(checkpoint["page_number"])
            if page_number < 1:
                recorder.issue(
                    "required_lane_zero_pages",
                    "required_lanes_incomplete",
                    "lane",
                    lane_identity,
                )
            pages = [int(row["page_number"]) for row in artifacts_by_lane.get(lane, [])]
            if sorted(pages) != list(range(1, page_number + 1)):
                recorder.issue(
                    "required_lane_page_missing",
                    "required_lanes_incomplete",
                    "lane",
                    lane_identity,
                )
            endpoints = {
                str(row["source_endpoint"]) for row in artifacts_by_lane.get(lane, [])
            }
            endpoint_evidence = bool(endpoints) and any(
                attempt["endpoint"] in endpoints and attempt["sent_at_utc"] is not None
                for attempt in attempts
            )
            if not endpoint_evidence:
                recorder.issue(
                    "required_lane_endpoint_attempt_missing",
                    "required_lanes_incomplete",
                    "lane",
                    lane_identity,
                )
            if checkpoint["stop_reason"] == "cursor_exhausted" and checkpoint["cursor"] is not None:
                recorder.issue(
                    "required_lane_bad_stop",
                    "required_lanes_incomplete",
                    "lane",
                    lane_identity,
                )
            if checkpoint["stop_reason"] == "older_than_window" and int(
                checkpoint["consecutive_old_pages"]
            ) < 2:
                recorder.issue(
                    "required_lane_bad_stop",
                    "required_lanes_incomplete",
                    "lane",
                    lane_identity,
                )

        _validate_full_detail_and_comment_ledgers(
            conn,
            run_id=run_id,
            candidates=candidates,
            checkpoints=checkpoints,
            artifact_rows=artifact_rows,
            payload_by_artifact=payload_by_artifact,
            recorder=recorder,
        )

    operational_codes = {
        "authorization_ledger_schema_invalid",
        "budget_extension_ledger_invalid",
        "hydration_resume_ledger_invalid",
        "invalid_discovery_occurrence",
        "occurrence_equation_mismatch",
        "candidate_first_occurrence_mismatch",
        "attempt_ledger_invalid",
    }
    current_codes = {issue[1] for issue in recorder._issues}
    operational_snapshot = operational_snapshot_sha256(conn, run_id)
    recorder.check(
        "operational_accounting",
        not bool(current_codes & operational_codes),
        operational_snapshot,
        operational_snapshot,
    )
    return required_lane_report


def _validate_full_detail_and_comment_ledgers(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    candidates: list[dict[str, object]],
    checkpoints: list[dict[str, object]],
    artifact_rows: list[dict[str, object]],
    payload_by_artifact: dict[str, bytes],
    recorder: _Recorder,
) -> None:
    candidate_by_post = {str(row["post_id"]): row for row in candidates}
    same_run_threads = {
        str(row[0])
        for row in conn.execute(
            "SELECT post_id FROM reddit_threads WHERE run_id=?", (run_id,)
        )
    }
    global_threads = {
        str(row[0]) for row in conn.execute("SELECT post_id FROM reddit_threads")
    }
    for post_id, candidate in candidate_by_post.items():
        status = str(candidate["status"])
        if status == "hydrated" and post_id not in same_run_threads:
            recorder.issue(
                "candidate_hydration_incomplete",
                "candidate_hydration_incomplete",
                "candidate",
                post_id,
            )
        elif status in {"pending", "failed", "budget_deferred"}:
            recorder.issue(
                "candidate_hydration_incomplete",
                "candidate_hydration_incomplete",
                "candidate",
                post_id,
            )
        elif status == "duplicate_existing_structured" and post_id not in global_threads:
            recorder.issue(
                "candidate_hydration_incomplete",
                "candidate_hydration_incomplete",
                "candidate",
                post_id,
            )
        elif status != "hydrated" and status != "duplicate_existing_structured" and post_id in same_run_threads:
            recorder.issue(
                "nonhydrated_candidate_has_entity",
                "candidate_hydration_incomplete",
                "candidate",
                post_id,
            )

    batches = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM backfill_detail_batches WHERE run_id=? ORDER BY batch_number",
            (run_id,),
        )
    ]
    members = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM backfill_detail_batch_members WHERE run_id=? "
            "ORDER BY batch_id, ordinal",
            (run_id,),
        )
    ]
    artifact_by_id = {str(row["artifact_id"]): row for row in artifact_rows}
    assigned_posts: set[str] = set()
    for batch in batches:
        batch_id = str(batch["batch_id"])
        batch_members = [row for row in members if row["batch_id"] == batch_id]
        ordinals = [int(row["ordinal"]) for row in batch_members]
        post_ids = tuple(str(row["post_id"]) for row in batch_members)
        expected_batch_id = "detail_batch_" + sha256(
            json.dumps(
                [run_id, list(post_ids)],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:24]
        member_contract_ok = (
            1 <= len(post_ids) <= 30
            and ordinals == list(range(len(post_ids)))
            and batch_id == expected_batch_id
            and all(post_id in candidate_by_post for post_id in post_ids)
            and not (assigned_posts & set(post_ids))
        )
        assigned_posts.update(post_ids)
        if not member_contract_ok:
            recorder.issue(
                "detail_batch_membership_invalid",
                "candidate_hydration_incomplete",
                "detail_batch",
                batch_id,
            )
        artifact = artifact_by_id.get(str(batch["artifact_id"])) if batch["artifact_id"] else None
        complete_ok = bool(
            batch["status"] == "complete"
            and batch["stop_reason"] is None
            and artifact
            and artifact["lane_type"] == "detail_batch"
            and artifact["lane_key_hash"] == sha256(batch_id.encode()).hexdigest()
            and artifact["parser_kind"] == "tikhub_detail"
            and artifact["source_method"] == "tikhub_detail"
            and artifact["page_number"] == batch["batch_number"]
        )
        if not complete_ok:
            recorder.issue(
                "detail_batch_incomplete",
                "candidate_hydration_incomplete",
                "detail_batch",
                batch_id,
            )

    comments_checkpoints = {
        str(row["lane_key"]): row
        for row in checkpoints
        if row["lane_type"] == "comments"
    }
    checkpoint_posts_by_hash: dict[str, list[str]] = {}
    for checkpoint_post_id in comments_checkpoints:
        checkpoint_posts_by_hash.setdefault(
            sha256(checkpoint_post_id.encode()).hexdigest(), []
        ).append(checkpoint_post_id)
    candidate_posts_by_hash: dict[str, list[str]] = {}
    for candidate_post_id in candidate_by_post:
        candidate_posts_by_hash.setdefault(
            sha256(candidate_post_id.encode()).hexdigest(), []
        ).append(candidate_post_id)
    for artifact in artifact_rows:
        if not _artifact_has_comment_marker(artifact):
            continue
        checkpoint_posts = checkpoint_posts_by_hash.get(
            str(artifact["lane_key_hash"]), []
        )
        candidate_posts = candidate_posts_by_hash.get(
            str(artifact["lane_key_hash"]), []
        )
        lane_closed = bool(
            _artifact_is_exact_comment_contract(artifact)
            and len(checkpoint_posts) == 1
            and len(candidate_posts) == 1
            and checkpoint_posts[0] == candidate_posts[0]
            and candidate_by_post[candidate_posts[0]]["status"] == "hydrated"
        )
        if not lane_closed:
            recorder.issue(
                "comment_chain_invalid",
                "candidate_hydration_incomplete",
                "comments",
                artifact["artifact_id"],
            )
    for post_id, checkpoint in comments_checkpoints.items():
        if post_id not in candidate_by_post or candidate_by_post[post_id]["status"] != "hydrated":
            recorder.issue(
                "comment_lane_unconfigured",
                "candidate_hydration_incomplete",
                "comments",
                post_id,
            )
        page_number = int(checkpoint["page_number"])
        lane_hash = sha256(post_id.encode()).hexdigest()
        pages = sorted(
            (
                row
                for row in artifact_rows
                if row["lane_type"] == "comments" and row["lane_key_hash"] == lane_hash
            ),
            key=lambda row: int(row["page_number"]),
        )
        chain_ok = (
            page_number >= 1
            and [int(row["page_number"]) for row in pages]
            == list(range(1, page_number + 1))
            and all(
                row["parser_kind"] == "tikhub_comments"
                and row["source_method"] == "tikhub_comments"
                for row in pages
            )
            and bool(pages)
            and pages[0]["request_cursor"] is None
            and all(
                pages[index]["response_cursor"]
                == pages[index + 1]["request_cursor"]
                for index in range(len(pages) - 1)
            )
            and pages[-1]["response_cursor"] == checkpoint["cursor"]
            and pages[-1]["request_cursor"] == checkpoint["previous_cursor"]
            and pages[-1]["captured_at_utc"] == checkpoint["last_success_utc"]
            and checkpoint["status"] == "complete"
            and checkpoint["stop_reason"] == "cursor_exhausted"
            and checkpoint["cursor"] is None
        )
        raw_chain_ok = bool(pages)
        raw_occurrence_count = 0
        raw_comments_by_id: dict[str, Any] = {}
        for page in pages:
            payload_bytes = payload_by_artifact.get(str(page["artifact_id"]))
            try:
                if payload_bytes is None:
                    raise _ReplayDataError("comment_payload_missing")
                payload = _decode_replay_json(payload_bytes)
                response_cursor = _cursor_from_checkpoint(
                    payload,
                    checkpoint,
                    allow_terminal_without_cursor=True,
                )
                if response_cursor != page["response_cursor"]:
                    raise _ReplayDataError("comment_chain_invalid")
                comments, _page_more = _parse_strict_tikhub_comment_payload(
                    payload,
                    post_id=post_id,
                    run_id=run_id,
                    raw_capture_id=str(page["raw_capture_id"]),
                    submitter_name="",
                )
            except Exception:
                raw_chain_ok = False
                continue
            raw_occurrence_count += len(comments)
            for comment in comments:
                existing = raw_comments_by_id.get(comment.comment_id)
                if existing is None:
                    raw_comments_by_id[comment.comment_id] = comment
                elif _comment_semantic_key(existing) != _comment_semantic_key(comment):
                    raw_chain_ok = False
        raw_chain_ok = bool(
            raw_chain_ok
            and raw_occurrence_count == int(checkpoint["discovered_count"])
            and len(raw_comments_by_id) == int(checkpoint["unique_count"])
        )
        chain_ok = chain_ok and raw_chain_ok
        if not chain_ok:
            recorder.issue(
                "comment_chain_invalid",
                "candidate_hydration_incomplete",
                "comments",
                post_id,
            )

    for post_id, candidate in candidate_by_post.items():
        if candidate["status"] == "hydrated" and post_id not in comments_checkpoints:
            recorder.issue(
                "comment_chain_invalid",
                "candidate_hydration_incomplete",
                "comments",
                post_id,
            )


def _result(
    *,
    run_id: str,
    scope: ValidationScope,
    baseline: SeedBaseline | None,
    recorder: _Recorder,
    replay_status: str,
    run_root_scan: str,
    source_provider_call: bool = False,
    counts: dict[str, int] | None = None,
    candidate_status_counts: dict[str, int] | None = None,
    occurrence_disposition_counts: dict[str, int] | None = None,
    required_lanes: list[dict[str, object]] | None = None,
    source_fingerprints: dict[str, object] | None = None,
    replay_fingerprints: dict[str, object] | None = None,
    known_seed_partial_count: int = 0,
    known_seed_partial_post_ids_sha256: str | None = None,
) -> dict[str, object]:
    if scope == "seed" and not recorder.categories:
        status = "accepted"
        stop_reason = "seed_validation_complete"
    elif scope == "full" and not recorder.categories and replay_status == "equivalent":
        status = "accepted"
        stop_reason = "full_validation_complete"
    else:
        status = "rejected"
        stop_reason = next(
            (reason for reason in _STOP_PRIORITY if reason in recorder.categories),
            "source_unreadable",
        )
    return {
        "schema_version": "backfill_validation_v1",
        "run_id": run_id,
        "scope": scope,
        "status": status,
        "stop_reason": stop_reason,
        "replay_status": replay_status,
        "full_ready": status == "accepted" and scope == "full" and replay_status == "equivalent",
        "source_provider_call": bool(source_provider_call),
        "provider_attempt_made": False,
        "live_send": False,
        "seed_baseline_sha256": _safe_sha(getattr(baseline, "baseline_sha256", None)),
        "known_seed_partial_count": int(known_seed_partial_count),
        "known_seed_partial_post_ids_sha256": (
            _safe_sha(
                known_seed_partial_post_ids_sha256
                if known_seed_partial_post_ids_sha256 is not None
                else getattr(baseline, "known_partial_post_ids_sha256", None)
            )
        ),
        "run_root_scan": run_root_scan,
        "counts": counts or {name: 0 for name in _COUNT_NAMES.values()},
        "candidate_status_counts": candidate_status_counts
        or {status_name: 0 for status_name in _CANDIDATE_STATUSES},
        "occurrence_disposition_counts": occurrence_disposition_counts
        or {disposition: 0 for disposition in _DISCOVERY_DISPOSITIONS},
        "required_lanes": required_lanes or [],
        "source_fingerprints": source_fingerprints or {},
        "replay_fingerprints": replay_fingerprints,
        "operational_metadata": {
            "mode": "constraints_checked",
            "failure_only_metadata": "none",
            "metadata_mirrored_count": 0,
            "provider_attempts": "source_only_not_replayed",
        },
        "checks": recorder.checks,
        "issues": recorder.public_issues(),
    }


def _scan_run_root(
    run_root: Path | None, *, scope: ValidationScope, recorder: _Recorder
) -> str:
    if run_root is None:
        if scope == "full":
            recorder.issue(
                "run_root_required", "replay_required", "run_root", recorder.run_id
            )
        return "not_run"
    try:
        if _path_has_existing_symlink_component(run_root):
            raise FileNotFoundError
        root = Path(run_root).resolve(strict=True)
        if not root.is_dir():
            raise FileNotFoundError
        stack = [root]
        found = False
        while stack:
            directory = stack.pop()
            with os.scandir(directory) as entries:
                for entry in sorted(entries, key=lambda item: item.name):
                    if entry.name.endswith("-live-send.json") and (
                        entry.is_file(follow_symlinks=False) or entry.is_symlink()
                    ):
                        found = True
                    elif entry.is_dir(follow_symlinks=False) and not entry.is_symlink():
                        stack.append(Path(entry.path))
        if found:
            recorder.issue(
                "live_send_artifact_found",
                "live_send_boundary_violation",
                "run_root",
                recorder.run_id,
            )
            return "failed"
        return "clean"
    except (FileNotFoundError, OSError):
        recorder.issue(
            "run_root_scan_failed",
            "live_send_boundary_violation",
            "run_root",
            recorder.run_id,
        )
        return "failed"


def _artifact_metadata_types_valid(artifact: RawArtifactMetadata) -> bool:
    required_strings = (
        artifact.artifact_id,
        artifact.run_id,
        artifact.artifact_kind,
        artifact.lane_type,
        artifact.lane_key_hash,
        artifact.identity_hash,
        artifact.raw_capture_id,
        artifact.parser_kind,
        artifact.source_method,
        artifact.source_url,
        artifact.source_endpoint,
        artifact.payload_sha256,
        artifact.relative_path,
        artifact.captured_at_utc,
    )
    if any(type(value) is not str or not value for value in required_strings):
        return False
    if not all(
        _is_sha(value)
        for value in (
            artifact.lane_key_hash,
            artifact.identity_hash,
            artifact.payload_sha256,
        )
    ):
        return False
    if artifact.page_number is not None and (
        type(artifact.page_number) is not int or artifact.page_number < 0
    ):
        return False
    if any(
        value is not None and type(value) is not str
        for value in (artifact.request_cursor, artifact.response_cursor)
    ):
        return False
    try:
        captured_at = datetime.fromisoformat(artifact.captured_at_utc)
    except ValueError:
        return False
    return captured_at.tzinfo is not None


def _capture_matches_artifact(
    capture: dict[str, object] | None, artifact: RawArtifactMetadata
) -> bool:
    if capture is None:
        return False
    expected_boundary = (
        "local_seed" if artifact.source_method == "historical_seed" else "provider_gate"
    )
    expected_capture_id = "raw_backfill_" + sha256(
        "\0".join(
            (
                artifact.run_id,
                artifact.source_method,
                artifact.source_url,
                artifact.payload_sha256,
            )
        ).encode("utf-8")
    ).hexdigest()[:24]
    return (
        capture.get("run_id") == artifact.run_id
        and capture.get("raw_capture_id") == artifact.raw_capture_id
        and artifact.raw_capture_id == expected_capture_id
        and capture.get("source_method") == artifact.source_method
        and capture.get("source_url") == artifact.source_url
        and capture.get("captured_at_utc") == artifact.captured_at_utc
        and capture.get("auth_boundary") == expected_boundary
        and capture.get("raw_payload_hash") == f"sha256:{artifact.payload_sha256}"
        and capture.get("payload_format") == "json"
        and capture.get("browser_status") == "ok"
        and capture.get("http_status") is None
        and capture.get("selector_version") is None
        and capture.get("blocked_reason") is None
        and capture.get("secrets_written") == 0
    )


def _archive_json_gzip_files(root: Path, run_id: str) -> set[str]:
    run_root = root / run_id
    if run_root.is_symlink():
        raise ArchiveIntegrityError("raw archive integrity verification failed")
    if not run_root.exists() or not run_root.is_dir():
        return set()
    files: set[str] = set()
    stack = [run_root]
    while stack:
        directory = stack.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError:
            raise ArchiveIntegrityError(
                "raw archive integrity verification failed"
            ) from None
        for entry in entries:
            try:
                path = Path(entry.path)
                if entry.is_symlink():
                    raise ArchiveIntegrityError(
                        "raw archive integrity verification failed"
                    )
                if entry.is_dir(follow_symlinks=False):
                    stack.append(path)
                elif entry.is_file(follow_symlinks=False) and entry.name.endswith(
                    ".json.gz"
                ):
                    files.add(path.relative_to(root).as_posix())
            except OSError:
                raise ArchiveIntegrityError(
                    "raw archive integrity verification failed"
                ) from None
    return files


def _grouped_counts(
    conn: sqlite3.Connection,
    *,
    table: str,
    column: str,
    values: tuple[str, ...],
    run_id: str,
) -> dict[str, int]:
    rows = conn.execute(
        f"SELECT {column}, COUNT(*) AS count FROM {table} "
        f"WHERE run_id=? GROUP BY {column}",
        (run_id,),
    ).fetchall()
    actual = {str(row[column]): int(row["count"]) for row in rows}
    return {value: actual.get(value, 0) for value in values}


def _manifest_window(
    manifest: dict[str, object] | None,
) -> tuple[datetime | None, datetime | None]:
    if manifest is None:
        return None, None
    try:
        start = datetime.fromisoformat(str(manifest["window_start_utc"]))
        end = datetime.fromisoformat(str(manifest["effective_end_utc"]))
    except (TypeError, ValueError):
        return None, None
    if start.tzinfo is None or end.tzinfo is None:
        return None, None
    return start, end


def _comment_record(comment: Any) -> dict[str, object]:
    record = comment.as_record()
    record["is_submitter"] = (
        None if comment.is_submitter is None else int(comment.is_submitter)
    )
    record["deleted_or_removed"] = int(comment.deleted_or_removed)
    return record


def _analysis_record(
    *,
    analysis_id: str,
    run_id: str,
    source_type: str,
    source_id: str,
    text: str,
) -> dict[str, object]:
    analysis = analyze_text(text)
    return {
        "analysis_id": analysis_id,
        "run_id": run_id,
        "source_type": source_type,
        "source_id": source_id,
        "analysis_version": "local_rules_v1",
        "sentiment_label": analysis.sentiment_label,
        "sentiment_score": float(analysis.sentiment_score),
        "topic": analysis.topic,
        "severity": analysis.severity,
        "confidence": float(analysis.confidence),
        "pain_points": json.dumps(
            list(analysis.pain_points), ensure_ascii=False, separators=(",", ":")
        ),
        "provider_call": 0,
    }


def _json_string_list(value: object) -> tuple[str, ...] | None:
    if type(value) is not str:
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    if (
        type(parsed) is not list
        or not parsed
        or any(type(item) is not str or not item.strip() for item in parsed)
        or len(set(parsed)) != len(parsed)
    ):
        return None
    return tuple(parsed)


def _canonical_sha(value: object, *, sort_keys: bool = False) -> str:
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=sort_keys,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _is_sha(value: object) -> bool:
    return type(value) is str and _SHA256_PATTERN.fullmatch(value) is not None


def _safe_sha(value: object) -> str:
    return str(value) if _is_sha(value) else "0" * 64
