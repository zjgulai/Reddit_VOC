#!/usr/bin/env python3
"""Build one immutable local V2 center-to-business activation manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from reddit_voc.v2_business_activation import (  # noqa: E402
    V2BusinessActivationError,
    build_business_activation,
)
from reddit_voc.v2_center import V2CenterError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build_business_activation(
            project_root=args.project_root,
            spec_path=args.spec,
            output_path=args.output,
        )
    except (OSError, KeyError, TypeError, V2BusinessActivationError, V2CenterError) as exc:
        sys.stderr.write(json.dumps({"error": str(exc), "status": "blocked"}, sort_keys=True) + "\n")
        return 1
    sys.stdout.write(
        json.dumps(
            {
                "activation_id": result.activation_id,
                "manifest_path": str(result.manifest_path),
                "manifest_sha256": result.manifest_sha256,
                "status": "passed",
                "write_status": result.write_status,
            },
            sort_keys=True,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
