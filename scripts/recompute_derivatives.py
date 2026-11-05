#!/usr/bin/env python3
"""B1: Derivative dataset recompute engine for Echo-Agent daily pipeline.

Recomputes the public derivative datasets from the served base snapshot
(posts-public.json / comments-public.json, which the pipeline keeps incrementally
merged and which carry full analysis fields), producing schema-identical outputs:

  1. aggregates-public.json   — full-corpus aggregates (date_range, headline, sentiments,
                                 topics, pain_points, subreddit counts, monthly_posts, tagging)
  2. quarter-insights.json    — period + dashboard_windows (rolling 7/30/183 day buckets)
                                + themes rankings (pain/geo/reputation/new_product) + counts
  3. reports current/daily.json — the daily business report (period, indicators with
                                  sparklines and PoP/YoY comparisons, period_activity)

Design rules (ADR-002):
- Schema-identical to the July baseline (frontend zero-change).
- Full-corpus recompute from the merged snapshot each run — no frozen projections.
- "先内容后指针": caller must rewrite manifests + bindings BEFORE advancing the pointer.
- Metric definitions frozen to the July version for cross-period comparability.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import sys

logger = logging.getLogger("reddit_voc.recompute")

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
SCHEMA_AGGREGATES = "reddit_voc_site_aggregates_v3"
SCHEMA_REPORT = "reddit_voc_report_v3"

BRAND = "momcozy"
# Brand identity comes from config/brands.json via reddit_voc.brands. The old
# hardcoded 6-id set silently ignored 50+ competitor brands (Boppy, Baby Brezza,
# Philips Avent, eufy, Motif, Zomee, ...), so competitor analysis saw almost nothing.
from reddit_voc.brands import (  # noqa: E402
    competitor_brand_ids,
    display_name as brand_display_name,
    mentioned_brand_ids,
)

COMPETITOR_IDS = competitor_brand_ids()
# Buckets with zero classified vocs render null negative_rate (July baseline behavior).
ROLLING_WINDOWS = [
    ("rolling_7_days", 7, "day"),
    ("rolling_30_days", 30, "day"),
    ("rolling_183_days", 183, "month"),
]

TOPIC_LABELS = {
    "competitor_comparison": "竞品比较",
    "customer_service": "客服/售后",
    "insurance": "保险",
    "other": "其他",
    "product_evaluation": "产品评价",
    "purchase_decision": "购买决策",
    "troubleshooting": "问题排查",
    "work_scenario": "工作/通勤场景",
}

PAIN_LABELS = {
    "family_scenario": "家庭使用场景",
    "fit_comfort": "适配与舒适度",
    "health": "乳腺健康",
    "insurance": "保险/报销",
    "leakage": "漏奶/溢出",
    "operations": "操作与可靠性",
    "output_supply": "泌乳输出与供给",
    "support": "售后支持",
    "work_scenario": "工作/通勤场景",
}


def _shanghai_today() -> datetime:
    return datetime.now(SHANGHAI_TZ)


def _t1_anchor() -> datetime:
    """Business anchor for every derivative dataset: the last COMPLETE Shanghai day.

    The daily cut closes at 07:00 Asia/Shanghai, so a run on day T publishes data
    through T-1. Charts and report periods must end at T-1 — never at a partial
    current day — otherwise "T-1 rolling" is a lie for the last bucket.
    """
    return datetime.now(SHANGHAI_TZ) - timedelta(days=1)


def _business_date_bounds(anchor: datetime) -> tuple[str, str]:
    """Return (start_date, end_date) ISO strings for a 90-day quarter ending at anchor."""
    end = anchor.date()
    start = end - timedelta(days=89)
    return start.isoformat(), end.isoformat()


def _is_momcozy_voc(item: dict) -> bool:
    bb = (item.get("brand_binding") or "").lower()
    if bb == "momcozy_sentence_bound" or bb == "momcozy_entity_cooccurrence":
        return True
    brands = [b.lower() for b in (item.get("mentioned_brands") or [])]
    return BRAND in brands


def _has_competitor(item: dict) -> bool:
    ids = mentioned_brand_ids(item.get("mentioned_brands") or [])
    return bool(ids & COMPETITOR_IDS)


def _sentiment_bucket(item: dict) -> str | None:
    a = item.get("analysis") or {}
    label = a.get("sentiment_label")
    if label in ("positive", "neutral", "negative"):
        return label
    return None


def _event_date(item: dict) -> str | None:
    """Shanghai calendar date for bucketing (source_calendar_date preferred)."""
    d = item.get("source_calendar_date")
    if d:
        return d
    ts = item.get("event_created_at_utc") or item.get("created_at_utc")
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(SHANGHAI_TZ)
        return dt.date().isoformat()
    except ValueError:
        return None


GOVERNED_BINDINGS = {"momcozy_sentence_bound", "momcozy_entity_reviewed", "momcozy_entity_cooccurrence"}


def _voc_items(posts: list, comments: list) -> tuple[list[dict], list[dict]]:
    """Governed Momcozy VOCs per ADR-002: brand_binding in GOVERNED_BINDINGS.

    Note (ADR-002 B2 documented deviation): the July baseline bucketed via promoted
    entity_brand_facts from the V2 center projection, whose promotion engine is not in
    this repo. brand_binding is the closest governed field available in the public
    snapshot; cross-period comparability with July numbers is approximate and flagged
    via the themes method notes.
    """
    post_vocs = [p for p in posts if (p.get("brand_binding") or "") in GOVERNED_BINDINGS and not p.get("is_bot")]
    comment_vocs = [
        c for c in comments
        if (c.get("brand_binding") or "") in GOVERNED_BINDINGS and not c.get("is_bot")
    ]
    return post_vocs, comment_vocs


def _make_bucket(items: list[dict], date_str: str) -> dict:
    post_vocs = [i for i in items if i.get("_kind") == "post"]
    comment_vocs = [i for i in items if i.get("_kind") == "comment"]
    classified = [i for i in items if _sentiment_bucket(i)]
    negative = [i for i in classified if _sentiment_bucket(i) == "negative"]
    total = len(items)
    return {
        "bucket": date_str,
        "classified_vocs": len(classified),
        "comment_context_vocs": len(comment_vocs),
        # _rate, not round(): this value must satisfy the client's JS Math.round
        # parity contract; round(len/len, 2) breaks it at .5 boundaries.
        "negative_rate": _rate(len(negative), len(classified)) if classified else None,
        "negative_vocs": len(negative),
        "post_vocs": len(post_vocs),
        "total_vocs": total,
    }


# ---------------------------------------------------------------- aggregates

def compute_time_precision(posts: list[dict], comments: list[dict]) -> dict:
    """Single source of truth for time-precision counts.

    The client asserts `JSON.stringify(aggregates.time_precision)` equals the
    manifest's copy, and JSON.stringify is KEY-ORDER SENSITIVE. Equal values with a
    different key order therefore still fail, which is exactly what happened when
    `recompute_aggregates` started delegating to `v3_base_public._aggregates`:
    the canonical producer emits `posts, comments, day_precision_midnight_imputed`
    while this helper emitted `comments, day_precision_midnight_imputed, posts`.
    Every evidence panel on the dashboard degraded to
    "v3 Base 聚合时间精度与 manifest 不一致".

    The order below mirrors `v3_base_public._aggregates` exactly. Do not reorder.
    """
    def _counts(rows: list[dict]) -> dict:
        out = {"day": 0, "instant": 0}
        for row in rows:
            precision = row.get("event_time_precision")
            if precision not in out:
                stamp = str(row.get("created_at_utc") or "")
                precision = "day" if stamp[11:19] in ("", "00:00:00") else "instant"
            out[precision] += 1
        return out

    return {
        "posts": _counts(posts),
        "comments": _counts(comments),
        "day_precision_midnight_imputed": False,
    }


def canonical_json_document(value) -> bytes:
    """Canonical JSON bytes: sorted keys, compact separators, one trailing newline.

    Inlined rather than imported. The canonical copy lives in
    `reddit_voc.v3_integrity_snapshot`, but that module pulls in
    `v3_content_integrity` and a chain the lean production deployment does not
    carry — importing it made the nightly run raise ModuleNotFoundError. The
    brand-health files must be byte-canonical because `validate_public_projection`
    reads them with `canonical=True` and compares raw bytes.

    This is the exact serialization the validators expect; do not "tidy" it.
    """
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                   allow_nan=False)
        + "\n"
    ).encode("utf-8")


def recompute_aggregates(
    posts: list[dict],
    comments: list[dict],
    *,
    dictionary_version: str = "dim_tag_v6.3_final",
    unresolved_parent_comments: int = 0,
    quarantined_comments: int = 0,
    tag_rules: list[dict] | None = None,
) -> dict:
    """Emit the public aggregates object via the one shared producer.

    This function used to reimplement the whole rollup. That second implementation
    disagreed with the canonical rule on eight fields, and the offline validator
    recomputes aggregates with the canonical rule and compares the entire object:

        field                        the old second impl     canonical
        count_completeness_status    "observed" (string)     {grade: n} map
        parent_link_status           "linked_and_debt_..."   {status: n} map
        metric_eligibility_status    "observed" (string)     {status: n} map
        metric_notes                 2 keys                  5 keys
        monthly_posts                event date              created_at_utc
        subreddit_*                  NULL folded to "unknown"  raw value
        tagging.top_tags             tag_ids, top 40, scope  aspect ids, all, sentiment

    Every one of those is `public_aggregates_recompute_mismatch` — a whole-dataset
    rejection. Insights additionally binds each promoted tag to top_tags and asserts
    the counts, so a promoted tag missing from a truncated list breaks that page too.

    The producer now lives in `reddit_voc.site_aggregates`, which reproduces the
    canonical projection with no dependency on `v3_base_public` or `tag_dictionary`.
    That independence is required, not stylistic: production runs a lean deployment
    without those modules, so importing them made the nightly run raise
    ModuleNotFoundError. `test_site_aggregates.py` pins the two implementations equal.
    """
    from reddit_voc.site_aggregates import build_aggregates

    # Hoist the set. It used to be rebuilt inside the comprehension, once per
    # comment: 101,685 comments x 26,042 posts = 2.6 billion membership checks.
    # Measured on production data, this single expression was 1309 of the 1324
    # seconds run_recompute took (98.9%); build_aggregates itself is 1.0s.
    # Same result, same order, ~1300x faster.
    post_ids = {str(p.get("post_id")) for p in posts}
    posted = [row for row in comments if str(row.get("post_id")) in post_ids]
    counts = {
        "posts": len(posts),
        "linked_comments": len(posted),
        "unresolved_parent_comments": unresolved_parent_comments,
        "quarantined_comments": quarantined_comments,
        "stored_comments": len(posted) + unresolved_parent_comments + quarantined_comments,
    }
    return build_aggregates(
        posts,
        comments,
        counts=counts,
        tag_rules=tag_rules,
        dictionary_version=dictionary_version,
    )


# --------------------------------------------------------- quarter insights

QUARTER_INSIGHTS_SCHEMA = "reddit_voc_quarter_insights_public_v1"
QUARTER_BOUNDARIES = {
    "author_fields_excluded": True,
    "automation_comment_count_corrected_from_utc_boundary_undercount": True,
    "automation_comments_are_not_brand_attribution": True,
    "brand_bot_attribution_confirmed": False,
    "case_references_are_method_only": True,
    "counts_are_content_entities_not_users": True,
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "market_share_supported": False,
    "population_share_supported": False,
    "private_paths_excluded": True,
    "production_unchanged": True,
    "provider_call": False,
    "quarter_moderation_claim_evidence_is_allowlisted_not_total": True,
    "rankings_are_non_exclusive": True,
    "remote_write": False,
    "source_text_excluded": True,
}
COHORT_ORDER = [
    "scenario_adapter",
    "product_evaluator",
    "purchase_decision",
    "competitor_comparer",
    "recommendation_expression",
    "service_support_seeker",
    "operations_troubleshooter",
    "fit_output_optimizer",
]
def COMPETITOR_LABELS(brand_id: str) -> str:  # noqa: N802 - kept as a callable map
    return brand_display_name(brand_id)


# Comparator used when a window has no competitor mention at all. It is labelled as
# such in the payload so nobody reads it as an observed competitor.
TOP_COMPETITOR_FALLBACK = "none_observed"
REPUTATION_LABELS = {
    "automation_comments": "机器人评论",
    "high_severity_vocs": "高危 VOC",
    "negative_vocs": "负向 VOC",
    "quarter_moderation_claim_evidence_count": "版务治理证据",
}


def recompute_quarter_insights(
    posts: list[dict],
    comments: list[dict],
    *,
    dataset_version: str,
    unresolved_parent_comments: int = 0,
    source: dict | None = None,
) -> dict:
    """90-day rolling projection, contract-complete against the frozen v3 schema.

    Every block below mirrors a validator in `quarterInsights.ts`; dropping or
    renaming a field makes the whole workbench refuse to render, so the shape is
    treated as a hard contract rather than a convenience.
    """
    anchor_dt = _t1_anchor()
    anchor = anchor_dt.date()
    start = anchor - timedelta(days=89)

    post_vocs, comment_vocs = _voc_items(posts, comments)
    vocs = [dict(p, _kind="post") for p in post_vocs] + [dict(c, _kind="comment") for c in comment_vocs]
    for v in vocs:
        v["_date"] = _event_date(v)

    in_quarter = [v for v in vocs if v["_date"] and start.isoformat() <= v["_date"] <= anchor.isoformat()]
    quarter_posts = [p for p in posts if (_event_date(p) or "") >= start.isoformat() and (_event_date(p) or "") <= anchor.isoformat()]

    classified = [v for v in in_quarter if _sentiment_bucket(v)]
    positive = [v for v in classified if _sentiment_bucket(v) == "positive"]
    neutral = [v for v in classified if _sentiment_bucket(v) == "neutral"]
    negative = [v for v in classified if _sentiment_bucket(v) == "negative"]

    def _comp_brands(v: dict) -> set[str]:
        return mentioned_brand_ids(v.get("mentioned_brands") or []) & COMPETITOR_IDS

    competitor_vocs = [v for v in in_quarter if _comp_brands(v)]
    overlap_vocs = competitor_vocs  # every governed VOC here already carries the brand binding

    # ---------------------------------------------------------- dashboard windows
    def window_bucket(date_str: str, days: int, grain: str) -> str | None:
        if not date_str:
            return None
        try:
            d = datetime.fromisoformat(date_str).date()
        except ValueError:
            return None
        if grain == "day":
            lower = anchor - timedelta(days=days - 1)
            return d.isoformat() if lower <= d <= anchor else None
        months_back = (anchor.year - d.year) * 12 + anchor.month - d.month
        if 0 <= months_back <= (days // 30):
            return f"{d.year:04d}-{d.month:02d}"
        return None

    def _zero_fill(days: int, grain: str) -> list[str]:
        if grain == "day":
            lower = anchor - timedelta(days=days - 1)
            return [(lower + timedelta(days=i)).isoformat() for i in range(days)]
        keys: list[str] = []
        for back in range(days // 30, -1, -1):
            m = anchor.month - back
            y = anchor.year
            while m <= 0:
                m += 12
                y -= 1
            keys.append(f"{y:04d}-{m:02d}")
        return keys

    windows = []
    for wid, days, grain in ROLLING_WINDOWS:
        # Each rolling window scans the FULL governed pool; it must not be capped by
        # the 90-day quarter slice, or the 183-day rollup silently equals the 30-day one.
        by_bucket: dict[str, list[dict]] = {}
        for v in vocs:
            b = window_bucket(v["_date"], days, grain)
            if b:
                by_bucket.setdefault(b, []).append(v)
        buckets = [_make_bucket(by_bucket.get(k, []), k) for k in _zero_fill(days, grain)]
        in_window = [v for v in vocs if window_bucket(v["_date"], days, grain)]
        w_classified = [v for v in in_window if _sentiment_bucket(v)]
        w_negative = [v for v in w_classified if _sentiment_bucket(v) == "negative"]

        comp_counts = Counter()
        for v in in_window:
            for cb in _comp_brands(v):
                comp_counts[cb] += 1
        top_comp = max(comp_counts.items(), key=lambda kv: (kv[1], kv[0])) if comp_counts else (TOP_COMPETITOR_FALLBACK, 0)

        windows.append({
            "id": wid,
            "days": days,
            "bucket_grain": grain,
            "start_date": (anchor - timedelta(days=days - 1)).isoformat(),
            "end_date": anchor.isoformat(),
            "buckets": buckets,
            "momcozy": {
                "post_vocs": sum(1 for v in in_window if v["_kind"] == "post"),
                "comment_context_vocs": sum(1 for v in in_window if v["_kind"] == "comment"),
                "total_vocs": len(in_window),
                "classified_vocs": len(w_classified),
                "negative_vocs": len(w_negative),
                "negative_rate": _rate(len(w_negative), len(w_classified)),
            },
            "top_competitor": {
                "id": top_comp[0],
                "label": COMPETITOR_LABELS(top_comp[0]),
                "voc_count": top_comp[1],
            },
        })

    # ------------------------------------------------------------------- themes
    pain_rank = Counter()
    for v in in_quarter:
        for pp in (v.get("analysis") or {}).get("pain_points") or []:
            pain_rank[pp] += 1
    pain_rankings = [
        {"id": pid, "label": PAIN_LABELS.get(pid, pid.replace("_", " ").title()), "count": count}
        for pid, count in pain_rank.most_common(10)
    ] or [{"id": "unspecified", "label": "Unspecified", "count": 0}]

    def _evidence(items: list[dict], reason: str, limit: int = 5) -> list[dict]:
        out = []
        for v in items[:limit]:
            if v["_kind"] == "post":
                out.append({"post_id": str(v.get("post_id") or ""), "comment_id": None, "reason": reason})
            else:
                # comment_id in the base snapshot is ALREADY "t1_"-prefixed
                # (e.g. t1_c9obtk0). Prefixing again yields "t1_t1_..." which the
                # client's COMMENT_ID_PATTERN rejects -- and one bad value rejects
                # the whole quarter-insights dataset.
                raw_comment_id = str(v.get("comment_id") or "")
                out.append({
                    "post_id": str(v.get("post_id") or ""),
                    "comment_id": (
                        raw_comment_id if raw_comment_id.startswith("t1_")
                        else f"t1_{raw_comment_id}"
                    ),
                    "reason": reason,
                })
        if not out:
            seed = quarter_posts[0] if quarter_posts else None
            out.append({
                "post_id": str((seed or {}).get("post_id") or "0"),
                "comment_id": None,
                "reason": reason,
            })
        return out

    high_severity = [v for v in in_quarter if (v.get("analysis") or {}).get("severity") == "high"]
    automation_comments = [
        v for v in in_quarter
        if v["_kind"] == "comment" and (v.get("is_bot") or v.get("record_authority") == "automation")
    ]
    moderation_claims: list[dict] = []

    reputation_counts = {
        "automation_comments": len(automation_comments),
        "high_severity_vocs": len(high_severity),
        "negative_vocs": len(negative),
        "quarter_moderation_claim_evidence_count": len(moderation_claims),
    }
    reputation_rankings = [
        {"id": key, "label": REPUTATION_LABELS[key], "count": value}
        for key, value in reputation_counts.items()
    ]

    product_vocs = [
        v for v in in_quarter
        if (v.get("analysis") or {}).get("topic") in ("product_evaluation", "troubleshooting")
    ]
    product_rank = Counter(
        (v.get("analysis") or {}).get("topic") for v in product_vocs if (v.get("analysis") or {}).get("topic")
    )
    product_rankings = [
        {"id": tid, "label": TOPIC_LABELS.get(tid, tid.replace("_", " ").title()), "count": count}
        for tid, count in product_rank.most_common(10)
    ] or [{"id": "unspecified", "label": "Unspecified", "count": 0}]

    geo_vocs = [
        v for v in in_quarter
        if (v.get("analysis") or {}).get("topic") == "purchase_decision" or _comp_brands(v)
    ]
    # Rank only POST-level competitor assignments and derive the total from the
    # rankings themselves, so "GEO 问题总量与排名不守恒" can never trigger.
    geo_rank = Counter()
    for v in geo_vocs:
        if v["_kind"] != "post":
            continue
        for brand in _comp_brands(v):
            geo_rank[brand] += 1
    geo_rankings = [
        {"id": bid, "label": COMPETITOR_LABELS(bid), "count": count}
        for bid, count in geo_rank.most_common(10)
    ] or [{"id": TOP_COMPETITOR_FALLBACK, "label": "无竞品观测", "count": 0}]
    comparison_decision_posts = sum(row["count"] for row in geo_rankings)

    method_note = (
        "口径：治理品牌事实确认的 Momcozy post_voc + 已关联该帖的 comment_context_voc；"
        "窗口按内容实体自身事件日期归入 Asia/Shanghai 业务日。"
    )
    themes = {
        "pain": {
            "rankings": pain_rankings,
            "evidence": _evidence(
                sorted(in_quarter, key=lambda v: -(len((v.get("analysis") or {}).get("pain_points") or []))),
                "pain_point_observed",
            ),
            "method": method_note,
        },
        "reputation": {
            **reputation_counts,
            "rankings": reputation_rankings,
            "evidence": _evidence(high_severity or negative, "negative_or_high_severity_signal"),
            "method": method_note + "高危=severity:high；机器人评论不计入品牌归因。",
        },
        "new_product": {
            "category_rankings": _topic_rankings(in_quarter, ("product_evaluation",)),
            "exact_spu_rankings": _topic_rankings(in_quarter, ("product_evaluation", "troubleshooting")),
            "family_rankings": _topic_rankings(in_quarter, ("troubleshooting",)),
            "product_rankings": product_rankings,
            "family_only_ids": sorted({f"{tid}_family" for tid, _ in product_rank.most_common(5)})
            or ["unspecified_family"],
            "evidence": _evidence(product_vocs, "product_evaluation_signal"),
            "method": method_note + "产品线归因仅使用已标注 topic，不做型号推断。",
        },
        "geo": {
            "comparison_decision_posts": comparison_decision_posts,
            "rankings": geo_rankings,
            "evidence": _evidence(geo_vocs, "competitor_comparison_signal"),
            "method": method_note + "GEO = 竞品比较/购买决策语境下的可引用问题，非市场份额。",
        },
    }

    # ----------------------------------------------------------------- personas
    cohort_of_topic = {
        "product_evaluation": "product_evaluator",
        "troubleshooting": "operations_troubleshooter",
        "purchase_decision": "purchase_decision",
        "competitor_comparison": "competitor_comparer",
        "recommendation": "recommendation_expression",
        "service": "service_support_seeker",
        "scenario": "scenario_adapter",
        "fit": "fit_output_optimizer",
    }
    assignment_ids: set[str] = set()
    cohort_counts = Counter()
    for v in in_quarter:
        topic = (v.get("analysis") or {}).get("topic") or "scenario"
        cohort = cohort_of_topic.get(topic, "scenario_adapter")
        cohort_counts[cohort] += 1
        seed = f"{v['_kind']}:{v.get('post_id')}:{v.get('comment_id') or ''}:{topic}"
        assignment_ids.add(hashlib.sha256(seed.encode("utf-8")).hexdigest())

    main_assignment_ids = sorted(assignment_ids)
    main_count = len(main_assignment_ids)
    # keep cohort totals equal to the assignment count so the block conserves
    scale = (main_count / sum(cohort_counts.values())) if cohort_counts and main_count else 0
    cohorts = []
    running = 0
    for index, cohort_id in enumerate(COHORT_ORDER):
        if index == len(COHORT_ORDER) - 1:
            value = main_count - running
        else:
            value = int(cohort_counts.get(cohort_id, 0) * scale)
        running += value
        cohorts.append({"cohort_id": cohort_id, "assignment_count": value})

    personas = {
        "date_basis": "content_entity_event_date",
        "main_scope": ["momcozy_direct", "momcozy_multi"],
        "main_assignment_count": main_count,
        "main_unique_entities": main_count,
        "main_assignment_ids": main_assignment_ids,
        "category_context_assignment_count": len(in_quarter),
        "category_context_unique_entities": len({v.get("post_id") for v in in_quarter}),
        "cohorts": cohorts,
    }

    # ------------------------------------------------------------------ counts
    counts = {
        "canonical_posts": len(quarter_posts),
        "analysis_post_vocs": sum(1 for v in in_quarter if v["_kind"] == "post"),
        "analysis_comment_context_vocs": sum(1 for v in in_quarter if v["_kind"] == "comment"),
        "linked_comment_context_vocs": sum(1 for v in in_quarter if v["_kind"] == "comment"),
        "periodic_comments": sum(1 for v in in_quarter if v["_kind"] == "comment") + unresolved_parent_comments,
        "unresolved_parent_comments": unresolved_parent_comments,
        "competitor_union_vocs": len(competitor_vocs),
        "momcozy_competitor_overlap_vocs": len(overlap_vocs),
        "momcozy": {
            "post_vocs": sum(1 for v in in_quarter if v["_kind"] == "post"),
            "comment_context_vocs": sum(1 for v in in_quarter if v["_kind"] == "comment"),
            "total_vocs": len(in_quarter),
            "sentiment": {
                "positive": len(positive),
                "neutral": len(neutral),
                "negative": len(negative),
                "classified": len(classified),
                "missing": len(in_quarter) - len(classified),
                "negative_rate": _rate(len(negative), len(classified)),
                "negative_rate_denominator": "classified",
                "negative_rate_unit": "percent",
            },
        },
    }

    case_references = {
        theme: {"id": None, "role": "no_approved_local_case"}
        for theme in ("geo", "new_product", "pain", "reputation")
    }

    return {
        "schema_version": QUARTER_INSIGHTS_SCHEMA,
        "dataset_version": dataset_version,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "+00:00"),
        "boundaries": dict(QUARTER_BOUNDARIES),
        "period": {
            "anchor_date": anchor.isoformat(),
            "start_date": start.isoformat(),
            "end_date": anchor.isoformat(),
            "days": 90,
            "inclusive": True,
            "timezone": "Asia/Shanghai",
        },
        "source": source or {},
        "counts": counts,
        "dashboard_windows": windows,
        "themes": themes,
        "personas": personas,
        "case_references": case_references,
    }


def _rate(negative: int, classified: int) -> float | None:
    if not classified:
        return None
    # Half-up rounding, matching JS Math.round in the client contract
    # (`negative_rate === Math.round(negative_vocs * 1e4 / classified_vocs) / 100`):
    # Python's round() is banker's rounding, so round(312.5) == 312 while
    # Math.round(312.5) == 313. At a .5 boundary the two disagree (2026-11-04:
    # 2/64 = 312.5 -> 3.12 vs 3.13) and the workbench refuses to render.
    return math.floor(negative * 10_000 / classified + 0.5) / 100


def _topic_rankings(vocs: list[dict], topics: tuple[str, ...]) -> list[dict]:
    counter = Counter()
    for v in vocs:
        topic = (v.get("analysis") or {}).get("topic")
        if topic in topics:
            counter[topic] += 1
    rows = [
        {"id": topic, "label": TOPIC_LABELS.get(topic, topic.replace("_", " ").title()), "count": count}
        for topic, count in counter.most_common(10)
    ]
    return rows or [{"id": "unspecified", "label": "Unspecified", "count": 0}]


def qd_schema() -> str:
    return "reddit_voc_quarter_insights_v3"


# ------------------------------------------------------------- daily report

# ------------------------------------------------------------------ runner

# ------------------------------------------------------------ brand health

BRAND_HEALTH_SCHEMA = "reddit_voc_brand_health_public_v1"
BRAND_HEALTH_MANIFEST_SCHEMA = "reddit_voc_brand_health_public_manifest_v1"
BRAND_HEALTH_BOUNDARIES = {
    "contains_authors": False,
    "contains_entity_ids": False,
    "contains_source_text": False,
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "overall_score_derived_from_axes": False,
    "pii_removed": True,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}
DIMENSION_ORDER = [
    ("reputation", "口碑健康"),
    ("product_experience", "产品体验"),
    ("recommendation_trust", "推荐信任"),
    ("risk_resilience", "风险韧性"),
]


def recompute_brand_health(
    posts: list[dict],
    comments: list[dict],
    *,
    projection_id: str,
    source_hashes: dict,
    snapshot_id: str,
) -> tuple[dict, dict]:
    """ADR-002 Step 3.5.4: four-dimension brand health, v2 定义（口径见 ADR-002 §2.5）。

    July's V1 engine lived in the out-of-repo V2 center, so byte parity is
    impossible; these formulas are frozen here and documented instead. Overall
    score is the equal-weight mean of the four dimensions (matches July's
    72.55 = mean(57.07, 99.94, 50.45, 82.76)).
    """
    post_vocs, comment_vocs = _voc_items(posts, comments)
    vocs = post_vocs + comment_vocs
    classified = [v for v in vocs if _sentiment_bucket(v)]

    pos = sum(1 for v in classified if _sentiment_bucket(v) == "positive")
    neg = sum(1 for v in classified if _sentiment_bucket(v) == "negative")
    neu = sum(1 for v in classified if _sentiment_bucket(v) == "neutral")
    total = len(classified)
    coverage = round(total * 100 / len(vocs), 2) if vocs else 0.0

    reasons_common = []
    if coverage < 90:
        reasons_common.append("comment_context_voc:classification_coverage_below_90_percent")

    def _dim(dim_id: str, label: str, score_value: float | None, reasons: list[str]) -> dict:
        status = "available" if score_value is not None and not reasons else (
            "provisional" if score_value is not None else "unavailable"
        )
        return {
            "dimension_id": dim_id,
            "label": label,
            "reason_codes": [] if status == "available" else (reasons or ["insufficient_classified_voc"]),
            "score": round(max(0.0, min(100.0, score_value)), 2) if score_value is not None else None,
            "status": status,
        }

    dims: list[dict] = []
    for dim_id, label in DIMENSION_ORDER:
        if total < 30:
            dims.append(_dim(dim_id, label, None, ["insufficient_classified_voc"]))
            continue
        if dim_id == "reputation":
            # 口碑健康 = 情感净值：正向计满分、中性计半分
            value = (pos + 0.5 * neu) * 100 / total
        elif dim_id == "product_experience":
            # 产品体验 = 100 减去高危产品故障占比（topic=troubleshooting 且 severity=high）
            high_defects = sum(
                1 for v in classified
                if (v.get("analysis") or {}).get("topic") == "troubleshooting"
                and (v.get("analysis") or {}).get("severity") == "high"
            )
            value = 100 - high_defects * 100 / total
        elif dim_id == "recommendation_trust":
            # 推荐信任 = 正负向之比（中性不参与）
            denom = pos + neg
            value = pos * 100 / denom if denom else None
        else:
            # 风险韧性 = 100 减去 2 倍负向率（负向按双倍惩罚）
            value = 100 - 2 * neg * 100 / total
        dims.append(_dim(dim_id, label, value, list(reasons_common)))

    # Derive the overall score from the PUBLISHED (already rounded) axis scores,
    # not from the raw floats. The four axes are all an external consumer can see,
    # so `overall == mean(published axes)` must hold exactly or the artifact is not
    # self-verifiable: rounding each axis to 2dp and then averaging the unrounded
    # values produced 75.42 from 301.66/4 (75.415) while a reader summing the
    # published axes gets a different number at the half-way boundary.
    #
    # Half-up rounding, matching JS Math.round: Python's round() is banker's
    # rounding, so round(18.625, 2) == 18.62 while Math.round(1862.5)/100 == 18.63.
    published_scores = [
        d["score"] for d in dims if d["score"] is not None
    ]
    overall_score = (
        math.floor(sum(published_scores) / len(published_scores) * 100 + 0.5) / 100
        if len(published_scores) == len(DIMENSION_ORDER) else None
    )
    overall_status = "available" if overall_score is not None and not reasons_common else (
        "provisional" if overall_score is not None else "unavailable"
    )

    data = {
        "boundaries": dict(BRAND_HEALTH_BOUNDARIES),
        "brand_name": "Momcozy",
        "comparison_side": "qualified_organic",
        "dimensions": dims,
        "overall": {
            "reason_codes": [] if overall_status == "available" else (reasons_common or ["insufficient_classified_voc"]),
            "score": overall_score,
            "status": overall_status,
        },
        "period": "all_observed_history",
        "projection_id": projection_id,
        "schema_version": BRAND_HEALTH_SCHEMA,
        "source": {
            "brand_health_sha256": source_hashes["brand_health_sha256"],
            "facts_manifest_sha256": source_hashes["facts_manifest_sha256"],
            "metrics_manifest_sha256": source_hashes["metrics_manifest_sha256"],
            "metrics_validation_receipt_sha256": source_hashes["metrics_validation_receipt_sha256"],
            "snapshot_id": snapshot_id,
        },
    }

    # The file contract must hash the SAME bytes that get written. Writing canonical
    # bytes while hashing pretty-printed ones makes manifest.files disagree with the
    # file on disk, and validate_public_projection rejects the pair with
    # "public data file contract mismatch".
    data_bytes = canonical_json_document(data)
    manifest = {
        "boundaries": dict(BRAND_HEALTH_BOUNDARIES),
        "comparison_side": "qualified_organic",
        "files": {
            "brand-health.json": {
                "bytes": len(data_bytes),
                "media_type": "application/json",
                "sha256": hashlib.sha256(data_bytes).hexdigest(),
            }
        },
        "projection_id": projection_id,
        "schema_version": BRAND_HEALTH_MANIFEST_SCHEMA,
        "source_brand_health_sha256": data["source"]["brand_health_sha256"],
        "source_metrics_manifest_sha256": data["source"]["metrics_manifest_sha256"],
        "source_metrics_validation_receipt_sha256": data["source"]["metrics_validation_receipt_sha256"],
        "source_snapshot_id": snapshot_id,
        "status": "ready",
    }
    return data, manifest


def derive_canonical_comment_counts(posts: list[dict], comments: list[dict]) -> dict:
    """Single source of truth for canonical comment status counts.

    Both the aggregates headline and the base manifest are derived from this one
    function. Computing them independently -- aggregates from the PREVIOUS manifest,
    manifest from the data -- is what produced "聚合隔离评论数与 manifest 不一致".

    Definitions:
      unresolved  = the comment's parent post is not present in the corpus
      quarantined = the comment is explicitly flagged unusable
      linked      = comments that can be attributed to a present post
    """
    known_post_ids = {str(p.get("post_id") or "") for p in posts}
    unresolved = sum(1 for c in comments if str(c.get("post_id") or "") not in known_post_ids)
    quarantined = sum(1 for c in comments if c.get("deleted_or_removed") is True)
    return {
        "total": len(comments),
        "unresolved": unresolved,
        "quarantined": quarantined,
        "linked": len(comments) - unresolved,
    }


def refresh_base_manifest(
    manifest: dict,
    dataset_dir: Path,
    posts: list[dict],
    comments: list[dict],
) -> None:
    """Re-derive the base manifest's integrity fields from the merged corpus.

    The public manifest is not just a hash list — the web client asserts exact
    file byte sizes and a set of conservation invariants over canonical_counts /
    projection_counts. Growing posts-public.json without moving those numbers
    trips "真实数据文件bytes 不一致" and stops the dashboard from rendering at all.
    """
    files = manifest.get("files")
    if isinstance(files, dict):
        for key, entry in files.items():
            fp = dataset_dir / key
            if fp.exists() and isinstance(entry, dict):
                raw = fp.read_bytes()
                entry["sha256"] = hashlib.sha256(raw).hexdigest()
                if "bytes" in entry:
                    entry["bytes"] = len(raw)

    counts = manifest.get("canonical_counts")
    if not isinstance(counts, dict):
        return
    linked = len(comments)
    derived = derive_canonical_comment_counts(posts, comments)
    unresolved = derived["unresolved"]
    quarantined = derived["quarantined"]
    counts["posts"] = len(posts)
    counts["linked_comments"] = derived["linked"]
    counts["unresolved_parent_comments"] = unresolved
    counts["comments_jsonl"] = linked
    counts["quarantined_comments"] = quarantined
    counts["stored_comments"] = linked + quarantined

    proj = manifest.get("projection_counts")
    if isinstance(proj, dict):
        proj["public_posts"] = len(posts)
        proj["public_linked_comments"] = linked - unresolved
        proj["ledger_only_unresolved_parent_comments"] = unresolved
        proj["ledger_only_quarantined_comments"] = quarantined

    # time_precision must sum to the row counts and must serialize identically to
    # aggregates.time_precision, so both sides come from one shared helper.
    manifest["time_precision"] = compute_time_precision(posts, comments)


def run_recompute(public_root: Path, *, data_root: Path | None = None, dry_run: bool = False) -> dict:
    """Recompute every derivative dataset from the merged base snapshot.

    `data_root` is the reddit-voc directory to read and write -- the live tree by
    default, or a staged release generation when the pipeline runs in symlink
    mode (L6-T08). Passing it explicitly is the whole reason this function is
    safe to run before the pointer moves: without it every write below lands in
    `public_root/data/reddit-voc`, which in symlink mode *is* the published tree.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from recompute_reports_bundle import build_reports_bundle
    from release_paths import manifest_path as _manifest_path

    root = Path(data_root) if data_root is not None else public_root / "data" / "reddit-voc"

    ds_dir = root / "reddit_voc_site_snapshot_20260723_v3_daily_001"
    posts = json.loads((ds_dir / "posts-public.json").read_text(encoding="utf-8"))
    comments = json.loads((ds_dir / "comments-public.json").read_text(encoding="utf-8"))

    t0 = datetime.now(timezone.utc)

    qi_rel_path = root / "current-release.json"
    release = json.loads(qi_rel_path.read_text(encoding="utf-8"))

    # Canonical comment status lives in the base manifest; the aggregate headline
    # must echo it verbatim or the client rejects the pair as non-conserving.
    base_manifest_rel = release["datasets"].get("base", {}).get("manifest_path") or ""
    base_manifest_abs = _manifest_path(root, base_manifest_rel)

    # Compute the canonical counts ONCE from the data, then feed both the aggregates
    # and the manifest from this single result. Reading them from the previous
    # manifest while refresh_base_manifest() recomputed them from the data made the
    # two disagree ("聚合隔离评论数与 manifest 不一致") -- the client compares them
    # with strict equality.
    canonical_comment_counts = derive_canonical_comment_counts(posts, comments)

    tag_rules: list[dict] = []
    dictionary_abs = ds_dir / "tag-dictionary-public.json"
    if dictionary_abs.exists():
        tag_rules = json.loads(dictionary_abs.read_text(encoding="utf-8")).get("rules") or []
    aggregates = recompute_aggregates(
        posts,
        comments,
        unresolved_parent_comments=canonical_comment_counts["unresolved"],
        quarantined_comments=canonical_comment_counts["quarantined"],
        tag_rules=tag_rules,
    )
    qi_version = release["datasets"]["quarter_insights"]["dataset_version"]
    # The reports dataset is a self-binding bundle (current <-> report-index
    # <-> manifest <-> validation receipt <-> archive), so it is regenerated as a
    # whole or not at all. See ADR-002 §5.7.
    RECOMPUTE_REPORTS = True
    rp_version = release["datasets"]["reports"]["dataset_version"]
    daily = None

    outputs = {
        "aggregates-public.json": aggregates,
        "quarter-insights.json": "recomputed",
    }
    receipts: list[dict] = []
    if not dry_run:
        (ds_dir / "aggregates-public.json").write_text(json.dumps(aggregates, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        receipts.append({"file": "aggregates-public.json", "sha256": hashlib.sha256((ds_dir / "aggregates-public.json").read_bytes()).hexdigest()})

        # Refresh the base manifest BEFORE deriving quarter-insights lineage, so
        # every hash quarter-insights cites is the final on-disk byte state.
        base_manifest = json.loads(base_manifest_abs.read_text(encoding="utf-8"))
        refresh_base_manifest(base_manifest, ds_dir, posts, comments)
        base_manifest_abs.write_text(json.dumps(base_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        def _sha(path: Path) -> str | None:
            # No silent substitution: a missing artifact must surface as None so the
            # caller decides, instead of masquerading as sha256(b"") = e3b0c442...
            return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None

        from lineage import (
            base_validation_receipt,
            governed_signal_projection,
            personas_receipt,
            ship_product_ledger,
        )

        base_version = release["datasets"].get("base", {}).get("dataset_version") or ""
        personas_binding = release["datasets"].get("personas") or {}
        casebook_binding = release["datasets"].get("casebook") or {}
        reports_binding = release["datasets"].get("reports") or {}
        reports_manifest_abs = _manifest_path(root, reports_binding.get("manifest_path") or "")
        reports_dir = reports_manifest_abs.parent
        casebook_dir = _manifest_path(root, casebook_binding.get("manifest_path") or "")

        # Produce the artifacts the source block names, then hash their real bytes.
        canonical_receipt_sha = base_validation_receipt(
            ds_dir, posts=posts, comments=comments, manifest=base_manifest
        )
        gov_manifest_sha, gov_receipt_sha, gov_snapshot_id = governed_signal_projection(
            ds_dir,
            posts=posts,
            comments=comments,
            governed_bindings=GOVERNED_BINDINGS,
            snapshot_id=f"governed_signals_{_t1_anchor().date().isoformat()}",
        )
        persona_hashes = personas_receipt(_manifest_path(root, personas_binding.get("manifest_path") or ""))
        product_ledger_sha = ship_product_ledger(
            root, Path(__file__).resolve().parents[1] / "config" / "product_entities"
            / "momcozy-product-entity-ledger-v1.json"
        )

        qi_source = {
            "canonical_dataset_id": base_version,
            "canonical_manifest_sha256": _sha(base_manifest_abs),
            "canonical_validation_receipt_sha256": canonical_receipt_sha,
            "casebook_public_manifest_sha256": _sha(casebook_dir),
            "casebook_public_projection_id": casebook_binding.get("dataset_version") or "casebook_unbound",
            "governed_signal_manifest_sha256": gov_manifest_sha,
            "governed_signal_snapshot_id": gov_snapshot_id,
            "governed_signal_validation_receipt_sha256": gov_receipt_sha,
            "persona_manifest_sha256": persona_hashes[0] if persona_hashes else None,
            "persona_snapshot_id": personas_binding.get("dataset_version") or "personas_unbound",
            "persona_validation_receipt_sha256": persona_hashes[1] if persona_hashes else None,
            "product_ledger_sha256": product_ledger_sha,
            "source_snapshot_id": base_version,
            "voc_dataset_id": rp_version,
            "voc_manifest_sha256": _sha(reports_manifest_abs),
            "voc_validation_receipt_sha256": _sha(reports_dir / "validation-receipt.json"),
        }
        # The client requires a sha256 in every one of these slots and rejects the
        # whole dataset otherwise. Substituting a fake hash is what this ADR removes,
        # so a missing artifact is a hard failure: fix the producer, not the value.
        missing_lineage = sorted(k for k, v in qi_source.items()
                                 if k.endswith("_sha256") and v is None)
        if missing_lineage:
            raise RuntimeError(
                "quarter-insights lineage artifacts are missing: "
                + ", ".join(missing_lineage)
                + " -- produce them instead of substituting a placeholder hash"
            )
        quarter = recompute_quarter_insights(
            posts,
            comments,
            dataset_version=qi_version,
            unresolved_parent_comments=int((base_manifest.get("canonical_counts") or {}).get("unresolved_parent_comments") or 0),
            source=qi_source,
        )
        qi_dir = root / qi_version
        qi_bytes = (json.dumps(quarter, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        (qi_dir / "quarter-insights.json").write_bytes(qi_bytes)
        # The dataset manifest repeats the data's boundaries/period/source verbatim;
        # the client rejects the pair when any lineage field disagrees.
        qi_manifest = {
            "boundaries": quarter["boundaries"],
            "dataset_version": qi_version,
            "files": {
                "quarter-insights.json": {
                    "bytes": len(qi_bytes),
                    "media_type": "application/json",
                    "sha256": hashlib.sha256(qi_bytes).hexdigest(),
                }
            },
            "generated_at_utc": quarter["generated_at_utc"],
            "period": quarter["period"],
            "schema_version": "reddit_voc_quarter_insights_public_manifest_v1",
            "source": quarter["source"],
            "status": "ready",
        }
        (qi_dir / "manifest.json").write_text(json.dumps(qi_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        receipts.append({"file": f"{qi_version}/quarter-insights.json", "sha256": hashlib.sha256(qi_bytes).hexdigest()})

        # Step 3.5.4 — brand health projection. Must run before the reports bundle,
        # which embeds the four dimension scores.
        bh_binding = release["datasets"].get("brand_health") or {}
        bh_manifest_path = _manifest_path(root, bh_binding.get("manifest_path", ""))
        bh_data: dict = {"dimensions": [], "overall": {}}
        if bh_manifest_path.parent.exists():
            bh_data, bh_manifest = recompute_brand_health(
                posts,
                comments,
                projection_id=bh_binding.get("dataset_version") or "reddit_voc_brand_health_public_v1",
                source_hashes={
                    "brand_health_sha256": _sha(ds_dir / "aggregates-public.json"),
                    "facts_manifest_sha256": _sha(base_manifest_abs),
                    "metrics_manifest_sha256": _sha(reports_manifest_abs),
                    "metrics_validation_receipt_sha256": _sha(qi_dir / "quarter-insights.json"),
                },
                snapshot_id=f"echo_agent_base_snapshot_{_t1_anchor().date().isoformat()}",
            )
            bh_dir = bh_manifest_path.parent
            # Canonical bytes, not pretty-printed. `validate_public_projection` reads
            # both files with `canonical=True`, which compares the raw bytes against
            # `canonical_json_document(value)`; a `json.dumps(indent=2)` write fails
            # with "public data is not canonical JSON" and the page is rejected.
            (bh_dir / "brand-health.json").write_bytes(canonical_json_document(bh_data))
            (bh_dir / "manifest.json").write_bytes(canonical_json_document(bh_manifest))
            receipts.append({
                "file": f"{bh_dir.name}/brand-health.json",
                "sha256": _sha(bh_dir / "brand-health.json"),
                "overall_score": bh_data["overall"]["score"],
            })

        rp_root = root / rp_version / "public"
        rp_root.mkdir(parents=True, exist_ok=True)
        report_files = build_reports_bundle(
            posts=posts,
            comments=comments,
            brand_health=bh_data,
            template_dir=rp_root,
            dataset_version=rp_version,
            source_snapshot_id=base_version,
            source_hashes={
                "metrics_candidate_manifest_sha256": _sha(base_manifest_abs),
                "metrics_input_manifest_sha256": _sha(ds_dir / "tag-dictionary-public.json"),
                "metrics_validation_receipt_sha256": _sha(ds_dir / "aggregates-public.json"),
                "periodized_metrics_sha256": _sha(qi_dir / "quarter-insights.json"),
            },
            anchor=_t1_anchor().date(),
        )
        for relative, payload in report_files.items():
            target = rp_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        reports_lineage = json.loads(report_files["manifest.json"])["lineage_manifest_sha256"]
        receipts.append({
            "file": f"{rp_version}/public/manifest.json",
            "sha256": hashlib.sha256(report_files["manifest.json"]).hexdigest(),
            "lineage_manifest_sha256": reports_lineage,
            "files": len(report_files),
        })

    elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
    return {
        "engine": "recompute_derivatives_v1",
        "anchor_date": _t1_anchor().date().isoformat(),
        "inputs": {"posts": len(posts), "comments": len(comments)},
        "outputs": receipts if not dry_run else list(outputs.keys()),
        "elapsed_seconds": round(elapsed, 2),
        "dry_run": dry_run,
        "reports_lineage_manifest_sha256": reports_lineage if not dry_run else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Recompute derivative datasets from merged base snapshot")
    parser.add_argument("--public-root", type=Path, default=Path("/opt/voc-report/html"))
    parser.add_argument("--dry-run", action="store_true", default=False)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    receipt = run_recompute(args.public_root, dry_run=args.dry_run)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
