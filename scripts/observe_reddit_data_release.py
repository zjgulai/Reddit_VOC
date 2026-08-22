#!/usr/bin/env python3
"""Emit a read-only freshness/SLO observation for one Reddit VOC data root."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

try:
    from scripts import reddit_data_release_control as control
except ModuleNotFoundError:
    import reddit_data_release_control as control


SCHEMA_VERSION = "reddit_voc_data_release_observation_v1"


def _utc(value: object, *, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label}_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label}_invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label}_not_utc")
    return parsed.astimezone(timezone.utc)


def _utc_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def expected_close(observed: datetime) -> datetime:
    """Return the latest closed 07:00 Asia/Shanghai boundary."""

    observed = observed.astimezone(timezone.utc)
    close = observed.replace(hour=23, minute=0, second=0, microsecond=0)
    if close > observed:
        close -= timedelta(days=1)
    return close


def classify(
    *,
    observed: datetime,
    data_as_of: datetime,
    freshness_status: str,
    slo_minutes: int,
    latest_attempt: Mapping[str, Any] | None = None,
    latest_control: Mapping[str, Any] | None = None,
    current_release_id: str,
) -> dict[str, Any]:
    close = expected_close(observed)
    if data_as_of > close:
        raise ValueError("data_as_of_after_latest_closed_period")
    deadline = close + timedelta(minutes=slo_minutes)
    current_period = data_as_of == close
    attempt_status = latest_attempt.get("status") if latest_attempt else None
    attempt_period = (
        _utc(latest_attempt.get("period_end_utc"), label="attempt_period_end_utc")
        if latest_attempt and latest_attempt.get("period_end_utc") is not None
        else None
    )
    rollback = bool(
        latest_control
        and latest_control.get("schema_version")
        == "reddit_voc_data_release_rollback_receipt_v1"
        and latest_control.get("status") == "rolled_back"
        and latest_control.get("to_release_id") == current_release_id
    )
    if rollback:
        state = "rollback"
    elif current_period and freshness_status == "partial":
        state = "partial"
    elif current_period:
        state = "fresh"
    elif (
        attempt_status == "failed"
        and attempt_period == close
    ):
        state = "failed"
    elif observed <= deadline:
        state = "awaiting"
    elif latest_attempt is None or attempt_period != close:
        state = "stalled"
    else:
        state = "stale"
    lag_seconds = max(0, int((observed - data_as_of).total_seconds()))
    return {
        "state": state,
        "expected_period_end_utc": _utc_z(close),
        "deadline_utc": _utc_z(deadline),
        "data_as_of_utc": _utc_z(data_as_of),
        "lag_seconds": lag_seconds,
        "slo_seconds": slo_minutes * 60,
        "slo_met": current_period and observed <= deadline,
        "metrics": {
            name: int(state == name)
            for name in (
                "fresh",
                "partial",
                "awaiting",
                "stalled",
                "stale",
                "failed",
                "rollback",
            )
        },
    }


def _load_optional(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    if path.is_symlink() or not path.is_file():
        raise ValueError("observation_input_unsafe")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("observation_input_invalid")
    return value


def _latest_control_receipt(root: Path) -> dict[str, Any] | None:
    receipts = root / "receipts"
    if not receipts.is_dir() or receipts.is_symlink():
        return None
    candidates: list[tuple[datetime, dict[str, Any]]] = []
    for path in receipts.glob("*.json"):
        try:
            value = _load_optional(path)
            if value is None:
                continue
            time_value = value.get("rolled_back_at_utc") or value.get("switched_at_utc")
            if time_value is None:
                continue
            candidates.append((_utc(time_value, label="control_time"), value))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def _switch_p95_seconds(root: Path) -> int | None:
    receipts = root / "receipts"
    if not receipts.is_dir() or receipts.is_symlink():
        return None
    values: list[int] = []
    for path in receipts.glob("*.json"):
        try:
            value = _load_optional(path)
            if (
                value is None
                or value.get("schema_version")
                != "reddit_voc_data_release_switch_receipt_v1"
                or value.get("status") != "switched"
            ):
                continue
            switched = _utc(value.get("switched_at_utc"), label="switched_at_utc")
            data_as_of = _utc(value.get("data_as_of_utc"), label="data_as_of_utc")
            values.append(max(0, int((switched - data_as_of).total_seconds())))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    if not values:
        return None
    values.sort()
    return values[max(0, math.ceil(len(values) * 0.95) - 1)]


def observe(
    *,
    root: Path,
    observed: datetime,
    slo_minutes: int,
    attempt_receipt: Path | None,
) -> dict[str, Any]:
    root = root.resolve(strict=True)
    current_release_id = control._read_link_release(root, "current")
    if current_release_id is None:
        raise ValueError("current_release_missing")
    validated = control.validate_release(root, current_release_id)
    latest_attempt = _load_optional(attempt_receipt)
    latest_control = _latest_control_receipt(root)
    result = classify(
        observed=observed,
        data_as_of=_utc(validated["data_as_of_utc"], label="data_as_of_utc"),
        freshness_status=str(validated["freshness_status"]),
        slo_minutes=slo_minutes,
        latest_attempt=latest_attempt,
        latest_control=latest_control,
        current_release_id=current_release_id,
    )
    p95 = _switch_p95_seconds(root)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "observed",
        "observed_at_utc": _utc_z(observed),
        "current_release_id": current_release_id,
        "current_pointer_sha256": validated["pointer_sha256"],
        **result,
        "historical_switch_p95_seconds": p95,
        "historical_switch_p95_slo_met": (
            None if p95 is None else p95 <= slo_minutes * 60
        ),
        "boundaries": {
            "production_switch": False,
            "remote_write": False,
            "schedule_change": False,
            "live_send": False,
            "collector_modified": False,
        },
    }


def _write(path: Path, value: Mapping[str, Any]) -> str:
    payload = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    if path.exists():
        if path.is_symlink() or path.read_bytes() != payload:
            raise ValueError("observation_output_collision")
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--observed-at-utc", required=True)
    parser.add_argument("--slo-minutes", type=int, default=90)
    parser.add_argument("--attempt-receipt", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.slo_minutes <= 0:
        parser.error("--slo-minutes must be positive")
    try:
        result = observe(
            root=args.root,
            observed=_utc(args.observed_at_utc, label="observed_at_utc"),
            slo_minutes=args.slo_minutes,
            attempt_receipt=args.attempt_receipt,
        )
        status = _write(args.output, result)
    except (OSError, ValueError, control.DataReleaseControlError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 1
    print(
        json.dumps(
            {
                "status": status,
                "state": result["state"],
                "slo_met": result["slo_met"],
                "output": str(args.output),
                "sha256": sha256(args.output.read_bytes()).hexdigest(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
