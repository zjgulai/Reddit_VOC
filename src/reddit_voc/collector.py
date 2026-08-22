from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from .adapters import BrowserJsonAdapter, BrowserJsonBlockedError, DiscoveryPost
from .analyzer import analyze_text, analyze_batch_with_deepseek, DeepSeekAnalysisItem
from .browser_runner import BrowserJsonCaptureResult, build_browser_json_urls
from .keywords import match_keywords
from .models import DailyCollectionSummary
from .raw_artifacts import persist_raw_artifact
from .search_config import DEFAULT_DAILY_SUBREDDITS
from .storage import VocStore
from .time_window import CollectionWindow, daily_window, rolling_window


class JsonCaptureRunner(Protocol):
    def capture_json_url(self, url: str) -> BrowserJsonCaptureResult:
        ...


def collect_daily_reddit(
    store: VocStore,
    *,
    run_id: str,
    runner: JsonCaptureRunner,
    subreddits: list[str] | None = None,
    anchor_utc: datetime | None = None,
    window_end_utc: datetime | None = None,
    rolling_window_hours: int = 24,
    run_hour: int = 7,
    listing_limit: int = 100,
    max_detail_posts: int = 50,
    new_post_overlap_hours: int = 2,
    raw_artifact_root: Path | str | None = None,
) -> DailyCollectionSummary:
    selected_subreddits = list(subreddits or DEFAULT_DAILY_SUBREDDITS)
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
        subreddits=selected_subreddits,
    )
    store.upsert_run(run_id, "failed", summary.window_start_utc, summary.window_end_utc)

    adapter = BrowserJsonAdapter()
    seen_posts: set[str] = set()
    candidates: list[DiscoveryPost] = []

    for subreddit in selected_subreddits:
        listing_url = build_listing_url(subreddit, limit=listing_limit)
        summary.listing_urls.append(listing_url)
        capture_result = runner.capture_json_url(listing_url)
        if not capture_result.is_usable_json:
            summary.issues.append(
                {
                    "stage": "listing",
                    "url": listing_url,
                    "browser_status": capture_result.browser_status,
                    "blocked_reason": capture_result.blocked_reason or "",
                }
            )
            continue
        listing_capture = adapter.build_raw_capture(
            capture_result.raw_text,
            run_id=run_id,
            source_url=listing_url,
            captured_at_utc=datetime.now(timezone.utc),
            browser_status=capture_result.browser_status,
        )
        if raw_artifact_root is not None:
            persist_raw_artifact(
                raw_artifact_root,
                listing_capture,
                capture_result.raw_text.encode("utf-8"),
            )
        store.insert_raw_capture(listing_capture)
        try:
            posts = adapter.parse_listing_text(capture_result.raw_text)
        except (BrowserJsonBlockedError, ValueError) as exc:
            summary.issues.append(
                {
                    "stage": "listing_parse",
                    "url": listing_url,
                    "browser_status": "error",
                    "blocked_reason": type(exc).__name__,
                }
            )
            continue
        summary.discovered_posts += len(posts)
        for post in posts:
            if not _is_in_window(post, discovery_window):
                continue
            summary.window_posts += 1
            if not _is_relevant_discovery(post):
                continue
            if post.post_id in seen_posts:
                continue
            seen_posts.add(post.post_id)
            candidates.append(post)

    summary.relevant_posts = len(candidates)

    for post in candidates[:max_detail_posts]:
        detail_url = build_browser_json_urls([post.source_url])[0]
        summary.detail_attempts += 1
        capture_result = runner.capture_json_url(detail_url)
        if not capture_result.is_usable_json:
            summary.issues.append(
                {
                    "stage": "detail",
                    "url": detail_url,
                    "browser_status": capture_result.browser_status,
                    "blocked_reason": capture_result.blocked_reason or "",
                }
            )
            continue

        capture = adapter.build_raw_capture(
            capture_result.raw_text,
            run_id=run_id,
            source_url=detail_url,
            captured_at_utc=datetime.now(timezone.utc),
            browser_status=capture_result.browser_status,
        )
        if raw_artifact_root is not None:
            persist_raw_artifact(
                raw_artifact_root,
                capture,
                capture_result.raw_text.encode("utf-8"),
            )
        store.insert_raw_capture(capture)
        try:
            parsed = adapter.parse_thread_text(
                capture_result.raw_text,
                run_id=run_id,
                raw_capture_id=capture.raw_capture_id,
                source_url=capture.source_url,
            )
        except (BrowserJsonBlockedError, ValueError) as exc:
            summary.issues.append(
                {
                    "stage": "detail_parse",
                    "url": detail_url,
                    "browser_status": "error",
                    "blocked_reason": type(exc).__name__,
                }
            )
            continue

        if not discovery_window.contains_utc(parsed.thread.created_at_utc):
            summary.issues.append(
                {
                    "stage": "detail_window",
                    "url": detail_url,
                    "browser_status": "skipped",
                    "blocked_reason": "post_created_outside_window",
                }
            )
            continue

        store.upsert_thread(parsed.thread)
        _insert_thread_analysis(store, run_id, parsed.thread.post_id, parsed.thread.title, parsed.thread.selftext)
        summary.ingested_threads += 1
        summary.coverage[parsed.thread.coverage_grade] = summary.coverage.get(parsed.thread.coverage_grade, 0) + 1

        for comment in parsed.comments:
            store.upsert_comment(comment)
            _insert_comment_analysis(store, run_id, comment.comment_id, comment.body)
            summary.ingested_comments += 1

    summary.analysis_items = store.count_for_run("analysis_results", run_id)
    summary.status = _derive_status(summary)
    store.upsert_run(run_id, summary.status, summary.window_start_utc, summary.window_end_utc)
    return summary


