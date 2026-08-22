from __future__ import annotations

from collections import Counter, defaultdict
import ctypes
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

from reddit_voc.report_contracts import canonical_json_bytes
from reddit_voc.v3_source_manifest import SourceContract, SourceManifest


ENTITY_SCHEMA = "reddit_voc_workbook_entity_v1"
ROW_OUTCOME_SCHEMA = "reddit_voc_workbook_row_outcome_v1"
PARENT_LINK_SCHEMA = "reddit_voc_workbook_parent_link_v1"
CONFLICT_SCHEMA = "reddit_voc_workbook_conflict_v1"
MANIFEST_SCHEMA = "reddit_voc_workbook_import_manifest_v1"
POST_TYPE = "forum post"
COMMENT_TYPE = "forum post reply"
TERMINAL_OUTCOMES = (
    "duplicate",
    "exact_base_overlap",
    "identity_conflict",
    "unresolved_parent",
    "incomplete_text",
    "net_new_text_ready",
)
OUTPUT_FILES = (
    "comments.jsonl",
    "conflict-ledger.jsonl",
    "parent-link-ledger.jsonl",
    "posts.jsonl",
    "row-outcomes.jsonl",
)
STRICT_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
STRICT_MIDNIGHT = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}(?:T| )00:00:00$"
)
REDDIT_ID = re.compile(r"^[a-z0-9]+$")


class WorkbookImportError(ValueError):
    """One source row, Base binding, or private bundle invariant failed."""


@dataclass(frozen=True)
class RedditIdentity:
    post_id: str
    comment_id: str | None


@dataclass(frozen=True)
class NormalizedWorkbookRow:
    source_snapshot_id: str
    source_row_ordinal: int
    source_record_id: str
    source_url: str
    entity_type: str
    identity: RedditIdentity
    source_text: str
    source_summary: str
    source_calendar_date: str
    event_time_precision: str
    source_timezone_status: str
    selection_class: str
    query_profile_status: str
    allowed_metric_families: tuple[str, ...]
    blocked_uses: tuple[str, ...]
    source_file_sha256: str
    source_annotations: Mapping[str, object]

    @property
    def bare_entity_id(self) -> str:
        return self.identity.comment_id or self.identity.post_id

    @property
    def canonical_reddit_id(self) -> str:
        if self.entity_type == "comment":
            return f"t1_{self.identity.comment_id}"
        return f"t3_{self.identity.post_id}"

    @property
    def occurrence_key(self) -> str:
        return f"{self.source_snapshot_id}:{self.source_row_ordinal}"

    def occurrence_dict(self) -> dict[str, object]:
        annotations = dict(self.source_annotations)
        value = {
            "allowed_metric_families": list(self.allowed_metric_families),
            "blocked_uses": list(self.blocked_uses),
            "occurrence_key": self.occurrence_key,
            "post_id": self.identity.post_id,
            "selection_class": self.selection_class,
            "source_calendar_date": self.source_calendar_date,
            "source_file_sha256": self.source_file_sha256,
            "source_record_id": self.source_record_id,
            "source_row_ordinal": self.source_row_ordinal,
            "source_snapshot_id": self.source_snapshot_id,
            "source_summary_sha256": hashlib.sha256(
                self.source_summary.encode("utf-8")
            ).hexdigest(),
            "source_annotations": annotations,
            "source_annotations_sha256": hashlib.sha256(
                canonical_json_bytes(annotations)
            ).hexdigest(),
            "source_text_sha256": hashlib.sha256(
                self.source_text.encode("utf-8")
            ).hexdigest(),
            "source_url": self.source_url,
        }
        return {
            **value,
            "occurrence_sha256": hashlib.sha256(
                canonical_json_bytes(value)
            ).hexdigest(),
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "allowed_metric_families": list(self.allowed_metric_families),
            "blocked_uses": list(self.blocked_uses),
            "canonical_reddit_id": self.canonical_reddit_id,
            "comment_id": self.identity.comment_id,
            "entity_type": self.entity_type,
            "event_time_precision": self.event_time_precision,
            "post_id": self.identity.post_id,
            "query_profile_status": self.query_profile_status,
            "selection_class": self.selection_class,
            "source_annotations": dict(self.source_annotations),
            "source_calendar_date": self.source_calendar_date,
            "source_record_id": self.source_record_id,
            "source_row_ordinal": self.source_row_ordinal,
            "source_snapshot_id": self.source_snapshot_id,
            "source_summary": self.source_summary,
            "source_summary_status": "source_derived_provenance_only",
            "source_text": self.source_text,
            "source_text_role": "reddit_original_text",
            "source_timezone_status": self.source_timezone_status,
            "source_url": self.source_url,
        }


@dataclass(frozen=True)
class WorkbookImportSummary:
    source_rows: int
    distinct_posts: int
    distinct_comments: int
    duplicate_rows: int
    base_overlap_posts: int
    base_overlap_comments: int
    net_new_posts: int
    net_new_comments: int
    terminal_outcomes: dict[str, int]
    manifest_sha256: str
    production_unchanged: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "base_overlap_comments": self.base_overlap_comments,
            "base_overlap_posts": self.base_overlap_posts,
            "distinct_comments": self.distinct_comments,
            "distinct_posts": self.distinct_posts,
            "duplicate_rows": self.duplicate_rows,
            "manifest_sha256": self.manifest_sha256,
            "net_new_comments": self.net_new_comments,
            "net_new_posts": self.net_new_posts,
            "production_unchanged": self.production_unchanged,
            "source_rows": self.source_rows,
            "consumption_status": "blocked_pending_independent_validation",
            "independent_validation_status": "pending",
            "promotable": False,
            "status": "candidate_built",
            "terminal_outcomes": dict(self.terminal_outcomes),
            "validation_receipt_sha256": None,
        }


@dataclass(frozen=True)
class _ImportDocuments:
    posts: tuple[dict[str, object], ...]
    comments: tuple[dict[str, object], ...]
    row_outcomes: tuple[dict[str, object], ...]
    parent_links: tuple[dict[str, object], ...]
    conflicts: tuple[dict[str, object], ...]
    counts: dict[str, int]
    terminal_outcomes: dict[str, int]


@dataclass(frozen=True)
class _BaseDocuments:
    posts: tuple[dict[str, Any], ...]
    comments: tuple[dict[str, Any], ...]
    quarantine: tuple[dict[str, Any], ...]
    unresolved: tuple[dict[str, Any], ...]
    base_conflicts: tuple[dict[str, object], ...]
    held_post_ids: frozenset[str]
    public_file_bindings: dict[str, dict[str, object]]
    lineage_file_bindings: dict[str, dict[str, object]]


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
        raise WorkbookImportError("source annotation contains a non-finite number")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _bare_id(value: object, prefix: str) -> str:
    result = str(value or "").strip().casefold()
    if result.startswith(prefix):
        result = result[len(prefix) :]
    if REDDIT_ID.fullmatch(result) is None:
        raise WorkbookImportError(f"invalid Reddit identity:{value}")
    return result


