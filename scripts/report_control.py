from __future__ import annotations

import argparse
import fcntl
import getpass
import hashlib
import importlib
import json
import os
import pwd
import re
import secrets
import subprocess
import stat
import sys
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Iterator, Mapping, Sequence
from zoneinfo import ZoneInfo


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VERSION_ID = re.compile(r"^[0-9]{8}T[0-9]{12}Z-[0-9a-f]{32}$")
_TERMINAL_STATUSES = frozenset(
    {
        "consumed",
        "partial",
        "closed_no_attempt",
        "blocked",
        "unknown",
        "revoked",
    }
)
_LEGACY_DAILY_POLICY_SHA256 = (
    "b22a4e29bd055db1c67f82a7974fd01513a57f293454d042d896047a4942bb2f"
)
_G6R5_DAILY_POLICY_SHA256 = (
    "98cbdd40b6b7ce06b15c5fd73d6f9a9329c22fc8f78cf6df114fcff3764c3cb4"
)
_G6R1_FIRST_REPORT_DATE = date(2026, 8, 12)
_G6R1_LAST_REPORT_DATE = date(2026, 8, 31)
_G6R1_MAX_SLOTS = 20
_G6R5_FIRST_REPORT_DATE = date(2026, 8, 22)
_G6R5_LAST_REPORT_DATE = date(2027, 8, 21)
_G6R5_MAX_SLOTS = 365
_G6R1_LOCAL_TIME = time(8, 0)
_G6R1_EXECUTION_WINDOW_MINUTES = 5
_G6R1_SEND_WINDOW_END = time(8, 30)
_G6R1_TIMEZONE = ZoneInfo("Asia/Shanghai")
_G6R1_PROVIDER_ATTEMPT_POLICY = {
    "model": "deepseek-v4-flash",
    "deadline_seconds": 300,
    "request_timeout_seconds": 45,
    "max_retries_per_request": 2,
    "retryable_http_statuses": [429, 500, 503],
    "retryable_terminal_outcomes": [
        "empty_response",
        "insufficient_system_resource",
    ],
    "retry_transport_errors": False,
    "max_attempts_per_cycle": 100,
    "max_attempts_total": 2_000,
    "cross_process_retry": False,
}
_G6R5_PROVIDER_ATTEMPT_POLICY = {
    **_G6R1_PROVIDER_ATTEMPT_POLICY,
    "max_attempts_total": 36_500,
}
_LEGACY_DAILY_POLICY_PATH = Path(
    "/home/ubuntu/.reddit-voc/report-control/task32aa-daily-live-policy.json"
)
_G6R5_DAILY_POLICY_PATH = Path(
    "/opt/reddit-voc-daily-report/control/authority/"
    "g6r5-annual-daily-live-policy.json"
)
_G6R1_SCHEDULED_POLICY_PATH = Path(
    "/opt/reddit-voc-daily-report/control/authority/"
    "g6r1-scheduled-cycle-policy.json"
)
_G6R1_ROTATION_RECEIPT_PATH = Path(
    "/opt/reddit-voc-daily-report/control/authority/"
    "g6r1-credential-rotation-receipt.json"
)
_G6R1_REPORT_ENV_INSTALL_RECEIPT_PATH = Path(
    "/opt/reddit-voc-daily-report/control/authority/"
    "g6r1-report-env-install-receipt.json"
)
_G6R1_DUAL_CREDENTIAL_SET_RECEIPT_PATH = Path(
    "/opt/reddit-voc-daily-report/control/authority/"
    "g6r1-dual-credential-set-receipt.json"
)
_G6R1_DUAL_REPORT_ENV_INSTALL_RECEIPT_PATH = Path(
    "/opt/reddit-voc-daily-report/control/authority/"
    "g6r1-dual-report-env-install-receipt.json"
)
_G6R1_TRANSACTIONS_ROOT = Path(
    "/opt/reddit-voc-daily-report/control/transactions"
)
_G6R1_ACTIVATION_MARKER_PATH = Path(
    "/opt/reddit-voc-daily-report/control/authority/"
    "g6r1-terminal-activation.json"
)
_G6R1_OWNER_POLICY_PERMIT_PATH = Path(
    "/opt/reddit-voc-daily-report/control/authority/g6r1-owner-policy-permit.json"
)
_G6R1_SECONDARY_DISPOSITION_PATH = Path(
    "/opt/reddit-voc-daily-report/control/g6r1-secondary-disposition.json"
)
_G6R1_PRIMARY_CRON_PATH = Path("/etc/cron.d/reddit-voc-site")
_G6R1_STABLE_ENTRYPOINT_PATH = Path(
    "/opt/reddit-voc-daily-report/control/bin/g6r1_stable_launcher.py"
)
_G6R1_REPORT_ENV_PATH = Path(
    "/home/ubuntu/.reddit-voc/secrets/reddit-voc-report.env"
)
_DAILY_REPORT_LOCK_PATH = Path(
    "/opt/reddit-voc-daily-report/control/locks/daily-report.lock"
)
_G6R1_PRIMARY_CRON_LINE = (
    "0 8 * * * ubuntu /usr/bin/env -i PATH=/usr/bin:/bin "
    "HOME=/home/ubuntu LANG=C.UTF-8 /usr/bin/python3 "
    "/opt/reddit-voc-daily-report/control/bin/g6r1_stable_launcher.py "
    "scheduled-cycle >> /opt/reddit-voc-site/logs/cron-report.log 2>&1"
)
_G6R1_LEGACY_SCRIPT_PATH = (
    "/home/ubuntu/.reddit-voc/forward_dingtalk_secondary.py"
)
_G6R1_LEGACY_CRON_LINE = (
    "10 8 * * * /usr/bin/python3 "
    "/home/ubuntu/.reddit-voc/forward_dingtalk_secondary.py >> "
    "/home/ubuntu/.reddit-voc/secondary-forward.log 2>&1"
)
_G6R1_DUAL_DESTINATION_SET_ID = "HighValueAssetDual"
_G6R1_DUAL_DESTINATIONS = (
    ("primary", "HighValueAsset"),
    ("secondary", "HighValueAssetSecondary"),
)
_G6R1_SECONDARY_DISPOSITION_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "legacy_script_path",
        "legacy_cron_token",
        "legacy_process_token",
        "secondary_sender_retired",
        "credential_output",
    }
)
_LEGACY_POLICY_KEYS = frozenset(
    {
        "schema_version",
        "policy_id",
        "cadence",
        "starts_at_utc",
        "expires_at_utc",
        "max_scheduled_runs",
        "destination_fingerprint",
        "required_keyword",
    }
)
_G6R5_POLICY_KEYS = frozenset(
    {
        "schema_version",
        "policy_id",
        "authorization_id",
        "status",
        "cadence",
        "timezone",
        "scheduled_local_time",
        "starts_at_utc",
        "expires_at_utc",
        "max_scheduled_runs",
        "destination_set_id",
        "destinations",
        "required_keyword",
        "provider_prepare",
        "live_send",
        "automatic_resend",
    }
)
_SCHEDULED_POLICY_KEYS = frozenset(
    {
        "schema_version",
        "policy_id",
        "authorization_id",
        "parent_policy_sha256",
        "report_release_sha256",
        "stable_entrypoint_sha256",
        "release_launcher_sha256",
        "cadence",
        "timezone",
        "scheduled_local_time",
        "starts_at_utc",
        "expires_at_utc",
        "max_slots",
        "credential_epoch_id",
        "destination_alias",
        "required_keyword",
        "credential_rotation_receipt_sha256",
        "secondary_sender_retired",
        "provider_attempt_policy",
        "slots",
    }
)
_SCHEDULED_POLICY_V2_KEYS = frozenset(
    {
        "schema_version",
        "policy_id",
        "authorization_id",
        "parent_policy_sha256",
        "report_release_sha256",
        "stable_entrypoint_sha256",
        "release_launcher_sha256",
        "cadence",
        "timezone",
        "scheduled_local_time",
        "starts_at_utc",
        "expires_at_utc",
        "max_slots",
        "credential_set_epoch_id",
        "destination_set_id",
        "destinations",
        "required_keyword",
        "credential_set_receipt_sha256",
        "secondary_sender_retired",
        "provider_attempt_policy",
        "slots",
    }
)
_SCHEDULED_POLICY_V3_KEYS = _SCHEDULED_POLICY_V2_KEYS | frozenset(
    {"automatic_resend"}
)
_ROTATION_RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "rotated_at_utc",
        "credential_epoch_id",
        "destination_alias",
        "secondary_sender_retired",
        "credential_output",
        "live_send",
        "old_credential_revoked",
        "new_credential_installed",
        "authority_event_id",
        "authority_kind",
        "scheduler_writable",
        "report_env_install_receipt_sha256",
    }
)
_REPORT_ENV_INSTALL_RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "report_env_path",
        "device_id",
        "inode_id",
        "owner_uid",
        "owner_gid",
        "mode",
        "credential_epoch_id",
        "destination_alias",
        "authority_event_id",
        "authority_kind",
        "credential_output",
        "live_send",
    }
)
_DUAL_REPORT_ENV_INSTALL_RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "report_env_path",
        "device_id",
        "inode_id",
        "owner_uid",
        "owner_gid",
        "mode",
        "credential_set_epoch_id",
        "destination_set_id",
        "destinations",
        "authority_event_id",
        "authority_kind",
        "credential_output",
        "live_send",
    }
)
_DUAL_CREDENTIAL_SET_RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "installed_at_utc",
        "credential_set_epoch_id",
        "destination_set_id",
        "destinations",
        "secondary_sender_retired",
        "existing_webhooks_preserved",
        "credential_output",
        "live_send",
        "authority_event_id",
        "authority_kind",
        "scheduler_writable",
        "report_env_install_receipt_sha256",
    }
)
_ACTIVATION_MARKER_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "transaction_id",
        "release_sha256",
        "stable_entrypoint_sha256",
        "release_launcher_sha256",
        "child_policy_sha256",
        "owner_permit_sha256",
        "rotation_receipt_sha256",
        "report_env_install_receipt_sha256",
        "secondary_disposition_sha256",
        "journal_file_sha256",
        "primary_cron_sha256",
        "schedule",
        "timezone",
        "secondary_sender_retired",
        "provider_call",
        "http_send",
        "production_database_write",
        "activation_marker_sha256",
    }
)
_ACTIVATION_MARKER_V2_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "transaction_id",
        "release_sha256",
        "stable_entrypoint_sha256",
        "release_launcher_sha256",
        "child_policy_sha256",
        "owner_permit_sha256",
        "credential_set_receipt_sha256",
        "report_env_install_receipt_sha256",
        "destination_set_id",
        "destinations",
        "secondary_disposition_sha256",
        "journal_file_sha256",
        "primary_cron_sha256",
        "schedule",
        "timezone",
        "secondary_sender_retired",
        "provider_call",
        "http_send",
        "production_database_write",
        "activation_marker_sha256",
    }
)
_SCHEDULED_CYCLE_EVENT_KEYS = frozenset(
    {
        "schema_version",
        "sequence",
        "previous_entry_sha256",
        "event",
        "cycle_id",
        "report_date",
        "run_id",
        "release_sha256",
        "launcher_sha256",
        "policy_sha256",
        "policy_authorization_id",
        "prepare_authorization_id",
        "cycle_lease_sha256",
        "prepare_attempt_id",
        "send_authorization_id",
        "artifact_version_id",
        "bundle_sha256",
        "outbox_sha256",
        "commit_request_sha256",
        "commit_receipt_sha256",
        "timestamp",
        "entry_sha256",
    }
)
_SCHEDULED_COMMIT_RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "cycle_id",
        "report_date",
        "run_id",
        "release_sha256",
        "launcher_sha256",
        "policy_sha256",
        "policy_authorization_id",
        "prepare_authorization_id",
        "prepare_attempt_id",
        "artifact_version_id",
        "bundle_sha256",
        "outbox_sha256",
        "commit_request_sha256",
        "provider_authorization_id",
        "cycle_lease_sha256",
        "committed_at",
        "commit_receipt_sha256",
    }
)
_SCHEDULED_SEND_PERMIT_KEYS = frozenset(
    {
        "schema_version",
        "authorization_id",
        "release_sha256",
        "expires_at",
        "run_id",
        "action",
        "artifact_version_id",
        "bundle_sha256",
        "outbox_sha256",
        "commit_request_sha256",
        "commit_receipt_sha256",
        "resend_part_indexes",
        "cycle_id",
        "report_date",
        "policy_sha256",
        "policy_authorization_id",
        "launcher_sha256",
        "prepare_authorization_id",
        "prepare_attempt_id",
        "credential_epoch_id",
        "destination_alias",
        "required_keyword",
        "automatic_resend",
        "cycle_lease_sha256",
    }
)
_SCHEDULED_SEND_PERMIT_V2_KEYS = frozenset(
    {
        "schema_version",
        "authorization_id",
        "release_sha256",
        "expires_at",
        "run_id",
        "action",
        "artifact_version_id",
        "bundle_sha256",
        "outbox_sha256",
        "commit_request_sha256",
        "commit_receipt_sha256",
        "resend_part_indexes",
        "cycle_id",
        "report_date",
        "policy_sha256",
        "policy_authorization_id",
        "launcher_sha256",
        "prepare_authorization_id",
        "prepare_attempt_id",
        "credential_set_epoch_id",
        "destination_set_id",
        "destinations",
        "delivery_plan",
        "required_keyword",
        "automatic_resend",
        "cycle_lease_sha256",
    }
)
_PRODUCTION_ROOTS = (
    Path("/home/ubuntu/.reddit-voc/secrets"),
    Path("/home/ubuntu/.reddit-voc/report-control"),
    Path("/opt/reddit-voc-daily-report"),
    # The periodic-report namespace is never a daily runtime target. Keep it
    # forbidden as a shadow root so local/test controls cannot alias it.
    Path("/opt/reddit-voc-report"),
    Path("/opt/reddit-voc-site"),
)
_GATE_KEYS = (
    "REDDIT_VOC_TRANSLATION_MODE",
    "REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION",
    "REDDIT_VOC_DINGTALK_MODE",
    "REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND",
    "REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT",
)
_ALL_OFF_GATES = {
    "REDDIT_VOC_TRANSLATION_MODE": "dry_run",
    "REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION": "0",
    "REDDIT_VOC_DINGTALK_MODE": "dry_run",
    "REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND": "0",
    "REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT": "0",
}
_ENV_ALLOWED = frozenset(
    {
        "REDDIT_VOC_DATABASE_PATH",
        "REDDIT_VOC_RUN_ID",
        "REDDIT_VOC_ATTEMPT_ID",
        "REDDIT_VOC_ARTIFACT_VERSION_ID",
        "REDDIT_VOC_REPORT_PUBLIC_ROOT",
        "REDDIT_VOC_REPORT_PRIVATE_ROOT",
        "REDDIT_VOC_REPORT_PUBLIC_STAGING_ROOT",
        "REDDIT_VOC_REPORT_PRIVATE_STAGING_ROOT",
        "REDDIT_VOC_REPORT_STATE_ROOT",
        "REDDIT_VOC_REPORT_BLOCKED_ROOT",
        "REDDIT_VOC_REPORT_HANDOFF_ROOT",
        "REDDIT_VOC_PROVIDER_ATTEMPT_ROOT",
        "REDDIT_VOC_CONFIG_ROOT",
        "REDDIT_VOC_ARTIFACT_BASE_URL",
        "DINGTALK_REQUIRED_KEYWORD",
        "REDDIT_VOC_DINGTALK_MAX_BYTES",
        "REDDIT_VOC_DINGTALK_MAX_PARTS",
        "REDDIT_VOC_DINGTALK_CREDENTIAL_EPOCH_ID",
        "REDDIT_VOC_DINGTALK_DESTINATION_ALIAS",
        "REDDIT_VOC_DINGTALK_CREDENTIAL_SET_EPOCH_ID",
        "REDDIT_VOC_DINGTALK_DESTINATION_SET_ID",
        "REDDIT_VOC_DINGTALK_PRIMARY_DESTINATION_ALIAS",
        "REDDIT_VOC_DINGTALK_SECONDARY_DESTINATION_ALIAS",
        *_GATE_KEYS,
        "DINGTALK_WEBHOOK_URL",
        "DINGTALK_WEBHOOK_SECRET",
        "DINGTALK_WEBHOOK_URL_2",
        "DINGTALK_WEBHOOK_SECRET_2",
    }
)


