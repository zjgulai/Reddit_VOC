from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping


POLICY_SCHEMA_VERSION = "reddit_voc_explicit_automation_policy_v1"
CLASSIFICATION_SCHEMA_VERSION = "reddit_voc_explicit_automation_classification_v1"
EXPECTED_BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}
EXPECTED_PATTERNS = (
    ("self_disclosed_bot", r"\bi am a bot\b"),
    (
        "automatic_action_disclosure",
        r"\bthis action was performed automatically\b",
    ),
    (
        "moderator_contact_disclosure",
        r"\bcontact the moderators of this subreddit\b",
    ),
    ("moderator_contact_link", r"/message/compose/\?to=/r/"),
)
EXPECTED_AUTHORITY_TEXT_FIELDS = {
    "governed_base": "body",
    "workbook_net_new": "source_text",
}
EXPECTED_FALLBACK_TEXT_FIELDS = ("body", "comment_body", "source_text")
EXPECTED_EXCLUDED_FAMILIES = ("RV-BR", "RV-IN", "RV-PS")
EXPECTED_AUDIT_INDICATORS = ("RV-CI-01",)
FOOTER_RULE_ID = "reddit_automation_footer_v1"
UPSTREAM_RULE_ID = "trusted_upstream_bot_state_v1"
DISCLOSURE_MATCH_IDS = (
    "self_disclosed_bot",
    "automatic_action_disclosure",
)
FOOTER_MATCH_IDS = tuple(match_id for match_id, _ in EXPECTED_PATTERNS)


class ExplicitAutomationError(ValueError):
    """The explicit-automation policy or input row is not governed."""


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
        raise ExplicitAutomationError(
            "value is not canonical JSON serializable"
        ) from exc


@dataclass(frozen=True)
class ExplicitAutomationPattern:
    match_id: str
    regex: str


@dataclass(frozen=True)
class ExplicitAutomationPolicy:
    policy_version: str
    policy_sha256: str
    matcher_version: str
    excluded_reason: str
    text_field_by_record_authority: dict[str, str]
    fallback_text_fields: tuple[str, ...]
    patterns: tuple[ExplicitAutomationPattern, ...]
    exclude_indicator_families: tuple[str, ...]
    audit_indicator_ids: tuple[str, ...]
    canonical_retention: bool
    commercial_attribution: str
    boundaries: dict[str, bool]
    schema_version: str = POLICY_SCHEMA_VERSION


@dataclass(frozen=True)
class AutomationEvidenceSpan:
    match_id: str
    field: str
    start: int
    end: int
    evidence_text_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "end": self.end,
            "evidence_text_sha256": self.evidence_text_sha256,
            "field": self.field,
            "match_id": self.match_id,
            "start": self.start,
        }


@dataclass(frozen=True)
class ExplicitAutomationClassification:
    canonical_entity_id: str
    entity_type: str
    record_authority: str
    comment_state: str
    text_field: str | None
    input_text_sha256: str | None
    audit_disclosure_detected: bool
    automation_determined: bool
    classification_status: str
    classification_accounting_bucket: str
    matched_rule_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    evidence_spans: tuple[AutomationEvidenceSpan, ...]
    upstream_automation_excluded: bool
    was_already_excluded: bool
    newly_excluded: bool
    requires_organic_exclusion: bool
    canonical_retained: bool
    excluded_reason: str | None
    commercial_attribution_status: str
    matcher_version: str
    policy_version: str
    policy_sha256: str
    schema_version: str = CLASSIFICATION_SCHEMA_VERSION

    @property
    def detected(self) -> bool:
        """Frozen disclosure-audit compatibility field, not the final decision."""
        return self.audit_disclosure_detected

    @property
    def organic_automation_eligible(self) -> bool:
        return not self.requires_organic_exclusion

    def as_dict(self) -> dict[str, object]:
        return {
            "audit_disclosure_detected": self.audit_disclosure_detected,
            "automation_determined": self.automation_determined,
            "canonical_entity_id": self.canonical_entity_id,
            "canonical_retained": self.canonical_retained,
            "classification_status": self.classification_status,
            "classification_accounting_bucket": self.classification_accounting_bucket,
            "comment_state": self.comment_state,
            "commercial_attribution_status": self.commercial_attribution_status,
            "entity_type": self.entity_type,
            "evidence_spans": [span.as_dict() for span in self.evidence_spans],
            "excluded_reason": self.excluded_reason,
            "input_text_sha256": self.input_text_sha256,
            "matched_rule_ids": list(self.matched_rule_ids),
            "matcher_version": self.matcher_version,
            "newly_excluded": self.newly_excluded,
            "policy_sha256": self.policy_sha256,
            "policy_version": self.policy_version,
            "reason_codes": list(self.reason_codes),
            "record_authority": self.record_authority,
            "requires_organic_exclusion": self.requires_organic_exclusion,
            "schema_version": self.schema_version,
            "text_field": self.text_field,
            "upstream_automation_excluded": self.upstream_automation_excluded,
            "was_already_excluded": self.was_already_excluded,
        }


