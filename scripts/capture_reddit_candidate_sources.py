#!/usr/bin/env python3
"""Capture allowlisted Reddit candidate inputs without mutating remote state.

Local external archives are copied only from an explicit relative-path
allowlist.  Tencent staging reports and their governed plans are captured over
one read-only SSH stdout stream after two matching observations.  The remote
helper never writes a file and this module never reads credential contents.
"""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import stat
import subprocess
from typing import Any, Callable, Iterable, Sequence


MANIFEST_SCHEMA_VERSION = "reddit_voc_candidate_source_freeze_v1"
REMOTE_SCHEMA_VERSION = "reddit_voc_candidate_remote_source_stream_v1"
REMOTE_ROOT = "/opt/reddit-voc-staging"
REMOTE_REPORT_NAMESPACE = "tencent_v2_reports"
REMOTE_PLAN_NAMESPACE = "tencent_v2_plans"
REPORT_BASENAMES = frozenset(
    {
        "search-lane-probe.json",
        "search-continuation-probe.json",
        "comment-repair-probe.json",
        "comment-reply-probe.json",
    }
)
PLAN_BASENAME_RE = re.compile(
    r"^v2-(?:search|search-cont|comment|reply)-task[1-9][0-9]*-plan\.json$"
)
NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
REMOTE_TARGET_RE = re.compile(
    r"^[a-z_][a-z0-9_-]{0,31}@[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REMOTE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
MAX_MEMBER_BYTES = 100_000_000
MAX_TOTAL_BYTES = 250_000_000
MAX_MEMBER_COUNT = 20_000
MAX_REMOTE_STDOUT_BYTES = 350_000_000
CAPTURE_COMPLETE_CUTOFF = "capture-complete"
LOCAL_FUSION_SUFFIXES = frozenset(
    {
        ".csv",
        ".db",
        ".json",
        ".jsonl",
        ".sqlite",
        ".sqlite3",
        ".xlsx",
        ".yaml",
        ".yml",
    }
)
REMOTE_SAFE_FAILURE_REASONS = frozenset(
    {
        "remote_capture_bound_exceeded",
        "remote_capture_empty",
        "remote_directory_unreadable",
        "remote_directory_unsafe",
        "remote_interval_invalid",
        "remote_member_unsafe",
        "remote_path_invalid",
        "remote_root_unsafe",
        "remote_source_drift",
        "remote_unclassified",
    }
)


class CandidateSourceCaptureError(ValueError):
    """An input changed, escaped its allowlist, or violated immutability."""


@dataclass(frozen=True)
class CapturedMember:
    source_namespace: str
    source_kind: str
    relative_path: str
    byte_count: int
    mtime_ns: int
    sha256: str
    content: bytes
    fusion_eligible: bool


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _utc(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise CandidateSourceCaptureError("source_cutoff_utc_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise CandidateSourceCaptureError("source_cutoff_utc_invalid")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _namespace(value: str) -> str:
    if not isinstance(value, str) or NAMESPACE_RE.fullmatch(value) is None:
        raise CandidateSourceCaptureError("source_namespace_invalid")
    if value in {REMOTE_REPORT_NAMESPACE, REMOTE_PLAN_NAMESPACE}:
        raise CandidateSourceCaptureError("source_namespace_reserved")
    return value


def _relative_path(value: str, *, remote: bool = False) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise CandidateSourceCaptureError("source_path_invalid")
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
        or pure.as_posix() != value
    ):
        raise CandidateSourceCaptureError("source_path_invalid")
    if remote and any(REMOTE_COMPONENT_RE.fullmatch(part) is None for part in pure.parts):
        raise CandidateSourceCaptureError("remote_source_path_invalid")
    return pure.as_posix()


def _ensure_root(root: Path) -> Path:
    try:
        metadata = os.lstat(root)
    except OSError as exc:
        raise CandidateSourceCaptureError("source_root_missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise CandidateSourceCaptureError("source_root_unsafe")
    return root.absolute()


def _read_regular_member(root: Path, relative: str) -> tuple[dict[str, Any], bytes]:
    current = root
    parts = PurePosixPath(relative).parts
    for index, part in enumerate(parts):
        current = current / part
        try:
            metadata = os.lstat(current)
        except OSError as exc:
            raise CandidateSourceCaptureError("source_member_missing") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise CandidateSourceCaptureError("source_member_unsafe")
        if index < len(parts) - 1:
            if not stat.S_ISDIR(metadata.st_mode):
                raise CandidateSourceCaptureError("source_member_unsafe")
        elif not stat.S_ISREG(metadata.st_mode):
            raise CandidateSourceCaptureError("source_member_unsafe")

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(current, flags)
    except OSError as exc:
        raise CandidateSourceCaptureError("source_member_unsafe") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_MEMBER_BYTES:
            raise CandidateSourceCaptureError("source_member_unsafe")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        len(content) != before.st_size
        or (before.st_dev, before.st_ino, before.st_mode, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_mode, after.st_size, after.st_mtime_ns)
    ):
        raise CandidateSourceCaptureError("source_drift")
    return (
        {
            "relative_path": relative,
            "bytes": before.st_size,
            "mtime_ns": before.st_mtime_ns,
            "mode": before.st_mode,
            "device": before.st_dev,
            "inode": before.st_ino,
            "sha256": _sha256_bytes(content),
        },
        content,
    )


def _observe_local(root: Path, paths: Sequence[str]) -> tuple[list[dict[str, Any]], dict[str, bytes]]:
    rows: list[dict[str, Any]] = []
    contents: dict[str, bytes] = {}
    total = 0
    for relative in paths:
        row, content = _read_regular_member(root, relative)
        rows.append(row)
        contents[relative] = content
        total += len(content)
        if total > MAX_TOTAL_BYTES:
            raise CandidateSourceCaptureError("source_total_bytes_exceeded")
    return rows, contents


def _local_role(relative: str) -> tuple[str, bool]:
    suffix = PurePosixPath(relative).suffix.lower()
    if suffix in LOCAL_FUSION_SUFFIXES:
        return "local_external_data", True
    if suffix == ".md":
        return "local_external_documentation", False
    raise CandidateSourceCaptureError("local_source_filename_invalid")


def capture_local_allowlist(
    source_namespace: str,
    source_root: Path,
    relative_paths: Sequence[str],
    *,
    between_observations: Callable[[], None] | None = None,
) -> list[CapturedMember]:
    """Read one external root twice and return only explicitly allowed members."""

    namespace = _namespace(source_namespace)
    root = _ensure_root(source_root)
    normalized = [_relative_path(value) for value in relative_paths]
    if not normalized:
        raise CandidateSourceCaptureError("source_allowlist_empty")
    if len(normalized) != len(set(normalized)):
        raise CandidateSourceCaptureError("source_allowlist_duplicate")
    normalized.sort()
    for relative in normalized:
        _local_role(relative)
    first, _ = _observe_local(root, normalized)
    if between_observations is not None:
        between_observations()
    second, contents = _observe_local(root, normalized)
    if first != second:
        raise CandidateSourceCaptureError("source_drift")
    result: list[CapturedMember] = []
    for row in second:
        relative = str(row["relative_path"])
        source_kind, fusion_eligible = _local_role(relative)
        result.append(
            CapturedMember(
                source_namespace=namespace,
                source_kind=source_kind,
                relative_path=relative,
                byte_count=int(row["bytes"]),
                mtime_ns=int(row["mtime_ns"]),
                sha256=str(row["sha256"]),
                content=contents[relative],
                fusion_eligible=fusion_eligible,
            )
        )
    return result


def _remote_role(relative: str, basename: str) -> tuple[str, str, bool]:
    pure = PurePosixPath(relative)
    if basename in REPORT_BASENAMES:
        if pure.parent.name != "reports":
            raise CandidateSourceCaptureError("remote_report_path_invalid")
        return REMOTE_REPORT_NAMESPACE, "remote_report", True
    if PLAN_BASENAME_RE.fullmatch(basename):
        if pure.parent.name == "reports":
            raise CandidateSourceCaptureError("remote_plan_path_invalid")
        return REMOTE_PLAN_NAMESPACE, "remote_plan", False
    raise CandidateSourceCaptureError("remote_source_filename_invalid")


def _validate_remote_row(row: object, *, content_required: bool) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise CandidateSourceCaptureError("remote_source_row_invalid")
    expected = {
        "relative_path",
        "basename",
        "role",
        "bytes",
        "mtime_ns",
        "mode",
        "device",
        "inode",
        "sha256",
    }
    if content_required:
        expected.add("content_base64")
    if set(row) != expected:
        raise CandidateSourceCaptureError("remote_source_row_invalid")
    relative = _relative_path(row["relative_path"], remote=True)
    basename = row["basename"]
    if not isinstance(basename, str) or PurePosixPath(relative).name != basename:
        raise CandidateSourceCaptureError("remote_source_filename_invalid")
    namespace, source_kind, fusion_eligible = _remote_role(relative, basename)
    expected_role = "report" if source_kind == "remote_report" else "plan"
    if row["role"] != expected_role:
        raise CandidateSourceCaptureError("remote_source_role_invalid")
    numeric_fields = ("bytes", "mtime_ns", "mode", "device", "inode")
    if any(isinstance(row[field], bool) or not isinstance(row[field], int) for field in numeric_fields):
        raise CandidateSourceCaptureError("remote_source_stat_invalid")
    if (
        row["bytes"] < 1
        or row["bytes"] > MAX_MEMBER_BYTES
        or row["mtime_ns"] < 0
        or row["device"] < 0
        or row["inode"] < 0
        or not stat.S_ISREG(row["mode"])
    ):
        raise CandidateSourceCaptureError("remote_source_member_unsafe")
    digest = row["sha256"]
    if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
        raise CandidateSourceCaptureError("remote_source_sha256_invalid")
    normalized = {
        "relative_path": relative,
        "basename": basename,
        "role": expected_role,
        "bytes": row["bytes"],
        "mtime_ns": row["mtime_ns"],
        "mode": row["mode"],
        "device": row["device"],
        "inode": row["inode"],
        "sha256": digest,
        "source_namespace": namespace,
        "source_kind": source_kind,
        "fusion_eligible": fusion_eligible,
    }
    if content_required:
        encoded = row["content_base64"]
        if not isinstance(encoded, str):
            raise CandidateSourceCaptureError("remote_source_content_invalid")
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise CandidateSourceCaptureError("remote_source_content_invalid") from exc
        if len(content) != row["bytes"] or _sha256_bytes(content) != digest:
            raise CandidateSourceCaptureError("remote_source_content_mismatch")
        normalized["content"] = content
    return normalized


def _remote_comparison(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row[key]
        for key in (
            "relative_path",
            "basename",
            "role",
            "bytes",
            "mtime_ns",
            "mode",
            "device",
            "inode",
            "sha256",
            "source_namespace",
            "source_kind",
            "fusion_eligible",
        )
    }


def validate_remote_payload(value: object) -> list[CapturedMember]:
    """Validate the complete stdout document before writing any captured byte."""

    if not isinstance(value, dict) or value.get("schema_version") != REMOTE_SCHEMA_VERSION:
        raise CandidateSourceCaptureError("remote_source_schema_invalid")
    if value.get("remote_root") != REMOTE_ROOT:
        raise CandidateSourceCaptureError("remote_source_root_invalid")
    interval = value.get("observation_interval_seconds")
    if isinstance(interval, bool) or not isinstance(interval, int) or not 1 <= interval <= 60:
        raise CandidateSourceCaptureError("remote_observation_interval_invalid")
    boundaries = value.get("boundaries")
    required_boundaries = {
        "provider_call",
        "provider_attempt_made",
        "remote_write",
        "database_write",
        "deploy",
        "live_send",
    }
    if (
        not isinstance(boundaries, dict)
        or not required_boundaries <= set(boundaries)
        or any(boundaries[field] is not False for field in boundaries)
    ):
        raise CandidateSourceCaptureError("remote_source_boundary_invalid")
    first_value = value.get("first_observation")
    second_value = value.get("second_observation")
    if not isinstance(first_value, list) or not isinstance(second_value, list):
        raise CandidateSourceCaptureError("remote_observation_invalid")
    if not first_value or len(first_value) > MAX_MEMBER_COUNT:
        raise CandidateSourceCaptureError("remote_observation_invalid")
    first = [_validate_remote_row(row, content_required=False) for row in first_value]
    second = [_validate_remote_row(row, content_required=True) for row in second_value]
    first_by_path = {row["relative_path"]: row for row in first}
    second_by_path = {row["relative_path"]: row for row in second}
    if len(first_by_path) != len(first) or len(second_by_path) != len(second):
        raise CandidateSourceCaptureError("remote_source_path_duplicate")
    if set(first_by_path) != set(second_by_path):
        raise CandidateSourceCaptureError("remote_source_drift")
    for relative in first_by_path:
        if _remote_comparison(first_by_path[relative]) != _remote_comparison(second_by_path[relative]):
            raise CandidateSourceCaptureError("remote_source_drift")
    if sum(int(row["bytes"]) for row in second) > MAX_TOTAL_BYTES:
        raise CandidateSourceCaptureError("remote_source_total_bytes_exceeded")
    return [
        CapturedMember(
            source_namespace=str(row["source_namespace"]),
            source_kind=str(row["source_kind"]),
            relative_path=str(row["relative_path"]),
            byte_count=int(row["bytes"]),
            mtime_ns=int(row["mtime_ns"]),
            sha256=str(row["sha256"]),
            content=row["content"],
            fusion_eligible=bool(row["fusion_eligible"]),
        )
        for row in sorted(second, key=lambda item: str(item["relative_path"]))
    ]


# This helper has a fixed root and fixed filename contracts.  It only reads
# regular files and emits one JSON document on stdout; it has no write call.
REMOTE_CAPTURE_CODE = r'''
import base64
import hashlib
import json
import os
import re
import stat
import sys
import time

ROOT = "/opt/reddit-voc-staging"
REPORT_NAMES = {
    "search-lane-probe.json",
    "search-continuation-probe.json",
    "comment-repair-probe.json",
    "comment-reply-probe.json",
}
PLAN_RE = re.compile(r"^v2-(?:search|search-cont|comment|reply)-task[1-9][0-9]*-plan\.json$")
COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
MAX_MEMBER_BYTES = 100000000
MAX_TOTAL_BYTES = 250000000
MAX_MEMBER_COUNT = 20000

def role_for(name):
    if name in REPORT_NAMES:
        return "report"
    if PLAN_RE.fullmatch(name):
        return "plan"
    return None

def read_file(path):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size < 1 or before.st_size > MAX_MEMBER_BYTES:
            raise RuntimeError("remote_member_unsafe")
        chunks = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(1048576, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if len(content) != before.st_size or (
        before.st_dev, before.st_ino, before.st_mode, before.st_size, before.st_mtime_ns
    ) != (
        after.st_dev, after.st_ino, after.st_mode, after.st_size, after.st_mtime_ns
    ):
        raise RuntimeError("remote_source_drift")
    return before, content

def observe(include_content):
    root_stat = os.lstat(ROOT)
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise RuntimeError("remote_root_unsafe")
    rows = []
    total = 0
    def walk_error(_error):
        raise RuntimeError("remote_directory_unreadable")
    for directory, directory_names, file_names in os.walk(
        ROOT, topdown=True, onerror=walk_error, followlinks=False
    ):
        directory_names.sort()
        file_names.sort()
        for name in directory_names:
            metadata = os.lstat(os.path.join(directory, name))
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise RuntimeError("remote_directory_unsafe")
        for name in file_names:
            path = os.path.join(directory, name)
            metadata = os.lstat(path)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise RuntimeError("remote_member_unsafe")
            role = role_for(name)
            if role is None:
                continue
            relative = os.path.relpath(path, ROOT)
            parts = relative.split("/")
            if (
                relative.startswith("/")
                or any(part in ("", ".", "..") or COMPONENT_RE.fullmatch(part) is None for part in parts)
                or (role == "report" and os.path.basename(os.path.dirname(path)) != "reports")
                or (role == "plan" and os.path.basename(os.path.dirname(path)) == "reports")
            ):
                raise RuntimeError("remote_path_invalid")
            current, content = read_file(path)
            if (metadata.st_dev, metadata.st_ino) != (current.st_dev, current.st_ino):
                raise RuntimeError("remote_source_drift")
            row = {
                "relative_path": relative,
                "basename": name,
                "role": role,
                "bytes": current.st_size,
                "mtime_ns": current.st_mtime_ns,
                "mode": current.st_mode,
                "device": current.st_dev,
                "inode": current.st_ino,
                "sha256": hashlib.sha256(content).hexdigest(),
            }
            if include_content:
                row["content_base64"] = base64.b64encode(content).decode("ascii")
            rows.append(row)
            total += len(content)
            if len(rows) > MAX_MEMBER_COUNT or total > MAX_TOTAL_BYTES:
                raise RuntimeError("remote_capture_bound_exceeded")
    if not rows:
        raise RuntimeError("remote_capture_empty")
    return rows

def comparison(rows):
    return [
        {key: value for key, value in row.items() if key != "content_base64"}
        for row in rows
    ]

try:
    interval = int(sys.argv[1])
    if interval < 1 or interval > 60:
        raise RuntimeError("remote_interval_invalid")
    first = observe(False)
    time.sleep(interval)
    second = observe(True)
    if comparison(first) != comparison(second):
        raise RuntimeError("remote_source_drift")
    value = {
        "schema_version": "reddit_voc_candidate_remote_source_stream_v1",
        "remote_root": ROOT,
        "observation_interval_seconds": interval,
        "first_observation": first,
        "second_observation": second,
        "boundaries": {
            "provider_call": False,
            "provider_attempt_made": False,
            "remote_write": False,
            "database_write": False,
            "deploy": False,
            "live_send": False,
        },
    }
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
except Exception as exc:
    reason = str(exc)
    allowed = {
        "remote_capture_bound_exceeded",
        "remote_capture_empty",
        "remote_directory_unreadable",
        "remote_directory_unsafe",
        "remote_interval_invalid",
        "remote_member_unsafe",
        "remote_path_invalid",
        "remote_root_unsafe",
        "remote_source_drift",
    }
    if reason not in allowed:
        reason = "remote_unclassified"
    print("candidate_source_capture_failed:" + reason, file=sys.stderr)
    raise SystemExit(2)
'''


def _credential_path(path: Path, *, error: str) -> Path:
    absolute = path.absolute()
    try:
        metadata = os.lstat(absolute)
    except OSError as exc:
        raise CandidateSourceCaptureError(error) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise CandidateSourceCaptureError(error)
    return absolute


def capture_remote_sources(
    *,
    remote: str,
    identity_file: Path,
    known_hosts_file: Path,
    observation_interval_seconds: int = 10,
) -> list[CapturedMember]:
    """Run the fixed remote reader over SSH and validate its stdout contract."""

    if (
        not isinstance(remote, str)
        or REMOTE_TARGET_RE.fullmatch(remote) is None
        or ".." in remote.split("@", 1)[1]
    ):
        raise CandidateSourceCaptureError("remote_target_invalid")
    if (
        isinstance(observation_interval_seconds, bool)
        or not isinstance(observation_interval_seconds, int)
        or not 1 <= observation_interval_seconds <= 60
    ):
        raise CandidateSourceCaptureError("remote_observation_interval_invalid")
    identity = _credential_path(identity_file, error="identity_file_unsafe")
    known_hosts = _credential_path(known_hosts_file, error="known_hosts_file_unsafe")
    remote_command = " ".join(
        (
            "sudo",
            "-n",
            "python3",
            "-c",
            shlex.quote(REMOTE_CAPTURE_CODE),
            str(observation_interval_seconds),
        )
    )
    result = subprocess.run(
        [
            "ssh",
            "-i",
            str(identity),
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            f"UserKnownHostsFile={known_hosts}",
            "-o",
            "ConnectTimeout=15",
            remote,
            remote_command,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=300,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        prefix = "candidate_source_capture_failed:"
        reason = stderr[len(prefix):] if stderr.startswith(prefix) else "remote_unclassified"
        if reason not in REMOTE_SAFE_FAILURE_REASONS:
            reason = "remote_unclassified"
        raise CandidateSourceCaptureError(f"remote_capture_failed:{reason}")
    if len(result.stdout) > MAX_REMOTE_STDOUT_BYTES:
        raise CandidateSourceCaptureError("remote_capture_stdout_too_large")
    try:
        payload = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateSourceCaptureError("remote_capture_output_invalid") from exc
    return validate_remote_payload(payload)


def _ensure_private_directory(path: Path) -> None:
    if path.exists() or path.is_symlink():
        metadata = os.lstat(path)
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise CandidateSourceCaptureError("destination_directory_unsafe")
        if stat.S_IMODE(metadata.st_mode) != 0o700:
            raise CandidateSourceCaptureError("destination_directory_mode_invalid")
        return
    path.mkdir(mode=0o700)
    os.chmod(path, 0o700)


def _ensure_private_tree(root: Path, destination: Path) -> None:
    _ensure_private_directory(root)
    relative = destination.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        _ensure_private_directory(current)


def _read_existing_private(path: Path) -> bytes:
    metadata = os.lstat(path)
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise CandidateSourceCaptureError("destination_member_unsafe")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            payload = handle.read(MAX_MEMBER_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(payload) > MAX_MEMBER_BYTES:
        raise CandidateSourceCaptureError("destination_member_unsafe")
    return payload


def _write_private_immutable(path: Path, payload: bytes, *, collision_error: str) -> str:
    if path.exists() or path.is_symlink():
        if _read_existing_private(path) != payload:
            raise CandidateSourceCaptureError(collision_error)
        return "no_change"
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        try:
            os.link(temporary, path)
        except FileExistsError:
            if _read_existing_private(path) != payload:
                raise CandidateSourceCaptureError(collision_error)
            return "no_change"
    finally:
        if temporary.exists():
            temporary.unlink()
    return "created"


def write_manifest(path: Path, value: dict[str, Any]) -> str:
    """Write one canonical LF-terminated immutable mode-0600 manifest."""

    _ensure_private_tree(path.parent, path.parent)
    return _write_private_immutable(
        path,
        _canonical_bytes(value) + b"\n",
        collision_error="manifest_immutable_collision",
    )


def _resolve_source_cutoff(value: str, output_root: Path) -> str:
    manifest_path = output_root.absolute() / "source-freeze-manifest.json"
    if manifest_path.exists() or manifest_path.is_symlink():
        try:
            existing = json.loads(_read_existing_private(manifest_path).decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise CandidateSourceCaptureError("manifest_existing_invalid") from exc
        if (
            not isinstance(existing, dict)
            or existing.get("schema_version") != MANIFEST_SCHEMA_VERSION
        ):
            raise CandidateSourceCaptureError("manifest_existing_invalid")
        existing_cutoff = _utc(existing.get("source_cutoff_utc"))
        if value != CAPTURE_COMPLETE_CUTOFF and _utc(value) != existing_cutoff:
            raise CandidateSourceCaptureError("source_cutoff_immutable_collision")
        return existing_cutoff
    if value != CAPTURE_COMPLETE_CUTOFF:
        raise CandidateSourceCaptureError("source_cutoff_requires_capture_complete")
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _private_tree_members(root: Path) -> tuple[set[str], set[str]]:
    files: set[str] = set()
    directories: set[str] = set()
    for directory, directory_names, file_names in os.walk(
        root, topdown=True, followlinks=False
    ):
        base = Path(directory)
        for name in directory_names:
            path = base / name
            metadata = os.lstat(path)
            if (
                stat.S_ISLNK(metadata.st_mode)
                or not stat.S_ISDIR(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o700
            ):
                raise CandidateSourceCaptureError("destination_tree_unsafe")
            directories.add(path.relative_to(root).as_posix())
        for name in file_names:
            path = base / name
            metadata = os.lstat(path)
            if (
                stat.S_ISLNK(metadata.st_mode)
                or not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o600
            ):
                raise CandidateSourceCaptureError("destination_tree_unsafe")
            files.add(path.relative_to(root).as_posix())
    return files, directories


def _expected_directories(relative_files: Iterable[str]) -> set[str]:
    directories: set[str] = set()
    for relative in relative_files:
        parent = PurePosixPath(relative).parent
        while parent != PurePosixPath("."):
            directories.add(parent.as_posix())
            parent = parent.parent
    return directories


def _validate_materialized_tree(
    root: Path,
    *,
    manifest_payload: bytes,
    rows: Sequence[dict[str, Any]],
    members_by_destination: dict[str, CapturedMember],
) -> None:
    expected_files = {
        "source-freeze-manifest.json",
        *(str(row["destination_relative_path"]) for row in rows),
    }
    actual_files, actual_directories = _private_tree_members(root)
    if actual_files != expected_files or actual_directories != _expected_directories(
        expected_files
    ):
        raise CandidateSourceCaptureError("destination_tree_set_mismatch")
    if _read_existing_private(root / "source-freeze-manifest.json") != manifest_payload:
        raise CandidateSourceCaptureError("manifest_immutable_collision")
    for relative, member in members_by_destination.items():
        payload = _read_existing_private(root / relative)
        if len(payload) != member.byte_count or _sha256_bytes(payload) != member.sha256:
            raise CandidateSourceCaptureError("destination_member_content_mismatch")


def _manifest_row(member: CapturedMember) -> dict[str, Any]:
    destination = PurePosixPath("sources") / member.source_namespace / member.relative_path
    return {
        "source_namespace": member.source_namespace,
        "source_kind": member.source_kind,
        "relative_path": member.relative_path,
        "destination_relative_path": destination.as_posix(),
        "bytes": member.byte_count,
        "mtime_ns": member.mtime_ns,
        "sha256": member.sha256,
        "fusion_eligible": member.fusion_eligible,
    }


def materialize_source_freeze(
    output_root: Path,
    *,
    source_cutoff_utc: str,
    members: Iterable[CapturedMember],
) -> tuple[dict[str, Any], str]:
    """Copy captured bytes and publish one immutable canonical manifest."""

    root = output_root.absolute()
    _ensure_private_directory(root)
    ordered = sorted(members, key=lambda item: (item.source_namespace, item.relative_path))
    if not ordered:
        raise CandidateSourceCaptureError("source_freeze_empty")
    if len(ordered) > MAX_MEMBER_COUNT:
        raise CandidateSourceCaptureError("source_member_count_exceeded")
    keys = [(item.source_namespace, item.relative_path) for item in ordered]
    if len(keys) != len(set(keys)):
        raise CandidateSourceCaptureError("source_member_duplicate")
    if sum(item.byte_count for item in ordered) > MAX_TOTAL_BYTES:
        raise CandidateSourceCaptureError("source_total_bytes_exceeded")

    rows: list[dict[str, Any]] = []
    members_by_destination: dict[str, CapturedMember] = {}
    for member in ordered:
        if NAMESPACE_RE.fullmatch(member.source_namespace) is None:
            raise CandidateSourceCaptureError("source_namespace_invalid")
        relative = _relative_path(member.relative_path, remote=member.source_kind.startswith("remote_"))
        if (
            len(member.content) != member.byte_count
            or _sha256_bytes(member.content) != member.sha256
        ):
            raise CandidateSourceCaptureError("captured_member_content_mismatch")
        row = _manifest_row(member)
        destination_relative = str(row["destination_relative_path"])
        members_by_destination[destination_relative] = member
        rows.append(row)

    aggregate = "".join(
        f"{row['source_namespace']}|{row['relative_path']}|{row['bytes']}|"
        f"{row['mtime_ns']}|{row['sha256']}|{str(row['fusion_eligible']).lower()}\n"
        for row in rows
    ).encode("utf-8")
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "source_cutoff_utc": _utc(source_cutoff_utc),
        "raw_payload_embedded_in_manifest": False,
        "quiescence_evidence": {
            "double_observation_member_stat_sha_verified": True,
            "mtime_compared_as_integer_ns": True,
        },
        "file_count": len(rows),
        "fusion_eligible_file_count": sum(bool(row["fusion_eligible"]) for row in rows),
        "documentation_file_count": sum(
            row["source_kind"] == "local_external_documentation" for row in rows
        ),
        "total_bytes": sum(int(row["bytes"]) for row in rows),
        "file_manifest_lf_sha256": _sha256_bytes(aggregate),
        "files": rows,
        "boundaries": {
            "provider_call": False,
            "provider_attempt_made": False,
            "remote_write": False,
            "database_write": False,
            "deploy": False,
            "live_send": False,
        },
    }
    manifest_path = root / "source-freeze-manifest.json"
    manifest_payload = _canonical_bytes(manifest) + b"\n"
    manifest_exists = manifest_path.exists() or manifest_path.is_symlink()
    if manifest_exists:
        if _read_existing_private(manifest_path) != manifest_payload:
            raise CandidateSourceCaptureError("manifest_immutable_collision")
        _validate_materialized_tree(
            root,
            manifest_payload=manifest_payload,
            rows=rows,
            members_by_destination=members_by_destination,
        )
        return manifest, "no_change"

    existing_files, existing_directories = _private_tree_members(root)
    if existing_files or existing_directories:
        raise CandidateSourceCaptureError("destination_tree_without_manifest")
    for relative, member in members_by_destination.items():
        destination = root / relative
        _ensure_private_tree(root, destination.parent)
        _write_private_immutable(
            destination,
            member.content,
            collision_error="destination_immutable_collision",
        )
    status = write_manifest(manifest_path, manifest)
    _validate_materialized_tree(
        root,
        manifest_payload=manifest_payload,
        rows=rows,
        members_by_destination=members_by_destination,
    )
    return manifest, status


def _assignment(value: str, *, label: str) -> tuple[str, str]:
    namespace, separator, remainder = value.partition("=")
    if not separator or not remainder:
        raise argparse.ArgumentTypeError(f"{label} must be NAMESPACE=VALUE")
    return namespace, remainder


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--source-cutoff-utc",
        required=True,
        help=(
            "UTC cutoff or 'capture-complete' to timestamp the first freeze after "
            "all observations; exact reruns reuse the existing immutable cutoff"
        ),
    )
    parser.add_argument(
        "--local-root",
        type=lambda value: _assignment(value, label="local root"),
        action="append",
        default=[],
        metavar="NAMESPACE=PATH",
    )
    parser.add_argument(
        "--local-allowlist",
        type=lambda value: _assignment(value, label="local allowlist"),
        action="append",
        default=[],
        metavar="NAMESPACE=RELATIVE_PATH",
    )
    parser.add_argument("--remote")
    parser.add_argument("--identity-file", type=Path)
    parser.add_argument("--known-hosts-file", type=Path)
    parser.add_argument("--remote-observation-interval-seconds", type=int, default=10)
    return parser


def main() -> int:
    args = _parser().parse_args()
    roots: dict[str, Path] = {}
    for namespace, raw_root in args.local_root:
        normalized = _namespace(namespace)
        if normalized in roots:
            raise CandidateSourceCaptureError("local_root_duplicate")
        roots[normalized] = Path(raw_root)
    allowed: dict[str, list[str]] = {namespace: [] for namespace in roots}
    for namespace, relative in args.local_allowlist:
        if namespace not in roots:
            raise CandidateSourceCaptureError("local_allowlist_root_missing")
        allowed[namespace].append(relative)

    members: list[CapturedMember] = []
    for namespace in sorted(roots):
        members.extend(capture_local_allowlist(namespace, roots[namespace], allowed[namespace]))
    if args.remote is not None:
        if args.identity_file is None or args.known_hosts_file is None:
            raise CandidateSourceCaptureError("remote_credentials_missing")
        members.extend(
            capture_remote_sources(
                remote=args.remote,
                identity_file=args.identity_file,
                known_hosts_file=args.known_hosts_file,
                observation_interval_seconds=args.remote_observation_interval_seconds,
            )
        )
    source_cutoff_utc = _resolve_source_cutoff(
        args.source_cutoff_utc, args.output_root
    )
    manifest, status = materialize_source_freeze(
        args.output_root,
        source_cutoff_utc=source_cutoff_utc,
        members=members,
    )
    manifest_path = args.output_root.absolute() / "source-freeze-manifest.json"
    print(
        json.dumps(
            {
                "schema_version": "reddit_voc_candidate_source_freeze_receipt_v1",
                "status": status,
                "output_root": str(args.output_root.absolute()),
                "manifest_sha256": _sha256_bytes(manifest_path.read_bytes()),
                "source_cutoff_utc": manifest["source_cutoff_utc"],
                "file_count": manifest["file_count"],
                "fusion_eligible_file_count": manifest["fusion_eligible_file_count"],
                "documentation_file_count": manifest["documentation_file_count"],
                "provider_call": False,
                "remote_write": False,
                "database_write": False,
                "deploy": False,
                "live_send": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