class ReportControlError(RuntimeError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_id(value: object, field: str) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise ReportControlError(f"{field}_invalid")
    return value


def _require_sha(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ReportControlError(f"{field}_invalid")
    return value


def _read_cycle_lease(args: argparse.Namespace, *, required: bool) -> str | None:
    descriptor = getattr(args, "cycle_lease_fd", None)
    if descriptor is None:
        if required:
            raise ReportControlError("cycle_lease_missing")
        return None
    if isinstance(descriptor, bool) or not isinstance(descriptor, int) or descriptor < 3:
        raise ReportControlError("cycle_lease_fd_invalid")
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_size != 64
        ):
            raise ReportControlError("cycle_lease_fd_invalid")
        os.lseek(descriptor, 0, os.SEEK_SET)
        payload = os.read(descriptor, 65)
        os.lseek(descriptor, 0, os.SEEK_SET)
    except OSError as exc:
        raise ReportControlError("cycle_lease_fd_invalid") from exc
    try:
        token = payload.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ReportControlError("cycle_lease_fd_invalid") from exc
    return _require_sha(token, "cycle_lease_token")


def _parse_datetime_text(value: object, reason: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ReportControlError(reason)
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ReportControlError(reason) from exc
    if parsed.tzinfo is None:
        raise ReportControlError(reason)
    return parsed


def _require_expiry(value: object) -> str:
    _parse_datetime_text(value, "permit_expiry_invalid")
    return str(value)


def _expiry_is_future(value: str) -> bool:
    if os.getenv("REDDIT_VOC_LOCAL_TEST_MODE") == "1":
        return True
    try:
        parsed = _parse_datetime_text(value, "permit_expiry_invalid")
    except ReportControlError:
        return False
    return parsed.astimezone(timezone.utc) > datetime.now(timezone.utc)


def canonical_g6r1_json_bytes(document: Mapping[str, object]) -> bytes:
    """Return the one canonical, newline-free authority document encoding."""
    if not isinstance(document, Mapping):
        raise ReportControlError("g6r1_authority_document_invalid")
    return _canonical(document)


def canonical_g6r1_provider_attempt_policy() -> Mapping[str, object]:
    return {
        **_G6R1_PROVIDER_ATTEMPT_POLICY,
        "retryable_http_statuses": list(
            _G6R1_PROVIDER_ATTEMPT_POLICY["retryable_http_statuses"]
        ),
        "retryable_terminal_outcomes": list(
            _G6R1_PROVIDER_ATTEMPT_POLICY["retryable_terminal_outcomes"]
        ),
    }


def canonical_g6r5_provider_attempt_policy() -> Mapping[str, object]:
    return {
        **_G6R5_PROVIDER_ATTEMPT_POLICY,
        "retryable_http_statuses": list(
            _G6R5_PROVIDER_ATTEMPT_POLICY["retryable_http_statuses"]
        ),
        "retryable_terminal_outcomes": list(
            _G6R5_PROVIDER_ATTEMPT_POLICY["retryable_terminal_outcomes"]
        ),
    }


def _is_supported_scheduled_provider_policy(value: object) -> bool:
    return value in (
        canonical_g6r1_provider_attempt_policy(),
        canonical_g6r5_provider_attempt_policy(),
    )


def canonical_g6r1_dual_destinations() -> list[Mapping[str, str]]:
    return [
        {"destination_id": destination_id, "destination_alias": alias}
        for destination_id, alias in _G6R1_DUAL_DESTINATIONS
    ]


def build_g6r5_parent_policy() -> Mapping[str, object]:
    return {
        "schema_version": "reddit-voc-bounded-dual-daily-live-policy-v2",
        "policy_id": "g6r5-dual-daily-live-20260822-20270821",
        "authorization_id": "owner-g6r5-annual-daily-dual-20260821",
        "status": "active",
        "cadence": "daily",
        "timezone": "Asia/Shanghai",
        "scheduled_local_time": "08:00",
        "starts_at_utc": "2026-08-22T00:00:00+00:00",
        "expires_at_utc": "2027-08-21T00:30:00+00:00",
        "max_scheduled_runs": _G6R5_MAX_SLOTS,
        "destination_set_id": _G6R1_DUAL_DESTINATION_SET_ID,
        "destinations": canonical_g6r1_dual_destinations(),
        "required_keyword": "LL",
        "provider_prepare": True,
        "live_send": True,
        "automatic_resend": False,
    }


def validate_g6r5_parent_policy(
    document: Mapping[str, object],
) -> Mapping[str, object]:
    if set(document) != _G6R5_POLICY_KEYS or document != build_g6r5_parent_policy():
        raise ReportControlError("parent_policy_invalid")
    return document


def canonical_g6r1_dual_delivery_plan() -> list[Mapping[str, object]]:
    return [
        {
            "destination_id": destination_id,
            "destination_alias": alias,
            "action": "initial",
            "resend_part_indexes": [],
        }
        for destination_id, alias in _G6R1_DUAL_DESTINATIONS
    ]


def _require_g6r1_dual_identity(
    *,
    credential_set_epoch_id: object,
    destination_set_id: object,
    destinations: object,
) -> tuple[str, str, list[Mapping[str, str]]]:
    epoch = _require_id(credential_set_epoch_id, "credential_set_epoch_id")
    set_id = _require_id(destination_set_id, "destination_set_id")
    expected = canonical_g6r1_dual_destinations()
    if set_id != _G6R1_DUAL_DESTINATION_SET_ID or destinations != expected:
        raise ReportControlError("dual_destination_identity_invalid")
    return epoch, set_id, expected


def build_g6r1_dual_report_env_install_receipt(
    *,
    device_id: int,
    inode_id: int,
    owner_uid: int,
    owner_gid: int,
    credential_set_epoch_id: str,
    destination_set_id: str,
    authority_event_id: str,
) -> Mapping[str, object]:
    for value, field, minimum in (
        (device_id, "device_id", 0),
        (inode_id, "inode_id", 1),
        (owner_uid, "owner_uid", 0),
        (owner_gid, "owner_gid", 0),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ReportControlError(f"{field}_invalid")
    epoch, set_id, destinations = _require_g6r1_dual_identity(
        credential_set_epoch_id=credential_set_epoch_id,
        destination_set_id=destination_set_id,
        destinations=canonical_g6r1_dual_destinations(),
    )
    _require_id(authority_event_id, "authority_event_id")
    return {
        "schema_version": "reddit-voc-g6r1-dual-report-env-install-receipt-v1",
        "status": "installed_terminal_no_send",
        "report_env_path": str(_G6R1_REPORT_ENV_PATH),
        "device_id": device_id,
        "inode_id": inode_id,
        "owner_uid": owner_uid,
        "owner_gid": owner_gid,
        "mode": "0600",
        "credential_set_epoch_id": epoch,
        "destination_set_id": set_id,
        "destinations": destinations,
        "authority_event_id": authority_event_id,
        "authority_kind": "owner_ops",
        "credential_output": False,
        "live_send": False,
    }


def validate_g6r1_dual_report_env_install_receipt(
    document: Mapping[str, object],
) -> Mapping[str, object]:
    if set(document) != _DUAL_REPORT_ENV_INSTALL_RECEIPT_KEYS:
        raise ReportControlError("dual_report_env_install_receipt_invalid")
    try:
        expected = build_g6r1_dual_report_env_install_receipt(
            device_id=document.get("device_id"),  # type: ignore[arg-type]
            inode_id=document.get("inode_id"),  # type: ignore[arg-type]
            owner_uid=document.get("owner_uid"),  # type: ignore[arg-type]
            owner_gid=document.get("owner_gid"),  # type: ignore[arg-type]
            credential_set_epoch_id=str(
                document.get("credential_set_epoch_id") or ""
            ),
            destination_set_id=str(document.get("destination_set_id") or ""),
            authority_event_id=str(document.get("authority_event_id") or ""),
        )
    except ReportControlError as exc:
        raise ReportControlError(
            "dual_report_env_install_receipt_invalid"
        ) from exc
    if document != expected:
        raise ReportControlError("dual_report_env_install_receipt_invalid")
    return document


def build_g6r1_dual_credential_set_receipt(
    *,
    installed_at_utc: str,
    credential_set_epoch_id: str,
    destination_set_id: str,
    authority_event_id: str,
    report_env_install_receipt_sha256: str,
) -> Mapping[str, object]:
    _parse_datetime_text(installed_at_utc, "dual_credential_set_receipt_invalid")
    epoch, set_id, destinations = _require_g6r1_dual_identity(
        credential_set_epoch_id=credential_set_epoch_id,
        destination_set_id=destination_set_id,
        destinations=canonical_g6r1_dual_destinations(),
    )
    _require_id(authority_event_id, "authority_event_id")
    _require_sha(
        report_env_install_receipt_sha256,
        "report_env_install_receipt_sha256",
    )
    return {
        "schema_version": "reddit-voc-g6r1-dual-credential-set-receipt-v1",
        "status": "installed_existing_dual_webhooks_verified_no_send",
        "installed_at_utc": installed_at_utc,
        "credential_set_epoch_id": epoch,
        "destination_set_id": set_id,
        "destinations": destinations,
        "secondary_sender_retired": True,
        "existing_webhooks_preserved": True,
        "credential_output": False,
        "live_send": False,
        "authority_event_id": authority_event_id,
        "authority_kind": "owner_ops",
        "scheduler_writable": False,
        "report_env_install_receipt_sha256": (
            report_env_install_receipt_sha256
        ),
    }


def validate_g6r1_dual_credential_set_receipt(
    document: Mapping[str, object],
) -> Mapping[str, object]:
    if set(document) != _DUAL_CREDENTIAL_SET_RECEIPT_KEYS:
        raise ReportControlError("dual_credential_set_receipt_invalid")
    try:
        expected = build_g6r1_dual_credential_set_receipt(
            installed_at_utc=str(document.get("installed_at_utc") or ""),
            credential_set_epoch_id=str(
                document.get("credential_set_epoch_id") or ""
            ),
            destination_set_id=str(document.get("destination_set_id") or ""),
            authority_event_id=str(document.get("authority_event_id") or ""),
            report_env_install_receipt_sha256=str(
                document.get("report_env_install_receipt_sha256") or ""
            ),
        )
    except ReportControlError as exc:
        raise ReportControlError("dual_credential_set_receipt_invalid") from exc
    if document != expected:
        raise ReportControlError("dual_credential_set_receipt_invalid")
    return document


def build_g6r1_scheduled_cycle_policy_v2(
    *,
    policy_id: str,
    authorization_id: str,
    parent_policy_sha256: str,
    release_sha256: str,
    stable_entrypoint_sha256: str,
    release_launcher_sha256: str,
    credential_set_epoch_id: str,
    destination_set_id: str,
    credential_set_receipt_sha256: str,
) -> Mapping[str, object]:
    _require_id(policy_id, "policy_id")
    _require_id(authorization_id, "policy_authorization_id")
    for value, field in (
        (parent_policy_sha256, "parent_policy_sha256"),
        (release_sha256, "release_sha256"),
        (stable_entrypoint_sha256, "stable_entrypoint_sha256"),
        (release_launcher_sha256, "release_launcher_sha256"),
        (credential_set_receipt_sha256, "credential_set_receipt_sha256"),
    ):
        _require_sha(value, field)
    epoch, set_id, destinations = _require_g6r1_dual_identity(
        credential_set_epoch_id=credential_set_epoch_id,
        destination_set_id=destination_set_id,
        destinations=canonical_g6r1_dual_destinations(),
    )
    return {
        "schema_version": "reddit-voc-g6r1-scheduled-cycle-policy-v2",
        "policy_id": policy_id,
        "authorization_id": authorization_id,
        "parent_policy_sha256": parent_policy_sha256,
        "report_release_sha256": release_sha256,
        "stable_entrypoint_sha256": stable_entrypoint_sha256,
        "release_launcher_sha256": release_launcher_sha256,
        "cadence": "daily",
        "timezone": "Asia/Shanghai",
        "scheduled_local_time": "08:00",
        "starts_at_utc": "2026-08-12T00:00:00Z",
        "expires_at_utc": "2026-08-31T00:30:00Z",
        "max_slots": _G6R1_MAX_SLOTS,
        "credential_set_epoch_id": epoch,
        "destination_set_id": set_id,
        "destinations": destinations,
        "required_keyword": "LL",
        "credential_set_receipt_sha256": credential_set_receipt_sha256,
        "secondary_sender_retired": True,
        "provider_attempt_policy": canonical_g6r1_provider_attempt_policy(),
        "slots": _canonical_g6r1_slots(),
    }


def validate_g6r1_scheduled_cycle_policy_v2(
    document: Mapping[str, object],
    *,
    parent_policy_sha256: str,
    release_sha256: str,
    stable_entrypoint_sha256: str,
    release_launcher_sha256: str,
) -> Mapping[str, object]:
    if set(document) != _SCHEDULED_POLICY_V2_KEYS:
        raise ReportControlError("scheduled_policy_invalid")
    try:
        expected = build_g6r1_scheduled_cycle_policy_v2(
            policy_id=str(document.get("policy_id") or ""),
            authorization_id=str(document.get("authorization_id") or ""),
            parent_policy_sha256=parent_policy_sha256,
            release_sha256=release_sha256,
            stable_entrypoint_sha256=stable_entrypoint_sha256,
            release_launcher_sha256=release_launcher_sha256,
            credential_set_epoch_id=str(
                document.get("credential_set_epoch_id") or ""
            ),
            destination_set_id=str(document.get("destination_set_id") or ""),
            credential_set_receipt_sha256=str(
                document.get("credential_set_receipt_sha256") or ""
            ),
        )
    except ReportControlError as exc:
        raise ReportControlError("scheduled_policy_invalid") from exc
    if document != expected:
        reason = (
            "scheduled_policy_slots_invalid"
            if document.get("slots") != expected["slots"]
            else "scheduled_policy_invalid"
        )
        raise ReportControlError(reason)
    return document


def build_g6r1_owner_policy_permit_v2(
    *,
    authorization_id: str,
    release_sha256: str,
    stable_entrypoint_sha256: str,
    release_launcher_sha256: str,
    policy_sha256: str,
    parent_policy_sha256: str,
    credential_set_receipt_sha256: str,
    credential_set_epoch_id: str,
    destination_set_id: str,
) -> Mapping[str, object]:
    for value, field in (
        (release_sha256, "release_sha256"),
        (stable_entrypoint_sha256, "stable_entrypoint_sha256"),
        (release_launcher_sha256, "release_launcher_sha256"),
        (policy_sha256, "policy_sha256"),
        (parent_policy_sha256, "parent_policy_sha256"),
        (credential_set_receipt_sha256, "credential_set_receipt_sha256"),
    ):
        _require_sha(value, field)
    _require_id(authorization_id, "policy_authorization_id")
    epoch, set_id, destinations = _require_g6r1_dual_identity(
        credential_set_epoch_id=credential_set_epoch_id,
        destination_set_id=destination_set_id,
        destinations=canonical_g6r1_dual_destinations(),
    )
    return {
        "schema_version": "report-scheduled-cycle-policy-permit-v2",
        "authorization_id": authorization_id,
        "release_sha256": release_sha256,
        "expires_at": "2026-08-31T00:30:00Z",
        "stable_entrypoint_sha256": stable_entrypoint_sha256,
        "release_launcher_sha256": release_launcher_sha256,
        "policy_sha256": policy_sha256,
        "parent_policy_sha256": parent_policy_sha256,
        "credential_set_receipt_sha256": credential_set_receipt_sha256,
        "max_slots": _G6R1_MAX_SLOTS,
        "credential_set_epoch_id": epoch,
        "destination_set_id": set_id,
        "destinations": destinations,
        "live_send": True,
        "provider_prepare": True,
        "provider_attempt_policy": canonical_g6r1_provider_attempt_policy(),
        "secondary_sender_retired": True,
    }


def validate_g6r1_owner_policy_permit_v2(
    document: Mapping[str, object],
    **expected_values: object,
) -> Mapping[str, object]:
    try:
        expected = build_g6r1_owner_policy_permit_v2(
            authorization_id=str(expected_values["authorization_id"]),
            release_sha256=str(expected_values["release_sha256"]),
            stable_entrypoint_sha256=str(
                expected_values["stable_entrypoint_sha256"]
            ),
            release_launcher_sha256=str(
                expected_values["release_launcher_sha256"]
            ),
            policy_sha256=str(expected_values["policy_sha256"]),
            parent_policy_sha256=str(
                expected_values["parent_policy_sha256"]
            ),
            credential_set_receipt_sha256=str(
                expected_values["credential_set_receipt_sha256"]
            ),
            credential_set_epoch_id=str(
                expected_values["credential_set_epoch_id"]
            ),
            destination_set_id=str(expected_values["destination_set_id"]),
        )
    except (KeyError, ReportControlError) as exc:
        raise ReportControlError("scheduled_policy_authorization_invalid") from exc
    if document != expected:
        raise ReportControlError("scheduled_policy_authorization_invalid")
    return document


def build_g6r5_scheduled_cycle_policy_v3(
    *,
    policy_id: str,
    authorization_id: str,
    parent_policy_sha256: str,
    release_sha256: str,
    stable_entrypoint_sha256: str,
    release_launcher_sha256: str,
    credential_set_epoch_id: str,
    destination_set_id: str,
    credential_set_receipt_sha256: str,
) -> Mapping[str, object]:
    _require_id(policy_id, "policy_id")
    _require_id(authorization_id, "policy_authorization_id")
    for value, field in (
        (parent_policy_sha256, "parent_policy_sha256"),
        (release_sha256, "release_sha256"),
        (stable_entrypoint_sha256, "stable_entrypoint_sha256"),
        (release_launcher_sha256, "release_launcher_sha256"),
        (credential_set_receipt_sha256, "credential_set_receipt_sha256"),
    ):
        _require_sha(value, field)
    if parent_policy_sha256 != _G6R5_DAILY_POLICY_SHA256:
        raise ReportControlError("parent_policy_sha256_invalid")
    epoch, set_id, destinations = _require_g6r1_dual_identity(
        credential_set_epoch_id=credential_set_epoch_id,
        destination_set_id=destination_set_id,
        destinations=canonical_g6r1_dual_destinations(),
    )
    return {
        "schema_version": "reddit-voc-g6r5-scheduled-cycle-policy-v3",
        "policy_id": policy_id,
        "authorization_id": authorization_id,
        "parent_policy_sha256": parent_policy_sha256,
        "report_release_sha256": release_sha256,
        "stable_entrypoint_sha256": stable_entrypoint_sha256,
        "release_launcher_sha256": release_launcher_sha256,
        "cadence": "daily",
        "timezone": "Asia/Shanghai",
        "scheduled_local_time": "08:00",
        "starts_at_utc": "2026-08-22T00:00:00Z",
        "expires_at_utc": "2027-08-21T00:30:00Z",
        "max_slots": _G6R5_MAX_SLOTS,
        "credential_set_epoch_id": epoch,
        "destination_set_id": set_id,
        "destinations": destinations,
        "required_keyword": "LL",
        "credential_set_receipt_sha256": credential_set_receipt_sha256,
        "secondary_sender_retired": True,
        "provider_attempt_policy": canonical_g6r5_provider_attempt_policy(),
        "slots": _canonical_g6r5_slots(),
        "automatic_resend": False,
    }


def validate_g6r5_scheduled_cycle_policy_v3(
    document: Mapping[str, object],
    *,
    parent_policy_sha256: str,
    release_sha256: str,
    stable_entrypoint_sha256: str,
    release_launcher_sha256: str,
) -> Mapping[str, object]:
    if set(document) != _SCHEDULED_POLICY_V3_KEYS:
        raise ReportControlError("scheduled_policy_invalid")
    try:
        expected = build_g6r5_scheduled_cycle_policy_v3(
            policy_id=str(document.get("policy_id") or ""),
            authorization_id=str(document.get("authorization_id") or ""),
            parent_policy_sha256=parent_policy_sha256,
            release_sha256=release_sha256,
            stable_entrypoint_sha256=stable_entrypoint_sha256,
            release_launcher_sha256=release_launcher_sha256,
            credential_set_epoch_id=str(
                document.get("credential_set_epoch_id") or ""
            ),
            destination_set_id=str(document.get("destination_set_id") or ""),
            credential_set_receipt_sha256=str(
                document.get("credential_set_receipt_sha256") or ""
            ),
        )
    except ReportControlError as exc:
        raise ReportControlError("scheduled_policy_invalid") from exc
    if document != expected:
        reason = (
            "scheduled_policy_slots_invalid"
            if document.get("slots") != expected["slots"]
            else "scheduled_policy_invalid"
        )
        raise ReportControlError(reason)
    return document


def build_g6r5_owner_policy_permit_v3(
    *,
    authorization_id: str,
    release_sha256: str,
    stable_entrypoint_sha256: str,
    release_launcher_sha256: str,
    policy_sha256: str,
    parent_policy_sha256: str,
    credential_set_receipt_sha256: str,
    credential_set_epoch_id: str,
    destination_set_id: str,
) -> Mapping[str, object]:
    for value, field in (
        (release_sha256, "release_sha256"),
        (stable_entrypoint_sha256, "stable_entrypoint_sha256"),
        (release_launcher_sha256, "release_launcher_sha256"),
        (policy_sha256, "policy_sha256"),
        (parent_policy_sha256, "parent_policy_sha256"),
        (credential_set_receipt_sha256, "credential_set_receipt_sha256"),
    ):
        _require_sha(value, field)
    if parent_policy_sha256 != _G6R5_DAILY_POLICY_SHA256:
        raise ReportControlError("parent_policy_sha256_invalid")
    _require_id(authorization_id, "policy_authorization_id")
    epoch, set_id, destinations = _require_g6r1_dual_identity(
        credential_set_epoch_id=credential_set_epoch_id,
        destination_set_id=destination_set_id,
        destinations=canonical_g6r1_dual_destinations(),
    )
    return {
        "schema_version": "report-scheduled-cycle-policy-permit-v3",
        "authorization_id": authorization_id,
        "release_sha256": release_sha256,
        "expires_at": "2027-08-21T00:30:00Z",
        "stable_entrypoint_sha256": stable_entrypoint_sha256,
        "release_launcher_sha256": release_launcher_sha256,
        "policy_sha256": policy_sha256,
        "parent_policy_sha256": parent_policy_sha256,
        "credential_set_receipt_sha256": credential_set_receipt_sha256,
        "max_slots": _G6R5_MAX_SLOTS,
        "credential_set_epoch_id": epoch,
        "destination_set_id": set_id,
        "destinations": destinations,
        "live_send": True,
        "provider_prepare": True,
        "provider_attempt_policy": canonical_g6r5_provider_attempt_policy(),
        "secondary_sender_retired": True,
        "automatic_resend": False,
    }


def validate_g6r5_owner_policy_permit_v3(
    document: Mapping[str, object],
    **expected_values: object,
) -> Mapping[str, object]:
    try:
        expected = build_g6r5_owner_policy_permit_v3(
            authorization_id=str(expected_values["authorization_id"]),
            release_sha256=str(expected_values["release_sha256"]),
            stable_entrypoint_sha256=str(
                expected_values["stable_entrypoint_sha256"]
            ),
            release_launcher_sha256=str(
                expected_values["release_launcher_sha256"]
            ),
            policy_sha256=str(expected_values["policy_sha256"]),
            parent_policy_sha256=str(
                expected_values["parent_policy_sha256"]
            ),
            credential_set_receipt_sha256=str(
                expected_values["credential_set_receipt_sha256"]
            ),
            credential_set_epoch_id=str(
                expected_values["credential_set_epoch_id"]
            ),
            destination_set_id=str(expected_values["destination_set_id"]),
        )
    except (KeyError, ReportControlError) as exc:
        raise ReportControlError("scheduled_policy_authorization_invalid") from exc
    if document != expected:
        raise ReportControlError("scheduled_policy_authorization_invalid")
    return document


def build_g6r1_report_env_install_receipt(
    *,
    device_id: int,
    inode_id: int,
    owner_uid: int,
    owner_gid: int,
    credential_epoch_id: str,
    destination_alias: str,
    authority_event_id: str,
) -> Mapping[str, object]:
    for value, field, minimum in (
        (device_id, "device_id", 0),
        (inode_id, "inode_id", 1),
        (owner_uid, "owner_uid", 0),
        (owner_gid, "owner_gid", 0),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ReportControlError(f"{field}_invalid")
    _require_id(credential_epoch_id, "credential_epoch_id")
    _require_id(authority_event_id, "authority_event_id")
    if destination_alias != "HighValueAsset":
        raise ReportControlError("scheduled_destination_alias_invalid")
    return {
        "schema_version": "reddit-voc-g6r1-report-env-install-receipt-v1",
        "status": "installed_terminal_no_send",
        "report_env_path": str(_G6R1_REPORT_ENV_PATH),
        "device_id": device_id,
        "inode_id": inode_id,
        "owner_uid": owner_uid,
        "owner_gid": owner_gid,
        "mode": "0600",
        "credential_epoch_id": credential_epoch_id,
        "destination_alias": destination_alias,
        "authority_event_id": authority_event_id,
        "authority_kind": "owner_ops",
        "credential_output": False,
        "live_send": False,
    }


def validate_g6r1_report_env_install_receipt(
    document: Mapping[str, object],
) -> Mapping[str, object]:
    if set(document) != _REPORT_ENV_INSTALL_RECEIPT_KEYS:
        raise ReportControlError("report_env_install_receipt_invalid")
    try:
        expected = build_g6r1_report_env_install_receipt(
            device_id=document.get("device_id"),  # type: ignore[arg-type]
            inode_id=document.get("inode_id"),  # type: ignore[arg-type]
            owner_uid=document.get("owner_uid"),  # type: ignore[arg-type]
            owner_gid=document.get("owner_gid"),  # type: ignore[arg-type]
            credential_epoch_id=str(document.get("credential_epoch_id") or ""),
            destination_alias=str(document.get("destination_alias") or ""),
            authority_event_id=str(document.get("authority_event_id") or ""),
        )
    except ReportControlError as exc:
        raise ReportControlError("report_env_install_receipt_invalid") from exc
    if document != expected:
        raise ReportControlError("report_env_install_receipt_invalid")
    return document


def build_g6r1_rotation_receipt(
    *,
    rotated_at_utc: str,
    credential_epoch_id: str,
    destination_alias: str,
    authority_event_id: str,
    report_env_install_receipt_sha256: str,
) -> Mapping[str, object]:
    _parse_datetime_text(rotated_at_utc, "credential_rotation_receipt_invalid")
    _require_id(credential_epoch_id, "credential_epoch_id")
    _require_id(authority_event_id, "authority_event_id")
    _require_sha(
        report_env_install_receipt_sha256,
        "report_env_install_receipt_sha256",
    )
    if destination_alias != "HighValueAsset":
        raise ReportControlError("scheduled_destination_alias_invalid")
    return {
        "schema_version": "reddit-voc-dingtalk-credential-rotation-receipt-v1",
        "status": "rotated_primary_verified_no_send",
        "rotated_at_utc": rotated_at_utc,
        "credential_epoch_id": credential_epoch_id,
        "destination_alias": destination_alias,
        "secondary_sender_retired": True,
        "credential_output": False,
        "live_send": False,
        "old_credential_revoked": True,
        "new_credential_installed": True,
        "authority_event_id": authority_event_id,
        "authority_kind": "owner_ops",
        "scheduler_writable": False,
        "report_env_install_receipt_sha256": (
            report_env_install_receipt_sha256
        ),
    }


def validate_g6r1_rotation_receipt(
    document: Mapping[str, object],
) -> Mapping[str, object]:
    if set(document) != _ROTATION_RECEIPT_KEYS:
        raise ReportControlError("credential_rotation_receipt_invalid")
    try:
        expected = build_g6r1_rotation_receipt(
            rotated_at_utc=str(document.get("rotated_at_utc") or ""),
            credential_epoch_id=str(document.get("credential_epoch_id") or ""),
            destination_alias=str(document.get("destination_alias") or ""),
            authority_event_id=str(document.get("authority_event_id") or ""),
            report_env_install_receipt_sha256=str(
                document.get("report_env_install_receipt_sha256") or ""
            ),
        )
    except ReportControlError as exc:
        raise ReportControlError("credential_rotation_receipt_invalid") from exc
    if document != expected:
        raise ReportControlError("credential_rotation_receipt_invalid")
    return document


def _canonical_g6r1_slots() -> list[Mapping[str, object]]:
    result: list[Mapping[str, object]] = []
    for offset in range(_G6R1_MAX_SLOTS):
        report_day = _G6R1_FIRST_REPORT_DATE + timedelta(days=offset)
        result.append(
            {
                "report_date": report_day.isoformat(),
                "run_id": f"daily_collect_{report_day:%Y%m%d}_0700",
                "slot_end_at_utc": f"{report_day.isoformat()}T00:30:00Z",
                "provider_prepare_allowed": True,
                "send_allowed": True,
            }
        )
    return result


def _canonical_g6r5_slots() -> list[Mapping[str, object]]:
    result: list[Mapping[str, object]] = []
    for offset in range(_G6R5_MAX_SLOTS):
        report_day = _G6R5_FIRST_REPORT_DATE + timedelta(days=offset)
        result.append(
            {
                "report_date": report_day.isoformat(),
                "run_id": f"daily_collect_{report_day:%Y%m%d}_0700",
                "slot_end_at_utc": f"{report_day.isoformat()}T00:30:00Z",
                "provider_prepare_allowed": True,
                "send_allowed": True,
            }
        )
    if result[-1]["report_date"] != _G6R5_LAST_REPORT_DATE.isoformat():
        raise ReportControlError("scheduled_policy_slots_invalid")
    return result


def build_g6r1_scheduled_cycle_policy(
    *,
    policy_id: str,
    authorization_id: str,
    parent_policy_sha256: str,
    release_sha256: str,
    stable_entrypoint_sha256: str,
    release_launcher_sha256: str,
    credential_epoch_id: str,
    destination_alias: str,
    credential_rotation_receipt_sha256: str,
) -> Mapping[str, object]:
    _require_id(policy_id, "policy_id")
    _require_id(authorization_id, "policy_authorization_id")
    _require_sha(parent_policy_sha256, "parent_policy_sha256")
    _require_sha(release_sha256, "release_sha256")
    _require_sha(stable_entrypoint_sha256, "stable_entrypoint_sha256")
    _require_sha(release_launcher_sha256, "release_launcher_sha256")
    _require_id(credential_epoch_id, "credential_epoch_id")
    _require_sha(
        credential_rotation_receipt_sha256,
        "credential_rotation_receipt_sha256",
    )
    if destination_alias != "HighValueAsset":
        raise ReportControlError("scheduled_destination_alias_invalid")
    return {
        "schema_version": "reddit-voc-g6r1-scheduled-cycle-policy-v1",
        "policy_id": policy_id,
        "authorization_id": authorization_id,
        "parent_policy_sha256": parent_policy_sha256,
        "report_release_sha256": release_sha256,
        "stable_entrypoint_sha256": stable_entrypoint_sha256,
        "release_launcher_sha256": release_launcher_sha256,
        "cadence": "daily",
        "timezone": "Asia/Shanghai",
        "scheduled_local_time": "08:00",
        "starts_at_utc": "2026-08-12T00:00:00Z",
        "expires_at_utc": "2026-08-31T00:30:00Z",
        "max_slots": _G6R1_MAX_SLOTS,
        "credential_epoch_id": credential_epoch_id,
        "destination_alias": destination_alias,
        "required_keyword": "LL",
        "credential_rotation_receipt_sha256": (
            credential_rotation_receipt_sha256
        ),
        "secondary_sender_retired": True,
        "provider_attempt_policy": canonical_g6r1_provider_attempt_policy(),
        "slots": _canonical_g6r1_slots(),
    }


def validate_g6r1_scheduled_cycle_policy(
    document: Mapping[str, object],
    *,
    parent_policy_sha256: str,
    release_sha256: str,
    stable_entrypoint_sha256: str,
    release_launcher_sha256: str,
) -> Mapping[str, object]:
    if set(document) != _SCHEDULED_POLICY_KEYS:
        raise ReportControlError("scheduled_policy_invalid")
    try:
        expected = build_g6r1_scheduled_cycle_policy(
            policy_id=str(document.get("policy_id") or ""),
            authorization_id=str(document.get("authorization_id") or ""),
            parent_policy_sha256=parent_policy_sha256,
            release_sha256=release_sha256,
            stable_entrypoint_sha256=stable_entrypoint_sha256,
            release_launcher_sha256=release_launcher_sha256,
            credential_epoch_id=str(document.get("credential_epoch_id") or ""),
            destination_alias=str(document.get("destination_alias") or ""),
            credential_rotation_receipt_sha256=str(
                document.get("credential_rotation_receipt_sha256") or ""
            ),
        )
    except ReportControlError as exc:
        raise ReportControlError("scheduled_policy_invalid") from exc
    if document != expected:
        reason = (
            "scheduled_policy_slots_invalid"
            if document.get("slots") != expected["slots"]
            else "scheduled_policy_invalid"
        )
        raise ReportControlError(reason)
    return document


def build_g6r1_owner_policy_permit(
    *,
    authorization_id: str,
    release_sha256: str,
    stable_entrypoint_sha256: str,
    release_launcher_sha256: str,
    policy_sha256: str,
    parent_policy_sha256: str,
    credential_rotation_receipt_sha256: str,
    credential_epoch_id: str,
    destination_alias: str,
) -> Mapping[str, object]:
    for value, field in (
        (release_sha256, "release_sha256"),
        (stable_entrypoint_sha256, "stable_entrypoint_sha256"),
        (release_launcher_sha256, "release_launcher_sha256"),
        (policy_sha256, "policy_sha256"),
        (parent_policy_sha256, "parent_policy_sha256"),
        (
            credential_rotation_receipt_sha256,
            "credential_rotation_receipt_sha256",
        ),
    ):
        _require_sha(value, field)
    _require_id(authorization_id, "policy_authorization_id")
    _require_id(credential_epoch_id, "credential_epoch_id")
    if destination_alias != "HighValueAsset":
        raise ReportControlError("scheduled_destination_alias_invalid")
    return {
        "schema_version": "report-scheduled-cycle-policy-permit-v1",
        "authorization_id": authorization_id,
        "release_sha256": release_sha256,
        "expires_at": "2026-08-31T00:30:00Z",
        "stable_entrypoint_sha256": stable_entrypoint_sha256,
        "release_launcher_sha256": release_launcher_sha256,
        "policy_sha256": policy_sha256,
        "parent_policy_sha256": parent_policy_sha256,
        "credential_rotation_receipt_sha256": (
            credential_rotation_receipt_sha256
        ),
        "max_slots": _G6R1_MAX_SLOTS,
        "credential_epoch_id": credential_epoch_id,
        "destination_alias": destination_alias,
        "live_send": True,
        "provider_prepare": True,
        "provider_attempt_policy": canonical_g6r1_provider_attempt_policy(),
        "secondary_sender_retired": True,
    }


def validate_g6r1_owner_policy_permit(
    document: Mapping[str, object],
    *,
    authorization_id: str,
    release_sha256: str,
    stable_entrypoint_sha256: str,
    release_launcher_sha256: str,
    policy_sha256: str,
    parent_policy_sha256: str,
    credential_rotation_receipt_sha256: str,
    credential_epoch_id: str,
    destination_alias: str,
) -> Mapping[str, object]:
    expected = build_g6r1_owner_policy_permit(
        authorization_id=authorization_id,
        release_sha256=release_sha256,
        stable_entrypoint_sha256=stable_entrypoint_sha256,
        release_launcher_sha256=release_launcher_sha256,
        policy_sha256=policy_sha256,
        parent_policy_sha256=parent_policy_sha256,
        credential_rotation_receipt_sha256=(
            credential_rotation_receipt_sha256
        ),
        credential_epoch_id=credential_epoch_id,
        destination_alias=destination_alias,
    )
    if document != expected:
        raise ReportControlError("scheduled_policy_authorization_invalid")
    return document


def build_g6r1_secondary_disposition() -> Mapping[str, object]:
    return {
        "schema_version": "reddit-voc-g6r1-secondary-disposition-v1",
        "status": "retired_terminal",
        "legacy_script_path": _G6R1_LEGACY_SCRIPT_PATH,
        "legacy_cron_token": _G6R1_LEGACY_CRON_LINE,
        "legacy_process_token": _G6R1_LEGACY_SCRIPT_PATH,
        "secondary_sender_retired": True,
        "credential_output": False,
    }


def validate_g6r1_secondary_disposition(
    document: Mapping[str, object],
) -> Mapping[str, object]:
    if document != build_g6r1_secondary_disposition():
        raise ReportControlError("secondary_disposition_invalid")
    return document


def build_g6r1_activation_marker(
    *,
    transaction_id: str,
    release_sha256: str,
    stable_entrypoint_sha256: str,
    release_launcher_sha256: str,
    child_policy_sha256: str,
    owner_permit_sha256: str,
    rotation_receipt_sha256: str,
    report_env_install_receipt_sha256: str,
    secondary_disposition_sha256: str,
    journal_file_sha256: str,
    primary_cron_sha256: str,
) -> Mapping[str, object]:
    _require_id(transaction_id, "transaction_id")
    values = {
        "release_sha256": release_sha256,
        "stable_entrypoint_sha256": stable_entrypoint_sha256,
        "release_launcher_sha256": release_launcher_sha256,
        "child_policy_sha256": child_policy_sha256,
        "owner_permit_sha256": owner_permit_sha256,
        "rotation_receipt_sha256": rotation_receipt_sha256,
        "report_env_install_receipt_sha256": (
            report_env_install_receipt_sha256
        ),
        "secondary_disposition_sha256": secondary_disposition_sha256,
        "journal_file_sha256": journal_file_sha256,
        "primary_cron_sha256": primary_cron_sha256,
    }
    for field, value in values.items():
        _require_sha(value, field)
    base = {
        "schema_version": "reddit-voc-g6r1-terminal-activation-v1",
        "status": "activated_terminal",
        "transaction_id": transaction_id,
        **values,
        "schedule": "0 8 * * *",
        "timezone": "Asia/Shanghai",
        "secondary_sender_retired": True,
        "provider_call": False,
        "http_send": False,
        "production_database_write": False,
    }
    return {
        **base,
        "activation_marker_sha256": _sha256(_canonical(base)),
    }


def validate_g6r1_activation_marker(
    document: Mapping[str, object],
) -> Mapping[str, object]:
    if set(document) != _ACTIVATION_MARKER_KEYS:
        raise ReportControlError("activation_marker_invalid")
    try:
        expected = build_g6r1_activation_marker(
            transaction_id=str(document.get("transaction_id") or ""),
            release_sha256=str(document.get("release_sha256") or ""),
            stable_entrypoint_sha256=str(
                document.get("stable_entrypoint_sha256") or ""
            ),
            release_launcher_sha256=str(
                document.get("release_launcher_sha256") or ""
            ),
            child_policy_sha256=str(document.get("child_policy_sha256") or ""),
            owner_permit_sha256=str(document.get("owner_permit_sha256") or ""),
            rotation_receipt_sha256=str(
                document.get("rotation_receipt_sha256") or ""
            ),
            report_env_install_receipt_sha256=str(
                document.get("report_env_install_receipt_sha256") or ""
            ),
            secondary_disposition_sha256=str(
                document.get("secondary_disposition_sha256") or ""
            ),
            journal_file_sha256=str(
                document.get("journal_file_sha256") or ""
            ),
            primary_cron_sha256=str(
                document.get("primary_cron_sha256") or ""
            ),
        )
    except ReportControlError as exc:
        raise ReportControlError("activation_marker_invalid") from exc
    if document != expected:
        raise ReportControlError("activation_marker_invalid")
    return document


def build_g6r1_activation_marker_v2(
    *,
    transaction_id: str,
    release_sha256: str,
    stable_entrypoint_sha256: str,
    release_launcher_sha256: str,
    child_policy_sha256: str,
    owner_permit_sha256: str,
    credential_set_receipt_sha256: str,
    report_env_install_receipt_sha256: str,
    destination_set_id: str,
    secondary_disposition_sha256: str,
    journal_file_sha256: str,
    primary_cron_sha256: str,
) -> Mapping[str, object]:
    _require_id(transaction_id, "transaction_id")
    _epoch, set_id, destinations = _require_g6r1_dual_identity(
        credential_set_epoch_id="g6r1-marker-identity",
        destination_set_id=destination_set_id,
        destinations=canonical_g6r1_dual_destinations(),
    )
    values = {
        "release_sha256": release_sha256,
        "stable_entrypoint_sha256": stable_entrypoint_sha256,
        "release_launcher_sha256": release_launcher_sha256,
        "child_policy_sha256": child_policy_sha256,
        "owner_permit_sha256": owner_permit_sha256,
        "credential_set_receipt_sha256": credential_set_receipt_sha256,
        "report_env_install_receipt_sha256": (
            report_env_install_receipt_sha256
        ),
        "secondary_disposition_sha256": secondary_disposition_sha256,
        "journal_file_sha256": journal_file_sha256,
        "primary_cron_sha256": primary_cron_sha256,
    }
    for field, value in values.items():
        _require_sha(value, field)
    base = {
        "schema_version": "reddit-voc-g6r1-terminal-activation-v2",
        "status": "activated_terminal",
        "transaction_id": transaction_id,
        **values,
        "destination_set_id": set_id,
        "destinations": destinations,
        "schedule": "0 8 * * *",
        "timezone": "Asia/Shanghai",
        "secondary_sender_retired": True,
        "provider_call": False,
        "http_send": False,
        "production_database_write": False,
    }
    return {**base, "activation_marker_sha256": _sha256(_canonical(base))}


def validate_g6r1_activation_marker_v2(
    document: Mapping[str, object],
) -> Mapping[str, object]:
    if set(document) != _ACTIVATION_MARKER_V2_KEYS:
        raise ReportControlError("activation_marker_invalid")
    try:
        expected = build_g6r1_activation_marker_v2(
            transaction_id=str(document.get("transaction_id") or ""),
            release_sha256=str(document.get("release_sha256") or ""),
            stable_entrypoint_sha256=str(
                document.get("stable_entrypoint_sha256") or ""
            ),
            release_launcher_sha256=str(
                document.get("release_launcher_sha256") or ""
            ),
            child_policy_sha256=str(document.get("child_policy_sha256") or ""),
            owner_permit_sha256=str(document.get("owner_permit_sha256") or ""),
            credential_set_receipt_sha256=str(
                document.get("credential_set_receipt_sha256") or ""
            ),
            report_env_install_receipt_sha256=str(
                document.get("report_env_install_receipt_sha256") or ""
            ),
            destination_set_id=str(document.get("destination_set_id") or ""),
            secondary_disposition_sha256=str(
                document.get("secondary_disposition_sha256") or ""
            ),
            journal_file_sha256=str(
                document.get("journal_file_sha256") or ""
            ),
            primary_cron_sha256=str(
                document.get("primary_cron_sha256") or ""
            ),
        )
    except ReportControlError as exc:
        raise ReportControlError("activation_marker_invalid") from exc
    if document != expected:
        raise ReportControlError("activation_marker_invalid")
    return document


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise ReportControlError("control_write_failed")
        view = view[written:]


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ensure_directory(path: Path, *, create: bool = False) -> Path:
    path = Path(path)
    if create and not path.exists():
        path.mkdir(parents=True, mode=0o700)
        path.chmod(0o700)
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ReportControlError("control_directory_missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ReportControlError("control_directory_invalid")
    if metadata.st_uid != os.getuid():
        raise ReportControlError("control_directory_owner_invalid")
    if stat.S_IMODE(metadata.st_mode) != 0o700:
        raise ReportControlError("control_directory_mode_invalid")
    return path


def _write_new(path: Path, payload: bytes, *, mode: int = 0o600) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, mode)
    try:
        _write_all(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.chmod(path, mode)
    _fsync_directory(path.parent)


def _atomic_replace(path: Path, payload: bytes, *, mode: int = 0o600) -> None:
    temporary = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
    try:
        _write_new(temporary, payload, mode=mode)
        os.replace(temporary, path)
        os.chmod(path, mode)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists() and not temporary.is_symlink():
            temporary.unlink()


def _strict_json_bytes(payload: bytes, reason: str) -> Mapping[str, object]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate")
            result[key] = value
        return result

    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ReportControlError(reason) from exc
    if not isinstance(value, Mapping):
        raise ReportControlError(reason)
    return value


def _read_regular(path: Path, *, reason: str) -> bytes:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ReportControlError(reason) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ReportControlError(reason)
    if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise ReportControlError(reason)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        descriptor_metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(descriptor_metadata.st_mode)
            or descriptor_metadata.st_uid != os.getuid()
            or stat.S_IMODE(descriptor_metadata.st_mode) != 0o600
            or descriptor_metadata.st_dev != metadata.st_dev
            or descriptor_metadata.st_ino != metadata.st_ino
        ):
            raise ReportControlError(reason)
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, 65_536)
            if not chunk:
                break
            total += len(chunk)
            if total > 4 * 1024 * 1024:
                raise ReportControlError(reason)
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _require_root_owned_directory_chain(path: Path, *, reason: str) -> None:
    if os.getenv("REDDIT_VOC_LOCAL_TEST_MODE") == "1":
        return
    absolute = path if path.is_absolute() else path.absolute()
    ancestors = tuple(reversed(absolute.parents))
    for directory in ancestors:
        try:
            metadata = directory.lstat()
        except FileNotFoundError as exc:
            raise ReportControlError(reason) from exc
        mode = stat.S_IMODE(metadata.st_mode)
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != 0
            or mode & 0o022
            or not mode & 0o001
        ):
            raise ReportControlError(reason)
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(directory, flags)
        try:
            opened = os.fstat(descriptor)
            if (
                opened.st_dev != metadata.st_dev
                or opened.st_ino != metadata.st_ino
                or not stat.S_ISDIR(opened.st_mode)
                or opened.st_uid != 0
                or stat.S_IMODE(opened.st_mode) != mode
            ):
                raise ReportControlError(reason)
        finally:
            os.close(descriptor)


def _read_authority_regular(path: Path, *, reason: str) -> bytes:
    if os.getenv("REDDIT_VOC_LOCAL_TEST_MODE") == "1":
        return _read_regular(path, reason=reason)
    _require_root_owned_directory_chain(path, reason=reason)
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ReportControlError(reason) from exc
    mode = stat.S_IMODE(metadata.st_mode)
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or mode != 0o444
    ):
        raise ReportControlError(reason)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if (
            opened.st_dev != metadata.st_dev
            or opened.st_ino != metadata.st_ino
            or not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != 0
            or stat.S_IMODE(opened.st_mode) != mode
        ):
            raise ReportControlError(reason)
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, 65_536)
            if not chunk:
                break
            total += len(chunk)
            if total > 4 * 1024 * 1024:
                raise ReportControlError(reason)
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _require_authority_directory(path: Path, *, reason: str) -> Path:
    if os.getenv("REDDIT_VOC_LOCAL_TEST_MODE") == "1":
        return _ensure_directory(path)
    _require_root_owned_directory_chain(path, reason=reason)
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ReportControlError(reason) from exc
    mode = stat.S_IMODE(metadata.st_mode)
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != 0
        or mode & 0o022
        or not mode & 0o001
    ):
        raise ReportControlError(reason)
    return path


def _read_stable_entrypoint(path: Path) -> bytes:
    reason = "stable_entrypoint_invalid"
    if os.getenv("REDDIT_VOC_LOCAL_TEST_MODE") == "1":
        return _read_regular(path, reason=reason)
    _require_root_owned_directory_chain(path, reason=reason)
    return _read_host_regular(
        path,
        allowed_modes=frozenset({0o555}),
        allowed_uids=frozenset({0}),
        reason=reason,
    )


def _validate_report_env_install_identity(
    args: argparse.Namespace, receipt: Mapping[str, object]
) -> None:
    path = _policy_path(
        getattr(args, "report_env_file", None),
        production=_G6R1_REPORT_ENV_PATH,
        reason="report_env_path_invalid",
    )
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ReportControlError("report_env_install_identity_mismatch") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ReportControlError("report_env_install_identity_mismatch")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ReportControlError("report_env_install_identity_mismatch") from exc
    try:
        opened = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    expected = (
        receipt.get("device_id"),
        receipt.get("inode_id"),
        receipt.get("owner_uid"),
        receipt.get("owner_gid"),
        receipt.get("mode"),
    )
    actual = (
        opened.st_dev,
        opened.st_ino,
        opened.st_uid,
        opened.st_gid,
        f"{stat.S_IMODE(opened.st_mode):04o}",
    )
    if (
        opened.st_dev != metadata.st_dev
        or opened.st_ino != metadata.st_ino
        or expected != actual
    ):
        raise ReportControlError("report_env_install_identity_mismatch")
    if os.getenv("REDDIT_VOC_LOCAL_TEST_MODE") != "1" and (
        opened.st_uid != 1000
        or opened.st_gid != 1000
        or stat.S_IMODE(opened.st_mode) != 0o600
    ):
        raise ReportControlError("report_env_install_identity_mismatch")


def _validate_g6r1_transaction_journal(
    payload: bytes, *, transaction_id: str
) -> Mapping[str, object]:
    reason = "transaction_journal_invalid"
    journal = _strict_json_bytes(payload, reason)
    if payload != _canonical(journal) + b"\n":
        raise ReportControlError(reason)
    required = {
        "schema_version",
        "transaction_id",
        "phase",
        "phase_history",
        "release_sha256",
        "preimage_sha256",
        "primary_schedule_state",
        "secondary_sender_retired",
        "provider_call",
        "http_send",
        "production_database_write",
        "public_current_switch",
        "created_at_utc",
        "updated_at_utc",
        "journal_sha256",
    }
    if not required.issubset(journal):
        raise ReportControlError(reason)
    self_hash = _require_sha(journal.get("journal_sha256"), "journal_sha256")
    unsigned = dict(journal)
    unsigned.pop("journal_sha256")
    if _sha256(_canonical(unsigned)) != self_hash:
        raise ReportControlError(reason)
    if (
        journal.get("schema_version")
        != "reddit-voc-g6r1-transaction-journal-v1"
        or journal.get("transaction_id") != transaction_id
        or journal.get("phase")
        not in {"committed", "rolled_back_schedule_disabled"}
        or not isinstance(journal.get("phase_history"), list)
        or not journal.get("phase_history")
        or journal.get("secondary_sender_retired") is not True
        or journal.get("provider_call") is not False
        or journal.get("http_send") is not False
        or journal.get("production_database_write") is not False
        or not isinstance(journal.get("primary_schedule_state"), str)
        or not isinstance(journal.get("public_current_switch"), bool)
    ):
        raise ReportControlError(reason)
    _require_sha(journal.get("release_sha256"), "release_sha256")
    _require_sha(journal.get("preimage_sha256"), "preimage_sha256")
    _parse_datetime_text(journal.get("created_at_utc"), reason)
    _parse_datetime_text(journal.get("updated_at_utc"), reason)
    return journal


def _control_layout(root: Path) -> Mapping[str, Path]:
    root = _ensure_directory(root, create=True)
    result = {
        "root": root,
        "permits": root / "permits",
        "states": root / "permit-state",
        "audit": root / "audit",
        "gates": root / "gates",
    }
    for path in result.values():
        if path == root:
            continue
        _ensure_directory(path, create=True)
    return result


