from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .adapters import (
    BrowserJsonAdapter,
    BrowserJsonBlockedError,
    DiscoveryPost,
    _canonical_url,
    _extract_media_urls,
    _hash_author,
    _post_identity_from_url,
)
from .analyzer import analyze_text
from .keywords import match_keywords
from .models import DailyCollectionSummary, RawCapture, RedditComment, RedditThread
from .raw_artifacts import persist_raw_artifact
from .storage import VocStore
from .time_window import CollectionWindow, daily_window, rolling_window


TIKHUB_BASE_URL = "https://api.tikhub.io"
FETCH_SUBREDDIT_FEED = "/api/v1/reddit/app/fetch_subreddit_feed"
FETCH_DYNAMIC_SEARCH = "/api/v1/reddit/app/fetch_dynamic_search"
FETCH_POST_DETAILS_BATCH_LARGE = "/api/v1/reddit/app/fetch_post_details_batch_large"
FETCH_POST_COMMENTS = "/api/v1/reddit/app/fetch_post_comments"
FETCH_COMMENT_REPLIES = "/api/v1/reddit/app/fetch_comment_replies"
MAX_TIKHUB_BATCH_SIZE = 30
DEFAULT_BRAND_SEARCH_TERMS = [
    "Momcozy",
    "momcozy",
    "\"Momcozy\"",
    "\"momcozy\"",
    "\"mom cozy\"",
]


@dataclass(frozen=True)
class TikHubEndpointPlan:
    discovery_endpoints: list[str] = field(default_factory=lambda: [FETCH_DYNAMIC_SEARCH, FETCH_SUBREDDIT_FEED])
    detail_endpoint: str = FETCH_POST_DETAILS_BATCH_LARGE
    comment_endpoint: str = FETCH_POST_COMMENTS
    rationale: str = (
        "Run brand-first dynamic search for Momcozy/momcozy recall, then category/community discovery; "
        "batch details for post bodies, and comments endpoint when detail payload is incomplete."
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "discovery_endpoints": self.discovery_endpoints,
            "detail_endpoint": self.detail_endpoint,
            "comment_endpoint": self.comment_endpoint,
            "max_batch_size": MAX_TIKHUB_BATCH_SIZE,
            "rationale": self.rationale,
        }


class TikHubClient:
    def __init__(self, *, api_key: str, base_url: str = TIKHUB_BASE_URL, timeout_seconds: int = 30) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        query = urlencode({k: v for k, v in (params or {}).items() if v is not None}, doseq=True)
        url = self.base_url + path + (f"?{query}" if query else "")
        request = Request(url, headers=self._headers(), method="GET")
        return self._send(request)

    def post_json(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=body,
            headers={**self._headers(), "Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        return self._send(request)

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": os.getenv(
                "TIKHUB_USER_AGENT",
                "Mozilla/5.0 (compatible; RedditVOC/1.0; +https://reddit.brand.lute-tlz-dddd.top)",
            ),
        }

    def _send(self, request: Request) -> Any:
        with urlopen(request, timeout=self.timeout_seconds) as response:
            raw = response.read().decode("utf-8", errors="replace")
        return json.loads(raw)


def collect_daily_tikhub(
    store: VocStore,
    *,
    run_id: str,
    client: Any,
    subreddits: list[str],
    search_terms: list[str],
    anchor_utc: datetime | None = None,
    window_end_utc: datetime | None = None,
    rolling_window_hours: int = 24,
    run_hour: int = 7,
    listing_limit: int = 100,
    max_detail_posts: int = 30,
    new_post_overlap_hours: int = 2,
    raw_artifact_root: Path | str | None = None,
) -> DailyCollectionSummary:
    window = (
        rolling_window(end_utc=window_end_utc, hours=rolling_window_hours)
        if window_end_utc
        else daily_window(anchor=anchor_utc or datetime.now(timezone.utc), run_hour=run_hour)
    )
    if isinstance(new_post_overlap_hours, bool) or new_post_overlap_hours < 0:
        raise ValueError("new_post_overlap_hours must be nonnegative")
    discovery_window = CollectionWindow(
        timezone_name=window.timezone_name,
        run_at_local=window.run_at_local,
        start_local=window.start_local - timedelta(hours=new_post_overlap_hours),
        end_local=window.end_local,
        start_utc=window.start_utc - timedelta(hours=new_post_overlap_hours),
        end_utc=window.end_utc,
    )
    summary = DailyCollectionSummary(
        run_id=run_id,
        status="failed",
        window_start_utc=window.start_utc.isoformat(),
        window_end_utc=window.end_utc.isoformat(),
        subreddits=subreddits,
        provider_call=True,
        live_send=False,
    )
    store.clear_collected_data_for_run(run_id)
    store.upsert_run(
        run_id,
        "failed",
        summary.window_start_utc,
        summary.window_end_utc,
        provider_call=True,
    )

    discovery_posts = _discover_posts(
        client,
        store=store,
        run_id=run_id,
        subreddits=subreddits,
        search_terms=search_terms,
        listing_limit=listing_limit,
        summary=summary,
        raw_artifact_root=raw_artifact_root,
    )
    candidates = _filter_candidates(discovery_posts, discovery_window, summary)
    for batch in _batches(candidates[:max_detail_posts], MAX_TIKHUB_BATCH_SIZE):
        summary.detail_attempts += len(batch)
        post_ids = [_tikhub_post_id(post.post_id) for post in batch if post.post_id]
        try:
            payload = client.get_json(
                FETCH_POST_DETAILS_BATCH_LARGE,
                {
                    "post_ids": ",".join(post_ids),
                    "include_comment_id": "false",
                    "comment_id": "",
                    "need_format": "false",
                },
            )
        except Exception as exc:
            summary.issues.append(_provider_issue("detail", FETCH_POST_DETAILS_BATCH_LARGE, exc))
            continue

        comment_payloads: dict[str, Any] = {}
        for post_id in post_ids:
            try:
                comment_payloads[post_id] = client.get_json(
                    FETCH_POST_COMMENTS,
                    {
                        "post_id": post_id,
                        "sort_type": "CONFIDENCE",
                        "after": "",
                        "need_format": "false",
                    },
                )
            except Exception as exc:
                summary.issues.append(_provider_issue("comments", FETCH_POST_COMMENTS, exc))
        _ingest_detail_payload(
            store,
            run_id=run_id,
            payload=payload,
            comment_payloads=comment_payloads,
            window=discovery_window,
            summary=summary,
            raw_artifact_root=raw_artifact_root,
        )

    summary.analysis_items = store.count_for_run("analysis_results", run_id)
    summary.status = _derive_provider_status(summary)
    store.upsert_run(
        run_id,
        summary.status,
        summary.window_start_utc,
        summary.window_end_utc,
        provider_call=True,
    )
    return summary


