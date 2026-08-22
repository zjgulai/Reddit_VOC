from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Iterable, Iterator, Mapping

from reddit_voc.v3_canonical_identity import (
    CanonicalIdentityError,
    canonical_comment_fullname,
    canonical_post_fullname,
)
from reddit_voc.v3_voc_facts import VocRecord


POLICY_SCHEMA_VERSION = "reddit_voc_metric_eligibility_policy_v1"
ROW_SCHEMA_VERSION = "reddit_voc_metric_eligibility_member_v1"
EXPECTED_BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}
COMPARISON_SIDES = {
    "baseline",
    "competitor_union",
    "current",
    "momcozy",
    "not_applicable",
    "qualified_organic",
    "raw_observed",
}
VOC_TYPES = {"comment_context_voc", "post_voc"}
MEMBER_TYPES = {
    "canonical_entity",
    "cluster",
    "event_dossier",
    "review_item",
    "thread",
}
INDICATOR_ID = re.compile(r"^RV-(DH|BR|PS|IN|CI)-[0-9]{2}$")
ORGANIC_EXCLUSION_FAMILIES = frozenset({"RV-BR", "RV-IN", "RV-PS"})
ORGANIC_EXCLUSION_REASONS = frozenset({"explicit_automation"})


class MetricEligibilityError(ValueError):
    """A metric eligibility policy or membership ledger is invalid."""


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
        raise MetricEligibilityError("value is not canonical JSON serializable") from exc


@dataclass(frozen=True)
class IndicatorEligibilityPolicy:
    reddit_indicator_id: str
    metric_family: str
    comparison_sides: tuple[str, ...]
    voc_types: tuple[str, ...]
    required_source_use: str | None
    text_required: bool
    metric_member_type: str = "canonical_entity"


@dataclass(frozen=True)
class MetricEligibilityPolicy:
    policy_version: str
    comparison_sides: tuple[str, ...]
    indicators: tuple[IndicatorEligibilityPolicy, ...]
    boundaries: dict[str, bool]
    schema_version: str = POLICY_SCHEMA_VERSION


@dataclass(frozen=True)
class EligibilityRow:
    metric_member_type: str
    metric_member_id: str
    reddit_indicator_id: str
    comparison_side: str
    period: str
    scope: str
    voc_type: str
    metric_family: str
    status: str
    anchor_source: str
    reason_codes: tuple[str, ...]
    policy_version: str
    denominator_member: bool
    numerator_member: bool | str
    membership_role: str
    schema_version: str = ROW_SCHEMA_VERSION

    @property
    def primary_key(self) -> tuple[str, ...]:
        return (
            self.metric_member_type,
            self.metric_member_id,
            self.reddit_indicator_id,
            self.comparison_side,
            self.period,
            self.scope,
            self.voc_type,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "anchor_source": self.anchor_source,
            "comparison_side": self.comparison_side,
            "denominator_member": self.denominator_member,
            "membership_role": self.membership_role,
            "metric_family": self.metric_family,
            "metric_member_id": self.metric_member_id,
            "metric_member_type": self.metric_member_type,
            "numerator_member": self.numerator_member,
            "period": self.period,
            "policy_version": self.policy_version,
            "reason_codes": list(self.reason_codes),
            "reddit_indicator_id": self.reddit_indicator_id,
            "schema_version": self.schema_version,
            "scope": self.scope,
            "status": self.status,
            "voc_type": self.voc_type,
        }


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise MetricEligibilityError(f"{label} must be a non-empty string")
    return value