@contextmanager
def _control_lock(root: Path) -> Iterator[None]:
    root = _ensure_directory(root, create=True)
    lock_path = root / "control.lock"
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        os.chmod(lock_path, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ReportControlError("lock_busy") from exc
        yield
    finally:
        os.close(descriptor)


def _permit_paths(root: Path, authorization_id: str) -> tuple[Path, Path]:
    layout = _control_layout(root)
    return (
        layout["permits"] / f"{authorization_id}.json",
        layout["states"] / f"{authorization_id}.json",
    )


def _append_audit(
    *,
    root: Path,
    permit: Mapping[str, object],
    event: str,
    status: str,
    terminal_evidence_sha256: str | None = None,
) -> None:
    layout = _control_layout(root)
    path = layout["audit"] / "authorization.jsonl"
    entries: list[Mapping[str, object]] = []
    if path.exists():
        for line in _read_regular(path, reason="authorization_audit_invalid").splitlines():
            if not line:
                raise ReportControlError("authorization_audit_invalid")
            entries.append(_strict_json_bytes(line, "authorization_audit_invalid"))
    previous = "0" * 64
    for sequence, existing in enumerate(entries, start=1):
        if (
            existing.get("sequence") != sequence
            or existing.get("previous_entry_sha256") != previous
        ):
            raise ReportControlError("authorization_audit_invalid")
        base = {
            key: existing[key]
            for key in existing
            if key != "entry_sha256"
        }
        if existing.get("entry_sha256") != _sha256(_canonical(base)):
            raise ReportControlError("authorization_audit_invalid")
        previous = str(existing["entry_sha256"])
    permit_payload = _canonical(permit)
    base = {
        "schema_version": "report-authorization-audit-v1",
        "sequence": len(entries) + 1,
        "previous_entry_sha256": previous,
        "authorization_id": permit["authorization_id"],
        "release_sha256": permit["release_sha256"],
        "permit_sha256": _sha256(permit_payload),
        "event": event,
        "status": status,
        "timestamp": _now_text(),
    }
    if terminal_evidence_sha256 is not None:
        base["terminal_evidence_sha256"] = _require_sha(
            terminal_evidence_sha256, "terminal_evidence_sha256"
        )
    entry = {**base, "entry_sha256": _sha256(_canonical(base))}
    payload = _canonical(entry) + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        _write_all(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.chmod(path, 0o600)
    _fsync_directory(path.parent)


def _install_permit(*, root: Path, document: Mapping[str, object]) -> Path:
    authorization_id = _require_id(document.get("authorization_id"), "authorization_id")
    _require_sha(document.get("release_sha256"), "release_sha256")
    permit_path, state_path = _permit_paths(root, authorization_id)
    if permit_path.exists() or permit_path.is_symlink() or state_path.exists() or state_path.is_symlink():
        raise ReportControlError("permit_exists")
    permit_payload = _canonical(document)
    state = {
        "schema_version": "report-permit-state-v1",
        "authorization_id": authorization_id,
        "permit_sha256": _sha256(permit_payload),
        "status": "installed",
        "updated_at": _now_text(),
    }
    _write_new(permit_path, permit_payload + b"\n")
    try:
        _write_new(state_path, _canonical(state) + b"\n")
    except Exception:
        if state_path.exists() and not state_path.is_symlink():
            state_path.unlink()
        if permit_path.exists() and not permit_path.is_symlink():
            permit_path.unlink()
        _fsync_directory(permit_path.parent)
        raise
    # Once state exists the authorization ID stays immutable even if the
    # append-only audit sink fails. Reusing the ID would be less safe than
    # requiring an operator to reconcile the missing audit entry.
    _append_audit(root=root, permit=document, event="installed", status="installed")
    return permit_path


def _load_permit_state(
    *, root: Path, authorization_id: str
) -> tuple[Mapping[str, object], Mapping[str, object], Path]:
    permit_path, state_path = _permit_paths(root, authorization_id)
    permit_bytes = _read_regular(permit_path, reason="permit_invalid")
    permit = _strict_json_bytes(permit_bytes, "permit_invalid")
    state = _strict_json_bytes(
        _read_regular(state_path, reason="permit_state_invalid"),
        "permit_state_invalid",
    )
    if (
        permit.get("authorization_id") != authorization_id
        or state.get("authorization_id") != authorization_id
        or state.get("permit_sha256") != _sha256(_canonical(permit))
    ):
        raise ReportControlError("permit_state_invalid")
    return permit, state, state_path


def _transition_permit(
    *,
    root: Path,
    authorization_id: str,
    expected_release_sha256: str,
    expected_run_id: str | None,
    target_status: str,
    scheduled_commit_receipt_sha256: str | None = None,
    terminal_evidence: Mapping[str, object] | None = None,
) -> None:
    permit, state, state_path = _load_permit_state(
        root=root, authorization_id=authorization_id
    )
    if permit.get("release_sha256") != expected_release_sha256:
        raise ReportControlError("permit_release_mismatch")
    if expected_run_id is not None and permit.get("run_id") != expected_run_id:
        raise ReportControlError("permit_run_mismatch")
    current = state.get("status")
    scheduled_prepare = (
        permit.get("schema_version")
        == "report-scheduled-cycle-prepare-permit-v1"
    )
    if scheduled_prepare and target_status == "consumed":
        if scheduled_commit_receipt_sha256 is None:
            raise ReportControlError("scheduled_prepare_commit_receipt_required")
        receipt = _load_scheduled_commit_receipt(
            control_root=root,
            cycle_id=_require_id(permit.get("cycle_id"), "cycle_id"),
        )
        if (
            receipt.get("commit_receipt_sha256")
            != _require_sha(
                scheduled_commit_receipt_sha256,
                "scheduled_commit_receipt_sha256",
            )
            or receipt.get("prepare_authorization_id") != authorization_id
            or receipt.get("run_id") != permit.get("run_id")
            or receipt.get("release_sha256") != permit.get("release_sha256")
            or receipt.get("cycle_lease_sha256")
            != permit.get("cycle_lease_sha256")
        ):
            raise ReportControlError("scheduled_prepare_commit_receipt_invalid")
    if target_status == "reserved":
        if current != "installed":
            raise ReportControlError("permit_not_reservable")
        expiry = permit.get("expires_at")
        if not isinstance(expiry, str) or not _expiry_is_future(expiry):
            raise ReportControlError("permit_expired")
    else:
        if target_status not in _TERMINAL_STATUSES:
            raise ReportControlError("permit_terminal_status_invalid")
        if current not in {"installed", "reserved"}:
            raise ReportControlError("permit_not_terminalizable")
        if current == "installed" and target_status not in {"closed_no_attempt", "revoked"}:
            raise ReportControlError("permit_not_reserved")
    if terminal_evidence is not None and target_status not in {
        "consumed",
        "partial",
        "blocked",
        "unknown",
        "closed_no_attempt",
    }:
        raise ReportControlError("permit_terminal_evidence_invalid")
    terminal_evidence_sha256 = None
    replacement = {
        **state,
        "status": target_status,
        "updated_at": _now_text(),
    }
    if terminal_evidence is not None:
        terminal_evidence_sha256 = _sha256(_canonical(terminal_evidence))
        replacement["terminal_evidence"] = dict(terminal_evidence)
        replacement["terminal_evidence_sha256"] = terminal_evidence_sha256
    _atomic_replace(state_path, _canonical(replacement) + b"\n")
    # Persist the one-way state first. A crash before audit append leaves the
    # permit non-reusable, which is the required fail-closed outcome.
    _append_audit(
        root=root,
        permit=permit,
        event=target_status,
        status=target_status,
        terminal_evidence_sha256=terminal_evidence_sha256,
    )


def _scheduled_cycle_directory(control_root: Path, *, create: bool) -> Path:
    layout = _control_layout(control_root)
    path = Path(layout["root"]) / "scheduled-cycles"
    if not create and not path.exists() and not path.is_symlink():
        return path
    return _ensure_directory(path, create=create)


def _scheduled_commit_receipt_directory(
    control_root: Path, *, create: bool
) -> Path:
    directory = _scheduled_cycle_directory(control_root, create=create)
    path = directory / "commit-receipts"
    if not create and not path.exists() and not path.is_symlink():
        return path
    return _ensure_directory(path, create=create)


def _load_scheduled_commit_receipt(
    *, control_root: Path, cycle_id: str
) -> Mapping[str, object]:
    cycle_id = _require_id(cycle_id, "cycle_id")
    path = _scheduled_commit_receipt_directory(
        control_root, create=False
    ) / f"{cycle_id}.json"
    receipt = _strict_json_bytes(
        _read_regular(path, reason="scheduled_commit_receipt_invalid"),
        "scheduled_commit_receipt_invalid",
    )
    if set(receipt) != _SCHEDULED_COMMIT_RECEIPT_KEYS:
        raise ReportControlError("scheduled_commit_receipt_invalid")
    base = {
        key: value
        for key, value in receipt.items()
        if key != "commit_receipt_sha256"
    }
    if (
        receipt.get("schema_version")
        != "report-scheduled-cycle-commit-receipt-v1"
        or receipt.get("status") != "host_committed"
        or receipt.get("cycle_id") != cycle_id
        or receipt.get("commit_receipt_sha256")
        != _sha256(_canonical(base))
    ):
        raise ReportControlError("scheduled_commit_receipt_invalid")
    for key in (
        "release_sha256",
        "launcher_sha256",
        "policy_sha256",
        "bundle_sha256",
        "outbox_sha256",
        "commit_request_sha256",
        "cycle_lease_sha256",
        "commit_receipt_sha256",
    ):
        _require_sha(receipt.get(key), key)
    for key in (
        "cycle_id",
        "run_id",
        "policy_authorization_id",
        "prepare_authorization_id",
        "prepare_attempt_id",
    ):
        _require_id(receipt.get(key), key)
    provider_id = receipt.get("provider_authorization_id")
    if provider_id is not None:
        _require_id(provider_id, "provider_authorization_id")
    version_id = receipt.get("artifact_version_id")
    if not isinstance(version_id, str) or _VERSION_ID.fullmatch(version_id) is None:
        raise ReportControlError("scheduled_commit_receipt_invalid")
    try:
        report_date = receipt.get("report_date")
        if not isinstance(report_date, str):
            raise ValueError
        date.fromisoformat(report_date)
    except ValueError as exc:
        raise ReportControlError("scheduled_commit_receipt_invalid") from exc
    _parse_datetime_text(
        receipt.get("committed_at"), "scheduled_commit_receipt_invalid"
    )
    return receipt


def _write_scheduled_commit_receipt(
    *,
    control_root: Path,
    prepare_permit: Mapping[str, object],
    latest: Mapping[str, object],
    attempt_id: str,
    artifact_version_id: str,
    bundle_sha256: str,
    outbox_sha256: str,
    commit_request_sha256: str,
    provider_authorization_id: str | None,
) -> Mapping[str, object]:
    cycle_id = _require_id(prepare_permit.get("cycle_id"), "cycle_id")
    base = {
        "schema_version": "report-scheduled-cycle-commit-receipt-v1",
        "status": "host_committed",
        "cycle_id": cycle_id,
        "report_date": latest["report_date"],
        "run_id": latest["run_id"],
        "release_sha256": latest["release_sha256"],
        "launcher_sha256": latest["launcher_sha256"],
        "policy_sha256": latest["policy_sha256"],
        "policy_authorization_id": latest["policy_authorization_id"],
        "prepare_authorization_id": latest["prepare_authorization_id"],
        "prepare_attempt_id": attempt_id,
        "artifact_version_id": artifact_version_id,
        "bundle_sha256": bundle_sha256,
        "outbox_sha256": outbox_sha256,
        "commit_request_sha256": commit_request_sha256,
        "provider_authorization_id": provider_authorization_id,
        "cycle_lease_sha256": latest["cycle_lease_sha256"],
        "committed_at": _now_text(),
    }
    receipt = {
        **base,
        "commit_receipt_sha256": _sha256(_canonical(base)),
    }
    directory = _scheduled_commit_receipt_directory(control_root, create=True)
    _write_new(directory / f"{cycle_id}.json", _canonical(receipt) + b"\n")
    return _load_scheduled_commit_receipt(
        control_root=control_root, cycle_id=cycle_id
    )


def _load_scheduled_cycle_ledger(
    control_root: Path, *, create: bool = False
) -> tuple[Mapping[str, object], ...]:
    directory = _scheduled_cycle_directory(control_root, create=create)
    path = directory / "ledger.jsonl"
    if not directory.exists() and not directory.is_symlink():
        return ()
    if not path.exists() and not path.is_symlink():
        return ()
    payload = _read_regular(path, reason="scheduled_cycle_ledger_invalid")
    entries: list[Mapping[str, object]] = []
    previous = "0" * 64
    latest_by_cycle: dict[str, str] = {}
    identities: dict[str, tuple[object, ...]] = {}
    consumed_dates: set[str] = set()
    allowed_next = {
        None: {"prepare_reserved"},
        "prepare_reserved": {
            "prepare_committed",
            "prepare_blocked",
            "prepare_unknown",
            "prepare_closed_no_attempt",
        },
        "prepare_committed": {
            "send_permit_derived",
            "prepare_unknown",
        },
        "send_permit_derived": {
            "send_consumed",
            "send_partial",
            "send_blocked",
            "send_unknown",
            "send_closed_no_attempt",
        },
    }
    for sequence, line in enumerate(payload.splitlines(), start=1):
        if not line:
            raise ReportControlError("scheduled_cycle_ledger_invalid")
        entry = _strict_json_bytes(line, "scheduled_cycle_ledger_invalid")
        if set(entry) != _SCHEDULED_CYCLE_EVENT_KEYS:
            raise ReportControlError("scheduled_cycle_ledger_invalid")
        base = {key: entry[key] for key in entry if key != "entry_sha256"}
        cycle_id = entry.get("cycle_id")
        event = entry.get("event")
        if (
            entry.get("schema_version") != "report-scheduled-cycle-event-v1"
            or entry.get("sequence") != sequence
            or entry.get("previous_entry_sha256") != previous
            or entry.get("entry_sha256") != _sha256(_canonical(base))
            or not isinstance(cycle_id, str)
            or _SAFE_ID.fullmatch(cycle_id) is None
            or not isinstance(event, str)
            or event not in allowed_next.get(latest_by_cycle.get(cycle_id), set())
        ):
            raise ReportControlError("scheduled_cycle_ledger_invalid")
        identity = (
            entry.get("report_date"),
            entry.get("run_id"),
            entry.get("release_sha256"),
            entry.get("launcher_sha256"),
            entry.get("policy_sha256"),
            entry.get("policy_authorization_id"),
            entry.get("prepare_authorization_id"),
            entry.get("cycle_lease_sha256"),
        )
        if cycle_id in identities and identities[cycle_id] != identity:
            raise ReportControlError("scheduled_cycle_ledger_invalid")
        identities[cycle_id] = identity
        if event == "prepare_reserved":
            report_date = entry.get("report_date")
            if not isinstance(report_date, str) or report_date in consumed_dates:
                raise ReportControlError("scheduled_cycle_ledger_invalid")
            consumed_dates.add(report_date)
        for key in (
            "release_sha256",
            "launcher_sha256",
            "policy_sha256",
            "cycle_lease_sha256",
        ):
            _require_sha(entry.get(key), key)
        for key in (
            "run_id",
            "policy_authorization_id",
            "prepare_authorization_id",
        ):
            _require_id(entry.get(key), key)
        for key in ("prepare_attempt_id", "send_authorization_id"):
            if entry.get(key) is not None:
                _require_id(entry.get(key), key)
        if entry.get("artifact_version_id") is not None and (
            not isinstance(entry.get("artifact_version_id"), str)
            or _VERSION_ID.fullmatch(str(entry["artifact_version_id"])) is None
        ):
            raise ReportControlError("scheduled_cycle_ledger_invalid")
        for key in (
            "bundle_sha256",
            "outbox_sha256",
            "commit_request_sha256",
            "commit_receipt_sha256",
        ):
            if entry.get(key) is not None:
                _require_sha(entry.get(key), key)
        _parse_datetime_text(entry.get("timestamp"), "scheduled_cycle_ledger_invalid")
        latest_by_cycle[cycle_id] = event
        previous = str(entry["entry_sha256"])
        entries.append(entry)
    return tuple(entries)


def _append_scheduled_cycle_event(
    *,
    control_root: Path,
    event: str,
    cycle_id: str,
    report_date: str,
    run_id: str,
    release_sha256: str,
    launcher_sha256: str,
    policy_sha256: str,
    policy_authorization_id: str,
    prepare_authorization_id: str,
    cycle_lease_sha256: str,
    prepare_attempt_id: str | None = None,
    send_authorization_id: str | None = None,
    artifact_version_id: str | None = None,
    bundle_sha256: str | None = None,
    outbox_sha256: str | None = None,
    commit_request_sha256: str | None = None,
    commit_receipt_sha256: str | None = None,
) -> Mapping[str, object]:
    entries = _load_scheduled_cycle_ledger(control_root, create=True)
    previous = str(entries[-1]["entry_sha256"]) if entries else "0" * 64
    base = {
        "schema_version": "report-scheduled-cycle-event-v1",
        "sequence": len(entries) + 1,
        "previous_entry_sha256": previous,
        "event": event,
        "cycle_id": cycle_id,
        "report_date": report_date,
        "run_id": run_id,
        "release_sha256": release_sha256,
        "launcher_sha256": launcher_sha256,
        "policy_sha256": policy_sha256,
        "policy_authorization_id": policy_authorization_id,
        "prepare_authorization_id": prepare_authorization_id,
        "cycle_lease_sha256": cycle_lease_sha256,
        "prepare_attempt_id": prepare_attempt_id,
        "send_authorization_id": send_authorization_id,
        "artifact_version_id": artifact_version_id,
        "bundle_sha256": bundle_sha256,
        "outbox_sha256": outbox_sha256,
        "commit_request_sha256": commit_request_sha256,
        "commit_receipt_sha256": commit_receipt_sha256,
        "timestamp": _now_text(),
    }
    entry = {**base, "entry_sha256": _sha256(_canonical(base))}
    directory = _scheduled_cycle_directory(control_root, create=True)
    path = directory / "ledger.jsonl"
    payload = b"".join(_canonical(item) + b"\n" for item in (*entries, entry))
    if path.exists() and not path.is_symlink():
        _atomic_replace(path, payload)
    else:
        _write_new(path, payload)
    _load_scheduled_cycle_ledger(control_root)
    return entry


def _latest_scheduled_cycle_event(
    entries: Sequence[Mapping[str, object]], cycle_id: str
) -> Mapping[str, object]:
    matches = [entry for entry in entries if entry.get("cycle_id") == cycle_id]
    if not matches:
        raise ReportControlError("scheduled_cycle_not_found")
    return matches[-1]


def _append_scheduled_cycle_terminal(
    *,
    control_root: Path,
    latest: Mapping[str, object],
    event: str,
) -> Mapping[str, object]:
    return _append_scheduled_cycle_event(
        control_root=control_root,
        event=event,
        cycle_id=str(latest["cycle_id"]),
        report_date=str(latest["report_date"]),
        run_id=str(latest["run_id"]),
        release_sha256=str(latest["release_sha256"]),
        launcher_sha256=str(latest["launcher_sha256"]),
        policy_sha256=str(latest["policy_sha256"]),
        policy_authorization_id=str(latest["policy_authorization_id"]),
        prepare_authorization_id=str(latest["prepare_authorization_id"]),
        cycle_lease_sha256=str(latest["cycle_lease_sha256"]),
        prepare_attempt_id=(
            str(latest["prepare_attempt_id"])
            if latest.get("prepare_attempt_id") is not None
            else None
        ),
        send_authorization_id=(
            str(latest["send_authorization_id"])
            if latest.get("send_authorization_id") is not None
            else None
        ),
        artifact_version_id=(
            str(latest["artifact_version_id"])
            if latest.get("artifact_version_id") is not None
            else None
        ),
        bundle_sha256=(
            str(latest["bundle_sha256"])
            if latest.get("bundle_sha256") is not None
            else None
        ),
        outbox_sha256=(
            str(latest["outbox_sha256"])
            if latest.get("outbox_sha256") is not None
            else None
        ),
        commit_request_sha256=(
            str(latest["commit_request_sha256"])
            if latest.get("commit_request_sha256") is not None
            else None
        ),
        commit_receipt_sha256=(
            str(latest["commit_receipt_sha256"])
            if latest.get("commit_receipt_sha256") is not None
            else None
        ),
    )


def _recover_scheduled_cycles(control_root: Path) -> Mapping[str, object]:
    """Close every abandoned scheduled cycle without ever resuming side effects."""
    entries = list(_load_scheduled_cycle_ledger(control_root, create=True))
    latest_by_cycle: dict[str, Mapping[str, object]] = {}
    for entry in entries:
        latest_by_cycle[str(entry["cycle_id"])] = entry
    reconciled = 0
    for cycle_id in sorted(latest_by_cycle):
        latest = latest_by_cycle[cycle_id]
        event = str(latest["event"])
        if event not in {
            "prepare_reserved",
            "prepare_committed",
            "send_permit_derived",
        }:
            continue
        authorization_key = (
            "prepare_authorization_id"
            if event in {"prepare_reserved", "prepare_committed"}
            else "send_authorization_id"
        )
        authorization_id = latest.get(authorization_key)
        if not isinstance(authorization_id, str):
            terminal_event = (
                "prepare_unknown"
                if event in {"prepare_reserved", "prepare_committed"}
                else "send_unknown"
            )
        else:
            try:
                _permit, state, _state_path = _load_permit_state(
                    root=control_root, authorization_id=authorization_id
                )
                status = state.get("status")
            except ReportControlError:
                status = "unknown"
            prefix = (
                "prepare"
                if event in {"prepare_reserved", "prepare_committed"}
                else "send"
            )
            if status in {"closed_no_attempt", "installed"}:
                terminal_event = f"{prefix}_closed_no_attempt"
            elif status == "blocked":
                terminal_event = f"{prefix}_blocked"
            elif status == "partial" and event == "send_permit_derived":
                terminal_event = "send_partial"
            elif status == "consumed" and event == "send_permit_derived":
                terminal_event = "send_consumed"
            else:
                # A reserved prepare may have reached Provider, a consumed
                # prepare may have reached host commit, and any reserved send
                # may have reached HTTP. None is safe to resume automatically.
                terminal_event = f"{prefix}_unknown"
            if status in {"installed", "reserved"}:
                try:
                    _transition_permit(
                        root=control_root,
                        authorization_id=authorization_id,
                        expected_release_sha256=str(latest["release_sha256"]),
                        expected_run_id=str(latest["run_id"]),
                        target_status=(
                            "closed_no_attempt"
                            if terminal_event.endswith("closed_no_attempt")
                            else "unknown"
                        ),
                    )
                except ReportControlError:
                    terminal_event = f"{prefix}_unknown"
        _append_scheduled_cycle_terminal(
            control_root=control_root, latest=latest, event=terminal_event
        )
        reconciled += 1
    return {
        "status": "recovered",
        "reconciled_cycle_count": reconciled,
        "automatic_prepare": False,
        "automatic_send": False,
    }


def _policy_path(
    supplied: Path | None, *, production: Path, reason: str
) -> Path:
    path = Path(supplied or production)
    if os.getenv("REDDIT_VOC_LOCAL_TEST_MODE") != "1" and path != production:
        raise ReportControlError(reason)
    return path


def _read_user_crontab(args: argparse.Namespace) -> bytes:
    if os.getenv("REDDIT_VOC_LOCAL_TEST_MODE") == "1":
        if args.user_crontab_snapshot_file is None:
            raise ReportControlError("secondary_cron_inspection_unavailable")
        return _read_regular(
            Path(args.user_crontab_snapshot_file),
            reason="secondary_cron_inspection_unavailable",
        )
    try:
        ubuntu = pwd.getpwnam("ubuntu")
    except KeyError as exc:
        raise ReportControlError("secondary_cron_inspection_unavailable") from exc
    if os.geteuid() != ubuntu.pw_uid:
        raise ReportControlError("scheduler_principal_invalid")
    try:
        completed = subprocess.run(
            ["crontab", "-l"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ReportControlError("secondary_cron_inspection_unavailable") from exc
    if completed.returncode == 0:
        return completed.stdout
    if completed.returncode == 1 and not completed.stdout:
        return b""
    raise ReportControlError("secondary_cron_inspection_unavailable")


def _legacy_process_present(args: argparse.Namespace, token: str) -> bool:
    if os.getenv("REDDIT_VOC_LOCAL_TEST_MODE") == "1":
        if args.process_snapshot_file is None:
            raise ReportControlError("secondary_process_inspection_unavailable")
        payload = _read_regular(
            Path(args.process_snapshot_file),
            reason="secondary_process_inspection_unavailable",
        )
        return token.encode("utf-8") in {
            item.strip() for item in payload.replace(b"\0", b"\n").splitlines()
        }
    try:
        ubuntu_uid = pwd.getpwnam("ubuntu").pw_uid
    except KeyError as exc:
        raise ReportControlError("secondary_process_inspection_unavailable") from exc
    if os.geteuid() != ubuntu_uid:
        raise ReportControlError("scheduler_principal_invalid")
    proc = Path("/proc")
    if not proc.is_dir() or proc.is_symlink():
        raise ReportControlError("secondary_process_inspection_unavailable")
    try:
        entries = tuple(proc.iterdir())
    except OSError as exc:
        raise ReportControlError("secondary_process_inspection_unavailable") from exc
    target = token.encode("utf-8")
    for entry in entries:
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            status = (entry / "status").read_bytes()
        except (OSError, PermissionError) as exc:
            raise ReportControlError(
                "secondary_process_inspection_unavailable"
            ) from exc
        uid_line = next(
            (line for line in status.splitlines() if line.startswith(b"Uid:")),
            None,
        )
        if uid_line is None:
            raise ReportControlError("secondary_process_inspection_unavailable")
        try:
            real_uid = int(uid_line.split()[1])
        except (IndexError, ValueError) as exc:
            raise ReportControlError(
                "secondary_process_inspection_unavailable"
            ) from exc
        if real_uid != ubuntu_uid:
            continue
        try:
            argv = tuple(
                item
                for item in (entry / "cmdline").read_bytes().split(b"\0")
                if item
            )
            executable = os.readlink(entry / "exe").encode("utf-8")
        except (OSError, PermissionError, UnicodeError) as exc:
            raise ReportControlError(
                "secondary_process_inspection_unavailable"
            ) from exc
        if target in argv or executable == target:
            return True
    return False


def _validate_live_schedule_postimage(
    args: argparse.Namespace, *, marker: Mapping[str, object]
) -> None:
    stable_entrypoint_path = _policy_path(
        getattr(args, "stable_entrypoint_file", None),
        production=_G6R1_STABLE_ENTRYPOINT_PATH,
        reason="stable_entrypoint_path_invalid",
    )
    stable_payload = _read_stable_entrypoint(stable_entrypoint_path)
    if _sha256(stable_payload) != marker.get("stable_entrypoint_sha256"):
        raise ReportControlError("stable_entrypoint_postimage_drift")
    cron_path = _policy_path(
        args.primary_cron_file,
        production=_G6R1_PRIMARY_CRON_PATH,
        reason="primary_cron_path_invalid",
    )
    if os.getenv("REDDIT_VOC_LOCAL_TEST_MODE") == "1":
        cron_payload = _read_regular(cron_path, reason="primary_cron_invalid")
    else:
        cron_payload = _read_host_regular(
            cron_path,
            allowed_modes=frozenset({0o644}),
            allowed_uids=frozenset({0}),
            reason="primary_cron_invalid",
        )
    if _sha256(cron_payload) != marker.get("primary_cron_sha256"):
        raise ReportControlError("primary_cron_postimage_drift")
    try:
        cron_lines = cron_payload.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ReportControlError("primary_cron_invalid") from exc
    active = [line.strip() for line in cron_lines if line.strip() and not line.lstrip().startswith("#")]
    if (
        active.count("CRON_TZ=Asia/Shanghai") != 1
        or active.count(_G6R1_PRIMARY_CRON_LINE) != 1
        or sum(1 for line in active if line.startswith("0 8 * * * ")) != 1
    ):
        raise ReportControlError("primary_cron_postimage_drift")

    disposition_path = _policy_path(
        args.secondary_disposition_file,
        production=_G6R1_SECONDARY_DISPOSITION_PATH,
        reason="secondary_disposition_path_invalid",
    )
    disposition_payload = _read_authority_regular(
        disposition_path, reason="secondary_disposition_invalid"
    )
    if _sha256(disposition_payload) != marker.get("secondary_disposition_sha256"):
        raise ReportControlError("secondary_disposition_invalid")
    disposition = _strict_json_bytes(
        disposition_payload, "secondary_disposition_invalid"
    )
    validate_g6r1_secondary_disposition(disposition)
    legacy_path_text = disposition.get("legacy_script_path")
    if (
        legacy_path_text != _G6R1_LEGACY_SCRIPT_PATH
        or disposition.get("legacy_cron_token") != _G6R1_LEGACY_CRON_LINE
        or disposition.get("legacy_process_token") != _G6R1_LEGACY_SCRIPT_PATH
    ):
        raise ReportControlError("secondary_disposition_invalid")
    legacy_path = Path(legacy_path_text)
    if legacy_path.exists() or legacy_path.is_symlink():
        # Presence alone is sufficient evidence. Never read this legacy file;
        # historical bytes may contain credential material.
        raise ReportControlError("secondary_legacy_path_present")
    crontab = _read_user_crontab(args)
    try:
        user_lines = [
            line.strip()
            for line in crontab.decode("utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
    except UnicodeDecodeError as exc:
        raise ReportControlError("secondary_cron_inspection_unavailable") from exc
    if _G6R1_LEGACY_CRON_LINE in user_lines or any(
        _G6R1_LEGACY_SCRIPT_PATH in line for line in user_lines
    ):
        raise ReportControlError("secondary_cron_present")
    if _G6R1_LEGACY_CRON_LINE in active or any(
        _G6R1_LEGACY_SCRIPT_PATH in line for line in active
    ):
        raise ReportControlError("secondary_cron_present")
    if _legacy_process_present(args, _G6R1_LEGACY_SCRIPT_PATH):
        raise ReportControlError("secondary_process_present")


def _validate_g6r1_activation(
    args: argparse.Namespace,
    *,
    release_sha256: str,
    stable_entrypoint_sha256: str,
    release_launcher_sha256: str,
    policy_sha256: str,
    policy_permit: Mapping[str, object],
    rotation_receipt_sha256: str,
    report_env_install_receipt_sha256: str,
) -> Mapping[str, object]:
    marker_path = _policy_path(
        args.activation_marker_file,
        production=_G6R1_ACTIVATION_MARKER_PATH,
        reason="activation_marker_path_invalid",
    )
    transactions_root = Path(args.transactions_root or _G6R1_TRANSACTIONS_ROOT)
    if (
        os.getenv("REDDIT_VOC_LOCAL_TEST_MODE") != "1"
        and transactions_root != _G6R1_TRANSACTIONS_ROOT
    ):
        raise ReportControlError("transaction_root_invalid")
    transactions_root = _require_authority_directory(
        transactions_root, reason="transaction_root_invalid"
    )
    journals: dict[str, tuple[Mapping[str, object], str]] = {}
    for transaction_root in sorted(transactions_root.iterdir()):
        if transaction_root.name.startswith("."):
            raise ReportControlError("transaction_journal_invalid")
        _require_authority_directory(
            transaction_root, reason="transaction_journal_invalid"
        )
        transaction_id = _require_id(transaction_root.name, "transaction_id")
        journal_path = transaction_root / "journal.json"
        payload = _read_authority_regular(
            journal_path, reason="transaction_journal_invalid"
        )
        journal = _validate_g6r1_transaction_journal(
            payload, transaction_id=transaction_id
        )
        journals[transaction_id] = (journal, _sha256(payload))
    if not journals:
        raise ReportControlError("transaction_journal_missing")

    marker_payload = _read_authority_regular(
        marker_path, reason="activation_marker_invalid"
    )
    marker_document = _strict_json_bytes(
        marker_payload, "activation_marker_invalid"
    )
    dual_authority = policy_permit.get("schema_version") in {
        "report-scheduled-cycle-policy-permit-v2",
        "report-scheduled-cycle-policy-permit-v3",
    }
    marker = (
        validate_g6r1_activation_marker_v2(marker_document)
        if dual_authority
        else validate_g6r1_activation_marker(marker_document)
    )
    transaction_id = _require_id(marker.get("transaction_id"), "transaction_id")
    owner_permit_sha = _sha256(_canonical(policy_permit))
    if (
        marker.get("release_sha256") != release_sha256
        or marker.get("stable_entrypoint_sha256")
        != stable_entrypoint_sha256
        or marker.get("release_launcher_sha256")
        != release_launcher_sha256
        or marker.get("child_policy_sha256") != policy_sha256
        or marker.get("owner_permit_sha256") != owner_permit_sha
        or marker.get("report_env_install_receipt_sha256")
        != report_env_install_receipt_sha256
    ):
        raise ReportControlError("activation_marker_invalid")
    if dual_authority:
        if (
            marker.get("credential_set_receipt_sha256")
            != rotation_receipt_sha256
            or marker.get("destination_set_id")
            != policy_permit.get("destination_set_id")
            or marker.get("destinations") != policy_permit.get("destinations")
        ):
            raise ReportControlError("activation_marker_invalid")
    elif marker.get("rotation_receipt_sha256") != rotation_receipt_sha256:
        raise ReportControlError("activation_marker_invalid")
    for key in (
        "release_sha256",
        "stable_entrypoint_sha256",
        "release_launcher_sha256",
        "child_policy_sha256",
        "owner_permit_sha256",
        "report_env_install_receipt_sha256",
        "secondary_disposition_sha256",
        "journal_file_sha256",
        "primary_cron_sha256",
        "activation_marker_sha256",
    ):
        _require_sha(marker.get(key), key)
    _require_sha(
        marker.get(
            "credential_set_receipt_sha256"
            if dual_authority
            else "rotation_receipt_sha256"
        ),
        "credential_authority_receipt_sha256",
    )
    selected = journals.get(transaction_id)
    if (
        selected is None
        or selected[0].get("phase") != "committed"
        or marker.get("journal_file_sha256") != selected[1]
    ):
        raise ReportControlError("activation_marker_journal_mismatch")
    _validate_live_schedule_postimage(args, marker=marker)
    return marker


def _load_scheduled_cycle_policy(
    args: argparse.Namespace,
    *,
    control_root: Path,
    release_sha256: str,
    launcher_sha256: str,
    run_id: str,
    scheduled_at: str,
    enforce_current_slot: bool = True,
    expected_report_date: str | None = None,
) -> Mapping[str, object]:
    parent_path = _policy_path(
        args.parent_policy_file,
        production=_G6R5_DAILY_POLICY_PATH,
        reason="parent_policy_path_invalid",
    )
    policy_path = _policy_path(
        args.policy_file,
        production=_G6R1_SCHEDULED_POLICY_PATH,
        reason="scheduled_policy_path_invalid",
    )
    rotation_path = _policy_path(
        args.credential_rotation_receipt_file,
        production=_G6R1_ROTATION_RECEIPT_PATH,
        reason="credential_rotation_receipt_path_invalid",
    )
    report_env_receipt_path = _policy_path(
        getattr(args, "report_env_install_receipt_file", None),
        production=_G6R1_REPORT_ENV_INSTALL_RECEIPT_PATH,
        reason="report_env_install_receipt_path_invalid",
    )
    dual_credential_set_receipt_path = _policy_path(
        getattr(args, "dual_credential_set_receipt_file", None),
        production=_G6R1_DUAL_CREDENTIAL_SET_RECEIPT_PATH,
        reason="dual_credential_set_receipt_path_invalid",
    )
    dual_report_env_receipt_path = _policy_path(
        getattr(args, "dual_report_env_install_receipt_file", None),
        production=_G6R1_DUAL_REPORT_ENV_INSTALL_RECEIPT_PATH,
        reason="dual_report_env_install_receipt_path_invalid",
    )
    parent_payload = _read_authority_regular(
        parent_path, reason="parent_policy_invalid"
    )
    parent_sha = _sha256(parent_payload)
    expected_parent_sha = str(
        args.expected_parent_policy_sha256 or _G6R5_DAILY_POLICY_SHA256
    )
    if (
        os.getenv("REDDIT_VOC_LOCAL_TEST_MODE") != "1"
        and expected_parent_sha != _G6R5_DAILY_POLICY_SHA256
    ):
        raise ReportControlError("parent_policy_sha256_invalid")
    if parent_sha != _require_sha(expected_parent_sha, "parent_policy_sha256"):
        raise ReportControlError("parent_policy_sha256_mismatch")
    parent = _strict_json_bytes(parent_payload, "parent_policy_invalid")
    annual_authority = parent_sha == _G6R5_DAILY_POLICY_SHA256
    if annual_authority:
        validate_g6r5_parent_policy(parent)
    else:
        if (
            os.getenv("REDDIT_VOC_LOCAL_TEST_MODE") != "1"
            or set(parent) != _LEGACY_POLICY_KEYS
            or parent.get("schema_version")
            != "reddit-voc-bounded-daily-live-policy-v1"
            or parent.get("cadence") != "daily"
            or parent.get("max_scheduled_runs") != 30
            or parent.get("required_keyword") != "LL"
            or parent.get("starts_at_utc")
            != "2026-08-01T08:41:23+00:00"
            or parent.get("expires_at_utc")
            != "2026-08-31T00:30:00+00:00"
        ):
            raise ReportControlError("parent_policy_invalid")
        _require_sha(
            parent.get("destination_fingerprint"), "destination_fingerprint"
        )

    policy_payload = _read_authority_regular(
        policy_path, reason="scheduled_policy_invalid"
    )
    policy_sha = _sha256(policy_payload)
    policy_document = _strict_json_bytes(policy_payload, "scheduled_policy_invalid")
    stable_entrypoint_sha = _require_sha(
        policy_document.get("stable_entrypoint_sha256"),
        "stable_entrypoint_sha256",
    )
    policy_schema = policy_document.get("schema_version")
    annual_policy = policy_schema == "reddit-voc-g6r5-scheduled-cycle-policy-v3"
    dual_authority = policy_schema in {
        "reddit-voc-g6r1-scheduled-cycle-policy-v2",
        "reddit-voc-g6r5-scheduled-cycle-policy-v3",
    }
    if annual_authority != annual_policy:
        raise ReportControlError("scheduled_policy_invalid")
    if annual_policy:
        policy = validate_g6r5_scheduled_cycle_policy_v3(
            policy_document,
            parent_policy_sha256=parent_sha,
            release_sha256=release_sha256,
            stable_entrypoint_sha256=stable_entrypoint_sha,
            release_launcher_sha256=launcher_sha256,
        )
    elif dual_authority:
        policy = validate_g6r1_scheduled_cycle_policy_v2(
            policy_document,
            parent_policy_sha256=parent_sha,
            release_sha256=release_sha256,
            stable_entrypoint_sha256=stable_entrypoint_sha,
            release_launcher_sha256=launcher_sha256,
        )
    else:
        policy = validate_g6r1_scheduled_cycle_policy(
            policy_document,
            parent_policy_sha256=parent_sha,
            release_sha256=release_sha256,
            stable_entrypoint_sha256=stable_entrypoint_sha,
            release_launcher_sha256=launcher_sha256,
        )
    authorization_id = _require_id(
        policy.get("authorization_id"), "policy_authorization_id"
    )
    expected_slots = (
        _canonical_g6r5_slots() if annual_policy else _canonical_g6r1_slots()
    )

    if dual_authority:
        credential_set_epoch_id, destination_set_id, destinations = (
            _require_g6r1_dual_identity(
                credential_set_epoch_id=policy.get("credential_set_epoch_id"),
                destination_set_id=policy.get("destination_set_id"),
                destinations=policy.get("destinations"),
            )
        )
        credential_authority_sha = _require_sha(
            policy.get("credential_set_receipt_sha256"),
            "credential_set_receipt_sha256",
        )
        credential_payload = _read_authority_regular(
            dual_credential_set_receipt_path,
            reason="dual_credential_set_receipt_invalid",
        )
        if _sha256(credential_payload) != credential_authority_sha:
            raise ReportControlError("dual_credential_set_receipt_invalid")
        credential_receipt = validate_g6r1_dual_credential_set_receipt(
            _strict_json_bytes(
                credential_payload, "dual_credential_set_receipt_invalid"
            )
        )
        if (
            credential_receipt.get("credential_set_epoch_id")
            != credential_set_epoch_id
            or credential_receipt.get("destination_set_id")
            != destination_set_id
            or credential_receipt.get("destinations") != destinations
        ):
            raise ReportControlError("dual_credential_set_receipt_invalid")
        report_env_receipt_sha = _require_sha(
            credential_receipt.get("report_env_install_receipt_sha256"),
            "report_env_install_receipt_sha256",
        )
        report_env_receipt_payload = _read_authority_regular(
            dual_report_env_receipt_path,
            reason="dual_report_env_install_receipt_invalid",
        )
        if _sha256(report_env_receipt_payload) != report_env_receipt_sha:
            raise ReportControlError("dual_report_env_install_receipt_invalid")
        report_env_receipt = validate_g6r1_dual_report_env_install_receipt(
            _strict_json_bytes(
                report_env_receipt_payload,
                "dual_report_env_install_receipt_invalid",
            )
        )
        if (
            report_env_receipt.get("credential_set_epoch_id")
            != credential_set_epoch_id
            or report_env_receipt.get("destination_set_id")
            != destination_set_id
            or report_env_receipt.get("destinations") != destinations
        ):
            raise ReportControlError("dual_report_env_install_receipt_invalid")
        credential_ready_at = _parse_datetime_text(
            credential_receipt.get("installed_at_utc"),
            "dual_credential_set_receipt_invalid",
        )
        credential_epoch_id = None
        destination_alias = None
    else:
        credential_epoch_id = _require_id(
            policy.get("credential_epoch_id"), "credential_epoch_id"
        )
        destination_alias = _require_id(
            policy.get("destination_alias"), "destination_alias"
        )
        credential_set_epoch_id = None
        destination_set_id = None
        destinations = None
        credential_authority_sha = _require_sha(
            policy.get("credential_rotation_receipt_sha256"),
            "credential_rotation_receipt_sha256",
        )
        rotation_payload = _read_authority_regular(
            rotation_path, reason="credential_rotation_receipt_invalid"
        )
        if _sha256(rotation_payload) != credential_authority_sha:
            raise ReportControlError("credential_rotation_receipt_invalid")
        credential_receipt = validate_g6r1_rotation_receipt(
            _strict_json_bytes(
                rotation_payload, "credential_rotation_receipt_invalid"
            )
        )
        if (
            credential_receipt.get("credential_epoch_id")
            != credential_epoch_id
            or credential_receipt.get("destination_alias")
            != destination_alias
        ):
            raise ReportControlError("credential_rotation_receipt_invalid")
        report_env_receipt_sha = _require_sha(
            credential_receipt.get("report_env_install_receipt_sha256"),
            "report_env_install_receipt_sha256",
        )
        report_env_receipt_payload = _read_authority_regular(
            report_env_receipt_path,
            reason="report_env_install_receipt_invalid",
        )
        if _sha256(report_env_receipt_payload) != report_env_receipt_sha:
            raise ReportControlError("report_env_install_receipt_invalid")
        report_env_receipt = validate_g6r1_report_env_install_receipt(
            _strict_json_bytes(
                report_env_receipt_payload,
                "report_env_install_receipt_invalid",
            )
        )
        if (
            report_env_receipt.get("credential_epoch_id")
            != credential_epoch_id
            or report_env_receipt.get("destination_alias") != destination_alias
        ):
            raise ReportControlError("report_env_install_receipt_invalid")
        credential_ready_at = _parse_datetime_text(
            credential_receipt.get("rotated_at_utc"),
            "credential_rotation_receipt_invalid",
        )
    _validate_report_env_install_identity(args, report_env_receipt)

    owner_permit_path = _policy_path(
        args.owner_policy_permit_file,
        production=_G6R1_OWNER_POLICY_PERMIT_PATH,
        reason="scheduled_policy_authority_path_invalid",
    )
    try:
        permit = _strict_json_bytes(
            _read_authority_regular(
                owner_permit_path,
                reason="scheduled_policy_authorization_missing",
            ),
            "scheduled_policy_authorization_invalid",
        )
    except ReportControlError as exc:
        raise ReportControlError("scheduled_policy_authorization_missing") from exc
    if annual_policy:
        validate_g6r5_owner_policy_permit_v3(
            permit,
            authorization_id=authorization_id,
            release_sha256=release_sha256,
            stable_entrypoint_sha256=stable_entrypoint_sha,
            release_launcher_sha256=launcher_sha256,
            policy_sha256=policy_sha,
            parent_policy_sha256=parent_sha,
            credential_set_receipt_sha256=credential_authority_sha,
            credential_set_epoch_id=credential_set_epoch_id,
            destination_set_id=destination_set_id,
        )
    elif dual_authority:
        validate_g6r1_owner_policy_permit_v2(
            permit,
            authorization_id=authorization_id,
            release_sha256=release_sha256,
            stable_entrypoint_sha256=stable_entrypoint_sha,
            release_launcher_sha256=launcher_sha256,
            policy_sha256=policy_sha,
            parent_policy_sha256=parent_sha,
            credential_set_receipt_sha256=credential_authority_sha,
            credential_set_epoch_id=credential_set_epoch_id,
            destination_set_id=destination_set_id,
        )
    else:
        validate_g6r1_owner_policy_permit(
            permit,
            authorization_id=authorization_id,
            release_sha256=release_sha256,
            stable_entrypoint_sha256=stable_entrypoint_sha,
            release_launcher_sha256=launcher_sha256,
            policy_sha256=policy_sha,
            parent_policy_sha256=parent_sha,
            credential_rotation_receipt_sha256=credential_authority_sha,
            credential_epoch_id=credential_epoch_id,
            destination_alias=destination_alias,
        )
    if not _expiry_is_future(str(permit.get("expires_at") or "")):
        raise ReportControlError("scheduled_policy_authorization_invalid")
    _validate_g6r1_activation(
        args,
        release_sha256=release_sha256,
        stable_entrypoint_sha256=stable_entrypoint_sha,
        release_launcher_sha256=launcher_sha256,
        policy_sha256=policy_sha,
        policy_permit=permit,
        rotation_receipt_sha256=credential_authority_sha,
        report_env_install_receipt_sha256=report_env_receipt_sha,
    )

    if enforce_current_slot:
        if os.getenv("REDDIT_VOC_LOCAL_TEST_MODE") == "1":
            slot_at = _parse_datetime_text(
                scheduled_at, "scheduled_time_invalid"
            ).astimezone(_G6R1_TIMEZONE)
        else:
            if args.scheduled_at is not None:
                raise ReportControlError("schedule_time_override_forbidden")
            slot_at = datetime.now(_G6R1_TIMEZONE)
        if (
            slot_at.hour != _G6R1_LOCAL_TIME.hour
            or not 0 <= slot_at.minute < _G6R1_EXECUTION_WINDOW_MINUTES
        ):
            raise ReportControlError("scheduled_time_invalid")
        report_date = slot_at.date().isoformat()
    else:
        if not isinstance(expected_report_date, str):
            raise ReportControlError("scheduled_slot_identity_mismatch")
        try:
            slot_day = date.fromisoformat(expected_report_date)
        except ValueError as exc:
            raise ReportControlError("scheduled_slot_identity_mismatch") from exc
        slot_at = datetime.combine(
            slot_day, _G6R1_LOCAL_TIME, tzinfo=_G6R1_TIMEZONE
        )
        report_date = expected_report_date
    matching = [
        slot
        for slot in expected_slots
        if slot["report_date"] == report_date
    ]
    if len(matching) != 1 or matching[0]["run_id"] != run_id:
        raise ReportControlError("scheduled_slot_identity_mismatch")
    slot_utc = slot_at.astimezone(timezone.utc)
    starts = _parse_datetime_text(policy["starts_at_utc"], "scheduled_policy_invalid")
    expires = _parse_datetime_text(policy["expires_at_utc"], "scheduled_policy_invalid")
    parent_starts = _parse_datetime_text(
        parent["starts_at_utc"], "parent_policy_invalid"
    )
    parent_expires = _parse_datetime_text(
        parent["expires_at_utc"], "parent_policy_invalid"
    )
    if not (
        starts <= slot_utc < expires
        and parent_starts <= slot_utc < parent_expires
        and credential_ready_at.astimezone(timezone.utc) <= slot_utc
    ):
        raise ReportControlError("scheduled_slot_inactive")
    return {
        "policy": policy,
        "policy_sha256": policy_sha,
        "policy_authorization_id": authorization_id,
        "parent_policy_sha256": parent_sha,
        "credential_rotation_receipt_sha256": (
            None if dual_authority else credential_authority_sha
        ),
        "credential_set_receipt_sha256": (
            credential_authority_sha if dual_authority else None
        ),
        "report_env_install_receipt_sha256": report_env_receipt_sha,
        "stable_entrypoint_sha256": stable_entrypoint_sha,
        "slot": matching[0],
        "report_date": report_date,
        "credential_epoch_id": credential_epoch_id,
        "destination_alias": destination_alias,
        "credential_set_epoch_id": credential_set_epoch_id,
        "destination_set_id": destination_set_id,
        "destinations": destinations,
        "destination_mode": "dual" if dual_authority else "single",
        "required_keyword": "LL",
        "provider_attempt_policy": policy["provider_attempt_policy"],
    }


def _scheduled_cycle_id(
    *,
    policy_sha256: str,
    release_sha256: str,
    launcher_sha256: str,
    report_date: str,
    run_id: str,
) -> str:
    digest = _sha256(
        _canonical(
            {
                "policy_sha256": policy_sha256,
                "release_sha256": release_sha256,
                "launcher_sha256": launcher_sha256,
                "report_date": report_date,
                "run_id": run_id,
            }
        )
    )[:24]
    return f"g6r1-cycle-{report_date.replace('-', '')}-{digest}"


def _require_scheduled_send_window(
    *, report_date: str, expires_at: str, scheduled_at: str | None
) -> None:
    try:
        report_day = date.fromisoformat(report_date)
    except ValueError as exc:
        raise ReportControlError("scheduled_cycle_lease_expired") from exc
    expected_deadline = datetime.combine(
        report_day, _G6R1_SEND_WINDOW_END, tzinfo=_G6R1_TIMEZONE
    ).astimezone(timezone.utc)
    expected_expiry = expected_deadline.strftime("%Y-%m-%dT%H:%M:%SZ")
    if expires_at != expected_expiry:
        raise ReportControlError("scheduled_send_deadline_invalid")
    if os.getenv("REDDIT_VOC_LOCAL_TEST_MODE") == "1":
        if not isinstance(scheduled_at, str):
            raise ReportControlError("scheduled_time_invalid")
        current = _parse_datetime_text(
            scheduled_at, "scheduled_time_invalid"
        ).astimezone(_G6R1_TIMEZONE)
    else:
        if scheduled_at is not None:
            raise ReportControlError("schedule_time_override_forbidden")
        current = datetime.now(_G6R1_TIMEZONE)
    window_start = datetime.combine(
        report_day, _G6R1_LOCAL_TIME, tzinfo=_G6R1_TIMEZONE
    )
    window_end = datetime.combine(
        report_day, _G6R1_SEND_WINDOW_END, tzinfo=_G6R1_TIMEZONE
    )
    if (
        current.date().isoformat() != report_date
        or current < window_start
        or current >= window_end
    ):
        raise ReportControlError("scheduled_cycle_lease_expired")


def _paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _init_shadow_root(args: argparse.Namespace) -> Path:
    if not args.authorize_shadow_provisioning:
        raise ReportControlError("shadow_provisioning_not_authorized")
    authorization_id = _require_id(args.authorization_id, "authorization_id")
    release_sha = _require_sha(args.expected_release_sha256, "release_sha256")
    candidate_sha = _require_sha(args.candidate_sha256, "candidate_sha256")
    raw_root = Path(args.shadow_root)
    if not raw_root.is_absolute():
        raise ReportControlError("shadow_root_not_absolute")
    root = raw_root.resolve(strict=False)
    repo_root = Path(__file__).resolve().parents[1]
    forbidden = (*_PRODUCTION_ROOTS, repo_root)
    if any(_paths_overlap(root, item.resolve(strict=False)) for item in forbidden):
        raise ReportControlError("shadow_root_overlap_forbidden")
    if root.exists() or root.is_symlink():
        raise ReportControlError("shadow_root_exists")
    root.mkdir(parents=False, mode=0o700)
    root.chmod(0o700)
    names = (
        "secrets",
        "control",
        "state",
        "public",
        "private",
        "public-staging",
        "private-staging",
        "blocked",
        "handoff",
        "provider-attempts",
        "logs",
        "database",
    )
    try:
        paths: dict[str, str] = {}
        for name in names:
            child = root / name
            mode = 0o755 if name == "public" else 0o700
            child.mkdir(mode=mode)
            child.chmod(mode)
            paths[name.replace("-", "_")] = str(child)
        _control_layout(root / "control")
        descriptor = {
            "schema_version": "report-shadow-root-v1",
            "authorization_id": authorization_id,
            "shadow_root": str(root),
            "owner_uid": os.getuid(),
            "candidate_sha256": candidate_sha,
            "release_sha256": release_sha,
            "paths": paths,
            "status": "initialized",
        }
        _write_new(root / "shadow-root.json", _canonical(descriptor) + b"\n")
        _fsync_directory(root)
        return root
    except Exception:
        # The descriptor is the commit marker. A failed initialization leaves a
        # visibly incomplete root and never grants shadow authority.
        raise


def _load_shadow_descriptor(root: Path) -> Mapping[str, object]:
    if not root.is_absolute():
        raise ReportControlError("shadow_root_not_absolute")
    root = root.resolve(strict=True)
    _ensure_directory(root)
    descriptor = _strict_json_bytes(
        _read_regular(root / "shadow-root.json", reason="shadow_descriptor_invalid"),
        "shadow_descriptor_invalid",
    )
    expected_keys = {
        "schema_version",
        "authorization_id",
        "shadow_root",
        "owner_uid",
        "candidate_sha256",
        "release_sha256",
        "paths",
        "status",
    }
    if (
        set(descriptor) != expected_keys
        or descriptor.get("schema_version") != "report-shadow-root-v1"
        or descriptor.get("shadow_root") != str(root)
        or descriptor.get("owner_uid") != os.getuid()
        or descriptor.get("status") != "initialized"
    ):
        raise ReportControlError("shadow_descriptor_invalid")
    names = (
        "secrets",
        "control",
        "state",
        "public",
        "private",
        "public-staging",
        "private-staging",
        "blocked",
        "handoff",
        "provider-attempts",
        "logs",
        "database",
    )
    expected_paths = {
        name.replace("-", "_"): str(root / name) for name in names
    }
    if descriptor.get("paths") != expected_paths:
        raise ReportControlError("shadow_descriptor_invalid")
    for name, path_text in expected_paths.items():
        path = Path(path_text)
        if name in {"public_staging", "private_staging"} and not path.exists():
            continue
        if name == "public":
            metadata = path.lstat()
            if (
                stat.S_ISLNK(metadata.st_mode)
                or not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or stat.S_IMODE(metadata.st_mode) != 0o755
            ):
                raise ReportControlError("shadow_public_directory_invalid")
        else:
            _ensure_directory(path)
    return descriptor


def _install_shadow_permit(args: argparse.Namespace) -> Path:
    root = Path(args.shadow_root)
    descriptor = _load_shadow_descriptor(root)
    release_sha = _require_sha(args.expected_release_sha256, "release_sha256")
    if descriptor.get("release_sha256") != release_sha:
        raise ReportControlError("shadow_release_mismatch")
    authorization_id = _require_id(args.authorization_id, "authorization_id")
    run_id = _require_id(args.run_id, "run_id")
    database_sha = _require_sha(
        args.copied_database_sha256, "copied_database_sha256"
    )
    if isinstance(args.max_attempts, bool) or not 1 <= args.max_attempts <= 100:
        raise ReportControlError("permit_attempt_cap_invalid")
    paths = descriptor.get("paths")
    if not isinstance(paths, Mapping):
        raise ReportControlError("shadow_descriptor_invalid")
    document = {
        "schema_version": "report-shadow-permit-v1",
        "authorization_id": authorization_id,
        "candidate_sha256": descriptor.get("candidate_sha256"),
        "release_sha256": release_sha,
        "run_id": run_id,
        "expires_at": _require_expiry(args.expires_at),
        "copied_database_sha256": database_sha,
        "shadow_root": str(root.resolve(strict=True)),
        "paths": dict(paths),
        "max_attempts": args.max_attempts,
        "report_count": 1,
        "live_send": False,
        "failure_alert": False,
    }
    canonical_root = root.resolve(strict=True)
    with _path_lock(canonical_root / "lock"):
        return _install_permit(root=canonical_root / "control", document=document)


def _permit_document(args: argparse.Namespace, kind: str) -> Mapping[str, object]:
    authorization_id = _require_id(args.authorization_id, "authorization_id")
    release_sha = _require_sha(args.expected_release_sha256, "release_sha256")
    base: dict[str, object] = {
        "schema_version": f"report-{kind}-permit-v1",
        "authorization_id": authorization_id,
        "release_sha256": release_sha,
        "expires_at": _require_expiry(args.expires_at),
    }
    if kind in {"prepare", "send", "schedule"}:
        base["run_id"] = _require_id(args.run_id, "run_id")
    if kind in {"prepare", "schedule"}:
        if isinstance(args.max_attempts, bool) or not 1 <= args.max_attempts <= 100:
            raise ReportControlError("permit_attempt_cap_invalid")
        base.update({"max_attempts": args.max_attempts, "live_send": False})
        if kind == "schedule":
            base.update(
                {
                    "action": "prepare_only",
                    "report_count": 1,
                    "failure_alert": False,
                }
            )
    elif kind == "send":
        if not isinstance(args.expected_artifact_version_id, str) or _VERSION_ID.fullmatch(
            args.expected_artifact_version_id
        ) is None:
            raise ReportControlError("permit_version_invalid")
        action = args.action
        if action not in {"initial", "resend"}:
            raise ReportControlError("permit_action_invalid")
        parts = tuple(args.resend_part_index or ())
        if any(value < 1 for value in parts) or len(parts) != len(set(parts)):
            raise ReportControlError("permit_resend_parts_invalid")
        if (action == "initial" and parts) or (action == "resend" and not parts):
            raise ReportControlError("permit_resend_parts_invalid")
        base.update(
            {
                "action": action,
                "artifact_version_id": args.expected_artifact_version_id,
                "bundle_sha256": _require_sha(args.expected_bundle_sha256, "bundle_sha256"),
                "outbox_sha256": _require_sha(args.expected_outbox_sha256, "outbox_sha256"),
                "resend_part_indexes": list(parts),
            }
        )
    elif kind == "scheduled-cycle-policy":
        if args.max_slots not in {_G6R1_MAX_SLOTS, _G6R5_MAX_SLOTS}:
            raise ReportControlError("scheduled_policy_slot_cap_invalid")
        common = {
            "authorization_id": authorization_id,
            "release_sha256": release_sha,
            "stable_entrypoint_sha256": str(
                args.expected_stable_entrypoint_sha256 or ""
            ),
            "release_launcher_sha256": str(
                args.expected_release_launcher_sha256
                or args.expected_launcher_sha256
                or ""
            ),
            "policy_sha256": str(args.expected_policy_sha256 or ""),
            "parent_policy_sha256": str(
                args.expected_parent_policy_sha256 or ""
            ),
        }
        if args.max_slots == _G6R5_MAX_SLOTS:
            if not (args.destination_set_id and args.credential_set_epoch_id):
                raise ReportControlError("scheduled_policy_authorization_invalid")
            document = build_g6r5_owner_policy_permit_v3(
                **common,
                credential_set_receipt_sha256=str(
                    args.expected_credential_set_receipt_sha256 or ""
                ),
                credential_set_epoch_id=str(
                    args.credential_set_epoch_id or ""
                ),
                destination_set_id=str(args.destination_set_id or ""),
            )
        elif args.destination_set_id or args.credential_set_epoch_id:
            document = build_g6r1_owner_policy_permit_v2(
                **common,
                credential_set_receipt_sha256=str(
                    args.expected_credential_set_receipt_sha256 or ""
                ),
                credential_set_epoch_id=str(
                    args.credential_set_epoch_id or ""
                ),
                destination_set_id=str(args.destination_set_id or ""),
            )
        else:
            document = build_g6r1_owner_policy_permit(
                **common,
                credential_rotation_receipt_sha256=str(
                    args.expected_credential_rotation_receipt_sha256 or ""
                ),
                credential_epoch_id=str(args.credential_epoch_id or ""),
                destination_alias=str(args.destination_alias or ""),
            )
        if document["expires_at"] != _require_expiry(args.expires_at):
            raise ReportControlError("scheduled_policy_expiry_invalid")
        return document
    elif kind == "admin":
        if args.action not in {"bootstrap", "activate", "rollback"}:
            raise ReportControlError("permit_action_invalid")
        base["action"] = args.action
        if args.action in {"bootstrap", "activate"}:
            base["expected_launcher_sha256"] = _require_sha(
                args.expected_launcher_sha256, "launcher_sha256"
            )
        else:
            base["expected_launcher_sha256"] = None
    return base


def _control_root(args: argparse.Namespace) -> Path:
    default = Path("/home/ubuntu/.reddit-voc/report-control")
    value = Path(args.control_root) if args.control_root else default
    if os.getenv("REDDIT_VOC_LOCAL_TEST_MODE") == "1" and value == default:
        raise ReportControlError("local_test_production_scope_forbidden")
    if value != default and os.getenv("REDDIT_VOC_LOCAL_TEST_MODE") != "1":
        raise ReportControlError("control_root_override_forbidden")
    return value


@contextmanager
def _permit_lifecycle_lock(args: argparse.Namespace) -> Iterator[Path]:
    if args.shadow_root is not None:
        shadow = Path(args.shadow_root).resolve(strict=True)
        _load_shadow_descriptor(shadow)
        with _applicable_lock(args, shadow / "lock"):
            yield shadow / "control"
        return
    root = _control_root(args)
    if args.control_root is not None:
        with _control_lock(root):
            yield root
        return
    with _applicable_lock(
        args,
        _DAILY_REPORT_LOCK_PATH,
    ):
        yield root


def _parse_env_document(
    payload: bytes,
) -> tuple[Mapping[str, str], tuple[bytes, ...]]:
    if b"\x00" in payload or b"\r" in payload:
        raise ReportControlError("runtime_env_invalid")
    try:
        payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReportControlError("runtime_env_invalid") from exc
    seen: set[str] = set()
    values: dict[str, str] = {}
    lines = tuple(payload.splitlines(keepends=True))
    if payload and not lines:
        raise ReportControlError("runtime_env_invalid")
    for raw_line in lines:
        content = raw_line[:-1] if raw_line.endswith(b"\n") else raw_line
        if not content or content.startswith(b"#"):
            continue
        if b"=" not in content:
            raise ReportControlError("runtime_env_invalid")
        key_bytes, value_bytes = content.split(b"=", 1)
        try:
            key = key_bytes.decode("ascii")
            value = value_bytes.decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError) as exc:
            raise ReportControlError("runtime_env_invalid") from exc
        if (
            re.fullmatch(r"[A-Z][A-Z0-9_]*", key) is None
            or key not in _ENV_ALLOWED
            or key in seen
        ):
            raise ReportControlError("runtime_env_invalid")
        seen.add(key)
        values[key] = value
    if any(key not in values for key in _GATE_KEYS):
        raise ReportControlError("runtime_env_gate_missing")
    _validate_gate_values({key: values[key] for key in _GATE_KEYS})
    return values, lines


def _parse_env(payload: bytes) -> tuple[Mapping[str, str], tuple[bytes, ...]]:
    values, lines = _parse_env_document(payload)
    return {key: values[key] for key in _GATE_KEYS}, lines


def _validate_gate_values(values: Mapping[str, str]) -> None:
    if set(values) != set(_GATE_KEYS):
        raise ReportControlError("runtime_gate_values_invalid")
    if values["REDDIT_VOC_TRANSLATION_MODE"] not in {"dry_run", "deepseek"}:
        raise ReportControlError("runtime_gate_values_invalid")
    if values["REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION"] not in {"0", "1"}:
        raise ReportControlError("runtime_gate_values_invalid")
    if values["REDDIT_VOC_DINGTALK_MODE"] not in {"dry_run", "live"}:
        raise ReportControlError("runtime_gate_values_invalid")
    if values["REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND"] not in {"0", "1"}:
        raise ReportControlError("runtime_gate_values_invalid")
    if values["REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT"] not in {"0", "1"}:
        raise ReportControlError("runtime_gate_values_invalid")
    if (
        values["REDDIT_VOC_TRANSLATION_MODE"] == "deepseek"
    ) != (values["REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION"] == "1"):
        raise ReportControlError("runtime_gate_values_invalid")
    if (values["REDDIT_VOC_DINGTALK_MODE"] == "live") != (
        values["REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND"] == "1"
    ):
        raise ReportControlError("runtime_gate_values_invalid")


def _replace_gate_values(payload: bytes, target: Mapping[str, str]) -> bytes:
    _validate_gate_values(target)
    _current, lines = _parse_env(payload)
    result: list[bytes] = []
    for raw_line in lines:
        content = raw_line[:-1] if raw_line.endswith(b"\n") else raw_line
        newline = b"\n" if raw_line.endswith(b"\n") else b""
        if not content or content.startswith(b"#") or b"=" not in content:
            result.append(raw_line)
            continue
        key_bytes, _value = content.split(b"=", 1)
        key = key_bytes.decode("ascii")
        if key in target:
            result.append(key_bytes + b"=" + target[key].encode("ascii") + newline)
        else:
            result.append(raw_line)
    return b"".join(result)


def _replace_env_values(payload: bytes, target: Mapping[str, str]) -> bytes:
    values, lines = _parse_env_document(payload)
    if any(key not in values for key in target):
        raise ReportControlError("runtime_env_required_name_missing")
    result: list[bytes] = []
    for raw_line in lines:
        content = raw_line[:-1] if raw_line.endswith(b"\n") else raw_line
        newline = b"\n" if raw_line.endswith(b"\n") else b""
        if not content or content.startswith(b"#"):
            result.append(raw_line)
            continue
        key_bytes, _value = content.split(b"=", 1)
        key = key_bytes.decode("ascii")
        if key in target:
            result.append(
                key_bytes + b"=" + target[key].encode("utf-8") + newline
            )
        else:
            result.append(raw_line)
    return b"".join(result)


def _drop_env_keys(payload: bytes, keys: frozenset[str]) -> bytes:
    _values, lines = _parse_env_document(payload)
    result: list[bytes] = []
    for raw_line in lines:
        content = raw_line[:-1] if raw_line.endswith(b"\n") else raw_line
        if not content or content.startswith(b"#"):
            result.append(raw_line)
            continue
        key = content.split(b"=", 1)[0].decode("ascii")
        if key not in keys:
            result.append(raw_line)
    return b"".join(result)


def _gate_digest(values: Mapping[str, str]) -> str:
    return _sha256(_canonical(dict(values)))


@contextmanager
def _path_lock(path: Path) -> Iterator[int]:
    if (
        os.getenv("REDDIT_VOC_LOCAL_TEST_MODE") != "1"
        and path == _DAILY_REPORT_LOCK_PATH
    ):
        _validate_production_lock_path(path)
        flags = os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        try:
            _validate_production_lock_path(path, descriptor=descriptor)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ReportControlError("lock_busy") from exc
            yield descriptor
        finally:
            os.close(descriptor)
        return
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.stat().st_uid != os.getuid():
        raise ReportControlError("lock_owner_invalid")
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        os.chmod(path, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ReportControlError("lock_busy") from exc
        yield descriptor
    finally:
        os.close(descriptor)


def _validate_production_lock_path(
    path: Path, *, descriptor: int | None = None
) -> None:
    if path != _DAILY_REPORT_LOCK_PATH:
        raise ReportControlError("lock_path_invalid")
    absolute = path.absolute()
    for directory in reversed(absolute.parents):
        try:
            metadata = directory.lstat()
        except FileNotFoundError as exc:
            raise ReportControlError("lock_path_invalid") from exc
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != 0
            or stat.S_IMODE(metadata.st_mode) & 0o022
            or not os.access(directory, os.X_OK)
        ):
            raise ReportControlError("lock_path_invalid")
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ReportControlError("lock_path_invalid") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_gid != 1000
        or stat.S_IMODE(metadata.st_mode) != 0o660
    ):
        raise ReportControlError("lock_path_invalid")
    if descriptor is not None:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != 0
            or opened.st_gid != 1000
            or stat.S_IMODE(opened.st_mode) != 0o660
            or opened.st_dev != metadata.st_dev
            or opened.st_ino != metadata.st_ino
        ):
            raise ReportControlError("lock_path_invalid")


def _validate_inherited_lock(descriptor: int, path: Path) -> None:
    if isinstance(descriptor, bool) or descriptor < 3:
        raise ReportControlError("inherited_lock_fd_invalid")
    try:
        fd_metadata = os.fstat(descriptor)
        path_metadata = path.lstat()
    except (OSError, FileNotFoundError) as exc:
        raise ReportControlError("inherited_lock_fd_invalid") from exc
    production_lock = (
        os.getenv("REDDIT_VOC_LOCAL_TEST_MODE") != "1"
        and path == _DAILY_REPORT_LOCK_PATH
    )
    if production_lock:
        _validate_production_lock_path(path, descriptor=descriptor)
    elif (
        stat.S_ISLNK(path_metadata.st_mode)
        or not stat.S_ISREG(path_metadata.st_mode)
        or path_metadata.st_uid != os.getuid()
        or stat.S_IMODE(path_metadata.st_mode) != 0o600
        or fd_metadata.st_dev != path_metadata.st_dev
        or fd_metadata.st_ino != path_metadata.st_ino
    ):
        raise ReportControlError("inherited_lock_fd_invalid")
    flags = os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    probe = os.open(path, flags)
    try:
        try:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            fcntl.flock(probe, fcntl.LOCK_UN)
            raise ReportControlError("inherited_lock_not_held")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ReportControlError("inherited_lock_fd_invalid") from exc
    finally:
        os.close(probe)


@contextmanager
def _applicable_lock(args: argparse.Namespace, path: Path) -> Iterator[int]:
    if args.inherited_lock_fd is None:
        with _path_lock(path) as descriptor:
            yield descriptor
        return
    _validate_inherited_lock(args.inherited_lock_fd, path)
    yield args.inherited_lock_fd


def _gate_paths(args: argparse.Namespace) -> Mapping[str, Path | Mapping[str, object]]:
    if args.shadow_root is not None:
        root = Path(args.shadow_root).resolve(strict=True)
        descriptor = _load_shadow_descriptor(root)
        return {
            "descriptor": descriptor,
            "env": root / "secrets" / "reddit-voc-report.env",
            "key": root / "secrets" / "deepseek-api-key",
            "snapshots": root / "secrets" / "snapshots",
            "gates": root / "control" / "gates",
            "control": root / "control",
            "lock": root / "lock",
        }
    if os.getenv("REDDIT_VOC_LOCAL_TEST_MODE") == "1":
        raise ReportControlError("local_test_production_scope_forbidden")
    return {
        "descriptor": {},
        "env": Path("/home/ubuntu/.reddit-voc/secrets/reddit-voc-report.env"),
        "key": Path("/home/ubuntu/.reddit-voc/secrets/deepseek-api-key"),
        "snapshots": Path("/home/ubuntu/.reddit-voc/secrets/report-env-snapshots"),
        "gates": Path("/home/ubuntu/.reddit-voc/report-control/gates"),
        "control": Path("/home/ubuntu/.reddit-voc/report-control"),
        "lock": _DAILY_REPORT_LOCK_PATH,
    }


def _read_secret_stdin(*, key: bool) -> bytes:
    if sys.stdin.isatty():
        payload = getpass.getpass("secret: ").encode("utf-8")
    else:
        payload = sys.stdin.buffer.read(4 * 1024 * 1024 + 1)
    if len(payload) > 4 * 1024 * 1024:
        raise ReportControlError("secret_input_invalid")
    if key and payload.endswith(b"\n"):
        payload = payload[:-1]
    if key and payload.endswith(b"\r"):
        payload = payload[:-1]
    if key:
        if (
            not payload
            or len(payload) > 4096
            or b"\x00" in payload
            or b"\n" in payload
            or b"\r" in payload
        ):
            raise ReportControlError("secret_input_invalid")
        try:
            decoded = payload.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ReportControlError("secret_input_invalid") from exc
        if any(character.isspace() or not character.isprintable() for character in decoded):
            raise ReportControlError("secret_input_invalid")
    return payload


def _install_secret_file(path: Path, payload: bytes) -> None:
    _ensure_directory(path.parent)
    if path.exists() or path.is_symlink():
        _read_regular(path, reason="runtime_secret_file_invalid")
        _atomic_replace(path, payload)
    else:
        _write_new(path, payload)


def _require_secret_provisioning(args: argparse.Namespace) -> None:
    if not args.authorize_secret_provisioning:
        raise ReportControlError("secret_provisioning_not_authorized")


def _check_key_metadata(path: Path) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ReportControlError("runtime_key_file_invalid") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_size < 1
        or metadata.st_size > 4096
    ):
        raise ReportControlError("runtime_key_file_invalid")


def _install_runtime_env(paths: Mapping[str, object]) -> Mapping[str, object]:
    payload = _read_secret_stdin(key=False)
    _current, _lines = _parse_env(payload)
    disabled = _replace_gate_values(payload, _ALL_OFF_GATES)
    _install_secret_file(Path(paths["env"]), disabled)
    return {"status": "installed", "secret_kind": "env", "gates": "all_off"}


def _install_runtime_key(paths: Mapping[str, object]) -> Mapping[str, object]:
    payload = _read_secret_stdin(key=True)
    _install_secret_file(Path(paths["key"]), payload)
    return {"status": "installed", "secret_kind": "key"}


def _materialize_prepare_env(
    args: argparse.Namespace, paths: Mapping[str, object]
) -> Mapping[str, object]:
    authorization_id = _require_id(args.authorization_id, "authorization_id")
    release_sha = _require_sha(args.expected_release_sha256, "release_sha256")
    run_id = _require_id(args.run_id, "run_id")
    attempt_id = _require_id(args.attempt_id, "attempt_id")
    artifact_version_id = args.artifact_version_id
    if (
        not isinstance(artifact_version_id, str)
        or _VERSION_ID.fullmatch(artifact_version_id) is None
    ):
        raise ReportControlError("artifact_version_id_invalid")
    _require_reserved_prepare_permit(
        control_root=Path(paths["control"]),
        authorization_id=authorization_id,
        release_sha256=release_sha,
        run_id=run_id,
    )
    provider_authorization_id = args.provider_authorization_id
    if provider_authorization_id is not None:
        provider_authorization_id = _require_id(
            provider_authorization_id, "provider_authorization_id"
        )
        _require_reserved_provider_permit(
            control_root=Path(paths["control"]),
            authorization_id=provider_authorization_id,
            release_sha256=release_sha,
            run_id=run_id,
        )
        descriptor = paths.get("descriptor")
        if isinstance(descriptor, Mapping) and descriptor:
            path_map = descriptor.get("paths")
            if not isinstance(path_map, Mapping):
                raise ReportControlError("shadow_descriptor_invalid")
            provider_attempt_root = Path(str(path_map["provider_attempts"]))
        else:
            provider_attempt_root = Path(
                "/home/ubuntu/.reddit-voc/report-control/provider-attempts"
            )
        binding = _strict_json_bytes(
            _read_regular(
                provider_attempt_root
                / provider_authorization_id
                / "binding.json",
                reason="provider_attempt_binding_invalid",
            ),
            "provider_attempt_binding_invalid",
        )
        if binding != {
            "schema_version": "provider-attempt-binding-v1",
            "provider_authorization_id": provider_authorization_id,
            "prepare_action_authorization_id": authorization_id,
            "release_sha256": release_sha,
            "run_id": run_id,
            "attempt_id": attempt_id,
        }:
            raise ReportControlError("provider_attempt_binding_invalid")
    payload = _read_regular(
        Path(paths["env"]), reason="runtime_secret_file_invalid"
    )
    values, _lines = _parse_env_document(payload)
    required_base = {
        "REDDIT_VOC_DATABASE_PATH",
        "REDDIT_VOC_ARTIFACT_BASE_URL",
        "DINGTALK_REQUIRED_KEYWORD",
        "REDDIT_VOC_DINGTALK_MAX_BYTES",
        "REDDIT_VOC_DINGTALK_MAX_PARTS",
    }
    if any(not values.get(key) for key in required_base):
        raise ReportControlError("runtime_env_required_value_missing")
    if (
        not values["REDDIT_VOC_ARTIFACT_BASE_URL"].startswith("https://")
        or not values["REDDIT_VOC_DINGTALK_MAX_BYTES"].isdigit()
        or not values["REDDIT_VOC_DINGTALK_MAX_PARTS"].isdigit()
        or {key: values[key] for key in _GATE_KEYS} != _ALL_OFF_GATES
        or _active_gate_journals(Path(paths["gates"]))
    ):
        raise ReportControlError("runtime_prepare_env_invalid")
    descriptor = paths.get("descriptor")
    if isinstance(descriptor, Mapping) and descriptor:
        path_map = descriptor.get("paths")
        if not isinstance(path_map, Mapping):
            raise ReportControlError("shadow_descriptor_invalid")
        host_paths = {str(key): str(value) for key, value in path_map.items()}
        database_path = str(Path(host_paths["database"]) / "reddit_voc.sqlite3")
    else:
        host_paths = {
            "public": "/opt/reddit-voc-site/outputs",
            "private": "/opt/reddit-voc-site/private",
            "public_staging": str(
                Path("/opt/reddit-voc-site/outputs/.report-staging") / attempt_id
            ),
            "private_staging": str(
                Path("/opt/reddit-voc-site/private/.report-staging") / attempt_id
            ),
            "state": "/opt/reddit-voc-daily-report/state",
            "blocked": "/opt/reddit-voc-daily-report/blocked",
            "handoff": "/opt/reddit-voc-daily-report/handoff",
            "provider_attempts": (
                "/home/ubuntu/.reddit-voc/report-control/provider-attempts"
            ),
        }
        database_path = "/opt/reddit-voc-site/data/reddit_voc_daily.sqlite3"
    if values["REDDIT_VOC_DATABASE_PATH"] != database_path:
        raise ReportControlError("runtime_database_path_mismatch")
    missing_runtime_identity_names = tuple(
        key
        for key in (
            "REDDIT_VOC_RUN_ID",
            "REDDIT_VOC_ATTEMPT_ID",
            "REDDIT_VOC_ARTIFACT_VERSION_ID",
        )
        if key not in values
    )
    if missing_runtime_identity_names:
        if payload and not payload.endswith(b"\n"):
            payload += b"\n"
        payload += b"".join(
            key.encode("ascii") + b"=\n"
            for key in missing_runtime_identity_names
        )
        values, _lines = _parse_env_document(payload)
    allowed_artifact_base_urls = {
        "https://reddit.brand.lute-tlz-dddd.top/artifacts",
        "https://reddit.lute-tlz-dddd.top/artifacts",
    }
    if values["REDDIT_VOC_ARTIFACT_BASE_URL"] not in allowed_artifact_base_urls:
        raise ReportControlError("runtime_artifact_base_url_mismatch")
    replacements = {
        "REDDIT_VOC_DATABASE_PATH": database_path,
        "REDDIT_VOC_ARTIFACT_BASE_URL": "https://reddit.lute-tlz-dddd.top/artifacts",
        "REDDIT_VOC_RUN_ID": run_id,
        "REDDIT_VOC_ATTEMPT_ID": attempt_id,
        "REDDIT_VOC_ARTIFACT_VERSION_ID": artifact_version_id,
        "REDDIT_VOC_REPORT_PUBLIC_ROOT": host_paths["public"],
        "REDDIT_VOC_REPORT_PRIVATE_ROOT": host_paths["private"],
        "REDDIT_VOC_REPORT_PUBLIC_STAGING_ROOT": host_paths["public_staging"],
        "REDDIT_VOC_REPORT_PRIVATE_STAGING_ROOT": host_paths["private_staging"],
        "REDDIT_VOC_REPORT_STATE_ROOT": host_paths["state"],
        "REDDIT_VOC_REPORT_BLOCKED_ROOT": host_paths["blocked"],
        "REDDIT_VOC_REPORT_HANDOFF_ROOT": host_paths["handoff"],
        "REDDIT_VOC_PROVIDER_ATTEMPT_ROOT": host_paths["provider_attempts"],
        "REDDIT_VOC_CONFIG_ROOT": "/app/config",
        "REDDIT_VOC_TRANSLATION_MODE": (
            "deepseek" if provider_authorization_id is not None else "dry_run"
        ),
        "REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION": (
            "1" if provider_authorization_id is not None else "0"
        ),
        "REDDIT_VOC_DINGTALK_MODE": "dry_run",
        "REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND": "0",
        "REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT": "0",
        "DINGTALK_WEBHOOK_URL": "",
        "DINGTALK_WEBHOOK_SECRET": "",
        "DINGTALK_WEBHOOK_URL_2": "",
        "DINGTALK_WEBHOOK_SECRET_2": "",
    }
    for optional_key in ("DINGTALK_WEBHOOK_URL_2", "DINGTALK_WEBHOOK_SECRET_2"):
        if optional_key not in values:
            replacements.pop(optional_key)
    attempt_payload = _replace_env_values(payload, replacements)
    attempt_payload = _drop_env_keys(
        attempt_payload,
        frozenset({"DINGTALK_WEBHOOK_URL_2", "DINGTALK_WEBHOOK_SECRET_2"}),
    )
    parsed_attempt, _attempt_lines = _parse_env_document(attempt_payload)
    if (
        parsed_attempt["DINGTALK_WEBHOOK_URL"]
        or parsed_attempt["DINGTALK_WEBHOOK_SECRET"]
        or parsed_attempt.get("DINGTALK_WEBHOOK_URL_2")
        or parsed_attempt.get("DINGTALK_WEBHOOK_SECRET_2")
    ):
        raise ReportControlError("runtime_prepare_env_invalid")
    runtime_root = Path(paths["control"]) / "runtime-env"
    _ensure_directory(runtime_root, create=True)
    target = runtime_root / f"{attempt_id}.env"
    if target.exists() or target.is_symlink():
        raise ReportControlError("runtime_attempt_env_exists")
    _write_new(target, attempt_payload)
    return {
        "status": "materialized",
        "attempt_id": attempt_id,
        "runtime_env": str(target),
        "dingtalk": "disabled",
        "translation": (
            "deepseek" if provider_authorization_id is not None else "dry_run"
        ),
    }


def _materialize_send_env(
    args: argparse.Namespace, paths: Mapping[str, object]
) -> Mapping[str, object]:
    authorization_id = _require_id(args.authorization_id, "authorization_id")
    release_sha = _require_sha(args.expected_release_sha256, "release_sha256")
    run_id = _require_id(args.run_id, "run_id")
    attempt_id = _require_id(args.attempt_id, "attempt_id")
    artifact_version_id = args.artifact_version_id
    if not isinstance(artifact_version_id, str) or _VERSION_ID.fullmatch(
        artifact_version_id
    ) is None:
        raise ReportControlError("artifact_version_id_invalid")
    bundle_sha = _require_sha(args.expected_bundle_sha256, "bundle_sha256")
    outbox_sha = _require_sha(args.expected_outbox_sha256, "outbox_sha256")
    permit = _require_send_permit(
        control_root=Path(paths["control"]),
        authorization_id=authorization_id,
        release_sha256=release_sha,
        run_id=run_id,
        artifact_version_id=artifact_version_id,
        bundle_sha256=bundle_sha,
        outbox_sha256=outbox_sha,
        action=args.action,
        resend_part_indexes=args.resend_part_index,
        expected_status="reserved",
        scheduled_cycle_id=args.scheduled_cycle_id,
        cycle_lease_token=_read_cycle_lease(
            args, required=args.scheduled_cycle_id is not None
        ),
        scheduled_at=getattr(args, "scheduled_at", None),
    )
    payload = _read_regular(
        Path(paths["env"]), reason="runtime_secret_file_invalid"
    )
    values, _lines = _parse_env_document(payload)
    if {key: values[key] for key in _GATE_KEYS} != _ALL_OFF_GATES:
        raise ReportControlError("runtime_send_env_invalid")
    if not values.get("DINGTALK_WEBHOOK_URL"):
        raise ReportControlError("runtime_send_env_invalid")
    dual = (
        permit.get("schema_version")
        == "report-scheduled-cycle-send-permit-v2"
    )
    if dual:
        expected_destinations = canonical_g6r1_dual_destinations()
        if (
            not values.get("DINGTALK_WEBHOOK_URL_2")
            or values.get("DINGTALK_WEBHOOK_URL")
            == values.get("DINGTALK_WEBHOOK_URL_2")
            or values.get("REDDIT_VOC_DINGTALK_CREDENTIAL_SET_EPOCH_ID")
            != permit.get("credential_set_epoch_id")
            or values.get("REDDIT_VOC_DINGTALK_DESTINATION_SET_ID")
            != permit.get("destination_set_id")
            or values.get("REDDIT_VOC_DINGTALK_PRIMARY_DESTINATION_ALIAS")
            != expected_destinations[0]["destination_alias"]
            or values.get("REDDIT_VOC_DINGTALK_SECONDARY_DESTINATION_ALIAS")
            != expected_destinations[1]["destination_alias"]
            or values.get("DINGTALK_REQUIRED_KEYWORD")
            != permit.get("required_keyword")
        ):
            raise ReportControlError("scheduled_destination_binding_invalid")
    elif values.get("DINGTALK_WEBHOOK_URL_2") or values.get(
        "DINGTALK_WEBHOOK_SECRET_2"
    ):
        raise ReportControlError("runtime_send_env_invalid")
    descriptor = paths.get("descriptor")
    if isinstance(descriptor, Mapping) and descriptor:
        path_map = descriptor.get("paths")
        if not isinstance(path_map, Mapping):
            raise ReportControlError("shadow_descriptor_invalid")
        host_paths = {str(key): str(value) for key, value in path_map.items()}
        database_path = str(Path(host_paths["database"]) / "reddit_voc.sqlite3")
    else:
        host_paths = {
            "public": "/opt/reddit-voc-site/outputs",
            "private": "/opt/reddit-voc-site/private",
            "state": "/opt/reddit-voc-daily-report/state",
        }
        database_path = "/opt/reddit-voc-site/data/reddit_voc_daily.sqlite3"
    if values.get("REDDIT_VOC_DATABASE_PATH") != database_path:
        raise ReportControlError("runtime_database_path_mismatch")
    if permit.get("schema_version") in {
        "report-scheduled-cycle-send-permit-v1",
        "report-scheduled-cycle-send-permit-v2",
    }:
        if not dual and (
            values.get("REDDIT_VOC_DINGTALK_CREDENTIAL_EPOCH_ID")
            != permit.get("credential_epoch_id")
            or values.get("REDDIT_VOC_DINGTALK_DESTINATION_ALIAS")
            != permit.get("destination_alias")
            or values.get("DINGTALK_REQUIRED_KEYWORD")
            != permit.get("required_keyword")
        ):
            raise ReportControlError("scheduled_destination_binding_invalid")
        state_root = Path(host_paths["state"])
        run_delivery_root = state_root / "delivery" / run_id
        if dual and run_delivery_root.exists():
            _ensure_directory(run_delivery_root)
            if any(run_delivery_root.iterdir()):
                raise ReportControlError("scheduled_delivery_history_exists")
        for candidate in (
            state_root / "delivery" / run_id / "ledger.jsonl",
            state_root / "delivery-ledger" / run_id,
        ):
            if not candidate.exists() and not candidate.is_symlink():
                continue
            if candidate.is_dir() and not candidate.is_symlink():
                _ensure_directory(candidate)
                if not any(candidate.iterdir()):
                    continue
            raise ReportControlError("scheduled_delivery_history_exists")
    replacements = {
        "REDDIT_VOC_DATABASE_PATH": database_path,
        "REDDIT_VOC_RUN_ID": run_id,
        "REDDIT_VOC_ATTEMPT_ID": attempt_id,
        "REDDIT_VOC_ARTIFACT_VERSION_ID": artifact_version_id,
        "REDDIT_VOC_REPORT_PUBLIC_ROOT": host_paths["public"],
        "REDDIT_VOC_REPORT_PRIVATE_ROOT": host_paths["private"],
        "REDDIT_VOC_REPORT_PUBLIC_STAGING_ROOT": "",
        "REDDIT_VOC_REPORT_PRIVATE_STAGING_ROOT": "",
        "REDDIT_VOC_REPORT_STATE_ROOT": host_paths["state"],
        "REDDIT_VOC_REPORT_BLOCKED_ROOT": "",
        "REDDIT_VOC_REPORT_HANDOFF_ROOT": "",
        "REDDIT_VOC_PROVIDER_ATTEMPT_ROOT": "",
        "REDDIT_VOC_CONFIG_ROOT": "/app/config",
        "REDDIT_VOC_TRANSLATION_MODE": "dry_run",
        "REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION": "0",
        "REDDIT_VOC_DINGTALK_MODE": "live",
        "REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND": "1",
        "REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT": "0",
    }
    attempt_payload = _replace_env_values(payload, replacements)
    if not dual:
        attempt_payload = _drop_env_keys(
            attempt_payload,
            frozenset(
                {"DINGTALK_WEBHOOK_URL_2", "DINGTALK_WEBHOOK_SECRET_2"}
            ),
        )
    parsed_attempt, _attempt_lines = _parse_env_document(attempt_payload)
    if (
        parsed_attempt["REDDIT_VOC_TRANSLATION_MODE"] != "dry_run"
        or parsed_attempt["REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION"] != "0"
        or parsed_attempt["REDDIT_VOC_DINGTALK_MODE"] != "live"
        or parsed_attempt["REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND"] != "1"
        or parsed_attempt["REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT"] != "0"
        or any(
            parsed_attempt.get(key)
            for key in (
                "REDDIT_VOC_REPORT_PUBLIC_STAGING_ROOT",
                "REDDIT_VOC_REPORT_PRIVATE_STAGING_ROOT",
                "REDDIT_VOC_REPORT_BLOCKED_ROOT",
                "REDDIT_VOC_REPORT_HANDOFF_ROOT",
                "REDDIT_VOC_PROVIDER_ATTEMPT_ROOT",
            )
        )
    ):
        raise ReportControlError("runtime_send_env_invalid")
    runtime_root = Path(paths["control"]) / "runtime-env"
    _ensure_directory(runtime_root, create=True)
    target = runtime_root / f"{attempt_id}.env"
    if target.exists() or target.is_symlink():
        raise ReportControlError("runtime_attempt_env_exists")
    _write_new(target, attempt_payload)
    return {
        "status": "materialized",
        "attempt_id": attempt_id,
        "runtime_env": str(target),
        "dingtalk": "enabled",
        "destination_mode": "dual" if dual else "single",
    }


def _remove_runtime_env(
    args: argparse.Namespace, paths: Mapping[str, object]
) -> Mapping[str, object]:
    attempt_id = _require_id(args.attempt_id, "attempt_id")
    runtime_root = Path(paths["control"]) / "runtime-env"
    _ensure_directory(runtime_root)
    target = runtime_root / f"{attempt_id}.env"
    _read_regular(target, reason="runtime_attempt_env_invalid")
    target.unlink()
    _fsync_directory(runtime_root)
    return {"status": "removed", "attempt_id": attempt_id}


def _target_gates(args: argparse.Namespace) -> Mapping[str, str]:
    target = {
        "REDDIT_VOC_TRANSLATION_MODE": str(args.translation_mode),
        "REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION": str(args.enable_deepseek),
        "REDDIT_VOC_DINGTALK_MODE": str(args.dingtalk_mode),
        "REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND": str(
            args.enable_dingtalk_live_send
        ),
        "REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT": str(args.enable_failure_alert),
    }
    _validate_gate_values(target)
    return target


def _journal_document(path: Path) -> Mapping[str, object]:
    return _strict_json_bytes(
        _read_regular(path, reason="gate_journal_invalid"),
        "gate_journal_invalid",
    )


def _active_gate_journals(gates_root: Path) -> tuple[Path, ...]:
    _ensure_directory(gates_root, create=True)
    active: list[Path] = []
    for path in sorted(gates_root.iterdir()):
        if path.name.startswith("."):
            continue
        if path.suffix == ".incident" or ".quarantine-" in path.name:
            continue
        if path.suffix != ".json":
            raise ReportControlError("gate_journal_invalid")
        journal = _journal_document(path)
        if journal.get("phase") in {"snapshot_created", "applied"}:
            active.append(path)
    return tuple(active)


def _require_reserved_gate_permit(
    *, control_root: Path, authorization_id: str, release_sha256: str
) -> None:
    permit, state, _state_path = _load_permit_state(
        root=control_root, authorization_id=authorization_id
    )
    schema_version = permit.get("schema_version")
    max_attempts = permit.get("max_attempts")
    if (
        schema_version
        not in {
            "report-prepare-permit-v1",
            "report-schedule-permit-v1",
            "report-shadow-permit-v1",
            "report-scheduled-cycle-prepare-permit-v1",
        }
        or permit.get("release_sha256") != release_sha256
        or permit.get("live_send") is not False
        or isinstance(max_attempts, bool)
        or not isinstance(max_attempts, int)
        or not 1 <= max_attempts <= 100
        or state.get("status") != "reserved"
    ):
        raise ReportControlError("gate_permit_not_reserved")
    if schema_version in {
        "report-schedule-permit-v1",
        "report-shadow-permit-v1",
        "report-scheduled-cycle-prepare-permit-v1",
    } and (
        permit.get("report_count") != 1
        or permit.get("failure_alert") is not False
    ):
        raise ReportControlError("gate_permit_not_reserved")
    if schema_version in {
        "report-schedule-permit-v1",
        "report-scheduled-cycle-prepare-permit-v1",
    }:
        expected_action = (
            "prepare_only"
            if schema_version == "report-schedule-permit-v1"
            else "prepare_once_then_derive_exact_send"
        )
        if permit.get("action") != expected_action:
            raise ReportControlError("gate_permit_not_reserved")
        if schema_version == "report-scheduled-cycle-prepare-permit-v1" and (
            not _is_supported_scheduled_provider_policy(
                permit.get("provider_attempt_policy")
            )
            or max_attempts
            != permit.get("provider_attempt_policy", {}).get(
                "max_attempts_per_cycle"
            )
        ):
            raise ReportControlError("gate_permit_not_reserved")


def _set_gates(args: argparse.Namespace, paths: Mapping[str, object]) -> Mapping[str, object]:
    authorization_id = _require_id(args.authorization_id, "authorization_id")
    release_sha = _require_sha(args.expected_release_sha256, "release_sha256")
    journal_id = _require_id(args.journal_id, "journal_id")
    descriptor = paths["descriptor"]
    if isinstance(descriptor, Mapping) and descriptor:
        if descriptor.get("release_sha256") != release_sha:
            raise ReportControlError("gate_release_mismatch")
    target = _target_gates(args)
    if args.terminal_kill_switch:
        if target != _ALL_OFF_GATES:
            raise ReportControlError("terminal_kill_switch_target_invalid")
    else:
        _require_reserved_gate_permit(
            control_root=Path(paths["control"]),
            authorization_id=authorization_id,
            release_sha256=release_sha,
        )
    gates_root = _ensure_directory(Path(paths["gates"]), create=True)
    if _active_gate_journals(gates_root):
        raise ReportControlError("gate_journal_active")
    env_path = Path(paths["env"])
    payload = _read_regular(env_path, reason="runtime_secret_file_invalid")
    prior, _lines = _parse_env(payload)
    if not args.terminal_kill_switch and prior != _ALL_OFF_GATES:
        raise ReportControlError("gate_prior_state_not_all_off")
    journal_path = gates_root / f"{journal_id}.json"
    if journal_path.exists() or journal_path.is_symlink():
        existing = _journal_document(journal_path)
        if (
            args.terminal_kill_switch
            and existing.get("terminal_kill_switch") is True
            and existing.get("phase") == "terminal_all_off"
            and existing.get("journal_id") == journal_id
            and existing.get("authorization_id") == authorization_id
            and existing.get("release_sha256") == release_sha
            and existing.get("target_gates") == target
            and prior == _ALL_OFF_GATES
        ):
            return {
                "status": "terminal_all_off",
                "journal_id": journal_id,
                "gates": "all_off",
            }
        raise ReportControlError("gate_journal_exists")
    snapshots = _ensure_directory(Path(paths["snapshots"]), create=True)
    snapshot_id = f"snapshot-{secrets.token_hex(16)}.env"
    snapshot_path = snapshots / snapshot_id
    _write_new(snapshot_path, payload)
    journal: Mapping[str, object] = {
        "schema_version": "report-gate-journal-v1",
        "journal_id": journal_id,
        "authorization_id": authorization_id,
        "release_sha256": release_sha,
        "snapshot_id": snapshot_id,
        "prior_gates": dict(prior),
        "target_gates": dict(target),
        "prior_gate_sha256": _gate_digest(prior),
        "target_gate_sha256": _gate_digest(target),
        "terminal_kill_switch": bool(args.terminal_kill_switch),
        "phase": "snapshot_created",
        "created_at": _now_text(),
        "updated_at": _now_text(),
    }
    try:
        _write_new(journal_path, _canonical(journal) + b"\n")
        _atomic_replace(env_path, _replace_gate_values(payload, target))
        journal = {**journal, "phase": "applied", "updated_at": _now_text()}
        _atomic_replace(journal_path, _canonical(journal) + b"\n")
        if args.terminal_kill_switch:
            snapshot_path.unlink()
            _fsync_directory(snapshot_path.parent)
            journal = {
                **journal,
                "phase": "terminal_all_off",
                "updated_at": _now_text(),
            }
            _atomic_replace(journal_path, _canonical(journal) + b"\n")
    except Exception:
        # Leave the snapshot/journal as recovery evidence. The next operation
        # must call recover-gates and can only move to all-off.
        raise
    return {
        "status": str(journal["phase"]),
        "journal_id": journal_id,
        "gates": "all_off" if target == _ALL_OFF_GATES else "provider_only",
    }


def _restore_gates(args: argparse.Namespace, paths: Mapping[str, object]) -> Mapping[str, object]:
    journal_id = _require_id(args.journal_id, "journal_id")
    journal_path = Path(paths["gates"]) / f"{journal_id}.json"
    journal = _journal_document(journal_path)
    if journal.get("phase") == "restored":
        return {"status": "restored", "journal_id": journal_id, "gates": "all_off"}
    if journal.get("phase") != "applied" or journal.get("terminal_kill_switch"):
        raise ReportControlError("gate_journal_not_restorable")
    target = journal.get("target_gates")
    prior = journal.get("prior_gates")
    if not isinstance(target, Mapping) or not isinstance(prior, Mapping):
        raise ReportControlError("gate_journal_invalid")
    _validate_gate_values(target)
    _validate_gate_values(prior)
    if prior != _ALL_OFF_GATES:
        raise ReportControlError("gate_restore_prior_not_all_off")
    env_path = Path(paths["env"])
    current_payload = _read_regular(env_path, reason="runtime_secret_file_invalid")
    current, _lines = _parse_env(current_payload)
    if current != target:
        _recover_gates(paths)
        raise ReportControlError("gate_restore_conflict_recovered")
    snapshot_id = journal.get("snapshot_id")
    if not isinstance(snapshot_id, str) or _SAFE_ID.fullmatch(snapshot_id) is None:
        raise ReportControlError("gate_snapshot_invalid")
    snapshot_path = Path(paths["snapshots"]) / snapshot_id
    snapshot = _read_regular(snapshot_path, reason="gate_snapshot_invalid")
    snapshot_gates, _snapshot_lines = _parse_env(snapshot)
    if snapshot_gates != prior:
        raise ReportControlError("gate_snapshot_invalid")
    _atomic_replace(env_path, snapshot)
    snapshot_path.unlink()
    _fsync_directory(snapshot_path.parent)
    terminal = {**journal, "phase": "restored", "updated_at": _now_text()}
    _atomic_replace(journal_path, _canonical(terminal) + b"\n")
    return {"status": "restored", "journal_id": journal_id, "gates": "all_off"}


def _minimal_all_off_env() -> bytes:
    return (
        b"DINGTALK_WEBHOOK_URL=\n"
        b"DINGTALK_WEBHOOK_SECRET=\n"
        b"DINGTALK_WEBHOOK_URL_2=\n"
        b"DINGTALK_WEBHOOK_SECRET_2=\n"
        b"REDDIT_VOC_TRANSLATION_MODE=dry_run\n"
        b"REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=0\n"
        b"REDDIT_VOC_DINGTALK_MODE=dry_run\n"
        b"REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=0\n"
        b"REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT=0\n"
    )


def _quarantine_env_and_install_all_off(env_path: Path) -> str:
    quarantine = env_path.with_name(
        f"{env_path.name}.quarantine-{secrets.token_hex(16)}"
    )
    os.rename(env_path, quarantine)
    os.chmod(quarantine, 0o600)
    _fsync_directory(env_path.parent)
    _write_new(env_path, _minimal_all_off_env())
    return quarantine.name


def _remove_journal_snapshot(
    *, journal: Mapping[str, object], snapshots_root: Path
) -> None:
    snapshot_id = journal.get("snapshot_id")
    if not isinstance(snapshot_id, str) or _SAFE_ID.fullmatch(snapshot_id) is None:
        return
    snapshot_path = snapshots_root / snapshot_id
    if snapshot_path.exists() and not snapshot_path.is_symlink():
        snapshot_path.unlink()
        _fsync_directory(snapshot_path.parent)


def _terminalize_recovered_journal(
    *, path: Path, journal: Mapping[str, object], reason: str
) -> None:
    terminal = {
        **journal,
        "phase": "recovered_all_off",
        "recovery_reason": reason,
        "updated_at": _now_text(),
    }
    _atomic_replace(path, _canonical(terminal) + b"\n")


def _write_gate_incident(*, gates_root: Path, reason: str) -> None:
    incident_id = f"incident-{secrets.token_hex(16)}"
    incident = {
        "schema_version": "report-gate-incident-v1",
        "incident_id": incident_id,
        "reason": reason,
        "phase": "recovered_all_off",
        "timestamp": _now_text(),
    }
    _write_new(gates_root / f"{incident_id}.incident", _canonical(incident) + b"\n")


def _quarantine_corrupt_gate_journals(gates_root: Path) -> int:
    quarantined = 0
    for path in sorted(gates_root.glob("*.json")):
        try:
            _journal_document(path)
        except ReportControlError:
            quarantine = path.with_name(
                f"{path.name}.quarantine-{secrets.token_hex(16)}"
            )
            os.rename(path, quarantine)
            os.chmod(quarantine, 0o600)
            _fsync_directory(path.parent)
            quarantined += 1
    if quarantined:
        _write_gate_incident(gates_root=gates_root, reason="gate_journal_invalid")
    return quarantined


def _cleanup_orphan_snapshots(snapshots_root: Path) -> int:
    if not snapshots_root.exists():
        return 0
    _ensure_directory(snapshots_root)
    removed = 0
    for path in sorted(snapshots_root.iterdir()):
        metadata = path.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise ReportControlError("gate_snapshot_invalid")
        path.unlink()
        removed += 1
    if removed:
        _fsync_directory(snapshots_root)
    return removed


def _recover_gates(paths: Mapping[str, object]) -> Mapping[str, object]:
    gates_root = _ensure_directory(Path(paths["gates"]), create=True)
    corrupt_journal_count = _quarantine_corrupt_gate_journals(gates_root)
    active = _active_gate_journals(gates_root)
    env_path = Path(paths["env"])
    missing_env = False
    try:
        payload = _read_regular(env_path, reason="runtime_secret_file_invalid")
    except ReportControlError:
        if env_path.exists() or env_path.is_symlink():
            raise
        _ensure_directory(env_path.parent)
        _write_new(env_path, _minimal_all_off_env())
        payload = _read_regular(env_path, reason="runtime_secret_file_invalid")
        missing_env = True
    quarantine_name: str | None = None
    try:
        current, _lines = _parse_env(payload)
        recovered_payload = _replace_gate_values(payload, _ALL_OFF_GATES)
    except ReportControlError:
        quarantine_name = _quarantine_env_and_install_all_off(env_path)
        payload = _read_regular(env_path, reason="runtime_secret_file_invalid")
        current, _lines = _parse_env(payload)
        recovered_payload = payload
    journal_id: str | None = None
    snapshots_root = Path(paths["snapshots"])
    if len(active) > 1:
        _atomic_replace(env_path, recovered_payload)
        for journal_path in active:
            journal = _journal_document(journal_path)
            _remove_journal_snapshot(
                journal=journal, snapshots_root=snapshots_root
            )
            _terminalize_recovered_journal(
                path=journal_path,
                journal=journal,
                reason="multiple_active_gate_journals",
            )
        _write_gate_incident(
            gates_root=gates_root, reason="multiple_active_gate_journals"
        )
        journal_id = "multiple"
    elif active:
        journal_path = active[0]
        journal = _journal_document(journal_path)
        journal_id_value = journal.get("journal_id")
        if not isinstance(journal_id_value, str):
            raise ReportControlError("gate_journal_invalid")
        journal_id = journal_id_value
        snapshot_id = journal.get("snapshot_id")
        if isinstance(snapshot_id, str) and _SAFE_ID.fullmatch(snapshot_id):
            snapshot_path = snapshots_root / snapshot_id
            try:
                snapshot = _read_regular(snapshot_path, reason="gate_snapshot_invalid")
                snapshot_gates, _snapshot_lines = _parse_env(snapshot)
                if snapshot_gates == _ALL_OFF_GATES:
                    recovered_payload = snapshot
            except ReportControlError:
                pass
            if snapshot_path.exists() and not snapshot_path.is_symlink():
                snapshot_path.unlink()
                _fsync_directory(snapshot_path.parent)
        _atomic_replace(env_path, recovered_payload)
        _terminalize_recovered_journal(
            path=journal_path,
            journal=journal,
            reason="active_transaction_recovery",
        )
    elif current != _ALL_OFF_GATES:
        _atomic_replace(env_path, recovered_payload)
    orphan_snapshot_count = _cleanup_orphan_snapshots(snapshots_root)
    if orphan_snapshot_count:
        _write_gate_incident(gates_root=gates_root, reason="orphan_gate_snapshots")
    if quarantine_name is not None:
        _write_gate_incident(gates_root=gates_root, reason="runtime_env_invalid")
    if missing_env:
        _write_gate_incident(gates_root=gates_root, reason="runtime_env_missing")
    incident = bool(
        quarantine_name
        or missing_env
        or corrupt_journal_count
        or orphan_snapshot_count
        or len(active) > 1
    )
    return {
        "status": "recovered_incident" if incident else "recovered",
        "journal_id": journal_id or "none",
        "gates": "all_off",
    }


def _gate_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("command")
    parser.add_argument("--shadow-root", type=Path)
    parser.add_argument("--authorization-id")
    parser.add_argument("--expected-release-sha256")
    parser.add_argument("--journal-id")
    parser.add_argument("--translation-mode")
    parser.add_argument("--enable-deepseek")
    parser.add_argument("--dingtalk-mode")
    parser.add_argument("--enable-dingtalk-live-send")
    parser.add_argument("--enable-failure-alert")
    parser.add_argument("--terminal-kill-switch", action="store_true")
    parser.add_argument("--authorize-secret-provisioning", action="store_true")
    parser.add_argument("--check-key", action="store_true")
    parser.add_argument("--inherited-lock-fd", type=int)
    parser.add_argument("--run-id")
    parser.add_argument("--attempt-id")
    parser.add_argument("--artifact-version-id")
    parser.add_argument("--provider-authorization-id")
    parser.add_argument("--expected-bundle-sha256")
    parser.add_argument("--expected-outbox-sha256")
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument("--action")
    parser.add_argument("--scheduled-cycle-id")
    parser.add_argument("--cycle-lease-fd", type=int)
    parser.add_argument("--scheduled-at")
    parser.add_argument("--resend-part-index", type=int, action="append", default=[])
    return parser


def gates_main(argv: Sequence[str]) -> int:
    try:
        args = _gate_parser().parse_args(list(argv))
        paths = _gate_paths(args)
        with _applicable_lock(args, Path(paths["lock"])):
            if args.command in {"check", "--check"}:
                _require_secret_provisioning(args)
                payload = _read_regular(
                    Path(paths["env"]), reason="runtime_secret_file_invalid"
                )
                gates, _lines = _parse_env(payload)
                if args.check_key:
                    _check_key_metadata(Path(paths["key"]))
                result = {
                    "status": "ok",
                    "gates": "all_off" if gates == _ALL_OFF_GATES else "enabled",
                }
            elif args.command == "verify-base-env":
                payload = _read_regular(
                    Path(paths["env"]), reason="runtime_secret_file_invalid"
                )
                gates, _lines = _parse_env(payload)
                if (
                    gates != _ALL_OFF_GATES
                    or _active_gate_journals(Path(paths["gates"]))
                ):
                    raise ReportControlError("runtime_base_env_not_immutable")
                result = {"status": "verified", "gates": "all_off"}
            elif args.command == "install-env":
                _require_secret_provisioning(args)
                result = _install_runtime_env(paths)
            elif args.command == "install-key":
                _require_secret_provisioning(args)
                result = _install_runtime_key(paths)
            elif args.command == "materialize-prepare-env":
                result = _materialize_prepare_env(args, paths)
            elif args.command == "materialize-send-env":
                result = _materialize_send_env(args, paths)
            elif args.command == "remove-runtime-env":
                result = _remove_runtime_env(args, paths)
            elif args.command == "set-gates":
                result = _set_gates(args, paths)
            elif args.command == "restore-gates":
                result = _restore_gates(args, paths)
            elif args.command == "recover-gates":
                result = _recover_gates(paths)
            else:
                raise ReportControlError("runtime_env_operation_not_implemented")
    except (ReportControlError, OSError, ValueError) as exc:
        reason = str(exc)
        if _SAFE_ID.fullmatch(reason) is None:
            reason = "runtime_env_operation_failed"
        print(
            f"status=blocked\nreason={reason}\nsecrets=<redacted>\n"
            "provider_call=false\nlive_send=false",
            file=sys.stderr,
        )
        return 1
    for key, value in result.items():
        print(f"{key}={value}")
    print("secrets=<redacted>")
    print("provider_call=false")
    print("live_send=false")
    return 0


def _prepared_admin_layout(
    args: argparse.Namespace,
) -> tuple[Mapping[str, object], Mapping[str, str]]:
    if args.shadow_root is None:
        if os.getenv("REDDIT_VOC_LOCAL_TEST_MODE") == "1":
            raise ReportControlError("local_test_production_scope_forbidden")
        fixed = {
            "public": Path("/opt/reddit-voc-site/outputs"),
            "private": Path("/opt/reddit-voc-site/private"),
            "state": Path("/opt/reddit-voc-daily-report/state"),
            "blocked": Path("/opt/reddit-voc-daily-report/blocked"),
            "handoff": Path("/opt/reddit-voc-daily-report/handoff"),
            "provider_attempts": Path(
                "/home/ubuntu/.reddit-voc/report-control/provider-attempts"
            ),
        }
        supplied = {
            "public": args.public_root,
            "private": args.private_root,
            "state": args.state_root,
            "blocked": args.blocked_root,
            "handoff": args.handoff_root,
        }
        for name, value in supplied.items():
            if value is not None and Path(value) != fixed[name]:
                raise ReportControlError("production_prepared_path_invalid")
        public_staging = Path(
            args.public_staging_root
            or fixed["public"] / ".report-staging" / "recovery-unused"
        )
        private_staging = Path(
            args.private_staging_root
            or fixed["private"] / ".report-staging" / "recovery-unused"
        )
        staging_pairs = (
            (public_staging, fixed["public"] / ".report-staging"),
            (private_staging, fixed["private"] / ".report-staging"),
        )
        for staging, parent in staging_pairs:
            if not staging.is_absolute() or staging.parent != parent:
                raise ReportControlError("production_staging_path_invalid")
            if args.attempt_id is not None and staging.name != args.attempt_id:
                raise ReportControlError("production_staging_path_invalid")
        paths = {
            **{name: str(path) for name, path in fixed.items()},
            "public_staging": str(public_staging),
            "private_staging": str(private_staging),
        }
        return (
            {
                "descriptor": {},
                "control": Path("/home/ubuntu/.reddit-voc/report-control"),
                "lock": _DAILY_REPORT_LOCK_PATH,
                "env": Path(
                    "/home/ubuntu/.reddit-voc/secrets/reddit-voc-report.env"
                ),
            },
            paths,
        )
    root = Path(args.shadow_root).resolve(strict=True)
    descriptor = _load_shadow_descriptor(root)
    paths = descriptor.get("paths")
    if not isinstance(paths, Mapping) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in paths.items()
    ):
        raise ReportControlError("shadow_descriptor_invalid")
    return (
        {
            "descriptor": descriptor,
            "control": root / "control",
            "lock": root / "lock",
            "env": root / "secrets" / "reddit-voc-report.env",
        },
        {str(key): str(value) for key, value in paths.items()},
    )


def _load_neutral_prepared_runtime(
    *, release_dir: Path, expected_release_sha256: str, config_root: Path
) -> Mapping[str, object]:
    release_sha = _require_sha(expected_release_sha256, "release_sha256")
    release = release_dir.resolve(strict=True)
    if (
        os.getenv("REDDIT_VOC_LOCAL_TEST_MODE") != "1"
        and release.name != release_sha
    ):
        raise ReportControlError("release_path_mismatch")
    source_root = release / "src"
    config = config_root.resolve(strict=True)
    if (
        os.getenv("REDDIT_VOC_LOCAL_TEST_MODE") != "1"
        and config != release / "config"
    ):
        raise ReportControlError("config_root_mismatch")
    if not source_root.is_dir() or source_root.is_symlink():
        raise ReportControlError("release_source_invalid")
    source_text = str(source_root)
    if source_text not in sys.path:
        sys.path.insert(0, source_text)
    importlib.invalidate_caches()
    contracts = importlib.import_module("reddit_voc.report_contracts")
    bundle = importlib.import_module("reddit_voc.prepared_bundle")
    delivery = importlib.import_module("reddit_voc.daily_report_delivery")
    provider_ledger = importlib.import_module("reddit_voc.provider_attempt_ledger")
    for module in (contracts, bundle, delivery, provider_ledger):
        module_file = getattr(module, "__file__", None)
        if not isinstance(module_file, str):
            raise ReportControlError("release_module_path_invalid")
        try:
            Path(module_file).resolve(strict=True).relative_to(release)
        except (OSError, ValueError) as exc:
            raise ReportControlError("release_module_path_invalid") from exc
    schema_assets = contracts.load_report_schema_assets(config_root=config)
    return {
        "PreparedReportRoots": bundle.PreparedReportRoots,
        "commit_staged_prepared_report": bundle.commit_staged_prepared_report,
        "commit_staged_blocked_attempt": bundle.commit_staged_blocked_attempt,
        "load_verified_prepared_report": bundle.load_verified_prepared_report,
        "recover_projection_journal": bundle.recover_projection_journal,
        "load_and_verify_delivery_ledger": (
            delivery.load_and_verify_delivery_ledger
        ),
        "project_sent_delivery_records_from_ledgers": (
            delivery.project_sent_delivery_records_from_ledgers
        ),
        "build_delivery_projection_plan_from_ledgers": (
            delivery.build_delivery_projection_plan_from_ledgers
        ),
        "apply_delivery_projection_plan": (
            delivery.apply_delivery_projection_plan
        ),
        "serialize_delivery_projection_plan": (
            delivery.serialize_delivery_projection_plan
        ),
        "deserialize_delivery_projection_plan": (
            delivery.deserialize_delivery_projection_plan
        ),
        "ProviderAttemptLedger": provider_ledger.ProviderAttemptLedger,
        "schema_assets": schema_assets,
    }


def _prepared_roots(runtime: Mapping[str, object], paths: Mapping[str, str]) -> object:
    prepared_roots_type = runtime["PreparedReportRoots"]
    return prepared_roots_type(
        public_root=Path(paths["public"]),
        private_root=Path(paths["private"]),
        public_staging_root=Path(paths["public_staging"]),
        private_staging_root=Path(paths["private_staging"]),
        state_root=Path(paths["state"]),
        blocked_root=Path(paths["blocked"]),
        handoff_root=Path(paths["handoff"]),
    )


def _require_reserved_prepare_permit(
    *,
    control_root: Path,
    authorization_id: str,
    release_sha256: str,
    run_id: str,
) -> Mapping[str, object]:
    permit, state, _state_path = _load_permit_state(
        root=control_root, authorization_id=authorization_id
    )
    expiry = permit.get("expires_at")
    schema_version = permit.get("schema_version")
    max_attempts = permit.get("max_attempts")
    if (
        schema_version
        not in {
            "report-prepare-permit-v1",
            "report-schedule-permit-v1",
            "report-scheduled-cycle-prepare-permit-v1",
        }
        or permit.get("release_sha256") != release_sha256
        or permit.get("run_id") != run_id
        or permit.get("live_send") is not False
        or isinstance(max_attempts, bool)
        or not isinstance(max_attempts, int)
        or not 1 <= max_attempts <= 100
        or state.get("status") != "reserved"
        or not isinstance(expiry, str)
        or not _expiry_is_future(expiry)
    ):
        raise ReportControlError("prepare_permit_not_reserved")
    if schema_version in {
        "report-schedule-permit-v1",
        "report-scheduled-cycle-prepare-permit-v1",
    }:
        expected_action = (
            "prepare_only"
            if schema_version == "report-schedule-permit-v1"
            else "prepare_once_then_derive_exact_send"
        )
        if (
            permit.get("action") != expected_action
            or permit.get("report_count") != 1
            or permit.get("failure_alert") is not False
        ):
            raise ReportControlError("prepare_permit_not_reserved")
        if schema_version == "report-scheduled-cycle-prepare-permit-v1" and (
            permit.get("max_prepare_invocations") != 1
            or not isinstance(permit.get("cycle_id"), str)
            or not isinstance(permit.get("report_date"), str)
            or not _is_supported_scheduled_provider_policy(
                permit.get("provider_attempt_policy")
            )
            or max_attempts
            != permit.get("provider_attempt_policy", {}).get(
                "max_attempts_per_cycle"
            )
        ):
            raise ReportControlError("prepare_permit_not_reserved")
    return permit


def _require_reserved_provider_permit(
    *,
    control_root: Path,
    authorization_id: str,
    release_sha256: str,
    run_id: str,
) -> Mapping[str, object]:
    permit, state, _state_path = _load_permit_state(
        root=control_root, authorization_id=authorization_id
    )
    expiry = permit.get("expires_at")
    max_attempts = permit.get("max_attempts")
    common_invalid = (
        permit.get("schema_version")
        not in {
            "report-shadow-permit-v1",
            "report-prepare-permit-v1",
            "report-schedule-permit-v1",
            "report-scheduled-cycle-prepare-permit-v1",
        }
        or permit.get("release_sha256") != release_sha256
        or permit.get("run_id") != run_id
        or permit.get("live_send") is not False
        or isinstance(max_attempts, bool)
        or not isinstance(max_attempts, int)
        or not 1 <= max_attempts <= 100
        or state.get("status") != "reserved"
        or not isinstance(expiry, str)
        or not _expiry_is_future(expiry)
    )
    if common_invalid:
        raise ReportControlError("provider_permit_not_reserved")
    if permit.get("schema_version") in {
        "report-shadow-permit-v1",
        "report-schedule-permit-v1",
        "report-scheduled-cycle-prepare-permit-v1",
    }:
        if (
            permit.get("failure_alert") is not False
            or permit.get("report_count") != 1
        ):
            raise ReportControlError("provider_permit_not_reserved")
        if permit.get("schema_version") == "report-shadow-permit-v1":
            _require_sha(permit.get("candidate_sha256"), "candidate_sha256")
        else:
            expected_action = (
                "prepare_only"
                if permit.get("schema_version") == "report-schedule-permit-v1"
                else "prepare_once_then_derive_exact_send"
            )
            if permit.get("action") != expected_action:
                raise ReportControlError("provider_permit_not_reserved")
            if permit.get("schema_version") == (
                "report-scheduled-cycle-prepare-permit-v1"
            ) and (
                not _is_supported_scheduled_provider_policy(
                    permit.get("provider_attempt_policy")
                )
                or max_attempts
                != permit.get("provider_attempt_policy", {}).get(
                    "max_attempts_per_cycle"
                )
            ):
                raise ReportControlError("provider_permit_not_reserved")
    return permit


def _require_send_permit(
    *,
    control_root: Path,
    authorization_id: str,
    release_sha256: str,
    run_id: str,
    artifact_version_id: str,
    bundle_sha256: str,
    outbox_sha256: str,
    action: str,
    resend_part_indexes: Sequence[int],
    expected_status: str,
    scheduled_cycle_id: str | None = None,
    cycle_lease_token: str | None = None,
    scheduled_at: str | None = None,
    enforce_use_boundary: bool = True,
) -> Mapping[str, object]:
    _require_id(authorization_id, "authorization_id")
    _require_sha(release_sha256, "release_sha256")
    _require_id(run_id, "run_id")
    if not isinstance(artifact_version_id, str) or _VERSION_ID.fullmatch(
        artifact_version_id
    ) is None:
        raise ReportControlError("artifact_version_id_invalid")
    _require_sha(bundle_sha256, "bundle_sha256")
    _require_sha(outbox_sha256, "outbox_sha256")
    if action not in {"initial", "resend"}:
        raise ReportControlError("send_permit_not_reserved")
    parts = tuple(resend_part_indexes)
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1
        for value in parts
    ) or len(parts) != len(set(parts)):
        raise ReportControlError("send_permit_not_reserved")
    if (action == "initial" and parts) or (action == "resend" and not parts):
        raise ReportControlError("send_permit_not_reserved")
    permit, state, _state_path = _load_permit_state(
        root=control_root, authorization_id=authorization_id
    )
    expiry = permit.get("expires_at")
    schema = permit.get("schema_version")
    common = {
        "authorization_id": authorization_id,
        "release_sha256": release_sha256,
        "expires_at": expiry,
        "run_id": run_id,
        "action": action,
        "artifact_version_id": artifact_version_id,
        "bundle_sha256": bundle_sha256,
        "outbox_sha256": outbox_sha256,
        "resend_part_indexes": list(parts),
    }
    invalid = (
        state.get("status") != expected_status
        or not isinstance(expiry, str)
        or (enforce_use_boundary and not _expiry_is_future(expiry))
        or any(permit.get(key) != value for key, value in common.items())
    )
    if schema == "report-send-permit-v1":
        expected = {"schema_version": schema, **common}
        invalid = invalid or permit != expected or scheduled_cycle_id is not None
        invalid = invalid or cycle_lease_token is not None
    elif schema in {
        "report-scheduled-cycle-send-permit-v1",
        "report-scheduled-cycle-send-permit-v2",
    }:
        if scheduled_cycle_id is None or cycle_lease_token is None:
            invalid = True
        else:
            cycle_id = _require_id(scheduled_cycle_id, "scheduled_cycle_id")
            lease_token = _require_sha(cycle_lease_token, "cycle_lease_token")
            dual = schema == "report-scheduled-cycle-send-permit-v2"
            invalid = invalid or (
                set(permit)
                != (
                    _SCHEDULED_SEND_PERMIT_V2_KEYS
                    if dual
                    else _SCHEDULED_SEND_PERMIT_KEYS
                )
                or permit.get("cycle_id") != cycle_id
                or permit.get("cycle_lease_sha256")
                != _sha256(lease_token.encode("ascii"))
                or permit.get("action") != "initial"
                or permit.get("resend_part_indexes") != []
                or permit.get("automatic_resend") is not False
                or permit.get("required_keyword") != "LL"
            )
            if dual:
                try:
                    _require_g6r1_dual_identity(
                        credential_set_epoch_id=permit.get(
                            "credential_set_epoch_id"
                        ),
                        destination_set_id=permit.get("destination_set_id"),
                        destinations=permit.get("destinations"),
                    )
                except ReportControlError:
                    invalid = True
                invalid = invalid or (
                    permit.get("delivery_plan")
                    != canonical_g6r1_dual_delivery_plan()
                )
            else:
                invalid = invalid or (
                    permit.get("destination_alias") != "HighValueAsset"
                )
            for key in (
                "policy_sha256",
                "launcher_sha256",
                "cycle_lease_sha256",
                "commit_request_sha256",
                "commit_receipt_sha256",
            ):
                _require_sha(permit.get(key), key)
            identity_keys = (
                "policy_authorization_id",
                "prepare_authorization_id",
                "prepare_attempt_id",
            ) + (
                ("credential_set_epoch_id", "destination_set_id")
                if dual
                else ("credential_epoch_id", "destination_alias")
            )
            for key in identity_keys:
                _require_id(permit.get(key), key)
            report_date = permit.get("report_date")
            try:
                if not isinstance(report_date, str):
                    raise ValueError
                date.fromisoformat(report_date)
            except ValueError:
                invalid = True
            if not invalid and enforce_use_boundary:
                _require_scheduled_send_window(
                    report_date=str(report_date),
                    expires_at=str(expiry),
                    scheduled_at=scheduled_at,
                )
            entries = _load_scheduled_cycle_ledger(control_root)
            latest = _latest_scheduled_cycle_event(entries, cycle_id)
            invalid = invalid or any(
                latest.get(key) != permit.get(key)
                for key in (
                    "cycle_id",
                    "report_date",
                    "run_id",
                    "release_sha256",
                    "launcher_sha256",
                    "policy_sha256",
                    "policy_authorization_id",
                    "prepare_authorization_id",
                    "prepare_attempt_id",
                    "artifact_version_id",
                    "bundle_sha256",
                    "outbox_sha256",
                    "commit_request_sha256",
                    "commit_receipt_sha256",
                )
            ) or latest.get("event") != "send_permit_derived"
            invalid = invalid or latest.get("send_authorization_id") != authorization_id
            receipt = _load_scheduled_commit_receipt(
                control_root=control_root, cycle_id=cycle_id
            )
            invalid = invalid or any(
                receipt.get(key) != permit.get(key)
                for key in (
                    "cycle_id",
                    "report_date",
                    "run_id",
                    "release_sha256",
                    "launcher_sha256",
                    "policy_sha256",
                    "policy_authorization_id",
                    "prepare_authorization_id",
                    "prepare_attempt_id",
                    "artifact_version_id",
                    "bundle_sha256",
                    "outbox_sha256",
                    "commit_request_sha256",
                    "cycle_lease_sha256",
                    "commit_receipt_sha256",
                )
            )
    else:
        invalid = True
    if invalid:
        raise ReportControlError("send_permit_not_reserved")
    return permit


