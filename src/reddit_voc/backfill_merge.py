from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import tempfile
from typing import cast, Literal

from .backfill_storage import STAGING_SCHEMA
from .storage import SCHEMA as PRODUCTION_SCHEMA


__all__ = [
    "BackfillMergeError",
    "MergeAuthorizationError",
    "MergeCommittedReviewError",
    "MergeInvariantError",
    "MergePreconditionError",
    "MergeSummary",
    "plan_insert_only_merge",
    "merge_staging_insert_only",
]


PLAN_KEYS = (
    "schema_version",
    "run_id",
    "status",
    "stop_reason",
    "query_only",
    "production_write",
    "provider_attempt_made",
    "live_send",
    "staging_sha256",
    "production_sha256",
    "staging_fingerprints",
    "production_baseline_counts",
    "delivery_baseline_count",
    "run_action",
    "staging_run_sha256",
    "existing_run_sha256",
    "approved_counts",
    "approved_post_ids_sha256",
    "skipped_post_count",
    "conflict_counts",
    "conflicts",
    "plan_sha256",
)

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_SAFE_REASON_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,95}")
_SQLITE_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")

_TABLE_COLUMNS = {
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
}
_PRIMARY_KEYS = {
    "runs": "run_id",
    "raw_captures": "raw_capture_id",
    "reddit_threads": "post_id",
    "reddit_comments": "comment_id",
    "analysis_results": "analysis_id",
    "delivery_previews": "delivery_id",
}
_MERGE_TABLES = (
    "runs",
    "raw_captures",
    "reddit_threads",
    "reddit_comments",
    "analysis_results",
)
_ALL_COMPATIBLE_TABLES = _MERGE_TABLES + ("delivery_previews",)
_MANIFEST_COLUMNS = (
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
)
_RAW_ARTIFACT_COLUMNS = (
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
)
_CONFLICT_KINDS = (
    "post_primary_key_conflict",
    "raw_primary_key_conflict",
    "raw_unique_conflict",
    "comment_primary_key_conflict",
    "analysis_primary_key_conflict",
)
_BACKFILL_STATUSES = {
    "prepared",
    "seed_complete",
    "running",
    "partial",
    "success",
    "blocked",
    "failed",
}


class BackfillMergeError(RuntimeError):
    def __init__(self, reason: str) -> None:
        if _SAFE_REASON_PATTERN.fullmatch(reason) is None:
            reason = "merge_failed"
        self.reason = reason
        super().__init__(reason)


class MergeAuthorizationError(BackfillMergeError):
    pass


class MergePreconditionError(BackfillMergeError):
    pass


class MergeInvariantError(BackfillMergeError):
    pass


class MergeCommittedReviewError(BackfillMergeError):
    pass


@dataclass(frozen=True)
class MergeSummary:
    schema_version: Literal["backfill_insert_only_merge_result_v1"]
    run_id: str
    status: Literal["merged"]
    stop_reason: Literal["merge_complete"]
    authorized: bool
    production_write: bool
    plan_sha256: str
    staging_sha256: str
    expected_production_sha256: str
    premerge_production_sha256: str
    backup_sha256: str
    postmerge_production_sha256: str
    planned_runs: int
    planned_raw_captures: int
    reused_raw_captures: int
    planned_threads: int
    planned_comments: int
    planned_analyses: int
    inserted_runs: int
    inserted_raw_captures: int
    inserted_threads: int
    inserted_comments: int
    inserted_analyses: int
    skipped_posts: int
    conflict_count: int
    delivery_before: int
    delivery_after: int
    delivery_delta: int
    updated: int
    deleted: int
    provider_attempt_made: bool
    live_send: bool


@dataclass(frozen=True)
class _FileIdentity:
    path: Path
    device: int
    inode: int


@dataclass(frozen=True)
class _VerifiedBackup:
    identity: _FileIdentity
    sha256: str


@dataclass(frozen=True)
class _InternalPlan:
    public: dict[str, object]
    internal_sha256: str
    staging_identity: _FileIdentity
    production_identity: _FileIdentity
    approved_post_ids: tuple[str, ...]
    raw_insert_ids: tuple[str, ...]
    raw_exact_ids: tuple[str, ...]
    comment_ids: tuple[str, ...]
    analysis_ids: tuple[str, ...]
    staging_rows: dict[str, dict[str, tuple[object, ...]]]
    production_before_hashes: dict[str, dict[str, str]]
    production_fingerprint: dict[str, object]


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MergePreconditionError("noncanonical_database_value") from None


def _canonical_sha256(value: object) -> str:
    return sha256(_canonical_bytes(value)).hexdigest()


def _identifier_sha256(value: object) -> str:
    return sha256(str(value).encode("utf-8")).hexdigest()


def _row_sha256(row: tuple[object, ...] | None) -> str:
    return _canonical_sha256([] if row is None else list(row))


def _exact_int(value: object) -> int:
    if type(value) is not int:
        raise MergeInvariantError("internal_integer_invalid")
    return cast(int, value)


def _object_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        raise MergeInvariantError("internal_mapping_invalid")
    return cast(dict[str, object], value)


def _object_list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise MergeInvariantError("internal_list_invalid")
    return cast(list[object], value)


def _schema_signature(
    conn: sqlite3.Connection, schema: str, table: str
) -> tuple[tuple[object, ...], ...]:
    rows = conn.execute(f"PRAGMA {schema}.table_xinfo('{table}')").fetchall()
    return tuple(
        (
            str(row["name"]),
            str(row["type"]),
            int(row["notnull"]),
            row["dflt_value"],
            int(row["pk"]),
            int(row["hidden"]),
        )
        for row in rows
    )


def _foreign_key_signature(
    conn: sqlite3.Connection, schema: str, table: str
) -> tuple[tuple[object, ...], ...]:
    rows = conn.execute(f"PRAGMA {schema}.foreign_key_list('{table}')").fetchall()
    return tuple(
        (
            int(row["id"]),
            int(row["seq"]),
            str(row["table"]),
            str(row["from"]),
            None if row["to"] is None else str(row["to"]),
            str(row["on_update"]),
            str(row["on_delete"]),
            str(row["match"]),
        )
        for row in sorted(rows, key=lambda row: (int(row["id"]), int(row["seq"])))
    )