def parse_reddit_identity(url: str, entity_type: str) -> RedditIdentity:
    kind = str(entity_type).strip().casefold()
    if kind not in {"post", "comment"}:
        raise WorkbookImportError("unsupported entity_type")
    parsed = urlsplit(str(url).strip())
    hostname = (parsed.hostname or "").casefold()
    try:
        port = parsed.port
    except ValueError as exc:
        raise WorkbookImportError("Reddit URL host or scheme invalid") from exc
    if (
        parsed.scheme.casefold() != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or not (
        hostname == "reddit.com" or hostname.endswith(".reddit.com")
        )
    ):
        raise WorkbookImportError("Reddit URL host or scheme invalid")
    if "\\" in parsed.path:
        raise WorkbookImportError("Reddit path grammar invalid")
    parts: list[str] = []
    for raw_part in parsed.path.split("/"):
        if not raw_part:
            continue
        decoded = unquote(raw_part)
        if "/" in decoded or "\\" in decoded or decoded in {".", ".."}:
            raise WorkbookImportError("Reddit path grammar invalid")
        parts.append(decoded.casefold())
    if len(parts) >= 3 and parts[0] == "r" and parts[2] == "comments":
        marker = 2
    elif parts and parts[0] == "comments":
        marker = 0
    else:
        raise WorkbookImportError("Reddit comments path missing")
    if marker + 1 >= len(parts):
        raise WorkbookImportError("post identity missing")
    post_id = parts[marker + 1]
    if REDDIT_ID.fullmatch(post_id) is None:
        raise WorkbookImportError("invalid Reddit identity in URL")
    tail = parts[marker + 2 :]
    if kind == "post":
        if len(tail) > 1:
            raise WorkbookImportError("post path contains comment identity")
        return RedditIdentity(post_id=post_id, comment_id=None)

    if len(tail) != 2:
        raise WorkbookImportError("comment identity missing")
    if tail[0] == "comment":
        candidate = tail[1]
    else:
        candidate = tail[-1]
    if REDDIT_ID.fullmatch(candidate) is None:
        raise WorkbookImportError("invalid Reddit identity in URL")
    return RedditIdentity(
        post_id=post_id,
        comment_id=candidate,
    )


def _floating_calendar_date(value: object) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None and value.time().isoformat() == "00:00:00":
            return value.date().isoformat()
    elif isinstance(value, date):
        return value.isoformat()
    elif isinstance(value, str):
        text = value.strip()
        if STRICT_DATE.fullmatch(text):
            try:
                return date.fromisoformat(text).isoformat()
            except ValueError:
                pass
        elif STRICT_MIDNIGHT.fullmatch(text):
            try:
                return datetime.fromisoformat(text).date().isoformat()
            except ValueError:
                pass
    raise WorkbookImportError("floating calendar date invalid")


def normalize_workbook_row(
    row: Mapping[str, object],
    *,
    source: SourceContract,
    row_ordinal: int,
) -> NormalizedWorkbookRow:
    if isinstance(row_ordinal, bool) or not isinstance(row_ordinal, int) or row_ordinal < 2:
        raise WorkbookImportError("source row ordinal invalid")
    raw_type = str(row.get("内容类型") or "").strip().casefold()
    if raw_type == POST_TYPE:
        entity_type = "post"
    elif raw_type == COMMENT_TYPE:
        entity_type = "comment"
    else:
        raise WorkbookImportError("workbook entity type invalid")
    source_record_id = str(row.get("舆情ID") or "").strip()
    if not source_record_id:
        raise WorkbookImportError("source record id missing")
    source_url = str(row.get("舆情链接") or "").strip()
    identity = parse_reddit_identity(source_url, entity_type)
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
    return NormalizedWorkbookRow(
        source_snapshot_id=source.source_snapshot_id,
        source_row_ordinal=row_ordinal,
        source_record_id=source_record_id,
        source_url=source_url,
        entity_type=entity_type,
        identity=identity,
        source_text=_text(row.get("标题")),
        source_summary=_text(row.get("内容概要")),
        source_calendar_date=_floating_calendar_date(row.get("发布时间")),
        event_time_precision="day",
        source_timezone_status="unknown",
        selection_class=source.selection_class,
        query_profile_status=source.query_profile_status,
        allowed_metric_families=source.allowed_metric_families,
        blocked_uses=source.blocked_uses,
        source_file_sha256=source.sha256,
        source_annotations=annotations,
    )


def _hash_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _reject_json_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise WorkbookImportError(f"duplicate JSON key:{key}")
        value[key] = item
    return value


def _reject_json_constant(value: str) -> object:
    raise WorkbookImportError(f"non-finite JSON number:{value}")


def _parse_json_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise WorkbookImportError(f"non-finite JSON number:{value}")
    return result


def _decode_json(payload: bytes, label: str) -> object:
    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_json_pairs,
            parse_constant=_reject_json_constant,
            parse_float=_parse_json_float,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkbookImportError(f"{label} invalid JSON") from exc


def _json_object(payload: bytes, label: str) -> dict[str, Any]:
    value = _decode_json(payload, label)
    if not isinstance(value, dict):
        raise WorkbookImportError(f"{label} must be an object")
    return value


def _json_list(payload: bytes, label: str) -> list[dict[str, Any]]:
    value = _decode_json(payload, label)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise WorkbookImportError(f"{label} must be a list of objects")
    return value


def _jsonl_rows(payload: bytes, label: str) -> list[dict[str, Any]]:
    if payload and not payload.endswith(b"\n"):
        raise WorkbookImportError(f"{label} must end with newline")
    rows: list[dict[str, Any]] = []
    for ordinal, line in enumerate(payload.splitlines(), start=1):
        if not line:
            raise WorkbookImportError(f"{label} contains blank line:{ordinal}")
        value = _decode_json(line, f"{label}:{ordinal}")
        if not isinstance(value, dict):
            raise WorkbookImportError(f"{label}:{ordinal} must be an object")
        rows.append(value)
    return rows


def _relative_parts(relative: PurePosixPath, label: str) -> tuple[str, ...]:
    if relative.is_absolute() or not relative.parts or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise WorkbookImportError(f"unsafe relative path:{label}")
    return relative.parts


