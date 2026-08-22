#!/usr/bin/env python3
"""Independently validate one exact V3 export bundle and write its receipt."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import tempfile
from typing import Any, Callable, Iterable, Iterator, Mapping


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from reddit_voc.v3_export_bundle import (  # noqa: E402
    ARTIFACT_FILES,
    BOUNDARIES,
    MANIFEST_SCHEMA,
    PRIMARY_KEYS,
    PUBLIC_DENIED_FIELDS,
    RECEIPT_SCHEMA,
    RELEASE_RE,
    ROW_SCHEMAS,
    SHA256_RE,
    canonical_json_bytes,
    canonical_json_document,
    sha256_bytes,
)


class ExportBundleValidationError(ValueError):
    """The candidate bundle failed independent validation."""


MATERIALIZATION_SCHEMA = "reddit_voc_export_materialization_v2"
SOURCE_LAYOUT = {
    "canonical": (
        "canonical-candidate-a1/manifest.json",
        "canonical-validation-a1/receipt.json",
        "bundle_manifest_sha256",
    ),
    "case_reference": (
        "case-reference-candidate-a1/manifest.json",
        "case-reference-validation-a1/receipt.json",
        "registry_manifest_sha256",
    ),
    "casebook": (
        "casebook-candidate-a1/manifest.json",
        "casebook-validation-a1/receipt.json",
        "casebook_manifest_sha256",
    ),
    "governed_signals": (
        "governed-signals-candidate-a1/manifest.json",
        "governed-signals-validation-a1/receipt.json",
        "snapshot_manifest_sha256",
    ),
    "integrity": (
        "integrity-candidate-a1/manifest.json",
        "integrity-validation-a1/receipt.json",
        "integrity_manifest_sha256",
    ),
    "integrity_input": (
        "integrity-input-a1/manifest.json",
        "integrity-input-validation-a1/receipt.json",
        "upstream_manifest_sha256",
    ),
    "metrics": (
        "metrics-candidate-a5/manifest.json",
        "metrics-validation-a5/receipt.json",
        "bundle_manifest_sha256",
    ),
    "personas": (
        "personas-candidate-a4/manifest.json",
        "personas-validation-a4/receipt.json",
        "manifest_sha256",
    ),
    "reports": (
        "reports-candidate-a5r2/manifest.json",
        "reports-validation-a5r2/receipt.json",
        "bundle_manifest_sha256",
    ),
    "voc_facts": (
        "voc-facts-candidate-a2/manifest.json",
        "voc-facts-validation-a2/receipt.json",
        "bundle_manifest_sha256",
    ),
}
CURRENT_RELEASE_PATH = "current-release-a5r2/current-release.json"
CURRENT_RELEASE_REQUIRED_COUNTS = {
    "reddit_voc_release_20260716_v3_818f7eae7627_ui2": {
        "canonical_comment_rows": 27148,
        "canonical_post_rows": 3494,
        "external_reference_rows": 1,
        "external_snapshot_rows": 1,
        "linked_comment_rows": 20205,
        "quarantine_rows": 10,
        "unresolved_parent_comment_rows": 6943,
        "unresolved_parent_exclusion_rows": 6943,
        "voc_exclusion_rows": 7066,
    }
}
SOURCE_STATUS_KEYS = frozenset(
    {
        "canonical_comment_rows",
        "canonical_post_rows",
        "external_reference_rows",
        "external_snapshot_rows",
        "linked_comment_rows",
        "quarantine_rows",
        "unresolved_parent_comment_rows",
        "unresolved_parent_exclusion_rows",
        "voc_exclusion_rows",
    }
)


def _safe_source_relative(value: object, label: str) -> str:
    """Accept only a portable path relative to the explicitly supplied root."""

    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ExportBundleValidationError(f"{label} path invalid")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ExportBundleValidationError(f"{label} path invalid")
    return path.as_posix()


def _source_layout(materialization: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    """Resolve the immutable source-tree layout bound into a materialization.

    Older export bundles did not carry a layout and therefore retain their
    historical candidate-directory convention.  New V3 candidates bind their
    own relative paths, which prevents a validator from reopening another
    cycle merely because it happens to use the old directory names.
    """

    raw = materialization.get("source_layout")
    if raw is None:
        resolved = {
            label: {"manifest": manifest, "receipt": receipt}
            for label, (manifest, receipt, _binding) in SOURCE_LAYOUT.items()
        }
        resolved["current_release"] = {"pointer": CURRENT_RELEASE_PATH}
        return resolved
    if not isinstance(raw, Mapping) or set(raw) != {
        *SOURCE_LAYOUT,
        "current_release",
    }:
        raise ExportBundleValidationError("materialization source layout invalid")
    resolved: dict[str, dict[str, str]] = {}
    for label in SOURCE_LAYOUT:
        item = raw.get(label)
        if not isinstance(item, Mapping) or set(item) != {"manifest", "receipt"}:
            raise ExportBundleValidationError("materialization source layout invalid")
        resolved[label] = {
            key: _safe_source_relative(item.get(key), f"{label} {key}")
            for key in ("manifest", "receipt")
        }
    current = raw.get("current_release")
    if not isinstance(current, Mapping) or set(current) != {"pointer"}:
        raise ExportBundleValidationError("materialization source layout invalid")
    resolved["current_release"] = {
        "pointer": _safe_source_relative(
            current.get("pointer"), "current release pointer"
        )
    }
    return resolved
FACT_SOURCE_FILES = {
    "governed_signals/commercial-relation-facts.jsonl",
    "governed_signals/community-governance-facts.jsonl",
    "governed_signals/entity-brand-facts.jsonl",
    "governed_signals/entity-problem-facts.jsonl",
    "governed_signals/entity-product-facts.jsonl",
    "governed_signals/entity-sentiment-facts.jsonl",
    "governed_signals/entity-tag-facts.jsonl",
    "governed_signals/integrity-signal-facts.jsonl",
    "integrity_input/governed-facts.jsonl",
    "casebook/external-governance-facts.jsonl",
    "personas/persona-atomic-facts.jsonl",
}


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


def _safe_directory_chain(path: Path, *, create: bool = False) -> Path:
    absolute = _absolute_path(path)
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            if not create:
                raise ExportBundleValidationError(
                    f"directory chain missing: {current}"
                )
            try:
                os.mkdir(current, 0o700)
            except FileExistsError:
                pass
            metadata = os.lstat(current)
        except OSError as exc:
            raise ExportBundleValidationError(
                f"directory chain unsafe: {current}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ExportBundleValidationError(
                f"directory chain contains symlink or non-directory: {current}"
            )
    return absolute


def _regular_payload(
    path: Path, *, label: str, mode: int | None = None
) -> bytes:
    path = _absolute_path(path)
    _safe_directory_chain(path.parent)
    try:
        path_metadata = os.lstat(path)
    except OSError as exc:
        raise ExportBundleValidationError(f"{label} missing") from exc
    if (
        stat.S_ISLNK(path_metadata.st_mode)
        or not stat.S_ISREG(path_metadata.st_mode)
        or (mode is not None and stat.S_IMODE(path_metadata.st_mode) != mode)
    ):
        raise ExportBundleValidationError(f"{label} unsafe mode or symlink")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ExportBundleValidationError(f"{label} unsafe") from exc
    try:
        before = os.fstat(descriptor)
        if _identity(before) != _identity(path_metadata):
            raise ExportBundleValidationError(f"{label} path changed before read")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        try:
            path_after = os.lstat(path)
        except OSError as exc:
            raise ExportBundleValidationError(f"{label} path changed during read") from exc
    finally:
        os.close(descriptor)
    if (
        _identity(before) != _identity(after)
        or _identity(before) != _identity(path_after)
        or stat.S_ISLNK(path_after.st_mode)
        or not stat.S_ISREG(path_after.st_mode)
    ):
        raise ExportBundleValidationError(f"{label} bytes drift")
    payload = b"".join(chunks)
    if len(payload) != before.st_size:
        raise ExportBundleValidationError(f"{label} bytes drift")
    return payload


def _load_manifest(path: Path, expected_sha: str) -> tuple[dict[str, Any], bytes]:
    if not isinstance(expected_sha, str) or SHA256_RE.fullmatch(expected_sha) is None:
        raise ExportBundleValidationError("expected manifest SHA-256 invalid")
    payload = _regular_payload(path, label="manifest", mode=0o600)
    if sha256_bytes(payload) != expected_sha:
        raise ExportBundleValidationError("manifest SHA-256 mismatch")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExportBundleValidationError("manifest JSON invalid") from exc
    if not isinstance(value, dict) or canonical_json_document(value) != payload:
        raise ExportBundleValidationError("manifest noncanonical")
    return value, payload


def _load_rows(payload: bytes, name: str) -> tuple[dict[str, Any], ...]:
    if payload and not payload.endswith(b"\n"):
        raise ExportBundleValidationError(f"{name} final newline missing")
    rows: list[dict[str, Any]] = []
    for ordinal, line in enumerate(payload.splitlines(), start=1):
        try:
            row = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ExportBundleValidationError(f"{name} row {ordinal} invalid") from exc
        if not isinstance(row, dict) or canonical_json_bytes(row) != line:
            raise ExportBundleValidationError(f"{name} row {ordinal} noncanonical")
        rows.append(row)
    if not rows:
        raise ExportBundleValidationError(f"{name} empty")
    return tuple(rows)


def _denied(value: object) -> str | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in PUBLIC_DENIED_FIELDS:
                return str(key)
            nested = _denied(item)
            if nested is not None:
                return nested
    elif isinstance(value, list):
        for item in value:
            nested = _denied(item)
            if nested is not None:
                return nested
    return None


def _refs(row: Mapping[str, Any], key: str) -> tuple[str, ...]:
    if key not in row:
        raise ExportBundleValidationError(f"{key} missing")
    value = row.get(key)
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item for item in value)
        or value != sorted(set(value))
    ):
        raise ExportBundleValidationError(f"{key} invalid")
    return tuple(value)


def _artifact_contracts(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != len(ARTIFACT_FILES):
        raise ExportBundleValidationError("artifact member set invalid")
    result: dict[str, Mapping[str, Any]] = {}
    for row in artifacts:
        if not isinstance(row, Mapping) or set(row) != {
            "byte_count",
            "path",
            "row_count",
            "sha256",
        }:
            raise ExportBundleValidationError("artifact contract invalid")
        name = row.get("path")
        if not isinstance(name, str) or name in result:
            raise ExportBundleValidationError("artifact path duplicate")
        result[name] = row
    if set(result) != set(ARTIFACT_FILES):
        raise ExportBundleValidationError("artifact member set invalid")
    return result


def _visit_regular_rows(
    path: Path,
    *,
    label: str,
    visitor: Callable[[dict[str, Any], int], None],
    mode: int | None = 0o600,
) -> dict[str, object]:
    path = _absolute_path(path)
    _safe_directory_chain(path.parent)
    try:
        path_metadata = os.lstat(path)
    except OSError as exc:
        raise ExportBundleValidationError(f"{label} missing") from exc
    if (
        stat.S_ISLNK(path_metadata.st_mode)
        or not stat.S_ISREG(path_metadata.st_mode)
        or (mode is not None and stat.S_IMODE(path_metadata.st_mode) != mode)
    ):
        raise ExportBundleValidationError(f"{label} unsafe mode or symlink")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    digest = sha256()
    byte_count = 0
    row_count = 0
    try:
        before = os.fstat(descriptor)
        if _identity(before) != _identity(path_metadata):
            raise ExportBundleValidationError(f"{label} path changed before read")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            while True:
                line_with_newline = handle.readline()
                if not line_with_newline:
                    break
                row_count += 1
                byte_count += len(line_with_newline)
                digest.update(line_with_newline)
                if not line_with_newline.endswith(b"\n"):
                    raise ExportBundleValidationError(
                        f"{label} final newline missing or bytes drift"
                    )
                line = line_with_newline[:-1]
                try:
                    row = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ExportBundleValidationError(
                        f"{label} row {row_count} invalid"
                    ) from exc
                if not isinstance(row, dict) or canonical_json_bytes(row) != line:
                    raise ExportBundleValidationError(
                        f"{label} row {row_count} noncanonical"
                    )
                visitor(row, row_count)
        after = os.fstat(descriptor)
        try:
            path_after = os.lstat(path)
        except OSError as exc:
            raise ExportBundleValidationError(f"{label} path changed during read") from exc
    finally:
        os.close(descriptor)
    if (
        row_count == 0
        or byte_count != before.st_size
        or _identity(before) != _identity(after)
        or _identity(before) != _identity(path_after)
        or stat.S_ISLNK(path_after.st_mode)
        or not stat.S_ISREG(path_after.st_mode)
    ):
        reason = "empty" if row_count == 0 else "bytes drift"
        raise ExportBundleValidationError(f"{label} {reason}")
    return {
        "byte_count": byte_count,
        "row_count": row_count,
        "sha256": digest.hexdigest(),
    }


def _required_object(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ExportBundleValidationError(f"{label} missing or invalid")
    return value


def _required_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ExportBundleValidationError(f"{label} missing or invalid")
    return value


def _string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ExportBundleValidationError(f"{label} missing or invalid")
    return list(value)


def _derived_fact_id(kind: str, payload: Mapping[str, Any]) -> str:
    digest = sha256(kind.encode("utf-8") + b"\0" + canonical_json_bytes(payload))
    return f"{kind}:{digest.hexdigest()}"


def _expected_fact_id(
    payload: Mapping[str, Any], source_artifact: str
) -> str:
    if source_artifact == "voc_facts/automation-classifications.jsonl":
        return _derived_fact_id("automation", payload)
    if source_artifact == "voc_facts/voc-exclusions.jsonl":
        return _derived_fact_id("voc_exclusion", payload)
    if source_artifact not in FACT_SOURCE_FILES:
        raise ExportBundleValidationError("fact source artifact is unsupported")
    return _required_string(payload.get("fact_id"), "payload fact_id")


def _independent_primary(name: str, row: Mapping[str, Any]) -> str:
    payload = _required_object(row.get("payload"), f"{name} payload")
    if name == "reddit-entities-full.jsonl":
        provenance = _required_object(
            row.get("source_provenance"), "entity source_provenance"
        )
        source_artifact = _required_string(
            provenance.get("source_artifact"), "entity source artifact"
        )
        if source_artifact in {
            "canonical/posts.jsonl",
            "canonical/comments.jsonl",
            "canonical/quarantine.jsonl",
        }:
            expected = _required_string(
                payload.get("canonical_reddit_id"), "canonical entity identity"
            )
        elif source_artifact == "case_reference/external-public-snapshots.jsonl":
            expected = "external_reddit_post:" + _required_string(
                payload.get("reddit_post_id"), "external Reddit post identity"
            )
        else:
            raise ExportBundleValidationError("entity source artifact is unsupported")
        if row.get("entity_id") != expected:
            raise ExportBundleValidationError(
                "entity_id does not match independent payload derivation"
            )
        return expected
    if name == "reddit-voc-facts.jsonl":
        source_artifact = _required_string(
            row.get("source_artifact"), "VOC/fact source artifact"
        )
        kind = row.get("record_kind")
        if kind == "voc":
            if source_artifact != "voc_facts/vocs.jsonl":
                raise ExportBundleValidationError("VOC source artifact is unsupported")
            voc_id = _required_string(payload.get("voc_id"), "payload voc_id")
            if row.get("voc_id") != voc_id:
                raise ExportBundleValidationError(
                    "voc_id does not match independent payload derivation"
                )
            expected = f"voc:{voc_id}"
        elif kind == "fact":
            fact_id = _expected_fact_id(payload, source_artifact)
            if row.get("fact_id") != fact_id:
                raise ExportBundleValidationError(
                    "fact_id does not match independent payload derivation"
                )
            expected = f"fact:{fact_id}"
        else:
            raise ExportBundleValidationError("VOC/fact record kind invalid")
        if row.get("record_id") != expected:
            raise ExportBundleValidationError(
                "record_id does not match independent payload derivation"
            )
        return expected
    if name == "reddit-metrics-reporting.jsonl":
        record_type = _required_string(row.get("record_type"), "metric record_type")
        source_artifact = _required_string(
            row.get("source_artifact"), "metric source artifact"
        )
        digest = sha256_bytes(
            canonical_json_bytes(
                {
                    "payload": payload,
                    "record_type": record_type,
                    "source": source_artifact,
                }
            )
        )
        expected = f"metric:{record_type}:{digest}"
        if row.get("metric_record_id") != expected:
            raise ExportBundleValidationError(
                "metric_record_id does not match independent payload derivation"
            )
        return expected
    if name == "reddit-governance-casebook.jsonl":
        record_type = _required_string(
            row.get("record_type"), "governance record_type"
        )
        source_artifact = _required_string(
            row.get("source_artifact"), "governance source artifact"
        )
        digest = sha256_bytes(
            canonical_json_bytes(
                {
                    "payload": payload,
                    "record_type": record_type,
                    "source": source_artifact,
                }
            )
        )
        expected = f"case:{record_type}:{digest}"
        if row.get("case_record_id") != expected:
            raise ExportBundleValidationError(
                "case_record_id does not match independent payload derivation"
            )
        return expected
    raise ExportBundleValidationError("unknown export artifact")


def _resolve_entity_reference(value: str, entity_ids: set[str]) -> str:
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
    elif value.startswith(("t1_", "t3_", "external_reddit_post:")):
        candidate = value
    else:
        candidate = f"t3_{value}"
        external = f"external_reddit_post:{value}"
        if external in entity_ids:
            candidate = external
    if candidate not in entity_ids:
        raise ExportBundleValidationError(
            f"payload entity reference is unresolved: {value}"
        )
    return candidate


def _collect_evidence_ids(value: object) -> Iterator[str]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in {"evidence_ids", "evidence_fact_ids"}:
                for candidate in _string_list(item, f"payload {key}"):
                    yield candidate
            else:
                yield from _collect_evidence_ids(item)
    elif isinstance(value, list):
        for item in value:
            yield from _collect_evidence_ids(item)


def _governance_entity_refs(
    payload: Mapping[str, Any], entity_ids: set[str]
) -> list[str]:
    resolved: set[str] = set()

    def add(value: object, *, kind: str | None = None) -> None:
        if value is None:
            return
        value = _required_string(value, "governance entity reference")
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
        resolved.add(_resolve_entity_reference(reference, entity_ids))

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
        if key not in payload:
            continue
        for value in _string_list(payload.get(key), f"payload {key}"):
            add(value, kind=kind)
    return sorted(resolved)


def _independent_refs(
    name: str,
    row: Mapping[str, Any],
    entity_ids: set[str],
    fact_ids: set[str],
) -> tuple[list[str], list[str]]:
    payload = _required_object(row.get("payload"), f"{name} payload")
    entity_refs: list[str]
    fact_refs: list[str]
    if name == "reddit-entities-full.jsonl":
        entity_refs, fact_refs = [], []
    elif name == "reddit-voc-facts.jsonl":
        source_artifact = _required_string(
            row.get("source_artifact"), "VOC/fact source artifact"
        )
        if row.get("record_kind") == "voc":
            values = [
                _required_string(
                    payload.get("canonical_entity_id"), "VOC canonical_entity_id"
                )
            ]
        elif source_artifact in FACT_SOURCE_FILES - {
            "personas/persona-atomic-facts.jsonl"
        }:
            values = [
                _required_string(
                    payload.get("canonical_entity_id"), "fact canonical_entity_id"
                )
            ]
            evidence_entity = payload.get("evidence_source_entity_id")
            if evidence_entity is not None:
                values.append(
                    _required_string(evidence_entity, "fact evidence_source_entity_id")
                )
        elif source_artifact in {
            "personas/persona-atomic-facts.jsonl",
            "voc_facts/automation-classifications.jsonl",
            "voc_facts/voc-exclusions.jsonl",
        }:
            values = [
                _required_string(
                    payload.get("canonical_entity_id"), "fact canonical_entity_id"
                )
            ]
        else:
            raise ExportBundleValidationError("fact source artifact is unsupported")
        entity_refs = sorted(
            {_resolve_entity_reference(value, entity_ids) for value in values}
        )
        fact_refs = []
    elif name == "reddit-metrics-reporting.jsonl":
        source_artifact = _required_string(
            row.get("source_artifact"), "metric source artifact"
        )
        record_type = _required_string(row.get("record_type"), "metric record_type")
        values: list[str] = []
        evidence: Iterable[str] = ()
        if source_artifact == "metrics/metrics.json":
            if record_type != "all_history_indicator":
                raise ExportBundleValidationError("metric record_type is unsupported")
            for key in (
                "denominator_member_ids",
                "metric_eligible_member_ids",
                "numerator_member_ids",
            ):
                values.extend(_string_list(payload.get(key), f"payload {key}"))
            evidence = _string_list(
                payload.get("evidence_fact_ids"), "payload evidence_fact_ids"
            )
        elif source_artifact == "metrics/periodized-metrics.json#rows":
            if record_type != "periodized_indicator":
                raise ExportBundleValidationError("metric record_type is unsupported")
            evidence = _string_list(payload.get("evidence_ids"), "payload evidence_ids")
        elif source_artifact == "metrics/periodized-metrics.json#brand_health_rows":
            if record_type != "periodized_brand_health":
                raise ExportBundleValidationError("metric record_type is unsupported")
        elif source_artifact.startswith("reports/"):
            if not record_type.startswith("report_"):
                raise ExportBundleValidationError("report record_type is unsupported")
            evidence = _collect_evidence_ids(payload)
        else:
            raise ExportBundleValidationError("metric source artifact is unsupported")
        entity_refs = sorted(
            {_resolve_entity_reference(value, entity_ids) for value in values}
        )
        fact_refs = sorted(set(evidence))
    elif name == "reddit-governance-casebook.jsonl":
        entity_refs = _governance_entity_refs(payload, entity_ids)
        evidence = list(_collect_evidence_ids(payload))
        if isinstance(payload.get("fact_id"), str) and payload["fact_id"]:
            evidence.append(str(payload["fact_id"]))
        fact_refs = sorted(set(evidence))
    else:
        raise ExportBundleValidationError("unknown export artifact")
    missing = [value for value in fact_refs if value not in fact_ids]
    if missing:
        raise ExportBundleValidationError(
            f"payload fact reference is unresolved: {missing[0]}"
        )
    reported_entity_refs = list(_refs(row, "entity_refs"))
    reported_fact_refs = list(_refs(row, "fact_refs"))
    if reported_entity_refs != entity_refs:
        raise ExportBundleValidationError(
            f"{name} unresolved entity or entity_refs do not match independent payload derivation"
        )
    if reported_fact_refs != fact_refs:
        raise ExportBundleValidationError(
            f"{name} fact_refs do not match independent payload derivation"
        )
    return entity_refs, fact_refs


def _load_source_object(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    payload = _regular_payload(path, label=label)
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ExportBundleValidationError(f"{label} invalid JSON") from exc
    if not isinstance(value, dict):
        raise ExportBundleValidationError(f"{label} must be an object")
    return value, payload


def _regular_source_sha_size(path: Path, label: str) -> tuple[str, int]:
    path = _absolute_path(path)
    _safe_directory_chain(path.parent)
    try:
        path_metadata = os.lstat(path)
    except OSError as exc:
        raise ExportBundleValidationError(f"{label} missing") from exc
    if stat.S_ISLNK(path_metadata.st_mode) or not stat.S_ISREG(path_metadata.st_mode):
        raise ExportBundleValidationError(f"{label} unsafe")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    digest = sha256()
    size = 0
    try:
        before = os.fstat(descriptor)
        if _identity(before) != _identity(path_metadata):
            raise ExportBundleValidationError(f"{label} path changed before read")
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
        raise ExportBundleValidationError(f"{label} bytes drift")
    return digest.hexdigest(), size


def _validate_declared_source_files(
    directory: Path, manifest: Mapping[str, Any], label: str
) -> None:
    files = manifest.get("files")
    if not isinstance(files, Mapping) or not files:
        raise ExportBundleValidationError(f"{label} source files missing")
    root = _absolute_path(directory)
    _safe_directory_chain(root)
    for relative, contract in files.items():
        if (
            not isinstance(relative, str)
            or not isinstance(contract, Mapping)
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
        ):
            raise ExportBundleValidationError(f"{label} source contract invalid")
        path = _absolute_path(root / relative)
        if os.path.commonpath((str(root), str(path))) != str(root):
            raise ExportBundleValidationError(f"{label} source path escapes root")
        actual_sha, actual_size = _regular_source_sha_size(
            path, f"{label} source artifact {relative}"
        )
        declared_size = contract.get("bytes", contract.get("byte_count"))
        if contract.get("sha256") != actual_sha or declared_size != actual_size:
            raise ExportBundleValidationError(
                f"{label} source artifact contract drift: {relative}"
            )


def _visit_source_rows(
    path: Path, label: str, visitor: Callable[[Mapping[str, Any]], None]
) -> int:
    count = 0

    def visit(row: dict[str, Any], _ordinal: int) -> None:
        nonlocal count
        count += 1
        visitor(row)

    result = _visit_regular_rows(path, label=label, visitor=visit, mode=None)
    return int(result["row_count"])


def _source_status_counts(
    candidate_root: Path, layout: Mapping[str, Mapping[str, str]]
) -> dict[str, int]:
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

    def comment(row: Mapping[str, Any]) -> None:
        state = row.get("comment_state")
        counts["canonical_comment_rows"] += 1
        if state == "linked":
            counts["linked_comment_rows"] += 1
        elif state == "unresolved_parent":
            counts["unresolved_parent_comment_rows"] += 1
        else:
            raise ExportBundleValidationError(
                f"unexpected canonical comment state: {state}"
            )

    def exclusion(row: Mapping[str, Any]) -> None:
        reasons = _string_list(row.get("reason_codes"), "source exclusion reason_codes")
        counts["voc_exclusion_rows"] += 1
        if "unresolved_parent" in reasons:
            counts["unresolved_parent_exclusion_rows"] += 1

    source_directory = {
        label: Path(layout[label]["manifest"]).parent
        for label in ("canonical", "case_reference", "voc_facts")
    }
    sources = (
        (
            source_directory["canonical"] / "posts.jsonl",
            "source posts",
            lambda _row: counts.__setitem__(
                "canonical_post_rows", counts["canonical_post_rows"] + 1
            ),
        ),
        (
            source_directory["canonical"] / "comments.jsonl",
            "source comments",
            comment,
        ),
        (
            source_directory["canonical"] / "quarantine.jsonl",
            "source quarantine",
            lambda _row: counts.__setitem__(
                "quarantine_rows", counts["quarantine_rows"] + 1
            ),
        ),
        (
            source_directory["case_reference"] / "references.jsonl",
            "source external references",
            lambda _row: counts.__setitem__(
                "external_reference_rows", counts["external_reference_rows"] + 1
            ),
        ),
        (
            source_directory["case_reference"] / "external-public-snapshots.jsonl",
            "source external snapshots",
            lambda _row: counts.__setitem__(
                "external_snapshot_rows", counts["external_snapshot_rows"] + 1
            ),
        ),
        (
            source_directory["voc_facts"] / "voc-exclusions.jsonl",
            "source exclusions",
            exclusion,
        ),
    )
    for relative, label, visitor in sources:
        _visit_source_rows(candidate_root / relative, label, visitor)
    return counts


def _validate_bound_sources(
    candidate_root: Path,
    materialization: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> dict[str, int]:
    candidate_root = _safe_directory_chain(candidate_root)
    source_bindings = _required_object(
        materialization.get("source_bindings"), "source bindings"
    )
    layout = _source_layout(materialization)
    source_manifests: dict[str, dict[str, Any]] = {}
    for label, (_default_manifest, _default_receipt, receipt_binding_key) in SOURCE_LAYOUT.items():
        manifest_rel = layout[label]["manifest"]
        receipt_rel = layout[label]["receipt"]
        binding = _required_object(source_bindings.get(label), f"{label} binding")
        source_manifest, manifest_payload = _load_source_object(
            candidate_root / manifest_rel, f"{label} manifest"
        )
        manifest_sha = sha256_bytes(manifest_payload)
        if binding.get("manifest_sha256") != manifest_sha:
            raise ExportBundleValidationError(f"{label} manifest binding mismatch")
        receipt, receipt_payload = _load_source_object(
            candidate_root / receipt_rel, f"{label} receipt"
        )
        if (
            binding.get("validation_receipt_sha256")
            != sha256_bytes(receipt_payload)
            or receipt.get("status") not in {"passed", "passed_candidate_only"}
            or receipt.get(receipt_binding_key) != manifest_sha
        ):
            raise ExportBundleValidationError(f"{label} receipt binding mismatch")
        _validate_declared_source_files(
            (candidate_root / manifest_rel).parent, source_manifest, label
        )
        source_manifests[label] = source_manifest

    current_binding = _required_object(
        source_bindings.get("current_release"), "current release binding"
    )
    current_release, current_payload = _load_source_object(
        candidate_root / layout["current_release"]["pointer"], "current release"
    )
    if (
        current_binding.get("manifest_sha256") != sha256_bytes(current_payload)
        or current_binding.get("validation_receipt_sha256") is not None
        or current_release.get("release_id") != manifest.get("release_id")
    ):
        raise ExportBundleValidationError("current release binding mismatch")
    datasets = _required_object(current_release.get("datasets"), "current datasets")
    for key, label in (
        ("base", "canonical"),
        ("reports", "reports"),
        ("personas", "personas"),
    ):
        dataset = _required_object(datasets.get(key), f"current {key} dataset")
        if dataset.get("lineage_manifest_sha256") != source_bindings[label].get(
            "manifest_sha256"
        ):
            raise ExportBundleValidationError(f"current release {key} lineage mismatch")
    source_snapshot_id = manifest.get("source_snapshot_id")
    if (
        source_manifests["governed_signals"].get("source_snapshot_id")
        != source_snapshot_id
        or source_manifests["integrity"].get("source_snapshot_id")
        != source_snapshot_id
        or source_manifests["integrity_input"].get("source_snapshot_id")
        != source_snapshot_id
        or source_manifests["casebook"].get("source_snapshot_id")
        != source_snapshot_id
        or source_manifests["reports"].get("source_snapshot_id")
        != source_snapshot_id
        or source_manifests["personas"].get("governed_signal_source_snapshot_id")
        != source_snapshot_id
        or not str(source_manifests["canonical"].get("dataset_id", "")).startswith(
            str(source_snapshot_id)
        )
        or not str(source_manifests["voc_facts"].get("dataset_id", "")).startswith(
            str(source_snapshot_id)
        )
    ):
        raise ExportBundleValidationError("bound source snapshot mismatch")
    facts_inputs = _required_object(
        source_manifests["voc_facts"].get("inputs"), "VOC facts inputs"
    )
    governed_inputs = _required_object(
        source_manifests["governed_signals"].get("inputs"),
        "governed signal inputs",
    )
    casebook_inputs = _required_object(
        source_manifests["casebook"].get("inputs"), "casebook inputs"
    )
    facts_binding = _required_object(source_bindings["voc_facts"], "facts binding")
    governed_binding = _required_object(
        source_bindings["governed_signals"], "governed binding"
    )
    if (
        facts_inputs.get("canonical_manifest_sha256")
        != source_bindings["canonical"].get("manifest_sha256")
        or facts_inputs.get("eligibility_policy_sha256")
        != manifest.get("eligibility_policy_sha256")
        or governed_inputs.get("facts_manifest_sha256")
        != facts_binding.get("manifest_sha256")
        or governed_inputs.get("facts_receipt_sha256")
        != facts_binding.get("validation_receipt_sha256")
        or governed_inputs.get("dim_tag_sha256")
        != manifest.get("dictionary_sha256")
        or source_manifests["metrics"].get("registry_sha256")
        != manifest.get("indicator_registry_sha256")
        or source_manifests["reports"].get("metrics_candidate_manifest_sha256")
        != source_bindings["metrics"].get("manifest_sha256")
        or casebook_inputs.get("facts_manifest_sha256")
        != facts_binding.get("manifest_sha256")
        or casebook_inputs.get("governed_manifest_sha256")
        != governed_binding.get("manifest_sha256")
        or casebook_inputs.get("reference_registry_manifest_sha256")
        != source_bindings["case_reference"].get("manifest_sha256")
        or source_manifests["integrity"].get("upstream_manifest_sha256")
        != source_bindings["integrity_input"].get("manifest_sha256")
    ):
        raise ExportBundleValidationError("bound source lineage mismatch")
    counts = _source_status_counts(candidate_root, layout)
    if materialization.get("source_status_counts") != counts:
        raise ExportBundleValidationError("bound source status counts mismatch")
    required_counts = CURRENT_RELEASE_REQUIRED_COUNTS.get(str(manifest.get("release_id")))
    if required_counts is not None and counts != required_counts:
        raise ExportBundleValidationError("current release required counts mismatch")
    return counts


def _validate_materialization(manifest: Mapping[str, Any]) -> dict[str, Any] | None:
    value = manifest.get("materialization")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ExportBundleValidationError("materialization contract invalid")
    expected_materializer_sha = sha256_bytes(
        (ROOT / "src/reddit_voc/v3_export_materializer.py").read_bytes()
    )
    filters = value.get("full_scope_filters")
    source_bindings = value.get("source_bindings")
    source_status_counts = value.get("source_status_counts")
    if (
        value.get("schema_version") != MATERIALIZATION_SCHEMA
        or value.get("materializer_code_sha256") != expected_materializer_sha
        or value.get("bundle_mode") != "private_audit"
        or manifest.get("bundle_mode") != "private_audit"
        or value.get("private_artifact") is not True
        or value.get("public_distribution_allowed") is not False
        or value.get("website_bundle_included") is not False
        or value.get("source_file_contracts_verified") is not True
        or not isinstance(filters, dict)
        or filters
        != {
            "engagement": False,
            "manual_case": False,
            "sentiment": False,
            "severity": False,
        }
        or not isinstance(source_bindings, dict)
        or set(source_bindings)
        != {
            "canonical",
            "case_reference",
            "casebook",
            "current_release",
            "governed_signals",
            "integrity",
            "integrity_input",
            "metrics",
            "personas",
            "reports",
            "voc_facts",
        }
        or not isinstance(source_status_counts, dict)
        or set(source_status_counts) != SOURCE_STATUS_KEYS
        or any(
            not isinstance(count, int) or isinstance(count, bool) or count < 0
            for count in source_status_counts.values()
        )
    ):
        raise ExportBundleValidationError("materialization contract invalid")
    for label, binding in source_bindings.items():
        if not isinstance(binding, dict):
            raise ExportBundleValidationError(
                f"materialization source binding invalid: {label}"
            )
        manifest_sha = binding.get("manifest_sha256")
        receipt_sha = binding.get("validation_receipt_sha256")
        if not isinstance(manifest_sha, str) or SHA256_RE.fullmatch(manifest_sha) is None:
            raise ExportBundleValidationError(
                f"materialization source manifest invalid: {label}"
            )
        if receipt_sha is not None and (
            not isinstance(receipt_sha, str)
            or SHA256_RE.fullmatch(receipt_sha) is None
        ):
            raise ExportBundleValidationError(
                f"materialization source receipt invalid: {label}"
            )
    _source_layout(value)
    return value


def validate_export_bundle(
    bundle_root: Path,
    *,
    expected_manifest_sha256: str,
    candidate_root: Path | None = None,
) -> dict[str, Any]:
    bundle_root = _safe_directory_chain(bundle_root)
    try:
        root_metadata = os.lstat(bundle_root)
    except OSError as exc:
        raise ExportBundleValidationError("bundle root missing") from exc
    if (
        stat.S_ISLNK(root_metadata.st_mode)
        or not stat.S_ISDIR(root_metadata.st_mode)
        or stat.S_IMODE(root_metadata.st_mode) != 0o700
    ):
        raise ExportBundleValidationError("bundle root unsafe mode or symlink")
    entries = {path.name for path in bundle_root.iterdir()}
    if entries != set(ARTIFACT_FILES) | {"manifest.json"}:
        raise ExportBundleValidationError("bundle contains unknown member")
    manifest, manifest_payload = _load_manifest(
        bundle_root / "manifest.json", expected_manifest_sha256
    )
    if (
        manifest.get("schema_version") != MANIFEST_SCHEMA
        or manifest.get("status") != "candidate_built"
        or manifest.get("consumption_status")
        != "candidate_pending_independent_validation"
        or manifest.get("promotable") is not False
        or manifest.get("boundaries") != BOUNDARIES
        or manifest.get("validation_receipt_sha256") is not None
        or manifest.get("bundle_mode") not in {"public", "private_audit"}
        or not isinstance(manifest.get("export_bundle_id"), str)
        or not manifest["export_bundle_id"]
        or not isinstance(manifest.get("release_id"), str)
        or RELEASE_RE.fullmatch(str(manifest["release_id"])) is None
        or not isinstance(manifest.get("source_snapshot_id"), str)
        or not manifest["source_snapshot_id"]
        or not isinstance(manifest.get("source_cutoff_value"), str)
        or not manifest["source_cutoff_value"]
        or manifest.get("source_cutoff_precision") not in {"instant", "hour", "day"}
        or manifest.get("source_timezone_status")
        not in {"known", "known_from_aware_instant", "unknown_floating_date"}
    ):
        raise ExportBundleValidationError("manifest lifecycle or identity invalid")
    for key in (
        "dictionary_sha256",
        "indicator_registry_sha256",
        "eligibility_policy_sha256",
        "builder_code_sha256",
        "validator_code_sha256",
        "candidate_release_sha256",
    ):
        if not isinstance(manifest.get(key), str) or SHA256_RE.fullmatch(str(manifest[key])) is None:
            raise ExportBundleValidationError(f"manifest {key} invalid")
    expected_builder_code_sha = sha256_bytes(
        (ROOT / "scripts/build_reddit_voc_export_bundle.py").read_bytes()
    )
    expected_validator_code_sha = sha256_bytes(Path(__file__).read_bytes())
    if manifest.get("builder_code_sha256") != expected_builder_code_sha:
        raise ExportBundleValidationError("builder code SHA-256 mismatch")
    if manifest.get("validator_code_sha256") != expected_validator_code_sha:
        raise ExportBundleValidationError("validator code SHA-256 mismatch")
    materialization = _validate_materialization(manifest)
    source_status_counts: dict[str, int] | None = None
    if materialization is not None:
        if candidate_root is None:
            raise ExportBundleValidationError(
                "candidate_root is required for real materialization validation"
            )
        source_status_counts = _validate_bound_sources(
            candidate_root, materialization, manifest
        )
    contracts = _artifact_contracts(manifest)
    primary_sets: dict[str, set[str]] = {}
    fact_ids: set[str] = set()
    row_counts: dict[str, int] = {}
    fact_rows = 0
    voc_rows = 0
    bundle_status_counts = {key: 0 for key in SOURCE_STATUS_KEYS}
    for name in ARTIFACT_FILES:
        contract = contracts[name]
        primary_key = PRIMARY_KEYS[name]
        seen: set[str] = set()
        local_fact_rows = 0
        local_voc_rows = 0

        def visit(row: dict[str, Any], _ordinal: int) -> None:
            nonlocal local_fact_rows, local_voc_rows
            if (
                row.get("schema_version") != ROW_SCHEMAS[name]
                or row.get("export_bundle_id") != manifest["export_bundle_id"]
                or row.get("release_id") != manifest["release_id"]
                or row.get("source_snapshot_id") != manifest["source_snapshot_id"]
            ):
                raise ExportBundleValidationError(
                    f"{name} release_id or source snapshot mismatch"
                )
            primary = _independent_primary(name, row)
            if row.get(primary_key) != primary or primary in seen:
                raise ExportBundleValidationError(f"{name} primary identity invalid")
            seen.add(primary)
            _refs(row, "entity_refs")
            _refs(row, "fact_refs")
            payload = _required_object(row.get("payload"), f"{name} payload")
            if name == "reddit-entities-full.jsonl":
                provenance = _required_object(
                    row.get("source_provenance"), "entity source_provenance"
                )
                source_artifact = provenance.get("source_artifact")
                if source_artifact == "canonical/posts.jsonl":
                    bundle_status_counts["canonical_post_rows"] += 1
                elif source_artifact == "canonical/comments.jsonl":
                    bundle_status_counts["canonical_comment_rows"] += 1
                    state = payload.get("comment_state")
                    if state == "linked":
                        bundle_status_counts["linked_comment_rows"] += 1
                    elif state == "unresolved_parent":
                        bundle_status_counts["unresolved_parent_comment_rows"] += 1
                    else:
                        raise ExportBundleValidationError(
                            f"unexpected exported comment state: {state}"
                        )
                elif source_artifact == "canonical/quarantine.jsonl":
                    bundle_status_counts["quarantine_rows"] += 1
                elif (
                    source_artifact
                    == "case_reference/external-public-snapshots.jsonl"
                ):
                    bundle_status_counts["external_reference_rows"] += 1
                    bundle_status_counts["external_snapshot_rows"] += 1
            if name == "reddit-voc-facts.jsonl":
                kind = row.get("record_kind")
                if kind == "fact":
                    fact_id = _expected_fact_id(
                        payload,
                        _required_string(
                            row.get("source_artifact"), "fact source artifact"
                        ),
                    )
                    if fact_id in fact_ids:
                        raise ExportBundleValidationError(
                            "fact export identity is duplicated"
                        )
                    fact_ids.add(fact_id)
                    local_fact_rows += 1
                    if (
                        row.get("source_artifact")
                        == "voc_facts/voc-exclusions.jsonl"
                    ):
                        reasons = _string_list(
                            payload.get("reason_codes"),
                            "export exclusion reason_codes",
                        )
                        bundle_status_counts["voc_exclusion_rows"] += 1
                        if "unresolved_parent" in reasons:
                            bundle_status_counts[
                                "unresolved_parent_exclusion_rows"
                            ] += 1
                elif kind == "voc":
                    local_voc_rows += 1
                else:
                    raise ExportBundleValidationError("VOC/fact record kind invalid")
            if manifest["bundle_mode"] == "public":
                denied = _denied(row)
                if denied is not None:
                    raise ExportBundleValidationError(
                        f"public bundle denied field: {denied}"
                    )

        actual = _visit_regular_rows(
            bundle_root / name,
            label=name,
            visitor=visit,
        )
        if (
            contract.get("byte_count") != actual["byte_count"]
            or contract.get("row_count") != actual["row_count"]
            or contract.get("sha256") != actual["sha256"]
        ):
            raise ExportBundleValidationError(
                f"{name} bytes drift or contract mismatch"
            )
        primary_sets[name] = seen
        row_counts[name] = int(actual["row_count"])
        fact_rows += local_fact_rows
        voc_rows += local_voc_rows

    if materialization is not None and materialization.get(
        "materialized_row_counts"
    ) != row_counts:
        raise ExportBundleValidationError(
            "materialization row counts do not match artifact replay"
        )
    if source_status_counts is not None and bundle_status_counts != source_status_counts:
        raise ExportBundleValidationError(
            "bundle status distribution does not match bound source"
        )

    entity_ids = primary_sets["reddit-entities-full.jsonl"]
    entity_ref_count = 0
    fact_ref_count = 0
    unresolved_entity = 0
    unresolved_fact = 0
    for name in ARTIFACT_FILES:
        def visit_refs(row: dict[str, Any], _ordinal: int) -> None:
            nonlocal entity_ref_count, fact_ref_count
            nonlocal unresolved_entity, unresolved_fact
            entity_refs, fact_refs = _independent_refs(
                name, row, entity_ids, fact_ids
            )
            entity_ref_count += len(entity_refs)
            fact_ref_count += len(fact_refs)
            unresolved_entity += sum(ref not in entity_ids for ref in entity_refs)
            unresolved_fact += sum(ref not in fact_ids for ref in fact_refs)

        replay = _visit_regular_rows(
            bundle_root / name,
            label=name,
            visitor=visit_refs,
        )
        contract = contracts[name]
        if (
            contract.get("byte_count") != replay["byte_count"]
            or contract.get("row_count") != replay["row_count"]
            or contract.get("sha256") != replay["sha256"]
        ):
            raise ExportBundleValidationError(
                f"{name} bytes drift or contract mismatch"
            )
    if unresolved_entity:
        raise ExportBundleValidationError("unresolved entity references")
    if unresolved_fact:
        raise ExportBundleValidationError("unresolved fact references")
    expected_cross = {
        "entity_reference_count": entity_ref_count,
        "entity_rows": row_counts["reddit-entities-full.jsonl"],
        "fact_rows": fact_rows,
        "fact_reference_count": fact_ref_count,
        "governance_case_rows": row_counts[
            "reddit-governance-casebook.jsonl"
        ],
        "metric_reporting_rows": row_counts[
            "reddit-metrics-reporting.jsonl"
        ],
        "resolved_entity_references": entity_ref_count,
        "resolved_fact_references": fact_ref_count,
        "unresolved_entity_references": 0,
        "unresolved_fact_references": 0,
        "voc_rows": voc_rows,
    }
    if manifest.get("cross_reference_counts") != expected_cross:
        raise ExportBundleValidationError("cross reference counts mismatch")
    return {
        "artifact_count": len(ARTIFACT_FILES),
        "boundaries": dict(BOUNDARIES),
        "consumption_status": "eligible_for_local_candidate_registry",
        "cross_reference_counts": expected_cross,
        "export_bundle_id": manifest["export_bundle_id"],
        "export_bundle_manifest_sha256": sha256_bytes(manifest_payload),
        "full_byte_independent_replay": True,
        "bundle_mode": manifest["bundle_mode"],
        "materialization": materialization,
        "private_artifact": manifest["bundle_mode"] == "private_audit",
        "promotable": True,
        "release_id": manifest["release_id"],
        "schema_version": RECEIPT_SCHEMA,
        "source_snapshot_id": manifest["source_snapshot_id"],
        "source_bindings_reopened": materialization is not None,
        "source_status_counts": source_status_counts,
        "status": "passed",
    }


def write_receipt(path: Path, result: Mapping[str, Any]) -> str:
    path = _absolute_path(path)
    payload = canonical_json_document(dict(result))
    _safe_directory_chain(path.parent, create=True)
    if os.path.lexists(path):
        existing = _regular_payload(path, label="validation receipt", mode=0o600)
        if existing != payload:
            raise ExportBundleValidationError("validation receipt collision")
        return "no_change"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.chmod(temporary, 0o600)
        _safe_directory_chain(path.parent)
        temporary_metadata = os.lstat(temporary)
        if stat.S_ISLNK(temporary_metadata.st_mode) or not stat.S_ISREG(
            temporary_metadata.st_mode
        ):
            raise ExportBundleValidationError("validation receipt staging unsafe")
        os.replace(temporary, path)
        final_metadata = os.lstat(path)
        if (
            stat.S_ISLNK(final_metadata.st_mode)
            or not stat.S_ISREG(final_metadata.st_mode)
            or stat.S_IMODE(final_metadata.st_mode) != 0o600
        ):
            raise ExportBundleValidationError("validation receipt final path unsafe")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()
    return "created"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = validate_export_bundle(
            args.bundle_root,
            expected_manifest_sha256=args.expected_manifest_sha256,
            candidate_root=args.candidate_root,
        )
        disposition = write_receipt(args.receipt, result)
    except (ExportBundleValidationError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {**result, "receipt_disposition": disposition},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
