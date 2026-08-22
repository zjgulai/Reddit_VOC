from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping

from .report_contracts import AttemptEvidence, TokenUsage


ZERO_TIP = "0" * 64
SCHEMA_VERSION = "provider-attempt-ledger-event-v2"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_PHASES = frozenset({"translation", "semantic_validation"})
_EVENT_TYPES = frozenset({"reservation", "start", "terminal", "unknown"})
_RESPONSE_METADATA_KEYS = frozenset(
    {
        "http_status",
        "response_id",
        "actual_model",
        "system_fingerprint",
        "finish_reason",
        "retryable",
        "duration_ms",
    }
)
_USAGE_KEYS = (
    "prompt_tokens",
    "completion_tokens",
    "prompt_cache_hit_tokens",
    "prompt_cache_miss_tokens",
    "total_tokens",
)
_EVENT_KEYS = frozenset(
    {
        "schema_version",
        "authorization_id",
        "release_sha256",
        "run_id",
        "attempt_id",
        "event_type",
        "phase",
        "sequence",
        "ledger_sequence",
        "request_payload_sha256",
        "external_attempt_made",
        "result",
        "response_metadata_sha256",
        "usage",
        "timestamp_utc",
        "previous_entry_hash",
        "entry_hash",
    }
)
_BINDING_KEYS = frozenset(
    {
        "schema_version",
        "authorization_id",
        "release_sha256",
        "run_id",
        "attempt_id",
        "status",
        "ledger_sha256",
        "ledger_tip",
        "event_count",
        "reservation_count",
        "external_attempt_count",
        "retry_count",
        "unknown_attempt_count",
        "usage",
        "attempts",
    }
)
_ATTEMPT_BINDING_KEYS = frozenset(
    {
        "sequence",
        "phase",
        "request_payload_sha256",
        "reservation_entry_hash",
        "start_entry_hash",
        "closure_event_type",
        "closure_entry_hash",
        "external_attempt_made",
        "result",
        "response_metadata_sha256",
        "usage",
    }
)


class ProviderAttemptLedgerError(RuntimeError):
    """A fail-closed provider-attempt evidence error."""


class ProviderAttemptLedgerCasError(ProviderAttemptLedgerError):
    """The caller's expected tip no longer matches the durable ledger tip."""


@dataclass(frozen=True)
class ProviderAttemptAppendResult:
    entry: Mapping[str, object]
    entry_hash: str


@dataclass(frozen=True)
class ProviderAttemptLedgerSnapshot:
    entries: tuple[Mapping[str, object], ...]
    tip: str
    ledger_sha256: str


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ProviderAttemptLedgerError(f"invalid_{field}")
    return value


def _require_safe_id(value: object, field: str) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise ProviderAttemptLedgerError(f"invalid_{field}")
    return value


def _require_phase(value: object) -> str:
    if value not in _PHASES:
        raise ProviderAttemptLedgerError("invalid_phase")
    return str(value)


def _require_sequence(value: object, field: str = "sequence") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ProviderAttemptLedgerError(f"invalid_{field}")
    return value


def _zero_usage() -> dict[str, int]:
    return {key: 0 for key in _USAGE_KEYS}


def _normalize_usage(value: Mapping[str, object] | None) -> dict[str, int]:
    if value is None:
        return _zero_usage()
    if not isinstance(value, Mapping) or set(value) != set(_USAGE_KEYS):
        raise ProviderAttemptLedgerError("invalid_usage")
    normalized: dict[str, int] = {}
    for key in _USAGE_KEYS:
        item = value[key]
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise ProviderAttemptLedgerError("invalid_usage")
        normalized[key] = item
    if normalized["total_tokens"] != (
        normalized["prompt_tokens"] + normalized["completion_tokens"]
    ):
        raise ProviderAttemptLedgerError("invalid_usage_total")
    return normalized