def _reserve_send_permit(
    args: argparse.Namespace, *, control_root: Path
) -> Mapping[str, object]:
    authorization_id = _require_id(args.authorization_id, "authorization_id")
    release_sha = _require_sha(args.expected_release_sha256, "release_sha256")
    run_id = _require_id(args.run_id, "run_id")
    permit = _require_send_permit(
        control_root=control_root,
        authorization_id=authorization_id,
        release_sha256=release_sha,
        run_id=run_id,
        artifact_version_id=args.expected_artifact_version_id,
        bundle_sha256=args.expected_bundle_sha256,
        outbox_sha256=args.expected_outbox_sha256,
        action=args.action,
        resend_part_indexes=args.resend_part_index,
        expected_status="installed",
        scheduled_cycle_id=args.scheduled_cycle_id,
        cycle_lease_token=_read_cycle_lease(
            args, required=args.scheduled_cycle_id is not None
        ),
        scheduled_at=getattr(args, "scheduled_at", None),
    )
    _transition_permit(
        root=control_root,
        authorization_id=authorization_id,
        expected_release_sha256=release_sha,
        expected_run_id=run_id,
        target_status="reserved",
    )
    return _require_send_permit(
        control_root=control_root,
        authorization_id=authorization_id,
        release_sha256=release_sha,
        run_id=run_id,
        artifact_version_id=args.expected_artifact_version_id,
        bundle_sha256=args.expected_bundle_sha256,
        outbox_sha256=args.expected_outbox_sha256,
        action=args.action,
        resend_part_indexes=args.resend_part_index,
        expected_status="reserved",
        scheduled_cycle_id=args.scheduled_cycle_id,
        cycle_lease_token=_read_cycle_lease(
            args, required=args.scheduled_cycle_id is not None
        ),
        scheduled_at=getattr(args, "scheduled_at", None),
    )


