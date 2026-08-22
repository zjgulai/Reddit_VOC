#!/usr/bin/env python3
"""Build a deterministic, PII-free public governance casebook projection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from reddit_voc.v3_casebook_public import (  # noqa: E402
    CasebookPublicProjectionError,
    build_public_projection,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--casebook-root", type=Path, required=True)
    parser.add_argument("--expected-casebook-manifest-sha256", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--expected-receipt-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--projection-id", required=True)
    args = parser.parse_args()
    try:
        result = build_public_projection(
            casebook_root=args.casebook_root,
            expected_casebook_manifest_sha256=args.expected_casebook_manifest_sha256,
            receipt_path=args.receipt,
            expected_receipt_sha256=args.expected_receipt_sha256,
            output_root=args.output,
            projection_id=args.projection_id,
        )
    except (CasebookPublicProjectionError, OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
