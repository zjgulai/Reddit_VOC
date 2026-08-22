#!/usr/bin/env python3
"""Register one explicitly supplied, already-built Reddit VOC candidate.

This C1 foundation is deliberately register-only.  It does not build a dist,
invoke Docker, discover a "latest" directory, contact a remote host, or deploy.
Every input path and expected SHA-256 is supplied by the caller.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
import sys
from typing import Any, Iterator, Mapping


ROOT = Path(__file__).resolve().parents[1]
AUTOMATION_ROOT = ROOT / "tmp/reddit-voc-candidate-automation"
REGISTRY_ROOT = ROOT / "output/reddit-voc-candidate-registry"
LOCK_NAME = "candidate-build.lock"

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,95}$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")

SAFE_BOUNDARIES: dict[str, bool] = {
    "database_write": False,
    "deploy": False,
    "deployment": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_attempt_made": False,
    "provider_call": False,
    "remote_write": False,
    "schedule_change": False,
}
MINIMUM_SAFE_BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}

FINAL_LINEAGE_KEYS = {
    "plan_a_candidate_input_sha256",
    "plan_a_candidate_data_manifest_sha256",
    "plan_a_validation_receipt_sha256",
    "frontend_candidate_input_sha256",
    "frontend_source_manifest_sha256",
    "frontend_source_validation_receipt_sha256",
    "build_contract_sha256",
}
FINAL_NATIVE_V3_LINEAGE_KEYS = {
    "frontend_candidate_input_sha256",
    "frontend_source_manifest_sha256",
    "frontend_source_validation_receipt_sha256",
    "frontend_source_stage_receipt_sha256",
    "build_contract_sha256",
}
FINAL_RELEASE_KEYS = {
    "release_sha256",
    "dist_manifest_sha256",
    "release_manifest_sha256",
    "release_manifest_evidence_sha256",
}
FINAL_DELIVERABLE_KEYS = {"image_tar_sha256", "transfer_tgz_sha256"}
FINAL_EVIDENCE_KEYS = {
    "browser_e2e_evidence_sha256",
    "container_evidence_sha256",
    "export_evidence_sha256",
    "security_evidence_sha256",
    "ui_validation_evidence_sha256",
}
V3_MANIFEST_FAMILIES = (
    "source",
    "canonical",
    "facts",
    "metrics",
    "integrity",
    "personas",
    "casebook",
    "reports",
    "insights",
    "export",
)
V3_RECEIPT_FAMILIES = (*V3_MANIFEST_FAMILIES, "e2e", "container")
V3_LINEAGE_ARTIFACT_KEYS = {
    *(f"{family}_manifest" for family in V3_MANIFEST_FAMILIES),
    *(f"{family}_receipt" for family in V3_RECEIPT_FAMILIES),
}
V3_NATIVE_LINEAGE_ARTIFACT_KEYS = {
    "v3_frontend_source_manifest",
    "v3_frontend_source_receipt",
    "v3_frontend_source_stage_receipt",
    "v3_base_manifest",
    "v3_base_receipt",
    "v3_insights_manifest",
    "v3_insights_receipt",
    "v3_reports_manifest",
    "v3_reports_receipt",
    "v3_personas_manifest",
    "v3_personas_receipt",
}
V3_FRONTEND_SOURCE_SCHEMA = "reddit_voc_frontend_source_manifest_v2"
V3_FRONTEND_RECEIPT_SCHEMA = "reddit_voc_candidate_ui_source_validation_receipt_v2"
V3_FRONTEND_STAGE_RECEIPT_SCHEMA = "reddit_voc_frontend_source_stage_receipt_v1"
V3_FRONTEND_LINEAGE_CONTRACT = "reddit_voc_v3_four_dataset_frontend_lineage_v1"
V3_FRONTEND_LINEAGE_CONTRACTS = {
    V3_FRONTEND_LINEAGE_CONTRACT,
    "reddit_voc_v3_seven_dataset_frontend_lineage_v2",
}
V3_CORE_DATASET_KEYS = {"base", "insights", "reports", "personas"}
V3_AUXILIARY_DATASET_KEYS = {"brand_health", "quarter_insights", "casebook"}
V3_DATASET_MANIFEST_SCHEMAS = {
    "base": "reddit_voc_site_snapshot_manifest_v3",
    "insights": "reddit_voc_insights_public_manifest_v3",
    "reports": "reddit_voc_reports_public_manifest_v3",
    "personas": "reddit_voc_personas_manifest_v3",
}
V3_DATASET_RECEIPT_SCHEMAS = {
    "base": "reddit_voc_base_public_validation_receipt_v1",
    "insights": "reddit_voc_insights_public_validation_receipt_v3",
    "reports": "reddit_voc_reports_public_validation_receipt_v3",
    "personas": "reddit_voc_personas_validation_v3",
}
V3_RECEIPT_POLICIES: dict[str, dict[str, object]] = {
    "source_receipt": {
        "schema_version": "reddit_voc_source_manifest_validation_receipt_v1",
        "status": "passed",
        "consumption_status": "eligible_for_downstream_consumption",
    },
    "canonical_receipt": {
        "schema_version": "reddit_voc_canonical_snapshot_validation_receipt_v1",
        "status": "passed",
        "consumption_status": "eligible_for_downstream_consumption",
    },
    "facts_receipt": {
        "schema_version": "reddit_voc_voc_facts_validation_receipt_v2",
        "status": "passed",
        "consumption_status": "eligible_for_downstream_consumption",
    },
    "metrics_receipt": {
        "schema_version": "reddit_voc_metrics_validation_receipt_v1",
        "status": "passed_candidate_only",
        "consumption_status": "eligible_for_downstream_consumption",
    },
    "integrity_receipt": {
        "schema_version": "reddit_voc_integrity_snapshot_validation_receipt_v1",
        "status": "passed",
        "consumption_status": "ready_for_task9_candidate",
    },
    "personas_receipt": {
        "schema_version": "reddit_voc_personas_validation_v3",
        "status": "passed",
        "consumption_status": "eligible_for_downstream_consumption",
        "top_level_boundaries": True,
    },
    "casebook_receipt": {
        "schema_version": "reddit_voc_governance_casebook_validation_receipt_v1",
        "status": "passed",
        "consumption_status": "eligible_for_private_casebook_review",
    },
    "reports_receipt": {
        "schema_version": "reddit_voc_reports_validation_receipt_v3",
        "status": "passed_candidate_only",
        "consumption_status": "eligible_for_frontend_candidate_consumption",
    },
    "insights_receipt": {
        "schema_version": "reddit_voc_insights_validation_receipt_v3",
        "status": "passed_candidate_only",
        "consumption_status": "eligible_for_frontend_candidate_consumption",
    },
    "export_receipt": {
        "schema_version": "reddit_voc_export_bundle_validation_receipt_v1",
        "status": "passed",
        "consumption_status": "eligible_for_local_candidate_registry",
    },
    "e2e_receipt": {
        "schema_version": "reddit_voc_same_dist_browser_e2e_receipt_v2",
        "status": "passed_local_same_dist_browser_acceptance",
        "lifecycle_required": False,
    },
    "container_receipt": {
        "schema_version": "reddit_voc_local_insights_container_smoke_receipt_v1",
        "status": "passed_local_isolated_container_smoke",
        "lifecycle_required": False,
    },
}
PERSONA_BOUNDARIES: dict[str, bool] = {
    "author_level_personas": False,
    "counts_are_content_entities_not_users": True,
    "database_write": False,
    "demographics_supported": False,
    "deploy": False,
    "live_send": False,
    "population_share_supported": False,
    "production_unchanged": True,
    "provider_call": False,
    "real_user_images": False,
    "remote_write": False,
}
REGISTRY_BASE_ARTIFACT_KEYS = {
    "build_contract",
    "final_validation_receipt",
    "frontend_source_manifest",
    "frontend_source_validation_receipt",
    "plan_a_candidate_data_manifest",
    "plan_a_validation_receipt",
}


class CandidateRegistrationError(ValueError):
    """An explicit candidate input or append-only registry contract failed."""


class CandidateBuildBusy(CandidateRegistrationError):
    """The stable singleton lock is currently held by another process."""


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _canonical_file_bytes(value: object) -> bytes:
    return canonical_bytes(value) + b"\n"


def _sha256_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _require_sha(value: object, *, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise CandidateRegistrationError(f"{label}_invalid")
    return value


def _require_utc(value: object, *, label: str) -> str:
    if not isinstance(value, str) or UTC_RE.fullmatch(value) is None:
        raise CandidateRegistrationError(f"{label}_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CandidateRegistrationError(f"{label}_invalid") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise CandidateRegistrationError(f"{label}_invalid")
    return value


def _ensure_private_directory(path: Path) -> None:
    if path.exists() or path.is_symlink():
        try:
            metadata = os.lstat(path)
        except OSError as exc:
            raise CandidateRegistrationError("private_directory_unsafe") from exc
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise CandidateRegistrationError("private_directory_unsafe")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        _ensure_private_directory(path)
        return
    os.chmod(path, 0o700)


def _regular_bytes(
    path: Path, *, label: str, expected_mode: int | None = None
) -> bytes:
    try:
        path_metadata = os.lstat(path)
    except OSError as exc:
        raise CandidateRegistrationError(f"{label}_missing") from exc
    if stat.S_ISLNK(path_metadata.st_mode) or not stat.S_ISREG(path_metadata.st_mode):
        raise CandidateRegistrationError(f"{label}_unsafe")
    if expected_mode is not None and stat.S_IMODE(path_metadata.st_mode) != expected_mode:
        raise CandidateRegistrationError(f"{label}_mode_invalid")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise CandidateRegistrationError(f"{label}_unsafe") from exc
    try:
        before = os.fstat(descriptor)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        not stat.S_ISREG(before.st_mode)
        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        or (before.st_dev, before.st_ino)
        != (path_metadata.st_dev, path_metadata.st_ino)
    ):
        raise CandidateRegistrationError(f"{label}_drift")
    payload = b"".join(chunks)
    if len(payload) != before.st_size:
        raise CandidateRegistrationError(f"{label}_drift")
    return payload


def _load_canonical_json(
    path: Path, *, label: str, expected_sha256: str, expected_mode: int | None = None
) -> tuple[dict[str, Any], bytes]:
    expected = _require_sha(expected_sha256, label=f"expected_{label}_sha256")
    payload = _regular_bytes(path, label=label, expected_mode=expected_mode)
    if _sha256_bytes(payload) != expected:
        raise CandidateRegistrationError(f"{label}_sha256_mismatch")
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateRegistrationError(f"{label}_invalid_json") from exc
    if not isinstance(value, dict):
        raise CandidateRegistrationError(f"{label}_not_object")
    if payload != _canonical_file_bytes(value):
        raise CandidateRegistrationError(f"{label}_noncanonical")
    return value, payload


def _safe_boundaries(
    value: object, *, label: str, exact: bool = False
) -> dict[str, bool]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, bool) for key, item in value.items()
    ):
        raise CandidateRegistrationError(f"{label}_boundaries_invalid")
    expected = SAFE_BOUNDARIES if exact else MINIMUM_SAFE_BOUNDARIES
    if exact and value != expected:
        raise CandidateRegistrationError(f"{label}_boundaries_invalid")
    if not exact and any(value.get(key) is not item for key, item in expected.items()):
        raise CandidateRegistrationError(f"{label}_boundaries_invalid")
    for key, item in value.items():
        if key != "production_unchanged" and item is not False:
            raise CandidateRegistrationError(f"{label}_boundaries_invalid")
    return dict(value)


def _validate_persona_boundaries(value: Mapping[str, Any], *, label: str) -> None:
    if any(value.get(key) is not expected for key, expected in PERSONA_BOUNDARIES.items()):
        raise CandidateRegistrationError(f"{label}_boundaries_invalid")
    if any(
        key in value and value.get(key) is not expected
        for key, expected in SAFE_BOUNDARIES.items()
    ):
        raise CandidateRegistrationError(f"{label}_boundaries_invalid")


def _validate_v3_receipt(key: str, value: Mapping[str, Any]) -> None:
    policy = V3_RECEIPT_POLICIES.get(key)
    if policy is None:
        raise CandidateRegistrationError(f"v3_{key}_policy_missing")
    schema_valid = value.get("schema_version") == policy["schema_version"]
    if (
        key == "container_receipt"
        and value.get("schema_version")
        == "reddit_voc_local_insights_container_smoke_receipt_v2"
    ):
        schema_valid = True
    if not schema_valid:
        raise CandidateRegistrationError(f"v3_{key}_schema_invalid")
    if value.get("status") != policy["status"]:
        raise CandidateRegistrationError(f"v3_{key}_status_invalid")
    if policy.get("lifecycle_required", True):
        if value.get("promotable") is not True:
            raise CandidateRegistrationError(f"v3_{key}_not_promotable")
        if value.get("consumption_status") != policy["consumption_status"]:
            raise CandidateRegistrationError(f"v3_{key}_consumption_status_invalid")
    if key == "source_receipt":
        summary = value.get("validator_summary")
        if (
            not isinstance(summary, Mapping)
            or summary.get("status") != "passed"
            or summary.get("production_unchanged") is not True
        ):
            raise CandidateRegistrationError("v3_source_receipt_summary_invalid")
    if policy.get("top_level_boundaries") is True:
        _validate_persona_boundaries(value, label=f"v3_{key}")
    else:
        _safe_boundaries(value.get("boundaries"), label=f"v3_{key}")


def _exact_sha_map(value: object, *, keys: set[str], label: str) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != keys:
        raise CandidateRegistrationError(f"{label}_contract_invalid")
    return {key: _require_sha(value[key], label=f"{label}_{key}") for key in sorted(keys)}


@contextmanager
def candidate_lock(automation_root: Path = AUTOMATION_ROOT) -> Iterator[int]:
    """Hold the one stable-inode candidate lock; never unlink or replace it."""

    _ensure_private_directory(automation_root)
    lock_path = automation_root / LOCK_NAME
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise CandidateRegistrationError("candidate_build_lock_unsafe") from exc
    try:
        fd_metadata = os.fstat(descriptor)
        path_metadata = os.lstat(lock_path)
        if (
            stat.S_ISLNK(path_metadata.st_mode)
            or not stat.S_ISREG(path_metadata.st_mode)
            or not stat.S_ISREG(fd_metadata.st_mode)
            or path_metadata.st_uid != os.getuid()
            or stat.S_IMODE(path_metadata.st_mode) != 0o600
            or (fd_metadata.st_dev, fd_metadata.st_ino)
            != (path_metadata.st_dev, path_metadata.st_ino)
        ):
            raise CandidateRegistrationError("candidate_build_lock_unsafe")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise CandidateBuildBusy("candidate_build_already_running") from exc
        current = os.lstat(lock_path)
        if (current.st_dev, current.st_ino) != (fd_metadata.st_dev, fd_metadata.st_ino):
            raise CandidateRegistrationError("candidate_build_lock_inode_changed")
        yield descriptor
        current = os.lstat(lock_path)
        if (current.st_dev, current.st_ino) != (fd_metadata.st_dev, fd_metadata.st_ino):
            raise CandidateRegistrationError("candidate_build_lock_inode_changed")
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_immutable(path: Path, value: Mapping[str, Any], *, label: str) -> str:
    _ensure_private_directory(path.parent)
    payload = _canonical_file_bytes(value)
    if path.exists() or path.is_symlink():
        existing = _regular_bytes(path, label=label, expected_mode=0o600)
        if existing != payload:
            raise CandidateRegistrationError(f"{label}_immutable_collision")
        return "no_change"

    temporary = path.parent / f".{path.name}.tmp-{os.getpid()}-{secrets.token_hex(6)}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            existing = _regular_bytes(path, label=label, expected_mode=0o600)
            if existing != payload:
                raise CandidateRegistrationError(f"{label}_immutable_collision")
            return "no_change"
        os.chmod(path, 0o600)
        _fsync_directory(path.parent)
        return "created"
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


@dataclass(frozen=True)
class RegistrationContract:
    candidate_input_sha256: str
    generated_at_utc: str
    expires_at_utc: str
    release: dict[str, str]
    deliverables: dict[str, str]
    evidence: dict[str, str]
    lineage: dict[str, str]
    artifacts: dict[str, dict[str, object]]
    v3_lineage: dict[str, object] | None = None

    def as_mapping(self) -> dict[str, Any]:
        value = {
            "candidate_input_sha256": self.candidate_input_sha256,
            "generated_at_utc": self.generated_at_utc,
            "expires_at_utc": self.expires_at_utc,
            "release": self.release,
            "deliverables": self.deliverables,
            "evidence": self.evidence,
            "lineage": self.lineage,
            "artifacts": self.artifacts,
        }
        if self.v3_lineage is not None:
            value["v3_lineage"] = self.v3_lineage
        return value


@dataclass(frozen=True)
class PreparedRegistration:
    """Validated, deterministic append-only registry transaction."""

    run_id: str
    contract: dict[str, Any]
    identity: str
    entry_path: Path
    entry: dict[str, Any]
    event_path: Path
    event: dict[str, Any]
    run_path: Path
    run: dict[str, Any]
    commit_path: Path
    commit: dict[str, Any]
    result: dict[str, Any]


def _artifact(path: Path, digest: str) -> dict[str, object]:
    payload = _regular_bytes(path, label="artifact")
    if _sha256_bytes(payload) != digest:
        raise CandidateRegistrationError("artifact_sha256_mismatch")
    return {"path": str(path.absolute()), "bytes": len(payload), "sha256": digest}


def _v3_lineage(
    args: argparse.Namespace,
    *,
    release_sha256: str,
) -> tuple[dict[str, object] | None, dict[str, dict[str, object]]]:
    paths = getattr(args, "v3_artifact_paths", None)
    expected_shas = getattr(args, "expected_v3_artifact_sha256s", None)
    release_id = getattr(args, "v3_release_id", None)
    source_snapshot_id = getattr(args, "v3_source_snapshot_id", None)
    values = (paths, expected_shas, release_id, source_snapshot_id)
    if all(value is None for value in values):
        return None, {}
    if (
        not isinstance(paths, Mapping)
        or set(paths) != V3_LINEAGE_ARTIFACT_KEYS
        or not isinstance(expected_shas, Mapping)
        or set(expected_shas) != V3_LINEAGE_ARTIFACT_KEYS
        or not isinstance(release_id, str)
        or not release_id
        or not isinstance(source_snapshot_id, str)
        or not source_snapshot_id
    ):
        raise CandidateRegistrationError("v3_lineage_contract_invalid")
    shas: dict[str, str] = {}
    artifacts: dict[str, dict[str, object]] = {}
    observed_release_ids: set[str] = set()
    observed_snapshot_ids: set[str] = set()
    for key in sorted(V3_LINEAGE_ARTIFACT_KEYS):
        expected = _require_sha(
            expected_shas[key], label=f"expected_v3_{key}_sha256"
        )
        path = Path(paths[key])
        payload = _regular_bytes(path, label=f"v3_{key}")
        if _sha256_bytes(payload) != expected:
            raise CandidateRegistrationError(f"v3_{key}_sha256_mismatch")
        try:
            value = json.loads(payload)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise CandidateRegistrationError(f"v3_{key}_invalid_json") from exc
        if not isinstance(value, dict) or payload != _canonical_file_bytes(value):
            raise CandidateRegistrationError(f"v3_{key}_noncanonical")
        if key.endswith("_receipt"):
            _validate_v3_receipt(key, value)
        elif key == "personas_manifest":
            if value.get("boundaries") != PERSONA_BOUNDARIES:
                raise CandidateRegistrationError("v3_personas_manifest_boundaries_invalid")
        else:
            _safe_boundaries(value.get("boundaries"), label=f"v3_{key}")
        if isinstance(value.get("release_id"), str):
            observed_release_ids.add(str(value["release_id"]))
        if isinstance(value.get("source_snapshot_id"), str):
            observed_snapshot_ids.add(str(value["source_snapshot_id"]))
        candidate_release = value.get("candidate_release_sha256")
        if candidate_release is not None and candidate_release != release_sha256:
            raise CandidateRegistrationError("v3_candidate_release_mismatch")
        shas[key] = expected
        artifacts[f"v3_{key}"] = _artifact(path, expected)
    if observed_release_ids - {release_id}:
        raise CandidateRegistrationError("v3_mixed_release_id")
    if observed_snapshot_ids - {source_snapshot_id}:
        raise CandidateRegistrationError("v3_mixed_source_snapshot_id")
    return {
        "artifact_sha256s": shas,
        "candidate_release_sha256": release_sha256,
        "release_id": release_id,
        "source_snapshot_id": source_snapshot_id,
    }, artifacts


def _native_v3_boundary(value: Mapping[str, Any], *, label: str, flat: bool = False) -> None:
    boundaries = value if flat else value.get("boundaries")
    if label == "v3_personas_receipt" and flat:
        _validate_persona_boundaries(value, label=label)
        return
    if (
        label in {"v3_personas_manifest", "v3_personas_receipt"}
        and isinstance(boundaries, Mapping)
        and "author_level_personas" in boundaries
    ):
        _validate_persona_boundaries(boundaries, label=label)
        return
    _safe_boundaries(boundaries, label=label)


def _validate_periodic_report_publication(
    value: object, *, release_id: str, label: str
) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {
        "assets",
        "bundle_id",
        "contract",
        "data_release_id",
        "manifest_relative_path",
        "manifest_sha256",
        "source_bundle_manifest_sha256",
    }:
        raise CandidateRegistrationError(f"{label}_contract_invalid")
    bundle_id = value.get("bundle_id")
    if (
        value.get("contract") != "reddit_voc_periodic_report_frontend_publication_v1"
        or value.get("data_release_id") != release_id
        or not isinstance(bundle_id, str)
        or not bundle_id.startswith("periodic_")
        or SHA256_RE.fullmatch(str(value.get("manifest_sha256"))) is None
        or SHA256_RE.fullmatch(str(value.get("source_bundle_manifest_sha256"))) is None
        or value.get("manifest_relative_path")
        != f"public/periodic-report-assets/{bundle_id}/manifest.json"
    ):
        raise CandidateRegistrationError(f"{label}_contract_invalid")
    assets = value.get("assets")
    if not isinstance(assets, list) or len(assets) != 3:
        raise CandidateRegistrationError(f"{label}_assets_invalid")
    grains: set[str] = set()
    for row in assets:
        if not isinstance(row, Mapping) or set(row) != {
            "bytes",
            "grain",
            "relative_path",
            "sha256",
        }:
            raise CandidateRegistrationError(f"{label}_assets_invalid")
        grain = row.get("grain")
        path = row.get("relative_path")
        if (
            grain not in {"daily", "weekly", "monthly"}
            or grain in grains
            or isinstance(row.get("bytes"), bool)
            or not isinstance(row.get("bytes"), int)
            or row["bytes"] <= 0
            or path
            != f"public/periodic-report-assets/{bundle_id}/public/{grain}/poster.png"
            or PurePosixPath(str(path)).is_absolute()
            or ".." in PurePosixPath(str(path)).parts
            or SHA256_RE.fullmatch(str(row.get("sha256"))) is None
        ):
            raise CandidateRegistrationError(f"{label}_assets_invalid")
        grains.add(str(grain))
    if grains != {"daily", "weekly", "monthly"}:
        raise CandidateRegistrationError(f"{label}_assets_invalid")
    return value


def _load_v3_native_artifacts(
    args: argparse.Namespace,
    *,
    release_manifest: Mapping[str, Any],
    release_sha256: str,
) -> tuple[dict[str, object], dict[str, dict[str, object]], dict[str, str]]:
    paths = getattr(args, "v3_native_artifact_paths", None)
    expected_shas = getattr(args, "expected_v3_native_artifact_sha256s", None)
    release_id = getattr(args, "v3_release_id", None)
    source_snapshot_id = getattr(args, "v3_source_snapshot_id", None)
    if (
        not isinstance(paths, Mapping)
        or set(paths) != V3_NATIVE_LINEAGE_ARTIFACT_KEYS
        or not isinstance(expected_shas, Mapping)
        or set(expected_shas) != V3_NATIVE_LINEAGE_ARTIFACT_KEYS
        or not isinstance(release_id, str)
        or not release_id
        or not isinstance(source_snapshot_id, str)
        or not source_snapshot_id
    ):
        raise CandidateRegistrationError("v3_native_lineage_contract_invalid")

    values: dict[str, dict[str, Any]] = {}
    artifacts: dict[str, dict[str, object]] = {}
    shas: dict[str, str] = {}
    for key in sorted(V3_NATIVE_LINEAGE_ARTIFACT_KEYS):
        expected = _require_sha(
            expected_shas[key], label=f"expected_{key}_sha256"
        )
        path = Path(paths[key])
        payload = _regular_bytes(path, label=key)
        if _sha256_bytes(payload) != expected:
            raise CandidateRegistrationError(f"{key}_sha256_mismatch")
        try:
            value = json.loads(payload)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise CandidateRegistrationError(f"{key}_invalid_json") from exc
        if (
            not isinstance(value, dict)
            or key != "v3_personas_receipt"
            and payload != _canonical_file_bytes(value)
        ):
            raise CandidateRegistrationError(f"{key}_noncanonical")
        values[key] = value
        shas[key] = expected
        artifacts[key] = _artifact(path, expected)

    source_manifest = values["v3_frontend_source_manifest"]
    source_receipt = values["v3_frontend_source_receipt"]
    source_stage_receipt = values["v3_frontend_source_stage_receipt"]
    frontend_input = source_manifest.get("frontend_candidate_input_sha256")
    source_manifest_sha = shas["v3_frontend_source_manifest"]
    if (
        source_manifest.get("schema_version") != V3_FRONTEND_SOURCE_SCHEMA
        or source_manifest.get("status") != "frontend_source_frozen_local"
        or not isinstance(frontend_input, str)
        or SHA256_RE.fullmatch(frontend_input) is None
    ):
        raise CandidateRegistrationError("v3_frontend_source_manifest_contract_invalid")
    _native_v3_boundary(source_manifest, label="v3_frontend_source_manifest")
    upstream = source_manifest.get("upstream")
    lineage = upstream.get("v3_lineage") if isinstance(upstream, Mapping) else None
    periodic_publication = (
        upstream.get("periodic_report_publication")
        if isinstance(upstream, Mapping)
        else None
    )
    datasets = lineage.get("datasets") if isinstance(lineage, Mapping) else None
    if (
        not isinstance(upstream, Mapping)
        or set(upstream) not in (
            {"v3_lineage"},
            {"v3_lineage", "periodic_report_publication"},
        )
        or not isinstance(lineage, dict)
        or lineage.get("contract") not in V3_FRONTEND_LINEAGE_CONTRACTS
        or lineage.get("source_snapshot_id") != source_snapshot_id
        or not isinstance(datasets, dict)
        or set(datasets) != V3_CORE_DATASET_KEYS
    ):
        raise CandidateRegistrationError("v3_frontend_source_lineage_invalid")
    periodic_publication = _validate_periodic_report_publication(
        periodic_publication,
        release_id=release_id,
        label="v3_periodic_report_publication",
    )
    lineage_contract = lineage["contract"]
    auxiliary_manifests = lineage.get("auxiliary_public_manifests")
    if lineage_contract == "reddit_voc_v3_seven_dataset_frontend_lineage_v2":
        if (
            set(lineage) != {
                "auxiliary_public_manifests",
                "contract",
                "current_release_pointer_sha256",
                "datasets",
                "source_snapshot_id",
            }
            or not isinstance(auxiliary_manifests, list)
            or len(auxiliary_manifests) != len(V3_AUXILIARY_DATASET_KEYS)
        ):
            raise CandidateRegistrationError("v3_frontend_source_auxiliary_lineage_invalid")
    elif auxiliary_manifests not in (None, []):
        raise CandidateRegistrationError("v3_frontend_source_auxiliary_lineage_invalid")
    if (
        source_receipt.get("schema_version") != V3_FRONTEND_RECEIPT_SCHEMA
        or source_receipt.get("status") != "passed_local_source_validation"
        or source_receipt.get("frontend_candidate_input_sha256") != frontend_input
        or source_receipt.get("frontend_source_manifest_sha256")
        != source_manifest_sha
        or source_receipt.get("v3_lineage") != lineage
        or source_receipt.get("periodic_report_publication")
        != periodic_publication
    ):
        raise CandidateRegistrationError("v3_frontend_source_receipt_contract_invalid")
    _native_v3_boundary(source_receipt, label="v3_frontend_source_receipt")
    if (
        source_stage_receipt.get("schema_version") != V3_FRONTEND_STAGE_RECEIPT_SCHEMA
        or source_stage_receipt.get("status") != "source_stage_materialized_local"
        or source_stage_receipt.get("frontend_candidate_input_sha256") != frontend_input
        or source_stage_receipt.get("frontend_source_manifest_sha256")
        != source_manifest_sha
        or source_stage_receipt.get("frontend_source_manifest_schema")
        != V3_FRONTEND_SOURCE_SCHEMA
    ):
        raise CandidateRegistrationError("v3_frontend_source_stage_receipt_contract_invalid")
    _native_v3_boundary(
        source_stage_receipt, label="v3_frontend_source_stage_receipt"
    )

    for name in ("base", "insights", "reports", "personas"):
        manifest_key = f"v3_{name}_manifest"
        receipt_key = f"v3_{name}_receipt"
        manifest = values[manifest_key]
        receipt = values[receipt_key]
        binding = datasets.get(name)
        observed_version = (
            manifest.get("snapshot_id")
            if name == "personas"
            else manifest.get("dataset_version")
        )
        observed_snapshot = (
            manifest.get("governed_signal_source_snapshot_id")
            if name == "personas"
            else manifest.get("source_snapshot_id")
        )
        if (
            not isinstance(binding, Mapping)
            or manifest.get("schema_version") != V3_DATASET_MANIFEST_SCHEMAS[name]
            or observed_version != binding.get("dataset_version")
            or observed_snapshot != source_snapshot_id
            or binding.get("public_manifest_sha256") != shas[manifest_key]
            or binding.get("validation_receipt_sha256") != shas[receipt_key]
            or binding.get("validation_receipt_schema")
            != V3_DATASET_RECEIPT_SCHEMAS[name]
            or manifest.get("promotable") is not True
        ):
            raise CandidateRegistrationError(f"v3_{name}_dataset_lineage_invalid")
        _native_v3_boundary(manifest, label=manifest_key)
        expected_status = "passed" if name == "personas" else "passed_candidate_only"
        receipt_manifest_sha = (
            receipt.get("manifest_sha256")
            if name == "personas"
            else receipt.get("bundle_manifest_sha256")
        )
        if (
            receipt.get("schema_version") != V3_DATASET_RECEIPT_SCHEMAS[name]
            or receipt.get("status") != expected_status
            or receipt.get("promotable") is not True
            or receipt_manifest_sha != shas[manifest_key]
        ):
            raise CandidateRegistrationError(f"v3_{name}_receipt_lineage_invalid")
        _native_v3_boundary(receipt, label=receipt_key, flat=name == "personas")
        expected_lineage_sha = (
            shas[manifest_key]
            if name == "personas"
            else manifest.get("lineage_manifest_sha256")
        )
        if binding.get("lineage_manifest_sha256") != expected_lineage_sha:
            raise CandidateRegistrationError(f"v3_{name}_private_lineage_invalid")

    frontend_source = release_manifest.get("frontend_source")
    release_current = release_manifest.get("current_release")
    release_dataset_versions = release_manifest.get("dataset_versions")
    release_dataset_manifests = release_manifest.get("dataset_manifests")
    if (
        not isinstance(frontend_source, Mapping)
        or frontend_source.get("contract_schema_version") != V3_FRONTEND_SOURCE_SCHEMA
        or frontend_source.get("frontend_candidate_input_sha256") != frontend_input
        or frontend_source.get("manifest", {}).get("sha256") != source_manifest_sha
        or frontend_source.get("validation_receipt", {}).get("sha256")
        != shas["v3_frontend_source_receipt"]
        or frontend_source.get("v3_lineage") != lineage
        or frontend_source.get("periodic_report_publication")
        != periodic_publication
        or not isinstance(release_current, Mapping)
        or release_current.get("release_id") != release_id
        or release_current.get("sha256") != lineage.get("current_release_pointer_sha256")
        or not isinstance(release_dataset_versions, Mapping)
        or not isinstance(release_dataset_manifests, Mapping)
        or set(release_dataset_versions)
        != (
            V3_CORE_DATASET_KEYS | V3_AUXILIARY_DATASET_KEYS
            if lineage_contract == "reddit_voc_v3_seven_dataset_frontend_lineage_v2"
            else V3_CORE_DATASET_KEYS
        )
        or set(release_dataset_manifests) != set(release_dataset_versions)
    ):
        raise CandidateRegistrationError("v3_release_frontend_lineage_invalid")
    for name in ("base", "insights", "reports", "personas"):
        binding = datasets[name]
        release_binding = release_dataset_manifests[name]
        public_path = binding.get("public_manifest_relative_path")
        if (
            not isinstance(public_path, str)
            or not public_path.startswith("public/")
            or release_dataset_versions[name] != binding.get("dataset_version")
            or not isinstance(release_binding, Mapping)
            or release_binding.get("manifest_path") != public_path.removeprefix("public/")
            or release_binding.get("public_manifest_sha256")
            != binding.get("public_manifest_sha256")
            or release_binding.get("lineage_manifest_sha256")
            != binding.get("lineage_manifest_sha256")
        ):
            raise CandidateRegistrationError(f"v3_{name}_release_lineage_invalid")
    if lineage_contract == "reddit_voc_v3_seven_dataset_frontend_lineage_v2":
        auxiliary_by_path: dict[str, Mapping[str, Any]] = {}
        for row in auxiliary_manifests:
            if (
                not isinstance(row, Mapping)
                or set(row) != {"relative_path", "sha256"}
                or not isinstance(row.get("relative_path"), str)
                or not isinstance(row.get("sha256"), str)
                or SHA256_RE.fullmatch(row["sha256"]) is None
                or row["relative_path"] in auxiliary_by_path
            ):
                raise CandidateRegistrationError(
                    "v3_frontend_source_auxiliary_lineage_invalid"
                )
            auxiliary_by_path[row["relative_path"]] = row
        for name in V3_AUXILIARY_DATASET_KEYS:
            version = release_dataset_versions[name]
            release_binding = release_dataset_manifests[name]
            expected_manifest_path = f"data/reddit-voc/{version}/manifest.json"
            source_binding = auxiliary_by_path.get(f"public/{expected_manifest_path}")
            if (
                not isinstance(version, str)
                or not isinstance(release_binding, Mapping)
                or release_binding.get("manifest_path") != expected_manifest_path
                or not isinstance(source_binding, Mapping)
                or release_binding.get("public_manifest_sha256")
                != source_binding.get("sha256")
                or release_binding.get("lineage_manifest_sha256")
                != source_binding.get("sha256")
            ):
                raise CandidateRegistrationError(
                    f"v3_{name}_release_lineage_invalid"
                )

    build_receipt = None
    if hasattr(args, "build_contract"):
        build_payload = _regular_bytes(Path(args.build_contract), label="build_contract")
        try:
            build_receipt = json.loads(build_payload)
        except (UnicodeError, json.JSONDecodeError):
            build_receipt = None
    if isinstance(build_receipt, Mapping):
        expected_data_lineage = {
            "current_release": release_current,
            "dataset_manifests": release_dataset_manifests,
            "dataset_versions": release_dataset_versions,
        }
        if (
            build_receipt.get("schema_version")
            == "reddit_voc_insights_build_receipt_v1"
            and (
                build_receipt.get("release_sha256") != release_sha256
                or build_receipt.get("frontend_source") != frontend_source
                or build_receipt.get("data_lineage") != expected_data_lineage
            )
        ):
            raise CandidateRegistrationError("v3_build_receipt_lineage_invalid")

    return {
        "artifact_sha256s": shas,
        "candidate_release_sha256": release_sha256,
        "release_id": release_id,
        "source_snapshot_id": source_snapshot_id,
    }, artifacts, {
        "frontend_candidate_input_sha256": frontend_input,
        "frontend_source_manifest_sha256": shas["v3_frontend_source_manifest"],
        "frontend_source_validation_receipt_sha256": shas["v3_frontend_source_receipt"],
        "frontend_source_stage_receipt_sha256": shas["v3_frontend_source_stage_receipt"],
    }


def _validate_native_v3_registration_inputs(args: argparse.Namespace) -> dict[str, Any]:
    build_contract_sha = _require_sha(
        args.expected_build_contract_sha256, label="expected_build_contract_sha256"
    )
    build_contract_payload = _regular_bytes(Path(args.build_contract), label="build_contract")
    if _sha256_bytes(build_contract_payload) != build_contract_sha:
        raise CandidateRegistrationError("build_contract_sha256_mismatch")

    release_payload, release_manifest_sha = _checked_payload(
        args.release_manifest,
        args.expected_release_manifest_sha256,
        label="release_manifest",
    )
    try:
        release_manifest = json.loads(release_payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateRegistrationError("release_manifest_invalid_json") from exc
    release_sha = (
        release_manifest.get("release_sha256")
        if isinstance(release_manifest, Mapping)
        else None
    )
    if (
        not isinstance(release_manifest, Mapping)
        or release_manifest.get("schema_version")
        != "reddit_voc_insights_site_release_v2"
        or not isinstance(release_sha, str)
        or SHA256_RE.fullmatch(release_sha) is None
    ):
        raise CandidateRegistrationError("release_manifest_contract_invalid")

    v3_lineage, v3_artifacts, native_lineage = _load_v3_native_artifacts(
        args, release_manifest=release_manifest, release_sha256=release_sha
    )
    lineage = {
        **native_lineage,
        "build_contract_sha256": build_contract_sha,
    }

    final_receipt, _ = _load_canonical_json(
        Path(args.final_receipt),
        label="final_receipt",
        expected_sha256=args.expected_final_receipt_sha256,
        expected_mode=0o600,
    )
    if (
        set(final_receipt)
        != {
            "schema_version",
            "status",
            "generated_at_utc",
            "expires_at_utc",
            "lineage",
            "release",
            "deliverables",
            "evidence",
            "v3_lineage",
            "boundaries",
        }
        or final_receipt.get("schema_version")
        != "reddit_voc_candidate_ui_validation_receipt_v2"
        or final_receipt.get("status") != "passed_local_candidate_validation"
    ):
        raise CandidateRegistrationError("final_receipt_contract_invalid")
    generated_at = _require_utc(final_receipt.get("generated_at_utc"), label="generated_at_utc")
    expires_at = _require_utc(final_receipt.get("expires_at_utc"), label="expires_at_utc")
    if expires_at <= generated_at:
        raise CandidateRegistrationError("final_receipt_expiry_invalid")
    observed_lineage = _exact_sha_map(
        final_receipt.get("lineage"),
        keys=FINAL_NATIVE_V3_LINEAGE_KEYS,
        label="lineage",
    )
    if observed_lineage != lineage:
        raise CandidateRegistrationError("final_receipt_lineage_invalid")
    release = _exact_sha_map(final_receipt.get("release"), keys=FINAL_RELEASE_KEYS, label="release")
    if (
        release["release_sha256"] != release_sha
        or release["release_manifest_sha256"] != release_manifest_sha
    ):
        raise CandidateRegistrationError("final_receipt_release_invalid")
    deliverables = _exact_sha_map(
        final_receipt.get("deliverables"),
        keys=FINAL_DELIVERABLE_KEYS,
        label="deliverables",
    )
    evidence = _exact_sha_map(final_receipt.get("evidence"), keys=FINAL_EVIDENCE_KEYS, label="evidence")
    if final_receipt.get("v3_lineage") != v3_lineage:
        raise CandidateRegistrationError("final_receipt_v3_lineage_invalid")
    _safe_boundaries(final_receipt.get("boundaries"), label="final_receipt", exact=True)

    candidate_input_document = {
        "schema_version": "reddit_voc_candidate_input_identity_v2",
        "frontend": native_lineage,
        "build_contract_sha256": build_contract_sha,
        "v3_lineage": v3_lineage,
    }
    candidate_input_sha = _sha256_bytes(canonical_bytes(candidate_input_document))
    artifacts = {
        "build_contract": _artifact(Path(args.build_contract), build_contract_sha),
        "final_validation_receipt": _artifact(
            Path(args.final_receipt), args.expected_final_receipt_sha256
        ),
        **v3_artifacts,
    }
    return RegistrationContract(
        candidate_input_sha256=candidate_input_sha,
        generated_at_utc=generated_at,
        expires_at_utc=expires_at,
        release=release,
        deliverables=deliverables,
        evidence=evidence,
        lineage=observed_lineage,
        artifacts=artifacts,
        v3_lineage=v3_lineage,
    ).as_mapping()


def validate_registration_inputs(args: argparse.Namespace) -> dict[str, Any]:
    if getattr(args, "native_v3", False):
        return _validate_native_v3_registration_inputs(args)

    plan_a_input = _require_sha(
        args.expected_plan_a_input_sha256, label="expected_plan_a_input_sha256"
    )
    if Path(args.plan_a_root).name != plan_a_input:
        raise CandidateRegistrationError("plan_a_root_identity_mismatch")
    plan_a_manifest_path = Path(args.plan_a_root) / "candidate-data-manifest.json"
    plan_a_receipt_path = Path(args.plan_a_root) / "candidate-data-validation-receipt.json"
    plan_a_manifest, _ = _load_canonical_json(
        plan_a_manifest_path,
        label="plan_a_manifest",
        expected_sha256=args.expected_plan_a_manifest_sha256,
        expected_mode=0o600,
    )
    plan_a_receipt, _ = _load_canonical_json(
        plan_a_receipt_path,
        label="plan_a_receipt",
        expected_sha256=args.expected_plan_a_receipt_sha256,
        expected_mode=0o600,
    )
    if (
        plan_a_manifest.get("schema_version") != "reddit_voc_candidate_data_manifest_v1"
        or plan_a_manifest.get("candidate_input_sha256") != plan_a_input
        or plan_a_receipt.get("schema_version")
        != "reddit_voc_candidate_data_validation_receipt_v1"
        or plan_a_receipt.get("status") != "passed"
        or plan_a_receipt.get("candidate_input_sha256") != plan_a_input
        or plan_a_receipt.get("candidate_data_manifest_sha256")
        != args.expected_plan_a_manifest_sha256
    ):
        raise CandidateRegistrationError("plan_a_contract_invalid")
    reconciliation = plan_a_manifest.get("reconciliation")
    if (
        not isinstance(reconciliation, dict)
        or plan_a_receipt.get("reconciliation_sha256") != reconciliation.get("sha256")
        or SHA256_RE.fullmatch(str(reconciliation.get("sha256"))) is None
    ):
        raise CandidateRegistrationError("plan_a_reconciliation_invalid")
    _safe_boundaries(plan_a_manifest.get("boundaries"), label="plan_a_manifest")
    _safe_boundaries(plan_a_receipt.get("boundaries"), label="plan_a_receipt")

    plan_b_input = _require_sha(
        args.expected_plan_b_input_sha256, label="expected_plan_b_input_sha256"
    )
    source_manifest, _ = _load_canonical_json(
        Path(args.plan_b_source_manifest),
        label="plan_b_source_manifest",
        expected_sha256=args.expected_plan_b_source_manifest_sha256,
        expected_mode=0o600,
    )
    source_receipt, _ = _load_canonical_json(
        Path(args.plan_b_source_receipt),
        label="plan_b_source_receipt",
        expected_sha256=args.expected_plan_b_source_receipt_sha256,
        expected_mode=0o600,
    )
    if (
        source_manifest.get("schema_version") != "reddit_voc_frontend_source_manifest_v1"
        or source_manifest.get("status") != "frontend_source_frozen_local"
        or source_manifest.get("frontend_candidate_input_sha256") != plan_b_input
        or source_receipt.get("schema_version")
        != "reddit_voc_candidate_ui_source_validation_receipt_v1"
        or source_receipt.get("status") != "passed_local_source_validation"
        or source_receipt.get("frontend_candidate_input_sha256") != plan_b_input
        or source_receipt.get("frontend_source_manifest_sha256")
        != args.expected_plan_b_source_manifest_sha256
    ):
        raise CandidateRegistrationError("plan_b_contract_invalid")
    for label, upstream in (
        ("plan_b_source_manifest", source_manifest.get("upstream")),
        ("plan_b_source_receipt", source_receipt.get("upstream")),
    ):
        if not isinstance(upstream, dict) or any(
            upstream.get(key) != expected
            for key, expected in {
                "plan_a_candidate_input_sha256": plan_a_input,
                "plan_a_candidate_data_manifest_sha256": args.expected_plan_a_manifest_sha256,
                "plan_a_independent_validation_receipt_sha256": args.expected_plan_a_receipt_sha256,
                "plan_a_reconciliation_sha256": reconciliation["sha256"],
            }.items()
        ):
            raise CandidateRegistrationError(f"{label}_lineage_invalid")
    _safe_boundaries(source_manifest.get("boundaries"), label="plan_b_source_manifest")
    _safe_boundaries(source_receipt.get("boundaries"), label="plan_b_source_receipt")

    build_contract_sha = _require_sha(
        args.expected_build_contract_sha256, label="expected_build_contract_sha256"
    )
    build_contract_payload = _regular_bytes(Path(args.build_contract), label="build_contract")
    if _sha256_bytes(build_contract_payload) != build_contract_sha:
        raise CandidateRegistrationError("build_contract_sha256_mismatch")

    final_receipt, _ = _load_canonical_json(
        Path(args.final_receipt),
        label="final_receipt",
        expected_sha256=args.expected_final_receipt_sha256,
        expected_mode=0o600,
    )
    if (
        set(final_receipt)
        != {
            "schema_version",
            "status",
            "generated_at_utc",
            "expires_at_utc",
            "lineage",
            "release",
            "deliverables",
            "evidence",
            "boundaries",
        }
        or final_receipt.get("schema_version")
        != "reddit_voc_candidate_ui_validation_receipt_v1"
        or final_receipt.get("status") != "passed_local_candidate_validation"
    ):
        raise CandidateRegistrationError("final_receipt_contract_invalid")
    generated_at = _require_utc(final_receipt.get("generated_at_utc"), label="generated_at_utc")
    expires_at = _require_utc(final_receipt.get("expires_at_utc"), label="expires_at_utc")
    if expires_at <= generated_at:
        raise CandidateRegistrationError("final_receipt_expiry_invalid")
    lineage = _exact_sha_map(final_receipt.get("lineage"), keys=FINAL_LINEAGE_KEYS, label="lineage")
    expected_lineage = {
        "plan_a_candidate_input_sha256": plan_a_input,
        "plan_a_candidate_data_manifest_sha256": args.expected_plan_a_manifest_sha256,
        "plan_a_validation_receipt_sha256": args.expected_plan_a_receipt_sha256,
        "frontend_candidate_input_sha256": plan_b_input,
        "frontend_source_manifest_sha256": args.expected_plan_b_source_manifest_sha256,
        "frontend_source_validation_receipt_sha256": args.expected_plan_b_source_receipt_sha256,
        "build_contract_sha256": build_contract_sha,
    }
    if lineage != expected_lineage:
        raise CandidateRegistrationError("final_receipt_lineage_invalid")
    release = _exact_sha_map(final_receipt.get("release"), keys=FINAL_RELEASE_KEYS, label="release")
    deliverables = _exact_sha_map(
        final_receipt.get("deliverables"),
        keys=FINAL_DELIVERABLE_KEYS,
        label="deliverables",
    )
    evidence = _exact_sha_map(final_receipt.get("evidence"), keys=FINAL_EVIDENCE_KEYS, label="evidence")
    _safe_boundaries(final_receipt.get("boundaries"), label="final_receipt", exact=True)

    v3_lineage, v3_artifacts = _v3_lineage(
        args, release_sha256=release["release_sha256"]
    )
    candidate_input_document = {
        "schema_version": "reddit_voc_candidate_input_identity_v1",
        "plan_a": {
            "candidate_input_sha256": plan_a_input,
            "candidate_data_manifest_sha256": args.expected_plan_a_manifest_sha256,
            "validation_receipt_sha256": args.expected_plan_a_receipt_sha256,
        },
        "plan_b": {
            "frontend_candidate_input_sha256": plan_b_input,
            "frontend_source_manifest_sha256": args.expected_plan_b_source_manifest_sha256,
            "source_validation_receipt_sha256": args.expected_plan_b_source_receipt_sha256,
        },
        "build_contract_sha256": build_contract_sha,
    }
    if v3_lineage is not None:
        candidate_input_document["v3_lineage"] = v3_lineage
    candidate_input_sha = _sha256_bytes(canonical_bytes(candidate_input_document))
    artifacts = {
        "build_contract": _artifact(Path(args.build_contract), build_contract_sha),
        "final_validation_receipt": _artifact(
            Path(args.final_receipt), args.expected_final_receipt_sha256
        ),
        "frontend_source_manifest": _artifact(
            Path(args.plan_b_source_manifest), args.expected_plan_b_source_manifest_sha256
        ),
        "frontend_source_validation_receipt": _artifact(
            Path(args.plan_b_source_receipt), args.expected_plan_b_source_receipt_sha256
        ),
        "plan_a_candidate_data_manifest": _artifact(
            plan_a_manifest_path, args.expected_plan_a_manifest_sha256
        ),
        "plan_a_validation_receipt": _artifact(
            plan_a_receipt_path, args.expected_plan_a_receipt_sha256
        ),
        **v3_artifacts,
    }
    return RegistrationContract(
        candidate_input_sha256=candidate_input_sha,
        generated_at_utc=generated_at,
        expires_at_utc=expires_at,
        release=release,
        deliverables=deliverables,
        evidence=evidence,
        lineage=lineage,
        artifacts=artifacts,
        v3_lineage=v3_lineage,
    ).as_mapping()


def candidate_id(contract: Mapping[str, Any]) -> str:
    release = _exact_sha_map(
        contract.get("release"), keys=FINAL_RELEASE_KEYS, label="release"
    )
    identity = {
        "schema_version": "reddit_voc_candidate_identity_v1",
        "candidate_input_sha256": _require_sha(
            contract.get("candidate_input_sha256"), label="candidate_input_sha256"
        ),
        "release": {
            "release_sha256": release["release_sha256"],
            "dist_manifest_sha256": release["dist_manifest_sha256"],
            "release_manifest_evidence_sha256": release[
                "release_manifest_evidence_sha256"
            ],
        },
        "stable_evidence": _exact_sha_map(
            contract.get("evidence"), keys=FINAL_EVIDENCE_KEYS, label="evidence"
        ),
    }
    if "v3_lineage" in contract:
        identity["v3_lineage"] = contract["v3_lineage"]
    return _sha256_bytes(canonical_bytes(identity))


def _entry(contract: Mapping[str, Any], identity: str) -> dict[str, Any]:
    value = {
        "schema_version": (
            "reddit_voc_candidate_registry_entry_v2"
            if "v3_lineage" in contract
            else "reddit_voc_candidate_registry_entry_v1"
        ),
        "status": "registered_local_candidate",
        "phase": "register_only_external_final_artifacts",
        "artifact_build_performed": False,
        "candidate_id": identity,
        "candidate_input_sha256": contract["candidate_input_sha256"],
        "created_at_utc": contract["generated_at_utc"],
        "expires_at_utc": contract["expires_at_utc"],
        "release": contract["release"],
        "deliverables": contract["deliverables"],
        "evidence": contract["evidence"],
        "lineage": contract["lineage"],
        "artifacts": contract["artifacts"],
        "boundaries": dict(SAFE_BOUNDARIES),
    }
    if "v3_lineage" in contract:
        value["v3_lineage"] = contract["v3_lineage"]
    return value


def _event(entry: Mapping[str, Any], entry_sha256: str) -> dict[str, Any]:
    value = {
        "schema_version": (
            "reddit_voc_candidate_registry_event_v2"
            if entry.get("schema_version") == "reddit_voc_candidate_registry_entry_v2"
            else "reddit_voc_candidate_registry_event_v1"
        ),
        "status": "candidate_registered",
        "candidate_id": entry["candidate_id"],
        "candidate_input_sha256": entry["candidate_input_sha256"],
        "entry_sha256": entry_sha256,
        "created_at_utc": entry["created_at_utc"],
        "boundaries": dict(SAFE_BOUNDARIES),
    }
    if value["schema_version"].endswith("_v2"):
        value["entry_schema_version"] = entry["schema_version"]
    return value


def _run(
    run_id: str,
    *,
    status: str,
    result_status: str,
    reason_code: str,
    contract: Mapping[str, Any] | None,
    identity: str | None,
    entry_written: bool,
    event_written: bool,
) -> dict[str, Any]:
    is_v2 = contract is not None and "v3_lineage" in contract
    value = {
        "schema_version": (
            "reddit_voc_candidate_run_v2" if is_v2 else "reddit_voc_candidate_run_v1"
        ),
        "run_id": run_id,
        "status": status,
        "result_status": result_status,
        "reason_code": reason_code,
        "phase": "register_only_external_final_artifacts",
        "artifact_build_performed": False,
        "candidate_id": identity,
        "candidate_input_sha256": (
            contract.get("candidate_input_sha256") if contract is not None else None
        ),
        "entry_written": entry_written,
        "event_written": event_written,
        "boundaries": dict(SAFE_BOUNDARIES),
    }
    if is_v2:
        value["registry_entry_schema_version"] = (
            "reddit_voc_candidate_registry_entry_v2"
        )
    return value


def _commit_marker(
    *,
    run_id: str,
    identity: str,
    candidate_input_sha256: str,
    entry_sha256: str,
    event_sha256: str,
    run_sha256: str,
) -> dict[str, Any]:
    return {
        "schema_version": "reddit_voc_candidate_registry_commit_v1",
        "status": "committed",
        "run_id": run_id,
        "candidate_id": identity,
        "candidate_input_sha256": candidate_input_sha256,
        "entry_sha256": entry_sha256,
        "event_sha256": event_sha256,
        "run_sha256": run_sha256,
        "boundaries": dict(SAFE_BOUNDARIES),
    }


def _reason_code(exc: Exception) -> str:
    value = str(exc)
    return value if re.fullmatch(r"[a-z0-9_.:-]{3,160}", value) else "candidate_registration_failed"


def register_candidate(
    args: argparse.Namespace,
    *,
    automation_root: Path = AUTOMATION_ROOT,
    registry_root: Path = REGISTRY_ROOT,
) -> dict[str, Any]:
    """Validate and register one candidate while owning the global lock."""

    if not isinstance(args.run_id, str) or RUN_ID_RE.fullmatch(args.run_id) is None:
        raise CandidateRegistrationError("run_id_invalid")
    with candidate_lock(automation_root):
        return register_candidate_locked(args, registry_root=registry_root)


def _immutable_target_status(
    path: Path, value: Mapping[str, Any], *, label: str
) -> str:
    """Preflight one immutable target without creating registry members."""

    payload = _canonical_file_bytes(value)
    if path.exists() or path.is_symlink():
        existing = _regular_bytes(path, label=label, expected_mode=0o600)
        if existing != payload:
            raise CandidateRegistrationError(f"{label}_immutable_collision")
        return "no_change"
    return "created"


def prepare_candidate_registration(
    args: argparse.Namespace,
    *,
    registry_root: Path = REGISTRY_ROOT,
) -> PreparedRegistration:
    """Validate and preflight all deterministic registry documents.

    No entry, event, or run is created here.  Callers may therefore persist
    their own immutable precommit receipt before invoking the commit function.
    """

    if not isinstance(args.run_id, str) or RUN_ID_RE.fullmatch(args.run_id) is None:
        raise CandidateRegistrationError("run_id_invalid")
    contract = validate_registration_inputs(args)
    identity = candidate_id(contract)
    entry = _entry(contract, identity)
    entry_path = Path(registry_root) / "entries" / f"{identity}.json"
    entry_status = _immutable_target_status(
        entry_path, entry, label="registry_entry"
    )
    entry_sha = _sha256_bytes(_canonical_file_bytes(entry))
    event = _event(entry, entry_sha)
    event_path = Path(registry_root) / "events" / f"{identity}.registered.json"
    event_status = _immutable_target_status(
        event_path, event, label="registry_event"
    )
    run_path = Path(registry_root) / "runs" / f"{args.run_id}.json"
    result_status = "created" if "created" in {entry_status, event_status} else "no_change"
    if run_path.exists() or run_path.is_symlink():
        existing_run_payload = _regular_bytes(
            run_path, label="registry_run", expected_mode=0o600
        )
        try:
            existing_run = json.loads(existing_run_payload)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise CandidateRegistrationError("registry_run_invalid_json") from exc
        existing_result_status = (
            existing_run.get("result_status")
            if isinstance(existing_run, dict)
            else None
        )
        if existing_result_status not in {"created", "no_change"}:
            raise CandidateRegistrationError("registry_run_contract_invalid")
        result_status = str(existing_result_status)
    run = _run(
        args.run_id,
        status="completed",
        result_status=result_status,
        reason_code="candidate_registered",
        contract=contract,
        identity=identity,
        entry_written=True,
        event_written=True,
    )
    _immutable_target_status(run_path, run, label="registry_run")
    event_sha = _sha256_bytes(_canonical_file_bytes(event))
    run_sha = _sha256_bytes(_canonical_file_bytes(run))
    commit = _commit_marker(
        run_id=args.run_id,
        identity=identity,
        candidate_input_sha256=str(contract["candidate_input_sha256"]),
        entry_sha256=entry_sha,
        event_sha256=event_sha,
        run_sha256=run_sha,
    )
    commit_path = Path(registry_root) / "commits" / f"{args.run_id}.json"
    _immutable_target_status(commit_path, commit, label="registry_commit")
    result = {
        "schema_version": "reddit_voc_candidate_registration_result_v1",
        "status": result_status,
        "phase": "register_only_external_final_artifacts",
        "artifact_build_performed": False,
        "candidate_id": identity,
        "candidate_input_sha256": contract["candidate_input_sha256"],
        "release_sha256": contract["release"]["release_sha256"],
        "entry_sha256": entry_sha,
        "deploy": False,
        "remote_write": False,
        "production_unchanged": True,
    }
    return PreparedRegistration(
        run_id=args.run_id,
        contract=contract,
        identity=identity,
        entry_path=entry_path,
        entry=entry,
        event_path=event_path,
        event=event,
        run_path=run_path,
        run=run,
        commit_path=commit_path,
        commit=commit,
        result=result,
    )


def commit_prepared_candidate(prepared: PreparedRegistration) -> dict[str, Any]:
    """Idempotently commit a preflighted registry transaction.

    The marker is linked last.  Readers recognize a candidate only when this
    marker binds the exact entry, event, and completed run.  A crash can leave a
    recoverable prefix, but never a consumable candidate.
    """

    commit_started = False
    try:
        commit_started = True
        _write_immutable(
            prepared.entry_path, prepared.entry, label="registry_entry"
        )
        _write_immutable(
            prepared.event_path, prepared.event, label="registry_event"
        )
        _write_immutable(prepared.run_path, prepared.run, label="registry_run")
        _write_immutable(
            prepared.commit_path, prepared.commit, label="registry_commit"
        )
    except (CandidateRegistrationError, OSError) as exc:
        if commit_started:
            raise CandidateRegistrationError(
                "candidate_registry_commit_incomplete"
            ) from exc
        raise
    return dict(prepared.result)


def register_candidate_locked(
    args: argparse.Namespace,
    *,
    registry_root: Path = REGISTRY_ROOT,
) -> dict[str, Any]:
    """Register while a caller already owns ``candidate_lock``.

    This exists for the candidate-only orchestrator so the singleton lock covers
    quiescence, source freeze, validation, and the append-only registry commit as
    one uninterrupted local critical section.  Direct callers should continue
    using :func:`register_candidate`.
    """

    if not isinstance(args.run_id, str) or RUN_ID_RE.fullmatch(args.run_id) is None:
        raise CandidateRegistrationError("run_id_invalid")
    try:
        prepared = prepare_candidate_registration(args, registry_root=registry_root)
    except CandidateRegistrationError as exc:
        failed = _run(
            args.run_id,
            status="failed",
            result_status="failed",
            reason_code=_reason_code(exc),
            contract=None,
            identity=None,
            entry_written=False,
            event_written=False,
        )
        try:
            _write_immutable(
                registry_root / "runs" / f"{args.run_id}.json",
                failed,
                label="registry_run",
            )
        except CandidateRegistrationError:
            pass
        raise
    return commit_prepared_candidate(prepared)


def _checked_payload(path: Path, expected_sha256: object, *, label: str) -> tuple[bytes, str]:
    expected = _require_sha(expected_sha256, label=f"expected_{label}_sha256")
    payload = _regular_bytes(Path(path), label=label)
    if _sha256_bytes(payload) != expected:
        raise CandidateRegistrationError(f"{label}_sha256_mismatch")
    return payload, expected


def build_final_ui_receipt(args: argparse.Namespace) -> dict[str, Any]:
    """Build the immutable local final receipt from explicit validated artifacts."""

    generated_at = _require_utc(args.generated_at_utc, label="generated_at_utc")
    expires_at = _require_utc(args.expires_at_utc, label="expires_at_utc")
    if expires_at <= generated_at:
        raise CandidateRegistrationError("final_receipt_expiry_invalid")
    native_v3 = getattr(args, "native_v3", False)
    lineage: dict[str, str]
    v3_lineage: dict[str, object] | None = None
    if not native_v3:
        lineage = {
            "plan_a_candidate_input_sha256": _require_sha(
                args.expected_plan_a_input_sha256, label="expected_plan_a_input_sha256"
            ),
            "plan_a_candidate_data_manifest_sha256": _require_sha(
                args.expected_plan_a_manifest_sha256,
                label="expected_plan_a_manifest_sha256",
            ),
            "plan_a_validation_receipt_sha256": _require_sha(
                args.expected_plan_a_receipt_sha256,
                label="expected_plan_a_receipt_sha256",
            ),
            "frontend_candidate_input_sha256": _require_sha(
                args.expected_plan_b_input_sha256, label="expected_plan_b_input_sha256"
            ),
            "frontend_source_manifest_sha256": _require_sha(
                args.expected_plan_b_source_manifest_sha256,
                label="expected_plan_b_source_manifest_sha256",
            ),
            "frontend_source_validation_receipt_sha256": _require_sha(
                args.expected_plan_b_source_receipt_sha256,
                label="expected_plan_b_source_receipt_sha256",
            ),
            "build_contract_sha256": _require_sha(
                args.expected_build_contract_sha256,
                label="expected_build_contract_sha256",
            ),
        }
    release_payload, release_manifest_sha = _checked_payload(
        args.release_manifest,
        args.expected_release_manifest_sha256,
        label="release_manifest",
    )
    try:
        release_manifest = json.loads(release_payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateRegistrationError("release_manifest_invalid_json") from exc
    release_sha = (
        release_manifest.get("release_sha256")
        if isinstance(release_manifest, dict)
        else None
    )
    if (
        not isinstance(release_manifest, dict)
        or release_manifest.get("schema_version")
        != "reddit_voc_insights_site_release_v2"
        or not isinstance(release_sha, str)
        or SHA256_RE.fullmatch(release_sha) is None
    ):
        raise CandidateRegistrationError("release_manifest_contract_invalid")
    if native_v3:
        v3_lineage, _v3_artifacts, native_lineage = _load_v3_native_artifacts(
            args, release_manifest=release_manifest, release_sha256=release_sha
        )
        lineage = {
            **native_lineage,
            "build_contract_sha256": _require_sha(
                args.expected_build_contract_sha256,
                label="expected_build_contract_sha256",
            ),
        }
    dist_payload, dist_sha = _checked_payload(
        args.dist_sums, args.expected_dist_sums_sha256, label="dist_sums"
    )
    image_payload, image_sha = _checked_payload(
        args.image_tar, args.expected_image_tar_sha256, label="image_tar"
    )
    transfer_payload, transfer_sha = _checked_payload(
        args.transfer_tgz,
        args.expected_transfer_tgz_sha256,
        label="transfer_tgz",
    )
    del image_payload, transfer_payload
    receipt_specs = {
        "browser_e2e": (
            args.browser_e2e_receipt,
            args.expected_browser_e2e_receipt_sha256,
            {
                ("reddit_voc_insights_browser_e2e_receipt_v1", "passed"),
                (
                    "reddit_voc_same_dist_browser_e2e_receipt_v2",
                    "passed_local_same_dist_browser_acceptance",
                ),
            },
        ),
        "export": (
            args.export_receipt,
            args.expected_export_receipt_sha256,
            {
                ("reddit_voc_insights_export_validation_receipt_v1", "passed"),
                (
                    "reddit_voc_insights_export_validation_receipt_v1",
                    "passed_public_readonly_export_acceptance",
                ),
                (
                    "reddit_voc_insights_export_validation_receipt_v1",
                    "passed_local_readonly_export_acceptance",
                ),
            },
        ),
        "container_smoke": (
            args.container_smoke_receipt,
            args.expected_container_smoke_receipt_sha256,
            {
                ("reddit_voc_insights_container_smoke_receipt_v1", "passed"),
                (
                    "reddit_voc_local_insights_container_smoke_receipt_v1",
                    "passed_local_isolated_container_smoke",
                ),
                (
                    "reddit_voc_local_insights_container_smoke_receipt_v2",
                    "passed_local_isolated_container_smoke",
                ),
            },
        ),
        "security": (
            args.security_receipt,
            args.expected_security_receipt_sha256,
            {("reddit_voc_insights_security_validation_receipt_v1", "passed")},
        ),
    }
    receipt_shas: dict[str, str] = {}
    for label, (path, expected_sha, expected_contracts) in receipt_specs.items():
        payload, digest = _checked_payload(path, expected_sha, label=f"{label}_receipt")
        try:
            value = json.loads(payload)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise CandidateRegistrationError(f"{label}_receipt_invalid_json") from exc
        if (
            not isinstance(value, dict)
            or (value.get("schema_version"), value.get("status"))
            not in expected_contracts
        ):
            raise CandidateRegistrationError(f"{label}_receipt_contract_invalid")
        _safe_boundaries(value.get("boundaries"), label=f"{label}_receipt")
        receipt_shas[label] = digest
    release_evidence_sha = _sha256_bytes(
        canonical_bytes(
            {
                "dist_sha256": dist_sha,
                "release_manifest_sha256": release_manifest_sha,
                "release_sha256": release_sha,
            }
        )
    )
    ui_validation_payload: dict[str, object] = {
        "lineage": lineage,
        "receipts": receipt_shas,
    }
    if v3_lineage is not None:
        ui_validation_payload["v3_lineage"] = v3_lineage
    ui_validation_sha = _sha256_bytes(canonical_bytes(ui_validation_payload))
    value = {
        "schema_version": (
            "reddit_voc_candidate_ui_validation_receipt_v2"
            if native_v3
            else "reddit_voc_candidate_ui_validation_receipt_v1"
        ),
        "status": "passed_local_candidate_validation",
        "generated_at_utc": generated_at,
        "expires_at_utc": expires_at,
        "lineage": lineage,
        "release": {
            "release_sha256": release_sha,
            "dist_manifest_sha256": dist_sha,
            "release_manifest_sha256": release_manifest_sha,
            "release_manifest_evidence_sha256": release_evidence_sha,
        },
        "deliverables": {
            "image_tar_sha256": image_sha,
            "transfer_tgz_sha256": transfer_sha,
        },
        "evidence": {
            "browser_e2e_evidence_sha256": receipt_shas["browser_e2e"],
            "container_evidence_sha256": receipt_shas["container_smoke"],
            "export_evidence_sha256": receipt_shas["export"],
            "security_evidence_sha256": receipt_shas["security"],
            "ui_validation_evidence_sha256": ui_validation_sha,
        },
        "boundaries": dict(SAFE_BOUNDARIES),
    }
    if v3_lineage is not None:
        value["v3_lineage"] = v3_lineage
    disposition = _write_immutable(
        Path(args.output), value, label="final_validation_receipt"
    )
    return {
        "final_receipt_sha256": _sha256_bytes(_canonical_file_bytes(value)),
        "production_unchanged": True,
        "status": disposition,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--native-v3", action="store_true")
    parser.add_argument("--plan-a-root", type=Path)
    parser.add_argument("--expected-plan-a-input-sha256")
    parser.add_argument("--expected-plan-a-manifest-sha256")
    parser.add_argument("--expected-plan-a-receipt-sha256")
    parser.add_argument("--plan-b-source-manifest", type=Path)
    parser.add_argument("--expected-plan-b-source-manifest-sha256")
    parser.add_argument("--plan-b-source-receipt", type=Path)
    parser.add_argument("--expected-plan-b-source-receipt-sha256")
    parser.add_argument("--expected-plan-b-input-sha256")
    parser.add_argument("--build-contract", type=Path, required=True)
    parser.add_argument("--expected-build-contract-sha256", required=True)
    parser.add_argument("--release-manifest", type=Path)
    parser.add_argument("--expected-release-manifest-sha256")
    parser.add_argument("--final-receipt", type=Path, required=True)
    parser.add_argument("--expected-final-receipt-sha256", required=True)
    parser.add_argument("--v3-release-id")
    parser.add_argument("--v3-source-snapshot-id")
    parser.add_argument("--v3-artifact", action="append")
    parser.add_argument("--expected-v3-artifact-sha256", action="append")
    parser.add_argument("--v3-native-artifact", action="append")
    parser.add_argument("--expected-v3-native-artifact-sha256", action="append")
    return parser


def _key_value_rows(
    values: list[str] | None,
    *,
    path_values: bool,
    label: str,
    allowed_keys: set[str] = V3_LINEAGE_ARTIFACT_KEYS,
) -> dict[str, object] | None:
    if values is None:
        return None
    result: dict[str, object] = {}
    for value in values:
        if not isinstance(value, str) or "=" not in value:
            raise CandidateRegistrationError(f"{label}_invalid")
        key, item = value.split("=", 1)
        if key not in allowed_keys or key in result or not item:
            raise CandidateRegistrationError(f"{label}_invalid")
        result[key] = Path(item) if path_values else item
    return result


def main() -> int:
    args = _parser().parse_args()
    try:
        args.v3_artifact_paths = _key_value_rows(
            args.v3_artifact,
            path_values=True,
            label="v3_artifact",
            allowed_keys=V3_LINEAGE_ARTIFACT_KEYS,
        )
        args.expected_v3_artifact_sha256s = _key_value_rows(
            args.expected_v3_artifact_sha256,
            path_values=False,
            label="expected_v3_artifact_sha256",
            allowed_keys=V3_LINEAGE_ARTIFACT_KEYS,
        )
        args.v3_native_artifact_paths = _key_value_rows(
            args.v3_native_artifact,
            path_values=True,
            label="v3_native_artifact",
            allowed_keys=V3_NATIVE_LINEAGE_ARTIFACT_KEYS,
        )
        args.expected_v3_native_artifact_sha256s = _key_value_rows(
            args.expected_v3_native_artifact_sha256,
            path_values=False,
            label="expected_v3_native_artifact_sha256",
            allowed_keys=V3_NATIVE_LINEAGE_ARTIFACT_KEYS,
        )
        result = register_candidate(args)
    except CandidateBuildBusy:
        print(
            json.dumps(
                {
                    "schema_version": "reddit_voc_candidate_registration_result_v1",
                    "status": "blocked",
                    "reason_code": "candidate_build_already_running",
                    "registry_write": False,
                    "production_unchanged": True,
                },
                sort_keys=True,
            )
        )
        return 3
    except CandidateRegistrationError as exc:
        print(
            json.dumps(
                {
                    "schema_version": "reddit_voc_candidate_registration_result_v1",
                    "status": "failed",
                    "reason_code": _reason_code(exc),
                    "production_unchanged": True,
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
