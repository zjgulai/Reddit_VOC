#!/usr/bin/env python3
"""Build the immutable V3 82-atom/8-cohort content-persona snapshot."""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from reddit_voc.v3_persona_inference import (  # noqa: E402
    canonical_json_bytes,
    load_persona_cohort_config,
    load_persona_dictionary,
    validate_governed_signal_fact,
)
from reddit_voc.v3_persona_snapshot import (  # noqa: E402
    build_v3_persona_documents,
    write_v3_persona_snapshot,
)


class PersonaBuildCliError(ValueError):
    pass


_AUTOMATION_CLASSIFICATION_KEYS = {
    "audit_disclosure_detected",
    "automation_determined",
    "canonical_entity_id",
    "canonical_retained",
    "classification_accounting_bucket",
    "classification_status",
    "comment_state",
    "commercial_attribution_status",
    "entity_type",
    "evidence_spans",
    "excluded_reason",
    "input_text_sha256",
    "matched_rule_ids",
    "matcher_version",
    "newly_excluded",
    "policy_sha256",
    "policy_version",
    "reason_codes",
    "record_authority",
    "requires_organic_exclusion",
    "schema_version",
    "text_field",
    "upstream_automation_excluded",
    "was_already_excluded",
}
_FOOTER_RULE_ID = "reddit_automation_footer_v1"
_UPSTREAM_RULE_ID = "trusted_upstream_bot_state_v1"
_FOOTER_MATCH_IDS = {
    "self_disclosed_bot",
    "automatic_action_disclosure",
    "moderator_contact_disclosure",
    "moderator_contact_link",
}
_BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}
_GOVERNED_SIGNAL_FILES = (
    "commercial-relation-facts.jsonl",
    "community-governance-facts.jsonl",
    "entity-brand-facts.jsonl",
    "entity-problem-facts.jsonl",
    "entity-product-facts.jsonl",
    "entity-sentiment-facts.jsonl",
    "entity-tag-facts.jsonl",
    "integrity-signal-facts.jsonl",
)
_PERSONA_SIGNAL_FACT_FILES = {
    "entity-brand-facts.jsonl": "entity_brand_fact",
    "entity-problem-facts.jsonl": "entity_problem_fact",
    "entity-tag-facts.jsonl": "entity_tag_fact",
}


@dataclass(frozen=True)
class BoundGovernedPersonaSignals:
    signals_by_voc_id: dict[str, dict[str, object]]
    facts_by_voc_id: dict[str, dict[str, dict[str, object]]]
    manifest_sha256: str
    validation_receipt_sha256: str
    snapshot_id: str
    source_snapshot_id: str
    loaded_promoted_fact_count: int
    injected_fact_count: int
    injected_voc_count: int
    dropped_comment_fact_count: int
    dropped_comment_voc_count: int
    consumption_status: str
    promotable: bool


