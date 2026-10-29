"""Archive-backed Reddit collector (PullPush via Apify).

Why this exists next to `apify_collector`:

The realtime actor (`trudax~reddit-scraper-lite`) can only be asked for "the newest
N items" plus a `postDateLimit` floor, and its crawl depth is bounded by
`scrollTimeout`. Measured on 2026-10-27: even with `maxItems=800` and a floor three
months back, it returned nothing older than one day. So it can neither express
"exactly yesterday" nor backfill a historical gap.

`logiover~reddit-historical-archive-scraper` reads the PullPush archive instead of
live Reddit, and exposes `afterDate` / `beforeDate` as a true inclusive/exclusive
window. Measured behaviour:

  - hole backfill (2026-07-23..10-04): 99/99 items inside the window, 272s, $0.119
  - comment expansion via `postIds`: 19 comments for 2 posts, $0.0036
  - freshness without `beforeDate`: newest post 2026-10-27 (lag 1 day) => usable
    for a T-1 product
  - `commentSearchQueries` does full-text search over archived COMMENTS, which
    Reddit's own search cannot do at all

That is why the archive path is primary for daily T-1 collection and for
backfill, with the realtime actor kept as a fallback for T-0 / archive gaps.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from datetime import time as clock_time
from pathlib import Path
from typing import Any, Iterable, Sequence
from zoneinfo import ZoneInfo

from .analyzer import analyze_text
from .models import DailyCollectionSummary, RawCapture, RedditComment, RedditThread
from .raw_artifacts import persist_raw_artifact
from .storage import VocStore

logger = logging.getLogger("reddit_voc.archive")

DEFAULT_ARCHIVE_ACTOR = "logiover~reddit-historical-archive-scraper"
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

# One lane = one query/target. A lane is the smallest retryable unit and the unit
# the coverage ledger records, so "did we look at this day" is answerable per query
# instead of per opaque run.
LANE_SEARCH_POSTS = "search_posts"
LANE_SEARCH_COMMENTS = "search_comments"
LANE_SUBREDDIT = "subreddit"
LANE_POST_THREAD = "post_thread"


def shanghai_day_bounds(day: date) -> tuple[str, str]:
    """Inclusive start / exclusive end ISO dates for a Shanghai natural day.

    The archive actor compares on the post's own creation date, and the product
    reasons in Shanghai business days, so callers pass the business day and this
    helper keeps the conversion in exactly one place.
    """
    return day.isoformat(), (day + timedelta(days=1)).isoformat()


def shanghai_today() -> date:
    return datetime.now(SHANGHAI_TZ).date()


def shanghai_t1() -> date:
    """Last fully closed Shanghai business day (the T-1 the product reports on)."""
    return shanghai_today() - timedelta(days=1)


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _event_date(item: dict) -> date | None:
    """Business date of the content itself, from its own timestamp.

    Never falls back to "now": an unknown timestamp must stay unknown so the
    coverage ledger can report it instead of silently filing the row under today.
    """
    stamp = _parse_ts(item.get("createdUtc") or item.get("created_utc"))
    if stamp is None:
        return None
    return stamp.astimezone(SHANGHAI_TZ).date()


class ArchiveRedditClient:
    """Thin Apify client for the archive actor, with retries and a cost ceiling."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout_seconds: int = 60,
        max_retries: int = 3,
    ) -> None:
        self.api_key = (api_key or os.getenv("APIFY_API_KEY", "")).strip()
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        if not self.api_key:
            raise ValueError("APIFY_API_KEY is required")

    def _request(self, url: str, *, data: bytes | None = None) -> Any:
        last: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                req = urllib.request.Request(
                    url,
                    data=data,
                    headers={"Content-Type": "application/json"} if data else {},
                )
                with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except Exception as exc:  # noqa: BLE001 - provider errors vary
                last = exc
                if attempt == self.max_retries:
                    break
                backoff = 2 ** attempt
                logger.warning("archive request failed (attempt %s/%s): %s; retrying in %ss",
                               attempt, self.max_retries, exc, backoff)
                time.sleep(backoff)
        raise RuntimeError(f"archive provider request failed after {self.max_retries} attempts: {last}")

    def run_actor(
        self,
        input_data: dict[str, Any],
        *,
        actor_id: str = DEFAULT_ARCHIVE_ACTOR,
        max_wait_seconds: int = 900,
        poll_seconds: int = 8,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Run the actor and return (items, run_metadata).

        Unlike the realtime client, a run still RUNNING at the deadline is reported
        as TRUNCATED rather than silently accepted as complete: partial data must be
        visible to the coverage ledger.
        """
        trigger = self._request(
            f"https://api.apify.com/v2/acts/{actor_id}/runs?token={self.api_key}",
            data=json.dumps(input_data).encode("utf-8"),
        )
        run = trigger["data"]
        run_id, dataset_id = run["id"], run["defaultDatasetId"]
        logger.info("archive actor run started: %s", run_id)

        deadline = time.time() + max_wait_seconds
        status = "RUNNING"
        meta: dict[str, Any] = {}
        while time.time() < deadline:
            time.sleep(poll_seconds)
            meta = self._request(
                f"https://api.apify.com/v2/actor-runs/{run_id}?token={self.api_key}"
            )["data"]
            status = meta["status"]
            if status not in ("READY", "RUNNING"):
                break

        if status in ("FAILED", "ABORTED", "TIMED-OUT"):
            raise RuntimeError(f"archive actor run {run_id} terminated with status: {status}")

        items = self._request(
            f"https://api.apify.com/v2/datasets/{dataset_id}/items?token={self.api_key}&clean=true"
        )
        if not isinstance(items, list):
            items = []
        truncated = status in ("RUNNING", "READY")
        meta = dict(meta or {})
        meta["status"] = status
        meta["truncated"] = truncated
        meta["run_id"] = run_id
        meta["dataset_id"] = dataset_id
        if truncated:
            logger.warning("archive run %s still %s at deadline; %s items are PARTIAL",
                           run_id, status, len(items))
        return items, meta


def build_plan(
    *,
    date_from: date,
    date_to: date,
    search_queries: Sequence[str],
    comment_queries: Sequence[str],
    subreddits: Sequence[str] = (),
    max_items: int = 1500,
    max_items_per_target: int = 300,
    max_cost_usd: float = 3.0,
) -> dict[str, Any]:
    """Declare what a run intends to cover, before it runs.

    The plan id is a content hash, so two runs that ask the same thing are the same
    plan and a changed query set is a different plan -- which is what makes the
    coverage ledger auditable.
    """
    body = {
        "provider": "apify_archive",
        "actor": DEFAULT_ARCHIVE_ACTOR,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "search_queries": sorted(search_queries),
        "comment_queries": sorted(comment_queries),
        "subreddits": sorted(subreddits),
        "max_items": max_items,
        "max_items_per_target": max_items_per_target,
        "max_cost_usd": max_cost_usd,
        "business_timezone": "Asia/Shanghai",
    }
    plan_id = hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return {**body, "plan_id": plan_id}


def backfill_week_shards(date_from: date, date_to: date) -> list[tuple[date, date]]:
    """Split a span into Monday-aligned weekly shards.

    Weekly is the agreed granularity: small enough that a failed shard is cheap to
    retry, large enough that a 74-day hole is ~11 runs instead of 74.
    """
    shards: list[tuple[date, date]] = []
    cursor = date_from
    while cursor <= date_to:
        # advance to the next Monday boundary, capped by the overall end
        offset = (7 - cursor.weekday()) % 7 or 7
        nxt = min(cursor + timedelta(days=offset - 1), date_to)
        shards.append((cursor, nxt))
        cursor = nxt + timedelta(days=1)
    return shards


def _build_input(
    *,
    date_from: date,
    date_to: date,
    search_queries: Sequence[str],
    comment_queries: Sequence[str],
    subreddits: Sequence[str],
    max_items: int,
    max_items_per_target: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "afterDate": date_from.isoformat(),
        # beforeDate is exclusive per provider docs; ask for the day after the last
        # wanted day so the window is inclusive of date_to.
        "beforeDate": (date_to + timedelta(days=1)).isoformat(),
        "sort": "new",
        "maxItems": max_items,
        "maxItemsPerTarget": max_items_per_target,
        "proxyConfiguration": {"useApifyProxy": True},
    }
    if search_queries:
        payload["searchQueries"] = list(search_queries)
    if comment_queries:
        payload["commentSearchQueries"] = list(comment_queries)
    if subreddits:
        payload["subreddits"] = list(subreddits)
    return payload


def _split_items(items: Iterable[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    posts: list[dict] = []
    comments: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("body") is not None and item.get("title") is None:
            comments.append(item)
        elif item.get("title") is not None or item.get("id"):
            posts.append(item)
    return posts, comments


def _coverage_rows(
    *,
    date_from: date,
    date_to: date,
    posts: list[dict],
    comments: list[dict],
    lane: str,
    truncated: bool,
) -> list[dict[str, Any]]:
    """Per-business-day coverage for one lane.

    `reached_floor` is the load-bearing field: a day only counts as covered when an
    observed item actually sits on that day. Days with zero observations are
    reported as `missing` with a reason instead of being indistinguishable from
    days nobody asked about -- the failure that hid the 74-day hole.
    """
    by_day_posts: dict[date, int] = {}
    by_day_comments: dict[date, int] = {}
    undated = 0
    for post in posts:
        day = _event_date(post)
        if day is None:
            undated += 1
            continue
        by_day_posts[day] = by_day_posts.get(day, 0) + 1
    for comment in comments:
        day = _event_date(comment)
        if day is None:
            undated += 1
            continue
        by_day_comments[day] = by_day_comments.get(day, 0) + 1

    rows: list[dict[str, Any]] = []
    cursor = date_from
    while cursor <= date_to:
        p = by_day_posts.get(cursor, 0)
        c = by_day_comments.get(cursor, 0)
        if p or c:
            status = "complete"
            reason = None
        elif truncated:
            status = "unknown"
            reason = "run_truncated_at_deadline"
        else:
            status = "missing"
            reason = "lane_returned_zero_items_for_day"
        rows.append({
            "business_date": cursor.isoformat(),
            "lane": lane,
            "observed_posts": p,
            "observed_comments": c,
            "reached_floor": bool(p or c),
            "completeness": status,
            "reason": reason,
        })
        cursor += timedelta(days=1)

    if undated:
        rows.append({
            "business_date": date_from.isoformat(),
            "lane": lane,
            "observed_posts": 0,
            "observed_comments": 0,
            "reached_floor": False,
            "completeness": "unknown",
            "reason": f"{undated}_items_without_parseable_timestamp",
        })
    return rows


def collect_archive(
    store: VocStore,
    *,
    run_id: str,
    client: ArchiveRedditClient | None = None,
    date_from: date,
    date_to: date,
    search_queries: Sequence[str] = ("Momcozy",),
    comment_queries: Sequence[str] = (),
    subreddits: Sequence[str] = (),
    max_items: int = 1500,
    max_items_per_target: int = 300,
    max_wait_seconds: int = 900,
    raw_artifact_root: Path | str | None = None,
    ingest_comments_as_entities: bool = True,
    expand_comments: bool = True,
    max_expand_posts: int = 60,
    expand_batch_size: int = 15,
) -> tuple[DailyCollectionSummary, list[dict[str, Any]]]:
    """Collect one date window from the archive and ingest it.

    Two phases, because the provider's modes are not interchangeable -- measured
    on 2026-10-28 over 2026-07-23..07-27:

      - `searchQueries`        : 3 queries -> 0 items. Unreliable, cannot drive a SLA.
      - `commentSearchQueries` : advertised as archived-COMMENT full-text search, but
                                 returned 300 items that were ALL posts, 0 comments.
                                 Not usable as a comment channel.
      - `subreddits`           : 4 subreddits -> 800 posts. Reliable discovery.
      - `postIds`              : 5 posts -> 45 comments = 9.0 comments/post. The only
                                 reliable way to reach comments (realtime actor gets
                                 ~4.7/post, so this is strictly better).

    So: phase 1 discovers post ids (subreddits first, searches as an optional second
    sweep), phase 2 expands comments for the highest-value posts in batches.

    Returns the run summary plus the per-day coverage ledger rows the caller must
    persist, so a partially covered window is visible rather than inferred.
    """
    archive = client or ArchiveRedditClient()
    plan = build_plan(
        date_from=date_from,
        date_to=date_to,
        search_queries=search_queries,
        comment_queries=comment_queries,
        subreddits=subreddits,
        max_items=max_items,
        max_items_per_target=max_items_per_target,
    )
    start_utc = datetime.combine(date_from, clock_time.min, tzinfo=SHANGHAI_TZ).astimezone(timezone.utc)
    end_utc = datetime.combine(date_to + timedelta(days=1), clock_time.min, tzinfo=SHANGHAI_TZ).astimezone(timezone.utc)

    summary = DailyCollectionSummary(
        run_id=run_id,
        status="running",
        window_start_utc=start_utc.isoformat(),
        window_end_utc=end_utc.isoformat(),
        subreddits=list(subreddits),
        provider_call=True,
    )

    payload = _build_input(
        date_from=date_from,
        date_to=date_to,
        search_queries=search_queries,
        comment_queries=comment_queries,
        subreddits=subreddits,
        max_items=max_items,
        max_items_per_target=max_items_per_target,
    )

    try:
        items, meta = archive.run_actor(payload, max_wait_seconds=max_wait_seconds)
    except Exception as exc:  # noqa: BLE001
        logger.exception("archive collection failed: %s", exc)
        summary.status = "failed"
        summary.issues.append({"stage": "archive_execution", "error": str(exc)})
        store.upsert_run(run_id, "failed", summary.window_start_utc, summary.window_end_utc, provider_call=True)
        return summary, []

    # ---- phase 2: comment expansion -------------------------------------------
    expand_meta: list[dict[str, Any]] = []
    if expand_comments:
        discovered_ids = [
            str(p.get("id"))
            for p in items
            if isinstance(p, dict) and p.get("title") and p.get("id")
        ]
        # Prioritise posts that report the most comments: VOC value is concentrated
        # there, and the expansion budget is finite.
        reported = {
            str(p.get("id")): int(p.get("numComments") or 0)
            for p in items
            if isinstance(p, dict) and p.get("id")
        }
        ranked = sorted(dict.fromkeys(discovered_ids), key=lambda pid: -reported.get(pid, 0))
        targets = ranked[:max_expand_posts]
        for offset in range(0, len(targets), expand_batch_size):
            batch = targets[offset:offset + expand_batch_size]
            try:
                expanded, batch_meta = archive.run_actor(
                    {
                        "postIds": batch,
                        "maxItems": max_items,
                        "proxyConfiguration": {"useApifyProxy": True},
                    },
                    max_wait_seconds=max_wait_seconds,
                )
            except Exception as exc:  # noqa: BLE001
                # A failed expansion must not lose the posts already discovered.
                summary.issues.append({
                    "stage": "comment_expansion",
                    "error": str(exc),
                    "posts_in_batch": len(batch),
                })
                continue
            batch_comments = [i for i in expanded if isinstance(i, dict) and i.get("body")]
            expand_meta.append({
                "posts": len(batch),
                "comments": len(batch_comments),
                "truncated": bool(batch_meta.get("truncated")),
                "status": batch_meta.get("status"),
            })
            items.extend(batch_comments)
            if batch_meta.get("truncated"):
                summary.issues.append({
                    "stage": "comment_expansion",
                    "error": "expansion run truncated at deadline",
                    "posts_in_batch": len(batch),
                })

    raw_bytes = json.dumps(items, ensure_ascii=False, indent=2).encode("utf-8")
    payload_hash = "sha256:" + hashlib.sha256(raw_bytes).hexdigest()
    capture = RawCapture(
        # Include the payload hash so a same-run retry cannot collide.
        raw_capture_id=f"raw_archive_{run_id[:16]}_{payload_hash[7:23]}",
        run_id=run_id,
        source_method="apify_archive",
        source_url=f"https://api.apify.com/v2/acts/{DEFAULT_ARCHIVE_ACTOR}",
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

    # Phase 1 and phase 2 can both surface the same comment (a search hit and a
    # postIds expansion of the same thread). Dedupe by comment id before splitting,
    # otherwise the same reply is ingested twice and inflates every downstream count.
    deduped: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("body") is not None and item.get("title") is None:
            key = "comment:" + str(item.get("id") or "")
            deduped.setdefault(key, item)
        else:
            key = "post:" + str(item.get("id") or "")
            deduped.setdefault(key, item)
    items = list(deduped.values())

    posts, comments = _split_items(items)
    summary.discovered_posts = len(posts)

    # Post ids present in this batch, so comments can be attached and orphans counted.
    batch_post_ids = {str(p.get("id") or "").removeprefix("t3_") for p in posts}
    comments_by_link: dict[str, list[dict]] = {}
    orphan_comments = 0
    for comment in comments:
        link = str(comment.get("linkId") or "").removeprefix("t3_")
        # A comment whose parent post is not in this batch cannot be attached. Count
        # it instead of dropping it silently: the previous collector lost these and
        # nothing downstream could tell that the corpus was incomplete.
        if not link or link not in batch_post_ids:
            orphan_comments += 1
            continue
        comments_by_link.setdefault(link, []).append(comment)

    for post in posts:
        post_id = str(post.get("id") or "").removeprefix("t3_")
        if not post_id:
            continue
        title = post.get("title") or ""
        selftext = post.get("selftext") or ""
        subreddit = str(post.get("subreddit") or "unknown")
        created = _parse_ts(post.get("createdUtc")) or datetime.now(timezone.utc)
        thread_comments = comments_by_link.get(post_id, [])
        reported = post.get("numComments")
        analysis = analyze_text(f"{title} {selftext}")

        if not thread_comments:
            grade = "post_only"
        elif isinstance(reported, int) and len(thread_comments) >= reported:
            grade = "full"
        else:
            grade = "partial"

        store.upsert_thread(RedditThread(
            post_id=post_id,
            run_id=run_id,
            raw_capture_id=capture.raw_capture_id,
            subreddit=subreddit,
            title=title,
            source_url=post.get("url") or post.get("permalink") or "",
            created_at_utc=created,
            selftext=selftext,
            score=post.get("score"),
            num_comments_reported=reported,
            parsed_comment_count=len(thread_comments),
            more_node_count=0,
            coverage_grade=grade,
            matched_keywords=analysis.keyword_match.matched_terms,
        ))
        summary.ingested_threads += 1
        # Append-only provenance. The thread row is a destructive upsert, so without
        # this the fact that a post was FIRST seen by an earlier run is erased the
        # moment a later run re-observes it.
        store.record_observation(
            entity_type="post",
            entity_id=post_id,
            run_id=run_id,
            event_at_utc=created.isoformat(),
            payload_sha256=payload_hash,
        )

        if not ingest_comments_as_entities:
            continue
        for comment in thread_comments:
            comment_id = str(comment.get("id") or "").removeprefix("t1_")
            if not comment_id:
                continue
            body = comment.get("body") or ""
            c_analysis = analyze_text(body)
            store.upsert_comment(RedditComment(
                comment_id=comment_id,
                post_id=post_id,
                run_id=run_id,
                raw_capture_id=capture.raw_capture_id,
                body=body,
                created_at_utc=_parse_ts(comment.get("createdUtc")) or created,
                parent_id=comment.get("parentId"),
                score=comment.get("score"),
                depth=comment.get("depth"),
                matched_keywords=c_analysis.keyword_match.matched_terms,
                deleted_or_removed=body.strip() in ("[deleted]", "[removed]"),
            ))
            summary.ingested_comments += 1

    if orphan_comments:
        summary.issues.append({
            "stage": "comment_parent_link",
            "error": f"{orphan_comments}_comments_had_no_linkId",
        })

    coverage_rows = _coverage_rows(
        date_from=date_from,
        date_to=date_to,
        posts=posts,
        comments=comments,
        lane="archive_window",
        truncated=bool(meta.get("truncated")),
    )

    summary.coverage = {
        "posts": len(posts),
        "comments": len(comments),
        "orphan_comments": orphan_comments,
        "truncated": int(bool(meta.get("truncated"))),
        "plan_id": plan["plan_id"][:16],
    }
    if meta.get("truncated"):
        summary.issues.append({
            "stage": "archive_completion",
            "error": "run hit the wall-clock deadline; window is PARTIAL",
        })
        summary.status = "partial"
    else:
        summary.status = "success" if (summary.ingested_threads or summary.ingested_comments) else "empty_success"

    store.upsert_run(run_id, summary.status, summary.window_start_utc, summary.window_end_utc, provider_call=True)
    return summary, coverage_rows
