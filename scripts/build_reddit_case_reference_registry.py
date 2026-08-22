#!/usr/bin/env python3
"""Build the private verified Reddit CaseReference registry."""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from reddit_voc.v3_case_reference_registry import (  # noqa: E402
    build_case_reference_documents,
    load_case_reference_policy,
    load_external_public_capture,
    sha256_bytes,
    write_case_reference_registry,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--policy",
        type=Path,
        default=ROOT / "config/cases/reddit-voc-case-reference-policy-v1.json",
    )
    parser.add_argument("--external-capture", type=Path, required=True)
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    parser.add_argument("--registry-id", required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    policy, policy_sha = load_case_reference_policy(args.policy)
    capture, capture_sha = load_external_public_capture(
        args.external_capture, policy=policy
    )
    documents = build_case_reference_documents(
        captures=[capture],
        capture_sha256s=[capture_sha],
        policy=policy,
        policy_sha256=policy_sha,
        as_of=args.as_of,
        registry_id=args.registry_id,
        generated_at=args.generated_at,
    )
    manifest = write_case_reference_registry(args.output_root, documents)
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
