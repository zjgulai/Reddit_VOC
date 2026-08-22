"""Build the private eight-table Reddit VOC V3 governed-signal snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import shutil
from typing import Any, Iterable, Mapping

from reddit_voc.v3_atomic_facts import (
    build_atomic_facts,
    canonical_json_bytes as canonical_atomic_json_bytes,
    governance_regression_coverage,
)
from reddit_voc.v3_closed_set_facts import (
    ClosedSetResources,
    build_closed_set_facts,
    canonical_json_bytes as canonical_closed_json_bytes,
)
from reddit_voc.v3_governed_signal_inputs import EXPECTED_BOUNDARIES, sha256_bytes


SNAPSHOT_SCHEMA_VERSION = "reddit_voc_governed_signal_snapshot_v1"
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
DECISION_STATUSES = ("held", "promoted", "rejected")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class GovernedSignalSnapshotError(ValueError):
    """The governed-signal snapshot cannot be materialized safely."""


@dataclass(frozen=True)
class GovernedSignalSnapshotSummary:
    output_root: Path
    manifest_sha256: str
    total_vocs: int
    automation_excluded_vocs: int
    organic_vocs: int
    fact_rows: int


def _created_at(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise GovernedSignalSnapshotError("created at must be a string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GovernedSignalSnapshotError("created at must be ISO-8601") from exc
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() != timedelta(0)
        or parsed.microsecond != 0
        or value != parsed.isoformat(timespec="seconds")
    ):
        raise GovernedSignalSnapshotError(
            "created at must be canonical UTC seconds"
        )
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise GovernedSignalSnapshotError(f"{label} must be a non-empty string")
    return value


def _vocs(value: Iterable[object]) -> tuple[Mapping[str, Any], ...]:
    result: dict[str, Mapping[str, Any]] = {}
    for raw in value:
        if hasattr(raw, "as_dict"):
            raw = raw.as_dict()
        if not isinstance(raw, Mapping):
            raise GovernedSignalSnapshotError("VOC must be an object")
        voc_id = raw.get("voc_id")
        if not isinstance(voc_id, str) or not voc_id or voc_id in result:
            raise GovernedSignalSnapshotError("VOC identity is invalid or duplicate")
        result[voc_id] = raw
    return tuple(result[key] for key in sorted(result))


def _bindings(value: Mapping[str, object]) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise GovernedSignalSnapshotError("input bindings are invalid")
    result: dict[str, str] = {}
    for key, digest in value.items():
        if (
            not isinstance(key, str)
            or not key.endswith("_sha256")
            or not isinstance(digest, str)
            or SHA256_PATTERN.fullmatch(digest) is None
        ):
            raise GovernedSignalSnapshotError("input binding is invalid")
        result[key] = digest
    return dict(sorted(result.items()))


def _file_contract(path: Path, rows: int) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "bytes": len(payload),
        "rows": rows,
        "sha256": sha256_bytes(payload),
    }


def write_governed_signal_snapshot(
    *,
    vocs: Iterable[object],
    automation_voc_ids: Iterable[str],
    resources: ClosedSetResources,
    input_bindings: Mapping[str, object],
    source_snapshot_id: str,
    snapshot_id: str,
    created_at: str,
    output_root: Path,
) -> GovernedSignalSnapshotSummary:
    """Write eight fact tables after removing explicit automation VOCs."""
    rows = _vocs(vocs)
    all_voc_ids = {str(row["voc_id"]) for row in rows}
    automation = frozenset(automation_voc_ids)
    if (
        any(not isinstance(value, str) or not value for value in automation)
        or not automation <= all_voc_ids
    ):
        raise GovernedSignalSnapshotError(
            "automation exclusion set is invalid or not VOC-bound"
        )
    source_snapshot_id = _string(source_snapshot_id, "source snapshot ID")
    snapshot_id = _string(snapshot_id, "snapshot ID")
    created_at = _created_at(created_at)
    bindings = _bindings(input_bindings)
    output_root = Path(output_root)
    if output_root.exists() or output_root.is_symlink():
        raise GovernedSignalSnapshotError("output root already exists")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging = output_root.parent / f".{output_root.name}.building"
    if staging.exists() or staging.is_symlink():
        raise GovernedSignalSnapshotError("staging root already exists")
    staging.mkdir()

    table_rows = {fact_type: 0 for fact_type in FACT_TABLE_FILES}
    status_counts = {status: 0 for status in DECISION_STATUSES}
    seen_fact_ids: set[str] = set()
    organic_vocs = 0
    handles: dict[str, Any] = {}
    try:
        for fact_type, filename in FACT_TABLE_FILES.items():
            handles[fact_type] = (staging / filename).open("wb")
        for row in rows:
            voc_id = str(row["voc_id"])
            if voc_id in automation:
                continue
            organic_vocs += 1
            closed_facts = build_closed_set_facts(
                row,
                resources=resources,
                source_snapshot_id=source_snapshot_id,
                created_at=created_at,
            )
            fixed_facts = build_atomic_facts(
                row,
                source_snapshot_id=source_snapshot_id,
                created_at=created_at,
            )
            for fact in (*closed_facts, *fixed_facts):
                if fact.fact_type not in FACT_TABLE_FILES:
                    raise GovernedSignalSnapshotError(
                        "unexpected governed signal fact type"
                    )
                if fact.fact_id in seen_fact_ids:
                    raise GovernedSignalSnapshotError("duplicate governed fact ID")
                if fact.voc_id in automation:
                    raise GovernedSignalSnapshotError(
                        "automation VOC reached governed facts"
                    )
                seen_fact_ids.add(fact.fact_id)
                document = fact.as_dict()
                canonical = (
                    canonical_closed_json_bytes(document)
                    if fact.fact_type in CLOSED_SET_TYPES
                    else canonical_atomic_json_bytes(document)
                )
                handles[fact.fact_type].write(canonical + b"\n")
                table_rows[fact.fact_type] += 1
                status = str(document["decision_status"])
                if status not in status_counts:
                    raise GovernedSignalSnapshotError(
                        "unexpected governed fact decision status"
                    )
                status_counts[status] += 1
        for handle in handles.values():
            handle.close()
        handles.clear()

        coverage = governance_regression_coverage(
            row for row in rows if row["voc_id"] not in automation
        )
        files = {
            filename: _file_contract(staging / filename, table_rows[fact_type])
            for fact_type, filename in FACT_TABLE_FILES.items()
        }
        manifest = {
            "boundaries": dict(EXPECTED_BOUNDARIES),
            "consumption_status": "blocked_pending_independent_validation",
            "counts": {
                "automation_excluded_vocs": len(automation),
                "fact_rows": sum(table_rows.values()),
                "held_facts": status_counts["held"],
                "organic_vocs": organic_vocs,
                "promoted_facts": status_counts["promoted"],
                "rejected_facts": status_counts["rejected"],
                "total_vocs": len(rows),
            },
            "created_at": created_at,
            "files": files,
            "governance_regression_coverage": coverage,
            "independent_validation_status": "pending",
            "inputs": bindings,
            "promotable": False,
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "snapshot_id": snapshot_id,
            "source_snapshot_id": source_snapshot_id,
            "status": "candidate_built",
            "table_rows": dict(sorted(table_rows.items())),
            "tables": [
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
            ],
        }
        manifest_payload = canonical_atomic_json_bytes(manifest) + b"\n"
        (staging / "manifest.json").write_bytes(manifest_payload)
        staging.rename(output_root)
        return GovernedSignalSnapshotSummary(
            output_root=output_root,
            manifest_sha256=sha256_bytes(manifest_payload),
            total_vocs=len(rows),
            automation_excluded_vocs=len(automation),
            organic_vocs=organic_vocs,
            fact_rows=len(seen_fact_ids),
        )
    except Exception:
        for handle in handles.values():
            try:
                handle.close()
            except OSError:
                pass
        if staging.exists():
            shutil.rmtree(staging)
        raise
