#!/usr/bin/env python3
"""Consume quiescent SourceBatch inputs and register a local V2 candidate."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from reddit_voc.report_contracts import canonical_json_bytes  # noqa: E402
from reddit_voc.source_batch import load_source_batch  # noqa: E402
from reddit_voc.v2_center import (  # noqa: E402
    BOUNDARIES,
    V2CenterError,
    V2CenterStore,
    build_metric_release,
    register_candidate,
)


def _utc(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise V2CenterError(f"{label} is invalid") from exc
    if parsed.tzinfo is None:
        raise V2CenterError(f"{label} is not timezone-aware")
    return parsed.astimezone(timezone.utc)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--center-database", type=Path, required=True)
    parser.add_argument("--source-batch-manifest", type=Path, action="append", required=True)
    parser.add_argument("--source-batch-validation-receipt", type=Path, action="append", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--cutoff-utc", required=True)
    parser.add_argument("--observed-at-utc", required=True)
    parser.add_argument("--quiescence-seconds", type=int, default=60)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--attempt-receipt", type=Path)
    parser.add_argument("--v3-baseline-bridge-receipt", type=Path)
    return parser


def _write_immutable(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise V2CenterError("orchestration receipt immutable collision")
        return "no_change"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return "created"


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if isinstance(args.quiescence_seconds, bool) or args.quiescence_seconds < 1:
            raise V2CenterError("quiescence_seconds is invalid")
        cutoff = _utc(args.cutoff_utc, "cutoff_utc")
        observed_at = _utc(args.observed_at_utc, "observed_at_utc")
        if observed_at > datetime.now(timezone.utc):
            raise V2CenterError("observed_at_utc must not be in the future")
        if len(args.source_batch_manifest) != len(args.source_batch_validation_receipt):
            raise V2CenterError("SourceBatch manifest/receipt cardinality mismatch")
        threshold = observed_at - timedelta(seconds=args.quiescence_seconds)
        inputs = []
        for path, receipt_path in zip(
            args.source_batch_manifest, args.source_batch_validation_receipt, strict=True
        ):
            try:
                receipt_payload = receipt_path.read_bytes()
                receipt = json.loads(receipt_payload)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise V2CenterError("SourceBatch validation receipt is invalid") from exc
            if (
                not isinstance(receipt, dict)
                or receipt_payload != canonical_json_bytes(receipt) + b"\n"
                or receipt.get("schema_version") != "reddit_voc_source_batch_validation_receipt_v1"
                or receipt.get("status") != "passed"
                or receipt.get("consumable") is not True
            ):
                raise V2CenterError("SourceBatch validation receipt is not passed")
            before = {
                str(member.relative_to(path.parent)): (
                    member.stat().st_size,
                    member.stat().st_mtime_ns,
                    hashlib.sha256(member.read_bytes()).hexdigest(),
                )
                for member in sorted(path.parent.rglob("*"))
                if member.is_file() and member != receipt_path
            }
            batch = load_source_batch(path, path.parent, require_consumable=True)
            after = {
                str(member.relative_to(path.parent)): (
                    member.stat().st_size,
                    member.stat().st_mtime_ns,
                    hashlib.sha256(member.read_bytes()).hexdigest(),
                )
                for member in sorted(path.parent.rglob("*"))
                if member.is_file() and member != receipt_path
            }
            if before != after:
                raise V2CenterError(f"SourceBatch changed during quiescence probe:{batch.batch_id}")
            if any(
                datetime.fromtimestamp(metadata[1] / 1_000_000_000, tz=timezone.utc) > threshold
                for metadata in after.values()
            ):
                raise V2CenterError(f"SourceBatch is not quiescent:{batch.batch_id}")
            if receipt.get("manifest_sha256") != batch.manifest_sha256:
                raise V2CenterError("SourceBatch validation receipt binding mismatch")
            inputs.append(
                (
                    batch.window.metric_end_utc,
                    batch.batch_id,
                    path,
                    batch.manifest_sha256,
                    hashlib.sha256(receipt_payload).hexdigest(),
                    receipt_path,
                )
            )
        inputs.sort(key=lambda item: (item[0], item[1], item[3]))
        center = V2CenterStore(args.center_database)
        consumption = []
        operation_statuses = []
        baseline_bridge_status = None
        baseline_manifest_sha256 = None
        if args.v3_baseline_bridge_receipt is not None:
            try:
                bridge_preview = json.loads(args.v3_baseline_bridge_receipt.read_bytes())
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise V2CenterError("V3 baseline bridge receipt is invalid") from exc
            if not isinstance(bridge_preview, dict) or not isinstance(
                bridge_preview.get("source_batch_manifest_sha256"), str
            ):
                raise V2CenterError("V3 baseline bridge receipt is invalid")
            baseline_manifest_sha256 = bridge_preview["source_batch_manifest_sha256"]
        for _end, _batch_id, path, _sha, receipt_sha, receipt_path in inputs:
            result = center.consume_source_batch(
                path, validation_receipt_path=receipt_path
            )
            consumption.append(
                {
                    "batch_id": result.batch_id,
                    "manifest_sha256": result.manifest_sha256,
                    "validation_receipt_sha256": receipt_sha,
                }
            )
            operation_statuses.append(
                {"batch_id": result.batch_id, "fusion": result.write_status}
            )
            if (
                args.v3_baseline_bridge_receipt is not None
                and result.manifest_sha256 == baseline_manifest_sha256
            ):
                baseline_bridge_status = center.register_v3_baseline_bridge_receipt(
                    args.v3_baseline_bridge_receipt
                )
        if args.v3_baseline_bridge_receipt is not None and baseline_bridge_status is None:
            # Delegate the final fail-closed binding error to the full receipt validator.
            baseline_bridge_status = center.register_v3_baseline_bridge_receipt(
                args.v3_baseline_bridge_receipt
            )
        cutoff_key = cutoff.strftime("%Y%m%dT%H%M%SZ")
        metric = build_metric_release(
            center,
            cutoff_utc=cutoff,
            output_path=args.output_root / "metric-releases" / cutoff_key / "metric-release.json",
        )
        candidate = register_candidate(
            center,
            metric_release_path=metric.path,
            registry_root=args.output_root / "candidate-registry",
        )
        receipt = {
            "boundaries": dict(BOUNDARIES),
            "candidate_id": candidate.candidate_id,
            "candidate_path": str(candidate.path),
            "candidate_sha256": candidate.sha256,
            "canonical_state_sha256": center.state_sha256(),
            "consumption": consumption,
            "baseline_bridge_status": baseline_bridge_status,
            "metric_release_id": metric.metric_release_id,
            "metric_release_path": str(metric.path),
            "metric_release_sha256": metric.sha256,
            "schema_version": "reddit_voc_v2_candidate_orchestration_receipt_v1",
            "status": "local_candidate_registered",
        }
        payload = canonical_json_bytes(receipt) + b"\n"
        _write_immutable(args.receipt, payload)
        attempt = {
            "candidate_write_status": candidate.write_status,
            "input_receipt_sha256": hashlib.sha256(payload).hexdigest(),
            "metric_write_status": metric.write_status,
            "observed_at_utc": args.observed_at_utc,
            "operation_statuses": operation_statuses,
            "baseline_bridge_status": baseline_bridge_status,
            "schema_version": "reddit_voc_v2_candidate_attempt_receipt_v1",
            "status": "passed",
        }
        if args.attempt_receipt is not None:
            _write_immutable(
                args.attempt_receipt, canonical_json_bytes(attempt) + b"\n"
            )
        sys.stdout.write(
            json.dumps(
                {
                    **receipt,
                    "operation_statuses": operation_statuses,
                    "metric_write_status": metric.write_status,
                    "candidate_write_status": candidate.write_status,
                    "attempt_receipt": str(args.attempt_receipt) if args.attempt_receipt else None,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
        )
        return 0
    except (OSError, V2CenterError, ValueError) as exc:
        sys.stderr.write(
            json.dumps(
                {
                    "boundaries": dict(BOUNDARIES),
                    "error": str(exc),
                    "status": "blocked",
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