def _validate_automation_classification_state(row: object) -> None:
    """Validate the serialized classifier state machine without trusting its flag."""
    if not isinstance(row, dict) or set(row) != _AUTOMATION_CLASSIFICATION_KEYS:
        raise PersonaBuildCliError("automation classification row is invalid")
    booleans = (
        "audit_disclosure_detected",
        "automation_determined",
        "canonical_retained",
        "newly_excluded",
        "requires_organic_exclusion",
        "upstream_automation_excluded",
        "was_already_excluded",
    )
    if any(type(row.get(name)) is not bool for name in booleans):
        raise PersonaBuildCliError("automation classification state is invalid")
    matched = row.get("matched_rule_ids")
    reasons = row.get("reason_codes")
    evidence = row.get("evidence_spans")
    if (
        not isinstance(matched, list)
        or any(not isinstance(value, str) or not value for value in matched)
        or matched != sorted(set(matched))
        or not isinstance(reasons, list)
        or any(not isinstance(value, str) or not value for value in reasons)
        or reasons != sorted(set(reasons))
        or not isinstance(evidence, list)
    ):
        raise PersonaBuildCliError("automation classification state is invalid")
    text_field = row.get("text_field")
    input_hash = row.get("input_text_sha256")
    if (text_field is None) is not (input_hash is None) or (
        text_field is not None
        and (
            not isinstance(text_field, str)
            or not text_field
            or not isinstance(input_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", input_hash) is None
        )
    ):
        raise PersonaBuildCliError("automation classification text state is invalid")
    observed_match_ids: set[str] = set()
    for span in evidence:
        if (
            not isinstance(span, dict)
            or set(span)
            != {"end", "evidence_text_sha256", "field", "match_id", "start"}
            or type(span.get("start")) is not int
            or type(span.get("end")) is not int
            or span["start"] < 0
            or span["end"] <= span["start"]
            or span.get("field") != text_field
            or span.get("match_id") not in _FOOTER_MATCH_IDS
            or not isinstance(span.get("evidence_text_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", span["evidence_text_sha256"])
            is None
        ):
            raise PersonaBuildCliError("automation classification evidence is invalid")
        observed_match_ids.add(str(span["match_id"]))

    determined = row["automation_determined"]
    upstream = row["upstream_automation_excluded"]
    footer = _FOOTER_RULE_ID in matched
    upstream_rule = _UPSTREAM_RULE_ID in matched
    held = row.get("classification_status") == "held"
    if set(matched) - {_FOOTER_RULE_ID, _UPSTREAM_RULE_ID}:
        raise PersonaBuildCliError("automation classification rules are invalid")
    if footer and not _FOOTER_MATCH_IDS <= observed_match_ids:
        raise PersonaBuildCliError("automation footer evidence is incomplete")
    if (not footer and not held) and evidence:
        raise PersonaBuildCliError("automation evidence is unbound")

    expected_reasons: list[str]
    if footer or upstream:
        expected_reasons = sorted(
            (["reddit_automation_footer"] if footer else [])
            + (["upstream_known_bot"] if upstream else [])
        )
    elif held:
        expected_reasons = ["incomplete_or_quoted_automation_disclosure"]
    else:
        expected_reasons = ["no_automation_signal"]
    expected_rules = sorted(
        ([_FOOTER_RULE_ID] if footer else [])
        + ([_UPSTREAM_RULE_ID] if upstream else [])
    )
    expected_status = "determined" if footer or upstream else "held" if held else "not_detected"
    expected_bucket = (
        "already_excluded_disclosure"
        if footer and upstream
        else "newly_excluded_disclosure"
        if footer
        else "upstream_known_bot_only"
        if upstream
        else "held_disclosure"
        if held
        else "not_automation"
    )
    if (
        matched != expected_rules
        or reasons != expected_reasons
        or row.get("classification_status") != expected_status
        or row.get("classification_accounting_bucket") != expected_bucket
        or row["audit_disclosure_detected"] is not (footer or held)
        or determined is not (footer or upstream)
        or upstream_rule is not upstream
        or row["requires_organic_exclusion"] is not determined
        or row["was_already_excluded"] is not upstream
        or row["newly_excluded"] is not (determined and not upstream)
        or row["canonical_retained"] is not True
        or row.get("excluded_reason")
        != ("explicit_automation" if determined else None)
        or row.get("commercial_attribution_status") != "not_inferred"
    ):
        raise PersonaBuildCliError("automation classification state is invalid")


def _sha(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, *, require_compact_canonical: bool = True) -> dict[str, Any]:
    payload = path.read_bytes()
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PersonaBuildCliError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict) or (
        require_compact_canonical
        and payload != canonical_json_bytes(value) + b"\n"
    ):
        raise PersonaBuildCliError(f"non-canonical JSON object: {path}")
    return value


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    with path.open("rb") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                value = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise PersonaBuildCliError(
                    f"invalid JSONL row: {path}:{line_number}"
                ) from exc
            if not isinstance(value, dict) or line != canonical_json_bytes(value) + b"\n":
                raise PersonaBuildCliError(
                    f"non-canonical JSONL row: {path}:{line_number}"
                )
            values.append(value)
    return values


def _verify_file_contract(root: Path, name: str, contract: object) -> None:
    if (
        not isinstance(contract, dict)
        or set(contract) != {"bytes", "rows", "sha256"}
        or isinstance(contract.get("rows"), bool)
        or not isinstance(contract.get("rows"), int)
        or int(contract["rows"]) < 0
    ):
        raise PersonaBuildCliError(f"invalid facts file contract: {name}")
    path = root / name
    if (
        not path.is_file()
        or path.is_symlink()
        or path.stat().st_size != contract.get("bytes")
        or _sha(path) != contract.get("sha256")
    ):
        raise PersonaBuildCliError(f"facts file contract mismatch: {name}")


def load_bound_persona_inputs(
    *,
    facts_dir: Path,
    expected_facts_manifest_sha256: str,
    facts_validation_receipt_path: Path,
    expected_facts_validation_receipt_sha256: str,
    reference_manifest_path: Path,
    expected_reference_manifest_sha256: str,
    allow_blocked_upstream_candidate: bool,
) -> tuple[
    list[dict[str, Any]],
    set[str],
    str,
    str,
    str,
    int,
    str,
    str,
    bool,
]:
    if facts_dir.is_symlink():
        raise PersonaBuildCliError("facts directory is a symlink")
    root = facts_dir.resolve(strict=True)
    manifest_path = root / "manifest.json"
    if _sha(manifest_path) != expected_facts_manifest_sha256:
        raise PersonaBuildCliError("facts manifest SHA mismatch")
    manifest = _load_json(manifest_path)
    if manifest.get("schema_version") != "reddit_voc_voc_facts_manifest_v2":
        raise PersonaBuildCliError("facts manifest schema mismatch")
    boundaries = manifest.get("boundaries")
    if not isinstance(boundaries, dict) or any(
        boundaries.get(key) is not False
        for key in ("database_write", "deploy", "live_send", "provider_call", "remote_write")
    ) or boundaries.get("production_unchanged") is not True:
        raise PersonaBuildCliError("facts manifest boundary mismatch")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise PersonaBuildCliError("facts manifest files are invalid")
    for required in ("vocs.jsonl", "automation-classifications.jsonl"):
        if required not in files:
            raise PersonaBuildCliError(f"facts a2 file missing: {required}")
        _verify_file_contract(root, required, files[required])

    if facts_validation_receipt_path.is_symlink():
        raise PersonaBuildCliError("facts validation receipt is a symlink")
    facts_receipt_path = facts_validation_receipt_path.resolve(strict=True)
    if _sha(facts_receipt_path) != expected_facts_validation_receipt_sha256:
        raise PersonaBuildCliError("facts validation receipt SHA mismatch")
    facts_receipt = _load_json(facts_receipt_path)
    if (
        facts_receipt.get("schema_version")
        != "reddit_voc_voc_facts_validation_receipt_v2"
        or facts_receipt.get("status") != "passed"
        or facts_receipt.get("bundle_manifest_sha256")
        != expected_facts_manifest_sha256
        or facts_receipt.get("counts") != manifest.get("counts")
        or facts_receipt.get("boundaries") != boundaries
        or type(facts_receipt.get("unaccounted_eligibility_members")) is not int
        or facts_receipt.get("unaccounted_eligibility_members") != 0
        or type(facts_receipt.get("unaccounted_vocs")) is not int
        or facts_receipt.get("unaccounted_vocs") != 0
    ):
        raise PersonaBuildCliError("facts validation receipt binding mismatch")
    manifest_inputs = manifest.get("inputs")
    if not isinstance(manifest_inputs, dict):
        raise PersonaBuildCliError("facts manifest inputs are invalid")
    for key in (
        "automation_family_contract_sha256",
        "automation_policy_sha256",
        "canonical_comments_sha256",
        "canonical_manifest_sha256",
        "canonical_validation_receipt_sha256",
        "eligibility_policy_sha256",
    ):
        if facts_receipt.get(key) != manifest_inputs.get(key):
            raise PersonaBuildCliError(f"facts receipt input binding mismatch: {key}")
    upstream_consumption_status = facts_receipt.get("consumption_status")
    upstream_promotable = facts_receipt.get("promotable")
    if upstream_consumption_status == "blocked_pending_atomic_facts":
        if upstream_promotable is not False or not allow_blocked_upstream_candidate:
            raise PersonaBuildCliError(
                "facts upstream is blocked pending atomic facts"
            )
    elif (
        upstream_consumption_status != "eligible_for_downstream_consumption"
        or upstream_promotable is not True
    ):
        raise PersonaBuildCliError("facts upstream consumption state is invalid")

    if reference_manifest_path.is_symlink():
        raise PersonaBuildCliError("reference manifest is a symlink")
    reference = reference_manifest_path.resolve(strict=True)
    if _sha(reference) != expected_reference_manifest_sha256:
        raise PersonaBuildCliError("reference manifest SHA mismatch")
    reference_value = _load_json(reference, require_compact_canonical=False)
    if reference_value.get("schema_version") != "reddit_voc_v3_reference_manifest_v1":
        raise PersonaBuildCliError("reference manifest schema mismatch")

    vocs = _load_jsonl(root / "vocs.jsonl")
    counts = manifest.get("counts")
    canonical_counts = manifest.get("canonical_counts")
    if not isinstance(counts, dict) or not isinstance(canonical_counts, dict):
        raise PersonaBuildCliError("facts manifest counts are invalid")
    if (
        len(vocs) != files["vocs.jsonl"]["rows"]
        or len(vocs) != counts.get("total_vocs")
    ):
        raise PersonaBuildCliError("facts VOC row accounting mismatch")
    entity_to_voc: dict[str, str] = {}
    for row in vocs:
        entity_id = row.get("canonical_entity_id")
        voc_id = row.get("voc_id")
        if not isinstance(entity_id, str) or not isinstance(voc_id, str) or entity_id in entity_to_voc:
            raise PersonaBuildCliError("facts VOC identity set is invalid")
        entity_to_voc[entity_id] = voc_id
    classifications = _load_jsonl(root / "automation-classifications.jsonl")
    if (
        len(classifications)
        != files["automation-classifications.jsonl"]["rows"]
        or len(classifications) != canonical_counts.get("comments_jsonl")
    ):
        raise PersonaBuildCliError("automation classification row accounting mismatch")
    classification_entities: set[str] = set()
    expected_policy_sha = manifest_inputs.get("automation_policy_sha256")
    expected_policy_version = manifest.get("automation_policy_version")
    for row in classifications:
        _validate_automation_classification_state(row)
        entity_id = row.get("canonical_entity_id")
        determined = row.get("automation_determined")
        excluded = row.get("requires_organic_exclusion")
        if (
            row.get("schema_version")
            != "reddit_voc_explicit_automation_classification_v1"
            or row.get("entity_type") != "comment"
            or not isinstance(entity_id, str)
            or re.fullmatch(r"t1_[a-z0-9]+", entity_id) is None
            or entity_id in classification_entities
            or row.get("record_authority")
            not in {"governed_base", "workbook_net_new"}
            or row.get("comment_state") not in {"linked", "unresolved_parent"}
            or row.get("classification_status")
            not in {"determined", "held", "not_detected"}
            or type(determined) is not bool
            or type(excluded) is not bool
            or determined is not excluded
            or row.get("canonical_retained") is not True
            or row.get("policy_sha256") != expected_policy_sha
            or row.get("policy_version") != expected_policy_version
            or row.get("matcher_version")
            != "explicit_bot_disclosure_regex_audit_v1"
            or (
                row.get("excluded_reason")
                != ("explicit_automation" if determined else None)
            )
        ):
            raise PersonaBuildCliError("automation classification row is invalid")
        classification_entities.add(entity_id)
    automation_entities = {
        str(row["canonical_entity_id"])
        for row in classifications
        if row.get("automation_determined") is True
        and row.get("requires_organic_exclusion") is True
    }
    automation_vocs = {
        entity_to_voc[entity_id]
        for entity_id in automation_entities & set(entity_to_voc)
    }
    if (
        counts.get("automation_total") != len(automation_entities)
        or counts.get("automation_voc") != len(automation_vocs)
        or counts.get("automation_non_voc") != len(automation_entities - set(entity_to_voc))
    ):
        raise PersonaBuildCliError("facts automation accounting mismatch")
    return (
        vocs,
        automation_vocs,
        expected_facts_manifest_sha256,
        expected_facts_validation_receipt_sha256,
        str(files["automation-classifications.jsonl"]["sha256"]),
        len(classifications),
        expected_reference_manifest_sha256,
        str(upstream_consumption_status),
        bool(upstream_promotable),
    )


def _verify_governed_file_contract(
    root: Path, name: str, contract: object
) -> dict[str, object]:
    if (
        not isinstance(contract, dict)
        or set(contract) != {"bytes", "rows", "sha256"}
        or type(contract.get("bytes")) is not int
        or contract["bytes"] < 0
        or type(contract.get("rows")) is not int
        or contract["rows"] < 0
        or not isinstance(contract.get("sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", str(contract["sha256"])) is None
    ):
        raise PersonaBuildCliError(
            f"invalid governed signal file contract: {name}"
        )
    path = root / name
    if (
        not path.is_file()
        or path.is_symlink()
        or path.stat().st_size != contract["bytes"]
        or _sha(path) != contract["sha256"]
    ):
        raise PersonaBuildCliError(
            f"governed signal file contract mismatch: {name}"
        )
    return contract


def _load_promoted_governed_signal_facts(
    path: Path,
    *,
    expected_rows: int,
    expected_fact_type: str,
    expected_source_snapshot_id: str,
) -> list[dict[str, object]]:
    promoted: list[dict[str, object]] = []
    observed_rows = 0
    with path.open("rb") as handle:
        for line_number, line in enumerate(handle, start=1):
            observed_rows += 1
            try:
                row = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise PersonaBuildCliError(
                    f"invalid governed signal JSONL row: {path}:{line_number}"
                ) from exc
            if not isinstance(row, dict) or line != canonical_json_bytes(row) + b"\n":
                raise PersonaBuildCliError(
                    f"non-canonical governed signal JSONL row: {path}:{line_number}"
                )
            status = row.get("decision_status")
            if status not in {"held", "promoted", "rejected"}:
                raise PersonaBuildCliError(
                    f"invalid governed signal decision: {path}:{line_number}"
                )
            if row.get("fact_type") != expected_fact_type:
                raise PersonaBuildCliError(
                    f"governed signal fact type mismatch: {path}:{line_number}"
                )
            if status != "promoted":
                continue
            fact_id = row.get("fact_id")
            try:
                validate_governed_signal_fact(
                    row,
                    registry_fact_id=str(fact_id),
                )
            except ValueError as exc:
                raise PersonaBuildCliError(
                    f"invalid promoted governed signal fact: {path}:{line_number}"
                ) from exc
            if row.get("source_snapshot_id") != expected_source_snapshot_id:
                raise PersonaBuildCliError(
                    f"governed signal source snapshot mismatch: {path}:{line_number}"
                )
            promoted.append(row)
    if observed_rows != expected_rows:
        raise PersonaBuildCliError(
            f"governed signal row accounting mismatch: {path.name}"
        )
    return promoted


def _signal_name_for_fact(row: Mapping[str, object]) -> str:
    fact_type = row.get("fact_type")
    attributes = row.get("attributes")
    canonical_value = row.get("canonical_value")
    if not isinstance(attributes, Mapping):
        raise PersonaBuildCliError("governed signal attributes are invalid")
    if fact_type == "entity_brand_fact":
        valid_brand = (
            canonical_value == "momcozy"
            and attributes.get("brand_id") == "momcozy"
            and attributes.get("brand_role") == "focal"
        ) or (
            canonical_value == "competitor"
            and attributes.get("brand_id") != "momcozy"
            and attributes.get("brand_role") == "competitor"
        )
        if not valid_brand:
            raise PersonaBuildCliError("governed brand role is inconsistent")
        return "brand_roles"
    if fact_type == "entity_problem_fact":
        return "problem_ids"
    if fact_type != "entity_tag_fact":
        raise PersonaBuildCliError("governed tag identity is inconsistent")
    signal_kind = attributes.get("signal_kind")
    if signal_kind == "scenario":
        return "scenario_ids"
    if signal_kind == "topic":
        return "topic_ids"
    if attributes.get("tag_id") != canonical_value:
        raise PersonaBuildCliError("governed dim tag identity is inconsistent")
    return "voc_tag_ids"


def _materialize_persona_signals(
    promoted_facts: list[dict[str, object]],
) -> tuple[
    dict[str, dict[str, object]],
    dict[str, dict[str, dict[str, object]]],
    int,
    int,
    int,
]:
    by_voc: dict[str, list[dict[str, object]]] = defaultdict(list)
    observed_fact_ids: set[str] = set()
    for row in promoted_facts:
        fact_id = str(row["fact_id"])
        voc_id = str(row["voc_id"])
        if fact_id in observed_fact_ids:
            raise PersonaBuildCliError("duplicate governed persona signal fact ID")
        observed_fact_ids.add(fact_id)
        by_voc[voc_id].append(row)

    signals_by_voc: dict[str, dict[str, object]] = {}
    facts_by_voc: dict[str, dict[str, dict[str, object]]] = {}
    injected_fact_count = 0
    dropped_comment_fact_count = 0
    dropped_comment_voc_count = 0
    evidence_scope_order = {
        "post_title": 0,
        "post_body": 1,
        "current_comment_body": 2,
        "cross_context": 3,
    }
    for voc_id, rows in sorted(by_voc.items()):
        voc_types = {row.get("voc_type") for row in rows}
        if len(voc_types) != 1:
            raise PersonaBuildCliError("governed signal VOC type is inconsistent")
        voc_type = next(iter(voc_types))
        included = rows
        if voc_type == "comment_context_voc":
            has_direct_comment = any(
                row.get("evidence_field") == "current_comment_body"
                and row.get("evidence_scope") == "direct"
                for row in rows
            )
            if not has_direct_comment:
                dropped_comment_fact_count += len(rows)
                dropped_comment_voc_count += 1
                continue
            included = [
                row
                for row in rows
                if (
                    row.get("evidence_field") == "current_comment_body"
                    and row.get("evidence_scope") == "direct"
                )
                or (
                    row.get("evidence_field") in {"post_title", "post_body"}
                    and row.get("evidence_scope") == "cross_context"
                    and _signal_name_for_fact(row) in {"brand_roles", "topic_ids"}
                )
            ]
            dropped_comment_fact_count += len(rows) - len(included)
        elif voc_type != "post_voc":
            raise PersonaBuildCliError("governed signal VOC type is invalid")

        values: dict[str, set[str]] = {
            "brand_roles": set(),
            "problem_ids": set(),
            "scenario_ids": set(),
            "topic_ids": set(),
            "voc_tag_ids": set(),
        }
        refs: list[dict[str, object]] = []
        registry: dict[str, dict[str, object]] = {}
        scope: set[str] = set()
        for row in included:
            signal_name = _signal_name_for_fact(row)
            canonical_value = str(row["canonical_value"])
            values[signal_name].add(canonical_value)
            fact_id = str(row["fact_id"])
            registry[fact_id] = row
            evidence_field = str(row["evidence_field"])
            if row.get("evidence_scope") == "cross_context":
                scope.add("cross_context")
            else:
                scope.add(evidence_field)
            refs.append(
                {
                    "canonical_value": canonical_value,
                    "end": row["evidence_end"],
                    "evidence_field": evidence_field,
                    "evidence_text_sha256": row["evidence_text_sha256"],
                    "fact_type": row["fact_type"],
                    "source_fact_id": fact_id,
                    "source_snapshot_id": row["source_snapshot_id"],
                    "start": row["evidence_start"],
                }
            )
        if not refs:
            continue
        refs.sort(
            key=lambda row: (
                str(row["source_fact_id"]),
                str(row["fact_type"]),
                str(row["canonical_value"]),
                str(row["evidence_field"]),
                int(row["start"]),
                int(row["end"]),
            )
        )
        roles = values["brand_roles"]
        if "momcozy" in roles and "competitor" in roles:
            business_scope = "momcozy_multi"
        elif "momcozy" in roles:
            business_scope = "momcozy_direct"
        else:
            business_scope = "category_context"
        signals_by_voc[voc_id] = {
            **{name: sorted(items) for name, items in values.items()},
            "evidence_scope": sorted(scope, key=evidence_scope_order.__getitem__),
            "scope": business_scope,
            "signal_evidence_refs": refs,
            "source_stratum": "governed_v3_voc",
        }
        facts_by_voc[voc_id] = registry
        injected_fact_count += len(registry)
    return (
        signals_by_voc,
        facts_by_voc,
        injected_fact_count,
        dropped_comment_fact_count,
        dropped_comment_voc_count,
    )


def load_bound_governed_persona_signals(
    *,
    manifest_path: Path,
    expected_manifest_sha256: str,
    validation_receipt_path: Path,
    expected_validation_receipt_sha256: str,
    expected_facts_manifest_sha256: str,
    expected_facts_validation_receipt_sha256: str,
) -> BoundGovernedPersonaSignals:
    if manifest_path.is_symlink():
        raise PersonaBuildCliError("governed signal manifest is a symlink")
    governed_manifest_path = manifest_path.resolve(strict=True)
    root = governed_manifest_path.parent
    if root.is_symlink() or not root.is_dir():
        raise PersonaBuildCliError("governed signal root is unsafe")
    if _sha(governed_manifest_path) != expected_manifest_sha256:
        raise PersonaBuildCliError("governed signal manifest SHA mismatch")
    manifest = _load_json(governed_manifest_path)
    if (
        manifest.get("schema_version")
        != "reddit_voc_governed_signal_snapshot_v1"
        or manifest.get("status") != "candidate_built"
        or manifest.get("consumption_status")
        != "blocked_pending_independent_validation"
        or manifest.get("independent_validation_status") != "pending"
        or manifest.get("promotable") is not False
        or manifest.get("boundaries") != _BOUNDARIES
    ):
        raise PersonaBuildCliError("governed signal manifest state is invalid")
    snapshot_id = manifest.get("snapshot_id")
    source_snapshot_id = manifest.get("source_snapshot_id")
    if (
        not isinstance(snapshot_id, str)
        or not snapshot_id
        or not isinstance(source_snapshot_id, str)
        or not source_snapshot_id
    ):
        raise PersonaBuildCliError("governed signal snapshot identity is invalid")
    inputs = manifest.get("inputs")
    if (
        not isinstance(inputs, dict)
        or inputs.get("facts_manifest_sha256")
        != expected_facts_manifest_sha256
        or inputs.get("facts_receipt_sha256")
        != expected_facts_validation_receipt_sha256
    ):
        raise PersonaBuildCliError("governed signal source facts binding mismatch")
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != set(_GOVERNED_SIGNAL_FILES):
        raise PersonaBuildCliError("governed signal manifest file set is invalid")
    contracts = {
        name: _verify_governed_file_contract(root, name, files[name])
        for name in _GOVERNED_SIGNAL_FILES
    }
    tables = manifest.get("tables")
    table_rows = manifest.get("table_rows")
    counts = manifest.get("counts")
    if (
        not isinstance(tables, list)
        or len(tables) != 8
        or {row.get("filename") for row in tables if isinstance(row, dict)}
        != set(_GOVERNED_SIGNAL_FILES)
        or not isinstance(table_rows, dict)
        or not isinstance(counts, dict)
        or sum(int(contract["rows"]) for contract in contracts.values())
        != counts.get("fact_rows")
    ):
        raise PersonaBuildCliError("governed signal table accounting is invalid")
    actual_files = {
        path.name
        for path in root.iterdir()
        if path.is_file() and not path.is_symlink()
    }
    if actual_files != {"manifest.json", *_GOVERNED_SIGNAL_FILES}:
        raise PersonaBuildCliError("governed signal root contains undeclared files")
    for table in tables:
        if (
            not isinstance(table, dict)
            or set(table) != {"fact_type", "filename", "scope"}
            or table_rows.get(table.get("fact_type"))
            != contracts[str(table.get("filename"))]["rows"]
        ):
            raise PersonaBuildCliError("governed signal table contract is invalid")

    if validation_receipt_path.is_symlink():
        raise PersonaBuildCliError("governed signal validation receipt is a symlink")
    receipt_path = validation_receipt_path.resolve(strict=True)
    if _sha(receipt_path) != expected_validation_receipt_sha256:
        raise PersonaBuildCliError("governed signal validation receipt SHA mismatch")
    receipt = _load_json(receipt_path, require_compact_canonical=False)
    if (
        receipt.get("schema_version")
        != "reddit_voc_governed_signal_validation_receipt_v1"
        or receipt.get("status") != "passed"
        or receipt.get("consumption_status")
        != "eligible_for_downstream_consumption"
        or receipt.get("promotable") is not True
        or receipt.get("validated_tables") != 8
        or type(receipt.get("validated_tables")) is not int
        or type(receipt.get("unaccounted_facts")) is not int
        or receipt.get("unaccounted_facts") != 0
        or type(receipt.get("unaccounted_vocs")) is not int
        or receipt.get("unaccounted_vocs") != 0
        or receipt.get("snapshot_manifest_sha256") != expected_manifest_sha256
        or receipt.get("snapshot_id") != snapshot_id
        or receipt.get("source_snapshot_id") != source_snapshot_id
        or receipt.get("boundaries") != _BOUNDARIES
        or receipt.get("counts") != counts
        or receipt.get("inputs") != inputs
    ):
        raise PersonaBuildCliError(
            "governed signal validation receipt binding mismatch"
        )

    promoted_facts: list[dict[str, object]] = []
    for filename, fact_type in _PERSONA_SIGNAL_FACT_FILES.items():
        promoted_facts.extend(
            _load_promoted_governed_signal_facts(
                root / filename,
                expected_rows=int(contracts[filename]["rows"]),
                expected_fact_type=fact_type,
                expected_source_snapshot_id=source_snapshot_id,
            )
        )
    (
        signals_by_voc,
        facts_by_voc,
        injected_fact_count,
        dropped_comment_fact_count,
        dropped_comment_voc_count,
    ) = _materialize_persona_signals(promoted_facts)
    return BoundGovernedPersonaSignals(
        signals_by_voc_id=signals_by_voc,
        facts_by_voc_id=facts_by_voc,
        manifest_sha256=expected_manifest_sha256,
        validation_receipt_sha256=expected_validation_receipt_sha256,
        snapshot_id=snapshot_id,
        source_snapshot_id=source_snapshot_id,
        loaded_promoted_fact_count=len(promoted_facts),
        injected_fact_count=injected_fact_count,
        injected_voc_count=len(signals_by_voc),
        dropped_comment_fact_count=dropped_comment_fact_count,
        dropped_comment_voc_count=dropped_comment_voc_count,
        consumption_status=str(receipt["consumption_status"]),
        promotable=bool(receipt["promotable"]),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--facts-dir", type=Path, required=True)
    parser.add_argument("--facts-manifest-sha256", required=True)
    parser.add_argument("--facts-validation-receipt", type=Path, required=True)
    parser.add_argument("--facts-validation-receipt-sha256", required=True)
    parser.add_argument("--governed-signals-manifest", type=Path, required=True)
    parser.add_argument("--governed-signals-manifest-sha256", required=True)
    parser.add_argument(
        "--governed-signals-validation-receipt", type=Path, required=True
    )
    parser.add_argument(
        "--governed-signals-validation-receipt-sha256", required=True
    )
    parser.add_argument("--reference-manifest", type=Path, required=True)
    parser.add_argument("--reference-manifest-sha256", required=True)
    parser.add_argument("--persona-dictionary", type=Path, required=True)
    parser.add_argument("--cohort-config", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--generated-at-utc", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--allow-blocked-upstream-candidate", action="store_true")
    args = parser.parse_args()

    (
        vocs,
        automation_vocs,
        facts_sha,
        facts_receipt_sha,
        automation_classifications_sha,
        automation_classification_rows,
        reference_sha,
        _facts_upstream_consumption_status,
        _facts_upstream_promotable,
    ) = load_bound_persona_inputs(
        facts_dir=args.facts_dir,
        expected_facts_manifest_sha256=args.facts_manifest_sha256,
        facts_validation_receipt_path=args.facts_validation_receipt,
        expected_facts_validation_receipt_sha256=(
            args.facts_validation_receipt_sha256
        ),
        reference_manifest_path=args.reference_manifest,
        expected_reference_manifest_sha256=args.reference_manifest_sha256,
        allow_blocked_upstream_candidate=args.allow_blocked_upstream_candidate,
    )
    governed = load_bound_governed_persona_signals(
        manifest_path=args.governed_signals_manifest,
        expected_manifest_sha256=args.governed_signals_manifest_sha256,
        validation_receipt_path=args.governed_signals_validation_receipt,
        expected_validation_receipt_sha256=(
            args.governed_signals_validation_receipt_sha256
        ),
        expected_facts_manifest_sha256=facts_sha,
        expected_facts_validation_receipt_sha256=facts_receipt_sha,
    )
    dictionary = load_persona_dictionary(args.persona_dictionary)
    config = load_persona_cohort_config(args.cohort_config, dictionary=dictionary)
    documents = build_v3_persona_documents(
        vocs,
        automation_voc_ids=automation_vocs,
        dictionary=dictionary,
        config=config,
        snapshot_id=args.snapshot_id,
        generated_at_utc=args.generated_at_utc,
        source_facts_manifest_sha256=facts_sha,
        source_facts_validation_receipt_sha256=facts_receipt_sha,
        automation_manifest_sha256=facts_sha,
        automation_classifications_sha256=automation_classifications_sha,
        automation_classification_rows=automation_classification_rows,
        reference_manifest_sha256=reference_sha,
        project_root=args.project_root,
        upstream_consumption_status=governed.consumption_status,
        upstream_promotable=governed.promotable,
        governed_signals_by_voc_id=governed.signals_by_voc_id,
        governed_signal_facts_by_voc_id=governed.facts_by_voc_id,
        governed_signal_manifest_sha256=governed.manifest_sha256,
        governed_signal_validation_receipt_sha256=(
            governed.validation_receipt_sha256
        ),
        governed_signal_snapshot_id=governed.snapshot_id,
        governed_signal_source_snapshot_id=governed.source_snapshot_id,
        governed_signal_loaded_promoted_fact_count=(
            governed.loaded_promoted_fact_count
        ),
        governed_signal_dropped_comment_fact_count=(
            governed.dropped_comment_fact_count
        ),
        governed_signal_dropped_comment_voc_count=(
            governed.dropped_comment_voc_count
        ),
    )
    manifest = write_v3_persona_snapshot(
        args.output_dir,
        documents,
        project_root=args.project_root,
        config=config,
    )
    print(
        json.dumps(
            {
                "boundaries": manifest["boundaries"],
                "counts": manifest["counts"],
                "manifest_sha256": _sha(args.output_dir / "manifest.json"),
                "governed_signal_manifest_sha256": governed.manifest_sha256,
                "governed_signal_validation_receipt_sha256": (
                    governed.validation_receipt_sha256
                ),
                "snapshot_id": manifest["snapshot_id"],
                "status": "built",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
