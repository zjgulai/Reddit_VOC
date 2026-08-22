#!/usr/bin/env python3
"""Build the pinned, local-only rolling-quarter public insight projection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from reddit_voc.v3_quarter_insights_public import (  # noqa: E402
    EXPECTED_DATASET_VERSION,
    QuarterInsightsPublicProjectionError,
    build_public_projection,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--casebook-public-root", type=Path, required=True)
    parser.add_argument("--product-ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dataset-version", default=EXPECTED_DATASET_VERSION)
    parser.add_argument("--generated-at-utc", default="2026-07-16T00:00:00+00:00")
    for name in (
        "canonical-manifest",
        "canonical-receipt",
        "voc-manifest",
        "voc-receipt",
        "governed-manifest",
        "governed-receipt",
        "persona-manifest",
        "persona-receipt",
        "casebook-public-manifest",
        "product-ledger",
    ):
        parser.add_argument(f"--expected-{name}-sha256", required=True)
    args = parser.parse_args()
    expected_hashes = {
        "canonical_manifest": args.expected_canonical_manifest_sha256,
        "canonical_receipt": args.expected_canonical_receipt_sha256,
        "voc_manifest": args.expected_voc_manifest_sha256,
        "voc_receipt": args.expected_voc_receipt_sha256,
        "governed_manifest": args.expected_governed_manifest_sha256,
        "governed_receipt": args.expected_governed_receipt_sha256,
        "persona_manifest": args.expected_persona_manifest_sha256,
        "persona_receipt": args.expected_persona_receipt_sha256,
        "casebook_public_manifest": args.expected_casebook_public_manifest_sha256,
        "product_ledger": args.expected_product_ledger_sha256,
    }
    try:
        result = build_public_projection(
            source_root=args.source_root,
            casebook_public_root=args.casebook_public_root,
            product_ledger_path=args.product_ledger,
            expected_hashes=expected_hashes,
            output_root=args.output,
            dataset_version=args.dataset_version,
            generated_at_utc=args.generated_at_utc,
        )
    except (QuarterInsightsPublicProjectionError, OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
