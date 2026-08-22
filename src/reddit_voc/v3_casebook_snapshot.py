"""Build the private, review-required Momcozy Reddit governance casebook."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
from typing import Any, Mapping

from reddit_voc.v3_atomic_facts import (
    build_external_reference_atomic_facts,
    validate_external_reference_atomic_facts,
)
from reddit_voc.v3_casebook import build_momcozy_governance_dossier


MANIFEST_SCHEMA = "reddit_voc_governance_casebook_manifest_v1"
RECEIPT_SCHEMA = "reddit_voc_governance_casebook_validation_receipt_v1"
EVENT_SCHEMA = "reddit_voc_governance_event_assessment_v1"
BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}
OUTPUT_FILES = (
    "action-monitoring-ledger.jsonl",
    "case-dossiers.jsonl",
    "event-assessments.jsonl",
    "external-governance-facts.jsonl",
)
CANONICAL_ROOT_IDS = ("1kkvihg", "1l2aofi", "1n2q1do", "1o1pqox")
EXTERNAL_REFERENCE_ID = "1u2gvn4"
EVIDENCE_ONLY_COMMENT_IDS = (
    "oqxzocv",
    "oqybf3b",
    "oqyl8ep",
    "oqysk5m",
    "oqysnp5",
    "oqywkz0",
    "oqyylwe",
    "oqz352q",
    "oqz88dy",
    "oqzjtem",
    "oqzkqnw",
    "or0e49n",
    "or0imt7",
    "or169tv",
    "or1cusw",
    "or37v9c",
)
FACTS_MANIFEST_SHA256 = (
    "4a0b43f664cc8bd2cf0fbd63d0428aaeadec1a6b405a066123250e4f90675b77"
)
FACTS_RECEIPT_SHA256 = (
    "ff6ee119c5861cfad50d256caebaf3600564013b6069b97d047e9197c90eb61f"
)
GOVERNED_MANIFEST_SHA256 = (
    "44c66b198f3dc33873036912c239f89d28fabe36ed2aaacc5662c7686dd4c24a"
)
GOVERNED_RECEIPT_SHA256 = (
    "135d9f4a78dd772f5feae193783d98f78969d8b68d3cf6bf2b368f6fee98d9db"
)
SHA256_RE = re.compile(r"[0-9a-f]{64}")


class CasebookSnapshotError(ValueError):
    """A casebook input or candidate violates the governed contract."""


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
        raise CasebookSnapshotError("value is not canonical JSON serializable") from exc


def canonical_json_document(value: object) -> bytes:
    return canonical_json_bytes(value) + b"\n"


def sha256_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = sha256()
    try:
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise CasebookSnapshotError(f"input is unreadable: {path}") from exc
    return digest.hexdigest()


def _load_json(path: Path, label: str) -> tuple[dict[str, Any], str]:
    path = Path(path)
    try:
        if path.is_symlink() or not path.is_file():
            raise CasebookSnapshotError(f"{label} must be a regular file")
        payload = path.read_bytes()
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CasebookSnapshotError(f"{label} is invalid") from exc
    if not isinstance(value, dict):
        raise CasebookSnapshotError(f"{label} must be an object")
    return value, sha256_bytes(payload)


def _canonical_utc(value: str, label: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise CasebookSnapshotError(f"{label} must be canonical UTC seconds") from exc
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() != timedelta(0)
        or parsed.microsecond != 0
        or value != parsed.isoformat(timespec="seconds")
    ):
        raise CasebookSnapshotError(f"{label} must be canonical UTC seconds")
    return value


def _check_file_contract(root: Path, manifest: Mapping[str, Any], name: str) -> str:
    files = manifest.get("files")
    contract = files.get(name) if isinstance(files, Mapping) else None
    path = root / name
    if (
        not isinstance(contract, Mapping)
        or not isinstance(contract.get("sha256"), str)
        or SHA256_RE.fullmatch(str(contract["sha256"])) is None
        or path.is_symlink()
        or not path.is_file()
        or sha256_file(path) != contract["sha256"]
    ):
        raise CasebookSnapshotError(f"{name} file contract mismatch")
    return str(contract["sha256"])


def _load_reference_inputs(
    registry_root: Path, receipt_path: Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    registry_root = Path(registry_root)
    manifest, manifest_sha = _load_json(registry_root / "manifest.json", "reference manifest")
    receipt, receipt_sha = _load_json(receipt_path, "reference receipt")
    if (
        receipt.get("status") != "passed"
        or receipt.get("promotable") is not True
        or receipt.get("consumption_status") != "eligible_for_casebook"
        or receipt.get("registry_manifest_sha256") != manifest_sha
        or manifest.get("counts", {}).get("default_eligible") != 1
    ):
        raise CasebookSnapshotError("reference registry is not casebook-eligible")
    _check_file_contract(registry_root, manifest, "references.jsonl")
    snapshot_sha = _check_file_contract(
        registry_root, manifest, "external-public-snapshots.jsonl"
    )
    snapshots = _read_jsonl(registry_root / "external-public-snapshots.jsonl", "external snapshots")
    references = _read_jsonl(registry_root / "references.jsonl", "references")
    if len(snapshots) != 1 or len(references) != 1:
        raise CasebookSnapshotError("reference registry must contain one external reference")
    snapshot = snapshots[0]
    reference = references[0]
    if (
        snapshot.get("reddit_post_id") != EXTERNAL_REFERENCE_ID
        or snapshot.get("source_role") != "external_public_reference_noncanonical"
        or snapshot.get("canonical_task4_row") is not False
        or reference.get("reference_id") != EXTERNAL_REFERENCE_ID
        or reference.get("default_eligible") is not True
        or reference.get("verification_status") != "verified"
        or reference.get("content_hash") != snapshot.get("content_hash")
    ):
        raise CasebookSnapshotError("external reference identity mismatch")
    return snapshot, reference, {
        "reference_registry_manifest_sha256": manifest_sha,
        "reference_registry_receipt_sha256": receipt_sha,
        "external_public_snapshots_sha256": snapshot_sha,
    }


def _read_jsonl(path: Path, label: str) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    try:
        with Path(path).open("rb") as handle:
            for ordinal, line in enumerate(handle, start=1):
                value = json.loads(line.decode("utf-8"))
                if not isinstance(value, dict):
                    raise CasebookSnapshotError(f"{label} row {ordinal} is invalid")
                rows.append(value)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CasebookSnapshotError(f"{label} is invalid") from exc
    return tuple(rows)


def _load_canonical_evidence(
    facts_root: Path,
    facts_receipt_path: Path,
    *,
    expected_manifest_sha256: str = FACTS_MANIFEST_SHA256,
    expected_receipt_sha256: str = FACTS_RECEIPT_SHA256,
) -> tuple[tuple[str, ...], tuple[str, ...], dict[str, str]]:
    facts_root = Path(facts_root)
    manifest, manifest_sha = _load_json(facts_root / "manifest.json", "VOC facts manifest")
    receipt, receipt_sha = _load_json(facts_receipt_path, "VOC facts receipt")
    if (
        manifest_sha != expected_manifest_sha256
        or receipt_sha != expected_receipt_sha256
        or receipt.get("status") != "passed"
        or receipt.get("bundle_manifest_sha256") != manifest_sha
    ):
        raise CasebookSnapshotError("VOC facts lineage mismatch")
    vocs_sha = _check_file_contract(facts_root, manifest, "vocs.jsonl")
    exclusions_sha = _check_file_contract(facts_root, manifest, "voc-exclusions.jsonl")
    root_ids: set[str] = set()
    with (facts_root / "vocs.jsonl").open("r", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            voc_id = row.get("voc_id")
            if voc_id in {f"post:{value}" for value in CANONICAL_ROOT_IDS}:
                post_id = str(row.get("post_id"))
                if (
                    row.get("voc_type") != "post_voc"
                    or row.get("canonical_entity_id") != f"t3_{post_id}"
                    or row.get("analysis_text_status") != "ready"
                ):
                    raise CasebookSnapshotError("canonical root is not analysis-ready")
                root_ids.add(post_id)
            if voc_id == f"post:{EXTERNAL_REFERENCE_ID}":
                raise CasebookSnapshotError("external reference masquerades as canonical VOC")
    if root_ids != set(CANONICAL_ROOT_IDS):
        raise CasebookSnapshotError("canonical governance roots are incomplete")
    comment_ids: set[str] = set()
    with (facts_root / "voc-exclusions.jsonl").open("r", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("post_id") != EXTERNAL_REFERENCE_ID:
                continue
            comment_id = row.get("comment_id")
            if (
                row.get("schema_version") != "reddit_voc_voc_exclusion_v1"
                or row.get("entity_type") != "comment"
                or row.get("canonical_entity_id") != f"t1_{comment_id}"
                or row.get("reason_codes") != ["unresolved_parent"]
                or not isinstance(comment_id, str)
            ):
                raise CasebookSnapshotError("external evidence-only comment is invalid")
            comment_ids.add(comment_id)
    if comment_ids != set(EVIDENCE_ONLY_COMMENT_IDS):
        raise CasebookSnapshotError("external evidence-only comments are incomplete")
    return tuple(sorted(root_ids)), tuple(sorted(comment_ids)), {
        "facts_manifest_sha256": manifest_sha,
        "facts_receipt_sha256": receipt_sha,
        "voc_exclusions_sha256": exclusions_sha,
        "vocs_sha256": vocs_sha,
    }


def _load_governed_fact_ids(
    governed_root: Path,
    governed_receipt_path: Path,
    *,
    expected_manifest_sha256: str = GOVERNED_MANIFEST_SHA256,
    expected_receipt_sha256: str = GOVERNED_RECEIPT_SHA256,
) -> tuple[tuple[str, ...], dict[str, str], str]:
    governed_root = Path(governed_root)
    manifest, manifest_sha = _load_json(governed_root / "manifest.json", "governed signal manifest")
    receipt, receipt_sha = _load_json(governed_receipt_path, "governed signal receipt")
    if (
        manifest_sha != expected_manifest_sha256
        or receipt_sha != expected_receipt_sha256
        or receipt.get("status") != "passed"
        or receipt.get("promotable") is not True
        or receipt.get("snapshot_manifest_sha256") != manifest_sha
    ):
        raise CasebookSnapshotError("governed signal lineage mismatch")
    input_hashes: dict[str, str] = {
        "governed_manifest_sha256": manifest_sha,
        "governed_receipt_sha256": receipt_sha,
    }
    expected_voc_ids = {f"post:{value}" for value in CANONICAL_ROOT_IDS}
    observed_voc_ids: set[str] = set()
    fact_ids: set[str] = set()
    for name in (
        "community-governance-facts.jsonl",
        "commercial-relation-facts.jsonl",
        "integrity-signal-facts.jsonl",
    ):
        input_hashes[name.replace(".jsonl", "_sha256")] = _check_file_contract(
            governed_root, manifest, name
        )
        for row in _read_jsonl(governed_root / name, name):
            voc_id = row.get("voc_id")
            if voc_id in expected_voc_ids:
                observed_voc_ids.add(str(voc_id))
                fact_id = row.get("fact_id")
                if not isinstance(fact_id, str) or SHA256_RE.fullmatch(fact_id) is None:
                    raise CasebookSnapshotError("canonical governed fact ID is invalid")
                fact_ids.add(fact_id)
            if voc_id == f"post:{EXTERNAL_REFERENCE_ID}":
                raise CasebookSnapshotError("external reference entered canonical fact tables")
    if observed_voc_ids != expected_voc_ids or not fact_ids:
        raise CasebookSnapshotError("canonical governed facts are incomplete")
    source_snapshot_id = manifest.get("source_snapshot_id")
    if not isinstance(source_snapshot_id, str) or not source_snapshot_id:
        raise CasebookSnapshotError("governed source snapshot ID is invalid")
    return tuple(sorted(fact_ids)), input_hashes, source_snapshot_id


@dataclass(frozen=True)
class CasebookDocuments:
    dossiers: tuple[dict[str, Any], ...]
    event_assessments: tuple[dict[str, Any], ...]
    external_facts: tuple[dict[str, Any], ...]
    action_ledger: tuple[dict[str, Any], ...]
    manifest_base: dict[str, Any]


def build_casebook_documents(
    *,
    reference_registry_root: Path,
    reference_receipt_path: Path,
    facts_root: Path,
    facts_receipt_path: Path,
    governed_root: Path,
    governed_receipt_path: Path,
    casebook_id: str,
    generated_at: str,
    facts_manifest_sha256: str = FACTS_MANIFEST_SHA256,
    facts_receipt_sha256: str = FACTS_RECEIPT_SHA256,
    governed_manifest_sha256: str = GOVERNED_MANIFEST_SHA256,
    governed_receipt_sha256: str = GOVERNED_RECEIPT_SHA256,
) -> CasebookDocuments:
    generated_at = _canonical_utc(generated_at, "casebook generated at")
    if not isinstance(casebook_id, str) or not casebook_id:
        raise CasebookSnapshotError("casebook ID is invalid")
    external_snapshot, _, reference_hashes = _load_reference_inputs(
        reference_registry_root, reference_receipt_path
    )
    root_ids, comment_ids, fact_hashes = _load_canonical_evidence(
        facts_root,
        facts_receipt_path,
        expected_manifest_sha256=facts_manifest_sha256,
        expected_receipt_sha256=facts_receipt_sha256,
    )
    canonical_fact_ids, governed_hashes, source_snapshot_id = _load_governed_fact_ids(
        governed_root,
        governed_receipt_path,
        expected_manifest_sha256=governed_manifest_sha256,
        expected_receipt_sha256=governed_receipt_sha256,
    )
    external_source_snapshot_id = (
        "case-reference-registry:"
        + reference_hashes["reference_registry_manifest_sha256"]
    )
    external_facts = build_external_reference_atomic_facts(
        external_snapshot,
        source_snapshot_id=external_source_snapshot_id,
        created_at=generated_at,
    )
    validate_external_reference_atomic_facts(
        external_facts,
        external_snapshot,
        source_snapshot_id=external_source_snapshot_id,
        created_at=generated_at,
    )
    external_fact_rows = tuple(row.as_dict() for row in external_facts)
    evidence_binding = {
        "canonical_governed_fact_ids": list(canonical_fact_ids),
        "canonical_root_ids": list(root_ids),
        "evidence_only_comment_ids": list(comment_ids),
        "external_governance_fact_ids": [row["fact_id"] for row in external_fact_rows],
        "external_reference_content_hash": external_snapshot["content_hash"],
        "external_reference_id": EXTERNAL_REFERENCE_ID,
        "external_snapshot_id": external_snapshot["snapshot_id"],
    }
    evidence_snapshot_sha = sha256_bytes(canonical_json_bytes(evidence_binding))
    review_due_at = (
        datetime.fromisoformat(generated_at) + timedelta(days=14)
    ).isoformat(timespec="seconds")
    dossier = build_momcozy_governance_dossier(
        canonical_root_ids=CANONICAL_ROOT_IDS,
        external_reference_id=EXTERNAL_REFERENCE_ID,
        evidence_only_comment_ids=comment_ids,
        insight_ref="storyline:community_trust_non_organic_promotion",
        snapshot_sha256=evidence_snapshot_sha,
        created_at=generated_at,
        review_due_at=review_due_at,
    ).as_dict()
    event = {
        "assertion_status": "subreddit_moderator_public_allegation",
        "brand_control_confirmed": False,
        "canonical_root_ids": list(root_ids),
        "case_id": dossier["case_id"],
        "commercial_relation": "C2",
        "evidence_only_comment_ids": list(comment_ids),
        "evidence_snapshot_sha256": evidence_snapshot_sha,
        "external_reference_id": EXTERNAL_REFERENCE_ID,
        "governance_authority": "subreddit_moderator",
        "integrity_level": "I3",
        "publication_boundary": "risk_observation_not_brand_attribution",
        "schema_version": EVENT_SCHEMA,
    }
    counts = {
        "action_monitoring_rows": 0,
        "canonical_governance_fact_refs": len(canonical_fact_ids),
        "canonical_roots": 4,
        "case_dossiers": 1,
        "event_assessments": 1,
        "evidence_only_comments": 16,
        "external_governance_facts": 3,
        "external_references": 1,
    }
    manifest_base = {
        "actions_display_mode": "suggestion_only",
        "boundaries": dict(BOUNDARIES),
        "casebook_id": casebook_id,
        "consumption_status": "candidate_pending_independent_validation",
        "counts": counts,
        "evidence_accounting": {
            "canonical_roots": 4,
            "evidence_only_comments": 16,
            "external_references": 1,
            "unaccounted": 0,
        },
        "evidence_snapshot_sha256": evidence_snapshot_sha,
        "generated_at": generated_at,
        "inputs": {**reference_hashes, **fact_hashes, **governed_hashes},
        "lifecycle_status": "review_required",
        "promotable": False,
        "schema_version": MANIFEST_SCHEMA,
        "source_snapshot_id": source_snapshot_id,
        "status": "candidate_built",
    }
    return CasebookDocuments(
        dossiers=(dossier,),
        event_assessments=(event,),
        external_facts=external_fact_rows,
        action_ledger=(),
        manifest_base=manifest_base,
    )


def _file_contract(payload: bytes) -> dict[str, object]:
    return {
        "bytes": len(payload),
        "media_type": "application/x-ndjson",
        "rows": len(payload.splitlines()),
        "sha256": sha256_bytes(payload),
    }


def write_casebook_snapshot(output_root: Path, documents: CasebookDocuments) -> dict[str, Any]:
    output_root = Path(output_root)
    if output_root.exists() or output_root.is_symlink():
        raise CasebookSnapshotError("casebook output root already exists")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging = output_root.parent / f".{output_root.name}.building"
    if staging.exists() or staging.is_symlink():
        raise CasebookSnapshotError("casebook staging root already exists")
    staging.mkdir()
    try:
        rows_by_file = {
            "action-monitoring-ledger.jsonl": documents.action_ledger,
            "case-dossiers.jsonl": documents.dossiers,
            "event-assessments.jsonl": documents.event_assessments,
            "external-governance-facts.jsonl": documents.external_facts,
        }
        payloads = {
            name: b"".join(canonical_json_document(row) for row in rows)
            for name, rows in rows_by_file.items()
        }
        for name, payload in payloads.items():
            (staging / name).write_bytes(payload)
        manifest = {
            **documents.manifest_base,
            "files": {
                name: _file_contract(payload)
                for name, payload in sorted(payloads.items())
            },
        }
        (staging / "manifest.json").write_bytes(canonical_json_document(manifest))
        staging.rename(output_root)
        return manifest
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
