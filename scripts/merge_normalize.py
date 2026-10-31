"""Normalize incrementally-merged records to the frozen public v3 contract.

The web client validates every post/comment against a strict schema
(`service.ts` → `validateSnapshotCore`). Records appended by the daily pipeline
come from a different producer (Apify) and must be reshaped to that contract, or
the whole workbench refuses to render. Everything here is derived from a record
that already passed validation, so the shape can never drift.
"""
from __future__ import annotations

from copy import deepcopy

import sys
from pathlib import Path


def _resolve_package_root() -> Path:
    """Locate the directory that CONTAINS the `reddit_voc` package.

    Two layouts must both work, and hardcoding either one breaks the other:

      repo   : <repo>/src/reddit_voc/...
      deploy : /opt/echo-agent-bot/reddit_voc/...   (no src/ directory at all)

    Hardcoding `parents[1]/src` (the repo layout) is how the production deploy
    raised ModuleNotFoundError for `reddit_voc.permalink` before. Walk up from this
    file and stop at the first directory whose parent holds `reddit_voc/`.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "reddit_voc").is_dir():
            return parent
        if (parent / "src" / "reddit_voc").is_dir():
            return parent / "src"
    return here.parents[1] / "src"


_PKG_ROOT = _resolve_package_root()
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from reddit_voc.permalink import (  # noqa: E402
    permalink_targets_entity,
    resolve_comment_permalink,
    resolve_post_permalink,
)

POST_SCHEMA_V3 = "reddit_voc_public_post_v3"
COMMENT_SCHEMA_V3 = "reddit_voc_public_comment_v3"
DICTIONARY_VERSION = "dim_tag_v6.3_final"
_CONTROLLED_BINDINGS = {
    "brand_unbound",
    "competitor_sentence_bound",
    "momcozy_entity_reviewed",
    "momcozy_sentence_bound",
    "multi_brand_context",
}

_BLANK_TAGGING = {
    "aspect_tag_ids": [],
    "brand_tag_ids": [],
    "dictionary_version": DICTIONARY_VERSION,
    "matches": [],
    "semantic_validation_status": "not_run",
    "tag_ids": [],
}


def _own_product_bindings(record: dict) -> list:
    """A record's own product bindings, never the template's.

    Same rule as `tagging`: a merged record's bindings must come from ITS OWN
    text. The previous code wrote a hardcoded `[]` here, which was safe but made
    the field permanently empty -- step3 could compute bindings and they were
    erased before the file was written. Taking the value from the record keeps
    that safety while letting a producer supply one.

    Non-list values become `[]` rather than propagating: the frontend validates
    every element against the nine-field contract and rejects the dataset on a
    mismatch, so a malformed value here would take the whole page down.
    """
    value = record.get("product_bindings")
    return value if isinstance(value, list) else []



def find_post_template(posts: list[dict]) -> dict | None:
    for post in reversed(posts):
        if post.get("schema_version") == POST_SCHEMA_V3:
            return post
    return None


def find_comment_template(comments: list[dict]) -> dict | None:
    for comment in reversed(comments):
        if comment.get("schema_version") == COMMENT_SCHEMA_V3:
            return comment
    return None


def _analysis_block(analysis) -> dict:
    return {
        "analysis_version": "local_rules_v1",
        "confidence": float(getattr(analysis, "confidence", 0.8) or 0.0),
        "pain_points": [str(pp) for pp in getattr(analysis, "pain_points", []) or []],
        "provider_call": False,
        "sentiment_label": str(getattr(analysis, "sentiment_label", "neutral")),
        "sentiment_score": float(getattr(analysis, "sentiment_score", 0.0) or 0.0),
        "severity": str(getattr(analysis, "severity", "low")),
        "topic": str(getattr(analysis, "topic", "other")),
    }


def normalize_post(record: dict, template: dict | None, analysis) -> dict:
    """Reshape one merged post onto the validated v3 post contract."""
    post = deepcopy(template) if template else {}
    created = record.get("created_at_utc") or ""
    post_id = str(record.get("post_id") or "")
    linked = int(record.get("linked_comment_count") or 0)
    grade = "partial" if linked > 0 else "post_only"
    permalink, permalink_basis = resolve_post_permalink(
        post_id=post_id,
        subreddit=record.get("subreddit"),
        permalink=record.get("permalink"),
        source_url=record.get("source_url"),
        recorded_basis=record.get("permalink_basis"),
    )

    post.update({
        "schema_version": POST_SCHEMA_V3,
        "post_id": post_id,
        "reddit_id": f"t3_{post_id}",
        "subreddit": record.get("subreddit") or "unknown",
        "title": record.get("title") or "",
        "content": record.get("content") or "",
        "score": float(record.get("score") or 0),
        "created_at_utc": created,
        "event_created_at_utc": created,
        "event_time_precision": "instant",
        "source_calendar_date": None,
        "author_pseudonym": None,
        "author_pseudonym_status": "suppressed_for_public_projection",
        "permalink": permalink or "",
        "permalink_basis": permalink_basis,
        "pii_redaction_flags": [],
        "product_bindings": _own_product_bindings(record),
        "evidence_id": f"post:{post_id}",
        "linked_comment_count": linked,
        "num_comments_reported": record.get("num_comments_reported"),
        "structural_coverage_grade": grade,
        "comment_coverage_status": grade,
        "count_completeness_status": "observed",
        "record_authority": "workbook_net_new",
        "title_basis": "source_title",
        "upvote_ratio": None,
        "brand_binding": record.get("brand_binding") or "brand_unbound",
        "mentioned_brands": record.get("mentioned_brands") or [],
        "include_in_voc_metrics": bool(record.get("include_in_voc_metrics")),
        "analysis": _analysis_block(analysis),
        "tagging": deepcopy(_BLANK_TAGGING),
    })
    return post


def normalize_comment(
    record: dict,
    template: dict | None,
    analysis,
    parent_binding: str,
    parent_permalink: str | None = None,
) -> dict:
    """Reshape one merged comment onto the validated v3 comment contract.

    A comment carries no permalink of its own in this corpus -- it points at its
    parent post, exactly as `v3_base_public` does for governed comments. Deriving it
    from the record's own field is what let 1,928 comments inherit a broken post URL.
    """
    comment = deepcopy(template) if template else {}
    created = record.get("created_at_utc") or ""
    comment_id = str(record.get("comment_id") or "")
    permalink, permalink_basis = resolve_comment_permalink(
        parent_permalink if parent_permalink is not None else record.get("permalink"),
        comment_id=str(record.get("comment_id") or "").removeprefix("t1_"),
        post_id=str(record.get("post_id") or "").removeprefix("t3_"),
        current=record.get("permalink"),
    )

    comment.update({
        "schema_version": COMMENT_SCHEMA_V3,
        "comment_id": comment_id,
        "reddit_id": f"t1_{comment_id}",
        "post_id": str(record.get("post_id") or ""),
        "body": record.get("body") or "",
        "score": float(record.get("score") or 0),
        "created_at_utc": created,
        "event_created_at_utc": created,
        "event_time_precision": "instant",
        "source_calendar_date": None,
        "author_pseudonym": None,
        "author_pseudonym_status": "suppressed_for_public_projection",
        "deleted_or_removed": False,
        "depth": int(record.get("depth") or 1),
        "parent_id": record.get("parent_id"),
        "parent_link_status": "linked",
        "permalink": permalink or "",
        "permalink_basis": permalink_basis,
        "pii_redaction_flags": [],
        "product_bindings": _own_product_bindings(record),
        "evidence_id": f"comment:{comment_id}",
        "is_bot": False,
        "record_authority": "workbook_net_new",
        "metric_eligibility_status": "source_explicit",
        "include_in_voc_metrics": False,
        "brand_binding": parent_binding if parent_binding in _CONTROLLED_BINDINGS else "brand_unbound",
        "mentioned_brands": record.get("mentioned_brands") or [],
        "subreddit": record.get("subreddit") or "unknown",
        "analysis": _analysis_block(analysis),
        "tagging": deepcopy(_BLANK_TAGGING),
    })
    return comment


def normalize_all(posts: list[dict], comments: list[dict]) -> int:
    """Re-normalize every pipeline-merged record already present in the corpus.

    Older runs wrote a partial shape; without this backfill those rows keep
    failing the client contract even after the producer is fixed.
    """
    post_tpl = find_post_template([p for p in posts if not p.get("run_id")])
    binding_by_post = {str(p.get("post_id")): p.get("brand_binding") for p in posts}
    fixed = 0

    for index, post in enumerate(posts):
        if not post.get("run_id"):
            continue
        created = post.get("created_at_utc") or ""
        if (
            post.get("schema_version") == POST_SCHEMA_V3
            and post.get("event_time_precision") == "instant"
            and post.get("event_created_at_utc") == created
            and post.get("source_calendar_date") is None
            and post.get("structural_coverage_grade") in {"full", "partial", "post_only", "source_observed"}
            and (post.get("tagging") or {}).get("semantic_validation_status") == "not_run"
            # A record that is otherwise well-formed but whose permalink names some
            # other post must still be rebuilt, otherwise the corruption this fixes
            # would be skipped forever by its own fast path.
            and permalink_targets_entity(post.get("permalink"), str(post.get("post_id") or ""))
        ):
            continue
        rebuilt = deepcopy(post_tpl) if post_tpl else {}
        rebuilt.update(post)
        created = post.get("created_at_utc") or ""
        post_id = str(post.get("post_id") or "")
        linked = int(post.get("linked_comment_count") or 0)
        grade = "partial" if linked > 0 else "post_only"
        # This block NEVER set `permalink`, so `deepcopy(post_tpl)` above left the
        # template's URL in place. That is how 159 merged posts came to share one
        # permalink. Recompute it here from the record's own identity.
        fixed_permalink, fixed_basis = resolve_post_permalink(
            post_id=post_id,
            subreddit=post.get("subreddit"),
            permalink=post.get("permalink"),
            source_url=post.get("source_url"),
            recorded_basis=post.get("permalink_basis"),
        )
        rebuilt.update({
            "schema_version": POST_SCHEMA_V3,
            "event_time_precision": "instant",
            "event_created_at_utc": created,
            "source_calendar_date": None,
            "author_pseudonym": None,
            "author_pseudonym_status": "suppressed_for_public_projection",
            "permalink": fixed_permalink or "",
            "permalink_basis": fixed_basis,
            "pii_redaction_flags": [],
            "product_bindings": _own_product_bindings(post),
            "evidence_id": f"post:{post_id}",
            "structural_coverage_grade": grade,
            "comment_coverage_status": grade,
            "count_completeness_status": "observed",
            "record_authority": "workbook_net_new",
            "title_basis": "source_title",
            "upvote_ratio": None,
        })
        analysis = post.get("analysis") or {}
        rebuilt["analysis"] = {
            "analysis_version": analysis.get("analysis_version", "local_rules_v1"),
            "confidence": float(analysis.get("confidence") or 0.0),
            "pain_points": [str(pp) for pp in analysis.get("pain_points") or []],
            "provider_call": False,
            "sentiment_label": str(analysis.get("sentiment_label") or "neutral"),
            "sentiment_score": float(analysis.get("sentiment_score") or 0.0),
            "severity": str(analysis.get("severity") or "low"),
            "topic": str(analysis.get("topic") or "other"),
        }
        # Template tag bleed: `deepcopy(post_tpl)` copies the template's tagging,
        # and a template whose tagging already carries `dictionary_version` kept
        # its aspect/brand tags + match records — so every appended post inherited
        # the template post's tags (aspect L0-GEN-171 etc., ~68/day of phantom
        # tagged posts). A merged record's tags must come from ITS OWN text, never
        # from the template; the pipeline-merged tagging is blank by contract.
        rebuilt["tagging"] = deepcopy(_BLANK_TAGGING)
        posts[index] = rebuilt
        binding_by_post[post_id] = rebuilt.get("brand_binding")
        fixed += 1

    # Aggregate counts are compared against per-post grades, so the whole corpus
    # must speak the same enum the client accepts.
    grade_map = {
        "thread_complete": "full",
        "full": "full",
        "observed_first_page": "partial",
        "partial": "partial",
        "source_rows_only": "source_observed",
        "source_observed": "source_observed",
        "post_only": "post_only",
    }
    # Apify reports communities as "r/Name"; the corpus (and the client, which
    # renders "r/" itself) expects the bare name.
    for record in posts + comments:
        subreddit = record.get("subreddit")
        if isinstance(subreddit, str) and subreddit.startswith("r/"):
            record["subreddit"] = subreddit[2:]
            fixed += 1

    for post in posts:
        raw_grade = post.get("structural_coverage_grade")
        mapped = grade_map.get(raw_grade or "", None)
        if mapped and mapped != raw_grade:
            post["structural_coverage_grade"] = mapped
            fixed += 1
        if post.get("structural_coverage_grade") == "source_observed":
            post["count_completeness_status"] = "source_rows_only"
            post["comment_coverage_status"] = "source_rows_only"

    comment_tpl = find_comment_template([c for c in comments if not c.get("run_id")])
    # A comment's permalink is its parent post's, so the post fixes must be visible
    # here -- build the map AFTER the post loop above.
    permalink_by_post = {str(p.get("post_id") or ""): p.get("permalink") for p in posts}
    for index, comment in enumerate(comments):
        if not comment.get("run_id"):
            continue
        created = comment.get("created_at_utc") or ""
        if (
            comment.get("schema_version") == COMMENT_SCHEMA_V3
            and comment.get("event_time_precision") == "instant"
            and comment.get("event_created_at_utc") == created
            and comment.get("source_calendar_date") is None
            and comment.get("metric_eligibility_status") == "source_explicit"
            # Same fast-path trap as posts: a correct-shaped comment pointing at a
            # broken parent URL would otherwise never be revisited.
            and permalink_targets_entity(
                comment.get("permalink"), str(comment.get("post_id") or "")
            )
        ):
            continue
        rebuilt = deepcopy(comment_tpl) if comment_tpl else {}
        rebuilt.update(comment)
        created = comment.get("created_at_utc") or ""
        comment_id = str(comment.get("comment_id") or "")
        parent_binding = binding_by_post.get(str(comment.get("post_id"))) or "brand_unbound"
        fixed_permalink, fixed_basis = resolve_comment_permalink(
            permalink_by_post.get(str(comment.get("post_id") or "")),
            comment_id=comment_id.removeprefix("t1_"),
            post_id=str(comment.get("post_id") or "").removeprefix("t3_"),
            current=comment.get("permalink"),
        )
        rebuilt.update({
            "schema_version": COMMENT_SCHEMA_V3,
            "event_time_precision": "instant",
            "event_created_at_utc": created,
            "source_calendar_date": None,
            "author_pseudonym": None,
            "author_pseudonym_status": "suppressed_for_public_projection",
            "deleted_or_removed": False,
            "depth": int(comment.get("depth") or 1),
            "parent_link_status": "linked",
            "permalink": fixed_permalink or "",
            "permalink_basis": fixed_basis,
            "pii_redaction_flags": [],
            "product_bindings": _own_product_bindings(comment),
            "evidence_id": f"comment:{comment_id}",
            "is_bot": False,
            "record_authority": "workbook_net_new",
            # Only records the pipeline itself created inherit the parent's binding.
            # Overwriting an existing governed binding would silently drop every
            # July comment_context_voc out of the metrics.
            "metric_eligibility_status": comment.get("metric_eligibility_status") or "source_explicit",
            "include_in_voc_metrics": comment.get("include_in_voc_metrics")
                if isinstance(comment.get("include_in_voc_metrics"), bool) else False,
            "brand_binding": (
                comment["brand_binding"]
                if comment.get("brand_binding") in _CONTROLLED_BINDINGS
                else parent_binding
            ),
        })
        analysis = comment.get("analysis") or {}
        rebuilt["analysis"] = {
            "analysis_version": analysis.get("analysis_version", "local_rules_v1"),
            "confidence": float(analysis.get("confidence") or 0.0),
            "pain_points": [str(pp) for pp in analysis.get("pain_points") or []],
            "provider_call": False,
            "sentiment_label": str(analysis.get("sentiment_label") or "neutral"),
            "sentiment_score": float(analysis.get("sentiment_score") or 0.0),
            "severity": str(analysis.get("severity") or "low"),
            "topic": str(analysis.get("topic") or "other"),
        }
        # Same template-bleed rule as posts: merged comments never inherit the
        # template's tags.
        rebuilt["tagging"] = deepcopy(_BLANK_TAGGING)
        comments[index] = rebuilt
        fixed += 1

    return fixed
