#!/usr/bin/env python3
"""Independently validate a private V3 fielded-VOC candidate."""

from __future__ import annotations

import argparse
import ctypes
from dataclasses import dataclass
from datetime import date, datetime
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Iterator, Mapping, Sequence
from urllib.parse import unquote, urlsplit
import uuid


BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}
CANONICAL_FILES = {
    "comments.jsonl",
    "conflict-ledger.jsonl",
    "manifest.json",
    "posts.jsonl",
    "provenance-ledger.jsonl",
    "quarantine.jsonl",
    "unresolved-parent-ledger.jsonl",
}
OUTPUT_FILES = {
    "manifest.json",
    "metric-eligibility.jsonl",
    "voc-exclusions.jsonl",
    "vocs.jsonl",
}
OUTPUT_FILES_A2 = OUTPUT_FILES | {"automation-classifications.jsonl"}
AUTOMATION_POLICY_SCHEMA = "reddit_voc_explicit_automation_policy_v1"
AUTOMATION_CLASSIFICATION_SCHEMA = (
    "reddit_voc_explicit_automation_classification_v1"
)
AUTOMATION_FAMILIES = ("RV-BR", "RV-IN", "RV-PS")
AUTOMATION_AUDIT_INDICATORS = ("RV-CI-01",)
AUTOMATION_AUTHORITY_FIELDS = {
    "governed_base": "body",
    "workbook_net_new": "source_text",
}
AUTOMATION_PATTERNS = (
    ("self_disclosed_bot", r"\bi am a bot\b"),
    (
        "automatic_action_disclosure",
        r"\bthis action was performed automatically\b",
    ),
    (
        "moderator_contact_disclosure",
        r"\bcontact the moderators of this subreddit\b",
    ),
    ("moderator_contact_link", r"/message/compose/\?to=/r/"),
)
AUTOMATION_FOOTER_RULE = "reddit_automation_footer_v1"
AUTOMATION_UPSTREAM_RULE = "trusted_upstream_bot_state_v1"
ID = re.compile(r"^[a-z0-9]+$")
INDICATOR_ID = re.compile(r"^RV-(DH|BR|PS|IN|CI)-[0-9]{2}$")
EXPECTED_INDICATOR_IDS = {
    *{f"RV-DH-{index:02d}" for index in range(1, 6)},
    *{f"RV-BR-{index:02d}" for index in range(1, 6)},
    *{f"RV-PS-{index:02d}" for index in range(1, 5)},
    *{f"RV-IN-{index:02d}" for index in range(1, 6)},
    *{f"RV-CI-{index:02d}" for index in range(1, 8)},
}
COMPARISON_SIDES = {
    "baseline",
    "competitor_union",
    "current",
    "momcozy",
    "not_applicable",
    "qualified_organic",
    "raw_observed",
}
DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
FILE_READ_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)


class VocFactValidationError(ValueError):
    """The VOC candidate does not reproduce its bound canonical input."""


class EvidenceIdentityConflict(VocFactValidationError):
    """A source link contradicts the canonical identity it accompanies."""


@dataclass(frozen=True)
class ValidationReceipt:
    bundle_manifest_sha256: str
    canonical_manifest_sha256: str
    canonical_validation_receipt_sha256: str
    eligibility_policy_sha256: str
    counts: dict[str, int]
    boundaries: dict[str, bool]
    automation_policy_sha256: str | None = None
    automation_family_contract_sha256: str | None = None
    canonical_comments_sha256: str | None = None
    schema_version: str = "reddit_voc_voc_facts_validation_receipt_v1"
    status: str = "passed"
    consumption_status: str = "blocked_pending_atomic_facts"
    promotable: bool = False

    def as_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "boundaries": dict(self.boundaries),
            "bundle_manifest_sha256": self.bundle_manifest_sha256,
            "canonical_manifest_sha256": self.canonical_manifest_sha256,
            "canonical_validation_receipt_sha256": self.canonical_validation_receipt_sha256,
            "consumption_status": self.consumption_status,
            "counts": dict(self.counts),
            "eligibility_policy_sha256": self.eligibility_policy_sha256,
            "promotable": self.promotable,
            "schema_version": self.schema_version,
            "status": self.status,
            "unaccounted_eligibility_members": 0,
            "unaccounted_vocs": 0,
        }
        if self.automation_policy_sha256 is not None:
            value["automation_family_contract_sha256"] = (
                self.automation_family_contract_sha256
            )
            value["automation_policy_sha256"] = self.automation_policy_sha256
            value["canonical_comments_sha256"] = self.canonical_comments_sha256
        return value


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise VocFactValidationError("value is not canonical JSON serializable") from exc


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha_value(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or not value.isascii()
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise VocFactValidationError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _decode(payload: bytes, label: str) -> object:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise VocFactValidationError(f"{label} contains a duplicate JSON key")
            result[key] = value
        return result

    def constant(value: str) -> object:
        raise VocFactValidationError(f"{label} contains a non-finite number:{value}")

    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=constant,
        )
    except VocFactValidationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise VocFactValidationError(f"{label} is invalid JSON") from exc


def _object(payload: bytes, label: str) -> dict[str, Any]:
    value = _decode(payload, label)
    if not isinstance(value, dict) or payload != _canonical(value) + b"\n":
        raise VocFactValidationError(f"{label} is not canonical JSON")
    return value


def _jsonl(payload: bytes, label: str) -> list[dict[str, Any]]:
    if payload and not payload.endswith(b"\n"):
        raise VocFactValidationError(f"{label} must end with a newline")
    rows: list[dict[str, Any]] = []
    for ordinal, line in enumerate(payload.splitlines(), start=1):
        value = _decode(line, f"{label} row {ordinal}")
        if not isinstance(value, dict) or line != _canonical(value):
            raise VocFactValidationError(f"{label} row {ordinal} is not canonical JSON")
        rows.append(value)
    return rows


def _project_parts(path: Path, project_root: Path, label: str) -> tuple[str, ...]:
    root = Path(os.path.abspath(os.fspath(project_root)))
    target = Path(
        os.path.abspath(os.fspath(path if path.is_absolute() else root / path))
    )
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise VocFactValidationError(f"{label} is outside the project boundary") from exc
    if not relative.parts or any(
        part in {"", ".", ".."} or "/" in part or "\\" in part
        for part in relative.parts
    ):
        raise VocFactValidationError(f"{label} path is unsafe")
    return relative.parts


def _private_parts(path: Path, project_root: Path, label: str) -> tuple[str, ...]:
    parts = _project_parts(path, project_root, label)
    if parts[:2] != ("tmp", "reddit-voc-v3") or len(parts) <= 2:
        raise VocFactValidationError(
            f"{label} must stay below private tmp/reddit-voc-v3"
        )
    return parts[2:]


def _open_directory_chain(
    project_root: Path,
    parts: Sequence[str],
    *,
    private_from: int | None,
    label: str,
) -> list[int]:
    opened: list[int] = []
    try:
        descriptor = os.open(
            os.path.abspath(os.fspath(project_root)), DIRECTORY_FLAGS
        )
        opened.append(descriptor)
        for ordinal, part in enumerate(parts):
            descriptor = os.open(part, DIRECTORY_FLAGS, dir_fd=descriptor)
            opened.append(descriptor)
            metadata = os.fstat(descriptor)
            if not stat.S_ISDIR(metadata.st_mode):
                raise VocFactValidationError(f"{label} ancestor is not a directory")
            if (
                private_from is not None
                and ordinal >= private_from
                and stat.S_IMODE(metadata.st_mode) != 0o700
            ):
                raise VocFactValidationError(
                    f"{label} private directory must have mode 0700"
                )
        return opened
    except (OSError, VocFactValidationError) as exc:
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                pass
        if isinstance(exc, VocFactValidationError):
            raise
        raise VocFactValidationError(f"{label} directory chain is unavailable") from exc


def _read_at(
    directory_fd: int,
    name: str,
    *,
    label: str,
    require_private: bool,
) -> bytes:
    try:
        descriptor = os.open(name, FILE_READ_FLAGS, dir_fd=directory_fd)
    except OSError as exc:
        raise VocFactValidationError(f"{label} is unavailable") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise VocFactValidationError(f"{label} must be a regular file")
        if require_private and stat.S_IMODE(before.st_mode) != 0o600:
            raise VocFactValidationError(f"{label} must have mode 0600")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        payload = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ) or len(payload) != after.st_size:
            raise VocFactValidationError(f"{label} changed while it was read")
        return payload
    finally:
        os.close(descriptor)


def _read_private_bundle(
    path: Path,
    *,
    expected_inventory: set[str],
    project_root: Path,
    label: str,
    selected_names: set[str] | None = None,
) -> dict[str, bytes]:
    selected = expected_inventory if selected_names is None else selected_names
    if not selected.issubset(expected_inventory):
        raise VocFactValidationError(f"{label} selected inventory is invalid")
    relative = _private_parts(path, project_root, label)
    opened = _open_directory_chain(
        project_root,
        ("tmp", "reddit-voc-v3", *relative),
        private_from=1,
        label=label,
    )
    try:
        directory_fd = opened[-1]
        try:
            inventory = set(os.listdir(directory_fd))
        except OSError as exc:
            raise VocFactValidationError(f"{label} inventory is unavailable") from exc
        if inventory != expected_inventory:
            raise VocFactValidationError(f"{label} inventory is invalid")
        return {
            name: _read_at(
                directory_fd,
                name,
                label=f"{label} {name}",
                require_private=True,
            )
            for name in sorted(selected)
        }
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)


def _receipt_blocker_name(receipt_name: str) -> str:
    return f".{receipt_name}.uncommitted"


def _require_receipt_committed(
    directory_fd: int, receipt_name: str, label: str
) -> None:
    try:
        os.stat(
            _receipt_blocker_name(receipt_name),
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return
    except OSError as exc:
        raise VocFactValidationError(
            f"{label} commit gate is unavailable"
        ) from exc
    raise VocFactValidationError(
        f"{label} is blocked by an uncommitted receipt marker"
    )


def _read_private_receipt(path: Path, *, project_root: Path, label: str) -> bytes:
    relative = _private_parts(path, project_root, label)
    opened = _open_directory_chain(
        project_root,
        ("tmp", "reddit-voc-v3", *relative[:-1]),
        private_from=1,
        label=label,
    )
    try:
        _require_receipt_committed(opened[-1], relative[-1], label)
        payload = _read_at(
            opened[-1],
            relative[-1],
            label=label,
            require_private=True,
        )
        _require_receipt_committed(opened[-1], relative[-1], label)
        return payload
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)


