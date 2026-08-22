#!/usr/bin/env python3
"""Run one fail-closed Reddit VOC data-release shadow or authorized switch."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import Any

try:
    from scripts import reddit_data_release_control as control
except ModuleNotFoundError:
    import reddit_data_release_control as control


SCHEMA_VERSION = "reddit_voc_data_pipeline_attempt_v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write(path: Path, value: dict[str, Any]) -> str:
    payload = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    if path.exists():
        if path.is_symlink() or path.read_bytes() != payload:
            raise ValueError("attempt_receipt_immutable_collision")
        return "no_change"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return "created"


def run(
    *,
    root: Path,
    candidate_release_id: str,
    expected_current_release_id: str | None,
    mode: str,
    authorize_switch: bool,
    attempt_receipt: Path,
) -> tuple[int, dict[str, Any], str]:
    started = _now()
    candidate: dict[str, Any] | None = None
    descriptor: int | None = None
    try:
        if mode not in {"shadow", "switch"}:
            raise ValueError("mode_invalid")
        if mode == "switch" and not authorize_switch:
            raise ValueError("scheduled_switch_not_authorized")
        if mode == "shadow" and authorize_switch:
            raise ValueError("shadow_must_not_carry_switch_authorization")
        root = root.resolve(strict=True)
        locks = root / "locks"
        locks.mkdir(mode=0o700, exist_ok=True)
        lock_path = locks / "data-pipeline.lock"
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("pipeline_lock_busy")
        candidate = control.validate_release(root, candidate_release_id)
        if mode == "shadow":
            result = control.shadow_validate_release(
                root=root,
                release_id=candidate_release_id,
            )
        else:
            result = control.switch_release(
                root=root,
                release_id=candidate_release_id,
                expected_current_release_id=expected_current_release_id,
                authorize_switch=True,
            )
        payload = {
            "schema_version": SCHEMA_VERSION,
            "status": result["status"],
            "mode": mode,
            "started_at_utc": started,
            "finished_at_utc": _now(),
            "period_end_utc": candidate["data_as_of_utc"],
            "candidate_release_id": candidate_release_id,
            "candidate_pointer_sha256": candidate["pointer_sha256"],
            "expected_current_release_id": expected_current_release_id,
            "control_receipt_path": result.get("receipt_path"),
            "control_receipt_sha256": result.get("receipt_sha256"),
            "boundaries": {
                "production_switch": mode == "switch",
                "remote_write": False,
                "schedule_change": False,
                "live_send": False,
                "collector_modified": False,
                "shared_nginx_modified": False,
                "other_docker_modified": False,
            },
        }
        write_status = _write(attempt_receipt, payload)
        return 0, payload, write_status
    except (OSError, ValueError, control.DataReleaseControlError) as exc:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "status": "failed",
            "mode": mode,
            "started_at_utc": started,
            "finished_at_utc": _now(),
            "period_end_utc": (
                candidate.get("data_as_of_utc") if candidate is not None else None
            ),
            "candidate_release_id": candidate_release_id,
            "expected_current_release_id": expected_current_release_id,
            "error_code": str(exc),
            "boundaries": {
                "production_switch": False,
                "remote_write": False,
                "schedule_change": False,
                "live_send": False,
                "collector_modified": False,
                "shared_nginx_modified": False,
                "other_docker_modified": False,
            },
        }
        write_status = _write(attempt_receipt, payload)
        return 1, payload, write_status
    finally:
        if descriptor is not None:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--candidate-release-id", required=True)
    parser.add_argument("--expected-current-release-id")
    parser.add_argument("--mode", choices=("shadow", "switch"), default="shadow")
    parser.add_argument("--authorize-switch", action="store_true")
    parser.add_argument("--attempt-receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        exit_code, payload, write_status = run(
            root=args.root,
            candidate_release_id=args.candidate_release_id,
            expected_current_release_id=args.expected_current_release_id,
            mode=args.mode,
            authorize_switch=args.authorize_switch,
            attempt_receipt=args.attempt_receipt,
        )
    except (OSError, ValueError, control.DataReleaseControlError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "status": payload["status"],
                "mode": payload["mode"],
                "receipt": str(args.attempt_receipt),
                "receipt_write_status": write_status,
                "receipt_sha256": sha256(args.attempt_receipt.read_bytes()).hexdigest(),
            },
            sort_keys=True,
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
