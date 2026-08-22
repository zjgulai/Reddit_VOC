#!/usr/bin/env python3
"""Independently validate one private Reddit VOC V3 canonical snapshot.

This module intentionally does not import the canonical snapshot builder.  It
re-opens the published bytes, validates the complete private bundle contract,
and only then may write an immutable validation receipt.
"""

from __future__ import annotations

import argparse
from collections import Counter
import ctypes
from dataclasses import dataclass
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import sys
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit


EXPECTED_FILES = {
    "comments.jsonl",
    "conflict-ledger.jsonl",
    "manifest.json",
    "posts.jsonl",
    "provenance-ledger.jsonl",
    "quarantine.jsonl",
    "unresolved-parent-ledger.jsonl",
}
JSONL_FILES = EXPECTED_FILES - {"manifest.json"}
INPUT_KEYS_V1 = {
    "base_lineage_manifest_sha256",
    "base_public_manifest_sha256",
    "source_manifest_sha256",
    "workbook_import_manifest_sha256",
    "workbook_import_validation_receipt_sha256",
}
INPUT_KEYS_V2 = {
    "center_orchestration_receipt_sha256",
    "center_state_sha256",
    "latest_source_batch_manifest_sha256",
    "latest_source_batch_validation_receipt_sha256",
    "previous_canonical_manifest_sha256",
    "previous_canonical_validation_receipt_sha256",
}
BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}
COMMENT_STATES = ["linked", "unresolved_parent", "quarantined"]
TERMINAL_OUTCOMES = {
    "duplicate",
    "exact_base_overlap",
    "identity_conflict",
    "incomplete_text",
    "net_new_text_ready",
    "unresolved_parent",
}
RECEIPT_KEYS = {
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
BARE_ID = re.compile(r"[a-z0-9]+", re.ASCII)
SHA256 = re.compile(r"[0-9a-f]{64}", re.ASCII)


class CanonicalSnapshotValidationError(ValueError):
    """The canonical snapshot failed an independent, fail-closed check."""


@dataclass(frozen=True)
class CanonicalValidationReceipt:
    schema_version: str
    status: str
    bundle_manifest_sha256: str
    inputs: dict[str, str]
    canonical_counts: dict[str, int]
    source_row_accounting: dict[str, object]
    unaccounted_canonical_identities: int
    unaccounted_foreign_keys: int
    boundaries: dict[str, bool]
    consumption_status: str
    promotable: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "boundaries": dict(self.boundaries),
            "bundle_manifest_sha256": self.bundle_manifest_sha256,
            "canonical_counts": dict(self.canonical_counts),
            "consumption_status": self.consumption_status,
            "inputs": dict(self.inputs),
            "promotable": self.promotable,
            "schema_version": self.schema_version,
            "source_row_accounting": self.source_row_accounting,
            "status": self.status,
            "unaccounted_canonical_identities": self.unaccounted_canonical_identities,
            "unaccounted_foreign_keys": self.unaccounted_foreign_keys,
        }


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
        raise CanonicalSnapshotValidationError("value is not canonical JSON") from exc


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _require_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.isascii():
        raise CanonicalSnapshotValidationError(f"{label} must be a lowercase SHA-256 digest")
    if not SHA256.fullmatch(value):
        raise CanonicalSnapshotValidationError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _reject_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CanonicalSnapshotValidationError(f"duplicate JSON key:{key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise CanonicalSnapshotValidationError(f"non-finite JSON number:{value}")


def _parse_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise CanonicalSnapshotValidationError(f"non-finite JSON number:{value}")
    return result


def _decode(payload: bytes, label: str) -> object:
    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_pairs,
            parse_constant=_reject_constant,
            parse_float=_parse_float,
        )
    except CanonicalSnapshotValidationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, OverflowError, ValueError) as exc:
        raise CanonicalSnapshotValidationError(f"{label} is not valid JSON") from exc


def _json_document(payload: bytes, label: str) -> dict[str, Any]:
    value = _decode(payload, label)
    if not isinstance(value, dict):
        raise CanonicalSnapshotValidationError(f"{label} must be a JSON object")
    if payload != _canonical_bytes(value) + b"\n":
        raise CanonicalSnapshotValidationError(f"{label} is not canonical JSON")
    return value


def _jsonl(payload: bytes, label: str) -> list[dict[str, Any]]:
    if payload and not payload.endswith(b"\n"):
        raise CanonicalSnapshotValidationError(f"{label} must end with newline")
    rows: list[dict[str, Any]] = []
    for ordinal, line in enumerate(payload.splitlines(), start=1):
        if not line:
            raise CanonicalSnapshotValidationError(f"{label} contains a blank row")
        value = _decode(line, f"{label}:{ordinal}")
        if not isinstance(value, dict):
            raise CanonicalSnapshotValidationError(f"{label}:{ordinal} must be an object")
        if line != _canonical_bytes(value):
            raise CanonicalSnapshotValidationError(f"{label}:{ordinal} is not canonical JSON")
        rows.append(value)
    return rows


def _exact_keys(value: Mapping[str, object], expected: Iterable[str], label: str) -> None:
    actual = set(value)
    target = set(expected)
    if actual != target:
        raise CanonicalSnapshotValidationError(
            f"{label} keys mismatch:missing={sorted(target-actual)}:extra={sorted(actual-target)}"
        )


