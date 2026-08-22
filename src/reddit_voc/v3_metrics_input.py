"""Materialize a source-bound metrics input from governed V3 artifacts.

This bridge never classifies text.  It converts independently validated VOC,
automation, canonical-identity and governed atomic-fact rows into the narrow
shape consumed by :mod:`reddit_voc.v3_indicators`.  Missing classifier or
ledger coverage is represented as ``unprocessed``/``unavailable`` rather than
as a fabricated zero.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence

from reddit_voc.v3_indicators import IndicatorRegistry
from reddit_voc.v3_metric_eligibility import validate_subset_contract


INPUT_SCHEMA_VERSION = "reddit_voc_metrics_input_v1"
INPUT_MANIFEST_SCHEMA_VERSION = "reddit_voc_metrics_input_manifest_v1"
EXPECTED_BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}
FACT_TYPES = frozenset(
    {
        "commercial_relation_fact",
        "community_governance_fact",
        "entity_brand_fact",
        "entity_problem_fact",
        "entity_product_fact",
        "entity_sentiment_fact",
        "entity_tag_fact",
        "integrity_signal_fact",
    }
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class MetricsInputError(ValueError):
    """The source rows cannot form a governed metrics input."""


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
        raise MetricsInputError("value is not canonical JSON serializable") from exc


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise MetricsInputError(f"{label} must be a non-empty string")
    return value


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or HEX64.fullmatch(value) is None:
        raise MetricsInputError(f"{label} must be lowercase SHA-256")
    return value


def _canonical_rows(
    values: Iterable[Mapping[str, object]], label: str, identity_field: str
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in values:
        if not isinstance(raw, Mapping):
            raise MetricsInputError(f"{label} row must be an object")
        row = dict(raw)
        identity = _string(row.get(identity_field), f"{label} identity")
        if identity in seen:
            raise MetricsInputError(f"duplicate {label} identity")
        seen.add(identity)
        rows.append(row)
    rows.sort(key=lambda row: str(row[identity_field]))
    return rows


def _validate_event_time(row: Mapping[str, object]) -> dict[str, object]:
    precision = row.get("event_time_precision")
    instant = row.get("event_created_at_utc")
    calendar_date = row.get("source_calendar_date")
    timezone_status = row.get("source_timezone_status")
    if precision in {"instant", "hour"}:
        if not isinstance(instant, str) or not instant or calendar_date is not None:
            raise MetricsInputError("instant/hour VOC time contract is invalid")
    elif precision == "day":
        if instant is not None or not isinstance(calendar_date, str) or not calendar_date:
            raise MetricsInputError("floating day VOC time contract is invalid")
        if "T" in calendar_date or ":" in calendar_date:
            raise MetricsInputError("floating day was converted into a timestamp")
    else:
        raise MetricsInputError("VOC event time precision is unsupported")
    return {
        "event_created_at_utc": instant,
        "event_time_precision": precision,
        "source_calendar_date": calendar_date,
        "source_timezone_status": timezone_status,
    }


def _promoted_facts(
    facts: Iterable[Mapping[str, object]],
    *,
    voc_by_id: Mapping[str, Mapping[str, object]],
    automation_voc_ids: set[str],
    source_snapshot_id: str,
) -> tuple[list[dict[str, object]], dict[str, list[dict[str, object]]], dict[str, int]]:
    promoted: list[dict[str, object]] = []
    by_entity: dict[str, list[dict[str, object]]] = defaultdict(list)
    seen: set[str] = set()
    statuses = {"held": 0, "promoted": 0, "rejected": 0}
    for raw in facts:
        if not isinstance(raw, Mapping):
            raise MetricsInputError("governed fact must be an object")
        row = dict(raw)
        fact_id = _string(row.get("fact_id"), "fact ID")
        if fact_id in seen:
            raise MetricsInputError("duplicate governed fact ID")
        seen.add(fact_id)
        status = row.get("decision_status")
        if status not in statuses:
            raise MetricsInputError("governed fact status is invalid")
        statuses[str(status)] += 1
        fact_type = row.get("fact_type")
        voc_id = row.get("voc_id")
        entity_id = row.get("canonical_entity_id")
        if (
            fact_type not in FACT_TYPES
            or not isinstance(voc_id, str)
            or voc_id not in voc_by_id
            or voc_id in automation_voc_ids
            or entity_id != voc_by_id[voc_id].get("canonical_entity_id")
            or row.get("source_snapshot_id") != source_snapshot_id
        ):
            raise MetricsInputError("governed fact foreign key is invalid")
        if status == "promoted":
            promoted.append(row)
            by_entity[str(entity_id)].append(row)
    promoted.sort(key=lambda row: str(row["fact_id"]))
    for rows in by_entity.values():
        rows.sort(key=lambda row: str(row["fact_id"]))
    return promoted, by_entity, statuses


def _fact_attributes(row: Mapping[str, object]) -> Mapping[str, object]:
    value = row.get("attributes")
    if not isinstance(value, Mapping):
        raise MetricsInputError("governed fact attributes are invalid")
    return value


def _highest_level(
    facts: Sequence[Mapping[str, object]], field: str, prefix: str
) -> str:
    highest = 0
    for fact in facts:
        value = _fact_attributes(fact).get(field)
        if value is None:
            continue
        text = str(value).upper()
        if not text.startswith(prefix):
            raise MetricsInputError(f"{field} is invalid")
        try:
            highest = max(highest, int(text[len(prefix) :]))
        except ValueError as exc:
            raise MetricsInputError(f"{field} is invalid") from exc
    return f"{prefix}{highest}"


def _product_route(
    facts: Sequence[Mapping[str, object]],
) -> tuple[bool, str | None, str | None, list[str]]:
    if not facts:
        return False, None, None, []
    categories: set[str] = set()
    families: set[str] = set()
    spus: set[str] = set()
    fact_ids: list[str] = []
    for fact in facts:
        attributes = _fact_attributes(fact)
        category = attributes.get("category_id")
        family = attributes.get("family_id")
        if isinstance(category, str) and category:
            categories.add(category)
        if isinstance(family, str) and family:
            families.add(family)
        canonical_value = str(fact.get("canonical_value", ""))
        if canonical_value.startswith("spu:"):
            spus.add(canonical_value.removeprefix("spu:"))
        fact_ids.append(str(fact["fact_id"]))
    if len(categories) != 1:
        return False, None, None, fact_ids
    parent_scope = next(iter(categories))
    if len(spus) == 1:
        return True, f"spu:{next(iter(spus))}", parent_scope, fact_ids
    if len(families) == 1:
        return True, f"family:{next(iter(families))}", parent_scope, fact_ids
    return True, f"category:{parent_scope}", parent_scope, fact_ids


def _canonical_analysis_by_id(
    posts: Sequence[Mapping[str, object]],
    comments: Sequence[Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    """Expose existing deterministic local analysis as a descriptive fallback.

    Governed promoted facts still win.  The fallback is accepted only when the
    canonical record explicitly says no provider call was made and carries a
    versioned analysis result.
    """

    result: dict[str, dict[str, object]] = {}
    for raw in (*posts, *comments):
        if not isinstance(raw, Mapping):
            raise MetricsInputError("canonical analysis row is invalid")
        entity_id = _string(raw.get("canonical_reddit_id"), "canonical analysis ID")
        record = raw.get("record")
        if not isinstance(record, Mapping):
            continue
        analysis = record.get("analysis")
        if analysis is None:
            continue
        if not isinstance(analysis, Mapping):
            raise MetricsInputError("canonical analysis payload is invalid")
        sentiment = analysis.get("sentiment_label")
        severity = analysis.get("severity")
        version = analysis.get("analysis_version")
        if (
            sentiment not in {"positive", "neutral", "negative"}
            or severity not in {"low", "medium", "high"}
            or not isinstance(version, str)
            or not version
            or analysis.get("provider_call") is not False
        ):
            raise MetricsInputError("canonical analysis contract is invalid")
        if entity_id in result:
            raise MetricsInputError("duplicate canonical analysis identity")
        result[entity_id] = {
            "analysis_version": version,
            "provider_call": False,
            "sentiment": sentiment,
            "severity": severity,
        }
    return result


def _observation(
    voc: Mapping[str, object],
    facts: Sequence[Mapping[str, object]],
    *,
    recommendation_closed_set_complete: bool,
    canonical_analysis: Mapping[str, object] | None = None,
) -> tuple[dict[str, object], str]:
    entity_id = _string(voc.get("canonical_entity_id"), "VOC canonical entity")
    voc_type = _string(voc.get("voc_type"), "VOC type")
    if voc_type not in {"post_voc", "comment_context_voc"}:
        raise MetricsInputError("VOC type is invalid")
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for fact in facts:
        grouped[str(fact["fact_type"])].append(fact)

    brand_roles = {
        str(fact["canonical_value"])
        for fact in grouped["entity_brand_fact"]
        if fact.get("decision_status") == "promoted"
    }
    brand_state = (
        "momcozy"
        if brand_roles == {"momcozy"}
        else "competitor"
        if brand_roles == {"competitor"}
        else "ambiguous"
        if brand_roles == {"momcozy", "competitor"}
        else "unassigned"
    )
    product_bound, product_scope, parent_scope, product_fact_ids = _product_route(
        grouped["entity_product_fact"]
    )
    sentiment_values = {
        str(fact["canonical_value"]).casefold()
        for fact in grouped["entity_sentiment_fact"]
    }
    if len(sentiment_values) == 1:
        sentiment_status = "complete"
        sentiment: str | None = next(iter(sentiment_values))
        sentiment_source = "governed_promoted_fact"
    elif sentiment_values:
        sentiment_status = "held"
        sentiment = None
        sentiment_source = "conflicting_governed_facts"
    elif canonical_analysis is not None:
        sentiment_status = "complete"
        sentiment = str(canonical_analysis["sentiment"])
        sentiment_source = f"canonical_{canonical_analysis['analysis_version']}"
    else:
        sentiment_status = "unprocessed"
        sentiment = None
        sentiment_source = "unavailable"

    severity = canonical_analysis.get("severity") if canonical_analysis is not None else None
    priority_map = {"low": "none", "medium": "p2", "high": "p1"}
    priority = priority_map.get(str(severity)) if severity is not None else None

    tag_facts = grouped["entity_tag_fact"]
    tag_ids = sorted(str(fact["fact_id"]) for fact in tag_facts)
    recommendation_fact_ids = sorted(
        str(fact["fact_id"])
        for fact in tag_facts
        if fact.get("canonical_value") == "L0-GEN-103"
    )
    recommendation = (
        "recommend"
        if recommendation_fact_ids
        else "none"
        if recommendation_closed_set_complete
        else None
    )
    problem_facts: list[dict[str, object]] = []
    for fact in grouped["entity_problem_fact"]:
        problem_facts.append(
            {
                "attributes": dict(_fact_attributes(fact)),
                "canonical_value": fact["canonical_value"],
                "decision_status": "promoted",
                "fact_id": fact["fact_id"],
                "fact_type": "entity_problem_fact",
                "polarity": "negative",
                "polarity_source": "governed_problem_fact_table_semantics",
                "tag_id": fact["canonical_value"],
            }
        )
    integrity_facts = grouped["integrity_signal_fact"]
    commercial_facts = grouped["commercial_relation_fact"]
    observation: dict[str, object] = {
        "brand": brand_state,
        "brand_eligible": brand_state in {"momcozy", "competitor"},
        "commercial_level": _highest_level(
            commercial_facts, "commercial_confidence_level", "C"
        ),
        "evidence_complete": all(
            isinstance(fact.get("evidence_text_sha256"), str)
            and HEX64.fullmatch(str(fact["evidence_text_sha256"])) is not None
            and type(fact.get("evidence_start")) is int
            and type(fact.get("evidence_end")) is int
            and int(fact["evidence_end"]) > int(fact["evidence_start"])
            for fact in tag_facts
        ),
        "integrity_level": _highest_level(integrity_facts, "signal_class", "I"),
        "linked_parent": voc_type == "post_voc" or voc.get("context_status") == "linked",
        "manual_confirmation": False,
        "metric_eligible": True,
        "metric_member_id": entity_id,
        "parent_scope": parent_scope,
        "priority": priority,
        "priority_classification_source": (
            f"canonical_{canonical_analysis['analysis_version']}"
            if canonical_analysis is not None
            else "unavailable"
        ),
        "priority_classification_status": "complete" if priority is not None else "unprocessed",
        "problem_classification_policy": "governed_closed_set_problem_matcher_v1",
        "problem_classification_status": "complete",
        "product_bound": product_bound,
        "product_fact_ids": product_fact_ids,
        "product_problem_facts": problem_facts,
        "product_relevant": bool(grouped["entity_product_fact"]),
        "product_scope": product_scope,
        "recommendation": recommendation,
        "recommendation_classification_status": (
            "complete" if recommendation_closed_set_complete else "unprocessed"
        ),
        "recommendation_fact_ids": recommendation_fact_ids,
        "sentiment": sentiment,
        "sentiment_classification_status": sentiment_status,
        "sentiment_classification_source": sentiment_source,
        "sentiment_fact_ids": sorted(
            str(fact["fact_id"]) for fact in grouped["entity_sentiment_fact"]
        ),
        "tag_fact_ids": tag_ids,
        "text_ready": voc.get("analysis_text_status") == "ready",
        "thread_id": voc.get("thread_id"),
        "voc_id": voc.get("voc_id"),
        "voc_type": voc_type,
    }
    observation.update(_validate_event_time(voc))
    return observation, brand_state


def _canonical_audit_rows(
    canonical_posts: Iterable[Mapping[str, object]],
    canonical_comments: Iterable[Mapping[str, object]],
    quarantine_comments: Iterable[Mapping[str, object]],
) -> tuple[list[dict[str, object]], dict[str, int]]:
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    post_count = 0
    linked = 0
    unresolved = 0
    quarantined = 0
    for raw in canonical_posts:
        if not isinstance(raw, Mapping):
            raise MetricsInputError("canonical post row is invalid")
        entity_id = _string(raw.get("canonical_reddit_id"), "canonical post ID")
        if entity_id in seen or not entity_id.startswith("t3_"):
            raise MetricsInputError("canonical post identity is invalid")
        seen.add(entity_id)
        record = raw.get("record")
        if not isinstance(record, Mapping):
            raise MetricsInputError("canonical post record is invalid")
        text_ready = bool(str(record.get("title") or "").strip() or str(record.get("content") or "").strip())
        result.append(
            {
                "linked_parent": True,
                "metric_eligible": True,
                "metric_member_id": entity_id,
                "text_ready": text_ready,
                "voc_type": "post_identity",
            }
        )
        post_count += 1
    for raw in canonical_comments:
        if not isinstance(raw, Mapping):
            raise MetricsInputError("canonical comment row is invalid")
        entity_id = _string(raw.get("canonical_reddit_id"), "canonical comment ID")
        if entity_id in seen or not entity_id.startswith("t1_"):
            raise MetricsInputError("canonical comment identity is invalid")
        seen.add(entity_id)
        state = raw.get("comment_state")
        if state not in {"linked", "unresolved_parent"}:
            raise MetricsInputError("canonical comment state is invalid")
        linked += state == "linked"
        unresolved += state == "unresolved_parent"
        record = raw.get("record")
        if not isinstance(record, Mapping):
            raise MetricsInputError("canonical comment record is invalid")
        result.append(
            {
                "linked_parent": state == "linked",
                "metric_eligible": True,
                "metric_member_id": entity_id,
                "text_ready": bool(str(record.get("body") or "").strip()),
                "voc_type": "comment_identity",
            }
        )
    for raw in quarantine_comments:
        if not isinstance(raw, Mapping):
            raise MetricsInputError("canonical quarantine row is invalid")
        entity_id = _string(raw.get("canonical_reddit_id"), "quarantine comment ID")
        if entity_id in seen or not entity_id.startswith("t1_"):
            raise MetricsInputError("quarantine identity is invalid")
        seen.add(entity_id)
        if raw.get("comment_state") != "quarantined":
            raise MetricsInputError("quarantine comment state is invalid")
        quarantined += 1
        result.append(
            {
                "linked_parent": False,
                "metric_eligible": True,
                "metric_member_id": entity_id,
                "text_ready": False,
                "voc_type": "comment_identity",
            }
        )
    result.sort(key=lambda row: str(row["metric_member_id"]))
    return result, {
        "comments_jsonl": linked + unresolved,
        "linked_comments": linked,
        "posts": post_count,
        "quarantined_comments": quarantined,
        "stored_comments": linked + unresolved + quarantined,
        "unresolved_parent_comments": unresolved,
    }


def _automation_audit_rows(
    classifications: Iterable[Mapping[str, object]],
) -> tuple[list[dict[str, object]], int]:
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    row_count = 0
    for raw in classifications:
        if not isinstance(raw, Mapping):
            raise MetricsInputError("automation classification is invalid")
        row_count += 1
        if raw.get("automation_determined") is not True:
            continue
        entity_id = _string(raw.get("canonical_entity_id"), "automation entity ID")
        if entity_id in seen:
            raise MetricsInputError("duplicate determined automation entity")
        seen.add(entity_id)
        if (
            raw.get("requires_organic_exclusion") is not True
            or raw.get("excluded_reason") != "explicit_automation"
            or raw.get("canonical_retained") is not True
        ):
            raise MetricsInputError("determined automation exclusion is invalid")
        result.append(
            {
                "automation_detected": True,
                "excluded_reason": "explicit_automation",
                "metric_eligible": True,
                "metric_member_id": entity_id,
                "voc_type": "comment_identity",
            }
        )
    result.sort(key=lambda row: str(row["metric_member_id"]))
    return result, row_count


def _commercial_audit_rows(
    facts: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    by_entity: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for fact in facts:
        if fact.get("fact_type") == "commercial_relation_fact":
            by_entity[str(fact["canonical_entity_id"])].append(fact)
    result: list[dict[str, object]] = []
    for entity_id, entity_facts in sorted(by_entity.items()):
        level = _highest_level(entity_facts, "commercial_confidence_level", "C")
        disclosed = any(
            "disclos" in str(fact.get("canonical_value", "")).casefold()
            or "affiliate" in str(fact.get("canonical_value", "")).casefold()
            for fact in entity_facts
        )
        result.append(
            {
                "commercial_disclosed": disclosed,
                "commercial_level": level,
                "metric_eligible": True,
                "metric_member_id": entity_id,
                "voc_type": str(entity_facts[0]["voc_type"]),
            }
        )
    return result


def _derive_eligibility(
    source_rows: Iterable[Mapping[str, object]],
    *,
    registry: IndicatorRegistry,
    observations_by_id: Mapping[str, Mapping[str, object]],
    period: str,
    scope: str,
) -> tuple[list[dict[str, object]], int]:
    defaults = {
        definition.reddit_indicator_id: definition.default_comparison_side
        for definition in registry.indicators
        if definition.metric_member_type == "canonical_entity"
    }
    output: list[dict[str, object]] = []
    source_count = 0
    seen_source_keys: set[tuple[str, str, str]] = set()
    for raw in source_rows:
        if not isinstance(raw, Mapping):
            raise MetricsInputError("source eligibility row is invalid")
        source_count += 1
        indicator_id = raw.get("reddit_indicator_id")
        side = raw.get("comparison_side")
        if defaults.get(str(indicator_id)) != side:
            continue
        entity_id = raw.get("metric_member_id")
        if not isinstance(entity_id, str) or entity_id not in observations_by_id:
            continue
        key = (str(indicator_id), str(side), entity_id)
        if key in seen_source_keys:
            raise MetricsInputError("duplicate default-side source eligibility row")
        seen_source_keys.add(key)
        observation = observations_by_id[entity_id]
        brand = observation.get("brand")
        include = False
        derived = dict(raw)
        if side == "not_applicable":
            include = raw.get("status") == "eligible"
        elif side == "raw_observed":
            include = brand == "momcozy" and raw.get("status") == "eligible"
        elif side == "momcozy":
            reasons = raw.get("reason_codes")
            other_reasons = (
                [reason for reason in reasons if reason != "brand_routing_pending"]
                if isinstance(reasons, list)
                else ["invalid_source_reasons"]
            )
            if brand == "momcozy" and not other_reasons:
                include = True
                derived.update(
                    {
                        "membership_role": "eligible_candidate",
                        "reason_codes": ["governed_brand_routing_resolved"],
                        "status": "eligible",
                    }
                )
        elif side == "current":
            # A single all-history source artifact cannot prove three complete,
            # profile-symmetric periods.  RV-IN-05 remains unavailable.
            include = False
        if not include:
            continue
        derived["period"] = period
        derived["scope"] = scope
        derived["denominator_member"] = False
        derived["numerator_member"] = "not_applicable"
        output.append(derived)
    output.sort(
        key=lambda row: (
            str(row["reddit_indicator_id"]),
            str(row["comparison_side"]),
            str(row["metric_member_id"]),
        )
    )
    validate_subset_contract(output)
    return output, source_count


@dataclass(frozen=True)
class MetricsInputBuild:
    document: dict[str, object]
    counts: dict[str, int]


def materialize_metrics_input(
    *,
    vocs: Iterable[Mapping[str, object]],
    automation_voc_ids: Iterable[str],
    automation_classifications: Iterable[Mapping[str, object]],
    governed_facts: Iterable[Mapping[str, object]],
    source_eligibility_rows: Iterable[Mapping[str, object]],
    canonical_posts: Iterable[Mapping[str, object]],
    canonical_comments: Iterable[Mapping[str, object]],
    quarantine_comments: Iterable[Mapping[str, object]],
    registry: IndicatorRegistry,
    source_snapshot_id: str,
    source_facts_manifest_sha256: str,
    period: str,
    scope: str,
    expected_source_eligibility_rows: int | None = None,
    recommendation_closed_set_complete: bool = False,
) -> MetricsInputBuild:
    source_snapshot_id = _string(source_snapshot_id, "source snapshot ID")
    source_facts_manifest_sha256 = _sha(
        source_facts_manifest_sha256, "source facts manifest SHA"
    )
    period = _string(period, "metrics period")
    scope = _string(scope, "metrics scope")
    if type(recommendation_closed_set_complete) is not bool:
        raise MetricsInputError("recommendation scan completeness must be boolean")
    voc_rows = _canonical_rows(vocs, "VOC", "voc_id")
    canonical_post_rows = list(canonical_posts)
    canonical_comment_rows = list(canonical_comments)
    quarantine_comment_rows = list(quarantine_comments)
    canonical_analysis = _canonical_analysis_by_id(
        canonical_post_rows,
        canonical_comment_rows,
    )
    voc_by_id = {str(row["voc_id"]): row for row in voc_rows}
    automation_set = set(automation_voc_ids)
    if any(not isinstance(value, str) or value not in voc_by_id for value in automation_set):
        raise MetricsInputError("automation VOC set is outside the VOC universe")
    promoted, facts_by_entity, status_counts = _promoted_facts(
        governed_facts,
        voc_by_id=voc_by_id,
        automation_voc_ids=automation_set,
        source_snapshot_id=source_snapshot_id,
    )
    observations: list[dict[str, object]] = []
    brand_counts = {"ambiguous": 0, "competitor": 0, "momcozy": 0, "unassigned": 0}
    day_precision = 0
    instant_or_hour_precision = 0
    for voc in voc_rows:
        if voc["voc_id"] in automation_set:
            continue
        entity_id = str(voc["canonical_entity_id"])
        observation, brand_state = _observation(
            voc,
            facts_by_entity.get(entity_id, []),
            recommendation_closed_set_complete=recommendation_closed_set_complete,
            canonical_analysis=canonical_analysis.get(entity_id),
        )
        brand_counts[brand_state] += 1
        day_precision += observation["event_time_precision"] == "day"
        instant_or_hour_precision += observation["event_time_precision"] in {
            "instant",
            "hour",
        }
        observations.append(observation)
    observations.sort(key=lambda row: str(row["metric_member_id"]))
    observation_ids = {str(row["metric_member_id"]) for row in observations}
    if len(observation_ids) != len(observations):
        raise MetricsInputError("duplicate organic observation entity")
    if any(
        str(voc_by_id[voc_id]["canonical_entity_id"]) in observation_ids
        for voc_id in automation_set
    ):
        raise MetricsInputError("automation entity leaked into organic observations")
    observations_by_id = {
        str(row["metric_member_id"]): row for row in observations
    }
    eligibility_rows, source_eligibility_count = _derive_eligibility(
        source_eligibility_rows,
        registry=registry,
        observations_by_id=observations_by_id,
        period=period,
        scope=scope,
    )
    if (
        expected_source_eligibility_rows is not None
        and source_eligibility_count != expected_source_eligibility_rows
    ):
        raise MetricsInputError("source eligibility row conservation mismatch")
    canonical_audit, canonical_counts = _canonical_audit_rows(
        canonical_post_rows, canonical_comment_rows, quarantine_comment_rows
    )
    automation_audit, automation_classification_rows = _automation_audit_rows(
        automation_classifications
    )
    commercial_audit = _commercial_audit_rows(promoted)
    context = {
        "RV-BR-05": {"profile_symmetric": False},
        "RV-CI-01": {"automation_audit_rows": automation_audit},
        "RV-CI-02": {"commercial_audit_rows": commercial_audit},
        "RV-CI-03": {
            "coverage_status": "unavailable",
            "reason_codes": ["governed_cluster_ledger_unavailable"],
        },
        "RV-CI-04": {
            "coverage_status": "unavailable",
            "reason_codes": ["governed_event_dossier_ledger_unavailable"],
        },
        "RV-CI-05": {
            "coverage_status": "unavailable",
            "reason_codes": ["manual_c3_i4_confirmation_ledger_unavailable"],
        },
        "RV-CI-07": {
            "coverage_status": "unavailable",
            "reason_codes": ["governed_review_backlog_ledger_unavailable"],
        },
        "RV-DH-01": {"canonical_audit_rows": canonical_audit},
        "RV-DH-02": {"canonical_audit_rows": canonical_audit},
        "RV-DH-04": {
            "coverage_status": "unavailable",
            "reason_codes": [
                "independent_product_relevance_evidence_unavailable"
            ],
        },
        "RV-BR-04": {
            "recommendation_closed_set_scan_complete": (
                recommendation_closed_set_complete
            )
        },
        "RV-IN-02": {"tag_a_member_ids": [], "tag_b_member_ids": []},
        "RV-IN-03": {"cohort_member_ids": [], "tag_member_ids": []},
        "RV-IN-04": {"threads": []},
        "RV-IN-05": {"complete_periods": []},
        "RV-PS-01": {
            "coverage_status": "unavailable",
            "reason_codes": [
                "independent_parent_scope_eligibility_evidence_unavailable"
            ],
        },
        "RV-PS-04": {"profile_symmetric": False},
    }
    document: dict[str, object] = {
        "atomic_facts": promoted,
        "brand_health_period": period,
        "brand_health_scope": "momcozy",
        "context": context,
        "decimal_places": 2,
        "eligibility_rows": eligibility_rows,
        "observations": observations,
        "period": period,
        "schema_version": INPUT_SCHEMA_VERSION,
        "scope": scope,
        "source_facts_manifest_sha256": source_facts_manifest_sha256,
        "source_snapshot_id": source_snapshot_id,
    }
    counts = {
        **canonical_counts,
        "ambiguous_brand_observations": brand_counts["ambiguous"],
        "atomic_facts": len(promoted),
        "automation_classification_rows": automation_classification_rows,
        "automation_excluded_vocs": len(automation_set),
        "automation_audit_entities": len(automation_audit),
        "competitor_observations": brand_counts["competitor"],
        "canonical_analysis_fallback_observations": sum(
            str(row.get("sentiment_classification_source", "")).startswith("canonical_")
            for row in observations
        ),
        "day_precision_observations": day_precision,
        "derived_eligibility_rows": len(eligibility_rows),
        "held_source_facts": status_counts["held"],
        "instant_or_hour_precision_observations": instant_or_hour_precision,
        "momcozy_observations": brand_counts["momcozy"],
        "organic_observations": len(observations),
        "promoted_source_facts": status_counts["promoted"],
        "rejected_source_facts": status_counts["rejected"],
        "recommendation_expression_observations": sum(
            bool(row.get("recommendation_fact_ids")) for row in observations
        ),
        "source_eligibility_rows": source_eligibility_count,
        "source_fact_rows": sum(status_counts.values()),
        "total_vocs": len(voc_rows),
        "unassigned_brand_observations": brand_counts["unassigned"],
    }
    if counts["organic_observations"] + counts["automation_excluded_vocs"] != counts["total_vocs"]:
        raise MetricsInputError("VOC/automation conservation mismatch")
    if (
        counts["day_precision_observations"]
        + counts["instant_or_hour_precision_observations"]
        != counts["organic_observations"]
    ):
        raise MetricsInputError("event-time precision conservation mismatch")
    if (
        counts["momcozy_observations"]
        + counts["competitor_observations"]
        + counts["ambiguous_brand_observations"]
        + counts["unassigned_brand_observations"]
        != counts["organic_observations"]
    ):
        raise MetricsInputError("brand-routing conservation mismatch")
    return MetricsInputBuild(document=document, counts=counts)


def metrics_input_manifest(
    *,
    document_payload: bytes,
    counts: Mapping[str, int],
    input_bindings: Mapping[str, str],
    source_snapshot_id: str,
) -> dict[str, object]:
    if any(type(value) is not int or value < 0 for value in counts.values()):
        raise MetricsInputError("metrics input counts are invalid")
    bindings = {str(key): _sha(value, f"input binding {key}") for key, value in input_bindings.items()}
    return {
        "boundaries": dict(EXPECTED_BOUNDARIES),
        "consumption_status": "pending_independent_metrics_validation",
        "counts": dict(sorted(counts.items())),
        "files": {
            "metrics-input.json": {
                "bytes": len(document_payload),
                "sha256": sha256(document_payload).hexdigest(),
            }
        },
        "independent_validation_status": "pending",
        "inputs": dict(sorted(bindings.items())),
        "promotable": False,
        "schema_version": INPUT_MANIFEST_SCHEMA_VERSION,
        "source_snapshot_id": _string(source_snapshot_id, "source snapshot ID"),
        "status": "candidate_built",
    }
