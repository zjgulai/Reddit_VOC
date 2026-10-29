"""The one-aggregates-producer constraint, pinned as tests.

`site_aggregates.build_aggregates` (self-contained, stdlib only) must agree with
`v3_base_public._aggregates` (canonical) field for field on the same inputs.
This was not always true: a hand-written second producer in
`recompute_derivatives` disagreed on eight fields — top_tags indexed every tag
instead of aspect tags only, three status fields were single strings instead of
`{value: count}` maps, and `metric_notes` had 2 of the 5 required keys. The
offline validator compares the whole object for equality
(`public_aggregates_recompute_mismatch`), so a diverging producer can never pass
the validator — yet it ran in production, because the lean deployment has no
`v3_base_public` to import and nothing pinned the equivalence.

These tests make the equivalence itself the contract. If the canonical producer
changes shape, they fail and the self-contained twin must move in the same
change.

The corpus here is adversarial, not realistic: day-precision timestamps beside
instant ones, pending metric eligibility (`include_in_voc_metrics=None`),
brand-scope tags that must stay out of `top_tags`, and a `counts` block whose
`stored_comments` deliberately disagrees with `len(comments)` — pass-through is
the contract. Where the two implementations are NOT both defined (empty corpus,
missing `analysis`), that divergence is documented and tested per-implementation
only.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import reddit_voc.site_aggregates as sa  # noqa: E402
import reddit_voc.v3_base_public as v3  # noqa: E402
from reddit_voc.site_aggregates import build_aggregates  # noqa: E402
from reddit_voc.tag_dictionary import TagDictionary, TagRule  # noqa: E402

DICTIONARY_VERSION = "dim_tag_v6.3_final"

COUNTS = {
    "posts": 3,
    "comments_jsonl": 3,
    "linked_comments": 3,
    # Deliberately NOT derived from the rows below: the headline must pass these
    # through untouched, not recompute them (that independence is what once
    # produced "聚合隔离评论数与 manifest 不一致").
    "unresolved_parent_comments": 7,
    "quarantined_comments": 4,
    "stored_comments": 14,
}


def _rule(tag_id: str, *, sentiment: str = "negative") -> TagRule:
    return TagRule(
        tag_id=tag_id,
        name_cn=f"标签{tag_id}",
        name_en=f"Tag {tag_id}",
        sentiment=sentiment,
        theme="experience",
        tag_scope="aspect",
        product_line="pump",
        voc_category="product",
        spu_id="",
        keywords=(tag_id,),
        fields=(("tag_id", tag_id),),
    )


def _rule_dicts(rules: list[TagRule]) -> list[dict]:
    """Exactly the keys `site_aggregates.tag_summary` reads."""
    return [
        {
            "tag_id": r.tag_id,
            "name_cn": r.name_cn,
            "name_en": r.name_en,
            "theme": r.theme,
            "sentiment": r.sentiment,
        }
        for r in rules
    ]


def _post(**overrides) -> dict:
    row = {
        "post_id": "p1",
        "subreddit": "Mom",
        "created_at_utc": "2026-10-01T12:00:00+00:00",
        "event_time_precision": "instant",
        "mentioned_brands": ["momcozy"],
        "structural_coverage_grade": "full",
        "count_completeness_status": "observed",
        "analysis": {
            "sentiment_label": "negative",
            "topic": "noise",
            "pain_points": ["loud motor"],
        },
        "tagging": {"tag_ids": ["leaking"], "aspect_tag_ids": ["leaking"]},
    }
    row.update(overrides)
    return row


def _comment(**overrides) -> dict:
    row = {
        "comment_id": "c1",
        "post_id": "p1",
        "subreddit": "Mom",
        "created_at_utc": "2026-10-02T09:00:00+00:00",
        "event_time_precision": "instant",
        "parent_link_status": "linked",
        "metric_eligibility_status": "source_explicit",
        "include_in_voc_metrics": True,
        "analysis": {
            "sentiment_label": "positive",
            "topic": "suction",
            "pain_points": [],
        },
        "tagging": {"tag_ids": [], "aspect_tag_ids": []},
    }
    row.update(overrides)
    return row


def _corpus() -> tuple[list[dict], list[dict]]:
    posts = [
        _post(),
        _post(
            post_id="p2",
            subreddit="baby",
            created_at_utc="2026-09-15T08:30:00+00:00",
            structural_coverage_grade="partial",
            count_completeness_status="observed",
            mentioned_brands=["momcozy", "elvie"],
            analysis={
                "sentiment_label": "positive",
                "topic": "suction",
                "pain_points": ["loud motor", "flange rub"],
            },
            tagging={"tag_ids": ["noise"], "aspect_tag_ids": ["noise"]},
        ),
        # Day-precision source: must be counted as "day", never imputed midnight.
        _post(
            post_id="p3",
            subreddit="Mom",
            created_at_utc="2026-10-20T00:00:00+00:00",
            event_time_precision="day",
            mentioned_brands=[],
            analysis={
                "sentiment_label": "neutral",
                "topic": "other",
                "pain_points": [],
            },
            tagging={"tag_ids": [], "aspect_tag_ids": []},
        ),
    ]
    comments = [
        _comment(),
        _comment(
            comment_id="c2",
            post_id="p2",
            include_in_voc_metrics=None,
            metric_eligibility_status="pending_base_projection",
            parent_link_status="unresolved_parent",
            tagging={"tag_ids": ["leaking"], "aspect_tag_ids": ["leaking"]},
            analysis={
                "sentiment_label": "negative",
                "topic": "leak",
                "pain_points": ["leaks overnight"],
            },
        ),
        _comment(
            comment_id="c3",
            post_id="p3",
            include_in_voc_metrics=False,
            analysis={
                "sentiment_label": "neutral",
                "topic": "other",
                "pain_points": [],
            },
        ),
    ]
    return posts, comments


def _dictionary() -> TagDictionary:
    return TagDictionary(
        [_rule("leaking"), _rule("noise", sentiment="positive")],
        version=DICTIONARY_VERSION,
    )


def _rule_payload() -> list[dict]:
    return _rule_dicts(_dictionary().rules)


def _both(posts, comments, counts=COUNTS):
    """Run both producers on identical inputs and return (canonical, standalone)."""
    dictionary = _dictionary()
    canonical = v3._aggregates(posts, comments, counts=counts, dictionary=dictionary)
    standalone = build_aggregates(
        posts,
        comments,
        counts=counts,
        tag_rules=_rule_payload(),
        dictionary_version=DICTIONARY_VERSION,
    )
    return canonical, standalone


def _assert_deeply_equal(canonical: dict, standalone: dict) -> None:
    if canonical == standalone:
        return
    differing = [
        key for key in sorted(set(canonical) | set(standalone))
        if canonical.get(key) != standalone.get(key)
    ]
    detail = {key: {"canonical": canonical.get(key), "standalone": standalone.get(key)}
              for key in differing}
    pytest.fail(f"aggregates producers diverge on {differing}: {detail!r}")


# ------------------------------------------------------------------ the contract

AGGREGATES_CASES = ["representative_corpus"]


def test_schema_versions_match() -> None:
    assert sa.AGGREGATES_SCHEMA == v3.AGGREGATES_SCHEMA


def test_metric_notes_identical_and_complete() -> None:
    canonical, standalone = _both(*_corpus())
    assert set(standalone["metric_notes"]) == {
        "brand_sample_mentions",
        "unresolved_parent_comments",
        "comments_in_voc_metrics",
        "time_precision",
        "tagging",
    }
    assert canonical["metric_notes"] == standalone["metric_notes"]


def test_producers_agree_on_representative_corpus() -> None:
    canonical, standalone = _both(*_corpus())
    _assert_deeply_equal(canonical, standalone)


def test_producers_agree_on_brand_heavy_corpus() -> None:
    posts, comments = _corpus()
    posts[0]["mentioned_brands"] = ["momcozy"] * 3 + ["elvie", "spectra"]
    posts[1]["mentioned_brands"] = []
    canonical, standalone = _both(posts, comments)
    _assert_deeply_equal(canonical, standalone)
    shares = {row["brand"]: row["sample_mention_share"]
              for row in standalone["brand_sample_mentions"]}
    # 3/5, 1/5, 1/5 — exactly representable decimals; pins the rounding rule
    # against accidental banker's-rounding or precision drift.
    assert shares["momcozy"] == 0.6
    assert shares["elvie"] == 0.2
    assert shares["spectra"] == 0.2


def test_top_tags_lists_aspect_tags_only_with_sentiment() -> None:
    """The four known divergences of the old second producer, each as its own pin.

    `tag_scope` was emitted where the client reads `tag_sentiment`, brand-scope
    tags were included, the list was truncated to 40, and the status fields were
    flat strings.
    """
    _, standalone = _both(*_corpus())
    top = standalone["tagging"]["top_tags"]
    assert [row["tag_id"] for row in top] == ["leaking", "noise"]
    # leaking: 1 post + 1 comment = 2 entities, ranked before noise (1+0).
    assert [row["total_entities"] for row in top] == [2, 1]
    for row in top:
        assert "tag_scope" not in row
        assert "tag_sentiment" in row
    by_id = {row["tag_id"]: row for row in top}
    assert by_id["leaking"]["tag_sentiment"] == "negative"
    assert by_id["noise"]["tag_sentiment"] == "positive"
    # Status fields are `{value: count}` maps, not single strings.
    assert standalone["count_completeness_status"] == {"observed": 3}
    assert standalone["parent_link_status"] == {"linked": 2, "unresolved_parent": 1}
    assert standalone["metric_eligibility_status"] == {
        "source_explicit": 2,
        "pending_base_projection": 1,
    }
    # The counts block passes through untouched.
    assert standalone["headline"]["stored_comments"] == COUNTS["stored_comments"]
    assert standalone["headline"]["unresolved_parent_comments"] == 7
    assert standalone["headline"]["quarantined_comments"] == 4
    assert standalone["headline"]["linked_comments"] == 3
    # Eligibility split drives the two headline counters.
    assert standalone["headline"]["comments_in_voc_metrics"] == 1
    assert standalone["headline"]["comments_metric_eligibility_pending_base_projection"] == 1


def test_monthly_posts_buckets_on_created_at_prefix() -> None:
    _, standalone = _both(*_corpus())
    # p1+p3 in October, p2 in September — bucketed on `created_at_utc[:7]`.
    assert standalone["monthly_posts"] == {"2026-09": 1, "2026-10": 2}


def test_time_precision_separates_day_from_instant() -> None:
    _, standalone = _both(*_corpus())
    assert standalone["time_precision"] == {
        "posts": {"day": 1, "instant": 2},
        "comments": {"instant": 3},
        "day_precision_midnight_imputed": False,
    }
    # Day-precision dates are never imputed to midnight anywhere in the payload.
    # (No row in the corpus carries an imputed 00:00:00+00:00 stamp under a
    # "day" precision flag.)


def test_subreddit_counters_keep_null_keys() -> None:
    """A NULL subreddit must survive as a key — canonical reads `row["subreddit"]`
    directly, so None lands in the Counter as a None key. The twin must do the
    same (folding it into the literal "unknown" was one of the 8 divergences)."""
    posts, comments = _corpus()
    posts[0]["subreddit"] = None
    comments[0]["subreddit"] = None
    canonical, standalone = _both(posts, comments)
    _assert_deeply_equal(canonical, standalone)
    assert standalone["subreddit_posts"] == {None: 1, "Mom": 1, "baby": 1}


def test_date_range_and_sentiment_maps() -> None:
    canonical, standalone = _both(*_corpus())
    assert standalone["date_range"] == {
        "posts": ["2026-09-15T08:30:00+00:00", "2026-10-20T00:00:00+00:00"],
        "comments": ["2026-10-02T09:00:00+00:00", "2026-10-02T09:00:00+00:00"],
    }
    assert canonical["post_sentiment"] == standalone["post_sentiment"] == {
        "negative": 1, "positive": 1, "neutral": 1,
    }
    assert canonical["comment_sentiment"] == standalone["comment_sentiment"] == {
        "positive": 1, "negative": 1, "neutral": 1,
    }


def test_producers_agree_on_canonical_key_order() -> None:
    """The client validates `time_precision` via JSON.stringify equality, which is
    key-order sensitive. Pin the canonical emission order of every nested object
    the frontend compares byte-for-byte."""
    canonical, standalone = _both(*_corpus())
    assert list(canonical["time_precision"].keys()) == [
        "posts", "comments", "day_precision_midnight_imputed",
    ]
    assert list(standalone["time_precision"].keys()) == list(
        canonical["time_precision"].keys()
    )
    assert list(standalone["headline"].keys()) == list(canonical["headline"].keys())
    assert list(standalone.keys()) == list(canonical.keys())


# --------------------------------------------- documented divergences (by design)

def test_canonical_crashes_on_missing_analysis_standalone_tolerates() -> None:
    """Documented divergence: canonical reads `row["analysis"][...]` directly and
    crashes on a record with no analysis block; the twin tolerates it (`_field`)
    so one bad record cannot kill the nightly run. Both behaviors are intended:
    the offline path fails loud, the nightly path degrades gracefully."""
    posts, comments = _corpus()
    del posts[0]["analysis"]
    with pytest.raises(KeyError):
        v3._aggregates(posts, comments, counts=COUNTS, dictionary=_dictionary())
    standalone = build_aggregates(
        posts, comments, counts=COUNTS,
        tag_rules=_rule_payload(),
        dictionary_version=DICTIONARY_VERSION,
    )
    assert standalone["headline"]["analysis_covered_posts"] == 3


def test_empty_corpus_standalone_returns_null_ranges() -> None:
    """Empty corpus: canonical crashes on min() of an empty list; the twin emits
    `date_range: {posts: None, comments: None}` so the nightly job can still
    publish an aggregates file for an (unlikely but possible) empty day."""
    canonical_diverges = False
    try:
        v3._aggregates([], [], counts=COUNTS, dictionary=_dictionary())
    except (ValueError, KeyError):
        canonical_diverges = True
    assert canonical_diverges, "canonical is expected to crash on an empty corpus"
    standalone = build_aggregates(
        [], [], counts=COUNTS,
        tag_rules=[], dictionary_version=DICTIONARY_VERSION,
    )
    assert standalone["date_range"] == {"posts": None, "comments": None}
    assert standalone["headline"]["unique_posts"] == 0