def _discover_posts(
    client: Any,
    *,
    store: VocStore,
    run_id: str,
    subreddits: list[str],
    search_terms: list[str],
    listing_limit: int,
    summary: DailyCollectionSummary,
    raw_artifact_root: Path | str | None,
) -> list[DiscoveryPost]:
    posts: list[DiscoveryPost] = []
    for term in _brand_first_search_terms(search_terms):
        summary.listing_urls.append(FETCH_DYNAMIC_SEARCH + f"?query={term}")
        try:
            payload = client.get_json(FETCH_DYNAMIC_SEARCH, {"query": term, "sort": "new", "limit": listing_limit})
            source_method = "tikhub_dynamic_search_brand" if _is_brand_search_term(term) else "tikhub_dynamic_search"
            _persist_tikhub_discovery_raw(
                store,
                run_id=run_id,
                payload=payload,
                source_method=source_method,
                source_url=FETCH_DYNAMIC_SEARCH + f"?query={term}",
                raw_artifact_root=raw_artifact_root,
            )
            posts.extend(_extract_discovery_posts(payload, source_method=source_method))
        except Exception as exc:
            summary.issues.append(_provider_issue("search", FETCH_DYNAMIC_SEARCH, exc))
    for subreddit in subreddits:
        summary.listing_urls.append(FETCH_SUBREDDIT_FEED + f"?subreddit_name={subreddit}")
        try:
            payload = client.get_json(
                FETCH_SUBREDDIT_FEED,
                {
                    "subreddit_name": subreddit,
                    "sort": "NEW",
                    "after": "",
                    "need_format": "false",
                },
            )
            _persist_tikhub_discovery_raw(
                store,
                run_id=run_id,
                payload=payload,
                source_method="tikhub_subreddit_feed",
                source_url=FETCH_SUBREDDIT_FEED + f"?subreddit_name={subreddit}",
                raw_artifact_root=raw_artifact_root,
            )
            posts.extend(_extract_discovery_posts(payload, source_method="tikhub_subreddit_feed"))
        except Exception as exc:
            summary.issues.append(_provider_issue("listing", FETCH_SUBREDDIT_FEED, exc))
    summary.discovered_posts = len(posts)
    return posts