def _validate_send_permit_use(
    args: argparse.Namespace, *, control_root: Path
) -> Mapping[str, object]:
    permit = _require_send_permit(
        control_root=control_root,
        authorization_id=_require_id(args.authorization_id, "authorization_id"),
        release_sha256=_require_sha(
            args.expected_release_sha256, "release_sha256"
        ),
        run_id=_require_id(args.run_id, "run_id"),
        artifact_version_id=args.expected_artifact_version_id,
        bundle_sha256=args.expected_bundle_sha256,
        outbox_sha256=args.expected_outbox_sha256,
        action=args.action,
        resend_part_indexes=args.resend_part_index,
        expected_status="reserved",
        scheduled_cycle_id=args.scheduled_cycle_id,
        cycle_lease_token=_read_cycle_lease(
            args, required=args.scheduled_cycle_id is not None
        ),
        scheduled_at=getattr(args, "scheduled_at", None),
    )
    return {
        "status": "validated",
        "authorization_id": permit["authorization_id"],
    }


def _dual_terminal_evidence(
    args: argparse.Namespace, *, target_status: str
) -> Mapping[str, object] | None:
    aggregate = str(args.delivery_status or "")
    primary = str(args.primary_delivery_status or "")
    secondary = str(args.secondary_delivery_status or "")
    primary_tip = str(args.primary_ledger_tip or "")
    secondary_tip = str(args.secondary_ledger_tip or "")
    if not aggregate and not primary and not secondary and not primary_tip and not secondary_tip:
        if target_status not in {"closed_no_attempt", "blocked", "unknown"}:
            raise ReportControlError("dual_delivery_evidence_required")
        return None
    if not aggregate or not primary or not secondary:
        raise ReportControlError("dual_delivery_evidence_invalid")
    allowed_aggregate = {
        "sent",
        "partially_sent",
        "partial_unknown_delivery_state",
        "unknown_delivery_state",
        "rejected",
        "blocked",
    }
    if aggregate not in allowed_aggregate:
        raise ReportControlError("dual_delivery_evidence_invalid")
    for value in (primary, secondary):
        if _SAFE_ID.fullmatch(value) is None:
            raise ReportControlError("dual_delivery_evidence_invalid")
    statuses = {primary, secondary}
    successful = sum(
        value in {"sent", "already_sent"} for value in (primary, secondary)
    )
    if successful == 2:
        expected_aggregate = "sent"
    elif "unknown_delivery_state" in statuses and successful:
        expected_aggregate = "partial_unknown_delivery_state"
    elif "unknown_delivery_state" in statuses:
        expected_aggregate = "unknown_delivery_state"
    elif successful:
        expected_aggregate = "partially_sent"
    elif statuses == {"rejected"}:
        expected_aggregate = "rejected"
    else:
        expected_aggregate = "blocked"
    target_by_aggregate = {
        "sent": "consumed",
        "partially_sent": "partial",
        "partial_unknown_delivery_state": "unknown",
        "unknown_delivery_state": "unknown",
        "rejected": "blocked",
        "blocked": "blocked",
    }
    if aggregate != expected_aggregate or target_by_aggregate[aggregate] != target_status:
        raise ReportControlError("dual_delivery_evidence_invalid")

    destinations: list[Mapping[str, object]] = []
    for destination_id, status, tip in (
        ("primary", primary, primary_tip),
        ("secondary", secondary, secondary_tip),
    ):
        if tip:
            ledger_tip: str | None = _require_sha(tip, "ledger_tip")
        else:
            ledger_tip = None
        if status in {
            "sent",
            "already_sent",
            "rejected",
            "unknown_delivery_state",
        } and ledger_tip is None:
            raise ReportControlError("dual_delivery_evidence_invalid")
        destinations.append(
            {
                "destination_id": destination_id,
                "status": status,
                "ledger_tip": ledger_tip,
            }
        )
    return {
        "schema_version": "report-dual-delivery-terminal-evidence-v1",
        "delivery_status": aggregate,
        "destinations": destinations,
    }


