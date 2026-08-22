"""Freeze the five-root Momcozy integrity evidence as governed inputs.

The fifth root remains an external public reference.  This module binds its
three exact-span facts to the verified Task 9 snapshot without creating a
Task 4 canonical row or VOC.
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
from typing import Any, Iterable, Mapping

from reddit_voc.v3_content_integrity import FIXED_EVENT_POST_IDS
from reddit_voc.v3_integrity_snapshot import (
    BOUNDARIES,
    EVENT_ROOT_SCHEMA,
    OBSERVATION_SCHEMA,
    UPSTREAM_MANIFEST_SCHEMA,
    UPSTREAM_RECEIPT_SCHEMA,
    _derived_classification_input,
    _validate_event_root,
    _validate_fact,
    _validate_observation,
    canonical_json_bytes,
    canonical_json_document,
    canonical_jsonl,
    sha256_bytes,
)


CANONICAL_ROOT_IDS = FIXED_EVENT_POST_IDS[:-1]
EXTERNAL_REFERENCE_ID = FIXED_EVENT_POST_IDS[-1]
GOVERNED_TABLES = (
    "community-governance-facts.jsonl",
    "commercial-relation-facts.jsonl",
    "integrity-signal-facts.jsonl",
)
INPUT_FILES = (
    "governed-facts.jsonl",
    "integrity-observations.jsonl",
    "event-roots.jsonl",
)
REFERENCE_MANIFEST_SCHEMA = "reddit_voc_case_reference_registry_manifest_v1"
REFERENCE_RECEIPT_SCHEMA = (
    "reddit_voc_case_reference_registry_validation_receipt_v1"
)
CASEBOOK_MANIFEST_SCHEMA = "reddit_voc_governance_casebook_manifest_v1"
CASEBOOK_RECEIPT_SCHEMA = "reddit_voc_governance_casebook_validation_receipt_v1"
GOVERNED_MANIFEST_SCHEMA = "reddit_voc_governed_signal_snapshot_v1"
GOVERNED_RECEIPT_SCHEMA = "reddit_voc_governed_signal_validation_receipt_v1"
FACTS_MANIFEST_SCHEMA = "reddit_voc_voc_facts_manifest_v2"
FACTS_RECEIPT_SCHEMA = "reddit_voc_voc_facts_validation_receipt_v2"
SHA256_RE = re.compile(r"[0-9a-f]{64}")


class IntegrityInputError(ValueError):
    """An integrity source or frozen input bundle violates its contract."""


@dataclass(frozen=True)
class IntegrityInputSources:
    canonical_facts: tuple[dict[str, Any], ...]
    external_facts: tuple[dict[str, Any], ...]
    source_snapshot_id: str
    input_hashes: dict[str, str]


@dataclass(frozen=True)
class IntegrityInputDocuments:
    facts: tuple[dict[str, Any], ...]
    observations: tuple[dict[str, Any], ...]
    event_roots: tuple[dict[str, Any], ...]
    manifest_base: dict[str, Any]


def _read_regular(path: Path, label: str) -> bytes:
    path = Path(path)
    try:
        if path.is_symlink() or not path.is_file():
            raise IntegrityInputError(f"{label} must be a regular file")
        return path.read_bytes()
    except OSError as exc:
        raise IntegrityInputError(f"{label} is unreadable") from exc


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    payload = _read_regular(path, label)
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegrityInputError(f"{label} JSON is invalid") from exc
    if not isinstance(value, dict) or canonical_json_document(value) != payload:
        raise IntegrityInputError(f"{label} is not canonical JSON")
    return value, payload


def _read_jsonl(path: Path, label: str) -> tuple[dict[str, Any], ...]:
    payload = _read_regular(path, label)
    if payload and not payload.endswith(b"\n"):
        raise IntegrityInputError(f"{label} lacks final newline")
    rows: list[dict[str, Any]] = []
    for ordinal, line in enumerate(payload.splitlines(), start=1):
        try:
            value = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise IntegrityInputError(f"{label} row {ordinal} is invalid") from exc
        if not isinstance(value, dict) or canonical_json_bytes(value) != line:
            raise IntegrityInputError(f"{label} row {ordinal} is not canonical JSON")
        rows.append(value)
    return tuple(rows)


def _canonical_utc(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise IntegrityInputError(f"{label} must be canonical UTC seconds")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IntegrityInputError(f"{label} must be canonical UTC seconds") from exc
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() != timedelta(0)
        or parsed.microsecond != 0
        or value != parsed.isoformat(timespec="seconds")
    ):
        raise IntegrityInputError(f"{label} must be canonical UTC seconds")
    return value


def _file_payload(root: Path, manifest: Mapping[str, Any], name: str) -> bytes:
    payload = _read_regular(Path(root) / name, name)
    files = manifest.get("files")
    contract = files.get(name) if isinstance(files, Mapping) else None
    if (
        not isinstance(contract, Mapping)
        or contract.get("bytes") != len(payload)
        or contract.get("rows") != len(payload.splitlines())
        or contract.get("sha256") != sha256_bytes(payload)
    ):
        raise IntegrityInputError(f"{name} file contract mismatch")
    return payload


def _validate_fact_span(row: Mapping[str, Any], fields: Mapping[str, str]) -> None:
    field = row.get("evidence_field")
    start = row.get("evidence_start")
    end = row.get("evidence_end")
    if (
        not isinstance(field, str)
        or field not in fields
        or type(start) is not int
        or type(end) is not int
        or start < 0
        or end <= start
        or end > len(fields[field])
        or row.get("evidence_text_sha256")
        != sha256(fields[field][start:end].encode("utf-8")).hexdigest()
        or row.get("evidence_scope") != "direct"
        or row.get("normalizer_version") != "source_codepoint_v1"
    ):
        raise IntegrityInputError("governed fact exact span does not replay")


def _load_governed(
    root: Path, receipt_path: Path
) -> tuple[tuple[dict[str, Any], ...], str, dict[str, str], dict[str, Any]]:
    root = Path(root)
    manifest, manifest_payload = _read_json(root / "manifest.json", "governed manifest")
    receipt, receipt_payload = _read_json(receipt_path, "governed receipt")
    manifest_sha = sha256_bytes(manifest_payload)
    receipt_sha = sha256_bytes(receipt_payload)
    if (
        manifest.get("schema_version") != GOVERNED_MANIFEST_SCHEMA
        or manifest.get("boundaries") != BOUNDARIES
        or receipt.get("schema_version") != GOVERNED_RECEIPT_SCHEMA
        or receipt.get("status") != "passed"
        or receipt.get("consumption_status") != "eligible_for_downstream_consumption"
        or receipt.get("promotable") is not True
        or receipt.get("snapshot_manifest_sha256") != manifest_sha
        or receipt.get("boundaries") != BOUNDARIES
        or receipt.get("unaccounted_facts") != 0
        or receipt.get("unaccounted_vocs") != 0
    ):
        raise IntegrityInputError("governed signal lineage is not eligible")
    expected_vocs = {f"post:{post_id}" for post_id in CANONICAL_ROOT_IDS}
    roots_seen: set[str] = set()
    facts: list[dict[str, Any]] = []
    hashes = {
        "governed_manifest_sha256": manifest_sha,
        "governed_receipt_sha256": receipt_sha,
    }
    for name in GOVERNED_TABLES:
        payload = _file_payload(root, manifest, name)
        hashes[name.replace(".jsonl", "_sha256")] = sha256_bytes(payload)
        for row in _read_jsonl(root / name, name):
            voc_id = row.get("voc_id")
            if voc_id == f"post:{EXTERNAL_REFERENCE_ID}":
                raise IntegrityInputError("external reference entered Task 5 canonical facts")
            if voc_id not in expected_vocs or row.get("decision_status") != "promoted":
                continue
            try:
                _validate_fact(row)
            except ValueError as exc:
                raise IntegrityInputError("canonical governed fact identity is invalid") from exc
            post_id = str(voc_id).removeprefix("post:")
            if row.get("canonical_entity_id") != f"t3_{post_id}":
                raise IntegrityInputError("canonical governed fact entity mismatch")
            roots_seen.add(post_id)
            facts.append(row)
    if roots_seen != set(CANONICAL_ROOT_IDS) or len(facts) != 9:
        raise IntegrityInputError("canonical governed root facts are incomplete")
    source_snapshot_id = manifest.get("source_snapshot_id")
    if not isinstance(source_snapshot_id, str) or not source_snapshot_id:
        raise IntegrityInputError("governed source snapshot ID is invalid")
    return tuple(facts), source_snapshot_id, hashes, receipt


def _load_voc_fields(
    root: Path,
    receipt_path: Path,
    *,
    governed_receipt: Mapping[str, Any],
) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    root = Path(root)
    manifest, manifest_payload = _read_json(root / "manifest.json", "VOC facts manifest")
    receipt, receipt_payload = _read_json(receipt_path, "VOC facts receipt")
    manifest_sha = sha256_bytes(manifest_payload)
    receipt_sha = sha256_bytes(receipt_payload)
    governed_inputs = governed_receipt.get("inputs")
    if (
        manifest.get("schema_version") != FACTS_MANIFEST_SCHEMA
        or receipt.get("schema_version") != FACTS_RECEIPT_SCHEMA
        or receipt.get("status") != "passed"
        or receipt.get("bundle_manifest_sha256") != manifest_sha
        or not isinstance(governed_inputs, Mapping)
        or governed_inputs.get("facts_manifest_sha256") != manifest_sha
        or governed_inputs.get("facts_receipt_sha256") != receipt_sha
    ):
        raise IntegrityInputError("VOC facts lineage does not match governed signals")
    payload = _file_payload(root, manifest, "vocs.jsonl")
    if governed_inputs.get("vocs_sha256") != sha256_bytes(payload):
        raise IntegrityInputError("VOC source text SHA does not match governed signals")
    wanted = {f"post:{post_id}": post_id for post_id in CANONICAL_ROOT_IDS}
    fields: dict[str, dict[str, str]] = {}
    for row in _read_jsonl(root / "vocs.jsonl", "vocs.jsonl"):
        voc_id = row.get("voc_id")
        if voc_id == f"post:{EXTERNAL_REFERENCE_ID}":
            raise IntegrityInputError("external reference masquerades as Task 4 VOC")
        post_id = wanted.get(str(voc_id))
        if post_id is None:
            continue
        analysis_fields = row.get("analysis_fields")
        if (
            row.get("voc_type") != "post_voc"
            or row.get("canonical_entity_id") != f"t3_{post_id}"
            or row.get("analysis_text_status") != "ready"
            or not isinstance(analysis_fields, Mapping)
            or not all(
                isinstance(analysis_fields.get(name), str)
                for name in ("post_title", "post_body")
            )
        ):
            raise IntegrityInputError("canonical root VOC is not replayable")
        fields[post_id] = {
            "post_title": str(analysis_fields["post_title"]),
            "post_body": str(analysis_fields["post_body"]),
        }
    if set(fields) != set(CANONICAL_ROOT_IDS):
        raise IntegrityInputError("canonical source text is incomplete")
    return fields, {
        "facts_manifest_sha256": manifest_sha,
        "facts_receipt_sha256": receipt_sha,
        "vocs_sha256": sha256_bytes(payload),
    }


def _load_external(
    reference_root: Path,
    reference_receipt_path: Path,
    casebook_root: Path,
    casebook_receipt_path: Path,
) -> tuple[tuple[dict[str, Any], ...], dict[str, str]]:
    reference_root = Path(reference_root)
    ref_manifest, ref_manifest_payload = _read_json(
        reference_root / "manifest.json", "reference manifest"
    )
    ref_receipt, ref_receipt_payload = _read_json(
        reference_receipt_path, "reference receipt"
    )
    ref_manifest_sha = sha256_bytes(ref_manifest_payload)
    if (
        ref_manifest.get("schema_version") != REFERENCE_MANIFEST_SCHEMA
        or ref_manifest.get("boundaries") != BOUNDARIES
        or ref_receipt.get("schema_version") != REFERENCE_RECEIPT_SCHEMA
        or ref_receipt.get("status") != "passed"
        or ref_receipt.get("consumption_status") != "eligible_for_casebook"
        or ref_receipt.get("promotable") is not True
        or ref_receipt.get("registry_manifest_sha256") != ref_manifest_sha
        or ref_receipt.get("boundaries") != BOUNDARIES
    ):
        raise IntegrityInputError("external reference registry is not eligible")
    _file_payload(reference_root, ref_manifest, "external-public-snapshots.jsonl")
    snapshots = _read_jsonl(
        reference_root / "external-public-snapshots.jsonl", "external snapshots"
    )
    if len(snapshots) != 1:
        raise IntegrityInputError("external snapshot cardinality is invalid")
    snapshot = snapshots[0]
    if (
        snapshot.get("reddit_post_id") != EXTERNAL_REFERENCE_ID
        or snapshot.get("source_role")
        != "external_public_reference_noncanonical"
        or snapshot.get("canonical_task4_row") is not False
        or not isinstance(snapshot.get("post_body"), str)
    ):
        raise IntegrityInputError("external snapshot crossed the canonical boundary")

    casebook_root = Path(casebook_root)
    case_manifest, case_manifest_payload = _read_json(
        casebook_root / "manifest.json", "casebook manifest"
    )
    case_receipt, case_receipt_payload = _read_json(
        casebook_receipt_path, "casebook receipt"
    )
    case_manifest_sha = sha256_bytes(case_manifest_payload)
    if (
        case_manifest.get("schema_version") != CASEBOOK_MANIFEST_SCHEMA
        or case_manifest.get("lifecycle_status") != "review_required"
        or case_manifest.get("boundaries") != BOUNDARIES
        or case_receipt.get("schema_version") != CASEBOOK_RECEIPT_SCHEMA
        or case_receipt.get("status") != "passed"
        or case_receipt.get("promotable") is not True
        or case_receipt.get("lifecycle_status") != "review_required"
        or case_receipt.get("casebook_manifest_sha256") != case_manifest_sha
        or case_receipt.get("boundaries") != BOUNDARIES
        or case_manifest.get("inputs", {}).get("reference_registry_manifest_sha256")
        != ref_manifest_sha
    ):
        raise IntegrityInputError("casebook external evidence is not eligible")
    _file_payload(casebook_root, case_manifest, "external-governance-facts.jsonl")
    external_facts = _read_jsonl(
        casebook_root / "external-governance-facts.jsonl", "external facts"
    )
    if len(external_facts) != 3:
        raise IntegrityInputError("external governed fact cardinality is invalid")
    fields = {"post_body": str(snapshot["post_body"])}
    for row in external_facts:
        try:
            _validate_fact(row)
        except ValueError as exc:
            raise IntegrityInputError("external governed fact identity is invalid") from exc
        attributes = row.get("attributes")
        if (
            row.get("canonical_entity_id")
            != f"external_reddit_post:{EXTERNAL_REFERENCE_ID}"
            or row.get("voc_id") != f"external-post:{EXTERNAL_REFERENCE_ID}"
            or row.get("voc_type") != "external_public_reference"
            or row.get("evidence_source_entity_id")
            != f"external_reddit_post:{EXTERNAL_REFERENCE_ID}"
            or not isinstance(attributes, Mapping)
            or attributes.get("source_role")
            != "external_public_reference_noncanonical"
            or attributes.get("brand_control_confirmed") is not False
            or attributes.get("commercial_relation_ceiling") != "C2"
            or attributes.get("integrity_level_ceiling") != "I3"
        ):
            raise IntegrityInputError("external fact exceeds evidence boundary")
        _validate_fact_span(row, fields)
    return external_facts, {
        "casebook_manifest_sha256": case_manifest_sha,
        "casebook_receipt_sha256": sha256_bytes(case_receipt_payload),
        "external_public_snapshots_sha256": str(
            ref_manifest["files"]["external-public-snapshots.jsonl"]["sha256"]
        ),
        "reference_manifest_sha256": ref_manifest_sha,
        "reference_receipt_sha256": sha256_bytes(ref_receipt_payload),
    }


def load_integrity_sources(
    *,
    governed_root: Path,
    governed_receipt_path: Path,
    voc_facts_root: Path,
    voc_facts_receipt_path: Path,
    reference_root: Path,
    reference_receipt_path: Path,
    casebook_root: Path,
    casebook_receipt_path: Path,
) -> IntegrityInputSources:
    canonical_facts, source_snapshot_id, governed_hashes, governed_receipt = (
        _load_governed(governed_root, governed_receipt_path)
    )
    voc_fields, voc_hashes = _load_voc_fields(
        voc_facts_root,
        voc_facts_receipt_path,
        governed_receipt=governed_receipt,
    )
    for row in canonical_facts:
        post_id = str(row["voc_id"]).removeprefix("post:")
        _validate_fact_span(row, voc_fields[post_id])
    external_facts, external_hashes = _load_external(
        reference_root,
        reference_receipt_path,
        casebook_root,
        casebook_receipt_path,
    )
    return IntegrityInputSources(
        canonical_facts=tuple(sorted(canonical_facts, key=lambda row: str(row["fact_id"]))),
        external_facts=tuple(sorted(external_facts, key=lambda row: str(row["fact_id"]))),
        source_snapshot_id=source_snapshot_id,
        input_hashes={**governed_hashes, **voc_hashes, **external_hashes},
    )


def _event_evidence(facts: Iterable[Mapping[str, Any]], post_id: str) -> str:
    candidates = [
        row
        for row in facts
        if row.get("canonical_entity_id")
        in {f"t3_{post_id}", f"external_reddit_post:{post_id}"}
        and (
            (
                row.get("fact_type") == "community_governance_fact"
                and row.get("attributes", {}).get("authority")
                == "subreddit_moderator"
            )
            or (
                row.get("fact_type") == "integrity_signal_fact"
                and row.get("attributes", {}).get("assertion_mode")
                == "subreddit_moderator_allegation"
            )
        )
    ]
    if not candidates:
        raise IntegrityInputError(f"fixed event root {post_id} lacks moderator evidence")
    candidates.sort(
        key=lambda row: (
            0 if row.get("fact_type") == "community_governance_fact" else 1,
            str(row["fact_id"]),
        )
    )
    return str(candidates[0]["fact_id"])


def build_integrity_input_documents(
    sources: IntegrityInputSources,
    *,
    policy_sha256: str,
    input_id: str,
    generated_at_utc: str,
) -> IntegrityInputDocuments:
    generated_at_utc = _canonical_utc(generated_at_utc, "input generated at")
    if not isinstance(input_id, str) or not input_id:
        raise IntegrityInputError("integrity input ID is invalid")
    if SHA256_RE.fullmatch(policy_sha256) is None:
        raise IntegrityInputError("integrity policy SHA is invalid")
    facts = tuple(
        sorted(
            (*sources.canonical_facts, *sources.external_facts),
            key=lambda row: str(row["fact_id"]),
        )
    )
    by_entity: dict[str, list[dict[str, Any]]] = {}
    by_fact_id = {str(row["fact_id"]): row for row in facts}
    for fact in facts:
        by_entity.setdefault(str(fact["canonical_entity_id"]), []).append(fact)
    expected_entities = {
        *(f"t3_{post_id}" for post_id in CANONICAL_ROOT_IDS),
        f"external_reddit_post:{EXTERNAL_REFERENCE_ID}",
    }
    if set(by_entity) != expected_entities:
        raise IntegrityInputError("integrity observation entities are incomplete")
    observations: list[dict[str, Any]] = []
    for entity_id, rows in sorted(by_entity.items()):
        evidence_ids = sorted(str(row["fact_id"]) for row in rows)
        observation = {
            "classification_input": _derived_classification_input(
                entity_id, evidence_ids, by_fact_id
            ),
            "cluster_key": "momcozy-community-governance-fixed-event",
            "entity_id": entity_id,
            "evidence_ids": evidence_ids,
            "schema_version": OBSERVATION_SCHEMA,
        }
        _validate_observation(observation, by_fact_id)
        observations.append(observation)
    event_roots = tuple(
        {
            "authority": "subreddit_moderator",
            "evidence_id": _event_evidence(facts, post_id),
            "post_id": post_id,
            "schema_version": EVENT_ROOT_SCHEMA,
        }
        for post_id in FIXED_EVENT_POST_IDS
    )
    for row in event_roots:
        _validate_event_root(row, by_fact_id)
    counts = {
        "canonical_facts": len(sources.canonical_facts),
        "canonical_roots": len(CANONICAL_ROOT_IDS),
        "event_roots": len(event_roots),
        "external_facts": len(sources.external_facts),
        "external_references": 1,
        "governed_facts": len(facts),
        "integrity_observations": len(observations),
    }
    manifest_base = {
        "boundaries": dict(BOUNDARIES),
        "consumption_status": "ready",
        "counts": counts,
        "external_reference_boundary": {
            "brand_control_confirmed": False,
            "canonical_task4_row": False,
            "reference_id": EXTERNAL_REFERENCE_ID,
            "source_role": "external_public_reference_noncanonical",
        },
        "generated_at_utc": generated_at_utc,
        "input_id": input_id,
        "inputs": dict(sorted(sources.input_hashes.items())),
        "lifecycle_status": "review_required",
        "policy_sha256": policy_sha256,
        "promotable": True,
        "schema_version": UPSTREAM_MANIFEST_SCHEMA,
        "source_snapshot_id": sources.source_snapshot_id,
        "status": "frozen",
    }
    return IntegrityInputDocuments(
        facts=facts,
        observations=tuple(observations),
        event_roots=event_roots,
        manifest_base=manifest_base,
    )


def _file_contract(payload: bytes) -> dict[str, object]:
    return {
        "bytes": len(payload),
        "rows": len(payload.splitlines()),
        "sha256": sha256_bytes(payload),
    }


def input_payloads(documents: IntegrityInputDocuments) -> dict[str, bytes]:
    return {
        "governed-facts.jsonl": canonical_jsonl(documents.facts),
        "integrity-observations.jsonl": canonical_jsonl(documents.observations),
        "event-roots.jsonl": canonical_jsonl(documents.event_roots),
    }


def write_integrity_inputs(output_root: Path, documents: IntegrityInputDocuments) -> dict[str, Any]:
    output_root = Path(output_root)
    if output_root.exists() or output_root.is_symlink():
        raise IntegrityInputError("integrity input output root already exists")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging = output_root.parent / f".{output_root.name}.building"
    if staging.exists() or staging.is_symlink():
        raise IntegrityInputError("integrity input staging root already exists")
    payloads = input_payloads(documents)
    manifest = {
        **documents.manifest_base,
        "files": {name: _file_contract(payload) for name, payload in sorted(payloads.items())},
    }
    staging.mkdir()
    try:
        for name, payload in payloads.items():
            (staging / name).write_bytes(payload)
        (staging / "manifest.json").write_bytes(canonical_json_document(manifest))
        os.replace(staging, output_root)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return manifest


def write_validation_receipt(path: Path, result: Mapping[str, object]) -> str:
    path = Path(path)
    payload = canonical_json_document(dict(result))
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise IntegrityInputError("integrity input receipt collision")
        return "no_change"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.write(descriptor, payload)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()
    return "created"
