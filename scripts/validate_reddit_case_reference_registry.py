#!/usr/bin/env python3
"""Validate and issue a receipt for the private CaseReference registry."""

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

from reddit_voc.v3_case_reference_registry import (  # noqa: E402
    CaseReferenceRegistryError,
    canonical_json_document,
)
from reddit_voc.v3_case_reference_registry_validator import (  # noqa: E402
    CaseReferenceRegistryValidationError,
    validate_case_reference_registry,
)


def _write_receipt(path: Path, receipt: dict[str, object]) -> str:
    payload = canonical_json_document(receipt)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise CaseReferenceRegistryValidationError("receipt collision")
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
    parser.add_argument("--registry-root", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument(
        "--policy",
        type=Path,
        default=ROOT / "config/cases/reddit-voc-case-reference-policy-v1.json",
    )
    parser.add_argument("--external-capture", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = validate_case_reference_registry(
            registry_root=args.registry_root,
            expected_manifest_sha256=args.expected_manifest_sha256,
            policy_path=args.policy,
            capture_path=args.external_capture,
        )
        disposition = _write_receipt(args.receipt, result)
    except (CaseReferenceRegistryError, CaseReferenceRegistryValidationError) as exc:
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
