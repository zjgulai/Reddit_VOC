#!/usr/bin/env python3
"""Build attested (owner-declaration) reports + insights from a metrics candidate.

Mirrors scripts/build_reddit_v3_honest_partial_candidate.py's flow, but passes
expected_coverage_attestation_sha256 so load_v3_formal_metrics_binding accepts an
owner-attested periodized candidate and emits
comparison_contract_proven=true. The honest-partial coordinator hard-rejects
attested candidates, so the library functions are driven directly — the same
functions, the same write/validate order, only the attestation expectation and
the output receipt differ.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_reddit_insights_snapshot import (
    build_v3_formal_insights_snapshot,
    build_v3_public_insights_wrapper,
    write_v3_insights_snapshot,
    write_v3_public_insights_wrapper,
)
from scripts.build_reddit_reports_snapshot import (
    V3_REPORT_PATHS,
    build_v3_formal_reports_snapshot,
    build_v3_public_reports_wrapper,
    load_v3_formal_metrics_binding,
    write_v3_public_reports_wrapper,
    write_v3_reports_snapshot,
)
from scripts.validate_reddit_insights_snapshot import (
    validate_v3_formal_insights_snapshot,
    validate_v3_public_insights_wrapper,
    write_v3_insights_validation_receipt,
)
from scripts.validate_reddit_reports_snapshot import (
    validate_v3_formal_reports_snapshot,
    validate_v3_public_reports_wrapper,
    write_v3_reports_validation_receipt,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_exact(path: Path, payload: bytes) -> None:
    descriptor, temporary_name = __import__("tempfile").mkstemp(dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        os.write(descriptor, payload)
        os.close(descriptor)
        descriptor = -1
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics-input-manifest", type=Path, required=True)
    parser.add_argument("--metrics-input-manifest-sha256", required=True)
    parser.add_argument("--metrics-root", type=Path, required=True)
    parser.add_argument("--metrics-manifest-sha256", required=True)
    parser.add_argument("--metrics-validation-receipt", type=Path, required=True)
    parser.add_argument("--metrics-validation-receipt-sha256", required=True)
    parser.add_argument("--expected-source-snapshot-id", required=True)
    parser.add_argument("--coverage-attestation-sha256", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    attestation_sha = args.coverage_attestation_sha256
    binding = load_v3_formal_metrics_binding(
        args.metrics_input_manifest,
        args.metrics_root,
        args.metrics_validation_receipt,
        expected_input_manifest_sha256=args.metrics_input_manifest_sha256,
        expected_candidate_manifest_sha256=args.metrics_manifest_sha256,
        expected_receipt_sha256=args.metrics_validation_receipt_sha256,
        expected_coverage_attestation_sha256=attestation_sha,
    )
    periodized = binding["periodized_metrics"]
    proven = periodized.get("comparison_contract_proven")
    if (
        binding["source_snapshot_id"] != args.expected_source_snapshot_id
        or proven is not True
    ):
        raise SystemExit(
            f"metrics binding is not owner-attested: source={binding['source_snapshot_id']}"
            f" expected={args.expected_source_snapshot_id} proven={proven}"
        )

    receipts_root = output_root / "receipts"
    reports_candidate_root = output_root / "reports-candidate"
    reports_public_root = output_root / "reports-public"
    reports, report_index, reports_manifest = build_v3_formal_reports_snapshot(binding)
    write_v3_reports_snapshot(
        reports_candidate_root, reports, report_index, reports_manifest
    )
    reports_manifest_sha = _sha(reports_candidate_root / "manifest.json")
    reports_receipt = validate_v3_formal_reports_snapshot(
        reports_candidate_root,
        args.metrics_input_manifest,
        args.metrics_root,
        args.metrics_validation_receipt,
        expected_metrics_input_manifest_sha256=args.metrics_input_manifest_sha256,
        expected_metrics_candidate_manifest_sha256=args.metrics_manifest_sha256,
        expected_metrics_receipt_sha256=args.metrics_validation_receipt_sha256,
        expected_coverage_attestation_sha256=attestation_sha,
    )
    reports_receipt_path = receipts_root / "reports-validation.json"
    write_v3_reports_validation_receipt(reports_receipt_path, reports_receipt)
    reports_receipt_sha = _sha(reports_receipt_path)
    (
        public_reports,
        public_report_index,
        embedded_reports_receipt,
        public_reports_manifest,
    ) = build_v3_public_reports_wrapper(
        reports_candidate_root,
        reports_receipt_path,
        expected_candidate_manifest_sha256=reports_manifest_sha,
        expected_validation_receipt_sha256=reports_receipt_sha,
    )
    write_v3_public_reports_wrapper(
        reports_public_root,
        public_reports,
        public_report_index,
        embedded_reports_receipt,
        public_reports_manifest,
    )
    public_reports_receipt = validate_v3_public_reports_wrapper(
        reports_public_root,
        reports_candidate_root,
        reports_receipt_path,
        expected_candidate_manifest_sha256=reports_manifest_sha,
        expected_validation_receipt_sha256=reports_receipt_sha,
    )
    _write_exact(
        receipts_root / "reports-public-validation-v2.json",
        json.dumps(public_reports_receipt, sort_keys=True, separators=(",", ":")).encode()
        + b"\n",
    )

    insights_candidate_root = output_root / "insights-candidate"
    insights_public_root = output_root / "insights-public"
    insight_reports = {name: reports[name] for name in V3_REPORT_PATHS}
    insights, insights_manifest = build_v3_formal_insights_snapshot(
        binding,
        insight_reports,
        report_index,
        reports_manifest,
        reports_receipt,
        report_validation_receipt_sha256=reports_receipt_sha,
    )
    write_v3_insights_snapshot(insights_candidate_root, insights, insights_manifest)
    insights_manifest_sha = _sha(insights_candidate_root / "manifest.json")
    insights_receipt = validate_v3_formal_insights_snapshot(
        insights_candidate_root,
        reports_candidate_root,
        reports_receipt_path,
        args.metrics_input_manifest,
        args.metrics_root,
        args.metrics_validation_receipt,
        expected_metrics_input_manifest_sha256=args.metrics_input_manifest_sha256,
        expected_metrics_candidate_manifest_sha256=args.metrics_manifest_sha256,
        expected_metrics_receipt_sha256=args.metrics_validation_receipt_sha256,
        expected_reports_manifest_sha256=reports_manifest_sha,
        expected_reports_receipt_sha256=reports_receipt_sha,
        expected_coverage_attestation_sha256=attestation_sha,
    )
    insights_receipt_path = receipts_root / "insights-validation.json"
    write_v3_insights_validation_receipt(insights_receipt_path, insights_receipt)
    insights_receipt_sha = _sha(insights_receipt_path)
    (
        public_insights,
        embedded_insights_receipt,
        public_insights_manifest,
    ) = build_v3_public_insights_wrapper(
        insights_candidate_root,
        insights_receipt_path,
        expected_candidate_manifest_sha256=insights_manifest_sha,
        expected_validation_receipt_sha256=insights_receipt_sha,
    )
    write_v3_public_insights_wrapper(
        insights_public_root,
        public_insights,
        embedded_insights_receipt,
        public_insights_manifest,
    )
    public_insights_receipt = validate_v3_public_insights_wrapper(
        insights_public_root,
        insights_candidate_root,
        insights_receipt_path,
        expected_candidate_manifest_sha256=insights_manifest_sha,
        expected_validation_receipt_sha256=insights_receipt_sha,
    )
    _write_exact(
        receipts_root / "insights-public-validation-v2.json",
        json.dumps(public_insights_receipt, sort_keys=True, separators=(",", ":")).encode()
        + b"\n",
    )

    summary = {
        "comparison_contract_proven": proven,
        "reports_candidate_manifest_sha256": reports_manifest_sha,
        "reports_public_manifest_sha256": _sha(
            reports_public_root / "manifest.json"
        ),
        "insights_candidate_manifest_sha256": insights_manifest_sha,
        "insights_public_manifest_sha256": _sha(
            insights_public_root / "manifest.json"
        ),
        "output_root": str(output_root),
    }
    print(json.dumps(summary, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
