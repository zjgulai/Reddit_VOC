from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
from typing import Any, Iterable, Mapping

from reddit_voc.report_contracts import canonical_json_bytes
from reddit_voc.source_batch import PRIORITY_REASON_CODES, SourceBatchManifest, load_source_batch


SCHEMA_VERSION = "reddit_voc_v2_center_v1"
METRIC_RELEASE_SCHEMA_VERSION = "reddit_voc_v2_metric_release_v2"
CANDIDATE_SCHEMA_VERSION = "reddit_voc_v2_candidate_v2"
BOUNDARIES = {
    "database_write": "local-test-only",
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "production_database_write": False,
    "remote_write": False,
}


class V2CenterError(ValueError):
    pass


@dataclass(frozen=True)
class FusionResult:
    batch_id: str
    manifest_sha256: str
    write_status: str
    new_posts: int
    new_comments: int
    new_occurrences: int


@dataclass(frozen=True)
class ActiveThread:
    post_id: str
    post_created_at_utc: datetime
    last_activity_at_utc: datetime
    priority_reason_codes: tuple[str, ...]
    lifecycle_status: str
    last_refreshed_at_utc: datetime | None = None


@dataclass(frozen=True)
class MetricReleaseResult:
    path: Path
    metric_release_id: str
    sha256: str
    write_status: str


@dataclass(frozen=True)
class CandidateResult:
    path: Path
    candidate_id: str
    sha256: str
    write_status: str
    production_unchanged: bool = True


_SCHEMA = """
CREATE TABLE IF NOT EXISTS center_metadata(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_batches(
    manifest_sha256 TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL UNIQUE,
    producer_type TEXT NOT NULL,
    batch_status TEXT NOT NULL,
    metric_start_utc TEXT NOT NULL,
    metric_end_utc TEXT NOT NULL,
    query_profile_sha256 TEXT NOT NULL,
    coverage_profile_sha256 TEXT NOT NULL,
    counts_json TEXT NOT NULL,
    active_thread_policy_json TEXT,
    validation_receipt_sha256 TEXT
);
CREATE TABLE IF NOT EXISTS canonical_posts(
    post_id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    created_at_utc TEXT,
    first_observed_at_utc TEXT NOT NULL,
    last_observed_at_utc TEXT NOT NULL,
    first_batch_sha256 TEXT NOT NULL,
    last_batch_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS canonical_comments(
    comment_id TEXT PRIMARY KEY,
    post_id TEXT NOT NULL,
    parent_id TEXT,
    payload_json TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    created_at_utc TEXT,
    first_observed_at_utc TEXT NOT NULL,
    last_observed_at_utc TEXT NOT NULL,
    first_batch_sha256 TEXT NOT NULL,
    last_batch_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS entity_occurrences(
    occurrence_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK(entity_type IN ('post','comment')),
    entity_id TEXT NOT NULL,
    raw_object_id TEXT NOT NULL,
    batch_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS content_versions(
    entity_type TEXT NOT NULL CHECK(entity_type IN ('post','comment')),
    entity_id TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    content_json TEXT NOT NULL,
    observed_at_utc TEXT NOT NULL,
    batch_sha256 TEXT NOT NULL,
    PRIMARY KEY(entity_type, entity_id, content_sha256)
);
CREATE TABLE IF NOT EXISTS engagement_snapshots(
    entity_type TEXT NOT NULL CHECK(entity_type IN ('post','comment')),
    entity_id TEXT NOT NULL,
    observed_at_utc TEXT NOT NULL,
    batch_sha256 TEXT NOT NULL,
    engagement_json TEXT NOT NULL,
    engagement_sha256 TEXT NOT NULL,
    PRIMARY KEY(entity_type, entity_id, observed_at_utc, engagement_sha256)
);
CREATE TABLE IF NOT EXISTS relationship_debt(
    comment_id TEXT PRIMARY KEY,
    post_id TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    first_batch_sha256 TEXT NOT NULL,
    last_batch_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS comment_parent_edges(
    comment_id TEXT PRIMARY KEY,
    parent_id TEXT,
    post_id TEXT NOT NULL,
    relationship_status TEXT NOT NULL CHECK(relationship_status IN ('linked','unresolved','quarantined')),
    reason_code TEXT,
    last_batch_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS comment_quarantine(
    comment_id TEXT PRIMARY KEY,
    reason_code TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    first_batch_sha256 TEXT NOT NULL,
    last_batch_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS active_threads(
    post_id TEXT PRIMARY KEY,
    post_created_at_utc TEXT NOT NULL,
    last_activity_at_utc TEXT NOT NULL,
    priority_reason_codes_json TEXT NOT NULL,
    last_batch_sha256 TEXT NOT NULL,
    last_refreshed_at_utc TEXT
);
CREATE TABLE IF NOT EXISTS profile_delta_closures(
    receipt_sha256 TEXT PRIMARY KEY,
    from_query_profile_sha256 TEXT NOT NULL,
    from_coverage_profile_sha256 TEXT NOT NULL,
    to_query_profile_sha256 TEXT NOT NULL,
    to_coverage_profile_sha256 TEXT NOT NULL,
    coverage_start_utc TEXT NOT NULL,
    coverage_end_utc TEXT NOT NULL,
    receipt_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS baseline_bridges(
    receipt_sha256 TEXT PRIMARY KEY,
    source_dataset_id TEXT NOT NULL UNIQUE,
    source_canonical_manifest_sha256 TEXT NOT NULL,
    source_canonical_validation_receipt_sha256 TEXT NOT NULL,
    source_batch_manifest_sha256 TEXT NOT NULL,
    source_batch_validation_receipt_sha256 TEXT NOT NULL,
    counts_json TEXT NOT NULL,
    receipt_json TEXT NOT NULL
);
"""


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_text(value: object) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def _utc(value: object, *, label: str, allow_none: bool = False) -> datetime | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str):
        raise V2CenterError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise V2CenterError(f"{label} is invalid") from exc
    if parsed.tzinfo is None:
        raise V2CenterError(f"{label} is not timezone-aware")
    return parsed.astimezone(timezone.utc)


