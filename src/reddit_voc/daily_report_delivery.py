from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import fcntl
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Literal, Mapping, Protocol, Sequence

from .prepared_bundle import PreparedOutboxPart, PreparedReportRoots, load_verified_prepared_report
from .report_contracts import (
    canonical_json_bytes,
    load_regular_json,
    load_report_schema_assets,
    sha256_hex,
)
from .report_source_state import (
    classify_report_source_state,
    validate_frozen_report_source_state,
)


TransportKind = Literal["synthetic", "external"]
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_HASH_LABEL = re.compile(r"^sha256:[0-9a-f]{64}$")
_EVENT_V1_INPUT_KEYS = {
    "schema_version",
    "run_id",
    "artifact_version_id",
    "bundle_sha256",
    "outbox_sha256",
    "part_kind",
    "part_index",
    "part_sha256",
    "authorization_id",
    "attempt_id",
    "timestamp",
    "status",
    "external_attempt_made",
    "http_status",
    "response_hash",
}
_EVENT_V2_INPUT_KEYS = {*_EVENT_V1_INPUT_KEYS, "destination_id"}
_EVENT_V1_KEYS = {
    *_EVENT_V1_INPUT_KEYS,
    "sequence",
    "previous_entry_hash",
    "entry_hash",
}
_EVENT_V2_KEYS = {
    *_EVENT_V2_INPUT_KEYS,
    "sequence",
    "previous_entry_hash",
    "entry_hash",
}
_DESTINATION_IDS = ("primary", "secondary")
_DELIVERY_RECORD_KEYS = (
    "delivery_id",
    "run_id",
    "channel",
    "mode",
    "status",
    "message_hash",
    "artifact_paths",
    "live_send",
)


class ArtifactHeadChecker(Protocol):
    def __call__(self, url: str, *, timeout_seconds: int) -> int: ...


class ExternalAttemptStartSink(Protocol):
    def __call__(self) -> None: ...


class DingTalkByteTransport(Protocol):
    transport_kind: TransportKind

    def __call__(
        self,
        *,
        webhook_url: str,
        body_bytes: bytes,
        secret: str | None,
        timeout_seconds: int,
        request_start_sink: ExternalAttemptStartSink | None,
    ) -> object: ...


class DeliveryBoundaryError(RuntimeError):
    def __init__(self, reason_code: str, *, external_attempt_made: bool) -> None:
        self.reason_code = reason_code
        self.external_attempt_made = external_attempt_made
        super().__init__(reason_code)


@dataclass(frozen=True)
class DeliveryDecision:
    sendable_part_indexes: tuple[int, ...]
    blocked_reason: str | None


@dataclass(frozen=True)
class DeliverySummary:
    run_id: str
    artifact_version_id: str | None
    outbox_sha256: str | None
    attempted_part_indexes: tuple[int, ...]
    sent_part_indexes: tuple[int, ...]
    rejected_part_indexes: tuple[int, ...]
    ledger_tip_before: str | None
    ledger_tip_after: str | None
    status: str
    report_live_send: bool
    alert_live_send: bool
    live_send: bool

    def as_dict(self) -> Mapping[str, object]:
        return {
            "run_id": self.run_id,
            "artifact_version_id": self.artifact_version_id,
            "outbox_sha256": self.outbox_sha256,
            "attempted_part_indexes": list(self.attempted_part_indexes),
            "sent_part_indexes": list(self.sent_part_indexes),
            "rejected_part_indexes": list(self.rejected_part_indexes),
            "ledger_tip_before": self.ledger_tip_before,
            "ledger_tip_after": self.ledger_tip_after,
            "status": self.status,
            "report_live_send": self.report_live_send,
            "alert_live_send": self.alert_live_send,
            "live_send": self.live_send,
        }


@dataclass(frozen=True)
class DingTalkDestinationCredential:
    destination_id: str
    webhook_url: str
    webhook_secret: str | None


@dataclass(frozen=True)
class DestinationDeliverySummary:
    destination_id: str
    attempted_part_indexes: tuple[int, ...]
    sent_part_indexes: tuple[int, ...]
    rejected_part_indexes: tuple[int, ...]
    ledger_tip_before: str | None
    ledger_tip_after: str | None
    status: str
    report_live_send: bool

    def as_dict(self) -> Mapping[str, object]:
        return {
            "destination_id": self.destination_id,
            "attempted_part_indexes": list(self.attempted_part_indexes),
            "sent_part_indexes": list(self.sent_part_indexes),
            "rejected_part_indexes": list(self.rejected_part_indexes),
            "ledger_tip_before": self.ledger_tip_before,
            "ledger_tip_after": self.ledger_tip_after,
            "status": self.status,
            "report_live_send": self.report_live_send,
        }


@dataclass(frozen=True)
class MultiDestinationDeliverySummary:
    run_id: str
    artifact_version_id: str | None
    outbox_sha256: str | None
    destinations: tuple[DestinationDeliverySummary, ...]
    status: str
    report_live_send: bool
    alert_live_send: bool
    live_send: bool

    def as_dict(self) -> Mapping[str, object]:
        return {
            "run_id": self.run_id,
            "artifact_version_id": self.artifact_version_id,
            "outbox_sha256": self.outbox_sha256,
            "destinations": [item.as_dict() for item in self.destinations],
            "status": self.status,
            "report_live_send": self.report_live_send,
            "alert_live_send": self.alert_live_send,
            "live_send": self.live_send,
        }


@dataclass(frozen=True)
class DeliveryProjectionSummary:
    run_id: str
    artifact_version_id: str
    outbox_sha256: str
    expected_count: int
    inserted_count: int
    existing_count: int
    fully_projected: bool
    primary_ledger_tip: str
    secondary_ledger_tip: str

    def as_dict(self) -> Mapping[str, object]:
        return {
            "run_id": self.run_id,
            "artifact_version_id": self.artifact_version_id,
            "outbox_sha256": self.outbox_sha256,
            "expected_count": self.expected_count,
            "inserted_count": self.inserted_count,
            "existing_count": self.existing_count,
            "fully_projected": self.fully_projected,
            "primary_ledger_tip": self.primary_ledger_tip,
            "secondary_ledger_tip": self.secondary_ledger_tip,
        }


@dataclass(frozen=True)
class DeliveryProjectionPlan:
    run_id: str
    artifact_version_id: str
    bundle_sha256: str
    outbox_sha256: str
    source_state: Mapping[str, object]
    record_rows: tuple[tuple[object, ...], ...]
    primary_ledger_tip: str
    secondary_ledger_tip: str


def serialize_delivery_projection_plan(plan: DeliveryProjectionPlan) -> bytes:
    if not isinstance(plan, DeliveryProjectionPlan):
        raise RuntimeError("delivery_projection_plan_invalid")
    value = {
        "schema_version": "delivery-projection-plan-v1",
        "run_id": plan.run_id,
        "artifact_version_id": plan.artifact_version_id,
        "bundle_sha256": plan.bundle_sha256,
        "outbox_sha256": plan.outbox_sha256,
        "source_state": dict(plan.source_state),
        "records": [
            dict(zip(_DELIVERY_RECORD_KEYS, row, strict=True))
            for row in plan.record_rows
        ],
        "primary_ledger_tip": plan.primary_ledger_tip,
        "secondary_ledger_tip": plan.secondary_ledger_tip,
    }
    return canonical_json_bytes(value)


def deserialize_delivery_projection_plan(payload: bytes) -> DeliveryProjectionPlan:
    if not isinstance(payload, bytes) or not payload or len(payload) > 256 * 1024:
        raise RuntimeError("delivery_projection_plan_invalid")
    value = _decode_json_object(payload, "delivery_projection_plan_invalid")
    if canonical_json_bytes(value) != payload or set(value) != {
        "schema_version",
        "run_id",
        "artifact_version_id",
        "bundle_sha256",
        "outbox_sha256",
        "source_state",
        "records",
        "primary_ledger_tip",
        "secondary_ledger_tip",
    }:
        raise RuntimeError("delivery_projection_plan_invalid")
    if value.get("schema_version") != "delivery-projection-plan-v1":
        raise RuntimeError("delivery_projection_plan_invalid")
    run_id = _require_safe_id(value.get("run_id"), "run_id")
    artifact_version_id = _require_safe_id(
        value.get("artifact_version_id"), "artifact_version_id"
    )
    bundle_sha256 = _require_sha(value.get("bundle_sha256"), "bundle_sha256")
    outbox_sha256 = _require_sha(value.get("outbox_sha256"), "outbox_sha256")
    source_state = validate_frozen_report_source_state(value.get("source_state"))
    primary_tip = _require_sha(
        value.get("primary_ledger_tip"), "primary_ledger_tip"
    )
    secondary_tip = _require_sha(
        value.get("secondary_ledger_tip"), "secondary_ledger_tip"
    )
    records_value = value.get("records")
    if not isinstance(records_value, list) or not records_value:
        raise RuntimeError("delivery_projection_plan_invalid")
    rows: list[tuple[object, ...]] = []
    identities: set[str] = set()
    hashes_by_destination: dict[str, list[str]] = {
        "dingtalk:primary": [],
        "dingtalk:secondary": [],
    }
    for record in records_value:
        if not isinstance(record, Mapping) or set(record) != set(
            _DELIVERY_RECORD_KEYS
        ):
            raise RuntimeError("delivery_projection_plan_invalid")
        delivery_id = record.get("delivery_id")
        channel = record.get("channel")
        message_hash = record.get("message_hash")
        artifact_paths = record.get("artifact_paths")
        if (
            not isinstance(delivery_id, str)
            or re.fullmatch(r"prepared_[0-9a-f]{64}", delivery_id) is None
            or delivery_id in identities
            or record.get("run_id") != run_id
            or channel not in hashes_by_destination
            or record.get("mode") != "live"
            or record.get("status") != "sent"
            or not isinstance(message_hash, str)
            or _HASH_LABEL.fullmatch(message_hash) is None
            or not isinstance(artifact_paths, str)
            or record.get("live_send") != 1
        ):
            raise RuntimeError("delivery_projection_plan_invalid")
        try:
            urls = json.loads(artifact_paths)
        except json.JSONDecodeError as exc:
            raise RuntimeError("delivery_projection_plan_invalid") from exc
        if (
            not isinstance(urls, list)
            or not urls
            or any(
                not isinstance(url, str)
                or not url.startswith(("http://", "https://"))
                for url in urls
            )
        ):
            raise RuntimeError("delivery_projection_plan_invalid")
        identities.add(delivery_id)
        hashes_by_destination[str(channel)].append(message_hash)
        rows.append(tuple(record[key] for key in _DELIVERY_RECORD_KEYS))
    if (
        sorted(hashes_by_destination["dingtalk:primary"])
        != sorted(hashes_by_destination["dingtalk:secondary"])
        or not hashes_by_destination["dingtalk:primary"]
    ):
        raise RuntimeError("delivery_projection_plan_invalid")
    return DeliveryProjectionPlan(
        run_id=run_id,
        artifact_version_id=artifact_version_id,
        bundle_sha256=bundle_sha256,
        outbox_sha256=outbox_sha256,
        source_state=dict(source_state),
        record_rows=tuple(rows),
        primary_ledger_tip=primary_tip,
        secondary_ledger_tip=secondary_tip,
    )


