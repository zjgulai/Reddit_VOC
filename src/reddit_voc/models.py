from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class DailyCollectionSummary:
    run_id: str
    status: str
    window_start_utc: str
    window_end_utc: str
    subreddits: list[str]
    listing_urls: list[str] = field(default_factory=list)
    discovered_posts: int = 0
    window_posts: int = 0
    relevant_posts: int = 0
    detail_attempts: int = 0
    ingested_threads: int = 0
    ingested_comments: int = 0
    analysis_items: int = 0
    coverage: dict[str, int] = field(default_factory=dict)
    issues: list[dict[str, str]] = field(default_factory=list)
    provider_call: bool = False
    live_send: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "window_start_utc": self.window_start_utc,
            "window_end_utc": self.window_end_utc,
            "subreddits": self.subreddits,
            "listing_urls": self.listing_urls,
            "discovered_posts": self.discovered_posts,
            "window_posts": self.window_posts,
            "relevant_posts": self.relevant_posts,
            "detail_attempts": self.detail_attempts,
            "ingested_threads": self.ingested_threads,
            "ingested_comments": self.ingested_comments,
            "analysis_items": self.analysis_items,
            "coverage": self.coverage,
            "issues": self.issues,
            "provider_call": self.provider_call,
            "live_send": self.live_send,
        }


@dataclass(frozen=True)
class RawCapture:
    raw_capture_id: str
    run_id: str
    source_method: str
    source_url: str
    captured_at_utc: datetime
    auth_boundary: str
    raw_payload_hash: str
    payload_format: str
    browser_status: str = "ok"
    http_status: int | None = None
    selector_version: str | None = None
    blocked_reason: str | None = None
    secrets_written: bool = False

    def as_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["captured_at_utc"] = self.captured_at_utc.isoformat()
        return record


@dataclass(frozen=True)
class RedditThread:
    post_id: str
    run_id: str
    raw_capture_id: str
    subreddit: str
    title: str
    source_url: str
    created_at_utc: datetime
    selftext: str = ""
    score: int | None = None
    num_comments_reported: int | None = None
    parsed_comment_count: int = 0
    more_node_count: int = 0
    coverage_grade: str = "post_only"
    matched_keywords: list[str] = field(default_factory=list)
    media_urls: list[str] = field(default_factory=list)
    author_hash: str | None = None

    def as_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["created_at_utc"] = self.created_at_utc.isoformat()
        record["matched_keywords"] = ",".join(self.matched_keywords)
        record["media_urls"] = json.dumps(self.media_urls, ensure_ascii=False)
        return record


@dataclass(frozen=True)
class RedditComment:
    comment_id: str
    post_id: str
    run_id: str
    raw_capture_id: str
    body: str
    created_at_utc: datetime
    parent_id: str | None = None
    score: int | None = None
    depth: int | None = None
    is_submitter: bool | None = None
    matched_keywords: list[str] = field(default_factory=list)
    author_hash: str | None = None
    deleted_or_removed: bool = False

    def as_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["created_at_utc"] = self.created_at_utc.isoformat()
        record["matched_keywords"] = ",".join(self.matched_keywords)
        return record