def _utc_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _coverage_union_complete(
    rows: Iterable[Mapping[str, Any]],
    *,
    start: datetime,
    end: datetime,
) -> bool:
    """Return true only when terminal batch windows cover [start, end) without gaps."""
    intervals: list[tuple[datetime, datetime]] = []
    for row in rows:
        if row["batch_status"] not in {"empty", "success"}:
            return False
        row_start = _utc(row["metric_start_utc"], label="coverage batch start")
        row_end = _utc(row["metric_end_utc"], label="coverage batch end")
        if row_start is None or row_end is None or row_start >= row_end:
            raise V2CenterError("coverage batch window is invalid")
        clipped_start = max(start, row_start)
        clipped_end = min(end, row_end)
        if clipped_start < clipped_end:
            intervals.append((clipped_start, clipped_end))
    if not intervals:
        return False
    cursor = start
    for interval_start, interval_end in sorted(intervals):
        if interval_start > cursor:
            return False
        if interval_end > cursor:
            cursor = interval_end
        if cursor >= end:
            return True
    return False


def _jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_bytes().splitlines():
        value = json.loads(line)
        if not isinstance(value, dict):
            raise V2CenterError("SourceBatch member row is invalid")
        rows.append(value)
    return rows


def _documents(batch: SourceBatchManifest, root: Path) -> dict[str, list[dict[str, Any]]]:
    return {
        role: _jsonl(root / batch.member(role).relative_path)
        for role in (
            "comment_occurrences",
            "comments",
            "post_occurrences",
            "posts",
        )
    }