def load_current_report_source_state(
    *, database: Path, run_id: str
) -> Mapping[str, object]:
    _require_safe_id(run_id, "run_id")
    database = Path(database)
    try:
        metadata = database.lstat()
    except FileNotFoundError as exc:
        raise RuntimeError("delivery_database_missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError("delivery_database_not_regular")
    uri = database.resolve(strict=True).as_uri() + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        source_state = _load_report_source_state_from_connection(
            connection=connection, run_id=run_id
        )
        connection.rollback()
    except RuntimeError:
        raise
    except sqlite3.Error as exc:
        raise RuntimeError("delivery_database_schema_invalid") from exc
    finally:
        if "connection" in locals():
            connection.close()
    return source_state


def _load_report_source_state_from_connection(
    *, connection: sqlite3.Connection, run_id: str
) -> Mapping[str, object]:
    row = connection.execute(
        "SELECT status FROM runs WHERE run_id=?", (run_id,)
    ).fetchone()
    if row is None:
        raise RuntimeError("run_not_found")
    post_count = int(
        connection.execute(
            "SELECT COUNT(*) FROM reddit_threads WHERE run_id=?", (run_id,)
        ).fetchone()[0]
    )
    comment_count = int(
        connection.execute(
            "SELECT COUNT(*) FROM reddit_comments WHERE run_id=?", (run_id,)
        ).fetchone()[0]
    )
    return classify_report_source_state(
        status=row[0], post_count=post_count, comment_count=comment_count
    )


def load_same_run_delivery_records(
    *, database: Path, run_id: str, destination_id: str | None = None
) -> tuple[Mapping[str, object], ...]:
    _require_safe_id(run_id, "run_id")
    if destination_id is not None:
        _require_destination_id(destination_id)
    database = Path(database)
    try:
        metadata = database.lstat()
    except FileNotFoundError as exc:
        raise RuntimeError("delivery_database_missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError("delivery_database_not_regular")
    uri = database.resolve(strict=True).as_uri() + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(delivery_previews)").fetchall()
        }
        required = {
            "delivery_id",
            "run_id",
            "channel",
            "mode",
            "status",
            "message_hash",
            "artifact_paths",
            "live_send",
        }
        if not required.issubset(columns):
            raise RuntimeError("delivery_database_schema_invalid")
        if destination_id is None:
            rows = connection.execute(
                "SELECT delivery_id,run_id,channel,mode,status,message_hash,artifact_paths,live_send "
                "FROM delivery_previews WHERE run_id=? AND status='sent' ORDER BY delivery_id",
                (run_id,),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT delivery_id,run_id,channel,mode,status,message_hash,artifact_paths,live_send "
                "FROM delivery_previews WHERE run_id=? AND channel=? AND status='sent' "
                "ORDER BY delivery_id",
                (run_id, f"dingtalk:{destination_id}"),
            ).fetchall()
        connection.rollback()
    except RuntimeError:
        raise
    except sqlite3.Error as exc:
        raise RuntimeError("delivery_database_schema_invalid") from exc
    finally:
        if "connection" in locals():
            connection.close()
    records: list[Mapping[str, object]] = []
    seen: set[str] = set()
    for row in rows:
        value = dict(row)
        delivery_id = str(value["delivery_id"])
        if delivery_id in seen:
            raise RuntimeError("delivery_database_duplicate_id")
        seen.add(delivery_id)
        try:
            artifacts = json.loads(str(value["artifact_paths"]))
        except json.JSONDecodeError as exc:
            raise RuntimeError("delivery_database_record_invalid") from exc
        if not isinstance(artifacts, list) or any(not isinstance(item, str) for item in artifacts):
            raise RuntimeError("delivery_database_record_invalid")
        value["artifact_paths"] = artifacts
        value["live_send"] = bool(value["live_send"])
        records.append(value)
    return tuple(records)


def load_and_verify_delivery_ledger(
    path: Path, *, run_id: str, destination_id: str | None = None
) -> tuple[Mapping[str, object], ...]:
    _require_safe_id(run_id, "run_id")
    if destination_id is not None:
        _require_destination_id(destination_id)
    path = Path(path)
    if not path.exists():
        return ()
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError("delivery_ledger_invalid")
    if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise RuntimeError("delivery_ledger_metadata_invalid")
    payload = _read_regular_bytes(path)
    return _decode_delivery_ledger(
        payload, run_id=run_id, destination_id=destination_id
    )


def _decode_delivery_ledger(
    payload: bytes, *, run_id: str, destination_id: str | None = None
) -> tuple[Mapping[str, object], ...]:
    if not payload:
        return ()
    if not payload.endswith(b"\n"):
        raise RuntimeError("delivery_ledger_truncated")
    entries: list[Mapping[str, object]] = []
    previous = "0" * 64
    for sequence, raw_line in enumerate(payload.splitlines(), start=1):
        if not raw_line:
            raise RuntimeError("delivery_ledger_truncated")
        value = _decode_json_object(raw_line, "delivery_ledger_invalid")
        if canonical_json_bytes(value) != raw_line:
            raise RuntimeError("delivery_ledger_noncanonical")
        schema_version = value.get("schema_version")
        expected_keys = (
            _EVENT_V2_KEYS
            if schema_version == "delivery-event-v2"
            else _EVENT_V1_KEYS
        )
        if set(value) != expected_keys:
            raise RuntimeError("delivery_ledger_invalid")
        base = {key: value[key] for key in value if key != "entry_hash"}
        if (
            value.get("sequence") != sequence
            or value.get("previous_entry_hash") != previous
            or value.get("entry_hash") != sha256_hex(canonical_json_bytes(base))
            or value.get("run_id") != run_id
        ):
            raise RuntimeError("delivery_ledger_chain_invalid")
        event_keys = (
            _EVENT_V2_INPUT_KEYS
            if schema_version == "delivery-event-v2"
            else _EVENT_V1_INPUT_KEYS
        )
        _validate_event_input({key: value[key] for key in event_keys})
        if destination_id is None:
            if schema_version != "delivery-event-v1":
                raise RuntimeError("delivery_ledger_destination_invalid")
        elif (
            schema_version != "delivery-event-v2"
            or value.get("destination_id") != destination_id
        ):
            raise RuntimeError("delivery_ledger_destination_invalid")
        entries.append(value)
        previous = str(value["entry_hash"])
    return tuple(entries)


def append_delivery_event(
    path: Path, *, event: Mapping[str, object]
) -> Mapping[str, object]:
    _validate_event_input(event)
    run_id = str(event["run_id"])
    path = Path(path)
    destination_id = event.get("destination_id")
    if destination_id is None:
        if path.name != "ledger.jsonl" or path.parent.name != run_id:
            raise RuntimeError("delivery_ledger_path_mismatch")
        _ensure_ledger_directories(path.parent)
    else:
        _require_destination_id(destination_id)
        if (
            path.name != "ledger.jsonl"
            or path.parent.name != destination_id
            or path.parent.parent.name != "destinations"
            or path.parent.parent.parent.name != run_id
        ):
            raise RuntimeError("delivery_ledger_path_mismatch")
        _ensure_destination_ledger_directories(path.parent)
    flags = os.O_RDWR | os.O_APPEND | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        metadata = os.fstat(descriptor)
        path_metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(path_metadata.st_mode)
            or not stat.S_ISREG(path_metadata.st_mode)
            or metadata.st_dev != path_metadata.st_dev
            or metadata.st_ino != path_metadata.st_ino
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise RuntimeError("delivery_ledger_metadata_invalid")
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > 16 * 1024 * 1024:
                raise RuntimeError("delivery_ledger_too_large")
            chunks.append(chunk)
        entries = _decode_delivery_ledger(
            b"".join(chunks),
            run_id=run_id,
            destination_id=(str(destination_id) if destination_id else None),
        )
        base = {
            **event,
            "sequence": len(entries) + 1,
            "previous_entry_hash": entries[-1]["entry_hash"] if entries else "0" * 64,
        }
        entry = {**base, "entry_hash": sha256_hex(canonical_json_bytes(base))}
        line = canonical_json_bytes(entry) + b"\n"
        os.lseek(descriptor, 0, os.SEEK_END)
        _write_all(descriptor, line)
        os.fsync(descriptor)
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)
    _fsync_directory(path.parent)
    return entry


