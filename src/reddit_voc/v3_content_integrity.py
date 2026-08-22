"""Conservative, evidence-level content-integrity classifications for V3."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Mapping


COMMERCIAL_LABELS = {
    "C0": "商业关系未知",
    "C1": "商业内容线索",
    "C2": "疑似商业传播模式",
    "C3": "已确认商业关联",
}
INTEGRITY_LABELS = {
    "I0": "无可用完整性结论",
    "I1": "待复核信号",
    "I2": "疑似非自然传播",
    "I3": "外部社区治理事件",
    "I4": "已确认不当干预",
}
SIGNAL_TYPES = frozenset({"content", "behavior", "link"})
GOVERNANCE_AUTHORITIES = frozenset(
    {"subreddit_moderator", "reddit_platform", "other_platform"}
)
DISCLOSURES = frozenset(
    {"affiliate", "sponsored", "coupon", "representative", "self_disclosed_brand_relation"}
)
FIXED_EVENT_POST_IDS = (
    "1kkvihg",
    "1l2aofi",
    "1n2q1do",
    "1o1pqox",
    "1u2gvn4",
)
RESPONSE_TRANSITIONS = {
    "unanswered": frozenset({"disputed", "confirmed", "retracted"}),
    "disputed": frozenset({"confirmed", "retracted"}),
    "confirmed": frozenset({"disputed", "retracted"}),
    "retracted": frozenset({"disputed", "confirmed"}),
}
REVIEW_TRANSITIONS = {
    "queued": frozenset({"in_review"}),
    "in_review": frozenset({"resolved_confirmed", "resolved_dismissed"}),
    "resolved_confirmed": frozenset(),
    "resolved_dismissed": frozenset(),
}
INPUT_KEYS = frozenset(
    {
        "affiliate_registry_bound",
        "ai_style_signal",
        "brand_attribution_confirmed",
        "brand_confirmation",
        "commercial_denial",
        "commercial_disclosure",
        "entity_id",
        "evidence_ids",
        "explicit_automation",
        "governance_authority",
        "manual_rule_violation_confirmed",
        "public_governance_action",
        "repeated_propagation_pattern",
        "signal_types",
    }
)


class ContentIntegrityError(ValueError):
    """An integrity classification exceeds its observable evidence."""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


@dataclass(frozen=True)
class IntegrityAssessment:
    assessment_id: str
    entity_id: str
    commercial_relation: str
    integrity_level: str
    publication_label: str
    commercial_publication_label: str
    governance_authority: str | None
    brand_control_confirmed: bool
    metric_excluded: bool
    evidence_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    response_status: str = "unanswered"

    def as_dict(self) -> dict[str, object]:
        return {
            "assessment_id": self.assessment_id,
            "brand_control_confirmed": self.brand_control_confirmed,
            "commercial_publication_label": self.commercial_publication_label,
            "commercial_relation": self.commercial_relation,
            "entity_id": self.entity_id,
            "evidence_ids": list(self.evidence_ids),
            "governance_authority": self.governance_authority,
            "integrity_level": self.integrity_level,
            "metric_excluded": self.metric_excluded,
            "publication_label": self.publication_label,
            "reason_codes": list(self.reason_codes),
            "response_status": self.response_status,
        }


@dataclass(frozen=True)
class IntegrityEventChain:
    event_id: str
    post_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    commercial_relation: str
    integrity_level: str
    governance_authority: str
    brand_control_confirmed: bool
    response_status: str
    lifecycle_status: str
    publication_label: str

    def as_dict(self) -> dict[str, object]:
        return {
            "brand_control_confirmed": self.brand_control_confirmed,
            "commercial_relation": self.commercial_relation,
            "event_id": self.event_id,
            "evidence_ids": list(self.evidence_ids),
            "governance_authority": self.governance_authority,
            "integrity_level": self.integrity_level,
            "lifecycle_status": self.lifecycle_status,
            "post_ids": list(self.post_ids),
            "publication_label": self.publication_label,
            "response_status": self.response_status,
        }


def _boolean(row: Mapping[str, object], key: str) -> bool:
    value = row.get(key, False)
    if type(value) is not bool:
        raise ContentIntegrityError(f"{key} must be a boolean")
    return value


def classify_integrity(value: object) -> IntegrityAssessment:
    if not isinstance(value, Mapping) or not set(value) <= INPUT_KEYS:
        raise ContentIntegrityError("integrity input fields are invalid")
    entity_id = value.get("entity_id")
    if not isinstance(entity_id, str) or not entity_id:
        raise ContentIntegrityError("integrity entity ID is invalid")
    signal_values = value.get("signal_types", [])
    if (
        not isinstance(signal_values, list)
        or any(item not in SIGNAL_TYPES for item in signal_values)
        or len(signal_values) != len(set(signal_values))
    ):
        raise ContentIntegrityError("integrity signal types are invalid")
    signals = set(signal_values)
    evidence_values = value.get("evidence_ids", [])
    if (
        not isinstance(evidence_values, list)
        or any(not isinstance(item, str) or not item for item in evidence_values)
        or len(evidence_values) != len(set(evidence_values))
    ):
        raise ContentIntegrityError("integrity evidence IDs are invalid")
    evidence_ids = tuple(sorted(evidence_values))

    disclosure = value.get("commercial_disclosure")
    if disclosure is not None and disclosure not in DISCLOSURES:
        raise ContentIntegrityError("commercial disclosure is invalid")
    explicit_automation = _boolean(value, "explicit_automation")
    repeated = _boolean(value, "repeated_propagation_pattern")
    denial = _boolean(value, "commercial_denial")
    ai_style = _boolean(value, "ai_style_signal")
    affiliate_bound = _boolean(value, "affiliate_registry_bound")
    brand_confirmation = _boolean(value, "brand_confirmation")
    brand_attribution = _boolean(value, "brand_attribution_confirmed")
    manual_violation = _boolean(value, "manual_rule_violation_confirmed")
    public_governance = _boolean(value, "public_governance_action")
    authority = value.get("governance_authority")
    if authority is not None and authority not in GOVERNANCE_AUTHORITIES:
        raise ContentIntegrityError("governance authority is invalid")

    if explicit_automation:
        commercial = "C0"
        integrity = "I0"
        reasons = ("explicit_automation_metric_gate_not_attribution",)
    else:
        confirmed_relation = (
            affiliate_bound
            or brand_confirmation
            or brand_attribution
            or disclosure == "self_disclosed_brand_relation"
        )
        commercial = (
            "C3"
            if confirmed_relation
            else "C2"
            if repeated
            else "C1"
            if disclosure is not None or denial
            else "C0"
        )
        if manual_violation and confirmed_relation:
            integrity = "I4"
        elif public_governance and authority is not None:
            integrity = "I3"
        elif len(signals) >= 2:
            integrity = "I2"
        elif signals or disclosure is not None or denial or ai_style or repeated:
            integrity = "I1"
        else:
            integrity = "I0"
        reasons_list: list[str] = []
        if disclosure is not None:
            reasons_list.append("commercial_disclosure_observed")
        if denial:
            reasons_list.append("commercial_denial_counter_evidence_only")
        if repeated:
            reasons_list.append("repeated_propagation_pattern")
        if signals:
            reasons_list.append("independent_signal_types_observed")
        if public_governance:
            reasons_list.append("external_governance_evidence")
        if manual_violation:
            reasons_list.append("manual_rule_review_confirmed")
        if confirmed_relation:
            reasons_list.append("commercial_attribution_confirmed")
        reasons = tuple(sorted(reasons_list or ["no_publishable_integrity_evidence"]))

    # A governed affiliate/self-disclosure can confirm a commercial relation
    # without proving that the brand controlled the account or message.  Keep
    # those two claims separate; the fixed moderator event is also never brand
    # control evidence.
    brand_control_confirmed = brand_confirmation
    payload = {
        "brand_control_confirmed": brand_control_confirmed,
        "commercial_relation": commercial,
        "entity_id": entity_id,
        "evidence_ids": list(evidence_ids),
        "governance_authority": authority if integrity in {"I3", "I4"} else None,
        "integrity_level": integrity,
        "metric_excluded": explicit_automation,
        "reason_codes": list(reasons),
        "response_status": "unanswered",
    }
    assessment_id = sha256(_canonical(payload)).hexdigest()
    return IntegrityAssessment(
        assessment_id=assessment_id,
        entity_id=entity_id,
        commercial_relation=commercial,
        integrity_level=integrity,
        publication_label=INTEGRITY_LABELS[integrity],
        commercial_publication_label=COMMERCIAL_LABELS[commercial],
        governance_authority=payload["governance_authority"],
        brand_control_confirmed=brand_control_confirmed,
        metric_excluded=explicit_automation,
        evidence_ids=evidence_ids,
        reason_codes=reasons,
    )


def build_event_chain(rows: object) -> IntegrityEventChain:
    if not isinstance(rows, list) or len(rows) != len(FIXED_EVENT_POST_IDS):
        raise ContentIntegrityError("Momcozy governance event roots are incomplete")
    by_post: dict[str, Mapping[str, object]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ContentIntegrityError("governance event row is invalid")
        post_id = row.get("post_id")
        evidence_id = row.get("evidence_id")
        if (
            not isinstance(post_id, str)
            or post_id in by_post
            or not isinstance(evidence_id, str)
            or not evidence_id
            or row.get("authority") != "subreddit_moderator"
        ):
            raise ContentIntegrityError("governance event evidence is invalid")
        by_post[post_id] = row
    if set(by_post) != set(FIXED_EVENT_POST_IDS):
        raise ContentIntegrityError("Momcozy governance event roots are incomplete")
    post_ids = tuple(FIXED_EVENT_POST_IDS)
    evidence_ids = tuple(str(by_post[post_id]["evidence_id"]) for post_id in post_ids)
    identity = {
        "brand_control_confirmed": False,
        "commercial_relation": "C2",
        "evidence_ids": list(evidence_ids),
        "governance_authority": "subreddit_moderator",
        "integrity_level": "I3",
        "post_ids": list(post_ids),
        "response_status": "unanswered",
    }
    return IntegrityEventChain(
        event_id=sha256(_canonical(identity)).hexdigest(),
        post_ids=post_ids,
        evidence_ids=evidence_ids,
        commercial_relation="C2",
        integrity_level="I3",
        governance_authority="subreddit_moderator",
        brand_control_confirmed=False,
        response_status="unanswered",
        lifecycle_status="review_required",
        publication_label="Subreddit 版主治理事件",
    )


def transition_brand_response(current: str, target: str) -> str:
    if current not in RESPONSE_TRANSITIONS or target not in RESPONSE_TRANSITIONS:
        raise ContentIntegrityError("brand response status is invalid")
    if target == current:
        return current
    if target not in RESPONSE_TRANSITIONS[current]:
        raise ContentIntegrityError("brand response transition is invalid")
    return target


def transition_review_status(
    current: str,
    target: str,
    *,
    reviewer_id: str | None = None,
    evidence_id: str | None = None,
) -> str:
    if current not in REVIEW_TRANSITIONS or target not in REVIEW_TRANSITIONS:
        raise ContentIntegrityError("integrity review status is invalid")
    if target == current:
        return current
    if target not in REVIEW_TRANSITIONS[current]:
        raise ContentIntegrityError("integrity review transition is invalid")
    if target.startswith("resolved_") and (
        not isinstance(reviewer_id, str)
        or not reviewer_id
        or not isinstance(evidence_id, str)
        or not evidence_id
    ):
        raise ContentIntegrityError("resolved review requires reviewer and evidence")
    return target
