#!/usr/bin/env python3
"""Freeze Task 5 and Task 9 evidence for the V3 integrity snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from reddit_voc.v3_integrity_inputs import (  # noqa: E402
    IntegrityInputError,
    build_integrity_input_documents,
    load_integrity_sources,
    write_integrity_inputs,
)
from reddit_voc.v3_integrity_snapshot import load_policy, sha256_bytes  # noqa: E402


def build_formal_inputs(
    *,
    governed_root: Path,
    governed_receipt_path: Path,
    voc_facts_root: Path,
    voc_facts_receipt_path: Path,
    reference_root: Path,
    reference_receipt_path: Path,
    casebook_root: Path,
    casebook_receipt_path: Path,
    policy_path: Path,
    output_root: Path,
    input_id: str,
    generated_at_utc: str,
) -> dict[str, object]:
    sources = load_integrity_sources(
        governed_root=governed_root,
        governed_receipt_path=governed_receipt_path,
        voc_facts_root=voc_facts_root,
        voc_facts_receipt_path=voc_facts_receipt_path,
        reference_root=reference_root,
        reference_receipt_path=reference_receipt_path,
        casebook_root=casebook_root,
        casebook_receipt_path=casebook_receipt_path,
    )
    _, policy_sha = load_policy(policy_path)
    documents = build_integrity_input_documents(
        sources,
        policy_sha256=policy_sha,
        input_id=input_id,
        generated_at_utc=generated_at_utc,
    )
    manifest = write_integrity_inputs(output_root, documents)
    manifest_sha = sha256_bytes((Path(output_root) / "manifest.json").read_bytes())
    return {
        "counts": manifest["counts"],
        "input_manifest_sha256": manifest_sha,
        "output_root": str(Path(output_root).resolve()),
        "promotable": False,
        "status": "frozen_pending_independent_validation",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--governed-root", type=Path, required=True)
    parser.add_argument("--governed-receipt", type=Path, required=True)
    parser.add_argument("--voc-facts-root", type=Path, required=True)
    parser.add_argument("--voc-facts-receipt", type=Path, required=True)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--reference-receipt", type=Path, required=True)
    parser.add_argument("--casebook-root", type=Path, required=True)
    parser.add_argument("--casebook-receipt", type=Path, required=True)
    parser.add_argument(
        "--policy",
        type=Path,
        default=ROOT / "config/analytics/reddit-voc-content-integrity-v1.json",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--input-id", required=True)
    parser.add_argument("--generated-at-utc", required=True)
    args = parser.parse_args()
    try:
        result = build_formal_inputs(
            governed_root=args.governed_root,
            governed_receipt_path=args.governed_receipt,
            voc_facts_root=args.voc_facts_root,
            voc_facts_receipt_path=args.voc_facts_receipt,
            reference_root=args.reference_root,
            reference_receipt_path=args.reference_receipt,
            casebook_root=args.casebook_root,
            casebook_receipt_path=args.casebook_receipt,
            policy_path=args.policy,
            output_root=args.output,
            input_id=args.input_id,
            generated_at_utc=args.generated_at_utc,
        )
    except (IntegrityInputError, OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
