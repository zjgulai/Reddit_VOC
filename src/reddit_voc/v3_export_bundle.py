"""Atomic four-artifact Reddit VOC V3 export bundle builder."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import stat
from typing import Any, Iterable, Iterator, Mapping, Sequence


MANIFEST_SCHEMA = "reddit_voc_export_bundle_manifest_v1"
RECEIPT_SCHEMA = "reddit_voc_export_bundle_validation_receipt_v1"
ARTIFACT_FILES = (
    "reddit-entities-full.jsonl",
    "reddit-voc-facts.jsonl",
    "reddit-metrics-reporting.jsonl",
    "reddit-governance-casebook.jsonl",
)
ROW_SCHEMAS = {
    "reddit-entities-full.jsonl": "reddit_voc_export_entity_v1",
    "reddit-voc-facts.jsonl": "reddit_voc_export_voc_fact_v1",
    "reddit-metrics-reporting.jsonl": "reddit_voc_export_metric_reporting_v1",
    "reddit-governance-casebook.jsonl": "reddit_voc_export_governance_case_v1",
}
PRIMARY_KEYS = {
    "reddit-entities-full.jsonl": "entity_id",
    "reddit-voc-facts.jsonl": "record_id",
    "reddit-metrics-reporting.jsonl": "metric_record_id",
    "reddit-governance-casebook.jsonl": "case_record_id",
}
BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}
PUBLIC_DENIED_FIELDS = frozenset(
    {
        "author",
        "author_name",
        "author_pseudonym",
        "internal_notes",
        "pii",
        "private_pseudonym",
        "reviewer_id",
    }
)
SHA256_RE = re.compile(r"[0-9a-f]{64}")
RELEASE_RE = re.compile(r"reddit_voc_release_[a-z0-9][a-z0-9_-]{2,127}")


class ExportBundleError(ValueError):
    """The export bundle would violate atomicity or privacy boundaries."""


@dataclass(frozen=True)
class ExportBundleMetadata:
    export_bundle_id: str
    release_id: str
    source_snapshot_id: str
    source_cutoff_value: str
    source_cutoff_precision: str
    source_timezone_status: str
    dictionary_sha256: str
    indicator_registry_sha256: str
    eligibility_policy_sha256: str
    builder_code_sha256: str
    validator_code_sha256: str
    candidate_release_sha256: str
    bundle_mode: str


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
        raise ExportBundleError("value is not canonical JSON serializable") from exc


def canonical_json_document(value: object) -> bytes:
    return canonical_json_bytes(value) + b"\n"


def canonical_jsonl(rows: Iterable[Mapping[str, object]]) -> bytes:
    return b"".join(canonical_json_document(dict(row)) for row in rows)


def sha256_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _require_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise ExportBundleError(f"{label} is invalid")
    return value


def _validate_metadata(metadata: ExportBundleMetadata) -> None:
    if (
        not isinstance(metadata.export_bundle_id, str)
        or not metadata.export_bundle_id
        or not isinstance(metadata.release_id, str)
        or RELEASE_RE.fullmatch(metadata.release_id) is None
        or not isinstance(metadata.source_snapshot_id, str)
        or not metadata.source_snapshot_id
        or not isinstance(metadata.source_cutoff_value, str)
        or not metadata.source_cutoff_value
        or metadata.source_cutoff_precision not in {"instant", "hour", "day"}
        or metadata.source_timezone_status
        not in {"known", "known_from_aware_instant", "unknown_floating_date"}
        or metadata.bundle_mode not in {"public", "private_audit"}
    ):
        raise ExportBundleError("export bundle metadata is invalid")
    for label in (
        "dictionary_sha256",
        "indicator_registry_sha256",
        "eligibility_policy_sha256",
        "builder_code_sha256",
        "validator_code_sha256",
        "candidate_release_sha256",
    ):
        _require_sha(getattr(metadata, label), label)


def _denied_field(value: object) -> str | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in PUBLIC_DENIED_FIELDS:
                return str(key)
            nested = _denied_field(item)
            if nested is not None:
                return nested
    elif isinstance(value, list):
        for item in value:
            nested = _denied_field(item)
            if nested is not None:
                return nested
    return None


def _reference_list(row: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = row.get(key, [])
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item for item in value)
        or value != sorted(set(value))
    ):
        raise ExportBundleError(f"{key} must be a sorted unique string list")
    return tuple(value)


def validate_rows(
    rows_by_file: Mapping[str, Sequence[Mapping[str, Any]]],
    metadata: ExportBundleMetadata,
) -> dict[str, int]:
    _validate_metadata(metadata)
    if set(rows_by_file) != set(ARTIFACT_FILES):
        raise ExportBundleError("export artifact member set is invalid")
    primary_sets: dict[str, set[str]] = {}
    normalized: dict[str, tuple[Mapping[str, Any], ...]] = {}
    for name in ARTIFACT_FILES:
        rows = tuple(rows_by_file[name])
        if not rows:
            raise ExportBundleError(f"{name} must not be empty")
        primary_key = PRIMARY_KEYS[name]
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, Mapping):
                raise ExportBundleError(f"{name} contains a non-object row")
            if (
                row.get("schema_version") != ROW_SCHEMAS[name]
                or row.get("export_bundle_id") != metadata.export_bundle_id
                or row.get("release_id") != metadata.release_id
                or row.get("source_snapshot_id") != metadata.source_snapshot_id
            ):
                raise ExportBundleError(f"{name} release or snapshot identity mismatch")
            primary = row.get(primary_key)
            if not isinstance(primary, str) or not primary or primary in seen:
                raise ExportBundleError(f"{name} primary identity is invalid")
            seen.add(primary)
            _reference_list(row, "entity_refs")
            _reference_list(row, "fact_refs")
            if name == "reddit-voc-facts.jsonl":
                kind = row.get("record_kind")
                if kind == "fact":
                    if not isinstance(row.get("fact_id"), str) or not row["fact_id"]:
                        raise ExportBundleError("fact export row lacks fact_id")
                elif kind == "voc":
                    if not isinstance(row.get("voc_id"), str) or not row["voc_id"]:
                        raise ExportBundleError("VOC export row lacks voc_id")
                else:
                    raise ExportBundleError("VOC/fact record kind is invalid")
            if metadata.bundle_mode == "public":
                denied = _denied_field(row)
                if denied is not None:
                    raise ExportBundleError(f"public bundle contains denied field: {denied}")
            canonical_json_bytes(row)
        primary_sets[name] = seen
        normalized[name] = rows

    entity_ids = primary_sets["reddit-entities-full.jsonl"]
    fact_ids = {
        str(row["fact_id"])
        for row in normalized["reddit-voc-facts.jsonl"]
        if row.get("record_kind") == "fact"
        and isinstance(row.get("fact_id"), str)
        and row.get("fact_id")
    }
    unresolved_entities = 0
    unresolved_facts = 0
    entity_reference_count = 0
    fact_reference_count = 0
    for name in ARTIFACT_FILES[1:]:
        for row in normalized[name]:
            entity_refs = _reference_list(row, "entity_refs")
            fact_refs = _reference_list(row, "fact_refs")
            entity_reference_count += len(entity_refs)
            fact_reference_count += len(fact_refs)
            unresolved_entities += sum(ref not in entity_ids for ref in entity_refs)
            unresolved_facts += sum(ref not in fact_ids for ref in fact_refs)
    if unresolved_entities:
        raise ExportBundleError("unresolved entity references")
    if unresolved_facts:
        raise ExportBundleError("unresolved fact references")
    return {
        "entity_reference_count": entity_reference_count,
        "entity_rows": len(normalized["reddit-entities-full.jsonl"]),
        "fact_rows": sum(
            row.get("record_kind") == "fact"
            for row in normalized["reddit-voc-facts.jsonl"]
        ),
        "fact_reference_count": fact_reference_count,
        "governance_case_rows": len(
            normalized["reddit-governance-casebook.jsonl"]
        ),
        "metric_reporting_rows": len(
            normalized["reddit-metrics-reporting.jsonl"]
        ),
        "resolved_entity_references": entity_reference_count,
        "resolved_fact_references": fact_reference_count,
        "unresolved_entity_references": 0,
        "unresolved_fact_references": 0,
        "voc_rows": sum(
            row.get("record_kind") == "voc"
            for row in normalized["reddit-voc-facts.jsonl"]
        ),
    }


def _file_contract(name: str, payload: bytes) -> dict[str, object]:
    return {
        "byte_count": len(payload),
        "path": name,
        "row_count": len(payload.splitlines()),
        "sha256": sha256_bytes(payload),
    }


def _manifest_from_contracts(
    *,
    contracts: Sequence[Mapping[str, object]],
    cross_reference_counts: Mapping[str, int],
    metadata: ExportBundleMetadata,
    materialization: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "artifacts": [dict(contract) for contract in contracts],
        "boundaries": dict(BOUNDARIES),
        "builder_code_sha256": metadata.builder_code_sha256,
        "bundle_mode": metadata.bundle_mode,
        "candidate_release_sha256": metadata.candidate_release_sha256,
        "consumption_status": "candidate_pending_independent_validation",
        "cross_reference_counts": dict(cross_reference_counts),
        "dictionary_sha256": metadata.dictionary_sha256,
        "eligibility_policy_sha256": metadata.eligibility_policy_sha256,
        "export_bundle_id": metadata.export_bundle_id,
        "indicator_registry_sha256": metadata.indicator_registry_sha256,
        "promotable": False,
        "release_id": metadata.release_id,
        "schema_version": MANIFEST_SCHEMA,
        "source_cutoff_precision": metadata.source_cutoff_precision,
        "source_cutoff_value": metadata.source_cutoff_value,
        "source_snapshot_id": metadata.source_snapshot_id,
        "source_timezone_status": metadata.source_timezone_status,
        "status": "candidate_built",
        "validation_receipt_sha256": None,
        "validator_code_sha256": metadata.validator_code_sha256,
    }
    if materialization is not None:
        canonical_json_bytes(materialization)
        manifest["materialization"] = dict(materialization)
    return manifest


def build_manifest(
    rows_by_file: Mapping[str, Sequence[Mapping[str, Any]]],
    metadata: ExportBundleMetadata,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    cross_reference_counts = validate_rows(rows_by_file, metadata)
    payloads = {
        name: canonical_jsonl(rows_by_file[name]) for name in ARTIFACT_FILES
    }
    manifest = _manifest_from_contracts(
        contracts=[_file_contract(name, payloads[name]) for name in ARTIFACT_FILES],
        cross_reference_counts=cross_reference_counts,
        metadata=metadata,
    )
    return manifest, payloads


def _write_file(path: Path, payload: bytes, mode: int) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, mode)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise
    os.chmod(path, mode)


def write_export_bundle(
    output_root: Path,
    rows_by_file: Mapping[str, Sequence[Mapping[str, Any]]],
    metadata: ExportBundleMetadata,
) -> dict[str, Any]:
    output_root = Path(output_root)
    if output_root.exists() or output_root.is_symlink():
        raise ExportBundleError("export bundle output root already exists")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging = output_root.parent / f".{output_root.name}.building"
    if staging.exists() or staging.is_symlink():
        raise ExportBundleError("export bundle staging root already exists")
    manifest, payloads = build_manifest(rows_by_file, metadata)
    os.mkdir(staging, 0o700)
    try:
        for name in ARTIFACT_FILES:
            _write_file(staging / name, payloads[name], 0o600)
        _write_file(staging / "manifest.json", canonical_json_document(manifest), 0o600)
        os.replace(staging, output_root)
        os.chmod(output_root, 0o700)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return manifest


def read_input_jsonl(path: Path, label: str) -> tuple[dict[str, Any], ...]:
    path = Path(path)
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise ExportBundleError(f"{label} is missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ExportBundleError(f"{label} is unsafe")
    payload = path.read_bytes()
    if payload and not payload.endswith(b"\n"):
        raise ExportBundleError(f"{label} lacks final newline")
    rows: list[dict[str, Any]] = []
    for ordinal, line in enumerate(payload.splitlines(), start=1):
        try:
            row = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ExportBundleError(f"{label} row {ordinal} is invalid") from exc
        if not isinstance(row, dict) or canonical_json_bytes(row) != line:
            raise ExportBundleError(f"{label} row {ordinal} is noncanonical")
        rows.append(row)
    return tuple(rows)


def _iter_input_jsonl(path: Path, label: str) -> Iterator[tuple[dict[str, Any], bytes]]:
    path = Path(path)
    try:
        path_metadata = os.lstat(path)
    except OSError as exc:
        raise ExportBundleError(f"{label} is missing") from exc
    if stat.S_ISLNK(path_metadata.st_mode) or not stat.S_ISREG(path_metadata.st_mode):
        raise ExportBundleError(f"{label} is unsafe")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            ordinal = 0
            while True:
                line_with_newline = handle.readline()
                if not line_with_newline:
                    break
                ordinal += 1
                if not line_with_newline.endswith(b"\n"):
                    raise ExportBundleError(f"{label} lacks final newline")
                line = line_with_newline[:-1]
                try:
                    row = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ExportBundleError(f"{label} row {ordinal} is invalid") from exc
                if not isinstance(row, dict) or canonical_json_bytes(row) != line:
                    raise ExportBundleError(f"{label} row {ordinal} is noncanonical")
                yield row, line_with_newline
        after = os.fstat(descriptor)
        try:
            path_after = os.lstat(path)
        except OSError as exc:
            raise ExportBundleError(f"{label} path changed during read") from exc
    finally:
        os.close(descriptor)
    if (
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        or (before.st_dev, before.st_ino)
        != (path_metadata.st_dev, path_metadata.st_ino)
        or (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        )
        != (
            path_after.st_dev,
            path_after.st_ino,
            path_after.st_size,
            path_after.st_mtime_ns,
        )
        or stat.S_ISLNK(path_after.st_mode)
        or not stat.S_ISREG(path_after.st_mode)
    ):
        raise ExportBundleError(f"{label} bytes drift")


def write_export_bundle_from_files(
    output_root: Path,
    input_paths: Mapping[str, Path],
    metadata: ExportBundleMetadata,
    *,
    materialization: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Stream one already-materialized four-file input into an atomic bundle.

    This path keeps memory proportional to primary-key sets instead of artifact
    byte size, which is required for the real private-audit export.
    """

    _validate_metadata(metadata)
    if set(input_paths) != set(ARTIFACT_FILES):
        raise ExportBundleError("export input member set is invalid")
    output_root = Path(output_root)
    if output_root.exists() or output_root.is_symlink():
        raise ExportBundleError("export bundle output root already exists")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging = output_root.parent / f".{output_root.name}.building"
    if staging.exists() or staging.is_symlink():
        raise ExportBundleError("export bundle staging root already exists")

    primary_sets: dict[str, set[str]] = {}
    fact_ids: set[str] = set()
    row_counts: dict[str, int] = {}
    fact_rows = 0
    voc_rows = 0
    contracts: list[dict[str, object]] = []
    os.mkdir(staging, 0o700)
    try:
        for name in ARTIFACT_FILES:
            primary_key = PRIMARY_KEYS[name]
            seen: set[str] = set()
            digest = sha256()
            byte_count = 0
            row_count = 0
            destination = staging / name
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(destination, flags, 0o600)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    for row, line in _iter_input_jsonl(input_paths[name], name):
                        if (
                            row.get("schema_version") != ROW_SCHEMAS[name]
                            or row.get("export_bundle_id") != metadata.export_bundle_id
                            or row.get("release_id") != metadata.release_id
                            or row.get("source_snapshot_id")
                            != metadata.source_snapshot_id
                        ):
                            raise ExportBundleError(
                                f"{name} release or snapshot identity mismatch"
                            )
                        primary = row.get(primary_key)
                        if (
                            not isinstance(primary, str)
                            or not primary
                            or primary in seen
                        ):
                            raise ExportBundleError(
                                f"{name} primary identity is invalid"
                            )
                        seen.add(primary)
                        _reference_list(row, "entity_refs")
                        _reference_list(row, "fact_refs")
                        if name == "reddit-voc-facts.jsonl":
                            kind = row.get("record_kind")
                            if kind == "fact":
                                fact_id = row.get("fact_id")
                                if not isinstance(fact_id, str) or not fact_id:
                                    raise ExportBundleError(
                                        "fact export row lacks fact_id"
                                    )
                                if fact_id in fact_ids:
                                    raise ExportBundleError(
                                        "fact export identity is duplicated"
                                    )
                                fact_ids.add(fact_id)
                                fact_rows += 1
                            elif kind == "voc":
                                if (
                                    not isinstance(row.get("voc_id"), str)
                                    or not row["voc_id"]
                                ):
                                    raise ExportBundleError("VOC export row lacks voc_id")
                                voc_rows += 1
                            else:
                                raise ExportBundleError(
                                    "VOC/fact record kind is invalid"
                                )
                        if metadata.bundle_mode == "public":
                            denied = _denied_field(row)
                            if denied is not None:
                                raise ExportBundleError(
                                    f"public bundle contains denied field: {denied}"
                                )
                        handle.write(line)
                        digest.update(line)
                        byte_count += len(line)
                        row_count += 1
                    handle.flush()
                    os.fsync(handle.fileno())
            except Exception:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
                raise
            if row_count == 0:
                raise ExportBundleError(f"{name} must not be empty")
            os.chmod(destination, 0o600)
            primary_sets[name] = seen
            row_counts[name] = row_count
            contracts.append(
                {
                    "byte_count": byte_count,
                    "path": name,
                    "row_count": row_count,
                    "sha256": digest.hexdigest(),
                }
            )

        entity_ids = primary_sets["reddit-entities-full.jsonl"]
        entity_reference_count = 0
        fact_reference_count = 0
        unresolved_entities = 0
        unresolved_facts = 0
        for name in ARTIFACT_FILES[1:]:
            for row, _ in _iter_input_jsonl(input_paths[name], name):
                entity_refs = _reference_list(row, "entity_refs")
                fact_refs = _reference_list(row, "fact_refs")
                entity_reference_count += len(entity_refs)
                fact_reference_count += len(fact_refs)
                unresolved_entities += sum(
                    reference not in entity_ids for reference in entity_refs
                )
                unresolved_facts += sum(
                    reference not in fact_ids for reference in fact_refs
                )
        if unresolved_entities:
            raise ExportBundleError("unresolved entity references")
        if unresolved_facts:
            raise ExportBundleError("unresolved fact references")
        cross_reference_counts = {
            "entity_reference_count": entity_reference_count,
            "entity_rows": row_counts["reddit-entities-full.jsonl"],
            "fact_rows": fact_rows,
            "fact_reference_count": fact_reference_count,
            "governance_case_rows": row_counts[
                "reddit-governance-casebook.jsonl"
            ],
            "metric_reporting_rows": row_counts[
                "reddit-metrics-reporting.jsonl"
            ],
            "resolved_entity_references": entity_reference_count,
            "resolved_fact_references": fact_reference_count,
            "unresolved_entity_references": 0,
            "unresolved_fact_references": 0,
            "voc_rows": voc_rows,
        }
        manifest = _manifest_from_contracts(
            contracts=contracts,
            cross_reference_counts=cross_reference_counts,
            metadata=metadata,
            materialization=materialization,
        )
        _write_file(
            staging / "manifest.json", canonical_json_document(manifest), 0o600
        )
        os.replace(staging, output_root)
        os.chmod(output_root, 0o700)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return manifest
