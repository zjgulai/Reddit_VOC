#!/usr/bin/env python3
"""Validate the current Echo-Agent workbench release lock.

The old `config/production-version-lock.json` pins the retired Docker
daily-report/insights stack on `101.34.52.232`. The workbench now runs on
`43.163.92.244` via `radar.luteos.com`, and the lock must describe that
release, not the retired one.

`--check` is local and hermetic (used by CI). `--public-url` adds a read-only
cache-busted comparison against the served pointer.

Exit codes: 0 valid / 1 invalid or mismatch / 2 cannot evaluate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = ROOT / "config" / "production-workbench-lock.json"
SCHEMA = "echo_agent_workbench_release_lock_v1"
SHA = re.compile(r"^[0-9a-f]{64}$")
DATASETS = {
    "base",
    "insights",
    "reports",
    "personas",
    "brand_health",
    "quarter_insights",
    "casebook",
}


def _is_utc(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def validate_lock(lock: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if lock.get("schema_version") != SCHEMA:
        errors.append("schema_version")
    for key in ("production_host", "public_url", "data_path", "release_id", "run_id"):
        if not isinstance(lock.get(key), str) or not str(lock.get(key)).strip():
            errors.append(key)
    if not str(lock.get("public_url", "")).startswith("https://"):
        errors.append("public_url_not_https")
    if not str(lock.get("data_path", "")).startswith("/"):
        errors.append("data_path_not_absolute")
    for key in (
        "observed_at",
        "generated_at_utc",
        "data_as_of_utc",
        "window_start_utc",
        "window_end_utc",
    ):
        if not _is_utc(lock.get(key)):
            errors.append(key)
    if not SHA.match(str(lock.get("pointer_sha256", ""))):
        errors.append("pointer_sha256")
    datasets = lock.get("datasets")
    if not isinstance(datasets, Mapping):
        errors.append("datasets")
        return errors
    if set(datasets) != DATASETS:
        errors.append("datasets_keys")
    for key, binding in datasets.items():
        if not isinstance(binding, Mapping):
            errors.append(f"dataset_binding:{key}")
            continue
        if not isinstance(binding.get("dataset_version"), str) or not binding["dataset_version"]:
            errors.append(f"dataset_version:{key}")
        if not SHA.match(str(binding.get("public_manifest_sha256", ""))):
            errors.append(f"dataset_sha:{key}")
    return sorted(set(errors))


def _fetch_pointer(url: str, timeout: int = 20) -> tuple[str, dict[str, Any]]:
    separator = "&" if "?" in url else "?"
    request = urllib.request.Request(
        f"{url}{separator}cb={int(time.time() * 1000)}",
        headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
    return hashlib.sha256(body).hexdigest(), json.loads(body.decode("utf-8"))


def compare_public(lock: Mapping[str, Any], pointer: Mapping[str, Any], sha: str) -> list[str]:
    errors: list[str] = []
    if sha != lock.get("pointer_sha256"):
        errors.append("pointer_sha256_mismatch")
    if pointer.get("release_id") != lock.get("release_id"):
        errors.append("release_id_mismatch")
    if pointer.get("generated_at_utc") != lock.get("generated_at_utc"):
        errors.append("generated_at_utc_mismatch")
    freshness = pointer.get("freshness") or {}
    if freshness.get("collector_run_id") != lock.get("run_id"):
        errors.append("run_id_mismatch")
    if freshness.get("data_as_of_utc") != lock.get("data_as_of_utc"):
        errors.append("data_as_of_utc_mismatch")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the workbench release lock")
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--public-url", default=None, help="compare against the served pointer")
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()

    try:
        lock = json.loads(args.lock.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "invalid", "error": f"lock_unreadable:{exc}"}, ensure_ascii=False))
        return 1

    errors = validate_lock(lock)
    result: dict[str, Any] = {
        "status": "valid" if not errors else "invalid",
        "lock": str(args.lock),
        "production_host": lock.get("production_host"),
        "release_id": lock.get("release_id"),
        "run_id": lock.get("run_id"),
        "errors": errors,
    }

    if not errors and args.public_url:
        try:
            sha, pointer = _fetch_pointer(args.public_url)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            result.update(status="unevaluable", error=f"public_fetch_failed:{exc}")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 2
        public_errors = compare_public(lock, pointer, sha)
        if public_errors:
            result.update(status="mismatch", public_errors=public_errors, public_sha256=sha)
            errors.extend(public_errors)
        else:
            result.update(public_status="match", public_sha256=sha)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())