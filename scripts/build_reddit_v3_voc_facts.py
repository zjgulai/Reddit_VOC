#!/usr/bin/env python3
"""Build an immutable private V3 fielded-VOC and eligibility candidate."""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Any, BinaryIO, Mapping, Sequence
import uuid


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from reddit_voc.v3_metric_eligibility import (  # noqa: E402
    MetricEligibilityError,
    canonical_json_bytes as eligibility_json_bytes,
    iter_metric_eligibility,
    materialize_metric_eligibility,
    parse_metric_eligibility_policy,
)
from reddit_voc.v3_explicit_automation import (  # noqa: E402
    ExplicitAutomationError,
    classify_explicit_automation,
    organic_exclusion_map,
    parse_explicit_automation_policy,
)
from reddit_voc.v3_voc_facts import (  # noqa: E402
    VocFactError,
    canonical_json_bytes,
    materialize_voc_materialization,
)


BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}
CANONICAL_FILES = {
    "comments.jsonl",
    "conflict-ledger.jsonl",
    "manifest.json",
    "posts.jsonl",
    "provenance-ledger.jsonl",
    "quarantine.jsonl",
    "unresolved-parent-ledger.jsonl",
}
OUTPUT_FILES = {
    "manifest.json",
    "metric-eligibility.jsonl",
    "voc-exclusions.jsonl",
    "vocs.jsonl",
}
OUTPUT_FILES_A2 = OUTPUT_FILES | {"automation-classifications.jsonl"}


class VocFactBuildError(ValueError):
    """The bound canonical input cannot become an immutable VOC candidate."""


DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
FILE_READ_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha_value(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or not value.isascii()
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise VocFactBuildError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _project_parts(path: Path, project_root: Path, label: str) -> tuple[str, ...]:
    root = Path(os.path.abspath(os.fspath(project_root)))
    target = Path(
        os.path.abspath(os.fspath(path if path.is_absolute() else root / path))
    )
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise VocFactBuildError(f"{label} is outside the project boundary") from exc
    if not relative.parts or any(
        part in {"", ".", ".."} or "/" in part or "\\" in part
        for part in relative.parts
    ):
        raise VocFactBuildError(f"{label} path is unsafe")
    return relative.parts


def _private_parts(path: Path, project_root: Path, label: str) -> tuple[str, ...]:
    parts = _project_parts(path, project_root, label)
    if parts[:2] != ("tmp", "reddit-voc-v3") or len(parts) <= 2:
        raise VocFactBuildError(f"{label} must stay below private tmp/reddit-voc-v3")
    return parts[2:]


def _open_directory_chain(
    project_root: Path,
    parts: Sequence[str],
    *,
    private_from: int | None,
    label: str,
) -> list[int]:
    opened: list[int] = []
    try:
        descriptor = os.open(os.path.abspath(os.fspath(project_root)), DIRECTORY_FLAGS)
        opened.append(descriptor)
        for ordinal, part in enumerate(parts):
            descriptor = os.open(part, DIRECTORY_FLAGS, dir_fd=descriptor)
            opened.append(descriptor)
            metadata = os.fstat(descriptor)
            if not stat.S_ISDIR(metadata.st_mode):
                raise VocFactBuildError(f"{label} ancestor is not a directory")
            if private_from is not None and ordinal >= private_from and stat.S_IMODE(metadata.st_mode) != 0o700:
                raise VocFactBuildError(f"{label} private directory must have mode 0700")
        return opened
    except (OSError, VocFactBuildError) as exc:
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                pass
        if isinstance(exc, VocFactBuildError):
            raise
        raise VocFactBuildError(f"{label} directory chain is unavailable") from exc


def _read_at(
    directory_fd: int,
    name: str,
    *,
    label: str,
    require_private: bool,
) -> bytes:
    try:
        descriptor = os.open(name, FILE_READ_FLAGS, dir_fd=directory_fd)
    except OSError as exc:
        raise VocFactBuildError(f"{label} is unavailable") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise VocFactBuildError(f"{label} must be a regular file")
        if require_private and stat.S_IMODE(before.st_mode) != 0o600:
            raise VocFactBuildError(f"{label} must have mode 0600")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        payload = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ) or len(payload) != after.st_size:
            raise VocFactBuildError(f"{label} changed while it was read")
        return payload
    finally:
        os.close(descriptor)


