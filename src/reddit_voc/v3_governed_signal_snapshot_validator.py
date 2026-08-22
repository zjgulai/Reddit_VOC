"""Independent validation for the private V3 eight-table signal snapshot.

This module does not import the snapshot writer or closed-set matcher.  It
reopens every declared file, independently reproduces the closed-set phrase
inventory and replays the frozen governance rules before issuing a receipt.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
from typing import Any, Mapping

from reddit_voc.v3_atomic_facts import (
    AtomicFact,
    governance_regression_coverage,
    validate_atomic_facts,
)
from reddit_voc.v3_closed_set_facts_validator import validate_closed_set_facts
from reddit_voc.v3_governed_signal_inputs import (
    EXPECTED_BOUNDARIES,
    GovernedSignalInputs,
    canonical_json_bytes,
    sha256_bytes,
)


SNAPSHOT_SCHEMA_VERSION = "reddit_voc_governed_signal_snapshot_v1"
RECEIPT_SCHEMA_VERSION = "reddit_voc_governed_signal_validation_receipt_v1"
FACT_TABLE_FILES = {
    "entity_brand_fact": "entity-brand-facts.jsonl",
    "entity_product_fact": "entity-product-facts.jsonl",
    "entity_sentiment_fact": "entity-sentiment-facts.jsonl",
    "entity_problem_fact": "entity-problem-facts.jsonl",
    "entity_tag_fact": "entity-tag-facts.jsonl",
    "community_governance_fact": "community-governance-facts.jsonl",
    "commercial_relation_fact": "commercial-relation-facts.jsonl",
    "integrity_signal_fact": "integrity-signal-facts.jsonl",
}
CLOSED_SET_TYPES = frozenset(tuple(FACT_TABLE_FILES)[:5])
FIXED_GOVERNANCE_TYPES = frozenset(tuple(FACT_TABLE_FILES)[5:])
FACT_KEYS = {
    "attributes",
    "canonical_entity_id",
    "canonical_value",
    "context_evidence_refs",
    "created_at",
    "decision_status",
    "dictionary_release_id",
    "evidence_end",
    "evidence_field",
    "evidence_scope",
    "evidence_source_entity_id",
    "evidence_start",
    "evidence_text_sha256",
    "fact_id",
    "fact_type",
    "matcher_version",
    "normalizer_version",
    "reason_codes",
    "schema_version",
    "source_snapshot_id",
    "voc_id",
    "voc_type",
}


class GovernedSignalValidationError(ValueError):
    """The governed-signal snapshot fails independent validation."""


def _read_regular(path: Path, *, label: str) -> bytes:
    path = Path(path)
    try:
        if path.is_symlink() or not path.is_file():
            raise GovernedSignalValidationError(f"{label} must be a regular file")
        return path.read_bytes()
    except OSError as exc:
        raise GovernedSignalValidationError(f"{label} is unreadable") from exc


def _read_manifest(path: Path) -> tuple[dict[str, Any], bytes]:
    payload = _read_regular(path, label="signal manifest")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GovernedSignalValidationError("signal manifest JSON is invalid") from exc
    if (
        not isinstance(value, dict)
        or payload != canonical_json_bytes(value) + b"\n"
    ):
        raise GovernedSignalValidationError("signal manifest is not canonical")
    return value, payload


def _read_fact_table(
    path: Path,
    *,
    fact_type: str,
    contract: object,
) -> tuple[dict[str, Any], ...]:
    payload = _read_regular(path, label=path.name)
    if (
        not isinstance(contract, Mapping)
        or set(contract) != {"bytes", "rows", "sha256"}
        or type(contract.get("bytes")) is not int
        or type(contract.get("rows")) is not int
        or contract["bytes"] < 0
        or contract["rows"] < 0
        or contract.get("bytes") != len(payload)
        or contract.get("sha256") != sha256_bytes(payload)
    ):
        raise GovernedSignalValidationError(f"{path.name} file contract mismatch")
    rows: list[dict[str, Any]] = []
    for ordinal, line in enumerate(payload.splitlines(), start=1):
        if not line:
            raise GovernedSignalValidationError(f"{path.name} has a blank row")
        try:
            row = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GovernedSignalValidationError(
                f"{path.name} row {ordinal} is invalid"
            ) from exc
        if (
            not isinstance(row, dict)
            or set(row) != FACT_KEYS
            or row.get("fact_type") != fact_type
            or line != canonical_json_bytes(row)
        ):
            raise GovernedSignalValidationError(
                f"{path.name} row {ordinal} is not canonical or partitioned"
            )
        rows.append(row)
    if payload and not payload.endswith(b"\n"):
        raise GovernedSignalValidationError(f"{path.name} lacks final newline")
    if len(rows) != contract["rows"]:
        raise GovernedSignalValidationError(f"{path.name} row count mismatch")
    return tuple(rows)


def _atomic_fact(row: Mapping[str, Any]) -> AtomicFact:
    attributes = row.get("attributes")
    context_refs = row.get("context_evidence_refs")
    reasons = row.get("reason_codes")
    if (
        not isinstance(attributes, dict)
        or not isinstance(context_refs, list)
        or any(not isinstance(value, str) for value in context_refs)
        or not isinstance(reasons, list)
        or any(not isinstance(value, str) for value in reasons)
    ):
        raise GovernedSignalValidationError("fixed fact collection shape is invalid")
    try:
        return AtomicFact(
            fact_id=row["fact_id"],
            canonical_entity_id=row["canonical_entity_id"],
            voc_id=row["voc_id"],
            voc_type=row["voc_type"],
            fact_type=row["fact_type"],
            canonical_value=row["canonical_value"],
            attributes=dict(attributes),
            evidence_field=row["evidence_field"],
            evidence_start=row["evidence_start"],
            evidence_end=row["evidence_end"],
            evidence_text_sha256=row["evidence_text_sha256"],
            evidence_scope=row["evidence_scope"],
            evidence_source_entity_id=row["evidence_source_entity_id"],
            context_evidence_refs=tuple(context_refs),
            decision_status=row["decision_status"],
            reason_codes=tuple(reasons),
            dictionary_release_id=row["dictionary_release_id"],
            matcher_version=row["matcher_version"],
            normalizer_version=row["normalizer_version"],
            source_snapshot_id=row["source_snapshot_id"],
            created_at=row["created_at"],
            schema_version=row["schema_version"],
        )
    except (KeyError, TypeError) as exc:
        raise GovernedSignalValidationError("fixed fact is malformed") from exc


def validate_governed_signal_snapshot(
    *,
    snapshot_root: Path,
    inputs: GovernedSignalInputs,
    dim_tag_path: Path,
    product_entity_ledger_path: Path,
    registry_path: Path,
) -> dict[str, object]:
    snapshot_root = Path(snapshot_root)
    if snapshot_root.is_symlink() or not snapshot_root.is_dir():
        raise GovernedSignalValidationError(
            "signal snapshot root must be a regular directory"
        )
    expected_names = {"manifest.json", *FACT_TABLE_FILES.values()}
    observed_names = {path.name for path in snapshot_root.iterdir()}
    if observed_names != expected_names:
        raise GovernedSignalValidationError(
            "signal snapshot contains missing or undeclared entries"
        )
    manifest, manifest_payload = _read_manifest(snapshot_root / "manifest.json")
    expected_manifest_keys = {
        "boundaries",
        "consumption_status",
        "counts",
        "created_at",
        "files",
        "governance_regression_coverage",
        "independent_validation_status",
        "inputs",
        "promotable",
        "schema_version",
        "snapshot_id",
        "source_snapshot_id",
        "status",
        "table_rows",
        "tables",
    }
    if (
        set(manifest) != expected_manifest_keys
        or manifest.get("schema_version") != SNAPSHOT_SCHEMA_VERSION
        or manifest.get("status") != "candidate_built"
        or manifest.get("consumption_status")
        != "blocked_pending_independent_validation"
        or manifest.get("independent_validation_status") != "pending"
        or manifest.get("promotable") is not False
        or manifest.get("boundaries") != EXPECTED_BOUNDARIES
        or manifest.get("inputs") != inputs.input_bindings
        or manifest.get("source_snapshot_id") != inputs.source_snapshot_id
        or not isinstance(manifest.get("snapshot_id"), str)
        or not manifest.get("snapshot_id")
        or not isinstance(manifest.get("created_at"), str)
        or not manifest.get("created_at")
    ):
        raise GovernedSignalValidationError("signal manifest lifecycle is invalid")
    expected_tables = [
        {
            "fact_type": fact_type,
            "filename": filename,
            "scope": (
                "full_corpus_closed_set"
                if fact_type in CLOSED_SET_TYPES
                else "fixed_governance_regression"
            ),
        }
        for fact_type, filename in FACT_TABLE_FILES.items()
    ]
    if manifest.get("tables") != expected_tables:
        raise GovernedSignalValidationError("signal table contract is invalid")
    files = manifest.get("files")
    table_rows_manifest = manifest.get("table_rows")
    if (
        not isinstance(files, Mapping)
        or set(files) != set(FACT_TABLE_FILES.values())
        or not isinstance(table_rows_manifest, Mapping)
        or set(table_rows_manifest) != set(FACT_TABLE_FILES)
    ):
        raise GovernedSignalValidationError("signal file inventory is invalid")

    facts_by_type: dict[str, tuple[dict[str, Any], ...]] = {}
    seen_fact_ids: set[str] = set()
    status_counts = {"held": 0, "promoted": 0, "rejected": 0}
    for fact_type, filename in FACT_TABLE_FILES.items():
        rows = _read_fact_table(
            snapshot_root / filename,
            fact_type=fact_type,
            contract=files[filename],
        )
        if table_rows_manifest.get(fact_type) != len(rows):
            raise GovernedSignalValidationError("signal table row count mismatch")
        for row in rows:
            fact_id = row.get("fact_id")
            voc_id = row.get("voc_id")
            status = row.get("decision_status")
            if (
                not isinstance(fact_id, str)
                or fact_id in seen_fact_ids
                or voc_id in inputs.automation_voc_ids
                or status not in status_counts
            ):
                raise GovernedSignalValidationError(
                    "signal fact identity, status, or automation boundary is invalid"
                )
            seen_fact_ids.add(fact_id)
            status_counts[str(status)] += 1
        facts_by_type[fact_type] = rows

    organic_vocs = inputs.organic_vocs
    by_voc = {str(row["voc_id"]): row for row in organic_vocs}
    closed_rows = tuple(
        row
        for fact_type in FACT_TABLE_FILES
        if fact_type in CLOSED_SET_TYPES
        for row in facts_by_type[fact_type]
    )
    fixed_rows = tuple(
        row
        for fact_type in FACT_TABLE_FILES
        if fact_type in FIXED_GOVERNANCE_TYPES
        for row in facts_by_type[fact_type]
    )
    closed_result = validate_closed_set_facts(
        closed_rows,
        organic_vocs,
        dim_tag_path=dim_tag_path,
        product_entity_ledger_path=product_entity_ledger_path,
        registry_path=registry_path,
        source_snapshot_id=inputs.source_snapshot_id,
        created_at=str(manifest["created_at"]),
    )
    validate_atomic_facts(
        tuple(_atomic_fact(row) for row in fixed_rows),
        by_voc,
        source_snapshot_id=inputs.source_snapshot_id,
        created_at=str(manifest["created_at"]),
    )
    expected_coverage = governance_regression_coverage(organic_vocs)
    counts = manifest.get("counts")
    expected_counts = {
        "automation_excluded_vocs": len(inputs.automation_voc_ids),
        "fact_rows": len(seen_fact_ids),
        "held_facts": status_counts["held"],
        "organic_vocs": len(organic_vocs),
        "promoted_facts": status_counts["promoted"],
        "rejected_facts": status_counts["rejected"],
        "total_vocs": len(inputs.vocs),
    }
    if (
        counts != expected_counts
        or manifest.get("governance_regression_coverage") != expected_coverage
        or closed_result.get("fact_rows") != len(closed_rows)
        or closed_result.get("unaccounted_fact_keys") != 0
        or len(closed_rows) + len(fixed_rows) != len(seen_fact_ids)
    ):
        raise GovernedSignalValidationError(
            "signal snapshot conservation or replay mismatch"
        )
    return {
        "boundaries": dict(EXPECTED_BOUNDARIES),
        "closed_set_replay": {
            "fact_rows": len(closed_rows),
            "held_rows": closed_result["held_rows"],
            "promoted_rows": closed_result["promoted_rows"],
            "unaccounted_fact_keys": 0,
        },
        "consumption_status": "eligible_for_downstream_consumption",
        "counts": expected_counts,
        "fixed_governance_replay": {
            "fact_rows": len(fixed_rows),
            "unaccounted_fact_keys": 0,
        },
        "inputs": dict(inputs.input_bindings),
        "promotable": True,
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "snapshot_manifest_sha256": sha256_bytes(manifest_payload),
        "snapshot_id": manifest["snapshot_id"],
        "source_snapshot_id": inputs.source_snapshot_id,
        "status": "passed",
        "unaccounted_facts": 0,
        "unaccounted_vocs": 0,
        "validated_tables": 8,
    }


def write_governed_signal_validation_receipt(
    receipt: Mapping[str, object],
    output_root: Path,
) -> str:
    output_root = Path(output_root)
    if output_root.exists() or output_root.is_symlink():
        raise GovernedSignalValidationError("validation output root already exists")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging = output_root.parent / f".{output_root.name}.building"
    if staging.exists() or staging.is_symlink():
        raise GovernedSignalValidationError("validation staging root already exists")
    staging.mkdir()
    try:
        payload = canonical_json_bytes(dict(receipt)) + b"\n"
        (staging / "receipt.json").write_bytes(payload)
        staging.rename(output_root)
        return sha256(payload).hexdigest()
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
