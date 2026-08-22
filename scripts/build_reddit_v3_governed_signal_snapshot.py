#!/usr/bin/env python3
"""Build the formal private V3 eight-table governed-signal candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from reddit_voc.v3_closed_set_facts import load_closed_set_resources  # noqa: E402
from reddit_voc.v3_governed_signal_inputs import (  # noqa: E402
    load_formal_governed_signal_inputs,
)
from reddit_voc.v3_governed_signal_snapshot import (  # noqa: E402
    write_governed_signal_snapshot,
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
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--created-at", required=True)
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
    resources = load_closed_set_resources(
        dim_tag_path=args.dim_tag,
        product_entity_ledger_path=args.product_ledger,
        registry_path=args.registry,
    )
    summary = write_governed_signal_snapshot(
        vocs=inputs.vocs,
        automation_voc_ids=inputs.automation_voc_ids,
        resources=resources,
        input_bindings=inputs.input_bindings,
        source_snapshot_id=inputs.source_snapshot_id,
        snapshot_id=args.snapshot_id,
        created_at=args.created_at,
        output_root=args.output_root,
    )
    print(
        json.dumps(
            {
                "automation_excluded_vocs": summary.automation_excluded_vocs,
                "boundaries": {
                    "database_write": False,
                    "deploy": False,
                    "live_send": False,
                    "production_unchanged": True,
                    "provider_call": False,
                    "remote_write": False,
                },
                "fact_rows": summary.fact_rows,
                "manifest_sha256": summary.manifest_sha256,
                "organic_vocs": summary.organic_vocs,
                "output_root": str(summary.output_root),
                "status": "candidate_built",
                "total_vocs": summary.total_vocs,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
