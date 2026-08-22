#!/usr/bin/env python3
"""Validate one immutable Reddit VOC SourceBatch and emit a local receipt."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from reddit_voc.report_contracts import canonical_json_bytes  # noqa: E402
from reddit_voc.source_batch import SourceBatchError, load_source_batch  # noqa: E402


RECEIPT_SCHEMA = "reddit_voc_source_batch_validation_receipt_v1"
VALIDATION_BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}


def _observed_at_utc(value: str) -> str:
    if not value.endswith("Z"):
        raise SourceBatchError("observed_at_utc must use UTC Z suffix")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise SourceBatchError("observed_at_utc must be ISO-8601") from exc
    return parsed.isoformat().replace("+00:00", "Z")


def _write_immutable(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise SourceBatchError("validation receipt output is unsafe")
        if path.read_bytes() != payload:
            raise SourceBatchError("validation receipt immutable collision")
        return "no_change"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return "created"


def validate_source_batch(
    *,
    manifest_path: Path,
    batch_root: Path,
    observed_at_utc: str,
    require_consumable: bool,
) -> dict[str, object]:
    batch = load_source_batch(
        manifest_path,
        batch_root,
        require_consumable=require_consumable,
    )
    return {
        "batch_id": batch.batch_id,
        "batch_status": batch.status,
        "consumable": batch.is_consumable,
        "counts": asdict(batch.counts),
        "manifest_sha256": batch.manifest_sha256,
        "observed_at_utc": _observed_at_utc(observed_at_utc),
        "producer_type": batch.producer_type,
        "profile_bindings": {
            "coverage_profile_sha256": batch.profiles.coverage_profile_sha256,
            "coverage_profile_version": batch.profiles.coverage_profile_version,
            "query_profile_sha256": batch.profiles.query_profile_sha256,
            "query_profile_version": batch.profiles.query_profile_version,
        },
        "schema_version": RECEIPT_SCHEMA,
        "source_boundaries": asdict(batch.boundaries),
        "status": "passed",
        "validation_boundaries": dict(VALIDATION_BOUNDARIES),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--batch-root", type=Path)
    parser.add_argument("--observed-at-utc", required=True)
    parser.add_argument("--require-consumable", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt = validate_source_batch(
            manifest_path=args.manifest,
            batch_root=args.batch_root or args.manifest.parent,
            observed_at_utc=args.observed_at_utc,
            require_consumable=args.require_consumable,
        )
        payload = canonical_json_bytes(receipt) + b"\n"
        write_status = _write_immutable(args.output, payload)
    except (OSError, SourceBatchError) as exc:
        error = {
            "error": str(exc),
            "schema_version": RECEIPT_SCHEMA,
            "status": "failed",
            "validation_boundaries": dict(VALIDATION_BOUNDARIES),
        }
        sys.stderr.write(json.dumps(error, ensure_ascii=False, sort_keys=True) + "\n")
        return 1
    result = {
        "receipt_sha256": hashlib.sha256(payload).hexdigest(),
        "status": "passed",
        "write_status": write_status,
    }
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
