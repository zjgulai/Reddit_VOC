#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
from typing import Any, Iterable


SCHEMA_VERSION = "task31z_committed_target_acceptance_v1"
TREE_SCHEMA_VERSION = "task31z_tree_inventory_v1"
EXPECTED_CHANGED_TABLES = {
    "analysis_results",
    "backfill_candidates",
    "backfill_checkpoints",
    "backfill_detail_batches",
    "reddit_threads",
}
EXPECTED_TARGET_STATUS_SUMMARY = {
    ("excluded", None): 1,
    ("hydrated", None): 10,
    ("hydrated", "post_only_coverage"): 1,
}
EXPECTED_CHECKPOINT_SUMMARY = {
    ("complete", "cursor_exhausted"): 11,
    ("partial", "post_only_coverage"): 1,
}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
LABEL_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")


class AcceptanceError(RuntimeError):
    pass


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_sha256(value: str, label: str) -> str:
    if SHA256_PATTERN.fullmatch(value) is None:
        raise AcceptanceError(f"{label}_invalid")
    return value


def _require_regular_file(path: Path, label: str) -> os.stat_result:
    try:
        value = path.lstat()
    except OSError as exc:
        raise AcceptanceError(f"{label}_unreadable") from exc
    if path.is_symlink() or not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
        raise AcceptanceError(f"{label}_not_pinned_regular_file")
    return value


def _require_directory(path: Path, label: str) -> os.stat_result:
    try:
        value = path.lstat()
    except OSError as exc:
        raise AcceptanceError(f"{label}_unreadable") from exc
    if path.is_symlink() or not stat.S_ISDIR(value.st_mode):
        raise AcceptanceError(f"{label}_not_pinned_directory")
    return value