def _nonnegative_int(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise CanonicalSnapshotValidationError(f"{label} must be a nonnegative integer")
    return value


def _private_parts(path: Path, project_root: Path, label: str) -> tuple[Path, tuple[str, ...]]:
    try:
        root = project_root.resolve(strict=True)
    except (FileNotFoundError, RuntimeError) as exc:
        raise CanonicalSnapshotValidationError("project root is unavailable") from exc
    private_root = root / "tmp/reddit-voc-v3"
    candidate = path if path.is_absolute() else root / path
    candidate = Path(os.path.abspath(os.fspath(candidate)))
    try:
        relative = candidate.relative_to(private_root)
    except ValueError as exc:
        raise CanonicalSnapshotValidationError(f"{label} must be under tmp/reddit-voc-v3") from exc
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise CanonicalSnapshotValidationError(f"{label} is unsafe")
    return private_root, relative.parts


def _open_directory_at(parent_fd: int, name: str, label: str) -> int:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
    except OSError as exc:
        raise CanonicalSnapshotValidationError(f"{label} unavailable or unsafe") from exc
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700:
        os.close(descriptor)
        raise CanonicalSnapshotValidationError(f"{label} must be a private directory with mode 0700")
    return descriptor


def _open_project_private_root(project_root: Path) -> list[int]:
    try:
        root = project_root.resolve(strict=True)
    except (FileNotFoundError, RuntimeError) as exc:
        raise CanonicalSnapshotValidationError("project root is unavailable") from exc
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    opened: list[int] = []
    try:
        descriptor = os.open(os.fspath(root), flags)
        opened.append(descriptor)
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise CanonicalSnapshotValidationError("project root must be a directory")
        try:
            descriptor = os.open("tmp", flags, dir_fd=descriptor)
        except OSError as exc:
            raise CanonicalSnapshotValidationError("project tmp directory unavailable or unsafe") from exc
        opened.append(descriptor)
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise CanonicalSnapshotValidationError("project tmp must be a directory")
        try:
            descriptor = os.open("reddit-voc-v3", flags, dir_fd=descriptor)
        except OSError as exc:
            raise CanonicalSnapshotValidationError("private root unavailable or unsafe") from exc
        opened.append(descriptor)
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700:
            raise CanonicalSnapshotValidationError("private root must have mode 0700")
        return opened
    except Exception:
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise


def _open_private_directory(path: Path, project_root: Path, label: str) -> tuple[int, list[int]]:
    _, parts = _private_parts(path, project_root, label)
    opened = _open_project_private_root(project_root)
    try:
        descriptor = opened[-1]
        for index, part in enumerate(parts):
            descriptor = _open_directory_at(
                descriptor,
                part,
                label if index == len(parts) - 1 else f"{label} parent",
            )
            opened.append(descriptor)
        return opened[-1], opened
    except Exception:
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise


def _read_regular_at(directory_fd: int, name: str, label: str) -> bytes:
    if name in {"", ".", ".."} or "/" in name or "\\" in name:
        raise CanonicalSnapshotValidationError(f"unsafe bundle member:{label}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=directory_fd)
    except OSError as exc:
        raise CanonicalSnapshotValidationError(f"{label} unavailable or unsafe") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise CanonicalSnapshotValidationError(f"{label} must be a regular file")
        if stat.S_IMODE(before.st_mode) != 0o600:
            raise CanonicalSnapshotValidationError(f"{label} must have private mode 0600")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        if before_identity != after_identity:
            raise CanonicalSnapshotValidationError(f"{label} changed while being read")
        payload = b"".join(chunks)
        if len(payload) != after.st_size:
            raise CanonicalSnapshotValidationError(f"{label} byte count changed while being read")
        return payload
    finally:
        os.close(descriptor)


def _read_bundle(bundle_root: Path, project_root: Path) -> tuple[dict[str, Any], bytes, dict[str, bytes]]:
    bundle_fd, opened = _open_private_directory(bundle_root, project_root, "canonical bundle")
    try:
        inventory = set(os.listdir(bundle_fd))
        if inventory != EXPECTED_FILES:
            raise CanonicalSnapshotValidationError(
                f"canonical bundle inventory mismatch:missing={sorted(EXPECTED_FILES-inventory)}:extra={sorted(inventory-EXPECTED_FILES)}"
            )
        payloads = {
            name: _read_regular_at(bundle_fd, name, f"canonical bundle {name}")
            for name in sorted(EXPECTED_FILES)
        }
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)
    manifest_payload = payloads["manifest.json"]
    return _json_document(manifest_payload, "canonical manifest"), manifest_payload, payloads


def _canonical_bare(value: object, prefix: str, label: str) -> str:
    if not isinstance(value, str) or not value.isascii():
        raise CanonicalSnapshotValidationError(f"{label} must be an ASCII Reddit identity")
    normalized = value.lower()
    bare = normalized[len(prefix) :] if normalized.startswith(prefix) else normalized
    if not BARE_ID.fullmatch(bare):
        raise CanonicalSnapshotValidationError(f"{label} is not a valid Reddit identity")
    return bare


def _canonical_fullname(value: object, prefix: str, label: str) -> str:
    bare = _canonical_bare(value, prefix, label)
    canonical = f"{prefix}{bare}"
    if value != canonical:
        raise CanonicalSnapshotValidationError(f"{label} is not canonical")
    return canonical


def _canonical_post_id(value: object, label: str) -> str:
    bare = _canonical_bare(value, "t3_", label)
    if value != bare:
        raise CanonicalSnapshotValidationError(f"{label} must be a canonical bare post ID")
    return bare


def _reddit_identity_from_url(value: object, entity_type: str, label: str) -> tuple[str, str | None]:
    if not isinstance(value, str) or not value:
        raise CanonicalSnapshotValidationError(f"{label} source URL is missing")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
    except (UnicodeError, ValueError) as exc:
        raise CanonicalSnapshotValidationError(f"{label} source URL is invalid") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not isinstance(host, str)
        or not host.isascii()
        or host.casefold() not in {"reddit.com", "www.reddit.com", "old.reddit.com"}
    ):
        raise CanonicalSnapshotValidationError(f"{label} source URL host is invalid")
    # Identity segments are parsed from the raw URL path.  Percent-encoded IDs
    # or encoded separators are not alternate canonical Reddit identities.
    parts = [part for part in parsed.path.split("/") if part]
    try:
        index = parts.index("comments")
        raw_post_id = parts[index + 1]
    except (ValueError, IndexError) as exc:
        raise CanonicalSnapshotValidationError(f"{label} source URL lacks a post identity") from exc
    post_id = _canonical_post_id(raw_post_id, f"{label} URL post_id")
    if entity_type == "post":
        return post_id, None
    tail = [part for part in parts[index + 2 :] if part.casefold() != "comment"]
    if not tail:
        raise CanonicalSnapshotValidationError(f"{label} source URL lacks a comment identity")
    comment_id = _canonical_bare(tail[-1], "t1_", f"{label} URL comment_id")
    if tail[-1] != comment_id:
        raise CanonicalSnapshotValidationError(f"{label} URL comment_id is not canonical")
    return post_id, comment_id


def _validate_record_identity(
    row: Mapping[str, object],
    canonical_id: str,
    post_id: str,
    authority: str,
    entity_type: str,
    label: str,
) -> dict[str, Any]:
    record = row.get("record")
    if not isinstance(record, dict):
        raise CanonicalSnapshotValidationError(f"{label} record must be an object")
    if entity_type == "post":
        if _canonical_post_id(record.get("post_id"), f"{label} record post_id") != post_id:
            raise CanonicalSnapshotValidationError(f"{label} record post identity mismatch")
        if record.get("reddit_id") is not None:
            if _canonical_fullname(record.get("reddit_id"), "t3_", f"{label} record reddit_id") != canonical_id:
                raise CanonicalSnapshotValidationError(f"{label} record Reddit identity mismatch")
        if authority == "workbook_net_new" and record.get("comment_id") is not None:
            raise CanonicalSnapshotValidationError(f"{label} workbook post comment_id must be null")
    else:
        if _canonical_fullname(record.get("comment_id"), "t1_", f"{label} record comment_id") != canonical_id:
            raise CanonicalSnapshotValidationError(f"{label} record comment identity mismatch")
        if record.get("reddit_id") is not None:
            if _canonical_fullname(record.get("reddit_id"), "t1_", f"{label} record reddit_id") != canonical_id:
                raise CanonicalSnapshotValidationError(f"{label} record Reddit identity mismatch")
        if _canonical_post_id(record.get("post_id"), f"{label} record post_id") != post_id:
            raise CanonicalSnapshotValidationError(f"{label} record post identity mismatch")
    if authority == "workbook_net_new":
        if record.get("canonical_reddit_id") != canonical_id or record.get("entity_type") != entity_type:
            raise CanonicalSnapshotValidationError(f"{label} workbook record identity mismatch")
        occurrences = record.get("source_occurrences")
        if not isinstance(occurrences, list) or not occurrences or any(not isinstance(item, dict) for item in occurrences):
            raise CanonicalSnapshotValidationError(f"{label} workbook record lacks source occurrences")
    return record