def _non_empty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ExplicitAutomationError(f"{label} must be a non-empty string")
    return value


def _canonical_policy_sha(value: Mapping[str, object]) -> str:
    return sha256(canonical_json_bytes(value) + b"\n").hexdigest()


def parse_explicit_automation_policy(value: object) -> ExplicitAutomationPolicy:
    if not isinstance(value, Mapping):
        raise ExplicitAutomationError("explicit automation policy must be an object")
    expected_keys = {
        "audit_indicator_ids",
        "boundaries",
        "canonical_retention",
        "commercial_attribution",
        "deterministic_rules",
        "exclude_indicator_families",
        "excluded_reason",
        "fallback_text_fields",
        "held_signal_rules",
        "matcher_version",
        "patterns",
        "policy_version",
        "schema_version",
        "text_field_by_record_authority",
    }
    if set(value) != expected_keys:
        raise ExplicitAutomationError("explicit automation policy fields are invalid")
    if value.get("schema_version") != POLICY_SCHEMA_VERSION:
        raise ExplicitAutomationError("explicit automation policy schema is unsupported")
    if value.get("boundaries") != EXPECTED_BOUNDARIES:
        raise ExplicitAutomationError("explicit automation boundaries are invalid")
    if value.get("excluded_reason") != "explicit_automation":
        raise ExplicitAutomationError("explicit automation excluded reason is invalid")
    if value.get("matcher_version") != "explicit_bot_disclosure_regex_audit_v1":
        raise ExplicitAutomationError("explicit automation matcher version is invalid")
    if value.get("canonical_retention") is not True:
        raise ExplicitAutomationError("explicit automation retention is invalid")
    if value.get("commercial_attribution") != "not_inferred":
        raise ExplicitAutomationError(
            "explicit automation commercial attribution is invalid"
        )
    if value.get("text_field_by_record_authority") != EXPECTED_AUTHORITY_TEXT_FIELDS:
        raise ExplicitAutomationError("explicit automation text fields are invalid")
    fallback_fields = value.get("fallback_text_fields")
    if (
        not isinstance(fallback_fields, list)
        or tuple(fallback_fields) != EXPECTED_FALLBACK_TEXT_FIELDS
    ):
        raise ExplicitAutomationError("explicit automation fallback fields are invalid")
    if value.get("exclude_indicator_families") != list(EXPECTED_EXCLUDED_FAMILIES):
        raise ExplicitAutomationError("explicit automation indicator families are invalid")
    if value.get("audit_indicator_ids") != list(EXPECTED_AUDIT_INDICATORS):
        raise ExplicitAutomationError("explicit automation audit indicators are invalid")
    expected_rules = [
        {
            "max_disclosure_gap_code_points": 16,
            "quoted_line_behavior": "held",
            "required_match_ids": list(FOOTER_MATCH_IDS),
            "rule_id": FOOTER_RULE_ID,
            "same_paragraph": True,
        },
        {
            "required_bot_detection_status": "known_from_archive_author",
            "required_is_bot": True,
            "rule_id": UPSTREAM_RULE_ID,
        },
    ]
    if value.get("deterministic_rules") != expected_rules:
        raise ExplicitAutomationError("explicit automation deterministic rules are invalid")
    if value.get("held_signal_rules") != [
        "single_disclosure",
        "quoted_disclosure",
    ]:
        raise ExplicitAutomationError("explicit automation held rules are invalid")
    raw_patterns = value.get("patterns")
    if not isinstance(raw_patterns, list):
        raise ExplicitAutomationError("explicit automation patterns are invalid")
    observed_patterns: list[tuple[str, str]] = []
    for raw_pattern in raw_patterns:
        if not isinstance(raw_pattern, Mapping) or set(raw_pattern) != {
            "match_id",
            "regex",
        }:
            raise ExplicitAutomationError("explicit automation patterns are invalid")
        observed_patterns.append(
            (
                _non_empty_string(raw_pattern.get("match_id"), "match ID"),
                _non_empty_string(raw_pattern.get("regex"), "regex"),
            )
        )
    if tuple(observed_patterns) != EXPECTED_PATTERNS:
        raise ExplicitAutomationError("explicit automation patterns are invalid")
    policy_version = _non_empty_string(value.get("policy_version"), "policy version")
    return ExplicitAutomationPolicy(
        policy_version=policy_version,
        policy_sha256=_canonical_policy_sha(value),
        matcher_version="explicit_bot_disclosure_regex_audit_v1",
        excluded_reason="explicit_automation",
        text_field_by_record_authority=dict(EXPECTED_AUTHORITY_TEXT_FIELDS),
        fallback_text_fields=EXPECTED_FALLBACK_TEXT_FIELDS,
        patterns=tuple(
            ExplicitAutomationPattern(match_id=match_id, regex=pattern)
            for match_id, pattern in EXPECTED_PATTERNS
        ),
        exclude_indicator_families=EXPECTED_EXCLUDED_FAMILIES,
        audit_indicator_ids=EXPECTED_AUDIT_INDICATORS,
        canonical_retention=True,
        commercial_attribution="not_inferred",
        boundaries=dict(EXPECTED_BOUNDARIES),
    )


