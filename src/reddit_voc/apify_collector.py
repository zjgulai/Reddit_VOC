"""Apify-based enterprise Reddit VOC collector adapter for Echo-Agent."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .analyzer import analyze_text
from .keywords import match_keywords
from .models import DailyCollectionSummary, RawCapture, RedditComment, RedditThread
from .raw_artifacts import persist_raw_artifact
from .storage import VocStore
from .time_window import CollectionWindow, daily_window, rolling_window

logger = logging.getLogger("reddit_voc.apify")

DEFAULT_APIFY_ACTOR = "trudax~reddit-scraper-lite"


class ApifyRedditClient:
    """Client for executing Reddit scraper actors on the Apify platform."""

    def __init__(self, api_key: str | None = None, timeout_seconds: int = 60) -> None:
        self.api_key = api_key or os.getenv("APIFY_API_KEY", "").strip()
        self.timeout_seconds = timeout_seconds
        if not self.api_key:
            raise ValueError("APIFY_API_KEY is required")

    def run_actor_sync(
        self,
        actor_id: str = DEFAULT_APIFY_ACTOR,
        input_data: dict[str, Any] | None = None,
        max_wait_seconds: int = 900,
    ) -> list[dict[str, Any]]:
        """Trigger an Apify actor, poll for completion, and return all dataset items."""
        run_url = f"https://api.apify.com/v2/acts/{actor_id}/runs?token={self.api_key}"
        payload = json.dumps(input_data or {}).encode("utf-8")
        req = urllib.request.Request(
            run_url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))["data"]
            run_id = data["id"]
            dataset_id = data["defaultDatasetId"]

        logger.info("Apify actor run started. Run ID: %s, Dataset ID: %s", run_id, dataset_id)

        # Poll status
        status_url = f"https://api.apify.com/v2/actor-runs/{run_id}?token={self.api_key}"
        deadline = time.time() + max_wait_seconds
        status = "RUNNING"
        while time.time() < deadline:
            time.sleep(3)
            with urllib.request.urlopen(urllib.request.Request(status_url), timeout=10) as resp:
                run_status = json.loads(resp.read().decode("utf-8"))["data"]
                status = run_status["status"]
                if status not in ("RUNNING", "READY"):
                    break

        if status not in ("SUCCEEDED", "RUNNING"):
            # FAILED/ABORTED are terminal failures; RUNNING past deadline still has
            # a usable partial dataset — log and proceed with what was scraped.
            if status == "RUNNING":
                logger.warning("Apify run %s still RUNNING past deadline; using partial dataset", run_id)
            else:
                raise RuntimeError(f"Apify run {run_id} terminated with status: {status}")

        items_url = f"https://api.apify.com/v2/datasets/{dataset_id}/items?token={self.api_key}&clean=true"
        with urllib.request.urlopen(urllib.request.Request(items_url), timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))


def collect_daily_apify(
    store: VocStore,
    *,
    run_id: str,
    client: ApifyRedditClient | None = None,
    subreddits: Sequence[str] = ("ExclusivelyPumping", "breastfeeding", "WorkingMoms", "beyondthebump"),
    search_terms: Sequence[str] = ("Momcozy", "wearable pump"),
    max_items_per_query: int = 30,
    max_comments_per_post: int = 20,
    raw_artifact_root: Path | str | None = None,
    scroll_timeout_seconds: int = 150,
    post_date_limit: str | None = None,
) -> DailyCollectionSummary:
    """Execute production collection via Apify Reddit scraper, ingest threads and comments into SQLite."""
    apify_client = client or ApifyRedditClient()
    window = daily_window(anchor=datetime.now(timezone.utc), run_hour=7)
    summary = DailyCollectionSummary(
        run_id=run_id,
        status="running",
        window_start_utc=window.start_utc.isoformat(),
        window_end_utc=window.end_utc.isoformat(),
        subreddits=list(subreddits),
        provider_call=True,
    )

    all_queries = list(search_terms) + [f"r/{sub}" for sub in subreddits]
    # Empirical notes from live probes (2026-10-27):
    #  - maxItems is a GLOBAL budget for the whole run, not per query, and it is
    #    NOT the binding constraint: runs stopped at 265/393 items well under 500/800.
    #  - Crawl depth is governed by scrollTimeout (how long each listing/search page
    #    keeps scrolling). Without it the actor returns only the newest page, which is
    #    why a 74-day historical hole could not be backfilled by raising maxItems.
    #  - postDateLimit is honoured as a floor but cannot reach past that crawl depth.
    input_data = {
        "searches": all_queries,
        "maxItems": max_items_per_query,
        "maxComments": max_comments_per_post,
        "sort": "new",
        "type": "link",
        "scrollTimeout": scroll_timeout_seconds,
        "searchPosts": True,
        "searchComments": False,
        "includeNSFW": False,
    }
    if post_date_limit is not None:
        input_data["postDateLimit"] = post_date_limit

    try:
        items = apify_client.run_actor_sync(input_data=input_data)
    except Exception as exc:
        logger.exception("Apify collection execution failed: %s", exc)
        summary.status = "failed"
        summary.issues.append({"stage": "apify_execution", "error": str(exc)})
        store.upsert_run(run_id, "failed", summary.window_start_utc, summary.window_end_utc, provider_call=True)
        return summary

    # Persist raw artifact
    raw_bytes = json.dumps(items, ensure_ascii=False, indent=2).encode("utf-8")
    payload_hash = "sha256:" + hashlib.sha256(raw_bytes).hexdigest()
    capture = RawCapture(
        raw_capture_id=f"raw_apify_{run_id[:16]}_{payload_hash[7:23]}",
        run_id=run_id,
        source_method="apify_reddit",
        source_url="https://api.apify.com/v2/acts/trudax~reddit-scraper-lite",
        captured_at_utc=datetime.now(timezone.utc),
        auth_boundary="apify_provider",
        raw_payload_hash=payload_hash,
        payload_format="json",
        browser_status="ok",
        secrets_written=False,
    )
    if raw_artifact_root is not None:
        persist_raw_artifact(raw_artifact_root, capture, raw_bytes)
    store.insert_raw_capture(capture)

    # Ingest posts and comments into SQLite
    posts_by_id: dict[str, dict[str, Any]] = {}
    comments_by_post_id: dict[str, list[dict[str, Any]]] = {}

    for item in items:
        data_type = item.get("dataType")
        if data_type == "post":
            p_id = str(item.get("id", ""))
            if p_id:
                posts_by_id[p_id] = item
        elif data_type == "comment":
            target_post_id = str(item.get("postId") or item.get("parentId") or "")
            if target_post_id:
                comments_by_post_id.setdefault(target_post_id, []).append(item)

    summary.discovered_posts = len(posts_by_id)

    for p_id, post_dict in posts_by_id.items():
        title = post_dict.get("title") or ""
        selftext = post_dict.get("body") or post_dict.get("text") or ""
        subreddit = post_dict.get("communityName") or post_dict.get("subreddit") or "unknown"
        clean_post_id = p_id.removeprefix("t3_")

        # Parse created_at
        created_at_str = post_dict.get("createdAt")
        try:
            created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00")) if created_at_str else datetime.now(timezone.utc)
        except Exception:
            created_at = datetime.now(timezone.utc)

        post_comments = comments_by_post_id.get(p_id, []) or comments_by_post_id.get(clean_post_id, [])
        post_analysis = analyze_text(title + " " + selftext)

        thread = RedditThread(
            post_id=clean_post_id,
            run_id=run_id,
            raw_capture_id=capture.raw_capture_id,
            subreddit=subreddit,
            title=title,
            source_url=post_dict.get("url") or f"https://reddit.com/r/{subreddit}/comments/{clean_post_id}/",
            created_at_utc=created_at,
            selftext=selftext,
            score=post_dict.get("upVotes") or post_dict.get("score") or 0,
            num_comments_reported=post_dict.get("numberOfComments") or len(post_comments),
            parsed_comment_count=len(post_comments),
            coverage_grade="full" if len(post_comments) > 0 else "post_only",
            matched_keywords=post_analysis.keyword_match.matched_terms,
        )
        store.upsert_thread(thread)
        summary.ingested_threads += 1

        for c_dict in post_comments:
            c_id = str(c_dict.get("id", "")).removeprefix("t1_")
            c_body = c_dict.get("body") or c_dict.get("text") or ""
            c_analysis = analyze_text(c_body)
            # Each comment carries its own createdAt; inheriting the post's timestamp
            # would file every reply under the thread's date and skew daily buckets.
            c_created_str = c_dict.get("createdAt")
            try:
                c_created_at = (
                    datetime.fromisoformat(c_created_str.replace("Z", "+00:00"))
                    if c_created_str
                    else created_at
                )
            except Exception:
                c_created_at = created_at
            comment = RedditComment(
                comment_id=c_id,
                post_id=clean_post_id,
                run_id=run_id,
                raw_capture_id=capture.raw_capture_id,
                body=c_body,
                created_at_utc=c_created_at,
                parent_id=c_dict.get("parentId"),
                score=c_dict.get("upVotes") or 0,
                matched_keywords=c_analysis.keyword_match.matched_terms,
            )
            store.upsert_comment(comment)
            summary.ingested_comments += 1

    summary.status = "success" if summary.ingested_threads > 0 else "empty_success"
    store.upsert_run(run_id, summary.status, summary.window_start_utc, summary.window_end_utc, provider_call=True)
    return summary
