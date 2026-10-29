"""The one aggregates producer, self-contained.

There used to be two implementations and they disagreed on eight fields:

  `v3_base_public._aggregates`            canonical, used by the offline validator
  `recompute_derivatives.recompute_aggregates`  a hand-written rollup

The validator recomputes aggregates with the canonical rule and compares the whole
object for equality (`public_aggregates_recompute_mismatch`), so the second producer
could never pass. The divergences were not cosmetic:

  - `top_tags` listed only the top 40 ids, carried `tag_scope` instead of
    `tag_sentiment`, and indexed every tag instead of aspect tags only. Insights
    binds each promoted tag to this list and asserts the counts, so a promoted tag
    missing from the 40 breaks the Insights page.
  - `count_completeness_status`, `parent_link_status` and
    `metric_eligibility_status` were single strings instead of `{value: count}` maps.
  - `metric_notes` had 2 of the 5 required keys.
  - `monthly_posts` bucketed on the event date rather than `created_at_utc`.
  - `subreddit_*` folded a NULL subreddit into the literal string "unknown".

The reason a second producer ever existed: production runs a lean deployment with no
`v3_base_public` and no `tag_dictionary`, so the canonical code could not be
imported there. This module removes that excuse — it reproduces the canonical
projection with no dependency beyond the standard library, so one implementation can
serve both the full repo and the lean deployment.

Keep this in lockstep with `v3_base_public._aggregates`; test_site_aggregates.py
asserts they agree field for field.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

AGGREGATES_SCHEMA = "reddit_voc_site_aggregates_v3"

METRIC_NOTES = {
    "brand_sample_mentions": "定向样本品牌提及份额，不代表市场份额。",
    "unresolved_parent_comments": "待关联评论保留在守恒账本中，不进入帖子评论明细、搜索或帖子+评论 VOC 上下文。",
    "comments_in_voc_metrics": "仅计 canonical Base 已显式给出资格的评论；完整指标口径由受治理 metrics 数据集提供。",
    "time_precision": "日精度来源仅显示 YYYY-MM-DD，不补造 00:00 或时区。",
    "tagging": "Base 公开投影使用确定性本地规则补齐检索标签，标签仍为待语义复核状态。",
}


def _field(row: dict, *path: str, default: Any = None) -> Any:
    """Read a nested field without crashing the nightly run on one bad record."""
    value: Any = row
    for key in path:
        if not isinstance(value, dict):
            return default
        value = value.get(key)
    return default if value is None else value


def tag_summary(
    posts: list[dict],
    comments: list[dict],
    *,
    tag_rules: list[dict],
    dictionary_version: str,
) -> dict:
    """Count aspect tags and describe every one of them.

    Indexing `aspect_tag_ids` (not `tag_ids`) is deliberate: the client builds a
    `tag_id -> entry` map from this list and looks up promoted aspect tags. A list
    that also contains brand tags dilutes it and a truncated list omits entries.
    """
    rules = {str(rule.get("tag_id")): rule for rule in tag_rules or []}
    post_tags = Counter(
        tag_id for row in posts for tag_id in (_field(row, "tagging", "aspect_tag_ids", default=[]) or [])
    )
    comment_tags = Counter(
        tag_id for row in comments for tag_id in (_field(row, "tagging", "aspect_tag_ids", default=[]) or [])
    )
    all_ids = set(post_tags) | set(comment_tags)
    top_tags = []
    for tag_id in sorted(
        all_ids, key=lambda value: (-(post_tags[value] + comment_tags[value]), value)
    ):
        rule = rules.get(tag_id) or {}
        top_tags.append({
            "tag_id": tag_id,
            "name_cn": rule.get("name_cn") or tag_id,
            "name_en": rule.get("name_en") or tag_id,
            "theme": rule.get("theme") or "",
            "tag_sentiment": rule.get("sentiment") or "",
            "post_entities": post_tags[tag_id],
            "comment_entities": comment_tags[tag_id],
            "total_entities": post_tags[tag_id] + comment_tags[tag_id],
        })
    return {
        "dictionary_version": dictionary_version,
        "posts_with_rule_tags": sum(
            bool(_field(row, "tagging", "tag_ids", default=[])) for row in posts
        ),
        "comments_with_rule_tags": sum(
            bool(_field(row, "tagging", "tag_ids", default=[])) for row in comments
        ),
        "posts_with_aspect_tags": sum(
            bool(_field(row, "tagging", "aspect_tag_ids", default=[])) for row in posts
        ),
        "comments_with_aspect_tags": sum(
            bool(_field(row, "tagging", "aspect_tag_ids", default=[])) for row in comments
        ),
        "top_tags": top_tags,
    }


def build_aggregates(
    posts: list[dict],
    comments: list[dict],
    *,
    counts: dict,
    tag_rules: list[dict] | None = None,
    dictionary_version: str = "dim_tag_v6.3_final",
) -> dict:
    """Emit the complete public aggregates object.

    `counts` is the canonical counts block (posts / linked_comments /
    unresolved_parent_comments / quarantined_comments / stored_comments). It is
    passed in rather than recomputed so the headline and the manifest are guaranteed
    to agree — deriving them independently is what once produced
    "聚合隔离评论数与 manifest 不一致".
    """
    post_sentiment = Counter(_field(row, "analysis", "sentiment_label", default="neutral") for row in posts)
    comment_sentiment = Counter(_field(row, "analysis", "sentiment_label", default="neutral") for row in comments)
    post_topics = Counter(_field(row, "analysis", "topic", default="other") for row in posts)
    pain_points = Counter(
        point
        for row in [*posts, *comments]
        for point in (_field(row, "analysis", "pain_points", default=[]) or [])
    )
    subreddit_posts = Counter(row.get("subreddit") for row in posts)
    subreddit_comments = Counter(row.get("subreddit") for row in comments)
    monthly_posts = Counter(str(row.get("created_at_utc") or "")[:7] for row in posts)
    brand_mentions = Counter(
        brand for row in posts for brand in (row.get("mentioned_brands") or [])
    )
    total_brand_mentions = sum(brand_mentions.values())
    coverage = Counter(row.get("structural_coverage_grade") for row in posts)
    completeness = Counter(row.get("count_completeness_status") for row in posts)
    parent_status = Counter(row.get("parent_link_status") for row in comments)
    precision_posts = Counter(row.get("event_time_precision") for row in posts)
    precision_comments = Counter(row.get("event_time_precision") for row in comments)
    eligibility = Counter(row.get("metric_eligibility_status") for row in comments)
    tagging = tag_summary(
        posts, comments, tag_rules=tag_rules or [], dictionary_version=dictionary_version
    )

    post_dates = [str(row.get("created_at_utc") or "") for row in posts]
    comment_dates = [str(row.get("created_at_utc") or "") for row in comments]

    return {
        "schema_version": AGGREGATES_SCHEMA,
        "headline": {
            "unique_posts": len(posts),
            "stored_comments": counts["stored_comments"],
            "linked_comments": len(comments),
            "unresolved_parent_comments": counts["unresolved_parent_comments"],
            "quarantined_comments": counts["quarantined_comments"],
            "comments_in_voc_metrics": sum(
                row.get("include_in_voc_metrics") is True for row in comments
            ),
            "comments_metric_eligibility_pending_base_projection": sum(
                row.get("include_in_voc_metrics") is None for row in comments
            ),
            "analysis_covered_posts": len(posts),
            "analysis_covered_comments": len(comments),
            "posts_with_rule_tags": tagging["posts_with_rule_tags"],
            "comments_with_rule_tags_in_voc_metrics": sum(
                row.get("include_in_voc_metrics") is True
                and bool(_field(row, "tagging", "tag_ids", default=[]))
                for row in comments
            ),
            "posts_with_aspect_tags": tagging["posts_with_aspect_tags"],
            "comments_with_aspect_tags": tagging["comments_with_aspect_tags"],
        },
        "date_range": {
            "posts": [min(post_dates), max(post_dates)] if post_dates else None,
            "comments": [min(comment_dates), max(comment_dates)] if comment_dates else None,
        },
        "time_precision": {
            "posts": dict(sorted(precision_posts.items(), key=lambda kv: str(kv[0]))),
            "comments": dict(sorted(precision_comments.items(), key=lambda kv: str(kv[0]))),
            "day_precision_midnight_imputed": False,
        },
        "post_sentiment": dict(sorted(post_sentiment.items(), key=lambda kv: str(kv[0]))),
        "comment_sentiment": dict(sorted(comment_sentiment.items(), key=lambda kv: str(kv[0]))),
        "post_topics": dict(post_topics.most_common()),
        "pain_points": dict(pain_points.most_common()),
        "subreddit_posts": dict(subreddit_posts.most_common()),
        "subreddit_comments": dict(subreddit_comments.most_common()),
        "monthly_posts": dict(sorted(monthly_posts.items())),
        "brand_sample_mentions": [
            {
                "brand": brand,
                "posts": value,
                "sample_mention_share": (
                    round(value / total_brand_mentions, 6)
                    if total_brand_mentions else 0.0
                ),
            }
            for brand, value in brand_mentions.most_common()
        ],
        "coverage_grade": dict(sorted(coverage.items(), key=lambda kv: str(kv[0]))),
        "count_completeness_status": dict(sorted(completeness.items(), key=lambda kv: str(kv[0]))),
        "parent_link_status": dict(sorted(parent_status.items(), key=lambda kv: str(kv[0]))),
        "metric_eligibility_status": dict(sorted(eligibility.items(), key=lambda kv: str(kv[0]))),
        "tagging": tagging,
        "metric_notes": dict(METRIC_NOTES),
    }
