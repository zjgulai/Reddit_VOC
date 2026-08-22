"""Independent semantic and byte replay for the private governance casebook."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Any, Mapping

from reddit_voc.v3_atomic_facts import build_external_reference_atomic_facts
from reddit_voc.v3_casebook import build_momcozy_governance_dossier
from reddit_voc.v3_casebook_snapshot import (
    BOUNDARIES,
    CANONICAL_ROOT_IDS,
    EVIDENCE_ONLY_COMMENT_IDS,
    EVENT_SCHEMA,
    EXTERNAL_REFERENCE_ID,
    FACTS_MANIFEST_SHA256,
    FACTS_RECEIPT_SHA256,
    GOVERNED_MANIFEST_SHA256,
    GOVERNED_RECEIPT_SHA256,
    MANIFEST_SCHEMA,
    OUTPUT_FILES,
    RECEIPT_SCHEMA,
    canonical_json_bytes,
    canonical_json_document,
    sha256_bytes,
    sha256_file,
)


class CasebookSnapshotValidationError(ValueError):
    """The casebook does not replay from its frozen private evidence."""


def _read_json(
    path: Path, label: str, *, require_canonical: bool = False
) -> tuple[dict[str, Any], bytes]:
    path = Path(path)
    try:
        if path.is_symlink() or not path.is_file():
            raise CasebookSnapshotValidationError(f"{label} must be a regular file")
        payload = path.read_bytes()
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CasebookSnapshotValidationError(f"{label} is invalid") from exc
    if not isinstance(value, dict) or (
        require_canonical and payload != canonical_json_document(value)
    ):
        raise CasebookSnapshotValidationError(f"{label} is not canonical")
    return value, payload


def _read_jsonl(
    path: Path, label: str, *, require_canonical: bool = False
) -> tuple[dict[str, Any], ...]:
    path = Path(path)
    try:
        if path.is_symlink() or not path.is_file():
            raise CasebookSnapshotValidationError(f"{label} must be a regular file")
        payload = path.read_bytes()
    except OSError as exc:
        raise CasebookSnapshotValidationError(f"{label} is unreadable") from exc
    rows: list[dict[str, Any]] = []
    for ordinal, line in enumerate(payload.splitlines(), start=1):
        try:
            row = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CasebookSnapshotValidationError(
                f"{label} row {ordinal} is invalid"
            ) from exc
        if not isinstance(row, dict) or (
            require_canonical and line != canonical_json_bytes(row)
        ):
            raise CasebookSnapshotValidationError(
                f"{label} row {ordinal} is not canonical"
            )
        rows.append(row)
    if require_canonical and payload and not payload.endswith(b"\n"):
        raise CasebookSnapshotValidationError(f"{label} lacks final newline")
    return tuple(rows)


def _file_contract(payload: bytes) -> dict[str, object]:
    return {
        "bytes": len(payload),
        "media_type": "application/x-ndjson",
        "rows": len(payload.splitlines()),
        "sha256": sha256_bytes(payload),
    }


def _upstream_file_sha(root: Path, manifest: Mapping[str, Any], name: str) -> str:
    files = manifest.get("files")
    contract = files.get(name) if isinstance(files, Mapping) else None
    path = root / name
    if (
        not isinstance(contract, Mapping)
        or not isinstance(contract.get("sha256"), str)
        or sha256_file(path) != contract["sha256"]
    ):
        raise CasebookSnapshotValidationError(f"upstream {name} contract mismatch")
    return str(contract["sha256"])


def _canonical_roots_and_comments(
    facts_root: Path,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    expected_voc_ids = {f"post:{value}" for value in CANONICAL_ROOT_IDS}
    roots: set[str] = set()
    try:
        with (facts_root / "vocs.jsonl").open("r", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                voc_id = row.get("voc_id")
                if voc_id in expected_voc_ids:
                    post_id = row.get("post_id")
                    if (
                        not isinstance(post_id, str)
                        or row.get("voc_type") != "post_voc"
                        or row.get("canonical_entity_id") != f"t3_{post_id}"
                        or row.get("analysis_text_status") != "ready"
                    ):
                        raise CasebookSnapshotValidationError(
                            "canonical root identity mismatch"
                        )
                    roots.add(post_id)
                if voc_id == f"post:{EXTERNAL_REFERENCE_ID}":
                    raise CasebookSnapshotValidationError(
                        "external reference entered canonical VOCs"
                    )
        comments: set[str] = set()
        with (facts_root / "voc-exclusions.jsonl").open(
            "r", encoding="utf-8"
        ) as handle:
            for line in handle:
                row = json.loads(line)
                if row.get("post_id") != EXTERNAL_REFERENCE_ID:
                    continue
                comment_id = row.get("comment_id")
                if (
                    not isinstance(comment_id, str)
                    or row.get("canonical_entity_id") != f"t1_{comment_id}"
                    or row.get("entity_type") != "comment"
                    or row.get("reason_codes") != ["unresolved_parent"]
                    or row.get("schema_version")
                    != "reddit_voc_voc_exclusion_v1"
                ):
                    raise CasebookSnapshotValidationError(
                        "evidence-only comment identity mismatch"
                    )
                comments.add(comment_id)
    except (OSError, json.JSONDecodeError) as exc:
        raise CasebookSnapshotValidationError(
            "canonical case evidence is unreadable"
        ) from exc
    if roots != set(CANONICAL_ROOT_IDS) or comments != set(
        EVIDENCE_ONLY_COMMENT_IDS
    ):
        raise CasebookSnapshotValidationError("4+16 case evidence mismatch")
    return tuple(sorted(roots)), tuple(sorted(comments))


def _canonical_governed_fact_ids(
    governed_root: Path, governed_manifest: Mapping[str, Any]
) -> tuple[tuple[str, ...], dict[str, str]]:
    expected_voc_ids = {f"post:{value}" for value in CANONICAL_ROOT_IDS}
    observed: set[str] = set()
    fact_ids: set[str] = set()
    hashes: dict[str, str] = {}
    for name in (
        "community-governance-facts.jsonl",
        "commercial-relation-facts.jsonl",
        "integrity-signal-facts.jsonl",
    ):
        hashes[name.replace(".jsonl", "_sha256")] = _upstream_file_sha(
            governed_root, governed_manifest, name
        )
        for row in _read_jsonl(governed_root / name, name):
            voc_id = row.get("voc_id")
            if voc_id in expected_voc_ids:
                observed.add(str(voc_id))
                fact_id = row.get("fact_id")
                if not isinstance(fact_id, str) or len(fact_id) != 64:
                    raise CasebookSnapshotValidationError(
                        "canonical governed fact ID is invalid"
                    )
                fact_ids.add(fact_id)
            if voc_id == f"post:{EXTERNAL_REFERENCE_ID}":
                raise CasebookSnapshotValidationError(
                    "external reference entered canonical governed facts"
                )
    if observed != expected_voc_ids or not fact_ids:
        raise CasebookSnapshotValidationError("canonical governed facts mismatch")
    return tuple(sorted(fact_ids)), hashes


def _contains_pii_key(value: object) -> bool:
    forbidden = {"author", "author_fullname", "author_pseudonym", "username"}
    if isinstance(value, Mapping):
        return bool(forbidden & set(value)) or any(
            _contains_pii_key(item) for item in value.values()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_pii_key(item) for item in value)
    return False


def validate_casebook_snapshot(
    *,
    casebook_root: Path,
    expected_manifest_sha256: str,
    reference_registry_root: Path,
    reference_receipt_path: Path,
    facts_root: Path,
    facts_receipt_path: Path,
    governed_root: Path,
    governed_receipt_path: Path,
    facts_manifest_sha256: str = FACTS_MANIFEST_SHA256,
    facts_receipt_sha256: str = FACTS_RECEIPT_SHA256,
    governed_manifest_sha256: str = GOVERNED_MANIFEST_SHA256,
    governed_receipt_sha256: str = GOVERNED_RECEIPT_SHA256,
) -> dict[str, object]:
    root = Path(casebook_root)
    if root.is_symlink() or not root.is_dir():
        raise CasebookSnapshotValidationError("casebook root is invalid")
    entries = {path.name for path in root.iterdir()}
    if entries != {"manifest.json", *OUTPUT_FILES} or any(
        path.is_symlink() or not path.is_file() for path in root.iterdir()
    ):
        raise CasebookSnapshotValidationError(
            "casebook contains missing or undeclared entries"
        )
    manifest, manifest_payload = _read_json(
        root / "manifest.json", "casebook manifest", require_canonical=True
    )
    if sha256_bytes(manifest_payload) != expected_manifest_sha256:
        raise CasebookSnapshotValidationError("casebook manifest SHA-256 mismatch")

    reference_manifest, reference_manifest_payload = _read_json(
        Path(reference_registry_root) / "manifest.json", "reference manifest"
    )
    reference_receipt, reference_receipt_payload = _read_json(
        reference_receipt_path, "reference receipt"
    )
    reference_manifest_sha = sha256_bytes(reference_manifest_payload)
    if (
        reference_receipt.get("status") != "passed"
        or reference_receipt.get("promotable") is not True
        or reference_receipt.get("consumption_status") != "eligible_for_casebook"
        or reference_receipt.get("registry_manifest_sha256")
        != reference_manifest_sha
    ):
        raise CasebookSnapshotValidationError("reference receipt mismatch")
    _upstream_file_sha(
        Path(reference_registry_root), reference_manifest, "references.jsonl"
    )
    external_snapshots_sha = _upstream_file_sha(
        Path(reference_registry_root),
        reference_manifest,
        "external-public-snapshots.jsonl",
    )
    external_snapshots = _read_jsonl(
        Path(reference_registry_root) / "external-public-snapshots.jsonl",
        "external snapshots",
    )
    references = _read_jsonl(
        Path(reference_registry_root) / "references.jsonl", "references"
    )
    if len(external_snapshots) != 1 or len(references) != 1:
        raise CasebookSnapshotValidationError("external reference count mismatch")
    external_snapshot = external_snapshots[0]
    reference = references[0]
    if (
        external_snapshot.get("reddit_post_id") != EXTERNAL_REFERENCE_ID
        or external_snapshot.get("canonical_task4_row") is not False
        or external_snapshot.get("source_role")
        != "external_public_reference_noncanonical"
        or reference.get("reference_id") != EXTERNAL_REFERENCE_ID
        or reference.get("default_eligible") is not True
        or reference.get("content_hash") != external_snapshot.get("content_hash")
    ):
        raise CasebookSnapshotValidationError("external reference boundary mismatch")

    facts_manifest, facts_manifest_payload = _read_json(
        Path(facts_root) / "manifest.json", "VOC facts manifest"
    )
    facts_receipt, facts_receipt_payload = _read_json(
        facts_receipt_path, "VOC facts receipt"
    )
    facts_manifest_sha = sha256_bytes(facts_manifest_payload)
    facts_receipt_sha = sha256_bytes(facts_receipt_payload)
    if (
        facts_manifest_sha != facts_manifest_sha256
        or facts_receipt_sha != facts_receipt_sha256
        or facts_receipt.get("status") != "passed"
        or facts_receipt.get("bundle_manifest_sha256") != facts_manifest_sha
    ):
        raise CasebookSnapshotValidationError("VOC facts lineage mismatch")
    vocs_sha = _upstream_file_sha(Path(facts_root), facts_manifest, "vocs.jsonl")
    exclusions_sha = _upstream_file_sha(
        Path(facts_root), facts_manifest, "voc-exclusions.jsonl"
    )
    root_ids, comment_ids = _canonical_roots_and_comments(Path(facts_root))

    governed_manifest, governed_manifest_payload = _read_json(
        Path(governed_root) / "manifest.json", "governed signal manifest"
    )
    governed_receipt, governed_receipt_payload = _read_json(
        governed_receipt_path, "governed signal receipt"
    )
    governed_manifest_sha = sha256_bytes(governed_manifest_payload)
    governed_receipt_sha = sha256_bytes(governed_receipt_payload)
    if (
        governed_manifest_sha != governed_manifest_sha256
        or governed_receipt_sha != governed_receipt_sha256
        or governed_receipt.get("status") != "passed"
        or governed_receipt.get("promotable") is not True
        or governed_receipt.get("snapshot_manifest_sha256")
        != governed_manifest_sha
    ):
        raise CasebookSnapshotValidationError("governed signal lineage mismatch")
    canonical_fact_ids, governed_file_hashes = _canonical_governed_fact_ids(
        Path(governed_root), governed_manifest
    )

    generated_at = manifest.get("generated_at")
    casebook_id = manifest.get("casebook_id")
    if not isinstance(generated_at, str) or not isinstance(casebook_id, str):
        raise CasebookSnapshotValidationError("casebook identity is invalid")
    try:
        generated = datetime.fromisoformat(generated_at)
    except ValueError as exc:
        raise CasebookSnapshotValidationError("casebook generation time is invalid") from exc
    if generated.tzinfo is None or generated.utcoffset() != timedelta(0):
        raise CasebookSnapshotValidationError("casebook generation time must be UTC")
    external_source_snapshot_id = f"case-reference-registry:{reference_manifest_sha}"
    expected_external_fact_objects = build_external_reference_atomic_facts(
        external_snapshot,
        source_snapshot_id=external_source_snapshot_id,
        created_at=generated_at,
    )
    expected_external_facts = tuple(
        row.as_dict() for row in expected_external_fact_objects
    )
    evidence_binding = {
        "canonical_governed_fact_ids": list(canonical_fact_ids),
        "canonical_root_ids": list(root_ids),
        "evidence_only_comment_ids": list(comment_ids),
        "external_governance_fact_ids": [
            row["fact_id"] for row in expected_external_facts
        ],
        "external_reference_content_hash": external_snapshot["content_hash"],
        "external_reference_id": EXTERNAL_REFERENCE_ID,
        "external_snapshot_id": external_snapshot["snapshot_id"],
    }
    evidence_snapshot_sha = sha256_bytes(canonical_json_bytes(evidence_binding))
    expected_dossier = build_momcozy_governance_dossier(
        canonical_root_ids=CANONICAL_ROOT_IDS,
        external_reference_id=EXTERNAL_REFERENCE_ID,
        evidence_only_comment_ids=comment_ids,
        insight_ref="storyline:community_trust_non_organic_promotion",
        snapshot_sha256=evidence_snapshot_sha,
        created_at=generated_at,
        review_due_at=(generated + timedelta(days=14)).isoformat(timespec="seconds"),
    ).as_dict()
    expected_event = {
        "assertion_status": "subreddit_moderator_public_allegation",
        "brand_control_confirmed": False,
        "canonical_root_ids": list(root_ids),
        "case_id": expected_dossier["case_id"],
        "commercial_relation": "C2",
        "evidence_only_comment_ids": list(comment_ids),
        "evidence_snapshot_sha256": evidence_snapshot_sha,
        "external_reference_id": EXTERNAL_REFERENCE_ID,
        "governance_authority": "subreddit_moderator",
        "integrity_level": "I3",
        "publication_boundary": "risk_observation_not_brand_attribution",
        "schema_version": EVENT_SCHEMA,
    }
    expected_counts = {
        "action_monitoring_rows": 0,
        "canonical_governance_fact_refs": len(canonical_fact_ids),
        "canonical_roots": 4,
        "case_dossiers": 1,
        "event_assessments": 1,
        "evidence_only_comments": 16,
        "external_governance_facts": 3,
        "external_references": 1,
    }
    expected_inputs = {
        "external_public_snapshots_sha256": external_snapshots_sha,
        "facts_manifest_sha256": facts_manifest_sha,
        "facts_receipt_sha256": facts_receipt_sha,
        "governed_manifest_sha256": governed_manifest_sha,
        "governed_receipt_sha256": governed_receipt_sha,
        "reference_registry_manifest_sha256": reference_manifest_sha,
        "reference_registry_receipt_sha256": sha256_bytes(
            reference_receipt_payload
        ),
        "voc_exclusions_sha256": exclusions_sha,
        "vocs_sha256": vocs_sha,
        **governed_file_hashes,
    }
    files = manifest.get("files")
    if (
        manifest.get("schema_version") != MANIFEST_SCHEMA
        or manifest.get("status") != "candidate_built"
        or manifest.get("consumption_status")
        != "candidate_pending_independent_validation"
        or manifest.get("promotable") is not False
        or manifest.get("boundaries") != BOUNDARIES
        or manifest.get("lifecycle_status") != "review_required"
        or manifest.get("actions_display_mode") != "suggestion_only"
        or manifest.get("counts") != expected_counts
        or manifest.get("evidence_accounting")
        != {
            "canonical_roots": 4,
            "evidence_only_comments": 16,
            "external_references": 1,
            "unaccounted": 0,
        }
        or manifest.get("evidence_snapshot_sha256") != evidence_snapshot_sha
        or manifest.get("inputs") != expected_inputs
        or manifest.get("source_snapshot_id")
        != governed_manifest.get("source_snapshot_id")
        or not isinstance(files, Mapping)
        or set(files) != set(OUTPUT_FILES)
    ):
        raise CasebookSnapshotValidationError("casebook manifest semantic mismatch")

    observed_dossiers = _read_jsonl(
        root / "case-dossiers.jsonl", "case dossiers", require_canonical=True
    )
    observed_events = _read_jsonl(
        root / "event-assessments.jsonl", "event assessments", require_canonical=True
    )
    observed_external_facts = _read_jsonl(
        root / "external-governance-facts.jsonl",
        "external governance facts",
        require_canonical=True,
    )
    observed_actions = _read_jsonl(
        root / "action-monitoring-ledger.jsonl",
        "action monitoring ledger",
        require_canonical=True,
    )
    if (
        observed_dossiers != (expected_dossier,)
        or observed_events != (expected_event,)
        or observed_external_facts != expected_external_facts
        or observed_actions
    ):
        raise CasebookSnapshotValidationError("casebook full-byte replay mismatch")
    if any(
        _contains_pii_key(value)
        for value in (
            observed_dossiers,
            observed_events,
            observed_external_facts,
            observed_actions,
        )
    ):
        raise CasebookSnapshotValidationError("casebook contains prohibited PII keys")
    for name in OUTPUT_FILES:
        payload = (root / name).read_bytes()
        if files.get(name) != _file_contract(payload):
            raise CasebookSnapshotValidationError(f"{name} file contract mismatch")
    return {
        "boundaries": dict(BOUNDARIES),
        "casebook_manifest_sha256": expected_manifest_sha256,
        "consumption_status": "eligible_for_private_casebook_review",
        "counts": expected_counts,
        "evidence_accounting": {
            "canonical_roots": 4,
            "evidence_only_comments": 16,
            "external_references": 1,
            "unaccounted": 0,
        },
        "full_byte_independent_replay": True,
        "lifecycle_status": "review_required",
        "promotable": True,
        "schema_version": RECEIPT_SCHEMA,
        "status": "passed",
    }