def _normalize_response_metadata(value: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != set(_RESPONSE_METADATA_KEYS):
        raise ProviderAttemptLedgerError("invalid_response_metadata")
    http_status = value["http_status"]
    if http_status is not None and (
        isinstance(http_status, bool) or not isinstance(http_status, int)
    ):
        raise ProviderAttemptLedgerError("invalid_response_metadata")
    duration_ms = value["duration_ms"]
    if isinstance(duration_ms, bool) or not isinstance(duration_ms, int) or duration_ms < 0:
        raise ProviderAttemptLedgerError("invalid_response_metadata")
    if not isinstance(value["retryable"], bool):
        raise ProviderAttemptLedgerError("invalid_response_metadata")
    normalized: dict[str, object] = {
        "http_status": http_status,
        "retryable": value["retryable"],
        "duration_ms": duration_ms,
    }
    for key in (
        "response_id",
        "actual_model",
        "system_fingerprint",
        "finish_reason",
    ):
        item = value[key]
        if item is not None and (not isinstance(item, str) or len(item) > 512):
            raise ProviderAttemptLedgerError("invalid_response_metadata")
        normalized[key] = item
    return normalized


def _require_utc_timestamp(value: object) -> str:
    if not isinstance(value, str):
        raise ProviderAttemptLedgerError("invalid_timestamp_utc")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProviderAttemptLedgerError("invalid_timestamp_utc") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ProviderAttemptLedgerError("invalid_timestamp_utc")
    return value


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProviderAttemptLedgerError(f"duplicate_json_key:{key}")
        result[key] = value
    return result


class ProviderAttemptLedger:
    """Durable v2 evidence for every externally bounded provider attempt.

    The ledger stores only request/response fingerprints and allow-listed scalar
    evidence. Prompt text, response bodies, credentials, and headers never enter
    the durable format.
    """

    def __init__(
        self,
        *,
        path: Path,
        authorization_id: str,
        release_sha256: str,
        run_id: str,
        attempt_id: str,
        clock: Callable[[], str],
    ) -> None:
        self.path = Path(path)
        self.authorization_id = _require_safe_id(authorization_id, "authorization_id")
        self.release_sha256 = _require_sha256(release_sha256, "release_sha256")
        self.run_id = _require_safe_id(run_id, "run_id")
        self.attempt_id = _require_safe_id(attempt_id, "attempt_id")
        if not callable(clock):
            raise ProviderAttemptLedgerError("invalid_clock")
        self._clock = clock
        self._lock_path = self.path.with_name(f".{self.path.name}.lock")
        self._validate_parent()

    def reserve(
        self,
        *,
        phase: str,
        sequence: int,
        request_payload_sha256: str,
        expected_tip: str,
    ) -> ProviderAttemptAppendResult:
        return self._append(
            event_type="reservation",
            phase=phase,
            sequence=sequence,
            request_payload_sha256=request_payload_sha256,
            external_attempt_made=False,
            result="reserved",
            response_metadata_sha256=None,
            usage=_zero_usage(),
            expected_tip=expected_tip,
        )

    def start(
        self,
        *,
        phase: str,
        sequence: int,
        request_payload_sha256: str,
        expected_tip: str,
    ) -> ProviderAttemptAppendResult:
        return self._append(
            event_type="start",
            phase=phase,
            sequence=sequence,
            request_payload_sha256=request_payload_sha256,
            external_attempt_made=True,
            result="attempting",
            response_metadata_sha256=None,
            usage=_zero_usage(),
            expected_tip=expected_tip,
        )

    def terminal(
        self,
        *,
        phase: str,
        sequence: int,
        request_payload_sha256: str,
        result: str,
        response_metadata: Mapping[str, object],
        usage: Mapping[str, object],
        expected_tip: str,
    ) -> ProviderAttemptAppendResult:
        if not isinstance(result, str) or _SAFE_ID.fullmatch(result) is None:
            raise ProviderAttemptLedgerError("invalid_result")
        metadata = _normalize_response_metadata(response_metadata)
        return self._append(
            event_type="terminal",
            phase=phase,
            sequence=sequence,
            request_payload_sha256=request_payload_sha256,
            external_attempt_made=True,
            result=result,
            response_metadata_sha256=_sha256_bytes(_canonical_json_bytes(metadata)),
            usage=_normalize_usage(usage),
            expected_tip=expected_tip,
        )

    def unknown(
        self,
        *,
        phase: str,
        sequence: int,
        request_payload_sha256: str,
        expected_tip: str,
    ) -> ProviderAttemptAppendResult:
        """Close a started call whose external outcome cannot be proven."""
        return self._append(
            event_type="unknown",
            phase=phase,
            sequence=sequence,
            request_payload_sha256=request_payload_sha256,
            external_attempt_made=True,
            result="unknown_external_state",
            response_metadata_sha256=None,
            usage=_zero_usage(),
            expected_tip=expected_tip,
        )

    def cancel_reserved(
        self,
        *,
        phase: str,
        sequence: int,
        request_payload_sha256: str,
        expected_tip: str,
    ) -> ProviderAttemptAppendResult:
        """Close a reservation proven not to have crossed the external boundary."""
        return self._append(
            event_type="terminal",
            phase=phase,
            sequence=sequence,
            request_payload_sha256=request_payload_sha256,
            external_attempt_made=False,
            result="cancelled_before_external",
            response_metadata_sha256=None,
            usage=_zero_usage(),
            expected_tip=expected_tip,
        )

    def load(self) -> ProviderAttemptLedgerSnapshot:
        try:
            metadata = self.path.lstat()
        except FileNotFoundError:
            return ProviderAttemptLedgerSnapshot((), ZERO_TIP, _sha256_bytes(b""))
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ProviderAttemptLedgerError("ledger_file_not_regular")
        lock_fd = self._open_private_file(self._lock_path, create=True)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_SH)
            ledger_fd = self._open_private_file(self.path, create=False)
            try:
                return self._load_fd(ledger_fd)
            finally:
                os.close(ledger_fd)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

    def build_manifest_binding(self, *, status: str) -> Mapping[str, object]:
        """Build the exact, privacy-preserving ledger section for a manifest."""
        if status not in {"complete", "blocked"}:
            raise ProviderAttemptLedgerError("invalid_manifest_status")
        snapshot = self.load()
        attempts = self._closed_attempt_documents(snapshot)
        if status == "complete" and any(
            attempt["closure_event_type"] == "unknown" for attempt in attempts
        ):
            raise ProviderAttemptLedgerError("complete_manifest_has_unknown_attempt")
        if status == "complete" and any(
            not attempt["external_attempt_made"] for attempt in attempts
        ):
            raise ProviderAttemptLedgerError(
                "complete_manifest_has_non_external_closure"
            )
        aggregate_usage = _zero_usage()
        external_by_request: dict[tuple[object, object], int] = {}
        for attempt in attempts:
            usage = attempt["usage"]
            assert isinstance(usage, Mapping)
            for key in _USAGE_KEYS:
                aggregate_usage[key] += int(usage[key])
            if attempt["external_attempt_made"]:
                request_key = (
                    attempt["phase"],
                    attempt["request_payload_sha256"],
                )
                external_by_request[request_key] = (
                    external_by_request.get(request_key, 0) + 1
                )
        return {
            "schema_version": "provider-attempt-ledger-binding-v2",
            "authorization_id": self.authorization_id,
            "release_sha256": self.release_sha256,
            "run_id": self.run_id,
            "attempt_id": self.attempt_id,
            "status": status,
            "ledger_sha256": snapshot.ledger_sha256,
            "ledger_tip": snapshot.tip,
            "event_count": len(snapshot.entries),
            "reservation_count": len(attempts),
            "external_attempt_count": sum(
                bool(attempt["external_attempt_made"]) for attempt in attempts
            ),
            "retry_count": sum(
                max(0, count - 1) for count in external_by_request.values()
            ),
            "unknown_attempt_count": sum(
                attempt["closure_event_type"] == "unknown" for attempt in attempts
            ),
            "usage": aggregate_usage,
            "attempts": attempts,
        }

    def verify_manifest_closure(self, manifest: Mapping[str, object]) -> None:
        """Fail closed unless manifest summaries exactly close over this ledger."""
        if not isinstance(manifest, Mapping):
            raise ProviderAttemptLedgerError("manifest_not_object")
        status = manifest.get("status")
        if status not in {"complete", "blocked"}:
            raise ProviderAttemptLedgerError("invalid_manifest_status")
        expected_binding = self.build_manifest_binding(status=str(status))
        if manifest.get("provider_attempt_ledger") != expected_binding:
            raise ProviderAttemptLedgerError("manifest_ledger_binding_mismatch")
        if manifest.get("run_id") != self.run_id:
            raise ProviderAttemptLedgerError("manifest_run_id_mismatch")
        if status == "blocked" and manifest.get("attempt_id") != self.attempt_id:
            raise ProviderAttemptLedgerError("manifest_attempt_id_mismatch")

        external_count = int(expected_binding["external_attempt_count"])
        attempted = external_count > 0
        authorization = manifest.get("provider_authorization_id")
        if attempted:
            if authorization != self.authorization_id:
                raise ProviderAttemptLedgerError(
                    "manifest_provider_authorization_mismatch"
                )
        elif authorization not in {None, self.authorization_id}:
            raise ProviderAttemptLedgerError("manifest_provider_authorization_mismatch")

        if manifest.get("request_count") != external_count:
            raise ProviderAttemptLedgerError("manifest_request_count_mismatch")
        if manifest.get("retry_count") != expected_binding["retry_count"]:
            raise ProviderAttemptLedgerError("manifest_retry_count_mismatch")
        for field in (
            "provider_call",
            "translation_provider_call",
            "translation_provider_attempt_made",
        ):
            if manifest.get(field) is not attempted:
                raise ProviderAttemptLedgerError(f"manifest_{field}_mismatch")
        attempts = expected_binding["attempts"]
        assert isinstance(attempts, list)
        translation_attempted = any(
            attempt["phase"] == "translation"
            and bool(attempt["external_attempt_made"])
            for attempt in attempts
        )
        semantic_attempted = any(
            attempt["phase"] == "semantic_validation"
            and bool(attempt["external_attempt_made"])
            for attempt in attempts
        )
        if manifest.get("translation_phase_attempt_made") is not translation_attempted:
            raise ProviderAttemptLedgerError(
                "manifest_translation_phase_attempt_made_mismatch"
            )
        if (
            manifest.get("semantic_validation_phase_attempt_made")
            is not semantic_attempted
        ):
            raise ProviderAttemptLedgerError(
                "manifest_semantic_validation_phase_attempt_made_mismatch"
            )
        if manifest.get("usage") != expected_binding["usage"]:
            raise ProviderAttemptLedgerError("manifest_usage_mismatch")

    @staticmethod
    def _closed_attempt_documents(
        snapshot: ProviderAttemptLedgerSnapshot,
    ) -> list[dict[str, object]]:
        attempts: dict[int, dict[str, object]] = {}
        for entry in snapshot.entries:
            sequence = int(entry["sequence"])
            event_type = str(entry["event_type"])
            if event_type == "reservation":
                attempts[sequence] = {
                    "sequence": sequence,
                    "phase": entry["phase"],
                    "request_payload_sha256": entry["request_payload_sha256"],
                    "reservation_entry_hash": entry["entry_hash"],
                    "start_entry_hash": None,
                    "closure_event_type": None,
                    "closure_entry_hash": None,
                    "external_attempt_made": False,
                    "result": None,
                    "response_metadata_sha256": None,
                    "usage": _zero_usage(),
                }
            elif event_type == "start":
                attempt = attempts[sequence]
                attempt["start_entry_hash"] = entry["entry_hash"]
                attempt["external_attempt_made"] = True
            else:
                attempt = attempts[sequence]
                attempt["closure_event_type"] = event_type
                attempt["closure_entry_hash"] = entry["entry_hash"]
                attempt["external_attempt_made"] = entry["external_attempt_made"]
                attempt["result"] = entry["result"]
                attempt["response_metadata_sha256"] = entry[
                    "response_metadata_sha256"
                ]
                attempt["usage"] = entry["usage"]
        for attempt in attempts.values():
            if attempt["closure_event_type"] is None:
                raise ProviderAttemptLedgerError(
                    f"ledger_open_attempt:{attempt['sequence']}"
                )
        sequences = sorted(attempts)
        if sequences != list(range(1, len(sequences) + 1)):
            raise ProviderAttemptLedgerError("ledger_attempt_sequence_gap")
        return [attempts[sequence] for sequence in sequences]

    def _append(
        self,
        *,
        event_type: str,
        phase: str,
        sequence: int,
        request_payload_sha256: str,
        external_attempt_made: bool,
        result: str,
        response_metadata_sha256: str | None,
        usage: Mapping[str, object],
        expected_tip: str,
    ) -> ProviderAttemptAppendResult:
        if event_type not in _EVENT_TYPES:
            raise ProviderAttemptLedgerError("invalid_event_type")
        phase = _require_phase(phase)
        sequence = _require_sequence(sequence)
        request_payload_sha256 = _require_sha256(
            request_payload_sha256, "request_payload_sha256"
        )
        expected_tip = _require_sha256(expected_tip, "expected_tip")
        normalized_usage = _normalize_usage(usage)
        lock_fd = self._open_private_file(self._lock_path, create=True)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            ledger_fd = self._open_private_file(self.path, create=True)
            try:
                snapshot = self._load_fd(ledger_fd)
                if snapshot.tip != expected_tip:
                    raise ProviderAttemptLedgerCasError("ledger_tip_mismatch")
                self._validate_transition(
                    snapshot=snapshot,
                    event_type=event_type,
                    phase=phase,
                    sequence=sequence,
                    request_payload_sha256=request_payload_sha256,
                    external_attempt_made=external_attempt_made,
                    result=result,
                    response_metadata_sha256=response_metadata_sha256,
                    usage=normalized_usage,
                )
                base: dict[str, object] = {
                    "schema_version": SCHEMA_VERSION,
                    "authorization_id": self.authorization_id,
                    "release_sha256": self.release_sha256,
                    "run_id": self.run_id,
                    "attempt_id": self.attempt_id,
                    "event_type": event_type,
                    "phase": phase,
                    "sequence": sequence,
                    "ledger_sequence": len(snapshot.entries) + 1,
                    "request_payload_sha256": request_payload_sha256,
                    "external_attempt_made": external_attempt_made,
                    "result": result,
                    "response_metadata_sha256": response_metadata_sha256,
                    "usage": normalized_usage,
                    "timestamp_utc": _require_utc_timestamp(self._clock()),
                    "previous_entry_hash": snapshot.tip,
                }
                entry_hash = _sha256_bytes(_canonical_json_bytes(base))
                entry = {**base, "entry_hash": entry_hash}
                payload = _canonical_json_bytes(entry) + b"\n"
                os.lseek(ledger_fd, 0, os.SEEK_END)
                view = memoryview(payload)
                while view:
                    written = os.write(ledger_fd, view)
                    if written <= 0:
                        raise ProviderAttemptLedgerError("ledger_append_failed")
                    view = view[written:]
                os.fsync(ledger_fd)
                return ProviderAttemptAppendResult(entry=entry, entry_hash=entry_hash)
            finally:
                os.close(ledger_fd)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

    def _load_fd(self, descriptor: int) -> ProviderAttemptLedgerSnapshot:
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        byte_count = 0
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            byte_count += len(chunk)
            if byte_count > 5 * 1024 * 1024:
                raise ProviderAttemptLedgerError("ledger_too_large")
            chunks.append(chunk)
        payload = b"".join(chunks)
        if payload and not payload.endswith(b"\n"):
            raise ProviderAttemptLedgerError("ledger_truncated")
        entries: list[Mapping[str, object]] = []
        previous = ZERO_TIP
        for line_number, line in enumerate(payload.splitlines(), start=1):
            if line_number > 400:
                raise ProviderAttemptLedgerError("ledger_too_many_events")
            try:
                entry = json.loads(line, object_pairs_hook=_reject_duplicate_pairs)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ProviderAttemptLedgerError(
                    f"ledger_invalid_json:{line_number}"
                ) from exc
            if not isinstance(entry, dict) or set(entry) != set(_EVENT_KEYS):
                raise ProviderAttemptLedgerError(f"ledger_invalid_keys:{line_number}")
            if _canonical_json_bytes(entry) != line:
                raise ProviderAttemptLedgerError(f"ledger_not_canonical:{line_number}")
            self._validate_loaded_entry(
                entry=entry,
                ledger_sequence=line_number,
                previous=previous,
            )
            base = {key: value for key, value in entry.items() if key != "entry_hash"}
            expected_hash = _sha256_bytes(_canonical_json_bytes(base))
            if entry["entry_hash"] != expected_hash:
                raise ProviderAttemptLedgerError(f"ledger_hash_mismatch:{line_number}")
            previous = expected_hash
            entries.append(entry)
        self._validate_loaded_transitions(entries)
        return ProviderAttemptLedgerSnapshot(
            entries=tuple(entries),
            tip=previous,
            ledger_sha256=_sha256_bytes(payload),
        )

    def _validate_loaded_entry(
        self,
        *,
        entry: Mapping[str, object],
        ledger_sequence: int,
        previous: str,
    ) -> None:
        if entry["schema_version"] != SCHEMA_VERSION:
            raise ProviderAttemptLedgerError("ledger_schema_mismatch")
        expected_scope = {
            "authorization_id": self.authorization_id,
            "release_sha256": self.release_sha256,
            "run_id": self.run_id,
            "attempt_id": self.attempt_id,
        }
        if any(entry[key] != value for key, value in expected_scope.items()):
            raise ProviderAttemptLedgerError("ledger_scope_mismatch")
        if entry["ledger_sequence"] != ledger_sequence:
            raise ProviderAttemptLedgerError("ledger_sequence_mismatch")
        if entry["previous_entry_hash"] != previous:
            raise ProviderAttemptLedgerError("ledger_previous_hash_mismatch")
        _require_sha256(entry["entry_hash"], "entry_hash")
        _require_sha256(entry["request_payload_sha256"], "request_payload_sha256")
        _require_phase(entry["phase"])
        _require_sequence(entry["sequence"])
        _require_utc_timestamp(entry["timestamp_utc"])
        event_type = entry["event_type"]
        if event_type not in _EVENT_TYPES:
            raise ProviderAttemptLedgerError("ledger_invalid_event_type")
        if not isinstance(entry["external_attempt_made"], bool):
            raise ProviderAttemptLedgerError("ledger_invalid_external_boundary")
        result = entry["result"]
        if not isinstance(result, str) or _SAFE_ID.fullmatch(result) is None:
            raise ProviderAttemptLedgerError("ledger_invalid_result")
        metadata_sha = entry["response_metadata_sha256"]
        if metadata_sha is not None:
            _require_sha256(metadata_sha, "response_metadata_sha256")
        usage = _normalize_usage(entry["usage"] if isinstance(entry["usage"], Mapping) else None)
        if usage != entry["usage"]:
            raise ProviderAttemptLedgerError("ledger_invalid_usage")

    def _validate_loaded_transitions(
        self, entries: list[Mapping[str, object]]
    ) -> None:
        states: dict[int, tuple[str, str, str]] = {}
        for entry in entries:
            sequence = int(entry["sequence"])
            phase = str(entry["phase"])
            request_hash = str(entry["request_payload_sha256"])
            event_type = str(entry["event_type"])
            if event_type == "reservation":
                if sequence in states:
                    raise ProviderAttemptLedgerError("ledger_reservation_sequence_invalid")
                if (
                    entry["external_attempt_made"]
                    or entry["result"] != "reserved"
                    or entry.get("response_metadata_sha256") is not None
                    or entry.get("usage") != _zero_usage()
                ):
                    raise ProviderAttemptLedgerError("ledger_reservation_invalid")
                states[sequence] = ("reserved", phase, request_hash)
                continue
            state = states.get(sequence)
            if state is None or state[1:] != (phase, request_hash):
                raise ProviderAttemptLedgerError("ledger_attempt_binding_mismatch")
            if event_type == "start":
                if state[0] != "reserved":
                    raise ProviderAttemptLedgerError("ledger_start_transition_invalid")
                if (
                    not entry["external_attempt_made"]
                    or entry["result"] != "attempting"
                    or entry.get("response_metadata_sha256") is not None
                    or entry.get("usage") != _zero_usage()
                ):
                    raise ProviderAttemptLedgerError("ledger_start_invalid")
                states[sequence] = ("started", phase, request_hash)
            elif event_type == "unknown":
                if state[0] != "started" or not entry["external_attempt_made"]:
                    raise ProviderAttemptLedgerError("ledger_closure_transition_invalid")
                if (
                    entry["result"] != "unknown_external_state"
                    or entry.get("response_metadata_sha256") is not None
                    or entry.get("usage") != _zero_usage()
                ):
                    raise ProviderAttemptLedgerError("ledger_unknown_invalid")
                states[sequence] = ("closed", phase, request_hash)
            elif event_type == "terminal":
                if state[0] == "reserved":
                    if (
                        entry["external_attempt_made"]
                        or entry["result"] != "cancelled_before_external"
                        or entry.get("response_metadata_sha256") is not None
                        or entry.get("usage") != _zero_usage()
                    ):
                        raise ProviderAttemptLedgerError("ledger_terminal_invalid")
                elif state[0] == "started":
                    if (
                        not entry["external_attempt_made"]
                        or entry["result"]
                        in {"reserved", "attempting", "unknown_external_state"}
                        or entry.get("response_metadata_sha256") is None
                    ):
                        raise ProviderAttemptLedgerError("ledger_terminal_invalid")
                else:
                    raise ProviderAttemptLedgerError(
                        "ledger_closure_transition_invalid"
                    )
                states[sequence] = ("closed", phase, request_hash)

    def _validate_transition(
        self,
        *,
        snapshot: ProviderAttemptLedgerSnapshot,
        event_type: str,
        phase: str,
        sequence: int,
        request_payload_sha256: str,
        external_attempt_made: bool,
        result: str,
        response_metadata_sha256: str | None,
        usage: Mapping[str, object],
    ) -> None:
        candidate: dict[str, object] = {
            "event_type": event_type,
            "phase": phase,
            "sequence": sequence,
            "request_payload_sha256": request_payload_sha256,
            "external_attempt_made": external_attempt_made,
            "result": result,
            "response_metadata_sha256": response_metadata_sha256,
            "usage": usage,
        }
        self._validate_loaded_transitions([*snapshot.entries, candidate])

    def _validate_parent(self) -> None:
        parent = self.path.parent
        try:
            metadata = parent.lstat()
        except OSError as exc:
            raise ProviderAttemptLedgerError("ledger_parent_unavailable") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ProviderAttemptLedgerError("ledger_parent_not_private_directory")
        if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
            raise ProviderAttemptLedgerError("ledger_parent_not_private_directory")

    @staticmethod
    def _open_private_file(path: Path, *, create: bool) -> int:
        flags = os.O_RDWR
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        created = False
        try:
            if create:
                try:
                    descriptor = os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o600)
                    created = True
                except FileExistsError:
                    descriptor = os.open(path, flags)
            else:
                descriptor = os.open(path, flags)
        except OSError as exc:
            raise ProviderAttemptLedgerError("ledger_open_failed") from exc
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_nlink != 1
            ):
                raise ProviderAttemptLedgerError("ledger_file_not_private")
            if created:
                os.fsync(descriptor)
                directory_fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise


class ProviderAttemptLifecycle:
    """Thread-safe lifecycle adapter consumed by the provider client."""

    def __init__(self, ledger: ProviderAttemptLedger) -> None:
        if not isinstance(ledger, ProviderAttemptLedger):
            raise ProviderAttemptLedgerError("invalid_ledger")
        self.ledger = ledger

    def reserve(
        self, *, sequence: int, phase: str, request_payload_sha256: str
    ) -> None:
        self._cas(
            lambda tip: self.ledger.reserve(
                sequence=sequence,
                phase=phase,
                request_payload_sha256=request_payload_sha256,
                expected_tip=tip,
            )
        )

    def start(
        self, *, sequence: int, phase: str, request_payload_sha256: str
    ) -> None:
        self._cas(
            lambda tip: self.ledger.start(
                sequence=sequence,
                phase=phase,
                request_payload_sha256=request_payload_sha256,
                expected_tip=tip,
            )
        )

    def terminal(
        self,
        *,
        sequence: int,
        phase: str,
        request_payload_sha256: str,
        evidence: AttemptEvidence,
    ) -> None:
        if (
            not isinstance(evidence, AttemptEvidence)
            or evidence.sequence != sequence
            or evidence.phase != phase
        ):
            raise ProviderAttemptLedgerError("attempt_evidence_binding_mismatch")
        usage = self._usage_document(evidence.usage)
        response_metadata = {
            "http_status": evidence.http_status,
            "response_id": evidence.response_id,
            "actual_model": evidence.actual_model,
            "system_fingerprint": evidence.system_fingerprint,
            "finish_reason": evidence.finish_reason,
            "retryable": evidence.retryable,
            "duration_ms": evidence.duration_ms,
        }
        self._cas(
            lambda tip: self.ledger.terminal(
                sequence=sequence,
                phase=phase,
                request_payload_sha256=request_payload_sha256,
                result=evidence.outcome,
                response_metadata=response_metadata,
                usage=usage,
                expected_tip=tip,
            )
        )

    def unknown(
        self, *, sequence: int, phase: str, request_payload_sha256: str
    ) -> None:
        self._cas(
            lambda tip: self.ledger.unknown(
                sequence=sequence,
                phase=phase,
                request_payload_sha256=request_payload_sha256,
                expected_tip=tip,
            )
        )

    def close_incomplete(self) -> tuple[int, ...]:
        """Conservatively close all unfinished rows after provider workers stop."""
        snapshot = self.ledger.load()
        open_attempts: dict[int, tuple[str, str, str]] = {}
        for entry in snapshot.entries:
            sequence = int(entry["sequence"])
            event_type = str(entry["event_type"])
            if event_type == "reservation":
                open_attempts[sequence] = (
                    "reserved",
                    str(entry["phase"]),
                    str(entry["request_payload_sha256"]),
                )
            elif event_type == "start":
                _state, phase, request_hash = open_attempts[sequence]
                open_attempts[sequence] = ("started", phase, request_hash)
            else:
                open_attempts.pop(sequence, None)
        closed: list[int] = []
        for sequence in sorted(open_attempts):
            state, phase, request_hash = open_attempts[sequence]
            if state == "started":
                self.unknown(
                    sequence=sequence,
                    phase=phase,
                    request_payload_sha256=request_hash,
                )
            else:
                self._cas(
                    lambda tip, sequence=sequence, phase=phase, request_hash=request_hash: (
                        self.ledger.cancel_reserved(
                            sequence=sequence,
                            phase=phase,
                            request_payload_sha256=request_hash,
                            expected_tip=tip,
                        )
                    )
                )
            closed.append(sequence)
        return tuple(closed)

    def _cas(
        self, operation: Callable[[str], ProviderAttemptAppendResult]
    ) -> ProviderAttemptAppendResult:
        for _ in range(64):
            tip = self.ledger.load().tip
            try:
                return operation(tip)
            except ProviderAttemptLedgerCasError:
                continue
        raise ProviderAttemptLedgerError("ledger_cas_retry_exhausted")

    @staticmethod
    def _usage_document(usage: TokenUsage | None) -> Mapping[str, int]:
        if usage is None:
            return _zero_usage()
        if not isinstance(usage, TokenUsage):
            raise ProviderAttemptLedgerError("invalid_attempt_usage")
        return {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "prompt_cache_hit_tokens": usage.prompt_cache_hit_tokens,
            "prompt_cache_miss_tokens": usage.prompt_cache_miss_tokens,
            "total_tokens": usage.total_tokens,
        }