def _read_project_file(path: Path, *, project_root: Path, label: str) -> bytes:
    relative = _project_parts(path, project_root, label)
    opened = _open_directory_chain(
        project_root,
        relative[:-1],
        private_from=None,
        label=label,
    )
    try:
        return _read_at(
            opened[-1],
            relative[-1],
            label=label,
            require_private=False,
        )
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)


def _bare(value: object, prefix: str, label: str) -> str:
    if not isinstance(value, str) or not value.isascii():
        raise VocFactValidationError(f"{label} is invalid")
    text = value.lower()
    if text.startswith(prefix):
        text = text[len(prefix) :]
    elif text.startswith(("t1_", "t3_")):
        raise VocFactValidationError(f"{label} namespace is invalid")
    if ID.fullmatch(text) is None:
        raise VocFactValidationError(f"{label} is invalid")
    return text


def _bound_documents(
    raw_payloads: Mapping[str, bytes],
    manifest: Mapping[str, Any],
    names: set[str],
    label: str,
    expected_manifest_names: set[str] | None = None,
) -> dict[str, bytes]:
    files = manifest.get("files")
    manifest_names = names if expected_manifest_names is None else expected_manifest_names
    if not isinstance(files, dict) or set(files) != manifest_names:
        raise VocFactValidationError(f"{label} file bindings are invalid")
    payloads: dict[str, bytes] = {}
    for name in sorted(names):
        binding = files.get(name)
        if not isinstance(binding, dict) or set(binding) != {"bytes", "rows", "sha256"}:
            raise VocFactValidationError(f"{label} {name} binding is invalid")
        payload = raw_payloads[name]
        if (
            type(binding.get("bytes")) is not int
            or binding["bytes"] != len(payload)
            or type(binding.get("rows")) is not int
            or binding["rows"] != payload.count(b"\n")
            or _sha_value(binding.get("sha256"), f"{label} {name} SHA-256") != _sha(payload)
        ):
            raise VocFactValidationError(f"{label} {name} binding mismatch")
        payloads[name] = payload
    return payloads


def _text(record: Mapping[str, Any], names: Sequence[str]) -> str:
    for name in names:
        if name in record and record[name] is not None:
            value = record[name]
            if not isinstance(value, str):
                raise VocFactValidationError(f"canonical {name} is not text")
            return value
    return ""


