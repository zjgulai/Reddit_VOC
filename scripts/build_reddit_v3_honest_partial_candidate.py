#!/usr/bin/env python3
"""Build and independently validate one coordinated unattested V3 candidate.

This local-only coordinator never deploys, switches the runtime pointer, calls a
provider, writes a database, or sends a message.  It accepts only the honest
``not_owner_attested`` metrics contract and materializes formal/public reports
with labeled same-profile observed comparisons. Formal completeness, market
trend, and insight direction claims remain disabled.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import tempfile
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


UNATTESTED_REASON = (
    "historical_collection_coverage_not_owner_attested_complete"
)
BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}


class HonestPartialCandidateError(ValueError):
    """The coordinated local candidate failed closed."""


def _sha(path: Path) -> str:
    digest = sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


def _write_exact(path: Path, value: object) -> None:
    payload = _canonical_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise HonestPartialCandidateError(f"output collision: {path}")
        return
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
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


def build(args: argparse.Namespace) -> dict[str, Any]:
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    binding = load_v3_formal_metrics_binding(
        args.metrics_input_manifest,
        args.metrics_root,
        args.metrics_validation_receipt,
        expected_input_manifest_sha256=args.metrics_input_manifest_sha256,
        expected_candidate_manifest_sha256=args.metrics_manifest_sha256,
        expected_receipt_sha256=args.metrics_validation_receipt_sha256,
        expected_coverage_attestation_sha256=None,
    )
    periodized = binding["periodized_metrics"]
    if (
        binding["source_snapshot_id"] != args.expected_source_snapshot_id
        or periodized.get("comparison_contract_proven") is not False
        or periodized.get("comparison_contract_basis") != "not_owner_attested"
        or periodized.get("comparison_unavailable_reason_codes")
        != [UNATTESTED_REASON]
        or periodized.get("coverage_attestation") is not None
        or periodized.get("data_owner_coverage_attestation_sha256") is not None
    ):
        raise HonestPartialCandidateError(
            "metrics binding is not the reviewed honest-partial contract"
        )

    receipts_root = output_root / "receipts"
    reports_candidate_root = output_root / "reports-candidate"
    reports_public_root = output_root / "reports-public"
    reports, report_index, reports_manifest = build_v3_formal_reports_snapshot(
        binding
    )
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
        expected_coverage_attestation_sha256=None,
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
        public_reports_receipt,
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
    write_v3_insights_snapshot(
        insights_candidate_root, insights, insights_manifest
    )
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
        expected_coverage_attestation_sha256=None,
        expected_reports_manifest_sha256=reports_manifest_sha,
        expected_reports_receipt_sha256=reports_receipt_sha,
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
        public_insights_receipt,
    )

    result = {
        "boundaries": dict(BOUNDARIES),
        "comparison_contract_basis": "not_owner_attested",
        "comparison_contract_proven": False,
        "comparison_unavailable_reason_codes": [UNATTESTED_REASON],
        "completeness_percent": None,
        "datasets": {
            "insights": {
                "candidate_manifest_sha256": insights_manifest_sha,
                "dataset_version": public_insights_manifest["dataset_version"],
                "public_manifest_sha256": _sha(
                    insights_public_root / "manifest.json"
                ),
                "public_validation_status": public_insights_receipt["status"],
                "validation_receipt_sha256": insights_receipt_sha,
            },
            "reports": {
                "candidate_manifest_sha256": reports_manifest_sha,
                "dataset_version": public_reports_manifest["dataset_version"],
                "history_report_count": public_reports_manifest[
                    "history_report_count"
                ],
                "public_manifest_sha256": _sha(
                    reports_public_root / "manifest.json"
                ),
                "public_validation_status": public_reports_receipt["status"],
                "validation_receipt_sha256": reports_receipt_sha,
            },
        },
        "metrics": {
            "input_manifest_sha256": args.metrics_input_manifest_sha256,
            "manifest_sha256": args.metrics_manifest_sha256,
            "validation_receipt_sha256": args.metrics_validation_receipt_sha256,
        },
        "promotable": False,
        "schema_version": "reddit_voc_honest_partial_candidate_receipt_v1",
        "source_snapshot_id": args.expected_source_snapshot_id,
        "status": "passed_local_candidate_only",
    }
    _write_exact(output_root / "coordinated-candidate-receipt.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics-input-manifest", type=Path, required=True)
    parser.add_argument("--metrics-input-manifest-sha256", required=True)
    parser.add_argument("--metrics-root", type=Path, required=True)
    parser.add_argument("--metrics-manifest-sha256", required=True)
    parser.add_argument("--metrics-validation-receipt", type=Path, required=True)
    parser.add_argument("--metrics-validation-receipt-sha256", required=True)
    parser.add_argument("--expected-source-snapshot-id", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    result = build(args)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
