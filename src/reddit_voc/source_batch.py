from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any, Iterable, Mapping

from reddit_voc.report_contracts import canonical_json_bytes


SCHEMA_VERSION = "reddit_voc_source_batch_v2"
PRODUCER_TYPES = frozenset({"daily_incremental", "historical_backfill", "comment_refresh"})
TERMINAL_STATUSES = frozenset({"empty", "failed", "partial", "success"})
CONSUMABLE_STATUSES = frozenset({"empty", "partial", "success"})
REQUIRED_MEMBER_ROLES = (
    "checkpoints",
    "comment_occurrences",
    "comments",
    "issues",
    "post_occurrences",
    "posts",
    "raw_index",
)
PRIORITY_REASON_CODES = (
    "admin_exposure",
    "brand_intervention",
    "content_compliance",
    "high_risk",
    "manual_case",
)

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_POST_FULLNAME = re.compile(r"^t3_[A-Za-z0-9]+$")
_COMMENT_FULLNAME = re.compile(r"^t1_[A-Za-z0-9]+$")


class SourceBatchError(ValueError):
    pass


@dataclass(frozen=True)
class BatchWindow:
    metric_start_utc: datetime
    metric_end_utc: datetime
    new_post_discovery_start_utc: datetime
    new_post_discovery_end_utc: datetime
    timezone: str


@dataclass(frozen=True)
class BatchProfiles:
    query_profile_version: str
    query_profile_sha256: str
    coverage_profile_version: str
    coverage_profile_sha256: str


@dataclass(frozen=True)
class ActiveThreadPolicy:
    normal_max_age_days: int
    normal_quiet_days: int
    priority_max_age_days: int
    priority_quiet_days: int
    priority_reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class BatchMember:
    role: str
    relative_path: PurePosixPath
    sha256: str
    bytes: int
    rows: int


@dataclass(frozen=True)
class BatchCounts:
    raw_objects: int
    posts: int
    comments: int
    post_occurrences: int
    comment_occurrences: int
    issues: int
    unresolved_continuations: int


@dataclass(frozen=True)
class BatchBoundaries:
    provider_call: bool
    database_write: bool
    remote_write: bool
    deploy: bool
    live_send: bool
    production_unchanged: bool