def _normalized_table_definition(
    conn: sqlite3.Connection, schema: str, table: str
) -> str:
    row = conn.execute(
        f"SELECT sql FROM {schema}.sqlite_master "
        "WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    if row is None or row["sql"] is None:
        return ""
    definition = str(row["sql"])
    definition = re.sub(
        r"\bCREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\b",
        "CREATE TABLE",
        definition,
        flags=re.IGNORECASE,
    )
    definition = re.sub(r"\s+", " ", definition.strip())
    definition = re.sub(r"\s*([(),])\s*", r"\1", definition)
    return definition


def _unique_index_signature(
    conn: sqlite3.Connection, schema: str, table: str
) -> tuple[tuple[object, ...], ...]:
    result: list[tuple[object, ...]] = []
    for index in conn.execute(f"PRAGMA {schema}.index_list('{table}')").fetchall():
        if int(index["unique"]) != 1:
            continue
        key_columns = tuple(
            (
                int(row["seqno"]),
                int(row["cid"]),
                None if row["name"] is None else str(row["name"]),
                int(row["desc"]),
                None if row["coll"] is None else str(row["coll"]),
                int(row["key"]),
            )
            for row in sorted(
                conn.execute(
                    f"PRAGMA {schema}.index_xinfo('{str(index['name'])}')"
                ).fetchall(),
                key=lambda row: int(row["seqno"]),
            )
            if int(row["key"]) == 1
        )
        if key_columns:
            result.append(
                (
                    str(index["origin"]),
                    int(index["partial"]),
                    key_columns,
                )
            )
    return tuple(sorted(result, key=_canonical_bytes))


def _derive_expected_contracts(
    schema_sql: str, tables: tuple[str, ...]
) -> dict[
    str,
    tuple[
        tuple[tuple[object, ...], ...],
        tuple[tuple[object, ...], ...],
        tuple[tuple[object, ...], ...],
        str,
    ],
]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(schema_sql)
        return {
            table: (
                _schema_signature(conn, "main", table),
                _unique_index_signature(conn, "main", table),
                _foreign_key_signature(conn, "main", table),
                _normalized_table_definition(conn, "main", table),
            )
            for table in tables
        }
    finally:
        conn.close()


_EXPECTED_PRODUCTION_CONTRACTS = _derive_expected_contracts(
    PRODUCTION_SCHEMA, _ALL_COMPATIBLE_TABLES
)
_EXPECTED_STAGING_CONTRACTS = _derive_expected_contracts(
    STAGING_SCHEMA,
    _ALL_COMPATIBLE_TABLES
    + ("backfill_manifests", "backfill_raw_artifacts"),
)


def _assert_database_contract(
    conn: sqlite3.Connection, *, schema: str, staging: bool
) -> None:
    try:
        integrity = conn.execute(f"PRAGMA {schema}.integrity_check").fetchall()
    except sqlite3.DatabaseError:
        raise MergePreconditionError("sqlite_integrity_check_failed") from None
    if len(integrity) != 1 or tuple(integrity[0]) != ("ok",):
        raise MergePreconditionError("sqlite_integrity_check_failed")
    if staging:
        try:
            foreign_key_rows = conn.execute(
                f"PRAGMA {schema}.foreign_key_check"
            ).fetchall()
        except sqlite3.DatabaseError:
            raise MergePreconditionError("staging_foreign_key_check_failed") from None
        if foreign_key_rows:
            raise MergePreconditionError("staging_foreign_key_check_failed")
        expected = _EXPECTED_STAGING_CONTRACTS
    else:
        expected = _EXPECTED_PRODUCTION_CONTRACTS
    for table, (
        columns,
        unique_indexes,
        foreign_keys,
        table_definition,
    ) in expected.items():
        if _schema_signature(conn, schema, table) != columns:
            raise MergePreconditionError("database_schema_mismatch")
        if _unique_index_signature(conn, schema, table) != unique_indexes:
            raise MergePreconditionError("database_unique_index_mismatch")
        if _foreign_key_signature(conn, schema, table) != foreign_keys:
            raise MergePreconditionError("database_foreign_key_mismatch")
        if (
            _normalized_table_definition(conn, schema, table)
            != table_definition
        ):
            raise MergePreconditionError("database_table_definition_mismatch")
    compatible_tables = tuple(_ALL_COMPATIBLE_TABLES)
    placeholders = ", ".join("?" for _ in compatible_tables)
    trigger_count = conn.execute(
        f"SELECT COUNT(*) FROM {schema}.sqlite_master "
        f"WHERE type='trigger' AND tbl_name IN ({placeholders})",
        compatible_tables,
    ).fetchone()[0]
    if int(trigger_count) != 0:
        raise MergePreconditionError("database_trigger_not_allowed")


def _assert_no_sidecars(path: Path) -> None:
    for suffix in _SQLITE_SIDECAR_SUFFIXES:
        sidecar = Path(str(path) + suffix)
        try:
            sidecar.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            raise MergePreconditionError("sqlite_sidecar_state_unknown") from None
        raise MergePreconditionError("sqlite_sidecar_present")


def _database_file(path: Path | str) -> _FileIdentity:
    candidate = Path(path)
    try:
        metadata = candidate.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise MergePreconditionError("database_path_invalid")
        resolved = candidate.resolve(strict=True)
        resolved_metadata = resolved.stat()
    except MergePreconditionError:
        raise
    except OSError:
        raise MergePreconditionError("database_path_invalid") from None
    if not stat.S_ISREG(resolved_metadata.st_mode):
        raise MergePreconditionError("database_path_invalid")
    _assert_no_sidecars(resolved)
    return _FileIdentity(
        path=resolved,
        device=int(resolved_metadata.st_dev),
        inode=int(resolved_metadata.st_ino),
    )


def _assert_file_identity(identity: _FileIdentity) -> None:
    try:
        metadata = identity.path.stat()
    except OSError:
        raise MergePreconditionError("database_identity_changed") from None
    if (int(metadata.st_dev), int(metadata.st_ino)) != (
        identity.device,
        identity.inode,
    ):
        raise MergePreconditionError("database_identity_changed")
    _assert_no_sidecars(identity.path)


def _sha256_file(path: Path) -> str:
    digest = sha256()
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
        try:
            with os.fdopen(descriptor, "rb", closefd=True) as handle:
                descriptor = -1
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    except OSError:
        raise MergePreconditionError("database_hash_failed") from None
    return digest.hexdigest()


def _open_readonly_database(path: Path) -> sqlite3.Connection:
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(
            f"{path.as_uri()}?mode=ro",
            uri=True,
            timeout=5.0,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("BEGIN")
        return conn
    except sqlite3.Error:
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass
        raise MergePreconditionError("database_readonly_open_failed") from None


def _rollback_and_close(conn: sqlite3.Connection | None) -> None:
    if conn is None:
        return
    try:
        conn.rollback()
    except sqlite3.Error:
        pass
    try:
        conn.close()
    except sqlite3.Error:
        pass


def _qualified(schema: str, table: str) -> str:
    if schema not in {"main", "staging"} or table not in (
        set(_ALL_COMPATIBLE_TABLES)
        | {"backfill_manifests", "backfill_raw_artifacts"}
    ):
        raise MergeInvariantError("internal_identifier_invalid")
    return f"{schema}.{table}"


def _selected_rows(
    conn: sqlite3.Connection,
    *,
    schema: str,
    table: str,
    columns: tuple[str, ...],
    where: str = "",
    parameters: tuple[object, ...] = (),
    order_by: str | None = None,
) -> list[tuple[object, ...]]:
    suffix = f" WHERE {where}" if where else ""
    ordering = f" ORDER BY {order_by}" if order_by else ""
    rows = conn.execute(
        f"SELECT {', '.join(columns)} FROM {_qualified(schema, table)}"
        f"{suffix}{ordering}",
        parameters,
    ).fetchall()
    return [tuple(row[column] for column in columns) for row in rows]


def _staging_fingerprints(
    conn: sqlite3.Connection, *, schema: str, run_id: str
) -> dict[str, object]:
    surfaces = (
        (
            "runs",
            ("run_id", "window_start_utc", "window_end_utc"),
            "run_id",
            None,
        ),
        (
            "backfill_raw_artifacts",
            _RAW_ARTIFACT_COLUMNS,
            "artifact_id",
            "payload_sha256",
        ),
        ("raw_captures", _TABLE_COLUMNS["raw_captures"], "raw_capture_id", "raw_payload_hash"),
        ("reddit_threads", _TABLE_COLUMNS["reddit_threads"], "post_id", None),
        ("reddit_comments", _TABLE_COLUMNS["reddit_comments"], "comment_id", None),
        ("analysis_results", _TABLE_COLUMNS["analysis_results"], "analysis_id", None),
    )
    result: dict[str, object] = {}
    for table, columns, identity_column, raw_hash_column in surfaces:
        rows = conn.execute(
            f"SELECT {', '.join(columns)} FROM {_qualified(schema, table)} "
            f"WHERE run_id=? ORDER BY {identity_column}",
            (run_id,),
        ).fetchall()
        encoded = [[row[column] for column in columns] for row in rows]
        table_result: dict[str, object] = {
            "row_count": len(rows),
            "id_set_sha256": _canonical_sha256(
                sorted(str(row[identity_column]) for row in rows)
            ),
            "canonical_rows_sha256": _canonical_sha256(encoded),
        }
        if raw_hash_column is not None:
            table_result["raw_payload_hash_set_sha256"] = _canonical_sha256(
                sorted(str(row[raw_hash_column]) for row in rows)
            )
        result[table] = table_result
    return result


def _typed_sqlite_value(value: object) -> list[object]:
    if value is None:
        return ["null", None]
    if type(value) is int:
        return ["integer", str(value)]
    if type(value) is float:
        return ["real", value.hex()]
    if type(value) is str:
        return ["text", value]
    if isinstance(value, bytes):
        return ["blob", value.hex()]
    raise MergePreconditionError("unsupported_sqlite_value")


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _full_database_fingerprint(
    conn: sqlite3.Connection, *, schema: str
) -> str:
    master_rows = conn.execute(
        f"SELECT type, name, tbl_name, sql FROM {schema}.sqlite_master "
        "ORDER BY type, name"
    ).fetchall()
    master_payload = [
        [_typed_sqlite_value(value) for value in tuple(row)] for row in master_rows
    ]
    table_payload: dict[str, object] = {}
    table_names = sorted(
        str(row["name"])
        for row in master_rows
        if row["type"] == "table" and not str(row["name"]).startswith("sqlite_")
    )
    for table in table_names:
        cursor = conn.execute(
            f"SELECT * FROM {schema}.{_quote_identifier(table)}"
        )
        columns = [str(item[0]) for item in (cursor.description or ())]
        encoded_rows = [
            [_typed_sqlite_value(value) for value in tuple(row)]
            for row in cursor.fetchall()
        ]
        encoded_rows.sort(key=_canonical_bytes)
        table_payload[table] = {
            "columns": columns,
            "row_count": len(encoded_rows),
            "rows_sha256": _canonical_sha256(encoded_rows),
        }
    pragmas = {
        name: conn.execute(f"PRAGMA {schema}.{name}").fetchone()[0]
        for name in ("application_id", "encoding", "user_version")
    }
    return _canonical_sha256(
        {
            "master": master_payload,
            "pragmas": pragmas,
            "tables": table_payload,
        }
    )


def _production_snapshot(
    conn: sqlite3.Connection, *, schema: str
) -> tuple[dict[str, int], int, dict[str, object], dict[str, dict[str, str]]]:
    counts: dict[str, int] = {}
    fingerprints: dict[str, object] = {}
    row_hashes: dict[str, dict[str, str]] = {}
    for table in _ALL_COMPATIBLE_TABLES:
        columns = _TABLE_COLUMNS[table]
        primary_key = _PRIMARY_KEYS[table]
        rows = _selected_rows(
            conn,
            schema=schema,
            table=table,
            columns=columns,
            order_by=primary_key,
        )
        counts[table] = len(rows)
        fingerprints[table] = {
            "row_count": len(rows),
            "canonical_rows_sha256": _canonical_sha256(
                [list(row) for row in rows]
            ),
        }
        primary_key_index = columns.index(primary_key)
        row_hashes[table] = {
            str(row[primary_key_index]): _row_sha256(row) for row in rows
        }
    fingerprints["schema"] = {
        table: _canonical_sha256(
            [list(row) for row in _schema_signature(conn, schema, table)]
        )
        for table in _ALL_COMPATIBLE_TABLES
    }
    fingerprints["full_database_sha256"] = _full_database_fingerprint(
        conn, schema=schema
    )
    public_counts = {table: counts[table] for table in _MERGE_TABLES}
    return (
        public_counts,
        counts["delivery_previews"],
        fingerprints,
        row_hashes,
    )


def _rows_for_run(
    conn: sqlite3.Connection,
    *,
    schema: str,
    table: str,
    run_id: str,
) -> dict[str, tuple[object, ...]]:
    columns = _TABLE_COLUMNS[table]
    primary_key = _PRIMARY_KEYS[table]
    rows = _selected_rows(
        conn,
        schema=schema,
        table=table,
        columns=columns,
        where="run_id=?",
        parameters=(run_id,),
        order_by=primary_key,
    )
    primary_key_index = columns.index(primary_key)
    return {str(row[primary_key_index]): row for row in rows}


def _require_staging_closure(
    conn: sqlite3.Connection, *, schema: str, run_id: str
) -> tuple[
    tuple[object, ...],
    dict[str, dict[str, tuple[object, ...]]],
]:
    run_rows = _selected_rows(
        conn,
        schema=schema,
        table="runs",
        columns=_TABLE_COLUMNS["runs"],
        where="run_id=?",
        parameters=(run_id,),
    )
    manifest_rows = _selected_rows(
        conn,
        schema=schema,
        table="backfill_manifests",
        columns=_MANIFEST_COLUMNS,
        where="run_id=?",
        parameters=(run_id,),
    )
    if len(run_rows) != 1 or len(manifest_rows) != 1:
        raise MergePreconditionError("staging_run_missing_or_ambiguous")
    run_row = run_rows[0]
    manifest = manifest_rows[0]
    run_values = dict(zip(_TABLE_COLUMNS["runs"], run_row, strict=True))
    manifest_values = dict(zip(_MANIFEST_COLUMNS, manifest, strict=True))
    if (
        run_values["status"] not in _BACKFILL_STATUSES
        or run_values["status"] != "success"
        or run_values["status"] != manifest_values["status"]
        or run_values["window_start_utc"] != manifest_values["window_start_utc"]
        or run_values["window_end_utc"] != manifest_values["effective_end_utc"]
        or run_values["provider_call"] != manifest_values["provider_call"]
        or _exact_int(run_values["provider_call"]) != 1
        or _exact_int(manifest_values["provider_call"]) != 1
        or run_values["live_send"] != manifest_values["live_send"]
        or _exact_int(run_values["live_send"]) != 0
    ):
        raise MergePreconditionError("staging_run_manifest_mismatch")
    delivery_count = conn.execute(
        f"SELECT COUNT(*) FROM {_qualified(schema, 'delivery_previews')} "
        "WHERE run_id=?",
        (run_id,),
    ).fetchone()[0]
    if int(delivery_count) != 0:
        raise MergePreconditionError("staging_delivery_not_empty")

    staging_rows = {
        table: _rows_for_run(conn, schema=schema, table=table, run_id=run_id)
        for table in (
            "raw_captures",
            "reddit_threads",
            "reddit_comments",
            "analysis_results",
        )
    }
    raws = staging_rows["raw_captures"]
    threads = staging_rows["reddit_threads"]
    comments = staging_rows["reddit_comments"]
    analyses = staging_rows["analysis_results"]
    raw_columns = _TABLE_COLUMNS["raw_captures"]
    thread_columns = _TABLE_COLUMNS["reddit_threads"]
    comment_columns = _TABLE_COLUMNS["reddit_comments"]
    analysis_columns = _TABLE_COLUMNS["analysis_results"]

    thread_raw_index = thread_columns.index("raw_capture_id")
    thread_parsed_index = thread_columns.index("parsed_comment_count")
    comment_post_index = comment_columns.index("post_id")
    comment_raw_index = comment_columns.index("raw_capture_id")
    analysis_type_index = analysis_columns.index("source_type")
    analysis_source_index = analysis_columns.index("source_id")
    raw_secret_index = raw_columns.index("secrets_written")
    analysis_provider_index = analysis_columns.index("provider_call")

    comments_by_post: dict[str, list[tuple[object, ...]]] = {
        post_id: [] for post_id in threads
    }
    referenced_raw_ids: set[str] = set()
    for post_id, thread in threads.items():
        raw_id = str(thread[thread_raw_index])
        if raw_id not in raws:
            raise MergePreconditionError("staging_lineage_invalid")
        referenced_raw_ids.add(raw_id)
    for comment in comments.values():
        post_id = str(comment[comment_post_index])
        raw_id = str(comment[comment_raw_index])
        if post_id not in threads or raw_id not in raws:
            raise MergePreconditionError("staging_lineage_invalid")
        comments_by_post[post_id].append(comment)
        referenced_raw_ids.add(raw_id)
    for post_id, thread in threads.items():
        if _exact_int(thread[thread_parsed_index]) != len(comments_by_post[post_id]):
            raise MergePreconditionError("staging_comment_parity_invalid")
    for raw_id in referenced_raw_ids:
        if _exact_int(raws[raw_id][raw_secret_index]) != 0:
            raise MergePreconditionError("staging_secret_boundary_invalid")

    expected_sources = {
        ("post", post_id) for post_id in threads
    } | {("comment", comment_id) for comment_id in comments}
    actual_sources: list[tuple[str, str]] = []
    for analysis in analyses.values():
        if _exact_int(analysis[analysis_provider_index]) != 0:
            raise MergePreconditionError("staging_analysis_provider_boundary_invalid")
        source_type = str(analysis[analysis_type_index])
        source_id = str(analysis[analysis_source_index])
        if source_type not in {"post", "comment"}:
            raise MergePreconditionError("staging_analysis_lineage_invalid")
        actual_sources.append((source_type, source_id))
    if (
        len(actual_sources) != len(set(actual_sources))
        or set(actual_sources) != expected_sources
    ):
        raise MergePreconditionError("staging_analysis_parity_invalid")

    cross_run_comments = conn.execute(
        f"SELECT COUNT(*) FROM {_qualified(schema, 'reddit_comments')} AS c "
        f"JOIN {_qualified(schema, 'reddit_threads')} AS t ON t.post_id=c.post_id "
        "WHERE t.run_id=? AND c.run_id<>?",
        (run_id, run_id),
    ).fetchone()[0]
    cross_run_analyses = conn.execute(
        f"SELECT COUNT(*) FROM {_qualified(schema, 'analysis_results')} AS a "
        f"LEFT JOIN {_qualified(schema, 'reddit_threads')} AS t "
        "ON a.source_type='post' AND a.source_id=t.post_id "
        f"LEFT JOIN {_qualified(schema, 'reddit_comments')} AS c "
        "ON a.source_type='comment' AND a.source_id=c.comment_id "
        "WHERE COALESCE(t.run_id, c.run_id)=? AND a.run_id<>?",
        (run_id, run_id),
    ).fetchone()[0]
    if int(cross_run_comments) or int(cross_run_analyses):
        raise MergePreconditionError("staging_cross_run_lineage_invalid")
    staging_rows["runs"] = {run_id: run_row}
    return run_row, staging_rows


def _conflict(
    *,
    post_id: str,
    entity_type: str,
    staging_id: str,
    existing_id: str,
    conflict_kind: str,
    staging_row: tuple[object, ...],
    existing_row: tuple[object, ...],
) -> dict[str, object]:
    return {
        "post_id_sha256": _identifier_sha256(post_id),
        "entity_type": entity_type,
        "staging_entity_id_sha256": _identifier_sha256(staging_id),
        "existing_entity_id_sha256": _identifier_sha256(existing_id),
        "conflict_kind": conflict_kind,
        "staging_row_sha256": _row_sha256(staging_row),
        "existing_row_sha256": _row_sha256(existing_row),
    }


def _build_internal_plan(
    staging_conn: sqlite3.Connection,
    production_conn: sqlite3.Connection,
    *,
    staging_schema: str,
    production_schema: str,
    run_id: str,
    staging_sha256: str,
    production_sha256: str,
    staging_identity: _FileIdentity,
    production_identity: _FileIdentity,
) -> _InternalPlan:
    run_row, staging_rows = _require_staging_closure(
        staging_conn, schema=staging_schema, run_id=run_id
    )
    production_counts, delivery_count, production_fingerprint, before_hashes = (
        _production_snapshot(production_conn, schema=production_schema)
    )
    production_rows = {
        table: {
            str(row[_TABLE_COLUMNS[table].index(_PRIMARY_KEYS[table])]): row
            for row in _selected_rows(
                production_conn,
                schema=production_schema,
                table=table,
                columns=_TABLE_COLUMNS[table],
                order_by=_PRIMARY_KEYS[table],
            )
        }
        for table in _MERGE_TABLES
    }
    existing_run = production_rows["runs"].get(run_id)
    if existing_run is not None and existing_run != run_row:
        raise MergePreconditionError("production_run_mismatch")
    run_action = "insert" if existing_run is None else "exact"

    raw_columns = _TABLE_COLUMNS["raw_captures"]
    thread_columns = _TABLE_COLUMNS["reddit_threads"]
    comment_columns = _TABLE_COLUMNS["reddit_comments"]
    analysis_columns = _TABLE_COLUMNS["analysis_results"]
    raw_unique_indexes = tuple(
        raw_columns.index(column)
        for column in ("source_method", "source_url", "raw_payload_hash")
    )
    production_raw_by_unique = {
        tuple(row[index] for index in raw_unique_indexes): (raw_id, row)
        for raw_id, row in production_rows["raw_captures"].items()
    }
    comment_post_index = comment_columns.index("post_id")
    analysis_type_index = analysis_columns.index("source_type")
    analysis_source_index = analysis_columns.index("source_id")
    thread_raw_index = thread_columns.index("raw_capture_id")
    comment_raw_index = comment_columns.index("raw_capture_id")

    comments_by_post: dict[str, list[tuple[str, tuple[object, ...]]]] = {
        post_id: [] for post_id in staging_rows["reddit_threads"]
    }
    for comment_id, row in staging_rows["reddit_comments"].items():
        comments_by_post[str(row[comment_post_index])].append((comment_id, row))
    analyses_by_post: dict[str, list[tuple[str, tuple[object, ...]]]] = {
        post_id: [] for post_id in staging_rows["reddit_threads"]
    }
    comment_to_post = {
        comment_id: str(row[comment_post_index])
        for comment_id, row in staging_rows["reddit_comments"].items()
    }
    for analysis_id, row in staging_rows["analysis_results"].items():
        source_type = str(row[analysis_type_index])
        source_id = str(row[analysis_source_index])
        post_id = source_id if source_type == "post" else comment_to_post[source_id]
        analyses_by_post[post_id].append((analysis_id, row))

    approved_posts: list[str] = []
    approved_comment_ids: set[str] = set()
    approved_analysis_ids: set[str] = set()
    approved_raw_insert_ids: set[str] = set()
    approved_raw_exact_ids: set[str] = set()
    conflicts: list[dict[str, object]] = []

    for post_id in sorted(staging_rows["reddit_threads"]):
        thread = staging_rows["reddit_threads"][post_id]
        post_conflicts: list[dict[str, object]] = []
        existing_thread = production_rows["reddit_threads"].get(post_id)
        if existing_thread is not None:
            post_conflicts.append(
                _conflict(
                    post_id=post_id,
                    entity_type="post",
                    staging_id=post_id,
                    existing_id=post_id,
                    conflict_kind="post_primary_key_conflict",
                    staging_row=thread,
                    existing_row=existing_thread,
                )
            )
        post_comments = sorted(comments_by_post[post_id], key=lambda item: item[0])
        post_analyses = sorted(analyses_by_post[post_id], key=lambda item: item[0])
        raw_ids = {str(thread[thread_raw_index])}
        raw_ids.update(str(row[comment_raw_index]) for _, row in post_comments)
        raw_statuses: dict[str, str] = {}
        for raw_id in sorted(raw_ids):
            staging_raw = staging_rows["raw_captures"][raw_id]
            existing_raw = production_rows["raw_captures"].get(raw_id)
            unique_key = tuple(staging_raw[index] for index in raw_unique_indexes)
            existing_unique = production_raw_by_unique.get(unique_key)
            if existing_raw is not None:
                if existing_raw == staging_raw:
                    raw_statuses[raw_id] = "exact"
                else:
                    raw_statuses[raw_id] = "conflict"
                    post_conflicts.append(
                        _conflict(
                            post_id=post_id,
                            entity_type="raw_capture",
                            staging_id=raw_id,
                            existing_id=raw_id,
                            conflict_kind="raw_primary_key_conflict",
                            staging_row=staging_raw,
                            existing_row=existing_raw,
                        )
                    )
            elif existing_unique is not None and existing_unique[0] != raw_id:
                raw_statuses[raw_id] = "conflict"
                post_conflicts.append(
                    _conflict(
                        post_id=post_id,
                        entity_type="raw_capture",
                        staging_id=raw_id,
                        existing_id=existing_unique[0],
                        conflict_kind="raw_unique_conflict",
                        staging_row=staging_raw,
                        existing_row=existing_unique[1],
                    )
                )
            else:
                raw_statuses[raw_id] = "insert"
        for comment_id, comment in post_comments:
            existing_comment = production_rows["reddit_comments"].get(comment_id)
            if existing_comment is not None:
                post_conflicts.append(
                    _conflict(
                        post_id=post_id,
                        entity_type="comment",
                        staging_id=comment_id,
                        existing_id=comment_id,
                        conflict_kind="comment_primary_key_conflict",
                        staging_row=comment,
                        existing_row=existing_comment,
                    )
                )
        for analysis_id, analysis in post_analyses:
            existing_analysis = production_rows["analysis_results"].get(analysis_id)
            if existing_analysis is not None:
                post_conflicts.append(
                    _conflict(
                        post_id=post_id,
                        entity_type="analysis",
                        staging_id=analysis_id,
                        existing_id=analysis_id,
                        conflict_kind="analysis_primary_key_conflict",
                        staging_row=analysis,
                        existing_row=existing_analysis,
                    )
                )
        if post_conflicts:
            conflicts.extend(post_conflicts)
            continue
        approved_posts.append(post_id)
        approved_comment_ids.update(comment_id for comment_id, _ in post_comments)
        approved_analysis_ids.update(analysis_id for analysis_id, _ in post_analyses)
        approved_raw_insert_ids.update(
            raw_id for raw_id, status_value in raw_statuses.items() if status_value == "insert"
        )
        approved_raw_exact_ids.update(
            raw_id for raw_id, status_value in raw_statuses.items() if status_value == "exact"
        )

    conflict_sort = lambda item: (
        str(item["post_id_sha256"]),
        str(item["entity_type"]),
        str(item["staging_entity_id_sha256"]),
        str(item["existing_entity_id_sha256"]),
        str(item["conflict_kind"]),
    )
    unique_conflicts: dict[tuple[str, ...], dict[str, object]] = {}
    for item in conflicts:
        unique_conflicts[conflict_sort(item)] = item
    conflicts = [unique_conflicts[key] for key in sorted(unique_conflicts)]
    conflict_counts = {kind: 0 for kind in _CONFLICT_KINDS}
    for item in conflicts:
        conflict_counts[str(item["conflict_kind"])] += 1

    staging_fingerprints = _staging_fingerprints(
        staging_conn, schema=staging_schema, run_id=run_id
    )
    approved_counts = {
        "runs_to_insert": int(run_action == "insert"),
        "raw_captures_to_insert": len(approved_raw_insert_ids),
        "raw_captures_exact": len(approved_raw_exact_ids),
        "reddit_threads_to_insert": len(approved_posts),
        "reddit_comments_to_insert": len(approved_comment_ids),
        "analysis_results_to_insert": len(approved_analysis_ids),
    }
    plan: dict[str, object] = {
        "schema_version": "backfill_insert_only_merge_plan_v1",
        "run_id": run_id,
        "status": "ready",
        "stop_reason": "merge_plan_complete",
        "query_only": True,
        "production_write": False,
        "provider_attempt_made": False,
        "live_send": False,
        "staging_sha256": staging_sha256,
        "production_sha256": production_sha256,
        "staging_fingerprints": staging_fingerprints,
        "production_baseline_counts": production_counts,
        "delivery_baseline_count": delivery_count,
        "run_action": run_action,
        "staging_run_sha256": _row_sha256(run_row),
        "existing_run_sha256": (
            None if existing_run is None else _row_sha256(existing_run)
        ),
        "approved_counts": approved_counts,
        "approved_post_ids_sha256": _canonical_sha256(sorted(approved_posts)),
        "skipped_post_count": len(staging_rows["reddit_threads"])
        - len(approved_posts),
        "conflict_counts": conflict_counts,
        "conflicts": conflicts,
    }
    plan["plan_sha256"] = _canonical_sha256(plan)
    if tuple(plan) != PLAN_KEYS:
        raise MergeInvariantError("plan_contract_invalid")

    internal_payload = {
        "plan_sha256": plan["plan_sha256"],
        "approved_post_ids": sorted(approved_posts),
        "raw_insert_ids": sorted(approved_raw_insert_ids),
        "raw_exact_ids": sorted(approved_raw_exact_ids),
        "comment_ids": sorted(approved_comment_ids),
        "analysis_ids": sorted(approved_analysis_ids),
        "staging_rows": {
            table: {
                identity: _row_sha256(row)
                for identity, row in sorted(rows.items())
            }
            for table, rows in sorted(staging_rows.items())
        },
        "production_fingerprint": production_fingerprint,
    }
    return _InternalPlan(
        public=plan,
        internal_sha256=_canonical_sha256(internal_payload),
        staging_identity=staging_identity,
        production_identity=production_identity,
        approved_post_ids=tuple(sorted(approved_posts)),
        raw_insert_ids=tuple(sorted(approved_raw_insert_ids)),
        raw_exact_ids=tuple(sorted(approved_raw_exact_ids)),
        comment_ids=tuple(sorted(approved_comment_ids)),
        analysis_ids=tuple(sorted(approved_analysis_ids)),
        staging_rows=staging_rows,
        production_before_hashes=before_hashes,
        production_fingerprint=production_fingerprint,
    )


def _plan_with_internal(
    staging_db: Path | str, production_db: Path | str, *, run_id: str
) -> _InternalPlan:
    if type(run_id) is not str or not run_id:
        raise MergePreconditionError("run_id_invalid")
    staging_identity = _database_file(staging_db)
    production_identity = _database_file(production_db)
    if (
        staging_identity.device,
        staging_identity.inode,
    ) == (
        production_identity.device,
        production_identity.inode,
    ):
        raise MergePreconditionError("database_path_alias")
    staging_hash = _sha256_file(staging_identity.path)
    production_hash = _sha256_file(production_identity.path)
    staging_conn: sqlite3.Connection | None = None
    production_conn: sqlite3.Connection | None = None
    try:
        staging_conn = _open_readonly_database(staging_identity.path)
        production_conn = _open_readonly_database(production_identity.path)
        _assert_database_contract(staging_conn, schema="main", staging=True)
        _assert_database_contract(production_conn, schema="main", staging=False)
        internal = _build_internal_plan(
            staging_conn,
            production_conn,
            staging_schema="main",
            production_schema="main",
            run_id=run_id,
            staging_sha256=staging_hash,
            production_sha256=production_hash,
            staging_identity=staging_identity,
            production_identity=production_identity,
        )
    except BackfillMergeError:
        raise
    except (sqlite3.Error, OSError, TypeError, ValueError):
        raise MergePreconditionError("merge_plan_failed") from None
    finally:
        _rollback_and_close(production_conn)
        _rollback_and_close(staging_conn)
    _assert_file_identity(staging_identity)
    _assert_file_identity(production_identity)
    if (
        _sha256_file(staging_identity.path) != staging_hash
        or _sha256_file(production_identity.path) != production_hash
    ):
        raise MergePreconditionError("database_snapshot_changed")
    return internal


def plan_insert_only_merge(
    staging_db: Path, production_db: Path, *, run_id: str
) -> dict[str, object]:
    return _plan_with_internal(staging_db, production_db, run_id=run_id).public


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_parent(path: Path) -> None:
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _cleanup_temporary_sqlite(path: Path) -> None:
    for candidate in (path,) + tuple(
        Path(str(path) + suffix) for suffix in _SQLITE_SIDECAR_SUFFIXES
    ):
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _create_sqlite_backup(
    production_path: Path, backup_path: Path
) -> _VerifiedBackup:
    try:
        parent = backup_path.parent.resolve(strict=True)
        if not parent.is_dir() or backup_path.exists() or backup_path.is_symlink():
            raise MergePreconditionError("backup_path_invalid")
    except MergePreconditionError:
        raise
    except OSError:
        raise MergePreconditionError("backup_path_invalid") from None
    temporary_handle: object | None = None
    temporary_path: Path | None = None
    source: sqlite3.Connection | None = None
    target: sqlite3.Connection | None = None
    published_backup: _VerifiedBackup | None = None
    try:
        temporary_handle = tempfile.NamedTemporaryFile(
            prefix=f".{backup_path.name}.",
            suffix=".sqlite-backup",
            dir=parent,
            delete=False,
        )
        temporary_path = Path(temporary_handle.name)
        temporary_handle.close()
        temporary_handle = None
        os.chmod(temporary_path, 0o600)
        source = _open_readonly_database(production_path)
        source.rollback()
        target = sqlite3.connect(temporary_path)
        source.backup(target)
        target.commit()
        target.close()
        target = None
        source.close()
        source = None
        _fsync_file(temporary_path)
        temporary_identity = _database_file(temporary_path)
        temporary_sha256 = _sha256_file(temporary_path)
        os.link(temporary_path, backup_path)
        final_identity = _database_file(backup_path)
        production_identity = _database_file(production_path)
        if (
            final_identity.device,
            final_identity.inode,
        ) == (
            production_identity.device,
            production_identity.inode,
        ):
            raise MergePreconditionError("database_path_alias")
        if (
            final_identity.device,
            final_identity.inode,
        ) != (
            temporary_identity.device,
            temporary_identity.inode,
        ):
            raise MergePreconditionError("backup_publication_changed")
        published_backup = _VerifiedBackup(
            identity=final_identity,
            sha256=temporary_sha256,
        )
        if _sha256_file(final_identity.path) != temporary_sha256:
            raise MergePreconditionError("backup_publication_changed")
        _fsync_parent(backup_path)
    except FileExistsError:
        raise MergePreconditionError("backup_path_exists") from None
    except BackfillMergeError:
        raise
    except (sqlite3.Error, OSError):
        raise MergePreconditionError("backup_creation_failed") from None
    finally:
        if temporary_handle is not None:
            try:
                temporary_handle.close()
            except OSError:
                pass
        _rollback_and_close(target)
        _rollback_and_close(source)
        if temporary_path is not None:
            _cleanup_temporary_sqlite(temporary_path)
    if published_backup is None:
        raise MergePreconditionError("backup_creation_failed")
    return published_backup


def _assert_verified_backup(
    backup: _VerifiedBackup, preflight: _InternalPlan
) -> None:
    if (
        backup.identity.device,
        backup.identity.inode,
    ) in {
        (
            preflight.staging_identity.device,
            preflight.staging_identity.inode,
        ),
        (
            preflight.production_identity.device,
            preflight.production_identity.inode,
        ),
    }:
        raise MergePreconditionError("database_path_alias")
    _assert_file_identity(backup.identity)
    if _sha256_file(backup.identity.path) != backup.sha256:
        raise MergePreconditionError("backup_snapshot_changed")
    _assert_file_identity(backup.identity)


def _verify_backup(
    published: _VerifiedBackup, preflight: _InternalPlan
) -> _VerifiedBackup:
    conn: sqlite3.Connection | None = None
    try:
        _assert_verified_backup(published, preflight)
        identity = _database_file(published.identity.path)
        if (
            identity.device,
            identity.inode,
        ) != (
            published.identity.device,
            published.identity.inode,
        ):
            raise MergePreconditionError("backup_publication_changed")
        if (
            identity.device,
            identity.inode,
        ) in {
            (
                preflight.staging_identity.device,
                preflight.staging_identity.inode,
            ),
            (
                preflight.production_identity.device,
                preflight.production_identity.inode,
            ),
        }:
            raise MergePreconditionError("database_path_alias")
        conn = _open_readonly_database(identity.path)
        _assert_database_contract(conn, schema="main", staging=False)
        _, _, fingerprint, _ = _production_snapshot(conn, schema="main")
        if fingerprint != preflight.production_fingerprint:
            raise MergePreconditionError("backup_snapshot_mismatch")
        _assert_file_identity(identity)
        _fsync_file(identity.path)
        _fsync_parent(identity.path)
        backup_sha256 = _sha256_file(identity.path)
        if backup_sha256 != published.sha256:
            raise MergePreconditionError("backup_snapshot_changed")
        verified = _VerifiedBackup(identity=identity, sha256=published.sha256)
        _assert_verified_backup(verified, preflight)
        return verified
    except BackfillMergeError:
        raise
    except (sqlite3.Error, OSError):
        raise MergePreconditionError("backup_verification_failed") from None
    finally:
        _rollback_and_close(conn)


def _open_merge_database(path: Path) -> sqlite3.Connection:
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(
            f"{path.as_uri()}?mode=rw",
            uri=True,
            timeout=5.0,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
    except sqlite3.Error:
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass
        raise MergePreconditionError("production_open_failed") from None


def _begin_immediate(conn: sqlite3.Connection) -> None:
    conn.execute("BEGIN IMMEDIATE")


def _insert_selected_rows(
    conn: sqlite3.Connection,
    *,
    table: str,
    identities: tuple[str, ...],
) -> int:
    columns = _TABLE_COLUMNS[table]
    primary_key = _PRIMARY_KEYS[table]
    inserted = 0
    for identity in identities:
        cursor = conn.execute(
            f"INSERT INTO main.{table}({', '.join(columns)}) "
            f"SELECT {', '.join('s.' + column for column in columns)} "
            f"FROM staging.{table} AS s WHERE s.{primary_key}=? "
            f"AND NOT EXISTS(SELECT 1 FROM main.{table} AS p "
            f"WHERE p.{primary_key}=s.{primary_key})",
            (identity,),
        )
        if cursor.rowcount not in {0, 1}:
            raise MergeInvariantError("insert_rowcount_invalid")
        inserted += int(cursor.rowcount)
    return inserted


def _insert_run(conn: sqlite3.Connection, run_id: str) -> int:
    return _insert_selected_rows(conn, table="runs", identities=(run_id,))


def _insert_raw_captures(
    conn: sqlite3.Connection, identities: tuple[str, ...]
) -> int:
    return _insert_selected_rows(conn, table="raw_captures", identities=identities)


def _insert_threads(conn: sqlite3.Connection, identities: tuple[str, ...]) -> int:
    return _insert_selected_rows(conn, table="reddit_threads", identities=identities)


def _insert_comments(conn: sqlite3.Connection, identities: tuple[str, ...]) -> int:
    return _insert_selected_rows(conn, table="reddit_comments", identities=identities)


def _insert_analyses(conn: sqlite3.Connection, identities: tuple[str, ...]) -> int:
    return _insert_selected_rows(conn, table="analysis_results", identities=identities)


def _verify_existing_rows_unchanged(
    conn: sqlite3.Connection, *, expected: dict[str, dict[str, str]]
) -> None:
    for table, expected_rows in expected.items():
        columns = _TABLE_COLUMNS[table]
        primary_key = _PRIMARY_KEYS[table]
        rows = _selected_rows(
            conn,
            schema="main",
            table=table,
            columns=columns,
            order_by=primary_key,
        )
        primary_key_index = columns.index(primary_key)
        actual = {
            str(row[primary_key_index]): _row_sha256(row)
            for row in rows
            if str(row[primary_key_index]) in expected_rows
        }
        if actual != expected_rows:
            raise MergeInvariantError("existing_rows_changed")


def _verify_approved_rows(
    conn: sqlite3.Connection, preflight: _InternalPlan
) -> None:
    expected_ids = {
        "runs": (str(preflight.public["run_id"]),),
        "raw_captures": tuple(
            sorted(set(preflight.raw_insert_ids) | set(preflight.raw_exact_ids))
        ),
        "reddit_threads": preflight.approved_post_ids,
        "reddit_comments": preflight.comment_ids,
        "analysis_results": preflight.analysis_ids,
    }
    for table, identities in expected_ids.items():
        columns = _TABLE_COLUMNS[table]
        primary_key = _PRIMARY_KEYS[table]
        for identity in identities:
            production_row = conn.execute(
                f"SELECT {', '.join(columns)} FROM main.{table} "
                f"WHERE {primary_key}=?",
                (identity,),
            ).fetchone()
            staging_row = preflight.staging_rows[table][identity]
            if production_row is None or tuple(production_row) != staging_row:
                raise MergeInvariantError("inserted_row_mismatch")


def _verify_in_transaction(
    conn: sqlite3.Connection,
    *,
    preflight: _InternalPlan,
    inserted: dict[str, int],
) -> None:
    approved = _object_mapping(preflight.public["approved_counts"])
    expected = {
        "runs": _exact_int(approved["runs_to_insert"]),
        "raw_captures": _exact_int(approved["raw_captures_to_insert"]),
        "reddit_threads": _exact_int(approved["reddit_threads_to_insert"]),
        "reddit_comments": _exact_int(approved["reddit_comments_to_insert"]),
        "analysis_results": _exact_int(approved["analysis_results_to_insert"]),
    }
    if inserted != expected:
        raise MergeInvariantError("insert_delta_mismatch")
    baseline_counts = _object_mapping(
        preflight.public["production_baseline_counts"]
    )
    for table, planned_delta in expected.items():
        actual_count = int(
            conn.execute(f"SELECT COUNT(*) FROM main.{table}").fetchone()[0]
        )
        if actual_count != _exact_int(baseline_counts[table]) + planned_delta:
            raise MergeInvariantError("insert_delta_mismatch")
    _verify_existing_rows_unchanged(
        conn, expected=preflight.production_before_hashes
    )
    _verify_approved_rows(conn, preflight)
    delivery_after = int(
        conn.execute("SELECT COUNT(*) FROM main.delivery_previews").fetchone()[0]
    )
    if delivery_after != _exact_int(
        preflight.public["delivery_baseline_count"]
    ):
        raise MergeInvariantError("delivery_delta_nonzero")
    for post_id in preflight.approved_post_ids:
        lineage = conn.execute(
            "SELECT t.run_id, r.run_id FROM main.reddit_threads AS t "
            "LEFT JOIN main.raw_captures AS r ON r.raw_capture_id=t.raw_capture_id "
            "WHERE t.post_id=?",
            (post_id,),
        ).fetchone()
        if (
            lineage is None
            or lineage[0] != preflight.public["run_id"]
            or lineage[1] != preflight.public["run_id"]
        ):
            raise MergeInvariantError("merged_lineage_invalid")
    for comment_id in preflight.comment_ids:
        lineage = conn.execute(
            "SELECT c.run_id, t.run_id, r.run_id "
            "FROM main.reddit_comments AS c "
            "LEFT JOIN main.reddit_threads AS t ON t.post_id=c.post_id "
            "LEFT JOIN main.raw_captures AS r ON r.raw_capture_id=c.raw_capture_id "
            "WHERE c.comment_id=?",
            (comment_id,),
        ).fetchone()
        if lineage is None or tuple(lineage) != (
            preflight.public["run_id"],
            preflight.public["run_id"],
            preflight.public["run_id"],
        ):
            raise MergeInvariantError("merged_lineage_invalid")


def _verify_postcommit(
    path: Path,
    preflight: _InternalPlan,
    backup: _VerifiedBackup,
) -> tuple[int, str]:
    identity = _database_file(path)
    if (
        identity.device,
        identity.inode,
    ) != (
        preflight.production_identity.device,
        preflight.production_identity.inode,
    ):
        raise MergeInvariantError("production_identity_changed")
    conn = _open_readonly_database(identity.path)
    try:
        _assert_file_identity(identity)
        _assert_verified_backup(backup, preflight)
        _assert_database_contract(conn, schema="main", staging=False)
        _verify_existing_rows_unchanged(
            conn, expected=preflight.production_before_hashes
        )
        _verify_approved_rows(conn, preflight)
        approved = _object_mapping(preflight.public["approved_counts"])
        planned_deltas = {
            "runs": _exact_int(approved["runs_to_insert"]),
            "raw_captures": _exact_int(approved["raw_captures_to_insert"]),
            "reddit_threads": _exact_int(approved["reddit_threads_to_insert"]),
            "reddit_comments": _exact_int(approved["reddit_comments_to_insert"]),
            "analysis_results": _exact_int(approved["analysis_results_to_insert"]),
        }
        baseline_counts = _object_mapping(
            preflight.public["production_baseline_counts"]
        )
        for table, planned_delta in planned_deltas.items():
            actual_count = int(
                conn.execute(f"SELECT COUNT(*) FROM main.{table}").fetchone()[0]
            )
            if actual_count != _exact_int(baseline_counts[table]) + planned_delta:
                raise MergeInvariantError("insert_delta_mismatch")
        delivery_after = int(
            conn.execute("SELECT COUNT(*) FROM delivery_previews").fetchone()[0]
        )
        if delivery_after != _exact_int(
            preflight.public["delivery_baseline_count"]
        ):
            raise MergeInvariantError("delivery_delta_nonzero")
        postmerge_sha256 = _sha256_file(identity.path)
        _assert_file_identity(identity)
        _assert_verified_backup(backup, preflight)
        return delivery_after, postmerge_sha256
    finally:
        _rollback_and_close(conn)


def merge_staging_insert_only(
    staging_db: Path,
    production_db: Path,
    *,
    run_id: str,
    backup_path: Path,
    expected_production_sha256: str,
    expected_plan_sha256: str | None = None,
    authorized: bool,
) -> MergeSummary:
    if authorized is not True or os.environ.get(
        "REDDIT_VOC_ENABLE_PRODUCTION_MERGE"
    ) != "1":
        raise MergeAuthorizationError("production_merge_not_authorized")
    if (
        type(expected_plan_sha256) is not str
        or _SHA256_PATTERN.fullmatch(expected_plan_sha256) is None
    ):
        raise MergePreconditionError("expected_plan_sha256_invalid")
    if (
        type(expected_production_sha256) is not str
        or _SHA256_PATTERN.fullmatch(expected_production_sha256) is None
    ):
        raise MergePreconditionError("expected_production_sha256_invalid")

    backup = Path(backup_path)
    if backup.exists() or backup.is_symlink():
        raise MergePreconditionError("backup_path_exists")
    try:
        backup_parent = backup.parent.resolve(strict=True)
    except OSError:
        raise MergePreconditionError("backup_path_invalid") from None
    if not backup_parent.is_dir():
        raise MergePreconditionError("backup_path_invalid")
    resolved_backup = backup_parent / backup.name

    preflight = _plan_with_internal(staging_db, production_db, run_id=run_id)
    if preflight.public["plan_sha256"] != expected_plan_sha256:
        raise MergePreconditionError("merge_plan_sha256_mismatch")
    if preflight.public["production_sha256"] != expected_production_sha256:
        raise MergePreconditionError("production_sha256_mismatch")
    if resolved_backup in {
        preflight.staging_identity.path,
        preflight.production_identity.path,
    }:
        raise MergePreconditionError("database_path_alias")

    published_backup = _create_sqlite_backup(
        preflight.production_identity.path, resolved_backup
    )
    try:
        verified_backup = _verify_backup(published_backup, preflight)
    except BackfillMergeError:
        raise
    except Exception:
        raise MergePreconditionError("backup_verification_failed") from None

    conn = _open_merge_database(preflight.production_identity.path)
    committed = False
    inserted: dict[str, int] = {}
    try:
        staging_uri = f"{preflight.staging_identity.path.as_uri()}?mode=ro"
        conn.execute("ATTACH DATABASE ? AS staging", (staging_uri,))
        _begin_immediate(conn)
        _assert_verified_backup(verified_backup, preflight)
        _assert_file_identity(preflight.staging_identity)
        _assert_file_identity(preflight.production_identity)
        if (
            _sha256_file(preflight.staging_identity.path)
            != preflight.public["staging_sha256"]
            or _sha256_file(preflight.production_identity.path)
            != expected_production_sha256
        ):
            raise MergePreconditionError("database_snapshot_changed")
        _assert_database_contract(conn, schema="main", staging=False)
        _assert_database_contract(conn, schema="staging", staging=True)
        locked = _build_internal_plan(
            conn,
            conn,
            staging_schema="staging",
            production_schema="main",
            run_id=run_id,
            staging_sha256=str(preflight.public["staging_sha256"]),
            production_sha256=expected_production_sha256,
            staging_identity=preflight.staging_identity,
            production_identity=preflight.production_identity,
        )
        if locked.public["plan_sha256"] != expected_plan_sha256:
            raise MergePreconditionError("merge_plan_sha256_mismatch")
        if (
            locked.internal_sha256 != preflight.internal_sha256
            or locked.public["plan_sha256"] != preflight.public["plan_sha256"]
        ):
            raise MergePreconditionError("merge_plan_drift")

        inserted["runs"] = _insert_run(conn, run_id)
        inserted["raw_captures"] = _insert_raw_captures(
            conn, preflight.raw_insert_ids
        )
        inserted["reddit_threads"] = _insert_threads(
            conn, preflight.approved_post_ids
        )
        inserted["reddit_comments"] = _insert_comments(
            conn, preflight.comment_ids
        )
        inserted["analysis_results"] = _insert_analyses(
            conn, preflight.analysis_ids
        )
        _verify_in_transaction(conn, preflight=preflight, inserted=inserted)
        _assert_verified_backup(verified_backup, preflight)
        try:
            conn.commit()
            committed = True
        except sqlite3.Error:
            raise MergeCommittedReviewError("commit_state_requires_review") from None
    except BackfillMergeError:
        if not committed:
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
        raise
    except Exception:
        if committed:
            raise MergeCommittedReviewError("committed_requires_review") from None
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        raise MergeInvariantError("merge_transaction_failed") from None
    finally:
        active_error = sys.exc_info()[0] is not None
        try:
            conn.close()
        except sqlite3.Error:
            if committed:
                raise MergeCommittedReviewError(
                    "committed_requires_review"
                ) from None
            if not active_error:
                raise MergeInvariantError(
                    "merge_connection_close_failed"
                ) from None

    try:
        delivery_after, postmerge_sha256 = _verify_postcommit(
            preflight.production_identity.path, preflight, verified_backup
        )
    except Exception:
        raise MergeCommittedReviewError("committed_requires_review") from None
    delivery_before = _exact_int(preflight.public["delivery_baseline_count"])
    approved = _object_mapping(preflight.public["approved_counts"])
    return MergeSummary(
        schema_version="backfill_insert_only_merge_result_v1",
        run_id=run_id,
        status="merged",
        stop_reason="merge_complete",
        authorized=True,
        production_write=True,
        plan_sha256=str(preflight.public["plan_sha256"]),
        staging_sha256=str(preflight.public["staging_sha256"]),
        expected_production_sha256=expected_production_sha256,
        premerge_production_sha256=expected_production_sha256,
        backup_sha256=verified_backup.sha256,
        postmerge_production_sha256=postmerge_sha256,
        planned_runs=_exact_int(approved["runs_to_insert"]),
        planned_raw_captures=_exact_int(approved["raw_captures_to_insert"]),
        reused_raw_captures=_exact_int(approved["raw_captures_exact"]),
        planned_threads=_exact_int(approved["reddit_threads_to_insert"]),
        planned_comments=_exact_int(approved["reddit_comments_to_insert"]),
        planned_analyses=_exact_int(approved["analysis_results_to_insert"]),
        inserted_runs=inserted["runs"],
        inserted_raw_captures=inserted["raw_captures"],
        inserted_threads=inserted["reddit_threads"],
        inserted_comments=inserted["reddit_comments"],
        inserted_analyses=inserted["analysis_results"],
        skipped_posts=_exact_int(preflight.public["skipped_post_count"]),
        conflict_count=len(_object_list(preflight.public["conflicts"])),
        delivery_before=delivery_before,
        delivery_after=delivery_after,
        delivery_delta=delivery_after - delivery_before,
        updated=0,
        deleted=0,
        provider_attempt_made=False,
        live_send=False,
    )