def evaluate_duplicate_guard(
    *,
    ledger_entries: Sequence[Mapping[str, object]],
    db_records: Sequence[Mapping[str, object]],
    expected_outbox_sha256: str,
    authorize_resend: bool,
    requested_part_indexes: Sequence[int],
) -> DeliveryDecision:
    _require_sha(expected_outbox_sha256, "outbox_sha256")
    requested = tuple(requested_part_indexes)
    if any(isinstance(index, bool) or not isinstance(index, int) or index < 1 for index in requested):
        return DeliveryDecision((), "resend_part_index_invalid")
    if len(requested) != len(set(requested)):
        return DeliveryDecision((), "resend_part_index_duplicate")
    report_entries = [
        entry for entry in ledger_entries if entry.get("part_kind") == "report"
    ]
    if any(entry.get("status") == "unknown_delivery_state" for entry in ledger_entries):
        return DeliveryDecision((), "unknown_delivery_state")
    terminal_keys = {
        (entry.get("part_kind"), entry.get("part_index"))
        for entry in ledger_entries
        if entry.get("status") in {"sent", "rejected", "unknown_delivery_state"}
    }
    if any(
        entry.get("status") == "attempting"
        and (entry.get("part_kind"), entry.get("part_index")) not in terminal_keys
        for entry in ledger_entries
    ):
        return DeliveryDecision((), "unknown_delivery_state")
    sent_entries = [entry for entry in ledger_entries if entry.get("status") == "sent"]
    sent_current = [
        entry
        for entry in report_entries
        if entry.get("status") == "sent"
        and entry.get("outbox_sha256") == expected_outbox_sha256
    ]
    sent_current_indexes = {int(entry["part_index"]) for entry in sent_current}
    rejected = {
        int(entry["part_index"])
        for entry in report_entries
        if entry.get("status") == "rejected"
        and entry.get("outbox_sha256") == expected_outbox_sha256
    } - sent_current_indexes
    if authorize_resend or requested:
        if not authorize_resend:
            return DeliveryDecision((), "resend_not_authorized")
        if not rejected:
            return DeliveryDecision((), "resend_without_rejected_history")
        if not requested or set(requested) != rejected:
            return DeliveryDecision((), "resend_part_set_mismatch")
        if any(
            entry.get("part_kind") != "report"
            or entry.get("outbox_sha256") != expected_outbox_sha256
            for entry in sent_entries
        ):
            return DeliveryDecision((), "same_run_live_history")
        if len(sent_current_indexes) != len(sent_current):
            return DeliveryDecision((), "same_run_live_history")
        expected_db_hashes = sorted(
            "sha256:" + str(entry.get("part_sha256")) for entry in sent_current
        )
        actual_db_hashes = sorted(str(record.get("message_hash")) for record in db_records)
        if expected_db_hashes != actual_db_hashes:
            return DeliveryDecision((), "same_run_db_mismatch")
        return DeliveryDecision(tuple(sorted(requested)), None)
    if db_records:
        return DeliveryDecision((), "same_run_db_success")
    if sent_entries:
        return DeliveryDecision((), "same_run_live_history")
    if rejected:
        if not authorize_resend:
            return DeliveryDecision((), "resend_authorization_required")
    return DeliveryDecision((), None)


def send_prepared_daily_report(
    *,
    database: Path,
    run_id: str,
    expected_artifact_version_id: str,
    expected_bundle_sha256: str,
    expected_outbox_sha256: str,
    authorization_id: str,
    roots: PreparedReportRoots,
    config_root: Path,
    webhook_url: str,
    webhook_secret: str | None,
    webhook_url_2: str = "",
    webhook_secret_2: str | None = None,
    timeout_seconds: int,
    authorize_live_send: bool,
    authorize_resend: bool = False,
    resend_part_indexes: tuple[int, ...] = (),
    head_checker: ArtifactHeadChecker,
    transport: DingTalkByteTransport,
    credential_loader: Callable[[], tuple[str, str | None]] | None = None,
) -> DeliverySummary:
    _require_safe_id(run_id, "run_id")
    _require_safe_id(authorization_id, "authorization_id")
    _require_sha(expected_bundle_sha256, "bundle_sha256")
    _require_sha(expected_outbox_sha256, "outbox_sha256")
    if not authorize_live_send:
        return _empty_summary(
            run_id=run_id,
            artifact_version_id=expected_artifact_version_id,
            outbox_sha256=expected_outbox_sha256,
            status="live_send_not_authorized",
        )
    if isinstance(timeout_seconds, bool) or not 1 <= timeout_seconds <= 60:
        raise ValueError("timeout_seconds_invalid")

    current = _load_current(roots.state_root)
    expected_current = {
        "run_id": run_id,
        "artifact_version_id": expected_artifact_version_id,
        "bundle_sha256": expected_bundle_sha256,
        "outbox_sha256": expected_outbox_sha256,
    }
    if any(current.get(key) != value for key, value in expected_current.items()):
        return _empty_summary(
            run_id=run_id,
            artifact_version_id=expected_artifact_version_id,
            outbox_sha256=expected_outbox_sha256,
            status="prepared_current_mismatch",
        )
    schema_assets = load_report_schema_assets(config_root=Path(config_root))
    verified = load_verified_prepared_report(
        roots=roots,
        expected_run_id=run_id,
        expected_artifact_version_id=expected_artifact_version_id,
        expected_bundle_sha256=expected_bundle_sha256,
        expected_outbox_sha256=expected_outbox_sha256,
        schema_assets=schema_assets,
    )
    if verified.translation_status != "complete":
        return _empty_summary(
            run_id=run_id,
            artifact_version_id=expected_artifact_version_id,
            outbox_sha256=expected_outbox_sha256,
            status="translation_not_complete",
        )

    try:
        current_source_state = load_current_report_source_state(
            database=Path(database), run_id=run_id
        )
    except RuntimeError:
        return _empty_summary(
            run_id=run_id,
            artifact_version_id=expected_artifact_version_id,
            outbox_sha256=expected_outbox_sha256,
            status="source_state_not_sendable",
        )
    if dict(current_source_state) != dict(verified.source_state):
        return _empty_summary(
            run_id=run_id,
            artifact_version_id=expected_artifact_version_id,
            outbox_sha256=expected_outbox_sha256,
            status="source_state_changed_after_prepare",
        )

    db_records = load_same_run_delivery_records(database=Path(database), run_id=run_id)
    ledger_path = _ledger_path(roots, run_id)
    ledger_before = load_and_verify_delivery_ledger(ledger_path, run_id=run_id)
    decision = evaluate_duplicate_guard(
        ledger_entries=ledger_before,
        db_records=db_records,
        expected_outbox_sha256=expected_outbox_sha256,
        authorize_resend=authorize_resend,
        requested_part_indexes=resend_part_indexes,
    )
    if decision.blocked_reason is not None:
        report_live, alert_live = _live_evidence(ledger_before)
        return DeliverySummary(
            run_id=run_id,
            artifact_version_id=expected_artifact_version_id,
            outbox_sha256=expected_outbox_sha256,
            attempted_part_indexes=(),
            sent_part_indexes=(),
            rejected_part_indexes=(),
            ledger_tip_before=_ledger_tip(ledger_before),
            ledger_tip_after=_ledger_tip(ledger_before),
            status="blocked_duplicate",
            report_live_send=report_live,
            alert_live_send=alert_live,
            live_send=report_live or alert_live,
        )
    selected_indexes = decision.sendable_part_indexes or tuple(
        part.index for part in verified.parts
    )
    part_by_index = {part.index: part for part in verified.parts}
    if any(index not in part_by_index for index in selected_indexes):
        raise RuntimeError("delivery_part_index_invalid")
    for url in verified.public_artifact_urls:
        status = head_checker(url, timeout_seconds=timeout_seconds)
        if isinstance(status, bool) or status != 200:
            return _empty_summary(
                run_id=run_id,
                artifact_version_id=expected_artifact_version_id,
                outbox_sha256=expected_outbox_sha256,
                status="artifact_preflight_blocked",
                ledger_tip=_ledger_tip(ledger_before),
            )

    if credential_loader is not None:
        if webhook_url or webhook_secret is not None:
            raise RuntimeError("dingtalk_credential_source_ambiguous")
        loaded_credentials = credential_loader()
        if (
            not isinstance(loaded_credentials, tuple)
            or len(loaded_credentials) != 2
            or not isinstance(loaded_credentials[0], str)
            or (
                loaded_credentials[1] is not None
                and not isinstance(loaded_credentials[1], str)
            )
        ):
            raise RuntimeError("dingtalk_credentials_invalid")
        webhook_url, webhook_secret = loaded_credentials
    if not webhook_url:
        return _empty_summary(
            run_id=run_id,
            artifact_version_id=expected_artifact_version_id,
            outbox_sha256=expected_outbox_sha256,
            status="dingtalk_webhook_missing",
            ledger_tip=_ledger_tip(ledger_before),
        )
    if webhook_url_2:
        return _empty_summary(
            run_id=run_id,
            artifact_version_id=expected_artifact_version_id,
            outbox_sha256=expected_outbox_sha256,
            status="secondary_webhook_not_supported",
            ledger_tip=_ledger_tip(ledger_before),
        )

    attempted: list[int] = []
    sent: list[int] = []
    rejected: list[int] = []
    terminal_status = "sent"
    for index in selected_indexes:
        part = part_by_index[index]
        outcome = deliver_one_frozen_part(
            ledger_path=ledger_path,
            run_id=run_id,
            artifact_version_id=expected_artifact_version_id,
            bundle_sha256=expected_bundle_sha256,
            outbox_sha256=expected_outbox_sha256,
            part_kind="report",
            part=part,
            authorization_id=authorization_id,
            attempt_id=None,
            webhook_url=webhook_url,
            webhook_secret=webhook_secret,
            timeout_seconds=timeout_seconds,
            transport=transport,
        )
        if outcome["attempted"]:
            attempted.append(index)
        status = str(outcome["status"])
        if status == "sent":
            sent.append(index)
            try:
                _insert_delivery_record(
                    database=Path(database),
                    run_id=run_id,
                    artifact_version_id=expected_artifact_version_id,
                    outbox_sha256=expected_outbox_sha256,
                    authorization_id=authorization_id,
                    part=part,
                    artifact_urls=verified.public_artifact_urls,
                    external_attempt_made=bool(outcome["external_attempt_made"]),
                )
            except RuntimeError as exc:
                ledger_after = load_and_verify_delivery_ledger(
                    ledger_path, run_id=run_id
                )
                report_live, alert_live = _live_evidence(ledger_after)
                reason = str(exc)
                if re.fullmatch(r"[a-z][a-z0-9_]{0,127}", reason) is None:
                    reason = "delivery_database_write_failed"
                return DeliverySummary(
                    run_id=run_id,
                    artifact_version_id=expected_artifact_version_id,
                    outbox_sha256=expected_outbox_sha256,
                    attempted_part_indexes=tuple(attempted),
                    sent_part_indexes=tuple(sent),
                    rejected_part_indexes=tuple(rejected),
                    ledger_tip_before=_ledger_tip(ledger_before),
                    ledger_tip_after=_ledger_tip(ledger_after),
                    status=reason,
                    report_live_send=report_live,
                    alert_live_send=alert_live,
                    live_send=report_live or alert_live,
                )
        elif status == "rejected":
            rejected.append(index)
            terminal_status = "rejected"
        elif status == "local_pre_request_blocked":
            terminal_status = status
            break
        else:
            terminal_status = "unknown_delivery_state"
            break
    ledger_after = load_and_verify_delivery_ledger(ledger_path, run_id=run_id)
    report_live, alert_live = _live_evidence(ledger_after)
    return DeliverySummary(
        run_id=run_id,
        artifact_version_id=expected_artifact_version_id,
        outbox_sha256=expected_outbox_sha256,
        attempted_part_indexes=tuple(attempted),
        sent_part_indexes=tuple(sent),
        rejected_part_indexes=tuple(rejected),
        ledger_tip_before=_ledger_tip(ledger_before),
        ledger_tip_after=_ledger_tip(ledger_after),
        status=terminal_status,
        report_live_send=report_live,
        alert_live_send=alert_live,
        live_send=report_live or alert_live,
    )


