#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from reddit_voc.v2_center_canonical_export import (  # noqa: E402
    CenterCanonicalExportError,
    build_center_canonical_bundle,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a governed V2 center as a V3 canonical v2 bundle.")
    parser.add_argument("--center-database", required=True, type=Path)
    parser.add_argument("--previous-canonical-root", required=True, type=Path)
    parser.add_argument("--previous-canonical-validation-receipt", required=True, type=Path)
    parser.add_argument("--center-state-sha256", required=True)
    parser.add_argument("--center-orchestration-receipt-sha256", required=True)
    parser.add_argument("--latest-source-batch-manifest-sha256", required=True)
    parser.add_argument("--latest-source-batch-validation-receipt-sha256", required=True)
    parser.add_argument("--previous-canonical-manifest-sha256", required=True)
    parser.add_argument("--previous-canonical-validation-receipt-sha256", required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = build_center_canonical_bundle(
            center_database=args.center_database,
            previous_canonical_root=args.previous_canonical_root,
            previous_canonical_validation_receipt=args.previous_canonical_validation_receipt,
            input_sha256={
                "center_orchestration_receipt_sha256": args.center_orchestration_receipt_sha256,
                "center_state_sha256": args.center_state_sha256,
                "latest_source_batch_manifest_sha256": args.latest_source_batch_manifest_sha256,
                "latest_source_batch_validation_receipt_sha256": args.latest_source_batch_validation_receipt_sha256,
                "previous_canonical_manifest_sha256": args.previous_canonical_manifest_sha256,
                "previous_canonical_validation_receipt_sha256": args.previous_canonical_validation_receipt_sha256,
            },
            dataset_id=args.dataset_id,
            output_root=args.output_root,
        )
    except CenterCanonicalExportError as exc:
        print(f"ERROR:{exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
