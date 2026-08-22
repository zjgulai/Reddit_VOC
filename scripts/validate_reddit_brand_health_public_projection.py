#!/usr/bin/env python3
"""Validate the pinned public V3 brand-health projection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from reddit_voc.v3_brand_health_public import (  # noqa: E402
    BrandHealthPublicProjectionError,
    validate_public_projection,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    args = parser.parse_args()
    try:
        result = validate_public_projection(
            output_root=args.output,
            expected_manifest_sha256=args.expected_manifest_sha256,
        )
    except (BrandHealthPublicProjectionError, OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
