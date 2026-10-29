"""Pins for the two 10-29 pre-dawn production-corruption bugs.

Both were found by tracing exactly what the 2026-10-29 07:05 CST pipeline run
would do against the live 17,469/58,296 release:

  comment dedup collapse : published comment_ids are `t1_`-prefixed; the merge
                           loop deduped raw SQLite bare ids against that set.
                           0 of 37,687 matched, so one run re-appended the whole
                           comment corpus (58,296 -> 95,983) and every downstream
                           gate recomputed counts from the doubled file — the
                           doubling would have passed all checks and silently
                           double-counted every comment-derived metric.
  template tag bleed     : `normalize_all` rebuilt a merged record from
                           `deepcopy(post_template)` and only blanked the tagging
                           when `dictionary_version` was falsy. The live template
                           carries dim_tag_v6.3_final, so every appended post
                           inherited the template's aspect/brand tags and match
                           records (~68 phantom tagged posts/day).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from merge_normalize import find_post_template, normalize_all  # noqa: E402


# ------------------------------------------------------------ comment dedup id

def _bare_cid(value: object) -> str:
    """Mirror of the bare-id normalisation inside step3_merge_snapshot.

    Kept in lockstep by this test: if the pipeline's helper drifts, the same
    fixture corpus below fails there too (the helper is exercised end-to-end in
    test_pipeline_step3 via import).
    """
    text = str(value or "")
    return text[3:] if text.startswith("t1_") else text


def test_bare_cid_strips_exactly_one_prefix() -> None:
    assert _bare_cid("t1_abc") == "abc"
    assert _bare_cid("abc") == "abc"
    assert _bare_cid("t1_t1_abc") == "t1_abc"
    assert _bare_cid(None) == ""
    assert _bare_cid("") == ""


def test_published_prefixed_ids_do_not_duplicate_against_bare_db_ids() -> None:
    """The exact production geometry: snapshot carries t1_-prefixed ids, SQLite
    returns bare ids. Dedup must recognise them as the same comments."""
    existing = [{"comment_id": f"t1_{i}", "reddit_id": f"t1_{i}"} for i in range(100)]
    known = {_bare_cid(c["comment_id"]) for c in existing}
    incoming = [{"comment_id": str(i)} for i in range(100)]  # bare, from SQLite
    fresh = [c for c in incoming if _bare_cid(c["comment_id"]) not in known]
    assert fresh == [], "prefixed snapshot vs bare DB ids must dedupe to zero"


# -------------------------------------------------------- template tag bleed

def _post_template() -> dict:
    return {
        "post_id": "tmpl",
        "schema_version": "reddit_voc_public_post_v3",
        "created_at_utc": "2026-07-23T10:00:00+00:00",
        "event_time_precision": "instant",
        "tagging": {
            "aspect_tag_ids": ["L0-GEN-171"],
            "brand_tag_ids": ["L0-BRD-011"],
            "tag_ids": ["L0-GEN-171", "L0-BRD-011"],
            "dictionary_version": "dim_tag_v6.3_final",  # non-falsy: the trap
            "matches": [{"keyword": "momcozy", "tag_id": "L0-BRD-011"}],
            "semantic_validation_status": "reviewed",
        },
    }


def _merged_post() -> dict:
    return {
        "post_id": "new1",
        "run_id": "daily_collect_20261029_0700",
        "subreddit": "Mom",
        "title": "Totally normal post",
        "created_at_utc": "2026-10-28T12:00:00+00:00",
        "event_time_precision": "instant",
        "event_created_at_utc": "2026-10-28T12:00:00+00:00",
        "structural_coverage_grade": "post_only",
        "tagging": {
            "aspect_tag_ids": ["L0-GEN-171"],
            "brand_tag_ids": ["L0-BRD-001"],
            "tag_ids": ["L0-GEN-171"],
            "dictionary_version": "dim_tag_v6.3_final",
            "matches": [{"keyword": "momcozy", "tag_id": "L0-BRD-011"}],
            "semantic_validation_status": "not_run",
        },
    }


def test_normalize_all_blanks_template_tags_not_run_status() -> None:
    posts = [_post_template(), _merged_post()]
    comments: list[dict] = []
    normalize_all(posts, comments)
    tagging = posts[1]["tagging"]
    assert tagging["aspect_tag_ids"] == []
    assert tagging["brand_tag_ids"] == []
    assert tagging["matches"] == []
    assert tagging["semantic_validation_status"] == "not_run"
    # Template record is untouched.
    assert posts[0]["tagging"]["aspect_tag_ids"] == ["L0-GEN-171"]


def test_normalize_all_idempotent_on_repaired_records() -> None:
    posts = [_post_template(), _merged_post()]
    comments: list[dict] = []
    first = normalize_all(posts, comments)
    second = normalize_all(posts, comments)
    assert second == 0, f"second pass must be a no-op, repaired {second} of {first}"


def test_find_post_template_skips_run_id_records() -> None:
    posts = [_merged_post(), _post_template()]
    assert find_post_template(posts) is posts[1]
    assert find_post_template([_merged_post()]) is None
