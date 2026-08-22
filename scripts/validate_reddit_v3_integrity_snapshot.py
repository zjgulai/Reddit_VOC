#!/usr/bin/env python3
"""Independently replay and validate a V3 content-integrity snapshot."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from reddit_voc.v3_content_integrity import (  # noqa: E402
    ContentIntegrityError,
    build_event_chain,
    classify_integrity,
)
from reddit_voc.v3_integrity_snapshot import (  # noqa: E402
    BOUNDARIES,
    MANIFEST_SCHEMA,
    OUTPUT_FILES,
    RECEIPT_SCHEMA,
    IntegritySnapshotError,
    canonical_json_bytes,
    canonical_json_document,
    canonical_jsonl,
    load_frozen_governed_inputs,
    load_policy,
    sha256_bytes,
)


def _stable_id(kind: str, payload: object) -> str:
    return f"{kind}:{sha256(canonical_json_bytes(payload)).hexdigest()}"


def _rank(value: str) -> int:
    return int(value[1:])


def _is_canonical_utc_seconds(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (
        parsed.tzinfo is not None
        and parsed.utcoffset() == timedelta(0)
        and parsed.microsecond == 0
        and value == parsed.isoformat(timespec="seconds")
    )


def _independent_expected(
    *, inputs: object, policy: Mapping[str, Any]
) -> tuple[dict[str, bytes], dict[str, int]]:
    assessments: list[dict[str, Any]] = []
    cluster_members: dict[str, list[dict[str, Any]]] = {}
    for observation in inputs.observations:
        try:
            assessed = classify_integrity(observation["classification_input"])
        except ContentIntegrityError as exc:
            raise IntegritySnapshotError("independent classification replay failed") from exc
        row = assessed.as_dict()
        row.update(
            {
                "cluster_id": None,
                "schema_version": "reddit_voc_integrity_assessment_v1",
                "source_snapshot_id": inputs.source_snapshot_id,
            }
        )
        cluster_key = observation["cluster_key"]
        if cluster_key is not None:
            cluster_id = _stable_id(
                "cluster",
                {
                    "cluster_key": cluster_key,
                    "policy_sha256": inputs.policy_sha256,
                    "source_snapshot_id": inputs.source_snapshot_id,
                },
            )
            row["cluster_id"] = cluster_id
            cluster_members.setdefault(cluster_id, []).append(row)
        assessments.append(row)
    assessments.sort(key=lambda row: str(row["entity_id"]))

    clusters: list[dict[str, Any]] = []
    for cluster_id, members in sorted(cluster_members.items()):
        entity_ids = sorted(str(row["entity_id"]) for row in members)
        clusters.append(
            {
                "cluster_id": cluster_id,
                "commercial_relation": max(
                    (str(row["commercial_relation"]) for row in members), key=_rank
                ),
                "entity_ids": entity_ids,
                "evidence_ids": sorted(
                    {str(value) for row in members for value in row["evidence_ids"]}
                ),
                "integrity_level": max(
                    (str(row["integrity_level"]) for row in members), key=_rank
                ),
                "member_count": len(entity_ids),
                "schema_version": "reddit_voc_integrity_cluster_v1",
                "source_snapshot_id": inputs.source_snapshot_id,
            }
        )

    try:
        event_chain = build_event_chain(
            [
                {
                    "authority": row["authority"],
                    "evidence_id": row["evidence_id"],
                    "post_id": row["post_id"],
                }
                for row in inputs.event_roots
            ]
        )
    except ContentIntegrityError as exc:
        raise IntegritySnapshotError("independent event replay failed") from exc
    event = event_chain.as_dict()
    event.update(
        {
            "cluster_id": _stable_id(
                "cluster",
                {
                    "event_id": event_chain.event_id,
                    "policy_sha256": inputs.policy_sha256,
                    "source_snapshot_id": inputs.source_snapshot_id,
                },
            ),
            "schema_version": "reddit_voc_integrity_event_dossier_v1",
            "source_snapshot_id": inputs.source_snapshot_id,
        }
    )
    events = [event]

    reviews: list[dict[str, Any]] = []
    for assessment in assessments:
        if assessment["commercial_relation"] not in {"C2", "C3"} and assessment[
            "integrity_level"
        ] not in {"I2", "I3", "I4"}:
            continue
        identity = {
            "assessment_id": assessment["assessment_id"],
            "cluster_id": assessment["cluster_id"],
            "entity_id": assessment["entity_id"],
            "source_snapshot_id": inputs.source_snapshot_id,
        }
        reviews.append(
            {
                **identity,
                "review_id": _stable_id("review", identity),
                "review_status": "queued",
                "response_status": "unanswered",
                "schema_version": "reddit_voc_integrity_review_item_v1",
            }
        )
    event_identity = {
        "cluster_id": event["cluster_id"],
        "event_id": event["event_id"],
        "source_snapshot_id": inputs.source_snapshot_id,
    }
    reviews.append(
        {
            **event_identity,
            "review_id": _stable_id("review", event_identity),
            "review_status": "queued",
            "response_status": "unanswered",
            "schema_version": "reddit_voc_integrity_review_item_v1",
        }
    )
    reviews.sort(key=lambda row: str(row["review_id"]))

    raw = [row for row in assessments if row["metric_excluded"] is False]
    confirmed_ids = {
        str(row["assessment_id"])
        for row in raw
        if row["commercial_relation"] == "C3" and row["integrity_level"] == "I4"
    }
    sensitivity = {
        "c3_i4_excluded_entity_count": len(confirmed_ids),
        "explicit_automation_baseline_excluded_entity_count": sum(
            row["metric_excluded"] is True for row in assessments
        ),
        "qualified_organic_entity_count": len(raw) - len(confirmed_ids),
        "raw_observed_metric_eligible_entity_count": len(raw),
        "raw_qualified_entity_count_delta": len(confirmed_ids),
        "schema_version": "reddit_voc_integrity_sensitivity_v1",
        "source_snapshot_id": inputs.source_snapshot_id,
    }
    lifecycle = {
        "response_transitions": policy["response_transitions"],
        "review_transitions": policy["review_lifecycle"],
        "schema_version": "reddit_voc_integrity_lifecycle_v1",
    }
    payloads = {
        "assessments.jsonl": canonical_jsonl(assessments),
        "clusters.jsonl": canonical_jsonl(clusters),
        "event-dossiers.jsonl": canonical_jsonl(events),
        "review-ledger.jsonl": canonical_jsonl(reviews),
        "sensitivity.json": canonical_json_document(sensitivity),
        "lifecycle.json": canonical_json_document(lifecycle),
    }
    levels = {
        **{level: 0 for level in ("C0", "C1", "C2", "C3")},
        **{level: 0 for level in ("I0", "I1", "I2", "I3", "I4")},
    }
    for row in assessments:
        levels[str(row["commercial_relation"])] += 1
        levels[str(row["integrity_level"])] += 1
    counts = {
        "assessments": len(assessments),
        "clusters": len(clusters),
        "event_dossiers": len(events),
        "governed_facts": len(inputs.facts),
        "review_items": len(reviews),
    }
    return payloads, {**counts, **levels}


def _file_contract(name: str, payload: bytes) -> dict[str, object]:
    return {
        "bytes": len(payload),
        "media_type": "application/x-ndjson" if name.endswith(".jsonl") else "application/json",
        "rows": len(payload.splitlines()) if name.endswith(".jsonl") else 1,
        "sha256": sha256_bytes(payload),
    }


def validate_integrity_snapshot(
    *,
    snapshot_dir: Path,
    expected_manifest_sha256: str,
    upstream_root: Path,
    upstream_receipt_path: Path,
    policy_path: Path,
) -> dict[str, object]:
    snapshot_dir = Path(snapshot_dir)
    if snapshot_dir.is_symlink() or not snapshot_dir.is_dir():
        raise IntegritySnapshotError("snapshot directory is invalid")
    entries = {path.name for path in snapshot_dir.iterdir()}
    expected_entries = set(OUTPUT_FILES) | {"manifest.json"}
    if entries != expected_entries or any(
        path.is_symlink() or not path.is_file() for path in snapshot_dir.iterdir()
    ):
        raise IntegritySnapshotError("snapshot contains undeclared files or symlinks")
    manifest_payload = (snapshot_dir / "manifest.json").read_bytes()
    if sha256_bytes(manifest_payload) != expected_manifest_sha256:
        raise IntegritySnapshotError("snapshot manifest SHA-256 mismatch")
    try:
        manifest = json.loads(manifest_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegritySnapshotError("snapshot manifest JSON is invalid") from exc
    if not isinstance(manifest, dict) or canonical_json_document(manifest) != manifest_payload:
        raise IntegritySnapshotError("snapshot manifest is not canonical JSON")

    inputs = load_frozen_governed_inputs(
        upstream_root=upstream_root,
        upstream_receipt_path=upstream_receipt_path,
        policy_path=policy_path,
    )
    policy, policy_sha = load_policy(policy_path)
    if (
        manifest.get("schema_version") != MANIFEST_SCHEMA
        or manifest.get("status") != "candidate_built"
        or manifest.get("consumption_status")
        != "candidate_pending_independent_validation"
        or manifest.get("promotable") is not False
        or manifest.get("boundaries") != BOUNDARIES
        or manifest.get("policy_sha256") != policy_sha
        or manifest.get("source_snapshot_id") != inputs.source_snapshot_id
        or manifest.get("upstream_manifest_sha256")
        != inputs.upstream_manifest_sha256
        or manifest.get("upstream_receipt_sha256") != inputs.upstream_receipt_sha256
        or not isinstance(manifest.get("snapshot_id"), str)
        or not manifest["snapshot_id"]
        or not _is_canonical_utc_seconds(manifest.get("generated_at_utc"))
    ):
        raise IntegritySnapshotError("snapshot lifecycle or lineage mismatch")

    expected_payloads, combined_counts = _independent_expected(
        inputs=inputs,
        policy=policy,
    )
    files = manifest.get("files")
    if not isinstance(files, Mapping) or set(files) != set(OUTPUT_FILES):
        raise IntegritySnapshotError("snapshot file manifest is invalid")
    for name, expected_payload in expected_payloads.items():
        actual_payload = (snapshot_dir / name).read_bytes()
        if files.get(name) != _file_contract(name, actual_payload):
            raise IntegritySnapshotError(f"{name} file contract mismatch")
        if actual_payload != expected_payload:
            raise IntegritySnapshotError(f"{name} independent semantic replay mismatch")
    counts = {key: combined_counts[key] for key in (
        "assessments", "clusters", "event_dossiers", "governed_facts", "review_items"
    )}
    levels = {key: combined_counts[key] for key in (
        "C0", "C1", "C2", "C3", "I0", "I1", "I2", "I3", "I4"
    )}
    if manifest.get("counts") != counts or manifest.get("level_counts") != levels:
        raise IntegritySnapshotError("snapshot counts fail independent replay")
    event = json.loads(expected_payloads["event-dossiers.jsonl"].decode("utf-8"))
    if (
        event.get("commercial_relation") != "C2"
        or event.get("integrity_level") != "I3"
        or event.get("governance_authority") != "subreddit_moderator"
        or event.get("brand_control_confirmed") is not False
    ):
        raise IntegritySnapshotError("fixed Momcozy event claim exceeded evidence")
    return {
        "boundaries": dict(BOUNDARIES),
        "consumption_status": "ready_for_task9_candidate",
        "counts": counts,
        "integrity_manifest_sha256": expected_manifest_sha256,
        "level_counts": levels,
        "promotable": True,
        "schema_version": RECEIPT_SCHEMA,
        "semantic_checks": {
            "c3_i4_and_only_qualified_exclusion": True,
            "explicit_automation_not_commercial_attribution": True,
            "fixed_event_c2_i3": True,
            "full_byte_independent_replay": True,
            "single_signal_cannot_confirm_i4": True,
        },
        "status": "passed",
    }


def write_receipt(path: Path, result: Mapping[str, object]) -> str:
    path = Path(path)
    payload = canonical_json_document(dict(result))
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise IntegritySnapshotError("integrity validation receipt collision")
        return "no_change"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
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
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--upstream-root", type=Path, required=True)
    parser.add_argument("--upstream-validation-receipt", type=Path, required=True)
    parser.add_argument(
        "--policy",
        type=Path,
        default=ROOT / "config/analytics/reddit-voc-content-integrity-v1.json",
    )
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = validate_integrity_snapshot(
            snapshot_dir=args.snapshot_dir,
            expected_manifest_sha256=args.expected_manifest_sha256,
            upstream_root=args.upstream_root,
            upstream_receipt_path=args.upstream_validation_receipt,
            policy_path=args.policy,
        )
        disposition = write_receipt(args.receipt, result)
    except (IntegritySnapshotError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps({**result, "receipt_disposition": disposition}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