def _read_relative_file(
    project_root: Path,
    relative: PurePosixPath,
    label: str,
) -> bytes:
    parts = _relative_parts(relative, label)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory_flags = flags | getattr(os, "O_DIRECTORY", 0)
    opened: list[int] = []
    try:
        root_metadata = Path(project_root).lstat()
        if stat.S_ISLNK(root_metadata.st_mode) or not stat.S_ISDIR(root_metadata.st_mode):
            raise WorkbookImportError("project root must be a regular directory")
        directory_fd = os.open(os.fspath(project_root), directory_flags)
        opened.append(directory_fd)
        for part in parts[:-1]:
            directory_fd = os.open(part, directory_flags, dir_fd=directory_fd)
            opened.append(directory_fd)
        file_fd = os.open(parts[-1], flags, dir_fd=directory_fd)
        opened.append(file_fd)
        metadata = os.fstat(file_fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise WorkbookImportError(f"{label} must be a regular file")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(file_fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    except OSError as exc:
        raise WorkbookImportError(f"{label} unavailable") from exc
    finally:
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _bound_base_member(
    *,
    project_root: Path,
    root_relative: PurePosixPath,
    inventory: Mapping[str, object],
    name: str,
    label: str,
) -> tuple[list[dict[str, Any]], dict[str, object]]:
    binding = inventory.get(name)
    if not isinstance(binding, dict):
        raise WorkbookImportError(f"Base file binding missing:{name}")
    payload = _read_relative_file(
        project_root,
        root_relative / name,
        f"{label}:{name}",
    )
    actual_sha = _hash_bytes(payload)
    if binding.get("bytes") != len(payload) or binding.get("sha256") != actual_sha:
        raise WorkbookImportError(f"Base file binding mismatch:{name}")
    return _json_list(payload, f"{label}:{name}"), {
        "bytes": len(payload),
        "sha256": actual_sha,
    }


def _bound_base_jsonl_member(
    *,
    project_root: Path,
    root_relative: PurePosixPath,
    inventory: Mapping[str, object],
    name: str,
    label: str,
) -> tuple[list[dict[str, Any]], dict[str, object]]:
    binding = inventory.get(name)
    if not isinstance(binding, dict):
        raise WorkbookImportError(f"Base file binding missing:{name}")
    payload = _read_relative_file(
        project_root,
        root_relative / name,
        f"{label}:{name}",
    )
    actual_sha = _hash_bytes(payload)
    if binding.get("bytes") != len(payload) or binding.get("sha256") != actual_sha:
        raise WorkbookImportError(f"Base file binding mismatch:{name}")
    return _jsonl_rows(payload, f"{label}:{name}"), {
        "bytes": len(payload),
        "sha256": actual_sha,
    }


def _canonical_counts(value: Mapping[str, Any], label: str) -> dict[str, int]:
    counts = value.get("canonical_counts")
    if not isinstance(counts, dict):
        raise WorkbookImportError(f"{label} canonical counts missing")
    required = ("posts", "linked_comments", "quarantined_comments", "stored_comments")
    result: dict[str, int] = {}
    for name in required:
        item = counts.get(name)
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise WorkbookImportError(f"{label} canonical count invalid:{name}")
        result[name] = item
    if result["stored_comments"] != (
        result["linked_comments"] + result["quarantined_comments"]
    ):
        raise WorkbookImportError(f"{label} canonical comment counts do not conserve")
    return result


def _load_base(
    manifest: SourceManifest,
    project_root: Path,
) -> _BaseDocuments:
    public_manifest_payload = _read_relative_file(
        project_root,
        manifest.base.manifest_relative_path,
        "Base public manifest",
    )
    if _hash_bytes(public_manifest_payload) != manifest.base.public_manifest_sha256:
        raise WorkbookImportError("Base public manifest sha256 mismatch")
    lineage_manifest_payload = _read_relative_file(
        project_root,
        manifest.base.lineage_manifest_relative_path,
        "Base lineage manifest",
    )
    if _hash_bytes(lineage_manifest_payload) != manifest.base.lineage_manifest_sha256:
        raise WorkbookImportError("Base lineage manifest sha256 mismatch")

    public_manifest = _json_object(public_manifest_payload, "Base public manifest")
    lineage_manifest = _json_object(lineage_manifest_payload, "Base lineage manifest")
    for label, value in (
        ("Base public manifest", public_manifest),
        ("Base lineage manifest", lineage_manifest),
    ):
        if value.get("dataset_version") != manifest.base.dataset_version:
            raise WorkbookImportError(f"{label} dataset_version mismatch")
        if not isinstance(value.get("files"), dict):
            raise WorkbookImportError(f"{label} file inventory missing")
    supported_schemas = {
        "reddit_voc_site_snapshot_manifest_v1",
        "reddit_voc_site_snapshot_manifest_v2",
    }
    if public_manifest.get("schema_version") not in supported_schemas:
        raise WorkbookImportError("Base public manifest schema unsupported")
    if lineage_manifest.get("schema_version") not in supported_schemas:
        raise WorkbookImportError("Base lineage manifest schema unsupported")
    public_projection = public_manifest.get("projection")
    if not isinstance(public_projection, dict) or public_projection.get("audience") != "public_ui":
        raise WorkbookImportError("Base public manifest role mismatch")
    if not isinstance(lineage_manifest.get("source_boundaries"), dict):
        raise WorkbookImportError("Base lineage manifest role mismatch")

    public_root = manifest.base.manifest_relative_path.parent
    lineage_root = manifest.base.lineage_manifest_relative_path.parent
    public_posts, public_posts_binding = _bound_base_member(
        project_root=project_root,
        root_relative=public_root,
        inventory=public_manifest["files"],
        name="posts-public.json",
        label="Base public file",
    )
    public_comments, public_comments_binding = _bound_base_member(
        project_root=project_root,
        root_relative=public_root,
        inventory=public_manifest["files"],
        name="comments-public.json",
        label="Base public file",
    )
    private_posts, private_posts_binding = _bound_base_member(
        project_root=project_root,
        root_relative=lineage_root,
        inventory=lineage_manifest["files"],
        name="posts.json",
        label="Base lineage file",
    )
    private_comments, private_comments_binding = _bound_base_member(
        project_root=project_root,
        root_relative=lineage_root,
        inventory=lineage_manifest["files"],
        name="comments.json",
        label="Base lineage file",
    )
    quarantine, quarantine_binding = _bound_base_member(
        project_root=project_root,
        root_relative=lineage_root,
        inventory=lineage_manifest["files"],
        name="quarantine.json",
        label="Base lineage file",
    )
    unresolved: list[dict[str, Any]] = []
    unresolved_binding: dict[str, object] | None = None
    if "unresolved-parent-ledger.jsonl" in lineage_manifest["files"]:
        unresolved, unresolved_binding = _bound_base_jsonl_member(
            project_root=project_root,
            root_relative=lineage_root,
            inventory=lineage_manifest["files"],
            name="unresolved-parent-ledger.jsonl",
            label="Base lineage file",
        )

    public_conflicts: list[dict[str, object]] = []
    public_held_post_ids: set[str] = set()
    public_post_map, public_comment_map = _base_maps(
        public_posts,
        public_comments,
        base_conflicts=public_conflicts,
        held_post_ids=public_held_post_ids,
    )
    base_conflicts: list[dict[str, object]] = []
    held_post_ids: set[str] = set()
    private_post_map, private_comment_map = _base_maps(
        private_posts,
        private_comments,
        base_conflicts=base_conflicts,
        held_post_ids=held_post_ids,
    )
    if set(public_post_map) != set(private_post_map):
        raise WorkbookImportError("Base public/private post identity drift")
    if set(public_comment_map) != set(private_comment_map):
        raise WorkbookImportError("Base public/private comment identity drift")
    public_conflict_keys = {
        (
            str(item.get("governed_post_id")),
            str(item.get("observed_permalink_post_id")),
        )
        for item in public_conflicts
    }
    private_conflict_keys = {
        (
            str(item.get("governed_post_id")),
            str(item.get("observed_permalink_post_id")),
        )
        for item in base_conflicts
    }
    if public_held_post_ids != held_post_ids or public_conflict_keys != private_conflict_keys:
        raise WorkbookImportError("Base public/private permalink conflict identity drift")
    for comment_id in private_comment_map:
        public_parent = _bare_id(public_comment_map[comment_id].get("post_id"), "t3_")
        private_parent = _bare_id(private_comment_map[comment_id].get("post_id"), "t3_")
        if public_parent != private_parent:
            raise WorkbookImportError("Base public/private comment parent drift")
        public_parent_id = _base_comment_parent_id(
            public_comment_map[comment_id].get("parent_id"),
            public_parent,
        )
        private_parent_id = _base_comment_parent_id(
            private_comment_map[comment_id].get("parent_id"),
            private_parent,
        )
        if public_parent_id != private_parent_id:
            raise WorkbookImportError("Base public/private comment parent_id drift")

    quarantine_ids: set[str] = set()
    for item in quarantine:
        comment_id = _bare_id(item.get("comment_id"), "t1_")
        reddit_id = item.get("reddit_id")
        if reddit_id is not None and _bare_id(reddit_id, "t1_") != comment_id:
            raise WorkbookImportError("Base quarantine redundant identity disagreement")
        missing_post_id = _bare_id(item.get("missing_post_id"), "t3_")
        if missing_post_id in private_post_map:
            raise WorkbookImportError("Base quarantined parent unexpectedly exists")
        if comment_id in quarantine_ids or comment_id in private_comment_map:
            raise WorkbookImportError("Base quarantine identity conflict")
        quarantine_ids.add(comment_id)

    unresolved_ids: set[str] = set()
    for item in unresolved:
        comment_id = _bare_id(item.get("canonical_reddit_id"), "t1_")
        _bare_id(item.get("post_id"), "t3_")
        if item.get("comment_state") != "unresolved_parent":
            raise WorkbookImportError("Base unresolved parent state is invalid")
        if item.get("schema_version") != "reddit_voc_canonical_unresolved_parent_v1":
            raise WorkbookImportError("Base unresolved parent schema is invalid")
        if comment_id in unresolved_ids:
            raise WorkbookImportError("duplicate Base unresolved parent identity")
        unresolved_ids.add(comment_id)

    public_counts = _canonical_counts(public_manifest, "Base public manifest")
    lineage_counts = _canonical_counts(lineage_manifest, "Base lineage manifest")
    if public_counts != lineage_counts:
        raise WorkbookImportError("Base public/private canonical count drift")
    actual_counts = {
        "posts": len(private_post_map),
        "linked_comments": len(private_comment_map),
        "quarantined_comments": len(quarantine_ids),
        "stored_comments": len(private_comment_map) + len(quarantine_ids),
    }
    if lineage_counts != actual_counts:
        raise WorkbookImportError("Base canonical counts mismatch physical members")

    return _BaseDocuments(
        posts=tuple(private_posts),
        comments=tuple(private_comments),
        quarantine=tuple(quarantine),
        unresolved=tuple(unresolved),
        base_conflicts=tuple(base_conflicts),
        held_post_ids=frozenset(held_post_ids),
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


def _load_source_rows(manifest: SourceManifest, project_root: Path) -> list[NormalizedWorkbookRow]:
    rows: list[NormalizedWorkbookRow] = []
    for source in manifest.sources:
        payload = _read_relative_file(
            project_root,
            source.relative_path,
            f"source workbook:{source.source_snapshot_id}",
        )
        if len(payload) != source.bytes or _hash_bytes(payload) != source.sha256:
            raise WorkbookImportError(f"source workbook binding mismatch:{source.source_snapshot_id}")
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="Workbook contains no default style, apply openpyxl's default",
                    category=UserWarning,
                )
                workbook = load_workbook(BytesIO(payload), read_only=False, data_only=True)
        except Exception as exc:
            raise WorkbookImportError(
                f"source workbook unreadable:{source.source_snapshot_id}"
            ) from exc
        try:
            if source.workbook.sheet_name not in workbook.sheetnames:
                raise WorkbookImportError(f"source worksheet missing:{source.source_snapshot_id}")
            sheet = workbook[source.workbook.sheet_name]
            if sheet.calculate_dimension() != source.workbook.expected_dimension:
                raise WorkbookImportError(f"source worksheet dimension mismatch:{source.source_snapshot_id}")
            headers = tuple(sheet.cell(1, column).value for column in range(1, 22))
            if headers != source.workbook.expected_headers:
                raise WorkbookImportError(f"source worksheet headers mismatch:{source.source_snapshot_id}")
            before = len(rows)
            type_counts: Counter[str] = Counter()
            for row_ordinal, values in enumerate(
                sheet.iter_rows(min_row=2, max_col=21, values_only=True),
                start=2,
            ):
                mapped = dict(zip(headers, values, strict=True))
                normalized = normalize_workbook_row(
                    mapped,
                    source=source,
                    row_ordinal=row_ordinal,
                )
                rows.append(normalized)
                type_counts[normalized.entity_type] += 1
            if len(rows) - before != source.workbook.expected_data_rows:
                raise WorkbookImportError(f"source row count mismatch:{source.source_snapshot_id}")
            if type_counts["post"] != source.workbook.expected_post_rows:
                raise WorkbookImportError(f"source post count mismatch:{source.source_snapshot_id}")
            if type_counts["comment"] != source.workbook.expected_comment_rows:
                raise WorkbookImportError(f"source comment count mismatch:{source.source_snapshot_id}")
        finally:
            workbook.close()
    return rows


def _identity_bearing_permalink_post_id(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    raw = value.strip()
    parsed_value = f"https://reddit.com{raw}" if raw.startswith("/") else raw
    parsed = urlsplit(parsed_value)
    hostname = (parsed.hostname or "").casefold()
    if hostname and not (hostname == "reddit.com" or hostname.endswith(".reddit.com")):
        return None
    parts = [unquote(part).casefold() for part in parsed.path.split("/") if part]
    if parts[:1] == ["gallery"] and len(parts) == 2:
        return _bare_id(parts[1], "t3_")
    if "comments" in parts:
        return parse_reddit_identity(parsed_value, "post").post_id
    return None


def _base_comment_parent_id(value: object, post_id: str) -> str | None:
    if value is None:
        return None
    raw = str(value).strip().casefold()
    if raw.startswith("t3_"):
        parent_post_id = _bare_id(raw, "t3_")
        if parent_post_id != post_id:
            raise WorkbookImportError("Base comment root parent disagreement")
        return f"t3_{parent_post_id}"
    if raw.startswith("t1_"):
        return f"t1_{_bare_id(raw, 't1_')}"
    raise WorkbookImportError("Base comment parent_id invalid")


def _base_maps(
    posts: Sequence[Mapping[str, object]],
    comments: Sequence[Mapping[str, object]],
    *,
    base_conflicts: list[dict[str, object]] | None = None,
    held_post_ids: set[str] | None = None,
) -> tuple[dict[str, Mapping[str, object]], dict[str, Mapping[str, object]]]:
    post_map: dict[str, Mapping[str, object]] = {}
    comment_map: dict[str, Mapping[str, object]] = {}
    for item in posts:
        post_id = _bare_id(item.get("post_id"), "t3_")
        reddit_id = item.get("reddit_id")
        if reddit_id is not None and _bare_id(reddit_id, "t3_") != post_id:
            raise WorkbookImportError("Base post redundant identity disagreement")
        permalink = item.get("permalink")
        permalink_post_id = _identity_bearing_permalink_post_id(permalink)
        if permalink_post_id is not None and permalink_post_id != post_id:
            if held_post_ids is not None:
                held_post_ids.add(post_id)
            if base_conflicts is not None:
                base_conflicts.append(
                    {
                        "canonical_reddit_id": f"t3_{post_id}",
                        "conflict_type": "base_permalink_identity_disagreement",
                        "entity_type": "post",
                        "governed_post_id": post_id,
                        "observed_permalink_post_id": permalink_post_id,
                        "resolution": "held_identity_conflict",
                        "schema_version": CONFLICT_SCHEMA,
                    }
                )
        if post_id in post_map:
            raise WorkbookImportError("duplicate Base post identity")
        post_map[post_id] = item
    for item in comments:
        comment_id = _bare_id(item.get("comment_id"), "t1_")
        reddit_id = item.get("reddit_id")
        if reddit_id is not None and _bare_id(reddit_id, "t1_") != comment_id:
            raise WorkbookImportError("Base comment redundant identity disagreement")
        post_id = _bare_id(item.get("post_id"), "t3_")
        if post_id not in post_map:
            raise WorkbookImportError("Base comment parent identity missing")
        _base_comment_parent_id(item.get("parent_id"), post_id)
        if comment_id in comment_map:
            raise WorkbookImportError("duplicate Base comment identity")
        comment_map[comment_id] = item
    return post_map, comment_map


def _row_key(row: NormalizedWorkbookRow) -> tuple[str, str]:
    return row.entity_type, row.bare_entity_id


def _entity_document(
    row: NormalizedWorkbookRow,
    occurrences: Sequence[NormalizedWorkbookRow],
    outcome: str,
    *,
    base_record: Mapping[str, object] | None = None,
    base_state: str | None = None,
    base_identity_held: bool = False,
    base_dataset_version: str = "fixture_base",
    base_lineage_manifest_sha256: str = "",
    base_public_manifest_sha256: str = "",
) -> dict[str, object]:
    value = row.as_dict()
    is_base_overlap = base_record is not None
    if outcome == "identity_conflict" or base_identity_held:
        analysis_status = (
            "governed_base_anchor_held_identity_conflict"
            if is_base_overlap
            else "held_identity_conflict"
        )
    elif outcome == "net_new_text_ready":
        analysis_status = "ready"
    elif outcome == "exact_base_overlap" and base_state == "quarantined_comment":
        analysis_status = "governed_base_quarantine"
    elif outcome == "exact_base_overlap":
        analysis_status = "governed_base_anchor"
    else:
        analysis_status = outcome
    if outcome == "identity_conflict" or base_identity_held:
        metric_eligibility_basis = "held_identity_conflict"
        effective_metric_eligibility_status = "excluded_identity_conflict"
        effective_allowed_metric_families: list[str] | None = []
    elif base_state == "quarantined_comment":
        metric_eligibility_basis = "held_quarantine"
        effective_metric_eligibility_status = "excluded_quarantine"
        effective_allowed_metric_families = []
    elif is_base_overlap:
        metric_eligibility_basis = "governed_base_anchor"
        effective_metric_eligibility_status = "pending_governed_base_fusion"
        effective_allowed_metric_families = None
    else:
        metric_eligibility_basis = "workbook_source_policy"
        effective_metric_eligibility_status = "source_policy_applied"
        effective_allowed_metric_families = list(row.allowed_metric_families)
    value.update(
        {
            "analysis_status": analysis_status,
            "base_overlap": is_base_overlap,
            "effective_allowed_metric_families": effective_allowed_metric_families,
            "effective_metric_eligibility_status": effective_metric_eligibility_status,
            "metric_eligibility_basis": metric_eligibility_basis,
            "schema_version": ENTITY_SCHEMA,
            "source_occurrences": [item.occurrence_dict() for item in occurrences],
            "terminal_outcome": outcome,
            "workbook_metric_eligibility_ignored_for_overlap": (
                is_base_overlap
            ),
        }
    )
    if base_record is not None:
        value["base_anchor"] = {
            "canonical_reddit_id": row.canonical_reddit_id,
            "canonical_state": base_state,
            "dataset_version": base_dataset_version,
            "entity_sha256": _hash_bytes(canonical_json_bytes(base_record)),
            "identity_status": "held_identity_conflict"
            if base_identity_held or outcome == "identity_conflict"
            else "governed",
            "lineage_manifest_sha256": base_lineage_manifest_sha256,
            "public_manifest_sha256": base_public_manifest_sha256,
            "source_occurrence_count": len(base_record.get("source_occurrences", []))
            if isinstance(base_record.get("source_occurrences"), list)
            else None,
        }
    if row.entity_type == "comment":
        value["comment_id"] = f"t1_{row.identity.comment_id}"
    return value


def _classify_rows(
    rows: Sequence[NormalizedWorkbookRow],
    base_posts: Sequence[Mapping[str, object]],
    base_comments: Sequence[Mapping[str, object]],
    base_quarantine: Sequence[Mapping[str, object]] = (),
    *,
    base_unresolved: Sequence[Mapping[str, object]] = (),
    base_conflicts: Sequence[Mapping[str, object]] = (),
    held_base_post_ids: Iterable[str] = (),
    base_dataset_version: str = "fixture_base",
    base_lineage_manifest_sha256: str = "",
    base_public_manifest_sha256: str = "",
) -> _ImportDocuments:
    held_base_posts = set(held_base_post_ids)
    ordered = sorted(
        rows,
        key=lambda item: (
            item.source_snapshot_id,
            item.source_row_ordinal,
            item.source_record_id,
        ),
    )
    base_post_map, base_comment_map = _base_maps(base_posts, base_comments)
    quarantine_map: dict[str, Mapping[str, object]] = {}
    for item in base_quarantine:
        comment_id = _bare_id(item.get("comment_id"), "t1_")
        reddit_id = item.get("reddit_id")
        if reddit_id is not None and _bare_id(reddit_id, "t1_") != comment_id:
            raise WorkbookImportError("Base quarantine redundant identity disagreement")
        _bare_id(item.get("missing_post_id"), "t3_")
        if comment_id in quarantine_map or comment_id in base_comment_map:
            raise WorkbookImportError("Base quarantine identity conflict")
        quarantine_map[comment_id] = item
    unresolved_map: dict[str, Mapping[str, object]] = {}
    for item in base_unresolved:
        comment_id = _bare_id(item.get("canonical_reddit_id"), "t1_")
        _bare_id(item.get("post_id"), "t3_")
        if item.get("comment_state") != "unresolved_parent":
            raise WorkbookImportError("Base unresolved parent state is invalid")
        if item.get("schema_version") != "reddit_voc_canonical_unresolved_parent_v1":
            raise WorkbookImportError("Base unresolved parent schema is invalid")
        if comment_id in unresolved_map:
            raise WorkbookImportError("duplicate Base unresolved parent identity")
        unresolved_map[comment_id] = item

    occurrences: dict[tuple[str, str], list[NormalizedWorkbookRow]] = defaultdict(list)
    for row in ordered:
        occurrences[_row_key(row)].append(row)

    representative: dict[tuple[str, str], NormalizedWorkbookRow] = {
        key: next((item for item in group if _match_text(item.source_text)), group[0])
        for key, group in occurrences.items()
    }
    source_post_map = {
        entity_id: representative[(entity_type, entity_id)]
        for entity_type, entity_id in occurrences
        if entity_type == "post"
    }
    row_outcome: dict[str, str] = {}
    conflicts: list[dict[str, object]] = [dict(item) for item in base_conflicts]
    parent_links: list[dict[str, object]] = []
    entity_outcomes: dict[tuple[str, str], str] = {}
    base_records: dict[tuple[str, str], tuple[Mapping[str, object], str]] = {}
    held_keys: set[tuple[str, str]] = set()
    base_held_keys: set[tuple[str, str]] = set()

    for key, group in sorted(occurrences.items()):
        entity_type, entity_id = key
        row = representative[key]
        if entity_type == "post" and entity_id in base_post_map:
            base_records[key] = (base_post_map[entity_id], "post")
            if entity_id in held_base_posts:
                base_held_keys.add(key)
        elif entity_type == "comment" and entity_id in base_comment_map:
            base_records[key] = (base_comment_map[entity_id], "linked_comment")
            base_parent_id = _bare_id(base_comment_map[entity_id].get("post_id"), "t3_")
            if base_parent_id in held_base_posts:
                base_held_keys.add(key)
        elif entity_type == "comment" and entity_id in quarantine_map:
            base_records[key] = (quarantine_map[entity_id], "quarantined_comment")
        elif entity_type == "comment" and entity_id in unresolved_map:
            base_records[key] = (unresolved_map[entity_id], "unresolved_comment")

        candidate_post_ids = sorted(
            {item.identity.post_id for item in group}
            if entity_type == "comment"
            else set()
        )
        governed_post_id: str | None = None
        if entity_type == "comment" and entity_id in base_comment_map:
            governed_post_id = _bare_id(base_comment_map[entity_id].get("post_id"), "t3_")
        elif entity_type == "comment" and entity_id in quarantine_map:
            governed_post_id = _bare_id(
                quarantine_map[entity_id].get("missing_post_id"),
                "t3_",
            )
        held_parent_conflict = (
            entity_type == "comment"
            and key not in base_records
            and len(candidate_post_ids) == 1
            and candidate_post_ids[0] in held_base_posts
        )
        parent_conflict = entity_type == "comment" and (
            len(candidate_post_ids) != 1
            or (
                governed_post_id is not None
                and candidate_post_ids != [governed_post_id]
            )
        )
        source_text_sha256s = sorted(
            {
                _hash_bytes(_match_text(item.source_text).encode("utf-8"))
                for item in group
                if _match_text(item.source_text)
            }
        )
        source_text_conflict = len(source_text_sha256s) > 1 and key not in base_records
        if parent_conflict or held_parent_conflict or source_text_conflict:
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
            if held_parent_conflict:
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
                        "source_text_sha256s": source_text_sha256s,
                    }
                )

    for key in sorted(
        occurrences,
        key=lambda item: (0 if item[0] == "post" else 1, item[1]),
    ):
        group = occurrences[key]
        row = representative[key]
        entity_type, entity_id = key
        base_record, base_state = base_records.get(key, (None, None))
        if key in held_keys:
            outcome = "identity_conflict"
            for item in group:
                row_outcome[item.occurrence_key] = outcome
        elif base_record is not None:
            outcome = "exact_base_overlap"
            row_outcome[group[0].occurrence_key] = outcome
            for item in group[1:]:
                row_outcome[item.occurrence_key] = "duplicate"
            base = base_record
            if entity_type == "post":
                base_texts = {_match_text(base.get("title")), _match_text(base.get("content"))}
            else:
                base_texts = {_match_text(base.get("body"))}
            base_texts.discard("")
            source_texts = {
                _match_text(item.source_text)
                for item in group
                if _match_text(item.source_text)
            }
            differing_source_texts = source_texts - base_texts
            if differing_source_texts and base_texts:
                conflicts.append(
                    {
                        "base_entity_sha256": _hash_bytes(canonical_json_bytes(base)),
                        "base_text_sha256s": sorted(
                            _hash_bytes(item.encode("utf-8")) for item in base_texts
                        ),
                        "canonical_reddit_id": row.canonical_reddit_id,
                        "conflict_type": "source_text_differs_from_governed_base",
                        "entity_type": entity_type,
                        "resolution": "governed_base_wins",
                        "schema_version": CONFLICT_SCHEMA,
                        "source_occurrences": [item.occurrence_dict() for item in group],
                        "source_text_sha256s": sorted(
                            _hash_bytes(item.encode("utf-8"))
                            for item in differing_source_texts
                        ),
                    }
                )
            elif source_texts and not base_texts:
                conflicts.append(
                    {
                        "base_entity_sha256": _hash_bytes(canonical_json_bytes(base)),
                        "base_text_sha256s": [],
                        "canonical_reddit_id": row.canonical_reddit_id,
                        "conflict_type": "governed_base_text_missing_source_fill_candidate",
                        "entity_type": entity_type,
                        "resolution": "defer_to_canonical_fusion",
                        "schema_version": CONFLICT_SCHEMA,
                        "source_occurrences": [item.occurrence_dict() for item in group],
                        "source_text_sha256s": sorted(
                            _hash_bytes(item.encode("utf-8")) for item in source_texts
                        ),
                    }
                )
        elif entity_type == "comment":
            post_id = row.identity.post_id
            if post_id in base_post_map:
                parent_status = "linked_base_post"
                parent = base_post_map[post_id]
                parent_text = _match_text(parent.get("title")) or _match_text(parent.get("content"))
            elif post_id in source_post_map:
                parent_status = "linked_workbook_post"
                parent_text = _match_text(source_post_map[post_id].source_text)
            else:
                parent_status = "unresolved_parent"
                parent_text = ""
            if parent_status == "unresolved_parent":
                outcome = "unresolved_parent"
            elif not _match_text(row.source_text) or not parent_text:
                outcome = "incomplete_text"
            else:
                outcome = "net_new_text_ready"
            row_outcome[group[0].occurrence_key] = outcome
            for item in group[1:]:
                row_outcome[item.occurrence_key] = "duplicate"
        elif not _match_text(row.source_text):
            outcome = "incomplete_text"
            row_outcome[group[0].occurrence_key] = outcome
            for item in group[1:]:
                row_outcome[item.occurrence_key] = "duplicate"
        else:
            outcome = "net_new_text_ready"
            row_outcome[group[0].occurrence_key] = outcome
            for item in group[1:]:
                row_outcome[item.occurrence_key] = "duplicate"
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
                    _bare_id(base_record.get("post_id"), "t3_")
                    if base_state == "linked_comment" and base_record is not None
                    else row.identity.post_id
                )
            elif base_state == "linked_comment" and base_record is not None:
                parent_id = _bare_id(base_record.get("post_id"), "t3_")
                base_parent = base_post_map[parent_id]
                parent_text = _match_text(base_parent.get("title")) or _match_text(
                    base_parent.get("content")
                )
                parent_status = "linked_governed_base_comment"
            elif base_state == "quarantined_comment":
                parent_id = None
                parent_text = ""
                parent_status = "quarantined_governed_base_comment"
            else:
                parent_id = row.identity.post_id
                if parent_id in base_post_map:
                    base_parent = base_post_map[parent_id]
                    parent_text = _match_text(base_parent.get("title")) or _match_text(
                        base_parent.get("content")
                    )
                    parent_status = "linked_base_post"
                elif parent_id in source_post_map and ("post", parent_id) not in held_keys:
                    parent_text = _match_text(source_post_map[parent_id].source_text)
                    parent_status = "linked_workbook_post"
                else:
                    parent_text = ""
                    parent_status = "unresolved_parent"
            parent_links.append(
                {
                    "candidate_post_ids": sorted(
                        {item.identity.post_id for item in group}
                    ),
                    "comment_id": f"t1_{row.identity.comment_id}",
                    "context_available": bool(parent_text),
                    "parent_link_status": parent_status,
                    "post_id": parent_id,
                    "schema_version": PARENT_LINK_SCHEMA,
                    "terminal_outcome": outcome,
                }
            )

    outcome_rows = tuple(
        {
            "canonical_reddit_id": row.canonical_reddit_id,
            "entity_type": row.entity_type,
            "occurrence_key": row.occurrence_key,
            "post_id": row.identity.post_id,
            "schema_version": ROW_OUTCOME_SCHEMA,
            "source_record_id": row.source_record_id,
            "source_row_ordinal": row.source_row_ordinal,
            "source_snapshot_id": row.source_snapshot_id,
            "terminal_outcome": row_outcome[row.occurrence_key],
        }
        for row in ordered
    )
    terminal_counts = Counter(str(item["terminal_outcome"]) for item in outcome_rows)
    terminal = {name: terminal_counts[name] for name in TERMINAL_OUTCOMES}
    if sum(terminal.values()) != len(ordered):
        raise WorkbookImportError("terminal row outcomes are not conserved")

    posts_out: list[dict[str, object]] = []
    comments_out: list[dict[str, object]] = []
    for key, row in sorted(representative.items()):
        base_record, base_state = base_records.get(key, (None, None))
        document = _entity_document(
            row,
            occurrences[key],
            entity_outcomes[key],
            base_record=base_record,
            base_state=base_state,
            base_identity_held=key in base_held_keys,
            base_dataset_version=base_dataset_version,
            base_lineage_manifest_sha256=base_lineage_manifest_sha256,
            base_public_manifest_sha256=base_public_manifest_sha256,
        )
        (posts_out if row.entity_type == "post" else comments_out).append(document)

    overlap_posts = sum(1 for key in base_records if key[0] == "post")
    overlap_comments = sum(1 for key in base_records if key[0] == "comment")
    counts = {
        "base_overlap_comments": overlap_comments,
        "base_overlap_posts": overlap_posts,
        "distinct_comments": len(comments_out),
        "distinct_posts": len(posts_out),
        "net_new_comments": len(comments_out) - overlap_comments,
        "net_new_posts": len(posts_out) - overlap_posts,
        "source_rows": len(ordered),
    }
    return _ImportDocuments(
        posts=tuple(posts_out),
        comments=tuple(comments_out),
        row_outcomes=outcome_rows,
        parent_links=tuple(sorted(parent_links, key=lambda item: str(item["comment_id"]))),
        conflicts=tuple(
            sorted(
                conflicts,
                key=lambda item: (
                    str(item["entity_type"]),
                    str(item["canonical_reddit_id"]),
                    str(item["conflict_type"]),
                    canonical_json_bytes(item).decode("utf-8"),
                ),
            )
        ),
        counts=counts,
        terminal_outcomes=terminal,
    )