def _terminalize_send_permit(
    args: argparse.Namespace, *, control_root: Path
) -> str:
    target = str(args.terminal_status or "")
    if target not in {
        "consumed",
        "partial",
        "closed_no_attempt",
        "blocked",
        "unknown",
    }:
        raise ReportControlError("send_permit_terminal_status_invalid")
    authorization_id = _require_id(args.authorization_id, "authorization_id")
    release_sha = _require_sha(args.expected_release_sha256, "release_sha256")
    run_id = _require_id(args.run_id, "run_id")
    permit = _require_send_permit(
        control_root=control_root,
        authorization_id=authorization_id,
        release_sha256=release_sha,
        run_id=run_id,
        artifact_version_id=args.expected_artifact_version_id,
        bundle_sha256=args.expected_bundle_sha256,
        outbox_sha256=args.expected_outbox_sha256,
        action=args.action,
        resend_part_indexes=args.resend_part_index,
        expected_status="reserved",
        scheduled_cycle_id=args.scheduled_cycle_id,
        cycle_lease_token=_read_cycle_lease(
            args, required=args.scheduled_cycle_id is not None
        ),
        scheduled_at=getattr(args, "scheduled_at", None),
        enforce_use_boundary=False,
    )
    dual = (
        permit.get("schema_version")
        == "report-scheduled-cycle-send-permit-v2"
    )
    if not dual and any(
        getattr(args, name, None)
        for name in (
            "delivery_status",
            "primary_delivery_status",
            "secondary_delivery_status",
            "primary_ledger_tip",
            "secondary_ledger_tip",
        )
    ):
        raise ReportControlError("dual_delivery_evidence_forbidden")
    terminal_evidence = (
        _dual_terminal_evidence(args, target_status=target) if dual else None
    )
    _transition_permit(
        root=control_root,
        authorization_id=authorization_id,
        expected_release_sha256=release_sha,
        expected_run_id=run_id,
        target_status=target,
        terminal_evidence=terminal_evidence,
    )
    if permit.get("schema_version") in {
        "report-scheduled-cycle-send-permit-v1",
        "report-scheduled-cycle-send-permit-v2",
    }:
        cycle_id = _require_id(args.scheduled_cycle_id, "scheduled_cycle_id")
        latest = _latest_scheduled_cycle_event(
            _load_scheduled_cycle_ledger(control_root), cycle_id
        )
        _append_scheduled_cycle_terminal(
            control_root=control_root,
            latest=latest,
            event={
                "consumed": "send_consumed",
                "partial": "send_partial",
                "closed_no_attempt": "send_closed_no_attempt",
                "blocked": "send_blocked",
                "unknown": "send_unknown",
            }[target],
        )
    return target


def _reserve_scheduled_prepare(
    args: argparse.Namespace, *, control_root: Path
) -> str:
    release_sha = _require_sha(args.expected_release_sha256, "release_sha256")
    run_id = _require_id(args.run_id, "run_id")
    layout = _control_layout(control_root)
    matches: list[str] = []
    for permit_path in sorted(layout["permits"].glob("*.json")):
        permit = _strict_json_bytes(
            _read_regular(permit_path, reason="permit_invalid"), "permit_invalid"
        )
        authorization_id = permit.get("authorization_id")
        if not isinstance(authorization_id, str) or permit_path.stem != authorization_id:
            raise ReportControlError("permit_invalid")
        if (
            permit.get("schema_version") != "report-schedule-permit-v1"
            or permit.get("release_sha256") != release_sha
            or permit.get("run_id") != run_id
        ):
            continue
        _permit, state, _state_path = _load_permit_state(
            root=control_root, authorization_id=authorization_id
        )
        expiry = permit.get("expires_at")
        if (
            permit.get("action") != "prepare_only"
            or permit.get("report_count") != 1
            or permit.get("live_send") is not False
            or permit.get("failure_alert") is not False
            or isinstance(permit.get("max_attempts"), bool)
            or not isinstance(permit.get("max_attempts"), int)
            or not 1 <= permit["max_attempts"] <= 100
            or state.get("status") != "installed"
            or not isinstance(expiry, str)
            or not _expiry_is_future(expiry)
        ):
            continue
        matches.append(authorization_id)
    if len(matches) != 1:
        raise ReportControlError(
            "schedule_permit_unavailable"
            if not matches
            else "schedule_permit_ambiguous"
        )
    authorization_id = matches[0]
    _transition_permit(
        root=control_root,
        authorization_id=authorization_id,
        expected_release_sha256=release_sha,
        expected_run_id=run_id,
        target_status="reserved",
    )
    return authorization_id


def _reserve_scheduled_cycle(
    args: argparse.Namespace, *, control_root: Path
) -> Mapping[str, object]:
    release_sha = _require_sha(args.expected_release_sha256, "release_sha256")
    launcher_sha = _require_sha(args.expected_launcher_sha256, "launcher_sha256")
    run_id = _require_id(args.run_id, "run_id")
    cycle_lease_token = str(_read_cycle_lease(args, required=True))
    cycle_lease_sha = _sha256(cycle_lease_token.encode("ascii"))
    if (
        os.getenv("REDDIT_VOC_LOCAL_TEST_MODE") == "1"
        and not isinstance(args.scheduled_at, str)
    ):
        raise ReportControlError("scheduled_time_invalid")
    authority = _load_scheduled_cycle_policy(
        args,
        control_root=control_root,
        release_sha256=release_sha,
        launcher_sha256=launcher_sha,
        run_id=run_id,
        scheduled_at=str(args.scheduled_at or ""),
    )
    report_date = str(authority["report_date"])
    _recover_scheduled_cycles(control_root)
    entries = _load_scheduled_cycle_ledger(control_root, create=True)
    all_reservations = [
        entry for entry in entries if entry.get("event") == "prepare_reserved"
    ]
    if any(
        entry.get("report_date") == report_date for entry in all_reservations
    ):
        raise ReportControlError("scheduled_slot_already_consumed")
    reservations = [
        entry
        for entry in all_reservations
        if entry.get("policy_sha256") == authority["policy_sha256"]
    ]
    max_slots = authority["policy"].get("max_slots")
    if isinstance(max_slots, bool) or not isinstance(max_slots, int):
        raise ReportControlError("scheduled_policy_slot_cap_invalid")
    if len(reservations) >= max_slots:
        raise ReportControlError("scheduled_slot_cap_exhausted")
    cycle_id = _scheduled_cycle_id(
        policy_sha256=str(authority["policy_sha256"]),
        release_sha256=release_sha,
        launcher_sha256=launcher_sha,
        report_date=report_date,
        run_id=run_id,
    )
    authorization_id = f"g6r1-prepare-{report_date.replace('-', '')}-{cycle_id[-24:]}"
    document = {
        "schema_version": "report-scheduled-cycle-prepare-permit-v1",
        "authorization_id": authorization_id,
        "release_sha256": release_sha,
        "expires_at": authority["policy"]["expires_at_utc"],
        "run_id": run_id,
        "cycle_id": cycle_id,
        "report_date": report_date,
        "policy_sha256": authority["policy_sha256"],
        "policy_authorization_id": authority["policy_authorization_id"],
        "launcher_sha256": launcher_sha,
        "cycle_lease_sha256": cycle_lease_sha,
        "provider_attempt_policy": authority["provider_attempt_policy"],
        "max_attempts": authority["provider_attempt_policy"][
            "max_attempts_per_cycle"
        ],
        "max_prepare_invocations": 1,
        "report_count": 1,
        "action": "prepare_once_then_derive_exact_send",
        "live_send": False,
        "failure_alert": False,
    }
    # The date is consumed before permit installation. Any crash or filesystem
    # error after this durable append stays fail-closed and cannot trigger a
    # second prepare or Provider attempt for the same natural slot.
    _append_scheduled_cycle_event(
        control_root=control_root,
        event="prepare_reserved",
        cycle_id=cycle_id,
        report_date=report_date,
        run_id=run_id,
        release_sha256=release_sha,
        launcher_sha256=launcher_sha,
        policy_sha256=str(authority["policy_sha256"]),
        policy_authorization_id=str(authority["policy_authorization_id"]),
        prepare_authorization_id=authorization_id,
        cycle_lease_sha256=cycle_lease_sha,
    )
    _install_permit(root=control_root, document=document)
    _transition_permit(
        root=control_root,
        authorization_id=authorization_id,
        expected_release_sha256=release_sha,
        expected_run_id=run_id,
        target_status="reserved",
    )
    return {
        "status": "reserved",
        "cycle_id": cycle_id,
        "authorization_id": authorization_id,
        "permit_kind": "scheduled_cycle_prepare",
        "report_date": report_date,
        "run_id": run_id,
    }


def _terminalize_scheduled_prepare(
    args: argparse.Namespace, *, control_root: Path
) -> Mapping[str, object]:
    target = str(args.terminal_status or "")
    if target not in {"blocked", "unknown", "closed_no_attempt"}:
        raise ReportControlError("scheduled_prepare_terminal_status_invalid")
    cycle_id = _require_id(args.cycle_id, "cycle_id")
    authorization_id = _require_id(
        args.prepare_action_authorization_id,
        "prepare_action_authorization_id",
    )
    release_sha = _require_sha(args.expected_release_sha256, "release_sha256")
    run_id = _require_id(args.run_id, "run_id")
    lease_token = str(_read_cycle_lease(args, required=True))
    latest = _latest_scheduled_cycle_event(
        _load_scheduled_cycle_ledger(control_root), cycle_id
    )
    latest_event = latest.get("event")
    if (
        latest_event not in {"prepare_reserved", "prepare_committed"}
        or latest.get("prepare_authorization_id") != authorization_id
        or latest.get("release_sha256") != release_sha
        or latest.get("run_id") != run_id
        or latest.get("cycle_lease_sha256")
        != _sha256(lease_token.encode("ascii"))
    ):
        raise ReportControlError("scheduled_prepare_cycle_mismatch")
    if latest_event == "prepare_committed":
        # Once host commit has a durable receipt, any failure before the exact
        # derived send in this invocation is indeterminate. Never label it a
        # retryable block or resume it on a later process.
        target = "unknown"
    _permit, state, _state_path = _load_permit_state(
        root=control_root, authorization_id=authorization_id
    )
    status = state.get("status")
    if status in {"installed", "reserved"}:
        permit_target = target
        if status == "installed" and target != "closed_no_attempt":
            permit_target = "closed_no_attempt"
            target = "closed_no_attempt"
        _transition_permit(
            root=control_root,
            authorization_id=authorization_id,
            expected_release_sha256=release_sha,
            expected_run_id=run_id,
            target_status=permit_target,
        )
    elif status not in {"consumed", "blocked", "unknown", "closed_no_attempt"}:
        raise ReportControlError("scheduled_prepare_state_invalid")
    _append_scheduled_cycle_terminal(
        control_root=control_root,
        latest=latest,
        event=f"prepare_{target}",
    )
    return {
        "status": target,
        "cycle_id": cycle_id,
        "authorization_id": authorization_id,
        "provider_call": False,
        "live_send": False,
    }


def _validate_provider_attempt_history(
    *, runtime: Mapping[str, object], provider_attempt_root: Path, run_id: str
) -> None:
    root = _ensure_directory(provider_attempt_root)
    ledger_type = runtime["ProviderAttemptLedger"]
    for authorization_root in sorted(root.iterdir()):
        if authorization_root.name.startswith("."):
            raise ReportControlError("provider_attempt_history_invalid")
        _ensure_directory(authorization_root)
        candidate_run_root = authorization_root / run_id
        if not candidate_run_root.exists() and not candidate_run_root.is_symlink():
            continue
        _ensure_directory(candidate_run_root)
        for attempt_root in sorted(candidate_run_root.iterdir()):
            _ensure_directory(attempt_root)
            path = attempt_root / "provider-attempts-v2.jsonl"
            if not path.exists() and not path.is_symlink():
                raise ReportControlError("provider_attempt_history_invalid")
            raw = _read_regular(path, reason="provider_attempt_history_invalid")
            lines = raw.splitlines()
            if not lines:
                continue
            first = _strict_json_bytes(
                lines[0], "provider_attempt_history_invalid"
            )
            try:
                ledger = ledger_type(
                    path=path,
                    authorization_id=authorization_root.name,
                    release_sha256=first.get("release_sha256"),
                    run_id=run_id,
                    attempt_id=attempt_root.name,
                    clock=lambda: _now_text(),
                )
                snapshot = ledger.load()
                attempts = ledger_type._closed_attempt_documents(snapshot)
            except Exception as exc:
                raise ReportControlError(
                    "provider_attempt_history_nonterminal"
                ) from exc
            if any(
                attempt.get("closure_event_type") != "terminal"
                or attempt.get("result") in {
                    None,
                    "reserved",
                    "attempting",
                    "unknown_external_state",
                }
                for attempt in attempts
            ):
                raise ReportControlError("provider_attempt_history_nonterminal")


def _validate_delivery_history_empty(
    *,
    runtime: Mapping[str, object],
    state_root: Path,
    run_id: str,
    destination_ids: Sequence[str] = (),
) -> None:
    delivery_run_root = state_root / "delivery" / run_id
    if destination_ids:
        expected_ids = tuple(destination_id for destination_id, _alias in _G6R1_DUAL_DESTINATIONS)
        if tuple(destination_ids) != expected_ids:
            raise ReportControlError("scheduled_destination_binding_invalid")
        destinations_root = delivery_run_root / "destinations"
        if destinations_root.exists() or destinations_root.is_symlink():
            _ensure_directory(destinations_root)
            actual = {candidate.name for candidate in destinations_root.iterdir()}
            if not actual.issubset(set(expected_ids)):
                raise ReportControlError("scheduled_delivery_history_invalid")
            for destination_id in expected_ids:
                ledger_path = destinations_root / destination_id / "ledger.jsonl"
                if not ledger_path.exists() and not ledger_path.is_symlink():
                    continue
                try:
                    entries = runtime["load_and_verify_delivery_ledger"](
                        ledger_path,
                        run_id=run_id,
                        destination_id=destination_id,
                    )
                except Exception as exc:
                    raise ReportControlError(
                        "scheduled_delivery_history_invalid"
                    ) from exc
                if entries:
                    statuses = {entry.get("status") for entry in entries}
                    if statuses & {"attempting", "unknown_delivery_state"}:
                        raise ReportControlError("scheduled_delivery_state_unknown")
                    raise ReportControlError("scheduled_delivery_history_exists")
        legacy_single_ledger = delivery_run_root / "ledger.jsonl"
        if legacy_single_ledger.exists() or legacy_single_ledger.is_symlink():
            raise ReportControlError("scheduled_delivery_history_exists")
    else:
        ledger_path = delivery_run_root / "ledger.jsonl"
        if ledger_path.exists() or ledger_path.is_symlink():
            try:
                entries = runtime["load_and_verify_delivery_ledger"](
                    ledger_path, run_id=run_id
                )
            except Exception as exc:
                raise ReportControlError(
                    "scheduled_delivery_history_invalid"
                ) from exc
            if entries:
                statuses = {entry.get("status") for entry in entries}
                if statuses & {"attempting", "unknown_delivery_state"}:
                    raise ReportControlError("scheduled_delivery_state_unknown")
                raise ReportControlError("scheduled_delivery_history_exists")
    legacy_run_root = state_root / "delivery-ledger" / run_id
    if legacy_run_root.exists() or legacy_run_root.is_symlink():
        _ensure_directory(legacy_run_root)
        if any(legacy_run_root.iterdir()):
            raise ReportControlError("scheduled_delivery_history_exists")


