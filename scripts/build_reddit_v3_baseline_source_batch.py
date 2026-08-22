#!/usr/bin/env python3
"""Convert one validated V3 canonical snapshot into an immutable SourceBatch V2."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from reddit_voc.v3_baseline_source_batch import (  # noqa: E402
    V3BaselineSourceBatchError,
    build_v3_baseline_source_batch,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical-root", type=Path, required=True)
    parser.add_argument("--canonical-validation-receipt", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--batch-id", required=True)
    args = parser.parse_args()
    try:
        result = build_v3_baseline_source_batch(
            canonical_root=args.canonical_root,
            validation_receipt_path=args.canonical_validation_receipt,
            output_root=args.output_root,
            batch_id=args.batch_id,
        )
    except (OSError, ValueError, V3BaselineSourceBatchError) as exc:
        sys.stderr.write(json.dumps({"error": str(exc), "status": "blocked"}, sort_keys=True) + "\n")
        return 1
    sys.stdout.write(
        json.dumps(
            {
                "batch_root": str(result.batch_root),
                "manifest_path": str(result.manifest_path),
                "manifest_sha256": result.manifest_sha256,
                "status": "passed",
                "write_status": result.write_status,
            },
            sort_keys=True,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
