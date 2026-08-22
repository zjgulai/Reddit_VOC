#!/usr/bin/env python3
"""Build and verify a local immutable daily/weekly/monthly shadow bundle.

This command only copies already-validated local poster bytes and freezes
secret-free DingTalk request bodies. It performs no network request or send.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from reddit_voc.periodic_report_bundle import (
    build_periodic_report_bundle,
    verify_periodic_report_bundle,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--poster-manifest", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--artifact-base-url", required=True)
    parser.add_argument("--dashboard-base-url", required=True)
    parser.add_argument("--destination-fingerprint", required=True)
    parser.add_argument("--expected-release-id", required=True)
    parser.add_argument("--expected-dataset-version", required=True)
    parser.add_argument("--required-keyword", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_sha256, manifest = build_periodic_report_bundle(
        poster_manifest_path=args.poster_manifest,
        output_root=args.output_root,
        artifact_base_url=args.artifact_base_url,
        dashboard_base_url=args.dashboard_base_url,
        destination_fingerprint=args.destination_fingerprint,
        expected_release_id=args.expected_release_id,
        expected_dataset_version=args.expected_dataset_version,
        required_keyword=args.required_keyword,
    )
    verified = verify_periodic_report_bundle(
        args.output_root,
        expected_release_id=args.expected_release_id,
        expected_destination_fingerprint=args.destination_fingerprint,
    )
    print(
        json.dumps(
            {
                "status": verified["status"],
                "bundle_id": verified["bundle_id"],
                "manifest_sha256": manifest_sha256,
                "periods": [row["grain"] for row in manifest["captures"]],
                "delivery_eligible": manifest["delivery"]["eligible"],
                "boundaries": manifest["boundaries"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