def _derive_scheduled_send_permit(
    args: argparse.Namespace,
    *,
    layout: Mapping[str, object],
    prepared_paths: Mapping[str, str],
) -> Mapping[str, object]:
    control_root = Path(layout["control"])
    release_sha = _require_sha(args.expected_release_sha256, "release_sha256")
    launcher_sha = _require_sha(args.expected_launcher_sha256, "launcher_sha256")
    run_id = _require_id(args.run_id, "run_id")
    cycle_id = _require_id(args.cycle_id, "cycle_id")
    cycle_lease_token = str(_read_cycle_lease(args, required=True))
    cycle_lease_sha = _sha256(cycle_lease_token.encode("ascii"))
    prepare_authorization_id = _require_id(
        args.prepare_action_authorization_id,
        "prepare_action_authorization_id",
    )
    attempt_id = _require_id(args.attempt_id, "attempt_id")
    artifact_version_id = args.expected_artifact_version_id
    if (
        not isinstance(artifact_version_id, str)
        or _VERSION_ID.fullmatch(artifact_version_id) is None
    ):
        raise ReportControlError("artifact_version_id_invalid")
    bundle_sha = _require_sha(args.expected_bundle_sha256, "bundle_sha256")
    outbox_sha = _require_sha(args.expected_outbox_sha256, "outbox_sha256")
    commit_request_sha = _require_sha(
        args.expected_commit_request_sha256, "commit_request_sha256"
    )
    entries = _load_scheduled_cycle_ledger(control_root)
    latest = _latest_scheduled_cycle_event(entries, cycle_id)
    if (
        latest.get("event") != "prepare_committed"
        or latest.get("run_id") != run_id
        or latest.get("release_sha256") != release_sha
        or latest.get("launcher_sha256") != launcher_sha
        or latest.get("prepare_authorization_id") != prepare_authorization_id
        or latest.get("cycle_lease_sha256") != cycle_lease_sha
        or latest.get("prepare_attempt_id") != attempt_id
        or latest.get("artifact_version_id") != artifact_version_id
        or latest.get("bundle_sha256") != bundle_sha
        or latest.get("outbox_sha256") != outbox_sha
        or latest.get("commit_request_sha256") != commit_request_sha
    ):
        raise ReportControlError("scheduled_cycle_not_derivable")
    report_date = str(latest["report_date"])
    authority = _load_scheduled_cycle_policy(
        args,
        control_root=control_root,
        release_sha256=release_sha,
        launcher_sha256=launcher_sha,
        run_id=run_id,
        scheduled_at="",
        enforce_current_slot=False,
        expected_report_date=report_date,
    )
    send_deadline = str(authority["slot"]["slot_end_at_utc"])
    _require_scheduled_send_window(
        report_date=report_date,
        expires_at=send_deadline,
        scheduled_at=getattr(args, "scheduled_at", None),
    )
    if (
        latest.get("policy_sha256") != authority["policy_sha256"]
        or latest.get("policy_authorization_id")
        != authority["policy_authorization_id"]
    ):
        raise ReportControlError("scheduled_cycle_policy_mismatch")
    prepare_permit, prepare_state, _prepare_state_path = _load_permit_state(
        root=control_root, authorization_id=prepare_authorization_id
    )
    if (
        prepare_permit.get("schema_version")
        != "report-scheduled-cycle-prepare-permit-v1"
        or prepare_permit.get("cycle_id") != cycle_id
        or prepare_permit.get("run_id") != run_id
        or prepare_permit.get("release_sha256") != release_sha
        or prepare_permit.get("policy_sha256") != authority["policy_sha256"]
        or prepare_permit.get("cycle_lease_sha256") != cycle_lease_sha
        or prepare_state.get("status") != "consumed"
    ):
        raise ReportControlError("scheduled_prepare_not_committed")
    commit_receipt = _load_scheduled_commit_receipt(
        control_root=control_root, cycle_id=cycle_id
    )
    expected_receipt_values = {
        "cycle_id": cycle_id,
        "report_date": report_date,
        "run_id": run_id,
        "release_sha256": release_sha,
        "launcher_sha256": launcher_sha,
        "policy_sha256": authority["policy_sha256"],
        "policy_authorization_id": authority["policy_authorization_id"],
        "prepare_authorization_id": prepare_authorization_id,
        "prepare_attempt_id": attempt_id,
        "artifact_version_id": artifact_version_id,
        "bundle_sha256": bundle_sha,
        "outbox_sha256": outbox_sha,
        "commit_request_sha256": commit_request_sha,
        "cycle_lease_sha256": cycle_lease_sha,
    }
    if (
        any(
            commit_receipt.get(key) != value
            for key, value in expected_receipt_values.items()
        )
        or latest.get("commit_receipt_sha256")
        != commit_receipt.get("commit_receipt_sha256")
    ):
        raise ReportControlError("scheduled_commit_receipt_mismatch")
    _require_commit_all_off(
        env_path=Path(layout["env"]), gates_root=control_root / "gates"
    )
    runtime = _load_neutral_prepared_runtime(
        release_dir=Path(args.release_dir),
        expected_release_sha256=release_sha,
        config_root=Path(args.config_root),
    )
    roots = _prepared_roots(runtime, prepared_paths)
    try:
        prepared = runtime["load_verified_prepared_report"](
            roots=roots,
            expected_run_id=run_id,
            expected_artifact_version_id=artifact_version_id,
            expected_bundle_sha256=bundle_sha,
            expected_outbox_sha256=outbox_sha,
            schema_assets=runtime["schema_assets"],
        )
    except Exception as exc:
        raise ReportControlError("scheduled_prepared_tuple_invalid") from exc
    if (
        prepared.run_id != run_id
        or prepared.artifact_version_id != artifact_version_id
        or prepared.bundle_sha256 != bundle_sha
        or prepared.outbox_sha256 != outbox_sha
    ):
        raise ReportControlError("scheduled_prepared_tuple_invalid")
    _validate_provider_attempt_history(
        runtime=runtime,
        provider_attempt_root=Path(prepared_paths["provider_attempts"]),
        run_id=run_id,
    )
    _validate_delivery_history_empty(
        runtime=runtime,
        state_root=Path(prepared_paths["state"]),
        run_id=run_id,
        destination_ids=(
            tuple(
                str(item["destination_id"])
                for item in authority["destinations"]
            )
            if authority["destination_mode"] == "dual"
            else ()
        ),
    )
    env_payload = _read_regular(
        Path(layout["env"]), reason="runtime_secret_file_invalid"
    )
    values, _lines = _parse_env_document(env_payload)
    if authority["destination_mode"] == "dual":
        expected_destinations = canonical_g6r1_dual_destinations()
        if (
            not values.get("DINGTALK_WEBHOOK_URL")
            or not values.get("DINGTALK_WEBHOOK_URL_2")
            or values.get("DINGTALK_WEBHOOK_URL")
            == values.get("DINGTALK_WEBHOOK_URL_2")
            or values.get("REDDIT_VOC_DINGTALK_CREDENTIAL_SET_EPOCH_ID")
            != authority["credential_set_epoch_id"]
            or values.get("REDDIT_VOC_DINGTALK_DESTINATION_SET_ID")
            != authority["destination_set_id"]
            or values.get("REDDIT_VOC_DINGTALK_PRIMARY_DESTINATION_ALIAS")
            != expected_destinations[0]["destination_alias"]
            or values.get("REDDIT_VOC_DINGTALK_SECONDARY_DESTINATION_ALIAS")
            != expected_destinations[1]["destination_alias"]
            or values.get("DINGTALK_REQUIRED_KEYWORD")
            != authority["required_keyword"]
        ):
            raise ReportControlError("scheduled_destination_binding_invalid")
    elif (
        not values.get("DINGTALK_WEBHOOK_URL")
        or values.get("REDDIT_VOC_DINGTALK_CREDENTIAL_EPOCH_ID")
        != authority["credential_epoch_id"]
        or values.get("REDDIT_VOC_DINGTALK_DESTINATION_ALIAS")
        != authority["destination_alias"]
        or values.get("DINGTALK_REQUIRED_KEYWORD") != authority["required_keyword"]
        or values.get("DINGTALK_WEBHOOK_URL_2")
        or values.get("DINGTALK_WEBHOOK_SECRET_2")
    ):
        raise ReportControlError("scheduled_destination_binding_invalid")
    send_digest = _sha256(
        _canonical(
            {
                "cycle_id": cycle_id,
                "run_id": run_id,
                "artifact_version_id": artifact_version_id,
                "bundle_sha256": bundle_sha,
                "outbox_sha256": outbox_sha,
            }
        )
    )[:24]
    send_authorization_id = (
        f"g6r1-send-{report_date.replace('-', '')}-{send_digest}"
    )
    document = {
        "schema_version": (
            "report-scheduled-cycle-send-permit-v2"
            if authority["destination_mode"] == "dual"
            else "report-scheduled-cycle-send-permit-v1"
        ),
        "authorization_id": send_authorization_id,
        "release_sha256": release_sha,
        "expires_at": send_deadline,
        "run_id": run_id,
        "action": "initial",
        "artifact_version_id": artifact_version_id,
        "bundle_sha256": bundle_sha,
        "outbox_sha256": outbox_sha,
        "commit_request_sha256": commit_request_sha,
        "commit_receipt_sha256": commit_receipt["commit_receipt_sha256"],
        "resend_part_indexes": [],
        "cycle_id": cycle_id,
        "report_date": report_date,
        "policy_sha256": authority["policy_sha256"],
        "policy_authorization_id": authority["policy_authorization_id"],
        "launcher_sha256": launcher_sha,
        "prepare_authorization_id": prepare_authorization_id,
        "prepare_attempt_id": attempt_id,
        "required_keyword": authority["required_keyword"],
        "automatic_resend": False,
        "cycle_lease_sha256": cycle_lease_sha,
    }
    if authority["destination_mode"] == "dual":
        document.update(
            {
                "credential_set_epoch_id": authority[
                    "credential_set_epoch_id"
                ],
                "destination_set_id": authority["destination_set_id"],
                "destinations": authority["destinations"],
                "delivery_plan": canonical_g6r1_dual_delivery_plan(),
            }
        )
    else:
        document.update(
            {
                "credential_epoch_id": authority["credential_epoch_id"],
                "destination_alias": authority["destination_alias"],
            }
        )
    # As with slot reservation, preserve the irreversible ledger event first.
    # A crash before permit installation consumes the cycle without a retry.
    _append_scheduled_cycle_event(
        control_root=control_root,
        event="send_permit_derived",
        cycle_id=cycle_id,
        report_date=report_date,
        run_id=run_id,
        release_sha256=release_sha,
        launcher_sha256=launcher_sha,
        policy_sha256=str(authority["policy_sha256"]),
        policy_authorization_id=str(authority["policy_authorization_id"]),
        prepare_authorization_id=prepare_authorization_id,
        cycle_lease_sha256=cycle_lease_sha,
        prepare_attempt_id=attempt_id,
        send_authorization_id=send_authorization_id,
        artifact_version_id=artifact_version_id,
        bundle_sha256=bundle_sha,
        outbox_sha256=outbox_sha,
        commit_request_sha256=commit_request_sha,
        commit_receipt_sha256=str(commit_receipt["commit_receipt_sha256"]),
    )
    _install_permit(root=control_root, document=document)
    return {
        "status": "derived",
        "cycle_id": cycle_id,
        "authorization_id": send_authorization_id,
        "run_id": run_id,
        "artifact_version_id": artifact_version_id,
        "bundle_sha256": bundle_sha,
        "outbox_sha256": outbox_sha,
        "provider_call": False,
        "live_send": False,
    }


def _bind_provider_attempt(
    args: argparse.Namespace,
    *,
    layout: Mapping[str, object],
    prepared_paths: Mapping[str, str],
) -> Mapping[str, object]:
    provider_id = _require_id(args.authorization_id, "authorization_id")
    action_id = _require_id(
        args.prepare_action_authorization_id,
        "prepare_action_authorization_id",
    )
    release_sha = _require_sha(args.expected_release_sha256, "release_sha256")
    run_id = _require_id(args.run_id, "run_id")
    attempt_id = _require_id(args.attempt_id, "attempt_id")
    control_root = Path(layout["control"])
    _require_reserved_provider_permit(
        control_root=control_root,
        authorization_id=provider_id,
        release_sha256=release_sha,
        run_id=run_id,
    )
    _require_reserved_prepare_permit(
        control_root=control_root,
        authorization_id=action_id,
        release_sha256=release_sha,
        run_id=run_id,
    )
    root = _ensure_directory(Path(prepared_paths["provider_attempts"]))
    authorization_root = root / provider_id
    if authorization_root.exists() or authorization_root.is_symlink():
        _ensure_directory(authorization_root)
    else:
        authorization_root.mkdir(mode=0o700)
        authorization_root.chmod(0o700)
        _fsync_directory(root)
    binding = {
        "schema_version": "provider-attempt-binding-v1",
        "provider_authorization_id": provider_id,
        "prepare_action_authorization_id": action_id,
        "release_sha256": release_sha,
        "run_id": run_id,
        "attempt_id": attempt_id,
    }
    path = authorization_root / "binding.json"
    if path.exists() or path.is_symlink():
        raise ReportControlError("provider_attempt_binding_exists")
    _write_new(path, _canonical(binding) + b"\n")
    return {
        "status": "bound",
        "provider_authorization_id": provider_id,
        "attempt_id": attempt_id,
    }


def _require_provider_attempt_evidence(
    *,
    control_root: Path,
    provider_attempt_root: Path,
    provider_authorization_id: str,
    prepare_action_authorization_id: str,
    release_sha256: str,
    run_id: str,
    attempt_id: str,
    manifest: Mapping[str, object],
    ledger_type: object,
    allow_empty_log: bool = False,
) -> None:
    permit = _require_reserved_provider_permit(
        control_root=control_root,
        authorization_id=provider_authorization_id,
        release_sha256=release_sha256,
        run_id=run_id,
    )
    authorization_root = provider_attempt_root / provider_authorization_id
    _ensure_directory(authorization_root)
    binding = _strict_json_bytes(
        _read_regular(
            authorization_root / "binding.json",
            reason="provider_attempt_binding_invalid",
        ),
        "provider_attempt_binding_invalid",
    )
    expected_binding = {
        "schema_version": "provider-attempt-binding-v1",
        "provider_authorization_id": provider_authorization_id,
        "prepare_action_authorization_id": prepare_action_authorization_id,
        "release_sha256": release_sha256,
        "run_id": run_id,
        "attempt_id": attempt_id,
    }
    if binding != expected_binding:
        raise ReportControlError("provider_attempt_binding_invalid")
    ledger_binding = manifest.get("provider_attempt_ledger")
    if not isinstance(ledger_binding, Mapping):
        raise ReportControlError("provider_attempt_ledger_invalid")
    runtime_release_sha = _require_sha(
        ledger_binding.get("release_sha256"),
        "provider_runtime_release_sha256",
    )
    ledger_path = (
        authorization_root
        / run_id
        / attempt_id
        / "provider-attempts-v2.jsonl"
    )
    try:
        ledger = ledger_type(
            path=ledger_path,
            authorization_id=provider_authorization_id,
            release_sha256=runtime_release_sha,
            run_id=run_id,
            attempt_id=attempt_id,
            clock=lambda: _now_text(),
        )
        snapshot = ledger.load()
        attempts = ledger_type._closed_attempt_documents(snapshot)
        ledger.verify_manifest_closure(manifest)
    except Exception as exc:
        raise ReportControlError("provider_attempt_ledger_invalid") from exc
    max_attempts = int(permit["max_attempts"])
    if (not attempts and not allow_empty_log) or len(attempts) > max_attempts:
        raise ReportControlError("provider_attempt_ledger_invalid")


def _require_commit_all_off(*, env_path: Path, gates_root: Path) -> None:
    payload = _read_regular(env_path, reason="runtime_secret_file_invalid")
    gates, _lines = _parse_env(payload)
    if gates != _ALL_OFF_GATES or _active_gate_journals(gates_root):
        raise ReportControlError("commit_requires_all_gates_off")


def _terminalize_failed_prepare_permit(
    *,
    control_root: Path,
    authorization_id: str,
    release_sha256: str,
) -> None:
    try:
        _transition_permit(
            root=control_root,
            authorization_id=authorization_id,
            expected_release_sha256=release_sha256,
            expected_run_id=None,
            target_status="blocked",
        )
    except Exception:
        try:
            _transition_permit(
                root=control_root,
                authorization_id=authorization_id,
                expected_release_sha256=release_sha256,
                expected_run_id=None,
                target_status="unknown",
            )
        except Exception:
            pass


def _commit_prepared_admin(
    args: argparse.Namespace,
    *,
    layout: Mapping[str, object],
    prepared_paths: Mapping[str, str],
) -> Mapping[str, object]:
    authorization_id = _require_id(args.authorization_id, "authorization_id")
    release_sha = _require_sha(args.expected_release_sha256, "release_sha256")
    run_id = _require_id(args.run_id, "run_id")
    attempt_id = _require_id(args.attempt_id, "attempt_id")
    commit_request_sha = _require_sha(
        args.expected_commit_request_sha256, "commit_request_sha256"
    )
    control_root = Path(layout["control"])
    prepare_permit = _require_reserved_prepare_permit(
        control_root=control_root,
        authorization_id=authorization_id,
        release_sha256=release_sha,
        run_id=run_id,
    )
    scheduled_prepare = (
        prepare_permit.get("schema_version")
        == "report-scheduled-cycle-prepare-permit-v1"
    )
    scheduled_latest: Mapping[str, object] | None = None
    if scheduled_prepare:
        cycle_id = _require_id(args.cycle_id, "cycle_id")
        lease_token = str(_read_cycle_lease(args, required=True))
        lease_sha = _sha256(lease_token.encode("ascii"))
        scheduled_latest = _latest_scheduled_cycle_event(
            _load_scheduled_cycle_ledger(control_root), cycle_id
        )
        if (
            scheduled_latest.get("event") != "prepare_reserved"
            or scheduled_latest.get("cycle_id") != prepare_permit.get("cycle_id")
            or scheduled_latest.get("report_date")
            != prepare_permit.get("report_date")
            or scheduled_latest.get("run_id") != run_id
            or scheduled_latest.get("release_sha256") != release_sha
            or scheduled_latest.get("launcher_sha256")
            != prepare_permit.get("launcher_sha256")
            or scheduled_latest.get("policy_sha256")
            != prepare_permit.get("policy_sha256")
            or scheduled_latest.get("policy_authorization_id")
            != prepare_permit.get("policy_authorization_id")
            or scheduled_latest.get("prepare_authorization_id")
            != authorization_id
            or scheduled_latest.get("cycle_lease_sha256") != lease_sha
            or prepare_permit.get("cycle_lease_sha256") != lease_sha
        ):
            raise ReportControlError("scheduled_prepare_commit_context_invalid")
    elif args.cycle_id is not None or args.cycle_lease_fd is not None:
        raise ReportControlError("scheduled_prepare_commit_context_invalid")
    _require_commit_all_off(
        env_path=Path(layout["env"]), gates_root=control_root / "gates"
    )
    runtime = _load_neutral_prepared_runtime(
        release_dir=Path(args.release_dir),
        expected_release_sha256=release_sha,
        config_root=Path(args.config_root),
    )
    roots = _prepared_roots(runtime, prepared_paths)
    provider_authorization_id = args.provider_authorization_id
    if provider_authorization_id is not None:
        _require_id(provider_authorization_id, "provider_authorization_id")
    try:
        if provider_authorization_id is not None:
            translation_manifest = _strict_json_bytes(
                _read_regular(
                    Path(prepared_paths["private_staging"])
                    / "translation-manifest.json",
                    reason="prepared_translation_manifest_invalid",
                ),
                "prepared_translation_manifest_invalid",
            )
            _require_provider_attempt_evidence(
                control_root=control_root,
                provider_attempt_root=Path(prepared_paths["provider_attempts"]),
                provider_authorization_id=provider_authorization_id,
                prepare_action_authorization_id=authorization_id,
                release_sha256=release_sha,
                run_id=run_id,
                attempt_id=attempt_id,
                manifest=translation_manifest,
                ledger_type=runtime["ProviderAttemptLedger"],
            )
        result = runtime["commit_staged_prepared_report"](
            roots=roots,
            expected_run_id=run_id,
            expected_artifact_version_id=args.expected_artifact_version_id,
            expected_bundle_sha256=args.expected_bundle_sha256,
            expected_outbox_sha256=args.expected_outbox_sha256,
            expected_commit_request_sha256=commit_request_sha,
            expected_provider_authorization_id=provider_authorization_id,
            expected_prepare_action_authorization_id=authorization_id,
            expected_attempt_id=attempt_id,
            schema_assets=runtime["schema_assets"],
        )
        verified = runtime["load_verified_prepared_report"](
            roots=roots,
            expected_run_id=run_id,
            expected_artifact_version_id=args.expected_artifact_version_id,
            expected_bundle_sha256=args.expected_bundle_sha256,
            expected_outbox_sha256=args.expected_outbox_sha256,
            schema_assets=runtime["schema_assets"],
        )
        if (
            result.run_id != run_id
            or result.attempt_id != attempt_id
            or result.artifact_version_id != args.expected_artifact_version_id
            or result.bundle_sha256 != args.expected_bundle_sha256
            or result.outbox_sha256 != args.expected_outbox_sha256
            or verified.run_id != run_id
            or verified.artifact_version_id != args.expected_artifact_version_id
            or verified.bundle_sha256 != args.expected_bundle_sha256
            or verified.outbox_sha256 != args.expected_outbox_sha256
        ):
            raise ReportControlError("prepared_commit_result_mismatch")
        commit_receipt: Mapping[str, object] | None = None
        if scheduled_prepare:
            if scheduled_latest is None:
                raise ReportControlError("scheduled_prepare_commit_context_invalid")
            commit_receipt = _write_scheduled_commit_receipt(
                control_root=control_root,
                prepare_permit=prepare_permit,
                latest=scheduled_latest,
                attempt_id=attempt_id,
                artifact_version_id=str(args.expected_artifact_version_id),
                bundle_sha256=str(args.expected_bundle_sha256),
                outbox_sha256=str(args.expected_outbox_sha256),
                commit_request_sha256=commit_request_sha,
                provider_authorization_id=provider_authorization_id,
            )
            scheduled_latest = _append_scheduled_cycle_event(
                control_root=control_root,
                event="prepare_committed",
                cycle_id=str(scheduled_latest["cycle_id"]),
                report_date=str(scheduled_latest["report_date"]),
                run_id=run_id,
                release_sha256=release_sha,
                launcher_sha256=str(scheduled_latest["launcher_sha256"]),
                policy_sha256=str(scheduled_latest["policy_sha256"]),
                policy_authorization_id=str(
                    scheduled_latest["policy_authorization_id"]
                ),
                prepare_authorization_id=authorization_id,
                cycle_lease_sha256=str(
                    scheduled_latest["cycle_lease_sha256"]
                ),
                prepare_attempt_id=attempt_id,
                artifact_version_id=str(args.expected_artifact_version_id),
                bundle_sha256=str(args.expected_bundle_sha256),
                outbox_sha256=str(args.expected_outbox_sha256),
                commit_request_sha256=commit_request_sha,
                commit_receipt_sha256=str(
                    commit_receipt["commit_receipt_sha256"]
                ),
            )
    except Exception:
        if (
            provider_authorization_id is not None
            and provider_authorization_id != authorization_id
        ):
            _terminalize_failed_prepare_permit(
                control_root=control_root,
                authorization_id=provider_authorization_id,
                release_sha256=release_sha,
            )
        _terminalize_failed_prepare_permit(
            control_root=control_root,
            authorization_id=authorization_id,
            release_sha256=release_sha,
        )
        raise
    if (
        provider_authorization_id is not None
        and provider_authorization_id != authorization_id
    ):
        _transition_permit(
            root=control_root,
            authorization_id=provider_authorization_id,
            expected_release_sha256=release_sha,
            expected_run_id=run_id,
            target_status="consumed",
        )
    _transition_permit(
        root=control_root,
        authorization_id=authorization_id,
        expected_release_sha256=release_sha,
        expected_run_id=run_id,
        target_status="consumed",
        scheduled_commit_receipt_sha256=(
            str(commit_receipt["commit_receipt_sha256"])
            if commit_receipt is not None
            else None
        ),
    )
    response = {
        "status": "committed",
        "run_id": result.run_id,
        "attempt_id": result.attempt_id,
        "artifact_version_id": result.artifact_version_id,
        "bundle_sha256": result.bundle_sha256,
        "outbox_sha256": result.outbox_sha256,
    }
    if commit_receipt is not None:
        response["commit_receipt_sha256"] = commit_receipt[
            "commit_receipt_sha256"
        ]
    return response


def _commit_blocked_admin(
    args: argparse.Namespace,
    *,
    layout: Mapping[str, object],
    prepared_paths: Mapping[str, str],
) -> Mapping[str, object]:
    authorization_id = _require_id(args.authorization_id, "authorization_id")
    release_sha = _require_sha(args.expected_release_sha256, "release_sha256")
    run_id = _require_id(args.run_id, "run_id")
    attempt_id = _require_id(args.attempt_id, "attempt_id")
    control_root = Path(layout["control"])
    _require_reserved_prepare_permit(
        control_root=control_root,
        authorization_id=authorization_id,
        release_sha256=release_sha,
        run_id=run_id,
    )
    _require_commit_all_off(
        env_path=Path(layout["env"]), gates_root=control_root / "gates"
    )
    runtime = _load_neutral_prepared_runtime(
        release_dir=Path(args.release_dir),
        expected_release_sha256=release_sha,
        config_root=Path(args.config_root),
    )
    roots = _prepared_roots(runtime, prepared_paths)
    provider_authorization_id = args.provider_authorization_id
    provider_attempt_made = False
    if provider_authorization_id is not None:
        _require_id(provider_authorization_id, "provider_authorization_id")
    try:
        if provider_authorization_id is not None:
            blocked_candidate = _strict_json_bytes(
                _read_regular(
                    Path(prepared_paths["handoff"])
                    / run_id
                    / attempt_id
                    / "blocked-manifest.json",
                    reason="blocked_handoff_invalid",
                ),
                "blocked_handoff_invalid",
            )
            provider_attempt_value = blocked_candidate.get(
                "translation_provider_attempt_made"
            )
            if (
                blocked_candidate.get("run_id") != run_id
                or blocked_candidate.get("attempt_id") != attempt_id
                or blocked_candidate.get("provider_authorization_id")
                != provider_authorization_id
                or not isinstance(provider_attempt_value, bool)
            ):
                raise ReportControlError("blocked_handoff_invalid")
            provider_attempt_made = provider_attempt_value
            _require_provider_attempt_evidence(
                control_root=control_root,
                provider_attempt_root=Path(prepared_paths["provider_attempts"]),
                provider_authorization_id=provider_authorization_id,
                prepare_action_authorization_id=authorization_id,
                release_sha256=release_sha,
                run_id=run_id,
                attempt_id=attempt_id,
                manifest=blocked_candidate,
                ledger_type=runtime["ProviderAttemptLedger"],
                allow_empty_log=not provider_attempt_made,
            )
        path = runtime["commit_staged_blocked_attempt"](
            roots=roots,
            expected_run_id=run_id,
            expected_attempt_id=attempt_id,
            expected_manifest_sha256=args.expected_blocked_manifest_sha256,
            expected_provider_authorization_id=provider_authorization_id,
            schema_assets=runtime["schema_assets"],
        )
    except Exception:
        if (
            provider_authorization_id is not None
            and provider_authorization_id != authorization_id
        ):
            _terminalize_failed_prepare_permit(
                control_root=control_root,
                authorization_id=provider_authorization_id,
                release_sha256=release_sha,
            )
        _terminalize_failed_prepare_permit(
            control_root=control_root,
            authorization_id=authorization_id,
            release_sha256=release_sha,
        )
        raise
    if (
        provider_authorization_id is not None
        and provider_authorization_id != authorization_id
    ):
        _transition_permit(
            root=control_root,
            authorization_id=provider_authorization_id,
            expected_release_sha256=release_sha,
            expected_run_id=run_id,
            target_status=(
                "blocked" if provider_attempt_made else "closed_no_attempt"
            ),
        )
    action_terminal_status = (
        "closed_no_attempt"
        if provider_authorization_id == authorization_id
        and not provider_attempt_made
        else "blocked"
    )
    _transition_permit(
        root=control_root,
        authorization_id=authorization_id,
        expected_release_sha256=release_sha,
        expected_run_id=run_id,
        target_status=action_terminal_status,
    )
    return {
        "status": "blocked_committed",
        "run_id": run_id,
        "attempt_id": attempt_id,
        "blocked_manifest": str(path),
    }


def _recover_prepared_admin(
    args: argparse.Namespace, *, prepared_paths: Mapping[str, str]
) -> Mapping[str, object]:
    release_sha = _require_sha(args.expected_release_sha256, "release_sha256")
    runtime = _load_neutral_prepared_runtime(
        release_dir=Path(args.release_dir),
        expected_release_sha256=release_sha,
        config_root=Path(args.config_root),
    )
    roots = _prepared_roots(runtime, prepared_paths)
    runtime["recover_projection_journal"](roots=roots)
    return {"status": "recovered", "projection_journal": "clean"}


def _project_delivery_ledgers_admin(
    args: argparse.Namespace, *, prepared_paths: Mapping[str, str]
) -> Mapping[str, object]:
    release_sha = _require_sha(args.expected_release_sha256, "release_sha256")
    database = Path(args.database) if args.database is not None else None
    if database is None:
        raise ReportControlError("delivery_database_missing")
    if (
        os.getenv("REDDIT_VOC_LOCAL_TEST_MODE") != "1"
        and database != Path("/opt/reddit-voc-site/data/reddit_voc_daily.sqlite3")
    ):
        raise ReportControlError("production_delivery_database_path_invalid")
    runtime = _load_neutral_prepared_runtime(
        release_dir=Path(args.release_dir),
        expected_release_sha256=release_sha,
        config_root=Path(args.config_root),
    )
    roots = _prepared_roots(runtime, prepared_paths)
    plan_arguments = {
        "run_id": _require_id(args.run_id, "run_id"),
        "expected_artifact_version_id": _require_id(
            args.expected_artifact_version_id, "artifact_version_id"
        ),
        "expected_bundle_sha256": _require_sha(
            args.expected_bundle_sha256, "bundle_sha256"
        ),
        "expected_outbox_sha256": _require_sha(
            args.expected_outbox_sha256, "outbox_sha256"
        ),
        "authorization_id": _require_id(
            args.authorization_id, "authorization_id"
        ),
        "roots": roots,
        "config_root": Path(args.config_root),
    }
    try:
        if os.geteuid() == 0:
            with _temporary_effective_uid(1000):
                plan = runtime[
                    "build_delivery_projection_plan_from_ledgers"
                ](**plan_arguments)
        else:
            plan = runtime[
                "build_delivery_projection_plan_from_ledgers"
            ](**plan_arguments)
        if (
            os.getenv("REDDIT_VOC_LOCAL_TEST_MODE") != "1"
            and os.geteuid() == 1000
        ):
            payload = runtime["serialize_delivery_projection_plan"](plan)
            return _apply_delivery_projection_plan_via_sudo(
                args=args, release_sha=release_sha, payload=payload
            )
        summary = runtime["apply_delivery_projection_plan"](
            database=database, plan=plan
        )
    except Exception as exc:
        reason = str(exc)
        if _SAFE_ID.fullmatch(reason) is None:
            reason = "delivery_projection_failed"
        raise ReportControlError(reason) from exc
    return {"status": "projected", **summary.as_dict()}