def send_prepared_daily_report_to_destinations(
    *,
    database: Path,
    run_id: str,
    expected_artifact_version_id: str,
    expected_bundle_sha256: str,
    expected_outbox_sha256: str,
    authorization_id: str,
    roots: PreparedReportRoots,
    config_root: Path,
    timeout_seconds: int,
    authorize_live_send: bool,
    head_checker: ArtifactHeadChecker,
    transport: DingTalkByteTransport,
    destination_credentials: Sequence[DingTalkDestinationCredential] = (),
    credential_loader: Callable[
        [], Sequence[DingTalkDestinationCredential]
    ]
    | None = None,
    destination_completion_sink: Callable[
        [DestinationDeliverySummary], None
    ]
    | None = None,
    defer_database_projection: bool = False,
    authorize_resend: bool = False,
    resend_part_indexes: tuple[int, ...] = (),
) -> MultiDestinationDeliverySummary:
    """Deliver one verified prepared outbox to exactly two isolated destinations."""
    _require_safe_id(run_id, "run_id")
    _require_safe_id(authorization_id, "authorization_id")
    _require_sha(expected_bundle_sha256, "bundle_sha256")
    _require_sha(expected_outbox_sha256, "outbox_sha256")
    if not authorize_live_send:
        return _empty_multi_summary(
            run_id=run_id,
            artifact_version_id=expected_artifact_version_id,
            outbox_sha256=expected_outbox_sha256,
            status="live_send_not_authorized",
        )
    if isinstance(timeout_seconds, bool) or not 1 <= timeout_seconds <= 60:
        raise ValueError("timeout_seconds_invalid")
    if destination_credentials and credential_loader is not None:
        raise RuntimeError("dingtalk_credential_source_ambiguous")

    current = _load_current(roots.state_root)
    expected_current = {
        "run_id": run_id,
        "artifact_version_id": expected_artifact_version_id,
        "bundle_sha256": expected_bundle_sha256,
        "outbox_sha256": expected_outbox_sha256,
    }
    if any(current.get(key) != value for key, value in expected_current.items()):
        return _empty_multi_summary(
            run_id=run_id,
            artifact_version_id=expected_artifact_version_id,
            outbox_sha256=expected_outbox_sha256,
            status="prepared_current_mismatch",
        )
    schema_assets = load_report_schema_assets(config_root=Path(config_root))
    verified = load_verified_prepared_report(
        roots=roots,
        expected_run_id=run_id,
        expected_artifact_version_id=expected_artifact_version_id,
        expected_bundle_sha256=expected_bundle_sha256,
        expected_outbox_sha256=expected_outbox_sha256,
        schema_assets=schema_assets,
    )
    if verified.translation_status != "complete":
        return _empty_multi_summary(
            run_id=run_id,
            artifact_version_id=expected_artifact_version_id,
            outbox_sha256=expected_outbox_sha256,
            status="translation_not_complete",
        )
    try:
        current_source_state = load_current_report_source_state(
            database=Path(database), run_id=run_id
        )
    except RuntimeError:
        return _empty_multi_summary(
            run_id=run_id,
            artifact_version_id=expected_artifact_version_id,
            outbox_sha256=expected_outbox_sha256,
            status="source_state_not_sendable",
        )
    if dict(current_source_state) != dict(verified.source_state):
        return _empty_multi_summary(
            run_id=run_id,
            artifact_version_id=expected_artifact_version_id,
            outbox_sha256=expected_outbox_sha256,
            status="source_state_changed_after_prepare",
        )
    for url in verified.public_artifact_urls:
        status = head_checker(url, timeout_seconds=timeout_seconds)
        if isinstance(status, bool) or status != 200:
            return _empty_multi_summary(
                run_id=run_id,
                artifact_version_id=expected_artifact_version_id,
                outbox_sha256=expected_outbox_sha256,
                status="artifact_preflight_blocked",
            )

    loaded = tuple(
        credential_loader() if credential_loader is not None else destination_credentials
    )
    credentials = _validate_destination_credentials(loaded)
    summary_items: list[DestinationDeliverySummary] = []
    for credential in credentials:
        destination_summary = _send_verified_destination(
            database=Path(database),
            run_id=run_id,
            expected_artifact_version_id=expected_artifact_version_id,
            expected_bundle_sha256=expected_bundle_sha256,
            expected_outbox_sha256=expected_outbox_sha256,
            authorization_id=authorization_id,
            roots=roots,
            verified=verified,
            credential=credential,
            timeout_seconds=timeout_seconds,
            authorize_resend=authorize_resend,
            resend_part_indexes=resend_part_indexes,
            defer_database_projection=defer_database_projection,
            transport=transport,
        )
        summary_items.append(destination_summary)
        if destination_completion_sink is not None:
            destination_completion_sink(destination_summary)
    summaries = tuple(summary_items)
    aggregate_status = _aggregate_destination_status(summaries)
    report_live = any(item.report_live_send for item in summaries)
    return MultiDestinationDeliverySummary(
        run_id=run_id,
        artifact_version_id=expected_artifact_version_id,
        outbox_sha256=expected_outbox_sha256,
        destinations=summaries,
        status=aggregate_status,
        report_live_send=report_live,
        alert_live_send=False,
        live_send=report_live,
    )