def _tree_inventory(root: Path) -> dict[str, object]:
    _require_directory(root, "inventory_root")
    entries: list[dict[str, object]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        value = path.lstat()
        if path.is_symlink():
            raise AcceptanceError(f"inventory_symlink:{relative}")
        if stat.S_ISDIR(value.st_mode):
            entries.append(
                {
                    "kind": "directory",
                    "mode": stat.S_IMODE(value.st_mode),
                    "path": relative,
                }
            )
            continue
        if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
            raise AcceptanceError(f"inventory_special_file:{relative}")
        entries.append(
            {
                "kind": "file",
                "mode": stat.S_IMODE(value.st_mode),
                "path": relative,
                "sha256": _sha256_file(path),
                "size": value.st_size,
            }
        )
    envelope = {"entries": entries, "schema_version": TREE_SCHEMA_VERSION}
    return {
        "entry_count": len(entries),
        "sha256": hashlib.sha256(_canonical_bytes(envelope)).hexdigest(),
    }


def _parse_label_map(values: Iterable[str], label: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise AcceptanceError(f"{label}_entry_invalid")
        key, item = value.split("=", 1)
        if LABEL_PATTERN.fullmatch(key) is None or not item or key in parsed:
            raise AcceptanceError(f"{label}_entry_invalid")
        parsed[key] = item
    return parsed


def _load_bound_json(path: Path, expected_sha256: str, label: str) -> dict[str, Any]:
    _require_regular_file(path, label)
    if _sha256_file(path) != expected_sha256:
        raise AcceptanceError(f"{label}_sha256_mismatch")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AcceptanceError(f"{label}_json_invalid") from exc
    if not isinstance(value, dict):
        raise AcceptanceError(f"{label}_json_invalid")
    return value


def _connect_readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _table_names(connection: sqlite3.Connection) -> list[str]:
    return [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
    ]


def _table_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [
        str(row[1])
        for row in connection.execute(
            f"PRAGMA table_info({_quote_identifier(table)})"
        )
    ]


def _normalized_value(value: object) -> object:
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    return value


def _table_digest(connection: sqlite3.Connection, table: str) -> dict[str, object]:
    columns = _table_columns(connection, table)
    order = ",".join(_quote_identifier(column) for column in columns)
    query = f"SELECT * FROM {_quote_identifier(table)}"
    if order:
        query += f" ORDER BY {order}"
    digest = hashlib.sha256()
    count = 0
    for row in connection.execute(query):
        digest.update(_canonical_bytes([_normalized_value(value) for value in row]))
        digest.update(b"\n")
        count += 1
    return {"row_count": count, "sha256": digest.hexdigest()}


def _rows(
    connection: sqlite3.Connection,
    sql: str,
    parameters: tuple[object, ...] = (),
) -> list[dict[str, object]]:
    return [dict(row) for row in connection.execute(sql, parameters)]


def _row_digest(rows: list[dict[str, object]]) -> str:
    normalized = [
        {key: _normalized_value(value) for key, value in sorted(row.items())}
        for row in rows
    ]
    return hashlib.sha256(_canonical_bytes(normalized)).hexdigest()


def _sidecars(path: Path) -> list[str]:
    return [
        str(candidate)
        for suffix in ("-wal", "-shm", "-journal")
        if (candidate := Path(str(path) + suffix)).exists()
    ]


def _counter_rows(counter: Counter[tuple[str, str | None]]) -> list[dict[str, object]]:
    return [
        {"count": count, "status": key[0], "status_reason": key[1]}
        for key, count in sorted(counter.items(), key=lambda item: str(item[0]))
    ]


def _checkpoint_counter_rows(
    counter: Counter[tuple[str, str | None]],
) -> list[dict[str, object]]:
    return [
        {"count": count, "status": key[0], "stop_reason": key[1]}
        for key, count in sorted(counter.items(), key=lambda item: str(item[0]))
    ]


def _manifest_provider_evidence(
    connection: sqlite3.Connection,
    run_id: str,
    provider_digest: dict[str, object],
) -> dict[str, object]:
    columns = set(_table_columns(connection, "backfill_manifests"))
    required = {"run_id", "provider_request_count"}
    if not required.issubset(columns):
        raise AcceptanceError("manifest_provider_columns_missing")
    max_column = (
        "max_provider_requests"
        if "max_provider_requests" in columns
        else "provider_request_count"
    )
    row = connection.execute(
        f"SELECT {_quote_identifier(max_column)}, provider_request_count "
        "FROM backfill_manifests WHERE run_id=?",
        (run_id,),
    ).fetchone()
    if row is None:
        raise AcceptanceError("manifest_missing")
    maximum = int(row[0])
    count = int(row[1])
    if maximum < 0 or count < 0 or count > maximum:
        raise AcceptanceError("manifest_provider_evidence_invalid")
    return {
        "ledger_sha256": provider_digest["sha256"],
        "max_provider_requests": maximum,
        "provider_request_count": count,
    }


def _validate_receipts(
    admission: dict[str, Any],
    execution: dict[str, Any],
    *,
    expected_source_sha256: str,
    expected_target_sha256: str,
) -> None:
    admission_checks = admission.get("checks")
    if (
        admission.get("status") != "passed"
        or not isinstance(admission_checks, dict)
        or not admission_checks
        or any(value is not True for value in admission_checks.values())
    ):
        raise AcceptanceError("admission_receipt_not_passed")
    execution_state = execution.get("execution")
    postflight = execution.get("postflight")
    boundaries = execution.get("boundaries")
    if (
        execution.get("status") != "blocked_target_committed_needs_review"
        or not isinstance(execution_state, dict)
        or execution_state.get("wrapper_invocations") != 1
        or execution_state.get("recover_collection_invocations") != 1
        or execution_state.get("retry_performed") is not False
        or execution_state.get("network_none_gate_passed") is not True
        or execution_state.get("provider_cap") != 0
        or execution_state.get("provider_call") is not False
        or execution_state.get("cli_reason")
        != "collection_recovery_target_committed_needs_review"
        or not isinstance(postflight, dict)
        or postflight.get("source_sha256") != expected_source_sha256
        or postflight.get("target_sha256") != expected_target_sha256
        or postflight.get("report_present") is not False
        or not isinstance(boundaries, dict)
        or boundaries.get("source_write") is not False
        or boundaries.get("raw_write") is not False
        or boundaries.get("old_root_write") is not False
        or boundaries.get("provider_call") is not False
        or boundaries.get("production_deploy") is not False
        or boundaries.get("dingtalk_send") is not False
    ):
        raise AcceptanceError("execution_receipt_contract_invalid")


def _evaluate(args: argparse.Namespace) -> dict[str, object]:
    expected_source_sha256 = _require_sha256(
        args.expected_source_sha256, "expected_source_sha256"
    )
    expected_target_sha256 = _require_sha256(
        args.expected_target_sha256, "expected_target_sha256"
    )
    expected_admission_sha256 = _require_sha256(
        args.expected_admission_sha256, "expected_admission_sha256"
    )
    expected_execution_sha256 = _require_sha256(
        args.expected_execution_sha256, "expected_execution_sha256"
    )
    expected_raw_sha256 = _require_sha256(
        args.expected_raw_inventory_sha256, "expected_raw_inventory_sha256"
    )
    try:
        recovered_at = datetime.fromisoformat(args.recovered_at_utc)
    except ValueError as exc:
        raise AcceptanceError("recovered_at_utc_invalid") from exc
    if recovered_at.tzinfo is None or recovered_at.utcoffset() is None:
        raise AcceptanceError("recovered_at_utc_invalid")
    recovered_text = recovered_at.isoformat()

    source_path = args.source_database
    raw_root = args.raw_archive_dir
    target_path = args.target_database
    report_path = args.report
    admission_path = args.admission_receipt
    execution_path = args.execution_receipt
    _require_regular_file(source_path, "source_database")
    _require_regular_file(target_path, "target_database")
    _require_directory(raw_root, "raw_archive")
    if report_path.exists() or report_path.is_symlink():
        raise AcceptanceError("original_recovery_report_present")
    if _sidecars(source_path):
        raise AcceptanceError("source_sidecars_present")
    if _sidecars(target_path):
        raise AcceptanceError("target_sidecars_present")
    if _sha256_file(source_path) != expected_source_sha256:
        raise AcceptanceError("source_database_sha256_mismatch")
    if _sha256_file(target_path) != expected_target_sha256:
        raise AcceptanceError("target_database_sha256_mismatch")

    old_roots = {
        label: Path(path)
        for label, path in _parse_label_map(args.old_root, "old_root").items()
    }
    expected_old_roots = _parse_label_map(
        args.expected_old_root_sha256, "expected_old_root_sha256"
    )
    if set(old_roots) != set(expected_old_roots):
        raise AcceptanceError("old_root_labels_mismatch")
    for label, digest in expected_old_roots.items():
        _require_sha256(digest, f"expected_old_root_sha256_{label}")

    raw_before = _tree_inventory(raw_root)
    if raw_before["sha256"] != expected_raw_sha256:
        raise AcceptanceError("raw_inventory_sha256_mismatch")
    old_before = {label: _tree_inventory(path) for label, path in old_roots.items()}
    for label, inventory in old_before.items():
        if inventory["sha256"] != expected_old_roots[label]:
            raise AcceptanceError(f"old_root_sha256_mismatch:{label}")

    admission = _load_bound_json(
        admission_path, expected_admission_sha256, "admission_receipt"
    )
    execution = _load_bound_json(
        execution_path, expected_execution_sha256, "execution_receipt"
    )
    _validate_receipts(
        admission,
        execution,
        expected_source_sha256=expected_source_sha256,
        expected_target_sha256=expected_target_sha256,
    )

    source = _connect_readonly(source_path)
    target = _connect_readonly(target_path)
    try:
        if [row[0] for row in source.execute("PRAGMA integrity_check")] != ["ok"]:
            raise AcceptanceError("source_integrity_check_failed")
        if source.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise AcceptanceError("source_foreign_key_check_failed")
        if [row[0] for row in target.execute("PRAGMA integrity_check")] != ["ok"]:
            raise AcceptanceError("target_integrity_check_failed")
        if target.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise AcceptanceError("target_foreign_key_check_failed")

        source_tables = _table_names(source)
        target_tables = _table_names(target)
        if source_tables != target_tables:
            raise AcceptanceError("target_schema_table_set_mismatch")
        table_comparison: dict[str, dict[str, object]] = {}
        changed_tables: set[str] = set()
        for table in source_tables:
            source_digest = _table_digest(source, table)
            target_digest = _table_digest(target, table)
            exact = source_digest == target_digest
            table_comparison[table] = {
                "exact": exact,
                "source": source_digest,
                "target": target_digest,
            }
            if not exact:
                changed_tables.add(table)
        if changed_tables != EXPECTED_CHANGED_TABLES:
            raise AcceptanceError("changed_table_domain_mismatch")

        provider = table_comparison.get("backfill_provider_attempts")
        if provider is None or provider["exact"] is not True:
            raise AcceptanceError("provider_ledger_changed")
        source_provider = _manifest_provider_evidence(
            source, args.run_id, provider["source"]
        )
        target_provider = _manifest_provider_evidence(
            target, args.run_id, provider["target"]
        )
        if source_provider != target_provider:
            raise AcceptanceError("provider_evidence_changed")

        source_candidates = _rows(
            source,
            "SELECT * FROM backfill_candidates WHERE run_id=? "
            "AND status='failed' AND status_reason='comments_schema_drift' "
            "ORDER BY post_id",
            (args.run_id,),
        )
        candidate_ids = tuple(str(row["post_id"]) for row in source_candidates)
        if len(candidate_ids) != 12 or len(set(candidate_ids)) != 12:
            raise AcceptanceError("source_candidate_set_mismatch")
        all_source_failures = {
            str(row[0])
            for row in source.execute(
                "SELECT post_id FROM backfill_candidates WHERE run_id=? "
                "AND (status='failed' OR status_reason='comments_schema_drift')",
                (args.run_id,),
            )
        }
        if all_source_failures != set(candidate_ids):
            raise AcceptanceError("source_failure_domain_mismatch")
        placeholders = ",".join("?" for _ in candidate_ids)
        target_candidates = _rows(
            target,
            f"SELECT * FROM backfill_candidates WHERE run_id=? "
            f"AND post_id IN ({placeholders}) ORDER BY post_id",
            (args.run_id, *candidate_ids),
        )
        if {str(row["post_id"]) for row in target_candidates} != set(candidate_ids):
            raise AcceptanceError("target_candidate_set_mismatch")
        if any(row.get("updated_at_utc") != recovered_text for row in target_candidates):
            raise AcceptanceError("target_candidate_timestamp_mismatch")
        target_status_summary = Counter(
            (str(row["status"]), row.get("status_reason"))
            for row in target_candidates
        )
        if target_status_summary != EXPECTED_TARGET_STATUS_SUMMARY:
            raise AcceptanceError("target_candidate_status_mismatch")

        checkpoints = _rows(
            target,
            "SELECT * FROM backfill_checkpoints WHERE run_id=? "
            "AND lane_type='comments' "
            f"AND lane_key IN ({placeholders}) ORDER BY lane_key",
            (args.run_id, *candidate_ids),
        )
        if {str(row["lane_key"]) for row in checkpoints} != set(candidate_ids):
            raise AcceptanceError("target_comment_checkpoint_set_mismatch")
        checkpoint_summary = Counter(
            (str(row["status"]), row.get("stop_reason")) for row in checkpoints
        )
        if checkpoint_summary != EXPECTED_CHECKPOINT_SUMMARY:
            raise AcceptanceError("target_comment_checkpoint_status_mismatch")

        artifact_mapping: list[dict[str, object]] = []
        for post_id in candidate_ids:
            lane_hash = hashlib.sha256(post_id.encode("utf-8")).hexdigest()
            artifact_sql = (
                "SELECT artifact_id,lane_key_hash,page_number,request_cursor,"
                "response_cursor,payload_sha256 FROM backfill_raw_artifacts "
                "WHERE run_id=? AND lane_type='comments' AND lane_key_hash=? "
                "ORDER BY page_number,artifact_id"
            )
            source_artifacts = _rows(
                source, artifact_sql, (args.run_id, lane_hash)
            )
            target_artifacts = _rows(
                target, artifact_sql, (args.run_id, lane_hash)
            )
            if (
                source_artifacts != target_artifacts
                or len(target_artifacts) != 1
                or target_artifacts[0]["page_number"] != 1
                or target_artifacts[0]["request_cursor"] is not None
                or target_artifacts[0]["response_cursor"] is not None
            ):
                raise AcceptanceError(f"comments_artifact_mapping_invalid:{post_id}")
            artifact_mapping.append(
                {
                    "artifact_id": target_artifacts[0]["artifact_id"],
                    "lane_key_hash": lane_hash,
                    "post_id": post_id,
                    "payload_sha256": target_artifacts[0]["payload_sha256"],
                }
            )

        source_structured = source.execute(
            "SELECT 1 FROM reddit_threads WHERE run_id=? "
            f"AND post_id IN ({placeholders}) LIMIT 1",
            (args.run_id, *candidate_ids),
        ).fetchone()
        source_comments = source.execute(
            "SELECT 1 FROM reddit_comments WHERE run_id=? "
            f"AND post_id IN ({placeholders}) LIMIT 1",
            (args.run_id, *candidate_ids),
        ).fetchone()
        if source_structured is not None or source_comments is not None:
            raise AcceptanceError("source_structured_residue_present")
        for candidate in target_candidates:
            if candidate["status"] != "hydrated":
                continue
            post_id = str(candidate["post_id"])
            thread = target.execute(
                "SELECT parsed_comment_count FROM reddit_threads "
                "WHERE run_id=? AND post_id=?",
                (args.run_id, post_id),
            ).fetchone()
            if thread is None:
                raise AcceptanceError(f"target_thread_missing:{post_id}")
            comment_count = int(
                target.execute(
                    "SELECT COUNT(*) FROM reddit_comments WHERE run_id=? AND post_id=?",
                    (args.run_id, post_id),
                ).fetchone()[0]
            )
            if int(thread["parsed_comment_count"]) != comment_count:
                raise AcceptanceError(f"target_comment_count_mismatch:{post_id}")

        owner_batches = _rows(
            source,
            "SELECT DISTINCT b.* FROM backfill_detail_batches AS b "
            "JOIN backfill_detail_batch_members AS m "
            "ON m.run_id=b.run_id AND m.batch_id=b.batch_id "
            f"WHERE b.run_id=? AND m.post_id IN ({placeholders}) "
            "ORDER BY b.batch_number",
            (args.run_id, *candidate_ids),
        )
        if len(owner_batches) != 6:
            raise AcceptanceError("owner_batch_count_mismatch")
        owner_batch_ids = tuple(str(row["batch_id"]) for row in owner_batches)
        batch_placeholders = ",".join("?" for _ in owner_batch_ids)
        if any(
            not (
                (row["status"] == "complete" and row.get("stop_reason") is None)
                or (
                    row["status"] == "failed"
                    and row.get("stop_reason") == "comments_schema_drift"
                )
            )
            for row in owner_batches
        ):
            raise AcceptanceError("source_owner_batch_state_invalid")
        target_owner_batches = _rows(
            target,
            "SELECT * FROM backfill_detail_batches WHERE run_id=? "
            f"AND batch_id IN ({batch_placeholders}) ORDER BY batch_number",
            (args.run_id, *owner_batch_ids),
        )
        if (
            {str(row["batch_id"]) for row in target_owner_batches}
            != set(owner_batch_ids)
            or any(
                row["status"] != "complete"
                or row.get("stop_reason") is not None
                or row.get("updated_at_utc") != recovered_text
                for row in target_owner_batches
            )
        ):
            raise AcceptanceError("target_owner_batch_state_invalid")
        raw_persisted_batch_count = 0
        for batch in owner_batches:
            artifact_id = batch.get("artifact_id")
            if artifact_id is None:
                continue
            artifact = source.execute(
                "SELECT artifact_kind,lane_type,parser_kind,source_method "
                "FROM backfill_raw_artifacts WHERE run_id=? AND artifact_id=?",
                (args.run_id, artifact_id),
            ).fetchone()
            if artifact is None or tuple(artifact) != (
                "detail",
                "detail_batch",
                "tikhub_detail",
                "tikhub_detail",
            ):
                raise AcceptanceError("owner_batch_artifact_invalid")
            raw_persisted_batch_count += 1

        owner_members = _rows(
            source,
            "SELECT batch_id,post_id,ordinal FROM backfill_detail_batch_members "
            "WHERE run_id=? "
            f"AND batch_id IN ({batch_placeholders}) ORDER BY batch_id,ordinal",
            (args.run_id, *owner_batch_ids),
        )
        member_ids = {str(row["post_id"]) for row in owner_members}
        if not set(candidate_ids).issubset(member_ids):
            raise AcceptanceError("owner_batch_candidate_membership_invalid")
        extra_member_ids = tuple(sorted(member_ids - set(candidate_ids)))
        if len(extra_member_ids) != 166:
            raise AcceptanceError("owner_batch_extra_member_count_mismatch")
        extra_placeholders = ",".join("?" for _ in extra_member_ids)
        source_extra_candidates = _rows(
            source,
            "SELECT * FROM backfill_candidates WHERE run_id=? "
            f"AND post_id IN ({extra_placeholders}) ORDER BY post_id",
            (args.run_id, *extra_member_ids),
        )
        target_extra_candidates = _rows(
            target,
            "SELECT * FROM backfill_candidates WHERE run_id=? "
            f"AND post_id IN ({extra_placeholders}) ORDER BY post_id",
            (args.run_id, *extra_member_ids),
        )
        if (
            source_extra_candidates != target_extra_candidates
            or any(
                row["status"] not in {"hydrated", "excluded"}
                for row in target_extra_candidates
            )
        ):
            raise AcceptanceError("owner_batch_extra_members_changed")

        if (
            target.execute(
                "SELECT 1 FROM delivery_previews WHERE run_id=? LIMIT 1",
                (args.run_id,),
            ).fetchone()
            is not None
        ):
            raise AcceptanceError("delivery_preview_present")

        source_candidate_ids = {
            str(row[0])
            for row in source.execute(
                "SELECT post_id FROM backfill_candidates WHERE run_id=?",
                (args.run_id,),
            )
        }
        target_candidate_ids = {
            str(row[0])
            for row in target.execute(
                "SELECT post_id FROM backfill_candidates WHERE run_id=?",
                (args.run_id,),
            )
        }
        new_candidate_count = len(target_candidate_ids - source_candidate_ids)
        discovery_artifact_count = int(
            source.execute(
                "SELECT COUNT(*) FROM backfill_raw_artifacts WHERE run_id=? "
                "AND lane_type NOT IN ('comments','detail_batch')",
                (args.run_id,),
            ).fetchone()[0]
        )
        occurrence_count = 0
        for table in source_tables:
            if "occurrence" in table and "backfill" in table:
                occurrence_count += int(
                    source.execute(
                        f"SELECT COUNT(*) FROM {_quote_identifier(table)} "
                        "WHERE run_id=?",
                        (args.run_id,),
                    ).fetchone()[0]
                )
        source_recoverable_discovery_lanes = _rows(
            source,
            "SELECT lane_type,lane_key,page_number FROM backfill_checkpoints "
            "WHERE run_id=? AND lane_type!='comments' AND status='partial' "
            "AND stop_reason='schema_drift' AND last_error='TikHubSchemaDrift' "
            "ORDER BY lane_type,lane_key",
            (args.run_id,),
        )
        recovered_discovery_lane_count = 0
        for lane in source_recoverable_discovery_lanes:
            lane_hash = hashlib.sha256(str(lane["lane_key"]).encode()).hexdigest()
            artifact_pages = [
                int(row[0])
                for row in source.execute(
                    "SELECT page_number FROM backfill_raw_artifacts "
                    "WHERE run_id=? AND artifact_kind='discovery' "
                    "AND lane_type=? AND lane_key_hash=? "
                    "ORDER BY page_number,artifact_id",
                    (args.run_id, lane["lane_type"], lane_hash),
                ).fetchall()
            ]
            page_chain_valid = artifact_pages == list(
                range(1, len(artifact_pages) + 1)
            )
            recoverable_extra_page = bool(
                page_chain_valid
                and len(artifact_pages) == int(lane["page_number"]) + 1
            )
            target_advanced = target.execute(
                "SELECT 1 FROM backfill_checkpoints WHERE run_id=? "
                "AND lane_type=? AND lane_key=? AND page_number=? "
                "AND NOT (status='partial' AND stop_reason='schema_drift' "
                "AND last_error='TikHubSchemaDrift')",
                (
                    args.run_id,
                    lane["lane_type"],
                    lane["lane_key"],
                    len(artifact_pages),
                ),
            ).fetchone() is not None
            if recoverable_extra_page and target_advanced:
                recovered_discovery_lane_count += 1
        archived_hydrated_candidate_count = sum(
            1 for row in target_candidates if row["status"] in {"hydrated", "excluded"}
        )
        reconstructed_result = {
            "archived_hydrated_candidate_count": archived_hydrated_candidate_count,
            "candidate_count": len(target_candidate_ids),
            "database_write": "recovery_target_only",
            "discovery_artifact_count": discovery_artifact_count,
            "discovery_occurrence_count": occurrence_count,
            "live_send": False,
            "new_candidate_count": new_candidate_count,
            "prepared_batch_count": len(owner_batches) - raw_persisted_batch_count,
            "provider_attempt_made": False,
            "provider_call": False,
            "raw_inventory_sha256": raw_before["sha256"],
            "raw_persisted_batch_count": raw_persisted_batch_count,
            "recovered_discovery_lane_count": recovered_discovery_lane_count,
            "reset_batch_count": len(owner_batches),
            "reset_candidate_count": len(candidate_ids),
            "reset_comment_checkpoint_count": len(checkpoints),
            "run_id": args.run_id,
            "schema_version": "backfill_collection_recovery_v1",
            "source_db_sha256": expected_source_sha256,
            "source_max_provider_requests": source_provider["max_provider_requests"],
            "source_provider_ledger_sha256": source_provider["ledger_sha256"],
            "source_provider_request_count": source_provider[
                "provider_request_count"
            ],
            "status": "complete",
            "stop_reason": "collection_recovery_complete",
            "target_db_sha256": expected_target_sha256,
            "target_max_provider_requests": target_provider["max_provider_requests"],
            "target_provider_ledger_sha256": target_provider["ledger_sha256"],
            "target_provider_request_count": target_provider[
                "provider_request_count"
            ],
        }
        count_keys = (
            "discovery_artifact_count",
            "discovery_occurrence_count",
            "candidate_count",
            "new_candidate_count",
            "recovered_discovery_lane_count",
            "reset_candidate_count",
            "reset_batch_count",
            "reset_comment_checkpoint_count",
            "raw_persisted_batch_count",
            "prepared_batch_count",
            "archived_hydrated_candidate_count",
        )
        acceptance_contract_valid = bool(
            reconstructed_result["status"] == "complete"
            and reconstructed_result["stop_reason"] == "collection_recovery_complete"
            and reconstructed_result["database_write"] == "recovery_target_only"
            and reconstructed_result["provider_call"] is False
            and reconstructed_result["provider_attempt_made"] is False
            and reconstructed_result["live_send"] is False
            and reconstructed_result["source_db_sha256"] == expected_source_sha256
            and reconstructed_result["target_db_sha256"] == expected_target_sha256
            and reconstructed_result["target_max_provider_requests"]
            == reconstructed_result["source_max_provider_requests"]
            and reconstructed_result["target_provider_request_count"]
            == reconstructed_result["source_provider_request_count"]
            and reconstructed_result["target_provider_ledger_sha256"]
            == reconstructed_result["source_provider_ledger_sha256"]
            and reconstructed_result["reset_candidate_count"] > 0
            and reconstructed_result["reset_batch_count"] > 0
            and reconstructed_result["reset_comment_checkpoint_count"] > 0
            and reconstructed_result["archived_hydrated_candidate_count"] > 0
            and reconstructed_result["candidate_count"]
            >= reconstructed_result["reset_candidate_count"]
            and reconstructed_result["raw_persisted_batch_count"]
            + reconstructed_result["prepared_batch_count"]
            == reconstructed_result["reset_batch_count"]
            and all(
                type(reconstructed_result[key]) is int
                and reconstructed_result[key] >= 0
                for key in count_keys
            )
        )
        original_cli_contract_valid = bool(
            acceptance_contract_valid
            and reconstructed_result["recovered_discovery_lane_count"] > 0
        )
        if not acceptance_contract_valid:
            raise AcceptanceError("reconstructed_recovery_contract_invalid")
    finally:
        source.close()
        target.close()

    raw_after = _tree_inventory(raw_root)
    old_after = {label: _tree_inventory(path) for label, path in old_roots.items()}
    if raw_after != raw_before:
        raise AcceptanceError("raw_inventory_changed_during_acceptance")
    if old_after != old_before:
        raise AcceptanceError("old_root_changed_during_acceptance")
    if _sha256_file(source_path) != expected_source_sha256:
        raise AcceptanceError("source_database_changed_during_acceptance")
    if _sha256_file(target_path) != expected_target_sha256:
        raise AcceptanceError("target_database_changed_during_acceptance")
    if _sidecars(source_path) or _sidecars(target_path):
        raise AcceptanceError("sqlite_sidecar_created_during_acceptance")

    return {
        "admission_receipt_sha256": expected_admission_sha256,
        "artifact_mapping": artifact_mapping,
        "boundaries": {
            "dingtalk_send": False,
            "original_cli_report_created": False,
            "production_deploy": False,
            "provider_call": False,
            "recover_collection_invoked": False,
            "remote_write": False,
            "source_write": False,
            "target_write": False,
        },
        "changed_tables": sorted(changed_tables),
        "checkpoint_summary": _checkpoint_counter_rows(checkpoint_summary),
        "evidence_grade": "L3-production-read-only",
        "execution_receipt_sha256": expected_execution_sha256,
        "extra_owner_member_count": len(extra_member_ids),
        "old_root_inventories": old_after,
        "original_cli_contract_divergences": (
            []
            if original_cli_contract_valid
            else ["recovered_discovery_lane_count_must_be_positive"]
        ),
        "original_cli_recovery_contract_valid": original_cli_contract_valid,
        "original_recovery_report_present": False,
        "owner_batch_count": len(owner_batches),
        "raw_inventory": raw_after,
        "reconstructed_recovery": reconstructed_result,
        "reconstructed_recovery_contract_valid": acceptance_contract_valid,
        "run_id": args.run_id,
        "schema_version": SCHEMA_VERSION,
        "source_database_sha256": expected_source_sha256,
        "status": "passed",
        "target_candidate_status_summary": _counter_rows(target_status_summary),
        "target_database_sha256": expected_target_sha256,
        "verdict": "accepted_recovery_candidate_not_original_cli_complete",
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-database", type=Path, required=True)
    parser.add_argument("--raw-archive-dir", type=Path, required=True)
    parser.add_argument("--target-database", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--admission-receipt", type=Path, required=True)
    parser.add_argument("--execution-receipt", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--recovered-at-utc", required=True)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--expected-target-sha256", required=True)
    parser.add_argument("--expected-admission-sha256", required=True)
    parser.add_argument("--expected-execution-sha256", required=True)
    parser.add_argument("--expected-raw-inventory-sha256", required=True)
    parser.add_argument("--old-root", action="append", default=[])
    parser.add_argument("--expected-old-root-sha256", action="append", default=[])
    return parser


def main() -> int:
    try:
        value = _evaluate(_build_parser().parse_args())
        exit_code = 0
    except (AcceptanceError, OSError, sqlite3.Error, ValueError) as exc:
        value = {
            "boundaries": {
                "dingtalk_send": False,
                "original_cli_report_created": False,
                "production_deploy": False,
                "provider_call": False,
                "recover_collection_invoked": False,
                "remote_write": False,
                "source_write": False,
                "target_write": False,
            },
            "errors": [f"{type(exc).__name__}:{exc}"],
            "evidence_grade": "L3-production-read-only",
            "generated_at_utc": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "schema_version": SCHEMA_VERSION,
            "status": "failed",
            "verdict": "quarantine_preserved",
        }
        exit_code = 3
    sys.stdout.buffer.write(_canonical_bytes(value) + b"\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
