#!/usr/bin/env python3
"""Refresh config/production-workbench-lock.json from a verified evidence receipt.

The lock pins the served workbench generation that a human verified in a
browser. It must not auto-advance (an unverified generation must never become
the trusted baseline), so this tool is the PR-side half of the drift story:

  1. run the daily verification (scripts/verify_daily_release.py or equivalent)
     producing reports/evidence/verify-YYYYMMDD.json,
  2. run this script with that receipt,
  3. review + commit the lock change like any other PR.

The independent half is scheduled drift detection
(.github/workflows/workbench-drift.yml), which compares the committed lock
against the live pointer and fails loudly when they diverge.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

DEFAULT_RECEIPT = Path("reports/evidence/verify-20261105.json")
DEFAULT_LOCK = Path("config/production-workbench-lock.json")

LOCK_SCHEMA = "echo_agent_workbench_release_lock_v1"


def build_lock(receipt: dict, source_note: str) -> dict:
    data = receipt["data"]
    pointer = data["pointer_document"]
    freshness = pointer.get("freshness") or {}
    datasets = {}
    for key, value in (pointer.get("datasets") or {}).items():
        datasets[key] = {
            "dataset_version": value.get("dataset_version"),
            "public_manifest_sha256": value.get("public_manifest_sha256"),
        }
    return {
        "schema_version": LOCK_SCHEMA,
        "production_host": "43.163.92.244",
        # public_url keeps the site-root semantics the schema and drift check
        # expect; the pointer path is derived from it at verification time.
        "public_url": data.get("public_url") or "https://radar.luteos.com",
        "data_path": data.get("pointer", {}).get("path", "/opt/voc-report/html/data/reddit-voc"),
        "observed_at": receipt.get("generated_at_utc"),
        "release_id": pointer.get("release_id"),
        "run_id": freshness.get("collector_run_id") or data.get("receipt", {}).get("run_id"),
        "pointer_sha256": data.get("pointer_sha256"),
        "generated_at_utc": pointer.get("generated_at_utc"),
        "data_as_of_utc": freshness.get("data_as_of_utc"),
        "window_start_utc": freshness.get("window_start_utc"),
        "window_end_utc": freshness.get("window_end_utc"),
        "freshness_status": freshness.get("status") or freshness.get("freshness"),
        "datasets": datasets,
        "source": source_note,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    summary = receipt.get("summary") or {}
    passed = (
        receipt.get("exit_code") == 0
        and summary.get("FAIL", 0) == 0
        and summary.get("FIND", 0) == 0
    )
    if not passed:
        # A failed verification must not become the trusted baseline.
        print(f"refusing: receipt is not a verified pass: {json.dumps(summary, ensure_ascii=False)} "
              f"exit_code={receipt.get('exit_code')}", file=sys.stderr)
        return 2

    lock = build_lock(receipt, source_note=str(args.receipt))
    rendered = json.dumps(lock, ensure_ascii=False, indent=2) + "\n"
    if args.dry_run:
        print(rendered)
        return 0
    args.lock.write_text(rendered, encoding="utf-8")
    print(f"lock updated from {args.receipt}: release={lock['release_id']} "
          f"run_id={lock['run_id']} pointer_sha256={str(lock['pointer_sha256'])[:12]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
