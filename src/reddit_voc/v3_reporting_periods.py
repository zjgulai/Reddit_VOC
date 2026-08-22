"""Calendar-exact reporting periods and precomputed comparison contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo


DISPLAY_TIMEZONE = "Asia/Shanghai"
COMPARABLE_STATUSES = frozenset({"available", "provisional"})
OBSERVED_COMPARISON_REASON = "owner_attestation_missing_observed_same_profile"
PROFILE_KEYS = (
    "source_selection_profile_hash",
    "coverage_profile_hash",
    "retrieval_contract_hash",
)
CONTRACT_KEYS = (
    "metric_policy_version",
    "scope",
    "voc_type",
    "time_precision",
    "unit",
)


class ReportingPeriodError(ValueError):
    """A period, series point, or comparison is not governed."""


@dataclass(frozen=True)
class PeriodWindow:
    period_id: str
    grain: str
    start: date
    end: date
    is_complete: bool = True


@dataclass(frozen=True)
class PeriodComparisonWindows:
    current: PeriodWindow
    previous: PeriodWindow
    year_over_year: PeriodWindow | None
    entry_label: str = "最新完整周期"


@dataclass(frozen=True)
class ComparisonResult:
    value: str | None
    display: str
    unit: str
    status: str
    direction: str | None
    line_color: str
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class SparklineResult:
    points: tuple[tuple[str, str | None], ...]
    status: str
    direction: str | None
    line_color: str
    trend_claim_supported: bool
    reason_codes: tuple[str, ...]


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _shift_month(value: date, offset: int) -> date:
    index = value.year * 12 + value.month - 1 + offset
    return date(index // 12, index % 12 + 1, 1)


def _window(grain: str, start: date, end: date) -> PeriodWindow:
    return PeriodWindow(
        period_id=f"{grain}:{start.isoformat()}:{end.isoformat()}",
        grain=grain,
        start=start,
        end=end,
    )


def _same_iso_week_previous_year(start: date) -> PeriodWindow | None:
    iso = start.isocalendar()
    try:
        prior = date.fromisocalendar(iso.year - 1, iso.week, 1)
    except ValueError:
        return None
    return _window("weekly", prior, prior + timedelta(days=7))


def complete_period_windows(as_of_date: date) -> dict[str, PeriodComparisonWindows]:
    """Return the latest complete calendar day, ISO week and month.

    ``as_of_date`` is the first not-yet-closed local calendar day.  All
    boundaries remain floating dates; no midnight timezone is fabricated.
    """
    if not isinstance(as_of_date, date) or isinstance(as_of_date, datetime):
        raise ReportingPeriodError("as-of date must be a floating calendar date")

    day_end = as_of_date
    day_start = day_end - timedelta(days=1)
    day_previous = day_start - timedelta(days=1)
    try:
        day_yoy = date(day_start.year - 1, day_start.month, day_start.day)
    except ValueError:
        day_yoy = None

    current_week_start = as_of_date - timedelta(days=as_of_date.weekday())
    week_start = current_week_start - timedelta(days=7)
    prior_week_start = week_start - timedelta(days=7)

    current_month_start = _month_start(as_of_date)
    month_start = _shift_month(current_month_start, -1)
    previous_month_start = _shift_month(month_start, -1)
    yoy_month_start = date(month_start.year - 1, month_start.month, 1)

    return {
        "daily": PeriodComparisonWindows(
            current=_window("daily", day_start, day_end),
            previous=_window("daily", day_previous, day_start),
            year_over_year=(
                _window("daily", day_yoy, day_yoy + timedelta(days=1))
                if day_yoy is not None
                else None
            ),
        ),
        "weekly": PeriodComparisonWindows(
            current=_window(
                "weekly", week_start, week_start + timedelta(days=7)
            ),
            previous=_window(
                "weekly", prior_week_start, week_start
            ),
            year_over_year=_same_iso_week_previous_year(week_start),
        ),
        "monthly": PeriodComparisonWindows(
            current=_window("monthly", month_start, current_month_start),
            previous=_window("monthly", previous_month_start, month_start),
            year_over_year=_window(
                "monthly", yoy_month_start, _shift_month(yoy_month_start, 1)
            ),
        ),
    }


def format_series_label(
    value: str,
    *,
    grain: str,
    timezone: str = DISPLAY_TIMEZONE,
) -> str:
    if not isinstance(value, str) or not value:
        raise ReportingPeriodError("series value must be a non-empty string")
    if grain in {"instant", "hour"}:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            target = ZoneInfo(timezone)
        except (ValueError, TypeError) as exc:
            raise ReportingPeriodError("instant series value is invalid") from exc
        if parsed.tzinfo is None:
            raise ReportingPeriodError("instant series value must include a timezone")
        local = parsed.astimezone(target)
        return local.strftime("%H:%M" if grain == "hour" else "%m-%d %H:%M")
    if grain in {"day", "week"}:
        try:
            parsed_date = date.fromisoformat(value)
        except ValueError as exc:
            raise ReportingPeriodError("floating series date is invalid") from exc
        return parsed_date.strftime("%m-%d")
    if grain == "month":
        if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value) is None:
            raise ReportingPeriodError("floating series month is invalid")
        return value
    raise ReportingPeriodError("series grain is unsupported")


def _decimal(value: object, label: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ReportingPeriodError(f"{label} is unavailable")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ReportingPeriodError(f"{label} is invalid") from exc
    if not parsed.is_finite():
        raise ReportingPeriodError(f"{label} is invalid")
    return parsed


def _format_decimal(value: Decimal, places: str = "0.1") -> str:
    quantized = value.quantize(Decimal(places), rounding=ROUND_HALF_UP)
    rendered = format(quantized, "f").rstrip("0").rstrip(".")
    return "0" if rendered in {"", "-0"} else rendered


def _unavailable(reasons: Iterable[str], *, unit: str = "unavailable") -> ComparisonResult:
    return ComparisonResult(
        value=None,
        display="—",
        unit=unit,
        status="unavailable",
        direction=None,
        line_color="gray",
        reason_codes=tuple(sorted(set(reasons))),
    )


def compare_periods(
    current: Mapping[str, object], baseline: Mapping[str, object]
) -> ComparisonResult:
    if not isinstance(current, Mapping) or not isinstance(baseline, Mapping):
        raise ReportingPeriodError("comparison inputs must be objects")
    reasons: list[str] = []
    provisional_reasons: list[str] = []
    for key in PROFILE_KEYS:
        left = current.get(key)
        right = baseline.get(key)
        if not isinstance(left, str) or not left or not isinstance(right, str) or not right:
            reasons.append(f"{key}_missing")
        elif left != right:
            reasons.append(f"{key}_mismatch")
    for key in CONTRACT_KEYS:
        if current.get(key) != baseline.get(key):
            reasons.append(f"{key}_mismatch")
    if current.get("status") not in COMPARABLE_STATUSES:
        reasons.append("current_value_unavailable")
    elif current.get("status") == "provisional":
        provisional_reasons.append("current_value_provisional")
    if baseline.get("status") not in COMPARABLE_STATUSES:
        reasons.append("baseline_value_unavailable")
    elif baseline.get("status") == "provisional":
        provisional_reasons.append("baseline_value_provisional")
    observed_same_profile = (
        current.get("comparison_contract_proven") is not True
        or baseline.get("comparison_contract_proven") is not True
    )
    if observed_same_profile:
        # Owner attestation proves coverage completeness, not whether two
        # already-observed scalar rows with identical governed profiles can be
        # arithmetically compared.  Keep the number visible as provisional and
        # retain an explicit evidence boundary instead of manufacturing 100%
        # completeness or a formal market-trend claim.
        provisional_reasons.append(OBSERVED_COMPARISON_REASON)
    unit = str(current.get("unit") or "unavailable")
    if current.get("value") is None:
        reasons.append("current_value_missing")
    if baseline.get("value") is None:
        reasons.append("baseline_value_missing")
    if reasons:
        return _unavailable(reasons, unit=unit)

    current_value = _decimal(current.get("value"), "current value")
    baseline_value = _decimal(baseline.get("value"), "baseline value")
    if unit in {"count", "ratio"}:
        if baseline_value == 0:
            return _unavailable(
                ("baseline_zero_relative_change_undefined",), unit="percent"
            )
        result = (current_value - baseline_value) / abs(baseline_value) * 100
        output_unit = "percent"
        suffix = "%"
    elif unit in {"share", "rate", "proportion"}:
        result = (current_value - baseline_value) * 100
        output_unit = "percentage_points"
        suffix = " pp"
    elif unit in {"percent", "pp"}:
        result = current_value - baseline_value
        output_unit = "percentage_points"
        suffix = " pp"
    elif unit in {"score", "index", "score_points", "log_delta2"}:
        result = current_value - baseline_value
        output_unit = "score_points"
        suffix = " points"
    else:
        raise ReportingPeriodError("comparison unit is unsupported")
    direction = "up" if result > 0 else "down" if result < 0 else "flat"
    line_color = (
        "blue"
        if observed_same_profile
        else "red"
        if direction == "up"
        else "green"
        if direction == "down"
        else "gray"
    )
    value = _format_decimal(result)
    sign = "+" if result > 0 else ""
    return ComparisonResult(
        value=value,
        display=f"{sign}{value}{suffix}",
        unit=output_unit,
        status="provisional" if provisional_reasons else "available",
        direction=direction,
        line_color=line_color,
        reason_codes=tuple(sorted(set(provisional_reasons))),
    )


def build_sparkline(
    values: Iterable[tuple[str, object]],
) -> SparklineResult:
    points: list[tuple[str, str | None]] = []
    finite: list[Decimal] = []
    max_contiguous = 0
    contiguous = 0
    for label, raw in values:
        if not isinstance(label, str) or not label:
            raise ReportingPeriodError("sparkline label is invalid")
        if raw is None:
            points.append((label, None))
            max_contiguous = max(max_contiguous, contiguous)
            contiguous = 0
            continue
        value = _decimal(raw, "sparkline value")
        rendered = format(value, "f")
        points.append((label, rendered))
        finite.append(value)
        contiguous += 1
    max_contiguous = max(max_contiguous, contiguous)
    if len(finite) < 2:
        return SparklineResult(
            points=tuple(points),
            status="unavailable",
            direction=None,
            line_color="gray",
            trend_claim_supported=False,
            reason_codes=("fewer_than_two_finite_points",),
        )
    delta = finite[-1] - finite[0]
    direction = "up" if delta > 0 else "down" if delta < 0 else "flat"
    return SparklineResult(
        points=tuple(points),
        status="available",
        direction=direction,
        line_color="red" if direction == "up" else "green" if direction == "down" else "gray",
        trend_claim_supported=max_contiguous >= 3,
        reason_codes=() if max_contiguous >= 3 else ("fewer_than_three_contiguous_complete_periods",),
    )
