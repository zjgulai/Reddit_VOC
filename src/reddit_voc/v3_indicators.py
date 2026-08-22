"""Deterministic Reddit VOC V3 indicator registry and computations.

The module deliberately works on already-governed observation, atomic-fact and
eligibility rows.  It performs no text classification and no provider calls.
All arithmetic uses :class:`~decimal.Decimal`; display rounding is ROUND_HALF_UP.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from hashlib import sha256
import json
from math import log1p
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence


REGISTRY_SCHEMA_VERSION = "reddit_voc_indicator_registry_v1"
RESULT_SCHEMA_VERSION = "reddit_voc_indicator_result_v1"
EXPECTED_BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}
EXPECTED_INDICATOR_IDS = tuple(
    [f"RV-DH-{index:02d}" for index in range(1, 6)]
    + [f"RV-BR-{index:02d}" for index in range(1, 6)]
    + [f"RV-PS-{index:02d}" for index in range(1, 5)]
    + [f"RV-IN-{index:02d}" for index in range(1, 6)]
    + [f"RV-CI-{index:02d}" for index in range(1, 8)]
)
COMPARISON_SIDES = frozenset(
    {
        "baseline",
        "competitor_union",
        "current",
        "momcozy",
        "not_applicable",
        "qualified_organic",
        "raw_observed",
    }
)
MEMBER_TYPES = frozenset(
    {"canonical_entity", "thread", "cluster", "event_dossier", "review_item"}
)
OUTPUT_SHAPES = frozenset({"scalar", "ranking", "buckets"})
THRESHOLD_POLICIES = frozenset(
    {
        "association_30_10",
        "audit_rate",
        "comparable_pair_30",
        "inherit_target",
        "integrity_count",
        "integrity_rate",
        "sample_30_10",
        "thread_pair_10",
        "three_complete_periods",
    }
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class IndicatorComputationError(ValueError):
    """The registry, governed inputs, or requested computation is invalid."""


def canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise IndicatorComputationError(
            "value is not canonical JSON serializable"
        ) from exc


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise IndicatorComputationError(f"{label} must be a non-empty string")
    return value


def _decimal(value: object, label: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise IndicatorComputationError(f"{label} must be numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise IndicatorComputationError(f"{label} must be numeric") from exc
    if not result.is_finite():
        raise IndicatorComputationError(f"{label} must be finite")
    return result


def _round(value: Decimal, decimal_places: int) -> Decimal:
    if type(decimal_places) is not int or not 0 <= decimal_places <= 12:
        raise IndicatorComputationError("decimal_places is invalid")
    quantum = Decimal(1).scaleb(-decimal_places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def _serialized_decimal(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


@dataclass(frozen=True)
class IndicatorDefinition:
    reddit_indicator_id: str
    metric_family: str
    metric_member_type: str
    name_cn: str
    output_shape: str
    unit: str
    default_comparison_side: str
    supports_raw_qualified: bool
    threshold_policy: str


@dataclass(frozen=True)
class IndicatorRegistry:
    registry_version: str
    core_indicator_count: int
    integrity_indicator_count: int
    indicators: tuple[IndicatorDefinition, ...]
    availability_policies: dict[str, dict[str, object]]
    boundaries: dict[str, bool]
    schema_version: str = REGISTRY_SCHEMA_VERSION

    @property
    def by_id(self) -> dict[str, IndicatorDefinition]:
        return {item.reddit_indicator_id: item for item in self.indicators}


@dataclass(frozen=True)
class IndicatorCoverage:
    candidate_count: int
    processed_count: int
    coverage_rate: Decimal | None
    status: str

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate_count": self.candidate_count,
            "coverage_rate": _serialized_decimal(self.coverage_rate),
            "processed_count": self.processed_count,
            "status": self.status,
        }


@dataclass(frozen=True)
class IndicatorResult:
    reddit_indicator_id: str
    metric_family: str
    name_cn: str
    comparison_side: str
    period: str
    scope: str
    voc_types: tuple[str, ...]
    metric_member_type: str
    output_shape: str
    unit: str
    status: str
    value: Decimal | tuple[dict[str, object], ...] | dict[str, int] | None
    numerator: Decimal
    denominator: Decimal
    metric_eligible_member_ids: tuple[str, ...]
    denominator_member_ids: tuple[str, ...]
    numerator_member_ids: tuple[str, ...]
    evidence_fact_ids: tuple[str, ...]
    unavailable_reason_codes: tuple[str, ...]
    coverage: IndicatorCoverage
    policy_version: str
    schema_version: str = RESULT_SCHEMA_VERSION

    def as_dict(self) -> dict[str, object]:
        if isinstance(self.value, Decimal) or self.value is None:
            serialized_value: object = _serialized_decimal(self.value)
        elif isinstance(self.value, tuple):
            serialized_value = [dict(item) for item in self.value]
        else:
            serialized_value = dict(self.value)
        return {
            "comparison_side": self.comparison_side,
            "coverage": self.coverage.as_dict(),
            "denominator": _serialized_decimal(self.denominator),
            "denominator_member_ids": list(self.denominator_member_ids),
            "evidence_fact_ids": list(self.evidence_fact_ids),
            "metric_eligible_member_ids": list(self.metric_eligible_member_ids),
            "metric_family": self.metric_family,
            "metric_member_type": self.metric_member_type,
            "name_cn": self.name_cn,
            "numerator": _serialized_decimal(self.numerator),
            "numerator_member_ids": list(self.numerator_member_ids),
            "output_shape": self.output_shape,
            "period": self.period,
            "policy_version": self.policy_version,
            "reddit_indicator_id": self.reddit_indicator_id,
            "schema_version": self.schema_version,
            "scope": self.scope,
            "status": self.status,
            "unavailable_reason_codes": list(self.unavailable_reason_codes),
            "unit": self.unit,
            "value": serialized_value,
            "voc_types": list(self.voc_types),
        }


def _parse_registry(value: object) -> IndicatorRegistry:
    if not isinstance(value, Mapping) or set(value) != {
        "availability_policies",
        "boundaries",
        "core_indicator_count",
        "indicators",
        "integrity_indicator_count",
        "registry_version",
        "schema_version",
    }:
        raise IndicatorComputationError("indicator registry fields are invalid")
    if value.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise IndicatorComputationError("indicator registry schema is unsupported")
    if value.get("boundaries") != EXPECTED_BOUNDARIES:
        raise IndicatorComputationError("indicator registry boundaries are invalid")
    if value.get("core_indicator_count") != 19 or value.get(
        "integrity_indicator_count"
    ) != 7:
        raise IndicatorComputationError("indicator registry counts are invalid")
    raw_policies = value.get("availability_policies")
    if not isinstance(raw_policies, Mapping) or set(raw_policies) != THRESHOLD_POLICIES:
        raise IndicatorComputationError("availability policy closed set is invalid")
    policies: dict[str, dict[str, object]] = {}
    for policy_id, policy in raw_policies.items():
        if not isinstance(policy, Mapping):
            raise IndicatorComputationError("availability policy is invalid")
        policies[str(policy_id)] = dict(policy)
    raw_indicators = value.get("indicators")
    if not isinstance(raw_indicators, list) or len(raw_indicators) != 26:
        raise IndicatorComputationError("indicator closed set is invalid")
    indicators: list[IndicatorDefinition] = []
    for raw in raw_indicators:
        if not isinstance(raw, Mapping) or set(raw) != {
            "default_comparison_side",
            "metric_family",
            "metric_member_type",
            "name_cn",
            "output_shape",
            "reddit_indicator_id",
            "supports_raw_qualified",
            "threshold_policy",
            "unit",
        }:
            raise IndicatorComputationError("indicator definition fields are invalid")
        indicator_id = _string(raw.get("reddit_indicator_id"), "indicator ID")
        family = _string(raw.get("metric_family"), "metric family")
        member_type = _string(raw.get("metric_member_type"), "metric member type")
        output_shape = _string(raw.get("output_shape"), "output shape")
        side = _string(raw.get("default_comparison_side"), "comparison side")
        threshold = _string(raw.get("threshold_policy"), "threshold policy")
        if family != indicator_id.rsplit("-", 1)[0]:
            raise IndicatorComputationError("metric family does not match indicator ID")
        if member_type not in MEMBER_TYPES or output_shape not in OUTPUT_SHAPES:
            raise IndicatorComputationError("indicator shape or member type is invalid")
        if side not in COMPARISON_SIDES or threshold not in THRESHOLD_POLICIES:
            raise IndicatorComputationError("indicator policy is invalid")
        supports = raw.get("supports_raw_qualified")
        if type(supports) is not bool:
            raise IndicatorComputationError("supports_raw_qualified must be boolean")
        indicators.append(
            IndicatorDefinition(
                reddit_indicator_id=indicator_id,
                metric_family=family,
                metric_member_type=member_type,
                name_cn=_string(raw.get("name_cn"), "indicator name"),
                output_shape=output_shape,
                unit=_string(raw.get("unit"), "indicator unit"),
                default_comparison_side=side,
                supports_raw_qualified=supports,
                threshold_policy=threshold,
            )
        )
    if tuple(item.reddit_indicator_id for item in indicators) != EXPECTED_INDICATOR_IDS:
        raise IndicatorComputationError("indicator registry order or closed set is invalid")
    return IndicatorRegistry(
        registry_version=_string(value.get("registry_version"), "registry version"),
        core_indicator_count=19,
        integrity_indicator_count=7,
        indicators=tuple(indicators),
        availability_policies=policies,
        boundaries=dict(EXPECTED_BOUNDARIES),
    )


def load_indicator_registry(path: Path) -> IndicatorRegistry:
    try:
        payload = Path(path).read_bytes()
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IndicatorComputationError("indicator registry is unreadable") from exc
    if payload != canonical_json_bytes(value) + b"\n":
        raise IndicatorComputationError("indicator registry is not canonical JSON")
    return _parse_registry(value)


def _default_registry() -> IndicatorRegistry:
    path = (
        Path(__file__).resolve().parents[2]
        / "config/analytics/reddit-voc-indicator-registry-v1.json"
    )
    return load_indicator_registry(path)


def _mapping_rows(values: Iterable[Mapping[str, object]], label: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, Mapping):
            raise IndicatorComputationError(f"{label} row must be an object")
        row = dict(value)
        member_id = _string(row.get("metric_member_id"), "metric member ID")
        if member_id in seen:
            raise IndicatorComputationError(f"duplicate {label} metric member")
        seen.add(member_id)
        if "metric_eligible" in row and type(row["metric_eligible"]) is not bool:
            raise IndicatorComputationError("metric_eligible must be boolean")
        rows.append(row)
    rows.sort(key=lambda row: str(row["metric_member_id"]))
    return rows


def _is_qualified_excluded(row: Mapping[str, object]) -> bool:
    commercial = str(row.get("commercial_level", "C0")).upper()
    integrity = str(row.get("integrity_level", "I0")).upper()
    try:
        commercial_level = int(commercial.removeprefix("C"))
        integrity_level = int(integrity.removeprefix("I"))
    except ValueError as exc:
        raise IndicatorComputationError("commercial or integrity level is invalid") from exc
    manual = row.get("manual_confirmation", False)
    if type(manual) is not bool:
        raise IndicatorComputationError("manual_confirmation must be boolean")
    return manual and commercial_level >= 3 and integrity_level >= 4


def _side_filter(
    rows: Sequence[dict[str, object]], comparison_side: str
) -> list[dict[str, object]]:
    if comparison_side == "qualified_organic":
        return [row for row in rows if not _is_qualified_excluded(row)]
    if comparison_side == "momcozy":
        return [row for row in rows if str(row.get("brand", "")).casefold() == "momcozy"]
    if comparison_side == "competitor_union":
        return [
            row
            for row in rows
            if str(row.get("brand", "")).casefold() not in {"", "momcozy"}
        ]
    if comparison_side in {"current", "baseline"}:
        selected = [
            row for row in rows if row.get("period_role") in {None, comparison_side}
        ]
        return selected
    return list(rows)


def _eligible_rows(
    observations: Sequence[dict[str, object]],
    *,
    indicator_id: str,
    comparison_side: str,
    period: str,
    scope: str,
    eligibility_rows: Iterable[Mapping[str, object]] | None,
) -> list[dict[str, object]]:
    base = [row for row in observations if row.get("metric_eligible", True) is True]
    base = _side_filter(base, comparison_side)
    if eligibility_rows is None:
        return base
    observation_by_id = {str(row["metric_member_id"]): row for row in observations}
    matched_ids: set[str] = set()
    seen_keys: set[tuple[str, str, str, str, str]] = set()
    for raw in eligibility_rows:
        if not isinstance(raw, Mapping):
            raise IndicatorComputationError("eligibility row must be an object")
        if raw.get("reddit_indicator_id") != indicator_id:
            continue
        if raw.get("comparison_side") != comparison_side:
            continue
        if raw.get("period") != period or raw.get("scope") != scope:
            continue
        member_id = _string(raw.get("metric_member_id"), "eligibility member ID")
        voc_type = _string(raw.get("voc_type"), "eligibility VOC type")
        key = (member_id, indicator_id, comparison_side, period, scope)
        if key in seen_keys:
            raise IndicatorComputationError("duplicate eligibility foreign key")
        seen_keys.add(key)
        if member_id not in observation_by_id:
            raise IndicatorComputationError("eligibility foreign key is missing observation")
        if observation_by_id[member_id].get("voc_type") != voc_type:
            raise IndicatorComputationError("eligibility VOC type foreign key mismatch")
        status = raw.get("status")
        if status not in {"eligible", "excluded"}:
            raise IndicatorComputationError("eligibility status is invalid")
        denominator_member = raw.get("denominator_member", False)
        numerator_member = raw.get("numerator_member", "not_applicable")
        if type(denominator_member) is not bool or (
            type(numerator_member) is not bool and numerator_member != "not_applicable"
        ):
            raise IndicatorComputationError("eligibility membership is invalid")
        if status == "excluded" and (denominator_member is True or numerator_member is True):
            raise IndicatorComputationError("excluded eligibility row has metric membership")
        if numerator_member is True and denominator_member is not True:
            raise IndicatorComputationError("eligibility numerator is outside denominator")
        if status == "eligible":
            matched_ids.add(member_id)
    return [row for row in base if str(row["metric_member_id"]) in matched_ids]


def _fact_index(
    atomic_facts: Iterable[Mapping[str, object]] | None,
) -> dict[str, dict[str, object]] | None:
    if atomic_facts is None:
        return None
    result: dict[str, dict[str, object]] = {}
    for raw in atomic_facts:
        if not isinstance(raw, Mapping):
            raise IndicatorComputationError("atomic fact must be an object")
        row = dict(raw)
        fact_id = _string(row.get("fact_id"), "fact ID")
        if fact_id in result:
            raise IndicatorComputationError("duplicate atomic fact ID")
        result[fact_id] = row
    return result


def _join_fact(
    inline: Mapping[str, object],
    *,
    member_id: str,
    facts: dict[str, dict[str, object]] | None,
) -> dict[str, object]:
    fact_id = _string(inline.get("fact_id"), "inline fact ID")
    if facts is None:
        return dict(inline)
    governed = facts.get(fact_id)
    if governed is None:
        raise IndicatorComputationError("fact foreign key is missing")
    if governed.get("canonical_entity_id") != member_id:
        raise IndicatorComputationError("fact foreign key entity mismatch")
    for field in ("decision_status", "fact_type"):
        if inline.get(field) != governed.get(field):
            raise IndicatorComputationError(f"fact foreign key {field} mismatch")
    for field in ("polarity", "tag_id"):
        if field in inline and field in governed and inline[field] != governed[field]:
            raise IndicatorComputationError(f"fact foreign key {field} mismatch")
    # Fixture and compatibility ledgers may keep polarity/tag metadata on the
    # observation-side reference while the governed registry exposes only the
    # identity/type/status foreign key.  Preserve those fields after validating
    # every overlapping value; a formal loader can require the richer fact row.
    merged = dict(governed)
    for field, value in inline.items():
        merged.setdefault(field, value)
    return merged


def _tag_fact_ids(
    row: Mapping[str, object], facts: dict[str, dict[str, object]] | None
) -> tuple[str, ...]:
    raw = row.get("tag_fact_ids", [])
    if not isinstance(raw, list) or any(not isinstance(value, str) or not value for value in raw):
        raise IndicatorComputationError("tag fact IDs are invalid")
    ids = tuple(sorted(set(raw)))
    if facts is not None:
        for fact_id in ids:
            fact = facts.get(fact_id)
            if (
                fact is None
                or fact.get("canonical_entity_id") != row["metric_member_id"]
                or fact.get("decision_status") != "promoted"
                or fact.get("fact_type") not in {"entity_tag_fact", "persona_atomic_fact"}
            ):
                raise IndicatorComputationError("tag fact foreign key mismatch")
    return ids


def _negative_problem_facts(
    row: Mapping[str, object], facts: dict[str, dict[str, object]] | None
) -> tuple[dict[str, object], ...]:
    raw = row.get("product_problem_facts", [])
    if not isinstance(raw, list):
        raise IndicatorComputationError("product problem facts must be an array")
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for inline in raw:
        if not isinstance(inline, Mapping):
            raise IndicatorComputationError("product problem fact must be an object")
        fact = _join_fact(
            inline,
            member_id=str(row["metric_member_id"]),
            facts=facts,
        )
        fact_id = _string(fact.get("fact_id"), "product problem fact ID")
        if fact_id in seen:
            raise IndicatorComputationError("duplicate product problem fact reference")
        seen.add(fact_id)
        attributes = fact.get("attributes")
        polarity = fact.get("polarity")
        if polarity is None and isinstance(attributes, Mapping):
            polarity = attributes.get("polarity")
        canonical_value = str(fact.get("canonical_value", "")).casefold()
        fact_type = fact.get("fact_type")
        product_problem = fact_type in {"entity_problem_fact", "product_problem"}
        if fact_type == "entity_problem_fact" and canonical_value:
            # Closed-set facts may encode the exact problem tag in canonical_value;
            # the fact type itself is the governed product-problem table.
            product_problem = True
        if (
            fact.get("decision_status") == "promoted"
            and product_problem
            and str(polarity).casefold() == "negative"
        ):
            result.append(dict(fact))
    return tuple(result)


def _problem_members(
    rows: Sequence[dict[str, object]], facts: dict[str, dict[str, object]] | None
) -> tuple[list[dict[str, object]], dict[str, tuple[dict[str, object], ...]]]:
    denominator: list[dict[str, object]] = []
    qualifying: dict[str, tuple[dict[str, object], ...]] = {}
    for row in rows:
        if row.get("product_bound") is not True:
            continue
        status = row.get("problem_classification_status")
        if status != "complete":
            continue
        denominator.append(row)
        member_id = str(row["metric_member_id"])
        problem_facts = _negative_problem_facts(row, facts)
        if str(row.get("sentiment", "")).casefold() == "negative" and problem_facts:
            qualifying[member_id] = problem_facts
    return denominator, qualifying


def _coverage(
    candidate_count: int,
    processed_count: int,
    *,
    availability_status: str,
    decimal_places: int,
) -> IndicatorCoverage:
    if candidate_count < 0 or processed_count < 0 or processed_count > candidate_count:
        raise IndicatorComputationError("coverage counts are invalid")
    rate = None
    if candidate_count:
        rate = _round(
            Decimal(processed_count) * Decimal(100) / Decimal(candidate_count),
            decimal_places,
        )
    return IndicatorCoverage(
        candidate_count=candidate_count,
        processed_count=processed_count,
        coverage_rate=rate,
        status=availability_status,
    )


def _sample_status(count: int) -> tuple[str, tuple[str, ...]]:
    if count <= 0:
        return "unavailable", ("zero_denominator",)
    if count >= 30:
        return "available", ()
    return "provisional", ("sample_below_available_threshold",)


def _result(
    definition: IndicatorDefinition,
    *,
    comparison_side: str,
    period: str,
    scope: str,
    eligible_rows: Sequence[Mapping[str, object]],
    denominator_rows: Sequence[Mapping[str, object]],
    numerator_ids: Iterable[str],
    numerator: Decimal,
    denominator: Decimal,
    status: str,
    value: Decimal | tuple[dict[str, object], ...] | dict[str, int] | None,
    evidence_fact_ids: Iterable[str] = (),
    unavailable_reason_codes: Iterable[str] = (),
    unit: str | None = None,
    coverage_candidate_count: int | None = None,
    coverage_processed_count: int | None = None,
    decimal_places: int = 2,
) -> IndicatorResult:
    eligible_ids = tuple(sorted({str(row["metric_member_id"]) for row in eligible_rows}))
    denominator_ids = tuple(
        sorted({str(row["metric_member_id"]) for row in denominator_rows})
    )
    numerator_member_ids = tuple(sorted(set(numerator_ids)))
    if not set(numerator_member_ids) <= set(denominator_ids):
        raise IndicatorComputationError("numerator IDs are outside denominator IDs")
    if not set(denominator_ids) <= set(eligible_ids):
        raise IndicatorComputationError("denominator IDs are outside metric eligible IDs")
    reason_codes = tuple(sorted(set(unavailable_reason_codes)))
    if status == "unavailable":
        value = None
        if not reason_codes:
            raise IndicatorComputationError("unavailable result lacks reason code")
    elif status not in {"available", "provisional"}:
        raise IndicatorComputationError("indicator status is invalid")
    candidate_count = (
        len(eligible_ids)
        if coverage_candidate_count is None
        else coverage_candidate_count
    )
    processed_count = (
        len(denominator_ids)
        if coverage_processed_count is None
        else coverage_processed_count
    )
    voc_types = tuple(
        sorted(
            {
                str(row.get("voc_type"))
                for row in eligible_rows
                if isinstance(row.get("voc_type"), str) and row.get("voc_type")
            }
        )
    )
    return IndicatorResult(
        reddit_indicator_id=definition.reddit_indicator_id,
        metric_family=definition.metric_family,
        name_cn=definition.name_cn,
        comparison_side=comparison_side,
        period=period,
        scope=scope,
        voc_types=voc_types,
        metric_member_type=definition.metric_member_type,
        output_shape=definition.output_shape,
        unit=definition.unit if unit is None else unit,
        status=status,
        value=value,
        numerator=numerator,
        denominator=denominator,
        metric_eligible_member_ids=eligible_ids,
        denominator_member_ids=denominator_ids,
        numerator_member_ids=numerator_member_ids,
        evidence_fact_ids=tuple(sorted(set(evidence_fact_ids))),
        unavailable_reason_codes=reason_codes,
        coverage=_coverage(
            candidate_count,
            processed_count,
            availability_status=status,
            decimal_places=decimal_places,
        ),
        policy_version=definition.threshold_policy,
    )


def _rate_value(numerator: Decimal, denominator: Decimal, decimal_places: int) -> Decimal:
    return _round(numerator * Decimal(100) / denominator, decimal_places)


def _status_for_definition(
    definition: IndicatorDefinition,
    denominator_count: int,
) -> tuple[str, tuple[str, ...]]:
    if definition.threshold_policy in {"audit_rate", "integrity_rate"}:
        if denominator_count <= 0:
            return "unavailable", ("zero_denominator",)
        return "available", ()
    if definition.threshold_policy == "sample_30_10":
        return _sample_status(denominator_count)
    if definition.threshold_policy == "integrity_count":
        return "available", ()
    return _sample_status(denominator_count)


def _fact_ids_for_rows(
    rows: Sequence[Mapping[str, object]],
    field: str,
    facts: dict[str, dict[str, object]] | None,
) -> tuple[str, ...]:
    result: set[str] = set()
    for row in rows:
        raw = row.get(field, [])
        if not isinstance(raw, list):
            raise IndicatorComputationError(f"{field} must be an array")
        for fact_id in raw:
            if not isinstance(fact_id, str) or not fact_id:
                raise IndicatorComputationError(f"{field} contains invalid fact ID")
            if facts is not None:
                fact = facts.get(fact_id)
                if (
                    fact is None
                    or fact.get("canonical_entity_id") != row["metric_member_id"]
                    or fact.get("decision_status") != "promoted"
                ):
                    raise IndicatorComputationError("fact foreign key mismatch")
            result.add(fact_id)
    return tuple(sorted(result))


def _recommendation_fact_ids(
    rows: Sequence[Mapping[str, object]],
    facts: dict[str, dict[str, object]] | None,
) -> tuple[str, ...]:
    for row in rows:
        raw = row.get("recommendation_fact_ids", [])
        if not isinstance(raw, list) or not raw:
            raise IndicatorComputationError(
                "positive recommendation lacks governed tag evidence"
            )
    ids = _fact_ids_for_rows(rows, "recommendation_fact_ids", facts)
    if facts is None:
        raise IndicatorComputationError(
            "recommendation evidence requires governed atomic facts"
        )
    for fact_id in ids:
        fact = facts[fact_id]
        if (
            fact.get("fact_type") != "entity_tag_fact"
            or fact.get("canonical_value") != "L0-GEN-103"
        ):
            raise IndicatorComputationError(
                "recommendation evidence is outside L0-GEN-103"
            )
    return ids


def _balance(
    rows: Sequence[dict[str, object]], decimal_places: int
) -> tuple[Decimal, list[dict[str, object]], list[str]]:
    classified = [
        row
        for row in rows
        if row.get("sentiment_classification_status") == "complete"
        and str(row.get("sentiment", "")).casefold()
        in {"positive", "neutral", "negative"}
    ]
    if not classified:
        raise IndicatorComputationError("sentiment comparison has zero denominator")
    positive = [
        row for row in classified if str(row.get("sentiment")).casefold() == "positive"
    ]
    negative = [
        row for row in classified if str(row.get("sentiment")).casefold() == "negative"
    ]
    value = _round(
        Decimal(len(positive) - len(negative))
        * Decimal(100)
        / Decimal(len(classified)),
        decimal_places,
    )
    return value, classified, [
        str(row["metric_member_id"]) for row in positive + negative
    ]


def compute_indicator(
    reddit_indicator_id: str,
    observations: Iterable[Mapping[str, object]],
    *,
    registry: IndicatorRegistry | None = None,
    comparison_side: str | None = None,
    period: str = "all",
    scope: str = "all",
    eligibility_rows: Iterable[Mapping[str, object]] | None = None,
    atomic_facts: Iterable[Mapping[str, object]] | None = None,
    context: Mapping[str, object] | None = None,
    decimal_places: int = 2,
) -> IndicatorResult:
    """Compute one registered indicator from governed entity/ledger rows."""

    registry = _default_registry() if registry is None else registry
    definition = registry.by_id.get(reddit_indicator_id)
    if definition is None:
        raise IndicatorComputationError("indicator ID is not registered")
    side = definition.default_comparison_side if comparison_side is None else comparison_side
    if side not in COMPARISON_SIDES:
        raise IndicatorComputationError("comparison side is unsupported")
    period = _string(period, "period")
    scope = _string(scope, "scope")
    if not isinstance(context if context is not None else {}, Mapping):
        raise IndicatorComputationError("indicator context must be an object")
    context = {} if context is None else dict(context)
    rows = _mapping_rows(observations, "observation")
    facts = _fact_index(atomic_facts)

    # CI-06 is derived from two precomputed, explicitly compatible targets and
    # therefore has no entity member set of its own.
    if reddit_indicator_id == "RV-CI-06":
        return _compute_sensitivity(
            definition,
            context=context,
            period=period,
            scope=scope,
            decimal_places=decimal_places,
        )

    eligible = _eligible_rows(
        rows,
        indicator_id=reddit_indicator_id,
        comparison_side=side,
        period=period,
        scope=scope,
        eligibility_rows=eligibility_rows,
    )

    if reddit_indicator_id == "RV-DH-01":
        unavailable = _controlled_coverage_unavailable(
            definition, context, side, period, scope, decimal_places
        )
        if unavailable is not None:
            return unavailable
        if "canonical_audit_rows" in context:
            eligible = _context_rows(
                context["canonical_audit_rows"], "canonical audit rows"
            )
        denominator_rows = [
            row
            for row in eligible
            if row.get("voc_type") in {"comment_context_voc", "comment_identity"}
        ]
        numerator_rows = [row for row in denominator_rows if row.get("linked_parent") is True]
        return _rate_result(
            definition, side, period, scope, eligible, denominator_rows, numerator_rows,
            decimal_places=decimal_places,
        )
    if reddit_indicator_id == "RV-DH-02":
        unavailable = _controlled_coverage_unavailable(
            definition, context, side, period, scope, decimal_places
        )
        if unavailable is not None:
            return unavailable
        if "canonical_audit_rows" in context:
            eligible = _context_rows(
                context["canonical_audit_rows"], "canonical audit rows"
            )
        denominator_rows = eligible
        numerator_rows = [row for row in denominator_rows if row.get("text_ready") is True]
        return _rate_result(
            definition, side, period, scope, eligible, denominator_rows, numerator_rows,
            decimal_places=decimal_places,
        )
    if reddit_indicator_id == "RV-DH-03":
        denominator_rows = [row for row in eligible if row.get("text_ready") is True]
        numerator_rows = [row for row in denominator_rows if _tag_fact_ids(row, facts)]
        evidence = [
            fact_id for row in numerator_rows for fact_id in _tag_fact_ids(row, facts)
        ]
        return _rate_result(
            definition, side, period, scope, eligible, denominator_rows, numerator_rows,
            evidence_fact_ids=evidence, decimal_places=decimal_places,
        )
    if reddit_indicator_id == "RV-DH-04":
        unavailable = _controlled_coverage_unavailable(
            definition, context, side, period, scope, decimal_places
        )
        if unavailable is not None:
            return unavailable
        proof = context.get("independent_product_relevance_evidence_complete")
        if proof is not True:
            if proof is not None and proof is not False:
                raise IndicatorComputationError(
                    "independent product relevance proof is invalid"
                )
            return _result(
                definition,
                comparison_side=side,
                period=period,
                scope=scope,
                eligible_rows=eligible,
                denominator_rows=(),
                numerator_ids=(),
                numerator=Decimal(0),
                denominator=Decimal(0),
                status="unavailable",
                value=None,
                unavailable_reason_codes=(
                    "independent_product_relevance_evidence_unavailable",
                ),
                decimal_places=decimal_places,
            )
        denominator_rows = [
            row
            for row in eligible
            if row.get("independent_product_relevant") is True
        ]
        numerator_rows = [
            row
            for row in denominator_rows
            if row.get("product_bound") is True
            and isinstance(row.get("product_scope"), str)
            and bool(row.get("product_scope"))
        ]
        return _rate_result(
            definition, side, period, scope, eligible, denominator_rows, numerator_rows,
            decimal_places=decimal_places,
        )
    if reddit_indicator_id == "RV-DH-05":
        denominator_rows = [row for row in eligible if _tag_fact_ids(row, facts)]
        numerator_rows = [row for row in denominator_rows if row.get("evidence_complete") is True]
        evidence = [
            fact_id for row in numerator_rows for fact_id in _tag_fact_ids(row, facts)
        ]
        return _rate_result(
            definition, side, period, scope, eligible, denominator_rows, numerator_rows,
            evidence_fact_ids=evidence, decimal_places=decimal_places,
        )
    if reddit_indicator_id == "RV-BR-01":
        denominator_rows = [row for row in eligible if row.get("brand_eligible") is True]
        # Direct volume is a measurement, not a sample estimate. Once the
        # report period is complete, zero (or any small count) is meaningful.
        # Sample-size gates remain on rates, scores and associations.
        status, reasons = "available", ()
        count = Decimal(len(denominator_rows))
        return _result(
            definition,
            comparison_side=side,
            period=period,
            scope=scope,
            eligible_rows=eligible,
            denominator_rows=denominator_rows,
            numerator_ids=(str(row["metric_member_id"]) for row in denominator_rows),
            numerator=count,
            denominator=count,
            status=status,
            value=count,
            unavailable_reason_codes=reasons,
            decimal_places=decimal_places,
        )
    if reddit_indicator_id == "RV-BR-02":
        denominator_rows = [
            row
            for row in eligible
            if row.get("brand_eligible") is True
            and row.get("sentiment_classification_status") == "complete"
        ]
        numerator_rows = [
            row
            for row in denominator_rows
            if str(row.get("sentiment", "")).casefold() == "negative"
        ]
        return _rate_result(
            definition, side, period, scope, eligible, denominator_rows, numerator_rows,
            decimal_places=decimal_places,
        )
    if reddit_indicator_id == "RV-BR-03":
        denominator_rows = [
            row
            for row in eligible
            if row.get("brand_eligible") is True
            and row.get("sentiment_classification_status") == "complete"
            and str(row.get("sentiment", "")).casefold()
            in {"positive", "neutral", "negative"}
        ]
        signed_rows = [
            row
            for row in denominator_rows
            if str(row.get("sentiment", "")).casefold() in {"positive", "negative"}
        ]
        positive = sum(
            str(row.get("sentiment", "")).casefold() == "positive"
            for row in denominator_rows
        )
        negative = sum(
            str(row.get("sentiment", "")).casefold() == "negative"
            for row in denominator_rows
        )
        status, reasons = _sample_status(len(denominator_rows))
        numerator = Decimal(positive - negative)
        value = (
            _rate_value(numerator, Decimal(len(denominator_rows)), decimal_places)
            if status != "unavailable"
            else None
        )
        return _result(
            definition,
            comparison_side=side,
            period=period,
            scope=scope,
            eligible_rows=eligible,
            denominator_rows=denominator_rows,
            numerator_ids=(str(row["metric_member_id"]) for row in signed_rows),
            numerator=numerator,
            denominator=Decimal(len(denominator_rows)),
            status=status,
            value=value,
            unavailable_reason_codes=reasons,
            decimal_places=decimal_places,
        )
    if reddit_indicator_id == "RV-BR-04":
        denominator_rows = [row for row in eligible if row.get("brand_eligible") is True]
        scan_complete = context.get("recommendation_closed_set_scan_complete")
        if scan_complete is not True:
            if scan_complete is not None and scan_complete is not False:
                raise IndicatorComputationError(
                    "recommendation closed-set scan proof is invalid"
                )
            return _result(
                definition,
                comparison_side=side,
                period=period,
                scope=scope,
                eligible_rows=denominator_rows,
                denominator_rows=(),
                numerator_ids=(),
                numerator=Decimal(0),
                denominator=Decimal(0),
                status="unavailable",
                value=None,
                unavailable_reason_codes=(
                    "recommendation_closed_set_scan_completeness_unproven",
                ),
                decimal_places=decimal_places,
            )
        if any(
            row.get("recommendation_classification_status") != "complete"
            for row in denominator_rows
        ):
            return _result(
                definition,
                comparison_side=side,
                period=period,
                scope=scope,
                eligible_rows=denominator_rows,
                denominator_rows=(),
                numerator_ids=(),
                numerator=Decimal(0),
                denominator=Decimal(0),
                status="unavailable",
                value=None,
                unavailable_reason_codes=(
                    "recommendation_closed_set_scan_coverage_incomplete",
                ),
                decimal_places=decimal_places,
            )
        numerator_rows = [
            row
            for row in denominator_rows
            if row.get("recommendation_classification_status") == "complete"
            and str(row.get("recommendation", "")).casefold()
            in {"recommend", "recommended", "positive", "promoted"}
        ]
        evidence = (
            _recommendation_fact_ids(numerator_rows, facts)
            if numerator_rows
            else ()
        )
        return _rate_result(
            definition, side, period, scope, eligible, denominator_rows, numerator_rows,
            evidence_fact_ids=evidence, decimal_places=decimal_places,
        )
    if reddit_indicator_id == "RV-BR-05":
        return _compute_pair_difference(
            definition,
            rows=rows,
            context=context,
            period=period,
            scope=scope,
            comparison_side=side,
            decimal_places=decimal_places,
            kind="sentiment",
        )
    if reddit_indicator_id == "RV-PS-01":
        unavailable = _controlled_coverage_unavailable(
            definition, context, side, period, scope, decimal_places
        )
        if unavailable is not None:
            return unavailable
        proof = context.get("independent_parent_scope_eligibility_complete")
        if proof is not True:
            if proof is not None and proof is not False:
                raise IndicatorComputationError(
                    "independent parent-scope proof is invalid"
                )
            return _result(
                definition,
                comparison_side=side,
                period=period,
                scope=scope,
                eligible_rows=eligible,
                denominator_rows=(),
                numerator_ids=(),
                numerator=Decimal(0),
                denominator=Decimal(0),
                status="unavailable",
                value=None,
                unavailable_reason_codes=(
                    "independent_parent_scope_eligibility_evidence_unavailable",
                ),
                decimal_places=decimal_places,
            )
        product_scope = context.get("product_scope")
        if product_scope is not None and (
            not isinstance(product_scope, str) or not product_scope
        ):
            raise IndicatorComputationError("product scope context is invalid")
        denominator_rows = [
            row
            for row in eligible
            if row.get("independent_parent_scope_eligible") is True
            and (
                product_scope is None
                or row.get("independent_parent_scope") == product_scope
            )
        ]
        numerator_rows = [
            row
            for row in denominator_rows
            if row.get("product_bound") is True
            and (product_scope is None or row.get("product_scope") == product_scope)
        ]
        return _rate_result(
            definition, side, period, scope, eligible, denominator_rows, numerator_rows,
            decimal_places=decimal_places,
        )
    if reddit_indicator_id == "RV-PS-02":
        product_scope = context.get("product_scope")
        if product_scope is not None and (
            not isinstance(product_scope, str) or not product_scope
        ):
            raise IndicatorComputationError("product scope context is invalid")
        candidate_rows = [
            row
            for row in eligible
            if product_scope is None or row.get("product_scope") == product_scope
        ]
        denominator_rows, qualifying = _problem_members(candidate_rows, facts)
        numerator_ids = tuple(sorted(qualifying))
        # Preserve every governed negative product-problem fact consulted for
        # the AND decision, including a fact whose entity sentiment prevents it
        # from entering the numerator.
        evidence = [
            str(fact["fact_id"])
            for row in denominator_rows
            for fact in _negative_problem_facts(row, facts)
        ]
        status, reasons = _sample_status(len(denominator_rows))
        numerator = Decimal(len(numerator_ids))
        denominator = Decimal(len(denominator_rows))
        value = (
            _rate_value(numerator, denominator, decimal_places)
            if status != "unavailable"
            else None
        )
        return _result(
            definition,
            comparison_side=side,
            period=period,
            scope=scope,
            eligible_rows=eligible,
            denominator_rows=denominator_rows,
            numerator_ids=numerator_ids,
            numerator=numerator,
            denominator=denominator,
            status=status,
            value=value,
            evidence_fact_ids=evidence,
            unavailable_reason_codes=reasons,
            coverage_candidate_count=len(candidate_rows),
            coverage_processed_count=len(denominator_rows),
            decimal_places=decimal_places,
        )
    if reddit_indicator_id == "RV-PS-03":
        product_scope = context.get("product_scope")
        if product_scope is not None and (
            not isinstance(product_scope, str) or not product_scope
        ):
            raise IndicatorComputationError("product scope context is invalid")
        candidate_rows = [
            row
            for row in eligible
            if product_scope is None or row.get("product_scope") == product_scope
        ]
        denominator_rows, qualifying = _problem_members(candidate_rows, facts)
        tag_members: dict[str, set[str]] = {}
        evidence: set[str] = set()
        for member_id, problem_facts in qualifying.items():
            for fact in problem_facts:
                attributes = fact.get("attributes")
                tag_id = fact.get("tag_id")
                if tag_id is None and isinstance(attributes, Mapping):
                    tag_id = attributes.get("tag_id")
                if tag_id is None:
                    tag_id = fact.get("canonical_value")
                tag = _string(tag_id, "problem tag ID")
                tag_members.setdefault(tag, set()).add(member_id)
                evidence.add(str(fact["fact_id"]))
        status, reasons = _sample_status(len(denominator_rows))
        ranking = tuple(
            {
                "count": len(member_ids),
                "rate": format(
                    _round(
                        Decimal(len(member_ids)) * Decimal(100) / Decimal(len(denominator_rows)),
                        decimal_places,
                    ),
                    "f",
                ),
                "tag_id": tag_id,
            }
            for tag_id, member_ids in sorted(
                tag_members.items(),
                key=lambda item: (
                    -len(item[1]),
                    -(
                        Decimal(len(item[1])) / Decimal(len(denominator_rows))
                        if denominator_rows
                        else Decimal(0)
                    ),
                    item[0],
                ),
            )
        )
        numerator_ids = tuple(sorted(qualifying))
        if status != "unavailable" and not ranking:
            reasons = (*reasons, "no_qualifying_items")
        return _result(
            definition,
            comparison_side=side,
            period=period,
            scope=scope,
            eligible_rows=eligible,
            denominator_rows=denominator_rows,
            numerator_ids=numerator_ids,
            numerator=Decimal(len(numerator_ids)),
            denominator=Decimal(len(denominator_rows)),
            status=status,
            value=ranking if status != "unavailable" else None,
            evidence_fact_ids=evidence,
            unavailable_reason_codes=reasons,
            coverage_candidate_count=len(candidate_rows),
            coverage_processed_count=len(denominator_rows),
            decimal_places=decimal_places,
        )
    if reddit_indicator_id == "RV-PS-04":
        return _compute_pair_difference(
            definition,
            rows=rows,
            context=context,
            period=period,
            scope=scope,
            comparison_side=side,
            decimal_places=decimal_places,
            kind="problem",
            facts=facts,
        )
    if reddit_indicator_id == "RV-IN-01":
        denominator_rows = [
            row
            for row in eligible
            if row.get("brand_eligible") is True
            and row.get("priority_classification_status") == "complete"
        ]
        weights = {"none": Decimal("0"), "p2": Decimal("0.3"), "p1": Decimal("0.7"), "p0": Decimal("1")}
        weighted_rows: list[dict[str, object]] = []
        weight_sum = Decimal(0)
        for row in denominator_rows:
            priority = str(row.get("priority", "")).casefold()
            if priority not in weights:
                raise IndicatorComputationError("priority classification is invalid")
            weight_sum += weights[priority]
            if weights[priority] > 0:
                weighted_rows.append(row)
        status, reasons = _sample_status(len(denominator_rows))
        denominator = Decimal(len(denominator_rows))
        value = (
            _round(weight_sum * Decimal(100) / denominator, decimal_places)
            if status != "unavailable"
            else None
        )
        evidence = _fact_ids_for_rows(weighted_rows, "priority_fact_ids", facts)
        return _result(
            definition,
            comparison_side=side,
            period=period,
            scope=scope,
            eligible_rows=eligible,
            denominator_rows=denominator_rows,
            numerator_ids=(str(row["metric_member_id"]) for row in weighted_rows),
            numerator=weight_sum,
            denominator=denominator,
            status=status,
            value=value,
            evidence_fact_ids=evidence,
            unavailable_reason_codes=reasons,
            decimal_places=decimal_places,
        )
    if reddit_indicator_id == "RV-IN-02":
        return _compute_association(
            definition, eligible, context, side, period, scope, decimal_places,
        )
    if reddit_indicator_id == "RV-IN-03":
        return _compute_persona_difference(
            definition, eligible, context, side, period, scope, decimal_places,
        )
    if reddit_indicator_id == "RV-IN-04":
        return _compute_thread_amplification(
            definition, eligible, context, side, period, scope, decimal_places,
        )
    if reddit_indicator_id == "RV-IN-05":
        return _compute_acceleration(
            definition, eligible, context, side, period, scope, decimal_places,
        )
    if reddit_indicator_id == "RV-CI-01":
        unavailable = _controlled_coverage_unavailable(
            definition, context, side, period, scope, decimal_places
        )
        if unavailable is not None:
            return unavailable
        if "automation_audit_rows" in context:
            eligible = _context_rows(
                context["automation_audit_rows"], "automation audit rows"
            )
        denominator_rows = [row for row in eligible if row.get("automation_detected") is True]
        numerator_rows = [
            row
            for row in denominator_rows
            if row.get("excluded_reason") == "explicit_automation"
        ]
        return _rate_result(
            definition, side, period, scope, eligible, denominator_rows, numerator_rows,
            decimal_places=decimal_places,
        )
    if reddit_indicator_id == "RV-CI-02":
        if "commercial_audit_rows" in context:
            eligible = _context_rows(
                context["commercial_audit_rows"], "commercial audit rows"
            )
        denominator_rows = [row for row in eligible if _level(row, "commercial_level", "C") >= 1]
        numerator_rows = [row for row in denominator_rows if row.get("commercial_disclosed") is True]
        return _rate_result(
            definition, side, period, scope, eligible, denominator_rows, numerator_rows,
            decimal_places=decimal_places,
        )
    if reddit_indicator_id == "RV-CI-03":
        unavailable = _controlled_coverage_unavailable(
            definition, context, side, period, scope, decimal_places
        )
        if unavailable is not None:
            return unavailable
        qualifying = [
            row
            for row in eligible
            if _level(row, "commercial_level", "C") >= 2
            or _level(row, "integrity_level", "I") >= 2
        ]
        return _count_result(
            definition, side, period, scope, eligible, qualifying, decimal_places,
        )
    if reddit_indicator_id == "RV-CI-04":
        unavailable = _controlled_coverage_unavailable(
            definition, context, side, period, scope, decimal_places
        )
        if unavailable is not None:
            return unavailable
        qualifying = [row for row in eligible if _level(row, "integrity_level", "I") >= 3]
        return _count_result(
            definition, side, period, scope, eligible, qualifying, decimal_places,
        )
    if reddit_indicator_id == "RV-CI-05":
        unavailable = _controlled_coverage_unavailable(
            definition, context, side, period, scope, decimal_places
        )
        if unavailable is not None:
            return unavailable
        qualifying = [
            row
            for row in eligible
            if _level(row, "commercial_level", "C") >= 3
            and _level(row, "integrity_level", "I") >= 4
            and row.get("manual_confirmation") is True
        ]
        return _count_result(
            definition, side, period, scope, eligible, qualifying, decimal_places,
        )
    if reddit_indicator_id == "RV-CI-07":
        unavailable = _controlled_coverage_unavailable(
            definition, context, side, period, scope, decimal_places
        )
        if unavailable is not None:
            return unavailable
        unresolved = [
            row
            for row in eligible
            if row.get("review_status") in {"unresolved", "pending", "open"}
            and (
                _level(row, "commercial_level", "C") >= 2
                or _level(row, "integrity_level", "I") >= 2
            )
        ]
        buckets = {"0_7_days": 0, "8_30_days": 0, "31_plus_days": 0, "unknown": 0}
        for row in unresolved:
            age = row.get("age_days")
            if type(age) is not int or age < 0:
                buckets["unknown"] += 1
            elif age <= 7:
                buckets["0_7_days"] += 1
            elif age <= 30:
                buckets["8_30_days"] += 1
            else:
                buckets["31_plus_days"] += 1
        return _result(
            definition,
            comparison_side=side,
            period=period,
            scope=scope,
            eligible_rows=eligible,
            denominator_rows=unresolved,
            numerator_ids=(str(row["metric_member_id"]) for row in unresolved),
            numerator=Decimal(len(unresolved)),
            denominator=Decimal(len(unresolved)),
            status="available",
            value=buckets,
            decimal_places=decimal_places,
        )
    raise IndicatorComputationError("indicator computation is not implemented")


def _rate_result(
    definition: IndicatorDefinition,
    side: str,
    period: str,
    scope: str,
    eligible: Sequence[dict[str, object]],
    denominator_rows: Sequence[dict[str, object]],
    numerator_rows: Sequence[dict[str, object]],
    *,
    evidence_fact_ids: Iterable[str] = (),
    decimal_places: int,
) -> IndicatorResult:
    status, reasons = _status_for_definition(definition, len(denominator_rows))
    numerator = Decimal(len({str(row["metric_member_id"]) for row in numerator_rows}))
    denominator = Decimal(len({str(row["metric_member_id"]) for row in denominator_rows}))
    value = (
        _rate_value(numerator, denominator, decimal_places)
        if status != "unavailable"
        else None
    )
    return _result(
        definition,
        comparison_side=side,
        period=period,
        scope=scope,
        eligible_rows=eligible,
        denominator_rows=denominator_rows,
        numerator_ids=(str(row["metric_member_id"]) for row in numerator_rows),
        numerator=numerator,
        denominator=denominator,
        status=status,
        value=value,
        evidence_fact_ids=evidence_fact_ids,
        unavailable_reason_codes=reasons,
        decimal_places=decimal_places,
    )


def _count_result(
    definition: IndicatorDefinition,
    side: str,
    period: str,
    scope: str,
    eligible: Sequence[dict[str, object]],
    qualifying: Sequence[dict[str, object]],
    decimal_places: int,
) -> IndicatorResult:
    count = Decimal(len({str(row["metric_member_id"]) for row in qualifying}))
    return _result(
        definition,
        comparison_side=side,
        period=period,
        scope=scope,
        eligible_rows=eligible,
        denominator_rows=qualifying,
        numerator_ids=(str(row["metric_member_id"]) for row in qualifying),
        numerator=count,
        denominator=count,
        status="available",
        value=count,
        decimal_places=decimal_places,
    )


def _controlled_coverage_unavailable(
    definition: IndicatorDefinition,
    context: Mapping[str, object],
    side: str,
    period: str,
    scope: str,
    decimal_places: int,
) -> IndicatorResult | None:
    coverage_status = context.get("coverage_status", "complete")
    if coverage_status == "complete":
        return None
    if coverage_status != "unavailable":
        raise IndicatorComputationError("controlled coverage status is invalid")
    raw_reasons = context.get("reason_codes")
    if (
        not isinstance(raw_reasons, list)
        or not raw_reasons
        or any(not isinstance(value, str) or not value for value in raw_reasons)
    ):
        raise IndicatorComputationError(
            "controlled unavailable coverage lacks reason codes"
        )
    return _result(
        definition,
        comparison_side=side,
        period=period,
        scope=scope,
        eligible_rows=(),
        denominator_rows=(),
        numerator_ids=(),
        numerator=Decimal(0),
        denominator=Decimal(0),
        status="unavailable",
        value=None,
        unavailable_reason_codes=raw_reasons,
        decimal_places=decimal_places,
    )


def _level(row: Mapping[str, object], field: str, prefix: str) -> int:
    value = str(row.get(field, f"{prefix}0")).upper()
    if not value.startswith(prefix):
        raise IndicatorComputationError(f"{field} is invalid")
    try:
        return int(value[len(prefix) :])
    except ValueError as exc:
        raise IndicatorComputationError(f"{field} is invalid") from exc


def _context_rows(
    value: object,
    label: str,
) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise IndicatorComputationError(f"{label} must be an array")
    return _mapping_rows(value, label)


def _compute_pair_difference(
    definition: IndicatorDefinition,
    *,
    rows: Sequence[dict[str, object]],
    context: Mapping[str, object],
    period: str,
    scope: str,
    comparison_side: str,
    decimal_places: int,
    kind: str,
    facts: dict[str, dict[str, object]] | None = None,
) -> IndicatorResult:
    momcozy = (
        _context_rows(context["momcozy_observations"], "Momcozy observations")
        if "momcozy_observations" in context
        else [row for row in rows if str(row.get("brand", "")).casefold() == "momcozy"]
    )
    competitor = (
        _context_rows(context["competitor_observations"], "competitor observations")
        if "competitor_observations" in context
        else [row for row in rows if str(row.get("brand", "")).casefold() not in {"", "momcozy"}]
    )
    momcozy = [row for row in momcozy if row.get("metric_eligible", True) is True]
    competitor = [row for row in competitor if row.get("metric_eligible", True) is True]
    symmetric = context.get("profile_symmetric", False)
    if type(symmetric) is not bool:
        raise IndicatorComputationError("profile symmetry flag is invalid")
    if kind == "sentiment":
        left_den = [row for row in momcozy if row.get("sentiment_classification_status") == "complete"]
        right_den = [row for row in competitor if row.get("sentiment_classification_status") == "complete"]
        left_value = right_value = Decimal(0)
        numerator_ids: list[str] = []
        if left_den:
            left_value, _, left_ids = _balance(left_den, decimal_places + 4)
            numerator_ids.extend(left_ids)
        if right_den:
            right_value, _, right_ids = _balance(right_den, decimal_places + 4)
            numerator_ids.extend(right_ids)
        evidence: list[str] = []
    elif kind == "problem":
        left_den, left_problem = _problem_members(momcozy, facts)
        right_den, right_problem = _problem_members(competitor, facts)
        left_value = (
            Decimal(len(left_problem)) * Decimal(100) / Decimal(len(left_den))
            if left_den
            else Decimal(0)
        )
        right_value = (
            Decimal(len(right_problem)) * Decimal(100) / Decimal(len(right_den))
            if right_den
            else Decimal(0)
        )
        numerator_ids = sorted(set(left_problem) | set(right_problem))
        evidence = [
            str(fact["fact_id"])
            for mapping in (left_problem, right_problem)
            for problem_facts in mapping.values()
            for fact in problem_facts
        ]
    else:
        raise IndicatorComputationError("pair difference kind is invalid")
    combined = sorted(
        momcozy + competitor, key=lambda row: str(row["metric_member_id"])
    )
    denominator_rows = left_den + right_den
    reasons: list[str] = []
    if not left_den or not right_den:
        reasons.append("comparison_side_zero_denominator")
        status = "unavailable"
        value = None
    else:
        if len(left_den) < 30 or len(right_den) < 30:
            reasons.append("comparison_sample_below_30_each")
        if not symmetric:
            reasons.append("comparison_profile_not_symmetric")
        status = "provisional" if reasons else "available"
        value = _round(left_value - right_value, decimal_places)
    return _result(
        definition,
        comparison_side=comparison_side,
        period=period,
        scope=scope,
        eligible_rows=combined,
        denominator_rows=denominator_rows,
        numerator_ids=numerator_ids,
        numerator=left_value - right_value,
        denominator=Decimal(len(left_den) + len(right_den)),
        status=status,
        value=value,
        evidence_fact_ids=evidence,
        unavailable_reason_codes=reasons,
        decimal_places=decimal_places,
    )


def _id_set(value: object, label: str, eligible_ids: set[str]) -> set[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise IndicatorComputationError(f"{label} must be an array of IDs")
    result = set(value)
    if len(result) != len(value):
        raise IndicatorComputationError(f"{label} contains duplicate IDs")
    if not result <= eligible_ids:
        raise IndicatorComputationError(f"{label} is outside metric eligible IDs")
    return result


def _compute_association(
    definition: IndicatorDefinition,
    eligible: Sequence[dict[str, object]],
    context: Mapping[str, object],
    side: str,
    period: str,
    scope: str,
    decimal_places: int,
) -> IndicatorResult:
    eligible_ids = {str(row["metric_member_id"]) for row in eligible}
    tag_a = _id_set(context.get("tag_a_member_ids", []), "tag A members", eligible_ids)
    tag_b = _id_set(context.get("tag_b_member_ids", []), "tag B members", eligible_ids)
    both = tag_a & tag_b
    reasons: list[str] = []
    if not eligible_ids or not tag_a or not tag_b:
        reasons.append("association_zero_denominator")
        status = "unavailable"
        value = None
    else:
        if len(eligible_ids) < 30:
            reasons.append("association_total_below_30")
        if len(tag_a) < 10 or len(tag_b) < 10:
            reasons.append("association_margin_below_10")
        status = "provisional" if reasons else "available"
        value = _round(
            Decimal(len(both)) * Decimal(len(eligible_ids))
            / (Decimal(len(tag_a)) * Decimal(len(tag_b))),
            decimal_places,
        )
    denominator_rows = [row for row in eligible if str(row["metric_member_id"]) in tag_a | tag_b]
    return _result(
        definition,
        comparison_side=side,
        period=period,
        scope=scope,
        eligible_rows=eligible,
        denominator_rows=denominator_rows,
        numerator_ids=both,
        numerator=Decimal(len(both)),
        denominator=Decimal(len(eligible_ids)),
        status=status,
        value=value,
        unavailable_reason_codes=reasons,
        decimal_places=decimal_places,
    )


def _compute_persona_difference(
    definition: IndicatorDefinition,
    eligible: Sequence[dict[str, object]],
    context: Mapping[str, object],
    side: str,
    period: str,
    scope: str,
    decimal_places: int,
) -> IndicatorResult:
    eligible_ids = {str(row["metric_member_id"]) for row in eligible}
    cohort = _id_set(context.get("cohort_member_ids", []), "cohort members", eligible_ids)
    tagged = _id_set(context.get("tag_member_ids", []), "tag members", eligible_ids)
    reasons: list[str] = []
    if not eligible_ids or not cohort:
        reasons.append("persona_zero_denominator")
        status = "unavailable"
    else:
        if len(eligible_ids) < 30:
            reasons.append("persona_total_below_30")
        if len(cohort) < 10 or len(tagged) < 10:
            reasons.append("persona_margin_below_10")
        status = "provisional" if reasons else "available"
    difference = Decimal(0)
    if cohort and eligible_ids:
        difference = (
            Decimal(len(cohort & tagged)) * Decimal(100) / Decimal(len(cohort))
            - Decimal(len(tagged)) * Decimal(100) / Decimal(len(eligible_ids))
        )
    value = _round(difference, decimal_places) if status != "unavailable" else None
    denominator_rows = [row for row in eligible if str(row["metric_member_id"]) in cohort | tagged]
    return _result(
        definition,
        comparison_side=side,
        period=period,
        scope=scope,
        eligible_rows=eligible,
        denominator_rows=denominator_rows,
        numerator_ids=cohort & tagged,
        numerator=Decimal(len(cohort & tagged)),
        denominator=Decimal(len(cohort)),
        status=status,
        value=value,
        unavailable_reason_codes=reasons,
        decimal_places=decimal_places,
    )


def _compute_thread_amplification(
    definition: IndicatorDefinition,
    eligible: Sequence[dict[str, object]],
    context: Mapping[str, object],
    side: str,
    period: str,
    scope: str,
    decimal_places: int,
) -> IndicatorResult:
    thread_rows = (
        _context_rows(context["threads"], "thread observations")
        if "threads" in context
        else list(eligible)
    )
    complete = [row for row in thread_rows if row.get("coverage_complete") is True]
    tagged = [row for row in complete if row.get("tagged") is True]
    reasons: list[str] = []
    if not complete or not tagged:
        reasons.append("thread_group_zero_denominator")
        status = "unavailable"
    else:
        if len(complete) < 10 or len(tagged) < 10:
            reasons.append("thread_group_below_10")
        if len(complete) != len(thread_rows):
            reasons.append("thread_coverage_incomplete")
        status = "provisional" if reasons else "available"
    value = None
    tagged_mean = eligible_mean = Decimal(0)
    if complete:
        eligible_mean = sum(
            (_decimal(row.get("complete_comment_count", 0), "complete comment count") for row in complete),
            Decimal(0),
        ) / Decimal(len(complete))
    if tagged:
        tagged_mean = sum(
            (_decimal(row.get("complete_comment_count", 0), "complete comment count") for row in tagged),
            Decimal(0),
        ) / Decimal(len(tagged))
    if status != "unavailable":
        if eligible_mean == 0:
            status = "unavailable"
            reasons.append("zero_eligible_thread_mean")
            value = None
        else:
            value = _round(tagged_mean / eligible_mean, decimal_places)
    return _result(
        definition,
        comparison_side=side,
        period=period,
        scope=scope,
        eligible_rows=thread_rows,
        denominator_rows=complete,
        numerator_ids=(str(row["metric_member_id"]) for row in tagged),
        numerator=tagged_mean,
        denominator=eligible_mean,
        status=status,
        value=value,
        unavailable_reason_codes=reasons,
        decimal_places=decimal_places,
    )


def _compute_acceleration(
    definition: IndicatorDefinition,
    eligible: Sequence[dict[str, object]],
    context: Mapping[str, object],
    side: str,
    period: str,
    scope: str,
    decimal_places: int,
) -> IndicatorResult:
    periods = context.get("complete_periods", [])
    if not isinstance(periods, list):
        raise IndicatorComputationError("complete periods must be an array")
    hard_reasons: list[str] = []
    provisional_reasons: list[str] = []
    if context.get("comparison_contract_proven") is not True:
        hard_reasons.append("comparison_contract_not_proven")
    if context.get("current_period_complete") is not True:
        hard_reasons.append("current_period_incomplete")
    if len(periods) < 3:
        hard_reasons.append("fewer_than_three_complete_periods")
    expected_grain = ""
    expected_policy = ""
    expected_scope = ""
    if periods:
        expected_grain = _string(context.get("grain"), "acceleration grain")
        expected_policy = _string(
            context.get("metric_policy_version"), "acceleration metric policy"
        )
        expected_scope = _string(context.get("scope"), "acceleration scope")
    parsed: list[tuple[str, int]] = []
    profile_hashes: set[tuple[object, object, object]] = set()
    seen_periods: set[str] = set()
    for item in periods:
        if not isinstance(item, Mapping):
            raise IndicatorComputationError("complete period row must be an object")
        period_id = _string(item.get("period"), "complete period")
        count = item.get("eligible_volume")
        if type(count) is not int or count < 0:
            raise IndicatorComputationError("period eligible volume is invalid")
        if item.get("complete") is not True:
            hard_reasons.append("period_incomplete")
        if item.get("grain") != expected_grain:
            hard_reasons.append("period_grain_mismatch")
        if item.get("metric_policy_version") != expected_policy:
            hard_reasons.append("period_metric_policy_mismatch")
        if item.get("scope") != expected_scope:
            hard_reasons.append("period_scope_mismatch")
        if item.get("unit") != "count":
            hard_reasons.append("period_unit_mismatch")
        if count < 10:
            provisional_reasons.append("period_sample_below_10")
        profile_tuple = (
            item.get("source_selection_profile_hash"),
            item.get("coverage_profile_hash"),
            item.get("retrieval_contract_hash"),
        )
        if any(
            not isinstance(value, str) or HEX64.fullmatch(value) is None
            for value in profile_tuple
        ):
            hard_reasons.append("period_profile_hash_invalid")
        profile_hashes.add(profile_tuple)
        if period_id in seen_periods:
            hard_reasons.append("duplicate_complete_period")
        seen_periods.add(period_id)
        parsed.append((period_id, count))
    if len(profile_hashes) > 1:
        hard_reasons.append("period_profiles_not_symmetric")
    parsed.sort(key=lambda item: item[0])
    reasons = [*hard_reasons, *provisional_reasons]
    status = (
        "unavailable"
        if hard_reasons
        else "provisional"
        if provisional_reasons
        else "available"
    )
    acceleration = Decimal(0)
    if len(parsed) >= 3:
        last = parsed[-3:]
        logs = [Decimal(str(log1p(count))) for _, count in last]
        acceleration = logs[2] - Decimal(2) * logs[1] + logs[0]
    value = _round(acceleration, decimal_places) if status != "unavailable" else None
    return _result(
        definition,
        comparison_side=side,
        period=period,
        scope=scope,
        eligible_rows=eligible,
        denominator_rows=eligible,
        numerator_ids=(),
        numerator=acceleration,
        denominator=Decimal(len(parsed)),
        status=status,
        value=value,
        unavailable_reason_codes=reasons,
        decimal_places=decimal_places,
    )


def _compute_sensitivity(
    definition: IndicatorDefinition,
    *,
    context: Mapping[str, object],
    period: str,
    scope: str,
    decimal_places: int,
) -> IndicatorResult:
    raw = context.get("target_raw")
    qualified = context.get("target_qualified")
    if not isinstance(raw, Mapping) or not isinstance(qualified, Mapping):
        reasons = ("sensitivity_target_missing",)
        return _result(
            definition,
            comparison_side="raw_observed",
            period=period,
            scope=scope,
            eligible_rows=(),
            denominator_rows=(),
            numerator_ids=(),
            numerator=Decimal(0),
            denominator=Decimal(0),
            status="unavailable",
            value=None,
            unavailable_reason_codes=reasons,
            unit="inherit",
            decimal_places=decimal_places,
        )
    target_id = raw.get("reddit_indicator_id")
    if target_id != qualified.get("reddit_indicator_id") or not isinstance(target_id, str):
        raise IndicatorComputationError("sensitivity target identity mismatch")
    unit = raw.get("unit")
    shape = raw.get("output_shape")
    if unit != qualified.get("unit") or shape != qualified.get("output_shape"):
        raise IndicatorComputationError("sensitivity target unit or shape mismatch")
    if shape != "scalar" or unit in {"count", "rank", "buckets", "object", None}:
        raise IndicatorComputationError("sensitivity target is not a rate or index")
    if target_id in {"RV-BR-01", "RV-PS-03"}:
        raise IndicatorComputationError("sensitivity target is not a rate or index")
    raw_status = raw.get("status")
    qualified_status = qualified.get("status")
    allowed_status = {"available", "provisional", "unavailable"}
    if raw_status not in allowed_status or qualified_status not in allowed_status:
        raise IndicatorComputationError("sensitivity target status is invalid")
    status = (
        "unavailable"
        if "unavailable" in {raw_status, qualified_status}
        else "provisional"
        if "provisional" in {raw_status, qualified_status}
        else "available"
    )
    reason_codes: list[str] = []
    if status == "unavailable":
        reason_codes.append("sensitivity_target_unavailable")
        difference = Decimal(0)
        value = None
    else:
        difference = _decimal(raw.get("value"), "raw target value") - _decimal(
            qualified.get("value"), "qualified target value"
        )
        value = _round(difference, decimal_places)
    derived_unit = "pp" if unit in {"percent", "pp", "rate"} else "score_points"
    return _result(
        definition,
        comparison_side="raw_observed",
        period=period,
        scope=scope,
        eligible_rows=(),
        denominator_rows=(),
        numerator_ids=(),
        numerator=difference,
        denominator=Decimal(0),
        status=status,
        value=value,
        unavailable_reason_codes=reason_codes,
        unit=derived_unit,
        decimal_places=decimal_places,
    )


def registry_sha256(path: Path) -> str:
    payload = Path(path).read_bytes()
    # Parsing first prevents a digest from blessing invalid bytes.
    load_indicator_registry(path)
    return sha256(payload).hexdigest()
