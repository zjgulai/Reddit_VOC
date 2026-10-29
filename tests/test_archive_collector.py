"""Archive collector: planning, sharding, coverage ledger, normalization.

These tests pin the behaviours that the old realtime collector got wrong, so they
cannot silently regress:

  - a same-run retry must not collide on raw capture identity
  - a truncated run must be reported PARTIAL, never success
  - a day with zero items must be distinguishable from a day nobody asked about
  - a missing timestamp must stay unknown rather than becoming "now"
"""
from __future__ import annotations

import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from reddit_voc.archive_collector import (
    ArchiveRedditClient,
    backfill_week_shards,
    build_plan,
    collect_archive,
    shanghai_day_bounds,
    shanghai_t1,
    _build_input,
    _coverage_rows,
    _event_date,
    _split_items,
)
from reddit_voc.storage import VocStore


@pytest.fixture()
def store(tmp_path: Path) -> VocStore:
    s = VocStore(tmp_path / "test.sqlite3")
    s.migrate()
    return s


def _post(post_id: str, created: str, title: str = "Momcozy leaking") -> dict:
    return {
        "id": post_id,
        "fullname": f"t3_{post_id}",
        "title": title,
        "selftext": "the valve leaks",
        "subreddit": "ExclusivePumping",
        "createdUtc": created,
        "score": 3,
        "numComments": 1,
        "url": f"https://reddit.com/r/x/comments/{post_id}/",
        "type": "post",
    }


def _comment(comment_id: str, link_id: str, created: str, body: str = "same here") -> dict:
    return {
        "id": comment_id,
        "linkId": f"t3_{link_id}",
        "parentId": f"t3_{link_id}",
        "body": body,
        "createdUtc": created,
        "score": 1,
        "depth": 0,
    }


class FakeClient:
    """Stands in for ArchiveRedditClient with canned items / metadata."""

    def __init__(self, items, meta=None):
        self.items = items
        self.meta = meta or {"status": "SUCCEEDED", "truncated": False}
        self.calls = []

    def run_actor(self, input_data, **kwargs):
        self.calls.append(input_data)
        return self.items, dict(self.meta)


class TestPlanAndSharding:
    def test_plan_id_is_stable_and_content_addressed(self):
        a = build_plan(date_from=date(2026, 7, 23), date_to=date(2026, 10, 4),
                       search_queries=["Momcozy"], comment_queries=["Momcozy"])
        b = build_plan(date_from=date(2026, 7, 23), date_to=date(2026, 10, 4),
                       search_queries=["Momcozy"], comment_queries=["Momcozy"])
        c = build_plan(date_from=date(2026, 7, 23), date_to=date(2026, 10, 4),
                       search_queries=["Momcozy", "Elvie"], comment_queries=["Momcozy"])
        assert a["plan_id"] == b["plan_id"]
        assert a["plan_id"] != c["plan_id"], "adding a query must change the plan identity"
        assert len(a["plan_id"]) == 64

    def test_week_shards_are_contiguous_and_complete(self):
        shards = backfill_week_shards(date(2026, 7, 23), date(2026, 10, 4))
        assert shards[0][0] == date(2026, 7, 23)
        assert shards[-1][1] == date(2026, 10, 4)
        for (_, prev_end), (next_start, _) in zip(shards, shards[1:]):
            assert next_start.toordinal() == prev_end.toordinal() + 1, "shards must not gap or overlap"
        for start, end in shards:
            assert start <= end
            # a week shard never crosses more than 7 days
            assert (end - start).days <= 6

    def test_shard_spanning_single_day(self):
        assert backfill_week_shards(date(2026, 10, 4), date(2026, 10, 4)) == [
            (date(2026, 10, 4), date(2026, 10, 4))
        ]


