#!/usr/bin/env python3
"""Validate and issue a receipt for the private governance casebook."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from reddit_voc.v3_casebook_snapshot import canonical_json_document  # noqa: E402
from reddit_voc.v3_casebook_snapshot_validator import (  # noqa: E402
    CasebookSnapshotValidationError,
    validate_casebook_snapshot,
)


V3_ROOT = ROOT / "tmp/reddit-voc-v3/reddit_add_data_20260715_v1"


def _write_receipt(path: Path, receipt: dict[str, object]) -> str:
    payload = canonical_json_document(receipt)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise CasebookSnapshotValidationError("receipt collision")
        return "no_change"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.write(descriptor, payload)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()
    return "created"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--casebook-root", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--reference-registry-root", type=Path, required=True)
    parser.add_argument("--reference-receipt", type=Path, required=True)
    parser.add_argument(
        "--facts-root", type=Path, default=V3_ROOT / "voc-facts-candidate-a2"
    )
    parser.add_argument(
        "--facts-receipt",
        type=Path,
        default=V3_ROOT / "voc-facts-validation-a2/receipt.json",
    )
    parser.add_argument(
        "--governed-root",
        type=Path,
        default=V3_ROOT / "governed-signals-candidate-a1",
    )
    parser.add_argument(
        "--governed-receipt",
        type=Path,
        default=V3_ROOT / "governed-signals-validation-a1/receipt.json",
    )
    parser.add_argument("--facts-manifest-sha256")
    parser.add_argument("--facts-receipt-sha256")
    parser.add_argument("--governed-manifest-sha256")
    parser.add_argument("--governed-receipt-sha256")
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = validate_casebook_snapshot(
            casebook_root=args.casebook_root,
            expected_manifest_sha256=args.expected_manifest_sha256,
            reference_registry_root=args.reference_registry_root,
            reference_receipt_path=args.reference_receipt,
            facts_root=args.facts_root,
            facts_receipt_path=args.facts_receipt,
            governed_root=args.governed_root,
            governed_receipt_path=args.governed_receipt,
            **{
                key: value
                for key, value in {
                    "facts_manifest_sha256": args.facts_manifest_sha256,
                    "facts_receipt_sha256": args.facts_receipt_sha256,
                    "governed_manifest_sha256": args.governed_manifest_sha256,
                    "governed_receipt_sha256": args.governed_receipt_sha256,
                }.items()
                if value is not None
            },
        )
        disposition = _write_receipt(args.receipt, result)
    except CasebookSnapshotValidationError as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {**result, "receipt_disposition": disposition},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
