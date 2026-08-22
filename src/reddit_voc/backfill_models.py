from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from typing import Literal


BackfillStatus = Literal[
    "prepared",
    "seed_complete",
    "running",
    "partial",
    "success",
    "blocked",
    "failed",
]
LaneType = Literal["dynamic_search", "subreddit_feed", "detail_batch", "comments"]
ArtifactLaneType = Literal[
    "seed",
    "dynamic_search",
    "subreddit_feed",
    "detail_batch",
    "comments",
]
LaneStatus = Literal["prepared", "running", "partial", "complete", "failed"]
ProviderAttemptStatus = Literal["reserved", "sent", "succeeded", "failed"]
DiscoveryDisposition = Literal[
    "new_candidate",
    "duplicate_occurrence",
    "outside_window",
    "duplicate_existing_structured",
    "invalid",
]
DiscoveryBaseDisposition = Literal["eligible", "outside_window", "invalid"]
CandidateStatus = Literal[
    "pending",
    "duplicate_existing_structured",
    "hydrated",
    "excluded",
    "outside_window_detail",
    "failed",
    "budget_deferred",
]
ValidationScope = Literal["seed", "full"]


def discovery_occurrence_contract(
    *,
    post_id: str,
    source_url: str,
    title: str,
    created_at_utc: datetime | None,
    window_start_utc: datetime,
    window_end_utc: datetime,
) -> tuple[
    DiscoveryBaseDisposition,
    str | None,
    str | None,
    datetime | None,
]:
    """Classify one discovery row while preserving any parsed identity fields."""
    normalized_post_id = post_id or None
    normalized_source_url = source_url or None
    if (
        normalized_post_id is None
        or normalized_source_url is None
        or not title
        or created_at_utc is None
    ):
        disposition: DiscoveryBaseDisposition = "invalid"
    elif not window_start_utc <= created_at_utc < window_end_utc:
        disposition = "outside_window"
    else:
        disposition = "eligible"
    return (
        disposition,
        normalized_post_id,
        normalized_source_url,
        created_at_utc,
    )


@dataclass(frozen=True)
class SeedBaseline:
    schema_version: Literal["momcozy_seed_baseline_v1"]
    files_total: int
    files_imported: int
    files_outside_window: int
    files_excluded: int
    files_duplicate: int
    parse_errors: int
    threads: int
    comments: int
    analyses: int
    coverage_full: int
    coverage_partial: int
    coverage_post_only: int
    source_inventory_sha256: str
    known_partial_post_ids_sha256: str
    reviewed_search_terms_sha256: str
    reviewed_subreddits: tuple[str, ...]
    reviewed_subreddits_sha256: str
    baseline_sha256: str


def required_lanes_snapshot(
    *,
    search_terms: Sequence[str],
    subreddits: Sequence[str],
    include_subreddit_sweep: bool,
) -> tuple[tuple[Literal["dynamic_search", "subreddit_feed"], str], ...]:
    terms = _validated_lane_keys("search_terms", search_terms)
    reviewed_subreddits = _validated_lane_keys("subreddits", subreddits)
    if type(include_subreddit_sweep) is not bool:
        raise ValueError("include_subreddit_sweep must be a bool")
    lanes: list[tuple[Literal["dynamic_search", "subreddit_feed"], str]] = [
        ("dynamic_search", term) for term in terms
    ]
    if include_subreddit_sweep:
        lanes.extend(("subreddit_feed", subreddit) for subreddit in reviewed_subreddits)
    return tuple(lanes)