def _unique_strings(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise MetricEligibilityError(f"{label} must be a non-empty array")
    result: list[str] = []
    for item in value:
        text = _string(item, label)
        if text in result:
            raise MetricEligibilityError(f"{label} contains a duplicate value")
        result.append(text)
    return tuple(result)


def parse_metric_eligibility_policy(value: object) -> MetricEligibilityPolicy:
    if not isinstance(value, Mapping):
        raise MetricEligibilityError("metric eligibility policy must be an object")
    required = {
        "boundaries",
        "comparison_sides",
        "indicators",
        "policy_version",
        "schema_version",
    }
    if set(value) != required:
        raise MetricEligibilityError("metric eligibility policy fields are invalid")
    if value.get("schema_version") != POLICY_SCHEMA_VERSION:
        raise MetricEligibilityError("metric eligibility policy schema is unsupported")
    if value.get("boundaries") != EXPECTED_BOUNDARIES:
        raise MetricEligibilityError("metric eligibility boundaries are invalid")
    policy_version = _string(value.get("policy_version"), "policy version")
    sides = _unique_strings(value.get("comparison_sides"), "comparison sides")
    if set(sides) - COMPARISON_SIDES:
        raise MetricEligibilityError("comparison side is unsupported")
    raw_indicators = value.get("indicators")
    if not isinstance(raw_indicators, list) or not raw_indicators:
        raise MetricEligibilityError("indicators must be a non-empty array")
    indicators: list[IndicatorEligibilityPolicy] = []
    seen: set[str] = set()
    for ordinal, raw in enumerate(raw_indicators, start=1):
        if not isinstance(raw, Mapping):
            raise MetricEligibilityError(f"indicator {ordinal} must be an object")
        allowed_fields = {
            "comparison_sides",
            "metric_family",
            "metric_member_type",
            "reddit_indicator_id",
            "required_source_use",
            "text_required",
            "voc_types",
        }
        if set(raw) - allowed_fields or not {
            "comparison_sides",
            "metric_family",
            "reddit_indicator_id",
            "required_source_use",
            "text_required",
            "voc_types",
        }.issubset(raw):
            raise MetricEligibilityError(f"indicator {ordinal} fields are invalid")
        indicator_id = _string(raw.get("reddit_indicator_id"), "indicator ID")
        if not indicator_id.isascii() or INDICATOR_ID.fullmatch(indicator_id) is None:
            raise MetricEligibilityError("indicator ID is invalid")
        if indicator_id in seen:
            raise MetricEligibilityError(f"duplicate indicator ID:{indicator_id}")
        seen.add(indicator_id)
        family = _string(raw.get("metric_family"), "metric family")
        if family != indicator_id.rsplit("-", 1)[0]:
            raise MetricEligibilityError("metric family does not match indicator ID")
        indicator_sides = _unique_strings(
            raw.get("comparison_sides"), f"{indicator_id} comparison sides"
        )
        if set(indicator_sides) - set(sides):
            raise MetricEligibilityError("indicator comparison side is not registered")
        voc_types = _unique_strings(raw.get("voc_types"), f"{indicator_id} VOC types")
        if set(voc_types) - VOC_TYPES:
            raise MetricEligibilityError("indicator VOC type is unsupported")
        source_use = raw.get("required_source_use")
        if source_use is not None:
            source_use = _string(source_use, "required source use")
        if type(raw.get("text_required")) is not bool:
            raise MetricEligibilityError("text_required must be a boolean")
        member_type = raw.get("metric_member_type", "canonical_entity")
        member_type = _string(member_type, "metric member type")
        if member_type not in MEMBER_TYPES:
            raise MetricEligibilityError("metric member type is unsupported")
        indicators.append(
            IndicatorEligibilityPolicy(
                reddit_indicator_id=indicator_id,
                metric_family=family,
                comparison_sides=indicator_sides,
                voc_types=voc_types,
                required_source_use=source_use,
                text_required=raw["text_required"],
                metric_member_type=member_type,
            )
        )
    indicators.sort(key=lambda item: item.reddit_indicator_id)
    return MetricEligibilityPolicy(
        policy_version=policy_version,
        comparison_sides=sides,
        indicators=tuple(indicators),
        boundaries=dict(EXPECTED_BOUNDARIES),
    )


def load_metric_eligibility_policy(path: Path) -> MetricEligibilityPolicy:
    try:
        payload = Path(path).read_bytes()
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MetricEligibilityError("metric eligibility policy is unreadable") from exc
    if payload != canonical_json_bytes(value) + b"\n":
        raise MetricEligibilityError("metric eligibility policy is not canonical JSON")
    return parse_metric_eligibility_policy(value)


def _membership_override(
    memberships: Mapping[tuple[str, str, str], Mapping[str, object]],
    key: tuple[str, str, str],
) -> tuple[bool, bool | str, str] | None:
    value = memberships.get(key)
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {
        "denominator_member",
        "membership_role",
        "numerator_member",
    }:
        raise MetricEligibilityError("membership override fields are invalid")
    denominator = value.get("denominator_member")
    numerator = value.get("numerator_member")
    role = value.get("membership_role")
    if type(denominator) is not bool:
        raise MetricEligibilityError("denominator membership must be a boolean")
    if type(numerator) is not bool and numerator != "not_applicable":
        raise MetricEligibilityError("numerator membership is invalid")
    if numerator is True and denominator is not True:
        raise MetricEligibilityError("numerator member is outside denominator")
    normalized_numerator: bool | str = (
        numerator if type(numerator) is bool else "not_applicable"
    )
    return denominator, normalized_numerator, _string(role, "membership role")


def _source_reasons(voc: VocRecord, indicator: IndicatorEligibilityPolicy) -> list[str]:
    reasons: list[str] = []
    if indicator.text_required and voc.analysis_text_status != "ready":
        reasons.append("analysis_text_incomplete")
    required = indicator.required_source_use
    if required is not None:
        policy = voc.source_policy
        governed_default = policy.get("governed_base_default") is True
        allowed = policy.get("allowed_metric_families")
        blocked = policy.get("blocked_uses")
        if not isinstance(blocked, list) or any(not isinstance(item, str) for item in blocked):
            raise MetricEligibilityError("VOC blocked uses are invalid")
        if allowed is not None and (
            not isinstance(allowed, list)
            or any(not isinstance(item, str) for item in allowed)
        ):
            raise MetricEligibilityError("VOC allowed source uses are invalid")
        if not governed_default and (not isinstance(allowed, list) or required not in allowed):
            reasons.append("source_use_not_allowed")
        if required in blocked and "source_use_not_allowed" not in reasons:
            reasons.append("source_use_not_allowed")
    return reasons


def _validated_organic_exclusions(
    value: Mapping[str, str] | None,
) -> Mapping[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise MetricEligibilityError("organic exclusions must be an object")
    result: dict[str, str] = {}
    for entity_id, reason in value.items():
        if (
            not isinstance(entity_id, str)
            or re.fullmatch(r"t[13]_[a-z0-9]+", entity_id) is None
        ):
            raise MetricEligibilityError("organic exclusion identity is invalid")
        if reason not in ORGANIC_EXCLUSION_REASONS:
            raise MetricEligibilityError("organic exclusion reason is unsupported")
        result[entity_id] = reason
    return result


def organic_exclusion_reason(
    *,
    metric_member_id: str,
    metric_family: str,
    organic_exclusions: Mapping[str, str] | None,
) -> str | None:
    exclusions = _validated_organic_exclusions(organic_exclusions)
    if metric_family not in ORGANIC_EXCLUSION_FAMILIES:
        return None
    return exclusions.get(metric_member_id)


def _validated_sorted_vocs(vocs: Iterable[VocRecord]) -> list[VocRecord]:
    values: list[VocRecord] = []
    seen_entities: set[str] = set()
    for voc in vocs:
        if not isinstance(voc, VocRecord):
            raise MetricEligibilityError("eligibility input must contain VocRecord values")
        if voc.canonical_entity_id in seen_entities:
            raise MetricEligibilityError("duplicate eligibility entity")
        seen_entities.add(voc.canonical_entity_id)
        try:
            expected = (
                canonical_post_fullname(voc.canonical_entity_id)
                if voc.voc_type == "post_voc"
                else canonical_comment_fullname(voc.canonical_entity_id)
            )
        except CanonicalIdentityError as exc:
            raise MetricEligibilityError("VOC canonical entity identity is invalid") from exc
        if expected != voc.canonical_entity_id:
            raise MetricEligibilityError("VOC canonical entity identity mismatch")
        values.append(voc)
    values.sort(key=lambda value: value.canonical_entity_id)
    return values


def iter_metric_eligibility(
    vocs: Iterable[VocRecord],
    policy: MetricEligibilityPolicy,
    *,
    period: str,
    scope: str,
    memberships: Mapping[tuple[str, str, str], Mapping[str, object]] | None = None,
    organic_exclusions: Mapping[str, str] | None = None,
) -> Iterator[EligibilityRow]:
    period = _string(period, "period")
    scope = _string(scope, "scope")
    memberships = {} if memberships is None else memberships
    if not isinstance(memberships, Mapping):
        raise MetricEligibilityError("memberships must be an object")
    governed_organic_exclusions = _validated_organic_exclusions(organic_exclusions)
    matched_overrides: set[tuple[str, str, str]] = set()
    previous_primary_key: tuple[str, ...] | None = None
    for voc in _validated_sorted_vocs(vocs):
        for indicator in sorted(
            policy.indicators, key=lambda value: value.reddit_indicator_id
        ):
            if indicator.metric_member_type != "canonical_entity" or voc.voc_type not in indicator.voc_types:
                continue
            for side in sorted(indicator.comparison_sides):
                reasons = _source_reasons(voc, indicator)
                organic_reason = (
                    governed_organic_exclusions.get(voc.canonical_entity_id)
                    if indicator.metric_family in ORGANIC_EXCLUSION_FAMILIES
                    else None
                )
                if organic_reason is not None:
                    reasons.append(organic_reason)
                if side in {"momcozy", "competitor_union"}:
                    reasons.append("brand_routing_pending")
                if side in {"current", "baseline"}:
                    reasons.append("period_binding_pending")
                reasons = sorted(set(reasons))
                status = "excluded" if reasons else "eligible"
                denominator = False
                numerator: bool | str = "not_applicable"
                membership_role = "excluded" if reasons else "eligible_candidate"
                key = (
                    indicator.reddit_indicator_id,
                    side,
                    voc.canonical_entity_id,
                )
                override = _membership_override(memberships, key)
                if override is not None:
                    matched_overrides.add(key)
                    if status != "eligible":
                        raise MetricEligibilityError(
                            "excluded entity cannot receive metric membership"
                        )
                    denominator, numerator, membership_role = override
                row = EligibilityRow(
                    metric_member_type="canonical_entity",
                    metric_member_id=voc.canonical_entity_id,
                    reddit_indicator_id=indicator.reddit_indicator_id,
                    comparison_side=side,
                    period=period,
                    scope=scope,
                    voc_type=voc.voc_type,
                    metric_family=indicator.metric_family,
                    status=status,
                    anchor_source=voc.anchor_source,
                    reason_codes=tuple(reasons or ["structurally_eligible"]),
                    policy_version=policy.policy_version,
                    denominator_member=denominator,
                    numerator_member=numerator,
                    membership_role=membership_role,
                )
                if row.primary_key == previous_primary_key:
                    raise MetricEligibilityError("duplicate eligibility primary key")
                previous_primary_key = row.primary_key
                yield row
    if set(memberships) - matched_overrides:
        raise MetricEligibilityError("membership override has no eligible policy row")


def materialize_metric_eligibility(
    vocs: Iterable[VocRecord],
    policy: MetricEligibilityPolicy,
    *,
    period: str,
    scope: str,
    memberships: Mapping[tuple[str, str, str], Mapping[str, object]] | None = None,
    organic_exclusions: Mapping[str, str] | None = None,
) -> list[EligibilityRow]:
    rows = list(
        iter_metric_eligibility(
            vocs,
            policy,
            period=period,
            scope=scope,
            memberships=memberships,
            organic_exclusions=organic_exclusions,
        )
    )
    validate_subset_contract(rows)
    return rows


def summarize_metric_eligibility(
    vocs: Iterable[VocRecord],
    policy: MetricEligibilityPolicy,
    *,
    period: str,
    scope: str,
    memberships: Mapping[tuple[str, str, str], Mapping[str, object]] | None = None,
    organic_exclusions: Mapping[str, str] | None = None,
) -> dict[str, object]:
    membership_rows = 0
    eligible_rows = 0
    excluded_rows = 0
    denominator_true_rows = 0
    numerator_true_rows = 0
    distinct_eligible_post_vocs = 0
    distinct_eligible_comment_context_vocs = 0
    distinct_eligible_voc_facts = 0
    eligible_identity_hash = sha256()
    current_identity: str | None = None
    current_voc_type: str | None = None
    current_identity_is_eligible = False

    def finish_identity() -> None:
        nonlocal distinct_eligible_post_vocs
        nonlocal distinct_eligible_comment_context_vocs
        nonlocal distinct_eligible_voc_facts
        if current_identity is None or not current_identity_is_eligible:
            return
        eligible_identity_hash.update(current_identity.encode("ascii") + b"\n")
        distinct_eligible_voc_facts += 1
        if current_voc_type == "post_voc":
            distinct_eligible_post_vocs += 1
        elif current_voc_type == "comment_context_voc":
            distinct_eligible_comment_context_vocs += 1
        else:
            raise MetricEligibilityError("eligible VOC type is unsupported")

    for row in iter_metric_eligibility(
        vocs,
        policy,
        period=period,
        scope=scope,
        memberships=memberships,
        organic_exclusions=organic_exclusions,
    ):
        if row.metric_member_id != current_identity:
            finish_identity()
            current_identity = row.metric_member_id
            current_voc_type = row.voc_type
            current_identity_is_eligible = False
        elif row.voc_type != current_voc_type:
            raise MetricEligibilityError("eligibility identity has conflicting VOC types")
        membership_rows += 1
        if row.status == "eligible":
            eligible_rows += 1
            current_identity_is_eligible = True
        elif row.status == "excluded":
            excluded_rows += 1
        else:
            raise MetricEligibilityError("eligibility status is invalid")
        if row.denominator_member is True:
            denominator_true_rows += 1
        if row.numerator_member is True:
            numerator_true_rows += 1
    finish_identity()

    return {
        "membership_rows": membership_rows,
        "eligible_rows": eligible_rows,
        "excluded_rows": excluded_rows,
        "denominator_true_rows": denominator_true_rows,
        "numerator_true_rows": numerator_true_rows,
        "distinct_eligible_post_vocs": distinct_eligible_post_vocs,
        "distinct_eligible_comment_context_vocs": (
            distinct_eligible_comment_context_vocs
        ),
        "distinct_eligible_voc_facts": distinct_eligible_voc_facts,
        "eligible_identity_lf_sha256": eligible_identity_hash.hexdigest(),
        "period": _string(period, "period"),
        "scope": _string(scope, "scope"),
    }


def _row_value(value: EligibilityRow | Mapping[str, object]) -> Mapping[str, object]:
    if isinstance(value, EligibilityRow):
        return value.as_dict()
    if not isinstance(value, Mapping):
        raise MetricEligibilityError("eligibility ledger row must be an object")
    return value


def validate_subset_contract(
    rows: Iterable[EligibilityRow | Mapping[str, object]],
) -> None:
    seen: set[tuple[object, ...]] = set()
    eligible: dict[tuple[object, ...], set[str]] = {}
    denominator: dict[tuple[object, ...], set[str]] = {}
    numerator: dict[tuple[object, ...], set[str]] = {}
    for raw in rows:
        row = _row_value(raw)
        required = {
            "anchor_source",
            "comparison_side",
            "denominator_member",
            "membership_role",
            "metric_family",
            "metric_member_id",
            "metric_member_type",
            "numerator_member",
            "period",
            "policy_version",
            "reason_codes",
            "reddit_indicator_id",
            "schema_version",
            "scope",
            "status",
            "voc_type",
        }
        if set(row) != required or row.get("schema_version") != ROW_SCHEMA_VERSION:
            raise MetricEligibilityError("eligibility ledger row fields are invalid")
        member_type = _string(row.get("metric_member_type"), "metric member type")
        if member_type not in MEMBER_TYPES:
            raise MetricEligibilityError("metric member type is unsupported")
        voc_type = _string(row.get("voc_type"), "VOC type")
        if voc_type not in VOC_TYPES:
            raise MetricEligibilityError("VOC type is unsupported")
        member_id = _string(row.get("metric_member_id"), "metric member ID")
        if member_type == "canonical_entity":
            try:
                canonical = (
                    canonical_post_fullname(member_id)
                    if voc_type == "post_voc"
                    else canonical_comment_fullname(member_id)
                )
            except CanonicalIdentityError as exc:
                raise MetricEligibilityError("metric member identity is invalid") from exc
            if canonical != member_id:
                raise MetricEligibilityError("metric member identity is not canonical")
        elif member_id.lower().startswith(("t1_", "t3_")):
            raise MetricEligibilityError(
                "non-entity metric member may not impersonate a Reddit entity"
            )
        indicator_id = _string(row.get("reddit_indicator_id"), "indicator ID")
        if not indicator_id.isascii() or INDICATOR_ID.fullmatch(indicator_id) is None:
            raise MetricEligibilityError("indicator ID is invalid")
        metric_family = _string(row.get("metric_family"), "metric family")
        if metric_family != indicator_id.rsplit("-", 1)[0]:
            raise MetricEligibilityError("metric family does not match indicator ID")
        _string(row.get("anchor_source"), "anchor source")
        _string(row.get("membership_role"), "membership role")
        _string(row.get("policy_version"), "policy version")
        side = _string(row.get("comparison_side"), "comparison side")
        if side not in COMPARISON_SIDES:
            raise MetricEligibilityError("comparison side is unsupported")
        status = row.get("status")
        if status not in {"eligible", "excluded"}:
            raise MetricEligibilityError("eligibility status is invalid")
        denominator_member = row.get("denominator_member")
        numerator_member = row.get("numerator_member")
        if type(denominator_member) is not bool:
            raise MetricEligibilityError("denominator membership must be a boolean")
        if type(numerator_member) is not bool and numerator_member != "not_applicable":
            raise MetricEligibilityError("numerator membership is invalid")
        if status == "excluded" and (
            denominator_member is True or numerator_member is True
        ):
            raise MetricEligibilityError("excluded member cannot enter numerator or denominator")
        reasons = row.get("reason_codes")
        if (
            not isinstance(reasons, list)
            or not reasons
            or any(not isinstance(item, str) or not item for item in reasons)
            or len(set(reasons)) != len(reasons)
        ):
            raise MetricEligibilityError("reason codes are invalid")
        key = (
            member_type,
            member_id,
            indicator_id,
            side,
            _string(row.get("period"), "period"),
            _string(row.get("scope"), "scope"),
            voc_type,
        )
        if key in seen:
            raise MetricEligibilityError("duplicate eligibility primary key")
        seen.add(key)
        group = (member_type, indicator_id, side, key[4], key[5], voc_type)
        if status == "eligible":
            eligible.setdefault(group, set()).add(member_id)
        if denominator_member:
            denominator.setdefault(group, set()).add(member_id)
        if numerator_member is True:
            numerator.setdefault(group, set()).add(member_id)
    for group in set(eligible) | set(denominator) | set(numerator):
        eligible_ids = eligible.get(group, set())
        denominator_ids = denominator.get(group, set())
        numerator_ids = numerator.get(group, set())
        if not numerator_ids <= denominator_ids:
            raise MetricEligibilityError("numerator IDs are outside denominator IDs")
        if not denominator_ids <= eligible_ids:
            raise MetricEligibilityError("denominator IDs are outside eligible IDs")
