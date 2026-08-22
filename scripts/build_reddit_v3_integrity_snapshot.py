#!/usr/bin/env python3
"""Build a V3 integrity candidate from frozen governed facts only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from reddit_voc.v3_integrity_snapshot import (  # noqa: E402
    IntegritySnapshotError,
    build_snapshot_documents,
    load_frozen_governed_inputs,
    load_policy,
    sha256_bytes,
    write_integrity_snapshot,
)


def build_formal_candidate(
    *,
    upstream_root: Path,
    upstream_receipt_path: Path,
    policy_path: Path,
    output_dir: Path,
    snapshot_id: str,
    generated_at_utc: str,
) -> dict[str, object]:
    inputs = load_frozen_governed_inputs(
        upstream_root=upstream_root,
        upstream_receipt_path=upstream_receipt_path,
        policy_path=policy_path,
    )
    policy, policy_sha = load_policy(policy_path)
    if policy_sha != inputs.policy_sha256:
        raise IntegritySnapshotError("policy changed after upstream binding")
    documents = build_snapshot_documents(
        inputs,
        policy=policy,
        snapshot_id=snapshot_id,
        generated_at_utc=generated_at_utc,
    )
    manifest = write_integrity_snapshot(output_dir, documents)
    manifest_path = Path(output_dir) / "manifest.json"
    return {
        "counts": manifest["counts"],
        "integrity_manifest_sha256": sha256_bytes(manifest_path.read_bytes()),
        "output_dir": str(Path(output_dir).resolve()),
        "promotable": False,
        "status": "candidate_built_pending_independent_validation",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream-root", type=Path, required=True)
    parser.add_argument("--upstream-validation-receipt", type=Path, required=True)
    parser.add_argument(
        "--policy",
        type=Path,
        default=ROOT / "config/analytics/reddit-voc-content-integrity-v1.json",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--generated-at-utc", required=True)
    args = parser.parse_args()
    try:
        result = build_formal_candidate(
            upstream_root=args.upstream_root,
            upstream_receipt_path=args.upstream_validation_receipt,
            policy_path=args.policy,
            output_dir=args.output,
            snapshot_id=args.snapshot_id,
            generated_at_utc=args.generated_at_utc,
        )
    except (IntegritySnapshotError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

