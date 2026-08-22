#!/usr/bin/env python3
"""Bind a validated V3 canonical snapshot to its validated SourceBatch V2."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from reddit_voc.report_contracts import canonical_json_bytes  # noqa: E402
from reddit_voc.v3_baseline_source_batch import (  # noqa: E402
    V3BaselineSourceBatchError,
    build_v3_baseline_bridge_receipt,
)


def _write_immutable(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise V3BaselineSourceBatchError("bridge receipt immutable collision")
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical-root", type=Path, required=True)
    parser.add_argument("--canonical-validation-receipt", type=Path, required=True)
    parser.add_argument("--source-batch-manifest", type=Path, required=True)
    parser.add_argument("--source-batch-validation-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        value = build_v3_baseline_bridge_receipt(
            canonical_root=args.canonical_root,
            canonical_validation_receipt_path=args.canonical_validation_receipt,
            source_batch_manifest_path=args.source_batch_manifest,
            source_batch_validation_receipt_path=args.source_batch_validation_receipt,
        )
        payload = canonical_json_bytes(value) + b"\n"
        write_status = _write_immutable(args.output, payload)
    except (OSError, ValueError, V3BaselineSourceBatchError) as exc:
        sys.stderr.write(json.dumps({"error": str(exc), "status": "blocked"}, sort_keys=True) + "\n")
        return 1
    sys.stdout.write(
        json.dumps(
            {
                "receipt_sha256": hashlib.sha256(payload).hexdigest(),
                "status": "passed",
                "write_status": write_status,
            },
            sort_keys=True,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