def _jsonl(rows: Iterable[Mapping[str, object]]) -> bytes:
    return b"".join(canonical_json_bytes(row) + b"\n" for row in rows)


def _private_output(path: Path, project_root: Path) -> Path:
    root = Path(os.path.abspath(os.fspath(project_root)))
    try:
        root_metadata = root.lstat()
    except OSError as exc:
        raise WorkbookImportError("project root unavailable") from exc
    if stat.S_ISLNK(root_metadata.st_mode) or not stat.S_ISDIR(root_metadata.st_mode):
        raise WorkbookImportError("project root must be a regular directory")
    private_root = root / "tmp/reddit-voc-v3"
    raw = Path(path)
    output = Path(
        os.path.abspath(os.fspath(raw if raw.is_absolute() else root / raw))
    )
    try:
        relative = output.relative_to(private_root)
    except ValueError as exc:
        raise WorkbookImportError("output must stay below the project private tmp/reddit-voc-v3 root") from exc
    if not relative.parts:
        raise WorkbookImportError("output must stay below the project private tmp/reddit-voc-v3 root")

    current = root
    for part in output.relative_to(root).parts:
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise WorkbookImportError("output path unavailable") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise WorkbookImportError("output path contains a symlink")
        if current != output and not stat.S_ISDIR(metadata.st_mode):
            raise WorkbookImportError("output ancestor must be a regular directory")
    return output