def _validation_receipt_sha256(
    path: Path, batch: SourceBatchManifest
) -> str:
    try:
        payload = path.read_bytes()
        value = json.loads(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V2CenterError("SourceBatch validation receipt is invalid") from exc
    if (
        not isinstance(value, dict)
        or payload != canonical_json_bytes(value) + b"\n"
        or value.get("schema_version") != "reddit_voc_source_batch_validation_receipt_v1"
        or value.get("status") != "passed"
        or value.get("consumable") is not True
        or value.get("batch_id") != batch.batch_id
        or value.get("manifest_sha256") != batch.manifest_sha256
    ):
        raise V2CenterError("SourceBatch validation receipt binding is invalid")
    return _sha_bytes(payload)


def _content(entity_type: str, row: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
        ("author_hash", "created_at_utc", "selftext", "source_url", "subreddit", "title")
        if entity_type == "post"
        else ("author_hash", "body", "created_at_utc", "deleted_or_removed", "parent_id", "post_id")
    )
    return {field: row.get(field) for field in fields}


def _engagement(entity_type: str, row: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
        ("more_node_count", "num_comments_reported", "parsed_comment_count", "score")
        if entity_type == "post"
        else ("score",)
    )
    return {field: row.get(field) for field in fields}


def _safe_regular_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.is_symlink():
        raise V2CenterError("center database parent is unsafe")
    path.parent.chmod(0o700)


class V2CenterStore:
    def __init__(self, path: Path | str, *, read_only: bool = False) -> None:
        self.path = Path(path)
        self.read_only = read_only
        if type(read_only) is not bool:
            raise V2CenterError("read_only must be boolean")
        if not read_only:
            _safe_regular_parent(self.path)
        if self.path.is_symlink():
            raise V2CenterError("center database is unsafe")
        if read_only:
            if not self.path.exists() or not self.path.is_file():
                raise V2CenterError("center database is unavailable")
            with self.connect() as connection:
                row = connection.execute(
                    "SELECT value FROM center_metadata WHERE key='schema_version'"
                ).fetchone()
                if row is None or row["value"] != SCHEMA_VERSION:
                    raise V2CenterError("center schema version mismatch")
        else:
            self._migrate()

    def connect(self) -> sqlite3.Connection:
        if self.read_only:
            connection = sqlite3.connect(
                self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5.0
            )
            connection.execute("PRAGMA query_only = ON")
        else:
            connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _migrate(self) -> None:
        with self.connect() as connection:
            connection.executescript(_SCHEMA)
            source_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(source_batches)")
            }
            if "active_thread_policy_json" not in source_columns:
                connection.execute("ALTER TABLE source_batches ADD COLUMN active_thread_policy_json TEXT")
            if "validation_receipt_sha256" not in source_columns:
                connection.execute("ALTER TABLE source_batches ADD COLUMN validation_receipt_sha256 TEXT")
            active_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(active_threads)")
            }
            if "last_refreshed_at_utc" not in active_columns:
                connection.execute("ALTER TABLE active_threads ADD COLUMN last_refreshed_at_utc TEXT")
            row = connection.execute(
                "SELECT value FROM center_metadata WHERE key='schema_version'"
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO center_metadata(key,value) VALUES('schema_version',?)",
                    (SCHEMA_VERSION,),
                )
            elif row["value"] != SCHEMA_VERSION:
                raise V2CenterError("center schema version mismatch")
        self.path.chmod(0o600)

    def _lock(self):
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        os.chmod(lock_path, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def count(self, table: str) -> int:
        allowed = {
            "active_threads",
            "baseline_bridges",
            "canonical_comments",
            "canonical_posts",
            "comment_parent_edges",
            "comment_quarantine",
            "content_versions",
            "engagement_snapshots",
            "entity_occurrences",
            "relationship_debt",
            "profile_delta_closures",
            "source_batches",
        }
        if table not in allowed:
            raise V2CenterError("unsupported center table")
        with self.connect() as connection:
            return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def register_v3_baseline_bridge_receipt(self, receipt_path: Path | str) -> str:
        if self.read_only:
            raise V2CenterError("center store is read-only")
        path = Path(receipt_path)
        try:
            payload = path.read_bytes()
            value = json.loads(payload)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise V2CenterError("V3 baseline bridge receipt is invalid") from exc
        required = {
            "bridge_version",
            "counts",
            "schema_version",
            "source_batch_manifest_sha256",
            "source_batch_validation_receipt_sha256",
            "source_canonical_manifest_sha256",
            "source_canonical_validation_receipt_sha256",
            "source_dataset_id",
            "status",
            "upstream_validation_status",
        }
        if (
            not isinstance(value, dict)
            or set(value) != required
            or payload != canonical_json_bytes(value) + b"\n"
            or value.get("schema_version") != "reddit_voc_v3_baseline_bridge_receipt_v1"
            or value.get("bridge_version") != "v3-canonical-to-source-batch-v1"
            or value.get("status") != "passed"
            or value.get("upstream_validation_status") != "passed"
        ):
            raise V2CenterError("V3 baseline bridge receipt is invalid")
        sha_keys = {
            "source_batch_manifest_sha256",
            "source_batch_validation_receipt_sha256",
            "source_canonical_manifest_sha256",
            "source_canonical_validation_receipt_sha256",
        }
        if any(
            not isinstance(value.get(key), str)
            or len(value[key]) != 64
            or any(character not in "0123456789abcdef" for character in value[key])
            for key in sha_keys
        ):
            raise V2CenterError("V3 baseline bridge receipt SHA is invalid")
        dataset_id = value.get("source_dataset_id")
        if not isinstance(dataset_id, str) or not dataset_id:
            raise V2CenterError("V3 baseline source dataset identity is invalid")
        counts = value.get("counts")
        count_keys = {
            "comments_jsonl",
            "linked_comments",
            "posts",
            "quarantined_comments",
            "stored_comments",
            "unresolved_parent_comments",
        }
        if (
            not isinstance(counts, dict)
            or set(counts) != count_keys
            or any(type(counts[key]) is not int or counts[key] < 0 for key in count_keys)
            or counts["comments_jsonl"] + counts["quarantined_comments"]
            != counts["stored_comments"]
            or counts["linked_comments"] + counts["unresolved_parent_comments"]
            != counts["comments_jsonl"]
        ):
            raise V2CenterError("V3 baseline bridge count contract is invalid")
        receipt_sha = _sha_bytes(payload)
        descriptor = self._lock()
        try:
            with self.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                batch = connection.execute(
                    "SELECT counts_json,validation_receipt_sha256 FROM source_batches WHERE manifest_sha256=?",
                    (value["source_batch_manifest_sha256"],),
                ).fetchone()
                if batch is None or batch["validation_receipt_sha256"] != value[
                    "source_batch_validation_receipt_sha256"
                ]:
                    raise V2CenterError("V3 baseline bridge SourceBatch binding mismatch")
                batch_counts = json.loads(batch["counts_json"])
                if (
                    batch_counts.get("posts") != counts["posts"]
                    or batch_counts.get("comments") != counts["stored_comments"]
                ):
                    raise V2CenterError("V3 baseline bridge SourceBatch counts mismatch")
                center_counts = {
                    "comments_jsonl": int(
                        connection.execute("SELECT COUNT(*) FROM canonical_comments").fetchone()[0]
                    )
                    - int(connection.execute("SELECT COUNT(*) FROM comment_quarantine").fetchone()[0]),
                    "linked_comments": int(
                        connection.execute("SELECT COUNT(*) FROM comment_parent_edges").fetchone()[0]
                    )
                    - int(connection.execute("SELECT COUNT(*) FROM relationship_debt").fetchone()[0])
                    - int(connection.execute("SELECT COUNT(*) FROM comment_quarantine").fetchone()[0]),
                    "posts": int(connection.execute("SELECT COUNT(*) FROM canonical_posts").fetchone()[0]),
                    "quarantined_comments": int(
                        connection.execute("SELECT COUNT(*) FROM comment_quarantine").fetchone()[0]
                    ),
                    "stored_comments": int(
                        connection.execute("SELECT COUNT(*) FROM canonical_comments").fetchone()[0]
                    ),
                    "unresolved_parent_comments": int(
                        connection.execute("SELECT COUNT(*) FROM relationship_debt").fetchone()[0]
                    ),
                }
                if center_counts != counts:
                    raise V2CenterError("V3 baseline bridge center conservation mismatch")
                existing = connection.execute(
                    "SELECT receipt_sha256 FROM baseline_bridges WHERE source_dataset_id=?",
                    (dataset_id,),
                ).fetchone()
                if existing is not None:
                    if existing["receipt_sha256"] != receipt_sha:
                        raise V2CenterError("V3 baseline source dataset immutable collision")
                    return "no_change"
                connection.execute(
                    "INSERT INTO baseline_bridges VALUES(?,?,?,?,?,?,?,?)",
                    (
                        receipt_sha,
                        dataset_id,
                        value["source_canonical_manifest_sha256"],
                        value["source_canonical_validation_receipt_sha256"],
                        value["source_batch_manifest_sha256"],
                        value["source_batch_validation_receipt_sha256"],
                        _canonical_text(counts),
                        _canonical_text(value),
                    ),
                )
                return "registered"
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def consume_source_batch(
        self,
        manifest_path: Path | str,
        *,
        validation_receipt_path: Path | str | None = None,
    ) -> FusionResult:
        if self.read_only:
            raise V2CenterError("center store is read-only")
        path = Path(manifest_path)
        root = path.parent
        batch = load_source_batch(path, root, require_consumable=True)
        validation_receipt_sha256 = (
            _validation_receipt_sha256(Path(validation_receipt_path), batch)
            if validation_receipt_path is not None
            else None
        )
        documents = _documents(batch, root)
        descriptor = self._lock()
        try:
            with self.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT batch_id FROM source_batches WHERE manifest_sha256=?",
                    (batch.manifest_sha256,),
                ).fetchone()
                if existing is not None:
                    return FusionResult(
                        batch_id=batch.batch_id,
                        manifest_sha256=batch.manifest_sha256,
                        write_status="no_change",
                        new_posts=0,
                        new_comments=0,
                        new_occurrences=0,
                    )
                batch_collision = connection.execute(
                    "SELECT manifest_sha256 FROM source_batches WHERE batch_id=?",
                    (batch.batch_id,),
                ).fetchone()
                if batch_collision is not None:
                    raise V2CenterError("batch identity immutable collision")
                before_posts = int(connection.execute("SELECT COUNT(*) FROM canonical_posts").fetchone()[0])
                before_comments = int(connection.execute("SELECT COUNT(*) FROM canonical_comments").fetchone()[0])
                before_occurrences = int(connection.execute("SELECT COUNT(*) FROM entity_occurrences").fetchone()[0])
                observed_at = _utc_z(batch.window.metric_end_utc)
                for row in documents["posts"]:
                    self._consume_post(connection, row, batch.manifest_sha256, observed_at)
                for row in documents["comments"]:
                    self._consume_comment(connection, row, batch.manifest_sha256, observed_at)
                self._reconcile_comment_relationships(connection, batch.manifest_sha256)
                self._consume_occurrences(
                    connection,
                    documents["post_occurrences"],
                    entity_type="post",
                    id_field="post_id",
                    batch_sha=batch.manifest_sha256,
                )
                self._consume_occurrences(
                    connection,
                    documents["comment_occurrences"],
                    entity_type="comment",
                    id_field="comment_id",
                    batch_sha=batch.manifest_sha256,
                )
                connection.execute(
                    "INSERT INTO source_batches(manifest_sha256,batch_id,producer_type,batch_status,metric_start_utc,metric_end_utc,query_profile_sha256,coverage_profile_sha256,counts_json,active_thread_policy_json,validation_receipt_sha256) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        batch.manifest_sha256,
                        batch.batch_id,
                        batch.producer_type,
                        batch.status,
                        _utc_z(batch.window.metric_start_utc),
                        _utc_z(batch.window.metric_end_utc),
                        batch.profiles.query_profile_sha256,
                        batch.profiles.coverage_profile_sha256,
                        _canonical_text(batch.counts.__dict__),
                        _canonical_text(batch.active_thread_policy.__dict__)
                        if batch.active_thread_policy is not None
                        else None,
                        validation_receipt_sha256,
                    ),
                )
                after_posts = int(connection.execute("SELECT COUNT(*) FROM canonical_posts").fetchone()[0])
                after_comments = int(connection.execute("SELECT COUNT(*) FROM canonical_comments").fetchone()[0])
                after_occurrences = int(connection.execute("SELECT COUNT(*) FROM entity_occurrences").fetchone()[0])
                return FusionResult(
                    batch_id=batch.batch_id,
                    manifest_sha256=batch.manifest_sha256,
                    write_status="consumed",
                    new_posts=after_posts - before_posts,
                    new_comments=after_comments - before_comments,
                    new_occurrences=after_occurrences - before_occurrences,
                )
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _consume_post(
        self,
        connection: sqlite3.Connection,
        row: Mapping[str, Any],
        batch_sha: str,
        observed_at: str,
    ) -> None:
        post_id = str(row.get("post_id") or "")
        if not post_id.startswith("t3_"):
            raise V2CenterError("post identity is invalid")
        created = row.get("created_at_utc")
        if created is not None:
            created = _utc_z(_utc(created, label="post created_at_utc"))
        existing = connection.execute(
            "SELECT * FROM canonical_posts WHERE post_id=?", (post_id,)
        ).fetchone()
        if existing is not None and created is not None and existing["created_at_utc"] not in {None, created}:
            raise V2CenterError("stable post identity conflict")
        content = _content("post", row)
        content_sha = _sha_bytes(canonical_json_bytes(content))
        payload = _canonical_text(dict(row))
        if existing is None:
            connection.execute(
                "INSERT INTO canonical_posts VALUES(?,?,?,?,?,?,?,?)",
                (post_id, payload, content_sha, created, observed_at, observed_at, batch_sha, batch_sha),
            )
        elif observed_at >= existing["last_observed_at_utc"]:
            connection.execute(
                "UPDATE canonical_posts SET payload_json=?,content_sha256=?,created_at_utc=COALESCE(created_at_utc,?),last_observed_at_utc=?,last_batch_sha256=? WHERE post_id=?",
                (payload, content_sha, created, observed_at, batch_sha, post_id),
            )
        connection.execute(
            "INSERT OR IGNORE INTO content_versions VALUES('post',?,?,?,?,?)",
            (post_id, content_sha, _canonical_text(content), observed_at, batch_sha),
        )
        self._snapshot(connection, "post", post_id, row, observed_at, batch_sha)
        if created is not None:
            active = connection.execute(
                "SELECT * FROM active_threads WHERE post_id=?", (post_id,)
            ).fetchone()
            if active is None:
                connection.execute(
                    "INSERT INTO active_threads(post_id,post_created_at_utc,last_activity_at_utc,priority_reason_codes_json,last_batch_sha256,last_refreshed_at_utc) VALUES(?,?,?,?,?,NULL)",
                    (post_id, created, created, "[]", batch_sha),
                )
            elif created != active["post_created_at_utc"]:
                raise V2CenterError("active thread post identity conflict")

    def _consume_comment(
        self,
        connection: sqlite3.Connection,
        row: Mapping[str, Any],
        batch_sha: str,
        observed_at: str,
    ) -> None:
        comment_id = str(row.get("comment_id") or "")
        post_id = str(row.get("post_id") or "")
        if not comment_id.startswith("t1_") or not post_id.startswith("t3_"):
            raise V2CenterError("comment identity is invalid")
        created = row.get("created_at_utc")
        if created is not None:
            created = _utc_z(_utc(created, label="comment created_at_utc"))
        normalized_row = dict(row)
        parent_id = normalized_row.get("parent_id")
        # Some Reddit providers omit ``parent_id`` for top-level comments even
        # though they still provide an explicit depth and root ``post_id``.
        # Preserve unknown nested parents as debt, but normalize this
        # unambiguous root relationship before hashing and persistence.
        if (
            not parent_id
            and type(normalized_row.get("depth")) is int
            and normalized_row["depth"] == 0
        ):
            parent_id = post_id
            normalized_row["parent_id"] = parent_id
        existing = connection.execute(
            "SELECT * FROM canonical_comments WHERE comment_id=?", (comment_id,)
        ).fetchone()
        if existing is not None and (
            existing["post_id"] != post_id
            or (created is not None and existing["created_at_utc"] not in {None, created})
        ):
            raise V2CenterError("stable comment identity conflict")
        content = _content("comment", normalized_row)
        content_sha = _sha_bytes(canonical_json_bytes(content))
        payload = _canonical_text(normalized_row)
        if existing is None:
            connection.execute(
                "INSERT INTO canonical_comments VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    comment_id,
                    post_id,
                    parent_id,
                    payload,
                    content_sha,
                    created,
                    observed_at,
                    observed_at,
                    batch_sha,
                    batch_sha,
                ),
            )
        elif observed_at >= existing["last_observed_at_utc"]:
            connection.execute(
                "UPDATE canonical_comments SET parent_id=?,payload_json=?,content_sha256=?,created_at_utc=COALESCE(created_at_utc,?),last_observed_at_utc=?,last_batch_sha256=? WHERE comment_id=?",
                (parent_id, payload, content_sha, created, observed_at, batch_sha, comment_id),
            )
        connection.execute(
            "INSERT OR IGNORE INTO content_versions VALUES('comment',?,?,?,?,?)",
            (comment_id, content_sha, _canonical_text(content), observed_at, batch_sha),
        )
        self._snapshot(connection, "comment", comment_id, normalized_row, observed_at, batch_sha)
        if created is not None:
            active = connection.execute(
                "SELECT last_activity_at_utc FROM active_threads WHERE post_id=?", (post_id,)
            ).fetchone()
            if active is not None and created > active["last_activity_at_utc"]:
                connection.execute(
                    "UPDATE active_threads SET last_activity_at_utc=?,last_batch_sha256=? WHERE post_id=?",
                    (created, batch_sha, post_id),
                )

    @staticmethod
    def _reconcile_comment_relationships(
        connection: sqlite3.Connection, batch_sha: str
    ) -> None:
        comments = connection.execute(
            "SELECT comment_id,post_id,parent_id FROM canonical_comments ORDER BY comment_id"
        ).fetchall()
        for row in comments:
            comment_id = str(row["comment_id"])
            post_id = str(row["post_id"])
            parent_id = row["parent_id"]
            status = "linked"
            reason: str | None = None
            if not parent_id:
                status, reason = "unresolved", "parent_id_missing"
            elif str(parent_id).startswith("t3_"):
                parent = connection.execute(
                    "SELECT 1 FROM canonical_posts WHERE post_id=?", (parent_id,)
                ).fetchone()
                if parent is None or parent_id != post_id:
                    status, reason = "unresolved", "parent_post_missing"
            elif str(parent_id).startswith("t1_"):
                parent = connection.execute(
                    "SELECT post_id FROM canonical_comments WHERE comment_id=?", (parent_id,)
                ).fetchone()
                if parent is None:
                    status, reason = "unresolved", "parent_comment_missing"
                elif parent["post_id"] != post_id:
                    status, reason = "quarantined", "parent_comment_post_conflict"
                elif connection.execute(
                    "SELECT 1 FROM canonical_posts WHERE post_id=?", (post_id,)
                ).fetchone() is None:
                    status, reason = "unresolved", "parent_post_missing"
            else:
                status, reason = "quarantined", "parent_identity_invalid"
            connection.execute(
                "INSERT INTO comment_parent_edges VALUES(?,?,?,?,?,?) ON CONFLICT(comment_id) DO UPDATE SET parent_id=excluded.parent_id,post_id=excluded.post_id,relationship_status=excluded.relationship_status,reason_code=excluded.reason_code,last_batch_sha256=excluded.last_batch_sha256",
                (comment_id, parent_id, post_id, status, reason, batch_sha),
            )
            if status == "unresolved":
                connection.execute(
                    "INSERT INTO relationship_debt VALUES(?,?,?,?,?) ON CONFLICT(comment_id) DO UPDATE SET post_id=excluded.post_id,reason_code=excluded.reason_code,last_batch_sha256=excluded.last_batch_sha256",
                    (comment_id, post_id, reason, batch_sha, batch_sha),
                )
                connection.execute("DELETE FROM comment_quarantine WHERE comment_id=?", (comment_id,))
            elif status == "quarantined":
                connection.execute("DELETE FROM relationship_debt WHERE comment_id=?", (comment_id,))
                connection.execute(
                    "INSERT INTO comment_quarantine VALUES(?,?,?,?,?) ON CONFLICT(comment_id) DO UPDATE SET reason_code=excluded.reason_code,evidence_json=excluded.evidence_json,last_batch_sha256=excluded.last_batch_sha256",
                    (
                        comment_id,
                        reason,
                        _canonical_text({"parent_id": parent_id, "post_id": post_id}),
                        batch_sha,
                        batch_sha,
                    ),
                )
            else:
                connection.execute("DELETE FROM relationship_debt WHERE comment_id=?", (comment_id,))
                connection.execute("DELETE FROM comment_quarantine WHERE comment_id=?", (comment_id,))

    @staticmethod
    def _snapshot(
        connection: sqlite3.Connection,
        entity_type: str,
        entity_id: str,
        row: Mapping[str, Any],
        observed_at: str,
        batch_sha: str,
    ) -> None:
        engagement = _engagement(entity_type, row)
        digest = _sha_bytes(canonical_json_bytes(engagement))
        connection.execute(
            "INSERT OR IGNORE INTO engagement_snapshots VALUES(?,?,?,?,?,?)",
            (entity_type, entity_id, observed_at, batch_sha, _canonical_text(engagement), digest),
        )

    @staticmethod
    def _consume_occurrences(
        connection: sqlite3.Connection,
        rows: Iterable[Mapping[str, Any]],
        *,
        entity_type: str,
        id_field: str,
        batch_sha: str,
    ) -> None:
        for row in rows:
            entity_id = str(row.get(id_field) or "")
            raw_id = str(row.get("raw_object_id") or "")
            occurrence_id = str(row.get("occurrence_id") or "") or _sha_bytes(
                canonical_json_bytes([batch_sha, entity_type, entity_id, raw_id])
            )
            existing = connection.execute(
                "SELECT * FROM entity_occurrences WHERE occurrence_id=?",
                (occurrence_id,),
            ).fetchone()
            expected = (entity_type, entity_id, raw_id, batch_sha)
            if existing is not None:
                observed = (
                    existing["entity_type"],
                    existing["entity_id"],
                    existing["raw_object_id"],
                    existing["batch_sha256"],
                )
                if observed != expected:
                    raise V2CenterError("occurrence identity immutable collision")
                continue
            connection.execute(
                "INSERT INTO entity_occurrences VALUES(?,?,?,?,?)",
                (occurrence_id, *expected),
            )

    def set_priority_reasons(self, post_id: str, reason_codes: Iterable[str]) -> None:
        if self.read_only:
            raise V2CenterError("center store is read-only")
        reasons = tuple(sorted(set(reason_codes)))
        if any(reason not in PRIORITY_REASON_CODES for reason in reasons):
            raise V2CenterError("active thread priority reason is invalid")
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE active_threads SET priority_reason_codes_json=? WHERE post_id=?",
                (_canonical_text(list(reasons)), post_id),
            )
            if cursor.rowcount != 1:
                raise V2CenterError("active thread is unknown")

    def register_profile_delta_closure(self, receipt_path: Path | str) -> str:
        if self.read_only:
            raise V2CenterError("center store is read-only")
        path = Path(receipt_path)
        try:
            payload = path.read_bytes()
            value = json.loads(payload)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise V2CenterError("profile delta closure receipt is invalid") from exc
        required = {
            "coverage_end_utc",
            "coverage_start_utc",
            "from_coverage_profile_sha256",
            "from_query_profile_sha256",
            "schema_version",
            "source_batch_evidence",
            "status",
            "to_coverage_profile_sha256",
            "to_query_profile_sha256",
        }
        if (
            not isinstance(value, dict)
            or set(value) != required
            or payload != canonical_json_bytes(value) + b"\n"
            or value.get("schema_version") != "reddit_voc_profile_delta_closure_receipt_v2"
            or value.get("status") != "passed"
        ):
            raise V2CenterError("profile delta closure receipt is invalid")
        for key in required - {
            "coverage_end_utc",
            "coverage_start_utc",
            "schema_version",
            "source_batch_evidence",
            "status",
        }:
            profile_sha = value.get(key)
            if not isinstance(profile_sha, str) or len(profile_sha) != 64:
                raise V2CenterError("profile delta closure SHA is invalid")
        start = _utc(value["coverage_start_utc"], label="delta coverage start")
        end = _utc(value["coverage_end_utc"], label="delta coverage end")
        if start is None or end is None or start >= end:
            raise V2CenterError("profile delta closure window is invalid")
        evidence = value.get("source_batch_evidence")
        if not isinstance(evidence, list) or not evidence:
            raise V2CenterError("profile delta closure evidence is invalid")
        expected_evidence_keys = {
            "manifest_sha256",
            "validation_receipt_sha256",
        }
        evidence_rows: list[sqlite3.Row] = []
        seen_manifests: set[str] = set()
        with self.connect() as connection:
            from_profile_exists = connection.execute(
                "SELECT 1 FROM source_batches WHERE query_profile_sha256=? AND coverage_profile_sha256=? LIMIT 1",
                (
                    value["from_query_profile_sha256"],
                    value["from_coverage_profile_sha256"],
                ),
            ).fetchone()
            if from_profile_exists is None:
                raise V2CenterError("profile delta closure source profile is unknown")
            for item in evidence:
                if not isinstance(item, dict) or set(item) != expected_evidence_keys:
                    raise V2CenterError("profile delta closure evidence is invalid")
                manifest_sha = item.get("manifest_sha256")
                receipt_sha = item.get("validation_receipt_sha256")
                if (
                    not isinstance(manifest_sha, str)
                    or len(manifest_sha) != 64
                    or not isinstance(receipt_sha, str)
                    or len(receipt_sha) != 64
                    or manifest_sha in seen_manifests
                ):
                    raise V2CenterError("profile delta closure evidence is invalid")
                row = connection.execute(
                    "SELECT * FROM source_batches WHERE manifest_sha256=?",
                    (manifest_sha,),
                ).fetchone()
                if (
                    row is None
                    or row["validation_receipt_sha256"] != receipt_sha
                    or row["query_profile_sha256"] != value["to_query_profile_sha256"]
                    or row["coverage_profile_sha256"] != value["to_coverage_profile_sha256"]
                ):
                    raise V2CenterError("profile delta closure evidence binding mismatch")
                seen_manifests.add(manifest_sha)
                evidence_rows.append(row)
            if not _coverage_union_complete(evidence_rows, start=start, end=end):
                raise V2CenterError("profile delta closure evidence does not cover window")
        receipt_sha = _sha_bytes(payload)
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO profile_delta_closures VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(receipt_sha256) DO NOTHING",
                (
                    receipt_sha,
                    value["from_query_profile_sha256"],
                    value["from_coverage_profile_sha256"],
                    value["to_query_profile_sha256"],
                    value["to_coverage_profile_sha256"],
                    _utc_z(start),
                    _utc_z(end),
                    _canonical_text(value),
                ),
            )
        return receipt_sha

    def active_threads(self, as_of_utc: datetime, *, limit: int | None = None) -> tuple[ActiveThread, ...]:
        if as_of_utc.tzinfo is None:
            raise V2CenterError("active thread as_of is not timezone-aware")
        as_of = as_of_utc.astimezone(timezone.utc)
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM active_threads ORDER BY post_id").fetchall()
            policy_row = connection.execute(
                "SELECT active_thread_policy_json FROM source_batches WHERE active_thread_policy_json IS NOT NULL AND metric_start_utc<=? ORDER BY metric_end_utc DESC,manifest_sha256 DESC LIMIT 1",
                (_utc_z(as_of),),
            ).fetchone()
        if policy_row is None:
            return ()
        policy = json.loads(policy_row["active_thread_policy_json"])
        result: list[ActiveThread] = []
        for row in rows:
            created = _utc(row["post_created_at_utc"], label="active post created")
            last_activity = _utc(row["last_activity_at_utc"], label="active last activity")
            if created is None or last_activity is None or created > as_of or last_activity > as_of:
                continue
            reasons = tuple(json.loads(row["priority_reason_codes_json"]))
            max_age = int(
                policy["priority_max_age_days"] if reasons else policy["normal_max_age_days"]
            )
            quiet_days = int(
                policy["priority_quiet_days"] if reasons else policy["normal_quiet_days"]
            )
            age = as_of - created
            quiet = as_of - last_activity
            active = age <= timedelta(days=max_age) or quiet <= timedelta(days=quiet_days)
            if not active:
                continue
            result.append(
                ActiveThread(
                    post_id=row["post_id"],
                    post_created_at_utc=created,
                    last_activity_at_utc=last_activity,
                    priority_reason_codes=reasons,
                    lifecycle_status="active_priority" if reasons else "active_normal",
                    last_refreshed_at_utc=_utc(
                        row["last_refreshed_at_utc"],
                        label="active last refreshed",
                        allow_none=True,
                    ),
                )
            )
        result.sort(
            key=lambda item: (
                0 if item.priority_reason_codes else 1,
                item.last_refreshed_at_utc is not None,
                item.last_refreshed_at_utc or datetime.min.replace(tzinfo=timezone.utc),
                -item.last_activity_at_utc.timestamp(),
                item.post_id,
            )
        )
        if limit is not None:
            if isinstance(limit, bool) or limit < 0:
                raise V2CenterError("active thread limit is invalid")
            result = result[:limit]
        return tuple(result)

    def mark_threads_refreshed(
        self, post_ids: Iterable[str], refreshed_at_utc: datetime
    ) -> None:
        if self.read_only:
            raise V2CenterError("center store is read-only")
        if refreshed_at_utc.tzinfo is None:
            raise V2CenterError("refresh timestamp is not timezone-aware")
        value = _utc_z(refreshed_at_utc.astimezone(timezone.utc))
        identifiers = tuple(sorted(set(post_ids)))
        with self.connect() as connection:
            for post_id in identifiers:
                cursor = connection.execute(
                    "UPDATE active_threads SET last_refreshed_at_utc=? WHERE post_id=?",
                    (value, post_id),
                )
                if cursor.rowcount != 1:
                    raise V2CenterError("refreshed active thread is unknown")

    def active_thread_payloads(
        self, as_of_utc: datetime, *, limit: int | None = None
    ) -> tuple[dict[str, Any], ...]:
        active = self.active_threads(as_of_utc, limit=limit)
        if not active:
            return ()
        with self.connect() as connection:
            result = []
            for item in active:
                row = connection.execute(
                    "SELECT payload_json FROM canonical_posts WHERE post_id=?",
                    (item.post_id,),
                ).fetchone()
                if row is None:
                    raise V2CenterError("active thread canonical post is unavailable")
                payload = json.loads(row["payload_json"])
                payload["priority_reason_codes"] = list(item.priority_reason_codes)
                result.append(payload)
        return tuple(result)

    def canonical_comment_ids(self) -> frozenset[str]:
        with self.connect() as connection:
            return frozenset(
                str(row[0])
                for row in connection.execute(
                    "SELECT comment_id FROM canonical_comments ORDER BY comment_id"
                ).fetchall()
            )

    def state_payload(self) -> dict[str, object]:
        with self.connect() as connection:
            tables = {
                "active_threads": "post_id",
                "baseline_bridges": "source_dataset_id,receipt_sha256",
                "canonical_comments": "comment_id",
                "canonical_posts": "post_id",
                "comment_parent_edges": "comment_id",
                "comment_quarantine": "comment_id",
                "content_versions": "entity_type,entity_id,content_sha256",
                "engagement_snapshots": "entity_type,entity_id,observed_at_utc,engagement_sha256",
                "entity_occurrences": "occurrence_id",
                "relationship_debt": "comment_id",
                "profile_delta_closures": "receipt_sha256",
                "source_batches": "metric_end_utc,manifest_sha256",
            }
            ledgers = {
                table: [
                    dict(row)
                    for row in connection.execute(
                        f"SELECT * FROM {table} ORDER BY {order_by}"
                    ).fetchall()
                ]
                for table, order_by in tables.items()
            }
        return {
            "ledgers": ledgers,
            "schema_version": SCHEMA_VERSION,
        }

    def state_sha256(self) -> str:
        return _sha_bytes(canonical_json_bytes(self.state_payload()))


