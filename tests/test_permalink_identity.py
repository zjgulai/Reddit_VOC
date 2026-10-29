"""Regression tests for permalink identity.

The published corpus carried 249 posts and 1,928 comments whose `permalink` did not
identify the record it was attached to. Three separate causes, all pinned here:

  A. `merge_normalize.normalize_all` rebuilt records from a template and never set
     `permalink`, so 159 pipeline-merged posts inherited ONE template URL
     (`.../r/Mom/comments/1v3v5m1/...`) -- including posts from other subreddits.
  B. `v3_base_public._governed_post_permalink` accepted any reddit host, so 90 rows
     published `https://i.redd.it/<hash>.jpeg` or `/gallery/<id>` as a source link.
  C. 4 July-import rows pointed at a neighbouring post's id.

Every assertion here is about *identity*: a permalink is valid only when its own
`/comments/<id>` segment equals the entity id. A wrong permalink is worse than a
missing one, because evidence clicks land on someone else's quote.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from reddit_voc.permalink import (  # noqa: E402
    BASIS_CANONICAL,
    BASIS_PARENT_POST,
    BASIS_SOURCE_PERMALINK,
    BASIS_SOURCE_URL,
    canonical_post_permalink,
    permalink_targets_entity,
    repair_permalinks,
    resolve_comment_permalink,
    resolve_post_permalink,
)


# --------------------------------------------------------------------------
# identity predicate
# --------------------------------------------------------------------------

def test_identifies_a_url_that_names_the_post() -> None:
    assert permalink_targets_entity(
        "https://www.reddit.com/r/Mom/comments/abc123/some_title/", "abc123"
    )


def test_rejects_a_url_naming_a_different_post() -> None:
    """The exact shape of the 159-row corruption: valid permalink, wrong post."""
    assert not permalink_targets_entity(
        "https://www.reddit.com/r/Mom/comments/1v3v5m1/is_electric_swing_safe/", "abc123"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://i.redd.it/7hmo1aejbh6h1.jpeg",
        "https://www.reddit.com/gallery/1tabnbt",
        "https://v.redd.it/qwmnn1d6zwah1",
        "",
        None,
    ],
)
def test_rejects_media_and_empty_urls(url) -> None:
    assert not permalink_targets_entity(url, "1tabnbt")


# --------------------------------------------------------------------------
# post resolution
# --------------------------------------------------------------------------

def test_self_identifying_permalink_is_preserved_verbatim() -> None:
    url = "https://www.reddit.com/r/Mom/comments/abc123/some_title/"
    assert resolve_post_permalink(post_id="abc123", subreddit="Mom", permalink=url) == (
        url,
        BASIS_SOURCE_PERMALINK,
    )


def test_media_url_is_replaced_with_canonical_identity() -> None:
    """Cause B: an image is not evidence of a thread."""
    resolved, basis = resolve_post_permalink(
        post_id="1tabnbt",
        subreddit="vinted",
        permalink="https://www.reddit.com/gallery/1tabnbt",
    )
    assert resolved == "https://www.reddit.com/r/vinted/comments/1tabnbt"
    assert basis == BASIS_CANONICAL


def test_neighbouring_post_permalink_is_replaced_not_trusted() -> None:
    """Cause C: a real permalink that names a different post must not survive."""
    resolved, basis = resolve_post_permalink(
        post_id="1ulwr3p",
        subreddit="parentsofmultiples",
        permalink="https://www.reddit.com/r/ExclusivelyPumping/comments/1uluztc/eufy_s1/",
    )
    assert "1ulwr3p" in resolved
    assert "1uluztc" not in resolved
    assert basis == BASIS_CANONICAL


def test_source_url_rescues_a_corrupted_permalink() -> None:
    """The 159 merged posts have a CORRECT source_url and a wrong permalink."""
    resolved, basis = resolve_post_permalink(
        post_id="1xfylhl",
        subreddit="BabyBumps",
        permalink="https://www.reddit.com/r/Mom/comments/1v3v5m1/is_electric_swing_safe/",
        source_url="https://www.reddit.com/r/BabyBumps/comments/1xfylhl/i_needed_a_diaper_pail/",
    )
    assert resolved == "https://www.reddit.com/r/BabyBumps/comments/1xfylhl/i_needed_a_diaper_pail/"
    assert basis == BASIS_SOURCE_URL


def test_subreddit_prefix_is_stripped_once() -> None:
    assert canonical_post_permalink("abc", "r/BabyBumps") == (
        "https://www.reddit.com/r/BabyBumps/comments/abc"
    )
    # "r/r/X" is malformed: one strip leaves "r/X", which still contains a slash.
    # Emitting "https://www.reddit.com/r/r/X/..." would be a link to nowhere, so the
    # contract is to emit nothing at all.
    assert canonical_post_permalink("abc", "r/r/X") is None


def test_no_subreddit_yields_no_permalink_rather_than_a_guess() -> None:
    """Publishing nothing is correct; publishing a wrong link is not."""
    resolved, _ = resolve_post_permalink(
        post_id="abc", subreddit="", permalink="https://i.redd.it/x.jpeg"
    )
    assert resolved is None


# --------------------------------------------------------------------------
# comment resolution
# --------------------------------------------------------------------------

def test_comment_inherits_parent_permalink() -> None:
    """Matches v3_base_public, which sets a governed comment's permalink to the post's."""
    resolved, basis = resolve_comment_permalink("https://www.reddit.com/r/Mom/comments/abc")
    assert resolved == "https://www.reddit.com/r/Mom/comments/abc"
    assert basis == BASIS_PARENT_POST


def test_comment_without_parent_has_no_permalink() -> None:
    assert resolve_comment_permalink(None) == (None, BASIS_PARENT_POST)


# --------------------------------------------------------------------------
# in-place repair
# --------------------------------------------------------------------------

def _corpus():
    posts = [
        # merged post with correct source_url but template-inherited permalink (cause A)
        {
            "post_id": "1xfylhl",
            "subreddit": "BabyBumps",
            "permalink": "https://www.reddit.com/r/Mom/comments/1v3v5m1/is_electric_swing_safe/",
            "source_url": "https://www.reddit.com/r/BabyBumps/comments/1xfylhl/i_needed/",
            "permalink_basis": "source_url",
            "record_authority": "workbook_net_new",
        },
        # July import publishing an image as its permalink (cause B)
        {
            "post_id": "1u26kf7",
            "subreddit": "babywearing",
            "permalink": "https://i.redd.it/7hmo1aejbh6h1.jpeg",
            "permalink_basis": "source_permalink",
            "record_authority": "governed_base",
            "title": "must survive",
        },
        # already correct
        {
            "post_id": "ok1",
            "subreddit": "Mom",
            "permalink": "https://www.reddit.com/r/Mom/comments/ok1/x/",
            "permalink_basis": "source_permalink",
        },
    ]
    comments = [
        {"comment_id": "t1_c1", "post_id": "1xfylhl",
         "permalink": "https://www.reddit.com/r/Mom/comments/1v3v5m1/is_electric_swing_safe/"},
        {"comment_id": "t1_c2", "post_id": "1u26kf7",
         "permalink": "https://i.redd.it/7hmo1aejbh6h1.jpeg"},
        {"comment_id": "t1_c3", "post_id": "ok1",
         "permalink": "https://www.reddit.com/r/Mom/comments/ok1/x/"},
        {"comment_id": "t1_c4", "post_id": "missing-post", "permalink": "https://x/y"},
    ]
    return posts, comments


def test_repair_fixes_every_broken_link() -> None:
    posts, comments = _corpus()
    stats = repair_permalinks(posts, comments)

    assert stats["posts_repaired"] == 2
    # c1 and c2 are repaired; c3 was already correct; c4's parent is absent from the
    # corpus, so it is counted as unfixable rather than silently rewritten.
    assert stats["comments_repaired"] == 2
    assert stats["comments_unfixable"] == 1


def test_repair_leaves_governance_untouched() -> None:
    """Rebuilding through the template would overwrite July-only governance fields."""
    posts, comments = _corpus()
    repair_permalinks(posts, comments)
    assert posts[1]["title"] == "must survive"
    assert posts[1]["record_authority"] == "governed_base"


def test_repair_only_touches_permalink_fields() -> None:
    posts, comments = _corpus()
    before = [dict(p) for p in posts]
    repair_permalinks(posts, comments)
    for old, new in zip(before, posts):
        changed = {k for k in new if old.get(k) != new.get(k)}
        assert changed <= {"permalink", "permalink_basis"}, changed


def test_repair_is_idempotent() -> None:
    posts, comments = _corpus()
    repair_permalinks(posts, comments)
    again = repair_permalinks(posts, comments)
    assert again["posts_repaired"] == 0
    assert again["comments_repaired"] == 0


def test_repair_never_leaves_a_link_to_another_post() -> None:
    posts, comments = _corpus()
    repair_permalinks(posts, comments)
    post_ids = {p["post_id"] for p in posts}
    for post in posts:
        assert permalink_targets_entity(post["permalink"], post["post_id"])
    for comment in comments:
        # A comment's permalink must name its PARENT POST, not itself.
        if comment["post_id"] in post_ids:
            assert permalink_targets_entity(comment["permalink"], comment["post_id"])


# --------------------------------------------------------------------------
# normalize_all must not skip the records it is meant to fix
# --------------------------------------------------------------------------

def test_normalize_all_rebuilds_a_record_whose_permalink_is_wrong() -> None:
    """The fast path skipped any well-formed record -- including all 159 corrupt ones.

    Before this, `normalize_all` returned 0 fixed records for a corpus that was
    schema-valid but permalink-wrong, so the corruption was permanent.
    """
    from merge_normalize import normalize_all

    template = {
        "schema_version": "reddit_voc_public_post_v3",
        "permalink": "https://www.reddit.com/r/Mom/comments/1v3v5m1/x/",
    }
    posts = [
        dict(template),  # template carrier: no run_id
        {
            "schema_version": "reddit_voc_public_post_v3",
            "post_id": "1xfylhl",
            "subreddit": "BabyBumps",
            "run_id": "run_1",
            "event_time_precision": "instant",
            "event_created_at_utc": "2026-10-01T00:00:00+00:00",
            "created_at_utc": "2026-10-01T00:00:00+00:00",
            "source_calendar_date": None,
            "structural_coverage_grade": "partial",
            "tagging": {"semantic_validation_status": "not_run"},
            "source_url": "https://www.reddit.com/r/BabyBumps/comments/1xfylhl/i_needed/",
            "permalink": "https://www.reddit.com/r/Mom/comments/1v3v5m1/x/",
        },
    ]
    fixed = normalize_all(posts, [])
    assert fixed >= 1
    assert "1xfylhl" in posts[1]["permalink"]
    assert "1v3v5m1" not in posts[1]["permalink"]