def build_listing_url(subreddit: str, *, limit: int = 100) -> str:
    safe = subreddit.strip().strip("/")
    return f"https://www.reddit.com/r/{safe}/new/.json?limit={max(1, min(limit, 100))}"


def _is_in_window(post: DiscoveryPost, window: CollectionWindow) -> bool:
    return bool(post.created_at_utc and window.contains_utc(post.created_at_utc))


def _is_relevant_discovery(post: DiscoveryPost) -> bool:
    return match_keywords(post.title).is_relevant


def _insert_thread_analysis(store: VocStore, run_id: str, post_id: str, title: str, selftext: str) -> None:
    analysis = analyze_text(f"{title}\n{selftext}")
    store.insert_analysis(
        analysis_id=f"analysis_post_{post_id}",
        run_id=run_id,
        source_type="post",
        source_id=post_id,
        sentiment_label=analysis.sentiment_label,
        sentiment_score=analysis.sentiment_score,
        topic=analysis.topic,
        severity=analysis.severity,
        confidence=analysis.confidence,
        pain_points=analysis.pain_points,
    )


def _insert_comment_analysis(store: VocStore, run_id: str, comment_id: str, body: str) -> None:
    analysis = analyze_text(body)
    store.insert_analysis(
        analysis_id=f"analysis_comment_{comment_id}",
        run_id=run_id,
        source_type="comment",
        source_id=comment_id,
        sentiment_label=analysis.sentiment_label,
        sentiment_score=analysis.sentiment_score,
        topic=analysis.topic,
        severity=analysis.severity,
        confidence=analysis.confidence,
        pain_points=analysis.pain_points,
    )


def _derive_status(summary: DailyCollectionSummary) -> str:
    if summary.ingested_threads == 0:
        if summary.relevant_posts == 0 and not summary.issues:
            return "empty"
        if summary.relevant_posts == 0 and summary.discovered_posts > 0:
            return "empty"
        return "failed"
    if summary.issues or any(grade != "full" for grade in summary.coverage):
        return "partial"
    return "success"


def _reanalyze_run_with_deepseek(
    store: VocStore,
    run_id: str,
    *,
    authorize_provider_call: bool = False,
) -> int:
    import os
    if not authorize_provider_call:
        return 0
    if not os.getenv("DEEPSEEK_API_KEY", "").strip():
        return 0

    posts = store.fetch_threads_for_run(run_id)
    comments = store.fetch_comments_for_run(run_id)

    items: list[DeepSeekAnalysisItem] = []
    for post in posts:
        post_id = str(post.get("post_id", ""))
        title = str(post.get("title") or "")
        selftext = str(post.get("selftext") or "")
        items.append(DeepSeekAnalysisItem(
            item_id=f"post:{post_id}",
            text=f"{title}\n{selftext}",
        ))
    for comment in comments:
        comment_id = str(comment.get("comment_id", ""))
        body = str(comment.get("body") or "")
        items.append(DeepSeekAnalysisItem(
            item_id=f"comment:{comment_id}",
            text=body,
        ))

    if not items:
        return 0

    _BATCH_SIZE = 20
    updated = 0
    for start in range(0, len(items), _BATCH_SIZE):
        batch = items[start : start + _BATCH_SIZE]
        results = analyze_batch_with_deepseek(batch)
        for result in results:
            parts = result.item_id.split(":", 1)
            if len(parts) != 2:
                continue
            source_type, source_id = parts
            if source_type not in ("post", "comment"):
                continue
            analysis_id = f"analysis_{source_type}_{source_id}"
            store.insert_analysis(
                analysis_id=analysis_id,
                run_id=run_id,
                source_type=source_type,
                source_id=source_id,
                sentiment_label=result.sentiment_label,
                sentiment_score=result.sentiment_score,
                topic=result.topic,
                severity=result.severity,
                confidence=0.9,
                pain_points=result.pain_points,
            )
            updated += 1
    return updated