def _open_or_create_directory(
    parent_fd: int,
    name: str,
    *,
    private: bool,
) -> int:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
    except FileNotFoundError:
        os.mkdir(name, 0o700 if private else 0o755, dir_fd=parent_fd)
        descriptor = os.open(name, flags, dir_fd=parent_fd)
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode):
        os.close(descriptor)
        raise WorkbookImportError("output ancestor must be a regular directory")
    if private and stat.S_IMODE(metadata.st_mode) & 0o077:
        os.close(descriptor)
        raise WorkbookImportError("private output ancestor permissions are too broad")
    return descriptor


def _write_bytes_at(directory_fd: int, name: str, payload: bytes) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(name, flags, 0o600, dir_fd=directory_fd)
    try:
        os.fchmod(descriptor, 0o600)
        view = memoryview(payload)
        written = 0
        while written < len(view):
            count = os.write(descriptor, view[written:])
            if count <= 0:
                raise WorkbookImportError(f"short output write:{name}")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _rename_noreplace(
    source_fd: int,
    source_name: str,
    target_fd: int,
    target_name: str,
) -> None:
    """Atomically publish one directory without replacing an existing target."""

    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        function = getattr(libc, "renameatx_np", None)
        no_replace_flag = 0x00000004  # RENAME_EXCL
    elif sys.platform.startswith("linux"):
        function = getattr(libc, "renameat2", None)
        no_replace_flag = 0x00000001  # RENAME_NOREPLACE
    else:
        function = None
        no_replace_flag = 0
    if function is None:
        raise WorkbookImportError("atomic no-replace rename unavailable")

    function.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    function.restype = ctypes.c_int
    ctypes.set_errno(0)
    result = function(
        source_fd,
        os.fsencode(source_name),
        target_fd,
        os.fsencode(target_name),
        no_replace_flag,
    )
    if result == 0:
        return

    error_number = ctypes.get_errno() or errno.EIO
    if error_number in (errno.EEXIST, errno.ENOTEMPTY):
        raise WorkbookImportError("immutable output already exists")
    raise OSError(error_number, os.strerror(error_number))


