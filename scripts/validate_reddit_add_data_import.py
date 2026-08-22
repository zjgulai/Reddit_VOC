from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
import errno
import hashlib
from io import BytesIO
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
import sys
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import unquote, urlsplit
import unicodedata
import warnings

from openpyxl import load_workbook

from reddit_voc.v3_source_manifest import SourceContract, SourceManifest, load_source_manifest


RECEIPT_SCHEMA = "reddit_voc_workbook_import_validation_receipt_v1"
BUNDLE_SCHEMA = "reddit_voc_workbook_import_manifest_v1"
ENTITY_SCHEMA = "reddit_voc_workbook_entity_v1"
ROW_OUTCOME_SCHEMA = "reddit_voc_workbook_row_outcome_v1"
PARENT_LINK_SCHEMA = "reddit_voc_workbook_parent_link_v1"
CONFLICT_SCHEMA = "reddit_voc_workbook_conflict_v1"

POST_TYPE = "forum post"
COMMENT_TYPE = "forum post reply"
TERMINAL_OUTCOMES = (
    "duplicate",
    "exact_base_overlap",
    "identity_conflict",
    "incomplete_text",
    "net_new_text_ready",
    "unresolved_parent",
)
BUNDLE_FILES = (
    "comments.jsonl",
    "conflict-ledger.jsonl",
    "parent-link-ledger.jsonl",
    "posts.jsonl",
    "row-outcomes.jsonl",
)
BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}

_REDDIT_ID = re.compile(r"^[a-z0-9]+$")
_STRICT_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_STRICT_MIDNIGHT = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}(?:T| )00:00:00$"
)
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


class ImportValidationError(ValueError):
    """The candidate cannot be proven equivalent to its bound physical inputs."""


@dataclass(frozen=True)
class ValidationReceipt:
    schema_version: str
    status: str
    bundle_manifest_sha256: str
    source_manifest_sha256: str
    base_public_manifest_sha256: str
    base_lineage_manifest_sha256: str
    counts: dict[str, object]
    unaccounted_source_rows: int
    unaccounted_import_identities: int
    boundaries: dict[str, bool]
    consumption_status: str
    promotable: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "base_lineage_manifest_sha256": self.base_lineage_manifest_sha256,
            "base_public_manifest_sha256": self.base_public_manifest_sha256,
            "boundaries": dict(self.boundaries),
            "bundle_manifest_sha256": self.bundle_manifest_sha256,
            "consumption_status": self.consumption_status,
            "counts": dict(self.counts),
            "promotable": self.promotable,
            "schema_version": self.schema_version,
            "source_manifest_sha256": self.source_manifest_sha256,
            "status": self.status,
            "unaccounted_import_identities": self.unaccounted_import_identities,
            "unaccounted_source_rows": self.unaccounted_source_rows,
        }


@dataclass(frozen=True)
class _SourceRow:
    source_snapshot_id: str
    source_row_ordinal: int
    source_record_id: str
    source_url: str
    entity_type: str
    post_id: str
    comment_id: str | None
    source_text: str
    source_summary: str
    source_calendar_date: str
    source_file_sha256: str
    selection_class: str
    query_profile_status: str
    allowed_metric_families: tuple[str, ...]
    blocked_uses: tuple[str, ...]
    source_annotations: dict[str, object]

    @property
    def bare_entity_id(self) -> str:
        return self.comment_id or self.post_id

    @property
    def canonical_reddit_id(self) -> str:
        prefix = "t1" if self.entity_type == "comment" else "t3"
        return f"{prefix}_{self.bare_entity_id}"

    @property
    def occurrence_key(self) -> str:
        return f"{self.source_snapshot_id}:{self.source_row_ordinal}"

    def occurrence_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "allowed_metric_families": list(self.allowed_metric_families),
            "blocked_uses": list(self.blocked_uses),
            "occurrence_key": self.occurrence_key,
            "post_id": self.post_id,
            "selection_class": self.selection_class,
            "source_annotations": dict(self.source_annotations),
            "source_annotations_sha256": _sha(_canonical_bytes(self.source_annotations)),
            "source_calendar_date": self.source_calendar_date,
            "source_file_sha256": self.source_file_sha256,
            "source_record_id": self.source_record_id,
            "source_row_ordinal": self.source_row_ordinal,
            "source_snapshot_id": self.source_snapshot_id,
            "source_summary_sha256": _sha(self.source_summary.encode("utf-8")),
            "source_text_sha256": _sha(self.source_text.encode("utf-8")),
            "source_url": self.source_url,
        }
        value["occurrence_sha256"] = _sha(_canonical_bytes(value))
        return value


@dataclass(frozen=True)
class _BaseData:
    posts: dict[str, dict[str, Any]]
    comments: dict[str, dict[str, Any]]
    quarantine: dict[str, dict[str, Any]]
    unresolved: dict[str, dict[str, Any]]
    held_post_ids: frozenset[str]
    conflicts: tuple[dict[str, object], ...]
    public_file_bindings: dict[str, dict[str, object]]
    lineage_file_bindings: dict[str, dict[str, object]]


@dataclass(frozen=True)
class _Classification:
    groups: dict[tuple[str, str], tuple[_SourceRow, ...]]
    representatives: dict[tuple[str, str], _SourceRow]
    row_outcomes: dict[str, str]
    entity_outcomes: dict[tuple[str, str], str]
    base_records: dict[tuple[str, str], tuple[dict[str, Any], str]]
    held_keys: frozenset[tuple[str, str]]
    base_held_keys: frozenset[tuple[str, str]]
    parent_links: tuple[dict[str, object], ...]
    conflicts: tuple[dict[str, object], ...]


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


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
        raise ImportValidationError("value is not canonical JSON") from exc


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ImportValidationError(f"duplicate JSON key:{key}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise ImportValidationError(f"non-finite JSON number:{value}")


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ImportValidationError(f"non-finite JSON number:{value}")
    return result


def _decode_json_document(payload: bytes, label: str) -> object:
    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite,
            parse_float=_finite_float,
        )
    except ImportValidationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, OverflowError, ValueError) as exc:
        raise ImportValidationError(f"{label} invalid JSON") from exc


def _json_object(payload: bytes, label: str, *, canonical: bool = False) -> dict[str, Any]:
    value = _decode_json_document(payload, label)
    if not isinstance(value, dict):
        raise ImportValidationError(f"{label} must be an object")
    if canonical and payload != _canonical_bytes(value) + b"\n":
        raise ImportValidationError(f"{label} is not canonical JSON")
    return value


def _json_list(payload: bytes, label: str) -> list[dict[str, Any]]:
    value = _decode_json_document(payload, label)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ImportValidationError(f"{label} must be a list of objects")
    return value


def _jsonl(payload: bytes, label: str) -> list[dict[str, Any]]:
    if payload and not payload.endswith(b"\n"):
        raise ImportValidationError(f"{label} must end with newline")
    rows: list[dict[str, Any]] = []
    for ordinal, line in enumerate(payload.splitlines(), start=1):
        if not line:
            raise ImportValidationError(f"{label} contains blank line:{ordinal}")
        value = _decode_json_document(line, f"{label}:{ordinal}")
        if not isinstance(value, dict):
            raise ImportValidationError(f"{label}:{ordinal} must be an object")
        if line != _canonical_bytes(value):
            raise ImportValidationError(f"{label}:{ordinal} is not canonical JSON")
        rows.append(value)
    return rows


def _exact_keys(value: Mapping[str, object], expected: Iterable[str], label: str) -> None:
    actual = set(value)
    target = set(expected)
    if actual != target:
        raise ImportValidationError(
            f"{label} keys mismatch:missing={sorted(target-actual)}:extra={sorted(actual-target)}"
        )