def _write_immutable(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            raise V2CenterError("immutable output is unsafe")
        if path.read_bytes() != payload:
            raise V2CenterError("immutable output collision")
        return "no_change"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return "created"


def _period_counts(
    rows: Iterable[sqlite3.Row],
    start: datetime,
    end: datetime,
) -> int:
    count = 0
    for row in rows:
        value = _utc(row["created_at_utc"], label="metric event time", allow_none=True)
        if value is not None and start <= value < end:
            count += 1
    return count


def compute_metric_release_value(
    store: V2CenterStore,
    *,
    cutoff_utc: datetime,
) -> dict[str, object]:
    if cutoff_utc.tzinfo is None:
        raise V2CenterError("metric cutoff is not timezone-aware")
    cutoff = cutoff_utc.astimezone(timezone.utc)
    with store.connect() as connection:
        posts = connection.execute("SELECT created_at_utc FROM canonical_posts").fetchall()
        comments = connection.execute("SELECT created_at_utc FROM canonical_comments").fetchall()
        source_batches = connection.execute(
            "SELECT batch_status,metric_start_utc,metric_end_utc,query_profile_sha256,coverage_profile_sha256 FROM source_batches ORDER BY metric_end_utc,manifest_sha256"
        ).fetchall()
        all_profiles = {
            (row["query_profile_sha256"], row["coverage_profile_sha256"])
            for row in source_batches
        }
        delta_closures = connection.execute(
            "SELECT * FROM profile_delta_closures ORDER BY coverage_end_utc,receipt_sha256"
        ).fetchall()
        batch_shas = [
            row[0]
            for row in connection.execute(
                "SELECT manifest_sha256 FROM source_batches ORDER BY metric_end_utc,manifest_sha256"
            ).fetchall()
        ]
        receipt_bindings = [
            {
                "manifest_sha256": row["manifest_sha256"],
                "validation_receipt_sha256": row["validation_receipt_sha256"],
            }
            for row in connection.execute(
                "SELECT manifest_sha256,validation_receipt_sha256 FROM source_batches ORDER BY metric_end_utc,manifest_sha256"
            ).fetchall()
        ]
        baseline_bridges = connection.execute(
            "SELECT receipt_sha256,source_dataset_id FROM baseline_bridges ORDER BY source_dataset_id,receipt_sha256"
        ).fetchall()
    if not batch_shas:
        raise V2CenterError("center has no consumed SourceBatch")
    if any(
        not isinstance(item["validation_receipt_sha256"], str)
        or len(item["validation_receipt_sha256"]) != 64
        for item in receipt_bindings
    ):
        raise V2CenterError("center contains candidate-ineligible SourceBatch")
    if len(baseline_bridges) > 1:
        raise V2CenterError("center contains multiple V3 baseline bridges")
    baseline_bridge = {
        "complete": len(baseline_bridges) == 1,
        "receipt_sha256": baseline_bridges[0]["receipt_sha256"] if baseline_bridges else None,
        "source_dataset_id": baseline_bridges[0]["source_dataset_id"] if baseline_bridges else None,
    }
    periods: dict[str, dict[str, object]] = {}
    windows = {
        "daily": timedelta(days=1),
        "weekly": timedelta(days=7),
        "monthly": timedelta(days=30),
    }
    for grain, duration in windows.items():
        current_start = cutoff - duration
        previous_start = current_start - duration
        relevant_batches = [
            row
            for row in source_batches
            if _utc(row["metric_end_utc"], label="profile period end") > previous_start
            and _utc(row["metric_start_utc"], label="profile period start") < cutoff
        ]
        period_profiles = {
            (row["query_profile_sha256"], row["coverage_profile_sha256"])
            for row in relevant_batches
        }
        coverage_complete = _coverage_union_complete(
            relevant_batches,
            start=previous_start,
            end=cutoff,
        )
        delta_closed = len(all_profiles) <= 1
        if len(all_profiles) > 1 and len(period_profiles) == 1:
            target_query, target_coverage = next(iter(period_profiles))
            delta_closed = any(
                row["to_query_profile_sha256"] == target_query
                and row["to_coverage_profile_sha256"] == target_coverage
                and _utc(row["coverage_start_utc"], label="delta coverage start") <= previous_start
                and _utc(row["coverage_end_utc"], label="delta coverage end") >= cutoff
                for row in delta_closures
            )
        comparison_available = (
            coverage_complete and len(period_profiles) == 1 and delta_closed
        )
        comparison_blockers = []
        if not coverage_complete:
            comparison_blockers.append("coverage_incomplete")
        if len(period_profiles) != 1:
            comparison_blockers.append("profile_mismatch")
        if not delta_closed:
            comparison_blockers.append("profile_delta_not_closed")
        current_posts = _period_counts(posts, current_start, cutoff)
        current_comments = _period_counts(comments, current_start, cutoff)
        previous_posts = _period_counts(posts, previous_start, current_start)
        previous_comments = _period_counts(comments, previous_start, current_start)
        current_voc = current_posts + current_comments
        previous_voc = previous_posts + previous_comments
        periods[grain] = {
            "comparison_available": comparison_available,
            "comparison_blockers": comparison_blockers,
            "current": {
                "comment_count": current_comments,
                "post_count": current_posts,
                "voc_count": current_voc,
            },
            "period_end_utc": _utc_z(cutoff),
            "period_start_utc": _utc_z(current_start),
            "previous": {
                "comment_count": previous_comments,
                "post_count": previous_posts,
                "voc_count": previous_voc,
            },
            "voc_change": current_voc - previous_voc if comparison_available else None,
        }
    state_sha = store.state_sha256()
    release_seed = {
        "cutoff_utc": _utc_z(cutoff),
        "source_batch_manifest_sha256s": batch_shas,
        "source_batch_validation_receipts": receipt_bindings,
        "state_sha256": state_sha,
    }
    release_id = "reddit-voc-v2-" + _sha_bytes(canonical_json_bytes(release_seed))[:20]
    surface_names = ("cases", "insights", "overview", "personas", "reports")
    surface_bindings = {}
    for name in surface_names:
        surface_value = {
            "canonical_state_sha256": state_sha,
            "metric_release_id": release_id,
            "schema_version": "reddit_voc_v2_surface_binding_v1",
            "surface": name,
        }
        surface_payload = canonical_json_bytes(surface_value) + b"\n"
        surface_bindings[name] = {
            "artifact_path": f"surface-artifacts/{name}.json",
            "artifact_sha256": _sha_bytes(surface_payload),
            "metric_release_id": release_id,
        }
    value = {
        "baseline_bridge": baseline_bridge,
        "boundaries": dict(BOUNDARIES),
        "canonical_state_sha256": state_sha,
        "cutoff_utc": _utc_z(cutoff),
        "metric_release_id": release_id,
        "periods": periods,
        "profile_comparable": all(
            bool(period["comparison_available"]) for period in periods.values()
        ),
        "schema_version": METRIC_RELEASE_SCHEMA_VERSION,
        "source_batch_manifest_sha256s": batch_shas,
        "source_batch_validation_receipts": receipt_bindings,
        "surface_bindings": surface_bindings,
        "totals": {
            "comments": len(comments),
            "linked_comments": store.count("comment_parent_edges")
            - store.count("relationship_debt")
            - store.count("comment_quarantine"),
            "posts": len(posts),
            "quarantined_comments": store.count("comment_quarantine"),
            "relationship_debt": store.count("relationship_debt"),
            "voc": len(posts) + len(comments),
        },
    }
    return value


def build_metric_release(
    store: V2CenterStore,
    *,
    cutoff_utc: datetime,
    output_path: Path | str,
) -> MetricReleaseResult:
    value = compute_metric_release_value(store, cutoff_utc=cutoff_utc)
    path = Path(output_path)
    for name, binding in value["surface_bindings"].items():
        surface_value = {
            "canonical_state_sha256": value["canonical_state_sha256"],
            "metric_release_id": value["metric_release_id"],
            "schema_version": "reddit_voc_v2_surface_binding_v1",
            "surface": name,
        }
        surface_path = path.parent / str(binding["artifact_path"])
        _write_immutable(surface_path, canonical_json_bytes(surface_value) + b"\n")
    payload = canonical_json_bytes(value) + b"\n"
    write_status = _write_immutable(path, payload)
    return MetricReleaseResult(
        path=path,
        metric_release_id=str(value["metric_release_id"]),
        sha256=_sha_bytes(payload),
        write_status=write_status,
    )


def register_candidate(
    store: V2CenterStore,
    *,
    metric_release_path: Path | str,
    registry_root: Path | str,
) -> CandidateResult:
    metric_path = Path(metric_release_path)
    try:
        metric_payload = metric_path.read_bytes()
        metric = json.loads(metric_payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V2CenterError("metric release is invalid") from exc
    if not isinstance(metric, dict) or metric_payload != canonical_json_bytes(metric) + b"\n":
        raise V2CenterError("metric release is not canonical")
    if metric.get("schema_version") != METRIC_RELEASE_SCHEMA_VERSION:
        raise V2CenterError("metric release schema is invalid")
    if metric.get("canonical_state_sha256") != store.state_sha256():
        raise V2CenterError("metric release is stale")
    cutoff_value = metric.get("cutoff_utc")
    if not isinstance(cutoff_value, str):
        raise V2CenterError("metric release cutoff is invalid")
    cutoff = _utc(cutoff_value, label="metric release cutoff")
    if cutoff is None or metric != compute_metric_release_value(store, cutoff_utc=cutoff):
        raise V2CenterError("metric release recomputation mismatch")
    value = compute_candidate_value(metric, metric_payload)
    candidate_id = str(value["candidate_id"])
    payload = canonical_json_bytes(value) + b"\n"
    root = Path(registry_root)
    path = root / candidate_id / "candidate.json"
    write_status = _write_immutable(path, payload)
    return CandidateResult(
        path=path,
        candidate_id=candidate_id,
        sha256=_sha_bytes(payload),
        write_status=write_status,
    )


def compute_candidate_value(
    metric: Mapping[str, Any], metric_payload: bytes
) -> dict[str, object]:
    metric_sha = _sha_bytes(metric_payload)
    candidate_id = "reddit-voc-v2-candidate-" + metric_sha[:20]
    baseline_bridge = metric.get("baseline_bridge")
    baseline_complete = (
        isinstance(baseline_bridge, dict) and baseline_bridge.get("complete") is True
    )
    blockers = ["reply_provider_schema_unverified"]
    blockers.append(
        "full_v3_page_e2e_and_shadow_incomplete"
        if baseline_complete
        else "full_v3_baseline_bridge_incomplete"
    )
    return {
        "boundaries": dict(BOUNDARIES),
        "candidate_id": candidate_id,
        "canonical_state_sha256": metric["canonical_state_sha256"],
        "metric_release_id": metric["metric_release_id"],
        "metric_release_sha256": metric_sha,
        "schema_version": CANDIDATE_SCHEMA_VERSION,
        "source_batch_manifest_sha256s": metric["source_batch_manifest_sha256s"],
        "source_batch_validation_receipts": metric["source_batch_validation_receipts"],
        "baseline_bridge_complete": baseline_complete,
        "baseline_bridge_receipt_sha256": (
            baseline_bridge.get("receipt_sha256") if baseline_complete else None
        ),
        "blockers": blockers,
        "promotable": False,
        "status": "local_candidate_registered",
    }