def _validate_posts(rows: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], set[str]]:
    expected_keys = {
        "canonical_identity_state",
        "canonical_reddit_id",
        "entity_type",
        "post_id",
        "record",
        "record_authority",
        "schema_version",
    }
    result: dict[str, dict[str, Any]] = {}
    post_ids: set[str] = set()
    ordered: list[str] = []
    for ordinal, row in enumerate(rows, start=1):
        label = f"posts.jsonl:{ordinal}"
        _exact_keys(row, expected_keys, label)
        canonical_id = _canonical_fullname(row["canonical_reddit_id"], "t3_", f"{label} canonical_reddit_id")
        post_id = _canonical_post_id(row["post_id"], f"{label} post_id")
        if canonical_id != f"t3_{post_id}":
            raise CanonicalSnapshotValidationError(f"{label} post identity mismatch")
        authority = row["record_authority"]
        if authority not in {"governed_base", "workbook_net_new"}:
            raise CanonicalSnapshotValidationError(f"{label} record authority is invalid")
        if row["canonical_identity_state"] != "canonical_identity" or row["entity_type"] != "post":
            raise CanonicalSnapshotValidationError(f"{label} canonical state is invalid")
        if row["schema_version"] != "reddit_voc_canonical_post_v1":
            raise CanonicalSnapshotValidationError(f"{label} schema is invalid")
        _validate_record_identity(row, canonical_id, post_id, authority, "post", label)
        if canonical_id in result or post_id in post_ids:
            raise CanonicalSnapshotValidationError("posts.jsonl contains duplicate identities")
        result[canonical_id] = row
        post_ids.add(post_id)
        ordered.append(canonical_id)
    if ordered != sorted(ordered):
        raise CanonicalSnapshotValidationError("posts.jsonl is not canonically sorted")
    return result, post_ids