def build_delivery_projection_plan_from_ledgers(
    *,
    run_id: str,
    expected_artifact_version_id: str,
    expected_bundle_sha256: str,
    expected_outbox_sha256: str,
    authorization_id: str,
    roots: PreparedReportRoots,
    config_root: Path,
    require_external_attempts: bool = True,
) -> DeliveryProjectionPlan:
    """Validate one fully-sent dual outbox and freeze its database projection."""
    _require_safe_id(run_id, "run_id")
    _require_safe_id(authorization_id, "authorization_id")
    _require_sha(expected_bundle_sha256, "bundle_sha256")
    _require_sha(expected_outbox_sha256, "outbox_sha256")
    current = _load_current(roots.state_root)
    expected_current = {
        "run_id": run_id,
        "artifact_version_id": expected_artifact_version_id,
        "bundle_sha256": expected_bundle_sha256,
        "outbox_sha256": expected_outbox_sha256,
    }
    if any(current.get(key) != value for key, value in expected_current.items()):
        raise RuntimeError("delivery_projection_prepared_current_mismatch")
    verified = load_verified_prepared_report(
        roots=roots,
        expected_run_id=run_id,
        expected_artifact_version_id=expected_artifact_version_id,
        expected_bundle_sha256=expected_bundle_sha256,
        expected_outbox_sha256=expected_outbox_sha256,
        schema_assets=load_report_schema_assets(config_root=Path(config_root)),
    )
    if verified.translation_status != "complete":
        raise RuntimeError("delivery_projection_translation_not_complete")

    parts = tuple(verified.parts)
    part_by_index = {part.index: part for part in parts}
    expected_indexes = set(part_by_index)
    records: list[Mapping[str, object]] = []
    ledger_tips: list[str] = []
    for destination_id in _DESTINATION_IDS:
        ledger = load_and_verify_delivery_ledger(
            _destination_ledger_path(roots, run_id, destination_id),
            run_id=run_id,
            destination_id=destination_id,
        )
        report_entries = [
            entry for entry in ledger if entry.get("part_kind") == "report"
        ]
        if not report_entries:
            raise RuntimeError("delivery_projection_ledger_incomplete")
        ledger_tips.append(str(ledger[-1]["entry_hash"]))
        if any(
            entry.get("artifact_version_id") != expected_artifact_version_id
            or entry.get("bundle_sha256") != expected_bundle_sha256
            or entry.get("outbox_sha256") != expected_outbox_sha256
            or entry.get("authorization_id") != authorization_id
            for entry in report_entries
        ):
            raise RuntimeError("delivery_projection_ledger_identity_mismatch")
        if any(
            entry.get("status") in {"rejected", "unknown_delivery_state"}
            for entry in report_entries
        ):
            raise RuntimeError("delivery_projection_ledger_not_sent")
        sent_entries = [
            entry for entry in report_entries if entry.get("status") == "sent"
        ]
        sent_indexes = {int(entry["part_index"]) for entry in sent_entries}
        if sent_indexes != expected_indexes or len(sent_entries) != len(parts):
            raise RuntimeError("delivery_projection_ledger_incomplete")
        terminal_indexes = {
            int(entry["part_index"])
            for entry in report_entries
            if entry.get("status") == "sent"
        }
        if any(
            entry.get("status") == "attempting"
            and int(entry["part_index"]) not in terminal_indexes
            for entry in report_entries
        ):
            raise RuntimeError("delivery_projection_ledger_incomplete")
        for entry in sorted(sent_entries, key=lambda item: int(item["part_index"])):
            part = part_by_index[int(entry["part_index"])]
            if entry.get("part_sha256") != part.sha256:
                raise RuntimeError("delivery_projection_part_mismatch")
            if require_external_attempts and (
                entry.get("external_attempt_made") is not True
                or entry.get("http_status") != 200
            ):
                raise RuntimeError(
                    "delivery_projection_external_evidence_required"
                )
            records.append(
                _delivery_record(
                    run_id=run_id,
                    artifact_version_id=expected_artifact_version_id,
                    outbox_sha256=expected_outbox_sha256,
                    authorization_id=authorization_id,
                    part=part,
                    artifact_urls=verified.public_artifact_urls,
                    external_attempt_made=bool(entry["external_attempt_made"]),
                    destination_id=destination_id,
                )
            )
    return DeliveryProjectionPlan(
        run_id=run_id,
        artifact_version_id=expected_artifact_version_id,
        bundle_sha256=expected_bundle_sha256,
        outbox_sha256=expected_outbox_sha256,
        source_state=dict(verified.source_state),
        record_rows=tuple(
            tuple(record[key] for key in _DELIVERY_RECORD_KEYS)
            for record in records
        ),
        primary_ledger_tip=ledger_tips[0],
        secondary_ledger_tip=ledger_tips[1],
    )


def apply_delivery_projection_plan(
    *, database: Path, plan: DeliveryProjectionPlan
) -> DeliveryProjectionSummary:
    """Apply one trusted in-process projection plan in a single transaction."""
    if not isinstance(plan, DeliveryProjectionPlan):
        raise RuntimeError("delivery_projection_plan_invalid")
    database = Path(database)
    try:
        metadata = database.lstat()
    except FileNotFoundError as exc:
        raise RuntimeError("delivery_database_missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError("delivery_database_not_regular")
    expected_records = tuple(
        dict(zip(_DELIVERY_RECORD_KEYS, row, strict=True))
        for row in plan.record_rows
    )
    expected_by_id = {
        str(record["delivery_id"]): record for record in expected_records
    }
    if len(expected_by_id) != len(expected_records) or not expected_records:
        raise RuntimeError("delivery_projection_plan_invalid")
    inserted_count = 0
    existing_count = 0
    try:
        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN IMMEDIATE")
        if dict(
            _load_report_source_state_from_connection(
                connection=connection, run_id=plan.run_id
            )
        ) != dict(plan.source_state):
            raise RuntimeError("delivery_projection_source_state_changed")
        columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(delivery_previews)"
            ).fetchall()
        }
        required = {
            "delivery_id",
            "run_id",
            "channel",
            "mode",
            "status",
            "message_hash",
            "artifact_paths",
            "live_send",
        }
        if not required.issubset(columns):
            raise RuntimeError("delivery_database_schema_invalid")
        existing_rows = connection.execute(
            "SELECT delivery_id,run_id,channel,mode,status,message_hash,artifact_paths,live_send "
            "FROM delivery_previews WHERE run_id=? AND channel IN (?,?) "
            "ORDER BY delivery_id",
            (plan.run_id, "dingtalk:primary", "dingtalk:secondary"),
        ).fetchall()
        seen_existing: set[str] = set()
        for row in existing_rows:
            actual = dict(row)
            delivery_id = str(actual["delivery_id"])
            expected = expected_by_id.get(delivery_id)
            if expected is None or actual != dict(expected):
                raise RuntimeError("delivery_database_projection_conflict")
            if delivery_id in seen_existing:
                raise RuntimeError("delivery_database_duplicate_id")
            seen_existing.add(delivery_id)
            existing_count += 1
        for delivery_id in sorted(set(expected_by_id) - seen_existing):
            record = expected_by_id[delivery_id]
            connection.execute(
                "INSERT INTO delivery_previews("
                "delivery_id,run_id,channel,mode,status,message_hash,artifact_paths,live_send"
                ") VALUES(?,?,?,?,?,?,?,?)",
                tuple(record[key] for key in _DELIVERY_RECORD_KEYS),
            )
            inserted_count += 1
        projected_rows = connection.execute(
            "SELECT delivery_id,run_id,channel,mode,status,message_hash,artifact_paths,live_send "
            "FROM delivery_previews WHERE run_id=? AND channel IN (?,?) "
            "ORDER BY delivery_id",
            (plan.run_id, "dingtalk:primary", "dingtalk:secondary"),
        ).fetchall()
        if {
            str(row["delivery_id"]): dict(row) for row in projected_rows
        } != expected_by_id:
            raise RuntimeError("delivery_database_projection_postflight_failed")
        connection.commit()
    except RuntimeError:
        if "connection" in locals():
            connection.rollback()
        raise
    except sqlite3.Error as exc:
        if "connection" in locals():
            connection.rollback()
        raise RuntimeError("delivery_database_write_failed") from exc
    finally:
        if "connection" in locals():
            connection.close()
    return DeliveryProjectionSummary(
        run_id=plan.run_id,
        artifact_version_id=plan.artifact_version_id,
        outbox_sha256=plan.outbox_sha256,
        expected_count=len(expected_records),
        inserted_count=inserted_count,
        existing_count=existing_count,
        fully_projected=True,
        primary_ledger_tip=plan.primary_ledger_tip,
        secondary_ledger_tip=plan.secondary_ledger_tip,
    )


def project_sent_delivery_records_from_ledgers(
    *,
    database: Path,
    run_id: str,
    expected_artifact_version_id: str,
    expected_bundle_sha256: str,
    expected_outbox_sha256: str,
    authorization_id: str,
    roots: PreparedReportRoots,
    config_root: Path,
    require_external_attempts: bool = True,
) -> DeliveryProjectionSummary:
    """Validate ledgers and atomically project their sent rows into SQLite."""
    plan = build_delivery_projection_plan_from_ledgers(
        run_id=run_id,
        expected_artifact_version_id=expected_artifact_version_id,
        expected_bundle_sha256=expected_bundle_sha256,
        expected_outbox_sha256=expected_outbox_sha256,
        authorization_id=authorization_id,
        roots=roots,
        config_root=config_root,
        require_external_attempts=require_external_attempts,
    )
    return apply_delivery_projection_plan(database=database, plan=plan)


