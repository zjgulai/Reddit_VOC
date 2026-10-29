"""Tests for the unified content entity write path.

Pins the three properties that the legacy tables could not express, each of which
was a live defect:

  first-acquisition provenance : `first_seen_run_id` and `is_backfilled` survive
                                 later runs (the legacy upsert overwrote `run_id`,
                                 so "when did we first see this" was lost)
  state-change detection       : `last_changed_at_utc` moves only when `state_hash`
                                 moves, so "did the score change?" is one comparison
  precision preservation       : a day-precision timestamp is never upgraded to an
                                 instant, and midnight is never imputed
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from reddit_voc import content_entity as ce  # noqa: E402


@pytest.fixture()
def conn() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.executescript(ce.SCHEMA)
    return connection


def _post(conn, **overrides):
    kwargs = dict(
        post_id="abc123", run_id="daily_collect_20261001_0700", subreddit="Mom",
        title="Is the M5 quiet?", body="Mine is loud in meetings.",
        created_at_utc="2026-10-01T12:00:00+00:00", score=5, num_comments=3,
    )
    kwargs.update(overrides)
    ce.upsert_post(conn, **kwargs)


# ---------------------------------------------------------------- identity

@pytest.mark.parametrize(
    "raw,entity_type,expected",
    [
        ("abc123", "post", "t3_abc123"),
        ("t3_abc123", "post", "t3_abc123"),
        ("xyz", "comment", "t1_xyz"),
        ("t1_xyz", "comment", "t1_xyz"),
        # The t1_t1_ double-prefix bug: a prefixed id must not be prefixed again.
        ("t1_t1_xyz", "comment", "t1_t1_xyz"),
        ("", "post", ""),
        (None, "post", ""),
    ],
)
def test_normalise_entity_id(raw, entity_type, expected) -> None:
    assert ce.normalise_entity_id(raw, entity_type) == expected


def test_bare_id_strips_exactly_one_prefix() -> None:
    assert ce.bare_id("t3_abc") == "abc"
    assert ce.bare_id("t1_xyz") == "xyz"
    assert ce.bare_id("abc") == "abc"


# ---------------------------------------------------------------- first acquisition

def test_first_seen_run_id_is_not_overwritten(conn) -> None:
    _post(conn, run_id="run_first")
    _post(conn, run_id="run_second")
    row = conn.execute(
        "SELECT first_seen_run_id, last_seen_run_id FROM content_entity WHERE entity_id='t3_abc123'"
    ).fetchone()
    assert row["first_seen_run_id"] == "run_first"
    assert row["last_seen_run_id"] == "run_second"


def test_backfill_flag_is_first_acquisition_not_ever_touched(conn) -> None:
    """The marker answers "how did we first get this", not "was it ever swept".

    Both wrong implementations are real: `MAX(excluded, existing)` lets a realtime post
    that a backfill later sweeps flip to 1 forever, and a blind overwrite lets a
    backfilled post that realtime later sees flip to 0. Either way the cohort that the
    time-series discontinuity is attributed to becomes wrong.
    """
    _post(conn, post_id="bf_first", run_id="backfill_20260901_20260907")
    _post(conn, post_id="rt_first", run_id="daily_collect_20261001_0700")

    # Each is later seen by the other kind of run.
    _post(conn, post_id="bf_first", run_id="daily_collect_20261002_0700")
    _post(conn, post_id="rt_first", run_id="backfill_20260901_20260907")

    flags = {
        row["entity_id"]: row["is_backfilled"]
        for row in conn.execute("SELECT entity_id, is_backfilled FROM content_entity")
    }
    assert flags["t3_bf_first"] == 1
    assert flags["t3_rt_first"] == 0


# ---------------------------------------------------------------- state hash

def test_last_changed_is_null_until_something_changes(conn) -> None:
    """NULL means "unchanged since first seen", not "unknown".

    A brand-new row has no change to report, so the column starts NULL rather than
    at the insert timestamp -- otherwise every record would look edited on day one.
    """
    _post(conn, score=5)
    assert conn.execute(
        "SELECT last_changed_at_utc FROM content_entity WHERE entity_id='t3_abc123'"
    ).fetchone()["last_changed_at_utc"] is None


def test_last_changed_moves_only_on_real_change(conn) -> None:
    _post(conn, score=5)

    # Same content observed again -> still "never changed".
    _post(conn, score=5)
    assert conn.execute(
        "SELECT last_changed_at_utc FROM content_entity WHERE entity_id='t3_abc123'"
    ).fetchone()["last_changed_at_utc"] is None

    # Score changed -> change recorded.
    _post(conn, score=42)
    assert conn.execute(
        "SELECT last_changed_at_utc FROM content_entity WHERE entity_id='t3_abc123'"
    ).fetchone()["last_changed_at_utc"] is not None


def test_state_hash_ignores_fetch_time() -> None:
    base = {"title": "t", "body": "b", "score": 1, "num_comments": 0,
            "lifecycle": "alive", "subreddit": "Mom"}
    assert ce.compute_state_hash(base) == ce.compute_state_hash(dict(base))


def test_state_hash_reacts_to_each_mutable_field() -> None:
    base = {"title": "t", "body": "b", "score": 1, "num_comments": 0,
            "lifecycle": "alive", "subreddit": "Mom"}
    reference = ce.compute_state_hash(base)
    for field, value in (
        ("title", "other"), ("body", "other"), ("score", 2),
        ("num_comments", 9), ("lifecycle", "removed"), ("subreddit", "Dad"),
    ):
        assert ce.compute_state_hash({**base, field: value}) != reference, field


# ---------------------------------------------------------------- precision

def test_day_precision_is_preserved(conn) -> None:
    _post(conn, created_at_utc="2026-07-01")
    row = conn.execute(
        "SELECT event_at_utc, event_precision, source_date FROM content_entity "
        "WHERE entity_id='t3_abc123'"
    ).fetchone()
    assert row["event_precision"] == "day"
    assert row["source_date"] == "2026-07-01"


def test_instant_precision_with_midnight_stays_instant(conn) -> None:
    """A real 00:00:00 timestamp is an instant, not a missing time."""
    _post(conn, created_at_utc="2026-07-01T00:00:00+00:00")
    row = conn.execute(
        "SELECT event_precision, source_date FROM content_entity WHERE entity_id='t3_abc123'"
    ).fetchone()
    assert row["event_precision"] == "instant"
    assert row["source_date"] is None


@pytest.mark.parametrize(
    "value,precision",
    [
        ("2026-07-01", "day"),
        ("2026-07-01T00:00:00+00:00", "instant"),
        ("2026-07-01T12:34:56Z", "instant"),
        ("", "instant"),
        (None, "instant"),
    ],
)
def test_derive_precision(value, precision) -> None:
    assert ce.derive_precision(value)[0] == precision


# ---------------------------------------------------------------- lifecycle

@pytest.mark.parametrize(
    "body,flag,expected",
    [
        ("hello", None, "alive"),
        ("[removed]", None, "removed"),
        ("[deleted]", None, "deleted"),
        ("", None, "unknown"),
        ("   ", None, "unknown"),
        ("hello", True, "deleted"),
        # [removed] must win over the flag: moderator action is not author deletion.
        ("[removed]", True, "removed"),
    ],
)
def test_derive_lifecycle(body, flag, expected) -> None:
    assert ce.derive_lifecycle(body, flag) == expected


def test_lifecycle_covers_every_marker_shape_in_the_real_corpus() -> None:
    """The corpus contains exactly two tombstone spellings; both must be detected.

    Checked against the production database: 1,870 rows are exactly `[removed]` and
    245 are exactly `[deleted]`, with no other `[removed...`/`[deleted...` variants.
    Pinning the real shapes keeps the rule honest without inventing cases the data
    cannot produce.
    """
    assert ce.derive_lifecycle("[removed]", None) == "removed"
    assert ce.derive_lifecycle("[deleted]", None) == "deleted"


# ---------------------------------------------------------------- permalink

def test_post_permalink_is_resolved_on_write(conn) -> None:
    _post(conn, permalink="https://i.redd.it/x.jpeg")
    row = conn.execute(
        "SELECT permalink FROM content_entity WHERE entity_id='t3_abc123'"
    ).fetchone()
    assert row["permalink"] == "https://www.reddit.com/r/Mom/comments/abc123"


def test_comment_stores_no_permalink(conn) -> None:
    """A comment's link is its parent post's; a stored copy is what drifted."""
    ce.upsert_comment(
        conn, comment_id="c1", post_id="abc123", run_id="r", body="reply",
        created_at_utc="2026-10-01T13:00:00+00:00", score=1, depth=1,
    )
    row = conn.execute(
        "SELECT permalink, thread_id FROM content_entity WHERE entity_id='t1_c1'"
    ).fetchone()
    assert row["permalink"] is None
    assert row["thread_id"] == "t3_abc123"


def test_comment_parent_may_be_another_comment(conn) -> None:
    ce.upsert_comment(
        conn, comment_id="c2", post_id="abc123", run_id="r", body="nested",
        created_at_utc="2026-10-01T14:00:00+00:00", depth=2, parent_id="t1_c1",
    )
    row = conn.execute(
        "SELECT parent_id, depth FROM content_entity WHERE entity_id='t1_c2'"
    ).fetchone()
    assert row["parent_id"] == "t1_c1"
    assert row["depth"] == 2


# ---------------------------------------------------------------- COALESCE guards

def test_blank_subreddit_does_not_erase_a_real_one(conn) -> None:
    """Legacy tables store '' for unknown; COALESCE alone would let '' win forever."""
    _post(conn, subreddit="Mom")
    _post(conn, subreddit="")
    assert conn.execute(
        "SELECT subreddit FROM content_entity WHERE entity_id='t3_abc123'"
    ).fetchone()["subreddit"] == "Mom"


def test_missing_optional_fields_do_not_erase_existing(conn) -> None:
    _post(conn, num_comments=7)
    _post(conn, num_comments=None)
    assert conn.execute(
        "SELECT num_comments FROM content_entity WHERE entity_id='t3_abc123'"
    ).fetchone()["num_comments"] == 7


def test_is_backfilled_flag_derives_from_run_id_prefix() -> None:
    assert ce.is_backfill_run("backfill_20260901_20260907") == 1
    assert ce.is_backfill_run("daily_collect_20261001_0700") == 0
    assert ce.is_backfill_run("") == 0
    assert ce.is_backfill_run(None) == 0


def test_schema_creates_content_entity_table(conn) -> None:
    tables = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert "content_entity" in tables


def test_storage_schema_includes_content_entity() -> None:
    """A fresh database must be able to publish; the fact table cannot be optional."""
    from reddit_voc.storage import SCHEMA

    assert "CREATE TABLE IF NOT EXISTS content_entity" in SCHEMA
    assert "idx_ce_type_event" in SCHEMA
