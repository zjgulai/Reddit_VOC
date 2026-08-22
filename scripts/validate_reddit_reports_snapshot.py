#!/usr/bin/env python3
"""Independently validate the versioned Reddit VOC static report dataset."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import html
import json
from pathlib import Path
import re
from typing import Any, Iterable
from zoneinfo import ZoneInfo


TIMEZONE_NAME = "Asia/Shanghai"
EXPECTED_DATASET_VERSION = "reddit_voc_reports_20260714_v1"
EXPECTED_PROMOTED = {"L0-GEN-075", "L0-GEN-103"}
EXPECTED_REPORT_PATHS = {
    "current/daily.json",
    "current/weekly.json",
    "current/monthly.json",
    "archive/daily-2026-07-13.json",
    "archive/weekly-2026-07-06_2026-07-12.json",
    "archive/monthly-2026-06.json",
}
SENTIMENTS = ("positive", "neutral", "negative")
BINDINGS = (
    "momcozy_sentence_bound",
    "momcozy_entity_cooccurrence",
    "multi_brand",
    "competitor_explicit",
    "category_general",
)
REQUIRED_REPORT_KEYS = {
    "schema_version",
    "identity",
    "window",
    "headline",
    "observed_timeline",
    "communities",
    "topics",
    "pain_points",
    "brand_mentions",
    "promoted_signals",
    "attention_items",
    "evidence_posts",
    "capabilities",
    "interpretation_boundaries",
    "runtime_boundaries",
}
REQUIRED_UNSUPPORTED = {
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
}

V3_REPORT_SCHEMA = "reddit_voc_report_v3"
V3_REPORT_INDEX_SCHEMA = "reddit_voc_report_index_v3"
V3_REPORT_MANIFEST_SCHEMA = "reddit_voc_reports_manifest_v3"
V3_REPORT_PATHS = {
    f"{role}/{grain}.json"
    for role in ("current", "archive")
    for grain in ("daily", "weekly", "monthly")
}
V3_BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}


class V3ReportsValidationError(ValueError):
    """A V3 fixture report candidate failed independent validation."""


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _check(parsed.tzinfo is not None, f"naive datetime: {value}")
    return parsed.astimezone(timezone.utc)


def _in_window(row: dict[str, Any], start: datetime, end: datetime) -> bool:
    created = _parse(row["created_at_utc"])
    return start <= created < end


def _share(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": round(numerator / denominator, 6) if denominator else None,
    }


def _sentiment_counts(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(row["analysis"]["sentiment_label"] for row in rows)
    _check(not (set(counts) - set(SENTIMENTS)), "unknown sentiment label")
    return {sentiment: counts[sentiment] for sentiment in SENTIMENTS}


def _sentiment_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = _sentiment_counts(rows)
    return {
        "denominator": len(rows),
        "counts": counts,
        "shares": {
            sentiment: _share(count, len(rows))
            for sentiment, count in counts.items()
        },
    }


def _normalise_brand(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _is_momcozy(value: str) -> bool:
    return _normalise_brand(value) in {"momcozy", "mcozy"}


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


def _entity_text(entity_type: str, row: dict[str, Any]) -> str:
    return (
        f"{row['title']}\n{row['content']}"
        if entity_type == "post"
        else row["body"]
    )


def _signal_keywords(row: dict[str, Any], tag_id: str) -> list[str]:
    return sorted(
        {
            keyword.casefold()
            for match in row["tagging"]["matches"]
            if match["tag_id"] == tag_id
            for keyword in match["evidence_keywords"]
        }
    )


def _binding(
    text: str,
    brands: list[str],
    keywords: list[str],
    momcozy_aliases: list[str],
) -> str:
    has_momcozy = any(_is_momcozy(brand) for brand in brands)
    has_other = any(not _is_momcozy(brand) for brand in brands)
    if has_momcozy and has_other:
        return "multi_brand"
    sentences = re.split(r"(?<=[.!?])\s+|\n+", html.unescape(text).casefold())
    sentence_bound = any(
        any(alias in sentence for alias in momcozy_aliases)
        and any(keyword in sentence for keyword in keywords)
        for sentence in sentences
        if sentence.strip()
    )
    if has_momcozy and sentence_bound:
        return "momcozy_sentence_bound"
    if has_momcozy:
        return "momcozy_entity_cooccurrence"
    if has_other:
        return "competitor_explicit"
    return "category_general"


def _expected_windows(as_of: datetime) -> dict[str, tuple[datetime, datetime, str, str, bool]]:
    tz = ZoneInfo(TIMEZONE_NAME)
    local = as_of.astimezone(tz)
    previous_day = local.date() - timedelta(days=1)
    current_week_start = local.date() - timedelta(days=local.weekday())
    previous_week_start = current_week_start - timedelta(days=7)
    current_month_start = local.date().replace(day=1)
    previous_month_start = (
        date(current_month_start.year - 1, 12, 1)
        if current_month_start.month == 1
        else date(current_month_start.year, current_month_start.month - 1, 1)
    )

    def midnight(value: date) -> datetime:
        return datetime.combine(value, time.min, tzinfo=tz).astimezone(timezone.utc)

    return {
        "current/daily.json": (
            as_of - timedelta(days=1), as_of, "daily", "rolling", False
        ),
        "current/weekly.json": (
            as_of - timedelta(days=7), as_of, "weekly", "rolling", False
        ),
        "current/monthly.json": (
            as_of - timedelta(days=30), as_of, "monthly", "rolling", False
        ),
        f"archive/daily-{previous_day.isoformat()}.json": (
            midnight(previous_day),
            midnight(previous_day + timedelta(days=1)),
            "daily",
            "calendar_closed",
            True,
        ),
        (
            "archive/weekly-"
            f"{previous_week_start.isoformat()}_"
            f"{(current_week_start - timedelta(days=1)).isoformat()}.json"
        ): (
            midnight(previous_week_start),
            midnight(current_week_start),
            "weekly",
            "calendar_closed",
            True,
        ),
        f"archive/monthly-{previous_month_start.strftime('%Y-%m')}.json": (
            midnight(previous_month_start),
            midnight(current_month_start),
            "monthly",
            "calendar_closed",
            True,
        ),
    }


def _expected_communities(
    posts: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    post_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"posts": set(), "comments": set(), "sentiments": Counter()}
    )
    for post in posts:
        name = post["subreddit"]
        grouped[name]["posts"].add(post["post_id"])
        grouped[name]["sentiments"][post["analysis"]["sentiment_label"]] += 1
    for comment in comments:
        name = post_by_id[comment["post_id"]]["subreddit"]
        grouped[name]["comments"].add(comment["comment_id"])
        grouped[name]["sentiments"][comment["analysis"]["sentiment_label"]] += 1
    result = []
    for name, row in grouped.items():
        post_count = len(row["posts"])
        comment_count = len(row["comments"])
        total = post_count + comment_count
        sentiment_counts = {
            sentiment: row["sentiments"][sentiment] for sentiment in SENTIMENTS
        }
        result.append(
            {
                "subreddit": name,
                "posts": post_count,
                "voc_comments": comment_count,
                "observed_entities": total,
                "sentiment_counts": sentiment_counts,
                "negative_share": _share(sentiment_counts["negative"], total),
            }
        )
    result.sort(
        key=lambda row: (
            -row["observed_entities"],
            -row["posts"],
            row["subreddit"].casefold(),
        )
    )
    return result


def _expected_topics(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


def _expected_pain_points(
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
    for name in sorted(set(post_counts) | set(comment_counts)):
        total = post_counts[name] + comment_counts[name]
        result.append(
            {
                "pain_point": name,
                "post_entities": post_counts[name],
                "comment_entities": comment_counts[name],
                "total_entities": total,
                "share": _share(total, denominator),
            }
        )
    result.sort(key=lambda row: (-row["total_entities"], row["pain_point"]))
    return result


def _expected_brands(
    posts: list[dict[str, Any]], brand_name_by_tag: dict[str, str]
) -> list[dict[str, Any]]:
    post_ids: dict[str, set[str]] = defaultdict(set)
    display: dict[str, str] = {}
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
            if key:
                candidate = governed_names.get(key, name)
                existing = display.get(key)
                if existing is None or (candidate.casefold(), candidate) < (
                    existing.casefold(),
                    existing,
                ):
                    display[key] = candidate
                post_ids[key].add(post["post_id"])
    result = [
        {
            "brand": display[key],
            "sample_mention_posts": len(ids),
            "sample_mention_share": _share(len(ids), len(posts)),
            "metric_label": "sample_mention_posts",
        }
        for key, ids in post_ids.items()
    ]
    result.sort(
        key=lambda row: (-row["sample_mention_posts"], row["brand"].casefold())
    )
    return result


def _validate_timeline(
    report: dict[str, Any],
    posts: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    start: datetime,
    end: datetime,
) -> None:
    timeline = report["observed_timeline"]
    expected_count = (
        24
        if report["identity"]["period"] == "daily"
        else int((end - start).total_seconds() // 86400)
    )
    _check(len(timeline) == expected_count, "timeline bucket count mismatch")
    cursor = start
    for bucket in timeline:
        bucket_start = _parse(bucket["bucket_start_utc"])
        bucket_end = _parse(bucket["bucket_end_utc"])
        _check(bucket_start == cursor, "timeline is not contiguous")
        _check(bucket_start < bucket_end <= end, "timeline bucket range invalid")
        bucket_posts = [row for row in posts if _in_window(row, bucket_start, bucket_end)]
        bucket_comments = [
            row for row in comments if _in_window(row, bucket_start, bucket_end)
        ]
        combined = bucket_posts + bucket_comments
        _check(bucket["posts"] == len(bucket_posts), "timeline post count mismatch")
        _check(
            bucket["voc_comments"] == len(bucket_comments),
            "timeline comment count mismatch",
        )
        _check(
            bucket["observed_entities"] == len(combined),
            "timeline entity count mismatch",
        )
        _check(
            bucket["sentiment_counts"] == _sentiment_counts(combined),
            "timeline sentiment mismatch",
        )
        cursor = bucket_end
    _check(cursor == end, "timeline does not end at report boundary")


def _expected_signal_counts(
    tag_id: str,
    posts: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    brand_name_by_tag: dict[str, str],
    momcozy_aliases: list[str],
) -> tuple[int, int, dict[str, int]]:
    counts = Counter()
    post_count = 0
    comment_count = 0
    for entity_type, rows in (("post", posts), ("comment", comments)):
        for row in rows:
            if tag_id not in row["tagging"]["aspect_tag_ids"]:
                continue
            keywords = _signal_keywords(row, tag_id)
            _check(bool(keywords), "promoted entity lacks evidence keywords")
            brands = _entity_brands(entity_type, row, brand_name_by_tag)
            counts[
                _binding(
                    _entity_text(entity_type, row),
                    brands,
                    keywords,
                    momcozy_aliases,
                )
            ] += 1
            if entity_type == "post":
                post_count += 1
            else:
                comment_count += 1
    return post_count, comment_count, {name: counts[name] for name in BINDINGS}


def _validate_report(
    path: str,
    report: dict[str, Any],
    *,
    expected_window: tuple[datetime, datetime, str, str, bool],
    as_of: datetime,
    base_posts: list[dict[str, Any]],
    base_comments: list[dict[str, Any]],
    post_by_id: dict[str, dict[str, Any]],
    insights_by_tag: dict[str, dict[str, Any]],
    held_ids: set[str],
    brand_name_by_tag: dict[str, str],
    momcozy_aliases: list[str],
    quarantined_count: int,
) -> None:
    _check(set(report) == REQUIRED_REPORT_KEYS, f"report module set mismatch: {path}")
    _check(report["schema_version"] == "reddit_voc_report_v1", "report schema mismatch")
    start, end, period, mode, is_closed = expected_window
    identity = report["identity"]
    window = report["window"]
    _check(identity["dataset_version"] == EXPECTED_DATASET_VERSION, "report dataset mismatch")
    _check(identity["period"] == period, "report period mismatch")
    _check(identity["window_mode"] == mode, "report window mode mismatch")
    _check(_parse(window["start_utc"]) == start, "report start mismatch")
    _check(_parse(window["end_utc"]) == end, "report end mismatch")
    _check(_parse(window["as_of_utc"]) == as_of, "report as-of mismatch")
    _check(window["timezone"] == TIMEZONE_NAME, "report timezone mismatch")
    _check(window["is_closed"] is is_closed, "report closed status mismatch")
    _check(window["comparison_status"] == "coverage_unverified", "comparison overclaim")

    posts = [row for row in base_posts if _in_window(row, start, end)]
    comments = [
        row
        for row in base_comments
        if row["include_in_voc_metrics"] and _in_window(row, start, end)
    ]
    expected_coverage = (
        "observed_records_present_but_collection_coverage_unverified"
        if posts or comments
        else "coverage_gap"
    )
    _check(window["coverage_status"] == expected_coverage, "coverage status mismatch")

    headline = report["headline"]
    _check(headline["posts"] == len(posts), "headline post count mismatch")
    _check(headline["voc_comments"] == len(comments), "headline comment count mismatch")
    _check(
        headline["observed_entities"] == len(posts) + len(comments),
        "headline entity count mismatch",
    )
    _check(headline["post_sentiment"] == _sentiment_summary(posts), "post sentiment mismatch")
    _check(
        headline["comment_sentiment"] == _sentiment_summary(comments),
        "comment sentiment mismatch",
    )
    _check(
        headline["quarantined_comments_in_base_snapshot"] == quarantined_count,
        "quarantine boundary mismatch",
    )
    _check(headline["quarantined_comments_counted"] == 0, "quarantine leakage")

    _validate_timeline(report, posts, comments, start, end)
    _check(
        report["communities"] == _expected_communities(posts, comments, post_by_id),
        "community aggregation mismatch",
    )
    _check(report["topics"] == _expected_topics(posts), "topic aggregation mismatch")
    _check(
        report["pain_points"] == _expected_pain_points(posts, comments),
        "pain-point aggregation mismatch",
    )
    _check(
        report["brand_mentions"] == _expected_brands(posts, brand_name_by_tag),
        "brand mention aggregation mismatch",
    )

    signals = report["promoted_signals"]
    signal_ids = {row["tag_id"] for row in signals}
    _check(signal_ids == EXPECTED_PROMOTED, "promoted report signal set mismatch")
    _check(not (signal_ids & held_ids), "held tag leaked into report")
    for signal in signals:
        tag_id = signal["tag_id"]
        post_count, comment_count, binding_counts = _expected_signal_counts(
            tag_id,
            posts,
            comments,
            brand_name_by_tag,
            momcozy_aliases,
        )
        _check(signal["matched_posts"] == post_count, "signal post count mismatch")
        _check(signal["matched_comments"] == comment_count, "signal comment count mismatch")
        _check(signal["matched_entities"] == post_count + comment_count, "signal total mismatch")
        _check(signal["binding_counts"] == binding_counts, "signal binding mismatch")
        _check(
            signal["momcozy_specific_entities"]
            == binding_counts["momcozy_sentence_bound"],
            "Momcozy-specific signal overclaim",
        )
        _check(
            signal["dictionary_reference"]
            == insights_by_tag[tag_id]["dictionary_reference"],
            "signal dictionary reference mismatch",
        )
        for evidence in signal["evidence"]:
            entity_rows = posts if evidence["entity_type"] == "post" else comments
            id_key = "post_id" if evidence["entity_type"] == "post" else "comment_id"
            entity = next(
                (row for row in entity_rows if row[id_key] == evidence["entity_id"]),
                None,
            )
            _check(entity is not None, "signal evidence is outside the report window")
            _check(tag_id in entity["tagging"]["aspect_tag_ids"], "signal evidence tag mismatch")
            keywords = _signal_keywords(entity, tag_id)
            brands = _entity_brands(evidence["entity_type"], entity, brand_name_by_tag)
            expected_binding = _binding(
                _entity_text(evidence["entity_type"], entity),
                brands,
                keywords,
                momcozy_aliases,
            )
            _check(evidence["binding_type"] == expected_binding, "evidence binding mismatch")

    capabilities = report["capabilities"]
    _check(
        set(capabilities["unsupported"]) == REQUIRED_UNSUPPORTED,
        "unsupported capability set mismatch",
    )
    boundaries = report["interpretation_boundaries"]
    _check(boundaries["market_share_supported"] is False, "market-share overclaim")
    _check(boundaries["roi_supported"] is False, "ROI overclaim")
    _check(boundaries["trend_claim_supported"] is False, "trend overclaim")
    _check(
        boundaries["consumer_card_is_reference_not_persona_id"] is True,
        "consumer-card/persona boundary missing",
    )
    _check(boundaries["persona_tags_generated"] is False, "persona overclaim")
    _check(boundaries["held_tags_in_business_findings"] == 0, "held tag overclaim")
    runtime = report["runtime_boundaries"]
    _check(runtime["production_unchanged"] is True, "production boundary mismatch")
    for key in (
        "provider_call",
        "database_write",
        "live_send",
        "webhook_send",
        "deploy",
        "schedule_change",
    ):
        _check(runtime[key] is False, f"runtime side effect enabled: {key}")


def validate(
    reports_dir: Path,
    snapshot_dir: Path,
    insights_dir: Path,
) -> dict[str, Any]:
    manifest_path = reports_dir / "manifest.json"
    manifest = _load(manifest_path)
    index = _load(reports_dir / "report-index.json")
    base_manifest_path = snapshot_dir / "manifest.json"
    insights_manifest_path = insights_dir / "manifest.json"
    base_manifest = _load(base_manifest_path)
    insights_manifest = _load(insights_manifest_path)
    insights = _load(insights_dir / "insights.json")
    posts = _load(snapshot_dir / "posts.json")
    comments = _load(snapshot_dir / "comments.json")
    dictionary = _load(snapshot_dir / "tag-dictionary.json")

    _check(manifest["schema_version"] == "reddit_voc_reports_manifest_v1", "manifest schema mismatch")
    _check(index["schema_version"] == "reddit_voc_report_index_v1", "index schema mismatch")
    _check(manifest["dataset_version"] == EXPECTED_DATASET_VERSION, "report dataset mismatch")
    _check(index["dataset_version"] == EXPECTED_DATASET_VERSION, "index dataset mismatch")
    _check(manifest["report_count"] == 6, "report count mismatch")
    _check(manifest["base_dataset_version"] == base_manifest["dataset_version"], "base version mismatch")
    _check(manifest["base_manifest_sha256"] == _sha256(base_manifest_path), "base hash mismatch")
    _check(
        manifest["insights_dataset_version"] == insights_manifest["dataset_version"],
        "insights version mismatch",
    )
    _check(
        manifest["insights_manifest_sha256"] == _sha256(insights_manifest_path),
        "insights hash mismatch",
    )
    _check(manifest["dictionary_version"] == dictionary["dictionary_version"], "dictionary version mismatch")
    _check(manifest["dictionary_sha256"] == dictionary["dictionary_sha256"], "dictionary hash mismatch")
    _check(set(manifest["promoted_tag_ids"]) == EXPECTED_PROMOTED, "manifest promoted set mismatch")
    held_ids = set(insights_manifest["audit_summary"]["held_tag_ids"])
    _check(set(manifest["held_tag_ids_excluded"]) == held_ids, "manifest held set mismatch")

    expected_files = {"report-index.json", *EXPECTED_REPORT_PATHS}
    _check(set(manifest["files"]) == expected_files, "report file set mismatch")
    for name, expected in manifest["files"].items():
        relative = Path(name)
        _check(not relative.is_absolute() and ".." not in relative.parts, "unsafe report path")
        path = reports_dir / relative
        _check(path.is_file(), f"report file missing: {name}")
        _check(path.stat().st_size == expected["bytes"], f"byte mismatch: {name}")
        _check(_sha256(path) == expected["sha256"], f"sha256 mismatch: {name}")

    indexed = {
        descriptor["path"]
        for group_name in ("current", "archive")
        for descriptor in index[group_name].values()
    }
    _check(indexed == EXPECTED_REPORT_PATHS, "report index path set mismatch")
    as_of = _parse(base_manifest["generated_at_utc"])
    _check(_parse(manifest["generated_at_utc"]) == as_of, "manifest time anchor mismatch")
    _check(_parse(index["as_of_utc"]) == as_of, "index time anchor mismatch")
    _check(index["timezone"] == TIMEZONE_NAME, "index timezone mismatch")

    post_by_id = {row["post_id"]: row for row in posts}
    _check(len(post_by_id) == len(posts), "duplicate base post id")
    _check(all(row["post_id"] in post_by_id for row in comments), "orphan base comment")
    rules_by_tag = {row["tag_id"]: row for row in dictionary["rules"]}
    brand_name_by_tag = {
        tag_id: rule["name_en"]
        for tag_id, rule in rules_by_tag.items()
        if tag_id.startswith("L0-BRD-")
    }
    momcozy_rule = rules_by_tag["L0-BRD-011"]
    momcozy_aliases = sorted(
        {value.casefold() for value in momcozy_rule["keywords_en"]},
        key=lambda value: (-len(value), value),
    )
    insights_by_tag = {row["tag_id"]: row for row in insights["signals"]}
    _check(set(insights_by_tag) == EXPECTED_PROMOTED, "insights promoted set mismatch")

    expected_windows = _expected_windows(as_of)
    _check(set(expected_windows) == EXPECTED_REPORT_PATHS, "expected window path mismatch")
    for path, expected_window in expected_windows.items():
        report = _load(reports_dir / path)
        _validate_report(
            path,
            report,
            expected_window=expected_window,
            as_of=as_of,
            base_posts=posts,
            base_comments=comments,
            post_by_id=post_by_id,
            insights_by_tag=insights_by_tag,
            held_ids=held_ids,
            brand_name_by_tag=brand_name_by_tag,
            momcozy_aliases=momcozy_aliases,
            quarantined_count=base_manifest["canonical_counts"]["quarantined_comments"],
        )
        descriptor = (
            index["current"][expected_window[2]]
            if expected_window[3] == "rolling"
            else index["archive"][expected_window[2]]
        )
        _check(descriptor["path"] == path, "index/report path mismatch")
        _check(descriptor["posts"] == report["headline"]["posts"], "index post count mismatch")
        _check(
            descriptor["voc_comments"] == report["headline"]["voc_comments"],
            "index comment count mismatch",
        )
        _check(
            descriptor["coverage_status"] == report["window"]["coverage_status"],
            "index coverage mismatch",
        )

    monthly_archive = _load(reports_dir / "archive/monthly-2026-06.json")
    _check(monthly_archive["window"]["coverage_status"] == "coverage_gap", "monthly gap missing")
    _check(monthly_archive["headline"]["posts"] == 0, "monthly archive post mismatch")
    _check(monthly_archive["headline"]["voc_comments"] == 0, "monthly archive comment mismatch")

    boundaries = manifest["boundaries"]
    _check(boundaries["production_unchanged"] is True, "manifest production boundary mismatch")
    for key in (
        "provider_call",
        "database_write",
        "live_send",
        "webhook_send",
        "deploy",
        "schedule_change",
        "persona_tags_generated",
        "market_share_supported",
        "roi_supported",
        "trend_claim_supported",
    ):
        _check(boundaries[key] is False, f"manifest boundary enabled: {key}")
    _check(
        boundaries["consumer_card_is_reference_not_persona_id"] is True,
        "manifest persona reference boundary missing",
    )

    checks = {
        "schema_and_version_binding": True,
        "base_and_insights_hash_binding": True,
        "report_file_hashes": True,
        "dual_window_contract": True,
        "headline_and_sentiment_reconciliation": True,
        "timeline_reconciliation": True,
        "community_topic_pain_point_brand_reconciliation": True,
        "promoted_tag_and_brand_binding_gate": True,
        "coverage_gap_and_comparison_boundaries": True,
        "persona_and_unsupported_metric_boundaries": True,
        "side_effect_boundaries": True,
    }
    return {
        "schema_version": "reddit_voc_reports_validation_v1",
        "validated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_version": manifest["dataset_version"],
        "status": "passed",
        "checks": checks,
        "counts": {
            "reports": 6,
            "current_reports": 3,
            "archive_reports": 3,
            "promoted_tags": len(EXPECTED_PROMOTED),
            "held_tags_excluded": len(held_ids),
        },
        "production_unchanged": True,
        "provider_call": False,
        "database_write": False,
        "live_send": False,
        "webhook_send": False,
        "deploy": False,
    }


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
        raise V3ReportsValidationError(
            "V3 document is not canonical-JSON serializable"
        ) from exc


def _v3_load_canonical(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = path.read_bytes()
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V3ReportsValidationError(f"{label} is unreadable") from exc
    if not isinstance(value, dict) or payload != _v3_canonical_bytes(value):
        raise V3ReportsValidationError(f"{label} is not canonical JSON")
    return value


def _v3_validate_inventory(
    root: Path,
    expected_files: set[str],
    label: str,
    *,
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
            raise V3ReportsValidationError(f"{label} contains a symlink")
        relative = path.relative_to(root).as_posix()
        if path.is_file():
            actual_files.add(relative)
        elif path.is_dir():
            actual_directories.add(relative)
        else:
            raise V3ReportsValidationError(f"{label} contains an unsafe entry")
    allowed_directories = expected_directories | (allowed_empty_directories or set())
    if actual_files != expected_files or actual_directories - allowed_directories:
        raise V3ReportsValidationError(f"{label} recursive file set is invalid")


def _v3_validated_artifact_path(root: Path, name: str, label: str) -> Path:
    if not isinstance(name, str) or not name or "\\" in name:
        raise V3ReportsValidationError(f"{label} path is unsafe")
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts or "." in relative.parts:
        raise V3ReportsValidationError(f"{label} path is unsafe")
    root_resolved = root.resolve(strict=True)
    current = root_resolved
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise V3ReportsValidationError(f"{label} path is unsafe")
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(root_resolved)
    except (OSError, ValueError) as exc:
        raise V3ReportsValidationError(f"{label} path is unsafe") from exc
    if not resolved.is_file():
        raise V3ReportsValidationError(f"{label} path is unsafe")
    return resolved


def validate_v3_reports_snapshot(
    reports_dir: Path,
    metrics_root: Path,
    metrics_validation_receipt_path: Path,
    period_series: dict[str, Any],
    *,
    expected_metrics_manifest_sha256: str,
    expected_metrics_receipt_sha256: str,
) -> dict[str, Any]:
    """Rebuild and byte-compare a fixture-only V3 report snapshot."""

    from scripts.build_reddit_reports_snapshot import (
        V3ReportsBuildError,
        build_v3_reports_snapshot,
        load_v3_metrics_binding,
    )

    try:
        binding = load_v3_metrics_binding(
            metrics_root,
            metrics_validation_receipt_path,
            expected_manifest_sha256=expected_metrics_manifest_sha256,
            expected_receipt_sha256=expected_metrics_receipt_sha256,
        )
    except V3ReportsBuildError as exc:
        raise V3ReportsValidationError(str(exc)) from exc
    reports_dir = Path(reports_dir)
    if reports_dir.is_symlink() or not reports_dir.is_dir():
        raise V3ReportsValidationError("V3 reports root is invalid")
    if {path.name for path in reports_dir.iterdir()} != {
        "archive",
        "current",
        "manifest.json",
        "report-index.json",
    }:
        raise V3ReportsValidationError("V3 reports root file set is invalid")
    for directory_name in ("archive", "current"):
        directory = reports_dir / directory_name
        if directory.is_symlink() or not directory.is_dir():
            raise V3ReportsValidationError("V3 report directory is invalid")
        if {path.name for path in directory.iterdir()} != {
            "daily.json",
            "monthly.json",
            "weekly.json",
        }:
            raise V3ReportsValidationError("V3 report directory file set is invalid")
        if any(path.is_symlink() or not path.is_file() for path in directory.iterdir()):
            raise V3ReportsValidationError("V3 report artifact is not a regular file")

    manifest = _v3_load_canonical(reports_dir / "manifest.json", "V3 manifest")
    index = _v3_load_canonical(reports_dir / "report-index.json", "V3 report index")
    if (
        manifest.get("schema_version") != V3_REPORT_MANIFEST_SCHEMA
        or manifest.get("artifact_stage") != "fixture_reports"
        or manifest.get("status") != "fixture_only_waiting_for_periodized_metrics"
        or manifest.get("fixture_only") is not True
        or manifest.get("promotable") is not False
        or manifest.get("boundaries") != V3_BOUNDARIES
        or manifest.get("report_count") != 6
        or manifest.get("metrics_manifest_sha256")
        != expected_metrics_manifest_sha256
        or manifest.get("metrics_validation_receipt_sha256")
        != expected_metrics_receipt_sha256
    ):
        raise V3ReportsValidationError("V3 manifest contract is invalid")
    files = manifest.get("files")
    expected_files = {"report-index.json", *V3_REPORT_PATHS}
    if not isinstance(files, dict) or set(files) != expected_files:
        raise V3ReportsValidationError("V3 manifest file set is invalid")
    actual_documents: dict[str, dict[str, Any]] = {}
    for name in sorted(files):
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise V3ReportsValidationError("unsafe V3 report path")
        path = reports_dir / relative
        record = files[name]
        if not isinstance(record, dict) or set(record) != {"bytes", "sha256"}:
            raise V3ReportsValidationError(f"invalid V3 file record: {name}")
        if record.get("bytes") != path.stat().st_size or record.get("sha256") != _sha256(path):
            raise V3ReportsValidationError(f"V3 file integrity mismatch: {name}")
        actual_documents[name] = _v3_load_canonical(path, name)
    if (
        index.get("schema_version") != V3_REPORT_INDEX_SCHEMA
        or index.get("fixture_only") is not True
        or index.get("business_entry_count") != 3
        or set(index.get("reports", {})) != {"daily", "weekly", "monthly"}
        or "current" in index
        or "archive" in index
    ):
        raise V3ReportsValidationError("V3 report index business-entry contract is invalid")
    for grain, descriptor in index["reports"].items():
        if (
            descriptor.get("entry_label") != "最新完整周期"
            or descriptor.get("artifact_path") != f"current/{grain}.json"
        ):
            raise V3ReportsValidationError("V3 report index exposes a second business entry")
    rendered_index = json.dumps(index, ensure_ascii=False, sort_keys=True)
    if "当前闭合期" in rendered_index or "闭合归档" in rendered_index:
        raise V3ReportsValidationError("legacy closure terminology leaked into V3 index")

    for name in sorted(V3_REPORT_PATHS):
        report = actual_documents[name]
        role = (
            "latest_complete_calendar_period"
            if name.startswith("current/")
            else "internal_comparison_archive"
        )
        if (
            report.get("schema_version") != V3_REPORT_SCHEMA
            or report.get("artifact_role") != role
            or report.get("fixture_only") is not True
            or report.get("boundaries") != V3_BOUNDARIES
        ):
            raise V3ReportsValidationError(f"V3 report contract is invalid: {name}")
        if name.startswith("archive/") and report.get("business_entry_visible") is not False:
            raise V3ReportsValidationError("V3 comparison archive became a business entry")
        if name.startswith("current/"):
            period = report.get("period", {})
            if period.get("is_complete") is not True:
                raise V3ReportsValidationError("V3 current period is not complete")
            for card in report.get("indicators", []):
                current = card.get("current", {})
                if current.get("status") == "unavailable" and (
                    card.get("direction") is not None
                    or card.get("line_color") != "gray"
                ):
                    raise V3ReportsValidationError(
                        "unavailable V3 metric emitted a direction"
                    )
                for comparison in card.get("comparisons", {}).values():
                    if comparison.get("status") == "unavailable" and (
                        comparison.get("display") != "—"
                        or comparison.get("direction") is not None
                    ):
                        raise V3ReportsValidationError(
                            "unavailable V3 comparison emitted a direction"
                        )

    try:
        expected_reports, expected_index, expected_manifest = (
            build_v3_reports_snapshot(binding, period_series)
        )
    except V3ReportsBuildError as exc:
        raise V3ReportsValidationError(str(exc)) from exc
    if index != expected_index:
        raise V3ReportsValidationError("V3 report index deterministic replay mismatch")
    if manifest != expected_manifest:
        raise V3ReportsValidationError("V3 manifest deterministic replay mismatch")
    for name, expected in expected_reports.items():
        if actual_documents[name] != expected:
            raise V3ReportsValidationError(
                f"V3 report deterministic replay mismatch: {name}"
            )
    return {
        "boundaries": dict(V3_BOUNDARIES),
        "deterministic_full_byte_replay": True,
        "fixture_only": True,
        "metrics_manifest_sha256": expected_metrics_manifest_sha256,
        "metrics_validation_receipt_sha256": expected_metrics_receipt_sha256,
        "promotable": False,
        "report_count": 6,
        "schema_version": "reddit_voc_reports_validation_receipt_v3",
        "status": "passed_fixture_only",
    }


def validate_v3_formal_reports_snapshot(
    reports_dir: Path,
    metrics_input_manifest_path: Path,
    metrics_root: Path,
    metrics_validation_receipt_path: Path,
    *,
    expected_metrics_input_manifest_sha256: str,
    expected_metrics_candidate_manifest_sha256: str,
    expected_metrics_receipt_sha256: str,
    expected_coverage_attestation_sha256: str | None,
) -> dict[str, Any]:
    """Independently reload A3 and replay the complete formal report candidate."""

    from scripts.build_reddit_reports_snapshot import (
        V3ReportsBuildError,
        build_v3_formal_reports_snapshot,
        load_v3_formal_metrics_binding,
    )

    try:
        binding = load_v3_formal_metrics_binding(
            metrics_input_manifest_path,
            metrics_root,
            metrics_validation_receipt_path,
            expected_input_manifest_sha256=expected_metrics_input_manifest_sha256,
            expected_candidate_manifest_sha256=expected_metrics_candidate_manifest_sha256,
            expected_receipt_sha256=expected_metrics_receipt_sha256,
            expected_coverage_attestation_sha256=expected_coverage_attestation_sha256,
        )
    except V3ReportsBuildError as exc:
        raise V3ReportsValidationError(str(exc)) from exc
    try:
        expected_reports, expected_index, expected_manifest = (
            build_v3_formal_reports_snapshot(binding)
        )
    except V3ReportsBuildError as exc:
        raise V3ReportsValidationError(str(exc)) from exc
    reports_dir = Path(reports_dir)
    if reports_dir.is_symlink() or not reports_dir.is_dir():
        raise V3ReportsValidationError("formal reports root is invalid")
    if {path.name for path in reports_dir.iterdir()} != {
        "archive",
        "business-history-index.json",
        "current",
        "history",
        "manifest.json",
        "report-index.json",
    }:
        raise V3ReportsValidationError("formal reports root file set is invalid")
    manifest = _v3_load_canonical(reports_dir / "manifest.json", "formal reports manifest")
    index = _v3_load_canonical(reports_dir / "report-index.json", "formal report index")
    comparison_contract_proven = expected_coverage_attestation_sha256 is not None
    expected_comparison_basis = (
        "owner_attested_dataset_scope_window"
        if comparison_contract_proven
        else "not_owner_attested"
    )
    expected_completeness = 100 if comparison_contract_proven else None
    expected_history_count = expected_manifest.get("history_report_count")
    if expected_history_count not in (
        {38} if comparison_contract_proven else {0, 38}
    ):
        raise V3ReportsValidationError("formal reports history state is invalid")
    expected_report_count = 6 + expected_history_count
    expected_business_count = 3 + expected_history_count
    if (
        manifest.get("schema_version") != V3_REPORT_MANIFEST_SCHEMA
        or manifest.get("artifact_stage") != "reports_candidate"
        or manifest.get("status") != "candidate_built"
        or manifest.get("consumption_status")
        != "blocked_pending_independent_validation"
        or manifest.get("independent_validation_status") != "pending"
        or manifest.get("promotable") is not False
        or manifest.get("fixture_only") is not False
        or manifest.get("boundaries") != V3_BOUNDARIES
        or manifest.get("comparison_contract_proven")
        is not comparison_contract_proven
        or manifest.get("comparison_contract_basis")
        != expected_comparison_basis
        or manifest.get("completeness_percent") != expected_completeness
        or manifest.get("data_owner_coverage_attestation_sha256")
        != expected_coverage_attestation_sha256
        or manifest.get("metrics_input_manifest_sha256")
        != expected_metrics_input_manifest_sha256
        or manifest.get("metrics_candidate_manifest_sha256")
        != expected_metrics_candidate_manifest_sha256
        or manifest.get("metrics_validation_receipt_sha256")
        != expected_metrics_receipt_sha256
        or manifest.get("report_count") != expected_report_count
        or manifest.get("history_report_count") != expected_history_count
        or manifest.get("business_entry_count") != expected_business_count
        or manifest.get("contract_extensions")
        != [
            "reddit_voc_period_activity_v1",
            "reddit_voc_brand_health_dimension_contribution_v1",
            "reddit_voc_action_review_v1",
            "reddit_voc_business_history_index_v1",
        ]
    ):
        raise V3ReportsValidationError("formal reports manifest contract is invalid")
    if manifest.get("coverage_attestation") != binding["coverage_attestation"]:
        raise V3ReportsValidationError("formal reports coverage attestation mismatch")
    files = manifest.get("files")
    expected_files = set(expected_manifest["files"])
    if (
        not isinstance(files, dict)
        or set(files) != expected_files
        or len(files) != expected_report_count + 2
    ):
        raise V3ReportsValidationError("formal reports manifest file set is invalid")
    _v3_validate_inventory(
        reports_dir,
        expected_files | {"manifest.json"},
        "formal reports root",
        allowed_empty_directories={"history"},
    )
    documents: dict[str, dict[str, Any]] = {}
    for name in sorted(files):
        path = _v3_validated_artifact_path(reports_dir, name, "formal report")
        record = files[name]
        if (
            not isinstance(record, dict)
            or set(record) != {"bytes", "sha256"}
            or record.get("bytes") != path.stat().st_size
            or record.get("sha256") != _sha256(path)
        ):
            raise V3ReportsValidationError(f"formal report file integrity mismatch: {name}")
        documents[name] = _v3_load_canonical(path, name)
    if (
        index.get("schema_version") != V3_REPORT_INDEX_SCHEMA
        or index.get("business_entry_count") != expected_business_count
        or index.get("current_entry_count") != 3
        or index.get("history_entry_count") != expected_history_count
        or index.get("business_history_index_path")
        != "business-history-index.json"
        or set(index.get("reports", {})) != {"daily", "weekly", "monthly"}
        or index.get("comparison_contract_proven")
        is not comparison_contract_proven
        or index.get("data_owner_coverage_attestation_sha256")
        != expected_coverage_attestation_sha256
        or "current" in index
        or "archive" in index
    ):
        raise V3ReportsValidationError("formal report index contract is invalid")
    for grain, descriptor in index["reports"].items():
        if (
            descriptor.get("entry_label")
            != (
                "最新完整周期"
                if comparison_contract_proven
                else "最新闭合周期（覆盖未证明）"
            )
            or descriptor.get("artifact_path") != f"current/{grain}.json"
        ):
            raise V3ReportsValidationError("formal report index exposes multiple entries")
    expected_precision = {
        "daily": "calendar_day_assignment_v1",
        "weekly": "iso_week_assignment_v1",
        "monthly": "calendar_month_assignment_v1",
    }
    for grain in ("daily", "weekly", "monthly"):
        report = documents[f"current/{grain}.json"]
        if (
            report.get("schema_version") != V3_REPORT_SCHEMA
            or report.get("artifact_role")
            != (
                "latest_complete_calendar_period"
                if comparison_contract_proven
                else "latest_closed_calendar_period_unattested"
            )
            or report.get("fixture_only") is not False
            or report.get("comparison_contract_proven")
            is not comparison_contract_proven
            or report.get("comparison_contract_basis")
            != expected_comparison_basis
            or report.get("completeness_percent") != expected_completeness
            or report.get("coverage_attestation") != binding["coverage_attestation"]
            or report.get("data_owner_coverage_attestation_sha256")
            != expected_coverage_attestation_sha256
        ):
            raise V3ReportsValidationError(f"formal current report contract is invalid: {grain}")
        for card in report.get("indicators", []):
            current = card.get("current", {})
            if (
                current.get("period_complete")
                is not comparison_contract_proven
                or current.get("comparison_contract_proven")
                is not comparison_contract_proven
                or current.get("data_owner_coverage_attestation_sha256")
                != expected_coverage_attestation_sha256
                or current.get("time_precision") != expected_precision[grain]
                or not isinstance(current.get("observed_time_precision"), str)
                or not current["observed_time_precision"]
                or not isinstance(current.get("observed_voc_type"), str)
                or not current["observed_voc_type"]
                or current.get("voc_type") != "post_voc+comment_context_voc"
            ):
                raise V3ReportsValidationError("formal current metric contract is invalid")
            if current.get("status") == "unavailable" and (
                current.get("value") is not None
                or current.get("display") != "—"
                or card.get("direction") is not None
                or card.get("line_color") != "gray"
            ):
                raise V3ReportsValidationError("unavailable formal metric emitted a direction")
            for comparison in card.get("comparisons", {}).values():
                if comparison.get("status") == "unavailable" and (
                    comparison.get("display") != "—"
                    or comparison.get("direction") is not None
                    or comparison.get("line_color") != "gray"
                    or not comparison.get("reason_codes")
                ):
                    raise V3ReportsValidationError("unavailable formal comparison overclaimed")
                if comparison.get("status") == "available":
                    direction = comparison.get("direction")
                    expected_color = (
                        "red" if direction == "up" else "green" if direction == "down" else "gray"
                    )
                    if comparison.get("line_color") != expected_color:
                        raise V3ReportsValidationError("formal comparison color is invalid")
        brand_rows = report.get("brand_health", {}).get("rows", [])
        if len(brand_rows) != 2:
            raise V3ReportsValidationError("formal brand-health side set is invalid")
        for row in brand_rows:
            if row.get("status") == "unavailable" and (
                row.get("value") is not None or row.get("display") != "—"
            ):
                raise V3ReportsValidationError("formal brand health fabricated a value")
        dimension_rows = report.get("brand_health", {}).get("dimension_rows", [])
        dimension_keys = {
            (row.get("comparison_side"), row.get("dimension_id"))
            for row in dimension_rows
            if isinstance(row, dict)
        }
        if len(dimension_rows) != 8 or dimension_keys != {
            (side, dimension)
            for side in ("raw_observed", "qualified_organic")
            for dimension in (
                "reputation",
                "product_experience",
                "recommendation_trust",
                "risk_resilience",
            )
        }:
            raise V3ReportsValidationError(
                "formal brand-health dimension set is invalid"
            )
        for row in dimension_rows:
            if (
                row.get("grain") != grain
                or row.get("period_id") != report.get("period", {}).get("period_id")
                or row.get("weight_percent") != "25.00"
                or row.get("unit") != "index_points"
            ):
                raise V3ReportsValidationError(
                    "formal brand-health dimension contract is invalid"
                )
            if row.get("status") == "unavailable" and (
                row.get("dimension_value") is not None
                or row.get("contribution_points") is not None
            ):
                raise V3ReportsValidationError(
                    "formal brand-health dimension fabricated a value"
                )
        activity = report.get("period_activity")
        if (
            not isinstance(activity, dict)
            or activity.get("grain") != grain
            or activity.get("period_id") != report.get("period", {}).get("period_id")
            or activity.get("period_complete")
            is not comparison_contract_proven
            or activity.get("time_precision") != expected_precision[grain]
        ):
            raise V3ReportsValidationError("formal period activity contract is invalid")
        for scope in ("all_observed", "momcozy"):
            counts = activity.get(scope)
            if (
                not isinstance(counts, dict)
                or any(type(value) is not int or value < 0 for value in counts.values())
                or counts.get("new_comment_count")
                != counts.get("comments_on_current_period_posts", 0)
                + counts.get("comments_on_historical_posts", 0)
                + counts.get("unresolved_parent_comment_count", 0)
            ):
                raise V3ReportsValidationError("formal period activity counts are invalid")
        action_review = report.get("action_review")
        if grain == "weekly":
            if action_review != {
                "completion_supported": False,
                "items": [],
                "ledger_available": False,
                "reason_codes": ["action_ledger_not_supplied"],
                "schema_version": "reddit_voc_action_review_v1",
                "status": "unavailable",
            }:
                raise V3ReportsValidationError(
                    "formal weekly action review empty-state contract is invalid"
                )
        elif action_review is not None:
            raise V3ReportsValidationError(
                "formal non-weekly report unexpectedly contains action review"
            )
    for grain in ("daily", "weekly", "monthly"):
        archive = documents[f"archive/{grain}.json"]
        if (
            archive.get("artifact_role") != "internal_comparison_archive"
            or archive.get("business_entry_visible") is not False
            or len(archive.get("brand_health_dimension_baselines", []))
            not in ({8, 16} if comparison_contract_proven else {0, 8, 16})
        ):
            raise V3ReportsValidationError("formal archive became a business entry")
    history_index = documents.get("business-history-index.json")
    if (
        not isinstance(history_index, dict)
        or history_index.get("schema_version")
        != "reddit_voc_business_history_index_v1"
        or history_index.get("limits")
        != {"daily": 14, "weekly": 12, "monthly": 12}
        or history_index.get("history_entry_count") != expected_history_count
        or history_index.get("total_business_entry_count")
        != expected_business_count
        or history_index.get("order") != "newest_first"
        or history_index.get("latest_complete_period_excluded") is not True
        or history_index.get("dataset_version") != manifest.get("dataset_version")
        or history_index.get("source") != index.get("source")
        or history_index.get("coverage_attestation")
        != index.get("coverage_attestation")
    ):
        raise V3ReportsValidationError("formal business history index contract is invalid")
    for grain, entries in history_index["reports"].items():
        expected_count = (
            {"daily": 14, "weekly": 12, "monthly": 12}[grain]
            if expected_history_count
            else 0
        )
        if len(entries) != expected_count:
            raise V3ReportsValidationError("formal business history count is invalid")
        for entry in entries:
            path = entry["artifact_path"]
            report = documents.get(path)
            if (
                not isinstance(report, dict)
                or report.get("schema_version") != V3_REPORT_SCHEMA
                or report.get("artifact_role")
                != (
                    "historical_complete_calendar_period"
                    if comparison_contract_proven
                    else "historical_observed_calendar_period_unattested"
                )
                or report.get("business_entry_visible") is not True
                or report.get("entry_label")
                != (
                    "历史完整周期"
                    if comparison_contract_proven
                    else "历史已观测周期（覆盖未证明）"
                )
                or report.get("grain") != grain
                or report.get("period") != entry.get("period")
                or report.get("comparison_archive_path") is not None
                or files[path]["sha256"] != entry.get("artifact_sha256")
            ):
                raise V3ReportsValidationError(
                    "formal historical business report contract is invalid"
                )
    if index != expected_index:
        raise V3ReportsValidationError("formal report index deterministic replay mismatch")
    if manifest != expected_manifest:
        raise V3ReportsValidationError("formal reports manifest deterministic replay mismatch")
    for name, expected in expected_reports.items():
        if documents[name] != expected:
            raise V3ReportsValidationError(
                f"formal report deterministic replay mismatch: {name}"
            )
    return {
        "boundaries": dict(V3_BOUNDARIES),
        "bundle_manifest_sha256": _sha256(reports_dir / "manifest.json"),
        "comparison_contract_basis": expected_comparison_basis,
        "comparison_contract_proven": comparison_contract_proven,
        "completeness_percent": expected_completeness,
        "coverage_attestation": binding["coverage_attestation"],
        "data_owner_coverage_attestation_sha256": expected_coverage_attestation_sha256,
        "deterministic_full_byte_replay": True,
        "metrics_candidate_manifest_sha256": expected_metrics_candidate_manifest_sha256,
        "metrics_input_manifest_sha256": expected_metrics_input_manifest_sha256,
        "metrics_validation_receipt_sha256": expected_metrics_receipt_sha256,
        "promotable": True,
        "business_entry_count": expected_business_count,
        "history_report_count": expected_history_count,
        "report_count": expected_report_count,
        "schema_version": "reddit_voc_reports_validation_receipt_v3",
        "status": "passed_candidate_only",
        "summary": manifest["summary"],
    }


def write_v3_reports_validation_receipt(
    path: Path, receipt: dict[str, Any]
) -> None:
    payload = _v3_canonical_bytes(receipt)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise V3ReportsValidationError("formal reports validation receipt collision")
        return
    path.write_bytes(payload)


def validate_v3_public_reports_wrapper(
    public_dir: Path,
    candidate_dir: Path,
    validation_receipt_path: Path,
    *,
    expected_candidate_manifest_sha256: str,
    expected_validation_receipt_sha256: str,
) -> dict[str, Any]:
    """Validate the release-ready privacy-safe wrapper and embedded receipt."""

    from scripts.build_reddit_reports_snapshot import (
        V3_PUBLIC_REPORT_MANIFEST_SCHEMA,
        V3ReportsBuildError,
        build_v3_public_reports_wrapper,
    )

    try:
        expected_reports, expected_index, expected_receipt, expected_manifest = (
            build_v3_public_reports_wrapper(
                candidate_dir,
                validation_receipt_path,
                expected_candidate_manifest_sha256=expected_candidate_manifest_sha256,
                expected_validation_receipt_sha256=expected_validation_receipt_sha256,
            )
        )
    except V3ReportsBuildError as exc:
        raise V3ReportsValidationError(str(exc)) from exc
    public_dir = Path(public_dir)
    if public_dir.is_symlink() or not public_dir.is_dir():
        raise V3ReportsValidationError("public reports root is invalid")
    if {path.name for path in public_dir.iterdir()} != {
        "archive",
        "business-history-index.json",
        "current",
        "history",
        "manifest.json",
        "report-index.json",
        "validation-receipt.json",
    }:
        raise V3ReportsValidationError("public reports root file set is invalid")
    manifest = _v3_load_canonical(public_dir / "manifest.json", "public reports manifest")
    index = _v3_load_canonical(public_dir / "report-index.json", "public report index")
    comparison_contract_proven = manifest.get("comparison_contract_proven")
    if type(comparison_contract_proven) is not bool:
        raise V3ReportsValidationError("public reports comparison state is invalid")
    expected_history_count = expected_manifest.get("history_report_count")
    if expected_history_count not in (
        {38} if comparison_contract_proven else {0, 38}
    ):
        raise V3ReportsValidationError("public reports history state is invalid")
    expected_report_count = 6 + expected_history_count
    expected_business_count = 3 + expected_history_count
    embedded_receipt = _v3_load_canonical(
        public_dir / "validation-receipt.json", "embedded reports validation receipt"
    )
    if (
        manifest.get("schema_version") != V3_PUBLIC_REPORT_MANIFEST_SCHEMA
        or manifest.get("artifact_stage") != "reports_public_candidate"
        or manifest.get("status") != "validated_candidate"
        or manifest.get("consumption_status")
        != "eligible_for_frontend_candidate_consumption"
        or manifest.get("independent_validation_status") != "passed"
        or manifest.get("promotable") is not True
        or manifest.get("privacy_safe_projection") is not True
        or manifest.get("lineage_manifest_sha256")
        != expected_candidate_manifest_sha256
        or manifest.get("validation_receipt_sha256")
        != expected_validation_receipt_sha256
        or manifest.get("report_count") != expected_report_count
        or manifest.get("history_report_count") != expected_history_count
        or manifest.get("business_entry_count") != expected_business_count
    ):
        raise V3ReportsValidationError("public reports lifecycle is invalid")
    files = manifest.get("files")
    expected_files = set(expected_manifest["files"])
    if (
        not isinstance(files, dict)
        or set(files) != expected_files
        or len(files) != expected_report_count + 3
    ):
        raise V3ReportsValidationError("public reports manifest file set is invalid")
    _v3_validate_inventory(
        public_dir,
        expected_files | {"manifest.json"},
        "public reports root",
        allowed_empty_directories={"history"},
    )
    actual_reports: dict[str, dict[str, Any]] = {}
    for name, record in sorted(files.items()):
        path = _v3_validated_artifact_path(public_dir, name, "public report")
        if (
            not isinstance(record, dict)
            or set(record) != {"bytes", "sha256"}
            or record.get("bytes") != path.stat().st_size
            or record.get("sha256") != _sha256(path)
        ):
            raise V3ReportsValidationError(f"public report file integrity mismatch: {name}")
        if name not in {"report-index.json", "validation-receipt.json"}:
            actual_reports[name] = _v3_load_canonical(path, name)
    if embedded_receipt != expected_receipt:
        raise V3ReportsValidationError("embedded reports validation receipt mismatch")
    if index != expected_index:
        raise V3ReportsValidationError("public report index replay mismatch")
    if manifest != expected_manifest:
        raise V3ReportsValidationError("public reports manifest replay mismatch")
    if actual_reports != expected_reports:
        raise V3ReportsValidationError("public reports deterministic replay mismatch")
    return {
        "boundaries": dict(V3_BOUNDARIES),
        "bundle_manifest_sha256": _sha256(public_dir / "manifest.json"),
        "comparison_contract_basis": manifest["comparison_contract_basis"],
        "comparison_contract_proven": manifest["comparison_contract_proven"],
        "completeness_percent": manifest["completeness_percent"],
        "data_owner_coverage_attestation_sha256": manifest[
            "data_owner_coverage_attestation_sha256"
        ],
        "deterministic_full_byte_replay": True,
        "lineage_manifest_sha256": expected_candidate_manifest_sha256,
        "business_entry_count": expected_business_count,
        "history_report_count": expected_history_count,
        "report_count": expected_report_count,
        "privacy_safe_projection": True,
        "promotable": True,
        "schema_version": "reddit_voc_reports_public_validation_receipt_v3",
        "status": "passed_candidate_only",
        "validation_receipt_sha256": expected_validation_receipt_sha256,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reports-dir", type=Path, required=True)
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--insights-dir", type=Path, required=True)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    result = validate(
        args.reports_dir.resolve(strict=True),
        args.snapshot_dir.resolve(strict=True),
        args.insights_dir.resolve(strict=True),
    )
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