def _write_bundle(
    output_root: Path,
    payloads: Mapping[str, bytes],
    manifest_payload: bytes,
    *,
    project_root: Path,
) -> None:
    if set(payloads) != set(OUTPUT_FILES):
        raise WorkbookImportError("private bundle payload inventory mismatch")
    output = _private_output(output_root, project_root)
    root = Path(os.path.abspath(os.fspath(project_root)))
    relative_parts = output.relative_to(root / "tmp/reddit-voc-v3").parts
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptors: list[int] = []
    staging_fd: int | None = None
    staging_name: str | None = None
    parent_fd: int | None = None
    staged_names: list[str] = []
    try:
        root_fd = os.open(os.fspath(root), directory_flags)
        descriptors.append(root_fd)
        tmp_fd = _open_or_create_directory(root_fd, "tmp", private=False)
        descriptors.append(tmp_fd)
        private_fd = _open_or_create_directory(tmp_fd, "reddit-voc-v3", private=True)
        descriptors.append(private_fd)
        parent_fd = private_fd
        for part in relative_parts[:-1]:
            parent_fd = _open_or_create_directory(parent_fd, part, private=True)
            descriptors.append(parent_fd)
        output_name = relative_parts[-1]
        legacy_reservation_name = f".{output_name}.build-lock"
        try:
            os.stat(
                legacy_reservation_name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            pass
        else:
            raise WorkbookImportError("candidate build already in progress")
        try:
            os.stat(output_name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise WorkbookImportError("immutable output already exists")

        for _ in range(20):
            candidate = f".{output_name}.{secrets.token_hex(8)}"
            try:
                os.mkdir(candidate, 0o700, dir_fd=parent_fd)
            except FileExistsError:
                continue
            staging_name = candidate
            break
        if staging_name is None:
            raise WorkbookImportError("unable to allocate private staging directory")
        staging_fd = os.open(staging_name, directory_flags, dir_fd=parent_fd)
        os.fchmod(staging_fd, 0o700)
        for name in OUTPUT_FILES:
            staged_names.append(name)
            _write_bytes_at(staging_fd, name, payloads[name])
        staged_names.append("manifest.json")
        _write_bytes_at(staging_fd, "manifest.json", manifest_payload)
        os.fsync(staging_fd)
        try:
            os.stat(output_name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise WorkbookImportError("immutable output already exists")
        _rename_noreplace(
            parent_fd,
            staging_name,
            parent_fd,
            output_name,
        )
        staging_name = output_name
        os.fsync(parent_fd)
        staging_name = None
    except OSError as exc:
        raise WorkbookImportError("private bundle write failed") from exc
    finally:
        if staging_fd is not None:
            if staging_name is not None:
                for name in reversed(staged_names):
                    try:
                        os.unlink(name, dir_fd=staging_fd)
                    except OSError:
                        pass
            try:
                os.close(staging_fd)
            except OSError:
                pass
        if staging_name is not None and descriptors:
            try:
                os.rmdir(staging_name, dir_fd=descriptors[-1])
            except OSError:
                pass
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass


def build_workbook_import(
    manifest: SourceManifest,
    output_root: Path,
    *,
    project_root: Path | None = None,
) -> WorkbookImportSummary:
    root = Path.cwd() if project_root is None else Path(project_root)
    _private_output(Path(output_root), root)
    rows = _load_source_rows(manifest, root)
    base = _load_base(manifest, root)
    documents = _classify_rows(
        rows,
        base.posts,
        base.comments,
        base.quarantine,
        base_unresolved=base.unresolved,
        base_conflicts=base.base_conflicts,
        held_base_post_ids=base.held_post_ids,
        base_dataset_version=manifest.base.dataset_version,
        base_lineage_manifest_sha256=manifest.base.lineage_manifest_sha256,
        base_public_manifest_sha256=manifest.base.public_manifest_sha256,
    )
    payloads = {
        "comments.jsonl": _jsonl(documents.comments),
        "conflict-ledger.jsonl": _jsonl(documents.conflicts),
        "parent-link-ledger.jsonl": _jsonl(documents.parent_links),
        "posts.jsonl": _jsonl(documents.posts),
        "row-outcomes.jsonl": _jsonl(documents.row_outcomes),
    }
    file_rows = {
        "comments.jsonl": len(documents.comments),
        "conflict-ledger.jsonl": len(documents.conflicts),
        "parent-link-ledger.jsonl": len(documents.parent_links),
        "posts.jsonl": len(documents.posts),
        "row-outcomes.jsonl": len(documents.row_outcomes),
    }
    manifest_value = {
        "base": {
            "dataset_version": manifest.base.dataset_version,
            "identity_reconciliation": {
                "linked_comments": len(base.comments),
                "posts": len(base.posts),
                "public_private_identity_sets_equal": True,
                "quarantined_comments": len(base.quarantine),
                "redundant_identity_conflicts": len(base.base_conflicts),
                "held_identity_conflicts": len(base.held_post_ids),
                "stored_comments": len(base.comments) + len(base.quarantine),
                **(
                    {"unresolved_parent_comments": len(base.unresolved)}
                    if "unresolved-parent-ledger.jsonl" in base.lineage_file_bindings
                    else {}
                ),
            },
            "lineage_file_bindings": base.lineage_file_bindings,
            "lineage_manifest_relative_path": (
                manifest.base.lineage_manifest_relative_path.as_posix()
            ),
            "lineage_manifest_sha256": manifest.base.lineage_manifest_sha256,
            "public_file_bindings": base.public_file_bindings,
            "public_manifest_relative_path": manifest.base.manifest_relative_path.as_posix(),
            "public_manifest_sha256": manifest.base.public_manifest_sha256,
        },
        "boundaries": {
            "database_write": False,
            "deploy": False,
            "live_send": False,
            "production_unchanged": True,
            "provider_call": False,
            "remote_write": False,
        },
        "counts": {
            **documents.counts,
            "duplicate_rows": documents.terminal_outcomes["duplicate"],
            "terminal_outcomes": documents.terminal_outcomes,
        },
        "dataset_id": manifest.dataset_id,
        "files": {
            name: {
                "bytes": len(payload),
                "rows": file_rows[name],
                "sha256": _hash_bytes(payload),
            }
            for name, payload in sorted(payloads.items())
        },
        "schema_version": MANIFEST_SCHEMA,
        "consumption_status": "blocked_pending_independent_validation",
        "independent_validation_status": "pending",
        "promotable": False,
        "source_manifest_sha256": manifest.manifest_sha256,
        "source_semantics": {
            "derived_summary_role": "provenance_only",
            "event_time_precision": "day",
            "source_text_column": "标题",
            "source_text_role": "reddit_original_text",
            "source_timezone_status": "unknown",
        },
        "status": "candidate_built",
        "validation_receipt_sha256": None,
    }
    manifest_payload = canonical_json_bytes(manifest_value) + b"\n"
    _write_bundle(
        Path(output_root),
        payloads,
        manifest_payload,
        project_root=root,
    )
    return WorkbookImportSummary(
        source_rows=documents.counts["source_rows"],
        distinct_posts=documents.counts["distinct_posts"],
        distinct_comments=documents.counts["distinct_comments"],
        duplicate_rows=documents.terminal_outcomes["duplicate"],
        base_overlap_posts=documents.counts["base_overlap_posts"],
        base_overlap_comments=documents.counts["base_overlap_comments"],
        net_new_posts=documents.counts["net_new_posts"],
        net_new_comments=documents.counts["net_new_comments"],
        terminal_outcomes=documents.terminal_outcomes,
        manifest_sha256=_hash_bytes(manifest_payload),
        production_unchanged=True,
    )