def _send_verified_destination(
    *,
    database: Path,
    run_id: str,
    expected_artifact_version_id: str,
    expected_bundle_sha256: str,
    expected_outbox_sha256: str,
    authorization_id: str,
    roots: PreparedReportRoots,
    verified: object,
    credential: DingTalkDestinationCredential,
    timeout_seconds: int,
    authorize_resend: bool,
    resend_part_indexes: tuple[int, ...],
    defer_database_projection: bool,
    transport: DingTalkByteTransport,
) -> DestinationDeliverySummary:
    destination_id = _require_destination_id(credential.destination_id)
    ledger_path = _destination_ledger_path(roots, run_id, destination_id)
    with _destination_delivery_lock(ledger_path.parent, run_id, destination_id):
        ledger_before = load_and_verify_delivery_ledger(
            ledger_path, run_id=run_id, destination_id=destination_id
        )
        db_records = load_same_run_delivery_records(
            database=database,
            run_id=run_id,
            destination_id=destination_id,
        )
        parts = tuple(getattr(verified, "parts"))
        if _destination_delivery_complete(
            ledger_entries=ledger_before,
            db_records=db_records,
            expected_outbox_sha256=expected_outbox_sha256,
            parts=parts,
        ):
            return _destination_summary(
                destination_id=destination_id,
                status="already_sent",
                ledger_before=ledger_before,
                ledger_after=ledger_before,
            )
        decision = evaluate_duplicate_guard(
            ledger_entries=ledger_before,
            db_records=db_records,
            expected_outbox_sha256=expected_outbox_sha256,
            authorize_resend=authorize_resend,
            requested_part_indexes=resend_part_indexes,
        )
        if decision.blocked_reason is not None:
            status = (
                "unknown_delivery_state"
                if decision.blocked_reason == "unknown_delivery_state"
                else "blocked_duplicate"
            )
            return _destination_summary(
                destination_id=destination_id,
                status=status,
                ledger_before=ledger_before,
                ledger_after=ledger_before,
            )
        selected_indexes = decision.sendable_part_indexes or tuple(
            part.index for part in parts
        )
        part_by_index = {part.index: part for part in parts}
        if any(index not in part_by_index for index in selected_indexes):
            raise RuntimeError("delivery_part_index_invalid")

        attempted: list[int] = []
        sent: list[int] = []
        rejected: list[int] = []
        terminal_status = "sent"
        for index in selected_indexes:
            part = part_by_index[index]
            outcome = deliver_one_frozen_part(
                ledger_path=ledger_path,
                run_id=run_id,
                artifact_version_id=expected_artifact_version_id,
                bundle_sha256=expected_bundle_sha256,
                outbox_sha256=expected_outbox_sha256,
                part_kind="report",
                part=part,
                authorization_id=authorization_id,
                attempt_id=None,
                destination_id=destination_id,
                webhook_url=credential.webhook_url,
                webhook_secret=credential.webhook_secret,
                timeout_seconds=timeout_seconds,
                transport=transport,
            )
            if outcome["attempted"]:
                attempted.append(index)
            status = str(outcome["status"])
            if status == "sent":
                sent.append(index)
                if not defer_database_projection:
                    try:
                        _insert_delivery_record(
                            database=database,
                            run_id=run_id,
                            artifact_version_id=expected_artifact_version_id,
                            outbox_sha256=expected_outbox_sha256,
                            authorization_id=authorization_id,
                            part=part,
                            artifact_urls=getattr(verified, "public_artifact_urls"),
                            external_attempt_made=bool(
                                outcome["external_attempt_made"]
                            ),
                            destination_id=destination_id,
                        )
                    except RuntimeError as exc:
                        ledger_after = load_and_verify_delivery_ledger(
                            ledger_path,
                            run_id=run_id,
                            destination_id=destination_id,
                        )
                        reason = str(exc)
                        if re.fullmatch(r"[a-z][a-z0-9_]{0,127}", reason) is None:
                            reason = "delivery_database_write_failed"
                        return _destination_summary(
                            destination_id=destination_id,
                            status=reason,
                            ledger_before=ledger_before,
                            ledger_after=ledger_after,
                            attempted=attempted,
                            sent=sent,
                            rejected=rejected,
                        )
            elif status == "rejected":
                rejected.append(index)
                terminal_status = "rejected"
            elif status == "local_pre_request_blocked":
                terminal_status = status
                break
            else:
                terminal_status = "unknown_delivery_state"
                break
        ledger_after = load_and_verify_delivery_ledger(
            ledger_path, run_id=run_id, destination_id=destination_id
        )
        return _destination_summary(
            destination_id=destination_id,
            status=terminal_status,
            ledger_before=ledger_before,
            ledger_after=ledger_after,
            attempted=attempted,
            sent=sent,
            rejected=rejected,
        )


def send_report_failure_alert(
    *,
    roots: PreparedReportRoots,
    run_id: str,
    attempt_id: str,
    stage: str,
    reason_code: str,
    occurred_at: datetime,
    webhook_url: str,
    webhook_secret: str | None,
    timeout_seconds: int,
    authorize_failure_alert: bool,
    transport: DingTalkByteTransport,
) -> DeliverySummary:
    _require_safe_id(run_id, "run_id")
    _require_safe_id(attempt_id, "attempt_id")
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,127}", stage):
        raise ValueError("alert_stage_invalid")
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,127}", reason_code):
        raise ValueError("alert_reason_invalid")
    if not authorize_failure_alert:
        return _empty_summary(
            run_id=run_id,
            artifact_version_id=None,
            outbox_sha256=None,
            status="failure_alert_not_authorized",
        )
    blocked_path = roots.blocked_root / run_id / attempt_id / "blocked-manifest.json"
    if not blocked_path.is_file() or blocked_path.is_symlink():
        return _empty_summary(
            run_id=run_id,
            artifact_version_id=None,
            outbox_sha256=None,
            status="blocked_attempt_missing",
        )
    ledger_path = _ledger_path(roots, run_id)
    before = load_and_verify_delivery_ledger(ledger_path, run_id=run_id)
    if any(entry.get("status") in {"sent", "unknown_delivery_state"} for entry in before):
        report_live, alert_live = _live_evidence(before)
        return DeliverySummary(
            run_id=run_id,
            artifact_version_id=None,
            outbox_sha256=None,
            attempted_part_indexes=(),
            sent_part_indexes=(),
            rejected_part_indexes=(),
            ledger_tip_before=_ledger_tip(before),
            ledger_tip_after=_ledger_tip(before),
            status="blocked_duplicate",
            report_live_send=report_live,
            alert_live_send=alert_live,
            live_send=report_live or alert_live,
        )
    occurred = occurred_at.astimezone(timezone.utc).isoformat()
    body = {
        "msgtype": "markdown",
        "markdown": {
            "title": f"Reddit VOC report failure {run_id}",
            "text": "\n".join(
                [
                    "# Reddit VOC report failure",
                    f"run_id={run_id}",
                    f"stage={stage}",
                    f"reason_code={reason_code}",
                    f"occurred_at={occurred}",
                ]
            ),
        },
    }
    payload = canonical_json_bytes(body)
    part = PreparedOutboxPart(
        index=1,
        total=1,
        path=blocked_path,
        body_bytes=payload,
        sha256=sha256_hex(payload),
        byte_count=len(payload),
    )
    outcome = deliver_one_frozen_part(
        ledger_path=ledger_path,
        run_id=run_id,
        artifact_version_id=None,
        bundle_sha256=None,
        outbox_sha256=None,
        part_kind="failure_alert",
        part=part,
        authorization_id=f"failure-alert:{attempt_id}",
        attempt_id=attempt_id,
        webhook_url=webhook_url,
        webhook_secret=webhook_secret,
        timeout_seconds=timeout_seconds,
        transport=transport,
    )
    after = load_and_verify_delivery_ledger(ledger_path, run_id=run_id)
    report_live, alert_live = _live_evidence(after)
    status = str(outcome["status"])
    return DeliverySummary(
        run_id=run_id,
        artifact_version_id=None,
        outbox_sha256=None,
        attempted_part_indexes=(1,) if outcome["attempted"] else (),
        sent_part_indexes=(1,) if status == "sent" else (),
        rejected_part_indexes=(1,) if status == "rejected" else (),
        ledger_tip_before=_ledger_tip(before),
        ledger_tip_after=_ledger_tip(after),
        status=status,
        report_live_send=report_live,
        alert_live_send=alert_live,
        live_send=report_live or alert_live,
    )