def _regular_file_once(path: Path, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(os.fspath(path), flags)
    except OSError as exc:
        raise ImportValidationError(f"{label} unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ImportValidationError(f"{label} must be a regular file")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    finally:
        os.close(descriptor)


def _regular_file_at(directory_fd: int, name: str, label: str) -> bytes:
    if "/" in name or "\\" in name or name in {"", ".", ".."}:
        raise ImportValidationError(f"unsafe file name:{label}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=directory_fd)
    except OSError as exc:
        raise ImportValidationError(f"{label} unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ImportValidationError(f"{label} must be a regular file")
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            raise ImportValidationError(f"{label} must have private mode 0600")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    finally:
        os.close(descriptor)


def _relative_parts(relative: PurePosixPath, label: str) -> tuple[str, ...]:
    if relative.is_absolute() or not relative.parts or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise ImportValidationError(f"unsafe relative path:{label}")
    return relative.parts


def _regular_relative_once(
    project_root: Path,
    relative: PurePosixPath,
    label: str,
) -> bytes:
    parts = _relative_parts(relative, label)
    root = Path(os.path.abspath(os.fspath(project_root)))
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory_flags = flags | getattr(os, "O_DIRECTORY", 0)
    opened: list[int] = []
    try:
        root_metadata = root.lstat()
        if not stat.S_ISDIR(root_metadata.st_mode) or stat.S_ISLNK(root_metadata.st_mode):
            raise ImportValidationError("project_root must be a regular directory")
        descriptor = os.open(os.fspath(root), directory_flags)
        opened.append(descriptor)
        for part in parts[:-1]:
            descriptor = os.open(part, directory_flags, dir_fd=descriptor)
            opened.append(descriptor)
        file_descriptor = os.open(parts[-1], flags, dir_fd=descriptor)
        opened.append(file_descriptor)
        metadata = os.fstat(file_descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ImportValidationError(f"{label} must be a regular file")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(file_descriptor, 1024 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    except ImportValidationError:
        raise
    except OSError as exc:
        raise ImportValidationError(f"{label} unavailable") from exc
    finally:
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _private_location(path: Path, project_root: Path, label: str) -> Path:
    root = Path(os.path.abspath(os.fspath(project_root)))
    private_root = root / "tmp/reddit-voc-v3"
    target = Path(
        os.path.abspath(os.fspath(path if path.is_absolute() else root / path))
    )
    try:
        relative = target.relative_to(private_root)
    except ValueError as exc:
        raise ImportValidationError(f"{label} must stay below private tmp/reddit-voc-v3") from exc
    if not relative.parts:
        raise ImportValidationError(f"{label} must stay below private tmp/reddit-voc-v3")
    return target


def _open_private_bundle_directory(
    bundle_root: Path, project_root: Path
) -> tuple[Path, list[int]]:
    root = Path(os.path.abspath(os.fspath(project_root)))
    target = _private_location(bundle_root, root, "bundle_root")
    relative = target.relative_to(root)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory_flags = flags | getattr(os, "O_DIRECTORY", 0)
    opened: list[int] = []
    try:
        root_metadata = root.lstat()
        if not stat.S_ISDIR(root_metadata.st_mode) or stat.S_ISLNK(root_metadata.st_mode):
            raise ImportValidationError("project_root must be a regular directory")
        descriptor = os.open(os.fspath(root), directory_flags)
        opened.append(descriptor)
        private_boundary_reached = False
        for part in relative.parts:
            descriptor = os.open(part, directory_flags, dir_fd=descriptor)
            opened.append(descriptor)
            if part == "reddit-voc-v3" and len(opened) >= 3:
                private_boundary_reached = True
            if private_boundary_reached:
                metadata = os.fstat(descriptor)
                if stat.S_IMODE(metadata.st_mode) & 0o077:
                    raise ImportValidationError("bundle directory ancestry must be private")
        return target, opened
    except ImportValidationError:
        for descriptor in reversed(opened):
            os.close(descriptor)
        raise
    except OSError as exc:
        for descriptor in reversed(opened):
            os.close(descriptor)
        raise ImportValidationError("bundle_root unavailable or unsafe") from exc


def _read_bundle(bundle_root: Path, project_root: Path) -> tuple[dict[str, Any], bytes, dict[str, list[dict[str, Any]]]]:
    _, opened = _open_private_bundle_directory(bundle_root, project_root)
    directory_fd = opened[-1]
    try:
        physical_names = set(os.listdir(directory_fd))
        if physical_names != {"manifest.json", *BUNDLE_FILES}:
            raise ImportValidationError("bundle physical file inventory mismatch")
        manifest_payload = _regular_file_at(directory_fd, "manifest.json", "bundle manifest")
        manifest = _json_object(manifest_payload, "bundle manifest", canonical=True)
        files = manifest.get("files")
        if not isinstance(files, dict) or set(files) != set(BUNDLE_FILES):
            raise ImportValidationError("bundle manifest file inventory mismatch")

        parsed: dict[str, list[dict[str, Any]]] = {}
        for name in BUNDLE_FILES:
            binding = files.get(name)
            if not isinstance(binding, dict):
                raise ImportValidationError(f"bundle file binding missing:{name}")
            _exact_keys(binding, {"bytes", "rows", "sha256"}, f"bundle file binding:{name}")
            payload = _regular_file_at(directory_fd, name, f"bundle file:{name}")
            if (
                binding.get("bytes") != len(payload)
                or binding.get("sha256") != _sha(payload)
            ):
                raise ImportValidationError(f"bundle file binding mismatch:{name}")
            rows = _jsonl(payload, name)
            if binding.get("rows") != len(rows):
                raise ImportValidationError(f"bundle file row binding mismatch:{name}")
            parsed[name] = rows
        return manifest, manifest_payload, parsed
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)


def _text(value: object) -> str:
    if value is None:
        return ""
    result = unicodedata.normalize("NFKC", str(value)).replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in result.split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _match_text(value: object) -> str:
    return " ".join(_text(value).split()).casefold()


def _json_scalar(value: object) -> object:
    if isinstance(value, float) and not math.isfinite(value):
        raise ImportValidationError("source annotation contains non-finite number")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _bare_id(value: object, prefix: str, label: str) -> str:
    if not isinstance(value, str):
        raise ImportValidationError(f"invalid Reddit identity:{label}")
    raw = value.strip()
    if not raw.isascii():
        raise ImportValidationError(f"invalid Reddit identity:{label}")
    result = raw.lower()
    if result.startswith(prefix):
        result = result[len(prefix) :]
    if _REDDIT_ID.fullmatch(result) is None:
        raise ImportValidationError(f"invalid Reddit identity:{label}")
    return result


def _parse_reddit_url(value: object, entity_type: str) -> tuple[str, str | None]:
    raw = str(value or "").strip()
    parsed = urlsplit(raw)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ImportValidationError("source Reddit URL invalid") from exc
    hostname_raw = parsed.hostname or ""
    scheme_raw = parsed.scheme
    if not hostname_raw.isascii() or not scheme_raw.isascii():
        raise ImportValidationError("source Reddit URL invalid")
    hostname = hostname_raw.lower()
    if (
        scheme_raw.lower() != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or not (hostname == "reddit.com" or hostname.endswith(".reddit.com"))
        or "\\" in parsed.path
    ):
        raise ImportValidationError("source Reddit URL invalid")
    parts: list[str] = []
    for raw_part in parsed.path.split("/"):
        if not raw_part:
            continue
        decoded = unquote(raw_part)
        if "/" in decoded or "\\" in decoded or decoded in {".", ".."}:
            raise ImportValidationError("source Reddit path grammar invalid")
        parts.append(decoded)
    structural = [part.lower() if part.isascii() else part for part in parts]
    if len(parts) >= 3 and structural[0] == "r" and structural[2] == "comments":
        marker = 2
    elif parts and structural[0] == "comments":
        marker = 0
    else:
        raise ImportValidationError("source Reddit comments path missing")
    if marker + 1 >= len(parts):
        raise ImportValidationError("source post identity missing")
    post_id = _bare_id(parts[marker + 1], "", "source post")
    tail = parts[marker + 2 :]
    if entity_type == "post":
        if len(tail) > 1:
            raise ImportValidationError("source post path contains comment identity")
        return post_id, None
    if len(tail) != 2:
        raise ImportValidationError("source comment identity missing")
    comment_id = _bare_id(tail[1], "", "source comment")
    return post_id, comment_id


def _floating_date(value: object) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None and value.time().isoformat() == "00:00:00":
            return value.date().isoformat()
    elif isinstance(value, date):
        return value.isoformat()
    elif isinstance(value, str):
        text = value.strip()
        if _STRICT_DATE.fullmatch(text):
            try:
                return date.fromisoformat(text).isoformat()
            except ValueError:
                pass
        if _STRICT_MIDNIGHT.fullmatch(text):
            try:
                return datetime.fromisoformat(text).date().isoformat()
            except ValueError:
                pass
    raise ImportValidationError("source floating calendar date invalid")


def _normalize_source_row(
    row: Mapping[str, object],
    source: SourceContract,
    row_ordinal: int,
) -> _SourceRow:
    raw_type = str(row.get("内容类型") or "").strip().casefold()
    if raw_type == POST_TYPE:
        entity_type = "post"
    elif raw_type == COMMENT_TYPE:
        entity_type = "comment"
    else:
        raise ImportValidationError("source entity type invalid")
    source_record_id = str(row.get("舆情ID") or "").strip()
    if not source_record_id:
        raise ImportValidationError("source record id missing")
    source_url = str(row.get("舆情链接") or "").strip()
    post_id, comment_id = _parse_reddit_url(source_url, entity_type)
    source_calendar_date = _floating_date(row.get("发布时间"))
    if not (
        source.selection_window.start_calendar_date
        <= source_calendar_date
        <= source.selection_window.end_calendar_date
    ):
        raise ImportValidationError("source row outside bound selection window")
    annotations = {
        "country": _json_scalar(row.get("国家")),
        "engagement_change": _json_scalar(row.get("转赞评数量环比")),
        "engagement_count": _json_scalar(row.get("转赞评数量")),
        "follower_count": _json_scalar(row.get("粉丝数量")),
        "handling_status": _json_scalar(row.get("处理状态")),
        "issue_category": _json_scalar(row.get("问题类别")),
        "product_category": _json_scalar(row.get("产品分类")),
        "relevance": _json_scalar(row.get("相关性")),
        "sentiment": _json_scalar(row.get("情感描述")),
        "severity": _json_scalar(row.get("舆情等级")),
        "source_name": _json_scalar(row.get("来源")),
        "view_change": _json_scalar(row.get("浏览量环比")),
        "view_count": _json_scalar(row.get("浏览量")),
    }
    return _SourceRow(
        source_snapshot_id=source.source_snapshot_id,
        source_row_ordinal=row_ordinal,
        source_record_id=source_record_id,
        source_url=source_url,
        entity_type=entity_type,
        post_id=post_id,
        comment_id=comment_id,
        source_text=_text(row.get("标题")),
        source_summary=_text(row.get("内容概要")),
        source_calendar_date=source_calendar_date,
        source_file_sha256=source.sha256,
        selection_class=source.selection_class,
        query_profile_status=source.query_profile_status,
        allowed_metric_families=source.allowed_metric_families,
        blocked_uses=source.blocked_uses,
        source_annotations=annotations,
    )


def _read_source_rows(manifest: SourceManifest, project_root: Path) -> tuple[_SourceRow, ...]:
    rows: list[_SourceRow] = []
    for source in manifest.sources:
        payload = _regular_relative_once(
            project_root,
            source.relative_path,
            f"source workbook:{source.source_snapshot_id}",
        )
        if len(payload) != source.bytes or _sha(payload) != source.sha256:
            raise ImportValidationError(f"source workbook binding mismatch:{source.source_snapshot_id}")
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="Workbook contains no default style, apply openpyxl's default",
                    category=UserWarning,
                )
                workbook = load_workbook(BytesIO(payload), read_only=False, data_only=True)
        except Exception as exc:
            raise ImportValidationError(f"source workbook unreadable:{source.source_snapshot_id}") from exc
        try:
            if source.workbook.sheet_name not in workbook.sheetnames:
                raise ImportValidationError(f"source worksheet missing:{source.source_snapshot_id}")
            sheet = workbook[source.workbook.sheet_name]
            if sheet.calculate_dimension() != source.workbook.expected_dimension:
                raise ImportValidationError(f"source worksheet dimension mismatch:{source.source_snapshot_id}")
            headers = tuple(sheet.cell(1, column).value for column in range(1, 22))
            if headers != source.workbook.expected_headers:
                raise ImportValidationError(f"source worksheet headers mismatch:{source.source_snapshot_id}")
            before = len(rows)
            entity_counts: Counter[str] = Counter()
            for ordinal, values in enumerate(
                sheet.iter_rows(min_row=2, max_col=21, values_only=True), start=2
            ):
                normalized = _normalize_source_row(
                    dict(zip(headers, values, strict=True)), source, ordinal
                )
                rows.append(normalized)
                entity_counts[normalized.entity_type] += 1
            if len(rows) - before != source.workbook.expected_data_rows:
                raise ImportValidationError(f"source workbook row count mismatch:{source.source_snapshot_id}")
            if entity_counts != Counter(
                post=source.workbook.expected_post_rows,
                comment=source.workbook.expected_comment_rows,
            ):
                raise ImportValidationError(f"source workbook entity count mismatch:{source.source_snapshot_id}")
        finally:
            workbook.close()
    occurrence_keys = [row.occurrence_key for row in rows]
    if len(set(occurrence_keys)) != len(occurrence_keys):
        raise ImportValidationError("source occurrence keys are not unique")
    return tuple(sorted(rows, key=lambda row: (row.source_snapshot_id, row.source_row_ordinal, row.source_record_id)))


def _bound_base_member(
    project_root: Path,
    root_relative: PurePosixPath,
    inventory: Mapping[str, object],
    name: str,
    label: str,
) -> tuple[list[dict[str, Any]], dict[str, object]]:
    binding = inventory.get(name)
    if not isinstance(binding, dict):
        raise ImportValidationError(f"Base file binding missing:{name}")
    payload = _regular_relative_once(project_root, root_relative / name, f"{label}:{name}")
    if binding.get("bytes") != len(payload) or binding.get("sha256") != _sha(payload):
        raise ImportValidationError(f"Base file binding mismatch:{name}")
    return _json_list(payload, f"{label}:{name}"), {
        "bytes": len(payload),
        "sha256": _sha(payload),
    }


def _permalink_post_id(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    raw = value.strip()
    parsed_value = f"https://reddit.com{raw}" if raw.startswith("/") else raw
    parsed = urlsplit(parsed_value)
    hostname_raw = parsed.hostname or ""
    if not hostname_raw.isascii():
        return None
    hostname = hostname_raw.lower()
    if hostname and not (hostname == "reddit.com" or hostname.endswith(".reddit.com")):
        return None
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    structural = [part.lower() if part.isascii() else part for part in parts]
    if structural[:1] == ["gallery"] and len(parts) == 2:
        return _bare_id(parts[1], "t3_", "Base gallery permalink")
    if "comments" not in structural:
        return None
    marker = structural.index("comments")
    if marker + 1 >= len(parts):
        return None
    candidate = parts[marker + 1]
    return _bare_id(candidate, "t3_", "Base permalink")


def _base_comment_parent(value: object, post_id: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip().isascii():
        raise ImportValidationError("Base comment parent_id invalid")
    raw = value.strip().lower()
    if raw.startswith("t3_"):
        parent = _bare_id(raw, "t3_", "Base comment root parent")
        if parent != post_id:
            raise ImportValidationError("Base comment root parent disagreement")
        return f"t3_{parent}"
    if raw.startswith("t1_"):
        return f"t1_{_bare_id(raw, 't1_', 'Base comment parent')}"
    raise ImportValidationError("Base comment parent_id invalid")


def _canonical_counts(value: Mapping[str, Any], label: str) -> dict[str, int]:
    raw = value.get("canonical_counts")
    if not isinstance(raw, dict):
        raise ImportValidationError(f"{label} canonical counts missing")
    result: dict[str, int] = {}
    for key in ("posts", "linked_comments", "quarantined_comments", "stored_comments"):
        item = raw.get(key)
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise ImportValidationError(f"{label} canonical count invalid:{key}")
        result[key] = item
    if result["stored_comments"] != result["linked_comments"] + result["quarantined_comments"]:
        raise ImportValidationError(f"{label} canonical comment counts do not conserve")
    return result


def _base_maps(
    posts: Sequence[dict[str, Any]],
    comments: Sequence[dict[str, Any]],
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    set[str],
    list[dict[str, object]],
]:
    post_map: dict[str, dict[str, Any]] = {}
    comment_map: dict[str, dict[str, Any]] = {}
    held: set[str] = set()
    conflicts: list[dict[str, object]] = []
    for item in posts:
        post_id = _bare_id(item.get("post_id"), "t3_", "Base post")
        reddit_id = item.get("reddit_id")
        if reddit_id is not None and _bare_id(reddit_id, "t3_", "Base post reddit_id") != post_id:
            raise ImportValidationError("Base post redundant identity disagreement")
        observed = _permalink_post_id(item.get("permalink"))
        if observed is not None and observed != post_id:
            held.add(post_id)
            conflicts.append(
                {
                    "canonical_reddit_id": f"t3_{post_id}",
                    "conflict_type": "base_permalink_identity_disagreement",
                    "entity_type": "post",
                    "governed_post_id": post_id,
                    "observed_permalink_post_id": observed,
                    "resolution": "held_identity_conflict",
                    "schema_version": CONFLICT_SCHEMA,
                }
            )
        if post_id in post_map:
            raise ImportValidationError("duplicate Base post identity")
        post_map[post_id] = item
    for item in comments:
        comment_id = _bare_id(item.get("comment_id"), "t1_", "Base comment")
        reddit_id = item.get("reddit_id")
        if reddit_id is not None and _bare_id(reddit_id, "t1_", "Base comment reddit_id") != comment_id:
            raise ImportValidationError("Base comment redundant identity disagreement")
        post_id = _bare_id(item.get("post_id"), "t3_", "Base comment post_id")
        if post_id not in post_map:
            raise ImportValidationError("Base comment parent identity missing")
        _base_comment_parent(item.get("parent_id"), post_id)
        if comment_id in comment_map:
            raise ImportValidationError("duplicate Base comment identity")
        comment_map[comment_id] = item
    return post_map, comment_map, held, conflicts


def _read_base(manifest: SourceManifest, project_root: Path) -> _BaseData:
    public_payload = _regular_relative_once(
        project_root, manifest.base.manifest_relative_path, "Base public manifest"
    )
    lineage_payload = _regular_relative_once(
        project_root, manifest.base.lineage_manifest_relative_path, "Base lineage manifest"
    )
    if _sha(public_payload) != manifest.base.public_manifest_sha256:
        raise ImportValidationError("Base public manifest sha256 mismatch")
    if _sha(lineage_payload) != manifest.base.lineage_manifest_sha256:
        raise ImportValidationError("Base lineage manifest sha256 mismatch")
    public_manifest = _json_object(public_payload, "Base public manifest")
    lineage_manifest = _json_object(lineage_payload, "Base lineage manifest")
    for label, value in (("Base public", public_manifest), ("Base lineage", lineage_manifest)):
        if value.get("dataset_version") != manifest.base.dataset_version:
            raise ImportValidationError(f"{label} dataset_version mismatch")
        if value.get("schema_version") not in {
            "reddit_voc_site_snapshot_manifest_v1",
            "reddit_voc_site_snapshot_manifest_v2",
        }:
            raise ImportValidationError(f"{label} schema unsupported")
        if not isinstance(value.get("files"), dict):
            raise ImportValidationError(f"{label} file inventory missing")
    projection = public_manifest.get("projection")
    if not isinstance(projection, dict) or projection.get("audience") != "public_ui":
        raise ImportValidationError("Base public manifest role mismatch")
    if not isinstance(lineage_manifest.get("source_boundaries"), dict):
        raise ImportValidationError("Base lineage manifest role mismatch")

    public_root = manifest.base.manifest_relative_path.parent
    lineage_root = manifest.base.lineage_manifest_relative_path.parent
    public_posts, public_posts_binding = _bound_base_member(
        project_root, public_root, public_manifest["files"], "posts-public.json", "Base public"
    )
    public_comments, public_comments_binding = _bound_base_member(
        project_root, public_root, public_manifest["files"], "comments-public.json", "Base public"
    )
    private_posts, private_posts_binding = _bound_base_member(
        project_root, lineage_root, lineage_manifest["files"], "posts.json", "Base lineage"
    )
    private_comments, private_comments_binding = _bound_base_member(
        project_root, lineage_root, lineage_manifest["files"], "comments.json", "Base lineage"
    )
    quarantine_rows, quarantine_binding = _bound_base_member(
        project_root, lineage_root, lineage_manifest["files"], "quarantine.json", "Base lineage"
    )
    unresolved_rows: list[dict[str, Any]] = []
    unresolved_binding: dict[str, object] | None = None
    raw_unresolved_binding = lineage_manifest["files"].get(
        "unresolved-parent-ledger.jsonl"
    )
    if raw_unresolved_binding is not None:
        if not isinstance(raw_unresolved_binding, dict):
            raise ImportValidationError(
                "Base file binding missing:unresolved-parent-ledger.jsonl"
            )
        unresolved_payload = _regular_relative_once(
            project_root,
            lineage_root / "unresolved-parent-ledger.jsonl",
            "Base lineage:unresolved-parent-ledger.jsonl",
        )
        unresolved_sha = _sha(unresolved_payload)
        if (
            raw_unresolved_binding.get("bytes") != len(unresolved_payload)
            or raw_unresolved_binding.get("sha256") != unresolved_sha
        ):
            raise ImportValidationError(
                "Base file binding mismatch:unresolved-parent-ledger.jsonl"
            )
        unresolved_rows = _jsonl(
            unresolved_payload,
            "Base lineage:unresolved-parent-ledger.jsonl",
        )
        unresolved_binding = {
            "bytes": len(unresolved_payload),
            "sha256": unresolved_sha,
        }
    public_post_map, public_comment_map, public_held, public_conflicts = _base_maps(
        public_posts, public_comments
    )
    post_map, comment_map, held, conflicts = _base_maps(private_posts, private_comments)
    if set(public_post_map) != set(post_map) or set(public_comment_map) != set(comment_map):
        raise ImportValidationError("Base public/private identity drift")
    if public_held != held or public_conflicts != conflicts:
        raise ImportValidationError("Base public/private conflict drift")
    for comment_id, item in comment_map.items():
        public = public_comment_map[comment_id]
        private_post = _bare_id(item.get("post_id"), "t3_", "Base private comment post_id")
        public_post = _bare_id(public.get("post_id"), "t3_", "Base public comment post_id")
        if private_post != public_post:
            raise ImportValidationError("Base public/private comment parent drift")
        if _base_comment_parent(item.get("parent_id"), private_post) != _base_comment_parent(
            public.get("parent_id"), public_post
        ):
            raise ImportValidationError("Base public/private comment parent_id drift")
    quarantine: dict[str, dict[str, Any]] = {}
    for item in quarantine_rows:
        comment_id = _bare_id(item.get("comment_id"), "t1_", "Base quarantine")
        reddit_id = item.get("reddit_id")
        if reddit_id is not None and _bare_id(reddit_id, "t1_", "Base quarantine reddit_id") != comment_id:
            raise ImportValidationError("Base quarantine redundant identity disagreement")
        missing_post = _bare_id(item.get("missing_post_id"), "t3_", "Base quarantine missing_post_id")
        if missing_post in post_map:
            raise ImportValidationError("Base quarantined parent unexpectedly exists")
        if comment_id in comment_map or comment_id in quarantine:
            raise ImportValidationError("Base quarantine identity conflict")
        quarantine[comment_id] = item
    unresolved: dict[str, dict[str, Any]] = {}
    for item in unresolved_rows:
        comment_id = _bare_id(
            item.get("canonical_reddit_id"),
            "t1_",
            "Base unresolved parent",
        )
        _bare_id(
            item.get("post_id"),
            "t3_",
            "Base unresolved parent post_id",
        )
        if item.get("comment_state") != "unresolved_parent":
            raise ImportValidationError("Base unresolved parent state is invalid")
        if item.get("schema_version") != "reddit_voc_canonical_unresolved_parent_v1":
            raise ImportValidationError("Base unresolved parent schema is invalid")
        if comment_id in unresolved:
            raise ImportValidationError(
                "duplicate Base unresolved parent identity"
            )
        unresolved[comment_id] = item
    public_counts = _canonical_counts(public_manifest, "Base public manifest")
    lineage_counts = _canonical_counts(lineage_manifest, "Base lineage manifest")
    actual_counts = {
        "posts": len(post_map),
        "linked_comments": len(comment_map),
        "quarantined_comments": len(quarantine),
        "stored_comments": len(comment_map) + len(quarantine),
    }
    if public_counts != lineage_counts or lineage_counts != actual_counts:
        raise ImportValidationError("Base canonical physical counts mismatch")
    return _BaseData(
        posts=post_map,
        comments=comment_map,
        quarantine=quarantine,
        unresolved=unresolved,
        held_post_ids=frozenset(held),
        conflicts=tuple(conflicts),
        public_file_bindings={
            "comments-public.json": public_comments_binding,
            "posts-public.json": public_posts_binding,
        },
        lineage_file_bindings={
            "comments.json": private_comments_binding,
            "posts.json": private_posts_binding,
            "quarantine.json": quarantine_binding,
            **(
                {"unresolved-parent-ledger.jsonl": unresolved_binding}
                if unresolved_binding is not None
                else {}
            ),
        },
    )


def _classify(rows: Sequence[_SourceRow], base: _BaseData) -> _Classification:
    grouped: dict[tuple[str, str], list[_SourceRow]] = defaultdict(list)
    for row in rows:
        grouped[(row.entity_type, row.bare_entity_id)].append(row)
    groups = {key: tuple(value) for key, value in grouped.items()}
    representatives = {
        key: next((row for row in group if _match_text(row.source_text)), group[0])
        for key, group in groups.items()
    }
    source_posts = {
        entity_id: representatives[(entity_type, entity_id)]
        for entity_type, entity_id in groups
        if entity_type == "post"
    }
    base_records: dict[tuple[str, str], tuple[dict[str, Any], str]] = {}
    held_keys: set[tuple[str, str]] = set()
    base_held_keys: set[tuple[str, str]] = set()
    conflicts: list[dict[str, object]] = [dict(item) for item in base.conflicts]

    for key, group in sorted(groups.items()):
        entity_type, entity_id = key
        row = representatives[key]
        if entity_type == "post" and entity_id in base.posts:
            base_records[key] = (base.posts[entity_id], "post")
            if entity_id in base.held_post_ids:
                base_held_keys.add(key)
        elif entity_type == "comment" and entity_id in base.comments:
            base_records[key] = (base.comments[entity_id], "linked_comment")
            if _bare_id(base.comments[entity_id].get("post_id"), "t3_", "Base comment post") in base.held_post_ids:
                base_held_keys.add(key)
        elif entity_type == "comment" and entity_id in base.quarantine:
            base_records[key] = (base.quarantine[entity_id], "quarantined_comment")
        elif entity_type == "comment" and entity_id in base.unresolved:
            base_records[key] = (base.unresolved[entity_id], "unresolved_comment")

        candidate_post_ids = sorted({item.post_id for item in group}) if entity_type == "comment" else []
        governed_post_id: str | None = None
        if entity_type == "comment" and entity_id in base.comments:
            governed_post_id = _bare_id(base.comments[entity_id].get("post_id"), "t3_", "Base comment post")
        elif entity_type == "comment" and entity_id in base.quarantine:
            governed_post_id = _bare_id(
                base.quarantine[entity_id].get("missing_post_id"), "t3_", "Base quarantine post"
            )
        held_parent = (
            entity_type == "comment"
            and key not in base_records
            and len(candidate_post_ids) == 1
            and candidate_post_ids[0] in base.held_post_ids
        )
        parent_conflict = entity_type == "comment" and (
            len(candidate_post_ids) != 1
            or (governed_post_id is not None and candidate_post_ids != [governed_post_id])
        )
        source_text_hashes = sorted(
            {
                _sha(_match_text(item.source_text).encode("utf-8"))
                for item in group
                if _match_text(item.source_text)
            }
        )
        source_text_conflict = len(source_text_hashes) > 1 and key not in base_records
        if parent_conflict or held_parent or source_text_conflict:
            held_keys.add(key)
            if parent_conflict:
                conflicts.append(
                    {
                        "candidate_post_ids": candidate_post_ids,
                        "canonical_reddit_id": row.canonical_reddit_id,
                        "conflict_type": "comment_parent_identity_conflict",
                        "entity_type": "comment",
                        "governed_post_id": governed_post_id,
                        "resolution": "held_pending_review",
                        "schema_version": CONFLICT_SCHEMA,
                        "source_occurrences": [item.occurrence_dict() for item in group],
                    }
                )
            if held_parent:
                conflicts.append(
                    {
                        "candidate_post_ids": candidate_post_ids,
                        "canonical_reddit_id": row.canonical_reddit_id,
                        "conflict_type": "base_parent_identity_conflict",
                        "entity_type": "comment",
                        "governed_post_id": candidate_post_ids[0],
                        "resolution": "held_pending_review",
                        "schema_version": CONFLICT_SCHEMA,
                        "source_occurrences": [item.occurrence_dict() for item in group],
                    }
                )
            if source_text_conflict:
                conflicts.append(
                    {
                        "canonical_reddit_id": row.canonical_reddit_id,
                        "conflict_type": "source_text_conflict_without_governed_base",
                        "entity_type": entity_type,
                        "resolution": "held_pending_review",
                        "schema_version": CONFLICT_SCHEMA,
                        "source_occurrences": [item.occurrence_dict() for item in group],
                        "source_text_sha256s": source_text_hashes,
                    }
                )

    row_outcomes: dict[str, str] = {}
    entity_outcomes: dict[tuple[str, str], str] = {}
    parent_links: list[dict[str, object]] = []
    for key in sorted(groups, key=lambda item: (0 if item[0] == "post" else 1, item[1])):
        group = groups[key]
        row = representatives[key]
        entity_type, _ = key
        base_record, base_state = base_records.get(key, (None, None))
        if key in held_keys:
            outcome = "identity_conflict"
            for item in group:
                row_outcomes[item.occurrence_key] = outcome
        elif base_record is not None:
            outcome = "exact_base_overlap"
            row_outcomes[group[0].occurrence_key] = outcome
            for item in group[1:]:
                row_outcomes[item.occurrence_key] = "duplicate"
            base_texts = (
                {_match_text(base_record.get("title")), _match_text(base_record.get("content"))}
                if entity_type == "post"
                else {_match_text(base_record.get("body"))}
            )
            base_texts.discard("")
            source_texts = {_match_text(item.source_text) for item in group if _match_text(item.source_text)}
            differing = source_texts - base_texts
            if differing and base_texts:
                conflicts.append(
                    {
                        "base_entity_sha256": _sha(_canonical_bytes(base_record)),
                        "base_text_sha256s": sorted(_sha(item.encode("utf-8")) for item in base_texts),
                        "canonical_reddit_id": row.canonical_reddit_id,
                        "conflict_type": "source_text_differs_from_governed_base",
                        "entity_type": entity_type,
                        "resolution": "governed_base_wins",
                        "schema_version": CONFLICT_SCHEMA,
                        "source_occurrences": [item.occurrence_dict() for item in group],
                        "source_text_sha256s": sorted(_sha(item.encode("utf-8")) for item in differing),
                    }
                )
            elif source_texts and not base_texts:
                conflicts.append(
                    {
                        "base_entity_sha256": _sha(_canonical_bytes(base_record)),
                        "base_text_sha256s": [],
                        "canonical_reddit_id": row.canonical_reddit_id,
                        "conflict_type": "governed_base_text_missing_source_fill_candidate",
                        "entity_type": entity_type,
                        "resolution": "defer_to_canonical_fusion",
                        "schema_version": CONFLICT_SCHEMA,
                        "source_occurrences": [item.occurrence_dict() for item in group],
                        "source_text_sha256s": sorted(_sha(item.encode("utf-8")) for item in source_texts),
                    }
                )
        elif entity_type == "comment":
            post_id = row.post_id
            if post_id in base.posts:
                parent_status = "linked_base_post"
                parent_text = _match_text(base.posts[post_id].get("title")) or _match_text(
                    base.posts[post_id].get("content")
                )
            elif post_id in source_posts:
                parent_status = "linked_workbook_post"
                parent_text = _match_text(source_posts[post_id].source_text)
            else:
                parent_status = "unresolved_parent"
                parent_text = ""
            if parent_status == "unresolved_parent":
                outcome = "unresolved_parent"
            elif not _match_text(row.source_text) or not parent_text:
                outcome = "incomplete_text"
            else:
                outcome = "net_new_text_ready"
            row_outcomes[group[0].occurrence_key] = outcome
            for item in group[1:]:
                row_outcomes[item.occurrence_key] = "duplicate"
        elif not _match_text(row.source_text):
            outcome = "incomplete_text"
            row_outcomes[group[0].occurrence_key] = outcome
            for item in group[1:]:
                row_outcomes[item.occurrence_key] = "duplicate"
        else:
            outcome = "net_new_text_ready"
            row_outcomes[group[0].occurrence_key] = outcome
            for item in group[1:]:
                row_outcomes[item.occurrence_key] = "duplicate"
        entity_outcomes[key] = outcome

        if entity_type == "comment":
            if key in held_keys:
                parent_status = "identity_conflict"
                parent_text = ""
                parent_id: str | None = None
            elif key in base_held_keys:
                parent_status = "held_governed_base_parent_identity_conflict"
                parent_text = ""
                parent_id = (
                    _bare_id(base_record.get("post_id"), "t3_", "Base held comment post")
                    if base_state == "linked_comment" and base_record is not None
                    else row.post_id
                )
            elif base_state == "linked_comment" and base_record is not None:
                parent_id = _bare_id(base_record.get("post_id"), "t3_", "Base linked comment post")
                parent = base.posts[parent_id]
                parent_text = _match_text(parent.get("title")) or _match_text(parent.get("content"))
                parent_status = "linked_governed_base_comment"
            elif base_state == "quarantined_comment":
                parent_id = None
                parent_text = ""
                parent_status = "quarantined_governed_base_comment"
            else:
                parent_id = row.post_id
                if parent_id in base.posts:
                    parent = base.posts[parent_id]
                    parent_text = _match_text(parent.get("title")) or _match_text(parent.get("content"))
                    parent_status = "linked_base_post"
                elif parent_id in source_posts and ("post", parent_id) not in held_keys:
                    parent_text = _match_text(source_posts[parent_id].source_text)
                    parent_status = "linked_workbook_post"
                else:
                    parent_text = ""
                    parent_status = "unresolved_parent"
            parent_links.append(
                {
                    "candidate_post_ids": sorted({item.post_id for item in group}),
                    "comment_id": f"t1_{row.comment_id}",
                    "context_available": bool(parent_text),
                    "parent_link_status": parent_status,
                    "post_id": parent_id,
                    "schema_version": PARENT_LINK_SCHEMA,
                    "terminal_outcome": outcome,
                }
            )

    ordered_conflicts = tuple(
        sorted(
            conflicts,
            key=lambda item: (
                str(item["entity_type"]),
                str(item["canonical_reddit_id"]),
                str(item["conflict_type"]),
                _canonical_bytes(item),
            ),
        )
    )
    return _Classification(
        groups=groups,
        representatives=representatives,
        row_outcomes=row_outcomes,
        entity_outcomes=entity_outcomes,
        base_records=base_records,
        held_keys=frozenset(held_keys),
        base_held_keys=frozenset(base_held_keys),
        parent_links=tuple(sorted(parent_links, key=lambda item: str(item["comment_id"]))),
        conflicts=ordered_conflicts,
    )


def _expected_entity(
    key: tuple[str, str],
    classification: _Classification,
    manifest: SourceManifest,
) -> dict[str, object]:
    row = classification.representatives[key]
    group = classification.groups[key]
    outcome = classification.entity_outcomes[key]
    base_record, base_state = classification.base_records.get(key, (None, None))
    is_overlap = base_record is not None
    base_held = key in classification.base_held_keys
    if outcome == "identity_conflict" or base_held:
        analysis_status = (
            "governed_base_anchor_held_identity_conflict"
            if is_overlap
            else "held_identity_conflict"
        )
        eligibility_basis = "held_identity_conflict"
        eligibility_status = "excluded_identity_conflict"
        effective_families: list[str] | None = []
    elif outcome == "exact_base_overlap" and base_state == "quarantined_comment":
        analysis_status = "governed_base_quarantine"
        eligibility_basis = "held_quarantine"
        eligibility_status = "excluded_quarantine"
        effective_families = []
    elif outcome == "exact_base_overlap":
        analysis_status = "governed_base_anchor"
        eligibility_basis = "governed_base_anchor"
        eligibility_status = "pending_governed_base_fusion"
        effective_families = None
    else:
        analysis_status = "ready" if outcome == "net_new_text_ready" else outcome
        eligibility_basis = "workbook_source_policy"
        eligibility_status = "source_policy_applied"
        effective_families = list(row.allowed_metric_families)
    value: dict[str, object] = {
        "allowed_metric_families": list(row.allowed_metric_families),
        "analysis_status": analysis_status,
        "base_overlap": is_overlap,
        "blocked_uses": list(row.blocked_uses),
        "canonical_reddit_id": row.canonical_reddit_id,
        "comment_id": f"t1_{row.comment_id}" if row.entity_type == "comment" else None,
        "effective_allowed_metric_families": effective_families,
        "effective_metric_eligibility_status": eligibility_status,
        "entity_type": row.entity_type,
        "event_time_precision": "day",
        "metric_eligibility_basis": eligibility_basis,
        "post_id": row.post_id,
        "query_profile_status": row.query_profile_status,
        "schema_version": ENTITY_SCHEMA,
        "selection_class": row.selection_class,
        "source_annotations": dict(row.source_annotations),
        "source_calendar_date": row.source_calendar_date,
        "source_occurrences": [item.occurrence_dict() for item in group],
        "source_record_id": row.source_record_id,
        "source_row_ordinal": row.source_row_ordinal,
        "source_snapshot_id": row.source_snapshot_id,
        "source_summary": row.source_summary,
        "source_summary_status": "source_derived_provenance_only",
        "source_text": row.source_text,
        "source_text_role": "reddit_original_text",
        "source_timezone_status": "unknown",
        "source_url": row.source_url,
        "terminal_outcome": outcome,
        "workbook_metric_eligibility_ignored_for_overlap": is_overlap,
    }
    if base_record is not None:
        source_occurrences = base_record.get("source_occurrences")
        value["base_anchor"] = {
            "canonical_reddit_id": row.canonical_reddit_id,
            "canonical_state": base_state,
            "dataset_version": manifest.base.dataset_version,
            "entity_sha256": _sha(_canonical_bytes(base_record)),
            "identity_status": "held_identity_conflict"
            if base_held or outcome == "identity_conflict"
            else "governed",
            "lineage_manifest_sha256": manifest.base.lineage_manifest_sha256,
            "public_manifest_sha256": manifest.base.public_manifest_sha256,
            "source_occurrence_count": len(source_occurrences)
            if isinstance(source_occurrences, list)
            else None,
        }
    return value


def _validate_row_outcomes(
    rows: Sequence[dict[str, Any]],
    source_rows: Sequence[_SourceRow],
    classification: _Classification,
) -> Counter[str]:
    if len(rows) != len(source_rows):
        raise ImportValidationError("row outcome count mismatch")
    expected_by_key = {row.occurrence_key: row for row in source_rows}
    seen: set[str] = set()
    counts: Counter[str] = Counter()
    for actual in rows:
        _exact_keys(
            actual,
            {
                "canonical_reddit_id",
                "entity_type",
                "occurrence_key",
                "post_id",
                "schema_version",
                "source_record_id",
                "source_row_ordinal",
                "source_snapshot_id",
                "terminal_outcome",
            },
            "row outcome",
        )
        occurrence_key = actual.get("occurrence_key")
        if not isinstance(occurrence_key, str) or occurrence_key in seen:
            raise ImportValidationError("row outcome occurrence is duplicate or invalid")
        seen.add(occurrence_key)
        source = expected_by_key.get(occurrence_key)
        if source is None:
            raise ImportValidationError("row outcome foreign key missing")
        expected = {
            "canonical_reddit_id": source.canonical_reddit_id,
            "entity_type": source.entity_type,
            "occurrence_key": source.occurrence_key,
            "post_id": source.post_id,
            "schema_version": ROW_OUTCOME_SCHEMA,
            "source_record_id": source.source_record_id,
            "source_row_ordinal": source.source_row_ordinal,
            "source_snapshot_id": source.source_snapshot_id,
            "terminal_outcome": classification.row_outcomes[source.occurrence_key],
        }
        if actual != expected:
            raise ImportValidationError(f"row outcome mismatch:{occurrence_key}")
        counts[str(actual["terminal_outcome"])] += 1
    if seen != set(expected_by_key):
        raise ImportValidationError("row outcome source coverage mismatch")
    if set(counts) - set(TERMINAL_OUTCOMES):
        raise ImportValidationError("row outcome terminal value invalid")
    return counts


def _validate_entities(
    posts: Sequence[dict[str, Any]],
    comments: Sequence[dict[str, Any]],
    classification: _Classification,
    manifest: SourceManifest,
) -> set[str]:
    expected_keys = set(classification.groups)
    actual_keys: set[tuple[str, str]] = set()
    occurrence_keys: set[str] = set()
    for expected_type, rows in (("post", posts), ("comment", comments)):
        previous_id = ""
        for actual in rows:
            if actual.get("schema_version") != ENTITY_SCHEMA or actual.get("entity_type") != expected_type:
                raise ImportValidationError("entity schema or type mismatch")
            canonical = actual.get("canonical_reddit_id")
            if not isinstance(canonical, str):
                raise ImportValidationError("entity canonical identity missing")
            prefix = "t3_" if expected_type == "post" else "t1_"
            entity_id = _bare_id(canonical, prefix, "bundle entity")
            if canonical != f"{prefix}{entity_id}" or entity_id <= previous_id:
                raise ImportValidationError("entity identity order or prefix mismatch")
            previous_id = entity_id
            key = (expected_type, entity_id)
            if key in actual_keys:
                raise ImportValidationError("duplicate import entity identity")
            actual_keys.add(key)
            if key not in classification.groups:
                raise ImportValidationError("entity foreign key missing from source")
            expected = _expected_entity(key, classification, manifest)
            actual_occurrences = actual.get("source_occurrences")
            if actual_occurrences != expected["source_occurrences"]:
                raise ImportValidationError(f"source occurrence mismatch:{canonical}")
            if actual != expected:
                raise ImportValidationError(f"entity field or status mismatch:{canonical}")
            for occurrence in actual_occurrences:
                if not isinstance(occurrence, dict):
                    raise ImportValidationError("source occurrence is not an object")
                key_value = occurrence.get("occurrence_key")
                if not isinstance(key_value, str) or key_value in occurrence_keys:
                    raise ImportValidationError("source occurrence duplicate or invalid")
                occurrence_keys.add(key_value)
    if actual_keys != expected_keys:
        raise ImportValidationError("import entity identity set mismatch")
    return occurrence_keys


def _validate_parent_links(
    rows: Sequence[dict[str, Any]], classification: _Classification
) -> None:
    if tuple(rows) != classification.parent_links:
        raise ImportValidationError("parent-link ledger mismatch")
    seen: set[str] = set()
    comment_ids = {
        f"t1_{entity_id}" for entity_type, entity_id in classification.groups if entity_type == "comment"
    }
    for row in rows:
        _exact_keys(
            row,
            {
                "candidate_post_ids",
                "comment_id",
                "context_available",
                "parent_link_status",
                "post_id",
                "schema_version",
                "terminal_outcome",
            },
            "parent-link ledger row",
        )
        comment_id = row.get("comment_id")
        if not isinstance(comment_id, str) or comment_id in seen or comment_id not in comment_ids:
            raise ImportValidationError("parent-link comment foreign key invalid")
        seen.add(comment_id)
    if seen != comment_ids:
        raise ImportValidationError("parent-link comment coverage mismatch")


def _validate_conflicts(
    rows: Sequence[dict[str, Any]], classification: _Classification
) -> None:
    if tuple(rows) != classification.conflicts:
        raise ImportValidationError("conflict ledger mismatch")
    entity_ids = {
        f"{'t3' if entity_type == 'post' else 't1'}_{entity_id}"
        for entity_type, entity_id in classification.groups
    }
    entity_ids.update(str(item["canonical_reddit_id"]) for item in classification.conflicts if item["conflict_type"] == "base_permalink_identity_disagreement")
    for row in rows:
        if row.get("schema_version") != CONFLICT_SCHEMA:
            raise ImportValidationError("conflict ledger schema mismatch")
        if row.get("canonical_reddit_id") not in entity_ids:
            raise ImportValidationError("conflict ledger entity foreign key invalid")


def _validate_bundle_manifest(
    bundle_manifest: dict[str, Any],
    source_manifest: SourceManifest,
    base: _BaseData,
    counts: dict[str, object],
) -> None:
    _exact_keys(
        bundle_manifest,
        {
            "base",
            "boundaries",
            "consumption_status",
            "counts",
            "dataset_id",
            "files",
            "independent_validation_status",
            "promotable",
            "schema_version",
            "source_manifest_sha256",
            "source_semantics",
            "status",
            "validation_receipt_sha256",
        },
        "bundle manifest",
    )
    if bundle_manifest.get("schema_version") != BUNDLE_SCHEMA:
        raise ImportValidationError("bundle manifest schema mismatch")
    if bundle_manifest.get("dataset_id") != source_manifest.dataset_id:
        raise ImportValidationError("bundle dataset_id mismatch")
    if bundle_manifest.get("source_manifest_sha256") != source_manifest.manifest_sha256:
        raise ImportValidationError("bundle source manifest sha256 mismatch")
    if bundle_manifest.get("boundaries") != BOUNDARIES:
        raise ImportValidationError("bundle boundaries mismatch")
    if (
        bundle_manifest.get("status") != "candidate_built"
        or bundle_manifest.get("independent_validation_status") != "pending"
        or bundle_manifest.get("consumption_status") != "blocked_pending_independent_validation"
        or bundle_manifest.get("promotable") is not False
        or bundle_manifest.get("validation_receipt_sha256") is not None
    ):
        raise ImportValidationError("bundle lifecycle must remain a blocked candidate")
    if bundle_manifest.get("source_semantics") != {
        "derived_summary_role": "provenance_only",
        "event_time_precision": "day",
        "source_text_column": "标题",
        "source_text_role": "reddit_original_text",
        "source_timezone_status": "unknown",
    }:
        raise ImportValidationError("bundle source semantics mismatch")
    if bundle_manifest.get("counts") != counts:
        raise ImportValidationError("bundle recomputed counts mismatch")
    expected_base = {
        "dataset_version": source_manifest.base.dataset_version,
        "identity_reconciliation": {
            "held_identity_conflicts": len(base.held_post_ids),
            "linked_comments": len(base.comments),
            "posts": len(base.posts),
            "public_private_identity_sets_equal": True,
            "quarantined_comments": len(base.quarantine),
            "redundant_identity_conflicts": len(base.conflicts),
            "stored_comments": len(base.comments) + len(base.quarantine),
            **(
                {"unresolved_parent_comments": len(base.unresolved)}
                if "unresolved-parent-ledger.jsonl" in base.lineage_file_bindings
                else {}
            ),
        },
        "lineage_file_bindings": base.lineage_file_bindings,
        "lineage_manifest_relative_path": source_manifest.base.lineage_manifest_relative_path.as_posix(),
        "lineage_manifest_sha256": source_manifest.base.lineage_manifest_sha256,
        "public_file_bindings": base.public_file_bindings,
        "public_manifest_relative_path": source_manifest.base.manifest_relative_path.as_posix(),
        "public_manifest_sha256": source_manifest.base.public_manifest_sha256,
    }
    if bundle_manifest.get("base") != expected_base:
        raise ImportValidationError("bundle Base binding or reconciliation mismatch")


def _computed_counts(
    source_rows: Sequence[_SourceRow],
    classification: _Classification,
    terminal_counts: Counter[str],
) -> dict[str, object]:
    distinct_posts = sum(1 for key in classification.groups if key[0] == "post")
    distinct_comments = sum(1 for key in classification.groups if key[0] == "comment")
    overlap_posts = sum(1 for key in classification.base_records if key[0] == "post")
    overlap_comments = sum(1 for key in classification.base_records if key[0] == "comment")
    terminal = {name: terminal_counts[name] for name in TERMINAL_OUTCOMES}
    if sum(terminal.values()) != len(source_rows):
        raise ImportValidationError("terminal row outcomes do not conserve source rows")
    return {
        "base_overlap_comments": overlap_comments,
        "base_overlap_posts": overlap_posts,
        "distinct_comments": distinct_comments,
        "distinct_posts": distinct_posts,
        "duplicate_rows": terminal["duplicate"],
        "net_new_comments": distinct_comments - overlap_comments,
        "net_new_posts": distinct_posts - overlap_posts,
        "source_rows": len(source_rows),
        "terminal_outcomes": terminal,
    }


def _open_private_receipt_parent(
    path: Path,
    project_root: Path,
) -> tuple[Path, list[int]]:
    target = _private_location(path, project_root, "receipt_path")
    root = Path(os.path.abspath(os.fspath(project_root)))
    relative_parent = target.parent.relative_to(root)
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    opened: list[int] = []
    try:
        descriptor = os.open(os.fspath(root), directory_flags)
        opened.append(descriptor)
        root_metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(root_metadata.st_mode):
            raise ImportValidationError("project_root must be a regular directory")
        for index, part in enumerate(relative_parent.parts):
            if part in {"", ".", ".."} or "/" in part or "\\" in part:
                raise ImportValidationError("receipt parent path is unsafe")
            private_component = index >= 1
            create_mode = 0o700 if private_component else 0o755
            try:
                child = os.open(part, directory_flags, dir_fd=descriptor)
            except FileNotFoundError:
                os.mkdir(part, create_mode, dir_fd=descriptor)
                child = os.open(part, directory_flags, dir_fd=descriptor)
            opened.append(child)
            descriptor = child
            metadata = os.fstat(descriptor)
            if not stat.S_ISDIR(metadata.st_mode):
                raise ImportValidationError("receipt parent must be a regular directory")
            if private_component and stat.S_IMODE(metadata.st_mode) & 0o077:
                raise ImportValidationError("receipt parent must be private")
        return target, opened
    except ImportValidationError:
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
        raise ImportValidationError("receipt parent unavailable or unsafe") from exc


def _receipt_outside_bundle(
    receipt_path: Path,
    bundle_root: Path,
    project_root: Path,
) -> None:
    receipt = _private_location(receipt_path, project_root, "receipt_path")
    bundle = _private_location(bundle_root, project_root, "bundle_root")
    if receipt == bundle or bundle in receipt.parents:
        raise ImportValidationError("receipt_path must stay outside input bundle")


def _identity_at(directory_fd: int, name: str) -> tuple[int, int] | None:
    try:
        metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    return metadata.st_dev, metadata.st_ino


def _require_owned_at(
    directory_fd: int,
    name: str,
    owned_identity: tuple[int, int],
) -> None:
    if _identity_at(directory_fd, name) != owned_identity:
        raise ImportValidationError("receipt publish ownership changed")


def _remove_owned_at(
    directory_fd: int,
    name: str,
    owned_identity: tuple[int, int],
) -> bool:
    if _identity_at(directory_fd, name) != owned_identity:
        return False
    os.unlink(name, dir_fd=directory_fd)
    return True


def _write_private_receipt(
    receipt_path: Path,
    value: Mapping[str, object],
    project_root: Path,
) -> None:
    target, opened = _open_private_receipt_parent(
        Path(receipt_path),
        Path(project_root),
    )
    parent_fd = opened[-1]
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    stage_name = f".{target.name}.stage-{secrets.token_hex(12)}"
    stage_fd: int | None = None
    stage_exists = False
    published = False
    completed = False
    owned_identity: tuple[int, int] | None = None
    try:
        try:
            stage_fd = os.open(stage_name, flags, 0o600, dir_fd=parent_fd)
            stage_exists = True
        except OSError as exc:
            raise ImportValidationError("receipt staging file unavailable") from exc
        stage_metadata = os.fstat(stage_fd)
        owned_identity = (stage_metadata.st_dev, stage_metadata.st_ino)
        os.fchmod(stage_fd, 0o600)
        payload = _canonical_bytes(dict(value)) + b"\n"
        view = memoryview(payload)
        while view:
            written = os.write(stage_fd, view)
            if written <= 0:
                raise OSError("receipt write made no progress")
            view = view[written:]
        os.fsync(stage_fd)
        os.close(stage_fd)
        stage_fd = None
        try:
            os.link(
                stage_name,
                target.name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileExistsError as exc:
            raise ImportValidationError("receipt already exists") from exc
        except OSError as exc:
            if exc.errno == errno.EEXIST:
                raise ImportValidationError("receipt already exists") from exc
            raise ImportValidationError("receipt atomic publish failed") from exc
        published = True
        os.fsync(parent_fd)
        _require_owned_at(parent_fd, target.name, owned_identity)
        _require_owned_at(parent_fd, stage_name, owned_identity)
        if not _remove_owned_at(parent_fd, stage_name, owned_identity):
            raise ImportValidationError("receipt publish ownership changed")
        stage_exists = False
        os.fsync(parent_fd)
        _require_owned_at(parent_fd, target.name, owned_identity)
        completed = True
    except ImportValidationError:
        raise
    except OSError as exc:
        raise ImportValidationError("receipt atomic publish failed") from exc
    finally:
        if stage_fd is not None:
            try:
                os.close(stage_fd)
            except OSError:
                pass
        if not completed:
            if published and owned_identity is not None:
                try:
                    _remove_owned_at(parent_fd, target.name, owned_identity)
                except OSError:
                    pass
            if stage_exists and owned_identity is not None:
                try:
                    _remove_owned_at(parent_fd, stage_name, owned_identity)
                except OSError:
                    pass
            try:
                os.fsync(parent_fd)
            except OSError:
                pass
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                pass


def validate_workbook_import(
    bundle_root: Path,
    source_manifest_path: Path,
    project_root: Path,
    receipt_path: Path | None = None,
) -> ValidationReceipt:
    root = Path(project_root)
    if receipt_path is not None:
        _receipt_outside_bundle(
            Path(receipt_path),
            Path(bundle_root),
            root,
        )
    source_manifest = load_source_manifest(Path(source_manifest_path), root)
    bundle_manifest, bundle_manifest_payload, documents = _read_bundle(
        Path(bundle_root), root
    )
    source_rows = _read_source_rows(source_manifest, root)
    base = _read_base(source_manifest, root)
    classification = _classify(source_rows, base)

    terminal_counts = _validate_row_outcomes(
        documents["row-outcomes.jsonl"], source_rows, classification
    )
    occurrence_keys = _validate_entities(
        documents["posts.jsonl"],
        documents["comments.jsonl"],
        classification,
        source_manifest,
    )
    _validate_parent_links(documents["parent-link-ledger.jsonl"], classification)
    _validate_conflicts(documents["conflict-ledger.jsonl"], classification)
    expected_occurrence_keys = {row.occurrence_key for row in source_rows}
    unaccounted_source_rows = len(expected_occurrence_keys - occurrence_keys)
    if occurrence_keys != expected_occurrence_keys:
        raise ImportValidationError("source occurrence coverage mismatch")
    expected_identity_count = len(classification.groups)
    physical_identity_count = len(documents["posts.jsonl"]) + len(documents["comments.jsonl"])
    unaccounted_import_identities = expected_identity_count - physical_identity_count
    if unaccounted_import_identities != 0:
        raise ImportValidationError("import identity conservation mismatch")
    counts = _computed_counts(source_rows, classification, terminal_counts)
    _validate_bundle_manifest(bundle_manifest, source_manifest, base, counts)

    receipt = ValidationReceipt(
        schema_version=RECEIPT_SCHEMA,
        status="passed",
        bundle_manifest_sha256=_sha(bundle_manifest_payload),
        source_manifest_sha256=source_manifest.manifest_sha256,
        base_public_manifest_sha256=source_manifest.base.public_manifest_sha256,
        base_lineage_manifest_sha256=source_manifest.base.lineage_manifest_sha256,
        counts=counts,
        unaccounted_source_rows=unaccounted_source_rows,
        unaccounted_import_identities=unaccounted_import_identities,
        boundaries=dict(BOUNDARIES),
        consumption_status="blocked_pending_canonical_snapshot",
        promotable=False,
    )
    if receipt_path is not None:
        _write_private_receipt(Path(receipt_path), receipt.as_dict(), root)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Independently validate a private Reddit workbook-import candidate."
    )
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--receipt-path", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = validate_workbook_import(
            args.bundle_root,
            args.source_manifest,
            args.project_root,
            receipt_path=args.receipt_path,
        )
    except Exception as exc:
        print(f"validation failed:{exc}", file=sys.stderr)
        return 1
    print((_canonical_bytes(result.as_dict()) + b"\n").decode("utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
