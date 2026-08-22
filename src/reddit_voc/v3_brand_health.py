"""Momcozy observed-sample brand health index V2.

Posts and comment-context VOCs are scored separately and then weighted 50/50.
Integrity suspicion is never an extra penalty: the qualified view only removes
entities with the conjunction of manual confirmation, C3+ and I4.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Iterable, Mapping

from reddit_voc.v3_indicators import (
    IndicatorComputationError,
    compute_indicator,
)


BRAND_HEALTH_SCHEMA_VERSION = "reddit_voc_brand_health_index_v2"
BRAND_HEALTH_VERSION = "brand_health_index_v2"
DIMENSIONS = (
    "reputation",
    "product_experience",
    "recommendation_trust",
    "risk_resilience",
)
GRAINS = ("post_voc", "comment_context_voc")


class BrandHealthError(ValueError):
    """Brand-health inputs or invariants are invalid."""


def _round(value: Decimal, decimal_places: int) -> Decimal:
    if type(decimal_places) is not int or not 0 <= decimal_places <= 12:
        raise BrandHealthError("decimal_places is invalid")
    return value.quantize(
        Decimal(1).scaleb(-decimal_places), rounding=ROUND_HALF_UP
    )


def _serialized(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


@dataclass(frozen=True)
class BrandHealthScore:
    value: Decimal | None
    status: str
    candidate_count: int
    classified_count: int
    coverage_rate: Decimal | None
    denominator_count: int
    numerator: Decimal
    denominator_member_ids: tuple[str, ...]
    numerator_member_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    _exact_value: Decimal | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate_count": self.candidate_count,
            "classified_count": self.classified_count,
            "coverage_rate": _serialized(self.coverage_rate),
            "denominator_count": self.denominator_count,
            "denominator_member_ids": list(self.denominator_member_ids),
            "numerator": _serialized(self.numerator),
            "numerator_member_ids": list(self.numerator_member_ids),
            "reason_codes": list(self.reason_codes),
            "status": self.status,
            "value": _serialized(self.value),
        }


@dataclass(frozen=True)
class BrandHealthDimension:
    dimension_id: str
    value: Decimal | None
    status: str
    grain_scores: dict[str, BrandHealthScore]
    reason_codes: tuple[str, ...]
    _exact_value: Decimal | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "dimension_id": self.dimension_id,
            "grain_scores": {
                grain: self.grain_scores[grain].as_dict() for grain in GRAINS
            },
            "reason_codes": list(self.reason_codes),
            "status": self.status,
            "value": _serialized(self.value),
        }


@dataclass(frozen=True)
class BrandHealthVariant:
    comparison_side: str
    total: BrandHealthScore
    dimensions: dict[str, BrandHealthDimension]
    included_entity_ids: tuple[str, ...]
    excluded_entity_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "comparison_side": self.comparison_side,
            "dimensions": {
                name: self.dimensions[name].as_dict() for name in DIMENSIONS
            },
            "excluded_entity_ids": list(self.excluded_entity_ids),
            "included_entity_ids": list(self.included_entity_ids),
            "total": self.total.as_dict(),
        }


@dataclass(frozen=True)
class BrandHealthResult:
    raw: BrandHealthVariant
    qualified: BrandHealthVariant
    sensitivity_difference: Decimal | None
    period: str
    scope: str
    decimal_places: int
    index_version: str = BRAND_HEALTH_VERSION
    schema_version: str = BRAND_HEALTH_SCHEMA_VERSION

    def as_dict(self) -> dict[str, object]:
        return {
            "decimal_places": self.decimal_places,
            "index_version": self.index_version,
            "period": self.period,
            "qualified_organic": self.qualified.as_dict(),
            "raw_observed": self.raw.as_dict(),
            "schema_version": self.schema_version,
            "scope": self.scope,
            "sensitivity_difference": _serialized(self.sensitivity_difference),
        }


def _level(row: Mapping[str, object], field: str, prefix: str) -> int:
    value = str(row.get(field, f"{prefix}0")).upper()
    if not value.startswith(prefix):
        raise BrandHealthError(f"{field} is invalid")
    try:
        return int(value[len(prefix) :])
    except ValueError as exc:
        raise BrandHealthError(f"{field} is invalid") from exc


def _qualified_excluded(row: Mapping[str, object]) -> bool:
    manual = row.get("manual_confirmation", False)
    if type(manual) is not bool:
        raise BrandHealthError("manual_confirmation must be boolean")
    return (
        manual
        and _level(row, "commercial_level", "C") >= 3
        and _level(row, "integrity_level", "I") >= 4
    )


def _normalize_rows(
    observations: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in observations:
        if not isinstance(raw, Mapping):
            raise BrandHealthError("brand health observation must be an object")
        row = dict(raw)
        member_id = row.get("metric_member_id")
        if not isinstance(member_id, str) or not member_id:
            raise BrandHealthError("metric member ID is invalid")
        if member_id in seen:
            raise BrandHealthError("duplicate brand health metric member")
        seen.add(member_id)
        if row.get("voc_type") not in GRAINS:
            raise BrandHealthError("brand health VOC type is invalid")
        if "metric_eligible" in row and type(row["metric_eligible"]) is not bool:
            raise BrandHealthError("metric_eligible must be boolean")
        result.append(row)
    result.sort(key=lambda row: str(row["metric_member_id"]))
    return result


def _status(
    candidate_count: int,
    classified_count: int,
    *,
    decimal_places: int,
) -> tuple[str, Decimal | None, tuple[str, ...]]:
    if candidate_count == 0:
        return "unavailable", None, ("zero_candidate_entities",)
    if classified_count > candidate_count:
        raise BrandHealthError("classified count exceeds candidate count")
    coverage = Decimal(classified_count) * Decimal(100) / Decimal(candidate_count)
    reasons: list[str] = []
    if classified_count == 0:
        return (
            "unavailable",
            _round(coverage, decimal_places),
            ("zero_classified_entities",),
        )
    if coverage < Decimal(90):
        status = "provisional"
        reasons.append("classification_coverage_below_90_percent")
    else:
        status = "available"
    if classified_count < 30:
        status = "provisional"
        reasons.append("classified_sample_below_30")
    return status, _round(coverage, decimal_places), tuple(sorted(set(reasons)))


def _score(
    *,
    candidate_rows: list[dict[str, object]],
    classified_rows: list[dict[str, object]],
    numerator: Decimal,
    numerator_ids: Iterable[str],
    exact_value: Decimal | None,
    decimal_places: int,
) -> BrandHealthScore:
    status, coverage, reasons = _status(
        len(candidate_rows), len(classified_rows), decimal_places=decimal_places
    )
    value = (
        _round(exact_value, decimal_places)
        if exact_value is not None and status != "unavailable"
        else None
    )
    return BrandHealthScore(
        value=value,
        status=status,
        candidate_count=len(candidate_rows),
        classified_count=len(classified_rows),
        coverage_rate=coverage,
        denominator_count=len(classified_rows),
        numerator=numerator,
        denominator_member_ids=tuple(
            sorted(str(row["metric_member_id"]) for row in classified_rows)
        ),
        numerator_member_ids=tuple(sorted(set(numerator_ids))),
        reason_codes=reasons,
        _exact_value=exact_value,
    )


def _reputation(
    rows: list[dict[str, object]], decimal_places: int
) -> BrandHealthScore:
    candidates = [row for row in rows if row.get("brand_eligible") is True]
    classified: list[dict[str, object]] = []
    signed_ids: list[str] = []
    total = Decimal(0)
    weights = {"positive": Decimal(1), "neutral": Decimal(0), "negative": Decimal(-1)}
    for row in candidates:
        if row.get("sentiment_classification_status") != "complete":
            continue
        sentiment = str(row.get("sentiment", "")).casefold()
        if sentiment not in weights:
            raise BrandHealthError("complete sentiment classification is invalid")
        classified.append(row)
        total += weights[sentiment]
        if weights[sentiment]:
            signed_ids.append(str(row["metric_member_id"]))
    exact = (
        Decimal(50) + Decimal(50) * total / Decimal(len(classified))
        if classified
        else None
    )
    return _score(
        candidate_rows=candidates,
        classified_rows=classified,
        numerator=total,
        numerator_ids=signed_ids,
        exact_value=exact,
        decimal_places=decimal_places,
    )


def _product_experience(
    rows: list[dict[str, object]],
    atomic_facts: Iterable[Mapping[str, object]] | None,
    decimal_places: int,
) -> BrandHealthScore:
    candidates = [row for row in rows if row.get("product_bound") is True]
    try:
        metric = compute_indicator(
            "RV-PS-02",
            candidates,
            comparison_side="raw_observed",
            atomic_facts=atomic_facts,
            decimal_places=decimal_places,
        )
    except IndicatorComputationError as exc:
        raise BrandHealthError(str(exc)) from exc
    classified_by_id = set(metric.denominator_member_ids)
    classified = [
        row for row in candidates if str(row["metric_member_id"]) in classified_by_id
    ]
    exact = (
        Decimal(100)
        * (Decimal(1) - metric.numerator / Decimal(len(classified)))
        if classified
        else None
    )
    return _score(
        candidate_rows=candidates,
        classified_rows=classified,
        numerator=metric.numerator,
        numerator_ids=metric.numerator_member_ids,
        exact_value=exact,
        decimal_places=decimal_places,
    )


def _recommendation_trust(
    rows: list[dict[str, object]], decimal_places: int
) -> BrandHealthScore:
    candidates = [row for row in rows if row.get("brand_eligible") is True]
    classified: list[dict[str, object]] = []
    signed_ids: list[str] = []
    total = Decimal(0)
    positive = {"recommend", "recommended", "positive", "promoted"}
    negative = {"avoid", "distrust", "negative", "do_not_recommend"}
    neutral = {"none", "neutral", "both"}
    for row in candidates:
        if row.get("recommendation_classification_status") != "complete":
            continue
        recommendation = str(row.get("recommendation", "")).casefold()
        if recommendation in positive:
            weight = Decimal(1)
        elif recommendation in negative:
            weight = Decimal(-1)
        elif recommendation in neutral:
            weight = Decimal(0)
        else:
            raise BrandHealthError("complete recommendation classification is invalid")
        classified.append(row)
        total += weight
        if weight:
            signed_ids.append(str(row["metric_member_id"]))
    exact = (
        Decimal(50) + Decimal(50) * total / Decimal(len(classified))
        if classified
        else None
    )
    return _score(
        candidate_rows=candidates,
        classified_rows=classified,
        numerator=total,
        numerator_ids=signed_ids,
        exact_value=exact,
        decimal_places=decimal_places,
    )


def _risk_resilience(
    rows: list[dict[str, object]], decimal_places: int
) -> BrandHealthScore:
    candidates = [row for row in rows if row.get("brand_eligible") is True]
    classified: list[dict[str, object]] = []
    risk_ids: list[str] = []
    total = Decimal(0)
    weights = {
        "none": Decimal(0),
        "p2": Decimal("0.3"),
        "p1": Decimal("0.7"),
        "p0": Decimal(1),
    }
    for row in candidates:
        if row.get("priority_classification_status") != "complete":
            continue
        priority = str(row.get("priority", "")).casefold()
        if priority not in weights:
            raise BrandHealthError("complete priority classification is invalid")
        classified.append(row)
        total += weights[priority]
        if weights[priority]:
            risk_ids.append(str(row["metric_member_id"]))
    exact = (
        Decimal(100) - Decimal(100) * total / Decimal(len(classified))
        if classified
        else None
    )
    return _score(
        candidate_rows=candidates,
        classified_rows=classified,
        numerator=total,
        numerator_ids=risk_ids,
        exact_value=exact,
        decimal_places=decimal_places,
    )


def _dimension(
    dimension_id: str,
    scores: dict[str, BrandHealthScore],
    decimal_places: int,
) -> BrandHealthDimension:
    unavailable = [grain for grain, score in scores.items() if score.status == "unavailable"]
    provisional = [grain for grain, score in scores.items() if score.status == "provisional"]
    reasons = sorted(
        {
            f"{grain}:{reason}"
            for grain, score in scores.items()
            for reason in score.reason_codes
        }
    )
    if unavailable:
        status = "unavailable"
        exact = None
        value = None
    else:
        if any(scores[grain]._exact_value is None for grain in GRAINS):
            raise BrandHealthError("available grain lacks exact score")
        exact = sum(
            (scores[grain]._exact_value for grain in GRAINS), Decimal(0)  # type: ignore[arg-type]
        ) / Decimal(2)
        status = "provisional" if provisional else "available"
        value = _round(exact, decimal_places)
    return BrandHealthDimension(
        dimension_id=dimension_id,
        value=value,
        status=status,
        grain_scores=scores,
        reason_codes=tuple(reasons),
        _exact_value=exact,
    )


def _variant(
    all_rows: list[dict[str, object]],
    *,
    comparison_side: str,
    excluded_entity_ids: tuple[str, ...],
    atomic_facts: Iterable[Mapping[str, object]] | None,
    decimal_places: int,
) -> BrandHealthVariant:
    excluded = set(excluded_entity_ids)
    rows = [row for row in all_rows if str(row["metric_member_id"]) not in excluded]
    dimensions: dict[str, BrandHealthDimension] = {}
    scorers = {
        "reputation": lambda grain_rows: _reputation(grain_rows, decimal_places),
        "product_experience": lambda grain_rows: _product_experience(
            grain_rows, atomic_facts, decimal_places
        ),
        "recommendation_trust": lambda grain_rows: _recommendation_trust(
            grain_rows, decimal_places
        ),
        "risk_resilience": lambda grain_rows: _risk_resilience(
            grain_rows, decimal_places
        ),
    }
    for dimension_id in DIMENSIONS:
        grain_scores = {
            grain: scorers[dimension_id](
                [row for row in rows if row.get("voc_type") == grain]
            )
            for grain in GRAINS
        }
        dimensions[dimension_id] = _dimension(
            dimension_id, grain_scores, decimal_places
        )
    unavailable = [
        name for name, dimension in dimensions.items() if dimension.status == "unavailable"
    ]
    provisional = [
        name for name, dimension in dimensions.items() if dimension.status == "provisional"
    ]
    if unavailable:
        total_status = "unavailable"
        exact = None
        value = None
    else:
        exact_values = [dimensions[name]._exact_value for name in DIMENSIONS]
        if any(value is None for value in exact_values):
            raise BrandHealthError("available dimension lacks exact score")
        exact = sum((value for value in exact_values if value is not None), Decimal(0)) / Decimal(4)
        total_status = "provisional" if provisional else "available"
        # The total is rounded once from the four unrounded dimensions.
        value = _round(exact, decimal_places)
    total_reasons = tuple(
        sorted(
            {
                f"{name}:{reason}"
                for name, dimension in dimensions.items()
                for reason in dimension.reason_codes
            }
        )
    )
    total = BrandHealthScore(
        value=value,
        status=total_status,
        candidate_count=len(rows),
        classified_count=len(rows) if total_status != "unavailable" else 0,
        coverage_rate=(Decimal(100) if rows and total_status != "unavailable" else None),
        denominator_count=len(rows) if total_status != "unavailable" else 0,
        numerator=exact if exact is not None else Decimal(0),
        denominator_member_ids=tuple(
            sorted(str(row["metric_member_id"]) for row in rows)
        ),
        numerator_member_ids=(),
        reason_codes=total_reasons or (() if total_status != "unavailable" else ("dimension_unavailable",)),
        _exact_value=exact,
    )
    return BrandHealthVariant(
        comparison_side=comparison_side,
        total=total,
        dimensions=dimensions,
        included_entity_ids=tuple(
            sorted(str(row["metric_member_id"]) for row in rows)
        ),
        excluded_entity_ids=excluded_entity_ids,
    )


def compute_brand_health(
    observations: Iterable[Mapping[str, object]],
    *,
    atomic_facts: Iterable[Mapping[str, object]] | None = None,
    period: str = "last_30_complete_calendar_days",
    scope: str = "momcozy",
    decimal_places: int = 1,
) -> BrandHealthResult:
    """Compute raw and qualified Momcozy brand-health views."""

    if not isinstance(period, str) or not period or not isinstance(scope, str) or not scope:
        raise BrandHealthError("period and scope must be non-empty strings")
    rows = _normalize_rows(observations)
    base = [
        row
        for row in rows
        if row.get("metric_eligible", True) is True
        and str(row.get("brand", "")).casefold() == "momcozy"
    ]
    qualified_excluded = tuple(
        sorted(
            str(row["metric_member_id"])
            for row in base
            if _qualified_excluded(row)
        )
    )
    raw = _variant(
        base,
        comparison_side="raw_observed",
        excluded_entity_ids=(),
        atomic_facts=atomic_facts,
        decimal_places=decimal_places,
    )
    qualified = _variant(
        base,
        comparison_side="qualified_organic",
        excluded_entity_ids=qualified_excluded,
        atomic_facts=atomic_facts,
        decimal_places=decimal_places,
    )
    sensitivity = None
    if raw.total.value is not None and qualified.total.value is not None:
        sensitivity = _round(raw.total.value - qualified.total.value, decimal_places)
    return BrandHealthResult(
        raw=raw,
        qualified=qualified,
        sensitivity_difference=sensitivity,
        period=period,
        scope=scope,
        decimal_places=decimal_places,
    )