def deliver_one_frozen_part(
    *,
    ledger_path: Path,
    run_id: str,
    artifact_version_id: str | None,
    bundle_sha256: str | None,
    outbox_sha256: str | None,
    part_kind: str,
    part: PreparedOutboxPart,
    authorization_id: str,
    attempt_id: str | None,
    webhook_url: str,
    webhook_secret: str | None,
    timeout_seconds: int,
    transport: DingTalkByteTransport,
    destination_id: str | None = None,
) -> Mapping[str, object]:
    kind = getattr(transport, "transport_kind", None)
    if kind not in {"synthetic", "external"}:
        raise RuntimeError("transport_kind_invalid")
    attempting_written = False

    def append_attempting(*, external: bool) -> None:
        nonlocal attempting_written
        if attempting_written:
            raise RuntimeError("delivery_attempting_duplicate")
        append_delivery_event(
            ledger_path,
            event=_event(
                run_id=run_id,
                artifact_version_id=artifact_version_id,
                bundle_sha256=bundle_sha256,
                outbox_sha256=outbox_sha256,
                part_kind=part_kind,
                part=part,
                authorization_id=authorization_id,
                attempt_id=attempt_id,
                destination_id=destination_id,
                status="attempting",
                external_attempt_made=external,
                http_status=None,
                response_hash=None,
            ),
        )
        attempting_written = True

    def append_terminal(*, event: Mapping[str, object], external: bool) -> None:
        try:
            append_delivery_event(ledger_path, event=event)
        except Exception as exc:
            raise DeliveryBoundaryError(
                "delivery_terminal_ledger_write_failed",
                external_attempt_made=external,
            ) from exc

    if kind == "synthetic":
        append_attempting(external=False)
        request_start_sink = None
    else:
        request_start_sink = lambda: append_attempting(external=True)
    try:
        result = transport(
            webhook_url=webhook_url,
            body_bytes=part.body_bytes,
            secret=webhook_secret,
            timeout_seconds=timeout_seconds,
            request_start_sink=request_start_sink,
        )
    except Exception as exc:
        external = bool(getattr(exc, "external_attempt_made", False)) or (
            kind == "external" and attempting_written
        )
        if external and not attempting_written:
            append_terminal(
                event=_event(
                    run_id=run_id,
                    artifact_version_id=artifact_version_id,
                    bundle_sha256=bundle_sha256,
                    outbox_sha256=outbox_sha256,
                    part_kind=part_kind,
                    part=part,
                    authorization_id=authorization_id,
                    attempt_id=attempt_id,
                    destination_id=destination_id,
                    status="unknown_delivery_state",
                    external_attempt_made=True,
                    http_status=None,
                    response_hash=None,
                ),
                external=True,
            )
            return {"status": "unknown_delivery_state", "attempted": True, "external_attempt_made": True}
        if attempting_written:
            append_terminal(
                event=_event(
                    run_id=run_id,
                    artifact_version_id=artifact_version_id,
                    bundle_sha256=bundle_sha256,
                    outbox_sha256=outbox_sha256,
                    part_kind=part_kind,
                    part=part,
                    authorization_id=authorization_id,
                    attempt_id=attempt_id,
                    destination_id=destination_id,
                    status="unknown_delivery_state",
                    external_attempt_made=external if kind == "external" else False,
                    http_status=None,
                    response_hash=None,
                ),
                external=external,
            )
            return {"status": "unknown_delivery_state", "attempted": True, "external_attempt_made": external}
        return {"status": "local_pre_request_blocked", "attempted": False, "external_attempt_made": False}

    result_external = bool(getattr(result, "external_attempt_made", False))
    if (kind == "external" and (not attempting_written or not result_external)) or (
        kind == "synthetic" and result_external
    ):
        if not attempting_written:
            append_terminal(
                event=_event(
                    run_id=run_id,
                    artifact_version_id=artifact_version_id,
                    bundle_sha256=bundle_sha256,
                    outbox_sha256=outbox_sha256,
                    part_kind=part_kind,
                    part=part,
                    authorization_id=authorization_id,
                    attempt_id=attempt_id,
                    destination_id=destination_id,
                    status="unknown_delivery_state",
                    external_attempt_made=result_external,
                    http_status=None,
                    response_hash=None,
                ),
                external=result_external,
            )
        else:
            append_terminal(
                event=_event(
                    run_id=run_id,
                    artifact_version_id=artifact_version_id,
                    bundle_sha256=bundle_sha256,
                    outbox_sha256=outbox_sha256,
                    part_kind=part_kind,
                    part=part,
                    authorization_id=authorization_id,
                    attempt_id=attempt_id,
                    destination_id=destination_id,
                    status="unknown_delivery_state",
                    external_attempt_made=kind == "external",
                    http_status=getattr(result, "http_status", None),
                    response_hash=getattr(result, "response_hash", None),
                ),
                external=kind == "external",
            )
        return {"status": "unknown_delivery_state", "attempted": True, "external_attempt_made": result_external}
    status = getattr(result, "status", None)
    if status not in {"sent", "rejected"}:
        status = "unknown_delivery_state"
    append_terminal(
        event=_event(
            run_id=run_id,
            artifact_version_id=artifact_version_id,
            bundle_sha256=bundle_sha256,
            outbox_sha256=outbox_sha256,
            part_kind=part_kind,
            part=part,
            authorization_id=authorization_id,
            attempt_id=attempt_id,
            destination_id=destination_id,
            status=status,
            external_attempt_made=result_external,
            http_status=getattr(result, "http_status", None),
            response_hash=getattr(result, "response_hash", None),
        ),
        external=result_external,
    )
    return {"status": status, "attempted": True, "external_attempt_made": result_external}


def _event(
    *,
    run_id: str,
    artifact_version_id: str | None,
    bundle_sha256: str | None,
    outbox_sha256: str | None,
    part_kind: str,
    part: PreparedOutboxPart,
    authorization_id: str,
    attempt_id: str | None,
    destination_id: str | None,
    status: str,
    external_attempt_made: bool,
    http_status: int | None,
    response_hash: str | None,
) -> Mapping[str, object]:
    event = {
        "schema_version": (
            "delivery-event-v2" if destination_id is not None else "delivery-event-v1"
        ),
        "run_id": run_id,
        "artifact_version_id": artifact_version_id,
        "bundle_sha256": bundle_sha256,
        "outbox_sha256": outbox_sha256,
        "part_kind": part_kind,
        "part_index": part.index,
        "part_sha256": part.sha256,
        "authorization_id": authorization_id,
        "attempt_id": attempt_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "external_attempt_made": external_attempt_made,
        "http_status": http_status,
        "response_hash": response_hash,
    }
    if destination_id is not None:
        event["destination_id"] = _require_destination_id(destination_id)
    return event


def _insert_delivery_record(
    *,
    database: Path,
    run_id: str,
    artifact_version_id: str,
    outbox_sha256: str,
    authorization_id: str,
    part: PreparedOutboxPart,
    artifact_urls: Sequence[str],
    external_attempt_made: bool,
    destination_id: str | None = None,
) -> None:
    record = _delivery_record(
        run_id=run_id,
        artifact_version_id=artifact_version_id,
        outbox_sha256=outbox_sha256,
        authorization_id=authorization_id,
        part=part,
        artifact_urls=artifact_urls,
        external_attempt_made=external_attempt_made,
        destination_id=destination_id,
    )
    try:
        connection = sqlite3.connect(database)
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO delivery_previews("
            "delivery_id,run_id,channel,mode,status,message_hash,artifact_paths,live_send"
            ") VALUES(?,?,?,?,?,?,?,?)",
            tuple(record[key] for key in _DELIVERY_RECORD_KEYS),
        )
        connection.commit()
    except sqlite3.IntegrityError as exc:
        if "connection" in locals():
            connection.rollback()
        raise RuntimeError("delivery_database_duplicate_id") from exc
    except sqlite3.Error as exc:
        if "connection" in locals():
            connection.rollback()
        raise RuntimeError("delivery_database_write_failed") from exc
    finally:
        if "connection" in locals():
            connection.close()


def _delivery_record(
    *,
    run_id: str,
    artifact_version_id: str,
    outbox_sha256: str,
    authorization_id: str,
    part: PreparedOutboxPart,
    artifact_urls: Sequence[str],
    external_attempt_made: bool,
    destination_id: str | None = None,
) -> Mapping[str, object]:
    if destination_id is not None:
        _require_destination_id(destination_id)
    identity = canonical_json_bytes(
        {
            "run_id": run_id,
            "artifact_version_id": artifact_version_id,
            "outbox_sha256": outbox_sha256,
            "authorization_id": authorization_id,
            "part_index": part.index,
            **(
                {"destination_id": destination_id}
                if destination_id is not None
                else {}
            ),
        }
    )
    delivery_id = "prepared_" + sha256_hex(identity)
    return {
        "delivery_id": delivery_id,
        "run_id": run_id,
        "channel": (
            f"dingtalk:{destination_id}"
            if destination_id is not None
            else "dingtalk"
        ),
        "mode": "live" if external_attempt_made else "synthetic",
        "status": "sent",
        "message_hash": "sha256:" + part.sha256,
        "artifact_paths": json.dumps(
            list(artifact_urls), ensure_ascii=False, sort_keys=True
        ),
        "live_send": int(external_attempt_made),
    }


