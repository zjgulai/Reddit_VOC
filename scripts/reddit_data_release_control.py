#!/usr/bin/env python3
"""Validate, shadow-check, switch, or roll back the Reddit VOC data-only release pointer."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Iterator


RELEASE_ID_RE = re.compile(r"^reddit_voc_release_[a-z0-9_-]{3,120}$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
DATASET_KEYS = {
    "base",
    "insights",
    "reports",
    "personas",
    "brand_health",
    "quarter_insights",
    "casebook",
}


class DataReleaseControlError(ValueError):
    """The data release control operation failed closed."""


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink():
        raise DataReleaseControlError(f"{label}_unsafe")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise DataReleaseControlError(f"{label}_missing") from exc
    if not resolved.is_file():
        raise DataReleaseControlError(f"{label}_unsafe")
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DataReleaseControlError(f"{label}_invalid_json") from exc
    if not isinstance(value, dict):
        raise DataReleaseControlError(f"{label}_not_object")
    return value


def _inside(path: Path, root: Path, *, label: str, directory: bool = False) -> Path:
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise DataReleaseControlError(f"{label}_outside_root") from exc
    metadata = resolved.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        raise DataReleaseControlError(f"{label}_unsafe")
    if directory and not resolved.is_dir():
        raise DataReleaseControlError(f"{label}_unsafe")
    if not directory and not resolved.is_file():
        raise DataReleaseControlError(f"{label}_unsafe")
    return resolved


def _safe_release_id(value: object, *, label: str) -> str:
    if not isinstance(value, str) or RELEASE_ID_RE.fullmatch(value) is None:
        raise DataReleaseControlError(f"{label}_invalid")
    return value


def _safe_relative(value: object, *, label: str) -> Path:
    if not isinstance(value, str):
        raise DataReleaseControlError(f"{label}_invalid")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise DataReleaseControlError(f"{label}_invalid")
    return relative


def validate_release(root: Path, release_id: str) -> dict[str, Any]:
    release_id = _safe_release_id(release_id, label="release_id")
    releases_root = _inside(root / "releases", root, label="releases_root", directory=True)
    release_root = _inside(
        releases_root / release_id,
        releases_root,
        label="release_root",
        directory=True,
    )
    public_root = _inside(
        release_root / "public",
        release_root,
        label="public_root",
        directory=True,
    )
    pointer_path = _inside(
        public_root / "data/reddit-voc/current-release.json",
        public_root,
        label="current_release",
    )
    pointer = _load(pointer_path, label="current_release")
    if pointer.get("schema_version") != "reddit_voc_current_release_v2":
        raise DataReleaseControlError("current_release_schema_invalid")
    if pointer.get("release_id") != release_id:
        raise DataReleaseControlError("current_release_id_mismatch")
    datasets = pointer.get("datasets")
    if not isinstance(datasets, dict) or set(datasets) != DATASET_KEYS:
        raise DataReleaseControlError("current_release_datasets_invalid")
    manifest_hashes: dict[str, str] = {}
    for key, binding in datasets.items():
        if not isinstance(binding, dict):
            raise DataReleaseControlError(f"{key}_binding_invalid")
        relative = _safe_relative(binding.get("manifest_path"), label=f"{key}_manifest_path")
        manifest = _inside(public_root / relative, public_root, label=f"{key}_manifest")
        expected = binding.get("public_manifest_sha256")
        if not isinstance(expected, str) or SHA256_RE.fullmatch(expected) is None:
            raise DataReleaseControlError(f"{key}_manifest_sha256_invalid")
        observed = _sha256(manifest)
        if observed != expected:
            raise DataReleaseControlError(f"{key}_manifest_sha256_mismatch")
        manifest_hashes[key] = observed
    cases = pointer.get("cases")
    if not isinstance(cases, dict) or cases.get("stock_content_preserved") is not True:
        raise DataReleaseControlError("cases_contract_invalid")
    for field, sha_field in (
        ("manifest_path", "public_manifest_sha256"),
        ("index_path", "index_sha256"),
    ):
        relative = _safe_relative(cases.get(field), label=f"cases_{field}")
        artifact = _inside(public_root / relative, public_root, label=f"cases_{field}")
        expected = cases.get(sha_field)
        if not isinstance(expected, str) or SHA256_RE.fullmatch(expected) is None:
            raise DataReleaseControlError(f"cases_{sha_field}_invalid")
        if _sha256(artifact) != expected:
            raise DataReleaseControlError(f"cases_{sha_field}_mismatch")
    freshness = pointer.get("freshness")
    if not isinstance(freshness, dict) or freshness.get("status") not in {
        "full",
        "partial",
        "empty_success",
    }:
        raise DataReleaseControlError("freshness_contract_invalid")
    return {
        "release_id": release_id,
        "pointer_sha256": _sha256(pointer_path),
        "manifest_sha256s": manifest_hashes,
        "freshness_status": freshness["status"],
        "data_as_of_utc": freshness.get("data_as_of_utc"),
        "release_root": str(release_root),
    }


def _read_link_release(root: Path, name: str) -> str | None:
    path = root / name
    if not path.exists() and not path.is_symlink():
        return None
    if not path.is_symlink():
        raise DataReleaseControlError(f"{name}_not_symlink")
    target = os.readlink(path)
    relative = Path(target)
    if relative.is_absolute() or ".." in relative.parts:
        raise DataReleaseControlError(f"{name}_unsafe")
    expected_prefix = Path("releases")
    if len(relative.parts) != 2 or relative.parts[0] != expected_prefix.name:
        raise DataReleaseControlError(f"{name}_unsafe")
    release_id = _safe_release_id(relative.parts[1], label=f"{name}_release_id")
    _inside(root / relative, root / "releases", label=f"{name}_target", directory=True)
    return release_id


@contextmanager
def _lock(root: Path) -> Iterator[None]:
    locks = root / "locks"
    locks.mkdir(mode=0o700, exist_ok=True)
    path = locks / "data-release.lock"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _replace_link(root: Path, name: str, release_id: str) -> None:
    target = Path("releases") / release_id
    path = root / name
    temporary = root / f".{name}.tmp-{os.getpid()}"
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()
    os.symlink(target.as_posix(), temporary)
    os.replace(temporary, path)


def _receipt(root: Path, payload: dict[str, Any]) -> Path:
    receipts = root / "receipts"
    receipts.mkdir(mode=0o700, exist_ok=True)
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    identity = sha256(canonical.encode("utf-8")).hexdigest()
    path = receipts / f"{identity}.json"
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if path.exists():
        if path.is_symlink() or path.read_bytes() != encoded:
            raise DataReleaseControlError("receipt_immutable_collision")
        return path
    temporary = receipts / f".{path.name}.tmp-{os.getpid()}"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


def switch_release(
    *,
    root: Path,
    release_id: str,
    expected_current_release_id: str | None,
    authorize_switch: bool,
) -> dict[str, Any]:
    if not authorize_switch:
        raise DataReleaseControlError("switch_not_authorized")
    root = root.resolve(strict=True)
    candidate = validate_release(root, release_id)
    with _lock(root):
        current = _read_link_release(root, "current")
        previous = _read_link_release(root, "previous")
        if expected_current_release_id is not None and current != expected_current_release_id:
            raise DataReleaseControlError("current_release_cas_mismatch")
        if current == release_id:
            return {
                "status": "no_change",
                "current_release_id": current,
                "previous_release_id": previous,
                **candidate,
            }
        if current is not None:
            validate_release(root, current)
            _replace_link(root, "previous", current)
        _replace_link(root, "current", release_id)
        if _read_link_release(root, "current") != release_id:
            raise DataReleaseControlError("current_release_switch_failed")
        payload = {
            "schema_version": "reddit_voc_data_release_switch_receipt_v1",
            "status": "switched",
            "switched_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "from_release_id": current,
            "to_release_id": release_id,
            "candidate_pointer_sha256": candidate["pointer_sha256"],
            "freshness_status": candidate["freshness_status"],
            "data_as_of_utc": candidate["data_as_of_utc"],
            "boundaries": {
                "collector_modified": False,
                "shared_nginx_modified": False,
                "other_docker_modified": False,
            },
        }
        receipt = _receipt(root, payload)
        return {
            **payload,
            "receipt_path": str(receipt),
            "receipt_sha256": _sha256(receipt),
        }


def shadow_validate_release(
    *,
    root: Path,
    release_id: str,
) -> dict[str, Any]:
    """Validate one candidate while proving that current/previous stay unchanged."""

    root = root.resolve(strict=True)
    with _lock(root):
        current_before = _read_link_release(root, "current")
        previous_before = _read_link_release(root, "previous")
        candidate = validate_release(root, release_id)
        current_after = _read_link_release(root, "current")
        previous_after = _read_link_release(root, "previous")
        if current_after != current_before or previous_after != previous_before:
            raise DataReleaseControlError("shadow_pointer_changed")
        payload = {
            "schema_version": "reddit_voc_data_release_shadow_receipt_v1",
            "status": "shadow_validated",
            "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "candidate_release_id": release_id,
            "candidate_pointer_sha256": candidate["pointer_sha256"],
            "freshness_status": candidate["freshness_status"],
            "data_as_of_utc": candidate["data_as_of_utc"],
            "current_release_id": current_after,
            "previous_release_id": previous_after,
            "pointer_unchanged": True,
            "boundaries": {
                "collector_modified": False,
                "shared_nginx_modified": False,
                "other_docker_modified": False,
                "production_switch": False,
                "remote_write": False,
                "schedule_change": False,
                "live_send": False,
            },
        }
        receipt = _receipt(root, payload)
        return {
            **payload,
            "receipt_path": str(receipt),
            "receipt_sha256": _sha256(receipt),
        }


def rollback_release(
    *,
    root: Path,
    expected_current_release_id: str,
    authorize_switch: bool,
) -> dict[str, Any]:
    if not authorize_switch:
        raise DataReleaseControlError("rollback_not_authorized")
    root = root.resolve(strict=True)
    with _lock(root):
        current = _read_link_release(root, "current")
        previous = _read_link_release(root, "previous")
        if current != expected_current_release_id:
            raise DataReleaseControlError("current_release_cas_mismatch")
        if previous is None:
            raise DataReleaseControlError("previous_release_missing")
        validate_release(root, previous)
        _replace_link(root, "current", previous)
        _replace_link(root, "previous", current)
        payload = {
            "schema_version": "reddit_voc_data_release_rollback_receipt_v1",
            "status": "rolled_back",
            "rolled_back_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "from_release_id": current,
            "to_release_id": previous,
            "boundaries": {
                "collector_modified": False,
                "shared_nginx_modified": False,
                "other_docker_modified": False,
            },
        }
        receipt = _receipt(root, payload)
        return {
            **payload,
            "receipt_path": str(receipt),
            "receipt_sha256": _sha256(receipt),
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--root", type=Path, required=True)
    validate.add_argument("--release-id", required=True)
    shadow = subparsers.add_parser("shadow")
    shadow.add_argument("--root", type=Path, required=True)
    shadow.add_argument("--release-id", required=True)
    switch = subparsers.add_parser("switch")
    switch.add_argument("--root", type=Path, required=True)
    switch.add_argument("--release-id", required=True)
    switch.add_argument("--expected-current-release-id")
    switch.add_argument("--authorize-switch", action="store_true")
    rollback = subparsers.add_parser("rollback")
    rollback.add_argument("--root", type=Path, required=True)
    rollback.add_argument("--expected-current-release-id", required=True)
    rollback.add_argument("--authorize-switch", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "validate":
            result = validate_release(args.root.resolve(strict=True), args.release_id)
        elif args.command == "shadow":
            result = shadow_validate_release(
                root=args.root,
                release_id=args.release_id,
            )
        elif args.command == "switch":
            result = switch_release(
                root=args.root,
                release_id=args.release_id,
                expected_current_release_id=args.expected_current_release_id,
                authorize_switch=args.authorize_switch,
            )
        else:
            result = rollback_release(
                root=args.root,
                expected_current_release_id=args.expected_current_release_id,
                authorize_switch=args.authorize_switch,
            )
    except (DataReleaseControlError, OSError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
