#!/usr/bin/env python3
"""Replay and independently validate frozen V3 integrity inputs."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from reddit_voc.v3_integrity_inputs import (  # noqa: E402
    CANONICAL_ROOT_IDS,
    EXTERNAL_REFERENCE_ID,
    INPUT_FILES,
    IntegrityInputError,
    IntegrityInputSources,
    load_integrity_sources,
    write_validation_receipt,
)
from reddit_voc.v3_content_integrity import FIXED_EVENT_POST_IDS  # noqa: E402
from reddit_voc.v3_integrity_snapshot import (  # noqa: E402
    BOUNDARIES,
    EVENT_ROOT_SCHEMA,
    OBSERVATION_SCHEMA,
    UPSTREAM_MANIFEST_SCHEMA,
    UPSTREAM_RECEIPT_SCHEMA,
    _derived_classification_input,
    _validate_event_root,
    _validate_observation,
    canonical_jsonl,
    canonical_json_document,
    load_policy,
    sha256_bytes,
)


def _read_manifest(path: Path) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file():
        raise IntegrityInputError("integrity input manifest must be a regular file")
    payload = path.read_bytes()
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegrityInputError("integrity input manifest is invalid") from exc
    if not isinstance(value, dict) or canonical_json_document(value) != payload:
        raise IntegrityInputError("integrity input manifest is not canonical JSON")
    return value, payload


def _contract(payload: bytes) -> dict[str, object]:
    return {
        "bytes": len(payload),
        "rows": len(payload.splitlines()),
        "sha256": sha256_bytes(payload),
    }


def _canonical_utc(value: object) -> str:
    if not isinstance(value, str):
        raise IntegrityInputError("integrity input generated time is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IntegrityInputError("integrity input generated time is invalid") from exc
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() != timedelta(0)
        or parsed.microsecond != 0
        or value != parsed.isoformat(timespec="seconds")
    ):
        raise IntegrityInputError("integrity input generated time is invalid")
    return value


def _independent_event_evidence(
    facts: tuple[dict[str, Any], ...], post_id: str
) -> str:
    entity_ids = {f"t3_{post_id}", f"external_reddit_post:{post_id}"}
    candidates: list[dict[str, Any]] = []
    for row in facts:
        if row.get("canonical_entity_id") not in entity_ids:
            continue
        attributes = row.get("attributes")
        if not isinstance(attributes, Mapping):
            raise IntegrityInputError("governed fact attributes are invalid")
        if (
            row.get("fact_type") == "community_governance_fact"
            and attributes.get("authority") == "subreddit_moderator"
        ) or (
            row.get("fact_type") == "integrity_signal_fact"
            and attributes.get("assertion_mode")
            == "subreddit_moderator_allegation"
        ):
            candidates.append(row)
    if not candidates:
        raise IntegrityInputError("fixed event root lacks moderator evidence")
    candidates.sort(
        key=lambda row: (
            0 if row.get("fact_type") == "community_governance_fact" else 1,
            str(row["fact_id"]),
        )
    )
    return str(candidates[0]["fact_id"])


def _independent_expected(
    *, sources: IntegrityInputSources, manifest: Mapping[str, Any], policy_sha: str
) -> tuple[dict[str, bytes], dict[str, Any], tuple[dict[str, Any], ...]]:
    facts = tuple(
        sorted(
            (*sources.canonical_facts, *sources.external_facts),
            key=lambda row: str(row["fact_id"]),
        )
    )
    by_fact_id = {str(row["fact_id"]): row for row in facts}
    by_entity: dict[str, list[dict[str, Any]]] = {}
    for row in facts:
        by_entity.setdefault(str(row["canonical_entity_id"]), []).append(row)
    expected_entities = {
        *(f"t3_{post_id}" for post_id in CANONICAL_ROOT_IDS),
        f"external_reddit_post:{EXTERNAL_REFERENCE_ID}",
    }
    if set(by_entity) != expected_entities:
        raise IntegrityInputError("independent observation entity replay failed")
    observations: list[dict[str, Any]] = []
    for entity_id, rows in sorted(by_entity.items()):
        evidence_ids = sorted(str(row["fact_id"]) for row in rows)
        observation = {
            "classification_input": _derived_classification_input(
                entity_id, evidence_ids, by_fact_id
            ),
            "cluster_key": "momcozy-community-governance-fixed-event",
            "entity_id": entity_id,
            "evidence_ids": evidence_ids,
            "schema_version": OBSERVATION_SCHEMA,
        }
        _validate_observation(observation, by_fact_id)
        observations.append(observation)
    event_roots = tuple(
        {
            "authority": "subreddit_moderator",
            "evidence_id": _independent_event_evidence(facts, post_id),
            "post_id": post_id,
            "schema_version": EVENT_ROOT_SCHEMA,
        }
        for post_id in FIXED_EVENT_POST_IDS
    )
    for row in event_roots:
        _validate_event_root(row, by_fact_id)
    counts = {
        "canonical_facts": len(sources.canonical_facts),
        "canonical_roots": len(CANONICAL_ROOT_IDS),
        "event_roots": len(event_roots),
        "external_facts": len(sources.external_facts),
        "external_references": 1,
        "governed_facts": len(facts),
        "integrity_observations": len(observations),
    }
    manifest_base = {
        "boundaries": dict(BOUNDARIES),
        "consumption_status": "ready",
        "counts": counts,
        "external_reference_boundary": {
            "brand_control_confirmed": False,
            "canonical_task4_row": False,
            "reference_id": EXTERNAL_REFERENCE_ID,
            "source_role": "external_public_reference_noncanonical",
        },
        "generated_at_utc": _canonical_utc(manifest.get("generated_at_utc")),
        "input_id": manifest.get("input_id"),
        "inputs": dict(sorted(sources.input_hashes.items())),
        "lifecycle_status": "review_required",
        "policy_sha256": policy_sha,
        "promotable": True,
        "schema_version": UPSTREAM_MANIFEST_SCHEMA,
        "source_snapshot_id": sources.source_snapshot_id,
        "status": "frozen",
    }
    payloads = {
        "governed-facts.jsonl": canonical_jsonl(facts),
        "integrity-observations.jsonl": canonical_jsonl(observations),
        "event-roots.jsonl": canonical_jsonl(event_roots),
    }
    return payloads, manifest_base, facts


def validate_integrity_inputs(
    *,
    input_root: Path,
    expected_manifest_sha256: str,
    governed_root: Path,
    governed_receipt_path: Path,
    voc_facts_root: Path,
    voc_facts_receipt_path: Path,
    reference_root: Path,
    reference_receipt_path: Path,
    casebook_root: Path,
    casebook_receipt_path: Path,
    policy_path: Path,
) -> dict[str, object]:
    input_root = Path(input_root)
    if input_root.is_symlink() or not input_root.is_dir():
        raise IntegrityInputError("integrity input root is invalid")
    entries = {path.name for path in input_root.iterdir()}
    if entries != set(INPUT_FILES) | {"manifest.json"} or any(
        path.is_symlink() or not path.is_file() for path in input_root.iterdir()
    ):
        raise IntegrityInputError("integrity input contains undeclared entries")
    manifest, manifest_payload = _read_manifest(input_root / "manifest.json")
    manifest_sha = sha256_bytes(manifest_payload)
    if manifest_sha != expected_manifest_sha256:
        raise IntegrityInputError("integrity input manifest SHA-256 mismatch")
    _, policy_sha = load_policy(policy_path)
    if (
        manifest.get("schema_version") != UPSTREAM_MANIFEST_SCHEMA
        or manifest.get("status") != "frozen"
        or manifest.get("consumption_status") != "ready"
        or manifest.get("promotable") is not True
        or manifest.get("boundaries") != BOUNDARIES
        or manifest.get("policy_sha256") != policy_sha
        or manifest.get("lifecycle_status") != "review_required"
        or not isinstance(manifest.get("input_id"), str)
        or not manifest["input_id"]
        or not isinstance(manifest.get("generated_at_utc"), str)
    ):
        raise IntegrityInputError("integrity input lifecycle is invalid")
    sources = load_integrity_sources(
        governed_root=governed_root,
        governed_receipt_path=governed_receipt_path,
        voc_facts_root=voc_facts_root,
        voc_facts_receipt_path=voc_facts_receipt_path,
        reference_root=reference_root,
        reference_receipt_path=reference_receipt_path,
        casebook_root=casebook_root,
        casebook_receipt_path=casebook_receipt_path,
    )
    expected_payloads, expected_manifest_base, facts = _independent_expected(
        sources=sources,
        manifest=manifest,
        policy_sha=policy_sha,
    )
    files = manifest.get("files")
    if not isinstance(files, Mapping) or set(files) != set(INPUT_FILES):
        raise IntegrityInputError("integrity input file manifest is invalid")
    for name, expected_payload in expected_payloads.items():
        actual_payload = (input_root / name).read_bytes()
        if files.get(name) != _contract(actual_payload):
            raise IntegrityInputError(f"{name} file contract mismatch")
        if actual_payload != expected_payload:
            raise IntegrityInputError(f"{name} independent replay mismatch")
    for key, expected in expected_manifest_base.items():
        if manifest.get(key) != expected:
            raise IntegrityInputError(f"integrity input manifest {key} mismatch")
    external = [
        row
        for row in facts
        if row.get("canonical_entity_id") == "external_reddit_post:1u2gvn4"
    ]
    if (
        len(external) != 3
        or any(row.get("voc_id") == "post:1u2gvn4" for row in facts)
        or any(row.get("canonical_entity_id") == "t3_1u2gvn4" for row in facts)
        or any(
            row.get("attributes", {}).get("brand_control_confirmed") is not False
            for row in external
        )
    ):
        raise IntegrityInputError("external reference canonical boundary failed replay")
    counts = expected_manifest_base["counts"]
    return {
        "boundaries": dict(BOUNDARIES),
        "consumption_status": "ready",
        "counts": counts,
        "full_byte_independent_replay": True,
        "promotable": True,
        "review_required": True,
        "schema_version": UPSTREAM_RECEIPT_SCHEMA,
        "semantic_checks": {
            "brand_control_confirmed_false": True,
            "canonical_roots_complete": True,
            "exact_span_sha_replayed": True,
            "external_reference_noncanonical": True,
            "fixed_event_roots_complete": True,
        },
        "status": "passed",
        "upstream_manifest_sha256": manifest_sha,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--governed-root", type=Path, required=True)
    parser.add_argument("--governed-receipt", type=Path, required=True)
    parser.add_argument("--voc-facts-root", type=Path, required=True)
    parser.add_argument("--voc-facts-receipt", type=Path, required=True)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--reference-receipt", type=Path, required=True)
    parser.add_argument("--casebook-root", type=Path, required=True)
    parser.add_argument("--casebook-receipt", type=Path, required=True)
    parser.add_argument(
        "--policy",
        type=Path,
        default=ROOT / "config/analytics/reddit-voc-content-integrity-v1.json",
    )
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = validate_integrity_inputs(
            input_root=args.input_root,
            expected_manifest_sha256=args.expected_manifest_sha256,
            governed_root=args.governed_root,
            governed_receipt_path=args.governed_receipt,
            voc_facts_root=args.voc_facts_root,
            voc_facts_receipt_path=args.voc_facts_receipt,
            reference_root=args.reference_root,
            reference_receipt_path=args.reference_receipt,
            casebook_root=args.casebook_root,
            casebook_receipt_path=args.casebook_receipt,
            policy_path=args.policy,
        )
        disposition = write_validation_receipt(args.receipt, result)
    except (IntegrityInputError, OSError, ValueError) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {**result, "receipt_disposition": disposition},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
