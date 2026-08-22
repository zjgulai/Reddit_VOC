#!/usr/bin/env python3
"""Create a public-only periodic report projection and local receipt."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from reddit_voc.periodic_report_publication import materialize_periodic_public_projection
from reddit_voc.report_contracts import canonical_json_bytes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", required=True, type=Path)
    parser.add_argument("--projection-root", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--expected-release-id", required=True)
    parser.add_argument("--expected-destination-fingerprint", required=True)
    parser.add_argument("--expected-bundle-manifest-sha256", required=True)
    return parser.parse_args()


def write_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> int:
    args = parse_args()
    _, receipt = materialize_periodic_public_projection(
        bundle_root=args.bundle_root,
        projection_root=args.projection_root,
        expected_release_id=args.expected_release_id,
        expected_destination_fingerprint=args.expected_destination_fingerprint,
        expected_bundle_manifest_sha256=args.expected_bundle_manifest_sha256,
    )
    write_new(args.receipt, canonical_json_bytes(receipt))
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