def _read_private_bundle(
    path: Path,
    *,
    expected_inventory: set[str],
    project_root: Path,
    label: str,
) -> dict[str, bytes]:
    relative = _private_parts(path, project_root, label)
    opened = _open_directory_chain(
        project_root,
        ("tmp", "reddit-voc-v3", *relative),
        private_from=1,
        label=label,
    )
    try:
        directory_fd = opened[-1]
        try:
            inventory = set(os.listdir(directory_fd))
        except OSError as exc:
            raise VocFactBuildError(f"{label} inventory is unavailable") from exc
        if inventory != expected_inventory:
            raise VocFactBuildError(f"{label} inventory is invalid")
        return {
            name: _read_at(
                directory_fd,
                name,
                label=f"{label} {name}",
                require_private=True,
            )
            for name in sorted(expected_inventory)
        }
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)


def _receipt_blocker_name(receipt_name: str) -> str:
    return f".{receipt_name}.uncommitted"


def _require_receipt_committed(
    directory_fd: int, receipt_name: str, label: str
) -> None:
    try:
        os.stat(
            _receipt_blocker_name(receipt_name),
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return
    except OSError as exc:
        raise VocFactBuildError(f"{label} commit gate is unavailable") from exc
    raise VocFactBuildError(f"{label} is blocked by an uncommitted receipt marker")


def _read_private_receipt(path: Path, *, project_root: Path, label: str) -> bytes:
    relative = _private_parts(path, project_root, label)
    opened = _open_directory_chain(
        project_root,
        ("tmp", "reddit-voc-v3", *relative[:-1]),
        private_from=1,
        label=label,
    )
    try:
        _require_receipt_committed(opened[-1], relative[-1], label)
        payload = _read_at(
            opened[-1],
            relative[-1],
            label=label,
            require_private=True,
        )
        _require_receipt_committed(opened[-1], relative[-1], label)
        return payload
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)


def _read_project_file(path: Path, *, project_root: Path, label: str) -> bytes:
    relative = _project_parts(path, project_root, label)
    opened = _open_directory_chain(
        project_root,
        relative[:-1],
        private_from=None,
        label=label,
    )
    try:
        return _read_at(
            opened[-1],
            relative[-1],
            label=label,
            require_private=False,
        )
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)


def _decode(payload: bytes, label: str) -> object:
    def reject_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise VocFactBuildError(f"{label} has a duplicate JSON key")
            value[key] = item
        return value

    def reject_constant(value: str) -> object:
        raise VocFactBuildError(f"{label} contains a non-finite number:{value}")

    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=reject_pairs,
            parse_constant=reject_constant,
        )
    except VocFactBuildError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise VocFactBuildError(f"{label} is invalid JSON") from exc


def _json_object(payload: bytes, label: str) -> dict[str, Any]:
    value = _decode(payload, label)
    if not isinstance(value, dict) or payload != canonical_json_bytes(value) + b"\n":
        raise VocFactBuildError(f"{label} is not a canonical JSON object")
    return value


def _jsonl(payload: bytes, label: str) -> list[dict[str, Any]]:
    if payload and not payload.endswith(b"\n"):
        raise VocFactBuildError(f"{label} must end with a newline")
    rows: list[dict[str, Any]] = []
    for ordinal, line in enumerate(payload.splitlines(), start=1):
        value = _decode(line, f"{label} row {ordinal}")
        if not isinstance(value, dict) or line != canonical_json_bytes(value):
            raise VocFactBuildError(f"{label} row {ordinal} is not canonical JSON")
        rows.append(value)
    return rows


