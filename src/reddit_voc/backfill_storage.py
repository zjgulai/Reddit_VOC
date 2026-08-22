from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Sequence
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal

from .backfill_models import (
    AnalysisRow,
    ArtifactLaneType,
    BackfillCheckpoint,
    BackfillManifest,
    CandidateStatus,
    DetailBatch,
    DiscoveryDisposition,
    InsertCounts,
    LaneType,
    RawArtifactMetadata,
)
from .models import RawCapture, RedditComment, RedditThread


_ERROR_CLASS_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}")
_PROVIDER_ENDPOINT_PATTERN = re.compile(r"/[A-Za-z0-9._~!$&'()*+,;=:@%/-]+")
_SAFE_REASON_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_ARTIFACT_LANE_TYPES = {
    "seed",
    "dynamic_search",
    "subreddit_feed",
    "detail_batch",
    "comments",
}
_CANDIDATE_STATUSES = {
    "pending",
    "duplicate_existing_structured",
    "hydrated",
    "excluded",
    "outside_window_detail",
    "failed",
    "budget_deferred",
}
_TERMINAL_CANDIDATE_STATUSES = _CANDIDATE_STATUSES - {"pending"}
_SEED_FILE_COLUMNS = {
    "run_id",
    "input_path_hash",
    "payload_sha256",
    "outcome",
    "artifact_id",
    "post_id",
    "error_class",
    "processed_at_utc",
}
_CHECKPOINT_COLUMNS = {
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
}
_BUDGET_EXTENSION_COLUMNS = {
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
}
_HYDRATION_RESUME_COLUMNS = {
    "run_id",
    "authorization_sha256",
    "candidate_post_ids_json",
    "candidate_post_ids_sha256",
    "batch_membership_json",
    "batch_membership_sha256",
    "candidate_count",
    "batch_count",
    "applied_at_utc",
}
_COLLECTION_RESUME_COLUMNS = {
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
}
_CANDIDATE_COLUMNS = {
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
}
_DISCOVERY_OCCURRENCE_COLUMNS = {
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
}
_DETAIL_BATCH_COLUMNS = {
    "run_id",
    "batch_id",
    "batch_number",
    "status",
    "artifact_id",
    "stop_reason",
    "created_at_utc",
    "updated_at_utc",
}
_DETAIL_BATCH_MEMBER_COLUMNS = {
    "run_id",
    "batch_id",
    "ordinal",
    "post_id",
}


class BackfillConflictError(RuntimeError):
    pass


class BackfillSchemaError(RuntimeError):
    pass


STAGING_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    window_start_utc TEXT NOT NULL,
    window_end_utc TEXT NOT NULL,
    provider_call INTEGER NOT NULL DEFAULT 0 CHECK (provider_call IN (0, 1)),
    live_send INTEGER NOT NULL DEFAULT 0 CHECK (live_send = 0)
);