def derive_blocked_binding_from_verified_complete_manifest(
    *, manifest: Mapping[str, object], attempt_id: str
) -> Mapping[str, object] | None:
    """Validate a detached complete binding before deriving commit-blocked evidence."""
    if not isinstance(manifest, Mapping):
        raise ProviderAttemptLedgerError("manifest_not_object")
    if (
        manifest.get("schema_version") != "daily-translation-manifest-v1"
        or manifest.get("status") != "complete"
    ):
        raise ProviderAttemptLedgerError("complete_manifest_identity_invalid")
    binding = manifest.get("provider_attempt_ledger")
    if binding is None:
        return None
    if not isinstance(binding, Mapping) or set(binding) != set(_BINDING_KEYS):
        raise ProviderAttemptLedgerError("manifest_ledger_binding_invalid")
    if (
        binding.get("schema_version") != "provider-attempt-ledger-binding-v2"
        or binding.get("status") != "complete"
    ):
        raise ProviderAttemptLedgerError("manifest_ledger_binding_invalid")
    _require_safe_id(attempt_id, "attempt_id")
    for key in ("authorization_id", "run_id", "attempt_id"):
        _require_safe_id(binding.get(key), key)
    for key in ("release_sha256", "ledger_sha256", "ledger_tip"):
        _require_sha256(binding.get(key), key)
    if (
        binding["attempt_id"] != attempt_id
        or binding["run_id"] != manifest.get("run_id")
        or binding["authorization_id"]
        != manifest.get("provider_authorization_id")
    ):
        raise ProviderAttemptLedgerError("manifest_ledger_identity_mismatch")

    attempts_value = binding.get("attempts")
    if not isinstance(attempts_value, list):
        raise ProviderAttemptLedgerError("manifest_ledger_attempts_invalid")
    attempts: list[Mapping[str, object]] = []
    aggregate_usage = _zero_usage()
    request_counts: dict[tuple[str, str], int] = {}
    event_hashes: set[str] = set()
    closure_hashes: set[str] = set()
    for expected_sequence, attempt in enumerate(attempts_value, start=1):
        if not isinstance(attempt, Mapping) or set(attempt) != set(
            _ATTEMPT_BINDING_KEYS
        ):
            raise ProviderAttemptLedgerError("manifest_ledger_attempt_invalid")
        if attempt.get("sequence") != expected_sequence:
            raise ProviderAttemptLedgerError("manifest_ledger_attempt_sequence_invalid")
        phase = _require_phase(attempt.get("phase"))
        request_hash = _require_sha256(
            attempt.get("request_payload_sha256"), "request_payload_sha256"
        )
        reservation_hash = _require_sha256(
            attempt.get("reservation_entry_hash"), "reservation_entry_hash"
        )
        start_hash = _require_sha256(
            attempt.get("start_entry_hash"), "start_entry_hash"
        )
        closure_hash = _require_sha256(
            attempt.get("closure_entry_hash"), "closure_entry_hash"
        )
        for entry_hash in (reservation_hash, start_hash, closure_hash):
            if entry_hash in event_hashes:
                raise ProviderAttemptLedgerError(
                    "manifest_ledger_entry_hash_reused"
                )
            event_hashes.add(entry_hash)
        closure_hashes.add(closure_hash)
        _require_sha256(
            attempt.get("response_metadata_sha256"),
            "response_metadata_sha256",
        )
        result = attempt.get("result")
        if not isinstance(result, str) or _SAFE_ID.fullmatch(result) is None:
            raise ProviderAttemptLedgerError("manifest_ledger_result_invalid")
        if (
            attempt.get("closure_event_type") != "terminal"
            or attempt.get("external_attempt_made") is not True
        ):
            raise ProviderAttemptLedgerError("complete_manifest_attempt_invalid")
        usage = _normalize_usage(
            attempt.get("usage") if isinstance(attempt.get("usage"), Mapping) else None
        )
        if usage != attempt.get("usage"):
            raise ProviderAttemptLedgerError("manifest_ledger_usage_invalid")
        for key in _USAGE_KEYS:
            aggregate_usage[key] += usage[key]
        request_key = (phase, request_hash)
        request_counts[request_key] = request_counts.get(request_key, 0) + 1
        attempts.append(attempt)

    expected_retry_count = sum(
        max(0, count - 1) for count in request_counts.values()
    )
    integer_counts = {
        "event_count": len(attempts) * 3,
        "reservation_count": len(attempts),
        "external_attempt_count": len(attempts),
        "retry_count": expected_retry_count,
        "unknown_attempt_count": 0,
    }
    for key, expected in integer_counts.items():
        value = binding.get(key)
        if isinstance(value, bool) or value != expected:
            raise ProviderAttemptLedgerError(f"manifest_ledger_{key}_mismatch")
    if binding.get("usage") != aggregate_usage:
        raise ProviderAttemptLedgerError("manifest_ledger_usage_mismatch")
    ledger_tip = binding["ledger_tip"]
    if attempts:
        if ledger_tip not in closure_hashes:
            raise ProviderAttemptLedgerError("manifest_ledger_tip_mismatch")
    elif (
        ledger_tip != ZERO_TIP
        or binding["ledger_sha256"] != _sha256_bytes(b"")
    ):
        raise ProviderAttemptLedgerError("manifest_empty_ledger_digest_mismatch")
    attempted = bool(attempts)
    for field in (
        "provider_call",
        "translation_provider_call",
        "translation_provider_attempt_made",
    ):
        if manifest.get(field) is not attempted:
            raise ProviderAttemptLedgerError(f"manifest_{field}_mismatch")
    if manifest.get("request_count") != len(attempts):
        raise ProviderAttemptLedgerError("manifest_request_count_mismatch")
    if manifest.get("retry_count") != expected_retry_count:
        raise ProviderAttemptLedgerError("manifest_retry_count_mismatch")
    if manifest.get("usage") != aggregate_usage:
        raise ProviderAttemptLedgerError("manifest_usage_mismatch")
    translation_attempted = any(
        attempt["phase"] == "translation" for attempt in attempts
    )
    semantic_attempted = any(
        attempt["phase"] == "semantic_validation" for attempt in attempts
    )
    if manifest.get("translation_phase_attempt_made") is not translation_attempted:
        raise ProviderAttemptLedgerError(
            "manifest_translation_phase_attempt_made_mismatch"
        )
    if manifest.get("semantic_validation_phase_attempt_made") is not semantic_attempted:
        raise ProviderAttemptLedgerError(
            "manifest_semantic_validation_phase_attempt_made_mismatch"
        )
    copied = json.loads(_canonical_json_bytes(binding).decode("utf-8"))
    copied["status"] = "blocked"
    return copied