def _validate_comments(
    rows: list[dict[str, Any]],
    post_ids: set[str],
    *,
    allow_governed_unresolved: bool = False,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    base_keys = {
        "canonical_identity_state",
        "canonical_reddit_id",
        "comment_state",
        "entity_type",
        "post_id",
        "record",
        "record_authority",
        "schema_version",
    }
    result: dict[str, dict[str, Any]] = {}
    comment_posts: dict[str, str] = {}
    ordered: list[str] = []
    for ordinal, row in enumerate(rows, start=1):
        label = f"comments.jsonl:{ordinal}"
        authority = row.get("record_authority")
        expected = base_keys | ({"immediate_parent_resolution"} if authority == "governed_base" else set())
        _exact_keys(row, expected, label)
        canonical_id = _canonical_fullname(row["canonical_reddit_id"], "t1_", f"{label} canonical_reddit_id")
        post_id = _canonical_post_id(row["post_id"], f"{label} post_id")
        state = row["comment_state"]
        if state not in {"linked", "unresolved_parent"}:
            raise CanonicalSnapshotValidationError(f"{label} comment state is invalid")
        if authority not in {"governed_base", "workbook_net_new"}:
            raise CanonicalSnapshotValidationError(f"{label} record authority is invalid")
        if authority == "governed_base" and state != "linked" and not allow_governed_unresolved:
            raise CanonicalSnapshotValidationError(f"{label} governed comment cannot be unresolved")
        if (
            authority == "governed_base"
            and state == "unresolved_parent"
            and row.get("immediate_parent_resolution") != "missing_root_post_entity"
        ):
            raise CanonicalSnapshotValidationError(
                f"{label} governed unresolved comment lacks the center root-debt state"
            )
        if authority == "workbook_net_new" and "immediate_parent_resolution" in row:
            raise CanonicalSnapshotValidationError(f"{label} workbook parent resolution is not canonical")
        if row["canonical_identity_state"] != "canonical_identity" or row["entity_type"] != "comment":
            raise CanonicalSnapshotValidationError(f"{label} canonical state is invalid")
        if row["schema_version"] != "reddit_voc_canonical_comment_v1":
            raise CanonicalSnapshotValidationError(f"{label} schema is invalid")
        if (state == "linked") != (post_id in post_ids):
            raise CanonicalSnapshotValidationError(f"{label} post foreign key disagrees with comment state")
        _validate_record_identity(row, canonical_id, post_id, authority, "comment", label)
        if canonical_id in result:
            raise CanonicalSnapshotValidationError("comments.jsonl contains duplicate identities")
        result[canonical_id] = row
        comment_posts[canonical_id] = post_id
        ordered.append(canonical_id)
    if ordered != sorted(ordered):
        raise CanonicalSnapshotValidationError("comments.jsonl is not canonically sorted")
    return result, comment_posts


def _validate_quarantine(
    rows: list[dict[str, Any]], post_ids: set[str]
) -> dict[str, dict[str, Any]]:
    expected_keys = {
        "canonical_identity_state",
        "canonical_reddit_id",
        "comment_state",
        "entity_type",
        "record",
        "record_authority",
        "schema_version",
    }
    result: dict[str, dict[str, Any]] = {}
    ordered: list[str] = []
    for ordinal, row in enumerate(rows, start=1):
        label = f"quarantine.jsonl:{ordinal}"
        _exact_keys(row, expected_keys, label)
        canonical_id = _canonical_fullname(row["canonical_reddit_id"], "t1_", f"{label} canonical_reddit_id")
        if row["canonical_identity_state"] != "canonical_identity" or row["entity_type"] != "comment":
            raise CanonicalSnapshotValidationError(f"{label} canonical state is invalid")
        if row["comment_state"] != "quarantined" or row["record_authority"] != "governed_base":
            raise CanonicalSnapshotValidationError(f"{label} quarantine state is invalid")
        if row["schema_version"] != "reddit_voc_canonical_quarantine_v1":
            raise CanonicalSnapshotValidationError(f"{label} schema is invalid")
        record = row.get("record")
        if not isinstance(record, dict):
            raise CanonicalSnapshotValidationError(f"{label} record must be an object")
        if _canonical_fullname(record.get("comment_id"), "t1_", f"{label} comment_id") != canonical_id:
            raise CanonicalSnapshotValidationError(f"{label} comment identity mismatch")
        missing_post_id = _canonical_post_id(record.get("missing_post_id"), f"{label} missing_post_id")
        if missing_post_id in post_ids:
            raise CanonicalSnapshotValidationError(f"{label} missing post unexpectedly exists")
        if canonical_id in result:
            raise CanonicalSnapshotValidationError("quarantine.jsonl contains duplicate identities")
        result[canonical_id] = row
        ordered.append(canonical_id)
    if ordered != sorted(ordered):
        raise CanonicalSnapshotValidationError("quarantine.jsonl is not canonically sorted")
    return result


def _validate_governed_parent_graph(
    comments: Mapping[str, dict[str, Any]], comment_posts: Mapping[str, str]
) -> dict[str, int]:
    governed = {
        canonical_id: row
        for canonical_id, row in comments.items()
        if row["record_authority"] == "governed_base"
        and row["comment_state"] == "linked"
    }
    nested: dict[str, str] = {}
    missing_immediate = 0
    missing_parent = 0
    for canonical_id, row in governed.items():
        record = row["record"]
        parent_value = record.get("parent_id")
        resolution = row["immediate_parent_resolution"]
        if parent_value is None:
            expected = "missing_immediate_parent_id"
            missing_immediate += 1
        else:
            if not isinstance(parent_value, str) or not parent_value.isascii():
                raise CanonicalSnapshotValidationError("governed parent identity must be ASCII")
            if parent_value.startswith("t3_"):
                parent_post = _canonical_fullname(parent_value, "t3_", "governed parent post")
                if parent_post != f"t3_{comment_posts[canonical_id]}":
                    raise CanonicalSnapshotValidationError("governed root parent crosses threads")
                expected = "resolved_root_parent"
            elif parent_value.startswith("t1_"):
                parent_comment = _canonical_fullname(parent_value, "t1_", "governed parent comment")
                if parent_comment not in governed:
                    expected = "missing_parent_comment_entity"
                    missing_parent += 1
                else:
                    if comment_posts[parent_comment] != comment_posts[canonical_id]:
                        raise CanonicalSnapshotValidationError("governed nested parent crosses threads")
                    nested[canonical_id] = parent_comment
                    expected = "resolved_nested_parent"
            else:
                raise CanonicalSnapshotValidationError("governed parent identity has invalid prefix")
        if resolution != expected:
            raise CanonicalSnapshotValidationError("governed immediate parent resolution mismatch")

    visit_state: dict[str, int] = {}

    def visit(comment_id: str) -> None:
        state = visit_state.get(comment_id, 0)
        if state == 1:
            raise CanonicalSnapshotValidationError("governed nested parent cycle detected")
        if state == 2:
            return
        visit_state[comment_id] = 1
        parent_id = nested.get(comment_id)
        if parent_id is not None:
            visit(parent_id)
        visit_state[comment_id] = 2

    for canonical_id in governed:
        visit(canonical_id)
    parent_without_parent = sum(
        governed[parent_id]["record"].get("parent_id") is None for parent_id in nested.values()
    )
    return {
        "missing_immediate_parent_id": missing_immediate,
        "missing_parent_comment_entity": missing_parent,
        "nested_links_whose_parent_record_lacks_immediate_parent_id": parent_without_parent,
    }


def _validate_unresolved(
    rows: list[dict[str, Any]], comments: Mapping[str, dict[str, Any]]
) -> set[str]:
    expected_keys = {
        "canonical_reddit_id",
        "comment_state",
        "post_id",
        "schema_version",
        "source_parent_link",
        "source_terminal_outcome",
    }
    unresolved_ids = {
        canonical_id for canonical_id, row in comments.items() if row["comment_state"] == "unresolved_parent"
    }
    observed: set[str] = set()
    ordered: list[str] = []
    for ordinal, row in enumerate(rows, start=1):
        label = f"unresolved-parent-ledger.jsonl:{ordinal}"
        _exact_keys(row, expected_keys, label)
        canonical_id = _canonical_fullname(row["canonical_reddit_id"], "t1_", f"{label} canonical_reddit_id")
        if canonical_id not in unresolved_ids or canonical_id in observed:
            raise CanonicalSnapshotValidationError("unresolved parent ledger identity mismatch")
        comment = comments[canonical_id]
        post_id = _canonical_post_id(row["post_id"], f"{label} post_id")
        if post_id != comment["post_id"]:
            raise CanonicalSnapshotValidationError("unresolved parent ledger post mismatch")
        source = row.get("source_parent_link")
        if not isinstance(source, dict):
            raise CanonicalSnapshotValidationError("unresolved parent source link must be an object")
        if _canonical_fullname(source.get("comment_id"), "t1_", f"{label} source comment_id") != canonical_id:
            raise CanonicalSnapshotValidationError("unresolved parent source comment mismatch")
        if _canonical_post_id(source.get("post_id"), f"{label} source post_id") != post_id:
            raise CanonicalSnapshotValidationError("unresolved parent source post mismatch")
        if source.get("parent_link_status") != "unresolved_parent":
            raise CanonicalSnapshotValidationError("unresolved parent source state mismatch")
        candidates = source.get("candidate_post_ids")
        if not isinstance(candidates, list) or any(
            _canonical_post_id(item, f"{label} candidate_post_id") != item for item in candidates
        ):
            raise CanonicalSnapshotValidationError("unresolved parent candidates are invalid")
        terminal = comment["record"].get("terminal_outcome")
        if (
            row["comment_state"] != "unresolved_parent"
            or row["schema_version"] != "reddit_voc_canonical_unresolved_parent_v1"
            or row["source_terminal_outcome"] != terminal
            or source.get("terminal_outcome") != terminal
        ):
            raise CanonicalSnapshotValidationError("unresolved parent terminal outcome mismatch")
        observed.add(canonical_id)
        ordered.append(canonical_id)
    if observed != unresolved_ids:
        raise CanonicalSnapshotValidationError("unresolved parent ledger is not conserved")
    if ordered != sorted(ordered):
        raise CanonicalSnapshotValidationError("unresolved parent ledger is not canonically sorted")
    return observed


def _entity_index(
    posts: Mapping[str, dict[str, Any]],
    comments: Mapping[str, dict[str, Any]],
    quarantine: Mapping[str, dict[str, Any]],
) -> dict[str, tuple[str, dict[str, Any]]]:
    result: dict[str, tuple[str, dict[str, Any]]] = {}
    for entity_type, rows in (("post", posts), ("comment", comments), ("comment", quarantine)):
        for canonical_id, row in rows.items():
            if canonical_id in result:
                raise CanonicalSnapshotValidationError("canonical identities are not mutually exclusive")
            result[canonical_id] = (entity_type, row)
    return result


def _validate_provenance(
    rows: list[dict[str, Any]], entities: Mapping[str, tuple[str, dict[str, Any]]]
) -> tuple[int, Counter[str], dict[str, dict[str, bytes]]]:
    base_keys = {
        "canonical_reddit_id",
        "entity_type",
        "provenance_id",
        "schema_version",
        "source_payload_sha256",
        "source_role",
    }
    provenance_ids: set[str] = set()
    occurrence_keys: set[str] = set()
    roles_by_entity: dict[str, Counter[str]] = {canonical_id: Counter() for canonical_id in entities}
    workbook_occurrences_by_entity: dict[str, dict[str, bytes]] = {
        canonical_id: {} for canonical_id in entities
    }
    workbook_outcomes_by_entity: dict[str, list[str]] = {
        canonical_id: [] for canonical_id in entities
    }
    outcomes: Counter[str] = Counter()
    ordered: list[tuple[str, str]] = []
    for ordinal, row in enumerate(rows, start=1):
        label = f"provenance-ledger.jsonl:{ordinal}"
        role = row.get("source_role")
        expected = base_keys | (
            {"source_occurrence_count"}
            if role == "governed_base_entity"
            else {"occurrence_key", "source_occurrence", "source_row_terminal_outcome"}
        )
        _exact_keys(row, expected, label)
        canonical_id = row.get("canonical_reddit_id")
        if canonical_id not in entities:
            raise CanonicalSnapshotValidationError("provenance references an unknown canonical identity")
        entity_type, entity = entities[canonical_id]
        if row["entity_type"] != entity_type or row["schema_version"] != "reddit_voc_canonical_provenance_v1":
            raise CanonicalSnapshotValidationError("provenance entity or schema mismatch")
        provenance_id = _require_sha(row["provenance_id"], f"{label} provenance_id")
        payload_sha = _require_sha(row["source_payload_sha256"], f"{label} source_payload_sha256")
        if provenance_id in provenance_ids:
            raise CanonicalSnapshotValidationError("provenance ledger contains duplicate IDs")
        provenance_ids.add(provenance_id)
        if role == "governed_base_entity":
            if entity["record_authority"] != "governed_base":
                raise CanonicalSnapshotValidationError("governed provenance authority mismatch")
            record = entity["record"]
            expected_payload = _sha(_canonical_bytes(record))
            expected_id = _sha(_canonical_bytes([canonical_id, role, expected_payload]))
            occurrences = record.get("source_occurrences", record.get("source_kinds", []))
            expected_count = len(occurrences) if isinstance(occurrences, list) else 0
            if (
                payload_sha != expected_payload
                or provenance_id != expected_id
                or _nonnegative_int(row["source_occurrence_count"], f"{label} occurrence count") != expected_count
            ):
                raise CanonicalSnapshotValidationError("governed provenance derivation mismatch")
        elif role == "workbook_occurrence":
            occurrence = row.get("source_occurrence")
            if not isinstance(occurrence, dict):
                raise CanonicalSnapshotValidationError("workbook provenance occurrence must be an object")
            occurrence_key = row.get("occurrence_key")
            if not isinstance(occurrence_key, str) or not occurrence_key or occurrence.get("occurrence_key") != occurrence_key:
                raise CanonicalSnapshotValidationError("workbook provenance occurrence key mismatch")
            if occurrence_key in occurrence_keys:
                raise CanonicalSnapshotValidationError("workbook provenance occurrence key is duplicated")
            occurrence_keys.add(occurrence_key)
            workbook_occurrences_by_entity[str(canonical_id)][occurrence_key] = _canonical_bytes(occurrence)
            expected_payload = _sha(_canonical_bytes(occurrence))
            expected_id = _sha(_canonical_bytes([canonical_id, role, occurrence_key, expected_payload]))
            if payload_sha != expected_payload or provenance_id != expected_id:
                raise CanonicalSnapshotValidationError("workbook provenance derivation mismatch")
            entity_post_id = entity.get("post_id")
            if entity_post_id is None:
                entity_post_id = entity["record"].get("missing_post_id")
            if _canonical_post_id(occurrence.get("post_id"), f"{label} occurrence post_id") != entity_post_id:
                raise CanonicalSnapshotValidationError("workbook provenance post identity mismatch")
            url_post_id, url_comment_id = _reddit_identity_from_url(
                occurrence.get("source_url"), entity_type, label
            )
            if url_post_id != entity_post_id:
                raise CanonicalSnapshotValidationError("workbook provenance URL post identity mismatch")
            if entity_type == "comment":
                if f"t1_{url_comment_id}" != canonical_id:
                    raise CanonicalSnapshotValidationError(
                        "workbook provenance URL comment identity mismatch"
                    )
            elif f"t3_{url_post_id}" != canonical_id:
                raise CanonicalSnapshotValidationError("workbook provenance URL post identity mismatch")
            if "canonical_reddit_id" in occurrence and occurrence["canonical_reddit_id"] != canonical_id:
                raise CanonicalSnapshotValidationError("workbook occurrence canonical identity mismatch")
            if "entity_type" in occurrence and occurrence["entity_type"] != entity_type:
                raise CanonicalSnapshotValidationError("workbook occurrence entity type mismatch")
            if "comment_id" in occurrence:
                expected_comment_id = canonical_id if entity_type == "comment" else None
                if occurrence["comment_id"] != expected_comment_id:
                    raise CanonicalSnapshotValidationError("workbook occurrence comment identity mismatch")
            if "occurrence_sha256" in occurrence:
                rebound = dict(occurrence)
                declared = rebound.pop("occurrence_sha256")
                if _require_sha(declared, f"{label} occurrence_sha256") != _sha(_canonical_bytes(rebound)):
                    raise CanonicalSnapshotValidationError("workbook provenance occurrence hash mismatch")
            terminal = row.get("source_row_terminal_outcome")
            if terminal not in TERMINAL_OUTCOMES:
                raise CanonicalSnapshotValidationError("workbook provenance terminal outcome is invalid")
            if "terminal_outcome" in occurrence and occurrence["terminal_outcome"] != terminal:
                raise CanonicalSnapshotValidationError(
                    "workbook provenance occurrence terminal outcome mismatch"
                )
            if entity_type == "comment":
                state = entity.get("comment_state")
                if terminal == "unresolved_parent" and state != "unresolved_parent":
                    raise CanonicalSnapshotValidationError(
                        "workbook provenance terminal outcome disagrees with comment state"
                    )
                if state == "unresolved_parent" and terminal not in {"unresolved_parent", "duplicate"}:
                    raise CanonicalSnapshotValidationError(
                        "workbook provenance terminal outcome disagrees with comment state"
                    )
            if terminal == "exact_base_overlap" and entity["record_authority"] != "governed_base":
                raise CanonicalSnapshotValidationError(
                    "exact Base overlap provenance lacks governed authority"
                )
            outcomes[terminal] += 1
            workbook_outcomes_by_entity[str(canonical_id)].append(str(terminal))
        else:
            raise CanonicalSnapshotValidationError("provenance source role is invalid")
        roles_by_entity[canonical_id][str(role)] += 1
        ordered.append((str(canonical_id), provenance_id))
    if ordered != sorted(ordered):
        raise CanonicalSnapshotValidationError("provenance ledger is not canonically sorted")
    for canonical_id, (_, entity) in entities.items():
        roles = roles_by_entity[canonical_id]
        if entity["record_authority"] == "governed_base":
            if roles["governed_base_entity"] != 1:
                raise CanonicalSnapshotValidationError("governed entity provenance is not one-to-one")
        else:
            if roles["governed_base_entity"] != 0 or roles["workbook_occurrence"] < 1:
                raise CanonicalSnapshotValidationError("workbook entity provenance is incomplete")
            record_occurrences = entity["record"].get("source_occurrences")
            if not isinstance(record_occurrences, list):
                raise CanonicalSnapshotValidationError("workbook entity source occurrences are missing")
            expected_occurrences: dict[str, bytes] = {}
            for occurrence in record_occurrences:
                if not isinstance(occurrence, dict):
                    raise CanonicalSnapshotValidationError("workbook entity source occurrence is invalid")
                occurrence_key = occurrence.get("occurrence_key")
                if not isinstance(occurrence_key, str) or not occurrence_key or occurrence_key in expected_occurrences:
                    raise CanonicalSnapshotValidationError("workbook entity source occurrence key is invalid")
                expected_occurrences[occurrence_key] = _canonical_bytes(occurrence)
            if workbook_occurrences_by_entity[canonical_id] != expected_occurrences:
                raise CanonicalSnapshotValidationError("workbook entity provenance occurrence coverage mismatch")
            record_terminal = entity["record"].get("terminal_outcome")
            if record_terminal not in TERMINAL_OUTCOMES - {"duplicate", "exact_base_overlap"}:
                raise CanonicalSnapshotValidationError("workbook entity terminal outcome is invalid")
            nonduplicate_outcomes = [
                outcome
                for outcome in workbook_outcomes_by_entity[canonical_id]
                if outcome != "duplicate"
            ]
            if nonduplicate_outcomes != [record_terminal]:
                raise CanonicalSnapshotValidationError(
                    "workbook entity/provenance terminal outcome coverage mismatch"
                )
    return len(occurrence_keys), outcomes, workbook_occurrences_by_entity


def _validate_conflicts(
    rows: list[dict[str, Any]],
    entities: Mapping[str, tuple[str, dict[str, Any]]],
    provenance_occurrences: Mapping[str, Mapping[str, bytes]],
) -> None:
    expected_keys = {
        "canonical_reddit_id",
        "conflict_type",
        "entity_type",
        "resolution",
        "schema_version",
        "source_conflict_record",
        "source_conflict_sha256",
        "source_role",
    }
    ordered: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    source_keys: set[tuple[str, str, str]] = set()
    for ordinal, row in enumerate(rows, start=1):
        label = f"conflict-ledger.jsonl:{ordinal}"
        _exact_keys(row, expected_keys, label)
        canonical_id = row.get("canonical_reddit_id")
        if canonical_id not in entities:
            raise CanonicalSnapshotValidationError("conflict ledger references an unknown identity")
        entity_type, _ = entities[canonical_id]
        source = row.get("source_conflict_record")
        if not isinstance(source, dict):
            raise CanonicalSnapshotValidationError("conflict source record must be an object")
        source_sha = _require_sha(row["source_conflict_sha256"], f"{label} source hash")
        if source_sha != _sha(_canonical_bytes(source)):
            raise CanonicalSnapshotValidationError("conflict source hash mismatch")
        if (
            row["schema_version"] != "reddit_voc_canonical_conflict_v1"
            or row["source_role"] != "workbook_import_conflict"
            or row["entity_type"] != entity_type
            or source.get("canonical_reddit_id") != canonical_id
            or source.get("entity_type") != entity_type
            or source.get("conflict_type") != row["conflict_type"]
            or source.get("resolution") != row["resolution"]
        ):
            raise CanonicalSnapshotValidationError("conflict ledger derivation mismatch")
        key = (str(canonical_id), str(row["conflict_type"]), source_sha)
        if key in seen:
            raise CanonicalSnapshotValidationError("conflict ledger contains a duplicate")
        seen.add(key)
        source_keys.add(
            (
                str(source.get("canonical_reddit_id")),
                str(source.get("conflict_type")),
                _sha(_canonical_bytes(source)),
            )
        )
        source_occurrences = source.get("source_occurrences")
        if source_occurrences is not None:
            if not isinstance(source_occurrences, list) or any(
                not isinstance(item, dict) for item in source_occurrences
            ):
                raise CanonicalSnapshotValidationError("conflict source occurrences are invalid")
            observed_occurrences: dict[str, bytes] = {}
            for occurrence in source_occurrences:
                occurrence_key = occurrence.get("occurrence_key")
                if (
                    not isinstance(occurrence_key, str)
                    or not occurrence_key
                    or occurrence_key in observed_occurrences
                ):
                    raise CanonicalSnapshotValidationError("conflict source occurrence key is invalid")
                observed_occurrences[occurrence_key] = _canonical_bytes(occurrence)
            available = provenance_occurrences.get(str(canonical_id), {})
            if any(available.get(key) != payload for key, payload in observed_occurrences.items()):
                raise CanonicalSnapshotValidationError(
                    "conflict source occurrence is absent from canonical provenance"
                )
        if row["conflict_type"] == "base_permalink_identity_disagreement":
            governed_post_id = _canonical_post_id(
                source.get("governed_post_id"), f"{label} governed_post_id"
            )
            observed_post_id = _canonical_post_id(
                source.get("observed_permalink_post_id"), f"{label} observed_permalink_post_id"
            )
            if canonical_id != f"t3_{governed_post_id}" or governed_post_id == observed_post_id:
                raise CanonicalSnapshotValidationError("permalink identity conflict is invalid")
        ordered.append(key)
    if source_keys != seen:
        raise CanonicalSnapshotValidationError("conflict ledger source/outer sets differ")
    if ordered != sorted(ordered):
        raise CanonicalSnapshotValidationError("conflict ledger is not canonically sorted")


def _validate_file_bindings(
    manifest: Mapping[str, object], payloads: Mapping[str, bytes]
) -> None:
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise CanonicalSnapshotValidationError("canonical manifest file bindings are missing")
    _exact_keys(files, JSONL_FILES, "canonical manifest files")
    for name in sorted(JSONL_FILES):
        binding = files.get(name)
        if not isinstance(binding, dict):
            raise CanonicalSnapshotValidationError(f"canonical manifest {name} binding is missing")
        _exact_keys(binding, {"bytes", "rows", "sha256"}, f"canonical manifest {name} binding")
        payload = payloads[name]
        if (
            _nonnegative_int(binding["bytes"], f"{name} bytes") != len(payload)
            or _nonnegative_int(binding["rows"], f"{name} rows") != payload.count(b"\n")
            or _require_sha(binding["sha256"], f"{name} SHA-256") != _sha(payload)
        ):
            raise CanonicalSnapshotValidationError(f"canonical manifest {name} file binding mismatch")


def _validate_manifest(
    manifest: dict[str, Any],
    manifest_payload: bytes,
    payloads: Mapping[str, bytes],
    expected_manifest_sha256: str,
    expected_inputs: Mapping[str, str],
    computed_counts: Mapping[str, int],
    source_rows: int,
    outcomes: Counter[str],
    lineage_debt: Mapping[str, int],
) -> None:
    expected_manifest_keys = {
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
    _exact_keys(manifest, expected_manifest_keys, "canonical manifest")
    if _sha(manifest_payload) != _require_sha(expected_manifest_sha256, "expected bundle manifest SHA-256"):
        raise CanonicalSnapshotValidationError("canonical manifest hash binding mismatch")
    schema_version = manifest["schema_version"]
    if schema_version not in {
        "reddit_voc_canonical_snapshot_manifest_v1",
        "reddit_voc_canonical_snapshot_manifest_v2",
    }:
        raise CanonicalSnapshotValidationError("canonical manifest schema is invalid")
    expected_suffix = "_canonical_v2" if schema_version.endswith("_v2") else "_canonical_v1"
    if not isinstance(manifest["dataset_id"], str) or not manifest["dataset_id"].endswith(expected_suffix):
        raise CanonicalSnapshotValidationError("canonical manifest dataset_id is invalid")
    if (
        manifest["status"] != "candidate_built"
        or manifest["independent_validation_status"] != "pending"
        or manifest["consumption_status"] != "blocked_pending_independent_validation"
        or manifest["promotable"] is not False
        or manifest["validation_receipt_sha256"] is not None
    ):
        raise CanonicalSnapshotValidationError("canonical manifest lifecycle boundary is invalid")
    if manifest["boundaries"] != BOUNDARIES:
        raise CanonicalSnapshotValidationError("canonical manifest side-effect boundaries are invalid")
    if manifest["state_contract"] != {
        "canonical_identity": True,
        "comment_states": COMMENT_STATES,
        "states_mutually_exclusive": True,
    }:
        raise CanonicalSnapshotValidationError("canonical manifest state contract is invalid")

    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict):
        raise CanonicalSnapshotValidationError("canonical manifest inputs are missing")
    input_keys = INPUT_KEYS_V2 if schema_version.endswith("_v2") else INPUT_KEYS_V1
    _exact_keys(inputs, input_keys, "canonical manifest inputs")
    normalized_expected = {key: _require_sha(expected_inputs.get(key), f"expected {key}") for key in input_keys}
    normalized_actual = {key: _require_sha(inputs.get(key), f"manifest {key}") for key in input_keys}
    if normalized_actual != normalized_expected:
        raise CanonicalSnapshotValidationError("canonical manifest input SHA bindings mismatch")

    _validate_file_bindings(manifest, payloads)

    counts = manifest.get("canonical_counts")
    if not isinstance(counts, dict):
        raise CanonicalSnapshotValidationError("canonical counts are missing")
    _exact_keys(counts, computed_counts, "canonical counts")
    validated_counts = {key: _nonnegative_int(counts[key], f"canonical count {key}") for key in computed_counts}
    if validated_counts != dict(computed_counts):
        raise CanonicalSnapshotValidationError("canonical count conservation mismatch")

    accounting = manifest.get("source_row_accounting")
    if not isinstance(accounting, dict):
        raise CanonicalSnapshotValidationError("source row accounting is missing")
    _exact_keys(accounting, {"layer_separation", "source_rows", "terminal_outcomes"}, "source row accounting")
    if accounting["layer_separation"] != "source_row_terminal_disposition_is_not_canonical_entity_state":
        raise CanonicalSnapshotValidationError("source row layer separation is invalid")
    if _nonnegative_int(accounting["source_rows"], "source rows") != source_rows:
        raise CanonicalSnapshotValidationError("source row count is not conserved")
    declared_outcomes = accounting.get("terminal_outcomes")
    if not isinstance(declared_outcomes, dict) or any(
        not isinstance(key, str) or type(value) is not int or value < 0
        for key, value in declared_outcomes.items()
    ):
        raise CanonicalSnapshotValidationError("source terminal outcomes are invalid")
    if set(declared_outcomes) != TERMINAL_OUTCOMES:
        raise CanonicalSnapshotValidationError("source terminal outcome key set is invalid")
    expected_outcomes = {key: outcomes.get(key, 0) for key in declared_outcomes}
    if set(outcomes) - set(declared_outcomes) or declared_outcomes != expected_outcomes:
        raise CanonicalSnapshotValidationError("source terminal outcome accounting mismatch")
    if sum(declared_outcomes.values()) != source_rows:
        raise CanonicalSnapshotValidationError("source terminal outcomes do not sum to source rows")

    debt = manifest.get("governed_base_parent_lineage_debt")
    if not isinstance(debt, dict):
        raise CanonicalSnapshotValidationError("governed Base lineage debt is missing")
    expected_debt_keys = set(lineage_debt) | {"linked_definition", "workbook_unresolved_parent_separate"}
    _exact_keys(debt, expected_debt_keys, "governed Base lineage debt")
    for key, value in lineage_debt.items():
        if _nonnegative_int(debt[key], f"governed Base lineage debt {key}") != value:
            raise CanonicalSnapshotValidationError("governed Base lineage debt count mismatch")
    if (
        debt["linked_definition"]
        != "post_id_resolves_to_canonical_post_not_complete_immediate_parent_chain"
        or debt["workbook_unresolved_parent_separate"] is not True
    ):
        raise CanonicalSnapshotValidationError("governed Base lineage debt boundary is invalid")


def _open_or_create_receipt_parent(
    receipt_path: Path, project_root: Path
) -> tuple[Path, list[int]]:
    _, parts = _private_parts(receipt_path, project_root, "receipt path")
    if len(parts) < 2:
        raise CanonicalSnapshotValidationError("receipt path requires a private parent")
    target = Path(parts[-1])
    if target.name != parts[-1] or target.name in {"", ".", ".."}:
        raise CanonicalSnapshotValidationError("receipt file name is unsafe")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    opened = _open_project_private_root(project_root)
    try:
        descriptor = opened[-1]
        for part in parts[:-1]:
            try:
                child = os.open(part, flags, dir_fd=descriptor)
            except FileNotFoundError:
                try:
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                os.fsync(descriptor)
                child = os.open(part, flags, dir_fd=descriptor)
            metadata = os.fstat(child)
            if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700:
                os.close(child)
                raise CanonicalSnapshotValidationError("receipt parent must have mode 0700")
            opened.append(child)
            descriptor = child
        return target, opened
    except CanonicalSnapshotValidationError:
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise
    except OSError as exc:
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise CanonicalSnapshotValidationError("receipt parent unavailable or unsafe") from exc


def _rename_noreplace(source_fd: int, source_name: str, target_fd: int, target_name: str) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    encoded_source = os.fsencode(source_name)
    encoded_target = os.fsencode(target_name)
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
        result = function(source_fd, encoded_source, target_fd, encoded_target, 0x00000004)
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
        result = function(source_fd, encoded_source, target_fd, encoded_target, 1)
    else:
        raise CanonicalSnapshotValidationError("atomic no-replace receipt rename is unavailable")
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise CanonicalSnapshotValidationError("validation receipt already exists")
    raise OSError(error_number, os.strerror(error_number))


def _require_receipt_target(
    directory_fd: int, name: str, expected_identity: tuple[int, int]
) -> None:
    try:
        metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except OSError as exc:
        raise CanonicalSnapshotValidationError("validation receipt publish ownership changed") from exc
    if (
        (metadata.st_dev, metadata.st_ino) != expected_identity
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise CanonicalSnapshotValidationError("validation receipt publish ownership changed")


def _write_private_receipt(receipt_path: Path, value: Mapping[str, object], project_root: Path) -> None:
    _exact_keys(value, RECEIPT_KEYS, "validation receipt")
    target, opened = _open_or_create_receipt_parent(receipt_path, project_root)
    parent_fd = opened[-1]
    stage_name = f".{target.name}.stage-{secrets.token_hex(12)}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    stage_fd: int | None = None
    stage_identity: tuple[int, int] | None = None
    published = False
    completed = False
    try:
        stage_fd = os.open(stage_name, flags, 0o600, dir_fd=parent_fd)
        metadata = os.fstat(stage_fd)
        stage_identity = (metadata.st_dev, metadata.st_ino)
        os.fchmod(stage_fd, 0o600)
        view = memoryview(_canonical_bytes(dict(value)) + b"\n")
        while view:
            written = os.write(stage_fd, view)
            if written <= 0:
                raise OSError("receipt write made no progress")
            view = view[written:]
        os.fsync(stage_fd)
        _rename_noreplace(parent_fd, stage_name, parent_fd, target.name)
        published = True
        os.fsync(parent_fd)
        _require_receipt_target(parent_fd, target.name, stage_identity)
        completed = True
    except CanonicalSnapshotValidationError:
        raise
    except OSError as exc:
        raise CanonicalSnapshotValidationError("validation receipt atomic publish failed") from exc
    finally:
        if not completed and published and stage_fd is not None:
            # Invalidate only the inode that this process created.  The open
            # descriptor remains bound to that inode even if a concurrent
            # actor replaces the target pathname, so this cannot truncate or
            # chmod a foreign replacement.  A failed publish must never leave
            # a mode-0600, hash-valid `passed` receipt at the target path.
            try:
                os.fchmod(stage_fd, 0o000)
            except OSError:
                pass
            try:
                os.ftruncate(stage_fd, 0)
            except OSError:
                pass
            try:
                os.fsync(stage_fd)
            except OSError:
                pass
        if stage_fd is not None:
            try:
                os.close(stage_fd)
            except OSError:
                pass
        # Failure evidence is deliberately not removed by pathname.  There is
        # no portable unlink-by-inode operation, so cleanup could otherwise
        # delete a concurrent foreign replacement of the hidden stage name.
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _receipt_outside_bundle(receipt_path: Path, bundle_root: Path, project_root: Path) -> None:
    private_root, receipt_parts = _private_parts(receipt_path, project_root, "receipt path")
    _, bundle_parts = _private_parts(bundle_root, project_root, "canonical bundle")
    receipt = private_root.joinpath(*receipt_parts)
    bundle = private_root.joinpath(*bundle_parts)
    if receipt == bundle or bundle in receipt.parents:
        raise CanonicalSnapshotValidationError("validation receipt must be outside the input bundle")


def validate_canonical_snapshot(
    bundle_root: Path,
    project_root: Path,
    *,
    expected_manifest_sha256: str,
    expected_source_manifest_sha256: str | None = None,
    expected_base_public_manifest_sha256: str | None = None,
    expected_base_lineage_manifest_sha256: str | None = None,
    expected_workbook_import_manifest_sha256: str | None = None,
    expected_workbook_import_validation_receipt_sha256: str | None = None,
    expected_center_state_sha256: str | None = None,
    expected_center_orchestration_receipt_sha256: str | None = None,
    expected_latest_source_batch_manifest_sha256: str | None = None,
    expected_latest_source_batch_validation_receipt_sha256: str | None = None,
    expected_previous_canonical_manifest_sha256: str | None = None,
    expected_previous_canonical_validation_receipt_sha256: str | None = None,
    receipt_path: Path | None = None,
) -> CanonicalValidationReceipt:
    """Validate one immutable canonical bundle without importing its builder."""

    root = Path(project_root)
    bundle = Path(bundle_root)
    if receipt_path is not None:
        _receipt_outside_bundle(Path(receipt_path), bundle, root)
    manifest, manifest_payload, payloads = _read_bundle(bundle, root)
    schema_version = manifest.get("schema_version")
    is_v2 = schema_version == "reddit_voc_canonical_snapshot_manifest_v2"
    _validate_file_bindings(manifest, payloads)
    rows = {name: _jsonl(payloads[name], name) for name in JSONL_FILES}

    posts, post_ids = _validate_posts(rows["posts.jsonl"])
    comments, comment_posts = _validate_comments(
        rows["comments.jsonl"], post_ids, allow_governed_unresolved=is_v2
    )
    quarantine = _validate_quarantine(rows["quarantine.jsonl"], post_ids)
    entities = _entity_index(posts, comments, quarantine)
    _validate_unresolved(rows["unresolved-parent-ledger.jsonl"], comments)
    lineage_debt = _validate_governed_parent_graph(comments, comment_posts)
    source_rows, outcomes, provenance_occurrences = _validate_provenance(
        rows["provenance-ledger.jsonl"], entities
    )
    _validate_conflicts(rows["conflict-ledger.jsonl"], entities, provenance_occurrences)

    linked = sum(row["comment_state"] == "linked" for row in comments.values())
    unresolved = sum(row["comment_state"] == "unresolved_parent" for row in comments.values())
    quarantined = len(quarantine)
    stored = len(comments) + quarantined
    if linked + unresolved + quarantined != stored:
        raise CanonicalSnapshotValidationError("canonical comment states are not conserved")
    computed_counts = {
        "comments_jsonl": len(comments),
        "linked_comments": linked,
        "posts": len(posts),
        "quarantined_comments": quarantined,
        "stored_comments": stored,
        "unresolved_parent_comments": unresolved,
    }
    if is_v2:
        expected_inputs = {
            "center_orchestration_receipt_sha256": expected_center_orchestration_receipt_sha256,
            "center_state_sha256": expected_center_state_sha256,
            "latest_source_batch_manifest_sha256": expected_latest_source_batch_manifest_sha256,
            "latest_source_batch_validation_receipt_sha256": expected_latest_source_batch_validation_receipt_sha256,
            "previous_canonical_manifest_sha256": expected_previous_canonical_manifest_sha256,
            "previous_canonical_validation_receipt_sha256": expected_previous_canonical_validation_receipt_sha256,
        }
    else:
        expected_inputs = {
            "base_lineage_manifest_sha256": expected_base_lineage_manifest_sha256,
            "base_public_manifest_sha256": expected_base_public_manifest_sha256,
            "source_manifest_sha256": expected_source_manifest_sha256,
            "workbook_import_manifest_sha256": expected_workbook_import_manifest_sha256,
            "workbook_import_validation_receipt_sha256": expected_workbook_import_validation_receipt_sha256,
        }
    _validate_manifest(
        manifest,
        manifest_payload,
        payloads,
        expected_manifest_sha256,
        expected_inputs,
        computed_counts,
        source_rows,
        outcomes,
        lineage_debt,
    )
    receipt = CanonicalValidationReceipt(
        schema_version=(
            "reddit_voc_canonical_snapshot_validation_receipt_v2"
            if is_v2
            else "reddit_voc_canonical_snapshot_validation_receipt_v1"
        ),
        status="passed",
        bundle_manifest_sha256=_sha(manifest_payload),
        inputs={key: _require_sha(value, f"receipt input {key}") for key, value in expected_inputs.items()},
        canonical_counts=computed_counts,
        source_row_accounting={
            "source_rows": source_rows,
            "terminal_outcomes": dict(
                sorted(manifest["source_row_accounting"]["terminal_outcomes"].items())
            ),
        },
        unaccounted_canonical_identities=0,
        unaccounted_foreign_keys=0,
        boundaries=dict(BOUNDARIES),
        consumption_status="blocked_pending_voc_facts",
        promotable=False,
    )
    if receipt_path is not None:
        _write_private_receipt(Path(receipt_path), receipt.as_dict(), root)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Independently validate a Reddit VOC V3 canonical snapshot.")
    parser.add_argument("--bundle-root", required=True, type=Path)
    parser.add_argument("--bundle-manifest-sha256", required=True)
    parser.add_argument("--source-manifest-sha256")
    parser.add_argument("--base-public-manifest-sha256")
    parser.add_argument("--base-lineage-manifest-sha256")
    parser.add_argument("--workbook-import-manifest-sha256")
    parser.add_argument("--workbook-import-validation-receipt-sha256")
    parser.add_argument("--center-state-sha256")
    parser.add_argument("--center-orchestration-receipt-sha256")
    parser.add_argument("--latest-source-batch-manifest-sha256")
    parser.add_argument("--latest-source-batch-validation-receipt-sha256")
    parser.add_argument("--previous-canonical-manifest-sha256")
    parser.add_argument("--previous-canonical-validation-receipt-sha256")
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--receipt-path", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt = validate_canonical_snapshot(
            args.bundle_root,
            args.project_root,
            expected_manifest_sha256=args.bundle_manifest_sha256,
            expected_source_manifest_sha256=args.source_manifest_sha256,
            expected_base_public_manifest_sha256=args.base_public_manifest_sha256,
            expected_base_lineage_manifest_sha256=args.base_lineage_manifest_sha256,
            expected_workbook_import_manifest_sha256=args.workbook_import_manifest_sha256,
            expected_workbook_import_validation_receipt_sha256=args.workbook_import_validation_receipt_sha256,
            expected_center_state_sha256=args.center_state_sha256,
            expected_center_orchestration_receipt_sha256=args.center_orchestration_receipt_sha256,
            expected_latest_source_batch_manifest_sha256=args.latest_source_batch_manifest_sha256,
            expected_latest_source_batch_validation_receipt_sha256=args.latest_source_batch_validation_receipt_sha256,
            expected_previous_canonical_manifest_sha256=args.previous_canonical_manifest_sha256,
            expected_previous_canonical_validation_receipt_sha256=args.previous_canonical_validation_receipt_sha256,
            receipt_path=args.receipt_path,
        )
    except CanonicalSnapshotValidationError as exc:
        print(f"canonical snapshot validation failed:{exc}", file=sys.stderr)
        return 1
    print((_canonical_bytes(receipt.as_dict()) + b"\n").decode("utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
