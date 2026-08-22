from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import RawCapture, RedditComment, RedditThread


def _comment_source_url(post_source_url: str | None, comment_id: str) -> str | None:
    if not post_source_url:
        return None
    short_id = comment_id.split("_", 1)[1] if comment_id.startswith("t1_") else comment_id
    return post_source_url.rstrip("/") + f"/{short_id}/"


def _json_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return [part.strip() for part in text.split(",") if part.strip()]
    if isinstance(parsed, list):
        return [str(item) for item in parsed if str(item).strip()]
    return []


def _thread_record(row: dict[str, Any]) -> dict[str, Any]:
    row["media_urls"] = _json_list(row.get("media_urls"))
    return row


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    window_start_utc TEXT NOT NULL,
    window_end_utc TEXT NOT NULL,
    provider_call INTEGER NOT NULL DEFAULT 0,
    live_send INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS raw_captures (
    raw_capture_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    source_method TEXT NOT NULL,
    source_url TEXT NOT NULL,
    captured_at_utc TEXT NOT NULL,
    auth_boundary TEXT NOT NULL,
    raw_payload_hash TEXT NOT NULL,
    payload_format TEXT NOT NULL,
    browser_status TEXT NOT NULL,
    http_status INTEGER,
    selector_version TEXT,
    blocked_reason TEXT,
    secrets_written INTEGER NOT NULL DEFAULT 0,
    UNIQUE(run_id, source_method, source_url, raw_payload_hash)
);

