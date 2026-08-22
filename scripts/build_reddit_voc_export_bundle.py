#!/usr/bin/env python3
"""Build one local candidate V3 four-artifact export bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from reddit_voc.v3_export_bundle import (  # noqa: E402
    ARTIFACT_FILES,
    ExportBundleError,
    ExportBundleMetadata,
    canonical_json_bytes,
    sha256_bytes,
    write_export_bundle_from_files,
)


def build_bundle_from_files(
    *,
    input_paths: dict[str, Path],
    output_root: Path,
    metadata: ExportBundleMetadata,
    materialization: dict[str, object] | None = None,
) -> dict[str, object]:
    if set(input_paths) != set(ARTIFACT_FILES):
        raise ExportBundleError("export input member set is invalid")
    manifest = write_export_bundle_from_files(
        output_root,
        input_paths,
        metadata,
        materialization=materialization,
    )
    manifest_sha = sha256_bytes((Path(output_root) / "manifest.json").read_bytes())
    return {
        "counts": {
            item["path"]: item["row_count"] for item in manifest["artifacts"]
        },
        "export_bundle_manifest_sha256": manifest_sha,
        "output_root": str(Path(output_root).resolve()),
        "promotable": False,
        "status": "candidate_built_pending_independent_validation",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    for option, name in {
        "--entities-full": "reddit-entities-full.jsonl",
        "--voc-facts": "reddit-voc-facts.jsonl",
        "--metrics-reporting": "reddit-metrics-reporting.jsonl",
        "--governance-casebook": "reddit-governance-casebook.jsonl",
    }.items():
        parser.add_argument(option, dest=name, type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--export-bundle-id", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--source-snapshot-id", required=True)
    parser.add_argument("--source-cutoff-value", required=True)
    parser.add_argument("--source-cutoff-precision", required=True)
    parser.add_argument("--source-timezone-status", required=True)
    parser.add_argument("--dictionary-sha256", required=True)
    parser.add_argument("--indicator-registry-sha256", required=True)
    parser.add_argument("--eligibility-policy-sha256", required=True)
    parser.add_argument("--builder-code-sha256", required=True)
    parser.add_argument("--validator-code-sha256", required=True)
    parser.add_argument("--candidate-release-sha256", required=True)
    parser.add_argument("--bundle-mode", choices=("public", "private_audit"), required=True)
    parser.add_argument("--materialization-metadata", type=Path)
    return parser


def _load_materialization(path: Path | None) -> dict[str, object] | None:
    if path is None:
        return None
    try:
        payload = path.read_bytes()
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExportBundleError("materialization metadata is invalid") from exc
    if not isinstance(value, dict) or canonical_json_bytes(value) + b"\n" != payload:
        raise ExportBundleError("materialization metadata is noncanonical")
    return value


def main() -> int:
    args = _parser().parse_args()
    metadata = ExportBundleMetadata(
        export_bundle_id=args.export_bundle_id,
        release_id=args.release_id,
        source_snapshot_id=args.source_snapshot_id,
        source_cutoff_value=args.source_cutoff_value,
        source_cutoff_precision=args.source_cutoff_precision,
        source_timezone_status=args.source_timezone_status,
        dictionary_sha256=args.dictionary_sha256,
        indicator_registry_sha256=args.indicator_registry_sha256,
        eligibility_policy_sha256=args.eligibility_policy_sha256,
        builder_code_sha256=args.builder_code_sha256,
        validator_code_sha256=args.validator_code_sha256,
        candidate_release_sha256=args.candidate_release_sha256,
        bundle_mode=args.bundle_mode,
    )
    try:
        result = build_bundle_from_files(
            input_paths={name: getattr(args, name) for name in ARTIFACT_FILES},
            output_root=args.output,
            metadata=metadata,
            materialization=_load_materialization(args.materialization_metadata),
        )
    except (ExportBundleError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
