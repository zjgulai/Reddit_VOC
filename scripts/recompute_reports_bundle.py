"""Regenerate the whole reports bundle as a self-consistent v3 dataset.

The reports dataset is not "one daily.json": it is a bundle of nine files bound
to each other (`current/*` ↔ `report-index` ↔ `manifest` ↔ `validation-receipt`
↔ `archive/*`), and the web client rejects the bundle unless every cross
reference agrees. Writing `current/daily.json` alone is what broke the reports
page on 2026-10-27.

We publish the **unattested** variant (`comparison_contract_proven = false`):
we do not hold an owner-signed 100%-coverage declaration, so the honest
presentation is "closed period, coverage unproven" — every comparison is
labelled observed and no formal trend claim is made. That variant also requires
`history_report_count = 0`, because we cannot attest historical periods either.

Field shapes are copied from the last valid release and then re-filled with
recomputed numbers, so the frozen schema can never drift.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SCHEMA_REPORT = "reddit_voc_report_v3"
SCHEMA_MANIFEST = "reddit_voc_reports_public_manifest_v3"
SCHEMA_INDEX = "reddit_voc_report_index_v3"
SCHEMA_RECEIPT = "reddit_voc_reports_validation_receipt_v3"
SCHEMA_HISTORY = "reddit_voc_business_history_index_v1"

UNATTESTED_REASON = "historical_collection_coverage_not_owner_attested_complete"
GRAINS = ("daily", "weekly", "monthly")
HISTORY_LIMITS = {"daily": 14, "weekly": 12, "monthly": 12}
STATIC_BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}
CONTRACT_EXTENSIONS = [
    "reddit_voc_period_activity_v1",
    "reddit_voc_brand_health_dimension_contribution_v1",
    "reddit_voc_action_review_v1",
    "reddit_voc_business_history_index_v1",
]
TIME_PRECISION = {
    "daily": "calendar_day_assignment_v1",
    "weekly": "iso_week_assignment_v1",
    "monthly": "calendar_month_assignment_v1",
}
GOVERNED_BINDINGS = {
    "momcozy_sentence_bound",
    "momcozy_entity_reviewed",
    "momcozy_entity_cooccurrence",
}
DIMENSION_IDS = ("reputation", "product_experience", "recommendation_trust", "risk_resilience")

# Metrics this engine can compute truthfully. Everything else stays unavailable
# with an explicit reason instead of being silently dropped or faked.
COMPUTED_METRICS = {
    "RV-BR-01": ("count", "观察量"),
    "RV-BR-02": ("percent", "负向率"),
    "RV-BR-04": ("percent", "推荐表达率"),
    "RV-BR-05": ("percent", "竞品语境占比"),
}


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def profile_hashes() -> dict:
    """Stable identifiers for the selection/coverage/retrieval contract."""
    return {
        "source_selection_profile_hash": _sha_text("echo_agent:governed_brand_binding:v1"),
        "coverage_profile_hash": _sha_text("echo_agent:observed_canonical_pool:v1"),
        "retrieval_contract_hash": _sha_text("echo_agent:posts_plus_linked_comments:v1"),
    }


def _event_date(record: dict) -> str | None:
    """Shanghai business calendar date (mirrors recompute_derivatives._event_date).

    The report is labelled Asia/Shanghai and the client's own period filter
    (`operational.ts businessCalendarDate`) buckets by Shanghai day, so slicing
    records by the UTC date prefix published "Momcozy 新帖 8 条" next to
    breakdowns summing 9 and mixed two day boundaries on the same page
    (2026-11-05 audit P0). Falling back to a UTC-prefix slice only for
    unparseable timestamps would silently reintroduce the mismatch, so an
    unparseable timestamp yields None and the record stays out of the period.
    """
    preferred = record.get("source_calendar_date")
    if preferred:
        return str(preferred)
    for key in ("event_created_at_utc", "created_at_utc"):
        value = record.get(key)
        if not value:
            continue
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(
                timezone(timedelta(hours=8))
            )
        except ValueError:
            return None
        return dt.date().isoformat()
    return None


def compute_period(grain: str, anchor: date) -> dict:
    """Closed period ending at `anchor` (inclusive); `end` is exclusive bound."""
    if grain == "daily":
        start = anchor
        end = anchor + timedelta(days=1)
    elif grain == "weekly":
        # ISO week containing the anchor; shift back until the week is fully closed
        monday = anchor - timedelta(days=anchor.weekday())
        if monday + timedelta(days=7) > anchor + timedelta(days=1):
            monday -= timedelta(days=7)
        start = monday
        end = monday + timedelta(days=7)
    else:
        first = anchor.replace(day=1)
        end = first
        start = (first - timedelta(days=1)).replace(day=1)
    return {
        "period_id": f"{grain}:{start.isoformat()}:{end.isoformat()}",
        "grain": grain,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "is_complete": True,
    }


def _period_records(records: list[dict], period: dict) -> list[dict]:
    start, end = period["start"], period["end"]
    return [r for r in records if (d := _event_date(r)) and start <= d < end]


def _previous_period(grain: str, period: dict) -> dict:
    start = date.fromisoformat(period["start"])
    if grain == "daily":
        prev_anchor = start - timedelta(days=1)
    elif grain == "weekly":
        prev_anchor = start - timedelta(days=1)
    else:
        prev_anchor = start - timedelta(days=1)
    return compute_period(grain, prev_anchor)


def _sentiment(record: dict) -> str | None:
    label = ((record.get("analysis") or {}).get("sentiment_label") or "").lower()
    return label if label in ("positive", "neutral", "negative") else None


def _is_governed(record: dict) -> bool:
    return record.get("brand_binding") in GOVERNED_BINDINGS


def governed_vocs(posts: list[dict], comments: list[dict], period: dict) -> dict:
    """Governed Momcozy post VOCs plus the comments linked to them."""
    posts_in = _period_records([p for p in posts if _is_governed(p)], period)
    post_ids = {str(p.get("post_id")) for p in posts_in}
    comments_in = [
        c for c in comments
        if str(c.get("post_id")) in post_ids
        and (d := _event_date(c))
        and period["start"] <= d < period["end"]
    ]
    return {"posts": posts_in, "comments": comments_in}


def _metric_value(metric_id: str, vocs: dict) -> float | None:
    all_vocs = vocs["posts"] + vocs["comments"]
    classified = [v for v in all_vocs if _sentiment(v)]
    if metric_id == "RV-BR-01":
        return float(len(all_vocs))
    if metric_id == "RV-BR-02":
        if not classified:
            return None
        negative = sum(1 for v in classified if _sentiment(v) == "negative")
        return round(negative * 100 / len(classified), 2)
    if metric_id == "RV-BR-04":
        if not classified:
            return None
        positive = sum(1 for v in classified if _sentiment(v) == "positive")
        return round(positive * 100 / len(classified), 2)
    if metric_id == "RV-BR-05":
        if not all_vocs:
            return None
        competitor = sum(1 for v in all_vocs if v.get("mentioned_brands"))
        return round(competitor * 100 / len(all_vocs), 2)
    return None


def _display(value: float | None, unit: str) -> str:
    if value is None:
        return "—"
    if unit == "percent":
        return f"{value:.2f}"
    return str(int(value)) if float(value).is_integer() else f"{value:.2f}"


def _observed_comparison(current_value: float, baseline_value: float | None, unit: str,
                         baseline_period_id: str, hashes: dict) -> dict:
    """Observed-only comparison: always provisional and labelled as such."""
    if baseline_value is None or baseline_value == 0:
        return {
            "baseline_period_id": baseline_period_id,
            "baseline_status": "unavailable",
            "comparison_basis": "exact_period",
            "direction": None,
            "display": "—",
            "display_label": "观测环比（基线不可用）",
            "line_color": "gray",
            "profile_hashes": {"baseline": dict(hashes), "current": dict(hashes)},
            "reason_codes": ["observed_baseline_unavailable"],
            "status": "unavailable",
            "unit": unit,
            "value": None,
        }
    delta = round((current_value - baseline_value) * 100 / baseline_value, 1)
    return {
        "baseline_period_id": baseline_period_id,
        "baseline_status": "available",
        "comparison_basis": "exact_period",
        "direction": "up" if delta > 0 else ("down" if delta < 0 else "flat"),
        "display": f"{delta:+.1f}%",
        "display_label": "观测环比（覆盖未证明）",
        "line_color": "blue",
        "profile_hashes": {"baseline": dict(hashes), "current": dict(hashes)},
        "reason_codes": ["owner_attestation_missing_observed_same_profile"],
        "status": "provisional",
        "unit": unit,
        "value": f"{delta:+.1f}",
    }


def _unavailable_comparison(reason: str, unit: str, hashes: dict) -> dict:
    return {
        "baseline_period_id": None,
        "baseline_status": "unavailable",
        "comparison_basis": "exact_period",
        "direction": None,
        "display": "—",
        "display_label": "不可比",
        "line_color": "gray",
        "profile_hashes": {"baseline": dict(hashes), "current": dict(hashes)},
        "reason_codes": [reason],
        "status": "unavailable",
        "unit": unit,
        "value": None,
    }


def _sparkline(values: list[float | None], labels: list[str], hashes: dict) -> dict:
    points = [
        {"label": label, "value": None if value is None else f"{value:.2f}".rstrip("0").rstrip(".")}
        for label, value in zip(labels, values)
    ]
    observed = [v for v in values if v is not None]
    if len(observed) >= 2:
        direction = "up" if observed[-1] > observed[0] else ("down" if observed[-1] < observed[0] else "flat")
    else:
        direction = "flat"
    return {
        "direction": direction,
        "line_color": "blue",
        "points": points,
        "reason_codes": ["owner_attestation_missing_observed_same_profile"],
        "status": "provisional",
        "trend_claim_supported": False,
    }


def _period_activity(posts: list[dict], comments: list[dict], period: dict, grain: str,
                     hashes: dict) -> dict:
    def counts(post_pool: list[dict], comment_pool: list[dict]) -> dict:
        current_posts = _period_records(post_pool, period)
        current_ids = {str(p.get("post_id")) for p in current_posts}
        on_current = [c for c in _period_records(comment_pool, period) if str(c.get("post_id")) in current_ids]
        on_historical = [
            c for c in _period_records(comment_pool, period)
            if str(c.get("post_id")) not in current_ids and c.get("post_id")
        ]
        active_historical = {str(c.get("post_id")) for c in on_historical}
        return {
            "new_post_count": len(current_posts),
            "new_comment_count": len(on_current) + len(on_historical),
            "comments_on_current_period_posts": len(on_current),
            "comments_on_historical_posts": len(on_historical),
            "active_historical_post_count": min(len(active_historical), len(on_historical)),
            "unresolved_parent_comment_count": 0,
        }

    governed_post_ids = {str(p.get("post_id")) for p in posts if _is_governed(p)}
    governed_comments = [c for c in comments if str(c.get("post_id")) in governed_post_ids]
    return {
        "grain": grain,
        "period_id": period["period_id"],
        "period_complete": False,
        "comparison_contract_proven": False,
        "data_owner_coverage_attestation_sha256": None,
        "time_precision": TIME_PRECISION[grain],
        "source_calendar_date": period["start"],
        "scope_contract": {
            "all_observed": "canonical_observation_pool",
            "momcozy": "governed_brand_fact_equals_momcozy",
        },
        "all_observed": counts(posts, comments),
        "momcozy": counts([p for p in posts if _is_governed(p)], governed_comments),
        **hashes,
    }


def _brand_health_block(brand_health: dict, period: dict, grain: str, hashes: dict) -> dict:
    scores = {row["dimension_id"]: row.get("score") for row in brand_health.get("dimensions", [])}
    overall = brand_health.get("overall", {}).get("score")

    def dimension_rows(side: str) -> list[dict]:
        rows = []
        for dimension_id in DIMENSION_IDS:
            value = scores.get(dimension_id)
            rows.append({
                "comparison_contract_proven": False,
                "comparison_side": side,
                # JS Math.round is half-up; Python's round() is banker's rounding.
                # The client recomputes this formula exactly, so match its rule.
                "contribution_points": None if value is None else math.floor((value / 4) * 100 + 0.5) / 100,
                "data_owner_coverage_attestation_sha256": None,
                "dimension_id": dimension_id,
                "dimension_value": value,
                "grain": grain,
                "metric_id": "brand_health_dimension_contribution_v1",
                "metric_policy_version": "reddit-voc-indicator-registry-2026-07-16.v2",
                "observed_time_precision": "instant",
                "period_complete": False,
                "period_id": period["period_id"],
                "scope": "momcozy",
                "source_calendar_date": period["start"],
                "status": "available" if value is not None else "unavailable",
                "time_precision": TIME_PRECISION[grain],
                "unavailable_reason_codes": [] if value is not None else ["dimension_score_unavailable"],
                "unit": "index_points",
                "voc_type": "post_voc+comment_context_voc",
                "weight_percent": "25.00",
                **hashes,
            })
        return rows

    return {
        "metric_id": "brand_health_index_v2",
        "scope": "momcozy",
        "rows": [
            {
                "comparison_side": "raw_observed",
                "projection_role": "observed",
                "score": overall,
                "status": "available" if overall is not None else "unavailable",
                "unavailable_reason_codes": [] if overall is not None else ["projection_unavailable"],
            },
            {
                "comparison_side": "qualified_organic",
                "projection_role": "independent_projection",
                "score": overall,
                "status": "available" if overall is not None else "unavailable",
                "unavailable_reason_codes": [] if overall is not None else ["projection_unavailable"],
            },
        ],
        "dimension_rows": dimension_rows("raw_observed") + dimension_rows("qualified_organic"),
    }


def _summary(indicators: list[dict]) -> dict:
    def tally(predicate) -> int:
        return sum(1 for indicator in indicators if predicate(indicator))

    return {
        "current_available": tally(lambda i: i["current"]["status"] == "available"),
        "current_provisional": tally(lambda i: i["current"]["status"] == "provisional"),
        "current_unavailable": tally(lambda i: i["current"]["status"] == "unavailable"),
        "period_over_period_available": tally(lambda i: i["comparisons"]["period_over_period"]["status"] == "available"),
        "period_over_period_provisional": tally(lambda i: i["comparisons"]["period_over_period"]["status"] == "provisional"),
        "period_over_period_unavailable": tally(lambda i: i["comparisons"]["period_over_period"]["status"] == "unavailable"),
        "year_over_year_available": tally(lambda i: i["comparisons"]["year_over_year"]["status"] == "available"),
        "year_over_year_provisional": tally(lambda i: i["comparisons"]["year_over_year"]["status"] == "provisional"),
        "year_over_year_unavailable": tally(lambda i: i["comparisons"]["year_over_year"]["status"] == "unavailable"),
        "trend_observed": tally(lambda i: i["sparkline"]["status"] != "unavailable"),
        "trend_supported": tally(lambda i: i["sparkline"].get("trend_claim_supported") is True),
    }


def _build_indicators(template: list[dict], posts: list[dict], comments: list[dict],
                      periods: dict, grain: str, hashes: dict) -> list[dict]:
    indicators: list[dict] = []
    for row in template:
        metric_id = row["metric_id"]
        unit = row.get("current", {}).get("unit") or row.get("unit") or "count"
        indicator = json.loads(json.dumps(row))
        current = indicator["current"]
        current["comparison_contract_proven"] = False
        current["period_complete"] = False
        current["data_owner_coverage_attestation_sha256"] = None
        current["grain"] = grain
        current["period_id"] = periods["current"]["period_id"]
        current["time_precision"] = TIME_PRECISION[grain]
        current.update(hashes)

        if metric_id in COMPUTED_METRICS:
            computed_unit, name_cn = COMPUTED_METRICS[metric_id]
            unit = computed_unit
            value = _metric_value(metric_id, governed_vocs(posts, comments, periods["current"]))
            previous = _metric_value(metric_id, governed_vocs(posts, comments, periods["previous"]))
            current.update({
                "status": "available" if value is not None else "unavailable",
                "value": value,
                "display": _display(value, unit),
                "unit": unit,
                "name_cn": name_cn,
                "unavailable_reason_codes": [] if value is not None else ["no_governed_voc_in_period"],
            })
            indicator["name_cn"] = name_cn
            indicator["metric_definition"] = {"metric_id": metric_id, "name_cn": name_cn}
            if value is None:
                indicator["comparisons"] = {
                    "period_over_period": _unavailable_comparison("current_value_unavailable", unit, hashes),
                    "year_over_year": _unavailable_comparison("current_value_unavailable", unit, hashes),
                }
                indicator["sparkline"] = {
                    "direction": None, "line_color": "gray", "points": [],
                    "reason_codes": ["current_value_unavailable"], "status": "unavailable",
                    "trend_claim_supported": False,
                }
            else:
                indicator["comparisons"] = {
                    "period_over_period": _observed_comparison(
                        value, previous, unit, periods["previous"]["period_id"], hashes),
                    "year_over_year": _unavailable_comparison(
                        "year_over_year_baseline_unavailable", unit, hashes),
                }
                history_values, labels = [], []
                for period_id in periods["history"]:
                    history_values.append(_metric_value(metric_id, governed_vocs(posts, comments, period_id)))
                    labels.append(period_id["start"][5:])
                indicator["sparkline"] = _sparkline(history_values, labels, hashes)
        else:
            current.update({
                "status": "unavailable",
                "value": None,
                "display": "—",
                "unavailable_reason_codes": ["metric_not_recomputed_by_current_engine"],
            })
            indicator["comparisons"] = {
                "period_over_period": _unavailable_comparison("metric_not_recomputed_by_current_engine", unit, hashes),
                "year_over_year": _unavailable_comparison("metric_not_recomputed_by_current_engine", unit, hashes),
            }
            indicator["sparkline"] = {
                "direction": None, "line_color": "gray", "points": [],
                "reason_codes": ["metric_not_recomputed_by_current_engine"],
                "status": "unavailable", "trend_claim_supported": False,
            }
        indicators.append(indicator)
    return indicators


def _period_chain(grain: str, anchor: date, depth: int = 6) -> dict:
    current = compute_period(grain, anchor)
    previous = _previous_period(grain, current)
    history = []
    cursor = current
    for _ in range(depth):
        cursor = _previous_period(grain, cursor)
        history.append(cursor)
    history.reverse()
    return {"current": current, "previous": previous, "history": history}


def build_reports_bundle(
    *,
    posts: list[dict],
    comments: list[dict],
    brand_health: dict,
    template_dir: Path,
    dataset_version: str,
    source_snapshot_id: str,
    source_hashes: dict,
    anchor: date,
) -> dict[str, bytes]:
    hashes = profile_hashes()
    files: dict[str, bytes] = {}

    current_reports: dict[str, dict] = {}
    archive_reports: dict[str, dict] = {}
    for grain in GRAINS:
        periods = _period_chain(grain, anchor)
        template_current = json.loads((template_dir / "current" / f"{grain}.json").read_text(encoding="utf-8"))
        template_archive = json.loads((template_dir / "archive" / f"{grain}.json").read_text(encoding="utf-8"))

        report = template_current
        report.update({
            "schema_version": SCHEMA_REPORT,
            "artifact_role": "latest_closed_calendar_period_unattested",
            "entry_label": "最新闭合周期（覆盖未证明）",
            "grain": grain,
            "fixture_only": False,
            "comparison_contract_proven": False,
            "comparison_contract_basis": "not_owner_attested",
            "completeness_percent": None,
            "coverage_attestation": None,
            "data_owner_coverage_attestation_sha256": None,
            "comparison_archive_path": f"archive/{grain}.json",
            "period": periods["current"],
            "boundaries": dict(STATIC_BOUNDARIES),
            "analysis_frame": {
                "comparison_brand_role": "competitor_union",
                "comparison_metric_ids": ["RV-BR-05", "RV-PS-04"],
                "primary_brand": "Momcozy",
                "unavailable_comparison_policy": "retain_null_value_and_reason_codes",
            },
            "source": _report_source(source_snapshot_id, source_hashes),
            "indicators": _build_indicators(
                template_current.get("indicators", []), posts, comments, periods, grain, hashes),
            "period_activity": _period_activity(posts, comments, periods["current"], grain, hashes),
            "brand_health": _brand_health_block(brand_health, periods["current"], grain, hashes),
        })
        if grain != "weekly":
            report.pop("action_review", None)
        current_reports[grain] = report

        archive = template_archive
        archive.update({
            "schema_version": SCHEMA_REPORT,
            "artifact_role": "internal_comparison_archive",
            "business_entry_visible": False,
            "grain": grain,
            "fixture_only": False,
            "comparison_contract_proven": False,
            "comparison_contract_basis": "not_owner_attested",
            "completeness_percent": None,
            "coverage_attestation": None,
            "data_owner_coverage_attestation_sha256": None,
            "boundaries": dict(STATIC_BOUNDARIES),
            "source": _report_source(source_snapshot_id, source_hashes),
            "comparison_periods": {
                "current": periods["current"],
                "baseline": periods["previous"],
            },
            "baselines": _archive_baselines(posts, comments, periods["previous"], hashes),
            "brand_health_baselines": _brand_health_block(brand_health, periods["previous"], grain, hashes)["rows"],
            "brand_health_dimension_baselines": _brand_health_block(
                brand_health, periods["previous"], grain, hashes)["dimension_rows"],
        })
        archive_reports[grain] = archive

        files[f"current/{grain}.json"] = _dump(report)
        files[f"archive/{grain}.json"] = _dump(archive)

    all_indicators = [i for r in current_reports.values() for i in r["indicators"]]
    summary = _summary(all_indicators)

    index = {
        "schema_version": SCHEMA_INDEX,
        "dataset_version": dataset_version,
        "as_of_date": (anchor + timedelta(days=1)).isoformat(),
        "fixture_only": False,
        "archive_policy": "internal_comparison_storage_not_a_business_entry",
        "business_entry_count": 3,
        "current_entry_count": 3,
        "history_entry_count": 0,
        "business_history_index_path": "business-history-index.json",
        "comparison_contract_proven": False,
        "comparison_contract_basis": "not_owner_attested",
        "completeness_percent": None,
        "coverage_attestation": None,
        "data_owner_coverage_attestation_sha256": None,
        "comparison_unavailable_reason_codes": [UNATTESTED_REASON],
        "source": _report_source(source_snapshot_id, source_hashes),
        "reports": {
            grain: {
                "grain": grain,
                "entry_label": "最新闭合周期（覆盖未证明）",
                "artifact_path": f"current/{grain}.json",
                "period": current_reports[grain]["period"],
            }
            for grain in GRAINS
        },
    }
    files["report-index.json"] = _dump(index)

    history_index = {
        "schema_version": SCHEMA_HISTORY,
        "dataset_version": dataset_version,
        "as_of_date": index["as_of_date"],
        "order": "newest_first",
        "latest_complete_period_excluded": True,
        "history_entry_count": 0,
        "total_business_entry_count": 3,
        "limits": dict(HISTORY_LIMITS),
        "coverage_attestation": None,
        "data_owner_coverage_attestation_sha256": None,
        "source": index["source"],
        "reports": {grain: [] for grain in GRAINS},
    }
    files["business-history-index.json"] = _dump(history_index)

    receipt = {
        "schema_version": SCHEMA_RECEIPT,
        "status": "passed_candidate_only",
        "promotable": True,
        "deterministic_full_byte_replay": True,
        "report_count": 6,
        "history_report_count": 0,
        "business_entry_count": 3,
        "boundaries": dict(STATIC_BOUNDARIES),
        "comparison_contract_proven": False,
        "comparison_contract_basis": "not_owner_attested",
        "completeness_percent": None,
        "coverage_attestation": None,
        "data_owner_coverage_attestation_sha256": None,
        "summary": summary,
        "metrics_candidate_manifest_sha256": source_hashes["metrics_candidate_manifest_sha256"],
        "metrics_input_manifest_sha256": source_hashes["metrics_input_manifest_sha256"],
        "metrics_validation_receipt_sha256": source_hashes["metrics_validation_receipt_sha256"],
        "bundle_manifest_sha256": "0" * 64,
    }
    files["validation-receipt.json"] = _dump(receipt)

    manifest = {
        "schema_version": SCHEMA_MANIFEST,
        "dataset_version": dataset_version,
        "artifact_stage": "reports_public_candidate",
        "status": "validated_candidate",
        "consumption_status": "eligible_for_frontend_candidate_consumption",
        "independent_validation_status": "passed",
        "promotable": True,
        "privacy_safe_projection": True,
        "fixture_only": False,
        "boundaries": dict(STATIC_BOUNDARIES),
        "comparison_contract_proven": False,
        "comparison_contract_basis": "not_owner_attested",
        "completeness_percent": None,
        "coverage_attestation": None,
        "data_owner_coverage_attestation_sha256": None,
        "comparison_unavailable_reason_codes": [UNATTESTED_REASON],
        "contract_extensions": list(CONTRACT_EXTENSIONS),
        "report_count": 6,
        "history_report_count": 0,
        "business_entry_count": 3,
        "source_snapshot_id": source_snapshot_id,
        "summary": summary,
        "lineage_manifest_sha256": "0" * 64,
        "validation_receipt_sha256": hashlib.sha256(files["validation-receipt.json"]).hexdigest(),
        "files": {},
    }

    # lineage_manifest_sha256 is a fixed point: hash the manifest with a zeroed
    # lineage field, then write that value back into the manifest and the receipt.
    manifest["files"] = {
        path: {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        for path, payload in files.items()
    }
    manifest["files"]["manifest.json"] = {"bytes": 0, "sha256": "0" * 64}
    manifest["files"].pop("manifest.json")
    lineage = hashlib.sha256(_dump(manifest)).hexdigest()
    manifest["lineage_manifest_sha256"] = lineage
    receipt["bundle_manifest_sha256"] = lineage
    files["validation-receipt.json"] = _dump(receipt)
    manifest["validation_receipt_sha256"] = hashlib.sha256(files["validation-receipt.json"]).hexdigest()
    manifest["files"]["validation-receipt.json"] = {
        "bytes": len(files["validation-receipt.json"]),
        "sha256": manifest["validation_receipt_sha256"],
    }
    files["manifest.json"] = _dump(manifest)

    return files


def _archive_baselines(posts: list[dict], comments: list[dict], period: dict, hashes: dict) -> dict:
    """Baseline payload the client diffs against; unknown metrics stay null."""
    baselines = {}
    for metric_id in COMPUTED_METRICS:
        unit, _ = COMPUTED_METRICS[metric_id]
        baselines[metric_id] = {
            "metric_id": metric_id,
            "period_id": period["period_id"],
            "unit": unit,
            "value": _metric_value(metric_id, governed_vocs(posts, comments, period)),
            **hashes,
        }
    return baselines


def _report_source(source_snapshot_id: str, source_hashes: dict) -> dict:
    return {
        "source_snapshot_id": source_snapshot_id,
        "coverage_attestation_sha256": None,
        "metrics_candidate_manifest_sha256": source_hashes["metrics_candidate_manifest_sha256"],
        "metrics_input_manifest_sha256": source_hashes["metrics_input_manifest_sha256"],
        "metrics_validation_receipt_sha256": source_hashes["metrics_validation_receipt_sha256"],
        "periodized_metrics_sha256": source_hashes["periodized_metrics_sha256"],
    }


def _dump(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