CREATE TABLE IF NOT EXISTS reddit_threads (
    post_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    raw_capture_id TEXT NOT NULL,
    subreddit TEXT NOT NULL,
    title TEXT NOT NULL,
    selftext TEXT NOT NULL,
    source_url TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    score INTEGER,
    num_comments_reported INTEGER,
    parsed_comment_count INTEGER NOT NULL,
    more_node_count INTEGER NOT NULL,
    coverage_grade TEXT NOT NULL,
    matched_keywords TEXT NOT NULL,
    author_hash TEXT,
    media_urls TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS reddit_comments (
    comment_id TEXT PRIMARY KEY,
    post_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    raw_capture_id TEXT NOT NULL,
    parent_id TEXT,
    body TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    score INTEGER,
    depth INTEGER,
    is_submitter INTEGER,
    matched_keywords TEXT NOT NULL,
    author_hash TEXT,
    deleted_or_removed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS analysis_results (
    analysis_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    analysis_version TEXT NOT NULL,
    sentiment_label TEXT NOT NULL,
    sentiment_score REAL NOT NULL,
    topic TEXT NOT NULL,
    severity TEXT NOT NULL,
    confidence REAL NOT NULL,
    pain_points TEXT NOT NULL,
    provider_call INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS delivery_previews (
    delivery_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    message_hash TEXT NOT NULL,
    artifact_paths TEXT NOT NULL,
    live_send INTEGER NOT NULL DEFAULT 0
);
"""


_SOURCE_BATCH_REQUIRED_TABLES = frozenset(
    {
        "runs",
        "raw_captures",
        "reddit_threads",
        "reddit_comments",
        "analysis_results",
    }
)
_CURRENT_RAW_CAPTURE_UNIQUE = (
    "run_id",
    "source_method",
    "source_url",
    "raw_payload_hash",
)
_LEGACY_RAW_CAPTURE_UNIQUE = (
    "source_method",
    "source_url",
    "raw_payload_hash",
)


class VocStore:
    def __init__(self, path: Path | str, *, read_only: bool = False) -> None:
        self.path = Path(path)
        self.read_only = read_only
        if self.read_only:
            if not self.path.is_file():
                raise FileNotFoundError(self.path)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        if self.read_only:
            uri = f"{self.path.resolve().as_uri()}?mode=ro"
            conn = sqlite3.connect(uri, uri=True)
            conn.execute("PRAGMA query_only = ON")
        else:
            conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def migrate(self) -> None:
        if self.read_only:
            raise RuntimeError("readonly_store_migration_forbidden")
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._ensure_columns(conn)

    @staticmethod
    def _ensure_columns(conn: sqlite3.Connection) -> None:
        thread_columns = {row["name"] for row in conn.execute("PRAGMA table_info(reddit_threads)").fetchall()}
        if "media_urls" not in thread_columns:
            conn.execute("ALTER TABLE reddit_threads ADD COLUMN media_urls TEXT NOT NULL DEFAULT '[]'")
        for index in conn.execute("PRAGMA index_list(raw_captures)").fetchall():
            if not index["unique"]:
                continue
            columns = tuple(
                row["name"]
                for row in conn.execute(f"PRAGMA index_info('{index['name']}')").fetchall()
            )
            if columns == ("source_method", "source_url", "raw_payload_hash"):
                conn.executescript(
                    """
                    CREATE TABLE raw_captures_v2 (
                        raw_capture_id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        source_method TEXT NOT NULL,
                        source_url TEXT NOT NULL,
                        captured_at_utc TEXT NOT NULL,
                        auth_boundary TEXT NOT NULL,
                        raw_payload_hash TEXT NOT NULL,
                        payload_format TEXT NOT NULL,
                        browser_status TEXT NOT NULL,
                        http_status INTEGER,
                        selector_version TEXT,
                        blocked_reason TEXT,
                        secrets_written INTEGER NOT NULL DEFAULT 0,
                        UNIQUE(run_id, source_method, source_url, raw_payload_hash)
                    );
                    INSERT INTO raw_captures_v2 SELECT * FROM raw_captures;
                    DROP TABLE raw_captures;
                    ALTER TABLE raw_captures_v2 RENAME TO raw_captures;
                    """
                )
                break

    def require_daily_source_batch_schema(self) -> None:
        with self.connect() as conn:
            tables = {
                str(row["name"])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            missing_tables = sorted(_SOURCE_BATCH_REQUIRED_TABLES - tables)
            if missing_tables:
                raise RuntimeError(
                    "daily_source_batch_schema_incompatible:missing_tables="
                    + ",".join(missing_tables)
                )

            thread_columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(reddit_threads)").fetchall()
            }
            if "media_urls" not in thread_columns:
                raise RuntimeError("daily_source_batch_schema_migration_required")

            unique_constraints: set[tuple[str, ...]] = set()
            for index in conn.execute("PRAGMA index_list(raw_captures)").fetchall():
                if not index["unique"]:
                    continue
                index_name = str(index["name"]).replace("'", "''")
                unique_constraints.add(
                    tuple(
                        str(row["name"])
                        for row in conn.execute(
                            f"PRAGMA index_info('{index_name}')"
                        ).fetchall()
                    )
                )

        if _CURRENT_RAW_CAPTURE_UNIQUE in unique_constraints:
            return
        if _LEGACY_RAW_CAPTURE_UNIQUE in unique_constraints:
            raise RuntimeError("daily_source_batch_schema_migration_required")
        raise RuntimeError("daily_source_batch_schema_incompatible:raw_captures_unique")

    def upsert_run(
        self,
        run_id: str,
        status: str,
        window_start_utc: str,
        window_end_utc: str,
        *,
        provider_call: bool = False,
        live_send: bool = False,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO runs(run_id, status, window_start_utc, window_end_utc, provider_call, live_send)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status=excluded.status,
                    window_start_utc=excluded.window_start_utc,
                    window_end_utc=excluded.window_end_utc,
                    provider_call=excluded.provider_call,
                    live_send=excluded.live_send
                """,
                (run_id, status, window_start_utc, window_end_utc, int(provider_call), int(live_send)),
            )

    def insert_raw_capture(self, capture: RawCapture) -> None:
        record = capture.as_record()
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT * FROM raw_captures WHERE raw_capture_id=?",
                (capture.raw_capture_id,),
            ).fetchone()
            if existing is not None:
                if dict(existing) != record:
                    raise ValueError(f"raw capture identity collision:{capture.raw_capture_id}")
                return
            conn.execute(
                """
                INSERT INTO raw_captures(
                    raw_capture_id, run_id, source_method, source_url, captured_at_utc,
                    auth_boundary, raw_payload_hash, payload_format, browser_status,
                    http_status, selector_version, blocked_reason, secrets_written
                ) VALUES (
                    :raw_capture_id, :run_id, :source_method, :source_url, :captured_at_utc,
                    :auth_boundary, :raw_payload_hash, :payload_format, :browser_status,
                    :http_status, :selector_version, :blocked_reason, :secrets_written
                )
                """,
                record,
            )

    def upsert_thread(self, thread: RedditThread) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO reddit_threads(
                    post_id, run_id, raw_capture_id, subreddit, title, selftext, source_url,
                    created_at_utc, score, num_comments_reported, parsed_comment_count,
                    more_node_count, coverage_grade, matched_keywords, author_hash, media_urls
                ) VALUES (
                    :post_id, :run_id, :raw_capture_id, :subreddit, :title, :selftext,
                    :source_url, :created_at_utc, :score, :num_comments_reported,
                    :parsed_comment_count, :more_node_count, :coverage_grade,
                    :matched_keywords, :author_hash, :media_urls
                )
                ON CONFLICT(post_id) DO UPDATE SET
                    run_id=excluded.run_id,
                    raw_capture_id=excluded.raw_capture_id,
                    subreddit=excluded.subreddit,
                    title=excluded.title,
                    selftext=excluded.selftext,
                    source_url=excluded.source_url,
                    created_at_utc=excluded.created_at_utc,
                    score=excluded.score,
                    num_comments_reported=excluded.num_comments_reported,
                    parsed_comment_count=excluded.parsed_comment_count,
                    more_node_count=excluded.more_node_count,
                    coverage_grade=excluded.coverage_grade,
                    matched_keywords=excluded.matched_keywords,
                    author_hash=excluded.author_hash,
                    media_urls=excluded.media_urls
                """,
                thread.as_record(),
            )

    def upsert_comment(self, comment: RedditComment) -> None:
        record = comment.as_record()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO reddit_comments(
                    comment_id, post_id, run_id, raw_capture_id, parent_id, body,
                    created_at_utc, score, depth, is_submitter, matched_keywords,
                    author_hash, deleted_or_removed
                ) VALUES (
                    :comment_id, :post_id, :run_id, :raw_capture_id, :parent_id, :body,
                    :created_at_utc, :score, :depth, :is_submitter, :matched_keywords,
                    :author_hash, :deleted_or_removed
                )
                ON CONFLICT(comment_id) DO UPDATE SET
                    post_id=excluded.post_id,
                    run_id=excluded.run_id,
                    raw_capture_id=excluded.raw_capture_id,
                    parent_id=excluded.parent_id,
                    body=excluded.body,
                    created_at_utc=excluded.created_at_utc,
                    score=excluded.score,
                    depth=excluded.depth,
                    is_submitter=excluded.is_submitter,
                    matched_keywords=excluded.matched_keywords,
                    author_hash=excluded.author_hash,
                    deleted_or_removed=excluded.deleted_or_removed
                """,
                record,
            )

    def table_count(self, table: str) -> int:
        if table not in {"runs", "raw_captures", "reddit_threads", "reddit_comments", "analysis_results", "delivery_previews"}:
            raise ValueError(f"unsupported table: {table}")
        with self.connect() as conn:
            row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
            return int(row["count"])

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            return dict(row) if row else None

    def count_for_run(self, table: str, run_id: str) -> int:
        if table not in {"raw_captures", "reddit_threads", "reddit_comments", "analysis_results", "delivery_previews"}:
            raise ValueError(f"unsupported run-scoped table: {table}")
        with self.connect() as conn:
            row = conn.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE run_id = ?", (run_id,)).fetchone()
            return int(row["count"])

    def clear_collected_data_for_run(self, run_id: str) -> None:
        with self.connect() as conn:
            for table in ("analysis_results", "reddit_comments", "reddit_threads", "raw_captures"):
                conn.execute(f"DELETE FROM {table} WHERE run_id = ?", (run_id,))

    def delivery_live_send_count_for_run(self, run_id: str) -> int:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM delivery_previews
                WHERE run_id = ? AND live_send = 1
                """,
                (run_id,),
            ).fetchone()
            return int(row["count"])

    def fetch_threads_for_run(self, run_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    post_id, run_id, raw_capture_id, subreddit, title, selftext,
                    source_url, created_at_utc, score, num_comments_reported,
                    parsed_comment_count, more_node_count, coverage_grade,
                    matched_keywords, author_hash, media_urls
                FROM reddit_threads
                WHERE run_id = ?
                ORDER BY created_at_utc, post_id
                """,
                (run_id,),
            ).fetchall()
            return [_thread_record(dict(row)) for row in rows]

    def fetch_metric_threads_for_run(self, run_id: str) -> list[dict[str, Any]]:
        run = self.get_run(run_id)
        if run is None:
            return []
        start = datetime.fromisoformat(str(run["window_start_utc"]).replace("Z", "+00:00")).astimezone(timezone.utc)
        end = datetime.fromisoformat(str(run["window_end_utc"]).replace("Z", "+00:00")).astimezone(timezone.utc)
        return [
            row
            for row in self.fetch_threads_for_run(run_id)
            if start
            <= datetime.fromisoformat(str(row["created_at_utc"]).replace("Z", "+00:00")).astimezone(timezone.utc)
            < end
        ]

    def fetch_raw_captures_for_run(self, run_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    raw_capture_id, run_id, source_method, source_url,
                    captured_at_utc, auth_boundary, raw_payload_hash,
                    payload_format, browser_status, http_status,
                    selector_version, blocked_reason, secrets_written
                FROM raw_captures
                WHERE run_id = ?
                ORDER BY captured_at_utc, raw_capture_id
                """,
                (run_id,),
            ).fetchall()
        records = [dict(row) for row in rows]
        for record in records:
            record["secrets_written"] = bool(record["secrets_written"])
        return records

    def fetch_recent_threads(self, *, limit: int = 200) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    post_id, run_id, raw_capture_id, subreddit, title, selftext,
                    source_url, created_at_utc, score, num_comments_reported,
                    parsed_comment_count, more_node_count, coverage_grade,
                    matched_keywords, author_hash, media_urls
                FROM reddit_threads
                ORDER BY created_at_utc DESC, post_id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [_thread_record(dict(row)) for row in rows]

    def fetch_comments_for_run(self, run_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    c.comment_id, c.post_id, c.run_id, c.raw_capture_id, c.parent_id,
                    c.body, c.created_at_utc, c.score, c.depth, c.is_submitter,
                    c.matched_keywords, c.author_hash, c.deleted_or_removed,
                    t.source_url AS post_source_url
                FROM reddit_comments c
                LEFT JOIN reddit_threads t ON c.post_id = t.post_id
                WHERE c.run_id = ?
                ORDER BY c.created_at_utc, c.comment_id
                """,
                (run_id,),
            ).fetchall()
            records = [dict(row) for row in rows]
            for record in records:
                if record["is_submitter"] is not None:
                    record["is_submitter"] = bool(record["is_submitter"])
                record["deleted_or_removed"] = bool(record["deleted_or_removed"])
                record["source_url"] = _comment_source_url(record.get("post_source_url"), record["comment_id"])
            return records

    def fetch_analysis_for_run(self, run_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    a.analysis_id, a.run_id, a.source_type, a.source_id,
                    a.analysis_version, a.sentiment_label, a.sentiment_score,
                    a.topic, a.severity, a.confidence, a.pain_points,
                    a.provider_call,
                    COALESCE(post_thread.source_url, comment_thread.source_url) AS post_source_url
                FROM analysis_results a
                LEFT JOIN reddit_threads post_thread
                    ON a.source_type = 'post' AND a.source_id = post_thread.post_id
                LEFT JOIN reddit_comments c
                    ON a.source_type = 'comment' AND a.source_id = c.comment_id
                LEFT JOIN reddit_threads comment_thread
                    ON c.post_id = comment_thread.post_id
                WHERE a.run_id = ?
                ORDER BY a.source_type, a.source_id
                """,
                (run_id,),
            ).fetchall()
        records = [dict(row) for row in rows]
        for record in records:
            record["provider_call"] = bool(record["provider_call"])
            if record["source_type"] == "comment":
                record["source_url"] = _comment_source_url(record.get("post_source_url"), record["source_id"])
            else:
                record["source_url"] = record.get("post_source_url")
        return records

    def coverage_summary_for_run(self, run_id: str) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT coverage_grade, COUNT(*) AS count
                FROM reddit_threads
                WHERE run_id = ?
                GROUP BY coverage_grade
                """,
                (run_id,),
            ).fetchall()
            return {str(row["coverage_grade"]): int(row["count"]) for row in rows}

    def find_runs_by_window(self, window_start_utc: str, window_end_utc: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM runs
                WHERE window_start_utc = ? AND window_end_utc = ?
                ORDER BY run_id
                """,
                (window_start_utc, window_end_utc),
            ).fetchall()
            return [dict(row) for row in rows]

    def fetch_metric_comments_for_run(self, run_id: str) -> list[dict[str, Any]]:
        metric_post_ids = {
            str(row["post_id"]) for row in self.fetch_metric_threads_for_run(run_id)
        }
        return [
            row
            for row in self.fetch_comments_for_run(run_id)
            if str(row["post_id"]) in metric_post_ids
        ]

    def insert_delivery_record(
        self,
        delivery_id: str,
        run_id: str,
        message_hash: str,
        artifact_paths: list[str],
        *,
        mode: str = "dry_run",
        status: str = "created",
        live_send: bool = False,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO delivery_previews(
                    delivery_id, run_id, channel, mode, status, message_hash, artifact_paths, live_send
                ) VALUES (?, ?, 'dingtalk', ?, ?, ?, ?, ?)
                """,
                (
                    delivery_id,
                    run_id,
                    mode,
                    status,
                    message_hash,
                    json.dumps(artifact_paths, ensure_ascii=False),
                    int(live_send),
                ),
            )

    def insert_delivery_preview(self, delivery_id: str, run_id: str, message_hash: str, artifact_paths: list[str]) -> None:
        self.insert_delivery_record(
            delivery_id,
            run_id,
            message_hash,
            artifact_paths,
            mode="dry_run",
            status="created",
            live_send=False,
        )

    def insert_analysis(
        self,
        *,
        analysis_id: str,
        run_id: str,
        source_type: str,
        source_id: str,
        sentiment_label: str,
        sentiment_score: float,
        topic: str,
        severity: str,
        confidence: float,
        pain_points: list[str],
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO analysis_results(
                    analysis_id, run_id, source_type, source_id, analysis_version,
                    sentiment_label, sentiment_score, topic, severity, confidence,
                    pain_points, provider_call
                ) VALUES (?, ?, ?, ?, 'local_rules_v1', ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    analysis_id,
                    run_id,
                    source_type,
                    source_id,
                    sentiment_label,
                    sentiment_score,
                    topic,
                    severity,
                    confidence,
                    json.dumps(pain_points, ensure_ascii=False),
                ),
            )
