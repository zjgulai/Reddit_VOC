#!/usr/bin/env python3
"""Independently validate the formal V3 governed-signal candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from reddit_voc.v3_governed_signal_inputs import (  # noqa: E402
    load_formal_governed_signal_inputs,
)
from reddit_voc.v3_governed_signal_snapshot_validator import (  # noqa: E402
    validate_governed_signal_snapshot,
    write_governed_signal_validation_receipt,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--facts-root", type=Path, required=True)
    parser.add_argument("--facts-receipt", type=Path, required=True)
    parser.add_argument("--facts-manifest-sha256")
    parser.add_argument("--facts-receipt-sha256")
    parser.add_argument("--dim-tag", type=Path, required=True)
    parser.add_argument("--product-ledger", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    inputs = load_formal_governed_signal_inputs(
        facts_root=args.facts_root,
        facts_receipt_path=args.facts_receipt,
        dim_tag_path=args.dim_tag,
        product_entity_ledger_path=args.product_ledger,
        registry_path=args.registry,
        **(
            {}
            if args.facts_manifest_sha256 is None and args.facts_receipt_sha256 is None
            else {
                "facts_manifest_sha256": args.facts_manifest_sha256,
                "facts_receipt_sha256": args.facts_receipt_sha256,
            }
        ),
    )
    receipt = validate_governed_signal_snapshot(
        snapshot_root=args.snapshot_root,
        inputs=inputs,
        dim_tag_path=args.dim_tag,
        product_entity_ledger_path=args.product_ledger,
        registry_path=args.registry,
    )
    receipt_sha256 = write_governed_signal_validation_receipt(
        receipt, args.output_root
    )
    print(
        json.dumps(
            {
                **receipt,
                "receipt_sha256": receipt_sha256,
                "validation_output_root": str(args.output_root),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
