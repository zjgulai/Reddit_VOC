#!/usr/bin/env python3
"""Materialize exactly one Plan B frontend source manifest into a private stage."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "reddit_voc_frontend_source_stage_receipt_v1"
MANIFEST_SCHEMAS = {
    "reddit_voc_frontend_source_manifest_v1",
    "reddit_voc_frontend_source_manifest_v2",
}
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
BOUNDARIES = {
    "production_unchanged": True,
    "deploy": False,
    "remote_write": False,
    "provider_call": False,
    "database_write": False,
    "live_send": False,
}


class SourceStageError(ValueError):
    """The frozen source or immutable materialization contract failed."""


def _canonical(value: object, *, newline: bool = False) -> bytes:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return payload + (b"\n" if newline else b"")


def _digest(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _valid_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise SourceStageError(f"{label}_sha256_invalid")
    return value


def _safe_relative(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise SourceStageError("source_member_path_invalid")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise SourceStageError("source_member_path_invalid")
    if any(part == ".env" or part.startswith(".env.") for part in path.parts):
        raise SourceStageError("source_member_forbidden")
    if path.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}:
        raise SourceStageError("source_member_forbidden")
    return path.as_posix()


def _safe_directory(path: Path, label: str) -> None:
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise SourceStageError(f"{label}_missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise SourceStageError(f"{label}_unsafe")


def _read_regular(path: Path, label: str) -> bytes:
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise SourceStageError(f"{label}_missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise SourceStageError(f"{label}_unsafe")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise SourceStageError(f"{label}_unsafe") from exc
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
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
        before.st_mtime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_size,
        after.st_mtime_ns,
    )
    payload = b"".join(chunks)
    if identity_before != identity_after or len(payload) != before.st_size:
        raise SourceStageError(f"{label}_drift")
    return payload


def _load_manifest(
    manifest_path: Path,
    expected_manifest_sha256: str,
    expected_candidate_input_sha256: str,
) -> tuple[dict[str, Any], bytes, list[dict[str, Any]]]:
    manifest_bytes = _read_regular(manifest_path, "frontend_source_manifest")
    if _digest(manifest_bytes) != _valid_sha(
        expected_manifest_sha256, "frontend_source_manifest"
    ):
        raise SourceStageError("frontend_source_manifest_sha256_mismatch")
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SourceStageError("frontend_source_manifest_invalid") from exc
    candidate_input = _valid_sha(
        expected_candidate_input_sha256, "frontend_candidate_input"
    )
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") not in MANIFEST_SCHEMAS
        or manifest.get("status") != "frontend_source_frozen_local"
        or manifest.get("frontend_candidate_input_sha256") != candidate_input
    ):
        raise SourceStageError("frontend_source_manifest_contract_invalid")
    source = manifest.get("source")
    inventory = source.get("inventory") if isinstance(source, dict) else None
    rows = inventory.get("files") if isinstance(inventory, dict) else None
    if not isinstance(rows, list) or not rows:
        raise SourceStageError("source_inventory_invalid")
    normalized: list[dict[str, Any]] = []
    paths: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "bytes", "sha256"}:
            raise SourceStageError("source_inventory_row_invalid")
        relative = _safe_relative(row.get("path"))
        size = row.get("bytes")
        digest = _valid_sha(row.get("sha256"), "source_member")
        if (
            relative in paths
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
        ):
            raise SourceStageError("source_inventory_row_invalid")
        paths.add(relative)
        normalized.append({"path": relative, "bytes": size, "sha256": digest})
    if normalized != sorted(normalized, key=lambda row: row["path"]):
        raise SourceStageError("source_inventory_not_sorted")
    if (
        inventory.get("file_count") != len(normalized)
        or inventory.get("total_bytes") != sum(row["bytes"] for row in normalized)
        or inventory.get("inventory_sha256") != _digest(_canonical(normalized))
    ):
        raise SourceStageError("source_inventory_contract_invalid")
    boundaries = manifest.get("boundaries")
    if not isinstance(boundaries, dict):
        raise SourceStageError("frontend_source_boundaries_invalid")
    for key in ("deploy", "remote_write", "provider_call", "database_write", "live_send"):
        if boundaries.get(key) is not False:
            raise SourceStageError("frontend_source_boundaries_invalid")
    if boundaries.get("production_unchanged") is not True:
        raise SourceStageError("frontend_source_boundaries_invalid")
    return manifest, manifest_bytes, normalized


def _observe_source(
    source_root: Path, rows: Sequence[Mapping[str, Any]]
) -> dict[str, bytes]:
    _safe_directory(source_root, "source_root")
    payloads: dict[str, bytes] = {}
    for row in rows:
        relative = str(row["path"])
        path = source_root.joinpath(*PurePosixPath(relative).parts)
        payload = _read_regular(path, "source_member")
        if len(payload) != row["bytes"] or _digest(payload) != row["sha256"]:
            raise SourceStageError("source_member_contract_mismatch")
        payloads[relative] = payload
    return payloads


def _inventory_stage(root: Path) -> list[dict[str, Any]]:
    _safe_directory(root, "destination")
    rows: list[dict[str, Any]] = []
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in directory_names:
            child = base / name
            metadata = os.lstat(child)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise SourceStageError("destination_immutable_collision")
        for name in file_names:
            child = base / name
            payload = _read_regular(child, "destination_member")
            relative = child.relative_to(root).as_posix()
            rows.append(
                {"path": relative, "bytes": len(payload), "sha256": _digest(payload)}
            )
    return sorted(rows, key=lambda row: row["path"])


def _write_private_file(path: Path, payload: bytes) -> str:
    if path.exists() or path.is_symlink():
        existing = _read_regular(path, "receipt")
        if existing != payload:
            raise SourceStageError("receipt_immutable_collision")
        if stat.S_IMODE(os.lstat(path).st_mode) != 0o600:
            raise SourceStageError("receipt_mode_invalid")
        return "no_change"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    descriptor, temporary_raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_raw)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists() or path.is_symlink():
            raise SourceStageError("receipt_immutable_collision")
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if temporary.exists():
            temporary.unlink()
    return "created"


def materialize_source_stage(
    *,
    source_root: Path,
    manifest_path: Path,
    expected_manifest_sha256: str,
    expected_candidate_input_sha256: str,
    destination: Path,
    receipt_path: Path,
) -> dict[str, Any]:
    manifest, manifest_bytes, rows = _load_manifest(
        manifest_path,
        expected_manifest_sha256,
        expected_candidate_input_sha256,
    )
    first = _observe_source(source_root, rows)
    second = _observe_source(source_root, rows)
    if first != second:
        raise SourceStageError("source_inventory_drift")

    destination_status = "created"
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not destination.is_dir():
            raise SourceStageError("destination_immutable_collision")
        if _inventory_stage(destination) != rows:
            raise SourceStageError("destination_immutable_collision")
        destination_status = "no_change"
    else:
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(destination.parent, 0o700)
        temporary = Path(
            tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent)
        )
        try:
            os.chmod(temporary, 0o700)
            for row in rows:
                relative = str(row["path"])
                target = temporary.joinpath(*PurePosixPath(relative).parts)
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                os.chmod(target.parent, 0o700)
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                descriptor = os.open(target, flags, 0o600)
                try:
                    with os.fdopen(descriptor, "wb", closefd=True) as stream:
                        stream.write(second[relative])
                        stream.flush()
                        os.fsync(stream.fileno())
                except BaseException:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass
                    raise
            if _inventory_stage(temporary) != rows:
                raise SourceStageError("materialized_inventory_mismatch")
            if destination.exists() or destination.is_symlink():
                raise SourceStageError("destination_immutable_collision")
            os.replace(temporary, destination)
            directory_descriptor = os.open(destination.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": "source_stage_materialized_local",
        "evidence_grade": "L2_local_manifest_only_source_stage",
        "frontend_candidate_input_sha256": _valid_sha(
            expected_candidate_input_sha256, "frontend_candidate_input"
        ),
        "frontend_source_manifest_sha256": _digest(manifest_bytes),
        "frontend_source_manifest_schema": manifest["schema_version"],
        "source_inventory": {
            "file_count": len(rows),
            "total_bytes": sum(row["bytes"] for row in rows),
            "inventory_sha256": _digest(_canonical(rows)),
        },
        "checks": {
            "source_double_observation_exact": True,
            "manifest_only_members_materialized": True,
            "destination_inventory_exact": True,
            "symlink_and_special_members_rejected": True,
        },
        "boundaries": BOUNDARIES,
    }
    receipt_status = _write_private_file(receipt_path, _canonical(receipt, newline=True))
    return {
        "status": (
            "no_change"
            if destination_status == "no_change" and receipt_status == "no_change"
            else "created"
        ),
        "destination": str(destination),
        "receipt": str(receipt_path),
        "frontend_candidate_input_sha256": receipt[
            "frontend_candidate_input_sha256"
        ],
        "frontend_source_manifest_sha256": receipt[
            "frontend_source_manifest_sha256"
        ],
    }


def _confined(path: Path, root: Path, label: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise SourceStageError(f"{label}_outside_project_tmp") from exc
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--expected-candidate-input-sha256", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parents[1]
    try:
        destination = _confined(args.destination, project_root / "tmp", "destination")
        receipt = _confined(args.receipt, project_root / "tmp", "receipt")
        result = materialize_source_stage(
            source_root=args.source_root,
            manifest_path=args.manifest,
            expected_manifest_sha256=args.expected_manifest_sha256,
            expected_candidate_input_sha256=args.expected_candidate_input_sha256,
            destination=destination,
            receipt_path=receipt,
        )
    except SourceStageError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
