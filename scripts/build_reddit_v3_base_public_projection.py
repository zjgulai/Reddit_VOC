#!/usr/bin/env python3
"""Build one isolated privacy-safe V3 Base snapshot from the canonical union."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from reddit_voc.v3_base_public import build_public_base_projection


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--source-snapshot-id", required=True)
    parser.add_argument("--generated-at-utc", required=True)
    parser.add_argument("--canonical-root", type=Path, required=True)
    parser.add_argument("--canonical-manifest-sha256", required=True)
    parser.add_argument("--canonical-validation-receipt", type=Path, required=True)
    parser.add_argument("--canonical-validation-receipt-sha256", required=True)
    parser.add_argument("--tag-dictionary", type=Path, required=True)
    parser.add_argument("--coverage-attestation", type=Path)
    parser.add_argument("--coverage-attestation-sha256")
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if (args.coverage_attestation is None) != (
        args.coverage_attestation_sha256 is None
    ):
        raise ValueError("coverage_attestation_and_sha_must_be_paired")
    coverage_attestation = None
    if args.coverage_attestation is not None:
        coverage_attestation = json.loads(
            args.coverage_attestation.read_text(encoding="utf-8")
        )
    result = build_public_base_projection(
        dataset_version=args.dataset_version,
        source_snapshot_id=args.source_snapshot_id,
        generated_at_utc=args.generated_at_utc,
        canonical_root=args.canonical_root,
        canonical_manifest_sha256=args.canonical_manifest_sha256,
        canonical_validation_receipt=args.canonical_validation_receipt,
        canonical_validation_receipt_sha256=(
            args.canonical_validation_receipt_sha256
        ),
        tag_dictionary_path=args.tag_dictionary,
        output_dir=args.output_dir,
        coverage_attestation=coverage_attestation,
        coverage_attestation_sha256=args.coverage_attestation_sha256,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