CREATE TABLE IF NOT EXISTS raw_captures (
    raw_capture_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    source_method TEXT NOT NULL,
    source_url TEXT NOT NULL,
    captured_at_utc TEXT NOT NULL,
    auth_boundary TEXT NOT NULL,
    raw_payload_hash TEXT NOT NULL,
    payload_format TEXT NOT NULL,
    browser_status TEXT NOT NULL,
    http_status INTEGER,
    selector_version TEXT,
    blocked_reason TEXT,
    secrets_written INTEGER NOT NULL DEFAULT 0 CHECK (secrets_written IN (0, 1)),
    UNIQUE (run_id, raw_capture_id),
    UNIQUE (run_id, source_method, source_url, raw_payload_hash),
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS reddit_threads (
    post_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    raw_capture_id TEXT NOT NULL,
    subreddit TEXT NOT NULL,
    title TEXT NOT NULL,
    selftext TEXT NOT NULL,
    source_url TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    score INTEGER,
    num_comments_reported INTEGER,
    parsed_comment_count INTEGER NOT NULL,
    more_node_count INTEGER NOT NULL,
    coverage_grade TEXT NOT NULL,
    matched_keywords TEXT NOT NULL,
    author_hash TEXT,
    media_urls TEXT NOT NULL DEFAULT '[]',
    UNIQUE (run_id, post_id),
    FOREIGN KEY (run_id, raw_capture_id)
        REFERENCES raw_captures(run_id, raw_capture_id)
);

CREATE TABLE IF NOT EXISTS reddit_comments (
    comment_id TEXT PRIMARY KEY,
    post_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    raw_capture_id TEXT NOT NULL,
    parent_id TEXT,
    body TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    score INTEGER,
    depth INTEGER,
    is_submitter INTEGER,
    matched_keywords TEXT NOT NULL,
    author_hash TEXT,
    deleted_or_removed INTEGER NOT NULL DEFAULT 0 CHECK (deleted_or_removed IN (0, 1)),
    FOREIGN KEY (run_id, post_id) REFERENCES reddit_threads(run_id, post_id),
    FOREIGN KEY (run_id, raw_capture_id)
        REFERENCES raw_captures(run_id, raw_capture_id)
);

CREATE TABLE IF NOT EXISTS analysis_results (
    analysis_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('post', 'comment')),
    source_id TEXT NOT NULL,
    analysis_version TEXT NOT NULL,
    sentiment_label TEXT NOT NULL,
    sentiment_score REAL NOT NULL,
    topic TEXT NOT NULL,
    severity TEXT NOT NULL,
    confidence REAL NOT NULL,
    pain_points TEXT NOT NULL,
    provider_call INTEGER NOT NULL DEFAULT 0 CHECK (provider_call IN (0, 1)),
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS delivery_previews (
    delivery_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    message_hash TEXT NOT NULL,
    artifact_paths TEXT NOT NULL,
    live_send INTEGER NOT NULL DEFAULT 0 CHECK (live_send = 0),
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS backfill_manifests (
    run_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (
        status IN ('prepared', 'seed_complete', 'running', 'partial',
                   'success', 'blocked', 'failed')
    ),
    window_start_utc TEXT NOT NULL,
    requested_end_utc TEXT NOT NULL,
    effective_end_utc TEXT NOT NULL,
    search_terms_json TEXT NOT NULL,
    subreddits_json TEXT NOT NULL,
    include_subreddit_sweep INTEGER NOT NULL CHECK (include_subreddit_sweep IN (0, 1)),
    required_lanes_sha256 TEXT NOT NULL,
    keyword_config_sha256 TEXT NOT NULL,
    max_provider_requests INTEGER NOT NULL CHECK (max_provider_requests >= 0),
    provider_request_count INTEGER NOT NULL CHECK (
        provider_request_count >= 0 AND provider_request_count <= max_provider_requests
    ),
    provider_call INTEGER NOT NULL DEFAULT 0 CHECK (provider_call IN (0, 1)),
    live_send INTEGER NOT NULL DEFAULT 0 CHECK (live_send = 0),
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS backfill_seed_files (
    run_id TEXT NOT NULL,
    input_path_hash TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (
        outcome IN ('imported', 'outside_window', 'excluded', 'duplicate', 'parse_error')
    ),
    artifact_id TEXT NOT NULL,
    post_id TEXT,
    error_class TEXT,
    processed_at_utc TEXT NOT NULL,
    PRIMARY KEY (run_id, input_path_hash),
    FOREIGN KEY (run_id) REFERENCES backfill_manifests(run_id),
    FOREIGN KEY (run_id, artifact_id)
        REFERENCES backfill_raw_artifacts(run_id, artifact_id)
);

CREATE TABLE IF NOT EXISTS backfill_raw_artifacts (
    artifact_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    artifact_kind TEXT NOT NULL,
    lane_type TEXT NOT NULL CHECK (
        lane_type IN ('seed', 'dynamic_search', 'subreddit_feed', 'detail_batch', 'comments')
    ),
    lane_key_hash TEXT NOT NULL,
    identity_hash TEXT NOT NULL,
    raw_capture_id TEXT NOT NULL,
    parser_kind TEXT NOT NULL,
    source_method TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_endpoint TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    relative_path TEXT NOT NULL UNIQUE,
    captured_at_utc TEXT NOT NULL,
    page_number INTEGER,
    request_cursor TEXT,
    response_cursor TEXT,
    PRIMARY KEY (run_id, artifact_id),
    UNIQUE (run_id, raw_capture_id),
    UNIQUE (run_id, source_method, source_url, payload_sha256),
    FOREIGN KEY (run_id) REFERENCES backfill_manifests(run_id)
);

CREATE TABLE IF NOT EXISTS backfill_provider_attempts (
    run_id TEXT NOT NULL,
    request_number INTEGER NOT NULL CHECK (request_number > 0),
    endpoint TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('reserved', 'sent', 'succeeded', 'failed')),
    reserved_at_utc TEXT NOT NULL,
    sent_at_utc TEXT,
    completed_at_utc TEXT,
    http_status INTEGER,
    error_class TEXT,
    PRIMARY KEY (run_id, request_number),
    FOREIGN KEY (run_id) REFERENCES backfill_manifests(run_id)
);

CREATE TABLE IF NOT EXISTS backfill_budget_extensions (
    run_id TEXT NOT NULL,
    authorization_sha256 TEXT NOT NULL CHECK (
        length(authorization_sha256) = 64
        AND authorization_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    expected_provider_request_count INTEGER NOT NULL CHECK (
        expected_provider_request_count >= 0
    ),
    expected_max_provider_requests INTEGER NOT NULL CHECK (
        expected_max_provider_requests >= 0
    ),
    new_max_provider_requests INTEGER NOT NULL CHECK (
        new_max_provider_requests > expected_max_provider_requests
    ),
    discovery_request_ceiling INTEGER NOT NULL CHECK (
        discovery_request_ceiling >= expected_provider_request_count
        AND discovery_request_ceiling < new_max_provider_requests
    ),
    lane_page_ceilings_sha256 TEXT NOT NULL CHECK (
        length(lane_page_ceilings_sha256) = 64
        AND lane_page_ceilings_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    include_subreddit_sweep INTEGER NOT NULL CHECK (
        include_subreddit_sweep IN (0, 1)
    ),
    required_lanes_sha256 TEXT NOT NULL CHECK (
        length(required_lanes_sha256) = 64
        AND required_lanes_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    applied_at_utc TEXT NOT NULL,
    PRIMARY KEY (run_id, authorization_sha256),
    UNIQUE (run_id, expected_max_provider_requests),
    UNIQUE (run_id, new_max_provider_requests),
    CHECK (expected_provider_request_count = expected_max_provider_requests),
    FOREIGN KEY (run_id) REFERENCES backfill_manifests(run_id)
);

CREATE TABLE IF NOT EXISTS backfill_hydration_resumes (
    run_id TEXT NOT NULL,
    authorization_sha256 TEXT NOT NULL CHECK (
        length(authorization_sha256) = 64
        AND authorization_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    candidate_post_ids_json TEXT NOT NULL,
    candidate_post_ids_sha256 TEXT NOT NULL CHECK (
        length(candidate_post_ids_sha256) = 64
        AND candidate_post_ids_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    batch_membership_json TEXT NOT NULL,
    batch_membership_sha256 TEXT NOT NULL CHECK (
        length(batch_membership_sha256) = 64
        AND batch_membership_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    candidate_count INTEGER NOT NULL CHECK (candidate_count > 0),
    batch_count INTEGER NOT NULL CHECK (batch_count > 0),
    applied_at_utc TEXT NOT NULL,
    PRIMARY KEY (run_id, authorization_sha256),
    FOREIGN KEY (run_id, authorization_sha256)
        REFERENCES backfill_budget_extensions(run_id, authorization_sha256)
);

CREATE TABLE IF NOT EXISTS backfill_collection_resumes (
    run_id TEXT NOT NULL,
    authorization_sha256 TEXT NOT NULL CHECK (
        length(authorization_sha256) = 64
        AND authorization_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    expected_source_database_sha256 TEXT NOT NULL CHECK (
        length(expected_source_database_sha256) = 64
        AND expected_source_database_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    expected_provider_request_count INTEGER NOT NULL CHECK (
        expected_provider_request_count >= 0
    ),
    max_provider_requests INTEGER NOT NULL CHECK (
        max_provider_requests > expected_provider_request_count
    ),
    discovery_request_ceiling INTEGER NOT NULL CHECK (
        discovery_request_ceiling >= expected_provider_request_count
        AND discovery_request_ceiling <= max_provider_requests
    ),
    lane_page_ceilings_sha256 TEXT NOT NULL CHECK (
        length(lane_page_ceilings_sha256) = 64
        AND lane_page_ceilings_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    candidate_state_sha256 TEXT NOT NULL CHECK (
        length(candidate_state_sha256) = 64
        AND candidate_state_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    include_subreddit_sweep INTEGER NOT NULL CHECK (
        include_subreddit_sweep IN (0, 1)
    ),
    required_lanes_sha256 TEXT NOT NULL CHECK (
        length(required_lanes_sha256) = 64
        AND required_lanes_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    applied_at_utc TEXT NOT NULL,
    PRIMARY KEY (run_id, authorization_sha256),
    UNIQUE (run_id, expected_provider_request_count),
    FOREIGN KEY (run_id) REFERENCES backfill_manifests(run_id)
);

CREATE TABLE IF NOT EXISTS backfill_checkpoints (
    run_id TEXT NOT NULL,
    lane_type TEXT NOT NULL CHECK (
        lane_type IN ('dynamic_search', 'subreddit_feed', 'detail_batch', 'comments')
    ),
    lane_key TEXT NOT NULL,
    cursor TEXT,
    previous_cursor TEXT,
    page_number INTEGER NOT NULL CHECK (page_number >= 0),
    newest_seen_utc TEXT,
    oldest_seen_utc TEXT,
    discovered_count INTEGER NOT NULL CHECK (discovered_count >= 0),
    unique_count INTEGER NOT NULL CHECK (unique_count >= 0),
    provider_request_count INTEGER NOT NULL CHECK (provider_request_count >= 0),
    last_success_utc TEXT,
    last_error TEXT,
    status TEXT NOT NULL CHECK (status IN ('prepared', 'running', 'partial', 'complete', 'failed')),
    stop_reason TEXT,
    cursor_json_path TEXT,
    cursor_schema_sha256 TEXT,
    consecutive_old_pages INTEGER NOT NULL DEFAULT 0 CHECK (consecutive_old_pages >= 0),
    PRIMARY KEY (run_id, lane_type, lane_key),
    FOREIGN KEY (run_id) REFERENCES backfill_manifests(run_id)
);

CREATE TABLE IF NOT EXISTS backfill_candidates (
    run_id TEXT NOT NULL,
    post_id TEXT NOT NULL,
    first_lane_type TEXT NOT NULL CHECK (first_lane_type IN ('dynamic_search', 'subreddit_feed')),
    first_lane_key TEXT NOT NULL,
    first_discovered_at_utc TEXT NOT NULL,
    source_url TEXT NOT NULL,
    post_created_at_utc TEXT NOT NULL,
    raw_artifact_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'duplicate_existing_structured', 'hydrated',
                   'excluded', 'outside_window_detail', 'failed', 'budget_deferred')
    ),
    status_reason TEXT,
    updated_at_utc TEXT NOT NULL,
    PRIMARY KEY (run_id, post_id),
    FOREIGN KEY (run_id) REFERENCES backfill_manifests(run_id),
    FOREIGN KEY (run_id, raw_artifact_id)
        REFERENCES backfill_raw_artifacts(run_id, artifact_id)
);

CREATE TABLE IF NOT EXISTS backfill_detail_batches (
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
    FOREIGN KEY (run_id) REFERENCES backfill_manifests(run_id),
    FOREIGN KEY (run_id, artifact_id)
        REFERENCES backfill_raw_artifacts(run_id, artifact_id)
);

CREATE TABLE IF NOT EXISTS backfill_detail_batch_members (
    run_id TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    post_id TEXT NOT NULL,
    PRIMARY KEY (run_id, batch_id, ordinal),
    UNIQUE (run_id, post_id),
    FOREIGN KEY (run_id, batch_id)
        REFERENCES backfill_detail_batches(run_id, batch_id),
    FOREIGN KEY (run_id, post_id)
        REFERENCES backfill_candidates(run_id, post_id)
);

CREATE TABLE IF NOT EXISTS backfill_discovery_occurrences (
    run_id TEXT NOT NULL,
    lane_type TEXT NOT NULL CHECK (
        lane_type IN ('dynamic_search', 'subreddit_feed', 'detail_batch', 'comments')
    ),
    lane_key TEXT NOT NULL,
    page_number INTEGER NOT NULL CHECK (page_number >= 0),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    post_id TEXT,
    source_url TEXT,
    post_created_at_utc TEXT,
    raw_artifact_id TEXT NOT NULL,
    discovered_at_utc TEXT NOT NULL,
    disposition TEXT NOT NULL CHECK (
        disposition IN (
            'new_candidate',
            'duplicate_occurrence',
            'outside_window',
            'duplicate_existing_structured',
            'invalid'
        )
    ),
    PRIMARY KEY (run_id, lane_type, lane_key, page_number, ordinal),
    FOREIGN KEY (run_id) REFERENCES backfill_manifests(run_id),
    FOREIGN KEY (run_id, raw_artifact_id)
        REFERENCES backfill_raw_artifacts(run_id, artifact_id)
);

CREATE TABLE IF NOT EXISTS backfill_issues (
    run_id TEXT NOT NULL,
    issue_id TEXT NOT NULL,
    issue_kind TEXT NOT NULL,
    lane_type TEXT,
    lane_key TEXT,
    entity_id TEXT,
    fatal INTEGER NOT NULL CHECK (fatal IN (0, 1)),
    error_class TEXT,
    detail TEXT,
    created_at_utc TEXT NOT NULL,
    PRIMARY KEY (run_id, issue_id),
    FOREIGN KEY (run_id) REFERENCES backfill_manifests(run_id)
);

CREATE TABLE IF NOT EXISTS backfill_merge_conflicts (
    merge_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    conflict_kind TEXT NOT NULL,
    staging_sha256 TEXT,
    existing_sha256 TEXT,
    created_at_utc TEXT NOT NULL,
    PRIMARY KEY (merge_id, entity_type, entity_id),
    FOREIGN KEY (run_id) REFERENCES backfill_manifests(run_id)
);
"""


class BackfillStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def migrate(self) -> None:
        with self.connect() as conn:
            seed_table = conn.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'table' AND name = 'backfill_seed_files'"
            ).fetchone()
            if seed_table is not None:
                columns = {
                    str(row["name"])
                    for row in conn.execute(
                        "PRAGMA table_info(backfill_seed_files)"
                    ).fetchall()
                }
                if columns != _SEED_FILE_COLUMNS:
                    raise BackfillSchemaError(
                        "incompatible backfill_seed_files schema; "
                        "use a fresh isolated staging DB"
                    )
            for table, expected_columns in (
                ("backfill_checkpoints", _CHECKPOINT_COLUMNS),
                ("backfill_budget_extensions", _BUDGET_EXTENSION_COLUMNS),
                ("backfill_hydration_resumes", _HYDRATION_RESUME_COLUMNS),
                ("backfill_collection_resumes", _COLLECTION_RESUME_COLUMNS),
                ("backfill_candidates", _CANDIDATE_COLUMNS),
                ("backfill_discovery_occurrences", _DISCOVERY_OCCURRENCE_COLUMNS),
                ("backfill_detail_batches", _DETAIL_BATCH_COLUMNS),
                (
                    "backfill_detail_batch_members",
                    _DETAIL_BATCH_MEMBER_COLUMNS,
                ),
            ):
                table_exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                    (table,),
                ).fetchone()
                if table_exists is None:
                    continue
                columns = {
                    str(row["name"])
                    for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
                }
                schema_contract_ok = True
                if table in {
                    "backfill_budget_extensions",
                    "backfill_hydration_resumes",
                    "backfill_collection_resumes",
                }:
                    schema_contract_ok = (
                        _authorization_ledger_schema_is_compatible(conn, table)
                    )
                elif table in {
                    "backfill_detail_batches",
                    "backfill_detail_batch_members",
                }:
                    schema_contract_ok = _detail_ledger_schema_is_compatible(
                        conn, table
                    )
                if columns != expected_columns or not schema_contract_ok:
                    raise BackfillSchemaError(
                        f"incompatible {table} schema; "
                        "use a fresh isolated staging DB"
                    )
            conn.executescript(STAGING_SCHEMA)

    def create_manifest(self, manifest: BackfillManifest) -> None:
        if manifest.provider_call:
            raise ValueError("provider_call requires a sent provider attempt")
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO backfill_manifests(
                    run_id, status, window_start_utc, requested_end_utc,
                    effective_end_utc, search_terms_json, subreddits_json,
                    include_subreddit_sweep, required_lanes_sha256,
                    keyword_config_sha256, max_provider_requests,
                    provider_request_count, provider_call, live_send,
                    created_at_utc, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    manifest.run_id,
                    manifest.status,
                    manifest.window_start_utc,
                    manifest.requested_end_utc,
                    manifest.effective_end_utc,
                    _canonical_json(manifest.search_terms),
                    _canonical_json(manifest.subreddits),
                    int(manifest.include_subreddit_sweep),
                    manifest.required_lanes_sha256,
                    manifest.keyword_config_sha256,
                    manifest.max_provider_requests,
                    manifest.provider_request_count,
                    int(manifest.provider_call),
                    int(manifest.live_send),
                    manifest.created_at_utc,
                    manifest.updated_at_utc,
                ),
            )
            conn.execute(
                """
                INSERT INTO runs(
                    run_id, status, window_start_utc, window_end_utc,
                    provider_call, live_send
                ) VALUES (?, ?, ?, ?, 0, 0)
                """,
                (
                    manifest.run_id,
                    manifest.status,
                    manifest.window_start_utc,
                    manifest.effective_end_utc,
                ),
            )

    def insert_entity_bundle(
        self,
        *,
        captures: Sequence[RawCapture],
        threads: Sequence[RedditThread],
        comments: Sequence[RedditComment],
        analyses: Sequence[AnalysisRow],
    ) -> InsertCounts:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            return _insert_entity_bundle_conn(
                conn,
                captures=captures,
                threads=threads,
                comments=comments,
                analyses=analyses,
            )

    def insert_raw_artifact(self, artifact: RawArtifactMetadata) -> bool:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            return _insert_raw_artifact_conn(conn, artifact)

    def persist_raw_capture_artifact(
        self, capture: RawCapture, artifact: RawArtifactMetadata
    ) -> RawArtifactMetadata:
        if (
            capture.run_id != artifact.run_id
            or capture.raw_capture_id != artifact.raw_capture_id
            or capture.source_method != artifact.source_method
            or capture.source_url != artifact.source_url
            or capture.raw_payload_hash != f"sha256:{artifact.payload_sha256}"
            or capture.captured_at_utc.isoformat() != artifact.captured_at_utc
        ):
            raise ValueError("raw capture does not match raw artifact metadata")
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            _require_run(conn, capture.run_id)
            _insert_entity_bundle_conn(
                conn,
                captures=(capture,),
                threads=(),
                comments=(),
                analyses=(),
            )
            _insert_raw_artifact_conn(conn, artifact)
            row = conn.execute(
                "SELECT * FROM backfill_raw_artifacts "
                "WHERE run_id = ? AND artifact_id = ?",
                (artifact.run_id, artifact.artifact_id),
            ).fetchone()
        return _raw_artifact_from_row(row)

    def complete_raw_artifact_response_cursor(
        self,
        *,
        run_id: str,
        artifact_id: str,
        response_cursor: str | None,
    ) -> RawArtifactMetadata:
        _require_nonempty_string("artifact_id", artifact_id)
        if response_cursor is not None:
            _require_nonempty_string("response_cursor", response_cursor)
        conflict_key = f"backfill_raw_artifacts:{run_id}/{artifact_id}"
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            _require_run(conn, run_id)
            row = conn.execute(
                "SELECT * FROM backfill_raw_artifacts "
                "WHERE run_id = ? AND artifact_id = ?",
                (run_id, artifact_id),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown backfill raw artifact: {run_id}/{artifact_id}")
            if (
                row["artifact_kind"] != "comments"
                or row["lane_type"] != "comments"
                or row["parser_kind"] != "tikhub_comments"
                or row["source_method"] != "tikhub_comments"
            ):
                raise ValueError(
                    "response cursor completion requires a TikHub comments artifact"
                )
            existing_cursor = row["response_cursor"]
            if existing_cursor is not None and existing_cursor != response_cursor:
                raise BackfillConflictError(conflict_key)
            if existing_cursor is None and response_cursor is not None:
                cursor = conn.execute(
                    "UPDATE backfill_raw_artifacts SET response_cursor = ? "
                    "WHERE run_id = ? AND artifact_id = ? "
                    "AND response_cursor IS NULL",
                    (response_cursor, run_id, artifact_id),
                )
                if cursor.rowcount != 1:
                    raise BackfillConflictError(conflict_key)
                row = conn.execute(
                    "SELECT * FROM backfill_raw_artifacts "
                    "WHERE run_id = ? AND artifact_id = ?",
                    (run_id, artifact_id),
                ).fetchone()
        return _raw_artifact_from_row(row)

    def load_candidates(
        self, *, run_id: str, post_ids: Sequence[str]
    ) -> tuple[dict[str, object], ...]:
        requested = _validated_post_ids(post_ids)
        with self.connect() as conn:
            _require_run(conn, run_id)
            rows: list[dict[str, object]] = []
            for post_id in requested:
                row = conn.execute(
                    "SELECT * FROM backfill_candidates "
                    "WHERE run_id = ? AND post_id = ?",
                    (run_id, post_id),
                ).fetchone()
                if row is None:
                    raise KeyError(f"unknown backfill candidate: {run_id}/{post_id}")
                rows.append(dict(row))
        return tuple(rows)

    def load_raw_capture(self, raw_capture_id: str) -> RawCapture | None:
        _require_nonempty_string("raw_capture_id", raw_capture_id)
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM raw_captures WHERE raw_capture_id = ?",
                (raw_capture_id,),
            ).fetchone()
        if row is None:
            return None
        return RawCapture(
            raw_capture_id=str(row["raw_capture_id"]),
            run_id=str(row["run_id"]),
            source_method=str(row["source_method"]),
            source_url=str(row["source_url"]),
            captured_at_utc=datetime.fromisoformat(str(row["captured_at_utc"])),
            auth_boundary=str(row["auth_boundary"]),
            raw_payload_hash=str(row["raw_payload_hash"]),
            payload_format=str(row["payload_format"]),
            browser_status=str(row["browser_status"]),
            http_status=row["http_status"],
            selector_version=row["selector_version"],
            blocked_reason=row["blocked_reason"],
            secrets_written=bool(row["secrets_written"]),
        )

    def load_hydration_outcomes(
        self, run_id: str
    ) -> tuple[dict[str, object], ...]:
        with self.connect() as conn:
            _require_run(conn, run_id)
            rows = conn.execute(
                "SELECT candidate.post_id, candidate.status, "
                "candidate.status_reason, thread.coverage_grade, "
                "checkpoint.status AS checkpoint_status, "
                "checkpoint.stop_reason AS checkpoint_stop_reason "
                "FROM backfill_candidates AS candidate "
                "LEFT JOIN reddit_threads AS thread "
                "ON thread.run_id = candidate.run_id "
                "AND thread.post_id = candidate.post_id "
                "LEFT JOIN backfill_checkpoints AS checkpoint "
                "ON checkpoint.run_id = candidate.run_id "
                "AND checkpoint.lane_type = 'comments' "
                "AND checkpoint.lane_key = candidate.post_id "
                "WHERE candidate.run_id = ? ORDER BY candidate.post_id",
                (run_id,),
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def structured_thread_run_id(self, post_id: str) -> str | None:
        if not isinstance(post_id, str) or not post_id.strip():
            raise ValueError("post_id must be a non-empty string")
        with self.connect() as conn:
            row = conn.execute(
                "SELECT run_id FROM reddit_threads WHERE post_id = ?", (post_id,)
            ).fetchone()
        return None if row is None else str(row["run_id"])

    def load_raw_artifacts(
        self,
        *,
        run_id: str,
        lane_type: ArtifactLaneType,
        lane_key: str,
    ) -> tuple[RawArtifactMetadata, ...]:
        if lane_type not in _ARTIFACT_LANE_TYPES:
            raise ValueError("invalid raw artifact lane type")
        if not isinstance(lane_key, str) or not lane_key:
            raise ValueError("lane_key must be a non-empty string")
        lane_key_hash = sha256(lane_key.encode()).hexdigest()
        with self.connect() as conn:
            _require_run(conn, run_id)
            rows = conn.execute(
                "SELECT * FROM backfill_raw_artifacts "
                "WHERE run_id = ? AND lane_type = ? AND lane_key_hash = ? "
                "ORDER BY page_number, artifact_id",
                (run_id, lane_type, lane_key_hash),
            ).fetchall()
        return tuple(_raw_artifact_from_row(row) for row in rows)

    def candidate_status_counts(self, run_id: str) -> dict[str, int]:
        with self.connect() as conn:
            _require_run(conn, run_id)
            rows = conn.execute(
                "SELECT status, COUNT(*) AS count FROM backfill_candidates "
                "WHERE run_id = ? GROUP BY status",
                (run_id,),
            ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def discovery_occurrence_total(self, run_id: str) -> int:
        with self.connect() as conn:
            _require_run(conn, run_id)
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM backfill_discovery_occurrences "
                "WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return int(row["count"])

    def raw_artifact_count(
        self, run_id: str, lane_types: Sequence[ArtifactLaneType]
    ) -> int:
        requested = tuple(lane_types)
        if any(lane_type not in _ARTIFACT_LANE_TYPES for lane_type in requested):
            raise ValueError("invalid raw artifact lane type")
        with self.connect() as conn:
            _require_run(conn, run_id)
            if not requested:
                return 0
            placeholders = ", ".join("?" for _ in requested)
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM backfill_raw_artifacts "
                f"WHERE run_id = ? AND lane_type IN ({placeholders})",
                (run_id, *requested),
            ).fetchone()
        return int(row["count"])

    def prepare_detail_batches(
        self,
        *,
        run_id: str,
        post_ids: Sequence[str],
        created_at_utc: datetime,
    ) -> tuple[DetailBatch, ...]:
        requested = _validated_post_ids(post_ids)
        _require_aware_datetime("created_at_utc", created_at_utc)
        created_text = created_at_utc.isoformat()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            _require_run(conn, run_id)
            if not requested:
                return ()

            placeholders = ", ".join("?" for _ in requested)
            candidate_rows = conn.execute(
                "SELECT post_id, status FROM backfill_candidates "
                f"WHERE run_id = ? AND post_id IN ({placeholders})",
                (run_id, *requested),
            ).fetchall()
            statuses = {
                str(row["post_id"]): str(row["status"]) for row in candidate_rows
            }
            missing = [post_id for post_id in requested if post_id not in statuses]
            if missing:
                raise KeyError(
                    f"unknown backfill candidate: {run_id}/{missing[0]}"
                )

            assigned_rows = conn.execute(
                "SELECT post_id FROM backfill_detail_batch_members "
                f"WHERE run_id = ? AND post_id IN ({placeholders})",
                (run_id, *requested),
            ).fetchall()
            assigned = {str(row["post_id"]) for row in assigned_rows}
            unassigned = sorted(
                post_id for post_id in requested if post_id not in assigned
            )
            nonpending = [
                post_id for post_id in unassigned if statuses[post_id] != "pending"
            ]
            if nonpending:
                raise ValueError(
                    "only pending candidates can be assigned to a detail batch"
                )

            row = conn.execute(
                "SELECT COALESCE(MAX(batch_number), 0) AS value "
                "FROM backfill_detail_batches WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            next_batch_number = int(row["value"]) + 1
            for offset in range(0, len(unassigned), 30):
                members = tuple(unassigned[offset : offset + 30])
                batch_id = _detail_batch_id(run_id, members)
                batch_number = next_batch_number
                next_batch_number += 1
                try:
                    conn.execute(
                        "INSERT INTO backfill_detail_batches("
                        "run_id, batch_id, batch_number, status, artifact_id, "
                        "stop_reason, created_at_utc, updated_at_utc"
                        ") VALUES (?, ?, ?, 'prepared', NULL, NULL, ?, ?)",
                        (
                            run_id,
                            batch_id,
                            batch_number,
                            created_text,
                            created_text,
                        ),
                    )
                    conn.executemany(
                        "INSERT INTO backfill_detail_batch_members("
                        "run_id, batch_id, ordinal, post_id"
                        ") VALUES (?, ?, ?, ?)",
                        (
                            (run_id, batch_id, ordinal, post_id)
                            for ordinal, post_id in enumerate(members)
                        ),
                    )
                except sqlite3.IntegrityError:
                    raise BackfillConflictError(
                        f"backfill_detail_batches:{run_id}/{batch_id}"
                    ) from None

            return _load_detail_batches_conn(
                conn, run_id=run_id, post_ids=requested
            )

    def load_detail_batches(
        self, *, run_id: str, post_ids: Sequence[str] = ()
    ) -> tuple[DetailBatch, ...]:
        requested = _validated_post_ids(post_ids)
        with self.connect() as conn:
            _require_run(conn, run_id)
            return _load_detail_batches_conn(
                conn, run_id=run_id, post_ids=requested
            )

    def attach_detail_batch_artifact(
        self,
        *,
        run_id: str,
        batch_id: str,
        artifact_id: str,
        updated_at_utc: datetime,
    ) -> DetailBatch:
        _require_nonempty_string("batch_id", batch_id)
        _require_nonempty_string("artifact_id", artifact_id)
        _require_aware_datetime("updated_at_utc", updated_at_utc)
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            _require_run(conn, run_id)
            batch = _detail_batch_by_id_conn(conn, run_id, batch_id)
            if batch.artifact_id is not None:
                if batch.artifact_id != artifact_id:
                    raise BackfillConflictError(
                        f"backfill_detail_batches:{run_id}/{batch_id}"
                    )
            artifact_row = conn.execute(
                "SELECT * FROM backfill_raw_artifacts "
                "WHERE run_id = ? AND artifact_id = ?",
                (run_id, artifact_id),
            ).fetchone()
            if artifact_row is None:
                raise KeyError(
                    f"unknown backfill raw artifact: {run_id}/{artifact_id}"
                )
            expected_lane_key_hash = sha256(batch_id.encode()).hexdigest()
            if (
                artifact_row["artifact_kind"] != "detail"
                or artifact_row["lane_type"] != "detail_batch"
                or artifact_row["parser_kind"] != "tikhub_detail"
                or artifact_row["source_method"] != "tikhub_detail"
                or artifact_row["lane_key_hash"] != expected_lane_key_hash
                or artifact_row["page_number"] != batch.batch_number
            ):
                raise ValueError("raw artifact does not match detail batch")

            if batch.artifact_id is not None:
                return batch
            if batch.status != "prepared":
                raise BackfillConflictError(
                    f"backfill_detail_batches:{run_id}/{batch_id}"
                )
            conn.execute(
                "UPDATE backfill_detail_batches "
                "SET status = 'raw_persisted', artifact_id = ?, updated_at_utc = ? "
                "WHERE run_id = ? AND batch_id = ?",
                (artifact_id, updated_at_utc.isoformat(), run_id, batch_id),
            )
            return _detail_batch_by_id_conn(conn, run_id, batch_id)

    def finish_detail_batch(
        self,
        *,
        run_id: str,
        batch_id: str,
        status: Literal["complete", "failed"],
        stop_reason: str | None,
        updated_at_utc: datetime,
    ) -> DetailBatch:
        _require_nonempty_string("batch_id", batch_id)
        if status not in {"complete", "failed"}:
            raise ValueError("invalid terminal detail batch status")
        if status == "complete" and stop_reason is not None:
            raise ValueError("complete detail batch must not have a stop reason")
        if status == "failed" and stop_reason is None:
            raise ValueError("failed detail batch requires a stop reason")
        _validate_safe_reason(stop_reason)
        _require_aware_datetime("updated_at_utc", updated_at_utc)
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            _require_run(conn, run_id)
            batch = _detail_batch_by_id_conn(conn, run_id, batch_id)
            if batch.status in {"complete", "failed"}:
                if batch.status == status and batch.stop_reason == stop_reason:
                    return batch
                raise BackfillConflictError(
                    f"backfill_detail_batches:{run_id}/{batch_id}"
                )
            if status == "complete":
                if batch.artifact_id is None:
                    raise BackfillConflictError(
                        f"backfill_detail_batches:{run_id}/{batch_id}"
                    )
                pending = conn.execute(
                    "SELECT 1 FROM backfill_detail_batch_members AS member "
                    "JOIN backfill_candidates AS candidate "
                    "ON candidate.run_id = member.run_id "
                    "AND candidate.post_id = member.post_id "
                    "WHERE member.run_id = ? AND member.batch_id = ? "
                    "AND candidate.status = 'pending' LIMIT 1",
                    (run_id, batch_id),
                ).fetchone()
                if pending is not None:
                    raise BackfillConflictError(
                        f"backfill_detail_batches:{run_id}/{batch_id}"
                    )
            conn.execute(
                "UPDATE backfill_detail_batches "
                "SET status = ?, stop_reason = ?, updated_at_utc = ? "
                "WHERE run_id = ? AND batch_id = ?",
                (
                    status,
                    stop_reason,
                    updated_at_utc.isoformat(),
                    run_id,
                    batch_id,
                ),
            )
            return _detail_batch_by_id_conn(conn, run_id, batch_id)

    def finalize_candidate(
        self,
        *,
        run_id: str,
        post_id: str,
        expected_statuses: Sequence[CandidateStatus],
        status: CandidateStatus,
        status_reason: str | None,
        updated_at_utc: datetime,
        captures: Sequence[RawCapture] = (),
        threads: Sequence[RedditThread] = (),
        comments: Sequence[RedditComment] = (),
        analyses: Sequence[AnalysisRow] = (),
    ) -> InsertCounts:
        _require_nonempty_string("post_id", post_id)
        expected = tuple(expected_statuses)
        if any(value not in _CANDIDATE_STATUSES for value in expected):
            raise ValueError("invalid expected candidate status")
        if len(set(expected)) != len(expected):
            raise ValueError("expected_statuses must not contain duplicates")
        if status not in _TERMINAL_CANDIDATE_STATUSES:
            raise ValueError("candidate finalization requires a terminal status")
        _validate_safe_reason(status_reason)
        _require_aware_datetime("updated_at_utc", updated_at_utc)

        captures = tuple(captures)
        threads = tuple(threads)
        comments = tuple(comments)
        analyses = tuple(analyses)
        conflict_key = f"backfill_candidates:{run_id}/{post_id}"
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            _require_run(conn, run_id)
            candidate = conn.execute(
                "SELECT status, status_reason FROM backfill_candidates "
                "WHERE run_id = ? AND post_id = ?",
                (run_id, post_id),
            ).fetchone()
            if candidate is None:
                raise KeyError(f"unknown backfill candidate: {run_id}/{post_id}")

            current_status = str(candidate["status"])
            current_reason = candidate["status_reason"]
            if current_status in _TERMINAL_CANDIDATE_STATUSES:
                if current_status != status or current_reason != status_reason:
                    raise BackfillConflictError(conflict_key)
                try:
                    _validate_candidate_finalization_bundle(
                        run_id=run_id,
                        post_id=post_id,
                        status=status,
                        captures=captures,
                        threads=threads,
                        comments=comments,
                        analyses=analyses,
                    )
                except ValueError:
                    raise BackfillConflictError(conflict_key) from None
                if status == "hydrated":
                    _verify_entity_bundle_conn(
                        conn,
                        captures=captures,
                        threads=threads,
                        comments=comments,
                        analyses=analyses,
                    )
                return InsertCounts()

            if current_status not in expected:
                raise BackfillConflictError(conflict_key)

            _validate_candidate_finalization_bundle(
                run_id=run_id,
                post_id=post_id,
                status=status,
                captures=captures,
                threads=threads,
                comments=comments,
                analyses=analyses,
            )

            counts = InsertCounts()
            if status == "hydrated":
                counts = _insert_entity_bundle_conn(
                    conn,
                    captures=captures,
                    threads=threads,
                    comments=comments,
                    analyses=analyses,
                )
            cursor = conn.execute(
                "UPDATE backfill_candidates "
                "SET status = ?, status_reason = ?, updated_at_utc = ? "
                "WHERE run_id = ? AND post_id = ? AND status = ?",
                (
                    status,
                    status_reason,
                    updated_at_utc.isoformat(),
                    run_id,
                    post_id,
                    current_status,
                ),
            )
            if cursor.rowcount != 1:
                raise BackfillConflictError(conflict_key)
            return counts

    def load_seed_file(
        self, run_id: str, input_path_hash: str
    ) -> dict[str, object] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM backfill_seed_files "
                "WHERE run_id = ? AND input_path_hash = ?",
                (run_id, input_path_hash),
            ).fetchone()
        return None if row is None else dict(row)

    def record_seed_file(
        self,
        *,
        run_id: str,
        input_path_hash: str,
        payload_sha256: str,
        outcome: Literal[
            "imported", "outside_window", "excluded", "duplicate", "parse_error"
        ],
        artifact_id: str,
        post_id: str | None,
        error_class: str | None,
        processed_at_utc: datetime,
    ) -> bool:
        allowed_outcomes = {
            "imported",
            "outside_window",
            "excluded",
            "duplicate",
            "parse_error",
        }
        if outcome not in allowed_outcomes:
            raise ValueError(f"invalid seed outcome: {outcome}")
        if error_class is not None and _ERROR_CLASS_PATTERN.fullmatch(error_class) is None:
            raise ValueError("invalid error_class")

        record: dict[str, object] = {
            "run_id": run_id,
            "input_path_hash": input_path_hash,
            "payload_sha256": payload_sha256,
            "outcome": outcome,
            "artifact_id": artifact_id,
            "post_id": post_id,
            "error_class": error_class,
            "processed_at_utc": processed_at_utc.isoformat(),
        }
        columns = tuple(record)
        expected = tuple(record[column] for column in columns)
        conflict_key = f"backfill_seed_files:{run_id}/{input_path_hash}"

        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                f"SELECT {', '.join(columns)} FROM backfill_seed_files "
                "WHERE run_id = ? AND input_path_hash = ?",
                (run_id, input_path_hash),
            ).fetchone()
            if existing is not None:
                actual = tuple(existing[column] for column in columns)
                if actual != expected:
                    raise BackfillConflictError(conflict_key)
                return False
            conn.execute(
                f"INSERT INTO backfill_seed_files({', '.join(columns)}) "
                f"VALUES ({', '.join(f':{column}' for column in columns)})",
                record,
            )
        return True

    def seed_file_count(self, run_id: str) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM backfill_seed_files WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return int(row["count"])

    def seed_outcome_counts(self, run_id: str) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT outcome, COUNT(*) AS count FROM backfill_seed_files "
                "WHERE run_id = ? GROUP BY outcome",
                (run_id,),
            ).fetchall()
        return {str(row["outcome"]): int(row["count"]) for row in rows}

    def set_backfill_status(
        self, run_id: str, status: str, updated_at_utc: datetime
    ) -> None:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            manifest = conn.execute(
                "SELECT status FROM backfill_manifests WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            run = conn.execute(
                "SELECT status FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if manifest is None or run is None:
                raise KeyError(f"unknown backfill run: {run_id}")
            if manifest["status"] == status and run["status"] == status:
                return
            manifest_cursor = conn.execute(
                "UPDATE backfill_manifests SET status = ?, updated_at_utc = ? "
                "WHERE run_id = ?",
                (status, updated_at_utc.isoformat(), run_id),
            )
            run_cursor = conn.execute(
                "UPDATE runs SET status = ? WHERE run_id = ?",
                (status, run_id),
            )
            if manifest_cursor.rowcount != 1 or run_cursor.rowcount != 1:
                raise KeyError(f"unknown backfill run: {run_id}")

    def freeze_full_collection_contract(
        self,
        run_id: str,
        *,
        expected_probe_request_count: int,
        max_provider_requests_total: int,
        include_subreddit_sweep: bool,
        required_lanes_sha256: str,
        updated_at_utc: datetime,
    ) -> None:
        if type(run_id) is not str or not run_id.strip():
            raise ValueError("run_id must be a non-empty string")
        if (
            type(expected_probe_request_count) is not int
            or not 1 <= expected_probe_request_count <= 4
        ):
            raise ValueError("expected_probe_request_count must be an integer from 1 to 4")
        if (
            type(max_provider_requests_total) is not int
            or max_provider_requests_total < 4
        ):
            raise ValueError("max_provider_requests_total must be an integer >= 4")
        if type(include_subreddit_sweep) is not bool:
            raise TypeError("include_subreddit_sweep must be a bool")
        if (
            type(required_lanes_sha256) is not str
            or _SHA256_PATTERN.fullmatch(required_lanes_sha256) is None
        ):
            raise ValueError("required_lanes_sha256 must be a lowercase SHA-256")
        if (
            not isinstance(updated_at_utc, datetime)
            or updated_at_utc.tzinfo is None
            or updated_at_utc.utcoffset() is None
        ):
            raise ValueError("updated_at_utc must be timezone-aware")

        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            manifest = conn.execute(
                "SELECT status, max_provider_requests, provider_request_count, "
                "include_subreddit_sweep, required_lanes_sha256 "
                "FROM backfill_manifests WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            run = conn.execute(
                "SELECT status FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if manifest is None or run is None:
                raise KeyError(f"unknown backfill run: {run_id}")

            current_status = str(manifest["status"])
            run_status = str(run["status"])
            current_max = int(manifest["max_provider_requests"])
            current_count = int(manifest["provider_request_count"])
            current_sweep = bool(manifest["include_subreddit_sweep"])
            current_lanes_sha256 = str(manifest["required_lanes_sha256"])
            if max_provider_requests_total < current_count:
                raise ValueError("collection budget is below the current request count")

            desired_contract = (
                max_provider_requests_total,
                include_subreddit_sweep,
                required_lanes_sha256,
            )
            current_contract = (
                current_max,
                current_sweep,
                current_lanes_sha256,
            )
            if current_status in {"running", "partial", "success"}:
                if run_status != current_status or current_contract != desired_contract:
                    raise ValueError("full collection contract is already frozen")
                return
            if current_status != "seed_complete" or run_status != "seed_complete":
                raise ValueError("probe state is not ready for full collection")
            if current_count != expected_probe_request_count:
                raise ValueError("probe request count changed")
            if current_max != 4 or current_sweep:
                raise ValueError("probe manifest contract is invalid")

            attempt_counts = conn.execute(
                "SELECT COUNT(*) AS total, "
                "SUM(CASE WHEN status IN ('succeeded', 'failed') THEN 1 ELSE 0 END) "
                "AS terminal, "
                "SUM(CASE WHEN status = 'succeeded' THEN 1 ELSE 0 END) AS succeeded "
                "FROM backfill_provider_attempts WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if (
                int(attempt_counts["total"] or 0) != current_count
                or int(attempt_counts["terminal"] or 0) != current_count
                or int(attempt_counts["succeeded"] or 0) < 1
            ):
                raise ValueError("probe attempt ledger is incomplete")

            updated_value = updated_at_utc.isoformat()
            manifest_cursor = conn.execute(
                "UPDATE backfill_manifests SET status = 'running', "
                "max_provider_requests = ?, include_subreddit_sweep = ?, "
                "required_lanes_sha256 = ?, updated_at_utc = ? WHERE run_id = ?",
                (
                    max_provider_requests_total,
                    int(include_subreddit_sweep),
                    required_lanes_sha256,
                    updated_value,
                    run_id,
                ),
            )
            run_cursor = conn.execute(
                "UPDATE runs SET status = 'running' WHERE run_id = ?", (run_id,)
            )
            if manifest_cursor.rowcount != 1 or run_cursor.rowcount != 1:
                raise KeyError(f"unknown backfill run: {run_id}")

    def extend_full_collection_budget(
        self,
        run_id: str,
        *,
        expected_provider_request_count: int,
        expected_max_provider_requests: int,
        new_max_provider_requests_total: int,
        discovery_request_ceiling: int,
        lane_page_ceilings_sha256: str,
        include_subreddit_sweep: bool,
        required_lanes_sha256: str,
        authorization_sha256: str,
        updated_at_utc: datetime,
    ) -> bool:
        _require_nonempty_string("run_id", run_id)
        for name, value in (
            ("expected_provider_request_count", expected_provider_request_count),
            ("expected_max_provider_requests", expected_max_provider_requests),
            ("new_max_provider_requests_total", new_max_provider_requests_total),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if expected_provider_request_count != expected_max_provider_requests:
            raise ValueError("budget extension requires an exhausted current budget")
        if new_max_provider_requests_total <= expected_max_provider_requests:
            raise ValueError("budget extension must increase the cumulative budget")
        if (
            type(discovery_request_ceiling) is not int
            or discovery_request_ceiling < expected_provider_request_count
            or discovery_request_ceiling >= new_max_provider_requests_total
        ):
            raise ValueError(
                "discovery_request_ceiling must be an integer between the "
                "expected request count and below the new cumulative budget"
            )
        if (
            type(lane_page_ceilings_sha256) is not str
            or _SHA256_PATTERN.fullmatch(lane_page_ceilings_sha256) is None
        ):
            raise ValueError(
                "lane_page_ceilings_sha256 must be a lowercase SHA-256"
            )
        if type(include_subreddit_sweep) is not bool:
            raise ValueError("include_subreddit_sweep must be a boolean")
        if (
            type(required_lanes_sha256) is not str
            or _SHA256_PATTERN.fullmatch(required_lanes_sha256) is None
        ):
            raise ValueError("required_lanes_sha256 must be a lowercase SHA-256")
        if (
            type(authorization_sha256) is not str
            or _SHA256_PATTERN.fullmatch(authorization_sha256) is None
        ):
            raise ValueError("authorization_sha256 must be a lowercase SHA-256")
        if (
            not isinstance(updated_at_utc, datetime)
            or updated_at_utc.tzinfo is None
            or updated_at_utc.utcoffset() is None
        ):
            raise ValueError("updated_at_utc must be timezone-aware")

        expected_extension = (
            expected_provider_request_count,
            expected_max_provider_requests,
            new_max_provider_requests_total,
            discovery_request_ceiling,
            lane_page_ceilings_sha256,
            int(include_subreddit_sweep),
            required_lanes_sha256,
        )
        conflict_key = (
            f"backfill_budget_extensions:{run_id}/{authorization_sha256}"
        )
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            manifest = conn.execute(
                "SELECT status, max_provider_requests, provider_request_count, "
                "provider_call, include_subreddit_sweep, required_lanes_sha256 "
                "FROM backfill_manifests WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            run = conn.execute(
                "SELECT status, provider_call FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if manifest is None or run is None:
                raise KeyError(f"unknown backfill run: {run_id}")

            current_status = str(manifest["status"])
            run_status = str(run["status"])
            current_max = int(manifest["max_provider_requests"])
            current_count = int(manifest["provider_request_count"])
            existing = conn.execute(
                "SELECT expected_provider_request_count, "
                "expected_max_provider_requests, new_max_provider_requests, "
                "discovery_request_ceiling, lane_page_ceilings_sha256, "
                "include_subreddit_sweep, required_lanes_sha256 "
                "FROM backfill_budget_extensions "
                "WHERE run_id = ? AND authorization_sha256 = ?",
                (run_id, authorization_sha256),
            ).fetchone()
            if existing is not None:
                actual_extension = (
                    int(existing["expected_provider_request_count"]),
                    int(existing["expected_max_provider_requests"]),
                    int(existing["new_max_provider_requests"]),
                    int(existing["discovery_request_ceiling"]),
                    str(existing["lane_page_ceilings_sha256"]),
                    int(existing["include_subreddit_sweep"]),
                    str(existing["required_lanes_sha256"]),
                )
                if actual_extension != expected_extension:
                    raise BackfillConflictError(conflict_key)

            live_scope_matches_authorization = (
                int(manifest["include_subreddit_sweep"])
                == int(include_subreddit_sweep)
                and str(manifest["required_lanes_sha256"])
                == required_lanes_sha256
            )
            if not live_scope_matches_authorization:
                if existing is not None:
                    raise BackfillConflictError(conflict_key)
                raise ValueError("budget extension collection scope changed")

            attempt_counts = conn.execute(
                "SELECT COUNT(*) AS total, "
                "SUM(CASE WHEN status IN ('succeeded', 'failed') THEN 1 ELSE 0 END) "
                "AS terminal, MIN(request_number) AS minimum, "
                "MAX(request_number) AS maximum "
                "FROM backfill_provider_attempts WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            ledger_complete = bool(
                current_count > 0
                and int(attempt_counts["total"] or 0) == current_count
                and int(attempt_counts["terminal"] or 0) == current_count
                and int(attempt_counts["minimum"] or 0) == 1
                and int(attempt_counts["maximum"] or 0) == current_count
                and int(manifest["provider_call"]) == 1
                and int(run["provider_call"]) == 1
            )
            if not ledger_complete:
                raise ValueError("provider attempt ledger is incomplete or in flight")

            if existing is not None:
                if (
                    current_status not in {"running", "partial", "success"}
                    or run_status != current_status
                    or current_max != new_max_provider_requests_total
                    or current_count < expected_provider_request_count
                    or current_count > new_max_provider_requests_total
                ):
                    raise BackfillConflictError(conflict_key)
                return False

            if current_status != "partial" or run_status != "partial":
                raise ValueError("collection state is not ready for budget extension")
            if (
                current_count != expected_provider_request_count
                or current_max != expected_max_provider_requests
                or current_count != current_max
            ):
                raise ValueError("budget extension expected state changed")

            try:
                conn.execute(
                    "INSERT INTO backfill_budget_extensions("
                    "run_id, authorization_sha256, "
                    "expected_provider_request_count, "
                    "expected_max_provider_requests, new_max_provider_requests, "
                    "discovery_request_ceiling, lane_page_ceilings_sha256, "
                    "include_subreddit_sweep, required_lanes_sha256, "
                    "applied_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        authorization_sha256,
                        expected_provider_request_count,
                        expected_max_provider_requests,
                        new_max_provider_requests_total,
                        discovery_request_ceiling,
                        lane_page_ceilings_sha256,
                        int(include_subreddit_sweep),
                        required_lanes_sha256,
                        updated_at_utc.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError:
                raise BackfillConflictError(conflict_key) from None
            cursor = conn.execute(
                "UPDATE backfill_manifests "
                "SET max_provider_requests = ?, updated_at_utc = ? "
                "WHERE run_id = ? AND max_provider_requests = ? "
                "AND provider_request_count = ?",
                (
                    new_max_provider_requests_total,
                    updated_at_utc.isoformat(),
                    run_id,
                    expected_max_provider_requests,
                    expected_provider_request_count,
                ),
            )
            if cursor.rowcount != 1:
                raise BackfillConflictError(conflict_key)
            return True

    def record_existing_budget_resume_authorization(
        self,
        run_id: str,
        *,
        authorization_sha256: str,
        expected_source_database_sha256: str,
        expected_provider_request_count: int,
        max_provider_requests: int,
        discovery_request_ceiling: int,
        lane_page_ceilings_sha256: str,
        candidate_state_sha256: str,
        include_subreddit_sweep: bool,
        required_lanes_sha256: str,
        applied_at_utc: datetime,
    ) -> bool:
        _require_nonempty_string("run_id", run_id)
        for name, value in (
            ("expected_provider_request_count", expected_provider_request_count),
            ("max_provider_requests", max_provider_requests),
            ("discovery_request_ceiling", discovery_request_ceiling),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if expected_provider_request_count >= max_provider_requests:
            raise ValueError("existing budget resume requires remaining budget")
        if not (
            expected_provider_request_count
            <= discovery_request_ceiling
            <= max_provider_requests
        ):
            raise ValueError("discovery_request_ceiling is outside the live budget")
        for name, value in (
            ("authorization_sha256", authorization_sha256),
            ("expected_source_database_sha256", expected_source_database_sha256),
            ("lane_page_ceilings_sha256", lane_page_ceilings_sha256),
            ("candidate_state_sha256", candidate_state_sha256),
            ("required_lanes_sha256", required_lanes_sha256),
        ):
            if type(value) is not str or _SHA256_PATTERN.fullmatch(value) is None:
                raise ValueError(f"{name} must be a lowercase SHA-256")
        if type(include_subreddit_sweep) is not bool:
            raise ValueError("include_subreddit_sweep must be a boolean")
        _require_aware_datetime("applied_at_utc", applied_at_utc)

        expected = (
            expected_source_database_sha256,
            expected_provider_request_count,
            max_provider_requests,
            discovery_request_ceiling,
            lane_page_ceilings_sha256,
            candidate_state_sha256,
            int(include_subreddit_sweep),
            required_lanes_sha256,
        )
        conflict_key = (
            f"backfill_collection_resumes:{run_id}/{authorization_sha256}"
        )
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            manifest = conn.execute(
                "SELECT status, max_provider_requests, provider_request_count, "
                "provider_call, live_send, include_subreddit_sweep, "
                "required_lanes_sha256 FROM backfill_manifests WHERE run_id=?",
                (run_id,),
            ).fetchone()
            run = conn.execute(
                "SELECT status, provider_call, live_send FROM runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if manifest is None or run is None:
                raise KeyError(f"unknown backfill run: {run_id}")
            current_count = int(manifest["provider_request_count"])
            current_max = int(manifest["max_provider_requests"])
            existing = conn.execute(
                "SELECT expected_source_database_sha256, "
                "expected_provider_request_count, max_provider_requests, "
                "discovery_request_ceiling, lane_page_ceilings_sha256, "
                "candidate_state_sha256, include_subreddit_sweep, "
                "required_lanes_sha256 FROM backfill_collection_resumes "
                "WHERE run_id=? AND authorization_sha256=?",
                (run_id, authorization_sha256),
            ).fetchone()
            if existing is not None and tuple(existing) != expected:
                raise BackfillConflictError(conflict_key)
            scope_matches = bool(
                int(manifest["include_subreddit_sweep"])
                == int(include_subreddit_sweep)
                and str(manifest["required_lanes_sha256"])
                == required_lanes_sha256
            )
            attempts = conn.execute(
                "SELECT COUNT(*) AS total, "
                "SUM(CASE WHEN status IN ('succeeded','failed') THEN 1 ELSE 0 END) "
                "AS terminal, MIN(request_number) AS minimum, "
                "MAX(request_number) AS maximum "
                "FROM backfill_provider_attempts WHERE run_id=?",
                (run_id,),
            ).fetchone()
            ledger_complete = bool(
                current_count > 0
                and int(attempts["total"] or 0) == current_count
                and int(attempts["terminal"] or 0) == current_count
                and int(attempts["minimum"] or 0) == 1
                and int(attempts["maximum"] or 0) == current_count
                and int(manifest["provider_call"]) == 1
                and int(run["provider_call"]) == 1
                and int(manifest["live_send"]) == 0
                and int(run["live_send"]) == 0
            )
            if not scope_matches or not ledger_complete:
                if existing is not None:
                    raise BackfillConflictError(conflict_key)
                raise ValueError("existing budget resume live state invalid")
            if existing is not None:
                if (
                    str(manifest["status"]) not in {"running", "partial", "success"}
                    or str(run["status"]) != str(manifest["status"])
                    or current_max != max_provider_requests
                    or not expected_provider_request_count
                    <= current_count
                    <= max_provider_requests
                ):
                    raise BackfillConflictError(conflict_key)
                return False
            if (
                str(manifest["status"]) != "partial"
                or str(run["status"]) != "partial"
                or current_count != expected_provider_request_count
                or current_max != max_provider_requests
            ):
                raise ValueError("existing budget resume expected state changed")
            try:
                conn.execute(
                    "INSERT INTO backfill_collection_resumes("
                    "run_id, authorization_sha256, "
                    "expected_source_database_sha256, "
                    "expected_provider_request_count, max_provider_requests, "
                    "discovery_request_ceiling, lane_page_ceilings_sha256, "
                    "candidate_state_sha256, include_subreddit_sweep, "
                    "required_lanes_sha256, applied_at_utc"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        authorization_sha256,
                        *expected,
                        applied_at_utc.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError:
                raise BackfillConflictError(conflict_key) from None
            return True

    def resume_budget_exhausted_hydration(
        self,
        run_id: str,
        *,
        authorization_sha256: str,
        updated_at_utc: datetime,
    ) -> bool:
        _require_nonempty_string("run_id", run_id)
        if (
            type(authorization_sha256) is not str
            or _SHA256_PATTERN.fullmatch(authorization_sha256) is None
        ):
            raise ValueError("authorization_sha256 must be a lowercase SHA-256")
        _require_aware_datetime("updated_at_utc", updated_at_utc)
        conflict_key = (
            f"backfill_hydration_resumes:{run_id}/{authorization_sha256}"
        )

        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            extension = conn.execute(
                "SELECT expected_provider_request_count, "
                "expected_max_provider_requests, new_max_provider_requests, "
                "discovery_request_ceiling, lane_page_ceilings_sha256, "
                "include_subreddit_sweep, required_lanes_sha256 "
                "FROM backfill_budget_extensions "
                "WHERE run_id = ? AND authorization_sha256 = ?",
                (run_id, authorization_sha256),
            ).fetchone()
            manifest = conn.execute(
                "SELECT status, max_provider_requests, provider_request_count, "
                "provider_call, live_send, include_subreddit_sweep, "
                "required_lanes_sha256 FROM backfill_manifests WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            run = conn.execute(
                "SELECT status, provider_call, live_send FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if extension is None or manifest is None or run is None:
                raise BackfillConflictError(conflict_key)

            expected_count = int(extension["expected_provider_request_count"])
            expected_max = int(extension["expected_max_provider_requests"])
            new_max = int(extension["new_max_provider_requests"])
            discovery_ceiling = int(extension["discovery_request_ceiling"])
            current_count = int(manifest["provider_request_count"])
            authorization_is_current = (
                expected_count == expected_max
                and new_max > expected_max
                and expected_count <= discovery_ceiling < new_max
                and _SHA256_PATTERN.fullmatch(
                    str(extension["lane_page_ceilings_sha256"])
                )
                is not None
                and _SHA256_PATTERN.fullmatch(
                    str(extension["required_lanes_sha256"])
                )
                is not None
                and int(extension["include_subreddit_sweep"]) in {0, 1}
                and int(manifest["max_provider_requests"]) == new_max
                and expected_count <= current_count <= discovery_ceiling
                and current_count < new_max
                and str(manifest["status"]) == "partial"
                and str(run["status"]) == "partial"
                and int(manifest["provider_call"]) == 1
                and int(run["provider_call"]) == 1
                and int(manifest["live_send"]) == 0
                and int(run["live_send"]) == 0
                and int(manifest["include_subreddit_sweep"])
                == int(extension["include_subreddit_sweep"])
                and str(manifest["required_lanes_sha256"])
                == str(extension["required_lanes_sha256"])
            )
            if not authorization_is_current:
                raise BackfillConflictError(conflict_key)

            attempt_counts = conn.execute(
                "SELECT COUNT(*) AS total, "
                "SUM(CASE WHEN status IN ('succeeded', 'failed') THEN 1 ELSE 0 END) "
                "AS terminal, MIN(request_number) AS minimum, "
                "MAX(request_number) AS maximum "
                "FROM backfill_provider_attempts WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            attempt_ledger_is_exact = bool(
                current_count > 0
                and int(attempt_counts["total"] or 0) == current_count
                and int(attempt_counts["terminal"] or 0) == current_count
                and int(attempt_counts["minimum"] or 0) == 1
                and int(attempt_counts["maximum"] or 0) == current_count
            )
            if not attempt_ledger_is_exact:
                raise BackfillConflictError(conflict_key)

            existing = conn.execute(
                "SELECT candidate_post_ids_json, candidate_post_ids_sha256, "
                "batch_membership_json, batch_membership_sha256, "
                "candidate_count, batch_count, applied_at_utc "
                "FROM backfill_hydration_resumes "
                "WHERE run_id = ? AND authorization_sha256 = ?",
                (run_id, authorization_sha256),
            ).fetchone()
            if existing is not None:
                try:
                    candidate_ids, recorded_membership = (
                        _decode_hydration_resume_ledger(existing)
                    )
                except (TypeError, ValueError, json.JSONDecodeError):
                    raise BackfillConflictError(conflict_key) from None
                batch_ids = tuple(item[0] for item in recorded_membership)
                candidate_placeholders = ", ".join("?" for _ in candidate_ids)
                candidate_rows = conn.execute(
                    "SELECT post_id, status, status_reason, updated_at_utc "
                    "FROM backfill_candidates WHERE run_id = ? "
                    f"AND post_id IN ({candidate_placeholders}) ORDER BY post_id",
                    (run_id, *candidate_ids),
                ).fetchall()
                batch_placeholders = ", ".join("?" for _ in batch_ids)
                batch_rows = conn.execute(
                    "SELECT * FROM backfill_detail_batches WHERE run_id = ? "
                    f"AND batch_id IN ({batch_placeholders}) "
                    "ORDER BY batch_number, batch_id",
                    (run_id, *batch_ids),
                ).fetchall()
                applied_at = str(existing["applied_at_utc"])
                current_membership = tuple(
                    (
                        batch.batch_id,
                        batch.batch_number,
                        batch.post_ids,
                    )
                    for batch in (
                        _detail_batch_from_row(conn, row) for row in batch_rows
                    )
                )
                candidate_state_is_exact = (
                    len(candidate_rows) == len(candidate_ids)
                    and tuple(str(row["post_id"]) for row in candidate_rows)
                    == candidate_ids
                    and all(
                        row["status"] == "pending"
                        and row["status_reason"] is None
                        and str(row["updated_at_utc"]) == applied_at
                        for row in candidate_rows
                    )
                )
                batch_state_is_exact = (
                    len(batch_rows) == len(batch_ids)
                    and current_membership == recorded_membership
                    and all(
                        row["status"] == "prepared"
                        and row["artifact_id"] is None
                        and row["stop_reason"] is None
                        and str(row["updated_at_utc"]) == applied_at
                        for row in batch_rows
                    )
                )
                if (
                    not candidate_state_is_exact
                    or not batch_state_is_exact
                    or _hydration_resume_has_existing_evidence(
                        conn,
                        run_id=run_id,
                        candidate_ids=candidate_ids,
                        batch_ids=batch_ids,
                    )
                ):
                    raise BackfillConflictError(conflict_key)
                return False

            candidate_contract_drift = conn.execute(
                "SELECT 1 FROM backfill_candidates WHERE run_id = ? "
                "AND (status = 'budget_deferred' "
                "OR status_reason = 'budget_exhausted') "
                "AND NOT (status = 'budget_deferred' "
                "AND status_reason = 'budget_exhausted') LIMIT 1",
                (run_id,),
            ).fetchone()
            batch_contract_drift = conn.execute(
                "SELECT 1 FROM backfill_detail_batches WHERE run_id = ? "
                "AND stop_reason = 'budget_exhausted' "
                "AND NOT (status = 'failed' AND artifact_id IS NULL) LIMIT 1",
                (run_id,),
            ).fetchone()
            if candidate_contract_drift is not None or batch_contract_drift is not None:
                raise BackfillConflictError(conflict_key)

            candidate_rows = conn.execute(
                "SELECT post_id FROM backfill_candidates WHERE run_id = ? "
                "AND status = 'budget_deferred' "
                "AND status_reason = 'budget_exhausted' ORDER BY post_id",
                (run_id,),
            ).fetchall()
            batch_rows = conn.execute(
                "SELECT * FROM backfill_detail_batches WHERE run_id = ? "
                "AND status = 'failed' AND stop_reason = 'budget_exhausted' "
                "AND artifact_id IS NULL ORDER BY batch_number, batch_id",
                (run_id,),
            ).fetchall()
            candidate_ids = tuple(str(row["post_id"]) for row in candidate_rows)
            batches = tuple(_detail_batch_from_row(conn, row) for row in batch_rows)
            batch_ids = tuple(batch.batch_id for batch in batches)
            batch_members = tuple(
                post_id for batch in batches for post_id in batch.post_ids
            )
            if (
                not candidate_ids
                or not batches
                or len(batch_members) != len(candidate_ids)
                or set(batch_members) != set(candidate_ids)
            ):
                raise BackfillConflictError(conflict_key)
            if _hydration_resume_has_existing_evidence(
                conn,
                run_id=run_id,
                candidate_ids=candidate_ids,
                batch_ids=batch_ids,
            ):
                raise BackfillConflictError(conflict_key)

            membership = tuple(
                (batch.batch_id, batch.batch_number, batch.post_ids)
                for batch in batches
            )
            candidate_json = _canonical_json(candidate_ids)
            membership_json = _canonical_json(membership)
            candidate_sha256 = sha256(candidate_json.encode()).hexdigest()
            membership_sha256 = sha256(membership_json.encode()).hexdigest()
            updated_text = updated_at_utc.isoformat()
            candidate_placeholders = ", ".join("?" for _ in candidate_ids)
            candidate_cursor = conn.execute(
                "UPDATE backfill_candidates SET status = 'pending', "
                "status_reason = NULL, updated_at_utc = ? WHERE run_id = ? "
                f"AND post_id IN ({candidate_placeholders}) "
                "AND status = 'budget_deferred' "
                "AND status_reason = 'budget_exhausted'",
                (updated_text, run_id, *candidate_ids),
            )
            batch_placeholders = ", ".join("?" for _ in batch_ids)
            batch_cursor = conn.execute(
                "UPDATE backfill_detail_batches SET status = 'prepared', "
                "artifact_id = NULL, stop_reason = NULL, updated_at_utc = ? "
                "WHERE run_id = ? "
                f"AND batch_id IN ({batch_placeholders}) "
                "AND status = 'failed' AND stop_reason = 'budget_exhausted' "
                "AND artifact_id IS NULL",
                (updated_text, run_id, *batch_ids),
            )
            if (
                candidate_cursor.rowcount != len(candidate_ids)
                or batch_cursor.rowcount != len(batch_ids)
            ):
                raise BackfillConflictError(conflict_key)
            try:
                conn.execute(
                    "INSERT INTO backfill_hydration_resumes("
                    "run_id, authorization_sha256, candidate_post_ids_json, "
                    "candidate_post_ids_sha256, batch_membership_json, "
                    "batch_membership_sha256, candidate_count, batch_count, "
                    "applied_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        authorization_sha256,
                        candidate_json,
                        candidate_sha256,
                        membership_json,
                        membership_sha256,
                        len(candidate_ids),
                        len(batch_ids),
                        updated_text,
                    ),
                )
            except sqlite3.IntegrityError:
                raise BackfillConflictError(conflict_key) from None
            return True

    def hydration_resume_recorded(
        self, run_id: str, authorization_sha256: str
    ) -> bool:
        _require_nonempty_string("run_id", run_id)
        if (
            type(authorization_sha256) is not str
            or _SHA256_PATTERN.fullmatch(authorization_sha256) is None
        ):
            raise ValueError("authorization_sha256 must be a lowercase SHA-256")
        conflict_key = (
            f"backfill_hydration_resumes:{run_id}/{authorization_sha256}"
        )
        with self.connect() as conn:
            resume = conn.execute(
                "SELECT candidate_post_ids_json, candidate_post_ids_sha256, "
                "batch_membership_json, batch_membership_sha256, "
                "candidate_count, batch_count, applied_at_utc "
                "FROM backfill_hydration_resumes "
                "WHERE run_id = ? AND authorization_sha256 = ?",
                (run_id, authorization_sha256),
            ).fetchone()
            if resume is None:
                return False
            extension = conn.execute(
                "SELECT 1 FROM backfill_budget_extensions "
                "WHERE run_id = ? AND authorization_sha256 = ?",
                (run_id, authorization_sha256),
            ).fetchone()
            if extension is None:
                raise BackfillConflictError(conflict_key)
            try:
                candidate_ids, recorded_membership = (
                    _decode_hydration_resume_ledger(resume)
                )
            except (TypeError, ValueError, json.JSONDecodeError):
                raise BackfillConflictError(conflict_key) from None

            candidate_placeholders = ", ".join("?" for _ in candidate_ids)
            candidate_rows = conn.execute(
                "SELECT post_id FROM backfill_candidates WHERE run_id = ? "
                f"AND post_id IN ({candidate_placeholders}) ORDER BY post_id",
                (run_id, *candidate_ids),
            ).fetchall()
            if (
                tuple(str(row["post_id"]) for row in candidate_rows)
                != candidate_ids
            ):
                raise BackfillConflictError(conflict_key)

            batch_ids = tuple(item[0] for item in recorded_membership)
            batch_placeholders = ", ".join("?" for _ in batch_ids)
            batch_rows = conn.execute(
                "SELECT * FROM backfill_detail_batches WHERE run_id = ? "
                f"AND batch_id IN ({batch_placeholders}) "
                "ORDER BY batch_number, batch_id",
                (run_id, *batch_ids),
            ).fetchall()
            current_membership = tuple(
                (batch.batch_id, batch.batch_number, batch.post_ids)
                for batch in (
                    _detail_batch_from_row(conn, row) for row in batch_rows
                )
            )
            if current_membership != recorded_membership:
                raise BackfillConflictError(conflict_key)
            return True

    def reserve_provider_request(
        self,
        run_id: str,
        endpoint: str,
        reserved_at_utc: datetime,
        *,
        request_ceiling: int | None = None,
    ) -> int | None:
        if (
            not isinstance(endpoint, str)
            or endpoint.startswith("//")
            or _PROVIDER_ENDPOINT_PATTERN.fullmatch(endpoint) is None
        ):
            raise ValueError("invalid provider endpoint")
        if request_ceiling is not None and (
            type(request_ceiling) is not int or request_ceiling < 0
        ):
            raise ValueError("request_ceiling must be a non-negative integer or None")
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT max_provider_requests, provider_request_count "
                "FROM backfill_manifests WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown backfill run: {run_id}")
            request_limit = int(row["max_provider_requests"])
            if request_ceiling is not None:
                request_limit = min(request_limit, request_ceiling)
            if int(row["provider_request_count"]) >= request_limit:
                return None
            next_count = int(row["provider_request_count"]) + 1
            conn.execute(
                "INSERT INTO backfill_provider_attempts("
                "run_id, request_number, endpoint, status, reserved_at_utc"
                ") VALUES (?, ?, ?, 'reserved', ?)",
                (run_id, next_count, endpoint, reserved_at_utc.isoformat()),
            )
            conn.execute(
                "UPDATE backfill_manifests "
                "SET provider_request_count = ?, updated_at_utc = ? WHERE run_id = ?",
                (next_count, reserved_at_utc.isoformat(), run_id),
            )
            return next_count

    def provider_request_count(self, run_id: str) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT provider_request_count FROM backfill_manifests WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown backfill run: {run_id}")
        return int(row["provider_request_count"])

    def mark_provider_attempt_sent(
        self, run_id: str, request_number: int, sent_at_utc: datetime
    ) -> None:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                "UPDATE backfill_provider_attempts "
                "SET status = 'sent', sent_at_utc = ? "
                "WHERE run_id = ? AND request_number = ? AND status = 'reserved'",
                (sent_at_utc.isoformat(), run_id, request_number),
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    f"provider attempt is missing or not reserved: {run_id}/{request_number}"
                )
            manifest_cursor = conn.execute(
                "UPDATE backfill_manifests "
                "SET provider_call = 1, updated_at_utc = ? WHERE run_id = ?",
                (sent_at_utc.isoformat(), run_id),
            )
            run_cursor = conn.execute(
                "UPDATE runs SET provider_call = 1 WHERE run_id = ?",
                (run_id,),
            )
            if manifest_cursor.rowcount != 1 or run_cursor.rowcount != 1:
                raise ValueError(f"incomplete provider evidence state for run: {run_id}")

    def complete_provider_attempt(
        self,
        run_id: str,
        request_number: int,
        *,
        status: Literal["succeeded", "failed"],
        completed_at_utc: datetime,
        http_status: int | None = None,
        error_class: str | None = None,
    ) -> None:
        if status not in {"succeeded", "failed"}:
            raise ValueError(f"invalid terminal provider attempt status: {status}")
        if error_class is not None and _ERROR_CLASS_PATTERN.fullmatch(error_class) is None:
            raise ValueError("invalid error_class")

        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                "UPDATE backfill_provider_attempts "
                "SET status = ?, completed_at_utc = ?, http_status = ?, error_class = ? "
                "WHERE run_id = ? AND request_number = ? AND status = 'sent'",
                (
                    status,
                    completed_at_utc.isoformat(),
                    http_status,
                    error_class,
                    run_id,
                    request_number,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    f"provider attempt is missing or not sent: {run_id}/{request_number}"
                )

    def provider_call_evidence(self, run_id: str) -> bool:
        with self.connect() as conn:
            manifest = conn.execute(
                "SELECT 1 FROM backfill_manifests WHERE run_id = ?", (run_id,)
            ).fetchone()
            if manifest is None:
                raise KeyError(f"unknown backfill run: {run_id}")
            row = conn.execute(
                "SELECT EXISTS(SELECT 1 FROM backfill_provider_attempts "
                "WHERE run_id = ? AND sent_at_utc IS NOT NULL) AS value",
                (run_id,),
            ).fetchone()
        return bool(row["value"])

    def record_discovery_occurrence(
        self,
        *,
        run_id: str,
        lane_type: LaneType,
        lane_key: str,
        page_number: int,
        ordinal: int,
        post_id: str | None,
        source_url: str | None,
        post_created_at_utc: datetime | None,
        raw_artifact_id: str,
        discovered_at_utc: datetime,
        base_disposition: Literal["eligible", "outside_window", "invalid"],
    ) -> DiscoveryDisposition:
        if lane_type not in {"dynamic_search", "subreddit_feed"}:
            raise ValueError("invalid discovery lane type")
        if (
            isinstance(page_number, bool)
            or not isinstance(page_number, int)
            or page_number < 0
        ):
            raise ValueError("page_number must be a non-negative integer")
        if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 0:
            raise ValueError("ordinal must be a non-negative integer")
        if base_disposition not in {"eligible", "outside_window", "invalid"}:
            raise ValueError("invalid base discovery disposition")
        if discovered_at_utc.tzinfo is None:
            raise ValueError("discovered_at_utc must be timezone-aware")
        if post_created_at_utc is not None and post_created_at_utc.tzinfo is None:
            raise ValueError("post_created_at_utc must be timezone-aware")
        if base_disposition == "eligible" and (
            not post_id or not source_url or post_created_at_utc is None
        ):
            raise ValueError("eligible discovery occurrence is incomplete")
        if post_id is not None and not isinstance(post_id, str):
            raise ValueError("post_id must be a string or None")
        if source_url is not None and not isinstance(source_url, str):
            raise ValueError("source_url must be a string or None")

        post_created_text = (
            None if post_created_at_utc is None else post_created_at_utc.isoformat()
        )
        discovered_text = discovered_at_utc.isoformat()
        key = (run_id, lane_type, lane_key, page_number, ordinal)
        conflict_key = (
            "backfill_discovery_occurrences:"
            f"{run_id}/{lane_type}/{lane_key}/{page_number}/{ordinal}"
        )
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT post_id, source_url, post_created_at_utc, "
                "raw_artifact_id, discovered_at_utc, disposition "
                "FROM backfill_discovery_occurrences "
                "WHERE run_id = ? AND lane_type = ? AND lane_key = ? "
                "AND page_number = ? AND ordinal = ?",
                key,
            ).fetchone()
            if existing is not None:
                expected_base = _base_disposition(str(existing["disposition"]))
                actual = (
                    existing["post_id"],
                    existing["source_url"],
                    existing["post_created_at_utc"],
                    existing["raw_artifact_id"],
                    existing["discovered_at_utc"],
                    expected_base,
                )
                expected = (
                    post_id,
                    source_url,
                    post_created_text,
                    raw_artifact_id,
                    discovered_text,
                    base_disposition,
                )
                if actual != expected:
                    raise BackfillConflictError(conflict_key)
                return existing["disposition"]

            disposition: DiscoveryDisposition
            if base_disposition == "outside_window":
                disposition = "outside_window"
            elif base_disposition == "invalid":
                disposition = "invalid"
            else:
                structured = conn.execute(
                    "SELECT 1 FROM reddit_threads WHERE post_id = ?", (post_id,)
                ).fetchone()
                if structured is not None:
                    disposition = "duplicate_existing_structured"
                else:
                    candidate = conn.execute(
                        "SELECT 1 FROM backfill_candidates "
                        "WHERE run_id = ? AND post_id = ?",
                        (run_id, post_id),
                    ).fetchone()
                    if candidate is not None:
                        disposition = "duplicate_occurrence"
                    else:
                        conn.execute(
                            "INSERT INTO backfill_candidates("
                            "run_id, post_id, first_lane_type, first_lane_key, "
                            "first_discovered_at_utc, source_url, post_created_at_utc, "
                            "raw_artifact_id, status, status_reason, updated_at_utc"
                            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL, ?)",
                            (
                                run_id,
                                post_id,
                                lane_type,
                                lane_key,
                                discovered_text,
                                source_url,
                                post_created_text,
                                raw_artifact_id,
                                discovered_text,
                            ),
                        )
                        disposition = "new_candidate"

            conn.execute(
                "INSERT INTO backfill_discovery_occurrences("
                "run_id, lane_type, lane_key, page_number, ordinal, post_id, "
                "source_url, post_created_at_utc, raw_artifact_id, "
                "discovered_at_utc, disposition"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    *key,
                    post_id,
                    source_url,
                    post_created_text,
                    raw_artifact_id,
                    discovered_text,
                    disposition,
                ),
            )
        return disposition

    def discovery_occurrence_counts(
        self, run_id: str, lane_type: LaneType, lane_key: str
    ) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT disposition, COUNT(*) AS count "
                "FROM backfill_discovery_occurrences "
                "WHERE run_id = ? AND lane_type = ? AND lane_key = ? "
                "GROUP BY disposition",
                (run_id, lane_type, lane_key),
            ).fetchall()
        return {str(row["disposition"]): int(row["count"]) for row in rows}

    def candidate_count(self, run_id: str) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM backfill_candidates WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return int(row["count"])

    def request_cursor_seen(
        self,
        run_id: str,
        lane_type: LaneType,
        lane_key_hash: str,
        cursor: str,
    ) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT EXISTS(SELECT 1 FROM backfill_raw_artifacts "
                "WHERE run_id = ? AND lane_type = ? AND lane_key_hash = ? "
                "AND request_cursor = ?) AS value",
                (run_id, lane_type, lane_key_hash, cursor),
            ).fetchone()
        return bool(row["value"])

    def save_checkpoint(self, checkpoint: BackfillCheckpoint) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO backfill_checkpoints(
                    run_id, lane_type, lane_key, cursor, previous_cursor,
                    page_number, newest_seen_utc, oldest_seen_utc,
                    discovered_count, unique_count, provider_request_count,
                    last_success_utc, last_error, status, stop_reason,
                    cursor_json_path, cursor_schema_sha256, consecutive_old_pages
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, lane_type, lane_key) DO UPDATE SET
                    cursor = excluded.cursor,
                    previous_cursor = excluded.previous_cursor,
                    page_number = excluded.page_number,
                    newest_seen_utc = excluded.newest_seen_utc,
                    oldest_seen_utc = excluded.oldest_seen_utc,
                    discovered_count = excluded.discovered_count,
                    unique_count = excluded.unique_count,
                    provider_request_count = excluded.provider_request_count,
                    last_success_utc = excluded.last_success_utc,
                    last_error = excluded.last_error,
                    status = excluded.status,
                    stop_reason = excluded.stop_reason,
                    cursor_json_path = excluded.cursor_json_path,
                    cursor_schema_sha256 = excluded.cursor_schema_sha256,
                    consecutive_old_pages = excluded.consecutive_old_pages
                """,
                (
                    checkpoint.run_id,
                    checkpoint.lane_type,
                    checkpoint.lane_key,
                    checkpoint.cursor,
                    checkpoint.previous_cursor,
                    checkpoint.page_number,
                    checkpoint.newest_seen_utc,
                    checkpoint.oldest_seen_utc,
                    checkpoint.discovered_count,
                    checkpoint.unique_count,
                    checkpoint.provider_request_count,
                    checkpoint.last_success_utc,
                    checkpoint.last_error,
                    checkpoint.status,
                    checkpoint.stop_reason,
                    checkpoint.cursor_json_path,
                    checkpoint.cursor_schema_sha256,
                    checkpoint.consecutive_old_pages,
                ),
            )

    def load_checkpoint(
        self, *, run_id: str, lane_type: LaneType, lane_key: str
    ) -> BackfillCheckpoint | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM backfill_checkpoints "
                "WHERE run_id = ? AND lane_type = ? AND lane_key = ?",
                (run_id, lane_type, lane_key),
            ).fetchone()
        if row is None:
            return None
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


def _require_run(conn: sqlite3.Connection, run_id: str) -> None:
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be a non-empty string")
    row = conn.execute(
        "SELECT 1 FROM backfill_manifests WHERE run_id = ?", (run_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown backfill run: {run_id}")


def _authorization_ledger_schema_is_compatible(
    conn: sqlite3.Connection, table: str
) -> bool:
    def sha_check(column: str) -> str:
        return _normalize_sql_fragment(
            f"length({column}) = 64 AND {column} NOT GLOB '*[^0-9a-f]*'"
        )

    if table == "backfill_budget_extensions":
        expected_primary_key = ("run_id", "authorization_sha256")
        expected_columns = (
            ("run_id", "TEXT", 1, None, 1),
            ("authorization_sha256", "TEXT", 1, None, 2),
            ("expected_provider_request_count", "INTEGER", 1, None, 0),
            ("expected_max_provider_requests", "INTEGER", 1, None, 0),
            ("new_max_provider_requests", "INTEGER", 1, None, 0),
            ("discovery_request_ceiling", "INTEGER", 1, None, 0),
            ("lane_page_ceilings_sha256", "TEXT", 1, None, 0),
            ("include_subreddit_sweep", "INTEGER", 1, None, 0),
            ("required_lanes_sha256", "TEXT", 1, None, 0),
            ("applied_at_utc", "TEXT", 1, None, 0),
        )
        expected_checks = {
            sha_check("authorization_sha256"),
            _normalize_sql_fragment("expected_provider_request_count >= 0"),
            _normalize_sql_fragment("expected_max_provider_requests >= 0"),
            _normalize_sql_fragment(
                "new_max_provider_requests > expected_max_provider_requests"
            ),
            _normalize_sql_fragment(
                "discovery_request_ceiling >= expected_provider_request_count "
                "AND discovery_request_ceiling < new_max_provider_requests"
            ),
            sha_check("lane_page_ceilings_sha256"),
            _normalize_sql_fragment("include_subreddit_sweep IN (0, 1)"),
            sha_check("required_lanes_sha256"),
            _normalize_sql_fragment(
                "expected_provider_request_count = expected_max_provider_requests"
            ),
        }
        expected_unique_indexes = {
            ("run_id", "authorization_sha256"),
            ("run_id", "expected_max_provider_requests"),
            ("run_id", "new_max_provider_requests"),
        }
        expected_foreign_keys = {
            (
                "backfill_manifests",
                (("run_id", "run_id"),),
                "NO ACTION",
                "NO ACTION",
                "NONE",
            ),
        }
    elif table == "backfill_hydration_resumes":
        expected_primary_key = ("run_id", "authorization_sha256")
        expected_columns = (
            ("run_id", "TEXT", 1, None, 1),
            ("authorization_sha256", "TEXT", 1, None, 2),
            ("candidate_post_ids_json", "TEXT", 1, None, 0),
            ("candidate_post_ids_sha256", "TEXT", 1, None, 0),
            ("batch_membership_json", "TEXT", 1, None, 0),
            ("batch_membership_sha256", "TEXT", 1, None, 0),
            ("candidate_count", "INTEGER", 1, None, 0),
            ("batch_count", "INTEGER", 1, None, 0),
            ("applied_at_utc", "TEXT", 1, None, 0),
        )
        expected_checks = {
            sha_check("authorization_sha256"),
            sha_check("candidate_post_ids_sha256"),
            sha_check("batch_membership_sha256"),
            _normalize_sql_fragment("candidate_count > 0"),
            _normalize_sql_fragment("batch_count > 0"),
        }
        expected_unique_indexes = {
            ("run_id", "authorization_sha256"),
        }
        expected_foreign_keys = {
            (
                "backfill_budget_extensions",
                (
                    ("run_id", "run_id"),
                    ("authorization_sha256", "authorization_sha256"),
                ),
                "NO ACTION",
                "NO ACTION",
                "NONE",
            ),
        }
    elif table == "backfill_collection_resumes":
        expected_primary_key = ("run_id", "authorization_sha256")
        expected_columns = (
            ("run_id", "TEXT", 1, None, 1),
            ("authorization_sha256", "TEXT", 1, None, 2),
            ("expected_source_database_sha256", "TEXT", 1, None, 0),
            ("expected_provider_request_count", "INTEGER", 1, None, 0),
            ("max_provider_requests", "INTEGER", 1, None, 0),
            ("discovery_request_ceiling", "INTEGER", 1, None, 0),
            ("lane_page_ceilings_sha256", "TEXT", 1, None, 0),
            ("candidate_state_sha256", "TEXT", 1, None, 0),
            ("include_subreddit_sweep", "INTEGER", 1, None, 0),
            ("required_lanes_sha256", "TEXT", 1, None, 0),
            ("applied_at_utc", "TEXT", 1, None, 0),
        )
        expected_checks = {
            sha_check("authorization_sha256"),
            sha_check("expected_source_database_sha256"),
            _normalize_sql_fragment("expected_provider_request_count >= 0"),
            _normalize_sql_fragment(
                "max_provider_requests > expected_provider_request_count"
            ),
            _normalize_sql_fragment(
                "discovery_request_ceiling >= expected_provider_request_count "
                "AND discovery_request_ceiling <= max_provider_requests"
            ),
            sha_check("lane_page_ceilings_sha256"),
            sha_check("candidate_state_sha256"),
            _normalize_sql_fragment("include_subreddit_sweep IN (0, 1)"),
            sha_check("required_lanes_sha256"),
        }
        expected_unique_indexes = {
            ("run_id", "authorization_sha256"),
            ("run_id", "expected_provider_request_count"),
        }
        expected_foreign_keys = {
            (
                "backfill_manifests",
                (("run_id", "run_id"),),
                "NO ACTION",
                "NO ACTION",
                "NONE",
            ),
        }
    else:
        raise ValueError("unknown authorization ledger table")

    return _table_schema_is_compatible(
        conn,
        table=table,
        expected_primary_key=expected_primary_key,
        expected_columns=expected_columns,
        expected_checks=expected_checks,
        expected_unique_indexes=expected_unique_indexes,
        expected_foreign_keys=expected_foreign_keys,
    )


def _detail_ledger_schema_is_compatible(
    conn: sqlite3.Connection, table: str
) -> bool:
    if table == "backfill_detail_batches":
        expected_primary_key = ("run_id", "batch_id")
        expected_columns = (
            ("run_id", "TEXT", 1, None, 1),
            ("batch_id", "TEXT", 1, None, 2),
            ("batch_number", "INTEGER", 1, None, 0),
            ("status", "TEXT", 1, None, 0),
            ("artifact_id", "TEXT", 0, None, 0),
            ("stop_reason", "TEXT", 0, None, 0),
            ("created_at_utc", "TEXT", 1, None, 0),
            ("updated_at_utc", "TEXT", 1, None, 0),
        )
        expected_checks = {
            _normalize_sql_fragment("batch_number > 0"),
            _normalize_sql_fragment(
                "status IN ('prepared', 'raw_persisted', 'complete', 'failed')"
            ),
        }
        expected_unique_indexes = {
            ("run_id", "batch_id"),
            ("run_id", "batch_number"),
        }
        expected_foreign_keys = {
            (
                "backfill_manifests",
                (("run_id", "run_id"),),
                "NO ACTION",
                "NO ACTION",
                "NONE",
            ),
            (
                "backfill_raw_artifacts",
                (("run_id", "run_id"), ("artifact_id", "artifact_id")),
                "NO ACTION",
                "NO ACTION",
                "NONE",
            ),
        }
    elif table == "backfill_detail_batch_members":
        expected_primary_key = ("run_id", "batch_id", "ordinal")
        expected_columns = (
            ("run_id", "TEXT", 1, None, 1),
            ("batch_id", "TEXT", 1, None, 2),
            ("ordinal", "INTEGER", 1, None, 3),
            ("post_id", "TEXT", 1, None, 0),
        )
        expected_checks = {_normalize_sql_fragment("ordinal >= 0")}
        expected_unique_indexes = {
            ("run_id", "batch_id", "ordinal"),
            ("run_id", "post_id"),
        }
        expected_foreign_keys = {
            (
                "backfill_detail_batches",
                (("run_id", "run_id"), ("batch_id", "batch_id")),
                "NO ACTION",
                "NO ACTION",
                "NONE",
            ),
            (
                "backfill_candidates",
                (("run_id", "run_id"), ("post_id", "post_id")),
                "NO ACTION",
                "NO ACTION",
                "NONE",
            ),
        }
    else:
        raise ValueError("unknown detail ledger table")

    return _table_schema_is_compatible(
        conn,
        table=table,
        expected_primary_key=expected_primary_key,
        expected_columns=expected_columns,
        expected_checks=expected_checks,
        expected_unique_indexes=expected_unique_indexes,
        expected_foreign_keys=expected_foreign_keys,
    )


def _table_schema_is_compatible(
    conn: sqlite3.Connection,
    *,
    table: str,
    expected_primary_key: tuple[str, ...],
    expected_columns: tuple[tuple[str, str, int, str | None, int], ...],
    expected_checks: set[str],
    expected_unique_indexes: set[tuple[str, ...]],
    expected_foreign_keys: set[
        tuple[
            str,
            tuple[tuple[str, str], ...],
            str,
            str,
            str,
        ]
    ],
) -> bool:
    table_info = conn.execute(f"PRAGMA table_info({table})").fetchall()
    actual_columns = tuple(
        (
            str(row["name"]),
            str(row["type"]).upper(),
            int(row["notnull"]),
            (
                None
                if row["dflt_value"] is None
                else _normalize_sql_fragment(str(row["dflt_value"]))
            ),
            int(row["pk"]),
        )
        for row in sorted(table_info, key=lambda row: int(row["cid"]))
    )
    primary_key = tuple(
        str(row["name"])
        for row in sorted(
            (row for row in table_info if int(row["pk"]) > 0),
            key=lambda row: int(row["pk"]),
        )
    )

    unique_indexes: set[tuple[str, ...]] = set()
    for index in conn.execute(f"PRAGMA index_list({table})").fetchall():
        if not bool(index["unique"]):
            continue
        index_name = str(index["name"]).replace("'", "''")
        columns = tuple(
            str(row["name"])
            for row in sorted(
                conn.execute(
                    f"PRAGMA index_info('{index_name}')"
                ).fetchall(),
                key=lambda row: int(row["seqno"]),
            )
        )
        unique_indexes.add(columns)

    foreign_key_groups: dict[int, list[sqlite3.Row]] = {}
    for row in conn.execute(f"PRAGMA foreign_key_list({table})").fetchall():
        foreign_key_groups.setdefault(int(row["id"]), []).append(row)
    foreign_keys = {
        (
            str(rows[0]["table"]),
            tuple(
                (str(row["from"]), str(row["to"]))
                for row in sorted(rows, key=lambda row: int(row["seq"]))
            ),
            str(rows[0]["on_update"]).upper(),
            str(rows[0]["on_delete"]).upper(),
            str(rows[0]["match"]).upper(),
        )
        for rows in foreign_key_groups.values()
    }
    checks = _table_check_constraints(conn, table)

    return (
        actual_columns == expected_columns
        and primary_key == expected_primary_key
        and checks == expected_checks
        and unique_indexes == expected_unique_indexes
        and foreign_keys == expected_foreign_keys
    )


def _table_check_constraints(
    conn: sqlite3.Connection, table: str
) -> set[str] | None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    if row is None or row["sql"] is None:
        return None
    sql = str(row["sql"])
    expressions: set[str] = set()
    for match in re.finditer(r"\bCHECK\s*\(", sql, flags=re.IGNORECASE):
        start = match.end()
        index = start
        depth = 1
        quote: str | None = None
        while index < len(sql) and depth:
            character = sql[index]
            if quote is not None:
                if character == quote:
                    if index + 1 < len(sql) and sql[index + 1] == quote:
                        index += 2
                        continue
                    quote = None
            elif character in {"'", '"', "`"}:
                quote = character
            elif character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0:
                    expressions.add(
                        _normalize_sql_fragment(sql[start:index])
                    )
                    break
            index += 1
        if depth != 0:
            return None
    return expressions


def _normalize_sql_fragment(value: str) -> str:
    normalized: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(value):
        character = value[index]
        if quote is not None:
            normalized.append(character)
            if character == quote:
                if index + 1 < len(value) and value[index + 1] == quote:
                    normalized.append(value[index + 1])
                    index += 1
                else:
                    quote = None
        elif character in {"'", '"', "`"}:
            quote = character
            normalized.append(character)
        elif not character.isspace():
            normalized.append(character.lower())
        index += 1
    return "".join(normalized)


def _validated_post_ids(post_ids: Sequence[str]) -> tuple[str, ...]:
    values = tuple(post_ids)
    if any(not isinstance(post_id, str) or not post_id.strip() for post_id in values):
        raise ValueError("post_ids must contain only non-empty strings")
    if len(set(values)) != len(values):
        raise ValueError("post_ids must not contain duplicates")
    return values


def _require_nonempty_string(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_aware_datetime(name: str, value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")


def _validate_safe_reason(reason: str | None) -> None:
    if reason is not None and (
        not isinstance(reason, str) or _SAFE_REASON_PATTERN.fullmatch(reason) is None
    ):
        raise ValueError("reason must be null or a safe snake-case token")


def _decode_hydration_resume_ledger(
    row: sqlite3.Row,
) -> tuple[
    tuple[str, ...],
    tuple[tuple[str, int, tuple[str, ...]], ...],
]:
    candidate_json = str(row["candidate_post_ids_json"])
    membership_json = str(row["batch_membership_json"])
    candidate_sha256 = str(row["candidate_post_ids_sha256"])
    membership_sha256 = str(row["batch_membership_sha256"])
    if (
        _SHA256_PATTERN.fullmatch(candidate_sha256) is None
        or _SHA256_PATTERN.fullmatch(membership_sha256) is None
        or sha256(candidate_json.encode()).hexdigest() != candidate_sha256
        or sha256(membership_json.encode()).hexdigest() != membership_sha256
    ):
        raise ValueError("invalid hydration resume ledger digest")

    raw_candidate_ids = json.loads(candidate_json)
    raw_membership = json.loads(membership_json)
    if not isinstance(raw_candidate_ids, list) or not isinstance(
        raw_membership, list
    ):
        raise ValueError("invalid hydration resume ledger shape")
    candidate_ids = tuple(raw_candidate_ids)
    if (
        not candidate_ids
        or any(type(post_id) is not str or not post_id.strip() for post_id in candidate_ids)
        or candidate_ids != tuple(sorted(set(candidate_ids)))
        or candidate_json != _canonical_json(candidate_ids)
        or type(row["candidate_count"]) is not int
        or row["candidate_count"] != len(candidate_ids)
    ):
        raise ValueError("invalid hydration resume candidate ledger")

    membership: list[tuple[str, int, tuple[str, ...]]] = []
    for item in raw_membership:
        if not isinstance(item, list) or len(item) != 3:
            raise ValueError("invalid hydration resume batch ledger")
        batch_id, batch_number, raw_post_ids = item
        if (
            type(batch_id) is not str
            or not batch_id.strip()
            or type(batch_number) is not int
            or batch_number <= 0
            or not isinstance(raw_post_ids, list)
        ):
            raise ValueError("invalid hydration resume batch ledger")
        post_ids = tuple(raw_post_ids)
        if (
            not 1 <= len(post_ids) <= 30
            or any(type(post_id) is not str or not post_id.strip() for post_id in post_ids)
            or len(set(post_ids)) != len(post_ids)
        ):
            raise ValueError("invalid hydration resume member ledger")
        membership.append((batch_id, batch_number, post_ids))
    membership_tuple = tuple(membership)
    member_ids = tuple(
        post_id for _, _, post_ids in membership_tuple for post_id in post_ids
    )
    if (
        not membership_tuple
        or membership_tuple
        != tuple(sorted(membership_tuple, key=lambda item: (item[1], item[0])))
        or len({item[0] for item in membership_tuple}) != len(membership_tuple)
        or len({item[1] for item in membership_tuple}) != len(membership_tuple)
        or membership_json != _canonical_json(membership_tuple)
        or type(row["batch_count"]) is not int
        or row["batch_count"] != len(membership_tuple)
        or len(member_ids) != len(candidate_ids)
        or set(member_ids) != set(candidate_ids)
    ):
        raise ValueError("invalid hydration resume membership ledger")
    return candidate_ids, membership_tuple


def _hydration_resume_has_existing_evidence(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    candidate_ids: tuple[str, ...],
    batch_ids: tuple[str, ...],
) -> bool:
    candidate_placeholders = ", ".join("?" for _ in candidate_ids)
    batch_hashes = tuple(sha256(batch_id.encode()).hexdigest() for batch_id in batch_ids)
    batch_hash_placeholders = ", ".join("?" for _ in batch_hashes)
    comment_hashes = tuple(
        sha256(post_id.encode()).hexdigest() for post_id in candidate_ids
    )
    comment_hash_placeholders = ", ".join("?" for _ in comment_hashes)
    checks = (
        conn.execute(
            "SELECT 1 FROM backfill_raw_artifacts WHERE run_id = ? "
            "AND lane_type = 'detail_batch' "
            f"AND lane_key_hash IN ({batch_hash_placeholders}) LIMIT 1",
            (run_id, *batch_hashes),
        ).fetchone(),
        conn.execute(
            "SELECT 1 FROM backfill_raw_artifacts WHERE run_id = ? "
            "AND lane_type = 'comments' "
            f"AND lane_key_hash IN ({comment_hash_placeholders}) LIMIT 1",
            (run_id, *comment_hashes),
        ).fetchone(),
        conn.execute(
            "SELECT 1 FROM backfill_checkpoints WHERE run_id = ? "
            "AND lane_type = 'comments' "
            f"AND lane_key IN ({candidate_placeholders}) LIMIT 1",
            (run_id, *candidate_ids),
        ).fetchone(),
        conn.execute(
            "SELECT 1 FROM reddit_threads WHERE run_id = ? "
            f"AND post_id IN ({candidate_placeholders}) LIMIT 1",
            (run_id, *candidate_ids),
        ).fetchone(),
        conn.execute(
            "SELECT 1 FROM reddit_comments WHERE run_id = ? "
            f"AND post_id IN ({candidate_placeholders}) LIMIT 1",
            (run_id, *candidate_ids),
        ).fetchone(),
        conn.execute(
            "SELECT 1 FROM analysis_results WHERE run_id = ? "
            "AND source_type = 'post' "
            f"AND source_id IN ({candidate_placeholders}) LIMIT 1",
            (run_id, *candidate_ids),
        ).fetchone(),
    )
    return any(row is not None for row in checks)


def _detail_batch_id(run_id: str, post_ids: tuple[str, ...]) -> str:
    identity = json.dumps(
        [run_id, list(post_ids)],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    return "detail_batch_" + sha256(identity).hexdigest()[:24]


def _detail_batch_by_id_conn(
    conn: sqlite3.Connection, run_id: str, batch_id: str
) -> DetailBatch:
    row = conn.execute(
        "SELECT * FROM backfill_detail_batches "
        "WHERE run_id = ? AND batch_id = ?",
        (run_id, batch_id),
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown detail batch: {run_id}/{batch_id}")
    return _detail_batch_from_row(conn, row)


def _detail_batch_from_row(
    conn: sqlite3.Connection, row: sqlite3.Row
) -> DetailBatch:
    member_rows = conn.execute(
        "SELECT ordinal, post_id FROM backfill_detail_batch_members "
        "WHERE run_id = ? AND batch_id = ? ORDER BY ordinal",
        (row["run_id"], row["batch_id"]),
    ).fetchall()
    run_id = str(row["run_id"])
    batch_id = str(row["batch_id"])
    post_ids = tuple(str(member["post_id"]) for member in member_rows)
    ordinals = tuple(int(member["ordinal"]) for member in member_rows)
    if (
        not 1 <= len(post_ids) <= 30
        or ordinals != tuple(range(len(post_ids)))
        or any(not post_id.strip() for post_id in post_ids)
        or len(set(post_ids)) != len(post_ids)
        or batch_id != _detail_batch_id(run_id, post_ids)
    ):
        raise BackfillConflictError(
            f"backfill_detail_batches:{run_id}/{batch_id}"
        )
    return DetailBatch(
        run_id=run_id,
        batch_id=batch_id,
        batch_number=int(row["batch_number"]),
        post_ids=post_ids,
        status=row["status"],
        artifact_id=row["artifact_id"],
        stop_reason=row["stop_reason"],
        created_at_utc=str(row["created_at_utc"]),
        updated_at_utc=str(row["updated_at_utc"]),
    )


def _load_detail_batches_conn(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    post_ids: tuple[str, ...],
) -> tuple[DetailBatch, ...]:
    if post_ids:
        placeholders = ", ".join("?" for _ in post_ids)
        rows = conn.execute(
            "SELECT DISTINCT batch.* FROM backfill_detail_batches AS batch "
            "JOIN backfill_detail_batch_members AS member "
            "ON member.run_id = batch.run_id AND member.batch_id = batch.batch_id "
            f"WHERE batch.run_id = ? AND member.post_id IN ({placeholders}) "
            "ORDER BY batch.batch_number",
            (run_id, *post_ids),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM backfill_detail_batches "
            "WHERE run_id = ? ORDER BY batch_number",
            (run_id,),
        ).fetchall()
    return tuple(_detail_batch_from_row(conn, row) for row in rows)


def _raw_artifact_from_row(row: sqlite3.Row) -> RawArtifactMetadata:
    return RawArtifactMetadata(
        artifact_id=str(row["artifact_id"]),
        run_id=str(row["run_id"]),
        artifact_kind=str(row["artifact_kind"]),
        lane_type=row["lane_type"],
        lane_key_hash=str(row["lane_key_hash"]),
        identity_hash=str(row["identity_hash"]),
        raw_capture_id=str(row["raw_capture_id"]),
        parser_kind=str(row["parser_kind"]),
        source_method=str(row["source_method"]),
        source_url=str(row["source_url"]),
        source_endpoint=str(row["source_endpoint"]),
        payload_sha256=str(row["payload_sha256"]),
        relative_path=str(row["relative_path"]),
        captured_at_utc=str(row["captured_at_utc"]),
        page_number=(
            None if row["page_number"] is None else int(row["page_number"])
        ),
        request_cursor=row["request_cursor"],
        response_cursor=row["response_cursor"],
    )


def _canonical_json(values) -> str:
    return json.dumps(list(values), ensure_ascii=False, separators=(",", ":"))


def _base_disposition(disposition: str) -> str:
    if disposition == "outside_window":
        return "outside_window"
    if disposition == "invalid":
        return "invalid"
    return "eligible"


def _raw_capture_record(capture: RawCapture) -> dict[str, object]:
    record = capture.as_record()
    record["secrets_written"] = int(capture.secrets_written)
    return record


def _raw_artifact_record(artifact: RawArtifactMetadata) -> dict[str, object]:
    return {
        "artifact_id": artifact.artifact_id,
        "run_id": artifact.run_id,
        "artifact_kind": artifact.artifact_kind,
        "lane_type": artifact.lane_type,
        "lane_key_hash": artifact.lane_key_hash,
        "identity_hash": artifact.identity_hash,
        "raw_capture_id": artifact.raw_capture_id,
        "parser_kind": artifact.parser_kind,
        "source_method": artifact.source_method,
        "source_url": artifact.source_url,
        "source_endpoint": artifact.source_endpoint,
        "payload_sha256": artifact.payload_sha256,
        "relative_path": artifact.relative_path,
        "captured_at_utc": artifact.captured_at_utc,
        "page_number": artifact.page_number,
        "request_cursor": artifact.request_cursor,
        "response_cursor": artifact.response_cursor,
    }


def _insert_raw_artifact_conn(
    conn: sqlite3.Connection, artifact: RawArtifactMetadata
) -> bool:
    record = _raw_artifact_record(artifact)
    columns = tuple(record)
    expected = tuple(record[column] for column in columns)
    conflict_key = f"backfill_raw_artifacts:{artifact.artifact_id}"
    existing = conn.execute(
        f"SELECT {', '.join(columns)} FROM backfill_raw_artifacts "
        "WHERE run_id = ? AND artifact_id = ?",
        (artifact.run_id, artifact.artifact_id),
    ).fetchone()
    if existing is not None:
        actual = tuple(existing[column] for column in columns)
        if actual != expected:
            raise BackfillConflictError(conflict_key)
        return False

    collision = conn.execute(
        "SELECT artifact_id FROM backfill_raw_artifacts "
        "WHERE relative_path = ? "
        "OR (run_id = ? AND raw_capture_id = ?) "
        "OR (run_id = ? AND source_method = ? AND source_url = ? "
        "AND payload_sha256 = ?)",
        (
            artifact.relative_path,
            artifact.run_id,
            artifact.raw_capture_id,
            artifact.run_id,
            artifact.source_method,
            artifact.source_url,
            artifact.payload_sha256,
        ),
    ).fetchone()
    if collision is not None:
        raise BackfillConflictError(conflict_key)

    conn.execute(
        f"INSERT INTO backfill_raw_artifacts({', '.join(columns)}) "
        f"VALUES ({', '.join(f':{column}' for column in columns)})",
        record,
    )
    return True


def _comment_record(comment: RedditComment) -> dict[str, object]:
    record = comment.as_record()
    record["is_submitter"] = (
        None if comment.is_submitter is None else int(comment.is_submitter)
    )
    record["deleted_or_removed"] = int(comment.deleted_or_removed)
    return record


def _analysis_record(analysis: AnalysisRow) -> dict[str, object]:
    return {
        "analysis_id": analysis.analysis_id,
        "run_id": analysis.run_id,
        "source_type": analysis.source_type,
        "source_id": analysis.source_id,
        "analysis_version": analysis.analysis_version,
        "sentiment_label": analysis.sentiment_label,
        "sentiment_score": float(analysis.sentiment_score),
        "topic": analysis.topic,
        "severity": analysis.severity,
        "confidence": float(analysis.confidence),
        "pain_points": _canonical_json(analysis.pain_points),
        "provider_call": int(analysis.provider_call),
    }


def _validate_candidate_finalization_bundle(
    *,
    run_id: str,
    post_id: str,
    status: CandidateStatus,
    captures: tuple[RawCapture, ...],
    threads: tuple[RedditThread, ...],
    comments: tuple[RedditComment, ...],
    analyses: tuple[AnalysisRow, ...],
) -> None:
    if status == "hydrated":
        _validate_hydrated_candidate_bundle(
            run_id=run_id,
            post_id=post_id,
            captures=captures,
            threads=threads,
            comments=comments,
            analyses=analyses,
        )
    elif captures or threads or comments or analyses:
        raise ValueError("only hydrated candidates may carry an entity bundle")


def _validate_hydrated_candidate_bundle(
    *,
    run_id: str,
    post_id: str,
    captures: tuple[RawCapture, ...],
    threads: tuple[RedditThread, ...],
    comments: tuple[RedditComment, ...],
    analyses: tuple[AnalysisRow, ...],
) -> None:
    if len(threads) != 1:
        raise ValueError("hydrated candidate requires exactly one thread")
    thread = threads[0]
    if thread.run_id != run_id or thread.post_id != post_id:
        raise ValueError("hydrated thread does not match candidate")
    if thread.parsed_comment_count != len(comments):
        raise ValueError("hydrated thread comment count does not match bundle")

    capture_ids = [capture.raw_capture_id for capture in captures]
    if len(set(capture_ids)) != len(capture_ids):
        raise ValueError("hydrated bundle contains duplicate raw captures")
    if any(capture.run_id != run_id for capture in captures):
        raise ValueError("hydrated raw capture uses a different run")

    required_capture_ids = {
        thread.raw_capture_id,
        *(comment.raw_capture_id for comment in comments),
    }
    if set(capture_ids) != required_capture_ids:
        raise ValueError("hydrated raw captures do not match entity lineage")

    comment_ids = [comment.comment_id for comment in comments]
    if len(set(comment_ids)) != len(comment_ids):
        raise ValueError("hydrated bundle contains duplicate comments")
    if any(
        comment.run_id != run_id or comment.post_id != post_id
        for comment in comments
    ):
        raise ValueError("hydrated comment does not match candidate")

    analysis_ids = [analysis.analysis_id for analysis in analyses]
    if len(set(analysis_ids)) != len(analysis_ids):
        raise ValueError("hydrated bundle contains duplicate analyses")
    if any(analysis.run_id != run_id for analysis in analyses):
        raise ValueError("hydrated analysis uses a different run")
    if any(analysis.provider_call for analysis in analyses):
        raise ValueError("hydrated analysis must be local")

    post_analyses = [
        analysis
        for analysis in analyses
        if analysis.source_type == "post" and analysis.source_id == post_id
    ]
    comment_analysis_ids = [
        analysis.source_id
        for analysis in analyses
        if analysis.source_type == "comment"
    ]
    if (
        len(post_analyses) != 1
        or len(analyses) != 1 + len(comments)
        or len(comment_analysis_ids) != len(comments)
        or set(comment_analysis_ids) != set(comment_ids)
    ):
        raise ValueError("hydrated bundle analysis parity mismatch")


def _verify_entity_bundle_conn(
    conn: sqlite3.Connection,
    *,
    captures: Sequence[RawCapture],
    threads: Sequence[RedditThread],
    comments: Sequence[RedditComment],
    analyses: Sequence[AnalysisRow],
) -> None:
    for capture in captures:
        _verify_existing_record(
            conn,
            table="raw_captures",
            primary_key="raw_capture_id",
            record=_raw_capture_record(capture),
        )
    for thread in threads:
        _verify_existing_record(
            conn,
            table="reddit_threads",
            primary_key="post_id",
            record=thread.as_record(),
        )
    for comment in comments:
        _verify_existing_record(
            conn,
            table="reddit_comments",
            primary_key="comment_id",
            record=_comment_record(comment),
        )
    for analysis in analyses:
        _verify_existing_record(
            conn,
            table="analysis_results",
            primary_key="analysis_id",
            record=_analysis_record(analysis),
        )


def _verify_existing_record(
    conn: sqlite3.Connection,
    *,
    table: str,
    primary_key: str,
    record: dict[str, object],
) -> None:
    columns = tuple(record)
    row = conn.execute(
        f"SELECT {', '.join(columns)} FROM {table} WHERE {primary_key} = ?",
        (record[primary_key],),
    ).fetchone()
    expected = tuple(record[column] for column in columns)
    if row is None or tuple(row[column] for column in columns) != expected:
        raise BackfillConflictError(f"{table}:{record[primary_key]}")


def _insert_entity_bundle_conn(
    conn: sqlite3.Connection,
    *,
    captures: Sequence[RawCapture],
    threads: Sequence[RedditThread],
    comments: Sequence[RedditComment],
    analyses: Sequence[AnalysisRow],
) -> InsertCounts:
    raw_capture_count = sum(
        _insert_or_verify(
            conn,
            table="raw_captures",
            primary_key="raw_capture_id",
            record=_raw_capture_record(capture),
            natural_key=(
                "run_id",
                "source_method",
                "source_url",
                "raw_payload_hash",
            ),
        )
        for capture in captures
    )
    thread_count = sum(
        _insert_or_verify(
            conn,
            table="reddit_threads",
            primary_key="post_id",
            record=thread.as_record(),
        )
        for thread in threads
    )
    comment_count = sum(
        _insert_or_verify(
            conn,
            table="reddit_comments",
            primary_key="comment_id",
            record=_comment_record(comment),
        )
        for comment in comments
    )
    analysis_count = sum(
        _insert_or_verify(
            conn,
            table="analysis_results",
            primary_key="analysis_id",
            record=_analysis_record(analysis),
        )
        for analysis in analyses
    )
    return InsertCounts(
        raw_captures=raw_capture_count,
        threads=thread_count,
        comments=comment_count,
        analyses=analysis_count,
    )


def _insert_or_verify(
    conn: sqlite3.Connection,
    *,
    table: str,
    primary_key: str,
    record: dict[str, object],
    natural_key: tuple[str, ...] | None = None,
) -> int:
    columns = tuple(record)
    existing = conn.execute(
        f"SELECT {', '.join(columns)} FROM {table} WHERE {primary_key} = ?",
        (record[primary_key],),
    ).fetchone()
    expected = tuple(record[column] for column in columns)
    if existing is not None:
        actual = tuple(existing[column] for column in columns)
        if actual != expected:
            raise BackfillConflictError(f"{table}:{record[primary_key]}")
        return 0

    if natural_key is not None:
        collision = conn.execute(
            f"SELECT {primary_key} FROM {table} WHERE "
            + " AND ".join(f"{column} = ?" for column in natural_key),
            tuple(record[column] for column in natural_key),
        ).fetchone()
        if collision is not None:
            raise BackfillConflictError(f"{table}:{record[primary_key]}")

    conn.execute(
        f"INSERT INTO {table}({', '.join(columns)}) "
        f"VALUES ({', '.join(f':{column}' for column in columns)})",
        record,
    )
    return 1