def _binding(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {"bytes", "rows", "sha256"}:
        raise VocFactBuildError(f"{label} binding is invalid")
    if type(value.get("bytes")) is not int or value["bytes"] < 0:
        raise VocFactBuildError(f"{label} byte count is invalid")
    if type(value.get("rows")) is not int or value["rows"] < 0:
        raise VocFactBuildError(f"{label} row count is invalid")
    _sha_value(value.get("sha256"), f"{label} SHA-256")
    return value


def _load_canonical(
    root: Path,
    *,
    expected_manifest_sha256: str,
    receipt_path: Path,
    expected_receipt_sha256: str,
    project_root: Path,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    bytes,
    bytes,
]:
    canonical_parts = _private_parts(root, project_root, "canonical bundle")
    receipt_parts = _private_parts(
        receipt_path, project_root, "canonical validation receipt"
    )
    if receipt_parts[: len(canonical_parts)] == canonical_parts:
        raise VocFactBuildError("canonical validation receipt must be outside the bundle")
    raw_payloads = _read_private_bundle(
        root,
        expected_inventory=CANONICAL_FILES,
        project_root=project_root,
        label="canonical bundle",
    )
    manifest_payload = raw_payloads["manifest.json"]
    if _sha(manifest_payload) != _sha_value(expected_manifest_sha256, "canonical manifest SHA-256"):
        raise VocFactBuildError("canonical manifest hash binding mismatch")
    manifest = _json_object(manifest_payload, "canonical manifest")
    expected_manifest_fields = {
        "boundaries",
        "canonical_counts",
        "consumption_status",
        "dataset_id",
        "files",
        "governed_base_parent_lineage_debt",
        "independent_validation_status",
        "inputs",
        "promotable",
        "schema_version",
        "source_row_accounting",
        "state_contract",
        "status",
        "validation_receipt_sha256",
    }
    if (
        set(manifest) != expected_manifest_fields
        or manifest.get("schema_version") not in {
            "reddit_voc_canonical_snapshot_manifest_v1",
            "reddit_voc_canonical_snapshot_manifest_v2",
        }
        or manifest.get("status") != "candidate_built"
        or manifest.get("independent_validation_status") != "pending"
        or manifest.get("consumption_status") != "blocked_pending_independent_validation"
        or manifest.get("boundaries") != BOUNDARIES
        or manifest.get("promotable") is not False
        or manifest.get("validation_receipt_sha256") is not None
    ):
        raise VocFactBuildError("canonical manifest lifecycle is invalid")
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != CANONICAL_FILES - {"manifest.json"}:
        raise VocFactBuildError("canonical file bindings are invalid")
    payloads: dict[str, bytes] = {}
    for name, raw_binding in files.items():
        binding = _binding(raw_binding, f"canonical {name}")
        payload = raw_payloads[name]
        if (
            len(payload) != binding["bytes"]
            or payload.count(b"\n") != binding["rows"]
            or _sha(payload) != binding["sha256"]
        ):
            raise VocFactBuildError(f"canonical {name} binding mismatch")
        payloads[name] = payload

    receipt_payload = _read_private_receipt(
        receipt_path,
        project_root=project_root,
        label="canonical validation receipt",
    )
    if _sha(receipt_payload) != _sha_value(expected_receipt_sha256, "canonical receipt SHA-256"):
        raise VocFactBuildError("canonical validation receipt hash binding mismatch")
    receipt = _json_object(receipt_payload, "canonical validation receipt")
    expected_receipt_fields = {
        "boundaries",
        "bundle_manifest_sha256",
        "canonical_counts",
        "consumption_status",
        "inputs",
        "promotable",
        "schema_version",
        "source_row_accounting",
        "status",
        "unaccounted_canonical_identities",
        "unaccounted_foreign_keys",
    }
    source_accounting = manifest.get("source_row_accounting")
    expected_receipt_accounting = None
    if isinstance(source_accounting, dict):
        expected_receipt_accounting = {
            "source_rows": source_accounting.get("source_rows"),
            "terminal_outcomes": source_accounting.get("terminal_outcomes"),
        }
    if (
        set(receipt) != expected_receipt_fields
        or receipt.get("schema_version")
        != (
            "reddit_voc_canonical_snapshot_validation_receipt_v2"
            if manifest.get("schema_version") == "reddit_voc_canonical_snapshot_manifest_v2"
            else "reddit_voc_canonical_snapshot_validation_receipt_v1"
        )
        or receipt.get("status") != "passed"
        or receipt.get("bundle_manifest_sha256") != _sha(manifest_payload)
        or receipt.get("consumption_status") != "blocked_pending_voc_facts"
        or receipt.get("promotable") is not False
        or receipt.get("boundaries") != BOUNDARIES
        or type(receipt.get("unaccounted_canonical_identities")) is not int
        or receipt.get("unaccounted_canonical_identities") != 0
        or type(receipt.get("unaccounted_foreign_keys")) is not int
        or receipt.get("unaccounted_foreign_keys") != 0
        or receipt.get("canonical_counts") != manifest.get("canonical_counts")
        or receipt.get("inputs") != manifest.get("inputs")
        or receipt.get("source_row_accounting") != expected_receipt_accounting
    ):
        raise VocFactBuildError("canonical validation receipt is invalid")
    return (
        manifest,
        _jsonl(payloads["posts.jsonl"], "canonical posts"),
        _jsonl(payloads["comments.jsonl"], "canonical comments"),
        _jsonl(payloads["quarantine.jsonl"], "canonical quarantine"),
        manifest_payload,
        receipt_payload,
    )


def _jsonl_bytes(rows: Sequence[Mapping[str, object]]) -> bytes:
    return b"".join(canonical_json_bytes(dict(row)) + b"\n" for row in rows)


def _rename_noreplace(parent_fd: int, source: str, target: str) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin" and hasattr(libc, "renameatx_np"):
        function = libc.renameatx_np
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        function.restype = ctypes.c_int
        result = function(parent_fd, os.fsencode(source), parent_fd, os.fsencode(target), 0x00000004)
    elif sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        function = libc.renameat2
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        function.restype = ctypes.c_int
        result = function(parent_fd, os.fsencode(source), parent_fd, os.fsencode(target), 1)
    else:
        raise VocFactBuildError("atomic no-replace publish is unavailable")
    if result == 0:
        return
    number = ctypes.get_errno()
    if number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise VocFactBuildError("immutable VOC output already exists")
    raise OSError(number, os.strerror(number))


def _write_candidate(
    output_root: Path,
    payloads: Mapping[str, bytes | BinaryIO],
    project_root: Path,
) -> None:
    output_inventory = set(payloads)
    if frozenset(output_inventory) not in {
        frozenset(OUTPUT_FILES),
        frozenset(OUTPUT_FILES_A2),
    }:
        raise VocFactBuildError("VOC output inventory is invalid")
    relative = _private_parts(output_root, project_root, "VOC output")
    opened = _open_directory_chain(
        project_root,
        ("tmp", "reddit-voc-v3", *relative[:-1]),
        private_from=1,
        label="VOC output parent",
    )
    parent_fd = opened[-1]
    output_name = relative[-1]
    staging_name = f".{output_name}.{uuid.uuid4().hex}.staging"
    staging_fd: int | None = None
    staged_names: list[str] = []
    completed = False
    try:
        os.mkdir(staging_name, 0o700, dir_fd=parent_fd)
        staging_fd = os.open(staging_name, DIRECTORY_FLAGS, dir_fd=parent_fd)
        os.fchmod(staging_fd, 0o700)
        staging_identity = (os.fstat(staging_fd).st_dev, os.fstat(staging_fd).st_ino)
        for name, payload in sorted(payloads.items()):
            descriptor = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=staging_fd,
            )
            staged_names.append(name)
            try:
                os.fchmod(descriptor, 0o600)
                if isinstance(payload, bytes):
                    source_chunks = (payload,)
                else:
                    payload.seek(0)
                    source_chunks = iter(lambda: payload.read(1024 * 1024), b"")
                for chunk in source_chunks:
                    view = memoryview(chunk)
                    while view:
                        written = os.write(descriptor, view)
                        if written <= 0:
                            raise OSError("VOC candidate write made no progress")
                        view = view[written:]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        os.fsync(staging_fd)
        os.fsync(parent_fd)
        _rename_noreplace(parent_fd, staging_name, output_name)
        os.fsync(parent_fd)
        target_fd = os.open(output_name, DIRECTORY_FLAGS, dir_fd=parent_fd)
        try:
            target_metadata = os.fstat(target_fd)
            if (
                (target_metadata.st_dev, target_metadata.st_ino) != staging_identity
                or not stat.S_ISDIR(target_metadata.st_mode)
                or stat.S_IMODE(target_metadata.st_mode) != 0o700
                or set(os.listdir(target_fd)) != output_inventory
            ):
                raise VocFactBuildError("VOC candidate publish ownership changed")
        finally:
            os.close(target_fd)
        completed = True
    except VocFactBuildError:
        raise
    except OSError as exc:
        raise VocFactBuildError("unable to publish VOC candidate") from exc
    finally:
        if not completed and staging_fd is not None:
            for name in staged_names:
                try:
                    os.unlink(name, dir_fd=staging_fd)
                except OSError:
                    pass
            try:
                marker = os.open(
                    ".publish-failed",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=staging_fd,
                )
                os.fsync(marker)
                os.close(marker)
                os.fsync(staging_fd)
            except OSError:
                pass
        if staging_fd is not None:
            os.close(staging_fd)
        for descriptor in reversed(opened):
            os.close(descriptor)


