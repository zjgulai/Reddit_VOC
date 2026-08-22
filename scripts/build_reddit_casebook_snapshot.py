#!/usr/bin/env python3
"""Build the private Momcozy Reddit governance casebook candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from reddit_voc.v3_casebook_snapshot import (  # noqa: E402
    build_casebook_documents,
    sha256_bytes,
    write_casebook_snapshot,
)


V3_ROOT = ROOT / "tmp/reddit-voc-v3/reddit_add_data_20260715_v1"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-registry-root", type=Path, required=True)
    parser.add_argument("--reference-receipt", type=Path, required=True)
    parser.add_argument(
        "--facts-root", type=Path, default=V3_ROOT / "voc-facts-candidate-a2"
    )
    parser.add_argument(
        "--facts-receipt",
        type=Path,
        default=V3_ROOT / "voc-facts-validation-a2/receipt.json",
    )
    parser.add_argument(
        "--governed-root",
        type=Path,
        default=V3_ROOT / "governed-signals-candidate-a1",
    )
    parser.add_argument(
        "--governed-receipt",
        type=Path,
        default=V3_ROOT / "governed-signals-validation-a1/receipt.json",
    )
    parser.add_argument("--facts-manifest-sha256")
    parser.add_argument("--facts-receipt-sha256")
    parser.add_argument("--governed-manifest-sha256")
    parser.add_argument("--governed-receipt-sha256")
    parser.add_argument("--casebook-id", required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    documents = build_casebook_documents(
        reference_registry_root=args.reference_registry_root,
        reference_receipt_path=args.reference_receipt,
        facts_root=args.facts_root,
        facts_receipt_path=args.facts_receipt,
        governed_root=args.governed_root,
        governed_receipt_path=args.governed_receipt,
        casebook_id=args.casebook_id,
        generated_at=args.generated_at,
        **{
            key: value
            for key, value in {
                "facts_manifest_sha256": args.facts_manifest_sha256,
                "facts_receipt_sha256": args.facts_receipt_sha256,
                "governed_manifest_sha256": args.governed_manifest_sha256,
                "governed_receipt_sha256": args.governed_receipt_sha256,
            }.items()
            if value is not None
        },
    )
    manifest = write_casebook_snapshot(args.output_root, documents)
    manifest_sha = sha256_bytes((args.output_root / "manifest.json").read_bytes())
    print(
        json.dumps(
            {
                "counts": manifest["counts"],
                "manifest_sha256": manifest_sha,
                "output_root": str(args.output_root),
                "promotable": False,
                "status": "candidate_built_pending_independent_validation",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
