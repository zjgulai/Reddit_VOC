#!/usr/bin/env python3
"""Independently validate one local Reddit VOC V2 center/metric/candidate chain."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from reddit_voc.report_contracts import canonical_json_bytes  # noqa: E402
from reddit_voc.v2_center import (  # noqa: E402
    BOUNDARIES,
    CANDIDATE_SCHEMA_VERSION,
    METRIC_RELEASE_SCHEMA_VERSION,
    V2CenterError,
    V2CenterStore,
    compute_candidate_value,
    compute_metric_release_value,
)


def _canonical(path: Path, label: str) -> tuple[dict[str, object], bytes]:
    try:
        payload = path.read_bytes()
        value = json.loads(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V2CenterError(f"{label} is invalid") from exc
    if not isinstance(value, dict) or payload != canonical_json_bytes(value) + b"\n":
        raise V2CenterError(f"{label} is not canonical")
    return value, payload


def _write_immutable(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise V2CenterError("validation receipt immutable collision")
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


def validate(
    *, center_database: Path, metric_release: Path, candidate: Path
) -> dict[str, object]:
    center = V2CenterStore(center_database, read_only=True)
    with center.connect() as connection:
        integrity = [row[0] for row in connection.execute("PRAGMA integrity_check").fetchall()]
        if integrity != ["ok"]:
            raise V2CenterError("center sqlite integrity failed")
        batches = [
            row[0]
            for row in connection.execute(
                "SELECT manifest_sha256 FROM source_batches ORDER BY metric_end_utc,manifest_sha256"
            ).fetchall()
        ]
    metric, metric_payload = _canonical(metric_release, "metric release")
    candidate_value, candidate_payload = _canonical(candidate, "candidate")
    if metric.get("schema_version") != METRIC_RELEASE_SCHEMA_VERSION:
        raise V2CenterError("metric release schema mismatch")
    if candidate_value.get("schema_version") != CANDIDATE_SCHEMA_VERSION:
        raise V2CenterError("candidate schema mismatch")
    if metric.get("boundaries") != BOUNDARIES or candidate_value.get("boundaries") != BOUNDARIES:
        raise V2CenterError("V2 boundaries mismatch")
    state_sha = center.state_sha256()
    if metric.get("canonical_state_sha256") != state_sha:
        raise V2CenterError("metric release center binding mismatch")
    if candidate_value.get("canonical_state_sha256") != state_sha:
        raise V2CenterError("candidate center binding mismatch")
    metric_sha = hashlib.sha256(metric_payload).hexdigest()
    if candidate_value.get("metric_release_sha256") != metric_sha:
        raise V2CenterError("candidate metric binding mismatch")
    cutoff = metric.get("cutoff_utc")
    if not isinstance(cutoff, str):
        raise V2CenterError("metric cutoff is invalid")
    try:
        cutoff_utc = datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
    except ValueError as exc:
        raise V2CenterError("metric cutoff is invalid") from exc
    expected_metric = compute_metric_release_value(center, cutoff_utc=cutoff_utc)
    if metric != expected_metric:
        raise V2CenterError("metric release recomputation mismatch")
    expected_candidate = compute_candidate_value(metric, metric_payload)
    if candidate_value != expected_candidate:
        raise V2CenterError("candidate recomputation mismatch")
    if metric.get("source_batch_manifest_sha256s") != batches:
        raise V2CenterError("metric SourceBatch ledger mismatch")
    if candidate_value.get("source_batch_manifest_sha256s") != batches:
        raise V2CenterError("candidate SourceBatch ledger mismatch")
    bindings = metric.get("surface_bindings")
    expected_surfaces = {"cases", "insights", "overview", "personas", "reports"}
    if not isinstance(bindings, dict) or set(bindings) != expected_surfaces:
        raise V2CenterError("metric surface bindings mismatch")
    for surface, binding in bindings.items():
        if not isinstance(binding, dict) or binding.get("metric_release_id") != metric.get("metric_release_id"):
            raise V2CenterError("metric surface releases diverge")
        artifact_path = metric_release.parent / str(binding.get("artifact_path") or "")
        artifact, artifact_payload = _canonical(artifact_path, f"surface artifact:{surface}")
        if artifact.get("surface") != surface:
            raise V2CenterError("surface artifact identity mismatch")
        if hashlib.sha256(artifact_payload).hexdigest() != binding.get("artifact_sha256"):
            raise V2CenterError("surface artifact hash mismatch")
    return {
        "boundaries": dict(BOUNDARIES),
        "candidate_sha256": hashlib.sha256(candidate_payload).hexdigest(),
        "canonical_state_sha256": state_sha,
        "checks": {
            "candidate_metric_binding": True,
            "center_sqlite_integrity": True,
            "source_batch_ledger_binding": True,
            "surface_release_binding": True,
            "metric_recomputation": True,
        },
        "metric_release_sha256": metric_sha,
        "schema_version": "reddit_voc_v2_candidate_validation_receipt_v1",
        "status": "passed",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--center-database", type=Path, required=True)
    parser.add_argument("--metric-release", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt = validate(
            center_database=args.center_database,
            metric_release=args.metric_release,
            candidate=args.candidate,
        )
        payload = canonical_json_bytes(receipt) + b"\n"
        _write_immutable(args.output, payload)
        sys.stdout.write(json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n")
        return 0
    except (OSError, sqlite3.Error, V2CenterError) as exc:
        sys.stderr.write(json.dumps({"error": str(exc), "status": "failed"}, ensure_ascii=False) + "\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
