#!/usr/bin/env python3
"""Validate and immutably stage rollback authority evidence.

The rollback wrapper runs ``validate`` locally before any transport.  On the
server it uploads the same files into a private ``/tmp`` directory and runs
``persist``.  ``persist`` re-opens and re-hashes every source, then publishes
the three JSON documents under content-addressed names without replacing an
existing path.
"""

from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import pwd
import secrets
import stat
import sys
from typing import Any, Mapping, NoReturn


SHA256_LENGTH = 64
MAX_EVIDENCE_BYTES = 16 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
EVIDENCE_NAMES = {
    "authorization_packet": "authorization-packet",
    "authorization_permit": "authorization-permit",
    "production_baseline": "production-baseline",
}
PERSIST_ACTION = "persist_exact_rollback_authority_evidence"
ALLOWED_ACTIONS = (
    "read_only_remote_preflight",
    "upload_exact_release_artifacts_to_isolated_directory",
    "verify_exact_remote_artifact_hashes",
    "stage_exact_insights_data_release",
    "load_exact_linux_amd64_image",
    "start_only_reddit_voc_insights_candidate_18339",
    "run_candidate_runtime_smoke",
    "compare_and_swap_only_insights_current",
    "compare_and_swap_only_insights_data_current",
    "run_public_production_acceptance",
    PERSIST_ACTION,
    "rollback_only_insights_current",
    "rollback_only_insights_data_current",
)
FORBIDDEN_ACTIONS = (
    "modify_collector",
    "restart_collector",
    "modify_cron",
    "modify_shared_nginx",
    "modify_tls",
    "modify_dns",
    "modify_other_docker_environment",
    "docker_prune",
    "provider_call",
    "database_write",
    "schedule_change",
    "live_send",
    "enable_candidate_registry_automation",
    "claim_four_exports_complete",
)
RUNTIME_NAMES = {
    "runner": "remote_rollback_insights.sh",
    "patcher": "patch_insights_nginx.py",
    "stager": "stage_reddit_rollback_evidence.py",
}
PRODUCTION_RUNTIME_PREFIX = "/tmp/reddit-voc-insights-rollback-sealed."


class EvidenceStageError(RuntimeError):
    """Fail-closed evidence validation or publication error."""


def _fail(message: str) -> NoReturn:
    raise EvidenceStageError(message)


def _is_sha256(value: str) -> bool:
    return (
        len(value) == SHA256_LENGTH
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _canonical_absolute_path(path: Path, *, label: str) -> Path:
    raw = os.fspath(path)
    if not path.is_absolute() or Path(os.path.abspath(raw)) != path:
        _fail(f"{label}_path_not_absolute_canonical")
    if os.path.realpath(raw) != raw:
        _fail(f"{label}_path_contains_symlink")
    return path


def _read_stable_regular(
    path: Path,
    *,
    label: str,
    exact_mode: int | None,
    max_bytes: int | None,
) -> bytes:
    path = _canonical_absolute_path(path, label=label)
    if not hasattr(os, "O_NOFOLLOW"):
        _fail(f"{label}_nofollow_unavailable")
    try:
        linked = os.lstat(path)
    except OSError as exc:
        raise EvidenceStageError(f"{label}_missing") from exc
    if (
        stat.S_ISLNK(linked.st_mode)
        or not stat.S_ISREG(linked.st_mode)
        or linked.st_nlink != 1
        or linked.st_uid != os.getuid()
    ):
        _fail(f"{label}_metadata_unsafe")
    if exact_mode is None:
        if linked.st_mode & 0o022:
            _fail(f"{label}_mode_unsafe")
    elif stat.S_IMODE(linked.st_mode) != exact_mode:
        _fail(f"{label}_mode_invalid")
    if max_bytes is not None and linked.st_size > max_bytes:
        _fail(f"{label}_too_large")

    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise EvidenceStageError(f"{label}_open_failed") from exc
    try:
        before = os.fstat(descriptor)
        chunks: list[bytes] = []
        length = 0
        while True:
            chunk = os.read(descriptor, CHUNK_BYTES)
            if not chunk:
                break
            length += len(chunk)
            if max_bytes is not None and length > max_bytes:
                _fail(f"{label}_too_large")
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)

    if (
        not stat.S_ISREG(before.st_mode)
        or not stat.S_ISREG(after.st_mode)
        or before.st_nlink != 1
        or after.st_nlink != 1
        or before.st_uid != os.getuid()
        or after.st_uid != os.getuid()
        or (before.st_dev, before.st_ino)
        != (linked.st_dev, linked.st_ino)
        or (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        )
        != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        )
        or length != before.st_size
    ):
        _fail(f"{label}_changed_while_reading")
    if exact_mode is None:
        if before.st_mode & 0o022 or after.st_mode & 0o022:
            _fail(f"{label}_mode_unsafe")
    elif (
        stat.S_IMODE(before.st_mode) != exact_mode
        or stat.S_IMODE(after.st_mode) != exact_mode
    ):
        _fail(f"{label}_mode_changed")
    return b"".join(chunks)


