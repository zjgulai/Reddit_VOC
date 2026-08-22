"""Validate that a historical public casebook remains resolvable in a newer canonical center."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import re
from typing import Any, Mapping

from reddit_voc.v3_casebook_public import validate_public_projection
from reddit_voc.v3_integrity_snapshot import canonical_json_document, sha256_bytes


RECEIPT_SCHEMA = "reddit_voc_casebook_latest_resolution_receipt_v1"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
BOUNDARIES = {
    "casebook_content_mutated": False,
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}


class CasebookResolutionError(ValueError):
    """A historical casebook cannot be resolved against the pinned canonical center."""


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        if path.is_symlink() or not path.is_file():
            raise CasebookResolutionError(f"{label} must be a regular file")
        payload = path.read_bytes()
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CasebookResolutionError(f"{label} is invalid") from exc
    if not isinstance(value, dict):
        raise CasebookResolutionError(f"{label} must be an object")
    return value, payload


def _require_hash(value: str, label: str) -> None:
    if SHA256_RE.fullmatch(value) is None:
        raise CasebookResolutionError(f"{label} SHA-256 is invalid")


def _validate_file_contract(root: Path, manifest: Mapping[str, Any], name: str) -> Path:
    path = root / name
    if path.is_symlink() or not path.is_file():
        raise CasebookResolutionError(f"canonical file is missing: {name}")
    payload = path.read_bytes()
    contract = manifest.get("files", {}).get(name)
    if (
        not isinstance(contract, Mapping)
        or contract.get("bytes") != len(payload)
        or contract.get("rows") != len(payload.splitlines())
        or contract.get("sha256") != sha256_bytes(payload)
    ):
        raise CasebookResolutionError(f"canonical file contract mismatch: {name}")
    return path


def _read_ids(path: Path, label: str) -> set[str]:
    result: set[str] = set()
    try:
        handle = path.open("r", encoding="utf-8")
    except OSError as exc:
        raise CasebookResolutionError(f"{label} is unreadable") from exc
    with handle:
        for ordinal, line in enumerate(handle, start=1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CasebookResolutionError(f"{label} row {ordinal} is invalid") from exc
            value = row.get("canonical_reddit_id") if isinstance(row, Mapping) else None
            if not isinstance(value, str) or value in result:
                raise CasebookResolutionError(f"{label} contains an invalid or duplicate id")
            result.add(value)
    return result


def _evidence_ids(casebook: Mapping[str, Any]) -> tuple[list[str], list[str], list[str]]:
    dossiers = casebook.get("dossiers")
    if not isinstance(dossiers, list) or not dossiers:
        raise CasebookResolutionError("public casebook has no dossiers")
    posts: list[str] = []
    comments: list[str] = []
    external: list[str] = []
    for dossier in dossiers:
        evidence = dossier.get("evidence") if isinstance(dossier, Mapping) else None
        if not isinstance(evidence, Mapping):
            raise CasebookResolutionError("public casebook evidence is invalid")
        for key, target in (
            ("canonical_post_ids", posts),
            ("evidence_comment_ids", comments),
            ("external_reference_ids", external),
        ):
            values = evidence.get(key)
            if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
                raise CasebookResolutionError(f"public casebook {key} is invalid")
            target.extend(values)
    if len(posts) != len(set(posts)) or len(comments) != len(set(comments)):
        raise CasebookResolutionError("public casebook evidence ids must be unique")
    return sorted(posts), sorted(comments), sorted(external)


def validate_latest_resolution(
    *,
    casebook_public_root: Path,
    expected_casebook_manifest_sha256: str,
    canonical_root: Path,
    expected_canonical_manifest_sha256: str,
    canonical_receipt_path: Path,
    expected_canonical_receipt_sha256: str,
    generated_at_utc: str,
) -> dict[str, Any]:
    """Return a deterministic receipt only when every canonical case evidence id resolves."""
    for value, label in (
        (expected_casebook_manifest_sha256, "casebook manifest"),
        (expected_canonical_manifest_sha256, "canonical manifest"),
        (expected_canonical_receipt_sha256, "canonical receipt"),
    ):
        _require_hash(value, label)
    try:
        generated_at = datetime.fromisoformat(generated_at_utc.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CasebookResolutionError("generated_at_utc is invalid") from exc
    if generated_at.tzinfo is None or generated_at.utcoffset() != timedelta(0):
        raise CasebookResolutionError("generated_at_utc must be UTC")

    validate_public_projection(
        public_root=casebook_public_root,
        expected_manifest_sha256=expected_casebook_manifest_sha256,
    )
    casebook, _ = _read_json(casebook_public_root / "casebook.json", "public casebook")
    canonical_manifest, canonical_manifest_payload = _read_json(
        canonical_root / "manifest.json", "canonical manifest"
    )
    canonical_receipt, canonical_receipt_payload = _read_json(
        canonical_receipt_path, "canonical validation receipt"
    )
    if sha256_bytes(canonical_manifest_payload) != expected_canonical_manifest_sha256:
        raise CasebookResolutionError("canonical manifest SHA-256 mismatch")
    if sha256_bytes(canonical_receipt_payload) != expected_canonical_receipt_sha256:
        raise CasebookResolutionError("canonical receipt SHA-256 mismatch")
    if (
        canonical_manifest.get("schema_version")
        not in {
            "reddit_voc_canonical_snapshot_manifest_v1",
            "reddit_voc_canonical_snapshot_manifest_v2",
        }
        or canonical_manifest.get("status") != "candidate_built"
        or canonical_receipt.get("schema_version")
        not in {
            "reddit_voc_canonical_snapshot_validation_receipt_v1",
            "reddit_voc_canonical_snapshot_validation_receipt_v2",
        }
        or canonical_receipt.get("status") != "passed"
        or canonical_receipt.get("bundle_manifest_sha256")
        != expected_canonical_manifest_sha256
    ):
        raise CasebookResolutionError("canonical source is ineligible")

    post_path = _validate_file_contract(canonical_root, canonical_manifest, "posts.jsonl")
    comment_path = _validate_file_contract(canonical_root, canonical_manifest, "comments.jsonl")
    canonical_posts = _read_ids(post_path, "canonical posts")
    canonical_comments = _read_ids(comment_path, "canonical comments")
    case_posts, case_comments, external = _evidence_ids(casebook)
    unresolved_posts = sorted(set(case_posts) - canonical_posts)
    unresolved_comments = sorted(set(case_comments) - canonical_comments)
    if unresolved_posts or unresolved_comments:
        raise CasebookResolutionError("historical casebook evidence is unresolved in the latest center")

    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "status": "passed",
        "generated_at_utc": generated_at_utc,
        "casebook": {
            "projection_id": casebook["projection_id"],
            "source_snapshot_id": casebook["source_snapshot_id"],
            "manifest_sha256": expected_casebook_manifest_sha256,
            "historical_content_preserved": True,
        },
        "latest_center": {
            "canonical_dataset_id": canonical_manifest["dataset_id"],
            "canonical_manifest_sha256": expected_canonical_manifest_sha256,
            "canonical_validation_receipt_sha256": expected_canonical_receipt_sha256,
        },
        "resolution": {
            "canonical_post_ids": len(case_posts),
            "resolved_canonical_post_ids": len(case_posts),
            "evidence_comment_ids": len(case_comments),
            "resolved_evidence_comment_ids": len(case_comments),
            "external_reference_ids": len(external),
            "external_references_intentionally_not_canonicalized": True,
            "unresolved_canonical_post_ids": [],
            "unresolved_evidence_comment_ids": [],
        },
        "boundaries": dict(BOUNDARIES),
    }
    payload = canonical_json_document(receipt)
    return {"receipt": receipt, "receipt_sha256": sha256_bytes(payload), "payload": payload}
