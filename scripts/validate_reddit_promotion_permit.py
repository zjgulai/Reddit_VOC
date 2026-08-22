#!/usr/bin/env python3
"""Read-only CLI for one exact Reddit VOC promotion permit."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

try:
    from scripts.build_reddit_promotion_permit import (
        PromotionPermitError,
        validate_promotion_permit,
    )
except ModuleNotFoundError:  # Direct ``python scripts/...`` execution.
    from build_reddit_promotion_permit import (
        PromotionPermitError,
        validate_promotion_permit,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--packet-artifact-root", type=Path)
    parser.add_argument("--permit", type=Path, required=True)
    parser.add_argument("--permit-sha256", required=True)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--packet-sha256", required=True)
    parser.add_argument("--release-sha256", required=True)
    parser.add_argument("--expected-current-release-sha256", required=True)
    parser.add_argument("--expected-current-data-release-id")
    parser.add_argument("--expected-current-data-pointer-sha256")
    parser.add_argument("--target-data-pointer-sha256")
    parser.add_argument(
        "--now-utc",
        default=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = validate_promotion_permit(
            artifact_root=args.artifact_root,
            packet_artifact_root=args.packet_artifact_root,
            permit_path=args.permit,
            expected_permit_sha256=args.permit_sha256,
            packet_path=args.packet,
            expected_packet_sha256=args.packet_sha256,
            expected_release_sha256=args.release_sha256,
            expected_current_release_sha256=args.expected_current_release_sha256,
            expected_current_data_release_id=(
                args.expected_current_data_release_id
            ),
            expected_current_data_pointer_sha256=(
                args.expected_current_data_pointer_sha256
            ),
            target_data_pointer_sha256=args.target_data_pointer_sha256,
            now_utc=args.now_utc,
        )
    except PromotionPermitError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
