#!/usr/bin/env python3
"""Validate the append-only local Reddit VOC candidate registry tree."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Mapping

try:
    from scripts import build_reddit_candidate as contract
except ModuleNotFoundError:  # Direct script execution.
    import build_reddit_candidate as contract


TREE_MEMBERS = frozenset({"entries", "events", "runs", "commits"})
NATIVE_REGISTRY_BASE_ARTIFACT_KEYS = {"build_contract", "final_validation_receipt"}
ENTRY_V1_KEYS = {
    "artifact_build_performed",
    "artifacts",
    "boundaries",
    "candidate_id",
    "candidate_input_sha256",
    "created_at_utc",
    "deliverables",
    "evidence",
    "expires_at_utc",
    "lineage",
    "phase",
    "release",
    "schema_version",
    "status",
}
ENTRY_V2_KEYS = ENTRY_V1_KEYS | {"v3_lineage"}
EVENT_V1_KEYS = {
    "boundaries",
    "candidate_id",
    "candidate_input_sha256",
    "created_at_utc",
    "entry_sha256",
    "schema_version",
    "status",
}
EVENT_V2_KEYS = EVENT_V1_KEYS | {"entry_schema_version"}
RUN_V1_KEYS = {
    "artifact_build_performed",
    "boundaries",
    "candidate_id",
    "candidate_input_sha256",
    "entry_written",
    "event_written",
    "phase",
    "reason_code",
    "result_status",
    "run_id",
    "schema_version",
    "status",
}
RUN_V2_KEYS = RUN_V1_KEYS | {"registry_entry_schema_version"}
ORCHESTRATION_RUN_V1_KEYS = {
    "artifact_build_performed",
    "boundaries",
    "candidate_id",
    "candidate_input_sha256",
    "entry_written",
    "event_written",
    "monitor_receipt_sha256",
    "orchestration_contract_sha256",
    "phase",
    "reason_code",
    "result_status",
    "run_id",
    "schema_version",
    "source_freeze_manifest_sha256",
    "status",
}
COMMIT_V1_KEYS = {
    "boundaries",
    "candidate_id",
    "candidate_input_sha256",
    "entry_sha256",
    "event_sha256",
    "run_id",
    "run_sha256",
    "schema_version",
    "status",
}


class RegistryValidationError(ValueError):
    """The append-only registry contains unsafe or inconsistent evidence."""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"


def _safe_file(path: Path, label: str) -> bytes:
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise RegistryValidationError(f"{label}_missing") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise RegistryValidationError(f"{label}_unsafe_mode")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RegistryValidationError(f"{label}_unsafe") from exc
    try:
        before = os.fstat(descriptor)
        parts: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            parts.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        or (before.st_dev, before.st_ino) != (metadata.st_dev, metadata.st_ino)
    ):
        raise RegistryValidationError(f"{label}_bytes_drift")
    payload = b"".join(parts)
    if len(payload) != before.st_size:
        raise RegistryValidationError(f"{label}_bytes_drift")
    return payload


def _object(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    payload = _safe_file(path, label)
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RegistryValidationError(f"{label}_invalid_json") from exc
    if not isinstance(value, dict) or _canonical(value) != payload:
        raise RegistryValidationError(f"{label}_noncanonical")
    return value, payload


def _exact(value: Mapping[str, Any], keys: set[str], label: str) -> None:
    if set(value) != keys:
        raise RegistryValidationError(f"{label}_unexpected_fields")


def _validate_artifacts(value: object) -> None:
    if not isinstance(value, Mapping) or not value:
        raise RegistryValidationError("entry_artifacts_invalid")
    seen_paths: set[str] = set()
    for key, record in value.items():
        if (
            not isinstance(key, str)
            or not isinstance(record, Mapping)
            or set(record) != {"bytes", "path", "sha256"}
        ):
            raise RegistryValidationError("entry_artifact_contract_invalid")
        path_value = record.get("path")
        expected_bytes = record.get("bytes")
        expected_sha = record.get("sha256")
        if (
            not isinstance(path_value, str)
            or not path_value
            or path_value in seen_paths
            or isinstance(expected_bytes, bool)
            or not isinstance(expected_bytes, int)
            or expected_bytes < 0
            or not isinstance(expected_sha, str)
            or contract.SHA256_RE.fullmatch(expected_sha) is None
        ):
            raise RegistryValidationError("entry_artifact_contract_invalid")
        seen_paths.add(path_value)
        path = Path(path_value)
        try:
            payload = contract._regular_bytes(path, label="artifact")
        except contract.CandidateRegistrationError as exc:
            raise RegistryValidationError(str(exc)) from exc
        if sha256(payload).hexdigest() != expected_sha:
            raise RegistryValidationError("artifact_sha256_drift")
        if len(payload) != expected_bytes:
            raise RegistryValidationError("artifact_bytes_drift")


def _validate_v3_lineage(value: object, artifacts: object) -> set[str]:
    if not isinstance(value, Mapping) or set(value) != {
        "artifact_sha256s",
        "candidate_release_sha256",
        "release_id",
        "source_snapshot_id",
    }:
        raise RegistryValidationError("v3_lineage_contract_invalid")
    shas = value.get("artifact_sha256s")
    if not isinstance(shas, Mapping):
        raise RegistryValidationError("v3_lineage_artifact_set_invalid")
    artifact_keys = set(shas)
    if artifact_keys == contract.V3_LINEAGE_ARTIFACT_KEYS:
        registry_artifact_keys = {f"v3_{key}" for key in artifact_keys}
        record_key = lambda key: f"v3_{key}"
    elif artifact_keys == contract.V3_NATIVE_LINEAGE_ARTIFACT_KEYS:
        registry_artifact_keys = artifact_keys
        record_key = lambda key: key
    else:
        raise RegistryValidationError("v3_lineage_artifact_set_invalid")
    if (
        not isinstance(value.get("candidate_release_sha256"), str)
        or contract.SHA256_RE.fullmatch(str(value["candidate_release_sha256"])) is None
        or not isinstance(value.get("release_id"), str)
        or not value["release_id"]
        or not isinstance(value.get("source_snapshot_id"), str)
        or not value["source_snapshot_id"]
        or not isinstance(artifacts, Mapping)
    ):
        raise RegistryValidationError("v3_lineage_contract_invalid")
    for key, digest in shas.items():
        record = artifacts.get(record_key(key))
        if (
            not isinstance(digest, str)
            or contract.SHA256_RE.fullmatch(digest) is None
            or not isinstance(record, Mapping)
            or record.get("sha256") != digest
        ):
            raise RegistryValidationError("v3_lineage_artifact_binding_invalid")
    return registry_artifact_keys


def _validate_entry(value: Mapping[str, Any]) -> None:
    schema = value.get("schema_version")
    if schema == "reddit_voc_candidate_registry_entry_v1":
        _exact(value, ENTRY_V1_KEYS, "entry")
        expected_artifact_keys = contract.REGISTRY_BASE_ARTIFACT_KEYS
    elif schema == "reddit_voc_candidate_registry_entry_v2":
        _exact(value, ENTRY_V2_KEYS, "entry")
        v3_artifact_keys = _validate_v3_lineage(
            value.get("v3_lineage"), value.get("artifacts")
        )
        base_artifact_keys = (
            NATIVE_REGISTRY_BASE_ARTIFACT_KEYS
            if v3_artifact_keys == contract.V3_NATIVE_LINEAGE_ARTIFACT_KEYS
            else contract.REGISTRY_BASE_ARTIFACT_KEYS
        )
        expected_artifact_keys = base_artifact_keys | v3_artifact_keys
    else:
        raise RegistryValidationError("entry_contract_invalid")
    artifacts = value.get("artifacts")
    if (
        value.get("status") != "registered_local_candidate"
        or value.get("phase") != "register_only_external_final_artifacts"
        or value.get("artifact_build_performed") is not False
        or value.get("boundaries") != contract.SAFE_BOUNDARIES
        or not isinstance(artifacts, Mapping)
        or set(artifacts) != expected_artifact_keys
    ):
        raise RegistryValidationError("entry_contract_invalid")
    if schema.endswith("_v2") and value["v3_lineage"][
        "candidate_release_sha256"
    ] != value.get("release", {}).get("release_sha256"):
        raise RegistryValidationError("v3_candidate_release_mismatch")
    try:
        expected_candidate_id = contract.candidate_id(value)
    except contract.CandidateRegistrationError as exc:
        raise RegistryValidationError(str(exc)) from exc
    if value.get("candidate_id") != expected_candidate_id:
        raise RegistryValidationError("entry_candidate_identity_mismatch")
    for key in ("created_at_utc", "expires_at_utc"):
        try:
            contract._require_utc(value.get(key), label=key)
        except contract.CandidateRegistrationError as exc:
            raise RegistryValidationError(str(exc)) from exc
    _validate_artifacts(value.get("artifacts"))


def _directory_files(root: Path, name: str) -> tuple[Path, ...]:
    directory = root / name
    if not directory.exists():
        return ()
    try:
        metadata = os.lstat(directory)
    except OSError as exc:
        raise RegistryValidationError("registry_tree_unsafe") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise RegistryValidationError("registry_tree_unsafe_mode")
    files = tuple(sorted(directory.iterdir(), key=lambda path: path.name))
    if any(path.name.startswith(".") or path.suffix != ".json" for path in files):
        raise RegistryValidationError("registry_tree_unknown_member")
    return files


def validate_registry(registry_root: Path) -> dict[str, Any]:
    registry_root = Path(registry_root)
    try:
        metadata = os.lstat(registry_root)
    except OSError as exc:
        raise RegistryValidationError("registry_tree_missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise RegistryValidationError("registry_tree_unsafe")
    if {path.name for path in registry_root.iterdir()} - TREE_MEMBERS:
        raise RegistryValidationError("registry_tree_unknown_member")

    entries: dict[str, tuple[dict[str, Any], str]] = {}
    for path in _directory_files(registry_root, "entries"):
        value, payload = _object(path, "registry_entry")
        _validate_entry(value)
        candidate_id = str(value["candidate_id"])
        if path.stem != candidate_id or candidate_id in entries:
            raise RegistryValidationError("entry_path_identity_mismatch")
        entries[candidate_id] = (value, sha256(payload).hexdigest())

    events: dict[str, tuple[dict[str, Any], str]] = {}
    for path in _directory_files(registry_root, "events"):
        value, payload = _object(path, "registry_event")
        event_schema = value.get("schema_version")
        if event_schema == "reddit_voc_candidate_registry_event_v1":
            _exact(value, EVENT_V1_KEYS, "event")
            expected_entry_schema = "reddit_voc_candidate_registry_entry_v1"
        elif event_schema == "reddit_voc_candidate_registry_event_v2":
            _exact(value, EVENT_V2_KEYS, "event")
            expected_entry_schema = "reddit_voc_candidate_registry_entry_v2"
            if value.get("entry_schema_version") != expected_entry_schema:
                raise RegistryValidationError("event_contract_invalid")
        else:
            raise RegistryValidationError("event_contract_invalid")
        candidate_id = value.get("candidate_id")
        if (
            value.get("status") != "candidate_registered"
            or value.get("boundaries") != contract.SAFE_BOUNDARIES
            or not isinstance(candidate_id, str)
            or path.name != f"{candidate_id}.registered.json"
            or candidate_id in events
            or candidate_id not in entries
            or entries[candidate_id][0].get("schema_version") != expected_entry_schema
            or value.get("candidate_input_sha256")
            != entries[candidate_id][0]["candidate_input_sha256"]
            or value.get("entry_sha256") != entries[candidate_id][1]
            or value.get("created_at_utc") != entries[candidate_id][0]["created_at_utc"]
        ):
            raise RegistryValidationError("event_contract_invalid")
        events[candidate_id] = (value, sha256(payload).hexdigest())

    completed_runs: dict[str, tuple[dict[str, Any], str]] = {}
    blocked_count = 0
    failed_count = 0
    run_count = 0
    for path in _directory_files(registry_root, "runs"):
        value, payload = _object(path, "registry_run")
        run_schema = value.get("schema_version")
        if run_schema == "reddit_voc_candidate_run_v1":
            _exact(value, RUN_V1_KEYS, "run")
            expected_entry_schema = "reddit_voc_candidate_registry_entry_v1"
        elif run_schema == "reddit_voc_candidate_run_v2":
            _exact(value, RUN_V2_KEYS, "run")
            expected_entry_schema = "reddit_voc_candidate_registry_entry_v2"
            if value.get("registry_entry_schema_version") != expected_entry_schema:
                raise RegistryValidationError("run_contract_invalid")
        elif run_schema == "reddit_voc_candidate_orchestration_run_v1":
            _exact(value, ORCHESTRATION_RUN_V1_KEYS, "run")
            run_count += 1
            if (
                value.get("run_id") != path.stem
                or value.get("phase") != "candidate_only_orchestration"
                or not isinstance(value.get("artifact_build_performed"), bool)
                or value.get("candidate_id") is not None
                or value.get("candidate_input_sha256") is not None
                or value.get("entry_written") is not False
                or value.get("event_written") is not False
                or value.get("boundaries") != contract.SAFE_BOUNDARIES
                or value.get("status") not in {"blocked", "failed"}
                or value.get("result_status") != value.get("status")
                or not isinstance(value.get("reason_code"), str)
                or not value["reason_code"]
                or not isinstance(value.get("orchestration_contract_sha256"), str)
                or contract.SHA256_RE.fullmatch(value["orchestration_contract_sha256"])
                is None
            ):
                raise RegistryValidationError("orchestration_run_contract_invalid")
            for key in ("monitor_receipt_sha256", "source_freeze_manifest_sha256"):
                digest = value.get(key)
                if digest is not None and (
                    not isinstance(digest, str)
                    or contract.SHA256_RE.fullmatch(digest) is None
                ):
                    raise RegistryValidationError("orchestration_run_contract_invalid")
            if value["status"] == "blocked":
                blocked_count += 1
            else:
                failed_count += 1
            continue
        else:
            raise RegistryValidationError("run_contract_invalid")
        run_count += 1
        if (
            value.get("run_id") != path.stem
            or value.get("phase") != "register_only_external_final_artifacts"
            or value.get("artifact_build_performed") is not False
            or value.get("boundaries") != contract.SAFE_BOUNDARIES
        ):
            raise RegistryValidationError("run_contract_invalid")
        if value.get("status") == "failed":
            if (
                value.get("result_status") != "failed"
                or value.get("entry_written") is not False
                or value.get("event_written") is not False
            ):
                raise RegistryValidationError("failed_run_contract_invalid")
            failed_count += 1
            continue
        candidate_id = value.get("candidate_id")
        if (
            value.get("status") != "completed"
            or value.get("result_status") not in {"created", "no_change"}
            or value.get("reason_code") != "candidate_registered"
            or value.get("entry_written") is not True
            or value.get("event_written") is not True
            or not isinstance(candidate_id, str)
            or candidate_id not in entries
            or candidate_id not in events
            or entries[candidate_id][0].get("schema_version") != expected_entry_schema
            or value.get("candidate_input_sha256")
            != entries[candidate_id][0]["candidate_input_sha256"]
        ):
            raise RegistryValidationError("completed_run_contract_invalid")
        completed_runs[str(value["run_id"])] = (value, sha256(payload).hexdigest())

    commits: dict[str, tuple[dict[str, Any], str]] = {}
    committed_candidates: set[str] = set()
    for path in _directory_files(registry_root, "commits"):
        value, payload = _object(path, "registry_commit")
        _exact(value, COMMIT_V1_KEYS, "commit")
        run_id = value.get("run_id")
        candidate_id = value.get("candidate_id")
        if (
            value.get("schema_version") != "reddit_voc_candidate_registry_commit_v1"
            or value.get("status") != "committed"
            or value.get("boundaries") != contract.SAFE_BOUNDARIES
            or not isinstance(run_id, str)
            or path.stem != run_id
            or run_id in commits
            or run_id not in completed_runs
            or not isinstance(candidate_id, str)
            or candidate_id not in entries
            or candidate_id not in events
        ):
            raise RegistryValidationError("registry_commit_contract_invalid")
        run, run_sha = completed_runs[run_id]
        entry, entry_sha = entries[candidate_id]
        event, event_sha = events[candidate_id]
        if (
            run.get("candidate_id") != candidate_id
            or value.get("candidate_input_sha256")
            != entry.get("candidate_input_sha256")
            or run.get("candidate_input_sha256")
            != entry.get("candidate_input_sha256")
            or event.get("candidate_input_sha256")
            != entry.get("candidate_input_sha256")
            or value.get("entry_sha256") != entry_sha
            or value.get("event_sha256") != event_sha
            or value.get("run_sha256") != run_sha
        ):
            raise RegistryValidationError("registry_commit_binding_invalid")
        commits[run_id] = (value, sha256(payload).hexdigest())
        committed_candidates.add(candidate_id)

    pending_run_ids = set(completed_runs) - set(commits)
    candidates_with_pending_runs = {
        str(completed_runs[run_id][0]["candidate_id"]) for run_id in pending_run_ids
    }
    pending_candidate_ids = (set(entries) | set(events)) - committed_candidates
    pending_transaction_count = len(pending_run_ids) + len(
        pending_candidate_ids - candidates_with_pending_runs
    )
    tree_identity = {
        "blocked_run_count": blocked_count,
        "commits": {key: value[1] for key, value in sorted(commits.items())},
        "committed_candidate_ids": sorted(committed_candidates),
        "failed_run_count": failed_count,
        "pending_transaction_count": pending_transaction_count,
        "raw_entries": {key: value[1] for key, value in sorted(entries.items())},
        "raw_events": {key: value[1] for key, value in sorted(events.items())},
        "raw_runs": {
            path.stem: sha256(_safe_file(path, "registry_run")).hexdigest()
            for path in _directory_files(registry_root, "runs")
        },
        "run_count": run_count,
    }
    return {
        "blocked_run_count": blocked_count,
        "candidate_ids": sorted(committed_candidates),
        "commit_count": len(commits),
        "entry_count": len(committed_candidates),
        "event_count": len(committed_candidates),
        "failed_run_count": failed_count,
        "pending_transaction_count": pending_transaction_count,
        "production_unchanged": True,
        "run_count": run_count,
        "schema_version": "reddit_voc_candidate_registry_validation_result_v1",
        "status": "passed",
        "tree_sha256": sha256(_canonical(tree_identity)).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = validate_registry(args.registry_root)
    except RegistryValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
