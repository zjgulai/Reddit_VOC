"""Materialize the real V3 candidate into the private four-artifact export."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
from typing import Any, Iterable, Iterator, Mapping, TextIO

from reddit_voc.v3_export_bundle import (
    ARTIFACT_FILES,
    BOUNDARIES,
    ExportBundleError,
    ExportBundleMetadata,
    ROW_SCHEMAS,
    canonical_json_bytes,
    canonical_json_document,
    sha256_bytes,
)


MATERIALIZATION_SCHEMA = "reddit_voc_export_materialization_v2"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
FACT_TABLES = (
    "commercial-relation-facts.jsonl",
    "community-governance-facts.jsonl",
    "entity-brand-facts.jsonl",
    "entity-problem-facts.jsonl",
    "entity-product-facts.jsonl",
    "entity-sentiment-facts.jsonl",
    "entity-tag-facts.jsonl",
    "integrity-signal-facts.jsonl",
)
REPORT_DOCUMENTS = (
    "current/daily.json",
    "current/weekly.json",
    "current/monthly.json",
    "archive/daily.json",
    "archive/weekly.json",
    "archive/monthly.json",
)
RECEIPT_BINDING_KEYS = {
    "canonical": "bundle_manifest_sha256",
    "case_reference": "registry_manifest_sha256",
    "casebook": "casebook_manifest_sha256",
    "governed_signals": "snapshot_manifest_sha256",
    "integrity": "integrity_manifest_sha256",
    "integrity_input": "upstream_manifest_sha256",
    "metrics": "bundle_manifest_sha256",
    "personas": "manifest_sha256",
    "reports": "bundle_manifest_sha256",
    "voc_facts": "bundle_manifest_sha256",
}


@dataclass(frozen=True)
class MaterializationPaths:
    canonical_dir: Path
    canonical_receipt: Path
    voc_facts_dir: Path
    voc_facts_receipt: Path
    governed_signals_dir: Path
    governed_signals_receipt: Path
    metrics_dir: Path
    metrics_receipt: Path
    integrity_dir: Path
    integrity_receipt: Path
    integrity_input_dir: Path
    integrity_input_receipt: Path
    casebook_dir: Path
    casebook_receipt: Path
    case_reference_dir: Path
    case_reference_receipt: Path
    reports_dir: Path
    reports_receipt: Path
    personas_dir: Path
    personas_receipt: Path
    current_release: Path


def _identity(metadata: os.stat_result) -> tuple[int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def _absolute_path(path: Path) -> Path:
    absolute = Path(os.path.abspath(os.fspath(path)))
    if sys.platform == "darwin" and absolute.parts[:2] in {("/", "var"), ("/", "tmp")}:
        absolute = Path("/private") / Path(*absolute.parts[1:])
    return absolute


def _safe_directory_chain(path: Path) -> Path:
    absolute = _absolute_path(path)
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        try:
            metadata = os.lstat(current)
        except OSError as exc:
            raise ExportBundleError(f"source directory chain is unsafe: {current}") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ExportBundleError(f"source directory chain is unsafe: {current}")
    return absolute


def _regular_bytes(path: Path, label: str) -> bytes:
    path = _absolute_path(path)
    _safe_directory_chain(path.parent)
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise ExportBundleError(f"{label} is missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ExportBundleError(f"{label} is unsafe")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if _identity(before) != _identity(metadata):
            raise ExportBundleError(f"{label} path changed before read")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        path_after = os.lstat(path)
    finally:
        os.close(descriptor)
    if (
        _identity(before) != _identity(after)
        or _identity(before) != _identity(path_after)
        or stat.S_ISLNK(path_after.st_mode)
        or not stat.S_ISREG(path_after.st_mode)
    ):
        raise ExportBundleError(f"{label} bytes drift")
    payload = b"".join(chunks)
    if len(payload) != before.st_size:
        raise ExportBundleError(f"{label} bytes drift")
    return payload


def _regular_sha_and_size(path: Path, label: str) -> tuple[str, int]:
    path = _absolute_path(path)
    _safe_directory_chain(path.parent)
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise ExportBundleError(f"{label} is missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ExportBundleError(f"{label} is unsafe")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    digest = sha256()
    size = 0
    try:
        before = os.fstat(descriptor)
        if _identity(before) != _identity(metadata):
            raise ExportBundleError(f"{label} path changed before read")
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
        after = os.fstat(descriptor)
        path_after = os.lstat(path)
    finally:
        os.close(descriptor)
    if (
        size != before.st_size
        or _identity(before) != _identity(after)
        or _identity(before) != _identity(path_after)
        or stat.S_ISLNK(path_after.st_mode)
        or not stat.S_ISREG(path_after.st_mode)
    ):
        raise ExportBundleError(f"{label} bytes drift")
    return digest.hexdigest(), size


def _load_object(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    payload = _regular_bytes(path, label)
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ExportBundleError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ExportBundleError(f"{label} must be an object")
    return value, payload


def _safe_boundaries(value: Mapping[str, Any], label: str) -> None:
    boundaries = value.get("boundaries")
    if not isinstance(boundaries, dict):
        raise ExportBundleError(f"{label} boundaries are missing")
    for key, expected in BOUNDARIES.items():
        if boundaries.get(key) is not expected:
            raise ExportBundleError(f"{label} boundary is unsafe: {key}")


def _validate_declared_files(directory: Path, manifest: Mapping[str, Any]) -> None:
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ExportBundleError("source manifest files are missing")
    root = _safe_directory_chain(directory)
    for relative, contract in files.items():
        if (
            not isinstance(relative, str)
            or not isinstance(contract, dict)
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
        ):
            raise ExportBundleError("source manifest file contract is invalid")
        path = _absolute_path(root / relative)
        if os.path.commonpath((str(root), str(path))) != str(root):
            raise ExportBundleError("source artifact escapes its manifest root")
        actual_sha, actual_size = _regular_sha_and_size(
            path, f"source artifact {relative}"
        )
        declared_bytes = contract.get("bytes", contract.get("byte_count"))
        if (
            declared_bytes != actual_size
            or contract.get("sha256") != actual_sha
        ):
            raise ExportBundleError(f"source artifact contract drift: {relative}")


def _validate_source(
    label: str,
    directory: Path,
    receipt_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    manifest, manifest_payload = _load_object(directory / "manifest.json", f"{label} manifest")
    receipt, receipt_payload = _load_object(receipt_path, f"{label} receipt")
    manifest_sha = sha256_bytes(manifest_payload)
    receipt_sha = sha256_bytes(receipt_payload)
    binding_key = RECEIPT_BINDING_KEYS[label]
    if (
        receipt.get("status") not in {"passed", "passed_candidate_only"}
        or receipt.get(binding_key) != manifest_sha
    ):
        raise ExportBundleError(f"{label} independent receipt is not bound")
    _safe_boundaries(manifest, f"{label} manifest")
    if "boundaries" in receipt:
        _safe_boundaries(receipt, f"{label} receipt")
    _validate_declared_files(directory, manifest)
    return manifest, receipt, {
        "manifest_sha256": manifest_sha,
        "validation_receipt_sha256": receipt_sha,
    }


def _validate_inputs(
    paths: MaterializationPaths,
    metadata: ExportBundleMetadata,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, str]]]:
    sources = {
        "canonical": (paths.canonical_dir, paths.canonical_receipt),
        "voc_facts": (paths.voc_facts_dir, paths.voc_facts_receipt),
        "governed_signals": (
            paths.governed_signals_dir,
            paths.governed_signals_receipt,
        ),
        "metrics": (paths.metrics_dir, paths.metrics_receipt),
        "integrity": (paths.integrity_dir, paths.integrity_receipt),
        "integrity_input": (
            paths.integrity_input_dir,
            paths.integrity_input_receipt,
        ),
        "casebook": (paths.casebook_dir, paths.casebook_receipt),
        "case_reference": (
            paths.case_reference_dir,
            paths.case_reference_receipt,
        ),
        "reports": (paths.reports_dir, paths.reports_receipt),
        "personas": (paths.personas_dir, paths.personas_receipt),
    }
    manifests: dict[str, dict[str, Any]] = {}
    bindings: dict[str, dict[str, str]] = {}
    for label, (directory, receipt) in sources.items():
        manifest, _, binding = _validate_source(label, directory, receipt)
        manifests[label] = manifest
        bindings[label] = binding

    pointer, pointer_payload = _load_object(paths.current_release, "current release")
    pointer_sha = sha256_bytes(pointer_payload)
    if (
        pointer.get("schema_version") != "reddit_voc_current_release_v1"
        or pointer.get("release_id") != metadata.release_id
    ):
        raise ExportBundleError("current release identity mismatch")
    datasets = pointer.get("datasets")
    if not isinstance(datasets, dict):
        raise ExportBundleError("current release datasets are missing")
    expected_lineage = {
        "base": bindings["canonical"]["manifest_sha256"],
        "reports": bindings["reports"]["manifest_sha256"],
        "personas": bindings["personas"]["manifest_sha256"],
    }
    for key, expected in expected_lineage.items():
        dataset = datasets.get(key)
        if not isinstance(dataset, dict) or dataset.get("lineage_manifest_sha256") != expected:
            raise ExportBundleError(f"current release {key} lineage mismatch")
    bindings["current_release"] = {
        "manifest_sha256": pointer_sha,
        "validation_receipt_sha256": None,
    }
    manifests["current_release"] = pointer

    source_snapshot_id = metadata.source_snapshot_id
    if (
        manifests["governed_signals"].get("source_snapshot_id")
        != source_snapshot_id
        or manifests["integrity"].get("source_snapshot_id") != source_snapshot_id
        or manifests["integrity_input"].get("source_snapshot_id")
        != source_snapshot_id
        or manifests["casebook"].get("source_snapshot_id") != source_snapshot_id
        or manifests["reports"].get("source_snapshot_id") != source_snapshot_id
        or manifests["personas"].get("governed_signal_source_snapshot_id")
        != source_snapshot_id
        or not str(manifests["canonical"].get("dataset_id", "")).startswith(
            source_snapshot_id
        )
        or not str(manifests["voc_facts"].get("dataset_id", "")).startswith(
            source_snapshot_id
        )
    ):
        raise ExportBundleError("source snapshot lineage mismatch")

    canonical_sha = bindings["canonical"]["manifest_sha256"]
    facts_sha = bindings["voc_facts"]["manifest_sha256"]
    facts_receipt_sha = bindings["voc_facts"]["validation_receipt_sha256"]
    governed_sha = bindings["governed_signals"]["manifest_sha256"]
    governed_receipt_sha = bindings["governed_signals"][
        "validation_receipt_sha256"
    ]
    case_reference_sha = bindings["case_reference"]["manifest_sha256"]
    integrity_input_sha = bindings["integrity_input"]["manifest_sha256"]
    facts_inputs = manifests["voc_facts"].get("inputs")
    governed_inputs = manifests["governed_signals"].get("inputs")
    casebook_inputs = manifests["casebook"].get("inputs")
    if (
        not isinstance(facts_inputs, dict)
        or facts_inputs.get("canonical_manifest_sha256") != canonical_sha
        or not isinstance(governed_inputs, dict)
        or governed_inputs.get("facts_manifest_sha256") != facts_sha
        or governed_inputs.get("facts_receipt_sha256") != facts_receipt_sha
        or governed_inputs.get("dim_tag_sha256") != metadata.dictionary_sha256
        or facts_inputs.get("eligibility_policy_sha256")
        != metadata.eligibility_policy_sha256
        or manifests["metrics"].get("registry_sha256")
        != metadata.indicator_registry_sha256
        or manifests["reports"].get("metrics_candidate_manifest_sha256")
        != bindings["metrics"]["manifest_sha256"]
        or manifests["personas"].get("source_facts_manifest_sha256") != facts_sha
        or manifests["personas"].get("source_facts_validation_receipt_sha256")
        != facts_receipt_sha
        or manifests["personas"].get("governed_signal_manifest_sha256")
        != governed_sha
        or manifests["personas"].get("governed_signal_validation_receipt_sha256")
        != governed_receipt_sha
        or not isinstance(casebook_inputs, dict)
        or casebook_inputs.get("facts_manifest_sha256") != facts_sha
        or casebook_inputs.get("facts_receipt_sha256") != facts_receipt_sha
        or casebook_inputs.get("governed_manifest_sha256") != governed_sha
        or casebook_inputs.get("governed_receipt_sha256") != governed_receipt_sha
        or casebook_inputs.get("reference_registry_manifest_sha256")
        != case_reference_sha
        or manifests["integrity"].get("upstream_manifest_sha256")
        != integrity_input_sha
    ):
        raise ExportBundleError("upstream manifest lineage mismatch")

    coverage = manifests["reports"].get("coverage_attestation")
    window = coverage.get("coverage_window") if isinstance(coverage, dict) else None
    if (
        not isinstance(window, dict)
        or window.get("end_calendar_date_inclusive")
        != metadata.source_cutoff_value
        or metadata.source_cutoff_precision != "day"
        or metadata.source_timezone_status != "unknown_floating_date"
    ):
        raise ExportBundleError("source cutoff contract mismatch")
    return manifests, bindings


def _iter_jsonl(path: Path, label: str) -> Iterator[dict[str, Any]]:
    path = _absolute_path(path)
    _safe_directory_chain(path.parent)
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise ExportBundleError(f"{label} is missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ExportBundleError(f"{label} is unsafe")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if _identity(before) != _identity(metadata):
            raise ExportBundleError(f"{label} path changed before read")
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
                except (UnicodeError, json.JSONDecodeError) as exc:
                    raise ExportBundleError(f"{label} row {ordinal} is invalid") from exc
                if not isinstance(row, dict):
                    raise ExportBundleError(f"{label} row {ordinal} is not an object")
                yield row
        after = os.fstat(descriptor)
        path_after = os.lstat(path)
    finally:
        os.close(descriptor)
    if (
        _identity(before) != _identity(after)
        or _identity(before) != _identity(path_after)
        or stat.S_ISLNK(path_after.st_mode)
        or not stat.S_ISREG(path_after.st_mode)
    ):
        raise ExportBundleError(f"{label} bytes drift")


@contextmanager
def _safe_text_reader(path: Path, label: str) -> Iterator[TextIO]:
    path = _absolute_path(path)
    _safe_directory_chain(path.parent)
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise ExportBundleError(f"{label} is missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ExportBundleError(f"{label} is unsafe")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    before = os.fstat(descriptor)
    if _identity(before) != _identity(metadata):
        os.close(descriptor)
        raise ExportBundleError(f"{label} path changed before read")
    try:
        with os.fdopen(descriptor, "r", encoding="utf-8", closefd=False) as handle:
            yield handle
        after = os.fstat(descriptor)
        path_after = os.lstat(path)
        if (
            _identity(before) != _identity(after)
            or _identity(before) != _identity(path_after)
            or stat.S_ISLNK(path_after.st_mode)
            or not stat.S_ISREG(path_after.st_mode)
        ):
            raise ExportBundleError(f"{label} bytes drift")
    finally:
        os.close(descriptor)


def _iter_large_json_array(path: Path, key: str) -> Iterator[dict[str, Any]]:
    """Incrementally decode one named top-level array from canonical JSON."""

    target = json.dumps(key, ensure_ascii=False, separators=(",", ":")) + ":["
    decoder = json.JSONDecoder()
    with _safe_text_reader(path, f"large JSON {key}") as handle:
        buffer = ""
        while target not in buffer:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                raise ExportBundleError(f"JSON array is missing: {key}")
            buffer = (buffer + chunk)[-max(len(target) + 8, 1024 * 1024) :]
        buffer = buffer.split(target, 1)[1]
        position = 0
        while True:
            while True:
                while position < len(buffer) and buffer[position].isspace():
                    position += 1
                if position < len(buffer):
                    break
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    raise ExportBundleError(f"JSON array is truncated: {key}")
                buffer = chunk
                position = 0
            if buffer[position] == "]":
                return
            try:
                value, end = decoder.raw_decode(buffer, position)
            except json.JSONDecodeError:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    raise ExportBundleError(f"JSON array row is invalid: {key}")
                buffer = buffer[position:] + chunk
                position = 0
                continue
            if not isinstance(value, dict):
                raise ExportBundleError(f"JSON array row is not an object: {key}")
            yield value
            position = end
            while True:
                while position < len(buffer) and buffer[position].isspace():
                    position += 1
                if position < len(buffer):
                    break
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    raise ExportBundleError(f"JSON array is truncated: {key}")
                buffer = chunk
                position = 0
            if buffer[position] == ",":
                position += 1
            elif buffer[position] != "]":
                raise ExportBundleError(f"JSON array separator is invalid: {key}")
            if position > 1024 * 1024:
                buffer = buffer[position:]
                position = 0


def _base(metadata: ExportBundleMetadata) -> dict[str, str]:
    return {
        "export_bundle_id": metadata.export_bundle_id,
        "release_id": metadata.release_id,
        "source_snapshot_id": metadata.source_snapshot_id,
    }


def _source_status_counts(paths: MaterializationPaths) -> dict[str, int]:
    counts = {
        "canonical_comment_rows": 0,
        "canonical_post_rows": 0,
        "external_reference_rows": 0,
        "external_snapshot_rows": 0,
        "linked_comment_rows": 0,
        "quarantine_rows": 0,
        "unresolved_parent_comment_rows": 0,
        "unresolved_parent_exclusion_rows": 0,
        "voc_exclusion_rows": 0,
    }
    for _ in _iter_jsonl(paths.canonical_dir / "posts.jsonl", "source posts"):
        counts["canonical_post_rows"] += 1
    for row in _iter_jsonl(
        paths.canonical_dir / "comments.jsonl", "source comments"
    ):
        counts["canonical_comment_rows"] += 1
        state = row.get("comment_state")
        if state == "linked":
            counts["linked_comment_rows"] += 1
        elif state == "unresolved_parent":
            counts["unresolved_parent_comment_rows"] += 1
        else:
            raise ExportBundleError(f"unexpected canonical comment state: {state}")
    for _ in _iter_jsonl(
        paths.canonical_dir / "quarantine.jsonl", "source quarantine"
    ):
        counts["quarantine_rows"] += 1
    for _ in _iter_jsonl(
        paths.case_reference_dir / "references.jsonl", "source external references"
    ):
        counts["external_reference_rows"] += 1
    for _ in _iter_jsonl(
        paths.case_reference_dir / "external-public-snapshots.jsonl",
        "source external snapshots",
    ):
        counts["external_snapshot_rows"] += 1
    for row in _iter_jsonl(
        paths.voc_facts_dir / "voc-exclusions.jsonl", "source exclusions"
    ):
        reasons = row.get("reason_codes")
        if not isinstance(reasons, list) or any(
            not isinstance(reason, str) or not reason for reason in reasons
        ):
            raise ExportBundleError("source exclusion reason_codes are invalid")
        counts["voc_exclusion_rows"] += 1
        if "unresolved_parent" in reasons:
            counts["unresolved_parent_exclusion_rows"] += 1
    return counts


def _write_rows(path: Path, rows: Iterable[Mapping[str, Any]]) -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    count = 0
    try:
        with os.fdopen(descriptor, "wb") as handle:
            for row in rows:
                handle.write(canonical_json_document(dict(row)))
                count += 1
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise
    os.chmod(path, 0o600)
    if count == 0:
        raise ExportBundleError(f"materialized artifact is empty: {path.name}")
    return count


def _entity_id_from_reference(value: str, entity_ids: set[str]) -> str:
    if value in entity_ids:
        return value
    if value.startswith("post:"):
        reddit_id = value.split(":", 1)[1]
        candidate = f"t3_{reddit_id}"
        external = f"external_reddit_post:{reddit_id}"
        if candidate not in entity_ids and external in entity_ids:
            candidate = external
    elif value.startswith("comment:"):
        candidate = f"t1_{value.split(':', 1)[1]}"
    elif value.startswith("external-post:"):
        candidate = f"external_reddit_post:{value.split(':', 1)[1]}"
    elif value.startswith("t1_") or value.startswith("t3_") or value.startswith(
        "external_reddit_post:"
    ):
        candidate = value
    else:
        candidate = f"t3_{value}"
        external = f"external_reddit_post:{value}"
        if external in entity_ids:
            candidate = external
    if candidate not in entity_ids:
        raise ExportBundleError(f"source entity reference is unresolved: {value}")
    return candidate


def _materialize_entities(
    paths: MaterializationPaths,
    metadata: ExportBundleMetadata,
    destination: Path,
) -> tuple[int, set[str], dict[str, list[str]]]:
    exclusions: dict[str, list[str]] = {}
    for row in _iter_jsonl(
        paths.voc_facts_dir / "voc-exclusions.jsonl", "VOC exclusions"
    ):
        entity_id = row.get("canonical_entity_id")
        reasons = row.get("reason_codes")
        if not isinstance(entity_id, str) or not isinstance(reasons, list):
            raise ExportBundleError("VOC exclusion identity is invalid")
        exclusions.setdefault(entity_id, []).extend(
            reason for reason in reasons if isinstance(reason, str) and reason
        )
    entity_ids: set[str] = set()
    base = _base(metadata)

    def rows() -> Iterator[dict[str, Any]]:
        for filename in ("posts.jsonl", "comments.jsonl", "quarantine.jsonl"):
            for source in _iter_jsonl(
                paths.canonical_dir / filename, f"canonical {filename}"
            ):
                entity_id = source.get("canonical_reddit_id")
                if not isinstance(entity_id, str) or not entity_id or entity_id in entity_ids:
                    raise ExportBundleError("canonical export entity identity is invalid")
                entity_ids.add(entity_id)
                reasons = list(exclusions.get(entity_id, []))
                if filename == "quarantine.jsonl":
                    reason = source.get("record", {}).get("reason")
                    reasons.extend(["quarantined", str(reason)] if reason else ["quarantined"])
                record = source.get("record")
                source_occurrences = (
                    record.get("source_occurrences", [])
                    if isinstance(record, dict)
                    else []
                )
                yield {
                    **base,
                    "data_status": source.get(
                        "comment_state", source.get("canonical_identity_state")
                    ),
                    "entity_id": entity_id,
                    "entity_refs": [],
                    "entity_type": source.get("entity_type"),
                    "exclusion_reasons": sorted(set(reasons)),
                    "fact_refs": [],
                    "payload": source,
                    "schema_version": ROW_SCHEMAS["reddit-entities-full.jsonl"],
                    "source_provenance": {
                        "record_authority": source.get("record_authority"),
                        "source_artifact": f"canonical/{filename}",
                        "source_occurrences": source_occurrences,
                    },
                }
        for snapshot in _iter_jsonl(
            paths.case_reference_dir / "external-public-snapshots.jsonl",
            "external public snapshots",
        ):
            reddit_post_id = snapshot.get("reddit_post_id")
            if not isinstance(reddit_post_id, str) or not reddit_post_id:
                raise ExportBundleError("external reference identity is invalid")
            entity_id = f"external_reddit_post:{reddit_post_id}"
            if entity_id in entity_ids:
                raise ExportBundleError("external reference identity is duplicated")
            entity_ids.add(entity_id)
            provenance = snapshot.get("provenance", {})
            if not isinstance(provenance, dict):
                raise ExportBundleError("external reference provenance is invalid")
            yield {
                **base,
                "data_status": "external_public_reference_noncanonical",
                "entity_id": entity_id,
                "entity_refs": [],
                "entity_type": "external_public_reference",
                "exclusion_reasons": [
                    "excluded_from_metrics",
                    "noncanonical_external_reference",
                ],
                "fact_refs": [],
                "payload": snapshot,
                "schema_version": ROW_SCHEMAS["reddit-entities-full.jsonl"],
                "source_provenance": {
                    **provenance,
                    "source_artifact": (
                        "case_reference/external-public-snapshots.jsonl"
                    ),
                },
            }

    return _write_rows(destination, rows()), entity_ids, exclusions


def _derived_fact_id(kind: str, payload: Mapping[str, Any]) -> str:
    digest = sha256(kind.encode("utf-8") + b"\0" + canonical_json_bytes(payload))
    return f"{kind}:{digest.hexdigest()}"


def _materialize_facts(
    paths: MaterializationPaths,
    metadata: ExportBundleMetadata,
    destination: Path,
    entity_ids: set[str],
) -> tuple[int, set[str]]:
    base = _base(metadata)
    fact_ids: set[str] = set()

    def fact_row(
        source: Mapping[str, Any],
        *,
        source_artifact: str,
        fact_id: str,
        entity_values: Iterable[str],
    ) -> dict[str, Any]:
        if fact_id in fact_ids:
            raise ExportBundleError(f"fact identity is duplicated: {fact_id}")
        fact_ids.add(fact_id)
        entity_refs = sorted(
            {
                _entity_id_from_reference(value, entity_ids)
                for value in entity_values
                if isinstance(value, str) and value
            }
        )
        return {
            **base,
            "entity_refs": entity_refs,
            "fact_id": fact_id,
            "fact_refs": [],
            "payload": dict(source),
            "record_id": f"fact:{fact_id}",
            "record_kind": "fact",
            "schema_version": ROW_SCHEMAS["reddit-voc-facts.jsonl"],
            "source_artifact": source_artifact,
        }

    def rows() -> Iterator[dict[str, Any]]:
        for source in _iter_jsonl(paths.voc_facts_dir / "vocs.jsonl", "VOC rows"):
            voc_id = source.get("voc_id")
            entity_id = source.get("canonical_entity_id")
            if not isinstance(voc_id, str) or not isinstance(entity_id, str):
                raise ExportBundleError("VOC identity is invalid")
            entity_ref = _entity_id_from_reference(entity_id, entity_ids)
            yield {
                **base,
                "entity_refs": [entity_ref],
                "fact_refs": [],
                "payload": source,
                "record_id": f"voc:{voc_id}",
                "record_kind": "voc",
                "schema_version": ROW_SCHEMAS["reddit-voc-facts.jsonl"],
                "source_artifact": "voc_facts/vocs.jsonl",
                "voc_id": voc_id,
            }
        for filename in FACT_TABLES:
            for source in _iter_jsonl(
                paths.governed_signals_dir / filename,
                f"governed facts {filename}",
            ):
                fact_id = source.get("fact_id")
                if not isinstance(fact_id, str) or not fact_id:
                    raise ExportBundleError("governed fact identity is invalid")
                yield fact_row(
                    source,
                    source_artifact=f"governed_signals/{filename}",
                    fact_id=fact_id,
                    entity_values=(
                        source.get("canonical_entity_id"),
                        source.get("evidence_source_entity_id"),
                    ),
                )
        for source in _iter_jsonl(
            paths.integrity_input_dir / "governed-facts.jsonl",
            "integrity input governed facts",
        ):
            fact_id = source.get("fact_id")
            if not isinstance(fact_id, str) or not fact_id:
                raise ExportBundleError("integrity input fact identity is invalid")
            # This validated downstream input repeats canonical governed facts
            # and adds the external governance evidence consumed by integrity.
            # Export a repeated fact only once while retaining the extra facts.
            if fact_id in fact_ids:
                continue
            yield fact_row(
                source,
                source_artifact="integrity_input/governed-facts.jsonl",
                fact_id=fact_id,
                entity_values=(
                    source.get("canonical_entity_id"),
                    source.get("evidence_source_entity_id"),
                ),
            )
        for source in _iter_jsonl(
            paths.casebook_dir / "external-governance-facts.jsonl",
            "external governance facts",
        ):
            fact_id = source.get("fact_id")
            if not isinstance(fact_id, str) or not fact_id:
                raise ExportBundleError("external governance fact identity is invalid")
            yield fact_row(
                source,
                source_artifact="casebook/external-governance-facts.jsonl",
                fact_id=fact_id,
                entity_values=(
                    source.get("canonical_entity_id"),
                    source.get("evidence_source_entity_id"),
                ),
            )
        for source in _iter_jsonl(
            paths.personas_dir / "persona-atomic-facts.jsonl",
            "persona atomic facts",
        ):
            fact_id = source.get("fact_id")
            if not isinstance(fact_id, str) or not fact_id:
                raise ExportBundleError("persona fact identity is invalid")
            yield fact_row(
                source,
                source_artifact="personas/persona-atomic-facts.jsonl",
                fact_id=fact_id,
                entity_values=(source.get("canonical_entity_id"),),
            )
        for source in _iter_jsonl(
            paths.voc_facts_dir / "automation-classifications.jsonl",
            "automation classifications",
        ):
            yield fact_row(
                source,
                source_artifact="voc_facts/automation-classifications.jsonl",
                fact_id=_derived_fact_id("automation", source),
                entity_values=(source.get("canonical_entity_id"),),
            )
        for source in _iter_jsonl(
            paths.voc_facts_dir / "voc-exclusions.jsonl", "VOC exclusions"
        ):
            yield fact_row(
                source,
                source_artifact="voc_facts/voc-exclusions.jsonl",
                fact_id=_derived_fact_id("voc_exclusion", source),
                entity_values=(source.get("canonical_entity_id"),),
            )

    return _write_rows(destination, rows()), fact_ids


def _require_fact_refs(values: Iterable[Any], fact_ids: set[str]) -> list[str]:
    refs = sorted({value for value in values if isinstance(value, str) and value})
    missing = [value for value in refs if value not in fact_ids]
    if missing:
        raise ExportBundleError(f"metric or case fact reference is unresolved: {missing[0]}")
    return refs


def _collect_evidence_ids(value: object) -> Iterator[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"evidence_ids", "evidence_fact_ids"} and isinstance(item, list):
                for candidate in item:
                    if isinstance(candidate, str):
                        yield candidate
            else:
                yield from _collect_evidence_ids(item)
    elif isinstance(value, list):
        for item in value:
            yield from _collect_evidence_ids(item)


def _materialize_metrics(
    paths: MaterializationPaths,
    metadata: ExportBundleMetadata,
    destination: Path,
    entity_ids: set[str],
    fact_ids: set[str],
) -> int:
    base = _base(metadata)

    def metric_row(
        source: Mapping[str, Any],
        *,
        source_artifact: str,
        record_type: str,
        entity_values: Iterable[Any] = (),
        evidence_values: Iterable[Any] = (),
        numerator: Any = None,
        denominator: Any = None,
        comparison: Any = None,
    ) -> dict[str, Any]:
        entity_refs = sorted(
            {
                _entity_id_from_reference(value, entity_ids)
                for value in entity_values
                if isinstance(value, str) and value
            }
        )
        fact_refs = _require_fact_refs(evidence_values, fact_ids)
        identity_payload = canonical_json_bytes(
            {"record_type": record_type, "source": source_artifact, "payload": source}
        )
        return {
            **base,
            "comparison": comparison,
            "denominator": denominator,
            "entity_refs": entity_refs,
            "fact_refs": fact_refs,
            "formula_version": source.get(
                "metric_policy_version", source.get("policy_version")
            ),
            "metric_id": source.get(
                "metric_id", source.get("reddit_indicator_id")
            ),
            "metric_record_id": f"metric:{record_type}:{sha256_bytes(identity_payload)}",
            "numerator": numerator,
            "payload": dict(source),
            "record_type": record_type,
            "schema_version": ROW_SCHEMAS["reddit-metrics-reporting.jsonl"],
            "source_artifact": source_artifact,
            "status": source.get("status"),
            "value": source.get("value"),
        }

    def rows() -> Iterator[dict[str, Any]]:
        metrics, _ = _load_object(paths.metrics_dir / "metrics.json", "metrics snapshot")
        indicators = metrics.get("indicators")
        if not isinstance(indicators, list):
            raise ExportBundleError("metrics snapshot indicators are missing")
        for source in indicators:
            if not isinstance(source, dict):
                raise ExportBundleError("metrics indicator is invalid")
            member_ids: list[Any] = []
            for key in (
                "denominator_member_ids",
                "metric_eligible_member_ids",
                "numerator_member_ids",
            ):
                values = source.get(key, [])
                if isinstance(values, list):
                    member_ids.extend(values)
            yield metric_row(
                source,
                source_artifact="metrics/metrics.json",
                record_type="all_history_indicator",
                entity_values=member_ids,
                evidence_values=source.get("evidence_fact_ids", []),
                numerator=source.get("numerator"),
                denominator=source.get("denominator"),
            )
        periodized = paths.metrics_dir / "periodized-metrics.json"
        for source in _iter_large_json_array(periodized, "rows"):
            yield metric_row(
                source,
                source_artifact="metrics/periodized-metrics.json#rows",
                record_type="periodized_indicator",
                evidence_values=source.get("evidence_ids", []),
            )
        for source in _iter_large_json_array(periodized, "brand_health_rows"):
            yield metric_row(
                source,
                source_artifact="metrics/periodized-metrics.json#brand_health_rows",
                record_type="periodized_brand_health",
            )
        for relative in REPORT_DOCUMENTS:
            report, _ = _load_object(paths.reports_dir / relative, f"report {relative}")
            for key in ("indicators", "baselines"):
                values = report.get(key, [])
                if not isinstance(values, list):
                    raise ExportBundleError(f"report {relative} {key} is invalid")
                for source in values:
                    if not isinstance(source, dict):
                        raise ExportBundleError("report indicator is invalid")
                    current = source.get("current", source.get("previous", {}))
                    yield metric_row(
                        source,
                        source_artifact=f"reports/{relative}#{key}",
                        record_type=f"report_{key}",
                        evidence_values=_collect_evidence_ids(source),
                        comparison=source.get("comparisons"),
                        numerator=(current or {}).get("numerator")
                        if isinstance(current, dict)
                        else None,
                        denominator=(current or {}).get("denominator")
                        if isinstance(current, dict)
                        else None,
                    )
            brand_key = (
                "brand_health_baselines" if relative.startswith("archive/") else None
            )
            brand_values = (
                report.get(brand_key, [])
                if brand_key
                else report.get("brand_health", {}).get("rows", [])
            )
            if not isinstance(brand_values, list):
                raise ExportBundleError(f"report {relative} brand health is invalid")
            for source in brand_values:
                if not isinstance(source, dict):
                    raise ExportBundleError("report brand health row is invalid")
                yield metric_row(
                    source,
                    source_artifact=f"reports/{relative}#brand_health",
                    record_type="report_brand_health",
                    evidence_values=_collect_evidence_ids(source),
                )

    return _write_rows(destination, rows())


def _governance_entity_refs(
    payload: Mapping[str, Any], entity_ids: set[str]
) -> list[str]:
    resolved: set[str] = set()

    def add(value: object, *, kind: str | None = None) -> None:
        if not isinstance(value, str) or not value:
            return
        reference = value
        if kind == "comment" and not value.startswith(("comment:", "t1_")):
            reference = f"comment:{value}"
        elif kind == "post" and not value.startswith(
            ("post:", "t3_", "external-post:", "external_reddit_post:")
        ):
            reference = f"post:{value}"
        elif kind == "external" and not value.startswith(
            ("external-post:", "external_reddit_post:")
        ):
            reference = f"external-post:{value}"
        resolved.add(_entity_id_from_reference(reference, entity_ids))

    for key in ("canonical_entity_id", "entity_id", "evidence_source_entity_id"):
        add(payload.get(key))
    for key in ("external_reference_id", "reddit_post_id", "reference_id"):
        add(payload.get(key), kind="external")
    for key, kind in (
        ("canonical_root_ids", "post"),
        ("entity_ids", None),
        ("evidence_only_comment_ids", "comment"),
        ("evidence_refs", None),
        ("post_ids", "post"),
    ):
        values = payload.get(key, [])
        if isinstance(values, list):
            for value in values:
                add(value, kind=kind)
    return sorted(resolved)


def _materialize_governance(
    paths: MaterializationPaths,
    metadata: ExportBundleMetadata,
    destination: Path,
    entity_ids: set[str],
    fact_ids: set[str],
) -> int:
    base = _base(metadata)
    sources = (
        (paths.casebook_dir, "casebook", "case-dossiers.jsonl", "case_dossier"),
        (paths.casebook_dir, "casebook", "event-assessments.jsonl", "event_assessment"),
        (
            paths.casebook_dir,
            "casebook",
            "external-governance-facts.jsonl",
            "external_governance_fact",
        ),
        (
            paths.casebook_dir,
            "casebook",
            "action-monitoring-ledger.jsonl",
            "action_monitoring",
        ),
        (paths.integrity_dir, "integrity", "assessments.jsonl", "integrity_assessment"),
        (paths.integrity_dir, "integrity", "clusters.jsonl", "integrity_cluster"),
        (paths.integrity_dir, "integrity", "event-dossiers.jsonl", "integrity_event"),
        (paths.integrity_dir, "integrity", "review-ledger.jsonl", "human_review"),
        (paths.case_reference_dir, "case_reference", "references.jsonl", "reference_case"),
        (
            paths.case_reference_dir,
            "case_reference",
            "external-public-snapshots.jsonl",
            "reference_snapshot",
        ),
    )

    def wrap(
        payload: Mapping[str, Any], source_artifact: str, record_type: str
    ) -> dict[str, Any]:
        fact_values = list(_collect_evidence_ids(payload))
        direct_fact = payload.get("fact_id")
        if isinstance(direct_fact, str):
            fact_values.append(direct_fact)
        identity = sha256_bytes(
            canonical_json_bytes(
                {"payload": payload, "record_type": record_type, "source": source_artifact}
            )
        )
        return {
            **base,
            "case_record_id": f"case:{record_type}:{identity}",
            "entity_refs": _governance_entity_refs(payload, entity_ids),
            "fact_refs": _require_fact_refs(fact_values, fact_ids),
            "lifecycle_status": payload.get(
                "lifecycle_status", payload.get("review_status")
            ),
            "payload": dict(payload),
            "record_type": record_type,
            "schema_version": ROW_SCHEMAS["reddit-governance-casebook.jsonl"],
            "source_artifact": source_artifact,
        }

    def rows() -> Iterator[dict[str, Any]]:
        for directory, prefix, filename, record_type in sources:
            path = directory / filename
            for payload in _iter_jsonl(path, f"governance {prefix}/{filename}"):
                yield wrap(payload, f"{prefix}/{filename}", record_type)
        for filename, record_type in (
            ("lifecycle.json", "integrity_lifecycle"),
            ("sensitivity.json", "integrity_sensitivity"),
        ):
            payload, _ = _load_object(paths.integrity_dir / filename, filename)
            yield wrap(payload, f"integrity/{filename}", record_type)

    return _write_rows(destination, rows())


def materialize_export_inputs(
    paths: MaterializationPaths,
    metadata: ExportBundleMetadata,
    output_root: Path,
    *,
    materializer_code_sha256: str,
) -> tuple[dict[str, Path], dict[str, Any]]:
    """Validate exact V3 inputs and write four canonical export-schema files."""

    if metadata.bundle_mode != "private_audit":
        raise ExportBundleError("real materialization is private_audit only")
    if SHA256_RE.fullmatch(materializer_code_sha256) is None:
        raise ExportBundleError("materializer code SHA-256 is invalid")
    manifests, bindings = _validate_inputs(paths, metadata)
    source_status_counts = _source_status_counts(paths)
    output_root = Path(output_root)
    if output_root.exists() or output_root.is_symlink():
        raise ExportBundleError("materialization output already exists")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    os.mkdir(output_root, 0o700)
    try:
        input_paths = {name: output_root / name for name in ARTIFACT_FILES}
        entity_count, entity_ids, _ = _materialize_entities(
            paths,
            metadata,
            input_paths["reddit-entities-full.jsonl"],
        )
        fact_voc_count, fact_ids = _materialize_facts(
            paths,
            metadata,
            input_paths["reddit-voc-facts.jsonl"],
            entity_ids,
        )
        metric_count = _materialize_metrics(
            paths,
            metadata,
            input_paths["reddit-metrics-reporting.jsonl"],
            entity_ids,
            fact_ids,
        )
        governance_count = _materialize_governance(
            paths,
            metadata,
            input_paths["reddit-governance-casebook.jsonl"],
            entity_ids,
            fact_ids,
        )
        counts = {
            "reddit-entities-full.jsonl": entity_count,
            "reddit-voc-facts.jsonl": fact_voc_count,
            "reddit-metrics-reporting.jsonl": metric_count,
            "reddit-governance-casebook.jsonl": governance_count,
        }
        materialization = {
            "bundle_mode": "private_audit",
            "full_scope_filters": {
                "engagement": False,
                "manual_case": False,
                "sentiment": False,
                "severity": False,
            },
            "materialized_row_counts": counts,
            "materializer_code_sha256": materializer_code_sha256,
            "private_artifact": True,
            "public_distribution_allowed": False,
            "schema_version": MATERIALIZATION_SCHEMA,
            "source_bindings": bindings,
            "source_file_contracts_verified": True,
            "source_status_counts": source_status_counts,
            "website_bundle_included": False,
        }
        _write_rows(
            output_root / "materialization-metadata.jsonl",
            (materialization,),
        )
        metadata_path = output_root / "materialization-metadata.jsonl"
        canonical_path = output_root / "materialization-metadata.json"
        os.replace(metadata_path, canonical_path)
        return input_paths, {**materialization, "manifests": manifests}
    except Exception:
        if output_root.exists():
            shutil.rmtree(output_root)
        raise