def _load_current(state_root: Path) -> Mapping[str, object]:
    value = load_regular_json(
        trusted_root=state_root,
        path=state_root / "prepared-current.json",
    )
    keys = {
        "schema_version",
        "run_id",
        "artifact_version_id",
        "bundle_sha256",
        "report_input_fingerprint",
        "outbox_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != keys:
        raise RuntimeError("prepared_current_invalid")
    if value.get("schema_version") != "prepared-current-v1":
        raise RuntimeError("prepared_current_invalid")
    return value


def _validate_event_input(event: Mapping[str, object]) -> None:
    if not isinstance(event, Mapping):
        raise RuntimeError("delivery_event_invalid")
    schema_version = event.get("schema_version")
    expected_keys = (
        _EVENT_V2_INPUT_KEYS
        if schema_version == "delivery-event-v2"
        else _EVENT_V1_INPUT_KEYS
    )
    if set(event) != expected_keys or schema_version not in {
        "delivery-event-v1",
        "delivery-event-v2",
    }:
        raise RuntimeError("delivery_event_invalid")
    if schema_version == "delivery-event-v2":
        _require_destination_id(event.get("destination_id"))
    _require_safe_id(event.get("run_id"), "run_id")
    _require_safe_id(event.get("authorization_id"), "authorization_id")
    if event.get("attempt_id") is not None:
        _require_safe_id(event.get("attempt_id"), "attempt_id")
    if event.get("artifact_version_id") is not None and not isinstance(
        event.get("artifact_version_id"), str
    ):
        raise RuntimeError("delivery_event_invalid")
    for key in ("bundle_sha256", "outbox_sha256"):
        if event.get(key) is not None:
            _require_sha(event.get(key), key)
    _require_sha(event.get("part_sha256"), "part_sha256")
    if event.get("part_kind") not in {"report", "failure_alert"}:
        raise RuntimeError("delivery_event_invalid")
    part_index = event.get("part_index")
    if isinstance(part_index, bool) or not isinstance(part_index, int) or part_index < 1:
        raise RuntimeError("delivery_event_invalid")
    if event.get("status") not in {
        "attempting",
        "sent",
        "rejected",
        "unknown_delivery_state",
        "local_pre_request_blocked",
    }:
        raise RuntimeError("delivery_event_invalid")
    if not isinstance(event.get("external_attempt_made"), bool):
        raise RuntimeError("delivery_event_invalid")
    http_status = event.get("http_status")
    if http_status is not None and (
        isinstance(http_status, bool) or not isinstance(http_status, int)
    ):
        raise RuntimeError("delivery_event_invalid")
    response_hash = event.get("response_hash")
    if response_hash is not None and (
        not isinstance(response_hash, str) or _HASH_LABEL.fullmatch(response_hash) is None
    ):
        raise RuntimeError("delivery_event_invalid")
    timestamp = event.get("timestamp")
    if not isinstance(timestamp, str):
        raise RuntimeError("delivery_event_invalid")
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError as exc:
        raise RuntimeError("delivery_event_invalid") from exc
    if parsed.tzinfo is None:
        raise RuntimeError("delivery_event_invalid")


def _ensure_ledger_directories(run_root: Path) -> None:
    delivery_root = run_root.parent
    state_root = delivery_root.parent
    _ensure_directory(state_root, mode=0o700)
    _ensure_or_make_directory(delivery_root)
    _ensure_or_make_directory(run_root)


def _ensure_destination_ledger_directories(destination_root: Path) -> None:
    destinations_root = destination_root.parent
    run_root = destinations_root.parent
    delivery_root = run_root.parent
    state_root = delivery_root.parent
    _ensure_directory(state_root, mode=0o700)
    for path in (delivery_root, run_root, destinations_root, destination_root):
        _ensure_or_make_directory(path)


@contextmanager
def _destination_delivery_lock(
    destination_root: Path, run_id: str, destination_id: str
) -> Iterator[None]:
    _require_safe_id(run_id, "run_id")
    _require_destination_id(destination_id)
    if (
        destination_root.name != destination_id
        or destination_root.parent.name != "destinations"
        or destination_root.parent.parent.name != run_id
    ):
        raise RuntimeError("delivery_lock_path_mismatch")
    _ensure_destination_ledger_directories(destination_root)
    path = destination_root / "send.lock"
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        metadata = os.fstat(descriptor)
        path_metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(path_metadata.st_mode)
            or not stat.S_ISREG(path_metadata.st_mode)
            or (metadata.st_dev, metadata.st_ino)
            != (path_metadata.st_dev, path_metadata.st_ino)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise RuntimeError("delivery_lock_metadata_invalid")
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)
    _fsync_directory(destination_root)


def _ensure_or_make_directory(path: Path) -> None:
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        _ensure_directory(path, mode=0o700)
        return
    path.chmod(0o700)
    _fsync_directory(path.parent)


def _ensure_directory(path: Path, *, mode: int) -> None:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError("delivery_directory_invalid")
    if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != mode:
        raise RuntimeError("delivery_directory_metadata_invalid")


def _read_regular_bytes(path: Path) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError("delivery_ledger_invalid")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > 16 * 1024 * 1024:
                raise RuntimeError("delivery_ledger_too_large")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        view = view[written:]


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _decode_json_object(payload: bytes, reason: str) -> Mapping[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate")
            result[key] = value
        return result

    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError(reason) from exc
    if not isinstance(value, Mapping):
        raise RuntimeError(reason)
    return value


def _ledger_path(roots: PreparedReportRoots, run_id: str) -> Path:
    return roots.state_root / "delivery" / run_id / "ledger.jsonl"


def _destination_ledger_path(
    roots: PreparedReportRoots, run_id: str, destination_id: str
) -> Path:
    _require_safe_id(run_id, "run_id")
    _require_destination_id(destination_id)
    return (
        roots.state_root
        / "delivery"
        / run_id
        / "destinations"
        / destination_id
        / "ledger.jsonl"
    )


def _ledger_tip(entries: Sequence[Mapping[str, object]]) -> str | None:
    return str(entries[-1]["entry_hash"]) if entries else None


def _live_evidence(entries: Sequence[Mapping[str, object]]) -> tuple[bool, bool]:
    report = any(
        entry.get("part_kind") == "report" and entry.get("external_attempt_made") is True
        for entry in entries
    )
    alert = any(
        entry.get("part_kind") == "failure_alert"
        and entry.get("external_attempt_made") is True
        for entry in entries
    )
    return report, alert


def _empty_summary(
    *,
    run_id: str,
    artifact_version_id: str | None,
    outbox_sha256: str | None,
    status: str,
    ledger_tip: str | None = None,
) -> DeliverySummary:
    return DeliverySummary(
        run_id=run_id,
        artifact_version_id=artifact_version_id,
        outbox_sha256=outbox_sha256,
        attempted_part_indexes=(),
        sent_part_indexes=(),
        rejected_part_indexes=(),
        ledger_tip_before=ledger_tip,
        ledger_tip_after=ledger_tip,
        status=status,
        report_live_send=False,
        alert_live_send=False,
        live_send=False,
    )


def _empty_multi_summary(
    *,
    run_id: str,
    artifact_version_id: str | None,
    outbox_sha256: str | None,
    status: str,
) -> MultiDestinationDeliverySummary:
    return MultiDestinationDeliverySummary(
        run_id=run_id,
        artifact_version_id=artifact_version_id,
        outbox_sha256=outbox_sha256,
        destinations=(),
        status=status,
        report_live_send=False,
        alert_live_send=False,
        live_send=False,
    )


def _destination_summary(
    *,
    destination_id: str,
    status: str,
    ledger_before: Sequence[Mapping[str, object]],
    ledger_after: Sequence[Mapping[str, object]],
    attempted: Sequence[int] = (),
    sent: Sequence[int] = (),
    rejected: Sequence[int] = (),
) -> DestinationDeliverySummary:
    report_live, _alert_live = _live_evidence(ledger_after)
    return DestinationDeliverySummary(
        destination_id=_require_destination_id(destination_id),
        attempted_part_indexes=tuple(attempted),
        sent_part_indexes=tuple(sent),
        rejected_part_indexes=tuple(rejected),
        ledger_tip_before=_ledger_tip(ledger_before),
        ledger_tip_after=_ledger_tip(ledger_after),
        status=status,
        report_live_send=report_live,
    )


def _validate_destination_credentials(
    values: Sequence[DingTalkDestinationCredential],
) -> tuple[DingTalkDestinationCredential, DingTalkDestinationCredential]:
    if not isinstance(values, (tuple, list)) or len(values) != 2:
        raise RuntimeError("dingtalk_destination_credentials_invalid")
    from .dingtalk import validate_webhook_url

    validated: list[DingTalkDestinationCredential] = []
    for expected_id, value in zip(_DESTINATION_IDS, values, strict=True):
        if not isinstance(value, DingTalkDestinationCredential):
            raise RuntimeError("dingtalk_destination_credentials_invalid")
        if value.destination_id != expected_id:
            raise RuntimeError("dingtalk_destination_order_invalid")
        if not isinstance(value.webhook_url, str) or not value.webhook_url:
            raise RuntimeError("dingtalk_destination_credentials_invalid")
        if value.webhook_secret is not None and not isinstance(
            value.webhook_secret, str
        ):
            raise RuntimeError("dingtalk_destination_credentials_invalid")
        validated.append(
            DingTalkDestinationCredential(
                destination_id=expected_id,
                webhook_url=validate_webhook_url(value.webhook_url),
                webhook_secret=value.webhook_secret,
            )
        )
    if validated[0].webhook_url == validated[1].webhook_url:
        raise RuntimeError("dingtalk_destination_duplicate")
    return validated[0], validated[1]


def _destination_delivery_complete(
    *,
    ledger_entries: Sequence[Mapping[str, object]],
    db_records: Sequence[Mapping[str, object]],
    expected_outbox_sha256: str,
    parts: Sequence[PreparedOutboxPart],
) -> bool:
    sent = [
        entry
        for entry in ledger_entries
        if entry.get("part_kind") == "report"
        and entry.get("status") == "sent"
        and entry.get("outbox_sha256") == expected_outbox_sha256
    ]
    expected_indexes = {part.index for part in parts}
    sent_indexes = {int(entry["part_index"]) for entry in sent}
    if sent_indexes != expected_indexes or len(sent) != len(expected_indexes):
        return False
    expected_hashes = sorted("sha256:" + str(entry["part_sha256"]) for entry in sent)
    actual_hashes = sorted(str(record.get("message_hash")) for record in db_records)
    return expected_hashes == actual_hashes


def _aggregate_destination_status(
    summaries: Sequence[DestinationDeliverySummary],
) -> str:
    if len(summaries) != 2:
        raise RuntimeError("destination_summary_count_invalid")
    statuses = {item.status for item in summaries}
    successful = sum(
        item.status in {"sent", "already_sent"} for item in summaries
    )
    unknown = "unknown_delivery_state" in statuses
    if successful == 2:
        return "sent"
    if unknown and successful:
        return "partial_unknown_delivery_state"
    if unknown:
        return "unknown_delivery_state"
    if successful:
        return "partially_sent"
    if statuses == {"rejected"}:
        return "rejected"
    return "blocked"


def _require_safe_id(value: object, field: str) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise ValueError(f"{field}_invalid")
    return value


def _require_destination_id(value: object) -> str:
    if not isinstance(value, str) or value not in _DESTINATION_IDS:
        raise ValueError("destination_id_invalid")
    return value


def _require_sha(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        raise ValueError(f"{field}_invalid")
    return value