def _canonical_json_bytes(raw: bytes, *, label: str) -> bytes:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=lambda token: _fail(
                f"{label}_nonfinite_json_constant_{token}"
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceStageError(f"{label}_json_invalid") from exc
    if not isinstance(value, dict):
        _fail(f"{label}_json_root_invalid")
    canonical = (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    if raw != canonical:
        _fail(f"{label}_json_noncanonical")
    return canonical


def _canonical_json_document(raw: bytes, *, label: str) -> dict[str, Any]:
    canonical = _canonical_json_bytes(raw, label=label)
    value = json.loads(canonical)
    if not isinstance(value, dict):
        _fail(f"{label}_json_root_invalid")
    return value


def validate_evidence(
    path: Path,
    expected_sha256: str,
    *,
    label: str,
) -> tuple[bytes, str]:
    if not _is_sha256(expected_sha256):
        _fail(f"{label}_sha256_invalid")
    raw = _read_stable_regular(
        path,
        label=label,
        exact_mode=0o600,
        max_bytes=MAX_EVIDENCE_BYTES,
    )
    canonical = _canonical_json_bytes(raw, label=label)
    digest = hashlib.sha256(canonical).hexdigest()
    if digest != expected_sha256:
        _fail(f"{label}_sha256_mismatch")
    return canonical, digest


def hash_runtime(path: Path, expected_sha256: str | None = None) -> str:
    if expected_sha256 is not None and not _is_sha256(expected_sha256):
        _fail("runtime_sha256_invalid")
    raw = _read_stable_regular(
        path,
        label="runtime",
        exact_mode=None,
        max_bytes=None,
    )
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        _fail("runtime_sha256_mismatch")
    return digest


def _open_safe_directory(
    path: Path,
    *,
    label: str,
    exact_mode: int | None,
    expected_uid: int | None = None,
) -> int:
    path = _canonical_absolute_path(path, label=label)
    if not hasattr(os, "O_NOFOLLOW"):
        _fail(f"{label}_nofollow_unavailable")
    try:
        linked = os.lstat(path)
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
    except OSError as exc:
        raise EvidenceStageError(f"{label}_open_failed") from exc
    opened = os.fstat(descriptor)
    owner_uid = os.getuid() if expected_uid is None else expected_uid
    if (
        not stat.S_ISDIR(linked.st_mode)
        or not stat.S_ISDIR(opened.st_mode)
        or (linked.st_dev, linked.st_ino) != (opened.st_dev, opened.st_ino)
        or linked.st_uid != owner_uid
        or opened.st_uid != owner_uid
        or (
            (linked.st_mode & 0o022 or opened.st_mode & 0o022)
            and exact_mode != 0o1777
        )
        or (
            exact_mode is not None
            and (
                stat.S_IMODE(linked.st_mode) != exact_mode
                or stat.S_IMODE(opened.st_mode) != exact_mode
            )
        )
    ):
        os.close(descriptor)
        _fail(f"{label}_metadata_unsafe")
    return descriptor


def _assert_directory_path_identity(
    path: Path,
    descriptor: int,
    *,
    label: str,
    exact_mode: int | None,
    expected_uid: int | None = None,
) -> None:
    owner_uid = os.getuid() if expected_uid is None else expected_uid
    try:
        linked = os.lstat(path)
        opened = os.fstat(descriptor)
    except OSError as exc:
        raise EvidenceStageError(f"{label}_path_identity_changed") from exc
    if (
        not stat.S_ISDIR(linked.st_mode)
        or not stat.S_ISDIR(opened.st_mode)
        or (linked.st_dev, linked.st_ino) != (opened.st_dev, opened.st_ino)
        or linked.st_uid != owner_uid
        or opened.st_uid != owner_uid
        or linked.st_mode & 0o022
        or opened.st_mode & 0o022
        or (
            exact_mode is not None
            and (
                stat.S_IMODE(linked.st_mode) != exact_mode
                or stat.S_IMODE(opened.st_mode) != exact_mode
            )
        )
    ):
        _fail(f"{label}_path_identity_changed")


def _assert_leaf_name(name: str, *, label: str) -> None:
    if (
        not name
        or name in {".", ".."}
        or os.sep in name
        or (os.altsep is not None and os.altsep in name)
    ):
        _fail(f"{label}_name_invalid")


def _read_stable_regular_at(
    directory_descriptor: int,
    name: str,
    *,
    label: str,
    exact_mode: int | None,
    max_bytes: int | None,
    expected_uid: int | None = None,
) -> bytes:
    _assert_leaf_name(name, label=label)
    if not hasattr(os, "O_NOFOLLOW"):
        _fail(f"{label}_nofollow_unavailable")
    try:
        linked = os.stat(
            name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError as exc:
        raise EvidenceStageError(f"{label}_missing") from exc
    except OSError as exc:
        raise EvidenceStageError(f"{label}_stat_failed") from exc
    owner_uid = os.getuid() if expected_uid is None else expected_uid
    if (
        stat.S_ISLNK(linked.st_mode)
        or not stat.S_ISREG(linked.st_mode)
        or linked.st_nlink != 1
        or linked.st_uid != owner_uid
    ):
        _fail(f"{label}_metadata_unsafe")
    if exact_mode is None:
        if linked.st_mode & 0o022:
            _fail(f"{label}_mode_unsafe")
    elif stat.S_IMODE(linked.st_mode) != exact_mode:
        _fail(f"{label}_mode_invalid")
    if max_bytes is not None and linked.st_size > max_bytes:
        _fail(f"{label}_too_large")

    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        descriptor = os.open(
            name,
            flags,
            dir_fd=directory_descriptor,
        )
    except OSError as exc:
        raise EvidenceStageError(f"{label}_open_failed") from exc
    try:
        before = os.fstat(descriptor)
        chunks: list[bytes] = []
        length = 0
        while True:
            chunk = os.read(descriptor, CHUNK_BYTES)
            if not chunk:
                break
            length += len(chunk)
            if max_bytes is not None and length > max_bytes:
                _fail(f"{label}_too_large")
            chunks.append(chunk)
        after = os.fstat(descriptor)
        try:
            current = os.stat(
                name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise EvidenceStageError(f"{label}_changed_while_reading") from exc
    finally:
        os.close(descriptor)

    stable_identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
        before.st_mode,
        before.st_uid,
        before.st_nlink,
    )
    if (
        not stat.S_ISREG(before.st_mode)
        or not stat.S_ISREG(after.st_mode)
        or not stat.S_ISREG(current.st_mode)
        or before.st_nlink != 1
        or after.st_nlink != 1
        or current.st_nlink != 1
        or before.st_uid != owner_uid
        or after.st_uid != owner_uid
        or current.st_uid != owner_uid
        or (linked.st_dev, linked.st_ino)
        != (before.st_dev, before.st_ino)
        or stable_identity
        != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
            after.st_mode,
            after.st_uid,
            after.st_nlink,
        )
        or stable_identity
        != (
            current.st_dev,
            current.st_ino,
            current.st_size,
            current.st_mtime_ns,
            current.st_ctime_ns,
            current.st_mode,
            current.st_uid,
            current.st_nlink,
        )
        or length != before.st_size
    ):
        _fail(f"{label}_changed_while_reading")
    if exact_mode is None:
        if (
            before.st_mode & 0o022
            or after.st_mode & 0o022
            or current.st_mode & 0o022
        ):
            _fail(f"{label}_mode_unsafe")
    elif (
        stat.S_IMODE(before.st_mode) != exact_mode
        or stat.S_IMODE(after.st_mode) != exact_mode
        or stat.S_IMODE(current.st_mode) != exact_mode
    ):
        _fail(f"{label}_mode_changed")
    return b"".join(chunks)


def _validate_evidence_at(
    directory_descriptor: int,
    name: str,
    expected_sha256: str,
    *,
    label: str,
) -> tuple[bytes, str]:
    if not _is_sha256(expected_sha256):
        _fail(f"{label}_sha256_invalid")
    raw = _read_stable_regular_at(
        directory_descriptor,
        name,
        label=label,
        exact_mode=0o600,
        max_bytes=MAX_EVIDENCE_BYTES,
    )
    canonical = _canonical_json_bytes(raw, label=label)
    digest = hashlib.sha256(canonical).hexdigest()
    if digest != expected_sha256:
        _fail(f"{label}_sha256_mismatch")
    return canonical, digest


def _parse_utc(value: object, *, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        _fail(f"{label}_timestamp_invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise EvidenceStageError(f"{label}_timestamp_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        _fail(f"{label}_timestamp_invalid")
    return parsed


def _require_mapping(value: object, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{label}_invalid")
    return value


def _has_action(value: object, *, label: str) -> None:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) for item in value)
        or PERSIST_ACTION not in value
    ):
        _fail(f"{label}_missing_{PERSIST_ACTION}")


def validate_authority_bundle(
    *,
    documents: Mapping[str, tuple[bytes, str]],
    expected_current_release: str,
    target_release: str,
    expected_current_data_release: str,
    expected_current_data_pointer_sha: str,
    target_data_release: str,
    target_data_pointer_sha: str,
    runner_sha: str,
    now_utc: str | None = None,
) -> None:
    """Cross-bind all rollback authority before any evidence publication."""

    for label, digest in (
        ("expected_current_release", expected_current_release),
        ("target_release", target_release),
        (
            "expected_current_data_pointer_sha",
            expected_current_data_pointer_sha,
        ),
        ("target_data_pointer_sha", target_data_pointer_sha),
        ("runner_sha", runner_sha),
    ):
        if not _is_sha256(digest):
            _fail(f"{label}_invalid")
    for label, release_id in (
        ("expected_current_data_release", expected_current_data_release),
        ("target_data_release", target_data_release),
    ):
        if (
            not isinstance(release_id, str)
            or not release_id.startswith("reddit_voc_release_")
            or any(
                character not in "abcdefghijklmnopqrstuvwxyz0123456789_-"
                for character in release_id
            )
        ):
            _fail(f"{label}_invalid")

    expected_labels = set(EVIDENCE_NAMES)
    if set(documents) != expected_labels:
        _fail("authority_document_set_invalid")
    packet_raw, packet_sha = documents["authorization_packet"]
    permit_raw, _permit_sha = documents["authorization_permit"]
    baseline_raw, baseline_sha = documents["production_baseline"]
    packet = _canonical_json_document(
        packet_raw,
        label="authorization_packet",
    )
    permit = _canonical_json_document(
        permit_raw,
        label="authorization_permit",
    )
    baseline = _canonical_json_document(
        baseline_raw,
        label="production_baseline",
    )

    target = _require_mapping(packet.get("target"), label="packet_target")
    rollback = _require_mapping(
        packet.get("rollback"),
        label="packet_rollback",
    )
    authorization = _require_mapping(
        packet.get("authorization"),
        label="packet_authorization",
    )
    artifacts = _require_mapping(
        packet.get("artifacts"),
        label="packet_artifacts",
    )
    baseline_record = _require_mapping(
        artifacts.get("production_baseline_receipt"),
        label="packet_baseline_artifact",
    )
    execution_runtime = _require_mapping(
        packet.get("execution_runtime"),
        label="packet_execution_runtime",
    )
    rollback_runtime = _require_mapping(
        execution_runtime.get("remote_rollback"),
        label="packet_rollback_runtime",
    )
    if (
        packet.get("schema_version") != "reddit_voc_promotion_packet_v4"
        or packet.get("status") != "ready_for_owner_authorization"
        or target.get("release_sha256") != expected_current_release
        or target.get("expected_current_release_sha256") != target_release
        or target.get("data_release_id") != expected_current_data_release
        or target.get("target_data_pointer_sha256")
        != expected_current_data_pointer_sha
        or target.get("expected_current_data_release_id")
        != target_data_release
        or target.get("expected_current_data_pointer_sha256")
        != target_data_pointer_sha
        or rollback.get("ready") is not True
        or rollback.get("readiness_mode")
        != "immediate_same_baseline_window"
        or rollback.get("scope") != "insights_site_and_data_current"
        or rollback.get("shared_nginx_change_allowed") is not False
        or rollback.get("target_release_sha256") != target_release
        or rollback.get("target_data_release_id") != target_data_release
        or rollback.get("target_data_pointer_sha256")
        != target_data_pointer_sha
        or rollback.get("valid_until_utc") != packet.get("expires_at_utc")
        or authorization.get("permit_required") is not True
        or authorization.get("consumed") is not False
        or authorization.get("promotion_authorized") is not False
        or authorization.get("allowed_actions") != list(ALLOWED_ACTIONS)
        or authorization.get("forbidden_actions") != list(FORBIDDEN_ACTIONS)
        or baseline_record.get("sha256") != baseline_sha
        or rollback_runtime.get("sha256") != runner_sha
    ):
        _fail("authorization_packet_cross_binding_invalid")
    permit_packet = _require_mapping(
        permit.get("packet"),
        label="permit_packet",
    )
    permit_authorization = _require_mapping(
        permit.get("authorization"),
        label="permit_authorization",
    )
    if (
        permit.get("schema_version") != "reddit_voc_promotion_permit_v1"
        or permit.get("status") != "authorized_unconsumed"
        or permit.get("consumed") is not False
        or permit.get("contract")
        != "reddit_voc_promotion_permit_exact_binding_v4"
        or permit.get("scope") != "insights_site_and_data_current"
        or permit.get("packet_sha256") != packet_sha
        or permit.get("release_sha256") != expected_current_release
        or permit.get("packet_id") != packet.get("packet_id")
        or permit_packet.get("packet_sha256") != packet_sha
        or permit_packet.get("packet_id") != packet.get("packet_id")
        or permit_packet.get("nonce") != packet.get("nonce")
        or permit_packet.get("release_sha256") != expected_current_release
        or permit_packet.get("expected_current_release_sha256")
        != target_release
        or permit_packet.get("data_release_id")
        != expected_current_data_release
        or permit_packet.get("target_data_pointer_sha256")
        != expected_current_data_pointer_sha
        or permit_packet.get("expected_current_data_release_id")
        != target_data_release
        or permit_packet.get("expected_current_data_pointer_sha256")
        != target_data_pointer_sha
        or permit_packet.get("expires_at_utc")
        != packet.get("expires_at_utc")
        or permit_packet.get("execution_runtime") != execution_runtime
        or permit_authorization.get("authorized_by")
        != "owner_explicit_confirmation"
        or permit_authorization.get("owner_confirmation")
        != "authorize_exact_reddit_voc_packet_and_release"
        or permit.get("authorized_actions") != list(ALLOWED_ACTIONS)
        or permit.get("forbidden_actions") != list(FORBIDDEN_ACTIONS)
        or permit_authorization.get("authorized_actions")
        != list(ALLOWED_ACTIONS)
        or permit_authorization.get("forbidden_actions")
        != list(FORBIDDEN_ACTIONS)
    ):
        _fail("authorization_permit_cross_binding_invalid")

    observations = _require_mapping(
        baseline.get("observations"),
        label="baseline_observations",
    )
    insights = _require_mapping(
        observations.get("insights"),
        label="baseline_insights",
    )
    site_tuple = _require_mapping(
        observations.get("site_data_tuple"),
        label="baseline_site_data_tuple",
    )
    if (
        baseline.get("schema_version")
        != "reddit_voc_production_baseline_receipt_v1"
        or baseline.get("status") != "passed"
        or baseline.get("evidence_grade") != "L3-production-read-only"
        or baseline.get("production_unchanged") is not True
        or baseline.get("remote_write") is not False
        or baseline.get("current_release_sha256") != target_release
        or insights.get("release_label") != target_release
        or insights.get("internal_release_sha256") != target_release
        or insights.get("internal_pointer") != target_data_release
        or insights.get("internal_pointer_sha256") != target_data_pointer_sha
        or site_tuple.get("site_release_sha256") != target_release
        or site_tuple.get("data_release_id") != target_data_release
        or site_tuple.get("pointer_sha256") != target_data_pointer_sha
    ):
        _fail("production_baseline_cross_binding_invalid")

    packet_generated = _parse_utc(
        packet.get("generated_at_utc"),
        label="packet_generated",
    )
    packet_expiry = _parse_utc(
        packet.get("expires_at_utc"),
        label="packet_expiry",
    )
    permit_authorized = _parse_utc(
        permit.get("authorized_recorded_at_utc"),
        label="permit_authorized",
    )
    permit_expiry = _parse_utc(
        permit.get("expires_at_utc"),
        label="permit_expiry",
    )
    nested_authorized = _parse_utc(
        permit_authorization.get("authorized_at_utc"),
        label="permit_nested_authorized",
    )
    baseline_observed = _parse_utc(
        baseline.get("observed_at_utc"),
        label="baseline_observed",
    )
    now = (
        datetime.now(timezone.utc)
        if now_utc is None
        else _parse_utc(now_utc, label="authority_validation_now")
    )
    evidence = _require_mapping(
        packet.get("evidence"),
        label="packet_evidence",
    )
    baseline_max_age = evidence.get("baseline_max_age_seconds")
    if (
        type(baseline_max_age) is not int
        or baseline_max_age <= 0
        or nested_authorized != permit_authorized
        or baseline_observed > packet_generated
        or (packet_generated - baseline_observed).total_seconds()
        > baseline_max_age
        or packet_generated > permit_authorized
        or permit_authorized > now
        or now >= packet_expiry
        or now >= permit_expiry
        or permit_expiry > packet_expiry
    ):
        _fail("authority_time_binding_invalid")


def _entry_exists_at(
    directory_descriptor: int,
    name: str,
    *,
    label: str,
) -> bool:
    _assert_leaf_name(name, label=label)
    try:
        os.stat(
            name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise EvidenceStageError(f"{label}_lookup_failed") from exc


def _rename_noreplace(
    directory_descriptor: int,
    source_name: str,
    destination_name: str,
) -> None:
    _assert_leaf_name(source_name, label="rename_source")
    _assert_leaf_name(destination_name, label="rename_destination")
    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source_name)
    destination_bytes = os.fsencode(destination_name)
    if sys.platform.startswith("linux"):
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            _fail("rename_noreplace_unavailable")
        renameat2.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        renameat2.restype = ctypes.c_int
        result = renameat2(
            directory_descriptor,
            source_bytes,
            directory_descriptor,
            destination_bytes,
            1,
        )
    elif sys.platform == "darwin":
        renameatx_np = getattr(libc, "renameatx_np", None)
        if renameatx_np is None:
            _fail("rename_noreplace_unavailable")
        renameatx_np.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        renameatx_np.restype = ctypes.c_int
        result = renameatx_np(
            directory_descriptor,
            source_bytes,
            directory_descriptor,
            destination_bytes,
            0x00000004,
        )
    else:
        _fail("rename_noreplace_unavailable")
    if result == 0:
        return
    error = ctypes.get_errno()
    if error == errno.EEXIST:
        raise FileExistsError(error, os.strerror(error), destination_name)
    raise OSError(error, os.strerror(error), destination_name)


def _assert_direct_child(path: Path, root: Path, *, label: str) -> None:
    path = _canonical_absolute_path(path, label=label)
    if path.parent != root:
        _fail(f"{label}_escaped_staging_root")


def runtime_bundle_sha256(runtime_shas: Mapping[str, str]) -> str:
    if set(runtime_shas) != set(RUNTIME_NAMES):
        _fail("runtime_bundle_set_invalid")
    digest = hashlib.sha256()
    for label in sorted(RUNTIME_NAMES):
        value = runtime_shas[label]
        if not _is_sha256(value):
            _fail(f"runtime_{label}_sha256_invalid")
        digest.update(label.encode("ascii"))
        digest.update(b"\0")
        digest.update(RUNTIME_NAMES[label].encode("ascii"))
        digest.update(b"\0")
        digest.update(value.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _runtime_bundle_path(
    runtime_root: Path,
    bundle_sha: str,
    *,
    production_contract: bool,
) -> Path:
    if not _is_sha256(bundle_sha):
        _fail("runtime_bundle_sha256_invalid")
    runtime_root = _canonical_absolute_path(
        runtime_root,
        label="runtime_bundle",
    )
    if production_contract:
        expected = Path(PRODUCTION_RUNTIME_PREFIX + bundle_sha)
        if runtime_root != expected:
            _fail("runtime_bundle_path_invalid")
    return runtime_root


def verify_runtime_bundle(
    *,
    runtime_root: Path,
    runtime_shas: Mapping[str, str],
    expected_owner_uid: int,
    production_contract: bool = False,
) -> Path:
    bundle_sha = runtime_bundle_sha256(runtime_shas)
    runtime_root = _runtime_bundle_path(
        runtime_root,
        bundle_sha,
        production_contract=production_contract,
    )
    descriptor = _open_safe_directory(
        runtime_root,
        label="runtime_bundle",
        exact_mode=0o555,
        expected_uid=expected_owner_uid,
    )
    try:
        names = set(os.listdir(descriptor))
        if names != set(RUNTIME_NAMES.values()):
            _fail("runtime_bundle_file_set_invalid")
        for label, name in RUNTIME_NAMES.items():
            raw = _read_stable_regular_at(
                descriptor,
                name,
                label=f"runtime_{label}",
                exact_mode=0o555,
                max_bytes=None,
                expected_uid=expected_owner_uid,
            )
            if hashlib.sha256(raw).hexdigest() != runtime_shas[label]:
                _fail(f"runtime_{label}_sha256_mismatch")
        os.fsync(descriptor)
        _assert_directory_path_identity(
            runtime_root,
            descriptor,
            label="runtime_bundle",
            exact_mode=0o555,
            expected_uid=expected_owner_uid,
        )
    finally:
        os.close(descriptor)
    return runtime_root


def _remove_runtime_temporary(
    parent_descriptor: int,
    temporary_name: str,
) -> None:
    try:
        descriptor = os.open(
            temporary_name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=parent_descriptor,
        )
    except FileNotFoundError:
        return
    try:
        for name in os.listdir(descriptor):
            _assert_leaf_name(name, label="runtime_cleanup")
            os.unlink(name, dir_fd=descriptor)
    finally:
        os.close(descriptor)
    os.rmdir(temporary_name, dir_fd=parent_descriptor)


def seal_runtime_bundle(
    *,
    staging_root: Path,
    runtime_root: Path,
    sources: Mapping[str, tuple[Path, str]],
    source_owner_uid: int,
    sealed_owner_uid: int,
    production_contract: bool = False,
) -> Path:
    runtime_shas = {
        label: digest
        for label, (_source, digest) in sources.items()
    }
    bundle_sha = runtime_bundle_sha256(runtime_shas)
    runtime_root = _runtime_bundle_path(
        runtime_root,
        bundle_sha,
        production_contract=production_contract,
    )
    if set(sources) != set(RUNTIME_NAMES):
        _fail("runtime_source_set_invalid")
    parent = runtime_root.parent
    if production_contract and parent != Path("/tmp"):
        _fail("runtime_bundle_parent_invalid")
    parent_descriptor = _open_safe_directory(
        parent,
        label="runtime_parent",
        exact_mode=0o1777 if production_contract else None,
        expected_uid=sealed_owner_uid,
    )
    staging_descriptor = _open_safe_directory(
        staging_root,
        label="runtime_staging_root",
        exact_mode=0o700,
        expected_uid=source_owner_uid,
    )
    destination_name = runtime_root.name
    temporary_name = (
        f".{destination_name}.tmp-{os.getpid()}-{secrets.token_hex(8)}"
    )
    try:
        payloads: dict[str, bytes] = {}
        for label, (source, expected_sha) in sources.items():
            _assert_direct_child(
                source,
                staging_root,
                label=f"runtime_{label}",
            )
            if source.name != RUNTIME_NAMES[label]:
                _fail(f"runtime_{label}_source_name_invalid")
            payload = _read_stable_regular_at(
                staging_descriptor,
                source.name,
                label=f"runtime_{label}",
                exact_mode=0o700,
                max_bytes=None,
                expected_uid=source_owner_uid,
            )
            if hashlib.sha256(payload).hexdigest() != expected_sha:
                _fail(f"runtime_{label}_sha256_mismatch")
            payloads[label] = payload
        os.fsync(staging_descriptor)

        if _entry_exists_at(
            parent_descriptor,
            destination_name,
            label="existing_runtime_bundle",
        ):
            return verify_runtime_bundle(
                runtime_root=runtime_root,
                runtime_shas=runtime_shas,
                expected_owner_uid=sealed_owner_uid,
                production_contract=production_contract,
            )

        os.mkdir(
            temporary_name,
            mode=0o700,
            dir_fd=parent_descriptor,
        )
        temporary_descriptor = os.open(
            temporary_name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=parent_descriptor,
        )
        try:
            for label, name in RUNTIME_NAMES.items():
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                if hasattr(os, "O_CLOEXEC"):
                    flags |= os.O_CLOEXEC
                descriptor = os.open(
                    name,
                    flags,
                    0o555,
                    dir_fd=temporary_descriptor,
                )
                try:
                    os.fchmod(descriptor, 0o555)
                    payload = payloads[label]
                    offset = 0
                    while offset < len(payload):
                        written = os.write(descriptor, payload[offset:])
                        if written <= 0:
                            _fail(f"runtime_{label}_write_failed")
                        offset += written
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            os.fchmod(temporary_descriptor, 0o555)
            os.fsync(temporary_descriptor)
        finally:
            os.close(temporary_descriptor)
        try:
            _rename_noreplace(
                parent_descriptor,
                temporary_name,
                destination_name,
            )
        except FileExistsError:
            _remove_runtime_temporary(
                parent_descriptor,
                temporary_name,
            )
        os.fsync(parent_descriptor)
        return verify_runtime_bundle(
            runtime_root=runtime_root,
            runtime_shas=runtime_shas,
            expected_owner_uid=sealed_owner_uid,
            production_contract=production_contract,
        )
    finally:
        try:
            _remove_runtime_temporary(
                parent_descriptor,
                temporary_name,
            )
        except FileNotFoundError:
            pass
        os.close(staging_descriptor)
        os.close(parent_descriptor)


def _publish_one(
    root: Path,
    root_descriptor: int,
    *,
    label: str,
    prefix: str,
    payload: bytes,
    digest: str,
) -> Path:
    destination_name = f"{prefix}-{digest}.json"
    temporary_name = (
        f".{prefix}-{digest}.tmp-{os.getpid()}-{secrets.token_hex(8)}"
    )
    _assert_directory_path_identity(
        root,
        root_descriptor,
        label="evidence_root",
        exact_mode=None,
    )
    if _entry_exists_at(
        root_descriptor,
        destination_name,
        label=f"existing_{label}",
    ):
        existing, existing_digest = _validate_evidence_at(
            root_descriptor,
            destination_name,
            digest,
            label=f"existing_{label}",
        )
        if existing != payload or existing_digest != digest:
            _fail(f"{label}_immutable_collision")
        os.fsync(root_descriptor)
        _assert_directory_path_identity(
            root,
            root_descriptor,
            label="evidence_root",
            exact_mode=None,
        )
        return root / destination_name

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = os.open(
        temporary_name,
        flags,
        0o600,
        dir_fd=root_descriptor,
    )
    try:
        os.fchmod(descriptor, 0o600)
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                _fail(f"{label}_temporary_write_failed")
            offset += written
        os.fsync(descriptor)
        temporary_metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(temporary_metadata.st_mode)
            or temporary_metadata.st_nlink != 1
            or temporary_metadata.st_uid != os.getuid()
            or stat.S_IMODE(temporary_metadata.st_mode) != 0o600
            or temporary_metadata.st_size != len(payload)
        ):
            _fail(f"{label}_temporary_metadata_unsafe")
    finally:
        os.close(descriptor)
    try:
        _assert_directory_path_identity(
            root,
            root_descriptor,
            label="evidence_root",
            exact_mode=None,
        )
        try:
            _rename_noreplace(
                root_descriptor,
                temporary_name,
                destination_name,
            )
        except FileExistsError:
            existing, existing_digest = _validate_evidence_at(
                root_descriptor,
                destination_name,
                digest,
                label=f"existing_{label}",
            )
            if existing != payload or existing_digest != digest:
                _fail(f"{label}_immutable_collision")
        os.fsync(root_descriptor)
        _assert_directory_path_identity(
            root,
            root_descriptor,
            label="evidence_root",
            exact_mode=None,
        )
        final, final_digest = _validate_evidence_at(
            root_descriptor,
            destination_name,
            digest,
            label=f"persisted_{label}",
        )
        if final != payload or final_digest != digest:
            _fail(f"{label}_final_verification_failed")
        _assert_directory_path_identity(
            root,
            root_descriptor,
            label="evidence_root",
            exact_mode=None,
        )
        return root / destination_name
    finally:
        try:
            os.unlink(temporary_name, dir_fd=root_descriptor)
        except FileNotFoundError:
            pass


def persist_evidence(
    *,
    staging_root: Path,
    evidence_root: Path,
    sources: dict[str, tuple[Path, str]],
    expected_current_release: str,
    target_release: str,
    expected_current_data_release: str,
    expected_current_data_pointer_sha: str,
    target_data_release: str,
    target_data_pointer_sha: str,
    runner_sha: str,
    now_utc: str | None = None,
) -> dict[str, Path]:
    staging_root = _canonical_absolute_path(
        staging_root,
        label="staging_root",
    )
    evidence_root = _canonical_absolute_path(
        evidence_root,
        label="evidence_root",
    )
    staging_descriptor = _open_safe_directory(
        staging_root,
        label="staging_root",
        exact_mode=0o700,
    )
    evidence_descriptor = _open_safe_directory(
        evidence_root,
        label="evidence_root",
        exact_mode=None,
    )
    try:
        validated: dict[str, tuple[bytes, str]] = {}
        for label in EVIDENCE_NAMES:
            source, expected_sha = sources[label]
            _assert_direct_child(source, staging_root, label=label)
            validated[label] = _validate_evidence_at(
                staging_descriptor,
                source.name,
                expected_sha,
                label=label,
            )
        os.fsync(staging_descriptor)
        validate_authority_bundle(
            documents=validated,
            expected_current_release=expected_current_release,
            target_release=target_release,
            expected_current_data_release=expected_current_data_release,
            expected_current_data_pointer_sha=expected_current_data_pointer_sha,
            target_data_release=target_data_release,
            target_data_pointer_sha=target_data_pointer_sha,
            runner_sha=runner_sha,
            now_utc=now_utc,
        )
        output: dict[str, Path] = {}
        for label, prefix in EVIDENCE_NAMES.items():
            payload, digest = validated[label]
            output[label] = _publish_one(
                evidence_root,
                evidence_descriptor,
                label=label,
                prefix=prefix,
                payload=payload,
                digest=digest,
            )
        os.fsync(evidence_descriptor)
        _assert_directory_path_identity(
            evidence_root,
            evidence_descriptor,
            label="evidence_root",
            exact_mode=None,
        )
        return output
    finally:
        os.close(evidence_descriptor)
        os.close(staging_descriptor)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate")
    validate.add_argument("--path", type=Path, required=True)
    validate.add_argument("--expected-sha", required=True)
    validate.add_argument(
        "--label",
        choices=tuple(EVIDENCE_NAMES),
        required=True,
    )

    runtime = commands.add_parser("hash-runtime")
    runtime.add_argument("--path", type=Path, required=True)
    runtime.add_argument("--expected-sha")

    bundle_id = commands.add_parser("bundle-id")
    for label in RUNTIME_NAMES:
        bundle_id.add_argument(f"--{label}-sha", required=True)

    seal = commands.add_parser("seal-runtime")
    seal.add_argument("--staging-root", type=Path, required=True)
    seal.add_argument("--runtime-root", type=Path, required=True)
    seal.add_argument("--source-owner", required=True)
    for label in RUNTIME_NAMES:
        seal.add_argument(f"--{label}-source", type=Path, required=True)
        seal.add_argument(f"--{label}-sha", required=True)

    verify_runtime = commands.add_parser("verify-runtime-bundle")
    verify_runtime.add_argument("--runtime-root", type=Path, required=True)
    for label in RUNTIME_NAMES:
        verify_runtime.add_argument(f"--{label}-sha", required=True)

    def add_authority_bindings(command: argparse.ArgumentParser) -> None:
        command.add_argument("--expected-current-release", required=True)
        command.add_argument("--target-release", required=True)
        command.add_argument(
            "--expected-current-data-release",
            required=True,
        )
        command.add_argument(
            "--expected-current-data-pointer-sha",
            required=True,
        )
        command.add_argument("--target-data-release", required=True)
        command.add_argument("--target-data-pointer-sha", required=True)
        command.add_argument("--runner-sha", required=True)
        command.add_argument("--now-utc")

    validate_bundle = commands.add_parser("validate-authority-bundle")
    for label in EVIDENCE_NAMES:
        option = label.replace("_", "-")
        validate_bundle.add_argument(
            f"--{option}-source",
            type=Path,
            required=True,
        )
        validate_bundle.add_argument(f"--{option}-sha", required=True)
    add_authority_bindings(validate_bundle)

    persist = commands.add_parser("persist")
    persist.add_argument("--staging-root", type=Path, required=True)
    persist.add_argument("--evidence-root", type=Path, required=True)
    for label in EVIDENCE_NAMES:
        option = label.replace("_", "-")
        persist.add_argument(f"--{option}-source", type=Path, required=True)
        persist.add_argument(f"--{option}-sha", required=True)
    add_authority_bindings(persist)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "validate":
            _, digest = validate_evidence(
                args.path,
                args.expected_sha,
                label=args.label,
            )
            print(digest)
            return 0
        if args.command == "hash-runtime":
            print(hash_runtime(args.path, args.expected_sha))
            return 0
        if args.command == "bundle-id":
            runtime_shas = {
                label: getattr(args, f"{label}_sha")
                for label in RUNTIME_NAMES
            }
            print(runtime_bundle_sha256(runtime_shas))
            return 0
        if args.command == "seal-runtime":
            if os.geteuid() != 0:
                _fail("seal_runtime_requires_root")
            try:
                source_owner_uid = pwd.getpwnam(args.source_owner).pw_uid
            except KeyError as exc:
                raise EvidenceStageError(
                    "runtime_source_owner_unknown"
                ) from exc
            sources = {
                label: (
                    getattr(args, f"{label}_source"),
                    getattr(args, f"{label}_sha"),
                )
                for label in RUNTIME_NAMES
            }
            output = seal_runtime_bundle(
                staging_root=args.staging_root,
                runtime_root=args.runtime_root,
                sources=sources,
                source_owner_uid=source_owner_uid,
                sealed_owner_uid=0,
                production_contract=True,
            )
            print(output)
            return 0
        if args.command == "verify-runtime-bundle":
            runtime_shas = {
                label: getattr(args, f"{label}_sha")
                for label in RUNTIME_NAMES
            }
            print(
                verify_runtime_bundle(
                    runtime_root=args.runtime_root,
                    runtime_shas=runtime_shas,
                    expected_owner_uid=0,
                    production_contract=True,
                )
            )
            return 0
        sources = {
            label: (
                getattr(args, f"{label}_source"),
                getattr(args, f"{label}_sha"),
            )
            for label in EVIDENCE_NAMES
        }
        bindings = {
            "expected_current_release": args.expected_current_release,
            "target_release": args.target_release,
            "expected_current_data_release": (
                args.expected_current_data_release
            ),
            "expected_current_data_pointer_sha": (
                args.expected_current_data_pointer_sha
            ),
            "target_data_release": args.target_data_release,
            "target_data_pointer_sha": args.target_data_pointer_sha,
            "runner_sha": args.runner_sha,
            "now_utc": args.now_utc,
        }
        if args.command == "validate-authority-bundle":
            validated = {
                label: validate_evidence(
                    source,
                    expected_sha,
                    label=label,
                )
                for label, (source, expected_sha) in sources.items()
            }
            validate_authority_bundle(
                documents=validated,
                **bindings,
            )
            print("authority_bundle_valid")
            return 0
        output = persist_evidence(
            staging_root=args.staging_root,
            evidence_root=args.evidence_root,
            sources=sources,
            **bindings,
        )
        for label in EVIDENCE_NAMES:
            print(f"{label}\t{output[label]}")
        return 0
    except EvidenceStageError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