class TestInputContract:
    def test_before_date_is_exclusive_so_window_includes_last_day(self):
        payload = _build_input(
            date_from=date(2026, 10, 1), date_to=date(2026, 10, 3),
            search_queries=["Momcozy"], comment_queries=[], subreddits=[],
            max_items=100, max_items_per_target=50,
        )
        assert payload["afterDate"] == "2026-10-01"
        # exclusive upper bound: one day past the last wanted day
        assert payload["beforeDate"] == "2026-10-04"

    def test_comment_queries_are_passed_through(self):
        payload = _build_input(
            date_from=date(2026, 10, 1), date_to=date(2026, 10, 1),
            search_queries=["Momcozy"], comment_queries=["Momcozy", "leaking"],
            subreddits=[], max_items=10, max_items_per_target=5,
        )
        assert payload["commentSearchQueries"] == ["Momcozy", "leaking"]


class TestTimestampHandling:
    def test_unknown_timestamp_is_not_replaced_with_now(self):
        assert _event_date({"createdUtc": None}) is None
        assert _event_date({}) is None
        assert _event_date({"createdUtc": "not-a-date"}) is None

    def test_epoch_seconds_are_parsed(self):
        assert _event_date({"createdUtc": 1780000000}).isoformat() == "2026-05-29"

    def test_iso_timestamp_maps_to_shanghai_business_day(self):
        # 2026-10-26T20:00Z is 2026-10-27 04:00 in Shanghai
        assert _event_date({"createdUtc": "2026-10-26T20:00:00.000Z"}).isoformat() == "2026-10-27"


class TestCoverageLedger:
    def test_zero_item_day_is_distinguishable_from_unasked_day(self):
        rows = _coverage_rows(
            date_from=date(2026, 7, 24), date_to=date(2026, 7, 26),
            posts=[_post("p1", "2026-07-24T10:00:00.000Z")], comments=[],
            lane="archive_window", truncated=False,
        )
        by_day = {r["business_date"]: r for r in rows}
        assert by_day["2026-07-24"]["completeness"] == "complete"
        assert by_day["2026-07-24"]["reached_floor"] is True
        assert by_day["2026-07-25"]["completeness"] == "missing"
        assert by_day["2026-07-25"]["reason"] == "lane_returned_zero_items_for_day"
        assert by_day["2026-07-25"]["reached_floor"] is False

    def test_truncated_run_marks_empty_days_unknown_not_missing(self):
        rows = _coverage_rows(
            date_from=date(2026, 7, 24), date_to=date(2026, 7, 25),
            posts=[], comments=[], lane="archive_window", truncated=True,
        )
        assert all(r["completeness"] == "unknown" for r in rows)
        assert all(r["reason"] == "run_truncated_at_deadline" for r in rows)

    def test_undated_items_are_reported_not_silently_dropped(self):
        rows = _coverage_rows(
            date_from=date(2026, 7, 24), date_to=date(2026, 7, 24),
            posts=[_post("p1", None)], comments=[], lane="archive_window", truncated=False,
        )
        undated = [r for r in rows if r["reason"] and "without_parseable_timestamp" in r["reason"]]
        assert len(undated) == 1
        assert undated[0]["completeness"] == "unknown"


class TestItemSplitting:
    def test_posts_and_comments_are_separated_by_shape(self):
        items = [_post("p1", "2026-07-24T00:00:00.000Z"),
                 _comment("c1", "p1", "2026-07-24T01:00:00.000Z")]
        posts, comments = _split_items(items)
        assert len(posts) == 1 and len(comments) == 1