@dataclass(frozen=True)
class SourceBatchManifest:
    schema_version: str
    batch_id: str
    producer_type: str
    status: str
    window: BatchWindow
    profiles: BatchProfiles
    active_thread_policy: ActiveThreadPolicy | None
    members: tuple[BatchMember, ...]
    counts: BatchCounts
    boundaries: BatchBoundaries
    manifest_sha256: str

    @property
    def is_consumable(self) -> bool:
        return self.status in CONSUMABLE_STATUSES

    def member(self, role: str) -> BatchMember:
        for item in self.members:
            if item.role == role:
                return item
        raise SourceBatchError(f"unknown member role:{role}")


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SourceBatchError(f"duplicate json key:{key}")
        result[key] = value
    return result


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SourceBatchError(f"{label} must be an object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: Iterable[str], label: str) -> None:
    actual = set(value)
    target = set(expected)
    if actual != target:
        raise SourceBatchError(
            f"{label} keys mismatch:missing={sorted(target - actual)}:extra={sorted(actual - target)}"
        )


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise SourceBatchError(f"{label} must be a non-empty string")
    return value


def _safe_id(value: object, label: str) -> str:
    result = _string(value, label)
    if not _SAFE_ID.fullmatch(result):
        raise SourceBatchError(f"{label} is invalid")
    return result


def _sha256_value(value: object, label: str) -> str:
    result = _string(value, label)
    if not _SHA256.fullmatch(result):
        raise SourceBatchError(f"{label} must be sha256")
    return result


def _nonnegative_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SourceBatchError(f"{label} must be a nonnegative integer")
    return value


def _positive_integer(value: object, label: str) -> int:
    result = _nonnegative_integer(value, label)
    if result == 0:
        raise SourceBatchError(f"{label} must be a positive integer")
    return result


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise SourceBatchError(f"{label} must be boolean")
    return value


def _utc(value: object, label: str) -> datetime:
    text = _string(value, label)
    if not text.endswith("Z"):
        raise SourceBatchError(f"{label} must be UTC with Z suffix")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise SourceBatchError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        raise SourceBatchError(f"{label} must be UTC")
    return parsed


def _relative_path(value: object, label: str) -> PurePosixPath:
    text = _string(value, label)
    path = PurePosixPath(text)
    if path.is_absolute() or text != path.as_posix() or any(part in {"", ".", ".."} for part in path.parts):
        raise SourceBatchError(f"{label} is unsafe")
    return path


def _regular_file(root: Path, relative_path: PurePosixPath, *, label: str) -> Path:
    current = root
    try:
        root_metadata = current.lstat()
    except OSError as exc:
        raise SourceBatchError(f"{label} unavailable") from exc
    if stat.S_ISLNK(root_metadata.st_mode) or not stat.S_ISDIR(root_metadata.st_mode):
        raise SourceBatchError("source batch root is unsafe")
    for part in relative_path.parts:
        current = current / part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise SourceBatchError(f"{label} unavailable") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise SourceBatchError(f"{label} must not be a symlink")
    if not stat.S_ISREG(metadata.st_mode):
        raise SourceBatchError(f"{label} must be a regular file")
    return current


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _jsonl_rows(path: Path, *, label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise SourceBatchError(f"{label} unavailable") from exc
    if payload and not payload.endswith(b"\n"):
        raise SourceBatchError(f"{label} must end with LF")
    lines = payload.splitlines()
    for row_number, line in enumerate(lines, start=1):
        if not line:
            raise SourceBatchError(f"{label} contains an empty row:{row_number}")
        try:
            value = json.loads(line, object_pairs_hook=_reject_duplicate_pairs)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SourceBatchError(f"{label} row is not valid JSON:{row_number}") from exc
        if not isinstance(value, dict):
            raise SourceBatchError(f"{label} row must be an object:{row_number}")
        if line != canonical_json_bytes(value):
            raise SourceBatchError(f"{label} row is not canonical JSON:{row_number}")
        rows.append(value)
    return rows


def _parse_window(value: object, producer_type: str) -> BatchWindow:
    item = _object(value, "window")
    _exact_keys(
        item,
        (
            "metric_start_utc",
            "metric_end_utc",
            "new_post_discovery_start_utc",
            "new_post_discovery_end_utc",
            "timezone",
        ),
        "window",
    )
    result = BatchWindow(
        metric_start_utc=_utc(item["metric_start_utc"], "window.metric_start_utc"),
        metric_end_utc=_utc(item["metric_end_utc"], "window.metric_end_utc"),
        new_post_discovery_start_utc=_utc(
            item["new_post_discovery_start_utc"], "window.new_post_discovery_start_utc"
        ),
        new_post_discovery_end_utc=_utc(
            item["new_post_discovery_end_utc"], "window.new_post_discovery_end_utc"
        ),
        timezone=_string(item["timezone"], "window.timezone"),
    )
    if result.metric_start_utc >= result.metric_end_utc:
        raise SourceBatchError("metric window is invalid")
    if result.new_post_discovery_start_utc > result.metric_start_utc:
        raise SourceBatchError("new-post discovery window must contain metric start")
    if result.new_post_discovery_end_utc != result.metric_end_utc:
        raise SourceBatchError("new-post discovery end must equal metric end")
    if producer_type in {"daily_incremental", "comment_refresh"} and (
        result.metric_end_utc - result.metric_start_utc != timedelta(hours=24)
    ):
        raise SourceBatchError("daily metric window must be exactly 24 hours")
    return result


def _parse_profiles(value: object) -> BatchProfiles:
    item = _object(value, "profiles")
    _exact_keys(
        item,
        (
            "query_profile_version",
            "query_profile_sha256",
            "coverage_profile_version",
            "coverage_profile_sha256",
        ),
        "profiles",
    )
    return BatchProfiles(
        query_profile_version=_safe_id(item["query_profile_version"], "profiles.query_profile_version"),
        query_profile_sha256=_sha256_value(item["query_profile_sha256"], "profiles.query_profile_sha256"),
        coverage_profile_version=_safe_id(
            item["coverage_profile_version"], "profiles.coverage_profile_version"
        ),
        coverage_profile_sha256=_sha256_value(
            item["coverage_profile_sha256"], "profiles.coverage_profile_sha256"
        ),
    )


def _parse_active_thread_policy(value: object, producer_type: str) -> ActiveThreadPolicy | None:
    if value is None:
        if producer_type != "historical_backfill":
            raise SourceBatchError("active_thread_policy is required for daily collection")
        return None
    item = _object(value, "active_thread_policy")
    _exact_keys(
        item,
        (
            "normal_max_age_days",
            "normal_quiet_days",
            "priority_max_age_days",
            "priority_quiet_days",
            "priority_reason_codes",
        ),
        "active_thread_policy",
    )
    reason_codes = item["priority_reason_codes"]
    if not isinstance(reason_codes, list) or tuple(reason_codes) != PRIORITY_REASON_CODES:
        raise SourceBatchError("active_thread_policy.priority_reason_codes mismatch")
    result = ActiveThreadPolicy(
        normal_max_age_days=_positive_integer(
            item["normal_max_age_days"], "active_thread_policy.normal_max_age_days"
        ),
        normal_quiet_days=_positive_integer(
            item["normal_quiet_days"], "active_thread_policy.normal_quiet_days"
        ),
        priority_max_age_days=_positive_integer(
            item["priority_max_age_days"], "active_thread_policy.priority_max_age_days"
        ),
        priority_quiet_days=_positive_integer(
            item["priority_quiet_days"], "active_thread_policy.priority_quiet_days"
        ),
        priority_reason_codes=PRIORITY_REASON_CODES,
    )
    if result.normal_quiet_days > result.normal_max_age_days:
        raise SourceBatchError("normal quiet period exceeds maximum age")
    if result.priority_quiet_days > result.priority_max_age_days:
        raise SourceBatchError("priority quiet period exceeds maximum age")
    if result.priority_max_age_days < result.normal_max_age_days:
        raise SourceBatchError("priority maximum age is shorter than normal maximum age")
    return result


def _parse_members(value: object) -> tuple[BatchMember, ...]:
    if not isinstance(value, list):
        raise SourceBatchError("members must be a list")
    result: list[BatchMember] = []
    for index, raw in enumerate(value):
        item = _object(raw, f"members[{index}]")
        _exact_keys(item, ("role", "relative_path", "sha256", "bytes", "rows"), f"members[{index}]")
        result.append(
            BatchMember(
                role=_safe_id(item["role"], f"members[{index}].role"),
                relative_path=_relative_path(item["relative_path"], f"members[{index}].relative_path"),
                sha256=_sha256_value(item["sha256"], f"members[{index}].sha256"),
                bytes=_nonnegative_integer(item["bytes"], f"members[{index}].bytes"),
                rows=_nonnegative_integer(item["rows"], f"members[{index}].rows"),
            )
        )
    roles = tuple(item.role for item in result)
    if roles != REQUIRED_MEMBER_ROLES:
        raise SourceBatchError(f"member roles mismatch:{roles}")
    paths = tuple(item.relative_path for item in result)
    if len(set(paths)) != len(paths):
        raise SourceBatchError("member paths contain duplicates")
    return tuple(result)


def _parse_counts(value: object) -> BatchCounts:
    item = _object(value, "counts")
    keys = (
        "raw_objects",
        "posts",
        "comments",
        "post_occurrences",
        "comment_occurrences",
        "issues",
        "unresolved_continuations",
    )
    _exact_keys(item, keys, "counts")
    return BatchCounts(**{key: _nonnegative_integer(item[key], f"counts.{key}") for key in keys})


def _parse_boundaries(value: object) -> BatchBoundaries:
    item = _object(value, "boundaries")
    keys = ("provider_call", "database_write", "remote_write", "deploy", "live_send", "production_unchanged")
    _exact_keys(item, keys, "boundaries")
    result = BatchBoundaries(**{key: _boolean(item[key], f"boundaries.{key}") for key in keys})
    if result.database_write or result.remote_write or result.deploy or result.live_send or not result.production_unchanged:
        raise SourceBatchError("source batch boundaries exceed acquisition scope")
    return result


def _validate_members(root: Path, members: tuple[BatchMember, ...], counts: BatchCounts) -> None:
    rows_by_role: dict[str, list[dict[str, Any]]] = {}
    for member in members:
        path = _regular_file(root, member.relative_path, label=f"member:{member.role}")
        if path.stat().st_size != member.bytes or _file_sha256(path) != member.sha256:
            raise SourceBatchError(f"member physical binding mismatch:{member.role}")
        rows = _jsonl_rows(path, label=f"member:{member.role}")
        if len(rows) != member.rows:
            raise SourceBatchError(f"member row count mismatch:{member.role}")
        rows_by_role[member.role] = rows

    expected_rows = {
        "raw_index": counts.raw_objects,
        "posts": counts.posts,
        "comments": counts.comments,
        "post_occurrences": counts.post_occurrences,
        "comment_occurrences": counts.comment_occurrences,
        "issues": counts.issues,
    }
    for role, expected in expected_rows.items():
        if len(rows_by_role[role]) != expected:
            raise SourceBatchError(f"count contract mismatch:{role}")

    raw_ids: set[str] = set()
    raw_paths: set[PurePosixPath] = set()
    for index, row in enumerate(rows_by_role["raw_index"]):
        label = f"raw_index[{index}]"
        _exact_keys(
            row,
            ("raw_object_id", "relative_path", "sha256", "bytes", "terminal_disposition"),
            label,
        )
        raw_id = _safe_id(row["raw_object_id"], f"{label}.raw_object_id")
        relative_path = _relative_path(row["relative_path"], f"{label}.relative_path")
        if not relative_path.parts or relative_path.parts[0] != "raw":
            raise SourceBatchError(f"{label}.relative_path must be under raw/")
        digest = _sha256_value(row["sha256"], f"{label}.sha256")
        byte_count = _nonnegative_integer(row["bytes"], f"{label}.bytes")
        disposition = _string(row["terminal_disposition"], f"{label}.terminal_disposition")
        if disposition not in {"entity_observed", "no_entity", "provider_error", "empty_page"}:
            raise SourceBatchError(f"{label}.terminal_disposition is invalid")
        if raw_id in raw_ids or relative_path in raw_paths:
            raise SourceBatchError("raw index contains duplicate identity or path")
        raw_ids.add(raw_id)
        raw_paths.add(relative_path)
        path = _regular_file(root, relative_path, label=f"raw object:{raw_id}")
        if path.stat().st_size != byte_count or _file_sha256(path) != digest:
            raise SourceBatchError(f"raw object physical binding mismatch:{raw_id}")

    post_ids: set[str] = set()
    for row in rows_by_role["posts"]:
        post_id = row.get("post_id")
        if not isinstance(post_id, str) or _POST_FULLNAME.fullmatch(post_id) is None:
            raise SourceBatchError("posts.post_id must be a t3 fullname")
        if post_id in post_ids:
            raise SourceBatchError(f"posts contains duplicate identity:{post_id}")
        post_ids.add(post_id)

    comment_ids: set[str] = set()
    for row in rows_by_role["comments"]:
        comment_id = row.get("comment_id")
        post_id = row.get("post_id")
        relationship_status = row.get("relationship_status", "linked")
        if not isinstance(comment_id, str) or _COMMENT_FULLNAME.fullmatch(comment_id) is None:
            raise SourceBatchError("comments.comment_id must be a t1 fullname")
        if not isinstance(post_id, str) or _POST_FULLNAME.fullmatch(post_id) is None:
            raise SourceBatchError("comments.post_id must be a t3 fullname")
        if relationship_status not in {"linked", "quarantined", "unresolved_parent"}:
            raise SourceBatchError("comments.relationship_status is invalid")
        if post_id not in post_ids and relationship_status == "linked":
            raise SourceBatchError(f"comment references post absent from batch:{post_id}")
        if comment_id in comment_ids:
            raise SourceBatchError(f"comments contains duplicate identity:{comment_id}")
        comment_ids.add(comment_id)

    occurrence_ids: set[str] = set()
    observed_post_ids: set[str] = set()
    observed_comment_ids: set[str] = set()
    referenced_raw_ids: set[str] = set()
    for row in rows_by_role["post_occurrences"]:
        post_id = row.get("post_id")
        raw_id = row.get("raw_object_id")
        occurrence_id = _safe_id(row.get("occurrence_id"), "post_occurrences.occurrence_id")
        if occurrence_id in occurrence_ids:
            raise SourceBatchError("occurrence_id is not unique")
        occurrence_ids.add(occurrence_id)
        if post_id not in post_ids:
            raise SourceBatchError("post occurrence references unknown post")
        if raw_id not in raw_ids:
            raise SourceBatchError("post occurrence references unknown raw object")
        observed_post_ids.add(str(post_id))
        referenced_raw_ids.add(str(raw_id))

    for row in rows_by_role["comment_occurrences"]:
        comment_id = row.get("comment_id")
        raw_id = row.get("raw_object_id")
        occurrence_id = _safe_id(row.get("occurrence_id"), "comment_occurrences.occurrence_id")
        if occurrence_id in occurrence_ids:
            raise SourceBatchError("occurrence_id is not unique")
        occurrence_ids.add(occurrence_id)
        if comment_id not in comment_ids:
            raise SourceBatchError("comment occurrence references unknown comment")
        if raw_id not in raw_ids:
            raise SourceBatchError("comment occurrence references unknown raw object")
        observed_comment_ids.add(str(comment_id))
        referenced_raw_ids.add(str(raw_id))

    if observed_post_ids != post_ids:
        raise SourceBatchError("post occurrence conservation failed")
    if observed_comment_ids != comment_ids:
        raise SourceBatchError("comment occurrence conservation failed")
    for row in rows_by_role["raw_index"]:
        raw_id = str(row["raw_object_id"])
        disposition = str(row["terminal_disposition"])
        if raw_id in referenced_raw_ids and disposition != "entity_observed":
            raise SourceBatchError("referenced raw disposition mismatch")
        if raw_id not in referenced_raw_ids and disposition == "entity_observed":
            raise SourceBatchError("unreferenced raw lacks terminal disposition")


def load_source_batch(
    manifest_path: Path | str,
    root: Path | str | None = None,
    *,
    require_consumable: bool = False,
) -> SourceBatchManifest:
    manifest_file = Path(manifest_path)
    batch_root = Path(root) if root is not None else manifest_file.parent
    batch_root = Path(os.path.abspath(os.fspath(batch_root)))
    try:
        payload = manifest_file.read_bytes()
    except OSError as exc:
        raise SourceBatchError("source batch manifest unavailable") from exc
    try:
        value = json.loads(payload, object_pairs_hook=_reject_duplicate_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceBatchError("source batch manifest is not valid JSON") from exc
    item = _object(value, "source batch manifest")
    if payload != canonical_json_bytes(item) + b"\n":
        raise SourceBatchError("source batch manifest is not canonical JSON")
    _exact_keys(
        item,
        (
            "schema_version",
            "batch_id",
            "producer_type",
            "status",
            "window",
            "profiles",
            "active_thread_policy",
            "members",
            "counts",
            "boundaries",
        ),
        "source batch manifest",
    )
    if item["schema_version"] != SCHEMA_VERSION:
        raise SourceBatchError("source batch schema_version unsupported")
    producer_type = _string(item["producer_type"], "producer_type")
    if producer_type not in PRODUCER_TYPES:
        raise SourceBatchError("producer_type unsupported")
    status = _string(item["status"], "status")
    if status not in TERMINAL_STATUSES:
        raise SourceBatchError("source batch status is not terminal")
    counts = _parse_counts(item["counts"])
    members = _parse_members(item["members"])
    result = SourceBatchManifest(
        schema_version=SCHEMA_VERSION,
        batch_id=_safe_id(item["batch_id"], "batch_id"),
        producer_type=producer_type,
        status=status,
        window=_parse_window(item["window"], producer_type),
        profiles=_parse_profiles(item["profiles"]),
        active_thread_policy=_parse_active_thread_policy(item["active_thread_policy"], producer_type),
        members=members,
        counts=counts,
        boundaries=_parse_boundaries(item["boundaries"]),
        manifest_sha256=hashlib.sha256(payload).hexdigest(),
    )
    _validate_members(batch_root, members, counts)
    if require_consumable and not result.is_consumable:
        raise SourceBatchError(f"source batch is not consumable:{result.status}")
    return result
