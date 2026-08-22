#!/usr/bin/env python3
"""Validate historical casebook evidence against a pinned newer canonical center."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from reddit_voc.v3_casebook_resolution import (  # noqa: E402
    CasebookResolutionError,
    validate_latest_resolution,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--casebook-public-root", type=Path, required=True)
    parser.add_argument("--expected-casebook-manifest-sha256", required=True)
    parser.add_argument("--canonical-root", type=Path, required=True)
    parser.add_argument("--expected-canonical-manifest-sha256", required=True)
    parser.add_argument("--canonical-receipt", type=Path, required=True)
    parser.add_argument("--expected-canonical-receipt-sha256", required=True)
    parser.add_argument("--generated-at-utc", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = validate_latest_resolution(
            casebook_public_root=args.casebook_public_root,
            expected_casebook_manifest_sha256=args.expected_casebook_manifest_sha256,
            canonical_root=args.canonical_root,
            expected_canonical_manifest_sha256=args.expected_canonical_manifest_sha256,
            canonical_receipt_path=args.canonical_receipt,
            expected_canonical_receipt_sha256=args.expected_canonical_receipt_sha256,
            generated_at_utc=args.generated_at_utc,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(result["payload"])
    except (CasebookResolutionError, OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        "receipt_sha256": result["receipt_sha256"],
        "status": result["receipt"]["status"],
        "resolution": result["receipt"]["resolution"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