class TestCollectArchive:
    def test_comments_attach_to_posts_and_coverage_is_recorded(self, store: VocStore):
        items = [
            _post("p1", "2026-07-24T10:00:00.000Z"),
            _comment("c1", "p1", "2026-07-24T11:00:00.000Z"),
        ]
        client = FakeClient(items)
        summary, rows = collect_archive(
            store, run_id="run_a", client=client,
            date_from=date(2026, 7, 24), date_to=date(2026, 7, 24),
            search_queries=["Momcozy"], comment_queries=["Momcozy"],
        )
        assert summary.status == "success"
        assert summary.ingested_threads == 1
        assert summary.ingested_comments == 1
        store.record_coverage("run_a", rows, "plan")
        with store.connect() as conn:
            thread = conn.execute("SELECT * FROM reddit_threads WHERE post_id='p1'").fetchone()
            comment = conn.execute("SELECT * FROM reddit_comments WHERE comment_id='c1'").fetchone()
        assert thread["coverage_grade"] == "full", "1 of 1 reported comments fetched"
        assert comment["post_id"] == "p1"
        # comment queries really reach the provider
        assert client.calls[0]["commentSearchQueries"] == ["Momcozy"]

    def test_truncated_run_is_partial_never_success(self, store: VocStore):
        client = FakeClient([_post("p1", "2026-07-24T10:00:00.000Z")],
                            meta={"status": "RUNNING", "truncated": True})
        summary, _ = collect_archive(
            store, run_id="run_t", client=client,
            date_from=date(2026, 7, 24), date_to=date(2026, 7, 24),
            search_queries=["Momcozy"],
        )
        assert summary.status == "partial"
        assert any(i["stage"] == "archive_completion" for i in summary.issues)

    def test_provider_failure_fails_the_run(self, store: VocStore):
        class Boom:
            def run_actor(self, *a, **k):
                raise RuntimeError("HTTP Error 502: Bad Gateway")

        summary, rows = collect_archive(
            store, run_id="run_f", client=Boom(),
            date_from=date(2026, 7, 24), date_to=date(2026, 7, 24),
            search_queries=["Momcozy"],
        )
        assert summary.status == "failed"
        assert rows == []
        with store.connect() as conn:
            assert conn.execute("SELECT status FROM runs WHERE run_id='run_f'").fetchone()["status"] == "failed"

    def test_orphan_comments_are_reported(self, store: VocStore):
        items = [_post("p1", "2026-07-24T10:00:00.000Z"),
                 _comment("c_orphan", "different_post", "2026-07-24T11:00:00.000Z")]
        summary, _ = collect_archive(
            store, run_id="run_o", client=FakeClient(items),
            date_from=date(2026, 7, 24), date_to=date(2026, 7, 24),
            search_queries=["Momcozy"],
        )
        assert any(i["stage"] == "comment_parent_link" for i in summary.issues)

    def test_retry_same_run_id_does_not_collide_on_capture(self, store: VocStore):
        items = [_post("p1", "2026-07-24T10:00:00.000Z")]
        collect_archive(store, run_id="run_r", client=FakeClient(items),
                        date_from=date(2026, 7, 24), date_to=date(2026, 7, 24),
                        search_queries=["Momcozy"])
        collect_archive(store, run_id="run_r", client=FakeClient(items),
                        date_from=date(2026, 7, 24), date_to=date(2026, 7, 24),
                        search_queries=["Momcozy"])
        with store.connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM raw_captures").fetchone()[0] == 1


class TestCoverageGapsQuery:
    def test_gaps_lists_exactly_the_unreached_days(self, store: VocStore):
        store.record_coverage("r1", [
            {"lane": "archive_window", "business_date": "2026-07-24",
             "observed_posts": 3, "reached_floor": True, "completeness": "complete"},
            {"lane": "archive_window", "business_date": "2026-07-26",
             "observed_posts": 0, "reached_floor": False, "completeness": "missing"},
        ])
        gaps = [g["business_date"] for g in store.coverage_gaps("2026-07-24", "2026-07-27")]
        # 07-24 reached the floor; 07-25 was never recorded; 07-26 was asked but
        # returned nothing (reached_floor=0); 07-27 was never asked.
        assert gaps == ["2026-07-25", "2026-07-26", "2026-07-27"]

    def test_business_day_helpers_agree(self):
        assert shanghai_day_bounds(date(2026, 10, 26)) == ("2026-10-26", "2026-10-27")
        # T-1 must always be strictly before the current Shanghai day
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo
        today = _dt.now(ZoneInfo("Asia/Shanghai")).date()
        assert shanghai_t1() < today
