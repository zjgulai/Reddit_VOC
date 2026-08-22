"""Private, hash-bound CaseReference registry for verified Reddit evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from reddit_voc.v3_casebook import build_reference_registry


POLICY_SCHEMA = "reddit_voc_case_reference_policy_v1"
CAPTURE_SCHEMA = "reddit_voc_external_public_post_capture_v1"
SNAPSHOT_SCHEMA = "reddit_voc_case_reference_registry_manifest_v1"
RECEIPT_SCHEMA = "reddit_voc_case_reference_registry_validation_receipt_v1"
POLICY_SHA256 = "fbf673f727801087729d647445d7ee98a471f667e725efc12e3351ee7fa506c8"
BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}
OUTPUT_FILES = ("references.jsonl", "external-public-snapshots.jsonl")
SHA256_RE = re.compile(r"[0-9a-f]{64}")


class CaseReferenceRegistryError(ValueError):
    """A reference policy, capture, or registry artifact is invalid."""


def canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CaseReferenceRegistryError(
            "value is not canonical JSON serializable"
        ) from exc


def canonical_json_document(value: object) -> bytes:
    return canonical_json_bytes(value) + b"\n"


def sha256_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _read_regular(path: Path, label: str) -> bytes:
    path = Path(path)
    try:
        if path.is_symlink() or not path.is_file():
            raise CaseReferenceRegistryError(f"{label} must be a regular file")
        return path.read_bytes()
    except OSError as exc:
        raise CaseReferenceRegistryError(f"{label} is unreadable") from exc


def _load_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    payload = _read_regular(path, label)
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CaseReferenceRegistryError(f"{label} JSON is invalid") from exc
    if not isinstance(value, dict):
        raise CaseReferenceRegistryError(f"{label} must be an object")
    return value, payload


def _canonical_utc(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise CaseReferenceRegistryError(f"{label} must be canonical UTC seconds")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CaseReferenceRegistryError(
            f"{label} must be canonical UTC seconds"
        ) from exc
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() != timedelta(0)
        or parsed.microsecond != 0
        or value != parsed.isoformat(timespec="seconds")
    ):
        raise CaseReferenceRegistryError(
            f"{label} must be canonical UTC seconds"
        )
    return value


def load_case_reference_policy(path: Path) -> tuple[dict[str, Any], str]:
    policy, payload = _load_json(path, "case reference policy")
    if (
        set(policy)
        != {
            "boundaries",
            "default_eligible_source_kinds",
            "max_redirects",
            "policy_version",
            "required_scheme",
            "schema_version",
            "verification_statuses",
            "verification_ttl_days",
        }
        or policy.get("schema_version") != POLICY_SCHEMA
        or policy.get("boundaries") != BOUNDARIES
        or policy.get("required_scheme") != "https"
        or policy.get("max_redirects") != 5
        or policy.get("verification_ttl_days") != 30
        or policy.get("default_eligible_source_kinds")
        != ["approved_delta", "curated_seed"]
        or policy.get("verification_statuses")
        != ["pending", "rejected", "stale", "verified"]
        or not isinstance(policy.get("policy_version"), str)
        or not policy["policy_version"]
        or sha256_bytes(payload) != POLICY_SHA256
    ):
        raise CaseReferenceRegistryError("case reference policy is invalid")
    return policy, POLICY_SHA256


EXTERNAL_POST_BODY = (
    "Just a heads up that Momcozy is at it again in the community, using AI bots "
    "and bogus accounts to shill their products. Thanks to those that have been "
    "reporting them, the accounts have been banned, but to be frank it is an "
    "alarming number. Please continue to report suspicious content."
)


CAPTURE_KEYS = {
    "canonical_task4_row",
    "canonical_url",
    "flair_text",
    "http_status",
    "pii_fields_collected",
    "post_body",
    "provenance",
    "reddit_post_id",
    "redirect_count",
    "requested_url",
    "schema_version",
    "subreddit",
    "theme_match",
    "title",
    "verified_at",
}


def load_external_public_capture(
    path: Path, *, policy: Mapping[str, Any]
) -> tuple[dict[str, Any], str]:
    capture, payload = _load_json(path, "external public capture")
    provenance = capture.get("provenance")
    canonical_url = capture.get("canonical_url")
    requested_url = capture.get("requested_url")
    post_id = capture.get("reddit_post_id")
    if (
        set(capture) != CAPTURE_KEYS
        or capture.get("schema_version") != CAPTURE_SCHEMA
        or post_id != "1u2gvn4"
        or not isinstance(canonical_url, str)
        or not isinstance(requested_url, str)
        or urlsplit(canonical_url).scheme != policy.get("required_scheme")
        or urlsplit(requested_url).scheme != policy.get("required_scheme")
        or f"/comments/{post_id}/" not in urlsplit(canonical_url).path
        or urlsplit(requested_url).path
        not in {f"/comments/{post_id}.json", f"/comments/{post_id}/"}
        or type(capture.get("http_status")) is not int
        or not 200 <= capture["http_status"] < 300
        or type(capture.get("redirect_count")) is not int
        or not 0 <= capture["redirect_count"] <= policy.get("max_redirects")
        or capture.get("theme_match") is not True
        or capture.get("canonical_task4_row") is not False
        or capture.get("pii_fields_collected") is not False
        or capture.get("title") != "Momcozy is at it again"
        or capture.get("subreddit") != "ExclusivelyPumping"
        or capture.get("flair_text") != "MOD RANT/ANNOUNCEMENT ETC"
        or capture.get("post_body") != EXTERNAL_POST_BODY
        or not isinstance(provenance, Mapping)
        or set(provenance)
        != {
            "access_mode",
            "collector",
            "observation_scope",
            "provider_call",
            "remote_write",
        }
        or provenance.get("access_mode") != "web_open_json_read_only"
        or provenance.get("observation_scope") != "public_post_minimal_fields"
        or provenance.get("provider_call") is not False
        or provenance.get("remote_write") is not False
        or not isinstance(provenance.get("collector"), str)
        or not provenance["collector"]
    ):
        raise CaseReferenceRegistryError("external public capture is invalid")
    _canonical_utc(capture.get("verified_at"), "capture verified at")
    return capture, sha256_bytes(payload)


@dataclass(frozen=True)
class CaseReferenceDocuments:
    references: tuple[dict[str, Any], ...]
    snapshots: tuple[dict[str, Any], ...]
    manifest_base: dict[str, Any]


def build_case_reference_documents(
    *,
    captures: Sequence[Mapping[str, Any]],
    capture_sha256s: Sequence[str],
    policy: Mapping[str, Any],
    policy_sha256: str,
    as_of: date,
    registry_id: str,
    generated_at: str,
) -> CaseReferenceDocuments:
    if (
        len(captures) != len(capture_sha256s)
        or not captures
        or any(SHA256_RE.fullmatch(value) is None for value in capture_sha256s)
    ):
        raise CaseReferenceRegistryError("capture bindings are invalid")
    _canonical_utc(generated_at, "registry generated at")
    if not isinstance(registry_id, str) or not registry_id:
        raise CaseReferenceRegistryError("registry ID is invalid")
    snapshots: list[dict[str, Any]] = []
    reference_inputs: list[dict[str, object]] = []
    for capture, capture_sha in zip(captures, capture_sha256s, strict=True):
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
        content_hash = "sha256:" + sha256_bytes(canonical_json_bytes(public_fields))
        snapshot = {
            **public_fields,
            "capture_sha256": capture_sha,
            "content_hash": content_hash,
            "http_status": capture["http_status"],
            "provenance": dict(capture["provenance"]),
            "redirect_count": capture["redirect_count"],
            "requested_url": capture["requested_url"],
            "schema_version": "reddit_voc_external_public_post_snapshot_v1",
            "snapshot_id": "external-post-snapshot:"
            + sha256_bytes(canonical_json_bytes(public_fields)),
            "theme_match": capture["theme_match"],
            "verified_at": capture["verified_at"],
        }
        snapshots.append(snapshot)
        reference_inputs.append(
            {
                "canonical_url": capture["canonical_url"],
                "content_hash": content_hash,
                "http_status": capture["http_status"],
                "last_verified_at": str(capture["verified_at"])[:10],
                "provenance": (
                    "external_public_reference_noncanonical;capture_sha256="
                    + capture_sha
                ),
                "redirect_count": capture["redirect_count"],
                "reference_id": capture["reddit_post_id"],
                "review_reason": "verified_reddit_governance_event_topic",
                "source_kind": "approved_delta",
                "theme_match": capture["theme_match"],
                "verification_status": "verified",
            }
        )
    try:
        registry = build_reference_registry(reference_inputs, as_of=as_of)
    except ValueError as exc:
        raise CaseReferenceRegistryError(str(exc)) from exc
    references = tuple(row.as_dict() for row in registry.references)
    if registry.default_eligible_count != len(references):
        raise CaseReferenceRegistryError(
            "formal external references must be verified and TTL-current"
        )
    snapshots.sort(key=lambda row: str(row["reddit_post_id"]))
    manifest_base = {
        "as_of": as_of.isoformat(),
        "boundaries": dict(BOUNDARIES),
        "consumption_status": "candidate_pending_independent_validation",
        "counts": {
            "default_eligible": registry.default_eligible_count,
            "external_public_snapshots": len(snapshots),
            "references": len(references),
            "stale": 0,
        },
        "generated_at": generated_at,
        "inputs": {
            "capture_sha256s": sorted(capture_sha256s),
            "policy_sha256": policy_sha256,
        },
        "policy_version": policy["policy_version"],
        "promotable": False,
        "registry_content_sha256": registry.content_sha256,
        "registry_id": registry_id,
        "schema_version": SNAPSHOT_SCHEMA,
        "status": "candidate_built",
        "verification_ttl_days": policy["verification_ttl_days"],
    }
    return CaseReferenceDocuments(
        references=references,
        snapshots=tuple(snapshots),
        manifest_base=manifest_base,
    )


def _file_contract(name: str, payload: bytes) -> dict[str, object]:
    return {
        "bytes": len(payload),
        "media_type": "application/x-ndjson",
        "rows": len(payload.splitlines()),
        "sha256": sha256_bytes(payload),
    }


def write_case_reference_registry(
    output_root: Path, documents: CaseReferenceDocuments
) -> dict[str, Any]:
    output_root = Path(output_root)
    if output_root.exists() or output_root.is_symlink():
        raise CaseReferenceRegistryError("registry output root already exists")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging = output_root.parent / f".{output_root.name}.building"
    if staging.exists() or staging.is_symlink():
        raise CaseReferenceRegistryError("registry staging root already exists")
    staging.mkdir()
    try:
        payloads = {
            "references.jsonl": b"".join(
                canonical_json_document(row) for row in documents.references
            ),
            "external-public-snapshots.jsonl": b"".join(
                canonical_json_document(row) for row in documents.snapshots
            ),
        }
        for name, payload in payloads.items():
            (staging / name).write_bytes(payload)
        manifest = {
            **documents.manifest_base,
            "files": {
                name: _file_contract(name, payload)
                for name, payload in sorted(payloads.items())
            },
        }
        (staging / "manifest.json").write_bytes(canonical_json_document(manifest))
        staging.rename(output_root)
        return manifest
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
