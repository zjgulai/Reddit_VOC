"""Hash-bound candidate snapshots for Reddit VOC V3 content integrity.

The formal loader accepts only a validated, frozen upstream governed-fact
bundle.  It deliberately has no "allow blocked" switch: until the five fixed
Momcozy roots and their promoted evidence are frozen, a formal integrity
snapshot cannot be built.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Iterable, Mapping, Sequence

from reddit_voc.v3_content_integrity import (
    FIXED_EVENT_POST_IDS,
    INPUT_KEYS,
    ContentIntegrityError,
    build_event_chain,
    classify_integrity,
)


POLICY_SCHEMA = "reddit_voc_content_integrity_policy_v1"
UPSTREAM_MANIFEST_SCHEMA = "reddit_voc_governed_integrity_inputs_manifest_v1"
UPSTREAM_RECEIPT_SCHEMA = (
    "reddit_voc_governed_integrity_inputs_validation_receipt_v1"
)
GOVERNED_SIGNAL_MANIFEST_SCHEMA = "reddit_voc_governed_signal_snapshot_v1"
GOVERNED_SIGNAL_RECEIPT_SCHEMA = "reddit_voc_governed_signal_validation_receipt_v1"
OBSERVATION_SCHEMA = "reddit_voc_integrity_observation_v1"
EVENT_ROOT_SCHEMA = "reddit_voc_integrity_event_root_v1"
MANIFEST_SCHEMA = "reddit_voc_integrity_snapshot_manifest_v1"
RECEIPT_SCHEMA = "reddit_voc_integrity_snapshot_validation_receipt_v1"
FACT_SCHEMA = "reddit_voc_atomic_fact_v2"
FACT_TYPES = frozenset(
    {
        "entity_brand_fact",
        "entity_product_fact",
        "entity_sentiment_fact",
        "entity_problem_fact",
        "entity_tag_fact",
        "persona_atomic_fact",
        "community_governance_fact",
        "commercial_relation_fact",
        "integrity_signal_fact",
    }
)
CLAIM_KEYS_BY_FACT_TYPE = {
    "commercial_relation_fact": frozenset(
        {
            "affiliate_registry_bound",
            "brand_attribution_confirmed",
            "brand_confirmation",
            "commercial_denial",
            "commercial_disclosure",
            "repeated_propagation_pattern",
        }
    ),
    "community_governance_fact": frozenset(
        {"governance_authority", "public_governance_action", "signal_types"}
    ),
    "integrity_signal_fact": frozenset(
        {
            "ai_style_signal",
            "explicit_automation",
            "manual_rule_violation_confirmed",
            "repeated_propagation_pattern",
            "signal_types",
        }
    ),
}
BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}
POLICY_BOUNDARIES = {
    **BOUNDARIES,
    "brand_control_inferred_from_moderator_event": False,
    "explicit_automation_is_commercial_evidence": False,
}
UPSTREAM_FILES = (
    "governed-facts.jsonl",
    "integrity-observations.jsonl",
    "event-roots.jsonl",
)
OUTPUT_FILES = (
    "assessments.jsonl",
    "clusters.jsonl",
    "event-dossiers.jsonl",
    "review-ledger.jsonl",
    "sensitivity.json",
    "lifecycle.json",
)
SHA256_RE = re.compile(r"[0-9a-f]{64}")


class IntegritySnapshotError(ValueError):
    """A governed input or integrity snapshot violates its contract."""


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
        raise IntegritySnapshotError("value is not canonical JSON serializable") from exc


def canonical_json_document(value: object) -> bytes:
    return canonical_json_bytes(value) + b"\n"


def canonical_jsonl(rows: Iterable[Mapping[str, object]]) -> bytes:
    return b"".join(canonical_json_document(dict(row)) for row in rows)


def sha256_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _read_regular(path: Path, label: str) -> bytes:
    path = Path(path)
    try:
        if path.is_symlink() or not path.is_file():
            raise IntegritySnapshotError(f"{label} must be a regular file")
        return path.read_bytes()
    except OSError as exc:
        raise IntegritySnapshotError(f"{label} is unreadable") from exc


def _read_canonical_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    payload = _read_regular(path, label)
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegritySnapshotError(f"{label} JSON is invalid") from exc
    if not isinstance(value, dict) or canonical_json_document(value) != payload:
        raise IntegritySnapshotError(f"{label} is not canonical JSON")
    return value, payload


def _read_canonical_jsonl(path: Path, label: str) -> tuple[dict[str, Any], ...]:
    payload = _read_regular(path, label)
    rows: list[dict[str, Any]] = []
    if payload and not payload.endswith(b"\n"):
        raise IntegritySnapshotError(f"{label} lacks final newline")
    for ordinal, line in enumerate(payload.splitlines(), start=1):
        if not line:
            raise IntegritySnapshotError(f"{label} has a blank line")
        try:
            row = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise IntegritySnapshotError(f"{label} row {ordinal} is invalid") from exc
        if not isinstance(row, dict) or canonical_json_bytes(row) != line:
            raise IntegritySnapshotError(
                f"{label} row {ordinal} is not canonical JSON"
            )
        rows.append(row)
    return tuple(rows)


def _canonical_utc(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise IntegritySnapshotError(f"{label} must be canonical UTC seconds")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IntegritySnapshotError(f"{label} must be canonical UTC seconds") from exc
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() != timedelta(0)
        or parsed.microsecond != 0
        or value != parsed.isoformat(timespec="seconds")
    ):
        raise IntegritySnapshotError(f"{label} must be canonical UTC seconds")
    return value


def load_policy(path: Path) -> tuple[dict[str, Any], str]:
    payload = _read_regular(path, "content-integrity policy")
    try:
        policy = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegritySnapshotError("content-integrity policy JSON is invalid") from exc
    if not isinstance(policy, dict):
        raise IntegritySnapshotError("content-integrity policy must be an object")
    fixed = policy.get("fixed_momcozy_event")
    if (
        policy.get("schema_version") != POLICY_SCHEMA
        or policy.get("boundaries") != POLICY_BOUNDARIES
        or not isinstance(fixed, Mapping)
        or fixed.get("post_ids") != list(FIXED_EVENT_POST_IDS)
        or fixed.get("commercial_relation") != "C2"
        or fixed.get("integrity_level") != "I3"
        or fixed.get("governance_authority") != "subreddit_moderator"
        or fixed.get("brand_control_confirmed") is not False
        or policy.get("qualified_organic_exclusion")
        != {
            "commercial_relation": "C3",
            "integrity_level": "I4",
            "operator": "and",
        }
    ):
        raise IntegritySnapshotError("content-integrity policy is invalid")
    response = policy.get("response_transitions")
    review = policy.get("review_lifecycle")
    if (
        not isinstance(response, Mapping)
        or set(response) != {"unanswered", "disputed", "confirmed", "retracted"}
        or not isinstance(review, Mapping)
        or set(review)
        != {"queued", "in_review", "resolved_confirmed", "resolved_dismissed"}
    ):
        raise IntegritySnapshotError("content-integrity lifecycle policy is invalid")
    return policy, sha256_bytes(payload)


def _validate_fact(row: Mapping[str, Any]) -> None:
    fact_id = row.get("fact_id")
    identity = dict(row)
    identity.pop("fact_id", None)
    if (
        row.get("schema_version") != FACT_SCHEMA
        or row.get("fact_type") not in FACT_TYPES
        or row.get("decision_status") != "promoted"
        or not isinstance(row.get("canonical_value"), str)
        or not row["canonical_value"]
        or not isinstance(row.get("canonical_entity_id"), str)
        or not row["canonical_entity_id"]
        or not isinstance(fact_id, str)
        or SHA256_RE.fullmatch(fact_id) is None
        or sha256_bytes(canonical_json_bytes(identity)) != fact_id
    ):
        raise IntegritySnapshotError("governed fact identity is invalid")


def _derived_classification_input(
    entity_id: str,
    evidence_ids: Sequence[str],
    facts: Mapping[str, Mapping[str, Any]],
) -> dict[str, object]:
    merged: dict[str, object] = {}
    signal_types: set[str] = set()
    for evidence_id in evidence_ids:
        fact = facts[evidence_id]
        attributes = fact.get("attributes")
        if not isinstance(attributes, Mapping):
            raise IntegritySnapshotError("governed fact attributes are invalid")
        native_claims: dict[str, object] = {}
        if (
            fact.get("fact_type") == "community_governance_fact"
            and attributes.get("authority") == "subreddit_moderator"
        ):
            native_claims = {
                "governance_authority": "subreddit_moderator",
                "public_governance_action": True,
            }
        elif (
            fact.get("fact_type") == "integrity_signal_fact"
            and attributes.get("assertion_mode")
            == "subreddit_moderator_allegation"
        ):
            native_claims = {"signal_types": ["content"]}
        explicit_claims = attributes.get("integrity_classification", {})
        if not isinstance(explicit_claims, Mapping):
            raise IntegritySnapshotError("governed integrity claims are invalid")
        claims = {**native_claims, **explicit_claims}
        if not isinstance(claims, Mapping):
            raise IntegritySnapshotError("governed integrity claims are invalid")
        allowed = CLAIM_KEYS_BY_FACT_TYPE.get(str(fact["fact_type"]), frozenset())
        if set(claims) - allowed:
            raise IntegritySnapshotError("governed integrity claim exceeds fact type")
        for key, value in claims.items():
            if key == "signal_types":
                if (
                    not isinstance(value, list)
                    or any(item not in {"content", "behavior", "link"} for item in value)
                    or value != sorted(set(value))
                ):
                    raise IntegritySnapshotError("governed signal types are invalid")
                signal_types.update(value)
                continue
            if key in {
                "affiliate_registry_bound",
                "ai_style_signal",
                "brand_attribution_confirmed",
                "brand_confirmation",
                "commercial_denial",
                "explicit_automation",
                "manual_rule_violation_confirmed",
                "public_governance_action",
                "repeated_propagation_pattern",
            } and value is not True:
                raise IntegritySnapshotError("governed boolean claim must be affirmative")
            previous = merged.get(key)
            if previous is not None and previous != value:
                raise IntegritySnapshotError("governed integrity claims conflict")
            merged[key] = value
        if claims.get("manual_rule_violation_confirmed") is True and (
            not isinstance(attributes.get("review_provenance_id"), str)
            or not attributes["review_provenance_id"]
        ):
            raise IntegritySnapshotError("manual rule claim lacks review provenance")
        if any(
            claims.get(key) is True
            for key in (
                "affiliate_registry_bound",
                "brand_attribution_confirmed",
                "brand_confirmation",
            )
        ) and (
            not isinstance(attributes.get("attribution_provenance_id"), str)
            or not attributes["attribution_provenance_id"]
        ):
            raise IntegritySnapshotError("commercial attribution lacks provenance")
    if signal_types:
        merged["signal_types"] = sorted(signal_types)
    return {
        "entity_id": entity_id,
        "evidence_ids": list(evidence_ids),
        **merged,
    }


def _validate_observation(
    row: Mapping[str, Any], facts: Mapping[str, Mapping[str, Any]]
) -> None:
    if set(row) != {
        "classification_input",
        "cluster_key",
        "entity_id",
        "evidence_ids",
        "schema_version",
    } or row.get("schema_version") != OBSERVATION_SCHEMA:
        raise IntegritySnapshotError("integrity observation schema is invalid")
    entity_id = row.get("entity_id")
    evidence_ids = row.get("evidence_ids")
    classification = row.get("classification_input")
    cluster_key = row.get("cluster_key")
    if (
        not isinstance(entity_id, str)
        or not entity_id
        or not isinstance(evidence_ids, list)
        or not evidence_ids
        or evidence_ids != sorted(set(evidence_ids))
        or any(not isinstance(value, str) for value in evidence_ids)
        or not isinstance(classification, Mapping)
        or set(classification) - INPUT_KEYS
        or classification.get("entity_id") != entity_id
        or classification.get("evidence_ids") != evidence_ids
        or cluster_key is not None
        and (not isinstance(cluster_key, str) or not cluster_key)
    ):
        raise IntegritySnapshotError("integrity observation identity is invalid")
    for evidence_id in evidence_ids:
        fact = facts.get(evidence_id)
        if fact is None or fact.get("canonical_entity_id") != entity_id:
            raise IntegritySnapshotError("integrity observation evidence is ungoverned")
    derived = _derived_classification_input(entity_id, evidence_ids, facts)
    if dict(classification) != derived:
        raise IntegritySnapshotError(
            "integrity observation claims do not replay from governed facts"
        )
    try:
        assessment = classify_integrity(derived)
    except ContentIntegrityError as exc:
        raise IntegritySnapshotError("integrity observation cannot be classified") from exc
    if (
        assessment.commercial_relation in {"C2", "C3"}
        or assessment.integrity_level in {"I2", "I3", "I4"}
    ) and cluster_key is None:
        raise IntegritySnapshotError("reviewable observation lacks a governed cluster key")


def _validate_event_root(
    row: Mapping[str, Any], facts: Mapping[str, Mapping[str, Any]]
) -> None:
    if set(row) != {"authority", "evidence_id", "post_id", "schema_version"}:
        raise IntegritySnapshotError("event-root schema is invalid")
    post_id = row.get("post_id")
    evidence_id = row.get("evidence_id")
    fact = facts.get(evidence_id) if isinstance(evidence_id, str) else None
    attributes = fact.get("attributes") if isinstance(fact, Mapping) else None
    moderator_evidence = isinstance(attributes, Mapping) and (
        (
            fact.get("fact_type") == "community_governance_fact"
            and attributes.get("authority") == "subreddit_moderator"
        )
        or (
            fact.get("fact_type") == "integrity_signal_fact"
            and attributes.get("assertion_mode")
            == "subreddit_moderator_allegation"
        )
    )
    expected_entity_id = (
        f"external_reddit_post:{post_id}"
        if post_id == "1u2gvn4"
        else f"t3_{post_id}"
    )
    external_boundary_valid = post_id != "1u2gvn4" or (
        isinstance(fact, Mapping)
        and fact.get("voc_id") == "external-post:1u2gvn4"
        and fact.get("voc_type") == "external_public_reference"
        and isinstance(attributes, Mapping)
        and attributes.get("source_role")
        == "external_public_reference_noncanonical"
        and attributes.get("brand_control_confirmed") is False
    )
    if (
        row.get("schema_version") != EVENT_ROOT_SCHEMA
        or post_id not in FIXED_EVENT_POST_IDS
        or row.get("authority") != "subreddit_moderator"
        or not isinstance(fact, Mapping)
        or fact.get("canonical_entity_id") != expected_entity_id
        or not moderator_evidence
        or not external_boundary_valid
    ):
        raise IntegritySnapshotError("event-root evidence is not governed")


@dataclass(frozen=True)
class GovernedIntegrityInputs:
    facts: tuple[dict[str, Any], ...]
    observations: tuple[dict[str, Any], ...]
    event_roots: tuple[dict[str, Any], ...]
    source_snapshot_id: str
    upstream_manifest_sha256: str
    upstream_receipt_sha256: str
    policy_sha256: str


@dataclass(frozen=True)
class IntegritySnapshotDocuments:
    assessments: tuple[dict[str, Any], ...]
    clusters: tuple[dict[str, Any], ...]
    events: tuple[dict[str, Any], ...]
    reviews: tuple[dict[str, Any], ...]
    sensitivity: dict[str, Any]
    lifecycle: dict[str, Any]
    manifest_base: dict[str, Any]


def load_frozen_governed_inputs(
    *, upstream_root: Path, upstream_receipt_path: Path, policy_path: Path
) -> GovernedIntegrityInputs:
    root = Path(upstream_root)
    if root.is_symlink() or not root.is_dir():
        raise IntegritySnapshotError("upstream governed-fact directory is invalid")
    policy, policy_sha = load_policy(policy_path)
    manifest, manifest_payload = _read_canonical_json(root / "manifest.json", "upstream manifest")
    receipt, receipt_payload = _read_canonical_json(
        upstream_receipt_path, "upstream validation receipt"
    )
    manifest_sha = sha256_bytes(manifest_payload)
    receipt_sha = sha256_bytes(receipt_payload)
    if manifest.get("schema_version") == GOVERNED_SIGNAL_MANIFEST_SCHEMA:
        if (
            receipt.get("schema_version") != GOVERNED_SIGNAL_RECEIPT_SCHEMA
            or receipt.get("status") != "passed"
            or receipt.get("consumption_status")
            != "eligible_for_downstream_consumption"
            or receipt.get("promotable") is not True
            or receipt.get("snapshot_manifest_sha256") != manifest_sha
            or receipt.get("boundaries") != BOUNDARIES
            or manifest.get("boundaries") != BOUNDARIES
        ):
            raise IntegritySnapshotError(
                "upstream governed-signal snapshot lacks a valid receipt"
            )
        coverage = manifest.get("governance_regression_coverage")
        missing = coverage.get("missing_root_voc_ids") if isinstance(coverage, Mapping) else None
        incomplete = (
            coverage.get("incomplete_root_voc_ids")
            if isinstance(coverage, Mapping)
            else None
        )
        if missing or incomplete:
            debt = sorted(
                str(value)
                for value in [*(missing or []), *(incomplete or [])]
            )
            raise IntegritySnapshotError(
                "fixed Momcozy event roots are incomplete: " + ",".join(debt)
            )
        raise IntegritySnapshotError(
            "full-corpus governed integrity observations are not frozen"
        )
    entries = {path.name for path in root.iterdir()}
    if entries != set(UPSTREAM_FILES) | {"manifest.json"} or any(
        path.is_symlink() or not path.is_file() for path in root.iterdir()
    ):
        raise IntegritySnapshotError(
            "upstream governed-fact directory contains undeclared entries"
        )
    if (
        manifest.get("schema_version") != UPSTREAM_MANIFEST_SCHEMA
        or manifest.get("status") != "frozen"
        or manifest.get("consumption_status") != "ready"
        or manifest.get("promotable") is not True
        or manifest.get("boundaries") != BOUNDARIES
        or manifest.get("policy_sha256") != policy_sha
        or receipt.get("schema_version") != UPSTREAM_RECEIPT_SCHEMA
        or receipt.get("status") != "passed"
        or receipt.get("consumption_status") != "ready"
        or receipt.get("promotable") is not True
        or receipt.get("upstream_manifest_sha256") != manifest_sha
        or receipt.get("boundaries") != BOUNDARIES
    ):
        raise IntegritySnapshotError(
            "upstream governed facts are not frozen and promotable"
        )
    source_snapshot_id = manifest.get("source_snapshot_id")
    files = manifest.get("files")
    if not isinstance(source_snapshot_id, str) or not source_snapshot_id or not isinstance(files, Mapping):
        raise IntegritySnapshotError("upstream governed-fact manifest is invalid")
    if set(files) != set(UPSTREAM_FILES):
        raise IntegritySnapshotError("upstream governed-fact file set is invalid")
    rows_by_name: dict[str, tuple[dict[str, Any], ...]] = {}
    for name in UPSTREAM_FILES:
        path = root / name
        payload = _read_regular(path, name)
        contract = files.get(name)
        if (
            not isinstance(contract, Mapping)
            or set(contract) != {"bytes", "rows", "sha256"}
            or contract.get("bytes") != len(payload)
            or contract.get("sha256") != sha256_bytes(payload)
            or not isinstance(contract.get("rows"), int)
            or isinstance(contract.get("rows"), bool)
        ):
            raise IntegritySnapshotError(f"{name} contract mismatch")
        rows = _read_canonical_jsonl(path, name)
        if len(rows) != contract["rows"]:
            raise IntegritySnapshotError(f"{name} row count mismatch")
        rows_by_name[name] = rows

    facts = rows_by_name["governed-facts.jsonl"]
    by_fact_id: dict[str, dict[str, Any]] = {}
    for fact in facts:
        _validate_fact(fact)
        fact_id = str(fact["fact_id"])
        if fact_id in by_fact_id:
            raise IntegritySnapshotError("duplicate governed fact ID")
        by_fact_id[fact_id] = fact

    observations = rows_by_name["integrity-observations.jsonl"]
    seen_entities: set[str] = set()
    for row in observations:
        _validate_observation(row, by_fact_id)
        entity_id = str(row["entity_id"])
        if entity_id in seen_entities:
            raise IntegritySnapshotError("duplicate integrity observation entity")
        seen_entities.add(entity_id)

    event_roots = rows_by_name["event-roots.jsonl"]
    if len(event_roots) != len(FIXED_EVENT_POST_IDS):
        raise IntegritySnapshotError("fixed Momcozy event roots are incomplete")
    seen_posts: set[str] = set()
    for row in event_roots:
        _validate_event_root(row, by_fact_id)
        post_id = str(row["post_id"])
        if post_id in seen_posts:
            raise IntegritySnapshotError("duplicate fixed event root")
        seen_posts.add(post_id)
    if seen_posts != set(FIXED_EVENT_POST_IDS):
        raise IntegritySnapshotError("fixed Momcozy event roots are incomplete")

    return GovernedIntegrityInputs(
        facts=tuple(sorted(facts, key=lambda row: str(row["fact_id"]))),
        observations=tuple(sorted(observations, key=lambda row: str(row["entity_id"]))),
        event_roots=tuple(
            sorted(event_roots, key=lambda row: FIXED_EVENT_POST_IDS.index(str(row["post_id"])))
        ),
        source_snapshot_id=source_snapshot_id,
        upstream_manifest_sha256=manifest_sha,
        upstream_receipt_sha256=receipt_sha,
        policy_sha256=policy_sha,
    )


def _stable_id(kind: str, payload: object) -> str:
    return f"{kind}:{sha256_bytes(canonical_json_bytes(payload))}"


def _level_rank(value: str) -> int:
    return int(value[1:])


def build_snapshot_documents(
    inputs: GovernedIntegrityInputs,
    *,
    policy: Mapping[str, Any],
    snapshot_id: str,
    generated_at_utc: str,
) -> IntegritySnapshotDocuments:
    if not isinstance(snapshot_id, str) or not snapshot_id:
        raise IntegritySnapshotError("snapshot ID is invalid")
    generated_at = _canonical_utc(generated_at_utc, "generated at")
    assessments: list[dict[str, Any]] = []
    cluster_members: dict[str, list[dict[str, Any]]] = {}
    for row in inputs.observations:
        try:
            assessment = classify_integrity(row["classification_input"])
        except ContentIntegrityError as exc:
            raise IntegritySnapshotError("integrity assessment replay failed") from exc
        value = assessment.as_dict()
        value["schema_version"] = "reddit_voc_integrity_assessment_v1"
        value["source_snapshot_id"] = inputs.source_snapshot_id
        value["cluster_id"] = None
        cluster_key = row["cluster_key"]
        if cluster_key is not None:
            cluster_id = _stable_id(
                "cluster",
                {
                    "cluster_key": cluster_key,
                    "policy_sha256": inputs.policy_sha256,
                    "source_snapshot_id": inputs.source_snapshot_id,
                },
            )
            value["cluster_id"] = cluster_id
            cluster_members.setdefault(cluster_id, []).append(value)
        assessments.append(value)
    assessments.sort(key=lambda row: str(row["entity_id"]))

    clusters: list[dict[str, Any]] = []
    for cluster_id, members in sorted(cluster_members.items()):
        entities = sorted(str(row["entity_id"]) for row in members)
        evidence = sorted(
            {str(value) for row in members for value in row["evidence_ids"]}
        )
        commercial = max(
            (str(row["commercial_relation"]) for row in members), key=_level_rank
        )
        integrity = max(
            (str(row["integrity_level"]) for row in members), key=_level_rank
        )
        clusters.append(
            {
                "cluster_id": cluster_id,
                "commercial_relation": commercial,
                "entity_ids": entities,
                "evidence_ids": evidence,
                "integrity_level": integrity,
                "member_count": len(entities),
                "schema_version": "reddit_voc_integrity_cluster_v1",
                "source_snapshot_id": inputs.source_snapshot_id,
            }
        )

    try:
        chain = build_event_chain(
            [
                {
                    "post_id": row["post_id"],
                    "authority": row["authority"],
                    "evidence_id": row["evidence_id"],
                }
                for row in inputs.event_roots
            ]
        )
    except ContentIntegrityError as exc:
        raise IntegritySnapshotError("fixed Momcozy event chain cannot be built") from exc
    event = chain.as_dict()
    event["schema_version"] = "reddit_voc_integrity_event_dossier_v1"
    event["cluster_id"] = _stable_id(
        "cluster",
        {
            "event_id": chain.event_id,
            "policy_sha256": inputs.policy_sha256,
            "source_snapshot_id": inputs.source_snapshot_id,
        },
    )
    event["source_snapshot_id"] = inputs.source_snapshot_id
    events = (event,)

    reviews: list[dict[str, Any]] = []
    for assessment in assessments:
        if assessment["commercial_relation"] not in {"C2", "C3"} and assessment[
            "integrity_level"
        ] not in {"I2", "I3", "I4"}:
            continue
        identity = {
            "assessment_id": assessment["assessment_id"],
            "cluster_id": assessment["cluster_id"],
            "entity_id": assessment["entity_id"],
            "source_snapshot_id": inputs.source_snapshot_id,
        }
        reviews.append(
            {
                **identity,
                "review_id": _stable_id("review", identity),
                "review_status": "queued",
                "response_status": "unanswered",
                "schema_version": "reddit_voc_integrity_review_item_v1",
            }
        )
    event_review_identity = {
        "event_id": event["event_id"],
        "cluster_id": event["cluster_id"],
        "source_snapshot_id": inputs.source_snapshot_id,
    }
    reviews.append(
        {
            **event_review_identity,
            "review_id": _stable_id("review", event_review_identity),
            "review_status": "queued",
            "response_status": "unanswered",
            "schema_version": "reddit_voc_integrity_review_item_v1",
        }
    )
    reviews.sort(key=lambda row: str(row["review_id"]))

    raw = [row for row in assessments if row["metric_excluded"] is False]
    confirmed = [
        row
        for row in raw
        if row["commercial_relation"] == "C3" and row["integrity_level"] == "I4"
    ]
    qualified = [row for row in raw if row not in confirmed]
    sensitivity = {
        "c3_i4_excluded_entity_count": len(confirmed),
        "explicit_automation_baseline_excluded_entity_count": sum(
            row["metric_excluded"] is True for row in assessments
        ),
        "qualified_organic_entity_count": len(qualified),
        "raw_observed_metric_eligible_entity_count": len(raw),
        "raw_qualified_entity_count_delta": len(raw) - len(qualified),
        "schema_version": "reddit_voc_integrity_sensitivity_v1",
        "source_snapshot_id": inputs.source_snapshot_id,
    }
    lifecycle = {
        "response_transitions": policy["response_transitions"],
        "review_transitions": policy["review_lifecycle"],
        "schema_version": "reddit_voc_integrity_lifecycle_v1",
    }
    level_counts = {
        **{level: 0 for level in ("C0", "C1", "C2", "C3")},
        **{level: 0 for level in ("I0", "I1", "I2", "I3", "I4")},
    }
    for row in assessments:
        level_counts[str(row["commercial_relation"])] += 1
        level_counts[str(row["integrity_level"])] += 1
    manifest_base = {
        "boundaries": dict(BOUNDARIES),
        "consumption_status": "candidate_pending_independent_validation",
        "counts": {
            "assessments": len(assessments),
            "clusters": len(clusters),
            "event_dossiers": len(events),
            "governed_facts": len(inputs.facts),
            "review_items": len(reviews),
        },
        "generated_at_utc": generated_at,
        "level_counts": level_counts,
        "policy_sha256": inputs.policy_sha256,
        "promotable": False,
        "schema_version": MANIFEST_SCHEMA,
        "snapshot_id": snapshot_id,
        "source_snapshot_id": inputs.source_snapshot_id,
        "status": "candidate_built",
        "upstream_manifest_sha256": inputs.upstream_manifest_sha256,
        "upstream_receipt_sha256": inputs.upstream_receipt_sha256,
    }
    return IntegritySnapshotDocuments(
        assessments=tuple(assessments),
        clusters=tuple(clusters),
        events=events,
        reviews=tuple(reviews),
        sensitivity=sensitivity,
        lifecycle=lifecycle,
        manifest_base=manifest_base,
    )


def snapshot_payloads(documents: IntegritySnapshotDocuments) -> dict[str, bytes]:
    return {
        "assessments.jsonl": canonical_jsonl(documents.assessments),
        "clusters.jsonl": canonical_jsonl(documents.clusters),
        "event-dossiers.jsonl": canonical_jsonl(documents.events),
        "review-ledger.jsonl": canonical_jsonl(documents.reviews),
        "sensitivity.json": canonical_json_document(documents.sensitivity),
        "lifecycle.json": canonical_json_document(documents.lifecycle),
    }


def _file_contract(name: str, payload: bytes) -> dict[str, object]:
    return {
        "bytes": len(payload),
        "media_type": "application/x-ndjson" if name.endswith(".jsonl") else "application/json",
        "rows": len(payload.splitlines()) if name.endswith(".jsonl") else 1,
        "sha256": sha256_bytes(payload),
    }


def write_integrity_snapshot(
    output_dir: Path, documents: IntegritySnapshotDocuments
) -> dict[str, Any]:
    output = Path(output_dir)
    if output.exists():
        raise IntegritySnapshotError("integrity snapshot output already exists")
    payloads = snapshot_payloads(documents)
    manifest = dict(documents.manifest_base)
    manifest["files"] = {
        name: _file_contract(name, payload) for name, payload in sorted(payloads.items())
    }
    parent = output.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=parent))
    try:
        for name, payload in payloads.items():
            (temporary / name).write_bytes(payload)
        (temporary / "manifest.json").write_bytes(canonical_json_document(manifest))
        os.replace(temporary, output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return manifest
