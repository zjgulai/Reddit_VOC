#!/usr/bin/env python3
"""Materialize the current validated V3 candidate into one private export bundle."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from build_reddit_voc_export_bundle import build_bundle_from_files  # noqa: E402
from reddit_voc.v3_export_bundle import (  # noqa: E402
    ExportBundleError,
    ExportBundleMetadata,
    canonical_json_document,
)
from reddit_voc.v3_export_materializer import (  # noqa: E402
    MaterializationPaths,
    _regular_bytes,
    _safe_directory_chain,
    materialize_export_inputs,
)


SOURCE_LAYOUT = {
    "canonical_dir": "canonical-candidate-a1",
    "canonical_receipt": "canonical-validation-a1/receipt.json",
    "voc_facts_dir": "voc-facts-candidate-a2",
    "voc_facts_receipt": "voc-facts-validation-a2/receipt.json",
    "governed_signals_dir": "governed-signals-candidate-a1",
    "governed_signals_receipt": "governed-signals-validation-a1/receipt.json",
    "metrics_dir": "metrics-candidate-a5",
    "metrics_receipt": "metrics-validation-a5/receipt.json",
    "integrity_dir": "integrity-candidate-a1",
    "integrity_receipt": "integrity-validation-a1/receipt.json",
    "integrity_input_dir": "integrity-input-a1",
    "integrity_input_receipt": "integrity-input-validation-a1/receipt.json",
    "casebook_dir": "casebook-candidate-a1",
    "casebook_receipt": "casebook-validation-a1/receipt.json",
    "case_reference_dir": "case-reference-candidate-a1",
    "case_reference_receipt": "case-reference-validation-a1/receipt.json",
    "reports_dir": "reports-candidate-a5r2",
    "reports_receipt": "reports-validation-a5r2/receipt.json",
    "personas_dir": "personas-candidate-a4",
    "personas_receipt": "personas-validation-a4/receipt.json",
    "current_release": "current-release-a5r2/current-release.json",
}


def _load_object(
    path: Path, label: str, *, require_canonical: bool = False
) -> dict[str, Any]:
    payload = _regular_bytes(path, label)
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ExportBundleError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ExportBundleError(f"{label} must be an object")
    if require_canonical and canonical_json_document(value) != payload:
        raise ExportBundleError(f"{label} is noncanonical")
    return value


def _required_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ExportBundleError(f"{label} is missing")
    return value


def _source_paths(candidate_root: Path) -> MaterializationPaths:
    return MaterializationPaths(
        **{key: candidate_root / relative for key, relative in SOURCE_LAYOUT.items()}
    )


def _metadata(
    *,
    paths: MaterializationPaths,
    export_bundle_id: str,
    candidate_release_sha256: str,
) -> ExportBundleMetadata:
    current_release = _load_object(paths.current_release, "current release")
    reports = _load_object(paths.reports_dir / "manifest.json", "reports manifest")
    governed = _load_object(
        paths.governed_signals_dir / "manifest.json", "governed signals manifest"
    )
    voc_facts = _load_object(
        paths.voc_facts_dir / "manifest.json", "VOC facts manifest"
    )
    metrics = _load_object(paths.metrics_dir / "manifest.json", "metrics manifest")
    governed_inputs = governed.get("inputs")
    facts_inputs = voc_facts.get("inputs")
    coverage = reports.get("coverage_attestation")
    window = coverage.get("coverage_window") if isinstance(coverage, Mapping) else None
    if (
        not isinstance(governed_inputs, Mapping)
        or not isinstance(facts_inputs, Mapping)
        or not isinstance(window, Mapping)
    ):
        raise ExportBundleError("candidate metadata lineage is incomplete")
    return ExportBundleMetadata(
        export_bundle_id=export_bundle_id,
        release_id=_required_string(current_release.get("release_id"), "release_id"),
        source_snapshot_id=_required_string(
            reports.get("source_snapshot_id"), "source_snapshot_id"
        ),
        source_cutoff_value=_required_string(
            window.get("end_calendar_date_inclusive"), "source cutoff"
        ),
        source_cutoff_precision="day",
        source_timezone_status="unknown_floating_date",
        dictionary_sha256=_required_string(
            governed_inputs.get("dim_tag_sha256"), "dictionary SHA-256"
        ),
        indicator_registry_sha256=_required_string(
            metrics.get("registry_sha256"), "indicator registry SHA-256"
        ),
        eligibility_policy_sha256=_required_string(
            facts_inputs.get("eligibility_policy_sha256"),
            "eligibility policy SHA-256",
        ),
        builder_code_sha256=sha256(
            (ROOT / "scripts/build_reddit_voc_export_bundle.py").read_bytes()
        ).hexdigest(),
        validator_code_sha256=sha256(
            (ROOT / "scripts/validate_reddit_voc_export_bundle.py").read_bytes()
        ).hexdigest(),
        candidate_release_sha256=candidate_release_sha256,
        bundle_mode="private_audit",
    )


def materialize_bundle(
    *,
    candidate_root: Path,
    output: Path,
    export_bundle_id: str,
    candidate_release_sha256: str,
) -> dict[str, object]:
    candidate_root = _safe_directory_chain(candidate_root)
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise ExportBundleError("export bundle output root already exists")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent_metadata = os.lstat(output.parent)
    if stat.S_ISLNK(parent_metadata.st_mode) or not stat.S_ISDIR(
        parent_metadata.st_mode
    ):
        raise ExportBundleError("export bundle output parent is unsafe")
    os.chmod(output.parent, 0o700)

    paths = _source_paths(candidate_root)
    metadata = _metadata(
        paths=paths,
        export_bundle_id=export_bundle_id,
        candidate_release_sha256=candidate_release_sha256,
    )
    materializer_sha = sha256(
        (ROOT / "src/reddit_voc/v3_export_materializer.py").read_bytes()
    ).hexdigest()
    workspace = Path(
        tempfile.mkdtemp(prefix=".reddit-voc-export-materialization-", dir=output.parent)
    )
    os.chmod(workspace, 0o700)
    try:
        input_root = workspace / "inputs"
        input_paths, _ = materialize_export_inputs(
            paths,
            metadata,
            input_root,
            materializer_code_sha256=materializer_sha,
        )
        materialization = _load_object(
            input_root / "materialization-metadata.json",
            "materialization metadata",
            require_canonical=True,
        )
        result = build_bundle_from_files(
            input_paths=input_paths,
            output_root=output,
            metadata=metadata,
            materialization=materialization,
        )
        return {
            **result,
            "bundle_mode": "private_audit",
            "release_id": metadata.release_id,
            "source_snapshot_id": metadata.source_snapshot_id,
        }
    finally:
        if workspace.exists():
            shutil.rmtree(workspace)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--export-bundle-id", required=True)
    parser.add_argument("--candidate-release-sha256", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = materialize_bundle(
            candidate_root=args.candidate_root,
            output=args.output,
            export_bundle_id=args.export_bundle_id,
            candidate_release_sha256=args.candidate_release_sha256,
        )
    except (ExportBundleError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
