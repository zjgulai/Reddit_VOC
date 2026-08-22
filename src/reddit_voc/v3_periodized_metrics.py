"""Hash-bound calendar periods and compact metric rows for V3 reporting.

Floating ``day`` observations keep their source calendar date.  Only
timezone-aware ``instant``/``hour`` observations are converted to the
reporting timezone.  Cross-period comparison fails closed unless an exact
dataset/snapshot/scope/window-bound data-owner coverage declaration is
provided.  That declaration is explicitly owner-attested evidence and is not
misrepresented as crawler or pagination proof.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import re
from typing import Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from reddit_voc.v3_brand_health import compute_brand_health
from reddit_voc.v3_indicators import (
    EXPECTED_BOUNDARIES,
    IndicatorRegistry,
    canonical_json_bytes,
    compute_indicator,
)
from reddit_voc.v3_reporting_periods import complete_period_windows


INPUT_SCHEMA_VERSION = "reddit_voc_periodized_metrics_input_v2"
CANDIDATE_SCHEMA_VERSION = "reddit_voc_periodized_metrics_candidate_v2"
PERIOD_ACTIVITY_EXTENSION = "reddit_voc_period_activity_v1"
BRAND_HEALTH_DIMENSION_EXTENSION = "reddit_voc_brand_health_dimension_contribution_v1"
BRAND_HEALTH_DIMENSIONS = (
    "reputation",
    "product_experience",
    "recommendation_trust",
    "risk_resilience",
)
ATTESTATION_SCHEMA_VERSION = "reddit_voc_data_owner_coverage_attestation_v1"
REPORTING_TIMEZONE = "Asia/Shanghai"
GRAINS = ("daily", "weekly", "monthly")
PERIOD_TIME_PRECISION = {
    "daily": "calendar_day_assignment_v1",
    "monthly": "calendar_month_assignment_v1",
    "weekly": "iso_week_assignment_v1",
}
PERIOD_VOC_TYPE_BY_MEMBER_TYPE = {
    "canonical_entity": "post_voc+comment_context_voc",
    "cluster": "post_voc+comment_context_voc",
    "event_dossier": "post_voc+comment_context_voc",
    "review_item": "post_voc+comment_context_voc",
    "thread": "post_voc+comment_context_voc",
}
COMPARISON_USES = ("period_over_period", "trend", "year_over_year")
OWNER_ATTESTED_EVIDENCE_CLASS = "owner_attested_not_crawler_proof"
UNATTESTED_REASON = "historical_collection_coverage_not_owner_attested_complete"
REPORT_COMPARISON_POLICY = {
    "baseline_zero_display": "—",
    "calculation_layer": "report",
    "required_profile_fields": [
        "source_selection_profile_hash",
        "coverage_profile_hash",
        "retrieval_contract_hash",
    ],
    "required_row_compatibility": [
        "same_grain",
        "same_metric_id",
        "same_profile_hashes",
        "same_status_available",
        "same_unit",
    ],
    "trend_minimum_complete_periods": 3,
    "unavailable_display": "—",
}
PROFILE_NAMES = (
    "source_selection_profile",
    "coverage_profile",
    "retrieval_contract",
)
PROFILE_HASH_FIELDS = {
    "source_selection_profile": "source_selection_profile_hash",
    "coverage_profile": "coverage_profile_hash",
    "retrieval_contract": "retrieval_contract_hash",
}
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class PeriodizedMetricsError(ValueError):
    """Period assignment, profile binding, or candidate replay is invalid."""


def _hash(value: object) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def _artifact_hash(value: object) -> str:
    return sha256(canonical_json_bytes(value) + b"\n").hexdigest()


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or HEX64.fullmatch(value) is None:
        raise PeriodizedMetricsError(f"{label} must be lowercase SHA-256")
    return value


def _calendar_date(row: Mapping[str, object]) -> date:
    precision = row.get("event_time_precision")
    instant = row.get("event_created_at_utc")
    calendar_date = row.get("source_calendar_date")
    if precision == "day":
        if instant is not None or not isinstance(calendar_date, str):
            raise PeriodizedMetricsError("floating day contract is invalid")
        try:
            return date.fromisoformat(calendar_date)
        except ValueError as exc:
            raise PeriodizedMetricsError("floating day is invalid") from exc
    if precision not in {"instant", "hour"} or not isinstance(instant, str):
        raise PeriodizedMetricsError("instant/hour contract is invalid")
    if calendar_date is not None:
        raise PeriodizedMetricsError("instant/hour cannot carry a floating day")
    try:
        parsed = datetime.fromisoformat(instant.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PeriodizedMetricsError("instant/hour value is invalid") from exc
    if parsed.tzinfo is None:
        raise PeriodizedMetricsError("instant/hour value lacks timezone")
    return parsed.astimezone(ZoneInfo(REPORTING_TIMEZONE)).date()


def _month_end(start: date) -> date:
    if start.month == 12:
        return date(start.year + 1, 1, 1)
    return date(start.year, start.month + 1, 1)


def _period_window(grain: str, value: date) -> tuple[str, date, date]:
    if grain == "daily":
        start = value
        end = value + timedelta(days=1)
    elif grain == "weekly":
        start = value - timedelta(days=value.weekday())
        end = start + timedelta(days=7)
    elif grain == "monthly":
        start = value.replace(day=1)
        end = _month_end(start)
    else:
        raise PeriodizedMetricsError("period grain is unsupported")
    return f"{grain}:{start.isoformat()}:{end.isoformat()}", start, end


def _precision_label(counts: Mapping[str, int]) -> str:
    present = {key for key, value in counts.items() if value}
    if not present:
        return "unobserved"
    if present == {"day"}:
        return "day"
    if present <= {"instant", "hour"}:
        return next(iter(present)) if len(present) == 1 else "instant_or_hour"
    return "mixed"


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise PeriodizedMetricsError(f"{label} is invalid")
    return value


def validate_coverage_attestation(
    value: Mapping[str, object],
    *,
    expected_sha256: str,
    dataset_id: str,
    source_snapshot_id: str,
    scope: str,
    min_observed_date: date,
    max_observed_date: date,
) -> dict[str, object]:
    required = {
        "attestation_basis",
        "attestation_date",
        "attestation_id",
        "boundaries",
        "comparison_uses",
        "completeness_percent",
        "coverage_window",
        "dataset_id",
        "evidence_class",
        "schema_version",
        "scope",
        "source_snapshot_id",
        "statement_cn",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise PeriodizedMetricsError("coverage attestation fields are invalid")
    document = dict(value)
    expected_sha256 = _sha(expected_sha256, "coverage attestation SHA")
    if _artifact_hash(document) != expected_sha256:
        raise PeriodizedMetricsError("coverage attestation hash mismatch")
    if document.get("schema_version") != ATTESTATION_SCHEMA_VERSION:
        raise PeriodizedMetricsError("coverage attestation schema is invalid")
    if document.get("attestation_basis") != "data_owner_declaration":
        raise PeriodizedMetricsError("coverage attestation basis is invalid")
    if document.get("evidence_class") != OWNER_ATTESTED_EVIDENCE_CLASS:
        raise PeriodizedMetricsError("coverage attestation evidence class is invalid")
    if document.get("boundaries") != EXPECTED_BOUNDARIES:
        raise PeriodizedMetricsError("coverage attestation boundaries are invalid")
    if document.get("completeness_percent") != 100:
        raise PeriodizedMetricsError("coverage attestation completeness is invalid")
    if document.get("comparison_uses") != list(COMPARISON_USES):
        raise PeriodizedMetricsError("coverage attestation comparison uses are invalid")
    if document.get("dataset_id") != dataset_id:
        raise PeriodizedMetricsError("coverage attestation dataset mismatch")
    if document.get("source_snapshot_id") != source_snapshot_id:
        raise PeriodizedMetricsError("coverage attestation snapshot mismatch")
    if document.get("scope") != scope:
        raise PeriodizedMetricsError("coverage attestation scope mismatch")
    _text(document.get("attestation_id"), "coverage attestation ID")
    _text(document.get("statement_cn"), "coverage attestation statement")
    try:
        date.fromisoformat(_text(document.get("attestation_date"), "attestation date"))
    except ValueError as exc:
        raise PeriodizedMetricsError("coverage attestation date is invalid") from exc
    window = document.get("coverage_window")
    expected_window = {
        "end_calendar_date_inclusive": max_observed_date.isoformat(),
        "start_calendar_date_inclusive": min_observed_date.isoformat(),
    }
    if not isinstance(window, Mapping) or dict(window) != expected_window:
        raise PeriodizedMetricsError("coverage attestation window mismatch")
    return document


def _iter_period_starts(grain: str, start: date, end: date) -> Iterable[date]:
    _, current, _ = _period_window(grain, start)
    while current <= end:
        yield current
        if grain == "daily":
            current += timedelta(days=1)
        elif grain == "weekly":
            current += timedelta(days=7)
        else:
            current = _month_end(current)


def _profiles(
    *,
    coverage_attestation_sha256: str | None,
    dataset_id: str,
    input_bindings: Mapping[str, str],
    metric_policy_version: str,
    scope: str,
    observation_count: int,
    min_observed_date: date,
    max_observed_date: date,
    precision_counts: Mapping[str, int],
    source_snapshot_id: str,
) -> tuple[dict[str, dict[str, object]], dict[str, str]]:
    if not isinstance(input_bindings, Mapping):
        raise PeriodizedMetricsError("input bindings must be an object")
    bindings = {
        str(key): _sha(value, f"input binding {key}")
        for key, value in input_bindings.items()
    }
    required = {
        "canonical_manifest_sha256",
        "canonical_receipt_sha256",
        "facts_manifest_sha256",
        "governed_manifest_sha256",
        "governed_receipt_sha256",
        "metric_eligibility_sha256",
        "vocs_sha256",
    }
    if not required <= set(bindings):
        raise PeriodizedMetricsError("periodized profile bindings are incomplete")
    source_selection = {
        "automation_exclusion_stage": "before_business_metrics",
        "facts_manifest_sha256": bindings["facts_manifest_sha256"],
        "governed_manifest_sha256": bindings["governed_manifest_sha256"],
        "metric_eligibility_sha256": bindings["metric_eligibility_sha256"],
        "metric_policy_version": metric_policy_version,
        "scope": scope,
        "selection_policy_version": "task4_default_side_governed_routing_v1",
    }
    coverage = {
        "canonical_manifest_sha256": bindings["canonical_manifest_sha256"],
        "canonical_receipt_sha256": bindings["canonical_receipt_sha256"],
        "collection_completeness_proven": coverage_attestation_sha256 is not None,
        "coverage_evidence_class": (
            OWNER_ATTESTED_EVIDENCE_CLASS
            if coverage_attestation_sha256 is not None
            else "not_attested"
        ),
        "coverage_status": (
            "owner_attested_complete_for_declared_dataset_scope_window"
            if coverage_attestation_sha256 is not None
            else UNATTESTED_REASON
        ),
        "data_owner_coverage_attestation_sha256": coverage_attestation_sha256,
        "dataset_id": dataset_id,
        "max_observed_calendar_date": max_observed_date.isoformat(),
        "min_observed_calendar_date": min_observed_date.isoformat(),
        "observation_count": observation_count,
        "scope": scope,
        "source_snapshot_id": source_snapshot_id,
        "time_precision_counts": dict(sorted(precision_counts.items())),
    }
    retrieval = {
        "calendar_assignment_policy": (
            "floating_day_literal_instant_hour_asia_shanghai_v1"
        ),
        "governed_receipt_sha256": bindings["governed_receipt_sha256"],
        "pagination_completeness_proven": False,
        "retrieval_completeness_status": "not_proven_by_crawler_telemetry",
        "vocs_sha256": bindings["vocs_sha256"],
    }
    profiles = {
        "source_selection_profile": source_selection,
        "coverage_profile": coverage,
        "retrieval_contract": retrieval,
    }
    hashes = {
        PROFILE_HASH_FIELDS[name]: _hash(profiles[name]) for name in PROFILE_NAMES
    }
    return profiles, hashes


def build_periodized_metrics_input(
    *,
    observations: Iterable[Mapping[str, object]],
    input_bindings: Mapping[str, str],
    dataset_id: str,
    metric_policy_version: str,
    scope: str,
    source_snapshot_id: str,
    coverage_attestation: Mapping[str, object] | None = None,
    coverage_attestation_sha256: str | None = None,
) -> dict[str, object]:
    rows = [dict(row) for row in observations]
    if not rows:
        raise PeriodizedMetricsError("periodized metrics require observations")
    if not isinstance(metric_policy_version, str) or not metric_policy_version:
        raise PeriodizedMetricsError("metric policy version is invalid")
    if not isinstance(scope, str) or not scope:
        raise PeriodizedMetricsError("metrics scope is invalid")
    dataset_id = _text(dataset_id, "dataset ID")
    source_snapshot_id = _text(source_snapshot_id, "source snapshot ID")
    by_id: dict[str, dict[str, object]] = {}
    dates: dict[str, date] = {}
    precision_counts: Counter[str] = Counter()
    for row in rows:
        member_id = row.get("metric_member_id")
        precision = row.get("event_time_precision")
        if not isinstance(member_id, str) or not member_id or member_id in by_id:
            raise PeriodizedMetricsError("periodized observation identity is invalid")
        if precision not in {"day", "instant", "hour"}:
            raise PeriodizedMetricsError("periodized time precision is invalid")
        by_id[member_id] = row
        dates[member_id] = _calendar_date(row)
        precision_counts[str(precision)] += 1
    min_observed = min(dates.values())
    max_observed = max(dates.values())
    if (coverage_attestation is None) != (coverage_attestation_sha256 is None):
        raise PeriodizedMetricsError("coverage attestation and SHA must be paired")
    attestation: dict[str, object] | None = None
    if coverage_attestation is not None:
        assert coverage_attestation_sha256 is not None
        attestation = validate_coverage_attestation(
            coverage_attestation,
            expected_sha256=coverage_attestation_sha256,
            dataset_id=dataset_id,
            source_snapshot_id=source_snapshot_id,
            scope=scope,
            min_observed_date=min_observed,
            max_observed_date=max_observed,
        )
    comparison_contract_proven = attestation is not None
    as_of_date = max_observed + timedelta(days=1)
    latest_windows = complete_period_windows(as_of_date)
    latest_ids = {
        grain: latest_windows[grain].current.period_id for grain in GRAINS
    }
    profiles, profile_hashes = _profiles(
        coverage_attestation_sha256=coverage_attestation_sha256,
        dataset_id=dataset_id,
        input_bindings=input_bindings,
        metric_policy_version=metric_policy_version,
        scope=scope,
        observation_count=len(rows),
        min_observed_date=min_observed,
        max_observed_date=max_observed,
        precision_counts=precision_counts,
        source_snapshot_id=source_snapshot_id,
    )

    grouped: dict[tuple[str, str], dict[str, object]] = {}
    for member_id, event_date in dates.items():
        observation = by_id[member_id]
        for grain in GRAINS:
            period_id, start, end = _period_window(grain, event_date)
            bucket = grouped.setdefault(
                (grain, period_id),
                {
                    "end_date": end.isoformat(),
                    "grain": grain,
                    "eligible_volume": 0,
                    "member_ids": [],
                    "period_id": period_id,
                    "start_date": start.isoformat(),
                    "time_precision_counts": Counter(),
                    "voc_type_counts": Counter(),
                },
            )
            bucket["member_ids"].append(member_id)
            bucket["eligible_volume"] += observation.get("metric_eligible") is True
            bucket["time_precision_counts"][str(observation["event_time_precision"])] += 1
            bucket["voc_type_counts"][str(observation.get("voc_type"))] += 1

    if comparison_contract_proven:
        for grain in GRAINS:
            for period_start in _iter_period_starts(grain, min_observed, max_observed):
                period_id, start, end = _period_window(grain, period_start)
                grouped.setdefault(
                    (grain, period_id),
                    {
                        "end_date": end.isoformat(),
                        "eligible_volume": 0,
                        "grain": grain,
                        "member_ids": [],
                        "period_id": period_id,
                        "start_date": start.isoformat(),
                        "time_precision_counts": Counter(),
                        "voc_type_counts": Counter(),
                    },
                )

    for grain in GRAINS:
        window = latest_windows[grain].current
        grouped.setdefault(
            (grain, window.period_id),
            {
                "end_date": window.end.isoformat(),
                "eligible_volume": 0,
                "grain": grain,
                "member_ids": [],
                "period_id": window.period_id,
                "start_date": window.start.isoformat(),
                "time_precision_counts": Counter(),
                "voc_type_counts": Counter(),
            },
        )

    periods: list[dict[str, object]] = []
    grain_order = {grain: index for index, grain in enumerate(GRAINS)}
    for bucket in sorted(
        grouped.values(),
        key=lambda value: (
            grain_order[str(value["grain"])],
            str(value["start_date"]),
        ),
    ):
        time_counts = dict(sorted(bucket["time_precision_counts"].items()))
        bucket_start = date.fromisoformat(str(bucket["start_date"]))
        bucket_end = date.fromisoformat(str(bucket["end_date"]))
        coverage_complete = bool(
            comparison_contract_proven
            and bucket_start >= min_observed
            and bucket_end <= as_of_date
        )
        periods.append(
            {
                "comparison_contract_proven": comparison_contract_proven,
                "coverage_complete": coverage_complete,
                "coverage_profile_hash": profile_hashes["coverage_profile_hash"],
                "data_owner_coverage_attestation_sha256": (
                    coverage_attestation_sha256
                ),
                "end_date": bucket["end_date"],
                "eligible_volume": int(bucket["eligible_volume"]),
                "grain": bucket["grain"],
                "is_latest_complete_period": (
                    bucket["period_id"] == latest_ids[str(bucket["grain"])]
                ),
                "member_ids": sorted(bucket["member_ids"]),
                "metric_policy_version": metric_policy_version,
                "period_id": bucket["period_id"],
                "retrieval_contract_hash": profile_hashes["retrieval_contract_hash"],
                "scope": scope,
                "source_selection_profile_hash": profile_hashes[
                    "source_selection_profile_hash"
                ],
                "start_date": bucket["start_date"],
                "observed_time_precision": _precision_label(time_counts),
                "time_precision": PERIOD_TIME_PRECISION[str(bucket["grain"])],
                "time_precision_counts": time_counts,
                "voc_type_counts": dict(sorted(bucket["voc_type_counts"].items())),
            }
        )
    document: dict[str, object] = {
        "as_of_date": as_of_date.isoformat(),
        "as_of_date_basis": "max_observed_calendar_date_plus_one",
        "boundaries": dict(EXPECTED_BOUNDARIES),
        "comparison_contract_basis": (
            "owner_attested_dataset_scope_window"
            if comparison_contract_proven
            else "not_owner_attested"
        ),
        "comparison_contract_proven": comparison_contract_proven,
        "comparison_unavailable_reason_codes": (
            [] if comparison_contract_proven else [UNATTESTED_REASON]
        ),
        "data_owner_coverage_attestation": attestation,
        "data_owner_coverage_attestation_sha256": coverage_attestation_sha256,
        "dataset_id": dataset_id,
        **profile_hashes,
        "latest_complete_period_ids": latest_ids,
        "metric_policy_version": metric_policy_version,
        "observation_count": len(rows),
        "periods": periods,
        "profiles": profiles,
        "report_comparison_policy": dict(REPORT_COMPARISON_POLICY),
        "schema_version": INPUT_SCHEMA_VERSION,
        "scope": scope,
        "source_snapshot_id": source_snapshot_id,
        "timezone": REPORTING_TIMEZONE,
    }
    validate_periodized_metrics_input(document)
    return document


def validate_periodized_metrics_input(value: Mapping[str, object]) -> None:
    if not isinstance(value, Mapping) or value.get("schema_version") != INPUT_SCHEMA_VERSION:
        raise PeriodizedMetricsError("periodized metrics input schema is invalid")
    if value.get("boundaries") != EXPECTED_BOUNDARIES:
        raise PeriodizedMetricsError("periodized metrics boundaries are invalid")
    if value.get("timezone") != REPORTING_TIMEZONE:
        raise PeriodizedMetricsError("periodized metrics timezone is invalid")
    if value.get("report_comparison_policy") != REPORT_COMPARISON_POLICY:
        raise PeriodizedMetricsError("report comparison policy is invalid")
    comparison_proven = value.get("comparison_contract_proven")
    if type(comparison_proven) is not bool:
        raise PeriodizedMetricsError("periodized comparison boundary is invalid")
    expected_reasons = [] if comparison_proven else [UNATTESTED_REASON]
    expected_basis = (
        "owner_attested_dataset_scope_window"
        if comparison_proven
        else "not_owner_attested"
    )
    if (
        value.get("comparison_unavailable_reason_codes") != expected_reasons
        or value.get("comparison_contract_basis") != expected_basis
    ):
        raise PeriodizedMetricsError("periodized comparison boundary is invalid")
    profiles = value.get("profiles")
    if not isinstance(profiles, Mapping) or set(profiles) != set(PROFILE_NAMES):
        raise PeriodizedMetricsError("periodized profiles are invalid")
    for name in PROFILE_NAMES:
        profile = profiles.get(name)
        if not isinstance(profile, Mapping):
            raise PeriodizedMetricsError("periodized profile is invalid")
        field = PROFILE_HASH_FIELDS[name]
        if value.get(field) != _hash(profile):
            raise PeriodizedMetricsError(f"profile hash mismatch:{name}")
    coverage_profile = profiles.get("coverage_profile")
    assert isinstance(coverage_profile, Mapping)
    dataset_id = _text(value.get("dataset_id"), "periodized dataset ID")
    source_snapshot_id = _text(
        value.get("source_snapshot_id"), "periodized source snapshot ID"
    )
    scope = _text(value.get("scope"), "periodized scope")
    try:
        min_observed = date.fromisoformat(
            _text(
                coverage_profile.get("min_observed_calendar_date"),
                "minimum observed calendar date",
            )
        )
        max_observed = date.fromisoformat(
            _text(
                coverage_profile.get("max_observed_calendar_date"),
                "maximum observed calendar date",
            )
        )
    except ValueError as exc:
        raise PeriodizedMetricsError("coverage profile dates are invalid") from exc
    attestation = value.get("data_owner_coverage_attestation")
    attestation_sha = value.get("data_owner_coverage_attestation_sha256")
    if comparison_proven:
        if not isinstance(attestation, Mapping) or not isinstance(attestation_sha, str):
            raise PeriodizedMetricsError("coverage attestation is missing")
        validate_coverage_attestation(
            attestation,
            expected_sha256=attestation_sha,
            dataset_id=dataset_id,
            source_snapshot_id=source_snapshot_id,
            scope=scope,
            min_observed_date=min_observed,
            max_observed_date=max_observed,
        )
    elif attestation is not None or attestation_sha is not None:
        raise PeriodizedMetricsError("unattested comparison carries an attestation")
    if (
        coverage_profile.get("collection_completeness_proven") is not comparison_proven
        or coverage_profile.get("data_owner_coverage_attestation_sha256")
        != attestation_sha
        or coverage_profile.get("dataset_id") != dataset_id
        or coverage_profile.get("source_snapshot_id") != source_snapshot_id
        or coverage_profile.get("scope") != scope
    ):
        raise PeriodizedMetricsError("coverage profile attestation binding mismatch")
    observation_count = value.get("observation_count")
    if type(observation_count) is not int or observation_count <= 0:
        raise PeriodizedMetricsError("periodized observation count is invalid")
    latest = value.get("latest_complete_period_ids")
    periods = value.get("periods")
    if not isinstance(latest, Mapping) or set(latest) != set(GRAINS):
        raise PeriodizedMetricsError("latest period IDs are invalid")
    if not isinstance(periods, list) or not periods:
        raise PeriodizedMetricsError("periodized periods are invalid")
    seen_periods: set[tuple[str, str]] = set()
    members_by_grain: dict[str, set[str]] = {grain: set() for grain in GRAINS}
    latest_seen = {grain: 0 for grain in GRAINS}
    for row in periods:
        if not isinstance(row, Mapping):
            raise PeriodizedMetricsError("periodized period row is invalid")
        grain = row.get("grain")
        period_id = row.get("period_id")
        member_ids = row.get("member_ids")
        if grain not in GRAINS or not isinstance(period_id, str):
            raise PeriodizedMetricsError("periodized period identity is invalid")
        key = (str(grain), period_id)
        if key in seen_periods:
            raise PeriodizedMetricsError("duplicate periodized period")
        seen_periods.add(key)
        if not isinstance(member_ids, list) or member_ids != sorted(set(member_ids)):
            raise PeriodizedMetricsError("periodized member IDs are invalid")
        eligible_volume = row.get("eligible_volume")
        if (
            type(eligible_volume) is not int
            or eligible_volume < 0
            or eligible_volume > len(member_ids)
        ):
            raise PeriodizedMetricsError("periodized eligible volume is invalid")
        if members_by_grain[str(grain)] & set(member_ids):
            raise PeriodizedMetricsError("periodized member appears twice in a grain")
        members_by_grain[str(grain)].update(member_ids)
        for field in PROFILE_HASH_FIELDS.values():
            if row.get(field) != value.get(field):
                raise PeriodizedMetricsError("period profile hash binding mismatch")
        if (
            row.get("comparison_contract_proven") is not comparison_proven
            or row.get("data_owner_coverage_attestation_sha256") != attestation_sha
        ):
            raise PeriodizedMetricsError("period comparison binding mismatch")
        if row.get("metric_policy_version") != value.get("metric_policy_version"):
            raise PeriodizedMetricsError("period metric policy mismatch")
        if row.get("scope") != value.get("scope"):
            raise PeriodizedMetricsError("period scope mismatch")
        if row.get("time_precision") != PERIOD_TIME_PRECISION[str(grain)]:
            raise PeriodizedMetricsError("period time assignment contract mismatch")
        if row.get("observed_time_precision") not in {
            "day",
            "hour",
            "instant",
            "instant_or_hour",
            "mixed",
            "unobserved",
        }:
            raise PeriodizedMetricsError("observed time precision is invalid")
        expected_latest = period_id == latest[str(grain)]
        if row.get("is_latest_complete_period") is not expected_latest:
            raise PeriodizedMetricsError("latest period marker mismatch")
        latest_seen[str(grain)] += expected_latest
        try:
            start_date = date.fromisoformat(_text(row.get("start_date"), "period start"))
            end_date = date.fromisoformat(_text(row.get("end_date"), "period end"))
        except ValueError as exc:
            raise PeriodizedMetricsError("period window is invalid") from exc
        expected_complete = bool(
            comparison_proven
            and start_date >= min_observed
            and end_date <= max_observed + timedelta(days=1)
        )
        if row.get("coverage_complete") is not expected_complete:
            raise PeriodizedMetricsError("period completeness marker mismatch")
    if any(len(members) != observation_count for members in members_by_grain.values()):
        raise PeriodizedMetricsError("periodized observation conservation mismatch")
    if any(count != 1 for count in latest_seen.values()):
        raise PeriodizedMetricsError("latest complete period is not unique")
    if comparison_proven:
        for grain in GRAINS:
            expected_ids = {
                _period_window(grain, start)[0]
                for start in _iter_period_starts(grain, min_observed, max_observed)
            }
            expected_ids.add(str(latest[grain]))
            actual_ids = {
                str(row["period_id"])
                for row in periods
                if row.get("grain") == grain
            }
            if actual_ids != expected_ids:
                raise PeriodizedMetricsError("attested period sequence is not contiguous")


def _acceleration_context(
    periodized: Mapping[str, object], descriptor: Mapping[str, object]
) -> dict[str, object]:
    grain = str(descriptor["grain"])
    current_end = str(descriptor["end_date"])
    complete = [
        row
        for row in periodized["periods"]
        if isinstance(row, Mapping)
        and row.get("grain") == grain
        and row.get("coverage_complete") is True
        and str(row.get("end_date")) <= current_end
    ]
    complete.sort(key=lambda row: str(row["start_date"]))
    rows = []
    for row in complete[-3:]:
        rows.append(
            {
                "complete": True,
                "coverage_profile_hash": row["coverage_profile_hash"],
                "eligible_volume": row["eligible_volume"],
                "grain": grain,
                "metric_policy_version": row["metric_policy_version"],
                "period": row["period_id"],
                "retrieval_contract_hash": row["retrieval_contract_hash"],
                "scope": row["scope"],
                "source_selection_profile_hash": row[
                    "source_selection_profile_hash"
                ],
                "unit": "count",
            }
        )
    return {
        "comparison_contract_proven": periodized[
            "comparison_contract_proven"
        ],
        "complete_periods": rows,
        "current_period_complete": descriptor["coverage_complete"],
        "grain": grain,
        "metric_policy_version": periodized["metric_policy_version"],
        "scope": periodized["scope"],
    }


def latest_acceleration_context(
    periodized: Mapping[str, object], *, grain: str = "monthly"
) -> dict[str, object]:
    validate_periodized_metrics_input(periodized)
    if grain not in GRAINS:
        raise PeriodizedMetricsError("acceleration grain is invalid")
    latest = periodized["latest_complete_period_ids"]
    assert isinstance(latest, Mapping)
    descriptor = next(
        (
            row
            for row in periodized["periods"]
            if isinstance(row, Mapping)
            and row.get("grain") == grain
            and row.get("period_id") == latest[grain]
        ),
        None,
    )
    if not isinstance(descriptor, Mapping):
        raise PeriodizedMetricsError("latest acceleration period is missing")
    return _acceleration_context(periodized, descriptor)


def _period_context(
    source: Mapping[str, object],
    member_ids: set[str],
    *,
    descriptor: Mapping[str, object],
    periodized: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    raw_context = source.get("context")
    if not isinstance(raw_context, Mapping):
        raise PeriodizedMetricsError("metrics context is invalid")
    result: dict[str, dict[str, object]] = {}
    for key, raw in raw_context.items():
        if not isinstance(key, str) or not isinstance(raw, Mapping):
            raise PeriodizedMetricsError("indicator context is invalid")
        result[key] = dict(raw)
    unavailable = {
        "coverage_status": "unavailable",
        "reason_codes": ["periodized_audit_time_contract_unavailable"],
    }
    result["RV-DH-01"] = dict(unavailable)
    result["RV-DH-02"] = dict(unavailable)
    result["RV-CI-01"] = {
        "coverage_status": "unavailable",
        "reason_codes": ["periodized_automation_time_contract_unavailable"],
    }
    commercial = result.get("RV-CI-02", {}).get("commercial_audit_rows", [])
    if not isinstance(commercial, list):
        raise PeriodizedMetricsError("commercial audit rows are invalid")
    result["RV-CI-02"] = {
        "commercial_audit_rows": [
            dict(row)
            for row in commercial
            if isinstance(row, Mapping)
            and row.get("metric_member_id") in member_ids
        ]
    }
    result["RV-IN-05"] = _acceleration_context(periodized, descriptor)
    return result


def _activity_counts(
    observations: Sequence[Mapping[str, object]],
    *,
    post_by_thread: Mapping[str, Mapping[str, object]],
    start: date,
    end: date,
    brand: str | None,
) -> dict[str, object]:
    scoped = [
        row
        for row in observations
        if brand is None or row.get("brand") == brand
    ]
    posts = [row for row in scoped if row.get("voc_type") == "post_voc"]
    comments = [
        row for row in scoped if row.get("voc_type") == "comment_context_voc"
    ]
    current_post_comments = 0
    historical_post_comments = 0
    unresolved_parent_comments = 0
    active_historical_threads: set[str] = set()
    for comment in comments:
        thread_id = comment.get("thread_id")
        parent = post_by_thread.get(str(thread_id)) if thread_id else None
        if parent is None:
            unresolved_parent_comments += 1
            continue
        parent_date = _calendar_date(parent)
        if parent_date < start:
            historical_post_comments += 1
            active_historical_threads.add(str(thread_id))
        elif parent_date < end:
            current_post_comments += 1
        else:
            raise PeriodizedMetricsError(
                "comment activity parent post is outside the current or historical period"
            )
    if (
        current_post_comments
        + historical_post_comments
        + unresolved_parent_comments
        != len(comments)
    ):
        raise PeriodizedMetricsError("comment activity conservation mismatch")
    return {
        "active_historical_post_count": len(active_historical_threads),
        "comments_on_current_period_posts": current_post_comments,
        "comments_on_historical_posts": historical_post_comments,
        "new_comment_count": len(comments),
        "new_post_count": len(posts),
        "unresolved_parent_comment_count": unresolved_parent_comments,
    }


def _period_activity_row(
    observations: Sequence[Mapping[str, object]],
    *,
    descriptor: Mapping[str, object],
    periodized: Mapping[str, object],
    post_by_thread: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    start = date.fromisoformat(str(descriptor["start_date"]))
    end = date.fromisoformat(str(descriptor["end_date"]))
    return {
        "all_observed": _activity_counts(
            observations,
            post_by_thread=post_by_thread,
            start=start,
            end=end,
            brand=None,
        ),
        "comparison_contract_proven": periodized["comparison_contract_proven"],
        "coverage_profile_hash": periodized["coverage_profile_hash"],
        "data_owner_coverage_attestation_sha256": periodized[
            "data_owner_coverage_attestation_sha256"
        ],
        "grain": descriptor["grain"],
        "momcozy": _activity_counts(
            observations,
            post_by_thread=post_by_thread,
            start=start,
            end=end,
            brand="momcozy",
        ),
        "period_complete": descriptor["coverage_complete"],
        "period_id": descriptor["period_id"],
        "retrieval_contract_hash": periodized["retrieval_contract_hash"],
        "scope_contract": {
            "all_observed": "canonical_observation_pool",
            "momcozy": "governed_brand_fact_equals_momcozy",
        },
        "source_calendar_date": descriptor["start_date"],
        "source_selection_profile_hash": periodized[
            "source_selection_profile_hash"
        ],
        "time_precision": descriptor["time_precision"],
    }


def build_periodized_metrics_candidate(
    source: Mapping[str, object], *, registry: IndicatorRegistry
) -> dict[str, object]:
    if not isinstance(source, Mapping):
        raise PeriodizedMetricsError("metrics source is invalid")
    periodized = source.get("periodized_metrics_input")
    if not isinstance(periodized, Mapping):
        raise PeriodizedMetricsError("periodized metrics input is missing")
    validate_periodized_metrics_input(periodized)
    observations = source.get("observations")
    atomic_facts = source.get("atomic_facts")
    eligibility = source.get("eligibility_rows")
    if not isinstance(observations, list) or not isinstance(atomic_facts, list):
        raise PeriodizedMetricsError("periodized metrics source rows are invalid")
    if not isinstance(eligibility, list):
        raise PeriodizedMetricsError("periodized eligibility is invalid")
    observation_by_id = {
        str(row.get("metric_member_id")): dict(row)
        for row in observations
        if isinstance(row, Mapping)
    }
    if len(observation_by_id) != len(observations):
        raise PeriodizedMetricsError("periodized observation identity mismatch")
    post_by_thread: dict[str, dict[str, object]] = {}
    for observation in observation_by_id.values():
        if observation.get("voc_type") != "post_voc":
            continue
        member_id = str(observation["metric_member_id"])
        thread_id = observation.get("thread_id")
        if thread_id is None and member_id.startswith("t3_"):
            thread_id = member_id.removeprefix("t3_")
        if not isinstance(thread_id, str) or not thread_id or thread_id in post_by_thread:
            raise PeriodizedMetricsError("periodized post thread identity is invalid")
        post_by_thread[thread_id] = observation
    facts_by_entity: dict[str, list[dict[str, object]]] = defaultdict(list)
    for raw in atomic_facts:
        if not isinstance(raw, Mapping) or not isinstance(
            raw.get("canonical_entity_id"), str
        ):
            raise PeriodizedMetricsError("periodized atomic fact is invalid")
        facts_by_entity[str(raw["canonical_entity_id"])].append(dict(raw))
    eligibility_by_member: dict[str, list[dict[str, object]]] = defaultdict(list)
    for raw in eligibility:
        if not isinstance(raw, Mapping) or not isinstance(
            raw.get("metric_member_id"), str
        ):
            raise PeriodizedMetricsError("periodized eligibility row is invalid")
        eligibility_by_member[str(raw["metric_member_id"])].append(dict(raw))

    rows: list[dict[str, object]] = []
    health_rows: list[dict[str, object]] = []
    health_dimension_rows: list[dict[str, object]] = []
    activity_rows: list[dict[str, object]] = []
    for descriptor in periodized["periods"]:
        assert isinstance(descriptor, Mapping)
        period_id = str(descriptor["period_id"])
        member_ids = set(descriptor["member_ids"])
        period_observations = [
            observation_by_id[member_id] for member_id in sorted(member_ids)
        ]
        period_facts = [
            fact
            for member_id in sorted(member_ids)
            for fact in facts_by_entity.get(member_id, [])
        ]
        period_eligibility = []
        for member_id in sorted(member_ids):
            for source_row in eligibility_by_member.get(member_id, []):
                row = dict(source_row)
                row["period"] = period_id
                row["scope"] = source["scope"]
                period_eligibility.append(row)
        activity_rows.append(
            _period_activity_row(
                period_observations,
                descriptor=descriptor,
                periodized=periodized,
                post_by_thread=post_by_thread,
            )
        )
        context = _period_context(
            source,
            member_ids,
            descriptor=descriptor,
            periodized=periodized,
        )
        for definition in registry.indicators:
            stable_voc_type = PERIOD_VOC_TYPE_BY_MEMBER_TYPE.get(
                definition.metric_member_type
            )
            if stable_voc_type is None:
                raise PeriodizedMetricsError(
                    "period VOC type contract is missing for metric member type"
                )
            indicator_context = context.get(definition.reddit_indicator_id, {})
            result = compute_indicator(
                definition.reddit_indicator_id,
                period_observations,
                registry=registry,
                comparison_side=definition.default_comparison_side,
                period=period_id,
                scope=str(source["scope"]),
                eligibility_rows=(period_eligibility if eligibility else None),
                atomic_facts=period_facts,
                context=indicator_context,
                decimal_places=2,
            ).as_dict()
            rows.append(
                {
                    "comparison_contract_proven": periodized[
                        "comparison_contract_proven"
                    ],
                    "coverage_profile_hash": periodized["coverage_profile_hash"],
                    "data_owner_coverage_attestation_sha256": periodized[
                        "data_owner_coverage_attestation_sha256"
                    ],
                    "evidence_ids": result["evidence_fact_ids"],
                    "grain": descriptor["grain"],
                    "metric_id": definition.reddit_indicator_id,
                    "metric_policy_version": registry.registry_version,
                    "name_cn": definition.name_cn,
                    "observed_voc_type": (
                        "+".join(result["voc_types"]) or "none"
                    ),
                    "observed_time_precision": descriptor[
                        "observed_time_precision"
                    ],
                    "period_complete": descriptor["coverage_complete"],
                    "period_id": period_id,
                    "retrieval_contract_hash": periodized[
                        "retrieval_contract_hash"
                    ],
                    "scope": source["scope"],
                    "source_calendar_date": descriptor["start_date"],
                    "source_selection_profile_hash": periodized[
                        "source_selection_profile_hash"
                    ],
                    "status": result["status"],
                    "time_precision": descriptor["time_precision"],
                    "unavailable_reason_codes": result[
                        "unavailable_reason_codes"
                    ],
                    "unit": result["unit"],
                    "value": result["value"],
                    "voc_type": stable_voc_type,
                }
            )
        health = compute_brand_health(
            period_observations,
            atomic_facts=period_facts,
            period=period_id,
            scope="momcozy",
            decimal_places=2,
        ).as_dict()
        for side in ("raw_observed", "qualified_organic"):
            total = health[side]["total"]
            health_rows.append(
                {
                    "comparison_contract_proven": periodized[
                        "comparison_contract_proven"
                    ],
                    "comparison_side": side,
                    "coverage_profile_hash": periodized["coverage_profile_hash"],
                    "data_owner_coverage_attestation_sha256": periodized[
                        "data_owner_coverage_attestation_sha256"
                    ],
                    "grain": descriptor["grain"],
                    "metric_id": "brand_health_index_v2",
                    "metric_policy_version": registry.registry_version,
                    "observed_time_precision": descriptor[
                        "observed_time_precision"
                    ],
                    "period_complete": descriptor["coverage_complete"],
                    "period_id": period_id,
                    "retrieval_contract_hash": periodized[
                        "retrieval_contract_hash"
                    ],
                    "scope": "momcozy",
                    "source_calendar_date": descriptor["start_date"],
                    "source_selection_profile_hash": periodized[
                        "source_selection_profile_hash"
                    ],
                    "status": total["status"],
                    "time_precision": descriptor["time_precision"],
                    "unavailable_reason_codes": total["reason_codes"],
                    "unit": "index",
                    "value": total["value"],
                    "voc_type": "post_voc+comment_context_voc",
                }
            )
            dimensions = health[side]["dimensions"]
            for dimension_id in BRAND_HEALTH_DIMENSIONS:
                dimension = dimensions[dimension_id]
                dimension_value = dimension["value"]
                contribution = (
                    None
                    if dimension_value is None
                    else format(
                        (Decimal(str(dimension_value)) / Decimal(4)).quantize(
                            Decimal("0.01"), rounding=ROUND_HALF_UP
                        ),
                        "f",
                    )
                )
                health_dimension_rows.append(
                    {
                        "comparison_contract_proven": periodized[
                            "comparison_contract_proven"
                        ],
                        "comparison_side": side,
                        "contribution_points": contribution,
                        "coverage_profile_hash": periodized[
                            "coverage_profile_hash"
                        ],
                        "data_owner_coverage_attestation_sha256": periodized[
                            "data_owner_coverage_attestation_sha256"
                        ],
                        "dimension_id": dimension_id,
                        "dimension_value": dimension_value,
                        "grain": descriptor["grain"],
                        "metric_id": "brand_health_dimension_contribution_v1",
                        "metric_policy_version": registry.registry_version,
                        "observed_time_precision": descriptor[
                            "observed_time_precision"
                        ],
                        "period_complete": descriptor["coverage_complete"],
                        "period_id": period_id,
                        "retrieval_contract_hash": periodized[
                            "retrieval_contract_hash"
                        ],
                        "scope": "momcozy",
                        "source_calendar_date": descriptor["start_date"],
                        "source_selection_profile_hash": periodized[
                            "source_selection_profile_hash"
                        ],
                        "status": dimension["status"],
                        "time_precision": descriptor["time_precision"],
                        "unavailable_reason_codes": dimension["reason_codes"],
                        "unit": "index_points",
                        "voc_type": "post_voc+comment_context_voc",
                        "weight_percent": "25.00",
                    }
                )
    attestation = periodized["data_owner_coverage_attestation"]
    coverage_attestation_summary = None
    if isinstance(attestation, Mapping):
        coverage_attestation_summary = {
            "attestation_basis": attestation["attestation_basis"],
            "completeness_percent": attestation["completeness_percent"],
            "coverage_window": dict(attestation["coverage_window"]),
            "evidence_class": attestation["evidence_class"],
            "scope": attestation["scope"],
            "source_snapshot_id": attestation["source_snapshot_id"],
        }
    return {
        "activity_row_count": len(activity_rows),
        "activity_rows": activity_rows,
        "boundaries": dict(EXPECTED_BOUNDARIES),
        "brand_health_row_count": len(health_rows),
        "brand_health_rows": health_rows,
        "brand_health_dimension_row_count": len(health_dimension_rows),
        "brand_health_dimension_rows": health_dimension_rows,
        "comparison_contract_basis": periodized["comparison_contract_basis"],
        "comparison_contract_proven": periodized["comparison_contract_proven"],
        "comparison_unavailable_reason_codes": list(
            periodized["comparison_unavailable_reason_codes"]
        ),
        "contract_extensions": [
            BRAND_HEALTH_DIMENSION_EXTENSION,
            PERIOD_ACTIVITY_EXTENSION,
        ],
        "coverage_profile_hash": periodized["coverage_profile_hash"],
        "coverage_attestation": coverage_attestation_summary,
        "data_owner_coverage_attestation_sha256": periodized[
            "data_owner_coverage_attestation_sha256"
        ],
        "latest_complete_period_ids": dict(
            periodized["latest_complete_period_ids"]
        ),
        "metric_row_count": len(rows),
        "period_count": len(periodized["periods"]),
        "registry_version": registry.registry_version,
        "retrieval_contract_hash": periodized["retrieval_contract_hash"],
        "report_comparison_policy": dict(periodized["report_comparison_policy"]),
        "rows": rows,
        "schema_version": CANDIDATE_SCHEMA_VERSION,
        "source_selection_profile_hash": periodized[
            "source_selection_profile_hash"
        ],
        "timezone": REPORTING_TIMEZONE,
    }
