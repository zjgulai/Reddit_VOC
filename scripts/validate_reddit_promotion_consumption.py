#!/usr/bin/env python3
"""Read-only CLI for one promotion consumption receipt."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

try:
    from scripts.build_reddit_promotion_consumption import (
        PromotionConsumptionError,
        validate_promotion_consumption,
        validate_promotion_consumption_document,
    )
except ModuleNotFoundError:  # Direct ``python scripts/...`` execution.
    from build_reddit_promotion_consumption import (
        PromotionConsumptionError,
        validate_promotion_consumption,
        validate_promotion_consumption_document,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--expected-receipt-sha256", required=True)
    parser.add_argument("--expected-packet-sha256")
    parser.add_argument("--expected-permit-sha256")
    parser.add_argument("--expected-release-sha256")
    parser.add_argument("--expected-remote-promotion-receipt-sha256")
    parser.add_argument("--expected-acceptance-receipt-sha256")
    parser.add_argument("--no-reopen-acceptance", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = validate_promotion_consumption(
            artifact_root=args.artifact_root,
            receipt_path=args.receipt,
            expected_receipt_sha256=args.expected_receipt_sha256,
            expected_packet_sha256=args.expected_packet_sha256,
            expected_permit_sha256=args.expected_permit_sha256,
            expected_release_sha256=args.expected_release_sha256,
            expected_remote_promotion_receipt_sha256=(
                args.expected_remote_promotion_receipt_sha256
            ),
            expected_acceptance_receipt_sha256=(
                args.expected_acceptance_receipt_sha256
            ),
            reopen_acceptance=not args.no_reopen_acceptance,
        )
    except PromotionConsumptionError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