def build_voc_fact_bundle(
    *,
    canonical_root: Path,
    canonical_manifest_sha256: str,
    canonical_validation_receipt: Path,
    canonical_validation_receipt_sha256: str,
    eligibility_policy_path: Path,
    eligibility_policy_sha256: str,
    automation_policy_path: Path | None = None,
    automation_policy_sha256: str | None = None,
    period: str,
    scope: str,
    output_root: Path,
    project_root: Path,
) -> dict[str, object]:
    if (automation_policy_path is None) != (automation_policy_sha256 is None):
        raise VocFactBuildError(
            "automation policy path and SHA-256 must be supplied together"
        )
    a2_enabled = automation_policy_path is not None
    root = Path(os.path.abspath(os.fspath(project_root)))
    canonical_parts = _private_parts(canonical_root, root, "canonical bundle")
    canonical_receipt_parts = _private_parts(
        canonical_validation_receipt,
        root,
        "canonical validation receipt",
    )
    output_parts = _private_parts(output_root, root, "VOC output")
    for protected_parts in (canonical_parts, canonical_receipt_parts):
        if (
            output_parts[: len(protected_parts)] == protected_parts
            or protected_parts[: len(output_parts)] == output_parts
        ):
            raise VocFactBuildError(
                "VOC output must not overlap a bound canonical input path"
            )
    manifest, posts, comments, quarantine, manifest_payload, receipt_payload = _load_canonical(
        canonical_root,
        expected_manifest_sha256=canonical_manifest_sha256,
        receipt_path=canonical_validation_receipt,
        expected_receipt_sha256=canonical_validation_receipt_sha256,
        project_root=root,
    )
    policy_payload = _read_project_file(
        eligibility_policy_path,
        project_root=root,
        label="metric eligibility policy",
    )
    if _sha(policy_payload) != _sha_value(eligibility_policy_sha256, "eligibility policy SHA-256"):
        raise VocFactBuildError("metric eligibility policy hash binding mismatch")
    policy_value = _decode(policy_payload, "metric eligibility policy")
    if not isinstance(policy_value, dict) or policy_payload != canonical_json_bytes(policy_value) + b"\n":
        raise VocFactBuildError("metric eligibility policy is not canonical JSON")
    policy = parse_metric_eligibility_policy(policy_value)
    automation_policy_payload: bytes | None = None
    automation_policy = None
    if a2_enabled:
        if automation_policy_path is None or automation_policy_sha256 is None:
            raise VocFactBuildError("explicit automation policy binding is missing")
        automation_policy_payload = _read_project_file(
            automation_policy_path,
            project_root=root,
            label="explicit automation policy",
        )
        if _sha(automation_policy_payload) != _sha_value(
            automation_policy_sha256, "automation policy SHA-256"
        ):
            raise VocFactBuildError("explicit automation policy hash binding mismatch")
        automation_policy_value = _decode(
            automation_policy_payload, "explicit automation policy"
        )
        if (
            not isinstance(automation_policy_value, dict)
            or automation_policy_payload
            != canonical_json_bytes(automation_policy_value) + b"\n"
        ):
            raise VocFactBuildError(
                "explicit automation policy is not canonical JSON"
            )
        automation_policy = parse_explicit_automation_policy(
            automation_policy_value
        )
        eligibility_families = {
            indicator.metric_family for indicator in policy.indicators
        }
        if not set(automation_policy.exclude_indicator_families).issubset(
            eligibility_families
        ):
            raise VocFactBuildError(
                "automation exclusion families are absent from eligibility policy"
            )
    materialization = materialize_voc_materialization(
        posts,
        comments,
        quarantine=quarantine,
    )
    vocs = list(materialization.vocs)
    exclusions = list(materialization.exclusions)
    classifications = ()
    automation_exclusions: dict[str, str] = {}
    family_contract_sha256: str | None = None
    classification_payload: bytes | None = None
    if automation_policy is not None:
        classifications = classify_explicit_automation(
            comments,
            policy=automation_policy,
        )
        automation_exclusions = organic_exclusion_map(classifications)
        family_contract = {
            "audit_indicator_ids": list(automation_policy.audit_indicator_ids),
            "exclude_indicator_families": list(
                automation_policy.exclude_indicator_families
            ),
        }
        family_contract_sha256 = _sha(
            canonical_json_bytes(family_contract) + b"\n"
        )
        classification_payload = _jsonl_bytes(
            [row.as_dict() for row in classifications]
        )
    voc_payload = _jsonl_bytes([row.as_dict() for row in vocs])
    exclusion_payload = _jsonl_bytes([row.as_dict() for row in exclusions])
    eligibility_row_count = 0
    effective_eligible_automation_rows = 0
    effective_business_rows_excluded_by_automation = 0
    exclusion_reason_counts: dict[str, int] = {}
    for exclusion in exclusions:
        for reason in exclusion.reason_codes:
            exclusion_reason_counts[reason] = exclusion_reason_counts.get(reason, 0) + 1
    voc_ids = {row.canonical_entity_id for row in vocs}
    exclusion_by_id = {
        row.canonical_entity_id: set(row.reason_codes) for row in exclusions
    }
    automation_ids = set(automation_exclusions)
    automation_voc_ids = automation_ids & voc_ids
    automation_non_voc_ids = automation_ids - voc_ids
    unresolved_automation_ids = {
        row.canonical_entity_id
        for row in classifications
        if row.automation_determined and row.comment_state == "unresolved_parent"
    }
    linked_incomplete_automation_ids = (
        automation_non_voc_ids - unresolved_automation_ids
    )
    if automation_policy is not None:
        if (
            sum(row.was_already_excluded for row in classifications)
            + sum(row.newly_excluded for row in classifications)
            != len(automation_ids)
        ):
            raise VocFactBuildError("automation accounting is not conserved")
        if (
            unresolved_automation_ids - automation_non_voc_ids
            or automation_non_voc_ids
            != unresolved_automation_ids | linked_incomplete_automation_ids
            or any(
                "root_post_context_incomplete" not in exclusion_by_id.get(entity_id, set())
                for entity_id in linked_incomplete_automation_ids
            )
        ):
            raise VocFactBuildError(
                "non-VOC automation identities are not fully explained"
            )

    with tempfile.TemporaryFile(mode="w+b") as eligibility_stream:
        if automation_policy is None:
            eligibility = materialize_metric_eligibility(
                vocs,
                policy,
                period=period,
                scope=scope,
            )
            for row in eligibility:
                payload = eligibility_json_bytes(row.as_dict()) + b"\n"
                eligibility_stream.write(payload)
                eligibility_row_count += 1
        else:
            for row in iter_metric_eligibility(
                vocs,
                policy,
                period=period,
                scope=scope,
                organic_exclusions=automation_exclusions,
            ):
                value = row.as_dict()
                eligibility_stream.write(eligibility_json_bytes(value) + b"\n")
                eligibility_row_count += 1
                if row.metric_member_id in automation_voc_ids:
                    if (
                        row.metric_family
                        in automation_policy.exclude_indicator_families
                        and row.status == "eligible"
                    ):
                        effective_eligible_automation_rows += 1
                    if (
                        row.metric_family
                        in automation_policy.exclude_indicator_families
                        and row.reason_codes == ("explicit_automation",)
                    ):
                        effective_business_rows_excluded_by_automation += 1
        eligibility_bytes = eligibility_stream.tell()
        eligibility_stream.seek(0)
        eligibility_sha256 = hashlib.sha256()
        while chunk := eligibility_stream.read(1024 * 1024):
            eligibility_sha256.update(chunk)
        eligibility_stream.seek(0)

        document_payloads: dict[str, bytes | BinaryIO] = {
            "metric-eligibility.jsonl": eligibility_stream,
            "voc-exclusions.jsonl": exclusion_payload,
            "vocs.jsonl": voc_payload,
        }
        document_bindings: dict[str, dict[str, object]] = {
            "metric-eligibility.jsonl": {
                "bytes": eligibility_bytes,
                "rows": eligibility_row_count,
                "sha256": eligibility_sha256.hexdigest(),
            },
            "voc-exclusions.jsonl": {
                "bytes": len(exclusion_payload),
                "rows": exclusion_payload.count(b"\n"),
                "sha256": _sha(exclusion_payload),
            },
            "vocs.jsonl": {
                "bytes": len(voc_payload),
                "rows": voc_payload.count(b"\n"),
                "sha256": _sha(voc_payload),
            },
        }
        if classification_payload is not None:
            document_payloads["automation-classifications.jsonl"] = (
                classification_payload
            )
            document_bindings["automation-classifications.jsonl"] = {
                "bytes": len(classification_payload),
                "rows": classification_payload.count(b"\n"),
                "sha256": _sha(classification_payload),
            }

        output_manifest: dict[str, object] = {
        "boundaries": dict(BOUNDARIES),
        "canonical_counts": dict(manifest["canonical_counts"]),
        "consumption_status": "blocked_pending_independent_validation",
        "counts": {
            "analysis_ready_comment_context_vocs": sum(
                row.voc_type == "comment_context_voc" and row.analysis_text_status == "ready"
                for row in vocs
            ),
            "analysis_ready_post_vocs": sum(
                row.voc_type == "post_voc" and row.analysis_text_status == "ready"
                for row in vocs
            ),
            "comment_context_vocs": sum(row.voc_type == "comment_context_voc" for row in vocs),
            "excluded_analysis_text_incomplete": exclusion_reason_counts.get(
                "analysis_text_incomplete", 0
            ),
            "excluded_comment_identities": sum(
                row.entity_type == "comment" for row in exclusions
            ),
            "excluded_post_identities": sum(
                row.entity_type == "post" for row in exclusions
            ),
            "excluded_quarantined": exclusion_reason_counts.get("quarantined", 0),
            "excluded_root_post_context_incomplete": exclusion_reason_counts.get(
                "root_post_context_incomplete", 0
            ),
            "excluded_source_url_identity_conflict": exclusion_reason_counts.get(
                "source_url_identity_conflict", 0
            ),
            "excluded_unresolved_parent": exclusion_reason_counts.get(
                "unresolved_parent", 0
            ),
            "day_precision_vocs": sum(row.event_time_precision == "day" for row in vocs),
            "eligibility_rows": eligibility_row_count,
            "instant_or_hour_precision_vocs": sum(
                row.event_time_precision in {"instant", "hour"} for row in vocs
            ),
            "missing_event_time_vocs": sum(row.event_time_precision is None for row in vocs),
            "post_vocs": sum(row.voc_type == "post_voc" for row in vocs),
            "total_vocs": len(vocs),
        },
        "dataset_id": f"{manifest['dataset_id']}_voc_facts_{'v2' if a2_enabled else 'v1'}",
        "files": dict(sorted(document_bindings.items())),
        "independent_validation_status": "pending",
        "inputs": {
            "canonical_manifest_sha256": _sha(manifest_payload),
            "canonical_validation_receipt_sha256": _sha(receipt_payload),
            "eligibility_policy_sha256": _sha(policy_payload),
        },
        "period": period,
        "policy_version": policy.policy_version,
        "promotable": False,
        "schema_version": f"reddit_voc_voc_facts_manifest_{'v2' if a2_enabled else 'v1'}",
        "scope": scope,
        "status": "candidate_built",
        "validation_receipt_sha256": None,
        }
        if automation_policy is not None:
            if (
                automation_policy_payload is None
                or family_contract_sha256 is None
            ):
                raise VocFactBuildError(
                    "explicit automation policy binding is incomplete"
                )
            canonical_comment_binding = manifest["files"]["comments.jsonl"]
            if not isinstance(canonical_comment_binding, dict):
                raise VocFactBuildError(
                    "canonical comments binding is invalid"
                )
            output_manifest["automation_policy_version"] = (
                automation_policy.policy_version
            )
            output_manifest["inputs"] = {
                **output_manifest["inputs"],
                "automation_family_contract_sha256": family_contract_sha256,
                "automation_policy_sha256": _sha(automation_policy_payload),
                "canonical_comments_sha256": canonical_comment_binding["sha256"],
            }
            output_manifest["counts"] = {
                **output_manifest["counts"],
                "automation_already_excluded": sum(
                    row.was_already_excluded for row in classifications
                ),
                "automation_disclosure_detected": sum(
                    row.audit_disclosure_detected for row in classifications
                ),
                "automation_linked": sum(
                    row.automation_determined and row.comment_state == "linked"
                    for row in classifications
                ),
                "automation_newly_excluded": sum(
                    row.newly_excluded for row in classifications
                ),
                "automation_non_voc": len(automation_non_voc_ids),
                "automation_non_voc_linked_incomplete": len(
                    linked_incomplete_automation_ids
                ),
                "automation_non_voc_unresolved": len(unresolved_automation_ids),
                "automation_total": len(automation_ids),
                "automation_unresolved": sum(
                    row.automation_determined
                    and row.comment_state == "unresolved_parent"
                    for row in classifications
                ),
                "automation_voc": len(automation_voc_ids),
                "effective_business_rows_excluded_by_automation": (
                    effective_business_rows_excluded_by_automation
                ),
                "effective_eligible_automation_rows": (
                    effective_eligible_automation_rows
                ),
            }
        output_manifest_payload = canonical_json_bytes(output_manifest) + b"\n"
        _write_candidate(
            output_root,
            {**document_payloads, "manifest.json": output_manifest_payload},
            root,
        )
    return {
        "boundaries": dict(BOUNDARIES),
        "counts": output_manifest["counts"],
        "dataset_id": output_manifest["dataset_id"],
        "manifest_sha256": _sha(output_manifest_payload),
        "schema_version": output_manifest["schema_version"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build one immutable private Reddit VOC V3 facts candidate.")
    parser.add_argument("--canonical-root", required=True, type=Path)
    parser.add_argument("--canonical-manifest-sha256", required=True)
    parser.add_argument("--canonical-validation-receipt", required=True, type=Path)
    parser.add_argument("--canonical-validation-receipt-sha256", required=True)
    parser.add_argument("--eligibility-policy", required=True, type=Path)
    parser.add_argument("--eligibility-policy-sha256", required=True)
    parser.add_argument("--automation-policy", type=Path)
    parser.add_argument("--automation-policy-sha256")
    parser.add_argument("--period", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--project-root", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        result = build_voc_fact_bundle(
            canonical_root=arguments.canonical_root,
            canonical_manifest_sha256=arguments.canonical_manifest_sha256,
            canonical_validation_receipt=arguments.canonical_validation_receipt,
            canonical_validation_receipt_sha256=arguments.canonical_validation_receipt_sha256,
            eligibility_policy_path=arguments.eligibility_policy,
            eligibility_policy_sha256=arguments.eligibility_policy_sha256,
            automation_policy_path=arguments.automation_policy,
            automation_policy_sha256=arguments.automation_policy_sha256,
            period=arguments.period,
            scope=arguments.scope,
            output_root=arguments.output_root,
            project_root=arguments.project_root,
        )
    except (
        ExplicitAutomationError,
        MetricEligibilityError,
        VocFactBuildError,
        VocFactError,
    ) as exc:
        print(f"reddit_v3_voc_facts_failed:{exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