def _optional_text(value: object, label: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise VocFactValidationError(f"{label} is invalid")
    return value


def _strings(value: object, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise VocFactValidationError(f"{label} is invalid")
    if len(value) != len(set(value)):
        raise VocFactValidationError(f"{label} has duplicates")
    return list(value)


def _source(row: Mapping[str, Any], record: Mapping[str, Any]) -> tuple[str, dict[str, object]]:
    authority = row.get("record_authority")
    if not isinstance(authority, str) or not authority:
        raise VocFactValidationError("canonical record authority is invalid")
    snapshot = record.get("source_snapshot_id")
    if snapshot is not None and (not isinstance(snapshot, str) or not snapshot):
        raise VocFactValidationError("canonical source snapshot is invalid")
    allowed_value = record.get("effective_allowed_metric_families")
    if allowed_value is None:
        allowed_value = record.get("allowed_metric_families")
    return (
        snapshot if isinstance(snapshot, str) else authority,
        {
            "allowed_metric_families": _strings(allowed_value, "allowed metric families")
            if allowed_value is not None
            else None,
            "blocked_uses": _strings(record.get("blocked_uses"), "blocked uses"),
            "governed_base_default": authority == "governed_base" and allowed_value is None,
        },
    )


def _event_time(
    record: Mapping[str, Any],
) -> tuple[str | None, str | None, str | None, str | None]:
    calendar_date = _optional_text(record.get("source_calendar_date"), "source date")
    precision = _optional_text(record.get("event_time_precision"), "event precision")
    timezone_status = _optional_text(record.get("source_timezone_status"), "timezone status")
    created_values = [
        value
        for value in (
            _optional_text(record.get("event_created_at_utc"), "event timestamp"),
            _optional_text(record.get("created_at_utc"), "created timestamp"),
        )
        if value is not None
    ]
    if len(set(created_values)) > 1:
        raise VocFactValidationError("canonical event timestamps conflict")
    created = created_values[0] if created_values else None
    if precision is None:
        if created is not None:
            precision = "instant"
        elif calendar_date is not None:
            precision = "day"
    if precision is None:
        if timezone_status is not None:
            raise VocFactValidationError("canonical timezone status lacks event time")
        return None, None, None, None
    if precision == "day":
        if created is not None:
            raise VocFactValidationError("day-precision canonical event contains an instant")
        if not isinstance(calendar_date, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", calendar_date) is None:
            raise VocFactValidationError("day-precision canonical event lacks a literal date")
        try:
            date.fromisoformat(calendar_date)
        except ValueError as exc:
            raise VocFactValidationError("canonical floating date is invalid") from exc
        if timezone_status not in {None, "unknown"}:
            raise VocFactValidationError("canonical floating date timezone status is invalid")
        return None, "day", calendar_date, "unknown"
    if precision not in {"instant", "hour"} or created is None or calendar_date is not None:
        raise VocFactValidationError("canonical instant/hour event contract is invalid")
    try:
        parsed = datetime.fromisoformat(created.replace("Z", "+00:00"))
    except ValueError as exc:
        raise VocFactValidationError("canonical event timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None or timezone_status == "unknown":
        raise VocFactValidationError("canonical event timestamp is not timezone-aware")
    return created, precision, None, timezone_status or "known_from_aware_instant"


def _record_identity(
    record: Mapping[str, Any],
    names: Sequence[str],
    prefix: str,
    expected: str,
    label: str,
) -> None:
    for name in names:
        if record.get(name) is None:
            continue
        if _bare(record.get(name), prefix, label) != expected:
            raise VocFactValidationError(f"{label} mismatch")


def _url_identity(value: str, label: str) -> tuple[str | None, str | None]:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise VocFactValidationError(f"{label} URL is invalid")
    parsed = urlsplit(value)
    reddit_web = False
    reddit_short = False
    if parsed.scheme:
        try:
            port = parsed.port
        except ValueError as exc:
            raise VocFactValidationError(f"{label} URL is invalid") from exc
        hostname = parsed.hostname
        if (
            parsed.scheme.lower() != "https"
            or hostname is None
            or not hostname.isascii()
            or hostname.endswith(".")
            or parsed.username is not None
            or parsed.password is not None
            or port not in {None, 443}
        ):
            raise VocFactValidationError(f"{label} URL is invalid")
        lowered_hostname = hostname.lower()
        reddit_web = lowered_hostname == "reddit.com" or lowered_hostname.endswith(
            ".reddit.com"
        )
        reddit_short = lowered_hostname == "redd.it"
    elif parsed.netloc or not value.startswith("/"):
        raise VocFactValidationError(f"{label} URL is invalid")
    else:
        reddit_web = True
    decoded_parts: list[str] = []
    parts: list[str] = []
    raw_parts: list[str] = []
    for raw_part in parsed.path.split("/"):
        if not raw_part:
            continue
        if re.search(r"%(?![0-9A-Fa-f]{2})", raw_part):
            raise VocFactValidationError(f"{label} URL path is invalid")
        try:
            decoded = unquote(raw_part, errors="strict")
        except UnicodeDecodeError as exc:
            raise VocFactValidationError(f"{label} URL path is invalid") from exc
        if (
            decoded in {".", ".."}
            or "/" in decoded
            or "\\" in decoded
            or any(ord(character) < 32 or ord(character) == 127 for character in decoded)
        ):
            raise VocFactValidationError(f"{label} URL path is invalid")
        raw_parts.append(raw_part)
        decoded_parts.append(decoded)
        parts.append(decoded.casefold())

    if reddit_short:
        if len(parts) != 1:
            raise VocFactValidationError(f"{label} URL path is invalid")
        if "%" in raw_parts[0]:
            raise VocFactValidationError(f"{label} URL raw identity is encoded")
        try:
            post_id = _bare(parts[0], "t3_", f"{label} URL post ID")
        except VocFactValidationError as exc:
            raise VocFactValidationError(
                f"{label} URL post identity is invalid"
            ) from exc
        if decoded_parts[0] != post_id:
            raise VocFactValidationError(
                f"{label} URL post identity is not canonical lowercase"
            )
        return post_id, None

    if not reddit_web:
        return None, None
    if len(parts) >= 4 and parts[0] == "r" and parts[2] == "comments":
        marker = 2
    elif len(parts) >= 2 and parts[0] == "comments":
        marker = 0
    elif len(parts) == 2 and parts[0] == "gallery":
        if "%" in raw_parts[1]:
            raise VocFactValidationError(f"{label} URL raw identity is encoded")
        post_id = _bare(parts[1], "t3_", f"{label} URL post ID")
        if decoded_parts[1] != post_id:
            raise VocFactValidationError(
                f"{label} URL post identity is not canonical lowercase"
            )
        return post_id, None
    else:
        raise VocFactValidationError(f"{label} URL comments path is missing")
    if any("%" in raw_parts[index] for index in (marker, marker + 1)):
        raise VocFactValidationError(f"{label} URL raw identity is encoded")
    post_id = _bare(parts[marker + 1], "t3_", f"{label} URL post ID")
    if decoded_parts[marker + 1] != post_id:
        raise VocFactValidationError(
            f"{label} URL post identity is not canonical lowercase"
        )
    tail = parts[marker + 2 :]
    comment_id: str | None = None
    if len(tail) > 2:
        raise VocFactValidationError(f"{label} URL comments path is invalid")
    if len(tail) >= 2:
        if "%" in raw_parts[-1]:
            raise VocFactValidationError(f"{label} URL raw identity is encoded")
        comment_id = _bare(tail[-1], "t1_", f"{label} URL comment ID")
        if decoded_parts[-1] != comment_id:
            raise VocFactValidationError(
                f"{label} URL comment identity is not canonical lowercase"
            )
    return post_id, comment_id


def _url_candidates(record: Mapping[str, Any]) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    for name in ("permalink", "source_url"):
        if record.get(name) is not None:
            value = record[name]
            if not isinstance(value, str):
                raise VocFactValidationError(f"{name} URL is invalid")
            candidates.append((name, value))
    occurrences = record.get("source_occurrences")
    if occurrences is not None:
        if not isinstance(occurrences, list):
            raise VocFactValidationError("source occurrences are invalid")
        for ordinal, occurrence in enumerate(occurrences, start=1):
            if not isinstance(occurrence, dict):
                raise VocFactValidationError("source occurrence is invalid")
            value = occurrence.get("source_url")
            if value is not None:
                if not isinstance(value, str):
                    raise VocFactValidationError("source occurrence URL is invalid")
                candidates.append((f"source occurrence {ordinal}", value))
    return candidates


def _validate_urls(record: Mapping[str, Any], post_id: str, comment_id: str | None) -> None:
    first_conflict: str | None = None
    for label, value in _url_candidates(record):
        url_post, url_comment = _url_identity(value, label)
        if url_post is None:
            if comment_id is not None:
                first_conflict = first_conflict or (
                    f"{label} URL comment identity is missing"
                )
            continue
        if url_post != post_id:
            first_conflict = first_conflict or (
                f"{label} URL post identity mismatch"
            )
            continue
        if comment_id is None and url_comment is not None:
            first_conflict = first_conflict or (
                f"{label} URL unexpectedly identifies a comment"
            )
        if comment_id is not None:
            if url_comment is None:
                first_conflict = first_conflict or (
                    f"{label} URL comment identity is missing"
                )
            if url_comment != comment_id:
                first_conflict = first_conflict or (
                    f"{label} URL comment identity mismatch"
                )
    if first_conflict is not None:
        raise EvidenceIdentityConflict(first_conflict)


def _authority(row: Mapping[str, Any]) -> str:
    value = row.get("record_authority")
    if value not in {"governed_base", "workbook_net_new"}:
        raise VocFactValidationError("canonical record authority is invalid")
    return str(value)


def _exclusion(
    canonical_id: str,
    entity_type: str,
    post_id: str | None,
    comment_id: str | None,
    reasons: Sequence[str],
) -> dict[str, object]:
    return {
        "canonical_entity_id": canonical_id,
        "comment_id": comment_id,
        "entity_type": entity_type,
        "intended_voc_type": "post_voc" if entity_type == "post" else "comment_context_voc",
        "post_id": post_id,
        "reason_codes": list(reasons),
        "schema_version": "reddit_voc_voc_exclusion_v1",
    }


def _expected_materialization(
    canonical_posts: list[dict[str, Any]],
    canonical_comments: list[dict[str, Any]],
    canonical_quarantine: list[dict[str, Any]],
    unresolved_ledger: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    posts: dict[str, tuple[Mapping[str, Any], str, str]] = {}
    expected: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    for row in canonical_posts:
        if (
            row.get("canonical_identity_state") != "canonical_identity"
            or row.get("entity_type") != "post"
            or row.get("schema_version") != "reddit_voc_canonical_post_v1"
        ):
            raise VocFactValidationError("canonical post header is invalid")
        authority = _authority(row)
        raw_post_id = row.get("post_id")
        post_id = _bare(raw_post_id, "t3_", "canonical post_id")
        raw_canonical_id = row.get("canonical_reddit_id")
        canonical_id = f"t3_{post_id}"
        if (
            raw_post_id != post_id
            or raw_canonical_id != canonical_id
            or post_id in posts
        ):
            raise VocFactValidationError("canonical post identity is duplicate or mismatched")
        record = row.get("record")
        if not isinstance(record, dict):
            raise VocFactValidationError("canonical post record is invalid")
        _record_identity(record, ("post_id", "reddit_id", "canonical_reddit_id"), "t3_", post_id, "post record ID")
        _record_identity(record, ("thread_id",), "t3_", post_id, "post thread ID")
        url_conflict = False
        try:
            _validate_urls(record, post_id, None)
        except EvidenceIdentityConflict:
            url_conflict = True
        title = _text(record, ("title", "source_text"))
        body = _text(record, ("content", "selftext", "body"))
        posts[post_id] = (record, title, body)
        reasons: list[str] = []
        if not title.strip() and not body.strip():
            reasons.append("analysis_text_incomplete")
        if url_conflict:
            reasons.append("source_url_identity_conflict")
        if reasons:
            exclusions.append(_exclusion(canonical_id, "post", post_id, None, reasons))
            continue
        author = _optional_text(record.get("author"), "post author")
        pseudonym = _optional_text(record.get("author_pseudonym"), "post author pseudonym")
        anchor, source_policy = _source(row, record)
        created, precision, calendar_date, timezone_status = _event_time(record)
        expected.append({
            "analysis_fields": {"current_comment_body": "", "post_body": body, "post_title": title},
            "analysis_text_status": "ready",
            "anchor_source": anchor,
            "author": author,
            "author_pseudonym": pseudonym,
            "author_scope": "post_author_only",
            "canonical_entity_id": canonical_id,
            "comment_context_id": None,
            "comment_id": None,
            "context_status": "not_applicable",
            "evidence_scope": {
                "brand_category_product_topic_coreference": ["post_title", "post_body"],
                "sentiment_problem_severity_recommendation_persona": ["post_title", "post_body"],
            },
            "event_created_at_utc": created,
            "event_time_precision": precision,
            "metric_distinct_key": post_id,
            "post_id": post_id,
            "record_authority": authority,
            "schema_version": "reddit_voc_fielded_voc_v1",
            "source_calendar_date": calendar_date,
            "source_policy": source_policy,
            "source_timezone_status": timezone_status,
            "thread_id": post_id,
            "voc_id": f"post:{post_id}",
            "voc_type": "post_voc",
        })

    comments: dict[str, tuple[dict[str, Any], str, Mapping[str, Any]]] = {}
    linked = 0
    unresolved = 0
    parent_links: dict[str, str] = {}
    comment_url_conflicts: set[str] = set()
    for row in canonical_comments:
        if (
            row.get("canonical_identity_state") != "canonical_identity"
            or row.get("entity_type") != "comment"
            or row.get("schema_version") != "reddit_voc_canonical_comment_v1"
        ):
            raise VocFactValidationError("canonical comment header is invalid")
        _authority(row)
        raw_canonical_id = row.get("canonical_reddit_id")
        comment_id = _bare(raw_canonical_id, "t1_", "canonical comment ID")
        canonical_id = f"t1_{comment_id}"
        raw_post_id = row.get("post_id")
        post_id = _bare(raw_post_id, "t3_", "canonical comment post ID")
        if (
            raw_canonical_id != canonical_id
            or raw_post_id != post_id
            or canonical_id in comments
        ):
            raise VocFactValidationError("canonical comment identity is duplicate or mismatched")
        record = row.get("record")
        if not isinstance(record, dict):
            raise VocFactValidationError("canonical comment record is invalid")
        _record_identity(record, ("comment_id", "reddit_id", "canonical_reddit_id"), "t1_", comment_id, "comment record ID")
        _record_identity(record, ("post_id", "thread_id"), "t3_", post_id, "comment thread ID")
        try:
            _validate_urls(record, post_id, comment_id)
        except EvidenceIdentityConflict:
            comment_url_conflicts.add(canonical_id)
        raw_parent = record.get("parent_id")
        if raw_parent is not None:
            if not isinstance(raw_parent, str) or not raw_parent.isascii():
                raise VocFactValidationError("comment parent identity is invalid")
            if raw_parent.lower().startswith("t3_"):
                if _bare(raw_parent, "t3_", "comment parent post") != post_id:
                    raise VocFactValidationError("comment parent post mismatch")
            elif raw_parent.lower().startswith("t1_"):
                parent_links[canonical_id] = f"t1_{_bare(raw_parent, 't1_', 'comment parent comment')}"
            else:
                raise VocFactValidationError("comment parent identity is invalid")
        state = row.get("comment_state")
        if state == "linked":
            linked += 1
        elif state == "unresolved_parent":
            unresolved += 1
        else:
            raise VocFactValidationError("canonical comment state is invalid")
        comments[canonical_id] = (row, post_id, record)

    visit_state: dict[str, int] = {}
    def visit(comment_id: str) -> None:
        state = visit_state.get(comment_id, 0)
        if state == 1:
            raise VocFactValidationError("canonical comment parent cycle")
        if state == 2:
            return
        visit_state[comment_id] = 1
        parent_id = parent_links.get(comment_id)
        if parent_id in comments:
            if comments[parent_id][1] != comments[comment_id][1]:
                raise VocFactValidationError("canonical nested parent crosses threads")
            visit(parent_id)
        visit_state[comment_id] = 2
    for canonical_id in comments:
        visit(canonical_id)

    for canonical_id in sorted(comments):
        row, post_id, record = comments[canonical_id]
        comment_id = _bare(canonical_id, "t1_", "canonical comment ID")
        if row["comment_state"] == "unresolved_parent":
            reasons = ["unresolved_parent"]
            if canonical_id in comment_url_conflicts:
                reasons.append("source_url_identity_conflict")
            exclusions.append(_exclusion(canonical_id, "comment", post_id, comment_id, reasons))
            continue
        if post_id not in posts:
            raise VocFactValidationError("linked canonical comment root is missing")
        parent_record, post_title, post_body = posts[post_id]
        body = _text(record, ("body", "source_text", "content"))
        reasons: list[str] = []
        if not body.strip():
            reasons.append("analysis_text_incomplete")
        if not post_title.strip() and not post_body.strip():
            reasons.append("root_post_context_incomplete")
        if canonical_id in comment_url_conflicts:
            reasons.append("source_url_identity_conflict")
        if reasons:
            exclusions.append(_exclusion(canonical_id, "comment", post_id, comment_id, reasons))
            continue
        authority = _authority(row)
        author = _optional_text(record.get("author"), "comment author")
        pseudonym = _optional_text(record.get("author_pseudonym"), "comment author pseudonym")
        anchor, source_policy = _source(row, record)
        created, precision, calendar_date, timezone_status = _event_time(record)
        expected.append({
            "analysis_fields": {"current_comment_body": body, "post_body": post_body, "post_title": post_title},
            "analysis_text_status": "ready",
            "anchor_source": anchor,
            "author": author,
            "author_pseudonym": pseudonym,
            "author_scope": "current_comment_author_only",
            "canonical_entity_id": canonical_id,
            "comment_context_id": f"{post_id}:{comment_id}",
            "comment_id": comment_id,
            "context_status": "ready",
            "evidence_scope": {
                "brand_category_product_topic_coreference": ["post_title", "post_body", "current_comment_body"],
                "sentiment_problem_severity_recommendation_persona": ["current_comment_body"],
            },
            "event_created_at_utc": created,
            "event_time_precision": precision,
            "metric_distinct_key": comment_id,
            "post_id": post_id,
            "record_authority": authority,
            "schema_version": "reddit_voc_fielded_voc_v1",
            "source_calendar_date": calendar_date,
            "source_policy": source_policy,
            "source_timezone_status": timezone_status,
            "thread_id": post_id,
            "voc_id": f"comment:{comment_id}",
            "voc_type": "comment_context_voc",
        })

    quarantine_ids: set[str] = set()
    quarantine_roots: dict[str, str] = {}
    quarantine_parent_links: dict[str, str] = {}
    quarantine_url_conflicts: set[str] = set()
    for row in canonical_quarantine:
        if (
            row.get("canonical_identity_state") != "canonical_identity"
            or row.get("entity_type") != "comment"
            or row.get("comment_state") != "quarantined"
            or row.get("schema_version") != "reddit_voc_canonical_quarantine_v1"
        ):
            raise VocFactValidationError("canonical quarantine header is invalid")
        _authority(row)
        raw_canonical_id = row.get("canonical_reddit_id")
        comment_id = _bare(
            raw_canonical_id, "t1_", "quarantined comment ID"
        )
        canonical_id = f"t1_{comment_id}"
        if (
            raw_canonical_id != canonical_id
            or canonical_id in comments
            or canonical_id in quarantine_ids
        ):
            raise VocFactValidationError("quarantined comment identity overlaps or duplicates")
        quarantine_ids.add(canonical_id)
        record = row.get("record")
        if not isinstance(record, dict):
            raise VocFactValidationError("quarantined comment record is invalid")
        _record_identity(record, ("comment_id", "reddit_id", "canonical_reddit_id"), "t1_", comment_id, "quarantine record ID")
        post_id = _bare(
            record.get("missing_post_id"),
            "t3_",
            "quarantine missing post ID",
        )
        if post_id in posts:
            raise VocFactValidationError(
                "quarantined comment missing root unexpectedly exists"
            )
        raw_parent = record.get("parent_id")
        if raw_parent is not None:
            if not isinstance(raw_parent, str) or not raw_parent.isascii():
                raise VocFactValidationError(
                    "quarantined comment parent identity is invalid"
                )
            if raw_parent.lower().startswith("t3_"):
                if (
                    _bare(
                        raw_parent,
                        "t3_",
                        "quarantined comment parent post",
                    )
                    != post_id
                ):
                    raise VocFactValidationError(
                        "quarantined comment parent post mismatch"
                    )
            elif raw_parent.lower().startswith("t1_"):
                parent_id = f"t1_{_bare(raw_parent, 't1_', 'quarantined comment parent comment')}"
                if parent_id == canonical_id:
                    raise VocFactValidationError(
                        "quarantined comment parent cycle"
                    )
                quarantine_parent_links[canonical_id] = parent_id
            else:
                raise VocFactValidationError(
                    "quarantined comment parent identity is invalid"
                )
        try:
            _validate_urls(record, post_id, comment_id)
        except EvidenceIdentityConflict:
            quarantine_url_conflicts.add(canonical_id)
        quarantine_roots[canonical_id] = post_id
        reasons = ["quarantined"]
        if canonical_id in quarantine_url_conflicts:
            reasons.append("source_url_identity_conflict")
        exclusions.append(_exclusion(canonical_id, "comment", post_id, comment_id, reasons))

    combined_roots = {
        canonical_id: post_id
        for canonical_id, (_, post_id, _) in comments.items()
    }
    combined_roots.update(quarantine_roots)
    combined_parent_links = dict(parent_links)
    combined_parent_links.update(quarantine_parent_links)
    for child_id, parent_id in combined_parent_links.items():
        if (
            parent_id in combined_roots
            and combined_roots[parent_id] != combined_roots[child_id]
        ):
            raise VocFactValidationError(
                "canonical comment parent crosses root threads"
            )

    combined_visit_state: dict[str, int] = {}

    def visit_combined(comment_id: str) -> None:
        state = combined_visit_state.get(comment_id, 0)
        if state == 1:
            raise VocFactValidationError("canonical comment parent cycle")
        if state == 2:
            return
        combined_visit_state[comment_id] = 1
        parent_id = combined_parent_links.get(comment_id)
        if parent_id in combined_roots:
            visit_combined(parent_id)
        combined_visit_state[comment_id] = 2

    for canonical_id in combined_roots:
        visit_combined(canonical_id)

    unresolved_ids = {canonical_id for canonical_id, (row, _, _) in comments.items() if row["comment_state"] == "unresolved_parent"}
    ledger_ids: set[str] = set()
    for row in unresolved_ledger:
        if row.get("schema_version") != "reddit_voc_canonical_unresolved_parent_v1" or row.get("comment_state") != "unresolved_parent":
            raise VocFactValidationError("unresolved parent ledger row is invalid")
        raw_canonical_id = row.get("canonical_reddit_id")
        comment_id = _bare(raw_canonical_id, "t1_", "unresolved ledger ID")
        canonical_id = f"t1_{comment_id}"
        if raw_canonical_id != canonical_id or canonical_id in ledger_ids:
            raise VocFactValidationError("unresolved parent ledger identity duplicates")
        ledger_ids.add(canonical_id)
        raw_post_id = row.get("post_id")
        ledger_post_id = _bare(
            raw_post_id, "t3_", "unresolved ledger post ID"
        )
        if (
            raw_post_id != ledger_post_id
            or canonical_id not in comments
            or ledger_post_id != comments[canonical_id][1]
        ):
            raise VocFactValidationError("unresolved parent ledger foreign key mismatch")
    if ledger_ids != unresolved_ids:
        raise VocFactValidationError("unresolved parent ledger does not match comment states")

    expected.sort(key=lambda row: (row["voc_type"] != "post_voc", row["canonical_entity_id"]))
    exclusions.sort(key=lambda row: row["canonical_entity_id"])
    expected_ids = [row["canonical_entity_id"] for row in expected]
    exclusion_ids = [row["canonical_entity_id"] for row in exclusions]
    if len(expected_ids) != len(set(expected_ids)) or len(exclusion_ids) != len(set(exclusion_ids)) or set(expected_ids) & set(exclusion_ids):
        raise VocFactValidationError("VOC/exclusion identity conservation failed")
    counts = {
        "comments_jsonl": len(canonical_comments),
        "linked_comments": linked,
        "posts": len(canonical_posts),
        "quarantined_comments": len(canonical_quarantine),
        "stored_comments": len(canonical_comments) + len(canonical_quarantine),
        "unresolved_parent_comments": unresolved,
    }
    return expected, exclusions, counts


def _automation_policy(
    value: Mapping[str, Any], policy_sha256: str
) -> dict[str, Any]:
    expected_keys = {
        "audit_indicator_ids",
        "boundaries",
        "canonical_retention",
        "commercial_attribution",
        "deterministic_rules",
        "exclude_indicator_families",
        "excluded_reason",
        "fallback_text_fields",
        "held_signal_rules",
        "matcher_version",
        "patterns",
        "policy_version",
        "schema_version",
        "text_field_by_record_authority",
    }
    expected_rules = [
        {
            "max_disclosure_gap_code_points": 16,
            "quoted_line_behavior": "held",
            "required_match_ids": [name for name, _ in AUTOMATION_PATTERNS],
            "rule_id": AUTOMATION_FOOTER_RULE,
            "same_paragraph": True,
        },
        {
            "required_bot_detection_status": "known_from_archive_author",
            "required_is_bot": True,
            "rule_id": AUTOMATION_UPSTREAM_RULE,
        },
    ]
    if (
        set(value) != expected_keys
        or value.get("schema_version") != AUTOMATION_POLICY_SCHEMA
        or value.get("boundaries") != BOUNDARIES
        or value.get("canonical_retention") is not True
        or value.get("commercial_attribution") != "not_inferred"
        or value.get("deterministic_rules") != expected_rules
        or value.get("exclude_indicator_families") != list(AUTOMATION_FAMILIES)
        or value.get("audit_indicator_ids")
        != list(AUTOMATION_AUDIT_INDICATORS)
        or value.get("excluded_reason") != "explicit_automation"
        or value.get("fallback_text_fields")
        != ["body", "comment_body", "source_text"]
        or value.get("held_signal_rules")
        != ["single_disclosure", "quoted_disclosure"]
        or value.get("matcher_version")
        != "explicit_bot_disclosure_regex_audit_v1"
        or value.get("patterns")
        != [
            {"match_id": name, "regex": regex}
            for name, regex in AUTOMATION_PATTERNS
        ]
        or value.get("text_field_by_record_authority")
        != AUTOMATION_AUTHORITY_FIELDS
        or not isinstance(value.get("policy_version"), str)
        or not value["policy_version"]
    ):
        raise VocFactValidationError("explicit automation policy is invalid")
    family_contract = {
        "audit_indicator_ids": list(AUTOMATION_AUDIT_INDICATORS),
        "exclude_indicator_families": list(AUTOMATION_FAMILIES),
    }
    return {
        "family_contract_sha256": _sha(_canonical(family_contract) + b"\n"),
        "matcher_version": value["matcher_version"],
        "policy_sha256": policy_sha256,
        "policy_version": value["policy_version"],
    }


def _automation_paragraph(text: str, position: int) -> tuple[int, int]:
    start = text.rfind("\n\n", 0, position)
    start = 0 if start < 0 else start + 2
    end = text.find("\n\n", position)
    return start, len(text) if end < 0 else end


def _automation_quoted(text: str, position: int) -> bool:
    line_start = text.rfind("\n", 0, position) + 1
    return text[line_start:position].lstrip().startswith(">")


def _expected_automation(
    comments: list[dict[str, Any]],
    policy: Mapping[str, Any],
) -> list[dict[str, Any]]:
    compiled = tuple(
        (match_id, re.compile(regex, re.IGNORECASE))
        for match_id, regex in AUTOMATION_PATTERNS
    )
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in comments:
        if (
            row.get("canonical_identity_state") != "canonical_identity"
            or row.get("entity_type") != "comment"
            or row.get("schema_version") != "reddit_voc_canonical_comment_v1"
        ):
            raise VocFactValidationError("canonical automation comment header is invalid")
        entity_id = row.get("canonical_reddit_id")
        if (
            not isinstance(entity_id, str)
            or re.fullmatch(r"t1_[a-z0-9]+", entity_id) is None
            or entity_id in seen
        ):
            raise VocFactValidationError("canonical automation identity is invalid")
        seen.add(entity_id)
        authority = _authority(row)
        state = row.get("comment_state")
        if state not in {"linked", "unresolved_parent"}:
            raise VocFactValidationError("canonical automation state is invalid")
        record = row.get("record")
        if not isinstance(record, dict):
            raise VocFactValidationError("canonical automation record is invalid")
        _record_identity(
            record,
            ("canonical_reddit_id", "reddit_id", "comment_id"),
            "t1_",
            entity_id[3:],
            "canonical automation record ID",
        )
        field = AUTOMATION_AUTHORITY_FIELDS[authority]
        if field not in record:
            raise VocFactValidationError("canonical automation text field is missing")
        text = record[field]
        if text is None:
            text = ""
        if not isinstance(text, str):
            raise VocFactValidationError("canonical automation text is invalid")

        spans: list[dict[str, Any]] = []
        for match_id, pattern in compiled:
            for match in pattern.finditer(text):
                evidence = text[match.start() : match.end()]
                spans.append(
                    {
                        "end": match.end(),
                        "evidence_text_sha256": _sha(evidence.encode("utf-8")),
                        "field": field,
                        "match_id": match_id,
                        "start": match.start(),
                    }
                )
        spans.sort(key=lambda span: (span["start"], span["end"], span["match_id"]))
        by_id: dict[str, list[dict[str, Any]]] = {}
        for span in spans:
            by_id.setdefault(str(span["match_id"]), []).append(span)
        audit_detected = any(
            by_id.get(match_id)
            for match_id in (
                "self_disclosed_bot",
                "automatic_action_disclosure",
            )
        )
        footer_determined = False
        if all(by_id.get(match_id) for match_id, _ in AUTOMATION_PATTERNS):
            for first in by_id["self_disclosed_bot"]:
                for second in by_id["automatic_action_disclosure"]:
                    if (
                        second["start"] < first["end"]
                        or second["start"] - first["end"] > 16
                    ):
                        continue
                    paragraph = _automation_paragraph(text, int(first["start"]))
                    if not (
                        paragraph[0]
                        <= second["start"]
                        < second["end"]
                        <= paragraph[1]
                    ):
                        continue
                    for contact in by_id["moderator_contact_disclosure"]:
                        if not (
                            second["end"]
                            <= contact["start"]
                            < contact["end"]
                            <= paragraph[1]
                        ):
                            continue
                        for link in by_id["moderator_contact_link"]:
                            if not (
                                contact["end"]
                                <= link["start"]
                                < link["end"]
                                <= paragraph[1]
                            ):
                                continue
                            selected = (first, second, contact, link)
                            if all(
                                not _automation_quoted(text, int(span["start"]))
                                for span in selected
                            ):
                                footer_determined = True
                                break
                        if footer_determined:
                            break
                    if footer_determined:
                        break
                if footer_determined:
                    break

        is_bot = record.get("is_bot")
        bot_status = record.get("bot_detection_status")
        if is_bot is not None and type(is_bot) is not bool:
            raise VocFactValidationError("canonical automation is_bot is invalid")
        if bot_status is not None and not isinstance(bot_status, str):
            raise VocFactValidationError("canonical automation bot status is invalid")
        upstream_known_bot = (
            is_bot is True and bot_status == "known_from_archive_author"
        )
        if upstream_known_bot and authority == "workbook_net_new":
            raise VocFactValidationError("workbook trusted bot state is not governed")
        determined = footer_determined or upstream_known_bot
        status = "determined" if determined else "held" if audit_detected else "not_detected"
        bucket = (
            "already_excluded_disclosure"
            if footer_determined and upstream_known_bot
            else "newly_excluded_disclosure"
            if footer_determined
            else "upstream_known_bot_only"
            if upstream_known_bot
            else "held_disclosure"
            if audit_detected
            else "not_automation"
        )
        matched_rules: list[str] = []
        reasons: list[str] = []
        if footer_determined:
            matched_rules.append(AUTOMATION_FOOTER_RULE)
            reasons.append("reddit_automation_footer")
        elif audit_detected:
            reasons.append("incomplete_or_quoted_automation_disclosure")
        if upstream_known_bot:
            matched_rules.append(AUTOMATION_UPSTREAM_RULE)
            reasons.append("upstream_known_bot")
        if not reasons:
            reasons.append("no_automation_signal")
        rows.append(
            {
                "audit_disclosure_detected": audit_detected,
                "automation_determined": determined,
                "canonical_entity_id": entity_id,
                "canonical_retained": True,
                "classification_accounting_bucket": bucket,
                "classification_status": status,
                "comment_state": state,
                "commercial_attribution_status": "not_inferred",
                "entity_type": "comment",
                "evidence_spans": spans,
                "excluded_reason": "explicit_automation" if determined else None,
                "input_text_sha256": _sha(text.encode("utf-8")),
                "matched_rule_ids": sorted(matched_rules),
                "matcher_version": policy["matcher_version"],
                "newly_excluded": determined and not upstream_known_bot,
                "policy_sha256": policy["policy_sha256"],
                "policy_version": policy["policy_version"],
                "reason_codes": sorted(reasons),
                "record_authority": authority,
                "requires_organic_exclusion": determined,
                "schema_version": AUTOMATION_CLASSIFICATION_SCHEMA,
                "text_field": field,
                "upstream_automation_excluded": upstream_known_bot,
                "was_already_excluded": upstream_known_bot,
            }
        )
    rows.sort(key=lambda row: row["canonical_entity_id"])
    return rows


def _iter_expected_eligibility(
    vocs: list[dict[str, Any]],
    policy: Mapping[str, Any],
    automation_ids: set[str] | None = None,
    automation_stats: dict[str, int] | None = None,
) -> Iterator[dict[str, Any]]:
    governed_automation_ids = set() if automation_ids is None else automation_ids
    policy_version = policy.get("policy_version")
    if not isinstance(policy_version, str) or not policy_version:
        raise VocFactValidationError("eligibility policy version is invalid")
    indicators = policy.get("indicators")
    if not isinstance(indicators, list):
        raise VocFactValidationError("eligibility policy indicators are invalid")
    sorted_indicators = sorted(
        indicators,
        key=lambda value: (
            value.get("reddit_indicator_id", "")
            if isinstance(value, dict)
            else ""
        ),
    )
    for voc in sorted(vocs, key=lambda row: row["canonical_entity_id"]):
        for indicator in sorted_indicators:
            if not isinstance(indicator, dict):
                raise VocFactValidationError("eligibility indicator is invalid")
            if indicator.get("metric_member_type", "canonical_entity") != "canonical_entity":
                continue
            voc_types = indicator.get("voc_types")
            sides = indicator.get("comparison_sides")
            if not isinstance(voc_types, list) or not isinstance(sides, list):
                raise VocFactValidationError("eligibility indicator scope is invalid")
            if voc["voc_type"] not in voc_types:
                continue
            required_use = indicator.get("required_source_use")
            if required_use is not None and not isinstance(required_use, str):
                raise VocFactValidationError("required source use is invalid")
            for side in sorted(sides):
                reasons: list[str] = []
                if indicator.get("text_required") is True and voc["analysis_text_status"] != "ready":
                    reasons.append("analysis_text_incomplete")
                if required_use is not None:
                    source_policy = voc["source_policy"]
                    allowed = source_policy["allowed_metric_families"]
                    blocked = source_policy["blocked_uses"]
                    governed = source_policy["governed_base_default"] is True
                    if not governed and (not isinstance(allowed, list) or required_use not in allowed):
                        reasons.append("source_use_not_allowed")
                    if required_use in blocked and "source_use_not_allowed" not in reasons:
                        reasons.append("source_use_not_allowed")
                if (
                    voc["canonical_entity_id"] in governed_automation_ids
                    and indicator["metric_family"] in AUTOMATION_FAMILIES
                ):
                    reasons.append("explicit_automation")
                if side in {"momcozy", "competitor_union"}:
                    reasons.append("brand_routing_pending")
                if side in {"current", "baseline"}:
                    reasons.append("period_binding_pending")
                reasons = sorted(set(reasons))
                if voc["canonical_entity_id"] in governed_automation_ids:
                    if (
                        indicator["metric_family"] in AUTOMATION_FAMILIES
                        and not reasons
                        and automation_stats is not None
                    ):
                        automation_stats["effective_eligible_automation_rows"] = (
                            automation_stats.get(
                                "effective_eligible_automation_rows", 0
                            )
                            + 1
                        )
                    if (
                        indicator["metric_family"] in AUTOMATION_FAMILIES
                        and reasons == ["explicit_automation"]
                        and automation_stats is not None
                    ):
                        automation_stats[
                            "effective_business_rows_excluded_by_automation"
                        ] = (
                            automation_stats.get(
                                "effective_business_rows_excluded_by_automation",
                                0,
                            )
                            + 1
                        )
                yield {
                    "anchor_source": voc["anchor_source"],
                    "comparison_side": side,
                    "denominator_member": False,
                    "membership_role": "excluded" if reasons else "eligible_candidate",
                    "metric_family": indicator["metric_family"],
                    "metric_member_id": voc["canonical_entity_id"],
                    "metric_member_type": "canonical_entity",
                    "numerator_member": "not_applicable",
                    "period": policy["_period"],
                    "policy_version": policy_version,
                    "reason_codes": reasons or ["structurally_eligible"],
                    "reddit_indicator_id": indicator["reddit_indicator_id"],
                    "schema_version": "reddit_voc_metric_eligibility_member_v1",
                    "scope": policy["_scope"],
                    "status": "excluded" if reasons else "eligible",
                    "voc_type": voc["voc_type"],
                }


def _expected_eligibility(
    vocs: list[dict[str, Any]], policy: Mapping[str, Any]
) -> list[dict[str, Any]]:
    return list(_iter_expected_eligibility(vocs, policy))


def _validate_eligibility_payload(
    payload: bytes,
    expected_rows: Iterator[dict[str, Any]],
) -> int:
    stream = io.BytesIO(payload)
    count = 0
    for expected in expected_rows:
        observed = stream.readline()
        if not observed or not observed.endswith(b"\n"):
            raise VocFactValidationError("metric eligibility ledger mismatch")
        if observed[:-1] != _canonical(expected):
            raise VocFactValidationError("metric eligibility ledger mismatch")
        count += 1
    if stream.read(1):
        raise VocFactValidationError("metric eligibility ledger mismatch")
    return count


def _validate_private_eligibility_file(
    bundle_root: Path,
    *,
    binding: Mapping[str, Any],
    expected_rows: Iterator[dict[str, Any]],
    project_root: Path,
) -> int:
    if set(binding) != {"bytes", "rows", "sha256"}:
        raise VocFactValidationError(
            "VOC facts metric-eligibility.jsonl binding is invalid"
        )
    expected_bytes = binding.get("bytes")
    expected_count = binding.get("rows")
    expected_sha = _sha_value(
        binding.get("sha256"),
        "VOC facts metric-eligibility.jsonl SHA-256",
    )
    if (
        type(expected_bytes) is not int
        or expected_bytes < 0
        or type(expected_count) is not int
        or expected_count < 0
    ):
        raise VocFactValidationError(
            "VOC facts metric-eligibility.jsonl binding is invalid"
        )
    relative = _private_parts(bundle_root, project_root, "VOC facts bundle")
    opened = _open_directory_chain(
        project_root,
        ("tmp", "reddit-voc-v3", *relative),
        private_from=1,
        label="VOC facts bundle",
    )
    descriptor: int | None = None
    try:
        descriptor = os.open(
            "metric-eligibility.jsonl", FILE_READ_FLAGS, dir_fd=opened[-1]
        )
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o600
        ):
            raise VocFactValidationError(
                "VOC facts metric-eligibility.jsonl must be a private regular file"
            )
        digest = hashlib.sha256()
        observed_bytes = 0
        observed_rows = 0
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = None
            for expected in expected_rows:
                observed = stream.readline()
                if not observed or not observed.endswith(b"\n"):
                    raise VocFactValidationError(
                        "metric eligibility ledger mismatch"
                    )
                digest.update(observed)
                observed_bytes += len(observed)
                observed_rows += 1
                if observed[:-1] != _canonical(expected):
                    raise VocFactValidationError(
                        "metric eligibility ledger mismatch"
                    )
            if stream.read(1):
                raise VocFactValidationError("metric eligibility ledger mismatch")
            after = os.fstat(stream.fileno())
        if (
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            or observed_bytes != before.st_size
            or observed_bytes != expected_bytes
            or observed_rows != expected_count
            or digest.hexdigest() != expected_sha
        ):
            raise VocFactValidationError(
                "VOC facts metric-eligibility.jsonl binding mismatch"
            )
        return observed_rows
    finally:
        if descriptor is not None:
            os.close(descriptor)
        for directory_fd in reversed(opened):
            os.close(directory_fd)


def _validate_policy(policy: Mapping[str, Any]) -> None:
    if set(policy) != {
        "boundaries",
        "comparison_sides",
        "indicators",
        "policy_version",
        "schema_version",
    }:
        raise VocFactValidationError("eligibility policy fields are invalid")
    if (
        policy.get("schema_version") != "reddit_voc_metric_eligibility_policy_v1"
        or policy.get("boundaries") != BOUNDARIES
        or not isinstance(policy.get("policy_version"), str)
        or not policy["policy_version"]
    ):
        raise VocFactValidationError("eligibility policy header is invalid")
    sides = policy.get("comparison_sides")
    if (
        not isinstance(sides, list)
        or not sides
        or any(not isinstance(side, str) or side not in COMPARISON_SIDES for side in sides)
        or len(sides) != len(set(sides))
    ):
        raise VocFactValidationError("eligibility policy comparison sides are invalid")
    indicators = policy.get("indicators")
    if not isinstance(indicators, list):
        raise VocFactValidationError("eligibility policy indicators are invalid")
    observed_ids: set[str] = set()
    for indicator in indicators:
        if not isinstance(indicator, dict) or set(indicator) != {
            "comparison_sides",
            "metric_family",
            "metric_member_type",
            "reddit_indicator_id",
            "required_source_use",
            "text_required",
            "voc_types",
        }:
            raise VocFactValidationError("eligibility indicator fields are invalid")
        indicator_id = indicator.get("reddit_indicator_id")
        if (
            not isinstance(indicator_id, str)
            or not indicator_id.isascii()
            or INDICATOR_ID.fullmatch(indicator_id) is None
            or indicator_id in observed_ids
        ):
            raise VocFactValidationError("eligibility indicator identity is invalid")
        observed_ids.add(indicator_id)
        if indicator.get("metric_family") != indicator_id.rsplit("-", 1)[0]:
            raise VocFactValidationError("eligibility metric family is invalid")
        indicator_sides = indicator.get("comparison_sides")
        if (
            not isinstance(indicator_sides, list)
            or not indicator_sides
            or any(side not in sides for side in indicator_sides)
            or len(indicator_sides) != len(set(indicator_sides))
        ):
            raise VocFactValidationError("eligibility indicator sides are invalid")
        voc_types = indicator.get("voc_types")
        if (
            not isinstance(voc_types, list)
            or not voc_types
            or any(value not in {"post_voc", "comment_context_voc"} for value in voc_types)
            or len(voc_types) != len(set(voc_types))
        ):
            raise VocFactValidationError("eligibility indicator VOC types are invalid")
        if indicator.get("metric_member_type") not in {
            "canonical_entity",
            "thread",
            "cluster",
            "event_dossier",
            "review_item",
        }:
            raise VocFactValidationError("eligibility metric member type is invalid")
        required_use = indicator.get("required_source_use")
        if required_use is not None and (not isinstance(required_use, str) or not required_use):
            raise VocFactValidationError("eligibility required source use is invalid")
        if type(indicator.get("text_required")) is not bool:
            raise VocFactValidationError("eligibility text requirement is invalid")
    if observed_ids != EXPECTED_INDICATOR_IDS:
        raise VocFactValidationError("eligibility indicator registry is incomplete")


def _rename_noreplace(parent_fd: int, source: str, target: str) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    encoded_source = os.fsencode(source)
    encoded_target = os.fsencode(target)
    if sys.platform == "darwin" and hasattr(libc, "renameatx_np"):
        function = libc.renameatx_np
        function.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        function.restype = ctypes.c_int
        result = function(
            parent_fd,
            encoded_source,
            parent_fd,
            encoded_target,
            0x00000004,
        )
    elif sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        function = libc.renameat2
        function.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        function.restype = ctypes.c_int
        result = function(
            parent_fd,
            encoded_source,
            parent_fd,
            encoded_target,
            1,
        )
    else:
        raise VocFactValidationError(
            "atomic no-replace validation receipt rename is unavailable"
        )
    if result == 0:
        return
    number = ctypes.get_errno()
    if number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise VocFactValidationError("validation receipt already exists")
    raise OSError(number, os.strerror(number))


def _write_receipt(path: Path, value: Mapping[str, object], project_root: Path) -> None:
    relative = _private_parts(path, project_root, "validation receipt")
    opened = _open_directory_chain(
        project_root,
        ("tmp", "reddit-voc-v3", *relative[:-1]),
        private_from=1,
        label="validation receipt parent",
    )
    parent_fd = opened[-1]
    target_name = relative[-1]
    payload = _canonical(dict(value)) + b"\n"
    blocker_name = _receipt_blocker_name(target_name)
    blocker_payload = _canonical(
        {
            "receipt_name": target_name,
            "schema_version": "reddit_voc_receipt_commit_blocker_v1",
            "status": "uncommitted",
        }
    ) + b"\n"
    staging_name = f".{target_name}.{uuid.uuid4().hex}.staging"
    blocker_fd: int | None = None
    stage_fd: int | None = None
    stage_identity: tuple[int, int] | None = None
    try:
        blocker_fd = os.open(
            blocker_name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent_fd,
        )
        os.fchmod(blocker_fd, 0o600)
        blocker_metadata = os.fstat(blocker_fd)
        if (
            not stat.S_ISREG(blocker_metadata.st_mode)
            or stat.S_IMODE(blocker_metadata.st_mode) != 0o600
        ):
            raise VocFactValidationError(
                "validation receipt commit blocker is invalid"
            )
        blocker_view = memoryview(blocker_payload)
        while blocker_view:
            written = os.write(blocker_fd, blocker_view)
            if written <= 0:
                raise OSError("receipt blocker write made no progress")
            blocker_view = blocker_view[written:]
        os.fsync(blocker_fd)
        os.close(blocker_fd)
        blocker_fd = None
        os.fsync(parent_fd)

        stage_fd = os.open(
            staging_name,
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent_fd,
        )
        os.fchmod(stage_fd, 0o600)
        metadata = os.fstat(stage_fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise VocFactValidationError("validation receipt stage is invalid")
        stage_identity = (metadata.st_dev, metadata.st_ino)
        view = memoryview(payload)
        while view:
            written = os.write(stage_fd, view)
            if written <= 0:
                raise OSError("receipt write made no progress")
            view = view[written:]
        os.fsync(stage_fd)
        os.fsync(parent_fd)
        _rename_noreplace(parent_fd, staging_name, target_name)
        os.fsync(parent_fd)
        target_fd = os.open(target_name, FILE_READ_FLAGS, dir_fd=parent_fd)
        try:
            target_before = os.fstat(target_fd)
            chunks: list[bytes] = []
            while True:
                chunk = os.read(target_fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            target_payload = b"".join(chunks)
            target_after = os.fstat(target_fd)
            if (
                (target_before.st_dev, target_before.st_ino) != stage_identity
                or not stat.S_ISREG(target_before.st_mode)
                or stat.S_IMODE(target_before.st_mode) != 0o600
                or target_before.st_size != len(payload)
                or (
                    target_before.st_dev,
                    target_before.st_ino,
                    target_before.st_size,
                    target_before.st_mtime_ns,
                )
                != (
                    target_after.st_dev,
                    target_after.st_ino,
                    target_after.st_size,
                    target_after.st_mtime_ns,
                )
                or target_payload != payload
            ):
                raise VocFactValidationError(
                    "validation receipt publish ownership changed"
                )
        finally:
            os.close(target_fd)
        # This is the commit point.  Every fallible durability and identity
        # check has completed while the deterministic blocker still existed.
        # After successful unlink, only descriptor closes remain and those are
        # deliberately non-raising.
        os.unlink(blocker_name, dir_fd=parent_fd)
    except VocFactValidationError:
        raise
    except OSError as exc:
        raise VocFactValidationError("validation receipt publish failed") from exc
    finally:
        if blocker_fd is not None:
            try:
                os.close(blocker_fd)
            except OSError:
                pass
        if stage_fd is not None:
            try:
                os.close(stage_fd)
            except OSError:
                pass
        # Failure deliberately leaves the deterministic blocker and any hidden
        # stage/target evidence.  No failure path performs pathname cleanup.
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                pass


def validate_voc_fact_bundle(
    *,
    bundle_root: Path,
    expected_manifest_sha256: str,
    canonical_root: Path,
    expected_canonical_manifest_sha256: str,
    canonical_validation_receipt: Path,
    expected_canonical_validation_receipt_sha256: str,
    eligibility_policy_path: Path,
    expected_eligibility_policy_sha256: str,
    automation_policy_path: Path | None = None,
    expected_automation_policy_sha256: str | None = None,
    project_root: Path,
    receipt_path: Path | None = None,
) -> ValidationReceipt:
    if (automation_policy_path is None) != (
        expected_automation_policy_sha256 is None
    ):
        raise VocFactValidationError(
            "automation policy path and SHA-256 must be supplied together"
        )
    a2_enabled = automation_policy_path is not None
    output_inventory = OUTPUT_FILES_A2 if a2_enabled else OUTPUT_FILES
    root = Path(os.path.abspath(os.fspath(project_root)))
    bundle_parts = _private_parts(bundle_root, root, "VOC facts bundle")
    canonical_parts = _private_parts(canonical_root, root, "canonical bundle")
    canonical_receipt_parts = _private_parts(
        canonical_validation_receipt,
        root,
        "canonical validation receipt",
    )
    for protected_parts in (canonical_parts, canonical_receipt_parts):
        if (
            bundle_parts[: len(protected_parts)] == protected_parts
            or protected_parts[: len(bundle_parts)] == bundle_parts
        ):
            raise VocFactValidationError(
                "VOC facts bundle must not overlap a bound canonical input path"
            )
    if canonical_receipt_parts[: len(canonical_parts)] == canonical_parts:
        raise VocFactValidationError(
            "canonical validation receipt must be outside the canonical bundle"
        )
    if receipt_path is not None:
        output_receipt_parts = _private_parts(
            receipt_path,
            root,
            "validation receipt",
        )
        for protected_label, protected_parts in (
            ("VOC bundle", bundle_parts),
            ("canonical bundle", canonical_parts),
            ("canonical validation receipt", canonical_receipt_parts),
        ):
            if (
                output_receipt_parts[: len(protected_parts)] == protected_parts
                or protected_parts[: len(output_receipt_parts)]
                == output_receipt_parts
            ):
                raise VocFactValidationError(
                    f"validation receipt must not overlap the {protected_label}"
                )
    bundle_raw_payloads = _read_private_bundle(
        bundle_root,
        expected_inventory=output_inventory,
        project_root=root,
        label="VOC facts bundle",
        selected_names=(
            output_inventory - {"metric-eligibility.jsonl"}
            if a2_enabled
            else None
        ),
    )
    manifest_payload = bundle_raw_payloads["manifest.json"]
    if _sha(manifest_payload) != _sha_value(expected_manifest_sha256, "VOC facts manifest SHA-256"):
        raise VocFactValidationError("VOC facts manifest hash binding mismatch")
    manifest = _object(manifest_payload, "VOC facts manifest")
    expected_manifest_fields = {
        "boundaries",
        "canonical_counts",
        "consumption_status",
        "counts",
        "dataset_id",
        "files",
        "independent_validation_status",
        "inputs",
        "period",
        "policy_version",
        "promotable",
        "schema_version",
        "scope",
        "status",
        "validation_receipt_sha256",
    }
    if a2_enabled:
        expected_manifest_fields.add("automation_policy_version")
    if set(manifest) != expected_manifest_fields:
        raise VocFactValidationError("VOC facts manifest fields are invalid")
    if (
        manifest["schema_version"]
        != f"reddit_voc_voc_facts_manifest_{'v2' if a2_enabled else 'v1'}"
        or manifest["status"] != "candidate_built"
        or manifest["independent_validation_status"] != "pending"
        or manifest["consumption_status"] != "blocked_pending_independent_validation"
        or manifest["promotable"] is not False
        or manifest["validation_receipt_sha256"] is not None
        or manifest["boundaries"] != BOUNDARIES
        or not isinstance(manifest.get("dataset_id"), str)
        or not manifest["dataset_id"].endswith(
            f"_voc_facts_{'v2' if a2_enabled else 'v1'}"
        )
        or not isinstance(manifest.get("period"), str)
        or not manifest["period"]
        or not isinstance(manifest.get("scope"), str)
        or not manifest["scope"]
    ):
        raise VocFactValidationError("VOC facts lifecycle is invalid")
    inputs = manifest.get("inputs")
    expected_inputs = {
        "canonical_manifest_sha256": _sha_value(
            expected_canonical_manifest_sha256, "canonical manifest SHA-256"
        ),
        "canonical_validation_receipt_sha256": _sha_value(
            expected_canonical_validation_receipt_sha256,
            "canonical validation receipt SHA-256",
        ),
        "eligibility_policy_sha256": _sha_value(
            expected_eligibility_policy_sha256, "eligibility policy SHA-256"
        ),
    }
    if a2_enabled:
        family_contract = {
            "audit_indicator_ids": list(AUTOMATION_AUDIT_INDICATORS),
            "exclude_indicator_families": list(AUTOMATION_FAMILIES),
        }
        if expected_automation_policy_sha256 is None:
            raise VocFactValidationError(
                "automation policy SHA-256 binding is missing"
            )
        expected_inputs.update(
            {
                "automation_family_contract_sha256": _sha(
                    _canonical(family_contract) + b"\n"
                ),
                "automation_policy_sha256": _sha_value(
                    expected_automation_policy_sha256,
                    "automation policy SHA-256",
                ),
                "canonical_comments_sha256": _sha_value(
                    inputs.get("canonical_comments_sha256")
                    if isinstance(inputs, dict)
                    else None,
                    "canonical comments SHA-256",
                ),
            }
        )
    if inputs != expected_inputs:
        raise VocFactValidationError("VOC facts input bindings mismatch")
    payloads = _bound_documents(
        bundle_raw_payloads,
        manifest,
        (
            output_inventory - {"manifest.json", "metric-eligibility.jsonl"}
            if a2_enabled
            else output_inventory - {"manifest.json"}
        ),
        "VOC facts",
        expected_manifest_names=output_inventory - {"manifest.json"},
    )

    canonical_raw_payloads = _read_private_bundle(
        canonical_root,
        expected_inventory=CANONICAL_FILES,
        project_root=root,
        label="canonical bundle",
    )
    canonical_manifest_payload = canonical_raw_payloads["manifest.json"]
    if _sha(canonical_manifest_payload) != expected_inputs["canonical_manifest_sha256"]:
        raise VocFactValidationError("canonical manifest hash mismatch")
    canonical_manifest = _object(canonical_manifest_payload, "canonical manifest")
    expected_canonical_manifest_fields = {
        "boundaries",
        "canonical_counts",
        "consumption_status",
        "dataset_id",
        "files",
        "governed_base_parent_lineage_debt",
        "independent_validation_status",
        "inputs",
        "promotable",
        "schema_version",
        "source_row_accounting",
        "state_contract",
        "status",
        "validation_receipt_sha256",
    }
    if set(canonical_manifest) != expected_canonical_manifest_fields or (
        canonical_manifest.get("schema_version") not in {
            "reddit_voc_canonical_snapshot_manifest_v1",
            "reddit_voc_canonical_snapshot_manifest_v2",
        }
        or canonical_manifest.get("status") != "candidate_built"
        or canonical_manifest.get("independent_validation_status") != "pending"
        or canonical_manifest.get("consumption_status") != "blocked_pending_independent_validation"
        or canonical_manifest.get("promotable") is not False
        or canonical_manifest.get("validation_receipt_sha256") is not None
        or canonical_manifest.get("boundaries") != BOUNDARIES
    ):
        raise VocFactValidationError("canonical manifest lifecycle is invalid")
    if manifest.get("canonical_counts") != canonical_manifest.get("canonical_counts"):
        raise VocFactValidationError("VOC facts canonical counts binding mismatch")
    canonical_payloads = _bound_documents(
        canonical_raw_payloads,
        canonical_manifest,
        CANONICAL_FILES - {"manifest.json"},
        "canonical",
    )
    canonical_comment_binding = canonical_manifest["files"].get("comments.jsonl")
    if (
        a2_enabled
        and (
            not isinstance(canonical_comment_binding, dict)
            or canonical_comment_binding.get("sha256")
            != expected_inputs["canonical_comments_sha256"]
        )
    ):
        raise VocFactValidationError("canonical comments input binding mismatch")
    receipt_payload = _read_private_receipt(
        canonical_validation_receipt,
        project_root=root,
        label="canonical validation receipt",
    )
    if _sha(receipt_payload) != expected_inputs["canonical_validation_receipt_sha256"]:
        raise VocFactValidationError("canonical validation receipt hash mismatch")
    canonical_receipt = _object(receipt_payload, "canonical validation receipt")
    expected_canonical_receipt_fields = {
        "boundaries",
        "bundle_manifest_sha256",
        "canonical_counts",
        "consumption_status",
        "inputs",
        "promotable",
        "schema_version",
        "source_row_accounting",
        "status",
        "unaccounted_canonical_identities",
        "unaccounted_foreign_keys",
    }
    source_accounting = canonical_manifest.get("source_row_accounting")
    expected_receipt_accounting = None
    if isinstance(source_accounting, dict):
        expected_receipt_accounting = {
            "source_rows": source_accounting.get("source_rows"),
            "terminal_outcomes": source_accounting.get("terminal_outcomes"),
        }
    if (
        set(canonical_receipt) != expected_canonical_receipt_fields
        or canonical_receipt.get("schema_version")
        != (
            "reddit_voc_canonical_snapshot_validation_receipt_v2"
            if canonical_manifest.get("schema_version")
            == "reddit_voc_canonical_snapshot_manifest_v2"
            else "reddit_voc_canonical_snapshot_validation_receipt_v1"
        )
        or canonical_receipt.get("status") != "passed"
        or canonical_receipt.get("bundle_manifest_sha256") != _sha(canonical_manifest_payload)
        or canonical_receipt.get("consumption_status") != "blocked_pending_voc_facts"
        or canonical_receipt.get("promotable") is not False
        or canonical_receipt.get("boundaries") != BOUNDARIES
        or type(canonical_receipt.get("unaccounted_canonical_identities")) is not int
        or canonical_receipt.get("unaccounted_canonical_identities") != 0
        or type(canonical_receipt.get("unaccounted_foreign_keys")) is not int
        or canonical_receipt.get("unaccounted_foreign_keys") != 0
        or canonical_receipt.get("canonical_counts") != canonical_manifest.get("canonical_counts")
        or canonical_receipt.get("inputs") != canonical_manifest.get("inputs")
        or canonical_receipt.get("source_row_accounting") != expected_receipt_accounting
    ):
        raise VocFactValidationError("canonical validation receipt is not consumable")

    policy_payload = _read_project_file(
        eligibility_policy_path,
        project_root=root,
        label="eligibility policy",
    )
    if _sha(policy_payload) != expected_inputs["eligibility_policy_sha256"]:
        raise VocFactValidationError("eligibility policy hash mismatch")
    policy = _object(policy_payload, "eligibility policy")
    _validate_policy(policy)
    if (
        manifest.get("policy_version") != policy.get("policy_version")
    ):
        raise VocFactValidationError("eligibility policy binding is invalid")

    automation_policy: dict[str, Any] | None = None
    if a2_enabled:
        if automation_policy_path is None:
            raise VocFactValidationError("automation policy path is missing")
        automation_policy_payload = _read_project_file(
            automation_policy_path,
            project_root=root,
            label="explicit automation policy",
        )
        if _sha(automation_policy_payload) != expected_inputs["automation_policy_sha256"]:
            raise VocFactValidationError("explicit automation policy hash mismatch")
        automation_policy_value = _object(
            automation_policy_payload, "explicit automation policy"
        )
        automation_policy = _automation_policy(
            automation_policy_value,
            _sha(automation_policy_payload),
        )
        if (
            automation_policy["family_contract_sha256"]
            != expected_inputs["automation_family_contract_sha256"]
            or manifest.get("automation_policy_version")
            != automation_policy["policy_version"]
        ):
            raise VocFactValidationError(
                "explicit automation policy binding is invalid"
            )

    canonical_posts = _jsonl(canonical_payloads["posts.jsonl"], "canonical posts")
    canonical_comments = _jsonl(
        canonical_payloads["comments.jsonl"], "canonical comments"
    )
    canonical_quarantine = _jsonl(
        canonical_payloads["quarantine.jsonl"], "canonical quarantine"
    )
    unresolved_ledger = _jsonl(
        canonical_payloads["unresolved-parent-ledger.jsonl"],
        "canonical unresolved parent ledger",
    )
    expected_vocs, expected_exclusions, computed_canonical_counts = _expected_materialization(
        canonical_posts,
        canonical_comments,
        canonical_quarantine,
        unresolved_ledger,
    )
    if canonical_manifest.get("canonical_counts") != computed_canonical_counts:
        raise VocFactValidationError("canonical counts do not reproduce canonical documents")
    observed_vocs = _jsonl(payloads["vocs.jsonl"], "VOC rows")
    if observed_vocs != expected_vocs:
        raise VocFactValidationError("VOC rows do not reproduce canonical entities")
    observed_exclusions = _jsonl(payloads["voc-exclusions.jsonl"], "VOC exclusions")
    if observed_exclusions != expected_exclusions:
        raise VocFactValidationError("VOC exclusions do not reproduce canonical-only debt")
    policy_with_context = dict(policy)
    policy_with_context["_period"] = manifest.get("period")
    policy_with_context["_scope"] = manifest.get("scope")
    automation_rows: list[dict[str, Any]] = []
    automation_ids: set[str] = set()
    automation_stats: dict[str, int] = {}
    if automation_policy is not None:
        automation_rows = _expected_automation(
            canonical_comments,
            automation_policy,
        )
        observed_automation = _jsonl(
            payloads["automation-classifications.jsonl"],
            "automation classifications",
        )
        if observed_automation != automation_rows:
            raise VocFactValidationError(
                "automation classifications do not reproduce canonical comments"
            )
        automation_ids = {
            row["canonical_entity_id"]
            for row in automation_rows
            if row["automation_determined"] is True
        }
        facts_files = manifest.get("files")
        if not isinstance(facts_files, dict):
            raise VocFactValidationError("VOC facts file bindings are invalid")
        eligibility_binding = facts_files.get("metric-eligibility.jsonl")
        if not isinstance(eligibility_binding, dict):
            raise VocFactValidationError(
                "VOC facts metric eligibility binding is invalid"
            )
        eligibility_row_count = _validate_private_eligibility_file(
            bundle_root,
            binding=eligibility_binding,
            expected_rows=_iter_expected_eligibility(
                expected_vocs,
                policy_with_context,
                automation_ids,
                automation_stats,
            ),
            project_root=root,
        )
    else:
        eligibility_row_count = _validate_eligibility_payload(
            payloads["metric-eligibility.jsonl"],
            _iter_expected_eligibility(expected_vocs, policy_with_context),
        )

    exclusion_reason_counts: dict[str, int] = {}
    for exclusion in expected_exclusions:
        for reason in exclusion["reason_codes"]:
            exclusion_reason_counts[reason] = exclusion_reason_counts.get(reason, 0) + 1
    counts = {
        "analysis_ready_comment_context_vocs": sum(
            row["voc_type"] == "comment_context_voc" and row["analysis_text_status"] == "ready"
            for row in expected_vocs
        ),
        "analysis_ready_post_vocs": sum(
            row["voc_type"] == "post_voc" and row["analysis_text_status"] == "ready"
            for row in expected_vocs
        ),
        "comment_context_vocs": sum(row["voc_type"] == "comment_context_voc" for row in expected_vocs),
        "excluded_analysis_text_incomplete": exclusion_reason_counts.get(
            "analysis_text_incomplete", 0
        ),
        "excluded_comment_identities": sum(
            row["entity_type"] == "comment" for row in expected_exclusions
        ),
        "excluded_post_identities": sum(
            row["entity_type"] == "post" for row in expected_exclusions
        ),
        "excluded_quarantined": exclusion_reason_counts.get("quarantined", 0),
        "excluded_root_post_context_incomplete": exclusion_reason_counts.get(
            "root_post_context_incomplete", 0
        ),
        "excluded_source_url_identity_conflict": exclusion_reason_counts.get(
            "source_url_identity_conflict", 0
        ),
        "excluded_unresolved_parent": exclusion_reason_counts.get(
            "unresolved_parent", 0
        ),
        "day_precision_vocs": sum(row["event_time_precision"] == "day" for row in expected_vocs),
        "eligibility_rows": eligibility_row_count,
        "instant_or_hour_precision_vocs": sum(
            row["event_time_precision"] in {"instant", "hour"} for row in expected_vocs
        ),
        "missing_event_time_vocs": sum(
            row["event_time_precision"] is None for row in expected_vocs
        ),
        "post_vocs": sum(row["voc_type"] == "post_voc" for row in expected_vocs),
        "total_vocs": len(expected_vocs),
    }
    if automation_policy is not None:
        voc_ids = {row["canonical_entity_id"] for row in expected_vocs}
        exclusion_by_id = {
            row["canonical_entity_id"]: set(row["reason_codes"])
            for row in expected_exclusions
        }
        automation_voc_ids = automation_ids & voc_ids
        non_voc_ids = automation_ids - voc_ids
        unresolved_ids = {
            row["canonical_entity_id"]
            for row in automation_rows
            if row["automation_determined"] is True
            and row["comment_state"] == "unresolved_parent"
        }
        linked_incomplete_ids = non_voc_ids - unresolved_ids
        if (
            unresolved_ids - non_voc_ids
            or non_voc_ids != unresolved_ids | linked_incomplete_ids
            or any(
                "root_post_context_incomplete"
                not in exclusion_by_id.get(entity_id, set())
                for entity_id in linked_incomplete_ids
            )
        ):
            raise VocFactValidationError(
                "non-VOC automation identities are not fully explained"
            )
        already = sum(row["was_already_excluded"] is True for row in automation_rows)
        newly = sum(row["newly_excluded"] is True for row in automation_rows)
        if already + newly != len(automation_ids):
            raise VocFactValidationError("automation accounting is not conserved")
        counts.update(
            {
                "automation_already_excluded": already,
                "automation_disclosure_detected": sum(
                    row["audit_disclosure_detected"] is True
                    for row in automation_rows
                ),
                "automation_linked": sum(
                    row["automation_determined"] is True
                    and row["comment_state"] == "linked"
                    for row in automation_rows
                ),
                "automation_newly_excluded": newly,
                "automation_non_voc": len(non_voc_ids),
                "automation_non_voc_linked_incomplete": len(linked_incomplete_ids),
                "automation_non_voc_unresolved": len(unresolved_ids),
                "automation_total": len(automation_ids),
                "automation_unresolved": sum(
                    row["automation_determined"] is True
                    and row["comment_state"] == "unresolved_parent"
                    for row in automation_rows
                ),
                "automation_voc": len(automation_voc_ids),
                "effective_business_rows_excluded_by_automation": automation_stats.get(
                    "effective_business_rows_excluded_by_automation", 0
                ),
                "effective_eligible_automation_rows": automation_stats.get(
                    "effective_eligible_automation_rows", 0
                ),
            }
        )
    if manifest.get("counts") != counts:
        raise VocFactValidationError("VOC facts counts are not conserved")
    receipt = ValidationReceipt(
        bundle_manifest_sha256=_sha(manifest_payload),
        canonical_manifest_sha256=_sha(canonical_manifest_payload),
        canonical_validation_receipt_sha256=_sha(receipt_payload),
        eligibility_policy_sha256=_sha(policy_payload),
        counts=counts,
        boundaries=dict(BOUNDARIES),
        automation_policy_sha256=(
            expected_inputs.get("automation_policy_sha256") if a2_enabled else None
        ),
        automation_family_contract_sha256=(
            expected_inputs.get("automation_family_contract_sha256")
            if a2_enabled
            else None
        ),
        canonical_comments_sha256=(
            expected_inputs.get("canonical_comments_sha256") if a2_enabled else None
        ),
        schema_version=(
            "reddit_voc_voc_facts_validation_receipt_v2"
            if a2_enabled
            else "reddit_voc_voc_facts_validation_receipt_v1"
        ),
    )
    if receipt_path is not None:
        _write_receipt(receipt_path, receipt.as_dict(), root)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Independently validate a Reddit VOC V3 facts candidate.")
    parser.add_argument("--bundle-root", required=True, type=Path)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--canonical-root", required=True, type=Path)
    parser.add_argument("--canonical-manifest-sha256", required=True)
    parser.add_argument("--canonical-validation-receipt", required=True, type=Path)
    parser.add_argument("--canonical-validation-receipt-sha256", required=True)
    parser.add_argument("--eligibility-policy", required=True, type=Path)
    parser.add_argument("--eligibility-policy-sha256", required=True)
    parser.add_argument("--automation-policy", type=Path)
    parser.add_argument("--automation-policy-sha256")
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--receipt-path", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        receipt = validate_voc_fact_bundle(
            bundle_root=arguments.bundle_root,
            expected_manifest_sha256=arguments.manifest_sha256,
            canonical_root=arguments.canonical_root,
            expected_canonical_manifest_sha256=arguments.canonical_manifest_sha256,
            canonical_validation_receipt=arguments.canonical_validation_receipt,
            expected_canonical_validation_receipt_sha256=arguments.canonical_validation_receipt_sha256,
            eligibility_policy_path=arguments.eligibility_policy,
            expected_eligibility_policy_sha256=arguments.eligibility_policy_sha256,
            automation_policy_path=arguments.automation_policy,
            expected_automation_policy_sha256=arguments.automation_policy_sha256,
            project_root=arguments.project_root,
            receipt_path=arguments.receipt_path,
        )
    except VocFactValidationError as exc:
        print(f"reddit_v3_voc_facts_validation_failed:{exc}", file=sys.stderr)
        return 1
    print((_canonical(receipt.as_dict()) + b"\n").decode("utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