def load_explicit_automation_policy(path: Path) -> ExplicitAutomationPolicy:
    try:
        payload = Path(path).read_bytes()
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExplicitAutomationError(
            "explicit automation policy is unreadable"
        ) from exc
    if payload != canonical_json_bytes(value) + b"\n":
        raise ExplicitAutomationError(
            "explicit automation policy is not canonical JSON"
        )
    return parse_explicit_automation_policy(value)


def _record(row: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = row.get("record")
    if nested is None:
        return row
    if not isinstance(nested, Mapping):
        raise ExplicitAutomationError("canonical record must be an object")
    return nested


def _first_value(
    row: Mapping[str, Any], record: Mapping[str, Any], names: tuple[str, ...]
) -> object:
    for container in (record, row):
        for name in names:
            if name in container:
                return container[name]
    return None


def _entity_id(row: Mapping[str, Any], record: Mapping[str, Any]) -> str:
    value = _first_value(
        row,
        record,
        ("canonical_reddit_id", "reddit_id", "comment_id", "entity_id"),
    )
    entity_id = _non_empty_string(value, "canonical entity ID")
    if re.fullmatch(r"t1_[a-z0-9]+", entity_id) is None:
        raise ExplicitAutomationError("canonical entity ID is invalid")
    return entity_id


def _authority(row: Mapping[str, Any]) -> str:
    value = row.get("record_authority")
    if value is None:
        if row.get("record") is not None:
            raise ExplicitAutomationError("canonical record authority is required")
        return "flat_snapshot"
    authority = _non_empty_string(value, "record authority")
    if authority not in EXPECTED_AUTHORITY_TEXT_FIELDS:
        raise ExplicitAutomationError("record authority is not governed")
    return authority


def _validate_input_contract(
    row: Mapping[str, Any],
    record: Mapping[str, Any],
    entity_id: str,
    authority: str,
) -> str:
    if record is row:
        state = row.get("comment_state")
        if state is None:
            return "flat_snapshot"
        if state != "flat_snapshot":
            raise ExplicitAutomationError("flat snapshot comment state is invalid")
        return "flat_snapshot"

    if (
        row.get("canonical_identity_state") != "canonical_identity"
        or row.get("entity_type") != "comment"
        or row.get("schema_version") != "reddit_voc_canonical_comment_v1"
    ):
        raise ExplicitAutomationError("canonical comment header is invalid")
    if row.get("canonical_reddit_id") != entity_id:
        raise ExplicitAutomationError("canonical wrapper identity mismatch")
    for name in ("canonical_reddit_id", "reddit_id", "comment_id"):
        if name in record and record[name] is not None and record[name] != entity_id:
            raise ExplicitAutomationError("canonical record identity mismatch")
    state = row.get("comment_state")
    if state not in {"linked", "unresolved_parent"}:
        raise ExplicitAutomationError("canonical comment state is invalid")
    if authority not in EXPECTED_AUTHORITY_TEXT_FIELDS:
        raise ExplicitAutomationError("canonical record authority is invalid")
    return state


def _selected_text(
    row: Mapping[str, Any],
    record: Mapping[str, Any],
    authority: str,
    policy: ExplicitAutomationPolicy,
) -> tuple[str | None, str]:
    governed_field = policy.text_field_by_record_authority.get(authority)
    if governed_field is not None:
        if governed_field not in record:
            raise ExplicitAutomationError(
                f"governed automation text field {governed_field} is missing"
            )
        value = record[governed_field]
        if value is None:
            return governed_field, ""
        if not isinstance(value, str):
            raise ExplicitAutomationError(
                f"{governed_field} must be a string or null"
            )
        return governed_field, value
    candidates: list[tuple[str, str]] = []
    for name in policy.fallback_text_fields:
        value = record.get(name)
        if value is None and record is not row:
            value = row.get(name)
        if value is None:
            continue
        if not isinstance(value, str):
            raise ExplicitAutomationError(f"{name} must be a string or null")
        if value:
            candidates.append((name, value))
    if not candidates:
        return None, ""
    distinct_values = {text for _, text in candidates}
    if len(distinct_values) != 1:
        raise ExplicitAutomationError("automation text authority is ambiguous")
    return candidates[0]


def _line_is_quote(text: str, start: int) -> bool:
    line_start = text.rfind("\n", 0, start) + 1
    return text[line_start:start].lstrip().startswith(">")


def _paragraph_bounds(text: str, position: int) -> tuple[int, int]:
    start = text.rfind("\n\n", 0, position)
    start = 0 if start < 0 else start + 2
    end = text.find("\n\n", position)
    end = len(text) if end < 0 else end
    return start, end


def _evidence_spans(
    text: str,
    field: str | None,
    compiled: tuple[tuple[str, re.Pattern[str]], ...],
) -> tuple[AutomationEvidenceSpan, ...]:
    if field is None:
        return ()
    spans: list[AutomationEvidenceSpan] = []
    for match_id, pattern in compiled:
        for match in pattern.finditer(text):
            evidence_text = text[match.start() : match.end()]
            spans.append(
                AutomationEvidenceSpan(
                    match_id=match_id,
                    field=field,
                    start=match.start(),
                    end=match.end(),
                    evidence_text_sha256=sha256(
                        evidence_text.encode("utf-8")
                    ).hexdigest(),
                )
            )
    spans.sort(key=lambda span: (span.start, span.end, span.match_id))
    return tuple(spans)


def _footer_determined(
    text: str, spans: tuple[AutomationEvidenceSpan, ...]
) -> tuple[bool, bool]:
    by_id: dict[str, list[AutomationEvidenceSpan]] = {}
    for span in spans:
        by_id.setdefault(span.match_id, []).append(span)
    audit_detected = all(by_id.get(match_id) for match_id in DISCLOSURE_MATCH_IDS)
    if not all(by_id.get(match_id) for match_id in FOOTER_MATCH_IDS):
        return audit_detected or any(by_id.get(mid) for mid in DISCLOSURE_MATCH_IDS), False
    for first in by_id["self_disclosed_bot"]:
        for second in by_id["automatic_action_disclosure"]:
            if second.start < first.end or second.start - first.end > 16:
                continue
            paragraph = _paragraph_bounds(text, first.start)
            if not (
                paragraph[0] <= second.start < second.end <= paragraph[1]
            ):
                continue
            for contact in by_id["moderator_contact_disclosure"]:
                if not (
                    second.end <= contact.start < contact.end <= paragraph[1]
                ):
                    continue
                for link in by_id["moderator_contact_link"]:
                    if not (
                        contact.end <= link.start < link.end <= paragraph[1]
                    ):
                        continue
                    selected = (first, second, contact, link)
                    if all(
                        not _line_is_quote(text, span.start) for span in selected
                    ):
                        return True, True
    return audit_detected, False


def classify_explicit_automation(
    rows: Iterable[Mapping[str, Any]],
    *,
    policy: ExplicitAutomationPolicy,
) -> tuple[ExplicitAutomationClassification, ...]:
    compiled = tuple(
        (pattern.match_id, re.compile(pattern.regex, re.IGNORECASE))
        for pattern in policy.patterns
    )
    classifications: list[ExplicitAutomationClassification] = []
    seen: set[str] = set()
    for raw_row in rows:
        if not isinstance(raw_row, Mapping):
            raise ExplicitAutomationError("explicit automation input must be an object")
        row = raw_row
        record = _record(row)
        entity_id = _entity_id(row, record)
        if entity_id in seen:
            raise ExplicitAutomationError("duplicate explicit automation entity")
        seen.add(entity_id)
        authority = _authority(row)
        comment_state = _validate_input_contract(
            row, record, entity_id, authority
        )
        field, text = _selected_text(row, record, authority, policy)
        spans = _evidence_spans(text, field, compiled)
        audit_detected, footer_determined = _footer_determined(text, spans)

        is_bot = _first_value(row, record, ("is_bot",))
        bot_status = _first_value(row, record, ("bot_detection_status",))
        if is_bot is not None and type(is_bot) is not bool:
            raise ExplicitAutomationError("is_bot must be a boolean or null")
        if bot_status is not None and not isinstance(bot_status, str):
            raise ExplicitAutomationError(
                "bot_detection_status must be a string or null"
            )
        upstream_known_bot = (
            is_bot is True and bot_status == "known_from_archive_author"
        )
        if upstream_known_bot and authority == "workbook_net_new":
            raise ExplicitAutomationError(
                "workbook trusted bot state is not governed"
            )
        determined = footer_determined or upstream_known_bot
        status = (
            "determined"
            if determined
            else "held"
            if audit_detected
            else "not_detected"
        )
        accounting_bucket = (
            "already_excluded_disclosure"
            if footer_determined and upstream_known_bot
            else "newly_excluded_disclosure"
            if footer_determined
            else "upstream_known_bot_only"
            if upstream_known_bot
            else "held_disclosure"
            if audit_detected
            else "not_automation"
        )
        matched_rules: list[str] = []
        reasons: list[str] = []
        if footer_determined:
            matched_rules.append(FOOTER_RULE_ID)
            reasons.append("reddit_automation_footer")
        elif audit_detected:
            reasons.append("incomplete_or_quoted_automation_disclosure")
        if upstream_known_bot:
            matched_rules.append(UPSTREAM_RULE_ID)
            reasons.append("upstream_known_bot")
        if not reasons:
            reasons.append("no_automation_signal")
        classifications.append(
            ExplicitAutomationClassification(
                canonical_entity_id=entity_id,
                entity_type="comment",
                record_authority=authority,
                comment_state=comment_state,
                text_field=field,
                input_text_sha256=sha256(text.encode("utf-8")).hexdigest()
                if field is not None
                else None,
                audit_disclosure_detected=audit_detected,
                automation_determined=determined,
                classification_status=status,
                classification_accounting_bucket=accounting_bucket,
                matched_rule_ids=tuple(sorted(matched_rules)),
                reason_codes=tuple(sorted(reasons)),
                evidence_spans=spans,
                upstream_automation_excluded=upstream_known_bot,
                was_already_excluded=upstream_known_bot,
                newly_excluded=determined and not upstream_known_bot,
                requires_organic_exclusion=determined,
                canonical_retained=policy.canonical_retention,
                excluded_reason=policy.excluded_reason if determined else None,
                commercial_attribution_status=policy.commercial_attribution,
                matcher_version=policy.matcher_version,
                policy_version=policy.policy_version,
                policy_sha256=policy.policy_sha256,
            )
        )
    classifications.sort(key=lambda row: row.canonical_entity_id)
    return tuple(classifications)


def organic_exclusion_map(
    rows: Iterable[ExplicitAutomationClassification],
) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, ExplicitAutomationClassification):
            raise ExplicitAutomationError(
                "automation exclusions require classification rows"
            )
        if row.requires_organic_exclusion:
            if row.canonical_entity_id in result:
                raise ExplicitAutomationError("duplicate automation exclusion")
            result[row.canonical_entity_id] = "explicit_automation"
    return dict(sorted(result.items()))