def required_lanes_sha256(
    *,
    search_terms: Sequence[str],
    subreddits: Sequence[str],
    include_subreddit_sweep: bool,
) -> str:
    snapshot = required_lanes_snapshot(
        search_terms=search_terms,
        subreddits=subreddits,
        include_subreddit_sweep=include_subreddit_sweep,
    )
    payload = json.dumps(
        [[lane_type, lane_key] for lane_type, lane_key in snapshot],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _validated_lane_keys(name: str, values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError(f"{name} must be a non-empty sequence of strings")
    result = tuple(values)
    if not result or any(type(value) is not str or not value.strip() for value in result):
        raise ValueError(f"{name} must be a non-empty sequence of strings")
    if len(set(result)) != len(result):
        raise ValueError(f"{name} must not contain duplicates")
    return result


@dataclass(frozen=True)
class CursorContract:
    cursor_path: tuple[str | int, ...]
    schema_sha256: str


@dataclass(frozen=True)
class LaneResult:
    run_id: str
    lane_type: LaneType
    lane_key: str
    status: Literal["complete", "partial", "failed"]
    stop_reason: str
    pages: int
    discovered_occurrences: int
    unique_candidates: int
    provider_request_count: int
    provider_call: bool
    live_send: bool = False


@dataclass(frozen=True)
class DetailBatch:
    run_id: str
    batch_id: str
    batch_number: int
    post_ids: tuple[str, ...]
    status: Literal["prepared", "raw_persisted", "complete", "failed"]
    artifact_id: str | None
    stop_reason: str | None
    created_at_utc: str
    updated_at_utc: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "post_ids", tuple(self.post_ids))


@dataclass(frozen=True)
class BackfillManifest:
    run_id: str
    status: BackfillStatus
    window_start_utc: str
    requested_end_utc: str
    effective_end_utc: str
    search_terms: Sequence[str]
    subreddits: Sequence[str]
    include_subreddit_sweep: bool
    required_lanes_sha256: str
    keyword_config_sha256: str
    max_provider_requests: int
    provider_request_count: int
    provider_call: bool
    live_send: bool
    created_at_utc: str
    updated_at_utc: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "search_terms", tuple(self.search_terms))
        object.__setattr__(self, "subreddits", tuple(self.subreddits))


@dataclass(frozen=True)
class BackfillCheckpoint:
    run_id: str
    lane_type: LaneType
    lane_key: str
    cursor: str | None
    previous_cursor: str | None
    page_number: int
    newest_seen_utc: str | None
    oldest_seen_utc: str | None
    discovered_count: int
    unique_count: int
    provider_request_count: int
    last_success_utc: str | None
    last_error: str | None
    status: LaneStatus
    stop_reason: str | None
    cursor_json_path: str | None
    cursor_schema_sha256: str | None
    consecutive_old_pages: int


@dataclass(frozen=True)
class RawArtifactMetadata:
    artifact_id: str
    run_id: str
    artifact_kind: str
    lane_type: ArtifactLaneType
    lane_key_hash: str
    identity_hash: str
    raw_capture_id: str
    parser_kind: str
    source_method: str
    source_url: str
    source_endpoint: str
    payload_sha256: str
    relative_path: str
    captured_at_utc: str
    page_number: int | None
    request_cursor: str | None
    response_cursor: str | None


@dataclass(frozen=True)
class ProviderAttempt:
    run_id: str
    request_number: int
    endpoint: str
    status: ProviderAttemptStatus
    reserved_at_utc: str
    sent_at_utc: str | None = None
    completed_at_utc: str | None = None
    http_status: int | None = None
    error_class: str | None = None


@dataclass(frozen=True)
class AnalysisRow:
    analysis_id: str
    run_id: str
    source_type: Literal["post", "comment"]
    source_id: str
    analysis_version: str
    sentiment_label: str
    sentiment_score: float
    topic: str
    severity: str
    confidence: float
    pain_points: tuple[str, ...]
    provider_call: bool = False


@dataclass(frozen=True)
class InsertCounts:
    raw_captures: int = 0
    threads: int = 0
    comments: int = 0
    analyses: int = 0


@dataclass(frozen=True)
class SeedImportSummary:
    run_id: str
    status: Literal["seed_complete", "failed"]
    files_total: int
    files_imported: int
    files_outside_window: int
    files_excluded: int
    files_duplicate: int
    parse_errors: int
    threads: int
    comments: int
    analyses: int
    coverage_full: int
    coverage_partial: int
    coverage_post_only: int
    provider_call: bool = False
    live_send: bool = False
