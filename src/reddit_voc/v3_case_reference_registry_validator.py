"""Independent replay validator for the V3 CaseReference registry."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from typing import Any, Mapping

from reddit_voc.v3_casebook import build_reference_registry
from reddit_voc.v3_case_reference_registry import (
    BOUNDARIES,
    OUTPUT_FILES,
    RECEIPT_SCHEMA,
    SNAPSHOT_SCHEMA,
    CaseReferenceRegistryError,
    canonical_json_bytes,
    canonical_json_document,
    load_case_reference_policy,
    load_external_public_capture,
    sha256_bytes,
)


class CaseReferenceRegistryValidationError(ValueError):
    """The CaseReference registry does not replay from the frozen capture."""


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    path = Path(path)
    try:
        if path.is_symlink() or not path.is_file():
            raise CaseReferenceRegistryValidationError(
                f"{label} must be a regular file"
            )
        payload = path.read_bytes()
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CaseReferenceRegistryValidationError(f"{label} is invalid") from exc
    if not isinstance(value, dict) or payload != canonical_json_document(value):
        raise CaseReferenceRegistryValidationError(f"{label} is not canonical")
    return value, payload


def _read_jsonl(path: Path, label: str) -> tuple[dict[str, Any], ...]:
    try:
        if path.is_symlink() or not path.is_file():
            raise CaseReferenceRegistryValidationError(
                f"{label} must be a regular file"
            )
        payload = path.read_bytes()
    except OSError as exc:
        raise CaseReferenceRegistryValidationError(f"{label} is unreadable") from exc
    rows: list[dict[str, Any]] = []
    for ordinal, line in enumerate(payload.splitlines(), start=1):
        try:
            row = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CaseReferenceRegistryValidationError(
                f"{label} row {ordinal} is invalid"
            ) from exc
        if not isinstance(row, dict) or line != canonical_json_bytes(row):
            raise CaseReferenceRegistryValidationError(
                f"{label} row {ordinal} is not canonical"
            )
        rows.append(row)
    if payload and not payload.endswith(b"\n"):
        raise CaseReferenceRegistryValidationError(f"{label} lacks final newline")
    return tuple(rows)


def _contract(name: str, payload: bytes) -> dict[str, object]:
    return {
        "bytes": len(payload),
        "media_type": "application/x-ndjson",
        "rows": len(payload.splitlines()),
        "sha256": sha256_bytes(payload),
    }


def validate_case_reference_registry(
    *,
    registry_root: Path,
    expected_manifest_sha256: str,
    policy_path: Path,
    capture_path: Path,
) -> dict[str, object]:
    root = Path(registry_root)
    if root.is_symlink() or not root.is_dir():
        raise CaseReferenceRegistryValidationError("registry root is invalid")
    entries = {path.name for path in root.iterdir()}
    if entries != {"manifest.json", *OUTPUT_FILES} or any(
        path.is_symlink() or not path.is_file() for path in root.iterdir()
    ):
        raise CaseReferenceRegistryValidationError(
            "registry contains missing or undeclared entries"
        )
    manifest, manifest_payload = _read_json(root / "manifest.json", "manifest")
    if sha256_bytes(manifest_payload) != expected_manifest_sha256:
        raise CaseReferenceRegistryValidationError("manifest SHA-256 mismatch")
    try:
        policy, policy_sha = load_case_reference_policy(policy_path)
        capture, capture_sha = load_external_public_capture(
            capture_path, policy=policy
        )
    except CaseReferenceRegistryError as exc:
        raise CaseReferenceRegistryValidationError(str(exc)) from exc
    files = manifest.get("files")
    if (
        manifest.get("schema_version") != SNAPSHOT_SCHEMA
        or manifest.get("status") != "candidate_built"
        or manifest.get("consumption_status")
        != "candidate_pending_independent_validation"
        or manifest.get("promotable") is not False
        or manifest.get("boundaries") != BOUNDARIES
        or manifest.get("policy_version") != policy["policy_version"]
        or manifest.get("verification_ttl_days") != 30
        or manifest.get("inputs")
        != {"capture_sha256s": [capture_sha], "policy_sha256": policy_sha}
        or not isinstance(files, Mapping)
        or set(files) != set(OUTPUT_FILES)
    ):
        raise CaseReferenceRegistryValidationError(
            "registry lifecycle or lineage mismatch"
        )
    try:
        as_of = date.fromisoformat(str(manifest.get("as_of")))
    except ValueError as exc:
        raise CaseReferenceRegistryValidationError("registry as-of is invalid") from exc
    public_fields = {
        "canonical_task4_row": False,
        "canonical_url": capture["canonical_url"],
        "flair_text": capture["flair_text"],
        "pii_fields_collected": False,
        "post_body": capture["post_body"],
        "reddit_post_id": capture["reddit_post_id"],
        "source_role": "external_public_reference_noncanonical",
        "subreddit": capture["subreddit"],
        "title": capture["title"],
    }
    content_digest = sha256_bytes(canonical_json_bytes(public_fields))
    expected_snapshot = {
        **public_fields,
        "capture_sha256": capture_sha,
        "content_hash": f"sha256:{content_digest}",
        "http_status": capture["http_status"],
        "provenance": dict(capture["provenance"]),
        "redirect_count": capture["redirect_count"],
        "requested_url": capture["requested_url"],
        "schema_version": "reddit_voc_external_public_post_snapshot_v1",
        "snapshot_id": f"external-post-snapshot:{content_digest}",
        "theme_match": True,
        "verified_at": capture["verified_at"],
    }
    expected_reference_registry = build_reference_registry(
        [
            {
                "canonical_url": capture["canonical_url"],
                "content_hash": f"sha256:{content_digest}",
                "http_status": capture["http_status"],
                "last_verified_at": str(capture["verified_at"])[:10],
                "provenance": (
                    "external_public_reference_noncanonical;capture_sha256="
                    + capture_sha
                ),
                "redirect_count": capture["redirect_count"],
                "reference_id": "1u2gvn4",
                "review_reason": "verified_reddit_governance_event_topic",
                "source_kind": "approved_delta",
                "theme_match": True,
                "verification_status": "verified",
            }
        ],
        as_of=as_of,
    )
    expected_references = tuple(
        row.as_dict() for row in expected_reference_registry.references
    )
    observed_references = _read_jsonl(root / "references.jsonl", "references")
    observed_snapshots = _read_jsonl(
        root / "external-public-snapshots.jsonl", "external snapshots"
    )
    if observed_references != expected_references or observed_snapshots != (
        expected_snapshot,
    ):
        raise CaseReferenceRegistryValidationError(
            "registry full-byte semantic replay mismatch"
        )
    for name in OUTPUT_FILES:
        payload = (root / name).read_bytes()
        if files.get(name) != _contract(name, payload):
            raise CaseReferenceRegistryValidationError(f"{name} contract mismatch")
    expected_counts = {
        "default_eligible": 1,
        "external_public_snapshots": 1,
        "references": 1,
        "stale": 0,
    }
    if (
        manifest.get("counts") != expected_counts
        or manifest.get("registry_content_sha256")
        != expected_reference_registry.content_sha256
    ):
        raise CaseReferenceRegistryValidationError("registry counts mismatch")
    return {
        "boundaries": dict(BOUNDARIES),
        "consumption_status": "eligible_for_casebook",
        "counts": expected_counts,
        "full_byte_independent_replay": True,
        "policy_sha256": policy_sha,
        "promotable": True,
        "registry_manifest_sha256": expected_manifest_sha256,
        "schema_version": RECEIPT_SCHEMA,
        "status": "passed",
        "tri_key_dedupe_unaccounted": 0,
        "ttl_unaccounted": 0,
    }
