"""Immutable input contract for the Reddit VOC V3 governed-signal snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping


FACTS_MANIFEST_SHA256 = (
    "4a0b43f664cc8bd2cf0fbd63d0428aaeadec1a6b405a066123250e4f90675b77"
)
FACTS_RECEIPT_SHA256 = (
    "ff6ee119c5861cfad50d256caebaf3600564013b6069b97d047e9197c90eb61f"
)
VOCS_SHA256 = (
    "e31889b22b0ec127c1198e634d1fdd7c12c7b50ecbfe9e66f16257ea76fb1afe"
)
AUTOMATION_CLASSIFICATIONS_SHA256 = (
    "980b6485bdaae1855b9406308982bb4ce067acc92044ed7492f7a7f72f39422d"
)
AUTOMATION_POLICY_SHA256 = (
    "7f73705c794f76d746e53eab9df162b43b4672f0d0c62ed677774e407a7769a3"
)
DIM_TAG_SHA256 = (
    "22664c9c446ddfa17446852079f507ab75b5af3d4dde6e4e3f3e44c195582e14"
)
PRODUCT_ENTITY_LEDGER_SHA256 = (
    "cc66f565d64c19d0624baf9821ff4e765c692c8d85b8a4d7368214ab555451ab"
)
CLOSED_SET_REGISTRY_SHA256 = (
    "35efdc71543f128acc96f9e30d1788d1e78972b042f64e369d01c43fd5723d71"
)
SOURCE_SNAPSHOT_ID = "reddit_add_data_20260715_v1"
EXPECTED_TOTAL_VOCS = 23_586
EXPECTED_AUTOMATION_VOCS = 737
EXPECTED_AUTOMATION_CLASSIFICATIONS = 27_148
EXPECTED_AUTOMATION_ENTITIES = 915
EXPECTED_BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
AUTOMATION_CLASSIFICATION_KEYS = {
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
FOOTER_RULE_ID = "reddit_automation_footer_v1"
UPSTREAM_RULE_ID = "trusted_upstream_bot_state_v1"
FOOTER_MATCH_IDS = {
    "self_disclosed_bot",
    "automatic_action_disclosure",
    "moderator_contact_disclosure",
    "moderator_contact_link",
}


class GovernedSignalInputError(ValueError):
    """The frozen facts-a2 or resource input contract is not satisfied."""


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
        raise GovernedSignalInputError(
            "value is not canonical JSON serializable"
        ) from exc


def sha256_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _read_bytes(path: Path, *, label: str) -> bytes:
    path = Path(path)
    try:
        if path.is_symlink() or not path.is_file():
            raise GovernedSignalInputError(f"{label} must be a regular file")
        return path.read_bytes()
    except OSError as exc:
        raise GovernedSignalInputError(f"{label} is unreadable") from exc


def _read_bound_json(
    path: Path,
    *,
    label: str,
    expected_sha256: str,
) -> tuple[dict[str, Any], bytes]:
    payload = _read_bytes(path, label=label)
    if sha256_bytes(payload) != expected_sha256:
        raise GovernedSignalInputError(f"{label} SHA-256 mismatch")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GovernedSignalInputError(f"{label} JSON is invalid") from exc
    if not isinstance(value, dict):
        raise GovernedSignalInputError(f"{label} must be an object")
    return value, payload


def _jsonl_rows(path: Path, *, label: str) -> tuple[dict[str, Any], ...]:
    payload = _read_bytes(path, label=label)
    rows: list[dict[str, Any]] = []
    for ordinal, line in enumerate(payload.splitlines(), start=1):
        if not line:
            raise GovernedSignalInputError(f"{label} has a blank line")
        try:
            row = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GovernedSignalInputError(
                f"{label} row {ordinal} is invalid"
            ) from exc
        if not isinstance(row, dict):
            raise GovernedSignalInputError(
                f"{label} row {ordinal} must be an object"
            )
        if canonical_json_bytes(row) != line:
            raise GovernedSignalInputError(
                f"{label} row {ordinal} is not canonical JSON"
            )
        rows.append(row)
    if payload and not payload.endswith(b"\n"):
        raise GovernedSignalInputError(f"{label} lacks final newline")
    return tuple(rows)


def _file_contract(
    manifest: Mapping[str, Any],
    name: str,
    path: Path,
    *,
    expected_sha256: str,
    expected_rows: int,
) -> None:
    files = manifest.get("files")
    contract = files.get(name) if isinstance(files, Mapping) else None
    payload = _read_bytes(path, label=name)
    if (
        not isinstance(contract, Mapping)
        or set(contract) != {"bytes", "rows", "sha256"}
        or contract.get("bytes") != len(payload)
        or contract.get("rows") != expected_rows
        or contract.get("sha256") != expected_sha256
        or sha256_bytes(payload) != expected_sha256
    ):
        raise GovernedSignalInputError(f"{name} file contract mismatch")


def _validate_automation_classification_state(row: object) -> None:
    if not isinstance(row, dict) or set(row) != AUTOMATION_CLASSIFICATION_KEYS:
        raise GovernedSignalInputError("automation classification row is invalid")
    boolean_fields = (
        "audit_disclosure_detected",
        "automation_determined",
        "canonical_retained",
        "newly_excluded",
        "requires_organic_exclusion",
        "upstream_automation_excluded",
        "was_already_excluded",
    )
    if any(type(row.get(name)) is not bool for name in boolean_fields):
        raise GovernedSignalInputError("automation classification state is invalid")
    matched = row.get("matched_rule_ids")
    reasons = row.get("reason_codes")
    evidence = row.get("evidence_spans")
    if (
        not isinstance(matched, list)
        or matched != sorted(set(matched))
        or any(not isinstance(value, str) or not value for value in matched)
        or not isinstance(reasons, list)
        or reasons != sorted(set(reasons))
        or any(not isinstance(value, str) or not value for value in reasons)
        or not isinstance(evidence, list)
    ):
        raise GovernedSignalInputError("automation classification state is invalid")
    text_field = row.get("text_field")
    input_hash = row.get("input_text_sha256")
    if (text_field is None) is not (input_hash is None) or (
        text_field is not None
        and (
            not isinstance(text_field, str)
            or not text_field
            or not isinstance(input_hash, str)
            or SHA256_PATTERN.fullmatch(input_hash) is None
        )
    ):
        raise GovernedSignalInputError(
            "automation classification text state is invalid"
        )
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
            or span.get("match_id") not in FOOTER_MATCH_IDS
            or not isinstance(span.get("evidence_text_sha256"), str)
            or SHA256_PATTERN.fullmatch(span["evidence_text_sha256"]) is None
        ):
            raise GovernedSignalInputError(
                "automation classification evidence is invalid"
            )
        observed_match_ids.add(str(span["match_id"]))

    upstream = row["upstream_automation_excluded"]
    footer = FOOTER_RULE_ID in matched
    upstream_rule = UPSTREAM_RULE_ID in matched
    held = row.get("classification_status") == "held"
    if set(matched) - {FOOTER_RULE_ID, UPSTREAM_RULE_ID}:
        raise GovernedSignalInputError("automation classification rules are invalid")
    if footer and not FOOTER_MATCH_IDS <= observed_match_ids:
        raise GovernedSignalInputError("automation footer evidence is incomplete")
    if not footer and not held and evidence:
        raise GovernedSignalInputError("automation evidence is unbound")
    expected_reasons = (
        sorted(
            (["reddit_automation_footer"] if footer else [])
            + (["upstream_known_bot"] if upstream else [])
        )
        if footer or upstream
        else ["incomplete_or_quoted_automation_disclosure"]
        if held
        else ["no_automation_signal"]
    )
    expected_rules = sorted(
        ([FOOTER_RULE_ID] if footer else [])
        + ([UPSTREAM_RULE_ID] if upstream else [])
    )
    expected_status = (
        "determined" if footer or upstream else "held" if held else "not_detected"
    )
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
    determined = footer or upstream
    if (
        matched != expected_rules
        or reasons != expected_reasons
        or row.get("classification_status") != expected_status
        or row.get("classification_accounting_bucket") != expected_bucket
        or row["audit_disclosure_detected"] is not (footer or held)
        or row["automation_determined"] is not determined
        or upstream_rule is not upstream
        or row["requires_organic_exclusion"] is not determined
        or row["was_already_excluded"] is not upstream
        or row["newly_excluded"] is not (determined and not upstream)
        or row["canonical_retained"] is not True
        or row.get("excluded_reason")
        != ("explicit_automation" if determined else None)
        or row.get("commercial_attribution_status") != "not_inferred"
    ):
        raise GovernedSignalInputError("automation classification state is invalid")


@dataclass(frozen=True)
class GovernedSignalInputs:
    vocs: tuple[dict[str, Any], ...]
    automation_voc_ids: frozenset[str]
    input_bindings: dict[str, str]
    source_snapshot_id: str = SOURCE_SNAPSHOT_ID

    @property
    def organic_vocs(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            row for row in self.vocs if row["voc_id"] not in self.automation_voc_ids
        )


def load_formal_governed_signal_inputs(
    *,
    facts_root: Path,
    facts_receipt_path: Path,
    dim_tag_path: Path,
    product_entity_ledger_path: Path,
    registry_path: Path,
    facts_manifest_sha256: str = FACTS_MANIFEST_SHA256,
    facts_receipt_sha256: str = FACTS_RECEIPT_SHA256,
) -> GovernedSignalInputs:
    """Reopen an explicitly SHA-bound facts input and three fixed resources."""
    if (
        not isinstance(facts_manifest_sha256, str)
        or not isinstance(facts_receipt_sha256, str)
        or
        SHA256_PATTERN.fullmatch(facts_manifest_sha256) is None
        or SHA256_PATTERN.fullmatch(facts_receipt_sha256) is None
    ):
        raise GovernedSignalInputError("facts input SHA-256 is invalid")
    facts_root = Path(facts_root)
    manifest_path = facts_root / "manifest.json"
    manifest, _manifest_payload = _read_bound_json(
        manifest_path,
        label="facts-a2 manifest",
        expected_sha256=facts_manifest_sha256,
    )
    receipt, _receipt_payload = _read_bound_json(
        facts_receipt_path,
        label="facts-a2 validation receipt",
        expected_sha256=facts_receipt_sha256,
    )
    if (
        manifest.get("schema_version") != "reddit_voc_voc_facts_manifest_v2"
        or not isinstance(manifest.get("dataset_id"), str)
        or not manifest["dataset_id"].endswith("_voc_facts_v2")
        or manifest.get("status") != "candidate_built"
        or manifest.get("boundaries") != EXPECTED_BOUNDARIES
        or type(manifest.get("counts", {}).get("total_vocs")) is not int
        or type(manifest.get("counts", {}).get("automation_voc")) is not int
        or receipt.get("schema_version")
        != "reddit_voc_voc_facts_validation_receipt_v2"
        or receipt.get("status") != "passed"
        or receipt.get("consumption_status") != "blocked_pending_atomic_facts"
        or receipt.get("promotable") is not False
        or receipt.get("bundle_manifest_sha256") != facts_manifest_sha256
        or receipt.get("counts") != manifest.get("counts")
        or receipt.get("boundaries") != EXPECTED_BOUNDARIES
        or type(receipt.get("unaccounted_vocs")) is not int
        or receipt.get("unaccounted_vocs") != 0
        or type(receipt.get("unaccounted_eligibility_members")) is not int
        or receipt.get("unaccounted_eligibility_members") != 0
    ):
        raise GovernedSignalInputError("facts-a2 lifecycle contract mismatch")
    manifest_inputs = manifest.get("inputs")
    if (
        not isinstance(manifest_inputs, Mapping)
        or manifest_inputs.get("automation_policy_sha256")
        != AUTOMATION_POLICY_SHA256
    ):
        raise GovernedSignalInputError("facts-a2 input bindings are invalid")
    for key in (
        "automation_family_contract_sha256",
        "automation_policy_sha256",
        "canonical_comments_sha256",
        "canonical_manifest_sha256",
        "canonical_validation_receipt_sha256",
        "eligibility_policy_sha256",
    ):
        if receipt.get(key) != manifest_inputs.get(key):
            raise GovernedSignalInputError(
                f"facts-a2 receipt input binding mismatch: {key}"
            )

    vocs_path = facts_root / "vocs.jsonl"
    automation_path = facts_root / "automation-classifications.jsonl"
    files = manifest.get("files")
    if not isinstance(files, Mapping):
        raise GovernedSignalInputError("facts-a2 file bindings are invalid")
    voc_binding = files.get("vocs.jsonl")
    automation_binding = files.get("automation-classifications.jsonl")
    if not isinstance(voc_binding, Mapping) or not isinstance(automation_binding, Mapping):
        raise GovernedSignalInputError("facts-a2 governed input bindings are missing")
    total_vocs = manifest["counts"]["total_vocs"]
    automation_vocs = manifest["counts"]["automation_voc"]
    _file_contract(
        manifest,
        "vocs.jsonl",
        vocs_path,
        expected_sha256=str(voc_binding.get("sha256")),
        expected_rows=total_vocs,
    )
    _file_contract(
        manifest,
        "automation-classifications.jsonl",
        automation_path,
        expected_sha256=str(automation_binding.get("sha256")),
        expected_rows=int(automation_binding.get("rows", -1)),
    )
    for path, label, expected_sha in (
        (dim_tag_path, "dim_tag_v6.3_final", DIM_TAG_SHA256),
        (
            product_entity_ledger_path,
            "product entity ledger",
            PRODUCT_ENTITY_LEDGER_SHA256,
        ),
        (registry_path, "closed-set registry", CLOSED_SET_REGISTRY_SHA256),
    ):
        if sha256_bytes(_read_bytes(path, label=label)) != expected_sha:
            raise GovernedSignalInputError(f"{label} SHA-256 mismatch")

    vocs = _jsonl_rows(vocs_path, label="vocs.jsonl")
    if len(vocs) != total_vocs:
        raise GovernedSignalInputError("facts-a2 VOC row count mismatch")
    by_id: dict[str, dict[str, Any]] = {}
    for row in vocs:
        voc_id = row.get("voc_id")
        if (
            not isinstance(voc_id, str)
            or voc_id in by_id
            or row.get("schema_version") != "reddit_voc_fielded_voc_v1"
            or row.get("analysis_text_status") != "ready"
        ):
            raise GovernedSignalInputError("facts-a2 VOC identity is invalid")
        by_id[voc_id] = row

    classifications = _jsonl_rows(
        automation_path, label="automation-classifications.jsonl"
    )
    if len(classifications) != automation_binding.get("rows"):
        raise GovernedSignalInputError("automation classification row count mismatch")
    automation_entities = 0
    automation_voc_ids: set[str] = set()
    seen_entities: set[str] = set()
    for row in classifications:
        _validate_automation_classification_state(row)
        entity_id = row.get("canonical_entity_id")
        if (
            not isinstance(entity_id, str)
            or re.fullmatch(r"t1_[a-z0-9]+", entity_id) is None
            or entity_id in seen_entities
            or row.get("schema_version")
            != "reddit_voc_explicit_automation_classification_v1"
            or row.get("entity_type") != "comment"
            or row.get("record_authority")
            not in {"governed_base", "workbook_net_new"}
            or row.get("comment_state") not in {"linked", "unresolved_parent"}
            or row.get("policy_sha256") != AUTOMATION_POLICY_SHA256
            or row.get("policy_version")
            != manifest.get("automation_policy_version")
            or row.get("matcher_version")
            != "explicit_bot_disclosure_regex_audit_v1"
        ):
            raise GovernedSignalInputError(
                "automation classification entity identity is invalid"
            )
        seen_entities.add(entity_id)
        if row["automation_determined"] is not True:
            continue
        automation_entities += 1
        if (
            row.get("classification_status") != "determined"
            or row.get("canonical_retained") is not True
            or row.get("requires_organic_exclusion") is not True
            or row.get("excluded_reason") != "explicit_automation"
            or row.get("policy_sha256") != AUTOMATION_POLICY_SHA256
        ):
            raise GovernedSignalInputError(
                "determined automation contract is invalid"
            )
        voc_id = f"comment:{entity_id.removeprefix('t1_')}"
        if voc_id in by_id:
            automation_voc_ids.add(voc_id)
    if (
        automation_entities != manifest["counts"].get("automation_total")
        or len(automation_voc_ids) != automation_vocs
        or len(vocs) - len(automation_voc_ids) != total_vocs - automation_vocs
    ):
        raise GovernedSignalInputError(
            "automation-before-organic conservation mismatch"
        )

    bindings = {
        "automation_classifications_sha256": str(automation_binding["sha256"]),
        "automation_policy_sha256": AUTOMATION_POLICY_SHA256,
        "closed_set_registry_sha256": CLOSED_SET_REGISTRY_SHA256,
        "dim_tag_sha256": DIM_TAG_SHA256,
        "facts_manifest_sha256": facts_manifest_sha256,
        "facts_receipt_sha256": facts_receipt_sha256,
        "product_entity_ledger_sha256": PRODUCT_ENTITY_LEDGER_SHA256,
        "vocs_sha256": str(voc_binding["sha256"]),
    }
    if any(SHA256_PATTERN.fullmatch(value) is None for value in bindings.values()):
        raise GovernedSignalInputError("formal input binding is invalid")
    return GovernedSignalInputs(
        vocs=tuple(sorted(vocs, key=lambda row: str(row["voc_id"]))),
        automation_voc_ids=frozenset(automation_voc_ids),
        input_bindings=bindings,
        source_snapshot_id=manifest["dataset_id"].removesuffix("_voc_facts_v2"),
    )
