#!/usr/bin/env python3
"""Build deterministic Reddit VOC daily, weekly, and monthly static reports."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from hashlib import sha256
import html
import json
from pathlib import Path
import re
from typing import Any, Iterable
from zoneinfo import ZoneInfo


DATASET_VERSION = "reddit_voc_reports_20260714_v1"
MANIFEST_SCHEMA = "reddit_voc_reports_manifest_v1"
INDEX_SCHEMA = "reddit_voc_report_index_v1"
REPORT_SCHEMA = "reddit_voc_report_v1"
TIMEZONE_NAME = "Asia/Shanghai"
SENTIMENTS = ("positive", "neutral", "negative")
PROMOTED_TAG_IDS = {"L0-GEN-075", "L0-GEN-103"}
MOMCOZY_TAG_ID = "L0-BRD-011"
BRAND_BINDINGS = (
    "momcozy_sentence_bound",
    "momcozy_entity_cooccurrence",
    "multi_brand",
    "competitor_explicit",
    "category_general",
)
UNSUPPORTED_CAPABILITIES = (
    "market_share",
    "roi",
    "response_time",
    "nps",
    "conversion_rate",
    "high_intent",
    "ugc_attribution",
    "kpi_attainment",
    "forecast",
    "trend_claim",
    "persona_population",
)

V3_METRICS_MANIFEST_SCHEMA = "reddit_voc_metrics_candidate_manifest_v1"
V3_METRICS_RECEIPT_SCHEMA = "reddit_voc_metrics_validation_receipt_v1"
V3_METRICS_SCHEMA = "reddit_voc_metrics_snapshot_v1"
V3_REPORT_SCHEMA = "reddit_voc_report_v3"
V3_REPORT_INDEX_SCHEMA = "reddit_voc_report_index_v3"
V3_REPORT_MANIFEST_SCHEMA = "reddit_voc_reports_manifest_v3"
V3_PUBLIC_REPORT_MANIFEST_SCHEMA = "reddit_voc_reports_public_manifest_v3"
V3_PERIOD_SERIES_SCHEMA = "reddit_voc_reporting_metric_series_v3"
V3_REPORT_PATHS = tuple(
    f"{role}/{grain}.json"
    for role in ("current", "archive")
    for grain in ("daily", "weekly", "monthly")
)
V3_BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}
V3_PROFILE_KEYS = (
    "source_selection_profile_hash",
    "coverage_profile_hash",
    "retrieval_contract_hash",
)
V3_ROW_FIELDS = {
    "comparison_contract_proven",
    "coverage_profile_hash",
    "evidence_ids",
    "grain",
    "metric_id",
    "metric_policy_version",
    "name_cn",
    "period_id",
    "retrieval_contract_hash",
    "scope",
    "source_calendar_date",
    "source_selection_profile_hash",
    "status",
    "time_precision",
    "unavailable_reason_codes",
    "unit",
    "value",
    "voc_type",
}
V3_FORMAL_PERIODIZED_SCHEMA = "reddit_voc_periodized_metrics_candidate_v2"
V3_FORMAL_ROW_FIELDS = V3_ROW_FIELDS | {
    "data_owner_coverage_attestation_sha256",
    "observed_time_precision",
    "observed_voc_type",
    "period_complete",
}
V3_FORMAL_BRAND_HEALTH_ROW_FIELDS = {
    "comparison_contract_proven",
    "comparison_side",
    "coverage_profile_hash",
    "data_owner_coverage_attestation_sha256",
    "grain",
    "metric_id",
    "metric_policy_version",
    "observed_time_precision",
    "period_complete",
    "period_id",
    "retrieval_contract_hash",
    "scope",
    "source_calendar_date",
    "source_selection_profile_hash",
    "status",
    "time_precision",
    "unavailable_reason_codes",
    "unit",
    "value",
    "voc_type",
}
V3_PERIOD_ACTIVITY_EXTENSION = "reddit_voc_period_activity_v1"
V3_BRAND_HEALTH_DIMENSION_EXTENSION = (
    "reddit_voc_brand_health_dimension_contribution_v1"
)
V3_BUSINESS_HISTORY_INDEX_SCHEMA = "reddit_voc_business_history_index_v1"
V3_REPORT_CONTRACT_EXTENSIONS = (
    V3_PERIOD_ACTIVITY_EXTENSION,
    V3_BRAND_HEALTH_DIMENSION_EXTENSION,
    "reddit_voc_action_review_v1",
    V3_BUSINESS_HISTORY_INDEX_SCHEMA,
)
V3_HISTORY_LIMITS = {"daily": 14, "weekly": 12, "monthly": 12}
V3_REPORT_HISTORY_REVISION = "history6_observed_comparisons"
V3_OBSERVED_COMPARISON_REASON = (
    "owner_attestation_missing_observed_same_profile"
)
V3_BRAND_HEALTH_DIMENSIONS = {
    "reputation",
    "product_experience",
    "recommendation_trust",
    "risk_resilience",
}
V3_FORMAL_BRAND_HEALTH_DIMENSION_ROW_FIELDS = {
    "comparison_contract_proven",
    "comparison_side",
    "contribution_points",
    "coverage_profile_hash",
    "data_owner_coverage_attestation_sha256",
    "dimension_id",
    "dimension_value",
    "grain",
    "metric_id",
    "metric_policy_version",
    "observed_time_precision",
    "period_complete",
    "period_id",
    "retrieval_contract_hash",
    "scope",
    "source_calendar_date",
    "source_selection_profile_hash",
    "status",
    "time_precision",
    "unavailable_reason_codes",
    "unit",
    "voc_type",
    "weight_percent",
}
V3_ACTIVITY_COUNT_FIELDS = {
    "active_historical_post_count",
    "comments_on_current_period_posts",
    "comments_on_historical_posts",
    "new_comment_count",
    "new_post_count",
    "unresolved_parent_comment_count",
}
V3_ACTIVITY_ROW_FIELDS = {
    "all_observed",
    "comparison_contract_proven",
    "coverage_profile_hash",
    "data_owner_coverage_attestation_sha256",
    "grain",
    "momcozy",
    "period_complete",
    "period_id",
    "retrieval_contract_hash",
    "scope_contract",
    "source_calendar_date",
    "source_selection_profile_hash",
    "time_precision",
}
V3_FORMAL_COMPARABLE_UNITS = {
    "count",
    "index",
    "log_delta2",
    "percent",
    "pp",
    "proportion",
    "rate",
    "ratio",
    "score",
    "score_points",
    "share",
}


class V3ReportsBuildError(ValueError):
    """A V3 report input or immutable output violates its governed contract."""


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"naive datetime is not allowed: {value}")
    return parsed.astimezone(timezone.utc)


def _verify_file_manifest(root: Path, manifest: dict[str, Any]) -> None:
    for name, expected in manifest["files"].items():
        path = root / name
        if not path.is_file():
            raise ValueError(f"manifest file missing: {name}")
        if path.stat().st_size != expected["bytes"]:
            raise ValueError(f"manifest byte mismatch: {name}")
        if _sha256(path) != expected["sha256"]:
            raise ValueError(f"manifest sha256 mismatch: {name}")


def _sentiment_counts(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(row["analysis"]["sentiment_label"] for row in rows)
    unknown = set(counts) - set(SENTIMENTS)
    if unknown:
        raise ValueError(f"unsupported sentiment labels: {sorted(unknown)}")
    return {sentiment: counts[sentiment] for sentiment in SENTIMENTS}


def _share(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": round(numerator / denominator, 6) if denominator else None,
    }


def _sentiment_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = _sentiment_counts(rows)
    denominator = len(rows)
    return {
        "denominator": denominator,
        "counts": counts,
        "shares": {
            sentiment: _share(count, denominator)
            for sentiment, count in counts.items()
        },
    }


def _compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _excerpt(value: str, limit: int = 280) -> str:
    compact = _compact_text(value)
    return compact if len(compact) <= limit else compact[: limit - 1].rstrip() + "…"


def _normalise_brand(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _is_momcozy(value: str) -> bool:
    return _normalise_brand(value) in {"momcozy", "mcozy"}


def _previous_month_start(current_month_start: date) -> date:
    if current_month_start.month == 1:
        return date(current_month_start.year - 1, 12, 1)
    return date(current_month_start.year, current_month_start.month - 1, 1)


def _window_specs(as_of_utc: datetime) -> list[dict[str, Any]]:
    tz = ZoneInfo(TIMEZONE_NAME)
    as_of_local = as_of_utc.astimezone(tz)
    current_week_start = as_of_local.date() - timedelta(days=as_of_local.weekday())
    previous_week_start = current_week_start - timedelta(days=7)
    current_month_start = as_of_local.date().replace(day=1)
    previous_month_start = _previous_month_start(current_month_start)

    def local_midnight(value: date) -> datetime:
        return datetime.combine(value, time.min, tzinfo=tz).astimezone(timezone.utc)

    previous_day = as_of_local.date() - timedelta(days=1)
    windows = [
        {
            "path": "current/daily.json",
            "report_id": "current-daily-rolling-24h",
            "period": "daily",
            "window_mode": "rolling",
            "display_name": "日报 · 过去24小时",
            "start": as_of_utc - timedelta(days=1),
            "end": as_of_utc,
            "bucket_delta": timedelta(hours=1),
            "bucket_grain": "hour",
            "is_closed": False,
        },
        {
            "path": "current/weekly.json",
            "report_id": "current-weekly-rolling-7d",
            "period": "weekly",
            "window_mode": "rolling",
            "display_name": "周报 · 过去7天",
            "start": as_of_utc - timedelta(days=7),
            "end": as_of_utc,
            "bucket_delta": timedelta(days=1),
            "bucket_grain": "day",
            "is_closed": False,
        },
        {
            "path": "current/monthly.json",
            "report_id": "current-monthly-rolling-30d",
            "period": "monthly",
            "window_mode": "rolling",
            "display_name": "月报 · 过去30天",
            "start": as_of_utc - timedelta(days=30),
            "end": as_of_utc,
            "bucket_delta": timedelta(days=1),
            "bucket_grain": "day",
            "is_closed": False,
        },
        {
            "path": f"archive/daily-{previous_day.isoformat()}.json",
            "report_id": f"archive-daily-{previous_day.isoformat()}",
            "period": "daily",
            "window_mode": "calendar_closed",
            "display_name": f"日报归档 · {previous_day.isoformat()}",
            "start": local_midnight(previous_day),
            "end": local_midnight(previous_day + timedelta(days=1)),
            "bucket_delta": timedelta(hours=1),
            "bucket_grain": "hour",
            "is_closed": True,
        },
        {
            "path": (
                "archive/weekly-"
                f"{previous_week_start.isoformat()}_"
                f"{(current_week_start - timedelta(days=1)).isoformat()}.json"
            ),
            "report_id": (
                "archive-weekly-"
                f"{previous_week_start.isoformat()}_"
                f"{(current_week_start - timedelta(days=1)).isoformat()}"
            ),
            "period": "weekly",
            "window_mode": "calendar_closed",
            "display_name": (
                "周报归档 · "
                f"{previous_week_start.isoformat()} 至 "
                f"{(current_week_start - timedelta(days=1)).isoformat()}"
            ),
            "start": local_midnight(previous_week_start),
            "end": local_midnight(current_week_start),
            "bucket_delta": timedelta(days=1),
            "bucket_grain": "day",
            "is_closed": True,
        },
        {
            "path": (
                f"archive/monthly-{previous_month_start.strftime('%Y-%m')}.json"
            ),
            "report_id": (
                f"archive-monthly-{previous_month_start.strftime('%Y-%m')}"
            ),
            "period": "monthly",
            "window_mode": "calendar_closed",
            "display_name": (
                f"月报归档 · {previous_month_start.strftime('%Y-%m')}"
            ),
            "start": local_midnight(previous_month_start),
            "end": local_midnight(current_month_start),
            "bucket_delta": timedelta(days=1),
            "bucket_grain": "day",
            "is_closed": True,
        },
    ]
    return windows


def _in_window(row: dict[str, Any], start: datetime, end: datetime) -> bool:
    created = _parse_datetime(row["created_at_utc"])
    return start <= created < end


def _timeline(
    posts: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    start: datetime,
    end: datetime,
    delta: timedelta,
) -> list[dict[str, Any]]:
    tz = ZoneInfo(TIMEZONE_NAME)
    result = []
    cursor = start
    while cursor < end:
        bucket_end = min(cursor + delta, end)
        bucket_posts = [row for row in posts if _in_window(row, cursor, bucket_end)]
        bucket_comments = [
            row for row in comments if _in_window(row, cursor, bucket_end)
        ]
        combined = bucket_posts + bucket_comments
        result.append(
            {
                "bucket_start_utc": cursor.isoformat(),
                "bucket_end_utc": bucket_end.isoformat(),
                "bucket_start_local": cursor.astimezone(tz).isoformat(),
                "posts": len(bucket_posts),
                "voc_comments": len(bucket_comments),
                "observed_entities": len(combined),
                "sentiment_counts": _sentiment_counts(combined),
            }
        )
        cursor = bucket_end
    return result


def _communities(
    posts: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    post_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"posts": set(), "comments": set(), "sentiments": Counter()}
    )
    for post in posts:
        community = post["subreddit"]
        rows[community]["posts"].add(post["post_id"])
        rows[community]["sentiments"][post["analysis"]["sentiment_label"]] += 1
    for comment in comments:
        community = post_by_id[comment["post_id"]]["subreddit"]
        rows[community]["comments"].add(comment["comment_id"])
        rows[community]["sentiments"][comment["analysis"]["sentiment_label"]] += 1

    output = []
    for community, value in rows.items():
        post_count = len(value["posts"])
        comment_count = len(value["comments"])
        denominator = post_count + comment_count
        sentiment_counts = {
            sentiment: value["sentiments"][sentiment] for sentiment in SENTIMENTS
        }
        output.append(
            {
                "subreddit": community,
                "posts": post_count,
                "voc_comments": comment_count,
                "observed_entities": denominator,
                "sentiment_counts": sentiment_counts,
                "negative_share": _share(
                    sentiment_counts["negative"], denominator
                ),
            }
        )
    output.sort(
        key=lambda row: (
            -row["observed_entities"],
            -row["posts"],
            row["subreddit"].casefold(),
        )
    )
    return output


def _topics(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter(row["analysis"]["topic"] for row in posts)
    result = [
        {
            "topic": topic,
            "post_entities": count,
            "share": _share(count, len(posts)),
        }
        for topic, count in counts.items()
    ]
    result.sort(key=lambda row: (-row["post_entities"], row["topic"]))
    return result


def _pain_points(
    posts: list[dict[str, Any]], comments: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    post_counts: Counter[str] = Counter()
    comment_counts: Counter[str] = Counter()
    for row in posts:
        post_counts.update(set(row["analysis"]["pain_points"]))
    for row in comments:
        comment_counts.update(set(row["analysis"]["pain_points"]))
    denominator = len(posts) + len(comments)
    result = []
    for pain_point in sorted(set(post_counts) | set(comment_counts)):
        total = post_counts[pain_point] + comment_counts[pain_point]
        result.append(
            {
                "pain_point": pain_point,
                "post_entities": post_counts[pain_point],
                "comment_entities": comment_counts[pain_point],
                "total_entities": total,
                "share": _share(total, denominator),
            }
        )
    result.sort(key=lambda row: (-row["total_entities"], row["pain_point"]))
    return result


def _brand_mentions(
    posts: list[dict[str, Any]], brand_name_by_tag: dict[str, str]
) -> list[dict[str, Any]]:
    post_ids_by_brand: dict[str, set[str]] = defaultdict(set)
    display_names: dict[str, str] = {}
    governed_names = {
        _normalise_brand(name): name for name in brand_name_by_tag.values()
    }
    for post in posts:
        names = list(post.get("mentioned_brands", []))
        names.extend(
            brand_name_by_tag[tag_id]
            for tag_id in post["tagging"]["brand_tag_ids"]
            if tag_id in brand_name_by_tag
        )
        for name in names:
            key = _normalise_brand(name)
            if not key:
                continue
            candidate = governed_names.get(key, name)
            existing = display_names.get(key)
            if existing is None or (candidate.casefold(), candidate) < (
                existing.casefold(),
                existing,
            ):
                display_names[key] = candidate
            post_ids_by_brand[key].add(post["post_id"])
    result = [
        {
            "brand": display_names[key],
            "sample_mention_posts": len(post_ids),
            "sample_mention_share": _share(len(post_ids), len(posts)),
            "metric_label": "sample_mention_posts",
        }
        for key, post_ids in post_ids_by_brand.items()
    ]
    result.sort(
        key=lambda row: (-row["sample_mention_posts"], row["brand"].casefold())
    )
    return result


def _entity_text(entity_type: str, row: dict[str, Any]) -> str:
    if entity_type == "post":
        return f"{row['title']}\n{row['content']}"
    return row["body"]


def _entity_brands(
    entity_type: str,
    row: dict[str, Any],
    brand_name_by_tag: dict[str, str],
) -> list[str]:
    names = list(row.get("mentioned_brands", [])) if entity_type == "post" else []
    names.extend(
        brand_name_by_tag[tag_id]
        for tag_id in row["tagging"]["brand_tag_ids"]
        if tag_id in brand_name_by_tag
    )
    governed_names = {
        _normalise_brand(name): name for name in brand_name_by_tag.values()
    }
    names_by_key: dict[str, str] = {}
    for name in names:
        key = _normalise_brand(name)
        if not key:
            continue
        candidate = governed_names.get(key, name)
        existing = names_by_key.get(key)
        if existing is None or (candidate.casefold(), candidate) < (
            existing.casefold(),
            existing,
        ):
            names_by_key[key] = candidate
    return sorted(names_by_key.values(), key=lambda value: (value.casefold(), value))


def _signal_keywords(row: dict[str, Any], tag_id: str) -> list[str]:
    keywords = {
        keyword.casefold()
        for match in row["tagging"]["matches"]
        if match["tag_id"] == tag_id
        for keyword in match["evidence_keywords"]
    }
    return sorted(keywords)


def _has_sentence_binding(
    text: str,
    signal_keywords: list[str],
    momcozy_aliases: list[str],
) -> bool:
    sentences = re.split(r"(?<=[.!?])\s+|\n+", html.unescape(text).casefold())
    return any(
        any(alias in sentence for alias in momcozy_aliases)
        and any(keyword in sentence for keyword in signal_keywords)
        for sentence in sentences
        if sentence.strip()
    )


def _brand_binding(
    text: str,
    brands: list[str],
    signal_keywords: list[str],
    momcozy_aliases: list[str],
) -> str:
    has_momcozy = any(_is_momcozy(brand) for brand in brands)
    has_other_brand = any(not _is_momcozy(brand) for brand in brands)
    if has_momcozy and has_other_brand:
        return "multi_brand"
    if has_momcozy and _has_sentence_binding(
        text, signal_keywords, momcozy_aliases
    ):
        return "momcozy_sentence_bound"
    if has_momcozy:
        return "momcozy_entity_cooccurrence"
    if has_other_brand:
        return "competitor_explicit"
    return "category_general"


def _promoted_signals(
    posts: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    post_by_id: dict[str, dict[str, Any]],
    insights_by_tag: dict[str, dict[str, Any]],
    brand_name_by_tag: dict[str, str],
    momcozy_aliases: list[str],
) -> list[dict[str, Any]]:
    result = []
    for tag_id in sorted(insights_by_tag):
        insight = insights_by_tag[tag_id]
        matches = []
        for entity_type, rows in (("post", posts), ("comment", comments)):
            for row in rows:
                if tag_id not in row["tagging"]["aspect_tag_ids"]:
                    continue
                keywords = _signal_keywords(row, tag_id)
                if not keywords:
                    raise ValueError(
                        f"promoted tag lacks evidence keywords: {tag_id}"
                    )
                brands = _entity_brands(
                    entity_type, row, brand_name_by_tag
                )
                text = _entity_text(entity_type, row)
                binding = _brand_binding(
                    text, brands, keywords, momcozy_aliases
                )
                parent = row if entity_type == "post" else post_by_id[row["post_id"]]
                matches.append(
                    {
                        "entity_type": entity_type,
                        "entity_id": (
                            row["post_id"]
                            if entity_type == "post"
                            else row["comment_id"]
                        ),
                        "post_id": row["post_id"],
                        "created_at_utc": row["created_at_utc"],
                        "subreddit": parent["subreddit"],
                        "binding_type": binding,
                        "brands": brands,
                        "evidence_keywords": keywords,
                        "context_excerpt": _excerpt(text),
                        "permalink": parent["permalink"],
                    }
                )
        binding_counts = Counter(row["binding_type"] for row in matches)
        post_count = sum(row["entity_type"] == "post" for row in matches)
        comment_count = len(matches) - post_count
        matches.sort(
            key=lambda row: (
                BRAND_BINDINGS.index(row["binding_type"]),
                row["created_at_utc"],
                row["entity_type"],
                row["entity_id"],
            )
        )
        result.append(
            {
                "tag_id": tag_id,
                "name_cn": insight["name_cn"],
                "name_en": insight["name_en"],
                "theme": insight["theme"],
                "matched_posts": post_count,
                "matched_comments": comment_count,
                "matched_entities": len(matches),
                "binding_counts": {
                    binding: binding_counts[binding]
                    for binding in BRAND_BINDINGS
                },
                "momcozy_specific_entities": binding_counts[
                    "momcozy_sentence_bound"
                ],
                "dictionary_reference": insight["dictionary_reference"],
                "evidence": matches[:8],
            }
        )
    return result


def _attention_items(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    severity_weight = {"low": 1, "medium": 2, "high": 3}
    candidates = []
    for post in posts:
        sentiment = post["analysis"]["sentiment_label"]
        severity = post["analysis"]["severity"]
        reasons = []
        if sentiment == "negative":
            reasons.append("negative_sentiment")
        if severity == "high":
            reasons.append("high_rule_severity")
        if not reasons:
            continue
        priority_score = (
            severity_weight.get(severity, 0) * 1000
            + (500 if sentiment == "negative" else 0)
            + max(post["score"], 0) * 2
            + post["linked_comment_count"]
        )
        candidates.append(
            {
                "attention_id": f"attention:{post['post_id']}",
                "post_id": post["post_id"],
                "title": post["title"],
                "subreddit": post["subreddit"],
                "created_at_utc": post["created_at_utc"],
                "sentiment": sentiment,
                "severity": severity,
                "score": post["score"],
                "linked_comment_count": post["linked_comment_count"],
                "reason_codes": reasons,
                "permalink": post["permalink"],
                "priority_score": priority_score,
            }
        )
    candidates.sort(
        key=lambda row: (
            -row["priority_score"],
            -row["score"],
            -row["linked_comment_count"],
            row["post_id"],
        )
    )
    return candidates[:8]


def _evidence_posts(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(
        posts,
        key=lambda row: (
            -(max(row["score"], 0) + row["linked_comment_count"]),
            -row["linked_comment_count"],
            row["post_id"],
        ),
    )
    return [
        {
            "post_id": row["post_id"],
            "title": row["title"],
            "subreddit": row["subreddit"],
            "created_at_utc": row["created_at_utc"],
            "sentiment": row["analysis"]["sentiment_label"],
            "severity": row["analysis"]["severity"],
            "topic": row["analysis"]["topic"],
            "score": row["score"],
            "linked_comment_count": row["linked_comment_count"],
            "mentioned_brands": row.get("mentioned_brands", []),
            "permalink": row["permalink"],
            "content_excerpt": _excerpt(row["content"]),
        }
        for row in ranked[:12]
    ]


def _build_report(
    spec: dict[str, Any],
    *,
    as_of_utc: datetime,
    posts: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    post_by_id: dict[str, dict[str, Any]],
    insights_by_tag: dict[str, dict[str, Any]],
    brand_name_by_tag: dict[str, str],
    momcozy_aliases: list[str],
    quarantined_comment_count: int,
) -> dict[str, Any]:
    start = spec["start"]
    end = spec["end"]
    window_posts = [row for row in posts if _in_window(row, start, end)]
    window_comments = [
        row
        for row in comments
        if row["include_in_voc_metrics"] and _in_window(row, start, end)
    ]
    coverage_status = (
        "observed_records_present_but_collection_coverage_unverified"
        if window_posts or window_comments
        else "coverage_gap"
    )
    tz = ZoneInfo(TIMEZONE_NAME)
    return {
        "schema_version": REPORT_SCHEMA,
        "identity": {
            "dataset_version": DATASET_VERSION,
            "report_id": spec["report_id"],
            "period": spec["period"],
            "window_mode": spec["window_mode"],
            "display_name": spec["display_name"],
        },
        "window": {
            "start_utc": start.isoformat(),
            "end_utc": end.isoformat(),
            "start_local": start.astimezone(tz).isoformat(),
            "end_local": end.astimezone(tz).isoformat(),
            "timezone": TIMEZONE_NAME,
            "as_of_utc": as_of_utc.isoformat(),
            "is_closed": spec["is_closed"],
            "bucket_grain": spec["bucket_grain"],
            "coverage_status": coverage_status,
            "comparison_status": "coverage_unverified",
        },
        "headline": {
            "posts": len(window_posts),
            "voc_comments": len(window_comments),
            "observed_entities": len(window_posts) + len(window_comments),
            "post_sentiment": _sentiment_summary(window_posts),
            "comment_sentiment": _sentiment_summary(window_comments),
            "quarantined_comments_in_base_snapshot": quarantined_comment_count,
            "quarantined_comments_counted": 0,
        },
        "observed_timeline": _timeline(
            window_posts,
            window_comments,
            start,
            end,
            spec["bucket_delta"],
        ),
        "communities": _communities(
            window_posts, window_comments, post_by_id
        ),
        "topics": _topics(window_posts),
        "pain_points": _pain_points(window_posts, window_comments),
        "brand_mentions": _brand_mentions(
            window_posts, brand_name_by_tag
        ),
        "promoted_signals": _promoted_signals(
            window_posts,
            window_comments,
            post_by_id,
            insights_by_tag,
            brand_name_by_tag,
            momcozy_aliases,
        ),
        "attention_items": _attention_items(window_posts),
        "evidence_posts": _evidence_posts(window_posts),
        "capabilities": {
            "supported": [
                "observed_volume",
                "sentiment_distribution",
                "observed_timeline",
                "community_distribution",
                "post_topics",
                "entity_pain_points",
                "sample_brand_mentions",
                "promoted_tag_signals",
                "brand_subject_binding",
                "evidence_posts",
            ],
            "conditionally_supported": [
                "cross_period_comparison_requires_collection_coverage_ledger",
                "persona_requires_dim_persona_v1_and_persona_tags",
            ],
            "unsupported": list(UNSUPPORTED_CAPABILITIES),
        },
        "interpretation_boundaries": {
            "counts_are_observed_entities_not_users": True,
            "comments_use_own_created_at_window": True,
            "brand_metric_label": "sample_mention_posts",
            "brand_counts_are_nonexclusive": True,
            "market_share_supported": False,
            "roi_supported": False,
            "trend_claim_supported": False,
            "comparison_status": "coverage_unverified",
            "consumer_card_is_reference_not_persona_id": True,
            "persona_tags_generated": False,
            "momcozy_specific_requires_sentence_binding": True,
            "held_tags_in_business_findings": 0,
        },
        "runtime_boundaries": {
            "delivery_mode": "versioned_static_reports",
            "production_unchanged": True,
            "provider_call": False,
            "database_write": False,
            "live_send": False,
            "webhook_send": False,
            "deploy": False,
            "schedule_change": False,
        },
    }


def build(
    snapshot_dir: Path,
    insights_dir: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any], dict[str, Any]]:
    base_manifest_path = snapshot_dir / "manifest.json"
    insights_manifest_path = insights_dir / "manifest.json"
    base_manifest = _load(base_manifest_path)
    insights_manifest = _load(insights_manifest_path)
    insights = _load(insights_dir / "insights.json")
    posts = _load(snapshot_dir / "posts.json")
    comments = _load(snapshot_dir / "comments.json")
    dictionary = _load(snapshot_dir / "tag-dictionary.json")

    _verify_file_manifest(snapshot_dir, base_manifest)
    _verify_file_manifest(insights_dir, insights_manifest)
    if not base_manifest["all_checks_passed"]:
        raise ValueError("base snapshot did not pass its checks")
    if insights_manifest["status"] != "passed_with_scope_limits":
        raise ValueError("insights overlay did not pass its scoped gate")
    if insights_manifest["base_dataset_version"] != base_manifest["dataset_version"]:
        raise ValueError("insights/base dataset version mismatch")
    if insights_manifest["base_manifest_sha256"] != _sha256(base_manifest_path):
        raise ValueError("insights/base manifest sha256 mismatch")
    if insights["base_dataset_version"] != base_manifest["dataset_version"]:
        raise ValueError("insights payload/base dataset version mismatch")
    if dictionary["dictionary_version"] != insights_manifest["dictionary_version"]:
        raise ValueError("dictionary version mismatch")
    if dictionary["dictionary_sha256"] != insights_manifest["dictionary_sha256"]:
        raise ValueError("dictionary sha256 mismatch")

    promoted_ids = set(insights_manifest["audit_summary"]["promoted_tag_ids"])
    held_ids = set(insights_manifest["audit_summary"]["held_tag_ids"])
    if promoted_ids != PROMOTED_TAG_IDS:
        raise ValueError("unexpected promoted tag set")
    if promoted_ids & held_ids:
        raise ValueError("promoted and held tag sets overlap")
    if {row["tag_id"] for row in insights["signals"]} != promoted_ids:
        raise ValueError("insights signal set mismatch")

    post_by_id = {row["post_id"]: row for row in posts}
    if len(post_by_id) != len(posts):
        raise ValueError("duplicate post ids in base snapshot")
    if any(row["post_id"] not in post_by_id for row in comments):
        raise ValueError("comment without parent post")

    rules_by_tag = {rule["tag_id"]: rule for rule in dictionary["rules"]}
    brand_rules = {
        tag_id: rule
        for tag_id, rule in rules_by_tag.items()
        if tag_id.startswith("L0-BRD-")
    }
    if MOMCOZY_TAG_ID not in brand_rules:
        raise ValueError("Momcozy brand rule missing")
    brand_name_by_tag = {
        tag_id: rule["name_en"] for tag_id, rule in brand_rules.items()
    }
    momcozy_aliases = sorted(
        {alias.casefold() for alias in brand_rules[MOMCOZY_TAG_ID]["keywords_en"]},
        key=lambda value: (-len(value), value),
    )
    insights_by_tag = {row["tag_id"]: row for row in insights["signals"]}
    as_of_utc = _parse_datetime(base_manifest["generated_at_utc"])

    reports: dict[str, dict[str, Any]] = {}
    descriptors = []
    for spec in _window_specs(as_of_utc):
        report = _build_report(
            spec,
            as_of_utc=as_of_utc,
            posts=posts,
            comments=comments,
            post_by_id=post_by_id,
            insights_by_tag=insights_by_tag,
            brand_name_by_tag=brand_name_by_tag,
            momcozy_aliases=momcozy_aliases,
            quarantined_comment_count=base_manifest["canonical_counts"][
                "quarantined_comments"
            ],
        )
        reports[spec["path"]] = report
        descriptors.append(
            {
                "report_id": spec["report_id"],
                "period": spec["period"],
                "window_mode": spec["window_mode"],
                "display_name": spec["display_name"],
                "path": spec["path"],
                "start_utc": report["window"]["start_utc"],
                "end_utc": report["window"]["end_utc"],
                "coverage_status": report["window"]["coverage_status"],
                "posts": report["headline"]["posts"],
                "voc_comments": report["headline"]["voc_comments"],
            }
        )

    index = {
        "schema_version": INDEX_SCHEMA,
        "dataset_version": DATASET_VERSION,
        "as_of_utc": as_of_utc.isoformat(),
        "timezone": TIMEZONE_NAME,
        "current": {
            row["period"]: row
            for row in descriptors
            if row["window_mode"] == "rolling"
        },
        "archive": {
            row["period"]: row
            for row in descriptors
            if row["window_mode"] == "calendar_closed"
        },
    }
    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "dataset_version": DATASET_VERSION,
        "delivery_mode": "versioned_static_reports",
        "generated_at_utc": as_of_utc.isoformat(),
        "base_dataset_version": base_manifest["dataset_version"],
        "base_manifest_sha256": _sha256(base_manifest_path),
        "insights_dataset_version": insights_manifest["dataset_version"],
        "insights_manifest_sha256": _sha256(insights_manifest_path),
        "dictionary_version": dictionary["dictionary_version"],
        "dictionary_sha256": dictionary["dictionary_sha256"],
        "report_count": len(reports),
        "promoted_tag_ids": sorted(promoted_ids),
        "held_tag_ids_excluded": sorted(held_ids),
        "files": {},
        "boundaries": {
            "production_unchanged": True,
            "provider_call": False,
            "database_write": False,
            "live_send": False,
            "webhook_send": False,
            "deploy": False,
            "schedule_change": False,
            "independent_human_review": False,
            "consumer_card_is_reference_not_persona_id": True,
            "persona_tags_generated": False,
            "market_share_supported": False,
            "roi_supported": False,
            "trend_claim_supported": False,
        },
    }
    return reports, index, manifest


def write_snapshot(
    output_dir: Path,
    reports: dict[str, dict[str, Any]],
    index: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    for relative_path, report in sorted(reports.items()):
        _write(output_dir / relative_path, report)
    _write(output_dir / "report-index.json", index)

    complete_manifest = deepcopy(manifest)
    file_names = ["report-index.json", *sorted(reports)]
    complete_manifest["files"] = {
        name: {
            "bytes": (output_dir / name).stat().st_size,
            "sha256": _sha256(output_dir / name),
        }
        for name in file_names
    }
    _write(output_dir / "manifest.json", complete_manifest)
    return complete_manifest


def _v3_canonical_bytes(value: Any) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise V3ReportsBuildError("V3 document is not canonical-JSON serializable") from exc


def _v3_hex(value: object, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise V3ReportsBuildError(f"{label} must be lowercase SHA-256")
    return value


def _v3_load_canonical(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = path.read_bytes()
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V3ReportsBuildError(f"{label} is unreadable") from exc
    if not isinstance(value, dict) or payload != _v3_canonical_bytes(value):
        raise V3ReportsBuildError(f"{label} is not canonical JSON")
    return value


def load_v3_metrics_binding(
    metrics_root: Path,
    validation_receipt_path: Path,
    *,
    expected_manifest_sha256: str,
    expected_receipt_sha256: str,
) -> dict[str, Any]:
    """Load only an exactly hash-bound and independently validated metrics bundle."""

    manifest_sha = _v3_hex(expected_manifest_sha256, "metrics manifest SHA")
    receipt_sha = _v3_hex(expected_receipt_sha256, "metrics receipt SHA")
    metrics_root = Path(metrics_root)
    receipt_path = Path(validation_receipt_path)
    if metrics_root.is_symlink() or not metrics_root.is_dir():
        raise V3ReportsBuildError("metrics root is invalid")
    actual_names = {path.name for path in metrics_root.iterdir()}
    if actual_names != {"brand-health.json", "manifest.json", "metrics.json"}:
        raise V3ReportsBuildError("metrics root file set is invalid")
    if any(path.is_symlink() or not path.is_file() for path in metrics_root.iterdir()):
        raise V3ReportsBuildError("metrics root contains a non-regular file")
    manifest_path = metrics_root / "manifest.json"
    if _sha256(manifest_path) != manifest_sha:
        raise V3ReportsBuildError("metrics manifest SHA mismatch")
    if receipt_path.is_symlink() or not receipt_path.is_file():
        raise V3ReportsBuildError("metrics validation receipt is invalid")
    if _sha256(receipt_path) != receipt_sha:
        raise V3ReportsBuildError("metrics validation receipt SHA mismatch")

    manifest = _v3_load_canonical(manifest_path, "metrics manifest")
    receipt = _v3_load_canonical(receipt_path, "metrics validation receipt")
    expected_manifest_fields = {
        "artifact_stage",
        "boundaries",
        "consumption_status",
        "core_indicator_count",
        "files",
        "indicator_count",
        "input_sha256",
        "integrity_indicator_count",
        "promotable",
        "registry_sha256",
        "schema_version",
        "source_facts_validation_receipt_sha256",
    }
    if set(manifest) != expected_manifest_fields:
        raise V3ReportsBuildError("metrics manifest fields are invalid")
    if (
        manifest.get("schema_version") != V3_METRICS_MANIFEST_SCHEMA
        or manifest.get("artifact_stage") != "metrics_candidate"
        or manifest.get("consumption_status")
        != "candidate_pending_independent_validation"
        or manifest.get("promotable") is not False
        or manifest.get("boundaries") != V3_BOUNDARIES
        or manifest.get("indicator_count") != 26
        or manifest.get("core_indicator_count") != 19
        or manifest.get("integrity_indicator_count") != 7
    ):
        raise V3ReportsBuildError("metrics manifest lifecycle is invalid")
    expected_receipt_fields = {
        "boundaries",
        "brand_health_recomputed",
        "bundle_manifest_sha256",
        "deterministic_full_byte_replay",
        "indicator_count",
        "input_sha256",
        "promotable",
        "registry_sha256",
        "schema_version",
        "source_facts_validation_receipt_sha256",
        "status",
    }
    if set(receipt) != expected_receipt_fields:
        raise V3ReportsBuildError("metrics validation receipt fields are invalid")
    receipt_status = receipt.get("status")
    expected_promotable = receipt_status == "passed_candidate_only"
    if (
        receipt.get("schema_version") != V3_METRICS_RECEIPT_SCHEMA
        or receipt_status not in {"passed_candidate_only", "passed_fixture_only"}
        or receipt.get("promotable") is not expected_promotable
        or receipt.get("boundaries") != V3_BOUNDARIES
        or receipt.get("brand_health_recomputed") is not True
        or receipt.get("deterministic_full_byte_replay") is not True
        or receipt.get("indicator_count") != 26
        or receipt.get("bundle_manifest_sha256") != manifest_sha
    ):
        raise V3ReportsBuildError("metrics validation receipt state is invalid")
    for key in (
        "input_sha256",
        "registry_sha256",
        "source_facts_validation_receipt_sha256",
    ):
        if receipt.get(key) != manifest.get(key):
            raise V3ReportsBuildError(f"metrics receipt {key} binding mismatch")

    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != {
        "brand-health.json",
        "metrics.json",
    }:
        raise V3ReportsBuildError("metrics manifest file set is invalid")
    documents: dict[str, dict[str, Any]] = {}
    for name in sorted(files):
        record = files[name]
        path = metrics_root / name
        if not isinstance(record, dict) or set(record) != {"bytes", "sha256"}:
            raise V3ReportsBuildError(f"metrics file record is invalid: {name}")
        if record.get("bytes") != path.stat().st_size or record.get("sha256") != _sha256(path):
            raise V3ReportsBuildError(f"metrics file integrity mismatch: {name}")
        documents[name] = _v3_load_canonical(path, name)
    metrics = documents["metrics.json"]
    brand_health = documents["brand-health.json"]
    if (
        metrics.get("schema_version") != V3_METRICS_SCHEMA
        or metrics.get("boundaries") != V3_BOUNDARIES
        or metrics.get("indicator_count") != 26
        or metrics.get("core_indicator_count") != 19
        or metrics.get("integrity_indicator_count") != 7
        or not isinstance(metrics.get("indicators"), list)
        or len(metrics["indicators"]) != 26
    ):
        raise V3ReportsBuildError("metrics document contract is invalid")
    indicator_ids = [
        row.get("reddit_indicator_id")
        for row in metrics["indicators"]
        if isinstance(row, dict)
    ]
    if (
        len(indicator_ids) != 26
        or len(set(indicator_ids)) != 26
        or any(not isinstance(value, str) or not value for value in indicator_ids)
    ):
        raise V3ReportsBuildError("metrics indicator ID set is invalid")
    lineage = metrics.get("lineage")
    if (
        not isinstance(lineage, dict)
        or not isinstance(lineage.get("source_snapshot_id"), str)
        or not lineage["source_snapshot_id"]
        or brand_health.get("schema_version") != "reddit_voc_brand_health_index_v2"
        or brand_health.get("boundaries") != V3_BOUNDARIES
        or brand_health.get("lineage") != lineage
    ):
        raise V3ReportsBuildError("metrics lineage contract is invalid")
    return {
        "brand_health": brand_health,
        "fixture_only": receipt_status == "passed_fixture_only",
        "indicator_ids": tuple(indicator_ids),
        "manifest": manifest,
        "manifest_sha256": manifest_sha,
        "metrics": metrics,
        "receipt": receipt,
        "receipt_sha256": receipt_sha,
        "source_snapshot_id": lineage["source_snapshot_id"],
    }


def _v3_load_hash_bound_object(path: Path, label: str) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V3ReportsBuildError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise V3ReportsBuildError(f"{label} must be a JSON object")
    return value


def load_v3_formal_metrics_binding(
    metrics_input_manifest_path: Path,
    metrics_root: Path,
    validation_receipt_path: Path,
    *,
    expected_input_manifest_sha256: str,
    expected_candidate_manifest_sha256: str,
    expected_receipt_sha256: str,
    expected_coverage_attestation_sha256: str | None,
) -> dict[str, Any]:
    """Load an independently validated periodized V2 candidate.

    Owner-attested and honest-unattested candidates are both accepted.  The
    latter must carry no attestation SHA and keeps every comparison disabled.
    """

    from reddit_voc.v3_reporting_periods import complete_period_windows

    input_manifest_sha = _v3_hex(
        expected_input_manifest_sha256, "metrics input manifest SHA"
    )
    candidate_manifest_sha = _v3_hex(
        expected_candidate_manifest_sha256, "metrics candidate manifest SHA"
    )
    receipt_sha = _v3_hex(expected_receipt_sha256, "metrics receipt SHA")
    attestation_sha = (
        _v3_hex(
            expected_coverage_attestation_sha256, "coverage attestation SHA"
        )
        if expected_coverage_attestation_sha256 is not None
        else None
    )
    input_manifest_path = Path(metrics_input_manifest_path)
    metrics_root = Path(metrics_root)
    receipt_path = Path(validation_receipt_path)
    if (
        input_manifest_path.is_symlink()
        or not input_manifest_path.is_file()
        or _sha256(input_manifest_path) != input_manifest_sha
    ):
        raise V3ReportsBuildError("metrics input manifest SHA mismatch")
    if metrics_root.is_symlink() or not metrics_root.is_dir():
        raise V3ReportsBuildError("formal metrics root is invalid")
    if {path.name for path in metrics_root.iterdir()} != {
        "brand-health.json",
        "manifest.json",
        "metrics.json",
        "periodized-metrics.json",
    } or any(path.is_symlink() or not path.is_file() for path in metrics_root.iterdir()):
        raise V3ReportsBuildError("formal metrics root file set is invalid")
    candidate_manifest_path = metrics_root / "manifest.json"
    if _sha256(candidate_manifest_path) != candidate_manifest_sha:
        raise V3ReportsBuildError("metrics candidate manifest SHA mismatch")
    if (
        receipt_path.is_symlink()
        or not receipt_path.is_file()
        or _sha256(receipt_path) != receipt_sha
    ):
        raise V3ReportsBuildError("metrics validation receipt SHA mismatch")

    input_manifest = _v3_load_canonical(
        input_manifest_path, "metrics input manifest"
    )
    candidate_manifest = _v3_load_canonical(
        candidate_manifest_path, "metrics candidate manifest"
    )
    receipt = _v3_load_canonical(receipt_path, "metrics validation receipt")
    if (
        input_manifest.get("schema_version") != "reddit_voc_metrics_input_manifest_v1"
        or input_manifest.get("status") != "candidate_built"
        or input_manifest.get("consumption_status")
        != "pending_independent_metrics_validation"
        or input_manifest.get("independent_validation_status") != "pending"
        or input_manifest.get("promotable") is not False
        or input_manifest.get("boundaries") != V3_BOUNDARIES
        or input_manifest.get("inputs", {}).get(
            "data_owner_coverage_attestation_sha256"
        )
        != attestation_sha
    ):
        raise V3ReportsBuildError("metrics input manifest lifecycle is invalid")
    input_files = input_manifest.get("files")
    if not isinstance(input_files, dict) or set(input_files) != {"metrics-input.json"}:
        raise V3ReportsBuildError("metrics input manifest file set is invalid")
    input_record = input_files["metrics-input.json"]
    metrics_input_path = input_manifest_path.parent / "metrics-input.json"
    if (
        not isinstance(input_record, dict)
        or set(input_record) != {"bytes", "sha256"}
        or metrics_input_path.is_symlink()
        or not metrics_input_path.is_file()
        or input_record.get("bytes") != metrics_input_path.stat().st_size
        or input_record.get("sha256") != _sha256(metrics_input_path)
    ):
        raise V3ReportsBuildError("metrics input file binding is invalid")

    expected_candidate_fields = {
        "artifact_stage",
        "boundaries",
        "consumption_status",
        "core_indicator_count",
        "files",
        "indicator_count",
        "input_sha256",
        "integrity_indicator_count",
        "period_count",
        "periodized_brand_health_row_count",
        "periodized_brand_health_dimension_row_count",
        "periodized_metric_row_count",
        "promotable",
        "registry_sha256",
        "schema_version",
        "source_facts_validation_receipt_sha256",
    }
    if set(candidate_manifest) != expected_candidate_fields or (
        candidate_manifest.get("schema_version") != V3_METRICS_MANIFEST_SCHEMA
        or candidate_manifest.get("artifact_stage") != "metrics_candidate"
        or candidate_manifest.get("consumption_status")
        != "candidate_pending_independent_validation"
        or candidate_manifest.get("promotable") is not False
        or candidate_manifest.get("boundaries") != V3_BOUNDARIES
        or candidate_manifest.get("indicator_count") != 26
        or candidate_manifest.get("core_indicator_count") != 19
        or candidate_manifest.get("integrity_indicator_count") != 7
        or candidate_manifest.get("input_sha256") != input_record.get("sha256")
    ):
        raise V3ReportsBuildError("formal metrics candidate lifecycle is invalid")
    expected_receipt_fields = {
        "boundaries",
        "brand_health_recomputed",
        "bundle_manifest_sha256",
        "deterministic_full_byte_replay",
        "indicator_count",
        "input_sha256",
        "periodized_metrics_recomputed",
        "promotable",
        "registry_sha256",
        "schema_version",
        "source_facts_validation_receipt_sha256",
        "status",
    }
    if set(receipt) != expected_receipt_fields or (
        receipt.get("schema_version") != V3_METRICS_RECEIPT_SCHEMA
        or receipt.get("status") != "passed_candidate_only"
        or receipt.get("promotable") is not True
        or receipt.get("boundaries") != V3_BOUNDARIES
        or receipt.get("brand_health_recomputed") is not True
        or receipt.get("periodized_metrics_recomputed") is not True
        or receipt.get("deterministic_full_byte_replay") is not True
        or receipt.get("indicator_count") != 26
        or receipt.get("bundle_manifest_sha256") != candidate_manifest_sha
    ):
        raise V3ReportsBuildError("formal metrics validation receipt is invalid")
    for key in (
        "input_sha256",
        "registry_sha256",
        "source_facts_validation_receipt_sha256",
    ):
        if receipt.get(key) != candidate_manifest.get(key):
            raise V3ReportsBuildError(f"formal metrics receipt {key} mismatch")

    files = candidate_manifest.get("files")
    if not isinstance(files, dict) or set(files) != {
        "brand-health.json",
        "metrics.json",
        "periodized-metrics.json",
    }:
        raise V3ReportsBuildError("formal metrics candidate file set is invalid")
    for name, record in files.items():
        path = metrics_root / name
        if (
            not isinstance(record, dict)
            or set(record) != {"bytes", "sha256"}
            or record.get("bytes") != path.stat().st_size
            or record.get("sha256") != _sha256(path)
        ):
            raise V3ReportsBuildError(f"formal metrics file integrity mismatch: {name}")
    metrics = _v3_load_canonical(metrics_root / "metrics.json", "formal metrics")
    brand_health = _v3_load_canonical(
        metrics_root / "brand-health.json", "formal brand health"
    )
    periodized = _v3_load_hash_bound_object(
        metrics_root / "periodized-metrics.json", "formal periodized metrics"
    )
    comparison_contract_proven = attestation_sha is not None
    expected_comparison_basis = (
        "owner_attested_dataset_scope_window"
        if comparison_contract_proven
        else "not_owner_attested"
    )
    expected_unavailable_reasons = (
        []
        if comparison_contract_proven
        else ["historical_collection_coverage_not_owner_attested_complete"]
    )
    if (
        metrics.get("schema_version") != V3_METRICS_SCHEMA
        or metrics.get("boundaries") != V3_BOUNDARIES
        or metrics.get("indicator_count") != 26
        or not isinstance(metrics.get("indicators"), list)
        or len(metrics["indicators"]) != 26
        or brand_health.get("schema_version") != "reddit_voc_brand_health_index_v2"
        or brand_health.get("boundaries") != V3_BOUNDARIES
        or brand_health.get("lineage") != metrics.get("lineage")
    ):
        raise V3ReportsBuildError("formal metrics documents are invalid")
    lineage = metrics.get("lineage")
    source_snapshot_id = input_manifest.get("source_snapshot_id")
    if (
        not isinstance(lineage, dict)
        or lineage.get("source_snapshot_id") != source_snapshot_id
        or periodized.get("schema_version") != V3_FORMAL_PERIODIZED_SCHEMA
        or periodized.get("boundaries") != V3_BOUNDARIES
        or periodized.get("lineage") != lineage
        or periodized.get("timezone") != TIMEZONE_NAME
        or periodized.get("comparison_contract_proven")
        is not comparison_contract_proven
        or periodized.get("comparison_contract_basis")
        != expected_comparison_basis
        or periodized.get("comparison_unavailable_reason_codes")
        != expected_unavailable_reasons
        or periodized.get("data_owner_coverage_attestation_sha256")
        != attestation_sha
    ):
        raise V3ReportsBuildError("formal periodized metrics contract is invalid")
    coverage_attestation = periodized.get("coverage_attestation")
    if comparison_contract_proven:
        if not isinstance(coverage_attestation, dict) or set(coverage_attestation) != {
            "attestation_basis",
            "completeness_percent",
            "coverage_window",
            "evidence_class",
            "scope",
            "source_snapshot_id",
        } or (
            coverage_attestation.get("attestation_basis")
            != "data_owner_declaration"
            or coverage_attestation.get("completeness_percent") != 100
            or coverage_attestation.get("evidence_class")
            != "owner_attested_not_crawler_proof"
            or coverage_attestation.get("scope")
            != "canonical_observation_pool"
            or coverage_attestation.get("source_snapshot_id")
            != source_snapshot_id
        ):
            raise V3ReportsBuildError("coverage attestation summary is invalid")
    elif coverage_attestation is not None:
        raise V3ReportsBuildError("unattested metrics carry coverage attestation")
    latest_ids = periodized.get("latest_complete_period_ids")
    if not isinstance(latest_ids, dict) or set(latest_ids) != {
        "daily",
        "weekly",
        "monthly",
    }:
        raise V3ReportsBuildError("latest complete period IDs are invalid")
    daily_start, daily_end = _v3_parse_period_id(latest_ids["daily"], "daily")
    expected_windows = complete_period_windows(daily_end)
    if any(
        latest_ids[grain] != expected_windows[grain].current.period_id
        for grain in latest_ids
    ):
        raise V3ReportsBuildError("latest complete period IDs are not calendar exact")
    if comparison_contract_proven:
        assert isinstance(coverage_attestation, dict)
        coverage_window = coverage_attestation.get("coverage_window")
        if not isinstance(coverage_window, dict) or set(coverage_window) != {
            "end_calendar_date_inclusive",
            "start_calendar_date_inclusive",
        } or coverage_window.get("end_calendar_date_inclusive") != daily_start.isoformat():
            raise V3ReportsBuildError("coverage attestation window is invalid")

    rows = periodized.get("rows")
    brand_rows = periodized.get("brand_health_rows")
    brand_dimension_rows = periodized.get("brand_health_dimension_rows")
    activity_rows = periodized.get("activity_rows")
    if (
        not isinstance(rows, list)
        or len(rows) != candidate_manifest.get("periodized_metric_row_count")
        or len(rows) != periodized.get("metric_row_count")
        or not isinstance(brand_rows, list)
        or len(brand_rows)
        != candidate_manifest.get("periodized_brand_health_row_count")
        or len(brand_rows) != periodized.get("brand_health_row_count")
        or not isinstance(brand_dimension_rows, list)
        or len(brand_dimension_rows)
        != candidate_manifest.get("periodized_brand_health_dimension_row_count")
        or periodized.get("contract_extensions")
        != [V3_BRAND_HEALTH_DIMENSION_EXTENSION, V3_PERIOD_ACTIVITY_EXTENSION]
        or len(brand_dimension_rows)
        != periodized.get("brand_health_dimension_row_count")
        or len(brand_dimension_rows) != periodized.get("period_count") * 8
        or not isinstance(activity_rows, list)
        or len(activity_rows) != periodized.get("activity_row_count")
        or len(activity_rows) != periodized.get("period_count")
        or periodized.get("period_count") != candidate_manifest.get("period_count")
    ):
        raise V3ReportsBuildError("formal periodized metrics counts are invalid")
    expected_precision = {
        "daily": "calendar_day_assignment_v1",
        "weekly": "iso_week_assignment_v1",
        "monthly": "calendar_month_assignment_v1",
    }
    profile_values = {
        key: _v3_hex(periodized.get(key), key) for key in V3_PROFILE_KEYS
    }
    for row in rows:
        if not isinstance(row, dict) or set(row) != V3_FORMAL_ROW_FIELDS:
            raise V3ReportsBuildError("formal periodized metric row fields are invalid")
        grain = row.get("grain")
        if grain not in expected_precision or row.get("time_precision") != expected_precision[grain]:
            raise V3ReportsBuildError("formal periodized stable precision is invalid")
        start, _ = _v3_parse_period_id(row.get("period_id"), grain)
        if (
            row.get("source_calendar_date") != start.isoformat()
            or not isinstance(row.get("period_complete"), bool)
            or row.get("comparison_contract_proven")
            is not comparison_contract_proven
            or row.get("data_owner_coverage_attestation_sha256") != attestation_sha
            or (
                not comparison_contract_proven
                and row.get("period_complete") is not False
            )
            or any(row.get(key) != value for key, value in profile_values.items())
            or row.get("voc_type") != "post_voc+comment_context_voc"
            or not isinstance(row.get("observed_time_precision"), str)
            or not row["observed_time_precision"]
            or not isinstance(row.get("observed_voc_type"), str)
            or not row["observed_voc_type"]
        ):
            raise V3ReportsBuildError("formal periodized metric row contract is invalid")
    for row in brand_rows:
        if not isinstance(row, dict) or set(row) != V3_FORMAL_BRAND_HEALTH_ROW_FIELDS:
            raise V3ReportsBuildError("formal brand-health row fields are invalid")
        grain = row.get("grain")
        if (
            grain not in expected_precision
            or row.get("time_precision") != expected_precision[grain]
            or row.get("comparison_contract_proven")
            is not comparison_contract_proven
            or row.get("data_owner_coverage_attestation_sha256") != attestation_sha
            or (
                not comparison_contract_proven
                and row.get("period_complete") is not False
            )
            or row.get("period_complete") not in {True, False}
            or any(row.get(key) != value for key, value in profile_values.items())
        ):
            raise V3ReportsBuildError("formal brand-health row contract is invalid")
    dimension_keys: set[tuple[object, object, object, object]] = set()
    for row in brand_dimension_rows:
        if (
            not isinstance(row, dict)
            or set(row) != V3_FORMAL_BRAND_HEALTH_DIMENSION_ROW_FIELDS
        ):
            raise V3ReportsBuildError(
                "formal brand-health dimension row fields are invalid"
            )
        grain = row.get("grain")
        dimension_id = row.get("dimension_id")
        contribution = row.get("contribution_points")
        dimension_value = row.get("dimension_value")
        if (
            grain not in expected_precision
            or row.get("time_precision") != expected_precision[grain]
            or row.get("comparison_contract_proven")
            is not comparison_contract_proven
            or row.get("data_owner_coverage_attestation_sha256") != attestation_sha
            or (
                not comparison_contract_proven
                and row.get("period_complete") is not False
            )
            or row.get("period_complete") not in {True, False}
            or any(row.get(key) != value for key, value in profile_values.items())
            or row.get("comparison_side")
            not in {"raw_observed", "qualified_organic"}
            or dimension_id not in V3_BRAND_HEALTH_DIMENSIONS
            or row.get("metric_id") != "brand_health_dimension_contribution_v1"
            or row.get("scope") != "momcozy"
            or row.get("unit") != "index_points"
            or row.get("voc_type") != "post_voc+comment_context_voc"
            or row.get("weight_percent") != "25.00"
        ):
            raise V3ReportsBuildError(
                "formal brand-health dimension row contract is invalid"
            )
        if row.get("status") == "unavailable":
            if dimension_value is not None or contribution is not None:
                raise V3ReportsBuildError(
                    "unavailable brand-health dimension fabricated a value"
                )
        elif (
            not isinstance(dimension_value, str)
            or not isinstance(contribution, str)
        ):
            raise V3ReportsBuildError(
                "available brand-health dimension value is invalid"
            )
        else:
            try:
                parsed_dimension = Decimal(dimension_value)
                parsed_contribution = Decimal(contribution)
            except InvalidOperation as exc:
                raise V3ReportsBuildError(
                    "available brand-health dimension value is invalid"
                ) from exc
            expected_contribution = (parsed_dimension / Decimal(4)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if (
                not parsed_dimension.is_finite()
                or not parsed_contribution.is_finite()
                or parsed_dimension < 0
                or parsed_dimension > 100
                or parsed_contribution != expected_contribution
            ):
                raise V3ReportsBuildError(
                    "brand-health dimension contribution formula mismatch"
                )
        key = (
            grain,
            row.get("period_id"),
            row.get("comparison_side"),
            dimension_id,
        )
        if key in dimension_keys:
            raise V3ReportsBuildError("duplicate brand-health dimension row")
        dimension_keys.add(key)
    for row in activity_rows:
        if not isinstance(row, dict) or set(row) != V3_ACTIVITY_ROW_FIELDS:
            raise V3ReportsBuildError("formal period-activity row fields are invalid")
        grain = row.get("grain")
        if (
            grain not in expected_precision
            or row.get("time_precision") != expected_precision[grain]
            or row.get("comparison_contract_proven")
            is not comparison_contract_proven
            or row.get("data_owner_coverage_attestation_sha256") != attestation_sha
            or (
                not comparison_contract_proven
                and row.get("period_complete") is not False
            )
            or row.get("period_complete") not in {True, False}
            or any(row.get(key) != value for key, value in profile_values.items())
            or row.get("scope_contract")
            != {
                "all_observed": "canonical_observation_pool",
                "momcozy": "governed_brand_fact_equals_momcozy",
            }
        ):
            raise V3ReportsBuildError("formal period-activity row contract is invalid")
        for scope in ("all_observed", "momcozy"):
            counts = row.get(scope)
            if (
                not isinstance(counts, dict)
                or set(counts) != V3_ACTIVITY_COUNT_FIELDS
                or any(type(value) is not int or value < 0 for value in counts.values())
                or counts["new_comment_count"]
                != counts["comments_on_current_period_posts"]
                + counts["comments_on_historical_posts"]
                + counts["unresolved_parent_comment_count"]
                or counts["active_historical_post_count"]
                > counts["comments_on_historical_posts"]
            ):
                raise V3ReportsBuildError("formal period-activity counts are invalid")
    indicator_definitions = {
        row["reddit_indicator_id"]: row
        for row in metrics["indicators"]
        if isinstance(row, dict) and isinstance(row.get("reddit_indicator_id"), str)
    }
    if len(indicator_definitions) != 26:
        raise V3ReportsBuildError("formal metric definition set is invalid")
    return {
        "brand_health": brand_health,
        "candidate_manifest": candidate_manifest,
        "candidate_manifest_sha256": candidate_manifest_sha,
        "coverage_attestation": coverage_attestation,
        "data_owner_coverage_attestation_sha256": attestation_sha,
        "formal": True,
        "indicator_definitions": indicator_definitions,
        "input_manifest": input_manifest,
        "input_manifest_sha256": input_manifest_sha,
        "metrics": metrics,
        "periodized_metrics": periodized,
        "periodized_metrics_sha256": files["periodized-metrics.json"]["sha256"],
        "receipt": receipt,
        "receipt_sha256": receipt_sha,
        "source_snapshot_id": source_snapshot_id,
    }


def _v3_validate_binding(binding: dict[str, Any]) -> None:
    required = {
        "brand_health",
        "fixture_only",
        "indicator_ids",
        "manifest",
        "manifest_sha256",
        "metrics",
        "receipt",
        "receipt_sha256",
        "source_snapshot_id",
    }
    if not isinstance(binding, dict) or set(binding) != required:
        raise V3ReportsBuildError("metrics binding object is invalid")
    manifest_sha = _v3_hex(binding.get("manifest_sha256"), "metrics manifest SHA")
    receipt_sha = _v3_hex(binding.get("receipt_sha256"), "metrics receipt SHA")
    if sha256(_v3_canonical_bytes(binding.get("manifest"))).hexdigest() != manifest_sha:
        raise V3ReportsBuildError("in-memory metrics manifest binding mismatch")
    if sha256(_v3_canonical_bytes(binding.get("receipt"))).hexdigest() != receipt_sha:
        raise V3ReportsBuildError("in-memory metrics receipt binding mismatch")
    if binding["receipt"].get("bundle_manifest_sha256") != manifest_sha:
        raise V3ReportsBuildError("in-memory metrics receipt targets another manifest")


def _v3_shift_month(value: date, offset: int) -> date:
    index = value.year * 12 + value.month - 1 + offset
    return date(index // 12, index % 12 + 1, 1)


def _v3_parse_period_id(value: object, grain: str) -> tuple[date, date]:
    if not isinstance(value, str):
        raise V3ReportsBuildError("period ID is invalid")
    parts = value.split(":")
    if len(parts) != 3 or parts[0] != grain:
        raise V3ReportsBuildError("period ID/grain mismatch")
    try:
        start = date.fromisoformat(parts[1])
        end = date.fromisoformat(parts[2])
    except ValueError as exc:
        raise V3ReportsBuildError("period ID date is invalid") from exc
    if grain == "daily" and end != start + timedelta(days=1):
        raise V3ReportsBuildError("daily period is not one calendar day")
    if grain == "weekly" and (
        start.weekday() != 0 or end != start + timedelta(days=7)
    ):
        raise V3ReportsBuildError("weekly period is not one complete ISO week")
    if grain == "monthly" and (
        start.day != 1 or end != _v3_shift_month(start, 1)
    ):
        raise V3ReportsBuildError("monthly period is not one complete calendar month")
    return start, end


def _v3_validate_period_series(
    period_series: dict[str, Any], binding: dict[str, Any]
) -> tuple[date, list[dict[str, Any]]]:
    _v3_validate_binding(binding)
    expected_fields = {
        "as_of_date",
        "fixture_only",
        "metrics_manifest_sha256",
        "metrics_validation_receipt_sha256",
        "rows",
        "schema_version",
        "source_snapshot_id",
    }
    if not isinstance(period_series, dict) or set(period_series) != expected_fields:
        raise V3ReportsBuildError("period-series fields are invalid")
    if (
        period_series.get("schema_version") != V3_PERIOD_SERIES_SCHEMA
        or period_series.get("fixture_only") is not True
    ):
        raise V3ReportsBuildError("period series must remain explicitly fixture-only")
    if (
        period_series.get("metrics_manifest_sha256") != binding["manifest_sha256"]
        or period_series.get("metrics_validation_receipt_sha256")
        != binding["receipt_sha256"]
        or period_series.get("source_snapshot_id") != binding["source_snapshot_id"]
    ):
        raise V3ReportsBuildError("period series metrics binding mismatch")
    try:
        as_of_date = date.fromisoformat(period_series["as_of_date"])
    except (TypeError, ValueError) as exc:
        raise V3ReportsBuildError("period-series as-of date is invalid") from exc
    rows = period_series.get("rows")
    if not isinstance(rows, list) or not rows:
        raise V3ReportsBuildError("period series rows are invalid")
    allowed_metric_ids = set(binding["indicator_ids"])
    seen: set[tuple[str, str, str]] = set()
    current_grains: set[str] = set()
    expected_precision = {"daily": "day", "weekly": "week", "monthly": "month"}
    for row in rows:
        if not isinstance(row, dict) or set(row) != V3_ROW_FIELDS:
            raise V3ReportsBuildError("period-series row fields are invalid")
        grain = row.get("grain")
        if grain not in expected_precision:
            raise V3ReportsBuildError("period-series grain is invalid")
        metric_id = row.get("metric_id")
        if metric_id not in allowed_metric_ids:
            raise V3ReportsBuildError("period-series metric is absent from metrics candidate")
        if row.get("time_precision") != expected_precision[grain]:
            raise V3ReportsBuildError("period-series time precision mismatch")
        start, _ = _v3_parse_period_id(row.get("period_id"), grain)
        expected_source_date = start.strftime("%Y-%m") if grain == "monthly" else start.isoformat()
        if row.get("source_calendar_date") != expected_source_date:
            raise V3ReportsBuildError("floating source calendar date mismatch")
        key = (grain, row["period_id"], metric_id)
        if key in seen:
            raise V3ReportsBuildError("duplicate period-series metric row")
        seen.add(key)
        status = row.get("status")
        if status not in {"available", "provisional", "unavailable"}:
            raise V3ReportsBuildError("period-series status is invalid")
        if (status == "unavailable") != (row.get("value") is None):
            raise V3ReportsBuildError("period-series value/status mismatch")
        if row.get("unit") not in V3_FORMAL_COMPARABLE_UNITS | {"inherit", "rank"}:
            raise V3ReportsBuildError("period-series comparison unit is unsupported")
        if not isinstance(row.get("comparison_contract_proven"), bool):
            raise V3ReportsBuildError("comparison-contract flag is invalid")
        for field in (
            "metric_policy_version",
            "name_cn",
            "scope",
            "voc_type",
        ):
            if not isinstance(row.get(field), str) or not row[field]:
                raise V3ReportsBuildError(f"period-series {field} is invalid")
        for field in V3_PROFILE_KEYS:
            _v3_hex(row.get(field), field)
        for field in ("evidence_ids", "unavailable_reason_codes"):
            values = row.get(field)
            if (
                not isinstance(values, list)
                or any(not isinstance(value, str) or not value for value in values)
                or len(values) != len(set(values))
            ):
                raise V3ReportsBuildError(f"period-series {field} is invalid")
        current_grains.add(grain)
    if current_grains != set(expected_precision):
        raise V3ReportsBuildError("period series does not cover all report grains")
    return as_of_date, rows


def _v3_window_payload(window: Any) -> dict[str, Any] | None:
    if window is None:
        return None
    return {
        "end": window.end.isoformat(),
        "grain": window.grain,
        "is_complete": window.is_complete,
        "period_id": window.period_id,
        "start": window.start.isoformat(),
    }


def _v3_missing_row(
    current: dict[str, Any], window: Any, reason: str
) -> dict[str, Any]:
    value = dict(current)
    value.update(
        {
            "evidence_ids": [],
            "period_id": window.period_id if window is not None else "unavailable",
            "source_calendar_date": (
                window.start.strftime("%Y-%m")
                if window is not None and window.grain == "monthly"
                else window.start.isoformat()
                if window is not None
                else "unavailable"
            ),
            "status": "unavailable",
            "unavailable_reason_codes": [reason],
            "value": None,
        }
    )
    return value


def _v3_comparison_payload(
    current: dict[str, Any],
    baseline: dict[str, Any] | None,
    *,
    baseline_window: Any,
    comparison_basis: str,
    display_label: str,
    missing_reason: str,
) -> dict[str, Any]:
    from reddit_voc.v3_reporting_periods import compare_periods

    actual_baseline = baseline or _v3_missing_row(
        current, baseline_window, missing_reason
    )
    current_value = current.get("value")
    baseline_value = actual_baseline.get("value")
    if (
        current.get("status") in {"available", "provisional"}
        and actual_baseline.get("status") in {"available", "provisional"}
        and (
            current.get("unit") not in V3_FORMAL_COMPARABLE_UNITS
            or isinstance(current_value, (dict, list, tuple, bool))
            or isinstance(baseline_value, (dict, list, tuple, bool))
        )
    ):
        return {
            "baseline_period_id": (
                baseline_window.period_id if baseline_window is not None else None
            ),
            "baseline_status": actual_baseline["status"],
            "comparison_basis": comparison_basis,
            "current_period_id": current.get("period_id"),
            "direction": None,
            "display": "—",
            "display_label": display_label,
            "line_color": "gray",
            "profile_hashes": {
                "baseline": {
                    key: actual_baseline.get(key) for key in V3_PROFILE_KEYS
                },
                "current": {key: current.get(key) for key in V3_PROFILE_KEYS},
            },
            "reason_codes": ["non_scalar_metric_not_comparable"],
            "status": "unavailable",
            "unit": "unavailable",
            "value": None,
        }
    result = compare_periods(current, actual_baseline)
    reasons = set(result.reason_codes)
    if baseline is None:
        reasons.add(missing_reason)
    return {
        "baseline_period_id": (
            baseline_window.period_id if baseline_window is not None else None
        ),
        "baseline_status": actual_baseline["status"],
        "comparison_basis": comparison_basis,
        "current_period_id": current.get("period_id"),
        "direction": result.direction,
        "display": result.display,
        "display_label": display_label,
        "line_color": result.line_color,
        "profile_hashes": {
            "baseline": {
                key: actual_baseline.get(key) for key in V3_PROFILE_KEYS
            },
            "current": {key: current.get(key) for key in V3_PROFILE_KEYS},
        },
        "reason_codes": sorted(reasons),
        "status": result.status,
        "unit": result.unit,
        "value": result.value,
    }


def _v3_prior_windows(current: Any, count: int = 6) -> list[tuple[str, date]]:
    values: list[tuple[str, date]] = []
    for offset in range(count - 1, -1, -1):
        if current.grain == "daily":
            start = current.start - timedelta(days=offset)
            end = start + timedelta(days=1)
        elif current.grain == "weekly":
            start = current.start - timedelta(days=offset * 7)
            end = start + timedelta(days=7)
        else:
            start = _v3_shift_month(current.start, -offset)
            end = _v3_shift_month(start, 1)
        values.append((f"{current.grain}:{start.isoformat()}:{end.isoformat()}", start))
    return values


def _v3_row_contract_matches(
    current: dict[str, Any], candidate: dict[str, Any] | None
) -> bool:
    if candidate is None:
        return False
    contract_fields = (
        "metric_policy_version",
        "scope",
        "time_precision",
        "unit",
        "voc_type",
        *V3_PROFILE_KEYS,
    )
    return (
        current.get("status") in {"available", "provisional"}
        and candidate.get("status") in {"available", "provisional"}
        and current.get("value") is not None
        and candidate.get("value") is not None
        and current.get("unit") in V3_FORMAL_COMPARABLE_UNITS
        and not isinstance(current.get("value"), (dict, list, tuple, bool))
        and not isinstance(candidate.get("value"), (dict, list, tuple, bool))
        and all(current.get(key) == candidate.get(key) for key in contract_fields)
    )


def _v3_sparkline_payload(
    current: dict[str, Any],
    current_window: Any,
    lookup: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    from reddit_voc.v3_reporting_periods import build_sparkline, format_series_label

    grain_label = {"daily": "day", "weekly": "week", "monthly": "month"}[
        current_window.grain
    ]
    values: list[tuple[str, object]] = []
    comparable_rows: list[dict[str, Any]] = []
    for period_id, start in _v3_prior_windows(current_window):
        candidate = lookup.get((period_id, current["metric_id"]))
        source_value = (
            start.strftime("%Y-%m") if grain_label == "month" else start.isoformat()
        )
        label = format_series_label(source_value, grain=grain_label)
        if _v3_row_contract_matches(current, candidate):
            assert candidate is not None
            comparable_rows.append(candidate)
            values.append((label, candidate.get("value")))
        else:
            values.append((label, None))
    sparkline = build_sparkline(values)
    observed_same_profile = (
        current.get("comparison_contract_proven") is not True
        or any(
            row.get("comparison_contract_proven") is not True
            for row in comparable_rows
        )
    )
    reason_codes = list(sparkline.reason_codes)
    status = sparkline.status
    line_color = sparkline.line_color
    trend_claim_supported = sparkline.trend_claim_supported
    if sparkline.status != "unavailable" and observed_same_profile:
        status = "provisional"
        line_color = "blue"
        trend_claim_supported = False
        reason_codes.append(V3_OBSERVED_COMPARISON_REASON)
    return {
        "direction": sparkline.direction,
        "line_color": line_color,
        "points": [
            {"label": label, "value": value} for label, value in sparkline.points
        ],
        "reason_codes": sorted(set(reason_codes)),
        "status": status,
        "trend_claim_supported": trend_claim_supported,
    }


def build_v3_reports_snapshot(
    metrics_binding: dict[str, Any],
    period_series: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """Build six fixture-only V3 artifacts without changing the legacy builder."""

    from reddit_voc.v3_reporting_periods import complete_period_windows

    as_of_date, rows = _v3_validate_period_series(period_series, metrics_binding)
    windows = complete_period_windows(as_of_date)
    global_metric_lookup = {
        (row["period_id"], row["metric_id"]): row for row in rows
    }
    row_lookup = {
        (row["grain"], row["period_id"], row["metric_id"]): row for row in rows
    }
    reports: dict[str, dict[str, Any]] = {}
    index_entries: dict[str, dict[str, Any]] = {}
    for grain in ("daily", "weekly", "monthly"):
        comparison_windows = windows[grain]
        current_rows = sorted(
            (
                row
                for row in rows
                if row["grain"] == grain
                and row["period_id"] == comparison_windows.current.period_id
            ),
            key=lambda row: row["metric_id"],
        )
        if not current_rows:
            raise V3ReportsBuildError(f"latest complete {grain} period is missing")
        metric_lookup = {
            (row["period_id"], row["metric_id"]): row
            for row in rows
            if row["grain"] == grain
        }
        cards: list[dict[str, Any]] = []
        baselines: list[dict[str, Any]] = []
        for current in current_rows:
            previous = metric_lookup.get(
                (comparison_windows.previous.period_id, current["metric_id"])
            )
            yoy = (
                metric_lookup.get(
                    (
                        comparison_windows.year_over_year.period_id,
                        current["metric_id"],
                    )
                )
                if comparison_windows.year_over_year is not None
                else None
            )
            previous_comparison = _v3_comparison_payload(
                current,
                previous,
                baseline_window=comparison_windows.previous,
                comparison_basis="exact_period",
                display_label=(
                    "环比" if current.get("comparison_contract_proven") is True
                    else "环比（观测口径）"
                ),
                missing_reason="previous_period_missing",
            )
            yoy_comparison = _v3_comparison_payload(
                current,
                yoy,
                baseline_window=comparison_windows.year_over_year,
                comparison_basis="exact_period",
                display_label=(
                    "同比" if current.get("comparison_contract_proven") is True
                    else "同比（观测口径）"
                ),
                missing_reason=(
                    "year_over_year_period_not_defined"
                    if comparison_windows.year_over_year is None
                    else "year_over_year_period_missing"
                ),
            )
            fallback_reasons = {
                "baseline_value_missing",
                "baseline_value_unavailable",
                "baseline_zero_relative_change_undefined",
                "year_over_year_period_missing",
            }
            if (
                grain == "daily"
                and current.get("status") in {"available", "provisional"}
                and current.get("value") is not None
                and yoy_comparison["status"] == "unavailable"
                and fallback_reasons.intersection(yoy_comparison["reason_codes"])
            ):
                weekly_windows = windows["weekly"]
                weekly_current = global_metric_lookup.get(
                    (weekly_windows.current.period_id, current["metric_id"])
                )
                weekly_yoy = (
                    global_metric_lookup.get(
                        (
                            weekly_windows.year_over_year.period_id,
                            current["metric_id"],
                        )
                    )
                    if weekly_windows.year_over_year is not None
                    else None
                )
                if weekly_current is not None:
                    proxy_comparison = _v3_comparison_payload(
                        weekly_current,
                        weekly_yoy,
                        baseline_window=weekly_windows.year_over_year,
                        comparison_basis="seven_day_proxy",
                        display_label="同比（7日替代窗口）",
                        missing_reason="year_over_year_seven_day_proxy_missing",
                    )
                    if proxy_comparison["status"] != "unavailable":
                        proxy_comparison["reason_codes"] = sorted(
                            set(proxy_comparison["reason_codes"])
                            | {"exact_daily_yoy_unavailable_used_seven_day_proxy"}
                        )
                        proxy_comparison["status"] = "provisional"
                        proxy_comparison["line_color"] = "blue"
                        yoy_comparison = proxy_comparison
            sparkline = _v3_sparkline_payload(
                current, comparison_windows.current, metric_lookup
            )
            direction = (
                previous_comparison["direction"]
                if current["status"] != "unavailable"
                and current.get("comparison_contract_proven") is True
                else None
            )
            cards.append(
                {
                    "comparison_help": {
                        "symbol": "?",
                        "text": "环比采用上一完整同粒度日/周/月；同比优先采用上年同日、同 ISO 周或同月。日报精确同比不可计算时，使用明确标注的 7 日替代窗口。覆盖未获所有者确认时仅作观测口径展示。",
                    },
                    "comparisons": {
                        "period_over_period": previous_comparison,
                        "year_over_year": yoy_comparison,
                    },
                    "current": {
                        **current,
                        "display": current["value"] if current["value"] is not None else "—",
                    },
                    "direction": direction,
                    "line_color": (
                        previous_comparison["line_color"]
                        if direction is not None
                        else "gray"
                    ),
                    "metric_id": current["metric_id"],
                    "name_cn": current["name_cn"],
                    "sparkline": sparkline,
                }
            )
            baselines.append(
                {
                    "metric_id": current["metric_id"],
                    "name_cn": current["name_cn"],
                    "previous": previous
                    or _v3_missing_row(
                        current,
                        comparison_windows.previous,
                        "previous_period_missing",
                    ),
                    "year_over_year": yoy
                    or _v3_missing_row(
                        current,
                        comparison_windows.year_over_year,
                        (
                            "year_over_year_period_not_defined"
                            if comparison_windows.year_over_year is None
                            else "year_over_year_period_missing"
                        ),
                    ),
                }
            )
        current_path = f"current/{grain}.json"
        archive_path = f"archive/{grain}.json"
        source = {
            "metrics_manifest_sha256": metrics_binding["manifest_sha256"],
            "metrics_validation_receipt_sha256": metrics_binding["receipt_sha256"],
            "source_snapshot_id": metrics_binding["source_snapshot_id"],
        }
        reports[current_path] = {
            "artifact_role": "latest_complete_calendar_period",
            "boundaries": dict(V3_BOUNDARIES),
            "comparison_archive_path": archive_path,
            "entry_label": comparison_windows.entry_label,
            "fixture_only": True,
            "grain": grain,
            "indicators": cards,
            "period": _v3_window_payload(comparison_windows.current),
            "schema_version": V3_REPORT_SCHEMA,
            "source": source,
        }
        reports[archive_path] = {
            "artifact_role": "internal_comparison_archive",
            "baselines": baselines,
            "boundaries": dict(V3_BOUNDARIES),
            "business_entry_visible": False,
            "comparison_periods": {
                "previous": _v3_window_payload(comparison_windows.previous),
                "year_over_year": _v3_window_payload(
                    comparison_windows.year_over_year
                ),
            },
            "fixture_only": True,
            "grain": grain,
            "schema_version": V3_REPORT_SCHEMA,
            "source": source,
        }
        index_entries[grain] = {
            "artifact_path": current_path,
            "entry_label": comparison_windows.entry_label,
            "grain": grain,
            "period": _v3_window_payload(comparison_windows.current),
        }
    index = {
        "archive_policy": "internal_comparison_storage_not_a_business_entry",
        "as_of_date": as_of_date.isoformat(),
        "business_entry_count": 3,
        "fixture_only": True,
        "reports": index_entries,
        "schema_version": V3_REPORT_INDEX_SCHEMA,
        "source": {
            "metrics_manifest_sha256": metrics_binding["manifest_sha256"],
            "metrics_validation_receipt_sha256": metrics_binding["receipt_sha256"],
            "source_snapshot_id": metrics_binding["source_snapshot_id"],
        },
    }
    files = {
        name: {
            "bytes": len(_v3_canonical_bytes(document)),
            "sha256": sha256(_v3_canonical_bytes(document)).hexdigest(),
        }
        for name, document in sorted(
            {"report-index.json": index, **reports}.items()
        )
    }
    manifest = {
        "artifact_stage": "fixture_reports",
        "boundaries": dict(V3_BOUNDARIES),
        "fixture_only": True,
        "files": files,
        "metrics_manifest_sha256": metrics_binding["manifest_sha256"],
        "metrics_validation_receipt_sha256": metrics_binding["receipt_sha256"],
        "promotable": False,
        "report_count": 6,
        "schema_version": V3_REPORT_MANIFEST_SCHEMA,
        "source_snapshot_id": metrics_binding["source_snapshot_id"],
        "status": "fixture_only_waiting_for_periodized_metrics",
    }
    return reports, index, manifest


def _v3_write_exact(path: Path, value: Any) -> None:
    payload = _v3_canonical_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise V3ReportsBuildError(f"V3 output collision: {path}")
        return
    path.write_bytes(payload)


def _v3_safe_relative_path(root: Path, name: str, label: str) -> Path:
    if not isinstance(name, str) or not name or "\\" in name:
        raise V3ReportsBuildError(f"{label} path is unsafe")
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts or "." in relative.parts:
        raise V3ReportsBuildError(f"{label} path is unsafe")
    root_resolved = root.resolve()
    candidate = root_resolved / relative
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise V3ReportsBuildError(f"{label} path is unsafe")
    current = root_resolved
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise V3ReportsBuildError(f"{label} path is unsafe")
    return candidate


def _v3_assert_output_inventory(
    root: Path,
    expected_files: set[str],
    label: str,
    *,
    exact: bool,
    allowed_empty_directories: set[str] | None = None,
) -> None:
    expected_directories = {
        parent.as_posix()
        for name in expected_files
        for parent in Path(name).parents
        if parent != Path(".")
    }
    actual_files: set[str] = set()
    actual_directories: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise V3ReportsBuildError(f"{label} contains a symlink")
        relative = path.relative_to(root).as_posix()
        if path.is_file():
            actual_files.add(relative)
        elif path.is_dir():
            actual_directories.add(relative)
        else:
            raise V3ReportsBuildError(f"{label} contains an unsafe entry")
    allowed_directories = expected_directories | (allowed_empty_directories or set())
    if actual_directories - allowed_directories:
        raise V3ReportsBuildError(f"{label} contains undeclared directories")
    file_set_invalid = (
        actual_files != expected_files
        if exact
        else bool(actual_files - expected_files)
    )
    if file_set_invalid:
        raise V3ReportsBuildError(f"{label} contains undeclared files")


def write_v3_reports_snapshot(
    output_dir: Path,
    reports: dict[str, dict[str, Any]],
    index: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    if output_dir.is_symlink() or (output_dir.exists() and not output_dir.is_dir()):
        raise V3ReportsBuildError("V3 output root is invalid")
    output_dir.mkdir(parents=True, exist_ok=True)
    declared_files = set(manifest.get("files", {}))
    has_business_history = "business-history-index.json" in declared_files
    allowed_empty_directories: set[str] = set()
    expected_top_level = {
        "archive",
        "current",
        "manifest.json",
        "report-index.json",
    }
    if has_business_history:
        history_root = output_dir / "history"
        if history_root.is_symlink() or (
            history_root.exists() and not history_root.is_dir()
        ):
            raise V3ReportsBuildError("V3 history output root is invalid")
        history_root.mkdir(exist_ok=True)
        expected_top_level.update({"business-history-index.json", "history"})
        allowed_empty_directories.add("history")
    if {path.name for path in output_dir.iterdir()} - expected_top_level:
        raise V3ReportsBuildError("V3 output root contains undeclared entries")
    declared_document_paths = declared_files - {"report-index.json"}
    if set(reports) != declared_document_paths or not set(V3_REPORT_PATHS).issubset(reports):
        raise V3ReportsBuildError("V3 report artifact set is invalid")
    expected_output_files = set(manifest["files"]) | {"manifest.json"}
    _v3_assert_output_inventory(
        output_dir,
        expected_output_files,
        "V3 output root",
        exact=False,
        allowed_empty_directories=allowed_empty_directories,
    )
    _v3_write_exact(output_dir / "report-index.json", index)
    for name, document in sorted(reports.items()):
        _v3_write_exact(_v3_safe_relative_path(output_dir, name, "V3 report"), document)
    _v3_write_exact(output_dir / "manifest.json", manifest)
    _v3_assert_output_inventory(
        output_dir,
        expected_output_files,
        "V3 output root",
        exact=True,
        allowed_empty_directories=allowed_empty_directories,
    )
    return manifest


def _v3_validate_formal_binding(binding: dict[str, Any]) -> None:
    required = {
        "brand_health",
        "candidate_manifest",
        "candidate_manifest_sha256",
        "coverage_attestation",
        "data_owner_coverage_attestation_sha256",
        "formal",
        "indicator_definitions",
        "input_manifest",
        "input_manifest_sha256",
        "metrics",
        "periodized_metrics",
        "periodized_metrics_sha256",
        "receipt",
        "receipt_sha256",
        "source_snapshot_id",
    }
    if not isinstance(binding, dict) or set(binding) != required or binding.get("formal") is not True:
        raise V3ReportsBuildError("formal metrics binding object is invalid")
    for document_key, hash_key, label in (
        ("input_manifest", "input_manifest_sha256", "metrics input manifest"),
        ("candidate_manifest", "candidate_manifest_sha256", "metrics candidate manifest"),
        ("receipt", "receipt_sha256", "metrics validation receipt"),
    ):
        if sha256(_v3_canonical_bytes(binding[document_key])).hexdigest() != binding[hash_key]:
            raise V3ReportsBuildError(f"in-memory {label} binding mismatch")
    periodized = binding["periodized_metrics"]
    comparison_contract_proven = periodized.get("comparison_contract_proven")
    coverage_attestation = binding["coverage_attestation"]
    attestation_sha = binding["data_owner_coverage_attestation_sha256"]
    if (
        periodized.get("schema_version") != V3_FORMAL_PERIODIZED_SCHEMA
        or type(comparison_contract_proven) is not bool
        or periodized.get("coverage_attestation") != coverage_attestation
        or periodized.get("data_owner_coverage_attestation_sha256")
        != attestation_sha
        or (
            comparison_contract_proven
            and (
                not isinstance(coverage_attestation, dict)
                or coverage_attestation.get("completeness_percent") != 100
                or not isinstance(attestation_sha, str)
            )
        )
        or (
            not comparison_contract_proven
            and (coverage_attestation is not None or attestation_sha is not None)
        )
    ):
        raise V3ReportsBuildError("in-memory formal coverage binding mismatch")


def _v3_adapt_formal_row(row: dict[str, Any]) -> dict[str, Any]:
    adapted = {key: deepcopy(row[key]) for key in V3_ROW_FIELDS}
    adapted["comparison_contract_proven"] = bool(
        row["comparison_contract_proven"] and row["period_complete"]
    )
    adapted["time_precision"] = {
        "daily": "day",
        "weekly": "week",
        "monthly": "month",
    }[row["grain"]]
    if row["grain"] == "monthly":
        adapted["source_calendar_date"] = row["source_calendar_date"][:7]
    return adapted


def build_v3_formal_reports_snapshot(
    formal_binding: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """Build an immutable formal V3 report candidate.

    Unattested inputs retain provisional same-profile comparisons while owner
    completeness and formal market-trend claims remain disabled.
    """

    _v3_validate_formal_binding(formal_binding)
    periodized = formal_binding["periodized_metrics"]
    comparison_contract_proven = bool(
        periodized["comparison_contract_proven"]
    )
    comparison_contract_basis = periodized["comparison_contract_basis"]
    completeness_percent = 100 if comparison_contract_proven else None
    comparison_unavailable_reason_codes = list(
        periodized["comparison_unavailable_reason_codes"]
    )
    coverage_attestation = deepcopy(formal_binding["coverage_attestation"])
    attestation_sha = formal_binding[
        "data_owner_coverage_attestation_sha256"
    ]
    latest_ids = periodized["latest_complete_period_ids"]
    latest_daily_start, as_of_date = _v3_parse_period_id(
        latest_ids["daily"], "daily"
    )
    dataset_version = (
        f"reddit_voc_reports_{latest_daily_start.strftime('%Y%m%d')}_v3_"
        + formal_binding["candidate_manifest_sha256"][:12]
        + f"_{V3_REPORT_HISTORY_REVISION}"
    )
    from reddit_voc.v3_reporting_periods import complete_period_windows

    windows = complete_period_windows(as_of_date)
    selected_period_ids: set[str] = set()
    for grain, comparison in windows.items():
        selected_period_ids.update(
            period_id for period_id, _ in _v3_prior_windows(comparison.current)
        )
        selected_period_ids.add(comparison.previous.period_id)
        if comparison.year_over_year is not None:
            selected_period_ids.add(comparison.year_over_year.period_id)
    selected_rows = [
        row for row in periodized["rows"] if row["period_id"] in selected_period_ids
    ]
    original_lookup = {
        (row["grain"], row["period_id"], row["metric_id"]): row
        for row in periodized["rows"]
    }
    period_series = {
        "as_of_date": as_of_date.isoformat(),
        "fixture_only": True,
        "metrics_manifest_sha256": formal_binding["candidate_manifest_sha256"],
        "metrics_validation_receipt_sha256": formal_binding["receipt_sha256"],
        "rows": [_v3_adapt_formal_row(row) for row in selected_rows],
        "schema_version": V3_PERIOD_SERIES_SCHEMA,
        "source_snapshot_id": formal_binding["source_snapshot_id"],
    }
    compatibility_binding = {
        "brand_health": formal_binding["brand_health"],
        "fixture_only": False,
        "indicator_ids": tuple(formal_binding["indicator_definitions"]),
        "manifest": formal_binding["candidate_manifest"],
        "manifest_sha256": formal_binding["candidate_manifest_sha256"],
        "metrics": formal_binding["metrics"],
        "receipt": formal_binding["receipt"],
        "receipt_sha256": formal_binding["receipt_sha256"],
        "source_snapshot_id": formal_binding["source_snapshot_id"],
    }
    reports, index, _ = build_v3_reports_snapshot(
        compatibility_binding, period_series
    )
    source = {
        "coverage_attestation_sha256": formal_binding[
            "data_owner_coverage_attestation_sha256"
        ],
        "metrics_candidate_manifest_sha256": formal_binding[
            "candidate_manifest_sha256"
        ],
        "metrics_input_manifest_sha256": formal_binding["input_manifest_sha256"],
        "metrics_validation_receipt_sha256": formal_binding["receipt_sha256"],
        "periodized_metrics_sha256": formal_binding["periodized_metrics_sha256"],
        "source_snapshot_id": formal_binding["source_snapshot_id"],
    }
    analysis_frame = {
        "comparison_brand_role": "competitor_union",
        "comparison_metric_ids": ["RV-BR-05", "RV-PS-04"],
        "primary_brand": "Momcozy",
        "unavailable_comparison_policy": "retain_null_value_and_reason_codes",
    }
    brand_rows = list(periodized["brand_health_rows"])
    brand_lookup = {
        (row["grain"], row["period_id"], row["comparison_side"]): row
        for row in brand_rows
    }
    brand_dimension_rows = list(periodized["brand_health_dimension_rows"])
    brand_dimension_lookup: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in brand_dimension_rows:
        brand_dimension_lookup[(row["grain"], row["period_id"])].append(row)
    activity_lookup = {
        (row["grain"], row["period_id"]): row
        for row in periodized["activity_rows"]
    }
    for grain in ("daily", "weekly", "monthly"):
        comparison = windows[grain]
        current_report = reports[f"current/{grain}.json"]
        archive_report = reports[f"archive/{grain}.json"]
        if not comparison_contract_proven:
            current_report["artifact_role"] = (
                "latest_closed_calendar_period_unattested"
            )
            current_report["entry_label"] = "最新闭合周期（覆盖未证明）"
            index["reports"][grain]["entry_label"] = (
                "最新闭合周期（覆盖未证明）"
            )
        for document in (current_report, archive_report):
            document.update(
                {
                    "analysis_frame": deepcopy(analysis_frame),
                    "comparison_contract_basis": comparison_contract_basis,
                    "comparison_contract_proven": comparison_contract_proven,
                    "comparison_unavailable_reason_codes": deepcopy(
                        comparison_unavailable_reason_codes
                    ),
                    "completeness_percent": completeness_percent,
                    "coverage_attestation": deepcopy(coverage_attestation),
                    "data_owner_coverage_attestation_sha256": formal_binding[
                        "data_owner_coverage_attestation_sha256"
                    ],
                    "fixture_only": False,
                    "source": deepcopy(source),
                }
            )
        for card in current_report["indicators"]:
            metric_id = card["metric_id"]
            original = original_lookup[
                (grain, comparison.current.period_id, metric_id)
            ]
            card["current"] = {
                **deepcopy(original),
                "display": original["value"] if original["value"] is not None else "—",
            }
            definition = formal_binding["indicator_definitions"][metric_id]
            card["metric_definition"] = {
                "comparison_side": definition["comparison_side"],
                "metric_family": definition["metric_family"],
                "output_shape": definition["output_shape"],
            }
            if original["status"] == "unavailable":
                card["direction"] = None
                card["line_color"] = "gray"
        current_brand_rows = []
        for side in ("raw_observed", "qualified_organic"):
            brand_row = deepcopy(
                brand_lookup[(grain, comparison.current.period_id, side)]
            )
            brand_row["display"] = (
                brand_row["value"] if brand_row["value"] is not None else "—"
            )
            current_brand_rows.append(brand_row)
        current_report["brand_health"] = {
            "dimension_rows": [
                deepcopy(row)
                for row in brand_dimension_lookup[
                    (grain, comparison.current.period_id)
                ]
            ],
            "metric_id": "brand_health_index_v2",
            "rows": current_brand_rows,
            "scope": "momcozy",
        }
        current_report["period_activity"] = deepcopy(
            activity_lookup[(grain, comparison.current.period_id)]
        )
        if grain == "weekly":
            current_report["action_review"] = {
                "completion_supported": False,
                "items": [],
                "ledger_available": False,
                "reason_codes": ["action_ledger_not_supplied"],
                "schema_version": "reddit_voc_action_review_v1",
                "status": "unavailable",
            }
        for baseline in archive_report["baselines"]:
            metric_id = baseline["metric_id"]
            previous = original_lookup.get(
                (grain, comparison.previous.period_id, metric_id)
            )
            if previous is not None:
                baseline["previous"] = deepcopy(previous)
            if comparison.year_over_year is not None:
                yoy = original_lookup.get(
                    (grain, comparison.year_over_year.period_id, metric_id)
                )
                if yoy is not None:
                    baseline["year_over_year"] = deepcopy(yoy)
        archive_report["brand_health_baselines"] = [
            deepcopy(row)
            for row in brand_rows
            if row["grain"] == grain
            and row["period_id"]
            in {
                comparison.previous.period_id,
                comparison.year_over_year.period_id
                if comparison.year_over_year is not None
                else "",
            }
        ]
        archive_report["brand_health_dimension_baselines"] = [
            deepcopy(row)
            for row in brand_dimension_rows
            if row["grain"] == grain
            and row["period_id"]
            in {
                comparison.previous.period_id,
                comparison.year_over_year.period_id
                if comparison.year_over_year is not None
                else "",
            }
        ]

    history_entries: dict[str, list[dict[str, Any]]] = {
        "daily": [],
        "weekly": [],
        "monthly": [],
    }
    historical_periods: dict[str, list[tuple[str, date, date]]] = {}
    for grain in ("daily", "weekly", "monthly"):
        current = windows[grain].current
        limit = V3_HISTORY_LIMITS[grain]
        expected: list[tuple[str, date, date]] = []
        for offset in range(1, limit + 1):
            if grain == "daily":
                start = current.start - timedelta(days=offset)
                end = start + timedelta(days=1)
            elif grain == "weekly":
                start = current.start - timedelta(days=offset * 7)
                end = start + timedelta(days=7)
            else:
                start = _v3_shift_month(current.start, -offset)
                end = _v3_shift_month(start, 1)
            expected.append((f"{grain}:{start.isoformat()}:{end.isoformat()}", start, end))
        # Closed observed periods are valid business-history entries even when
        # full crawler coverage is not owner-attested.  Their payload keeps the
        # comparison contract disabled, so this opens browsing without
        # manufacturing completeness or trend claims.
        available = {
            row["period_id"]
            for row in periodized["rows"]
            if row["grain"] == grain
        }
        missing = [period_id for period_id, _, _ in expected if period_id not in available]
        if missing:
            raise V3ReportsBuildError(
                f"formal {grain} history is not contiguous: {missing[0]} is missing"
            )
        historical_periods[grain] = expected

    adapted_rows_by_period: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in periodized["rows"]:
        adapted_rows_by_period[row["period_id"]].append(_v3_adapt_formal_row(row))
    history_fixture_cache: dict[date, dict[str, dict[str, Any]]] = {}
    for grain in ("daily", "weekly", "monthly"):
        for period_id, start, end in historical_periods[grain]:
            if end not in history_fixture_cache:
                target_windows = complete_period_windows(end)
                required_period_ids: set[str] = set()
                for target_comparison in target_windows.values():
                    required_period_ids.update(
                        item[0] for item in _v3_prior_windows(target_comparison.current)
                    )
                    required_period_ids.add(target_comparison.previous.period_id)
                    if target_comparison.year_over_year is not None:
                        required_period_ids.add(
                            target_comparison.year_over_year.period_id
                        )
                target_rows = [
                    row
                    for required_period_id in sorted(required_period_ids)
                    for row in adapted_rows_by_period.get(required_period_id, [])
                ]
                generated, _, _ = build_v3_reports_snapshot(
                    compatibility_binding,
                    {
                        **period_series,
                        "as_of_date": end.isoformat(),
                        "rows": target_rows,
                    },
                )
                history_fixture_cache[end] = generated
            report = deepcopy(history_fixture_cache[end][f"current/{grain}.json"])
            historical_role = (
                "historical_complete_calendar_period"
                if comparison_contract_proven
                else "historical_observed_calendar_period_unattested"
            )
            historical_label = (
                "历史完整周期"
                if comparison_contract_proven
                else "历史已观测周期（覆盖未证明）"
            )
            report.update(
                {
                    "analysis_frame": deepcopy(analysis_frame),
                    "artifact_role": historical_role,
                    "business_entry_visible": True,
                    "comparison_contract_basis": comparison_contract_basis,
                    "comparison_contract_proven": comparison_contract_proven,
                    "comparison_unavailable_reason_codes": deepcopy(
                        comparison_unavailable_reason_codes
                    ),
                    "completeness_percent": completeness_percent,
                    "coverage_attestation": deepcopy(coverage_attestation),
                    "data_owner_coverage_attestation_sha256": formal_binding[
                        "data_owner_coverage_attestation_sha256"
                    ],
                    "entry_label": historical_label,
                    "fixture_only": False,
                    "source": deepcopy(source),
                }
            )
            report.pop("comparison_archive_path", None)
            for card in report["indicators"]:
                metric_id = card["metric_id"]
                original = original_lookup[(grain, period_id, metric_id)]
                card["current"] = {
                    **deepcopy(original),
                    "display": (
                        original["value"] if original["value"] is not None else "—"
                    ),
                }
                definition = formal_binding["indicator_definitions"][metric_id]
                card["metric_definition"] = {
                    "comparison_side": definition["comparison_side"],
                    "metric_family": definition["metric_family"],
                    "output_shape": definition["output_shape"],
                }
                if original["status"] == "unavailable":
                    card["direction"] = None
                    card["line_color"] = "gray"
            current_brand_rows = []
            for side in ("raw_observed", "qualified_organic"):
                brand_row = deepcopy(brand_lookup[(grain, period_id, side)])
                brand_row["display"] = (
                    brand_row["value"] if brand_row["value"] is not None else "—"
                )
                current_brand_rows.append(brand_row)
            report["brand_health"] = {
                "dimension_rows": [
                    deepcopy(row)
                    for row in brand_dimension_lookup[(grain, period_id)]
                ],
                "metric_id": "brand_health_index_v2",
                "rows": current_brand_rows,
                "scope": "momcozy",
            }
            report["period_activity"] = deepcopy(activity_lookup[(grain, period_id)])
            if grain == "weekly":
                report["action_review"] = {
                    "completion_supported": False,
                    "items": [],
                    "ledger_available": False,
                    "reason_codes": ["action_ledger_not_supplied"],
                    "schema_version": "reddit_voc_action_review_v1",
                    "status": "unavailable",
                }
            path_slug = (
                start.isoformat()
                if grain == "daily"
                else f"{start.isoformat()}_{(end - timedelta(days=1)).isoformat()}"
                if grain == "weekly"
                else start.strftime("%Y-%m")
            )
            artifact_path = f"history/{grain}/{path_slug}.json"
            report_bytes = _v3_canonical_bytes(report)
            reports[artifact_path] = report
            history_entries[grain].append(
                {
                    "artifact_path": artifact_path,
                    "artifact_sha256": sha256(report_bytes).hexdigest(),
                    "entry_label": historical_label,
                    "grain": grain,
                    "period": {
                        "end": end.isoformat(),
                        "grain": grain,
                        "is_complete": True,
                        "period_id": period_id,
                        "start": start.isoformat(),
                    },
                }
            )

    history_count = sum(len(entries) for entries in history_entries.values())
    history_index = {
        "as_of_date": as_of_date.isoformat(),
        "coverage_attestation": deepcopy(coverage_attestation),
        "comparison_unavailable_reason_codes": deepcopy(
            comparison_unavailable_reason_codes
        ),
        "data_owner_coverage_attestation_sha256": formal_binding[
            "data_owner_coverage_attestation_sha256"
        ],
        "dataset_version": dataset_version,
        "history_entry_count": history_count,
        "latest_complete_period_excluded": True,
        "limits": dict(V3_HISTORY_LIMITS),
        "order": "newest_first",
        "reports": history_entries,
        "schema_version": V3_BUSINESS_HISTORY_INDEX_SCHEMA,
        "source": deepcopy(source),
        "total_business_entry_count": 3 + history_count,
    }
    reports["business-history-index.json"] = history_index
    index.update(
        {
            "business_entry_count": 3 + history_count,
            "business_history_index_path": "business-history-index.json",
            "comparison_contract_basis": comparison_contract_basis,
            "comparison_contract_proven": comparison_contract_proven,
            "comparison_unavailable_reason_codes": deepcopy(
                comparison_unavailable_reason_codes
            ),
            "completeness_percent": completeness_percent,
            "coverage_attestation": deepcopy(coverage_attestation),
            "data_owner_coverage_attestation_sha256": formal_binding[
                "data_owner_coverage_attestation_sha256"
            ],
            "dataset_version": dataset_version,
            "fixture_only": False,
            "current_entry_count": 3,
            "history_entry_count": history_count,
            "source": deepcopy(source),
        }
    )
    current_cards = [
        card
        for grain in ("daily", "weekly", "monthly")
        for card in reports[f"current/{grain}.json"]["indicators"]
    ]
    summary = {
        "current_available": sum(
            card["current"]["status"] == "available" for card in current_cards
        ),
        "current_provisional": sum(
            card["current"]["status"] == "provisional" for card in current_cards
        ),
        "current_unavailable": sum(
            card["current"]["status"] == "unavailable" for card in current_cards
        ),
        "period_over_period_available": sum(
            card["comparisons"]["period_over_period"]["status"] == "available"
            for card in current_cards
        ),
        "period_over_period_provisional": sum(
            card["comparisons"]["period_over_period"]["status"] == "provisional"
            for card in current_cards
        ),
        "period_over_period_unavailable": sum(
            card["comparisons"]["period_over_period"]["status"] == "unavailable"
            for card in current_cards
        ),
        "trend_observed": sum(
            card["sparkline"]["status"] != "unavailable"
            for card in current_cards
        ),
        "trend_supported": sum(
            card["sparkline"]["trend_claim_supported"] is True
            for card in current_cards
        ),
        "year_over_year_available": sum(
            card["comparisons"]["year_over_year"]["status"] == "available"
            for card in current_cards
        ),
        "year_over_year_provisional": sum(
            card["comparisons"]["year_over_year"]["status"] == "provisional"
            for card in current_cards
        ),
        "year_over_year_unavailable": sum(
            card["comparisons"]["year_over_year"]["status"] == "unavailable"
            for card in current_cards
        ),
    }
    documents = {"report-index.json": index, **reports}
    files = {
        name: {
            "bytes": len(_v3_canonical_bytes(document)),
            "sha256": sha256(_v3_canonical_bytes(document)).hexdigest(),
        }
        for name, document in sorted(documents.items())
    }
    manifest = {
        "artifact_stage": "reports_candidate",
        "boundaries": dict(V3_BOUNDARIES),
        "comparison_contract_basis": comparison_contract_basis,
        "comparison_contract_proven": comparison_contract_proven,
        "comparison_unavailable_reason_codes": comparison_unavailable_reason_codes,
        "completeness_percent": completeness_percent,
        "contract_extensions": list(V3_REPORT_CONTRACT_EXTENSIONS),
        "consumption_status": "blocked_pending_independent_validation",
        "coverage_attestation": coverage_attestation,
        "data_owner_coverage_attestation_sha256": formal_binding[
            "data_owner_coverage_attestation_sha256"
        ],
        "dataset_version": dataset_version,
        "files": files,
        "fixture_only": False,
        "business_entry_count": 3 + history_count,
        "history_report_count": history_count,
        "independent_validation_status": "pending",
        "metrics_candidate_manifest_sha256": formal_binding[
            "candidate_manifest_sha256"
        ],
        "metrics_input_manifest_sha256": formal_binding["input_manifest_sha256"],
        "metrics_validation_receipt_sha256": formal_binding["receipt_sha256"],
        "periodized_metrics_sha256": formal_binding["periodized_metrics_sha256"],
        "promotable": False,
        "report_count": 6 + history_count,
        "schema_version": V3_REPORT_MANIFEST_SCHEMA,
        "source_snapshot_id": formal_binding["source_snapshot_id"],
        "status": "candidate_built",
        "summary": summary,
    }
    return reports, index, manifest


def _v3_assert_privacy_safe(value: Any, path: str = "root") -> None:
    prohibited_keys = {
        "author",
        "body",
        "content",
        "email",
        "permalink",
        "raw_text",
        "selftext",
        "title",
        "url",
        "username",
    }
    if isinstance(value, dict):
        overlap = prohibited_keys & set(value)
        if overlap:
            raise V3ReportsBuildError(
                f"public report contains prohibited fields at {path}: {sorted(overlap)}"
            )
        for key, child in value.items():
            _v3_assert_privacy_safe(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _v3_assert_privacy_safe(child, f"{path}[{index}]")


def _v3_history_paths_from_index(index: dict[str, Any]) -> set[str]:
    if (
        not isinstance(index, dict)
        or index.get("schema_version") != V3_BUSINESS_HISTORY_INDEX_SCHEMA
        or index.get("limits") != V3_HISTORY_LIMITS
        or index.get("order") != "newest_first"
        or index.get("latest_complete_period_excluded") is not True
        or set(index.get("reports", {})) != set(V3_HISTORY_LIMITS)
    ):
        raise V3ReportsBuildError("business history index contract is invalid")
    paths: set[str] = set()
    count = 0
    attested = index.get("coverage_attestation") is not None
    if not attested and index.get("data_owner_coverage_attestation_sha256") is not None:
        raise V3ReportsBuildError("unattested business history carries an attestation SHA")
    history_entry_count = index.get("history_entry_count")
    if history_entry_count not in {0, sum(V3_HISTORY_LIMITS.values())}:
        raise V3ReportsBuildError("business history index count is invalid")
    for grain, limit in V3_HISTORY_LIMITS.items():
        entries = index["reports"].get(grain)
        expected_count = limit if history_entry_count else 0
        if not isinstance(entries, list) or len(entries) != expected_count:
            raise V3ReportsBuildError("business history index count is invalid")
        previous_start: date | None = None
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {
                "artifact_path",
                "artifact_sha256",
                "entry_label",
                "grain",
                "period",
            }:
                raise V3ReportsBuildError("business history entry fields are invalid")
            path = entry["artifact_path"]
            if (
                not isinstance(path, str)
                or re.fullmatch(rf"history/{grain}/[0-9_-]+\.json", path) is None
                or path in paths
                or entry.get("entry_label")
                != (
                    "历史完整周期"
                    if attested
                    else "历史已观测周期（覆盖未证明）"
                )
                or entry.get("grain") != grain
                or re.fullmatch(r"[a-f0-9]{64}", str(entry.get("artifact_sha256")))
                is None
            ):
                raise V3ReportsBuildError("business history entry path is invalid")
            period = entry.get("period")
            if (
                not isinstance(period, dict)
                or period.get("grain") != grain
                or period.get("is_complete") is not True
                or not isinstance(period.get("start"), str)
                or not isinstance(period.get("end"), str)
                or period.get("start") >= period.get("end", "")
            ):
                raise V3ReportsBuildError("business history entry period is invalid")
            start, end = _v3_parse_period_id(period.get("period_id"), grain)
            if period.get("start") != start.isoformat() or period.get("end") != end.isoformat():
                raise V3ReportsBuildError("business history entry period ID mismatch")
            expected_slug = (
                start.isoformat()
                if grain == "daily"
                else f"{start.isoformat()}_{(end - timedelta(days=1)).isoformat()}"
                if grain == "weekly"
                else start.strftime("%Y-%m")
            )
            if path != f"history/{grain}/{expected_slug}.json":
                raise V3ReportsBuildError("business history entry path/period mismatch")
            if previous_start is not None:
                expected_start = (
                    previous_start - timedelta(days=1)
                    if grain == "daily"
                    else previous_start - timedelta(days=7)
                    if grain == "weekly"
                    else _v3_shift_month(previous_start, -1)
                )
                if start != expected_start:
                    raise V3ReportsBuildError("business history entries are not contiguous")
            previous_start = start
            paths.add(path)
            count += 1
    if (
        index.get("history_entry_count") != count
        or index.get("total_business_entry_count") != count + 3
    ):
        raise V3ReportsBuildError("business history index totals are invalid")
    return paths


def _v3_validate_history_lineage(
    history_index: dict[str, Any],
    report_index: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    if (
        history_index.get("dataset_version") != manifest.get("dataset_version")
        or history_index.get("as_of_date") != report_index.get("as_of_date")
        or history_index.get("source") != report_index.get("source")
        or history_index.get("coverage_attestation")
        != report_index.get("coverage_attestation")
        or history_index.get("data_owner_coverage_attestation_sha256")
        != manifest.get("data_owner_coverage_attestation_sha256")
        or report_index.get("business_history_index_path")
        != "business-history-index.json"
        or report_index.get("current_entry_count") != 3
        or report_index.get("history_entry_count")
        != history_index.get("history_entry_count")
        or report_index.get("business_entry_count")
        != history_index.get("total_business_entry_count")
    ):
        raise V3ReportsBuildError("business history index lineage mismatch")
    for grain, entries in history_index["reports"].items():
        if not entries:
            continue
        current_period = report_index.get("reports", {}).get(grain, {}).get("period", {})
        try:
            current_start = date.fromisoformat(current_period["start"])
        except (KeyError, TypeError, ValueError) as exc:
            raise V3ReportsBuildError("current report index period is invalid") from exc
        first_start, _ = _v3_parse_period_id(entries[0]["period"]["period_id"], grain)
        expected_first = (
            current_start - timedelta(days=1)
            if grain == "daily"
            else current_start - timedelta(days=7)
            if grain == "weekly"
            else _v3_shift_month(current_start, -1)
        )
        if first_start != expected_first:
            raise V3ReportsBuildError("business history overlaps or skips current period")


def build_v3_public_reports_wrapper(
    candidate_dir: Path,
    validation_receipt_path: Path,
    *,
    expected_candidate_manifest_sha256: str,
    expected_validation_receipt_sha256: str,
) -> tuple[
    dict[str, dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any]
]:
    """Wrap validated formal reports without mutating their lineage candidate."""

    candidate_sha = _v3_hex(
        expected_candidate_manifest_sha256, "candidate reports manifest SHA"
    )
    receipt_sha = _v3_hex(
        expected_validation_receipt_sha256, "reports validation receipt SHA"
    )
    candidate_dir = Path(candidate_dir)
    receipt_path = Path(validation_receipt_path)
    if candidate_dir.is_symlink() or not candidate_dir.is_dir():
        raise V3ReportsBuildError("candidate reports root is invalid")
    candidate_manifest_path = candidate_dir / "manifest.json"
    if _sha256(candidate_manifest_path) != candidate_sha:
        raise V3ReportsBuildError("candidate reports manifest SHA mismatch")
    if (
        receipt_path.is_symlink()
        or not receipt_path.is_file()
        or _sha256(receipt_path) != receipt_sha
    ):
        raise V3ReportsBuildError("reports validation receipt SHA mismatch")
    candidate_manifest = _v3_load_canonical(
        candidate_manifest_path, "candidate reports manifest"
    )
    validation_receipt = _v3_load_canonical(
        receipt_path, "reports validation receipt"
    )
    comparison_contract_proven = candidate_manifest.get(
        "comparison_contract_proven"
    )
    if type(comparison_contract_proven) is not bool:
        raise V3ReportsBuildError("validated reports comparison state is invalid")
    expected_history_count = candidate_manifest.get("history_report_count")
    if expected_history_count not in (
        {38} if comparison_contract_proven else {0, 38}
    ):
        raise V3ReportsBuildError("validated reports history state is invalid")
    expected_report_count = 6 + expected_history_count
    expected_business_count = 3 + expected_history_count
    expected_completeness = 100 if comparison_contract_proven else None
    if (
        candidate_manifest.get("schema_version") != V3_REPORT_MANIFEST_SCHEMA
        or candidate_manifest.get("artifact_stage") != "reports_candidate"
        or candidate_manifest.get("status") != "candidate_built"
        or candidate_manifest.get("promotable") is not False
        or candidate_manifest.get("fixture_only") is not False
        or candidate_manifest.get("report_count") != expected_report_count
        or candidate_manifest.get("history_report_count")
        != expected_history_count
        or candidate_manifest.get("business_entry_count")
        != expected_business_count
        or candidate_manifest.get("contract_extensions")
        != list(V3_REPORT_CONTRACT_EXTENSIONS)
        or validation_receipt.get("schema_version")
        != "reddit_voc_reports_validation_receipt_v3"
        or validation_receipt.get("status") != "passed_candidate_only"
        or validation_receipt.get("promotable") is not True
        or validation_receipt.get("bundle_manifest_sha256") != candidate_sha
        or validation_receipt.get("comparison_contract_proven")
        is not comparison_contract_proven
        or validation_receipt.get("completeness_percent")
        != expected_completeness
        or validation_receipt.get("report_count") != expected_report_count
        or validation_receipt.get("history_report_count")
        != expected_history_count
        or validation_receipt.get("business_entry_count")
        != expected_business_count
        or validation_receipt.get("data_owner_coverage_attestation_sha256")
        != candidate_manifest.get("data_owner_coverage_attestation_sha256")
    ):
        raise V3ReportsBuildError("validated reports lifecycle binding is invalid")
    candidate_files = candidate_manifest.get("files")
    if not isinstance(candidate_files, dict) or "business-history-index.json" not in candidate_files:
        raise V3ReportsBuildError("candidate reports file set is invalid")
    documents: dict[str, dict[str, Any]] = {}
    for name in candidate_files:
        _v3_safe_relative_path(candidate_dir, name, "candidate report")
    for name, record in sorted(candidate_files.items()):
        path = _v3_safe_relative_path(candidate_dir, name, "candidate report")
        if (
            path.is_symlink()
            or not path.is_file()
            or not isinstance(record, dict)
            or set(record) != {"bytes", "sha256"}
            or record.get("bytes") != path.stat().st_size
            or record.get("sha256") != _sha256(path)
        ):
            raise V3ReportsBuildError(f"candidate report file integrity mismatch: {name}")
        document = _v3_load_canonical(path, name)
        _v3_assert_privacy_safe(document, name)
        documents[name] = document
    history_index = documents["business-history-index.json"]
    history_paths = _v3_history_paths_from_index(history_index)
    _v3_validate_history_lineage(
        history_index,
        documents["report-index.json"],
        candidate_manifest,
    )
    expected_candidate_files = {
        "business-history-index.json",
        "report-index.json",
        *V3_REPORT_PATHS,
        *history_paths,
    }
    if set(candidate_files) != expected_candidate_files:
        raise V3ReportsBuildError("candidate reports file set is invalid")
    for grain_entries in history_index["reports"].values():
        for entry in grain_entries:
            if candidate_files[entry["artifact_path"]]["sha256"] != entry["artifact_sha256"]:
                raise V3ReportsBuildError("business history index SHA binding mismatch")
    reports = {
        name: documents[name]
        for name in sorted(set(documents) - {"report-index.json"})
    }
    index = documents["report-index.json"]
    receipt_payload = _v3_canonical_bytes(validation_receipt)
    files = {
        name: deepcopy(record) for name, record in sorted(candidate_files.items())
    }
    files["validation-receipt.json"] = {
        "bytes": len(receipt_payload),
        "sha256": receipt_sha,
    }
    public_manifest = {
        "artifact_stage": "reports_public_candidate",
        "boundaries": dict(V3_BOUNDARIES),
        "comparison_contract_basis": candidate_manifest[
            "comparison_contract_basis"
        ],
        "comparison_contract_proven": comparison_contract_proven,
        "comparison_unavailable_reason_codes": deepcopy(
            candidate_manifest["comparison_unavailable_reason_codes"]
        ),
        "completeness_percent": expected_completeness,
        "contract_extensions": deepcopy(candidate_manifest["contract_extensions"]),
        "consumption_status": "eligible_for_frontend_candidate_consumption",
        "coverage_attestation": deepcopy(candidate_manifest["coverage_attestation"]),
        "data_owner_coverage_attestation_sha256": candidate_manifest[
            "data_owner_coverage_attestation_sha256"
        ],
        "dataset_version": candidate_manifest["dataset_version"],
        "files": files,
        "fixture_only": False,
        "business_entry_count": candidate_manifest["business_entry_count"],
        "history_report_count": candidate_manifest["history_report_count"],
        "independent_validation_status": "passed",
        "lineage_manifest_sha256": candidate_sha,
        "privacy_safe_projection": True,
        "promotable": True,
        "report_count": candidate_manifest["report_count"],
        "schema_version": V3_PUBLIC_REPORT_MANIFEST_SCHEMA,
        "source_snapshot_id": candidate_manifest["source_snapshot_id"],
        "status": "validated_candidate",
        "summary": deepcopy(candidate_manifest["summary"]),
        "validation_receipt_sha256": receipt_sha,
    }
    return reports, index, validation_receipt, public_manifest


def write_v3_public_reports_wrapper(
    output_dir: Path,
    reports: dict[str, dict[str, Any]],
    index: dict[str, Any],
    validation_receipt: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    if output_dir.is_symlink() or (output_dir.exists() and not output_dir.is_dir()):
        raise V3ReportsBuildError("public reports output root is invalid")
    output_dir.mkdir(parents=True, exist_ok=True)
    history_root = output_dir / "history"
    if history_root.is_symlink() or (
        history_root.exists() and not history_root.is_dir()
    ):
        raise V3ReportsBuildError("public reports history root is invalid")
    history_root.mkdir(exist_ok=True)
    allowed = {
        "archive",
        "business-history-index.json",
        "current",
        "history",
        "manifest.json",
        "report-index.json",
        "validation-receipt.json",
    }
    if {path.name for path in output_dir.iterdir()} - allowed:
        raise V3ReportsBuildError("public reports output contains undeclared entries")
    expected_documents = set(manifest.get("files", {})) - {
        "report-index.json",
        "validation-receipt.json",
    }
    if set(reports) != expected_documents or not set(V3_REPORT_PATHS).issubset(reports):
        raise V3ReportsBuildError("public reports artifact set is invalid")
    expected_output_files = set(manifest["files"]) | {"manifest.json"}
    _v3_assert_output_inventory(
        output_dir,
        expected_output_files,
        "public reports output",
        exact=False,
        allowed_empty_directories={"history"},
    )
    for name, document in sorted(reports.items()):
        _v3_write_exact(
            _v3_safe_relative_path(output_dir, name, "public report"), document
        )
    _v3_write_exact(output_dir / "report-index.json", index)
    _v3_write_exact(output_dir / "validation-receipt.json", validation_receipt)
    _v3_write_exact(output_dir / "manifest.json", manifest)
    _v3_assert_output_inventory(
        output_dir,
        expected_output_files,
        "public reports output",
        exact=True,
        allowed_empty_directories={"history"},
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--insights-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    reports, index, manifest = build(
        args.snapshot_dir.resolve(strict=True),
        args.insights_dir.resolve(strict=True),
    )
    complete_manifest = write_snapshot(
        args.output_dir.resolve(), reports, index, manifest
    )
    print(json.dumps(complete_manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
