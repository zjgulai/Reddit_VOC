"""Frozen governance-regression facts for Reddit VOC V3.

This module intentionally proves the fixed 4+1 root-post and three-comment
governance examples.  It is not the full-corpus matcher for the nine atomic
fact tables and must not be used to claim that those tables are populated.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping

from reddit_voc.v3_canonical_identity import (
    CanonicalIdentityError,
    canonical_comment_fullname,
    canonical_comment_id,
    canonical_post_fullname,
    canonical_post_id,
)


ATOMIC_FACT_SCHEMA_VERSION = "reddit_voc_atomic_fact_v2"
IMPLEMENTATION_SCOPE = "fixed_governance_regression_only"
FULL_CORPUS_ATOMIC_FACT_MATCHER_IMPLEMENTED = False
ATOMIC_FACT_TYPES = (
    "entity_brand_fact",
    "entity_product_fact",
    "entity_sentiment_fact",
    "entity_problem_fact",
    "entity_tag_fact",
    "persona_atomic_fact",
    "community_governance_fact",
    "commercial_relation_fact",
    "integrity_signal_fact",
)
DECISION_STATUSES = frozenset({"promoted", "held", "rejected"})
DEFAULT_DICTIONARY_RELEASE_ID = (
    "dim_tag_v6.3_final@"
    "22664c9c446ddfa17446852079f507ab75b5af3d4dde6e4e3f3e44c195582e14"
)
DEFAULT_MATCHER_VERSION = "reddit_voc_governance_regression_rules_20260716_v2"
NORMALIZER_VERSION = "source_codepoint_v1"
GOVERNANCE_ROOT_VOC_IDS = (
    "post:1kkvihg",
    "post:1l2aofi",
    "post:1n2q1do",
    "post:1o1pqox",
    "post:1u2gvn4",
)


class AtomicFactError(ValueError):
    """An atomic fact cannot be replayed to its governed evidence."""


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
        raise AtomicFactError("value is not canonical JSON serializable") from exc


@dataclass(frozen=True)
class AtomicFact:
    fact_id: str
    canonical_entity_id: str
    voc_id: str
    voc_type: str
    fact_type: str
    canonical_value: str
    attributes: dict[str, object]
    evidence_field: str
    evidence_start: int
    evidence_end: int
    evidence_text_sha256: str
    evidence_scope: str
    evidence_source_entity_id: str
    context_evidence_refs: tuple[str, ...]
    decision_status: str
    reason_codes: tuple[str, ...]
    dictionary_release_id: str
    matcher_version: str
    normalizer_version: str
    source_snapshot_id: str
    created_at: str
    schema_version: str = ATOMIC_FACT_SCHEMA_VERSION

    def as_dict(self) -> dict[str, object]:
        return {
            "attributes": dict(self.attributes),
            "canonical_entity_id": self.canonical_entity_id,
            "canonical_value": self.canonical_value,
            "context_evidence_refs": list(self.context_evidence_refs),
            "created_at": self.created_at,
            "decision_status": self.decision_status,
            "dictionary_release_id": self.dictionary_release_id,
            "evidence_end": self.evidence_end,
            "evidence_field": self.evidence_field,
            "evidence_scope": self.evidence_scope,
            "evidence_source_entity_id": self.evidence_source_entity_id,
            "evidence_start": self.evidence_start,
            "evidence_text_sha256": self.evidence_text_sha256,
            "fact_id": self.fact_id,
            "fact_type": self.fact_type,
            "matcher_version": self.matcher_version,
            "normalizer_version": self.normalizer_version,
            "reason_codes": list(self.reason_codes),
            "schema_version": self.schema_version,
            "source_snapshot_id": self.source_snapshot_id,
            "voc_id": self.voc_id,
            "voc_type": self.voc_type,
        }


@dataclass(frozen=True)
class _RegisteredRule:
    voc_id: str
    fact_type: str
    canonical_value: str
    evidence_field: str
    evidence_text: str
    decision_status: str
    reason_codes: tuple[str, ...]
    attributes: tuple[tuple[str, object], ...]


def _rule(
    voc_id: str,
    fact_type: str,
    canonical_value: str,
    evidence_field: str,
    evidence_text: str,
    *,
    decision_status: str = "promoted",
    reason_codes: tuple[str, ...] = ("governed_regression_exact_span",),
    **attributes: object,
) -> _RegisteredRule:
    return _RegisteredRule(
        voc_id=voc_id,
        fact_type=fact_type,
        canonical_value=canonical_value,
        evidence_field=evidence_field,
        evidence_text=evidence_text,
        decision_status=decision_status,
        reason_codes=reason_codes,
        attributes=tuple(sorted(attributes.items())),
    )


REGISTERED_RULES = (
    _rule(
        "post:1kkvihg",
        "integrity_signal_fact",
        "integrity_allegation",
        "post_body",
        "Momcozy sends employees/planted users in here to subtly advertise their products.",
        assertion_mode="subreddit_moderator_allegation",
        event_aggregation_required=True,
        signal_class="I1",
    ),
    _rule(
        "post:1kkvihg",
        "community_governance_fact",
        "moderation_warning",
        "post_body",
        "we will ban accounts",
        action_type="account_ban_warning",
        authority="subreddit_moderator",
        claim_role="direct_governance_statement",
    ),
    _rule(
        "post:1kkvihg",
        "integrity_signal_fact",
        "repurchase_signal",
        "post_body",
        "keep coming back",
        decision_status="rejected",
        reason_codes=("speaker_target_mismatch",),
        observation_role="speaker_target_negative_control",
        target_role="alleged_promotional_accounts",
    ),
    _rule(
        "post:1l2aofi",
        "integrity_signal_fact",
        "integrity_allegation",
        "post_body",
        "Momcozy is back at trying to alter their perception in our community.",
        assertion_mode="subreddit_moderator_allegation",
        event_aggregation_required=True,
        signal_class="I1",
    ),
    _rule(
        "post:1l2aofi",
        "integrity_signal_fact",
        "fake_review_allegation",
        "post_body",
        "fake reviews",
        assertion_mode="subreddit_moderator_allegation",
        event_aggregation_required=True,
        signal_class="I1",
    ),
    _rule(
        "post:1n2q1do",
        "community_governance_fact",
        "manual_review_policy",
        "post_title",
        "manually reviewing every single post mentioning momcozy",
        action_type="manual_content_review",
        authority="subreddit_moderator",
        governance_level="I3",
    ),
    _rule(
        "post:1n2q1do",
        "community_governance_fact",
        "temporary_ban_policy",
        "post_title",
        "temporary bans",
        action_type="temporary_account_ban",
        authority="subreddit_moderator",
        governance_level="I3",
    ),
    _rule(
        "post:1n2q1do",
        "community_governance_fact",
        "permanent_ban_policy",
        "post_title",
        "permanent bans",
        action_type="permanent_account_ban",
        authority="subreddit_moderator",
        governance_level="I3",
    ),
    _rule(
        "post:1o1pqox",
        "integrity_signal_fact",
        "integrity_allegation",
        "post_title",
        "Momcozy paying creators to lie",
        assertion_mode="subreddit_moderator_allegation",
        event_aggregation_required=True,
        signal_class="I1",
    ),
    _rule(
        "post:1o1pqox",
        "commercial_relation_fact",
        "creator_payment_allegation",
        "post_body",
        "offered $600",
        assertion_mode="third_party_payment_allegation",
        commercial_confidence_level="C1",
        event_aggregation_required=True,
        relation_type="paid_creator_offer",
    ),
    _rule(
        "comment:mrxlcx3",
        "integrity_signal_fact",
        "integrity_allegation",
        "current_comment_body",
        "They spam comments when momcozy is mentioned",
        assertion_mode="comment_observation",
        event_aggregation_required=True,
        signal_class="I1",
    ),
    _rule(
        "comment:mrxqx1g",
        "integrity_signal_fact",
        "past_purchase_decision",
        "current_comment_body",
        "I bought a Momcozy pump based off Reddit reviews",
        observation_role="purchase_decision_impact",
    ),
    _rule(
        "comment:mrxqx1g",
        "integrity_signal_fact",
        "consumer_trust_impact",
        "current_comment_body",
        "questioning their legitimacy",
        impact_type="brand_trust_questioned",
        signal_class="I1",
    ),
    _rule(
        "comment:mrxu2ve",
        "integrity_signal_fact",
        "consumer_trust_impact",
        "current_comment_body",
        "I do not trust or support companies that engage in this kind of covert and deceptive marketing",
        impact_type="brand_trust_rejected",
        signal_class="I1",
    ),
    _rule(
        "comment:mrxu2ve",
        "integrity_signal_fact",
        "purchase_avoidance",
        "current_comment_body",
        "I am crossing Momcozy off my list as an option.",
        observation_role="avoid_purchase_decision_impact",
    ),
    _rule(
        "external-post:1u2gvn4",
        "integrity_signal_fact",
        "ai_bot_allegation",
        "post_body",
        "AI bots",
        assertion_mode="subreddit_moderator_allegation",
        brand_control_confirmed=False,
        commercial_relation_ceiling="C2",
        event_aggregation_required=True,
        integrity_level_ceiling="I3",
        signal_class="I1",
        source_role="external_public_reference_noncanonical",
    ),
    _rule(
        "external-post:1u2gvn4",
        "integrity_signal_fact",
        "bogus_account_allegation",
        "post_body",
        "bogus accounts",
        assertion_mode="subreddit_moderator_allegation",
        brand_control_confirmed=False,
        commercial_relation_ceiling="C2",
        event_aggregation_required=True,
        integrity_level_ceiling="I3",
        signal_class="I1",
        source_role="external_public_reference_noncanonical",
    ),
    _rule(
        "external-post:1u2gvn4",
        "community_governance_fact",
        "account_ban_action",
        "post_body",
        "accounts have been banned",
        action_type="account_ban_action",
        authority="subreddit_moderator",
        brand_control_confirmed=False,
        commercial_relation_ceiling="C2",
        governance_level="I3",
        integrity_level_ceiling="I3",
        source_role="external_public_reference_noncanonical",
    ),
)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise AtomicFactError(f"{label} must be a non-empty string")
    return value


def _voc_mapping(value: object) -> Mapping[str, Any]:
    if hasattr(value, "as_dict"):
        value = value.as_dict()
    if not isinstance(value, Mapping):
        raise AtomicFactError("VOC must be an object")
    return value


def _analysis_fields(voc: Mapping[str, Any]) -> Mapping[str, str]:
    value = voc.get("analysis_fields")
    if not isinstance(value, Mapping):
        raise AtomicFactError("VOC analysis fields must be an object")
    expected_fields = {"post_title", "post_body", "current_comment_body"}
    if set(value) != expected_fields:
        raise AtomicFactError("VOC analysis fields are invalid")
    result: dict[str, str] = {}
    for field in ("post_title", "post_body", "current_comment_body"):
        text = value[field]
        if not isinstance(text, str):
            raise AtomicFactError(f"VOC {field} must be a string")
        result[field] = text
    return result


def _validate_voc_identity(voc: Mapping[str, Any]) -> None:
    if voc.get("schema_version") != "reddit_voc_fielded_voc_v1":
        raise AtomicFactError("VOC schema is unsupported")
    voc_id = _string(voc.get("voc_id"), "VOC ID")
    voc_type = _string(voc.get("voc_type"), "VOC type")
    canonical_entity_id = _string(
        voc.get("canonical_entity_id"), "canonical entity ID"
    )
    raw_post_id = _string(voc.get("post_id"), "post ID")
    raw_thread_id = _string(voc.get("thread_id"), "thread ID")
    raw_metric_key = _string(
        voc.get("metric_distinct_key"), "metric distinct key"
    )
    try:
        post_id = canonical_post_id(raw_post_id)
    except CanonicalIdentityError as exc:
        raise AtomicFactError("VOC post identity is invalid") from exc
    if raw_post_id != post_id or raw_thread_id != post_id:
        raise AtomicFactError("VOC post/thread identity mismatch")

    if voc_type == "post_voc":
        if not voc_id.startswith("post:"):
            raise AtomicFactError("post VOC ID namespace mismatch")
        raw_voc_post_id = voc_id.removeprefix("post:")
        try:
            voc_post_id = canonical_post_id(raw_voc_post_id)
        except CanonicalIdentityError as exc:
            raise AtomicFactError("post VOC identity is invalid") from exc
        if (
            raw_voc_post_id != voc_post_id
            or voc_post_id != post_id
            or canonical_entity_id != canonical_post_fullname(post_id)
            or raw_metric_key != post_id
            or voc.get("comment_id") is not None
            or voc.get("comment_context_id") is not None
        ):
            raise AtomicFactError("post VOC canonical identity mismatch")
    elif voc_type == "comment_context_voc":
        if not voc_id.startswith("comment:"):
            raise AtomicFactError("comment VOC ID namespace mismatch")
        raw_voc_comment_id = voc_id.removeprefix("comment:")
        raw_comment_id = _string(voc.get("comment_id"), "comment ID")
        try:
            voc_comment_id = canonical_comment_id(raw_voc_comment_id)
            comment_id = canonical_comment_id(raw_comment_id)
        except CanonicalIdentityError as exc:
            raise AtomicFactError("comment VOC identity is invalid") from exc
        if (
            raw_voc_comment_id != voc_comment_id
            or raw_comment_id != comment_id
            or voc_comment_id != comment_id
            or canonical_entity_id != canonical_comment_fullname(comment_id)
            or raw_metric_key != comment_id
            or voc.get("comment_context_id") != f"{post_id}:{comment_id}"
        ):
            raise AtomicFactError("comment VOC canonical identity mismatch")
    else:
        raise AtomicFactError("VOC type is unsupported")
    _analysis_fields(voc)


def _validate_created_at(value: object) -> str:
    text = _string(value, "created at")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AtomicFactError("created at must be ISO-8601") from exc
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() != timedelta(0)
        or parsed.microsecond != 0
        or text != parsed.isoformat(timespec="seconds")
    ):
        raise AtomicFactError("created at must be canonical UTC seconds")
    return text


def _fact_id(fact: AtomicFact) -> str:
    payload = fact.as_dict()
    payload.pop("fact_id")
    return sha256(canonical_json_bytes(payload)).hexdigest()


def _validate_registered_rules() -> None:
    seen: set[tuple[object, ...]] = set()
    for rule in REGISTERED_RULES:
        attributes = dict(rule.attributes)
        if rule.fact_type not in ATOMIC_FACT_TYPES:
            raise AtomicFactError("registered atomic fact type is unsupported")
        if rule.fact_type == "entity_tag_fact":
            raise AtomicFactError("regression behavior may not masquerade as a tag")
        if rule.decision_status not in DECISION_STATUSES:
            raise AtomicFactError("registered decision status is invalid")
        if not rule.evidence_text or not rule.reason_codes:
            raise AtomicFactError("registered evidence or reasons are empty")
        if rule.reason_codes != tuple(sorted(set(rule.reason_codes))):
            raise AtomicFactError("registered reasons are invalid")
        if rule.voc_id.startswith("post:"):
            if rule.evidence_field not in {"post_title", "post_body"}:
                raise AtomicFactError("registered post evidence field is invalid")
        elif rule.voc_id.startswith("comment:"):
            if rule.evidence_field != "current_comment_body":
                raise AtomicFactError("registered comment evidence field is invalid")
        elif rule.voc_id.startswith("external-post:"):
            if rule.evidence_field != "post_body":
                raise AtomicFactError(
                    "registered external evidence field is invalid"
                )
            if attributes.get("source_role") != (
                "external_public_reference_noncanonical"
            ):
                raise AtomicFactError("registered external source role is invalid")
        else:
            raise AtomicFactError("registered VOC namespace is invalid")
        if attributes.get("commercial_confidence_level") not in {None, "C1"}:
            raise AtomicFactError("entity commercial level exceeds C1")
        if attributes.get("signal_class") not in {None, "I1"}:
            raise AtomicFactError("entity integrity signal exceeds I1")
        if attributes.get("governance_level") not in {None, "I3"}:
            raise AtomicFactError("governance level exceeds I3")
        canonical_json_bytes(attributes)
        key = (
            rule.voc_id,
            rule.fact_type,
            rule.canonical_value,
            rule.evidence_field,
            rule.evidence_text,
            rule.decision_status,
        )
        if key in seen:
            raise AtomicFactError("duplicate registered atomic fact rule")
        seen.add(key)


def _make_fact(
    *,
    voc: Mapping[str, Any],
    rule: _RegisteredRule,
    fields: Mapping[str, str],
    dictionary_release_id: str,
    matcher_version: str,
    source_snapshot_id: str,
    created_at: str,
) -> AtomicFact:
    text = fields[rule.evidence_field]
    start = text.find(rule.evidence_text)
    if start < 0 or text.find(rule.evidence_text, start + 1) >= 0:
        raise AtomicFactError(
            f"governed evidence is missing or ambiguous: {rule.voc_id}:{rule.canonical_value}"
        )
    end = start + len(rule.evidence_text)
    evidence_hash = sha256(rule.evidence_text.encode("utf-8")).hexdigest()
    canonical_entity_id = _string(
        voc.get("canonical_entity_id"), "canonical entity ID"
    )
    voc_id = _string(voc.get("voc_id"), "VOC ID")
    voc_type = _string(voc.get("voc_type"), "VOC type")
    fact = AtomicFact(
        fact_id="",
        canonical_entity_id=canonical_entity_id,
        voc_id=voc_id,
        voc_type=voc_type,
        fact_type=rule.fact_type,
        canonical_value=rule.canonical_value,
        attributes=dict(rule.attributes),
        evidence_field=rule.evidence_field,
        evidence_start=start,
        evidence_end=end,
        evidence_text_sha256=evidence_hash,
        evidence_scope="direct",
        evidence_source_entity_id=canonical_entity_id,
        context_evidence_refs=(),
        decision_status=rule.decision_status,
        reason_codes=tuple(sorted(set(rule.reason_codes))),
        dictionary_release_id=dictionary_release_id,
        matcher_version=matcher_version,
        normalizer_version=NORMALIZER_VERSION,
        source_snapshot_id=source_snapshot_id,
        created_at=created_at,
    )
    return replace(fact, fact_id=_fact_id(fact))


def build_atomic_facts(
    voc: object,
    *,
    source_snapshot_id: str,
    created_at: str,
    dictionary_release_id: str = DEFAULT_DICTIONARY_RELEASE_ID,
    matcher_version: str = DEFAULT_MATCHER_VERSION,
) -> tuple[AtomicFact, ...]:
    row = _voc_mapping(voc)
    _validate_registered_rules()
    _validate_voc_identity(row)
    voc_id = _string(row.get("voc_id"), "VOC ID")
    fields = _analysis_fields(row)
    source_snapshot_id = _string(source_snapshot_id, "source snapshot ID")
    dictionary_release_id = _string(
        dictionary_release_id, "dictionary release ID"
    )
    matcher_version = _string(matcher_version, "matcher version")
    if dictionary_release_id != DEFAULT_DICTIONARY_RELEASE_ID:
        raise AtomicFactError("dictionary release is not the frozen regression release")
    if matcher_version != DEFAULT_MATCHER_VERSION:
        raise AtomicFactError("matcher version is not the frozen regression matcher")
    created_at = _validate_created_at(created_at)
    rules = [rule for rule in REGISTERED_RULES if rule.voc_id == voc_id]
    if rules and row.get("analysis_text_status") != "ready":
        raise AtomicFactError("registered governance VOC text is not analysis-ready")
    facts = [
        _make_fact(
            voc=row,
            rule=rule,
            fields=fields,
            dictionary_release_id=dictionary_release_id,
            matcher_version=matcher_version,
            source_snapshot_id=source_snapshot_id,
            created_at=created_at,
        )
        for rule in rules
    ]
    facts.sort(
        key=lambda fact: (
            fact.fact_type,
            fact.canonical_value,
            fact.evidence_field,
            fact.evidence_start,
            fact.fact_id,
        )
    )
    return tuple(facts)


EXTERNAL_PUBLIC_POST_SCHEMA = "reddit_voc_external_public_post_snapshot_v1"
EXTERNAL_PUBLIC_POST_SOURCE_ROLE = "external_public_reference_noncanonical"


def build_external_reference_atomic_facts(
    external_snapshot: object,
    *,
    source_snapshot_id: str,
    created_at: str,
    dictionary_release_id: str = DEFAULT_DICTIONARY_RELEASE_ID,
    matcher_version: str = DEFAULT_MATCHER_VERSION,
) -> tuple[AtomicFact, ...]:
    """Replay fixed evidence without admitting the external post to Task 4."""
    row = _voc_mapping(external_snapshot)
    _validate_registered_rules()
    post_id = _string(row.get("reddit_post_id"), "external Reddit post ID")
    if (
        row.get("schema_version") != EXTERNAL_PUBLIC_POST_SCHEMA
        or post_id != "1u2gvn4"
        or row.get("source_role") != EXTERNAL_PUBLIC_POST_SOURCE_ROLE
        or row.get("canonical_task4_row") is not False
        or row.get("pii_fields_collected") is not False
        or row.get("title") != "Momcozy is at it again"
        or row.get("subreddit") != "ExclusivelyPumping"
        or row.get("flair_text") != "MOD RANT/ANNOUNCEMENT ETC"
        or row.get("post_body")
        != (
            "Just a heads up that Momcozy is at it again in the community, using "
            "AI bots and bogus accounts to shill their products. Thanks to those "
            "that have been reporting them, the accounts have been banned, but to "
            "be frank it is an alarming number. Please continue to report "
            "suspicious content."
        )
        or any(
            key in row
            for key in (
                "author",
                "author_fullname",
                "author_pseudonym",
                "canonical_entity_id",
                "voc_id",
            )
        )
    ):
        raise AtomicFactError("external public post snapshot is invalid")
    source_snapshot_id = _string(source_snapshot_id, "source snapshot ID")
    dictionary_release_id = _string(
        dictionary_release_id, "dictionary release ID"
    )
    matcher_version = _string(matcher_version, "matcher version")
    if dictionary_release_id != DEFAULT_DICTIONARY_RELEASE_ID:
        raise AtomicFactError("dictionary release is not the frozen regression release")
    if matcher_version != DEFAULT_MATCHER_VERSION:
        raise AtomicFactError("matcher version is not the frozen regression matcher")
    created_at = _validate_created_at(created_at)
    external_voc_id = f"external-post:{post_id}"
    synthetic = {
        "canonical_entity_id": f"external_reddit_post:{post_id}",
        "voc_id": external_voc_id,
        "voc_type": "external_public_reference",
    }
    fields = {"post_body": str(row["post_body"])}
    facts = tuple(
        _make_fact(
            voc=synthetic,
            rule=rule,
            fields=fields,
            dictionary_release_id=dictionary_release_id,
            matcher_version=matcher_version,
            source_snapshot_id=source_snapshot_id,
            created_at=created_at,
        )
        for rule in REGISTERED_RULES
        if rule.voc_id == external_voc_id
    )
    if len(facts) != 3:
        raise AtomicFactError("external public post governed rules are incomplete")
    return tuple(
        sorted(
            facts,
            key=lambda fact: (
                fact.fact_type,
                fact.evidence_start,
                fact.canonical_value,
                fact.fact_id,
            ),
        )
    )


def validate_external_reference_atomic_facts(
    facts: Iterable[AtomicFact],
    external_snapshot: object,
    *,
    source_snapshot_id: str,
    created_at: str,
) -> None:
    actual = tuple(facts)
    expected = build_external_reference_atomic_facts(
        external_snapshot,
        source_snapshot_id=source_snapshot_id,
        created_at=created_at,
    )
    if [fact.as_dict() for fact in actual] != [fact.as_dict() for fact in expected]:
        raise AtomicFactError("external reference facts fail exact replay")
    if any(
        fact.canonical_entity_id.startswith(("t1_", "t3_"))
        or fact.voc_id.startswith(("post:", "comment:"))
        or fact.voc_type != "external_public_reference"
        or fact.attributes.get("brand_control_confirmed") is not False
        or fact.attributes.get("commercial_relation_ceiling") != "C2"
        or fact.attributes.get("integrity_level_ceiling") != "I3"
        for fact in actual
    ):
        raise AtomicFactError("external reference fact exceeded publication boundary")


def governance_regression_coverage(
    vocs: Iterable[object],
    *,
    external_references: Iterable[object] = (),
) -> dict[str, object]:
    _validate_registered_rules()
    observed: dict[str, Mapping[str, Any]] = {}
    for raw in vocs:
        row = _voc_mapping(raw)
        voc_id = _string(row.get("voc_id"), "VOC ID")
        if voc_id in GOVERNANCE_ROOT_VOC_IDS:
            if voc_id in observed:
                raise AtomicFactError("duplicate governance root VOC ID")
            observed[voc_id] = row
    external_by_root: dict[str, Mapping[str, Any]] = {}
    for raw in external_references:
        row = _voc_mapping(raw)
        post_id = _string(row.get("reddit_post_id"), "external Reddit post ID")
        root_voc_id = f"post:{post_id}"
        if root_voc_id in external_by_root or root_voc_id in observed:
            raise AtomicFactError("duplicate governance external root ID")
        external_by_root[root_voc_id] = row
    statuses: dict[str, str] = {}
    for voc_id in GOVERNANCE_ROOT_VOC_IDS:
        row = observed.get(voc_id)
        if row is None:
            external = external_by_root.get(voc_id)
            if external is None:
                statuses[voc_id] = "canonical_root_missing"
                continue
            try:
                external_facts = build_external_reference_atomic_facts(
                    external,
                    source_snapshot_id="governance_coverage_probe_external",
                    created_at="1970-01-01T00:00:00+00:00",
                )
            except AtomicFactError:
                statuses[voc_id] = "evidence_incomplete"
            else:
                statuses[voc_id] = (
                    "replayable_external_reference"
                    if external_facts
                    else "evidence_incomplete"
                )
            continue
        try:
            facts = build_atomic_facts(
                row,
                source_snapshot_id="governance_coverage_probe",
                created_at="1970-01-01T00:00:00+00:00",
            )
        except AtomicFactError:
            statuses[voc_id] = "evidence_incomplete"
        else:
            statuses[voc_id] = "replayable" if facts else "evidence_incomplete"
    available = sorted(
        voc_id
        for voc_id, status in statuses.items()
        if status in {"replayable", "replayable_external_reference"}
    )
    missing = sorted(
        voc_id
        for voc_id, status in statuses.items()
        if status == "canonical_root_missing"
    )
    incomplete = sorted(
        voc_id
        for voc_id, status in statuses.items()
        if status == "evidence_incomplete"
    )
    return {
        "available_root_voc_ids": available,
        "incomplete_root_voc_ids": incomplete,
        "missing_root_voc_ids": missing,
        "status_by_root_voc_id": statuses,
    }


def group_atomic_fact_tables(
    facts: Iterable[AtomicFact],
) -> dict[str, list[dict[str, object]]]:
    result: dict[str, list[dict[str, object]]] = {
        fact_type: [] for fact_type in ATOMIC_FACT_TYPES
    }
    seen: set[str] = set()
    for fact in facts:
        if not isinstance(fact, AtomicFact):
            raise AtomicFactError("atomic fact table input is invalid")
        if fact.fact_type not in result:
            raise AtomicFactError("atomic fact type is unsupported")
        if fact.fact_id in seen:
            raise AtomicFactError("duplicate atomic fact ID")
        seen.add(fact.fact_id)
        result[fact.fact_type].append(fact.as_dict())
    for rows in result.values():
        rows.sort(key=lambda row: str(row["fact_id"]))
    return result


def canonical_atomic_fact_jsonl_bytes(facts: Iterable[AtomicFact]) -> bytes:
    values = list(facts)
    if len({fact.fact_id for fact in values}) != len(values):
        raise AtomicFactError("duplicate atomic fact ID")
    values.sort(
        key=lambda fact: (
            fact.fact_type,
            fact.voc_id,
            fact.canonical_value,
            fact.evidence_field,
            fact.evidence_start,
            fact.fact_id,
        )
    )
    return b"".join(canonical_json_bytes(fact.as_dict()) + b"\n" for fact in values)


def validate_atomic_facts(
    facts: Iterable[AtomicFact],
    vocs: Mapping[str, object] | Iterable[object],
    *,
    source_snapshot_id: str,
    created_at: str,
    dictionary_release_id: str = DEFAULT_DICTIONARY_RELEASE_ID,
    matcher_version: str = DEFAULT_MATCHER_VERSION,
) -> None:
    _validate_registered_rules()
    source_snapshot_id = _string(source_snapshot_id, "source snapshot ID")
    created_at = _validate_created_at(created_at)
    dictionary_release_id = _string(
        dictionary_release_id, "dictionary release ID"
    )
    matcher_version = _string(matcher_version, "matcher version")
    if dictionary_release_id != DEFAULT_DICTIONARY_RELEASE_ID:
        raise AtomicFactError("dictionary release is not the frozen regression release")
    if matcher_version != DEFAULT_MATCHER_VERSION:
        raise AtomicFactError("matcher version is not the frozen regression matcher")

    if isinstance(vocs, Mapping):
        by_voc_id: dict[str, Mapping[str, Any]] = {}
        for key, raw in vocs.items():
            row = _voc_mapping(raw)
            voc_id = _string(row.get("voc_id"), "VOC ID")
            if str(key) != voc_id:
                raise AtomicFactError("validation VOC mapping key mismatch")
            if voc_id in by_voc_id:
                raise AtomicFactError("duplicate validation VOC ID")
            _validate_voc_identity(row)
            by_voc_id[voc_id] = row
    else:
        by_voc_id = {}
        for raw in vocs:
            row = _voc_mapping(raw)
            voc_id = _string(row.get("voc_id"), "VOC ID")
            if voc_id in by_voc_id:
                raise AtomicFactError("duplicate validation VOC ID")
            _validate_voc_identity(row)
            by_voc_id[voc_id] = row

    actual = tuple(facts)
    seen: set[str] = set()
    for fact in actual:
        if not isinstance(fact, AtomicFact):
            raise AtomicFactError("atomic fact validation input is invalid")
        if fact.fact_id in seen:
            raise AtomicFactError("duplicate atomic fact ID")
        seen.add(fact.fact_id)
        if fact.fact_type not in ATOMIC_FACT_TYPES:
            raise AtomicFactError("atomic fact type is unsupported")
        if fact.schema_version != ATOMIC_FACT_SCHEMA_VERSION:
            raise AtomicFactError("atomic fact schema is unsupported")
        if fact.decision_status not in DECISION_STATUSES:
            raise AtomicFactError("atomic fact decision status is invalid")
        if fact.reason_codes != tuple(sorted(set(fact.reason_codes))) or not fact.reason_codes:
            raise AtomicFactError("atomic fact reasons are invalid")
        if (
            fact.dictionary_release_id != dictionary_release_id
            or fact.matcher_version != matcher_version
            or fact.normalizer_version != NORMALIZER_VERSION
            or fact.source_snapshot_id != source_snapshot_id
            or fact.created_at != created_at
        ):
            raise AtomicFactError("atomic fact provenance mismatch")
        voc = by_voc_id.get(fact.voc_id)
        if voc is None:
            raise AtomicFactError("atomic fact VOC is missing")
        if (
            voc.get("canonical_entity_id") != fact.canonical_entity_id
            or voc.get("voc_type") != fact.voc_type
        ):
            raise AtomicFactError("atomic fact VOC identity mismatch")
        fields = _analysis_fields(voc)
        if fact.evidence_field not in fields:
            raise AtomicFactError("atomic fact evidence field is invalid")
        if fact.voc_type == "comment_context_voc" and fact.evidence_field != "current_comment_body":
            raise AtomicFactError("comment atomic fact inherited parent evidence")
        if fact.voc_type == "post_voc" and fact.evidence_field not in {
            "post_title",
            "post_body",
        }:
            raise AtomicFactError("post atomic fact evidence field is invalid")
        text = fields[fact.evidence_field]
        if not (
            0 <= fact.evidence_start < fact.evidence_end <= len(text)
        ):
            raise AtomicFactError("atomic fact evidence offsets are invalid")
        evidence = text[fact.evidence_start : fact.evidence_end]
        if sha256(evidence.encode("utf-8")).hexdigest() != fact.evidence_text_sha256:
            raise AtomicFactError("atomic fact evidence hash mismatch")
        if _fact_id(fact) != fact.fact_id:
            raise AtomicFactError("atomic fact ID mismatch")
        if (
            fact.evidence_scope != "direct"
            or fact.evidence_source_entity_id != fact.canonical_entity_id
            or fact.context_evidence_refs
        ):
            raise AtomicFactError("atomic fact evidence scope is invalid")

    expected = tuple(
        fact
        for voc_id in sorted(by_voc_id)
        for fact in build_atomic_facts(
            by_voc_id[voc_id],
            source_snapshot_id=source_snapshot_id,
            created_at=created_at,
            dictionary_release_id=dictionary_release_id,
            matcher_version=matcher_version,
        )
    )
    actual_documents = sorted(
        (fact.as_dict() for fact in actual), key=lambda row: str(row["fact_id"])
    )
    expected_documents = sorted(
        (fact.as_dict() for fact in expected), key=lambda row: str(row["fact_id"])
    )
    if actual_documents != expected_documents:
        raise AtomicFactError("atomic facts do not match frozen governed rules")