def _apply_delivery_projection_plan_via_sudo(
    *, args: argparse.Namespace, release_sha: str, payload: bytes
) -> Mapping[str, object]:
    if os.getuid() != 1000 or os.geteuid() != 1000:
        raise ReportControlError("delivery_projection_identity_invalid")
    if not isinstance(payload, bytes) or not payload or len(payload) > 256 * 1024:
        raise ReportControlError("delivery_projection_plan_invalid")
    release = Path(args.release_dir)
    command = [
        "/usr/bin/sudo",
        "-n",
        "/usr/bin/python3",
        str(release / "scripts/report_control.py"),
        "admin",
        "apply-delivery-projection-plan",
        "--expected-release-sha256",
        release_sha,
        "--expected-plan-sha256",
        hashlib.sha256(payload).hexdigest(),
        "--authorization-id",
        str(args.authorization_id),
        "--run-id",
        str(args.run_id),
        "--expected-artifact-version-id",
        str(args.expected_artifact_version_id),
        "--expected-bundle-sha256",
        str(args.expected_bundle_sha256),
        "--expected-outbox-sha256",
        str(args.expected_outbox_sha256),
        "--release-dir",
        str(release),
        "--config-root",
        str(args.config_root),
        "--database",
        str(args.database),
    ]
    try:
        completed = subprocess.run(
            command,
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
            env={
                "PATH": "/usr/bin:/bin",
                "HOME": "/root",
                "LANG": "C.UTF-8",
            },
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ReportControlError("delivery_projection_root_apply_failed") from exc
    if completed.returncode != 0:
        raise ReportControlError("delivery_projection_root_apply_failed")
    try:
        text = completed.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReportControlError("delivery_projection_root_result_invalid") from exc
    pairs: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            raise ReportControlError("delivery_projection_root_result_invalid")
        key, value = line.split("=", 1)
        if key in pairs:
            raise ReportControlError("delivery_projection_root_result_invalid")
        pairs[key] = value
    expected_keys = {
        "status",
        "run_id",
        "artifact_version_id",
        "outbox_sha256",
        "expected_count",
        "inserted_count",
        "existing_count",
        "fully_projected",
        "primary_ledger_tip",
        "secondary_ledger_tip",
        "provider_call",
        "live_send",
    }
    if set(pairs) != expected_keys:
        raise ReportControlError("delivery_projection_root_result_invalid")
    counts = []
    for key in ("expected_count", "inserted_count", "existing_count"):
        value = pairs[key]
        if re.fullmatch(r"0|[1-9][0-9]*", value) is None:
            raise ReportControlError("delivery_projection_root_result_invalid")
        counts.append(int(value))
    if (
        pairs["status"] != "projected"
        or pairs["run_id"] != args.run_id
        or pairs["artifact_version_id"] != args.expected_artifact_version_id
        or pairs["outbox_sha256"] != args.expected_outbox_sha256
        or counts[0] < 1
        or counts[1] + counts[2] != counts[0]
        or pairs["fully_projected"] != "True"
        or _SHA256.fullmatch(pairs["primary_ledger_tip"]) is None
        or _SHA256.fullmatch(pairs["secondary_ledger_tip"]) is None
        or pairs["provider_call"] != "false"
        or pairs["live_send"] != "false"
    ):
        raise ReportControlError("delivery_projection_root_result_invalid")
    return {
        "status": "projected",
        "run_id": pairs["run_id"],
        "artifact_version_id": pairs["artifact_version_id"],
        "outbox_sha256": pairs["outbox_sha256"],
        "expected_count": counts[0],
        "inserted_count": counts[1],
        "existing_count": counts[2],
        "fully_projected": True,
        "primary_ledger_tip": pairs["primary_ledger_tip"],
        "secondary_ledger_tip": pairs["secondary_ledger_tip"],
    }


def _apply_delivery_projection_plan_admin(
    args: argparse.Namespace,
) -> Mapping[str, object]:
    if (
        os.getenv("REDDIT_VOC_LOCAL_TEST_MODE") == "1"
        or os.getuid() != 0
        or os.geteuid() != 0
    ):
        raise ReportControlError("delivery_projection_identity_invalid")
    release_sha = _require_sha(args.expected_release_sha256, "release_sha256")
    plan_sha = _require_sha(args.expected_plan_sha256, "plan_sha256")
    release = Path(args.release_dir)
    if release != Path("/opt/reddit-voc-daily-report/releases") / release_sha:
        raise ReportControlError("release_path_mismatch")
    config_root = Path(args.config_root)
    if config_root != release / "config":
        raise ReportControlError("config_root_mismatch")
    database = Path(args.database)
    if database != Path("/opt/reddit-voc-site/data/reddit_voc_daily.sqlite3"):
        raise ReportControlError("production_delivery_database_path_invalid")
    payload = sys.stdin.buffer.read(256 * 1024 + 1)
    if not payload or len(payload) > 256 * 1024:
        raise ReportControlError("delivery_projection_plan_invalid")
    if hashlib.sha256(payload).hexdigest() != plan_sha:
        raise ReportControlError("delivery_projection_plan_sha_mismatch")
    runtime = _load_neutral_prepared_runtime(
        release_dir=release,
        expected_release_sha256=release_sha,
        config_root=config_root,
    )
    try:
        supplied_plan = runtime["deserialize_delivery_projection_plan"](payload)
        _layout, prepared_paths = _prepared_admin_layout(args)
        roots = _prepared_roots(runtime, prepared_paths)
        expected_run_id = _require_id(args.run_id, "run_id")
        expected_artifact_version_id = _require_id(
            args.expected_artifact_version_id, "artifact_version_id"
        )
        expected_bundle_sha256 = _require_sha(
            args.expected_bundle_sha256, "bundle_sha256"
        )
        expected_outbox_sha256 = _require_sha(
            args.expected_outbox_sha256, "outbox_sha256"
        )
        with _temporary_effective_uid(1000):
            verified_plan = runtime[
                "build_delivery_projection_plan_from_ledgers"
            ](
                run_id=expected_run_id,
                expected_artifact_version_id=expected_artifact_version_id,
                expected_bundle_sha256=expected_bundle_sha256,
                expected_outbox_sha256=expected_outbox_sha256,
                authorization_id=_require_id(
                    args.authorization_id, "authorization_id"
                ),
                roots=roots,
                config_root=config_root,
            )
        if (
            supplied_plan != verified_plan
            or runtime["serialize_delivery_projection_plan"](verified_plan)
            != payload
        ):
            raise ReportControlError("delivery_projection_plan_identity_mismatch")
        summary = runtime["apply_delivery_projection_plan"](
            database=database, plan=verified_plan
        )
    except ReportControlError:
        raise
    except Exception as exc:
        reason = str(exc)
        if _SAFE_ID.fullmatch(reason) is None:
            reason = "delivery_projection_failed"
        raise ReportControlError(reason) from exc
    return {"status": "projected", **summary.as_dict()}


@contextmanager
def _temporary_effective_uid(uid: int) -> Iterator[None]:
    if os.getuid() != 0 or os.geteuid() != 0 or uid != 1000:
        raise ReportControlError("delivery_projection_identity_invalid")
    os.seteuid(uid)
    try:
        yield
    finally:
        os.seteuid(0)


def _mapped_host_path(host_root: Path | None, absolute: str) -> Path:
    path = Path(absolute)
    if not path.is_absolute():
        raise ReportControlError("host_path_invalid")
    if host_root is None:
        return path
    return host_root / path.relative_to("/")


def _host_admin_layout(args: argparse.Namespace) -> Mapping[str, Path]:
    host_root: Path | None = None
    if args.host_root is not None:
        if os.getenv("REDDIT_VOC_LOCAL_TEST_MODE") != "1":
            raise ReportControlError("host_root_override_forbidden")
        host_root = Path(args.host_root).resolve(strict=True)
        metadata = host_root.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid()
        ):
            raise ReportControlError("host_root_invalid")
    return {
        "host_root": host_root or Path("/"),
        "lock": _mapped_host_path(
            host_root,
            "/opt/reddit-voc-daily-report/control/locks/daily-report.lock",
        ),
        "control": _mapped_host_path(
            host_root, "/home/ubuntu/.reddit-voc/report-control"
        ),
        "env": _mapped_host_path(
            host_root,
            "/home/ubuntu/.reddit-voc/secrets/reddit-voc-report.env",
        ),
        "releases": _mapped_host_path(
            host_root, "/opt/reddit-voc-daily-report/releases"
        ),
        "current": _mapped_host_path(
            host_root, "/opt/reddit-voc-daily-report/current"
        ),
        "launcher": _mapped_host_path(
            host_root, "/opt/reddit-voc-site/scripts/server_daily_report.sh"
        ),
        "cron": _mapped_host_path(host_root, "/etc/cron.d/reddit-voc-site"),
    }


def _read_host_regular(
    path: Path,
    *,
    allowed_modes: frozenset[int],
    allowed_uids: frozenset[int] | None = None,
    reason: str,
) -> bytes:
    if allowed_uids is None:
        allowed_uids = frozenset({os.getuid()})
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ReportControlError(reason) from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid not in allowed_uids
        or stat.S_IMODE(metadata.st_mode) not in allowed_modes
    ):
        raise ReportControlError(reason)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 65_536)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _atomic_install_host_file(path: Path, payload: bytes, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
    try:
        _write_new(temporary, payload, mode=mode)
        os.replace(temporary, path)
        os.chmod(path, mode)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists() and not temporary.is_symlink():
            temporary.unlink()


def _atomic_switch_release(current: Path, release: Path) -> None:
    current.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = current.parent / f".{current.name}.{secrets.token_hex(8)}.tmp"
    try:
        os.symlink(str(release), temporary)
        os.replace(temporary, current)
        _fsync_directory(current.parent)
    finally:
        if temporary.is_symlink():
            temporary.unlink()


def _current_release(
    *, current: Path, releases: Path, expected_sha256: str
) -> Path:
    _require_sha(expected_sha256, "current_release_sha256")
    try:
        metadata = current.lstat()
    except FileNotFoundError as exc:
        raise ReportControlError("current_release_missing") from exc
    if not stat.S_ISLNK(metadata.st_mode):
        raise ReportControlError("current_release_pointer_invalid")
    resolved = current.resolve(strict=True)
    canonical_releases = releases.resolve(strict=True)
    if resolved.parent != canonical_releases or resolved.name != expected_sha256:
        raise ReportControlError("current_release_mismatch")
    if resolved.is_symlink() or not resolved.is_dir():
        raise ReportControlError("current_release_invalid")
    return resolved


def _verify_host_release(
    *, release: Path, releases: Path, expected_release_sha256: str
) -> bytes:
    release_sha = _require_sha(expected_release_sha256, "release_sha256")
    canonical_releases = releases.resolve(strict=True)
    canonical_release = release.resolve(strict=True)
    if (
        canonical_release.parent != canonical_releases
        or canonical_release.name != release_sha
        or release.is_symlink()
        or not release.is_dir()
    ):
        raise ReportControlError("release_path_invalid")
    builder = canonical_release / "scripts/build_daily_report_release.py"
    launcher = canonical_release / "scripts/server_daily_report.sh"
    environment = {
        **os.environ,
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": str(canonical_release / "src"),
    }
    verified = subprocess.run(
        [
            sys.executable,
            str(builder),
            "verify",
            "--release-dir",
            str(canonical_release),
        ],
        env=environment,
        cwd=canonical_release,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if verified.returncode != 0:
        raise ReportControlError("release_verification_failed")
    return _read_host_regular(
        launcher,
        allowed_modes=frozenset({0o755}),
        reason="release_launcher_invalid",
    )


def _assert_maintenance_window(args: argparse.Namespace) -> str:
    maintenance_id = _require_id(args.maintenance_window_id, "maintenance_window_id")
    if args.allow_local_maintenance_window:
        if os.getenv("REDDIT_VOC_LOCAL_TEST_MODE") != "1":
            raise ReportControlError("local_maintenance_override_forbidden")
        return maintenance_id
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    if now.hour == 8 or (now.hour == 7 and now.minute >= 45):
        raise ReportControlError("maintenance_window_conflicts_with_report")
    return maintenance_id


def _assert_no_report_processes(args: argparse.Namespace) -> None:
    if args.allow_local_maintenance_window:
        return
    proc = Path("/proc")
    if not proc.is_dir():
        raise ReportControlError("process_inspection_unavailable")
    forbidden = {"server_daily_report.sh", "run_daily_report.sh"}
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name) in {os.getpid(), os.getppid()}:
            continue
        try:
            values = entry.joinpath("cmdline").read_bytes().split(b"\0")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        basenames = {Path(value.decode("utf-8", "ignore")).name for value in values if value}
        if basenames & forbidden:
            raise ReportControlError("report_process_active")


def _run_host_text(command: Sequence[str], *, reason: str) -> str:
    completed = subprocess.run(
        list(command),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
        env={**os.environ, "PYTHONNOUSERSITE": "1"},
    )
    if completed.returncode != 0:
        raise ReportControlError(reason)
    return completed.stdout.strip()


def _validate_report_network(args: argparse.Namespace, *, create: bool) -> None:
    if args.docker_bin is not None and os.getenv("REDDIT_VOC_LOCAL_TEST_MODE") != "1":
        raise ReportControlError("docker_bin_override_forbidden")
    docker = str(args.docker_bin or "docker")
    base = [docker, "network", "inspect", "reddit_voc_report_net", "--format"]
    try:
        driver = _run_host_text([*base, "{{.Driver}}"], reason="report_network_missing")
    except ReportControlError:
        if not create:
            raise
        created = subprocess.run(
            [docker, "network", "create", "--driver", "bridge", "reddit_voc_report_net"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if created.returncode != 0:
            raise ReportControlError("report_network_create_failed")
        driver = _run_host_text([*base, "{{.Driver}}"], reason="report_network_invalid")
    members = _run_host_text(
        [*base, "{{len .Containers}}"], reason="report_network_invalid"
    )
    internal = _run_host_text(
        [*base, "{{.Internal}}"], reason="report_network_invalid"
    )
    if driver != "bridge" or members != "0" or internal != "false":
        raise ReportControlError("report_network_invalid")


def _require_admin_action_permit(
    *,
    control_root: Path,
    authorization_id: str,
    action: str,
    release_sha256: str,
    launcher_sha256: str | None,
) -> None:
    permit, state, _state_path = _load_permit_state(
        root=control_root, authorization_id=authorization_id
    )
    expiry = permit.get("expires_at")
    if (
        permit.get("schema_version") != "report-admin-permit-v1"
        or permit.get("action") != action
        or permit.get("release_sha256") != release_sha256
        or permit.get("expected_launcher_sha256") != launcher_sha256
        or state.get("status") != "installed"
        or not isinstance(expiry, str)
        or not _expiry_is_future(expiry)
    ):
        raise ReportControlError("admin_permit_invalid")
    _transition_permit(
        root=control_root,
        authorization_id=authorization_id,
        expected_release_sha256=release_sha256,
        expected_run_id=None,
        target_status="reserved",
    )


def _validate_smoke_output(output: str) -> None:
    values: dict[str, str] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    required = {
        "provider_call": "false",
        "translation_provider_attempt_made": "false",
        "report_live_send": "false",
        "live_send": "false",
    }
    if any(values.get(key) != value for key, value in required.items()):
        raise ReportControlError("report_smoke_boundary_invalid")
    if values.get("runtime_smoke") not in {"passed", None} and values.get("status") != "complete":
        raise ReportControlError("report_smoke_failed")


def _run_admin_smoke(
    args: argparse.Namespace,
    *,
    layout: Mapping[str, Path],
    launcher: Path,
    inherited_lock_fd: int | None = None,
) -> None:
    if args.local_smoke_command is not None:
        if os.getenv("REDDIT_VOC_LOCAL_TEST_MODE") != "1":
            raise ReportControlError("local_smoke_override_forbidden")
        command = [str(args.local_smoke_command)]
        environment = {**os.environ, "PYTHONNOUSERSITE": "1"}
    else:
        command = [str(launcher), "smoke", "--authorize-host-launch"]
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        environment = {
            **os.environ,
            "PYTHONNOUSERSITE": "1",
            "REDDIT_VOC_ENABLE_HOST_LAUNCH": "1",
            "REDDIT_VOC_RUN_ID": f"admin_smoke_{now:%Y%m%d_%H%M%S}",
            "REDDIT_VOC_INHERITED_LOCK_FD": str(inherited_lock_fd)
            if inherited_lock_fd is not None
            else "",
        }
    completed = subprocess.run(
        command,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
        pass_fds=(inherited_lock_fd,) if inherited_lock_fd is not None else (),
    )
    if completed.returncode != 0:
        raise ReportControlError("report_smoke_failed")
    _validate_smoke_output(completed.stdout)


def _activate_report_release(
    args: argparse.Namespace,
    *,
    layout: Mapping[str, Path],
    action: str,
    inherited_lock_fd: int | None = None,
) -> Mapping[str, object]:
    if action not in {"bootstrap", "activate"}:
        raise ReportControlError("admin_action_invalid")
    authorized = args.authorize_bootstrap if action == "bootstrap" else args.authorize_activate
    if not authorized:
        raise ReportControlError(f"{action}_not_authorized")
    maintenance_id = _assert_maintenance_window(args)
    authorization_id = _require_id(args.authorization_id, "authorization_id")
    release_sha = _require_sha(args.expected_release_sha256, "release_sha256")
    launcher_sha = _require_sha(args.expected_launcher_sha256, "launcher_sha256")
    old_launcher_sha = _require_sha(
        args.expected_old_launcher_sha256, "old_launcher_sha256"
    )
    current_value = args.expected_current_release_sha256
    if action == "bootstrap" and current_value == "absent":
        current_sha: str | None = None
    else:
        current_sha = _require_sha(current_value, "current_release_sha256")
    cron_sha = _require_sha(args.expected_cron_sha256, "cron_sha256")
    control_root = _ensure_directory(layout["control"], create=True)
    _require_admin_action_permit(
        control_root=control_root,
        authorization_id=authorization_id,
        action=action,
        release_sha256=release_sha,
        launcher_sha256=launcher_sha,
    )
    reserved = True
    freeze = control_root / "report.freeze"
    try:
        _assert_no_report_processes(args)
        if freeze.exists() or freeze.is_symlink():
            raise ReportControlError("report_freeze_exists")
        freeze_document = {
            "schema_version": "report-freeze-v1",
            "authorization_id": authorization_id,
            "maintenance_window_id": maintenance_id,
            "action": action,
            "release_sha256": release_sha,
            "created_at": _now_text(),
        }
        _write_new(freeze, _canonical(freeze_document) + b"\n")
        _assert_no_report_processes(args)
        env_payload = _read_regular(layout["env"], reason="runtime_secret_file_invalid")
        gates, _lines = _parse_env(env_payload)
        if gates != _ALL_OFF_GATES or _active_gate_journals(control_root / "gates"):
            raise ReportControlError("admin_action_requires_all_gates_off")
        cron_payload = _read_host_regular(
            layout["cron"],
            allowed_modes=frozenset({0o600, 0o644}),
            allowed_uids=frozenset({os.getuid(), 0}),
            reason="cron_file_invalid",
        )
        if _sha256(cron_payload) != cron_sha:
            raise ReportControlError("cron_sha256_mismatch")
        if current_sha is None:
            if layout["current"].exists() or layout["current"].is_symlink():
                raise ReportControlError("current_release_expected_absent")
            previous_release_sha: str | None = None
        else:
            previous_release_sha = _current_release(
                current=layout["current"],
                releases=layout["releases"],
                expected_sha256=current_sha,
            ).name
        old_launcher = _read_host_regular(
            layout["launcher"],
            allowed_modes=frozenset({0o755}),
            reason="old_launcher_invalid",
        )
        if _sha256(old_launcher) != old_launcher_sha:
            raise ReportControlError("old_launcher_sha256_mismatch")
        release = layout["releases"] / release_sha
        new_launcher = _verify_host_release(
            release=release,
            releases=layout["releases"],
            expected_release_sha256=release_sha,
        )
        if _sha256(new_launcher) != launcher_sha:
            raise ReportControlError("new_launcher_sha256_mismatch")
        backup_root = control_root / "backups"
        _ensure_directory(backup_root, create=True)
        backup = backup_root / authorization_id
        if backup.exists() or backup.is_symlink():
            raise ReportControlError("admin_backup_exists")
        backup.mkdir(mode=0o700)
        backup.chmod(0o700)
        _atomic_install_host_file(backup / "launcher", old_launcher, mode=0o600)
        if action == "bootstrap":
            _atomic_install_host_file(backup / "report-env", env_payload, mode=0o600)
        _atomic_install_host_file(layout["launcher"], new_launcher, mode=0o755)
        _atomic_switch_release(layout["current"], release)
        _validate_report_network(args, create=action == "bootstrap")
        _run_admin_smoke(
            args,
            layout=layout,
            launcher=layout["launcher"],
            inherited_lock_fd=inherited_lock_fd,
        )
        if _sha256(
            _read_host_regular(
                layout["cron"],
                allowed_modes=frozenset({0o600, 0o644}),
                allowed_uids=frozenset({os.getuid(), 0}),
                reason="cron_file_invalid",
            )
        ) != cron_sha:
            raise ReportControlError("cron_changed")
        _current_release(
            current=layout["current"],
            releases=layout["releases"],
            expected_sha256=release_sha,
        )
        installed_launcher = _read_host_regular(
            layout["launcher"],
            allowed_modes=frozenset({0o755}),
            reason="installed_launcher_invalid",
        )
        if _sha256(installed_launcher) != launcher_sha:
            raise ReportControlError("installed_launcher_sha256_mismatch")
        action_root = control_root / "admin-actions"
        _ensure_directory(action_root, create=True)
        action_record = {
            "schema_version": "report-admin-action-v1",
            "authorization_id": authorization_id,
            "action": action,
            "maintenance_window_id": maintenance_id,
            "previous_release_sha256": previous_release_sha,
            "release_sha256": release_sha,
            "old_launcher_sha256": old_launcher_sha,
            "launcher_sha256": launcher_sha,
            "cron_sha256": cron_sha,
            "status": "complete",
            "completed_at": _now_text(),
        }
        _write_new(
            action_root / f"{authorization_id}.json",
            _canonical(action_record) + b"\n",
        )
        freeze.unlink()
        _fsync_directory(freeze.parent)
        _transition_permit(
            root=control_root,
            authorization_id=authorization_id,
            expected_release_sha256=release_sha,
            expected_run_id=None,
            target_status="consumed",
        )
        reserved = False
        return {
            "status": "activated",
            "action": action,
            "release_sha256": release_sha,
            "launcher_sha256": launcher_sha,
            "cron_changed": False,
            "service_restarted": False,
        }
    except Exception:
        if reserved:
            _terminalize_failed_prepare_permit(
                control_root=control_root,
                authorization_id=authorization_id,
                release_sha256=release_sha,
            )
        raise


def _revoke_side_effect_permits(
    *, control_root: Path, skip_authorization_id: str
) -> tuple[str, ...]:
    layout = _control_layout(control_root)
    revoked: list[str] = []
    for permit_path in sorted(layout["permits"].glob("*.json")):
        permit = _strict_json_bytes(
            _read_regular(permit_path, reason="permit_invalid"), "permit_invalid"
        )
        schema = permit.get("schema_version")
        authorization_id = permit.get("authorization_id")
        if (
            schema
            not in {
                "report-prepare-permit-v1",
                "report-send-permit-v1",
                "report-schedule-permit-v1",
                "report-shadow-permit-v1",
            }
            or not isinstance(authorization_id, str)
            or authorization_id == skip_authorization_id
        ):
            continue
        _permit, state, _state_path = _load_permit_state(
            root=control_root, authorization_id=authorization_id
        )
        if state.get("status") not in {"installed", "reserved"}:
            continue
        _transition_permit(
            root=control_root,
            authorization_id=authorization_id,
            expected_release_sha256=str(permit["release_sha256"]),
            expected_run_id=None,
            target_status="revoked",
        )
        revoked.append(authorization_id)
    return tuple(revoked)


def _rollback_report_release(
    args: argparse.Namespace,
    *,
    layout: Mapping[str, Path],
    inherited_lock_fd: int | None = None,
) -> Mapping[str, object]:
    if not args.authorize_rollback:
        raise ReportControlError("rollback_not_authorized")
    maintenance_id = _assert_maintenance_window(args)
    authorization_id = _require_id(args.authorization_id, "authorization_id")
    target_release_sha = _require_sha(
        args.expected_release_sha256, "release_sha256"
    )
    current_release_sha = _require_sha(
        args.expected_current_release_sha256, "current_release_sha256"
    )
    launcher_sha = _require_sha(args.expected_launcher_sha256, "launcher_sha256")
    cron_sha = _require_sha(args.expected_cron_sha256, "cron_sha256")
    control_root = _ensure_directory(layout["control"], create=True)
    snapshots = layout["env"].parent / "report-env-snapshots"
    _recover_gates(
        {
            "gates": control_root / "gates",
            "env": layout["env"],
            "snapshots": snapshots,
        }
    )
    _require_admin_action_permit(
        control_root=control_root,
        authorization_id=authorization_id,
        action="rollback",
        release_sha256=target_release_sha,
        launcher_sha256=None,
    )
    reserved = True
    freeze = control_root / "report.freeze"
    try:
        _assert_no_report_processes(args)
        if freeze.exists() or freeze.is_symlink():
            raise ReportControlError("report_freeze_exists")
        _write_new(
            freeze,
            _canonical(
                {
                    "schema_version": "report-freeze-v1",
                    "authorization_id": authorization_id,
                    "maintenance_window_id": maintenance_id,
                    "action": "rollback",
                    "release_sha256": target_release_sha,
                    "created_at": _now_text(),
                }
            )
            + b"\n",
        )
        _assert_no_report_processes(args)
        current_release = _current_release(
            current=layout["current"],
            releases=layout["releases"],
            expected_sha256=current_release_sha,
        )
        installed_launcher = _read_host_regular(
            layout["launcher"],
            allowed_modes=frozenset({0o755}),
            reason="installed_launcher_invalid",
        )
        if _sha256(installed_launcher) != launcher_sha:
            raise ReportControlError("installed_launcher_sha256_mismatch")
        target_release = layout["releases"] / target_release_sha
        target_launcher = _verify_host_release(
            release=target_release,
            releases=layout["releases"],
            expected_release_sha256=target_release_sha,
        )
        if _sha256(target_launcher) != launcher_sha:
            raise ReportControlError("rollback_launcher_incompatible")
        cron_payload = _read_host_regular(
            layout["cron"],
            allowed_modes=frozenset({0o600, 0o644}),
            allowed_uids=frozenset({os.getuid(), 0}),
            reason="cron_file_invalid",
        )
        if _sha256(cron_payload) != cron_sha:
            raise ReportControlError("cron_sha256_mismatch")
        revoked = _revoke_side_effect_permits(
            control_root=control_root,
            skip_authorization_id=authorization_id,
        )
        _atomic_switch_release(layout["current"], target_release)
        _validate_report_network(args, create=False)
        _run_admin_smoke(
            args,
            layout=layout,
            launcher=layout["launcher"],
            inherited_lock_fd=inherited_lock_fd,
        )
        _current_release(
            current=layout["current"],
            releases=layout["releases"],
            expected_sha256=target_release_sha,
        )
        if _sha256(
            _read_host_regular(
                layout["cron"],
                allowed_modes=frozenset({0o600, 0o644}),
                allowed_uids=frozenset({os.getuid(), 0}),
                reason="cron_file_invalid",
            )
        ) != cron_sha:
            raise ReportControlError("cron_changed")
        action_root = control_root / "admin-actions"
        _ensure_directory(action_root, create=True)
        _write_new(
            action_root / f"{authorization_id}.json",
            _canonical(
                {
                    "schema_version": "report-admin-action-v1",
                    "authorization_id": authorization_id,
                    "action": "rollback",
                    "maintenance_window_id": maintenance_id,
                    "previous_release_sha256": current_release.name,
                    "release_sha256": target_release_sha,
                    "launcher_sha256": launcher_sha,
                    "cron_sha256": cron_sha,
                    "revoked_authorization_ids": list(revoked),
                    "status": "complete",
                    "completed_at": _now_text(),
                }
            )
            + b"\n",
        )
        freeze.unlink()
        _fsync_directory(freeze.parent)
        _transition_permit(
            root=control_root,
            authorization_id=authorization_id,
            expected_release_sha256=target_release_sha,
            expected_run_id=None,
            target_status="consumed",
        )
        reserved = False
        return {
            "status": "rolled_back",
            "release_sha256": target_release_sha,
            "launcher_sha256": launcher_sha,
            "revoked_permit_count": len(revoked),
            "cron_changed": False,
            "service_restarted": False,
        }
    except Exception:
        if reserved:
            _terminalize_failed_prepare_permit(
                control_root=control_root,
                authorization_id=authorization_id,
                release_sha256=target_release_sha,
            )
        raise


def _admin_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("command")
    parser.add_argument("--control-root", type=Path)
    parser.add_argument("--shadow-root", type=Path)
    parser.add_argument("--authorization-id")
    parser.add_argument("--expected-release-sha256")
    parser.add_argument("--candidate-sha256")
    parser.add_argument("--copied-database-sha256")
    parser.add_argument("--run-id")
    parser.add_argument("--max-attempts", type=int)
    parser.add_argument("--expires-at")
    parser.add_argument("--expected-artifact-version-id")
    parser.add_argument("--expected-bundle-sha256")
    parser.add_argument("--expected-outbox-sha256")
    parser.add_argument("--expected-launcher-sha256")
    parser.add_argument("--expected-stable-entrypoint-sha256")
    parser.add_argument("--expected-release-launcher-sha256")
    parser.add_argument("--expected-policy-sha256")
    parser.add_argument("--expected-parent-policy-sha256")
    parser.add_argument("--expected-credential-rotation-receipt-sha256")
    parser.add_argument("--expected-credential-set-receipt-sha256")
    parser.add_argument("--expected-old-launcher-sha256")
    parser.add_argument("--expected-current-release-sha256")
    parser.add_argument("--expected-cron-sha256")
    parser.add_argument("--release-dir", type=Path)
    parser.add_argument("--config-root", type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--attempt-id")
    parser.add_argument("--expected-commit-request-sha256")
    parser.add_argument("--expected-blocked-manifest-sha256")
    parser.add_argument("--provider-authorization-id")
    parser.add_argument("--prepare-action-authorization-id")
    parser.add_argument("--public-root", type=Path)
    parser.add_argument("--private-root", type=Path)
    parser.add_argument("--public-staging-root", type=Path)
    parser.add_argument("--private-staging-root", type=Path)
    parser.add_argument("--state-root", type=Path)
    parser.add_argument("--blocked-root", type=Path)
    parser.add_argument("--handoff-root", type=Path)
    parser.add_argument("--inherited-lock-fd", type=int)
    parser.add_argument("--host-root", type=Path)
    parser.add_argument("--maintenance-window-id")
    parser.add_argument("--docker-bin", type=Path)
    parser.add_argument("--local-smoke-command", type=Path)
    parser.add_argument("--action")
    parser.add_argument("--max-slots", type=int)
    parser.add_argument("--credential-epoch-id")
    parser.add_argument("--destination-alias")
    parser.add_argument("--credential-set-epoch-id")
    parser.add_argument("--destination-set-id")
    parser.add_argument("--scheduled-at")
    parser.add_argument("--policy-file", type=Path)
    parser.add_argument("--parent-policy-file", type=Path)
    parser.add_argument("--credential-rotation-receipt-file", type=Path)
    parser.add_argument("--report-env-install-receipt-file", type=Path)
    parser.add_argument("--dual-credential-set-receipt-file", type=Path)
    parser.add_argument("--dual-report-env-install-receipt-file", type=Path)
    parser.add_argument("--report-env-file", type=Path)
    parser.add_argument("--stable-entrypoint-file", type=Path)
    parser.add_argument("--owner-policy-permit-file", type=Path)
    parser.add_argument("--activation-marker-file", type=Path)
    parser.add_argument("--transactions-root", type=Path)
    parser.add_argument("--primary-cron-file", type=Path)
    parser.add_argument("--secondary-disposition-file", type=Path)
    parser.add_argument("--user-crontab-snapshot-file", type=Path)
    parser.add_argument("--process-snapshot-file", type=Path)
    parser.add_argument("--cycle-id")
    parser.add_argument("--scheduled-cycle-id")
    parser.add_argument("--cycle-lease-fd", type=int)
    parser.add_argument("--resend-part-index", type=int, action="append", default=[])
    parser.add_argument("--terminal-status")
    parser.add_argument("--delivery-status")
    parser.add_argument("--primary-delivery-status")
    parser.add_argument("--secondary-delivery-status")
    parser.add_argument("--primary-ledger-tip")
    parser.add_argument("--secondary-ledger-tip")
    parser.add_argument("--authorize-shadow-provisioning", action="store_true")
    parser.add_argument("--authorize-bootstrap", action="store_true")
    parser.add_argument("--authorize-activate", action="store_true")
    parser.add_argument("--authorize-rollback", action="store_true")
    parser.add_argument("--allow-local-maintenance-window", action="store_true")
    return parser


def admin_main(argv: Sequence[str]) -> int:
    try:
        args = _admin_parser().parse_args(list(argv))
        command = args.command
        if command == "init-shadow-root":
            path = _init_shadow_root(args)
            result = {"status": "initialized", "shadow_root": str(path)}
        elif command == "install-shadow-permit":
            path = _install_shadow_permit(args)
            result = {
                "status": "installed",
                "authorization_id": args.authorization_id,
                "permit_kind": "shadow",
                "permit_path": str(path),
            }
        elif command in {
            "install-prepare-permit",
            "install-send-permit",
            "install-schedule-permit",
            "install-scheduled-cycle-policy-permit",
            "install-admin-permit",
        }:
            kind = command.removeprefix("install-").removesuffix("-permit")
            with _permit_lifecycle_lock(args) as root:
                path = _install_permit(
                    root=root, document=_permit_document(args, kind)
                )
            result = {
                "status": "installed",
                "authorization_id": args.authorization_id,
                "permit_kind": kind,
                "permit_path": str(path),
            }
        elif command == "reserve-scheduled-cycle":
            with _permit_lifecycle_lock(args) as root:
                result = _reserve_scheduled_cycle(args, control_root=root)
        elif command == "recover-scheduled-cycles":
            with _permit_lifecycle_lock(args) as root:
                result = _recover_scheduled_cycles(root)
        elif command == "terminalize-scheduled-prepare":
            with _permit_lifecycle_lock(args) as root:
                result = _terminalize_scheduled_prepare(args, control_root=root)
        elif command == "reserve-scheduled-prepare":
            with _permit_lifecycle_lock(args) as root:
                authorization_id = _reserve_scheduled_prepare(
                    args, control_root=root
                )
            result = {
                "status": "reserved",
                "authorization_id": authorization_id,
                "permit_kind": "schedule",
            }
        elif command == "reserve-send-permit":
            with _permit_lifecycle_lock(args) as root:
                _reserve_send_permit(args, control_root=root)
            result = {
                "status": "reserved",
                "authorization_id": args.authorization_id,
                "permit_kind": "send",
            }
        elif command == "validate-send-permit-use":
            with _permit_lifecycle_lock(args) as root:
                result = _validate_send_permit_use(args, control_root=root)
        elif command == "terminalize-send-permit":
            with _permit_lifecycle_lock(args) as root:
                target = _terminalize_send_permit(args, control_root=root)
            result = {
                "status": target,
                "authorization_id": args.authorization_id,
                "permit_kind": "send",
            }
        elif command == "apply-delivery-projection-plan":
            result = _apply_delivery_projection_plan_admin(args)
        elif command == "reserve-permit":
            authorization_id = _require_id(args.authorization_id, "authorization_id")
            release_sha = _require_sha(args.expected_release_sha256, "release_sha256")
            with _permit_lifecycle_lock(args) as root:
                _transition_permit(
                    root=root,
                    authorization_id=authorization_id,
                    expected_release_sha256=release_sha,
                    expected_run_id=args.run_id,
                    target_status="reserved",
                )
            result = {"status": "reserved", "authorization_id": authorization_id}
        elif command == "terminalize-permit":
            authorization_id = _require_id(args.authorization_id, "authorization_id")
            release_sha = _require_sha(args.expected_release_sha256, "release_sha256")
            target = str(args.terminal_status or "")
            with _permit_lifecycle_lock(args) as root:
                _transition_permit(
                    root=root,
                    authorization_id=authorization_id,
                    expected_release_sha256=release_sha,
                    expected_run_id=None,
                    target_status=target,
                )
            result = {"status": target, "authorization_id": authorization_id}
        elif command in {
            "recover-prepared-state",
            "commit-prepared",
            "commit-blocked",
            "bind-provider-attempt",
            "derive-scheduled-send-permit",
            "project-delivery-ledgers",
        }:
            layout, prepared_paths = _prepared_admin_layout(args)
            with _applicable_lock(args, Path(layout["lock"])):
                if command == "recover-prepared-state":
                    result = _recover_prepared_admin(
                        args, prepared_paths=prepared_paths
                    )
                elif command == "commit-prepared":
                    result = _commit_prepared_admin(
                        args, layout=layout, prepared_paths=prepared_paths
                    )
                elif command == "commit-blocked":
                    result = _commit_blocked_admin(
                        args, layout=layout, prepared_paths=prepared_paths
                    )
                elif command == "derive-scheduled-send-permit":
                    result = _derive_scheduled_send_permit(
                        args, layout=layout, prepared_paths=prepared_paths
                    )
                elif command == "project-delivery-ledgers":
                    result = _project_delivery_ledgers_admin(
                        args, prepared_paths=prepared_paths
                    )
                else:
                    result = _bind_provider_attempt(
                        args, layout=layout, prepared_paths=prepared_paths
                    )
        elif command in {"bootstrap", "activate"}:
            layout = _host_admin_layout(args)
            with _applicable_lock(args, layout["lock"]) as lock_fd:
                result = _activate_report_release(
                    args,
                    layout=layout,
                    action=command,
                    inherited_lock_fd=lock_fd,
                )
        elif command == "rollback":
            layout = _host_admin_layout(args)
            with _applicable_lock(args, layout["lock"]) as lock_fd:
                result = _rollback_report_release(
                    args, layout=layout, inherited_lock_fd=lock_fd
                )
        else:
            raise ReportControlError("admin_operation_not_implemented")
    except (ReportControlError, OSError, ValueError, RuntimeError, ImportError) as exc:
        reason = str(exc)
        if _SAFE_ID.fullmatch(reason) is None:
            reason = "admin_operation_failed"
        print(
            f"status=blocked\nreason={reason}\nprovider_call=false\nlive_send=false",
            file=sys.stderr,
        )
        return 1
    for key, value in result.items():
        print(f"{key}={value}")
    print("provider_call=false")
    print("live_send=false")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    if not values or values[0] not in {"admin", "gates"}:
        print(
            "status=blocked\nreason=control_mode_invalid\nprovider_call=false\nlive_send=false",
            file=sys.stderr,
        )
        return 1
    if values[0] == "admin":
        return admin_main(values[1:])
    return gates_main(values[1:])


if __name__ == "__main__":
    raise SystemExit(main())