def _persist_tikhub_discovery_raw(
    store: VocStore,
    *,
    run_id: str,
    payload: Any,
    source_method: str,
    source_url: str,
    raw_artifact_root: Path | str | None,
) -> None:
    raw_text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    raw_bytes = raw_text.encode("utf-8")
    payload_digest = hashlib.sha256(raw_bytes).hexdigest()
    identity_digest = hashlib.sha256(
        json.dumps(
            [run_id, source_method, source_url, payload_digest],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    capture = RawCapture(
        raw_capture_id="raw_tikhub_discovery_" + identity_digest[:16],
        run_id=run_id,
        source_method=source_method,
        source_url=source_url,
        captured_at_utc=datetime.now(timezone.utc),
        auth_boundary="provider_api",
        raw_payload_hash="sha256:" + payload_digest,
        payload_format="json",
        browser_status="ok",
        secrets_written=False,
    )
    if raw_artifact_root is not None:
        persist_raw_artifact(raw_artifact_root, capture, raw_bytes)
    store.insert_raw_capture(capture)


def _brand_first_search_terms(search_terms: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for term in [*DEFAULT_BRAND_SEARCH_TERMS, *search_terms]:
        value = str(term or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _is_brand_search_term(term: str) -> bool:
    normalized = str(term or "").strip().strip('"').strip("'").lower()
    compact = re.sub(r"\s+", "", normalized)
    return "momcozy" in compact or normalized == "mom cozy"


def _provider_issue(stage: str, url: str, exc: Exception) -> dict[str, Any]:
    issue: dict[str, Any] = {
        "stage": stage,
        "url": url,
        "browser_status": "error",
        "blocked_reason": type(exc).__name__,
    }
    if isinstance(exc, HTTPError):
        issue["http_status"] = exc.code
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        if body:
            issue["response_preview"] = body[:240]
    return issue


def _filter_candidates(posts: list[DiscoveryPost], window: CollectionWindow, summary: DailyCollectionSummary) -> list[DiscoveryPost]:
    seen: set[str] = set()
    candidates: list[DiscoveryPost] = []
    for post in posts:
        if not post.created_at_utc or not window.contains_utc(post.created_at_utc):
            continue
        summary.window_posts += 1
        if not match_keywords(post.title).is_relevant and post.source_method != "tikhub_dynamic_search_brand":
            continue
        if post.post_id in seen:
            continue
        seen.add(post.post_id)
        candidates.append(post)
    summary.relevant_posts = len(candidates)
    return candidates


def _ingest_detail_payload(
    store: VocStore,
    *,
    run_id: str,
    payload: Any,
    comment_payloads: dict[str, Any] | None = None,
    window: CollectionWindow,
    summary: DailyCollectionSummary,
    raw_artifact_root: Path | str | None = None,
) -> None:
    adapter = BrowserJsonAdapter()
    combined_payload = {"detail": payload, "comments_by_post_id": comment_payloads or {}}
    raw_text = json.dumps(combined_payload, ensure_ascii=False, sort_keys=True)
    raw_capture_hash = "sha256:" + hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    capture_identity = hashlib.sha256(
        json.dumps([run_id, raw_capture_hash], separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    capture = RawCapture(
        raw_capture_id="raw_tikhub_" + capture_identity[:16],
        run_id=run_id,
        source_method="tikhub",
        source_url=FETCH_POST_DETAILS_BATCH_LARGE,
        captured_at_utc=datetime.now(timezone.utc),
        auth_boundary="provider_api",
        raw_payload_hash=raw_capture_hash,
        payload_format="json",
        browser_status="ok",
        secrets_written=False,
    )
    if raw_artifact_root is not None:
        persist_raw_artifact(raw_artifact_root, capture, raw_text.encode("utf-8"))
    store.insert_raw_capture(capture)
    parsed_count = 0
    for thread, comments in _parse_tikhub_app_detail_payload(
        payload,
        comment_payloads=comment_payloads or {},
        run_id=run_id,
        raw_capture_id=capture.raw_capture_id,
    ):
        if not window.contains_utc(thread.created_at_utc):
            continue
        store.upsert_thread(thread)
        _insert_thread_analysis(store, run_id, thread)
        summary.ingested_threads += 1
        summary.ingested_comments += len(comments)
        summary.coverage[thread.coverage_grade] = summary.coverage.get(thread.coverage_grade, 0) + 1
        for comment in comments:
            store.upsert_comment(comment)
            _insert_comment_analysis(store, run_id, comment)
        parsed_count += 1
    if parsed_count:
        return

    for thread_payload in _extract_thread_payloads(payload):
        try:
            parsed = adapter.parse_thread_payload(
                thread_payload,
                run_id=run_id,
                raw_capture_id=capture.raw_capture_id,
                source_url=FETCH_POST_DETAILS_BATCH_LARGE,
            )
        except (BrowserJsonBlockedError, ValueError) as exc:
            summary.issues.append({"stage": "detail_parse", "url": FETCH_POST_DETAILS_BATCH_LARGE, "browser_status": "error", "blocked_reason": type(exc).__name__})
            continue
        if not window.contains_utc(parsed.thread.created_at_utc):
            continue
        if parsed_count == 0:
            store.insert_raw_capture(capture)
        store.upsert_thread(parsed.thread)
        _insert_thread_analysis(store, run_id, parsed.thread)
        summary.ingested_threads += 1
        summary.ingested_comments += len(parsed.comments)
        summary.coverage[parsed.thread.coverage_grade] = summary.coverage.get(parsed.thread.coverage_grade, 0) + 1
        for comment in parsed.comments:
            store.upsert_comment(comment)
            _insert_comment_analysis(store, run_id, comment)
        parsed_count += 1
    if parsed_count == 0:
        summary.issues.append({"stage": "detail_parse", "url": FETCH_POST_DETAILS_BATCH_LARGE, "browser_status": "error", "blocked_reason": "no_reddit_thread_payload_found"})


def _extract_discovery_posts(
    payload: Any, source_method: str, *, dedupe: bool = True
) -> list[DiscoveryPost]:
    adapter = BrowserJsonAdapter()
    if isinstance(payload, dict):
        try:
            parsed = adapter.parse_listing_payload(payload)
            if parsed:
                posts = [
                    DiscoveryPost(
                        **{**post.__dict__, "source_method": source_method}
                    )
                    for post in parsed
                ]
                return _dedupe_discovery_posts(posts) if dedupe else posts
        except Exception:
            pass

    posts: list[DiscoveryPost] = []
    for row in _walk_discovery_rows(payload):
        title = row.get("title") or row.get("post_title") or row.get("postTitle") or row.get("name")
        url = row.get("permalink") or row.get("url") or row.get("post_url") or row.get("share_url")
        if not _looks_like_discovery_row(row):
            continue
        source_url = _canonical_url(str(url)) if url else ""
        subreddit, post_id = _post_identity_from_url(source_url) if source_url else (None, None)
        raw_post_id = row.get("id") or row.get("post_id") or post_id or ""
        post_id = _normalize_post_id(raw_post_id)
        if dedupe and (not title or not source_url or not post_id):
            continue
        subreddit_value = row.get("subreddit")
        if isinstance(subreddit_value, dict):
            subreddit_value = subreddit_value.get("name") or str(subreddit_value.get("prefixedName") or "").removeprefix("r/")
        created_at = _parse_time(
            row.get("created_utc")
            or row.get("created_at")
            or row.get("createdAt")
            or row.get("created")
            or row.get("created_time")
        )
        posts.append(
            DiscoveryPost(
                post_id=post_id,
                subreddit=str(subreddit_value or subreddit or ""),
                title=str(title or ""),
                source_url=source_url,
                created_at_utc=created_at,
                source_method=source_method,
                score=_int_or_none(row.get("score")),
                num_comments_reported=_int_or_none(row.get("num_comments") or row.get("comment_count") or row.get("commentCount")),
            )
        )
    return _dedupe_discovery_posts(posts) if dedupe else posts


class TikHubDiscoveryShapeError(ValueError):
    pass


_STRICT_DISCOVERY_CONTENT_TYPENAMES = frozenset(
    {"SearchPost", "SearchCrosspost"}
)
_STRICT_DISCOVERY_TELEMETRY_KEYS = frozenset(
    {
        "__typename",
        "actionInfo",
        "answers",
        "metaSearch",
        "post",
        "profile",
        "search",
        "subreddit",
    }
)
_STRICT_DISCOVERY_TELEMETRY_POST_KEYS = frozenset(
    {"id", "isNsfw", "isSpoiler", "title", "type"}
)
STRICT_SUBREDDIT_V3_CURSOR_PATH = (
    "data",
    "subredditV3",
    "elements",
    "pageInfo",
    "endCursor",
)
STRICT_SUBREDDIT_V3_CURSOR_SCHEMA_SHA256 = (
    "3bc27a141e675230d962942491bb87b8378a956142a75bfc79a631f10b479dbf"
)
_STRICT_SUBREDDIT_V3_ELEMENTS_KEYS = frozenset({"dist", "edges", "pageInfo"})
_STRICT_SUBREDDIT_V3_EDGE_KEYS = frozenset({"__typename", "node"})
_STRICT_SUBREDDIT_V3_NODE_KEYS = frozenset(
    {
        "__typename",
        "adPayload",
        "cells",
        "crosspostCells",
        "groupId",
        "groupRecommendationContext",
        "id",
        "payload",
    }
)
_STRICT_SUBREDDIT_METADATA_KEYS = frozenset(
    {
        "__typename",
        "authorName",
        "color",
        "createdAt",
        "detailsLink",
        "detailsString",
        "iconPath",
        "iconShape",
        "id",
        "isBrandAffiliate",
        "isJoinButtonShown",
        "isOverflowButtonHidden",
        "isRecommended",
        "joinSubredditId",
        "mediaDomain",
        "mediaPath",
        "modUserNoteLabel",
        "statusIndicators",
    }
)
_STRICT_SUBREDDIT_TITLE_KEYS = frozenset(
    {"__typename", "id", "isVisited", "title"}
)
_STRICT_SUBREDDIT_TITLE_WITH_THUMBNAIL_KEYS = frozenset(
    {
        "__typename",
        "id",
        "indicatorsCell",
        "previewTextCell",
        "thumbnail",
        "titleCell",
    }
)
_STRICT_SUBREDDIT_ACTION_KEYS = frozenset(
    {
        "__typename",
        "commentCount",
        "goldenUpvoteInfo",
        "id",
        "isModeratable",
        "isScoreHidden",
        "isShareButtonHidden",
        "isTranslatable",
        "isTranslated",
        "score",
        "shareCount",
        "voteState",
    }
)
_STRICT_SUBREDDIT_AUXILIARY_KEYS = {
    "FlairCell": frozenset({"__typename", "flair", "id"}),
    "PreviewTextCell": frozenset({"__typename", "id", "isRead", "text"}),
    "ImageCell": frozenset({"__typename", "id", "media"}),
    "GalleryCell": frozenset({"__typename", "height", "id", "pages"}),
    "EmptyContentCell": frozenset({"__typename"}),
    "CrossPostCell": frozenset({"__typename", "id"}),
    "MarginCell": frozenset({"__typename"}),
}
_STRICT_SUBREDDIT_REAL_ORGANIC_CELL_SEQUENCES = frozenset(
    {
        (
            "MetadataCell",
            "TitleCell",
            "CrossPostCell",
            "ActionCell",
            "MarginCell",
        ),
        (
            "MetadataCell",
            "TitleCell",
            "EmptyContentCell",
            "ActionCell",
            "MarginCell",
        ),
        (
            "MetadataCell",
            "TitleCell",
            "FlairCell",
            "EmptyContentCell",
            "ActionCell",
            "MarginCell",
        ),
        (
            "MetadataCell",
            "TitleCell",
            "FlairCell",
            "GalleryCell",
            "ActionCell",
            "MarginCell",
        ),
        (
            "MetadataCell",
            "TitleCell",
            "FlairCell",
            "ImageCell",
            "ActionCell",
            "MarginCell",
        ),
        (
            "MetadataCell",
            "TitleCell",
            "FlairCell",
            "PreviewTextCell",
            "ActionCell",
            "MarginCell",
        ),
        (
            "MetadataCell",
            "TitleCell",
            "GalleryCell",
            "ActionCell",
            "MarginCell",
        ),
        (
            "MetadataCell",
            "TitleCell",
            "ImageCell",
            "ActionCell",
            "MarginCell",
        ),
        (
            "MetadataCell",
            "TitleCell",
            "PreviewTextCell",
            "ActionCell",
            "MarginCell",
        ),
    }
)


def _extract_backfill_discovery_posts(
    payload: Any,
    source_method: str,
    *,
    dedupe: bool = False,
    lane_key: str | None = None,
) -> list[DiscoveryPost]:
    records = _extract_backfill_discovery_post_records(
        payload, source_method, lane_key=lane_key
    )
    posts = [post for _typename, post in records]
    return _dedupe_discovery_posts(posts) if dedupe else posts


def _extract_backfill_discovery_post_records(
    payload: Any, source_method: str, *, lane_key: str | None = None
) -> list[tuple[str, DiscoveryPost]]:
    if source_method == "tikhub_dynamic_search":
        return [
            (typename, _discovery_post_from_row(row, source_method))
            for typename, row in _strict_dynamic_search_post_records(payload)
        ]
    if source_method == "tikhub_subreddit_feed" and lane_key is not None:
        return _strict_subreddit_v3_post_records(payload, lane_key=lane_key)
    raise TikHubDiscoveryShapeError(
        "unreviewed TikHub backfill discovery payload shape"
    )


def _is_strict_subreddit_v3_terminal_empty(payload: Any) -> bool:
    try:
        subreddit_v3 = payload["data"]["subredditV3"]
    except (KeyError, TypeError):
        return False
    return bool(
        isinstance(subreddit_v3, dict)
        and "elements" in subreddit_v3
        and subreddit_v3["elements"] is None
    )


def _strict_subreddit_v3_post_records(
    payload: Any, *, lane_key: str
) -> list[tuple[str, DiscoveryPost]]:
    if not re.fullmatch(r"[A-Za-z0-9_]+", lane_key):
        raise TikHubDiscoveryShapeError("TikHub subreddit lane key is invalid")
    try:
        elements = payload["data"]["subredditV3"]["elements"]
    except (KeyError, TypeError):
        raise TikHubDiscoveryShapeError(
            "TikHub subredditV3 post container is missing"
        ) from None
    if elements is None:
        return []
    if (
        not isinstance(elements, dict)
        or set(elements) != _STRICT_SUBREDDIT_V3_ELEMENTS_KEYS
        or type(elements.get("dist")) is not int
        or not isinstance(elements.get("edges"), list)
        or not isinstance(elements.get("pageInfo"), dict)
        or set(elements["pageInfo"]) != {"endCursor"}
        or (
            elements["pageInfo"]["endCursor"] is not None
            and not isinstance(elements["pageInfo"]["endCursor"], str)
        )
    ):
        raise TikHubDiscoveryShapeError(
            "TikHub subredditV3 post container is invalid"
        )

    records: list[tuple[str, DiscoveryPost]] = []
    for edge in elements["edges"]:
        if (
            not isinstance(edge, dict)
            or set(edge) != _STRICT_SUBREDDIT_V3_EDGE_KEYS
            or edge.get("__typename") != "FeedElementEdge"
        ):
            raise TikHubDiscoveryShapeError("TikHub subredditV3 edge is invalid")
        node = edge.get("node")
        if (
            not isinstance(node, dict)
            or set(node) != _STRICT_SUBREDDIT_V3_NODE_KEYS
            or node.get("__typename") != "CellGroup"
            or not isinstance(node.get("cells"), list)
        ):
            raise TikHubDiscoveryShapeError("TikHub subredditV3 node is invalid")
        cells = node["cells"]
        typenames = [
            cell.get("__typename") if isinstance(cell, dict) else None
            for cell in cells
        ]
        if node.get("adPayload") is not None or "AdMetadataCell" in typenames:
            continue
        if typenames == ["SortCell"]:
            continue
        crosspost_cells = node.get("crosspostCells")
        real_cell_contract = crosspost_cells not in (None, [])
        if real_cell_contract:
            if (
                not isinstance(crosspost_cells, list)
                or len(crosspost_cells) != len(cells)
                or tuple(typenames)
                not in _STRICT_SUBREDDIT_REAL_ORGANIC_CELL_SEQUENCES
            ):
                raise TikHubDiscoveryShapeError(
                    "TikHub subredditV3 organic cell group is ambiguous"
                )
            for cell, mirror in zip(cells, crosspost_cells, strict=True):
                typename = cell.get("__typename") if isinstance(cell, dict) else None
                expected_mirror_keys = (
                    {"__typename", "innerPost"}
                    if typename == "CrossPostCell"
                    else {"__typename"}
                )
                if (
                    not isinstance(mirror, dict)
                    or set(mirror) != expected_mirror_keys
                    or mirror.get("__typename") != typename
                    or (
                        typename == "CrossPostCell"
                        and not isinstance(mirror.get("innerPost"), dict)
                    )
                ):
                    raise TikHubDiscoveryShapeError(
                        "TikHub subredditV3 crosspost mirror changed"
                    )
            for cell in cells:
                typename = cell.get("__typename") if isinstance(cell, dict) else None
                expected_keys = _STRICT_SUBREDDIT_AUXILIARY_KEYS.get(typename)
                if expected_keys is not None and set(cell) != expected_keys:
                    raise TikHubDiscoveryShapeError(
                        "TikHub subredditV3 auxiliary cell changed"
                    )

        fullname = _decode_subreddit_v3_id(node.get("id"))
        if not re.fullmatch(r"t3_[a-z0-9]+", fullname):
            raise TikHubDiscoveryShapeError(
                "TikHub subredditV3 post identity is invalid"
            )
        metadata_cells = [
            cell
            for cell in cells
            if isinstance(cell, dict) and cell.get("__typename") == "MetadataCell"
        ]
        title_cells = [
            cell
            for cell in cells
            if isinstance(cell, dict)
            and cell.get("__typename") in {"TitleCell", "TitleWithThumbnailCell"}
        ]
        action_cells = [
            cell
            for cell in cells
            if isinstance(cell, dict) and cell.get("__typename") == "ActionCell"
        ]
        if (
            len(metadata_cells) != 1
            or len(title_cells) != 1
            or len(action_cells) != 1
            or (not real_cell_contract and len(cells) != 3)
        ):
            raise TikHubDiscoveryShapeError(
                "TikHub subredditV3 organic cell group is ambiguous"
            )

        metadata = metadata_cells[0]
        title_wrapper = title_cells[0]
        action = action_cells[0]
        if set(metadata) != _STRICT_SUBREDDIT_METADATA_KEYS:
            raise TikHubDiscoveryShapeError(
                "TikHub subredditV3 metadata cell changed"
            )
        if title_wrapper.get("__typename") == "TitleWithThumbnailCell":
            if set(title_wrapper) != _STRICT_SUBREDDIT_TITLE_WITH_THUMBNAIL_KEYS:
                raise TikHubDiscoveryShapeError(
                    "TikHub subredditV3 title thumbnail cell changed"
                )
            title = title_wrapper.get("titleCell")
        else:
            title = title_wrapper
        if not isinstance(title, dict) or set(title) != _STRICT_SUBREDDIT_TITLE_KEYS:
            raise TikHubDiscoveryShapeError("TikHub subredditV3 title cell changed")
        if set(action) != _STRICT_SUBREDDIT_ACTION_KEYS:
            raise TikHubDiscoveryShapeError("TikHub subredditV3 action cell changed")

        relevant_cells = (metadata, title_wrapper, title, action)
        if any(
            fullname not in _decode_subreddit_v3_id(cell.get("id"))
            for cell in relevant_cells
        ):
            raise TikHubDiscoveryShapeError(
                "TikHub subredditV3 cell identity does not match post"
            )
        created_at = metadata.get("createdAt")
        post_title = title.get("title")
        if (
            not isinstance(created_at, str)
            or _parse_time(created_at) is None
            or not isinstance(post_title, str)
            or not post_title.strip()
            or type(action.get("score")) not in {int, type(None)}
            or type(action.get("commentCount")) not in {int, type(None)}
        ):
            raise TikHubDiscoveryShapeError(
                "TikHub subredditV3 organic post values are invalid"
            )
        post_id = fullname.removeprefix("t3_")
        row = {
            "id": fullname,
            "createdAt": created_at,
            "postTitle": post_title,
            "url": f"https://www.reddit.com/r/{lane_key}/comments/{post_id}/",
            "subreddit": {"name": lane_key},
            "score": action.get("score"),
            "commentCount": action.get("commentCount"),
        }
        records.append(
            ("SubredditV3Post", _discovery_post_from_row(row, "tikhub_subreddit_feed"))
        )
    return records


def _decode_subreddit_v3_id(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise TikHubDiscoveryShapeError("TikHub subredditV3 identity is missing")
    try:
        decoded = base64.b64decode(value, validate=True).decode("ascii")
    except (binascii.Error, UnicodeDecodeError):
        raise TikHubDiscoveryShapeError(
            "TikHub subredditV3 identity is not reviewed base64"
        ) from None
    return decoded


def _strict_dynamic_search_post_records(
    payload: Any,
) -> list[tuple[str, dict[str, Any]]]:
    try:
        main = payload["data"]["search"]["dynamic"]["components"]["main"]
    except (KeyError, TypeError):
        raise TikHubDiscoveryShapeError(
            "TikHub dynamic search post container is missing"
        ) from None
    if not isinstance(main, dict) or not isinstance(main.get("pageInfo"), dict):
        raise TikHubDiscoveryShapeError(
            "TikHub dynamic search post container is invalid"
        )
    edges = main.get("edges")
    if not isinstance(edges, list):
        raise TikHubDiscoveryShapeError(
            "TikHub dynamic search edges are missing"
        )

    wrappers: list[dict[str, Any]] = []
    records: list[tuple[str, dict[str, Any]]] = []
    for edge in edges:
        if not isinstance(edge, dict):
            raise TikHubDiscoveryShapeError(
                "TikHub dynamic search edge is invalid"
            )
        node = edge.get("node")
        children = node.get("children") if isinstance(node, dict) else None
        if not isinstance(children, list):
            raise TikHubDiscoveryShapeError(
                "TikHub dynamic search children are missing"
            )
        for child in children:
            if not isinstance(child, dict):
                raise TikHubDiscoveryShapeError(
                    "TikHub dynamic search child is invalid"
                )
            typename = child.get("__typename")
            if typename in _STRICT_DISCOVERY_CONTENT_TYPENAMES:
                post = child.get("post")
                if not isinstance(post, dict):
                    raise TikHubDiscoveryShapeError(
                        f"TikHub {typename} payload is invalid"
                    )
                wrappers.append(child)
                records.append((str(typename), post))
            elif isinstance(child.get("post"), dict):
                raise TikHubDiscoveryShapeError(
                    "TikHub dynamic search post wrapper is ambiguous"
                )

    allowed_wrapper_ids = {id(value) for value in wrappers}
    for wrapper in wrappers:
        nested_post_wrappers: list[dict[str, Any]] = []
        for key, value in wrapper.items():
            if key != "post":
                _collect_post_wrappers(value, nested_post_wrappers)
        allowed_wrapper_ids.update(
            id(value)
            for value in nested_post_wrappers
            if _is_reviewed_discovery_telemetry_wrapper(value)
        )
        if wrapper.get("__typename") == "SearchCrosspost":
            post = wrapper["post"]
            crosspost_root = post.get("crosspostRoot")
            if (
                isinstance(crosspost_root, dict)
                and isinstance(crosspost_root.get("post"), dict)
            ):
                if set(crosspost_root) != {"post"}:
                    raise TikHubDiscoveryShapeError(
                        "TikHub dynamic search post container is ambiguous"
                    )
                allowed_wrapper_ids.add(id(crosspost_root))

    all_post_wrappers: list[dict[str, Any]] = []
    _collect_post_wrappers(payload, all_post_wrappers)
    if {id(value) for value in all_post_wrappers} != allowed_wrapper_ids:
        raise TikHubDiscoveryShapeError(
            "TikHub dynamic search post container is ambiguous"
        )
    return records


def _is_reviewed_discovery_telemetry_wrapper(value: dict[str, Any]) -> bool:
    post = value.get("post")
    return bool(
        value.get("__typename") == "SearchTelemetryTrackingContext"
        and set(value) == _STRICT_DISCOVERY_TELEMETRY_KEYS
        and isinstance(post, dict)
        and set(post) == _STRICT_DISCOVERY_TELEMETRY_POST_KEYS
    )


def _collect_post_wrappers(value: Any, output: list[dict[str, Any]]) -> None:
    if isinstance(value, dict):
        if isinstance(value.get("post"), dict):
            output.append(value)
        for child in value.values():
            _collect_post_wrappers(child, output)
    elif isinstance(value, list):
        for child in value:
            _collect_post_wrappers(child, output)


def _discovery_post_from_row(
    row: dict[str, Any], source_method: str
) -> DiscoveryPost:
    title = (
        row.get("title")
        or row.get("post_title")
        or row.get("postTitle")
        or row.get("name")
    )
    url = (
        row.get("permalink")
        or row.get("url")
        or row.get("post_url")
        or row.get("share_url")
    )
    source_url = _canonical_url(str(url)) if url else ""
    subreddit, post_id = (
        _post_identity_from_url(source_url) if source_url else (None, None)
    )
    raw_post_id = row.get("id") or row.get("post_id") or post_id or ""
    post_id = _normalize_post_id(raw_post_id)
    subreddit_value = row.get("subreddit")
    if isinstance(subreddit_value, dict):
        subreddit_value = subreddit_value.get("name") or str(
            subreddit_value.get("prefixedName") or ""
        ).removeprefix("r/")
    created_at = _parse_time(
        row.get("created_utc")
        or row.get("created_at")
        or row.get("createdAt")
        or row.get("created")
        or row.get("created_time")
    )
    return DiscoveryPost(
        post_id=post_id,
        subreddit=str(subreddit_value or subreddit or ""),
        title=str(title or ""),
        source_url=source_url,
        created_at_utc=created_at,
        source_method=source_method,
        score=_int_or_none(row.get("score")),
        num_comments_reported=_int_or_none(
            row.get("num_comments")
            or row.get("comment_count")
            or row.get("commentCount")
        ),
    )


def _dedupe_discovery_posts(posts: list[DiscoveryPost]) -> list[DiscoveryPost]:
    deduped: dict[str, DiscoveryPost] = {}
    for post in posts:
        deduped.setdefault(post.post_id, post)
    return list(deduped.values())


def _walk_discovery_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        wrapped_post = value.get("post")
        if isinstance(wrapped_post, dict):
            rows = [wrapped_post]
            for key, child in value.items():
                if key != "post":
                    rows.extend(_walk_discovery_rows(child))
            return rows
        rows = [value]
        for child in value.values():
            rows.extend(_walk_discovery_rows(child))
        return rows
    if isinstance(value, list):
        rows: list[dict[str, Any]] = []
        for child in value:
            rows.extend(_walk_discovery_rows(child))
        return rows
    return []


def _looks_like_discovery_row(row: dict[str, Any]) -> bool:
    identity_or_url_keys = {
        "id",
        "post_id",
        "permalink",
        "url",
        "post_url",
        "share_url",
    }
    title_keys = {"title", "post_title", "postTitle"}
    created_keys = {
        "created_utc",
        "created_at",
        "createdAt",
        "created",
        "created_time",
    }
    return bool(
        identity_or_url_keys.intersection(row)
        or (
            title_keys.intersection(row)
            and created_keys.intersection(row)
        )
    )


def _normalize_post_id(value: Any) -> str:
    text = str(value or "")
    return text[3:] if text.startswith("t3_") else text


def _tikhub_post_id(value: Any) -> str:
    text = str(value or "")
    return text if text.startswith("t3_") else f"t3_{text}"


def _parse_tikhub_app_detail_payload(
    payload: Any,
    *,
    comment_payloads: dict[str, Any],
    run_id: str,
    raw_capture_id: str,
) -> list[tuple[RedditThread, list[RedditComment]]]:
    parsed: list[tuple[RedditThread, list[RedditComment]]] = []
    for post_info in _extract_tikhub_posts_info(payload):
        full_post_id = str(post_info.get("id") or "")
        post_id = _normalize_post_id(full_post_id)
        if not post_id:
            continue

        source_url = _canonical_url(post_info.get("permalink") or post_info.get("url"))
        subreddit = _subreddit_name(post_info.get("subreddit"))
        if not subreddit:
            subreddit, _ = _post_identity_from_url(source_url)
        title = str(post_info.get("postTitle") or post_info.get("title") or "")
        selftext = _content_markdown(post_info.get("content"))
        created_at = _parse_time(post_info.get("createdAt") or post_info.get("created_at") or post_info.get("created"))
        if not title or created_at is None:
            continue

        reported_count = _int_or_none(post_info.get("commentCount") or post_info.get("num_comments"))
        submitter_name = _author_name(post_info.get("authorInfo")) or str(post_info.get("author") or "")
        comment_payload = comment_payloads.get(full_post_id) or comment_payloads.get(_tikhub_post_id(post_id)) or comment_payloads.get(post_id)
        comments, more_node_count = _parse_tikhub_comment_payload(
            comment_payload,
            post_id=post_id,
            run_id=run_id,
            raw_capture_id=raw_capture_id,
            submitter_name=submitter_name,
        )
        post_analysis = analyze_text(f"{title}\n{selftext}")
        thread = RedditThread(
            post_id=post_id,
            run_id=run_id,
            raw_capture_id=raw_capture_id,
            subreddit=str(subreddit or ""),
            title=title,
            selftext=selftext,
            source_url=source_url,
            created_at_utc=created_at,
            score=_int_or_none(post_info.get("score")),
            num_comments_reported=reported_count,
            parsed_comment_count=len(comments),
            more_node_count=more_node_count,
            coverage_grade=BrowserJsonAdapter._coverage_grade(
                parsed_comment_count=len(comments),
                more_node_count=more_node_count,
                reported_count=reported_count,
            ),
            matched_keywords=post_analysis.keyword_match.matched_terms,
            media_urls=_extract_media_urls(post_info),
            author_hash=_hash_author(submitter_name),
        )
        parsed.append((thread, comments))
    return parsed


def _extract_tikhub_posts_info(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        posts_info = value.get("postsInfoByIds")
        if isinstance(posts_info, list):
            found.extend([item for item in posts_info if isinstance(item, dict)])
        for child in value.values():
            found.extend(_extract_tikhub_posts_info(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_extract_tikhub_posts_info(child))
    return found


def _parse_tikhub_comment_payload(
    payload: Any,
    *,
    post_id: str,
    run_id: str,
    raw_capture_id: str,
    submitter_name: str,
) -> tuple[list[RedditComment], int]:
    if not payload:
        return [], 0
    post_info = _extract_tikhub_comment_post_info(payload)
    if not post_info:
        return [], 0
    forest = post_info.get("commentForest") if isinstance(post_info, dict) else None
    trees = forest.get("trees") if isinstance(forest, dict) else None
    if not isinstance(trees, list):
        return [], 0

    comments: list[RedditComment] = []
    more_node_count = 0
    for tree in trees:
        tree_comments, tree_more = _parse_tikhub_comment_tree(
            tree,
            post_id=post_id,
            run_id=run_id,
            raw_capture_id=raw_capture_id,
            submitter_name=submitter_name,
            fallback_depth=0,
        )
        comments.extend(tree_comments)
        more_node_count += tree_more
    return comments, more_node_count


def _parse_strict_tikhub_comment_payload(
    payload: Any,
    *,
    post_id: str,
    run_id: str,
    raw_capture_id: str,
    submitter_name: str,
) -> tuple[list[RedditComment], int]:
    """Parse backfill comment raw only after its response identity/schema is proven."""
    post_info = _extract_tikhub_comment_post_info(payload)
    if not isinstance(post_info, dict):
        raise ValueError("TikHub comment postInfoById is missing")
    if _normalize_post_id(post_info.get("id")) != post_id:
        raise ValueError("TikHub comment response post ID does not match")
    forest = post_info.get("commentForest")
    if not isinstance(forest, dict) or not isinstance(forest.get("trees"), list):
        raise ValueError("TikHub comment forest is missing or invalid")
    try:
        return _parse_tikhub_comment_payload(
            payload,
            post_id=post_id,
            run_id=run_id,
            raw_capture_id=raw_capture_id,
            submitter_name=submitter_name,
        )
    except Exception:
        raise ValueError("TikHub comment payload parser failed") from None


def extract_tikhub_more_cursors(payload: Any) -> tuple[str, ...]:
    """Return deduplicated `more.cursor` values in their response order.

    TikHub documents reply retrieval separately from post-comment pagination.
    This utility only extracts cursors already present in archived comment JSON;
    it does not issue a request or infer a reply response schema.
    """

    cursors: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            more = value.get("more")
            if isinstance(more, dict):
                cursor = more.get("cursor")
                if isinstance(cursor, str) and cursor and cursor not in cursors:
                    cursors.append(cursor)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    return tuple(cursors)


def _extract_tikhub_comment_post_info(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        post_info = value.get("postInfoById")
        if isinstance(post_info, dict):
            return post_info
        for child in value.values():
            found = _extract_tikhub_comment_post_info(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _extract_tikhub_comment_post_info(child)
            if found:
                return found
    return None


def _parse_tikhub_comment_tree(
    tree: Any,
    *,
    post_id: str,
    run_id: str,
    raw_capture_id: str,
    submitter_name: str,
    fallback_depth: int,
) -> tuple[list[RedditComment], int]:
    if not isinstance(tree, dict):
        return [], 0

    comments: list[RedditComment] = []
    more_node_count = 1 if tree.get("more") else 0
    node = tree.get("node") if isinstance(tree.get("node"), dict) else tree
    if isinstance(node, dict) and (node.get("__typename") == "MoreComments" or node.get("type") == "more"):
        more_node_count += 1

    if isinstance(node, dict) and (node.get("__typename") == "Comment" or ("id" in node and "content" in node)):
        comment_id = str(node.get("id") or "")
        if comment_id and not comment_id.startswith("t1_"):
            comment_id = f"t1_{comment_id}"
        created_at = _parse_time(node.get("createdAt") or node.get("created_at") or node.get("created"))
        if comment_id and created_at is not None:
            body = _content_markdown(node.get("content")) or str(node.get("body") or node.get("text") or "")
            deleted_or_removed = bool(node.get("isRemoved") or node.get("isAdminTakedown")) or body in {"[deleted]", "[removed]"}
            if not body and deleted_or_removed:
                body = "[removed]"
            author_name = _author_name(node.get("authorInfo")) or str(node.get("author") or "")
            analysis = analyze_text(body)
            depth = _int_or_none(tree.get("depth"))
            comments.append(
                RedditComment(
                    comment_id=comment_id,
                    post_id=post_id,
                    run_id=run_id,
                    raw_capture_id=raw_capture_id,
                    body=body,
                    created_at_utc=created_at,
                    parent_id=tree.get("parentId") or node.get("parentId"),
                    score=_int_or_none(node.get("score")),
                    depth=depth if depth is not None else fallback_depth,
                    is_submitter=(author_name == submitter_name) if author_name and submitter_name else None,
                    matched_keywords=analysis.keyword_match.matched_terms,
                    author_hash=None if deleted_or_removed else _hash_author(author_name),
                    deleted_or_removed=deleted_or_removed,
                )
            )

    for child_key in ("children", "replies", "trees"):
        child_value = tree.get(child_key)
        if child_value is None and isinstance(node, dict):
            child_value = node.get(child_key)
        child_trees = child_value.get("trees") if isinstance(child_value, dict) else child_value
        if isinstance(child_trees, list):
            for child in child_trees:
                child_comments, child_more = _parse_tikhub_comment_tree(
                    child,
                    post_id=post_id,
                    run_id=run_id,
                    raw_capture_id=raw_capture_id,
                    submitter_name=submitter_name,
                    fallback_depth=fallback_depth + 1,
                )
                comments.extend(child_comments)
                more_node_count += child_more
    return comments, more_node_count


def _subreddit_name(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("name") or str(value.get("prefixedName") or "").removeprefix("r/")
    if value:
        return str(value)
    return None


def _author_name(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("name")
    if value:
        return str(value)
    return None


def _content_markdown(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("markdown") or value.get("text") or value.get("plainText") or "")
    if value is None:
        return ""
    return str(value)


def _extract_thread_payloads(payload: Any) -> list[list[Any]]:
    found: list[list[Any]] = []
    if _looks_like_thread_payload(payload):
        return [payload]
    if isinstance(payload, dict):
        for value in payload.values():
            found.extend(_extract_thread_payloads(value))
    elif isinstance(payload, list):
        for value in payload:
            found.extend(_extract_thread_payloads(value))
    return found


def _looks_like_thread_payload(value: Any) -> bool:
    if not isinstance(value, list) or len(value) < 2:
        return False
    try:
        first_children = value[0].get("data", {}).get("children", [])
        return bool(first_children and first_children[0].get("kind") == "t3")
    except AttributeError:
        return False


def _walk_dicts(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        rows = [value]
        for child in value.values():
            rows.extend(_walk_dicts(child))
        return rows
    if isinstance(value, list):
        rows: list[dict[str, Any]] = []
        for child in value:
            rows.extend(_walk_dicts(child))
        return rows
    return []


def _parse_time(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            return datetime.fromtimestamp(float(text), tz=timezone.utc)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _batches(posts: list[DiscoveryPost], size: int) -> list[list[DiscoveryPost]]:
    return [posts[idx : idx + size] for idx in range(0, len(posts), size)]


def _insert_thread_analysis(store: VocStore, run_id: str, thread: RedditThread) -> None:
    analysis = analyze_text(f"{thread.title}\n{thread.selftext}")
    store.insert_analysis(
        analysis_id=f"analysis_post_{thread.post_id}",
        run_id=run_id,
        source_type="post",
        source_id=thread.post_id,
        sentiment_label=analysis.sentiment_label,
        sentiment_score=analysis.sentiment_score,
        topic=analysis.topic,
        severity=analysis.severity,
        confidence=analysis.confidence,
        pain_points=analysis.pain_points,
    )


def _insert_comment_analysis(store: VocStore, run_id: str, comment: RedditComment) -> None:
    analysis = analyze_text(comment.body)
    store.insert_analysis(
        analysis_id=f"analysis_comment_{comment.comment_id}",
        run_id=run_id,
        source_type="comment",
        source_id=comment.comment_id,
        sentiment_label=analysis.sentiment_label,
        sentiment_score=analysis.sentiment_score,
        topic=analysis.topic,
        severity=analysis.severity,
        confidence=analysis.confidence,
        pain_points=analysis.pain_points,
    )


def _derive_provider_status(summary: DailyCollectionSummary) -> str:
    if summary.ingested_threads == 0:
        if summary.relevant_posts == 0 and summary.discovered_posts > 0:
            return "empty"
        return "failed" if summary.issues else "empty"
    if summary.issues or any(grade != "full" for grade in summary.coverage):
        return "partial"
    return "success"
