#!/usr/bin/env python3
"""Build one immutable private Reddit VOC V3 canonical snapshot candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from reddit_voc.v3_canonical_fusion import (  # noqa: E402
    CanonicalFusionError,
    build_canonical_snapshot,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build an immutable private Reddit VOC V3 canonical snapshot candidate."
    )
    parser.add_argument("--import-bundle-root", required=True, type=Path)
    parser.add_argument("--import-bundle-manifest-sha256", required=True)
    parser.add_argument("--import-validation-receipt", required=True, type=Path)
    parser.add_argument("--import-validation-receipt-sha256", required=True)
    parser.add_argument("--source-manifest", required=True, type=Path)
    parser.add_argument("--base-public-manifest-sha256", required=True)
    parser.add_argument("--base-lineage-manifest-sha256", required=True)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--project-root", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        result = build_canonical_snapshot(
            import_bundle_root=arguments.import_bundle_root,
            import_bundle_manifest_sha256=arguments.import_bundle_manifest_sha256,
            import_validation_receipt_path=arguments.import_validation_receipt,
            import_validation_receipt_sha256=arguments.import_validation_receipt_sha256,
            source_manifest_path=arguments.source_manifest,
            base_public_manifest_sha256=arguments.base_public_manifest_sha256,
            base_lineage_manifest_sha256=arguments.base_lineage_manifest_sha256,
            output_root=arguments.output_root,
            project_root=arguments.project_root,
        )
    except CanonicalFusionError as exc:
        print(f"reddit_v3_canonical_snapshot_failed:{exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "boundaries": result.boundaries,
                "dataset_id": result.dataset_id,
                "linked_comments": result.linked_comments,
                "manifest_sha256": result.manifest_sha256,
                "posts": result.posts,
                "quarantined_comments": result.quarantined_comments,
                "schema_version": result.schema_version,
                "stored_comments": result.stored_comments,
                "unresolved_parent_comments": result.unresolved_parent_comments,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
